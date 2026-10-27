#!/usr/bin/env python3
"""Run the frozen eval500 calibration/test sets through POST /api/search.

This tool records a rank-derived retrieval score proxy, not calibrated answer
confidence. It sends query/category/limit/purpose/retrieval_mode only; score
selection, case labels, and qrels never enter the request body. The JSONL
journal is owner-only and resumable.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import eval500_metrics as metrics


DEFAULT_BASE_URL = "http://127.0.0.1:8080"
EXPECTED_POLICY_VERSION = metrics.POLICY_VERSION
HTTP_TIMEOUT_SECONDS = 60
JEV_HTTP_TIMEOUT_SECONDS = 180
MAX_RETRIES = 2
MAX_HTTP_ATTEMPTS = MAX_RETRIES + 1
MAX_JEV_HTTP_ATTEMPTS = 1
MAX_RETRY_SLEEP_SECONDS = 30.0
MAX_WORKERS = 2
MAX_RESPONSE_BYTES = 2_500_000
MAX_JOURNAL_BYTES = 20_000_000
BOOTSTRAP_REPLICATES = 1000
JOURNAL_SCHEMA_VERSION = "retrieval-eval500-journal/v1"
THRESHOLD_SCHEMA_VERSION = "retrieval-eval500-threshold/v1"
RUNNER_VERSION = "eval500-runner/v1"
RUNTIME_VERSION_STATUS = "not_provided_by_search_response"
REQUEST_BODY = {"category": "", "limit": 12, "purpose": "auto"}
TRANSIENT_HTTP_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


class EvaluationRunError(RuntimeError):
    """Safe, machine-readable batch/evaluation error with no response body."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class SearchRequestError(RuntimeError):
    """Safe HTTP/transport failure; intentionally omits URL, headers and body."""

    def __init__(self, code: str, *, http_status: int | None = None, attempts: int = 1):
        self.code = code
        self.http_status = http_status
        self.attempts = attempts
        super().__init__(code)


@dataclass(frozen=True)
class SearchResponse:
    payload: dict
    http_status: int
    attempts: int
    response_bytes: int


def _validated_base_url(base_url: str) -> str:
    if not isinstance(base_url, str):
        raise EvaluationRunError("invalid_base_url")
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise EvaluationRunError("invalid_base_url")
    return base_url.rstrip("/")


def _validated_retrieval_mode(value: str) -> str:
    if value not in metrics.RETRIEVAL_MODES:
        raise EvaluationRunError("invalid_retrieval_mode")
    return value


def _validated_score_name(value: str) -> str:
    if value not in metrics.SCORE_NAMES:
        raise EvaluationRunError("invalid_score_name")
    return value


def _validated_evidence_advice(value: str) -> str:
    if not isinstance(value, str) or value not in {"off", "jev"}:
        raise EvaluationRunError("invalid_evidence_advice")
    return value


def _request_body(retrieval_mode: str, evidence_advice: str = "off", *, legacy_without_advice: bool = False) -> dict:
    body = {**REQUEST_BODY, "retrieval_mode": _validated_retrieval_mode(retrieval_mode)}
    if not legacy_without_advice:
        body["evidence_advice"] = _validated_evidence_advice(evidence_advice)
    return body


def _score_definition(score_name: str) -> str:
    score_name = _validated_score_name(score_name)
    if score_name == metrics.SCORE_NAME:
        return "maximum finite item.trace.rank_score; empty items score 0; malformed scores are errors"
    if score_name == metrics.JEV_SCORE_NAME:
        return (
            "assessed evidence_advice.support_score only; unavailable/disabled/skipped advice has null score; "
            "uncalibrated direct-support proxy, not answerability probability or action"
        )
    return (
        "maximum item.trace.reranker_relevance_score in [0,1] among scored items; empty items score 0; "
        "items with neither candidate rank nor reranker score are skipped as unscored backfill; "
        "score and rank must be paired; invalid candidate ranks, malformed scores, and no scored candidates "
        "are errors; relevance is not answerability"
    )


class HTTPTransport:
    """Bounded urllib client with two transient retries and a 2.5 MB response cap."""

    def __init__(self, base_url: str, *, urlopen=None, sleep_fn=None):
        self.base_url = _validated_base_url(base_url)
        self._urlopen = urlopen
        self._sleep = sleep_fn or time.sleep

    def _open(self, request, *, timeout_seconds=HTTP_TIMEOUT_SECONDS):
        if self._urlopen is not None:
            return self._urlopen(request, timeout=timeout_seconds)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(request, timeout=timeout_seconds)

    @staticmethod
    def _header(headers, name: str):
        if headers is None:
            return None
        getter = getattr(headers, "get", None)
        return getter(name) if getter else None

    def _retry_delay(self, attempt: int, headers=None) -> float:
        retry_after = self._header(headers, "Retry-After")
        if retry_after is not None:
            try:
                value = float(retry_after)
                if math.isfinite(value) and value >= 0:
                    return min(MAX_RETRY_SLEEP_SECONDS, value)
            except (TypeError, ValueError):
                pass
        return min(MAX_RETRY_SLEEP_SECONDS, float(2 ** (attempt - 1)))

    def post_search(self, payload: dict) -> SearchResponse:
        legacy_fields = {"query", "category", "limit", "purpose"}
        mode_fields = legacy_fields | {"retrieval_mode"}
        advice_fields = mode_fields | {"evidence_advice"}
        if not isinstance(payload, dict) or set(payload) not in (legacy_fields, mode_fields, advice_fields):
            raise SearchRequestError("invalid_request_shape")
        if not isinstance(payload.get("query"), str) or not payload["query"].strip() or len(payload["query"]) > 2000:
            raise SearchRequestError("invalid_request_query")
        if payload.get("category") != "" or payload.get("limit") != 12 or payload.get("purpose") != "auto":
            raise SearchRequestError("request_policy_mismatch")
        if "retrieval_mode" in payload and payload.get("retrieval_mode") not in metrics.RETRIEVAL_MODES:
            raise SearchRequestError("invalid_request_retrieval_mode")
        if ("evidence_advice" in payload
                and (not isinstance(payload.get("evidence_advice"), str)
                     or payload.get("evidence_advice") not in {"off", "jev"})):
            raise SearchRequestError("invalid_request_evidence_advice")
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/api/search", data=encoded,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        advice_enabled = payload.get("evidence_advice", "off") == "jev"
        max_attempts = MAX_JEV_HTTP_ATTEMPTS if advice_enabled else MAX_HTTP_ATTEMPTS
        timeout_seconds = JEV_HTTP_TIMEOUT_SECONDS if advice_enabled else HTTP_TIMEOUT_SECONDS
        for attempt in range(1, max_attempts + 1):
            try:
                response = self._open(request, timeout_seconds=timeout_seconds)
                with response:
                    status = getattr(response, "status", None)
                    if not isinstance(status, int):
                        status = response.getcode()
                    headers = getattr(response, "headers", None)
                    if status != 200:
                        if status in TRANSIENT_HTTP_STATUSES and attempt < max_attempts:
                            self._sleep(self._retry_delay(attempt, headers))
                            continue
                        raise SearchRequestError(f"http_{status}", http_status=status, attempts=attempt)
                    length_header = self._header(headers, "Content-Length")
                    if length_header is not None:
                        try:
                            content_length = int(length_header)
                        except (TypeError, ValueError):
                            raise SearchRequestError("invalid_content_length", http_status=status, attempts=attempt) from None
                        if content_length < 0 or content_length > MAX_RESPONSE_BYTES:
                            raise SearchRequestError("response_too_large", http_status=status, attempts=attempt)
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                if not isinstance(raw, bytes):
                    raise SearchRequestError("invalid_response_bytes", http_status=status, attempts=attempt)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise SearchRequestError("response_too_large", http_status=status, attempts=attempt)
                try:
                    body = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise SearchRequestError("invalid_json_response", http_status=status, attempts=attempt) from None
                if not isinstance(body, dict):
                    raise SearchRequestError("invalid_json_response_shape", http_status=status, attempts=attempt)
                return SearchResponse(body, status, attempt, len(raw))
            except urllib.error.HTTPError as error:
                status = getattr(error, "code", None)
                headers = getattr(error, "headers", None)
                if status in TRANSIENT_HTTP_STATUSES and attempt < max_attempts:
                    self._sleep(self._retry_delay(attempt, headers))
                    continue
                raise SearchRequestError(
                    f"http_{status}" if isinstance(status, int) else "http_error",
                    http_status=status if isinstance(status, int) else None,
                    attempts=attempt,
                ) from None
            except SearchRequestError:
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
                if attempt < max_attempts:
                    self._sleep(self._retry_delay(attempt))
                    continue
                raise SearchRequestError("transport_error", attempts=attempt) from None
        raise SearchRequestError("transport_error", attempts=max_attempts)


def _read_case_file(path: Path, stage: str) -> tuple[list[dict], str, dict]:
    try:
        raw = path.read_bytes()
    except OSError:
        raise EvaluationRunError("case_file_unavailable") from None
    digest = hashlib.sha256(raw).hexdigest()
    cases = []
    try:
        for line in raw.splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError("case row not object")
            cases.append(item)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise EvaluationRunError("case_file_invalid_jsonl") from None
    summary = metrics.validate_cases(cases, stage)
    return cases, digest, summary


def _case_contract_sha256() -> str:
    repo_root = Path(__file__).resolve().parents[1]
    contract_paths = (
        repo_root / "research" / "eval500" / "case-contract-v1.json",
        repo_root / ".superpowers" / "sdd" / "eval500" / "case-contract.json",
    )
    for contract_path in contract_paths:
        try:
            return hashlib.sha256(contract_path.read_bytes()).hexdigest()
        except FileNotFoundError:
            continue
        except OSError:
            raise EvaluationRunError("case_contract_unavailable") from None
    raise EvaluationRunError("case_contract_unavailable")


def _validate_sha256(value: str, code: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[a-fA-F0-9]{64}", value) is None:
        raise EvaluationRunError(code)
    return value.lower()


def _ensure_parent(path: Path) -> None:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if parent.is_symlink() or not parent.is_dir():
        raise EvaluationRunError("unsafe_output_directory")


def _safe_stat(path: Path):
    try:
        info = path.lstat()
    except OSError:
        raise EvaluationRunError("journal_unavailable") from None
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise EvaluationRunError("unsafe_journal_file")
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise EvaluationRunError("journal_permissions_invalid")
    return info


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short write")
        view = view[written:]


class JsonlJournal:
    """Owner-only append journal. It contains sanitized metadata, never raw API bodies."""

    def __init__(self, path: Path, identity: dict, *, resume: bool):
        self.path = Path(path)
        _ensure_parent(self.path)
        self.records: list[dict] = []
        self._write_lock = threading.RLock()
        self.header = {"event": "manifest", "schema_version": JOURNAL_SCHEMA_VERSION, **identity}
        self.run_id = uuid.uuid4().hex
        flags = (os.O_RDWR if resume else os.O_WRONLY) | os.O_APPEND | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        if not resume:
            flags |= os.O_CREAT | os.O_EXCL
            try:
                self.fd = os.open(self.path, flags, 0o600)
            except FileExistsError:
                raise EvaluationRunError("fresh_journal_exists") from None
            os.fchmod(self.fd, 0o600)
            self.header["run_id"] = self.run_id
            try:
                self._append_bytes(self.header)
            except BaseException:
                os.close(self.fd)
                self.fd = None
                raise
            return
        _safe_stat(self.path)
        try:
            self.fd = os.open(self.path, flags)
        except OSError:
            raise EvaluationRunError("journal_unavailable") from None
        self._load_and_validate(identity)

    def _append_bytes(self, record: dict) -> None:
        try:
            encoded = (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
        except (OSError, TypeError, ValueError):
            raise EvaluationRunError("journal_write_failed") from None
        with self._write_lock:
            try:
                current_size = os.fstat(self.fd).st_size
            except OSError:
                raise EvaluationRunError("journal_write_failed") from None
            if current_size + len(encoded) > MAX_JOURNAL_BYTES:
                raise EvaluationRunError("journal_size_limit")
            try:
                _write_all(self.fd, encoded)
                os.fsync(self.fd)
            except OSError:
                raise EvaluationRunError("journal_write_failed") from None

    def _load_and_validate(self, identity: dict) -> None:
        try:
            os.lseek(self.fd, 0, os.SEEK_SET)
            chunks = []
            total = 0
            while True:
                chunk = os.read(self.fd, min(1024 * 1024, MAX_JOURNAL_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_JOURNAL_BYTES:
                    raise EvaluationRunError("journal_size_limit")
            raw = b"".join(chunks)
        except OSError:
            raise EvaluationRunError("journal_unavailable") from None
        if not raw:
            raise EvaluationRunError("journal_invalid")
        if not raw.endswith(b"\n"):
            last_newline = raw.rfind(b"\n")
            if last_newline < 0:
                raise EvaluationRunError("journal_invalid")
            raw = raw[:last_newline + 1]
            try:
                os.ftruncate(self.fd, len(raw))
                os.fsync(self.fd)
            except OSError:
                raise EvaluationRunError("journal_recovery_failed") from None
        try:
            lines = [json.loads(line) for line in raw.splitlines()]
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise EvaluationRunError("journal_invalid") from None
        if not lines or not isinstance(lines[0], dict):
            raise EvaluationRunError("journal_invalid")
        saved_header = lines[0]
        for key, value in identity.items():
            if saved_header.get(key) != value:
                raise EvaluationRunError("journal_identity_mismatch")
        if saved_header.get("event") != "manifest" or saved_header.get("schema_version") != JOURNAL_SCHEMA_VERSION:
            raise EvaluationRunError("journal_schema_mismatch")
        self.header = saved_header
        self.run_id = saved_header.get("run_id", "")
        seen = set()
        for record in lines[1:]:
            if not isinstance(record, dict) or record.get("event") not in {"case_result", "threshold_frozen"}:
                raise EvaluationRunError("journal_record_invalid")
            case_id = record.get("case_id")
            if record.get("event") == "case_result":
                if not isinstance(case_id, str) or case_id in seen:
                    raise EvaluationRunError("journal_duplicate_or_invalid_case")
                seen.add(case_id)
            self.records.append(record)
        os.lseek(self.fd, 0, os.SEEK_END)

    def append(self, record: dict) -> None:
        with self._write_lock:
            if record.get("event") == "case_result" and any(
                prior.get("event") == "case_result" and prior.get("case_id") == record.get("case_id")
                for prior in self.records
            ):
                raise EvaluationRunError("journal_duplicate_case")
            self._append_bytes(record)
            self.records.append(record)

    def close(self) -> None:
        if getattr(self, "fd", None) is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _load_private_json(path: Path) -> tuple[dict, str]:
    _safe_stat(path)
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise EvaluationRunError("threshold_file_invalid") from None
    if not isinstance(value, dict):
        raise EvaluationRunError("threshold_file_invalid")
    return value, hashlib.sha256(raw).hexdigest()


def _write_private_json_no_overwrite(path: Path, value: dict) -> str:
    _ensure_parent(path)
    if path.exists() or path.is_symlink():
        existing, digest = _load_private_json(path)
        if existing == value:
            return digest
        raise EvaluationRunError("threshold_file_exists_mismatch")
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    fd = None
    temp_name = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=".eval500-", dir=path.parent)
        os.fchmod(fd, 0o600)
        _write_all(fd, data)
        os.fsync(fd)
        os.close(fd)
        fd = None
        os.link(temp_name, path, follow_symlinks=False)
        dir_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        return hashlib.sha256(data).hexdigest()
    except FileExistsError:
        existing, digest = _load_private_json(path)
        if existing == value:
            return digest
        raise EvaluationRunError("threshold_file_exists_mismatch") from None
    except (OSError, TypeError, ValueError):
        raise EvaluationRunError("threshold_write_failed") from None
    finally:
        if fd is not None:
            os.close(fd)
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass


def _threshold_policy(path: Path, corpus_manifest_sha256: str, case_contract_sha256: str, *,
                      retrieval_mode: str = "baseline", score_name: str = metrics.SCORE_NAME,
                      evidence_advice: str = "off") -> tuple[dict, str]:
    retrieval_mode = _validated_retrieval_mode(retrieval_mode)
    score_name = _validated_score_name(score_name)
    evidence_advice = _validated_evidence_advice(evidence_advice)
    value, digest = _load_private_json(path)
    if (value.get("schema_version") != THRESHOLD_SCHEMA_VERSION
            or value.get("runner_version") != RUNNER_VERSION
            or value.get("runtime_version_status") != RUNTIME_VERSION_STATUS
            or value.get("stage") != "calibration_frozen_threshold"):
        raise EvaluationRunError("threshold_identity_mismatch")
    if (value.get("policy_version") != EXPECTED_POLICY_VERSION
            or value.get("corpus_manifest_sha256") != corpus_manifest_sha256
            or value.get("case_contract_sha256") != case_contract_sha256
            or value.get("retrieval_mode") != retrieval_mode
            or value.get("evidence_advice", "off") != evidence_advice):
        raise EvaluationRunError("threshold_identity_mismatch")
    if value.get("score_name") != score_name or value.get("comparison") != ">=":
        raise EvaluationRunError("threshold_identity_mismatch")
    threshold = value.get("threshold")
    if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
            or not math.isfinite(threshold)
            or (score_name == metrics.SCORE_NAME and threshold < 0)
            or (score_name in {metrics.RERANKER_SCORE_NAME, metrics.JEV_SCORE_NAME} and not 0 <= threshold <= 1)):
        raise EvaluationRunError("threshold_identity_mismatch")
    request = value.get("request")
    if request != _request_body(retrieval_mode, evidence_advice):
        legacy_off = evidence_advice == "off" and "evidence_advice" not in value
        if not legacy_off or request != _request_body(retrieval_mode, evidence_advice, legacy_without_advice=True):
            raise EvaluationRunError("threshold_identity_mismatch")
    if value.get("target_supported_tpr") != 0.90 or value.get("probability") is not False:
        raise EvaluationRunError("threshold_identity_mismatch")
    calibration_hash = value.get("calibration_case_manifest_sha256")
    if not isinstance(calibration_hash, str) or re.fullmatch(r"[a-fA-F0-9]{64}", calibration_hash) is None:
        raise EvaluationRunError("threshold_identity_mismatch")
    for key in ("calibration_case_id_sha256", "calibration_intent_group_sha256", "calibration_source_material_sha256"):
        hashes = value.get(key)
        if (not isinstance(hashes, list) or any(not isinstance(h, str) or re.fullmatch(r"[a-fA-F0-9]{64}", h) is None for h in hashes)
                or len(hashes) != len(set(hashes))):
            raise EvaluationRunError("threshold_identity_mismatch")
    return value, digest


def _case_result_record(case: dict, *, index: int, response_body: dict | None, error: SearchRequestError | None,
                        latency: float, retrieval_mode: str = "baseline",
                        score_name: str = metrics.SCORE_NAME,
                        evidence_advice: str = "off") -> dict:
    retrieval_mode = _validated_retrieval_mode(retrieval_mode)
    score_name = _validated_score_name(score_name)
    evidence_advice = _validated_evidence_advice(evidence_advice)
    metadata = {
        "event": "case_result", "case_index": index, "case_id": case["id"],
        "split": case["split"], "query": case["query"], "language": case["language"],
        "retrieval_mode": retrieval_mode, "score_name": score_name,
        "evidence_advice": evidence_advice,
        "category": case["category"], "difficulty": case["difficulty"],
        "intent_group": case["intent_group"], "answerability": case["answerability"],
        "expected_action": case["expected_action"], "boundary_type": case["boundary_type"],
        "actual_confidence": "not_provided", "actual_action": "not_evaluated",
        "actual_abstention": "not_evaluated", "threshold_is_proxy_only": True,
        "latency_seconds": float(latency), "http_status": error.http_status if error else 200,
        "http_attempts": error.attempts if error else 1,
    }
    if error is not None:
        metadata.update({"status": "error", "error_type": error.code, "score": None, "result": None})
        if case["answerability"] == metrics.SUPPORTED:
            metadata["ranking"] = {
                stream: metrics.ranking_metrics(case, {}, stream=stream, limit=12)
                for stream in ("source_results", "items")
            }
        return metadata
    try:
        if response_body.get("retrieval_mode") != retrieval_mode:
            raise metrics.EvalScoreError("retrieval_mode_mismatch")
        score = metrics.primary_score(response_body, score_name=score_name)
        projection = metrics.project_search_result(response_body, limit=12)
        advice = projection.get("evidence_advice")
        if evidence_advice == "jev" and not isinstance(advice, dict):
            raise metrics.EvalScoreError("missing evidence_advice envelope")
    except metrics.EvalScoreError:
        metadata.update({"status": "error", "error_type": "response_schema_error", "score": None, "result": None, "http_status": 200})
        if case["answerability"] == metrics.SUPPORTED:
            metadata["ranking"] = {
                stream: metrics.ranking_metrics(case, {}, stream=stream, limit=12)
                for stream in ("source_results", "items")
            }
        return metadata
    if evidence_advice == "jev" and advice["status"] != "assessed":
        error_types = {
            "disabled": "advisor_disabled",
            "unavailable": "advisor_unavailable",
            "skipped_over_budget": "advisor_skipped_over_budget",
            "skipped_prompt_budget": "advisor_skipped_prompt_budget",
        }
        metadata.update({
            "status": "error",
            "error_type": error_types[advice["status"]],
            "score": None if score_name == metrics.JEV_SCORE_NAME else score,
            "result": projection,
        })
        if case["answerability"] == metrics.SUPPORTED:
            metadata["ranking"] = {
                stream: metrics.ranking_metrics(case, projection, stream=stream, limit=12)
                for stream in ("source_results", "items")
            }
        return metadata
    metadata.update({"status": "ok", "error_type": None, "score": score, "result": projection})
    if case["answerability"] == metrics.SUPPORTED:
        metadata["ranking"] = {
            stream: metrics.ranking_metrics(case, projection, stream=stream, limit=12)
            for stream in ("source_results", "items")
        }
    return metadata


def _response_parts(value) -> tuple[dict, int, int, int]:
    if isinstance(value, SearchResponse):
        return value.payload, value.http_status, value.attempts, value.response_bytes
    if isinstance(value, dict):
        return value, 200, 1, 0
    raise SearchRequestError("invalid_transport_result")


def _summary_from_records(stage: str, cases: list[dict], records: list[dict], threshold: dict | None, *,
                          bootstrap_replicates: int, retrieval_mode: str = "baseline",
                          score_name: str = metrics.SCORE_NAME,
                          evidence_advice: str = "off") -> dict:
    evidence_advice = _validated_evidence_advice(evidence_advice)
    by_id = {record["case_id"]: record for record in records if record.get("event") == "case_result"}
    ordered = [by_id[case["id"]] for case in cases if case["id"] in by_id]
    errors = [record for record in ordered if record.get("status") != "ok"]
    advice_status_counts = Counter()
    assessed_case_ids = set()
    if evidence_advice == "jev":
        for record in ordered:
            advice = (record.get("result") or {}).get("evidence_advice")
            status = advice.get("status") if isinstance(advice, dict) else "missing"
            advice_status_counts[status] += 1
            if status == "assessed":
                assessed_case_ids.add(record["case_id"])
        missing_records = len(cases) - len(ordered)
        if missing_records:
            advice_status_counts["no_record"] += missing_records
    valid_assessed_semantic_denominator = None
    if evidence_advice == "jev" and score_name == metrics.JEV_SCORE_NAME:
        valid_assessed_semantic_denominator = sum(
            record["case_id"] in assessed_case_ids
            and record.get("score") is not None
            and record.get("answerability") in {metrics.SUPPORTED, metrics.INSUFFICIENT}
            for record in ordered
        )
    score_records = [{
        "case_id": record["case_id"], "intent_group": record["intent_group"],
        "answerability": record["answerability"], "boundary_type": record["boundary_type"],
        "score": record.get("score"),
    } for record in ordered]
    execution_passed = len(ordered) == len(cases) and not errors
    result_by_id = {record["case_id"]: record.get("result") or {} for record in ordered}
    report = {
        "stage": stage,
        "status": "complete" if execution_passed else "failed",
        "execution_gate_passed": execution_passed,
        "case_count": len(cases), "recorded_case_count": len(ordered),
        "success_count": len(ordered) - len(errors), "error_count": len(errors),
        "errors_by_type": dict(Counter(record.get("error_type") for record in errors)),
        "answerability_counts": dict(Counter(case["answerability"] for case in cases)),
        "policy_version": EXPECTED_POLICY_VERSION,
        "runner_version": RUNNER_VERSION,
        "runtime_version_status": RUNTIME_VERSION_STATUS,
        "retrieval_mode": _validated_retrieval_mode(retrieval_mode),
        "score_name": _validated_score_name(score_name),
        "evidence_advice": {
            "mode": evidence_advice,
            "status_counts": dict(advice_status_counts),
            "assessed_count": len(assessed_case_ids),
            "unassessed_count": len(cases) - len(assessed_case_ids) if evidence_advice == "jev" else 0,
            "valid_assessed_semantic_denominator": valid_assessed_semantic_denominator,
        },
        "probability": False,
        "actual_confidence": "not_provided",
        "actual_action": "not_evaluated",
        "actual_abstention": "not_evaluated",
        "threshold_is_proxy_only": True,
        "threshold_proxy_enforcement": "not_evaluated",
        "group_counts": {
            "intent_groups": len(metrics.intent_group_hashes(cases)),
            "source_materials": len(metrics.source_material_hashes(cases)),
        },
        "rankings": {
            stream: metrics.aggregate_ranking(cases, result_by_id, stream=stream, limit=12)
            for stream in ("source_results", "items")
        },
        "score_metrics": {
            "roc_auc": metrics.roc_auc(score_records),
            "average_precision": metrics.average_precision(score_records),
            "scored_binary_denominator": sum(record.get("answerability") in {metrics.SUPPORTED, metrics.INSUFFICIENT} and record.get("score") is not None for record in score_records),
            "valid_assessed_semantic_denominator": valid_assessed_semantic_denominator,
            "binary_denominator": sum(case["answerability"] in {metrics.SUPPORTED, metrics.INSUFFICIENT} for case in cases),
            "ambiguous_excluded_from_binary": sum(case["answerability"] == metrics.AMBIGUOUS for case in cases),
        },
        "errors": errors,
        "case_results": ordered,
    }
    if threshold is not None:
        cutoff = float(threshold["threshold"])
        classification = metrics.confusion_metrics(score_records, cutoff)
        challenge = metrics.challenge_false_positive_rates(score_records, cutoff)
        gates = metrics.quality_gates(classification, challenge)
        report["threshold"] = threshold
        report["test_metrics" if stage == "test" else "development_metrics"] = {
            **classification,
            **challenge,
            "quality_gates": gates,
        }
        if evidence_advice == "jev":
            all_advice_assessed = execution_passed and len(assessed_case_ids) == len(cases)
            gates["checks"]["evidence_advice_all_assessed"] = all_advice_assessed
            gates["passed"] = bool(gates.get("passed")) and all_advice_assessed
            report["test_metrics" if stage == "test" else "development_metrics"]["quality_gates"] = gates
        report["quality_gates"] = gates
        if stage == "test":
            report["bootstrap"] = metrics.intent_cluster_bootstrap(
                score_records, replicates=bootstrap_replicates, seed=500,
                source_material_count=len(metrics.source_material_hashes(cases)),
            )
    return report


def run_stage(*, stage: str, cases_path: Path, journal_path: Path, corpus_manifest_sha256: str,
              base_url: str = DEFAULT_BASE_URL, threshold_path: Path, transport=None,
              resume: bool = False, bootstrap_replicates: int = BOOTSTRAP_REPLICATES,
              retrieval_mode: str = "baseline", score_name: str = metrics.SCORE_NAME,
              evidence_advice: str = "off") -> dict:
    if stage not in {"calibration", "test"}:
        raise EvaluationRunError("invalid_stage")
    if bootstrap_replicates < 1:
        raise EvaluationRunError("invalid_bootstrap_replicates")
    retrieval_mode = _validated_retrieval_mode(retrieval_mode)
    score_name = _validated_score_name(score_name)
    evidence_advice = _validated_evidence_advice(evidence_advice)
    if score_name == metrics.RERANKER_SCORE_NAME and retrieval_mode not in {"rerank", "contextual_rerank"}:
        raise EvaluationRunError("score_requires_reranker_mode")
    if score_name == metrics.JEV_SCORE_NAME and evidence_advice != "jev":
        raise EvaluationRunError("score_requires_jev_evidence_advice")
    cases_path = Path(cases_path)
    journal_path = Path(journal_path)
    threshold_path = Path(threshold_path)
    base_url = _validated_base_url(base_url)
    corpus_manifest_sha256 = _validate_sha256(corpus_manifest_sha256, "invalid_corpus_manifest_hash")
    cases, case_sha, distributions = _read_case_file(cases_path, stage)
    contract_sha = _case_contract_sha256()
    source_hashes = metrics.source_material_hashes(cases)
    threshold_value = None
    threshold_file_sha = None
    threshold_group_hashes = []
    if stage == "test":
        threshold_value, threshold_file_sha = _threshold_policy(
            threshold_path, corpus_manifest_sha256, contract_sha,
            retrieval_mode=retrieval_mode, score_name=score_name,
            evidence_advice=evidence_advice,
        )
        threshold_case_hashes = threshold_value.get("calibration_case_id_sha256", [])
        if set(metrics.case_id_hashes(cases)).intersection(threshold_case_hashes):
            raise EvaluationRunError("calibration_test_case_overlap")
        threshold_group_hashes = threshold_value.get("calibration_intent_group_sha256", [])
        if not isinstance(threshold_group_hashes, list) or any(not isinstance(x, str) for x in threshold_group_hashes):
            raise EvaluationRunError("threshold_identity_mismatch")
        current_groups = set(metrics.intent_group_hashes(cases))
        if current_groups.intersection(threshold_group_hashes):
            raise EvaluationRunError("calibration_test_intent_overlap")
        current_sources = set(source_hashes)
        if current_sources.intersection(threshold_value.get("calibration_source_material_sha256", [])):
            raise EvaluationRunError("calibration_test_source_overlap")
    elif not resume and (threshold_path.exists() or threshold_path.is_symlink()):
        raise EvaluationRunError("fresh_threshold_exists")

    identity = {
        "stage": stage,
        "runner_version": RUNNER_VERSION,
        "runtime_version_status": RUNTIME_VERSION_STATUS,
        "case_manifest_sha256": case_sha,
        "case_contract_sha256": contract_sha,
        "corpus_manifest_sha256": corpus_manifest_sha256,
        "policy_version": EXPECTED_POLICY_VERSION,
        "retrieval_mode": retrieval_mode,
        "score_name": score_name,
        "evidence_advice": evidence_advice,
        "base_url": base_url,
        "request": _request_body(retrieval_mode, evidence_advice),
        "threshold_file_sha256": threshold_file_sha,
    }
    http = transport or HTTPTransport(base_url)
    with JsonlJournal(journal_path, identity, resume=resume) as journal:
        case_records = [record for record in journal.records if record.get("event") == "case_result"]
        recorded_ids = {record["case_id"] for record in case_records}
        known_ids = {case["id"] for case in cases}
        if recorded_ids - known_ids:
            raise EvaluationRunError("journal_case_set_mismatch")
        pending = [(index, case) for index, case in enumerate(cases) if case["id"] not in recorded_ids]

        def execute_case(index_case):
            index, case = index_case
            payload = {"query": case["query"], **_request_body(retrieval_mode, evidence_advice)}
            started = time.monotonic()
            try:
                value = http.post_search(payload)
                body, status, attempts, response_bytes = _response_parts(value)
                if status != 200:
                    raise SearchRequestError(f"http_{status}", http_status=status, attempts=attempts)
                if body.get("policy_version") != EXPECTED_POLICY_VERSION:
                    raise SearchRequestError("retrieval_policy_mismatch", http_status=status, attempts=attempts)
                record = _case_result_record(
                    case, index=index, response_body=body, error=None,
                    latency=time.monotonic() - started, retrieval_mode=retrieval_mode,
                    score_name=score_name, evidence_advice=evidence_advice,
                )
                record["http_status"] = status
                record["http_attempts"] = attempts
                record["response_bytes"] = response_bytes
                return record
            except SearchRequestError as error:
                return _case_result_record(
                    case, index=index, response_body=None, error=error,
                    latency=time.monotonic() - started, retrieval_mode=retrieval_mode,
                    score_name=score_name, evidence_advice=evidence_advice,
                )
            except Exception:
                safe_error = SearchRequestError("internal_evaluation_error")
                return _case_result_record(
                    case, index=index, response_body=None, error=safe_error,
                    latency=time.monotonic() - started, retrieval_mode=retrieval_mode,
                    score_name=score_name, evidence_advice=evidence_advice,
                )

        if pending:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = [executor.submit(execute_case, pair) for pair in pending]
                for future in as_completed(futures):
                    journal.append(future.result())
        case_records = [record for record in journal.records if record.get("event") == "case_result"]
        by_id = {record["case_id"]: record for record in case_records}
        latest_records = [by_id[case["id"]] for case in cases if case["id"] in by_id]
        if stage == "calibration":
            all_success = len(latest_records) == len(cases) and all(record.get("status") == "ok" for record in latest_records)
            if all_success:
                selected = metrics.select_threshold([
                    {"score": record["score"], "answerability": record["answerability"]}
                    for record in latest_records
                ], target_tpr=0.90)
                policy = {
                    "schema_version": THRESHOLD_SCHEMA_VERSION,
                    "stage": "calibration_frozen_threshold",
                    "runner_version": RUNNER_VERSION,
                    "runtime_version_status": RUNTIME_VERSION_STATUS,
                    "retrieval_mode": retrieval_mode,
                    "score_name": score_name,
                    "evidence_advice": evidence_advice,
                    "probability": False,
                    "threshold": selected["threshold"],
                    "target_supported_tpr": selected["target_tpr"],
                    "calibration_supported_tpr": selected["supported_tpr"],
                    "comparison": ">=",
                    "policy_version": EXPECTED_POLICY_VERSION,
                    "request": _request_body(retrieval_mode, evidence_advice),
                    "corpus_manifest_sha256": corpus_manifest_sha256,
                    "case_contract_sha256": contract_sha,
                    "calibration_case_manifest_sha256": case_sha,
                    "calibration_case_id_sha256": metrics.case_id_hashes(cases),
                    "calibration_intent_group_sha256": metrics.intent_group_hashes(cases),
                    "calibration_source_material_sha256": source_hashes,
                    "score_definition": _score_definition(score_name),
                }
                _write_private_json_no_overwrite(threshold_path, policy)
                frozen_hash = hashlib.sha256(threshold_path.read_bytes()).hexdigest()
                if not any(record.get("event") == "threshold_frozen" for record in journal.records):
                    journal.append({"event": "threshold_frozen", "threshold_file_sha256": frozen_hash, "threshold": policy["threshold"], "retrieval_mode": retrieval_mode, "score_name": score_name, "evidence_advice": evidence_advice, "policy_version": EXPECTED_POLICY_VERSION})
                threshold_value = policy
            elif threshold_path.exists() and resume:
                frozen, _digest = _load_private_json(threshold_path)
                if (frozen.get("calibration_case_manifest_sha256") != case_sha
                        or frozen.get("corpus_manifest_sha256") != corpus_manifest_sha256
                        or frozen.get("case_contract_sha256") != contract_sha
                        or frozen.get("retrieval_mode") != retrieval_mode
                        or frozen.get("score_name") != score_name
                        or frozen.get("evidence_advice", "off") != evidence_advice
                        or frozen.get("request") not in (
                            _request_body(retrieval_mode, evidence_advice),
                            _request_body(retrieval_mode, evidence_advice, legacy_without_advice=True)
                            if evidence_advice == "off" else {},
                        )
                        or frozen.get("calibration_case_id_sha256") != metrics.case_id_hashes(cases)):
                    raise EvaluationRunError("threshold_identity_mismatch")
                threshold_value = frozen
        report = _summary_from_records(
            stage, cases, journal.records, threshold_value,
            bootstrap_replicates=bootstrap_replicates,
            retrieval_mode=retrieval_mode, score_name=score_name,
            evidence_advice=evidence_advice,
        )
        report["case_manifest_sha256"] = case_sha
        report["case_contract_sha256"] = contract_sha
        report["corpus_manifest_sha256"] = corpus_manifest_sha256
        report["request"] = _request_body(retrieval_mode, evidence_advice)
        report["case_distribution"] = distributions
        report["run_id"] = journal.run_id
        report["journal_sha256"] = hashlib.sha256(journal_path.read_bytes()).hexdigest()
        if stage == "test" and threshold_value is not None:
            report["threshold_file_sha256"] = threshold_file_sha
    if stage == "calibration" and report.get("execution_gate_passed") and report.get("threshold") is None:
        report["status"] = "failed"
        report["execution_gate_passed"] = False
        report["error_count"] += 1
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the frozen eval500 sets against POST /api/search and persist a bounded owner-only JSONL journal.",
        epilog=(
            "Examples (run calibration first, then freeze its threshold for test):\n"
            "  python scripts/evaluate-retrieval-confidence.py --stage calibration --cases calibration.jsonl --journal calibration.journal.jsonl --threshold-output calibration-threshold.json --corpus-manifest-sha256 <sha256>\n"
            "  python scripts/evaluate-retrieval-confidence.py --stage test --cases test.jsonl --journal test.journal.jsonl --threshold-input calibration-threshold.json --corpus-manifest-sha256 <same-sha256>\n"
            "  Add --retrieval-mode, --evidence-advice, and --score-name identically to calibration and test to compare a frozen policy/score pair.\n"
            "  Jev advice scores are uncalibrated direct-support proxies; actual answer/action remains not evaluated.\n"
            "  Add --resume only for the exact same stage, case file, corpus, API base URL, policy, mode, advice, score, request, and threshold identity."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--stage", choices=("calibration", "test"), required=True)
    parser.add_argument("--cases", type=Path, required=True, help="Owner-held JSONL file using the published eval500 case contract.")
    parser.add_argument("--journal", type=Path, required=True, help="Owner-only resumable JSONL result journal; fresh paths are never overwritten.")
    parser.add_argument("--corpus-manifest-sha256", required=True, help="Frozen source/chunk snapshot manifest SHA-256.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--retrieval-mode", choices=sorted(metrics.RETRIEVAL_MODES), default="baseline", help="API retrieval mode; calibration and test thresholds are isolated per mode.")
    parser.add_argument("--evidence-advice", choices=("off", "jev"), default="off", help="Request optional Jev evidence advice; default off preserves existing search behavior.")
    parser.add_argument("--score-name", choices=sorted(metrics.SCORE_NAMES), default=metrics.SCORE_NAME, help="Rank-derived or Jev direct-support proxy; neither is answerability probability.")
    parser.add_argument("--resume", action="store_true", help="Resume missing case rows from a journal with identical manifest/policy identity.")
    parser.add_argument("--threshold-output", type=Path, help="Calibration stage: create frozen owner-only threshold JSON without overwriting.")
    parser.add_argument("--threshold-input", type=Path, help="Test stage: require a frozen calibration threshold JSON.")
    parser.add_argument("--bootstrap-replicates", type=int, default=BOOTSTRAP_REPLICATES)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.stage == "calibration":
        if args.threshold_output is None or args.threshold_input is not None:
            parser.error("calibration requires --threshold-output and forbids --threshold-input")
        threshold_path = args.threshold_output
    else:
        if args.threshold_input is None or args.threshold_output is not None:
            parser.error("test requires --threshold-input and forbids --threshold-output")
        threshold_path = args.threshold_input
    try:
        report = run_stage(
            stage=args.stage, cases_path=args.cases, journal_path=args.journal,
            corpus_manifest_sha256=args.corpus_manifest_sha256,
            base_url=args.base_url, threshold_path=threshold_path,
            resume=args.resume, bootstrap_replicates=args.bootstrap_replicates,
            retrieval_mode=args.retrieval_mode, score_name=args.score_name,
            evidence_advice=args.evidence_advice,
        )
    except EvaluationRunError as error:
        print(json.dumps({"status": "failed", "error_type": error.code}, separators=(",", ":")))
        return 1
    summary = {key: report.get(key) for key in (
        "stage", "status", "execution_gate_passed", "case_count", "recorded_case_count",
        "success_count", "error_count", "case_distribution", "group_counts",
        "retrieval_mode", "evidence_advice", "score_name", "probability", "actual_confidence", "actual_action",
        "actual_abstention", "threshold_is_proxy_only", "threshold_proxy_enforcement",
        "score_metrics", "development_metrics", "test_metrics", "rankings", "bootstrap",
        "threshold", "quality_gates", "policy_version", "runner_version",
        "runtime_version_status", "request", "case_manifest_sha256",
        "case_contract_sha256", "corpus_manifest_sha256", "threshold_file_sha256",
        "journal_sha256",
    )}
    print(json.dumps(summary, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
    return 0 if report.get("execution_gate_passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
