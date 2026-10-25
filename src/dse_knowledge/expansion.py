"""Runtime handlers and bounded worker entrypoint for the pilot-1000 collection."""
from __future__ import annotations

import json
import math
import os
import re
import stat
import datetime as dt
import time
from pathlib import Path
from typing import Any

from .collection import (
    CollectionManager,
    PermanentCollectionError,
    ResourceCollectionError,
    RetryableCollectionError,
)


MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_PREPARED_CACHE_BYTES = 32 * 1024 * 1024
WORST_CASE_ACQUIRE_BYTES = MAX_SOURCE_BYTES + MAX_PREPARED_CACHE_BYTES
HOST_RESERVE_BYTES = 10 * 1024**3
INITIAL_ARTIFACT_BUDGET_BYTES = 4 * 1024**3
STAGE_CAPS = {"acquire": 1, "assess": None, "index": 2, "extract": 4}
MAX_WORKERS = 4
QUALITY_VERSION = "knowledge-quality/v2"
DEFAULT_COLLECTION_POLICY = {
    "max_workers": MAX_WORKERS,
    "stage_caps": STAGE_CAPS,
    "host_reserve_bytes": HOST_RESERVE_BYTES,
    "initial_artifact_budget_bytes": INITIAL_ARTIFACT_BUDGET_BYTES,
    "artifact_budget_bytes": INITIAL_ARTIFACT_BUDGET_BYTES,
}
_SAFE_REASON = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")
_TRANSIENT_SOURCE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_PRIVATE_ROOT = "pilot1000"
_ARTIFACT_INVENTORY_MAX_PASSES = 3
_ARTIFACT_INVENTORY_RETRY_SECONDS = 0.05
_RAW_ARTIFACT_TEMP_NAME = re.compile(r"^\.artifact-[a-z0-9_]{8}$")


class _ArtifactInventoryWriterActive(Exception):
    """A trusted raw artifact writer temp requires a fresh whole inventory pass."""


def _construct_store(settings):
    from .db import Store
    return Store(settings)


def _cache_helpers():
    """Load the project's owner-only cache primitives only when a stage runs."""
    from .pipeline import (
        _cached_material_reason,
        _check_private_directory,
        _ensure_private_directory,
        _read_cache_json,
        safe_material_id,
        save_json,
    )
    return {
        "cached_material_reason": _cached_material_reason,
        "check_private_directory": _check_private_directory,
        "ensure_private_directory": _ensure_private_directory,
        "read_cache_json": _read_cache_json,
        "safe_material_id": safe_material_id,
        "save_json": save_json,
    }


def _baseline_path(settings):
    return Path(settings.data_root) / _PRIVATE_ROOT / "artifact-baseline.json"


def _scan_artifact_inventory_once(settings, ops):
    data_root = Path(settings.data_root)
    artifact_root = Path(settings.artifact_root)
    prepared_root = data_root / _PRIVATE_ROOT / "prepared"
    ops["ensure_private_directory"](artifact_root)
    ops["ensure_private_directory"](prepared_root)
    raw_files = {}
    for prefix in sorted(artifact_root.iterdir()):
        if prefix.is_symlink() or not prefix.is_dir():
            raise ValueError("artifact_inventory_untrusted")
        ops["check_private_directory"](prefix)
        if not re.fullmatch(r"[0-9a-f]{2}", prefix.name):
            raise ValueError("artifact_inventory_untrusted")
        for artifact in sorted(prefix.iterdir()):
            info = artifact.lstat()
            if (artifact.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) & 0o077):
                raise ValueError("artifact_inventory_untrusted")
            if _RAW_ARTIFACT_TEMP_NAME.fullmatch(artifact.name):
                if stat.S_IMODE(info.st_mode) != 0o600:
                    raise ValueError("artifact_inventory_untrusted")
                raise _ArtifactInventoryWriterActive from None
            if (not re.fullmatch(r"[0-9a-f]{64}", artifact.name)
                    or not artifact.name.startswith(prefix.name)):
                raise ValueError("artifact_inventory_untrusted")
            raw_files[artifact.name] = int(info.st_size)
    prepared_files = {}
    for directory in (data_root / "pilot100" / "prepared", prepared_root):
        if not directory.exists():
            continue
        ops["check_private_directory"](directory)
        for prepared in sorted(directory.iterdir()):
            info = prepared.lstat()
            if (prepared.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) & 0o077):
                raise ValueError("prepared_inventory_untrusted")
            prepared_files[prepared.relative_to(data_root).as_posix()] = int(info.st_size)
    return {"raw_files": raw_files, "prepared_files": prepared_files}


def _scan_artifact_inventory(settings, ops):
    """Accept only a complete trust-checked pass, retrying narrow atomic-writer races."""
    for attempt in range(_ARTIFACT_INVENTORY_MAX_PASSES):
        try:
            return _scan_artifact_inventory_once(settings, ops)
        except (FileNotFoundError, _ArtifactInventoryWriterActive):
            if attempt + 1 < _ARTIFACT_INVENTORY_MAX_PASSES:
                time.sleep(_ARTIFACT_INVENTORY_RETRY_SECONDS)
    raise ResourceCollectionError("artifact_inventory_unavailable")


def _load_artifact_baseline(settings, ops=None):
    ops = ops or _cache_helpers()
    path = _baseline_path(settings)
    if not path.parent.exists():
        raise ResourceCollectionError("artifact_baseline_missing")
    try:
        ops["check_private_directory"](path.parent)
    except Exception:
        raise ResourceCollectionError("artifact_baseline_untrusted") from None
    try:
        path.lstat()
    except FileNotFoundError:
        raise ResourceCollectionError("artifact_baseline_missing") from None
    except OSError:
        raise ResourceCollectionError("artifact_baseline_unreadable") from None
    payload, reason = ops["read_cache_json"](path)
    if (reason or not isinstance(payload, dict) or payload.get("schema_version") != "pilot1000-artifact-baseline/v1"
            or not isinstance(payload.get("raw_files"), dict) or not isinstance(payload.get("prepared_files"), dict)):
        raise ResourceCollectionError("artifact_baseline_invalid")
    if any(type(size) is not int or size < 0 for size in (*payload["raw_files"].values(), *payload["prepared_files"].values())):
        raise ResourceCollectionError("artifact_baseline_invalid")
    return payload


def freeze_artifact_baseline(settings):
    """Create the owner-only pre-batch artifact baseline once; resume never replaces it."""
    ops = _cache_helpers()
    path = _baseline_path(settings)
    ops["ensure_private_directory"](path.parent)
    if path.exists() or path.is_symlink():
        return _load_artifact_baseline(settings, ops)
    inventory = _scan_artifact_inventory(settings, ops)
    payload = {
        "schema_version": "pilot1000-artifact-baseline/v1",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        **inventory,
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        return _load_artifact_baseline(settings, ops)
    except OSError:
        raise ValueError("artifact_baseline_write_failed") from None
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        directory_fd = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        # An incomplete baseline is retained and fails closed on every later read.
        raise ValueError("artifact_baseline_write_failed") from None
    return payload


def artifact_inventory_delta(settings):
    """Return physical file growth since the immutable baseline without exposing paths or hashes."""
    ops = _cache_helpers()
    baseline = _load_artifact_baseline(settings, ops)
    current = _scan_artifact_inventory(settings, ops)
    baseline_raw = baseline["raw_files"]
    baseline_prepared = baseline["prepared_files"]
    raw_bytes = sum(
        max(0, size - int(baseline_raw.get(digest, 0)))
        for digest, size in current["raw_files"].items()
    )
    prepared_bytes = sum(
        max(0, size - int(baseline_prepared.get(path, 0)))
        for path, size in current["prepared_files"].items()
    )
    return {
        "raw_artifact_bytes_delta": raw_bytes,
        "prepared_cache_bytes_delta": prepared_bytes,
        "physical_artifact_bytes_delta": raw_bytes + prepared_bytes,
        "baseline_created_at": baseline["created_at"],
    }


def _prepare_material(record, settings):
    from .ingestion import prepare_material
    return prepare_material(record, settings)


def _assess_role(document, settings, store):
    from .quality import assess_role
    return assess_role(document, settings, store=store, persist=False)


def _index_materials(settings, documents, store):
    from .pipeline import index_materials
    return index_materials(settings, documents, store)


def _enrich_context(document, settings, store):
    from .quality import enrich_context
    return enrich_context(document, settings, store=store)


def _extract_structured(document, settings, store):
    from .quality import extract_structured
    return extract_structured(document, settings, store=store)


def _safe_reason(value, fallback="collection_stage_failed"):
    return value if isinstance(value, str) and _SAFE_REASON.fullmatch(value) else fallback


def _provider_for_stage(stage):
    return {
        "acquire": "source_http",
        "assess": "decision_models",
        "index": "deepinfra",
        "extract": "codex_cli",
    }.get(stage, "unknown")


def _classify_error(exc, stage):
    """Map typed failures to safe durable outcomes; exception bodies are never copied."""
    if isinstance(exc, (PermanentCollectionError, RetryableCollectionError, ResourceCollectionError)):
        return exc

    exception_type = type(exc)
    if exception_type.__module__ == "dse_knowledge.providers" and exception_type.__name__ == "ProviderError":
        status = getattr(exc, "http_status", None)
        reason = _safe_reason(getattr(exc, "reason", None), "provider_error")
        code = f"{_provider_for_stage(stage)}_http_{status}" if type(status) is int else reason
        return RetryableCollectionError(code, provider=_provider_for_stage(stage))

    if exception_type.__module__ == "dse_knowledge.ingestion" and exception_type.__name__ == "IngestionError":
        reason = _safe_reason(getattr(exc, "reason", None), "source_acquisition_failed")
        status = getattr(exc, "http_status", None)
        if reason in {"artifact_store_unavailable"}:
            return ResourceCollectionError("artifact_store_unavailable")
        if reason.startswith(("claim_provider_failed.", "claim_provider_failed-", "claim_provider_failed_")):
            return RetryableCollectionError("codex_provider_failed", provider="codex_cli")
        for prefix in ("claim_provider_failed:", "claim_context_provider_failed:"):
            if isinstance(getattr(exc, "reason", None), str) and exc.reason.startswith(prefix):
                return RetryableCollectionError("codex_provider_failed", provider="codex_cli")
        if stage == "acquire":
            if type(status) is int and status in _TRANSIENT_SOURCE_STATUS:
                return RetryableCollectionError(f"source_http_{status}", provider="source_http")
            if reason in {"source_transport_error", "source_dns_failed"}:
                return RetryableCollectionError(reason, provider="source_http")
            if type(status) is int and status == 404:
                return PermanentCollectionError("source_not_found", state="failed")
            if type(status) is int and status == 410:
                return PermanentCollectionError("source_gone", state="failed")
            if reason in {"source_host_not_allowed", "non_public_source_address", "source_url_invalid"}:
                return PermanentCollectionError(reason, state="excluded")
            return PermanentCollectionError(reason, state="failed")
        if "provider_failed" in reason:
            return RetryableCollectionError("codex_provider_failed", provider="codex_cli")
        if any(token in reason for token in ("invalid", "mismatch", "shape", "quote", "schema", "context")):
            return PermanentCollectionError(reason, state="needs_review")
        return PermanentCollectionError(reason, state="needs_review")

    # quality.assess_role currently raises short, internal reason codes for Jev failures.
    message = exc.args[0] if getattr(exc, "args", None) and isinstance(exc.args[0], str) else ""
    if stage == "assess" and message in {"role_provider_unavailable", "role_provider_failed"}:
        return RetryableCollectionError(message, provider="decision_models")
    if stage == "assess" and message.startswith("role_provider_"):
        return PermanentCollectionError(_safe_reason(message, "role_assessment_invalid"), state="needs_review")

    module = type(exc).__module__
    sqlstate = getattr(exc, "sqlstate", None)
    if module.startswith("psycopg"):
        name = type(exc).__name__
        if name in {"OperationalError", "InterfaceError", "SerializationFailure", "DeadlockDetected"} or (isinstance(sqlstate, str) and sqlstate[:2] in {"08", "40", "53", "57"}):
            return RetryableCollectionError("database_transient", provider=False)
        return PermanentCollectionError("database_operation_failed", state="needs_review")
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return PermanentCollectionError("strict_validation_failed", state="needs_review")
    if isinstance(exc, OSError):
        return ResourceCollectionError("private_storage_failed")
    return PermanentCollectionError("collection_stage_failed", state="needs_review")


def _raise_classified(exc, stage):
    safe = _classify_error(exc, stage)
    raise safe from None


def _material_id(record):
    if not isinstance(record, dict):
        raise PermanentCollectionError("material_record_invalid", state="needs_review")
    for key in ("material_id", "id", "mid"):
        value = record.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()
    raise PermanentCollectionError("material_identity_missing", state="needs_review")


def _source_record(record, material_id):
    result = dict(record)
    result.setdefault("id", material_id)
    return result


def _validate_document(document, material_id):
    if not isinstance(document, dict):
        raise PermanentCollectionError("prepared_document_invalid", state="needs_review")
    material, revision = document.get("material"), document.get("revision")
    text, chunks = document.get("text"), document.get("chunks")
    if not isinstance(material, dict) or str(material.get("id") or material.get("mid")) != material_id:
        raise PermanentCollectionError("prepared_identity_mismatch", state="needs_review")
    if not isinstance(revision, dict) or not isinstance(text, str) or not isinstance(chunks, list) or not chunks:
        raise PermanentCollectionError("prepared_document_invalid", state="needs_review")
    if revision.get("scope") != "public_fulltext":
        raise PermanentCollectionError("source_fulltext_unavailable", state="failed")
    digest = revision.get("sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise PermanentCollectionError("prepared_revision_invalid", state="needs_review")
    byte_count = revision.get("bytes")
    if type(byte_count) is not int or byte_count <= 0 or byte_count > MAX_SOURCE_BYTES:
        raise PermanentCollectionError("source_size_invalid", state="failed")
    if len(text.strip()) < 500:
        raise PermanentCollectionError("source_fulltext_too_short", state="failed")


def _candidate_record_paths(settings, material_id, declared_path, ops):
    safe_id = ops["safe_material_id"](material_id)
    new_path = Path(settings.data_root) / _PRIVATE_ROOT / "prepared" / f"{safe_id}.json"
    old_path = Path(settings.data_root) / "pilot100" / "prepared" / f"{safe_id}.json"
    candidates = []
    if declared_path:
        declared = Path(os.path.abspath(os.fspath(declared_path)))
        allowed = {Path(os.path.abspath(new_path)), Path(os.path.abspath(old_path))}
        if declared not in allowed:
            raise PermanentCollectionError("prepared_path_untrusted", state="needs_review")
        candidates.append(declared)
    candidates.extend((new_path, old_path))
    unique = []
    for path in candidates:
        absolute = Path(os.path.abspath(path))
        if absolute not in unique:
            unique.append(absolute)
    return unique, Path(os.path.abspath(new_path))


def _read_prepared_cache(record, item_metadata, settings, store):
    ops = _cache_helpers()
    material_id = _material_id(record)
    source_record = _source_record(record, material_id)
    declared = item_metadata.get("prepared_path") or record.get("prepared_path")
    if not declared:
        declared = (record.get("metadata") or {}).get("prepared_path") if isinstance(record.get("metadata"), dict) else None
    paths, new_path = _candidate_record_paths(settings, material_id, declared, ops)
    for path in paths:
        if not path.parent.exists():
            continue
        try:
            ops["check_private_directory"](path.parent)
        except Exception:
            raise PermanentCollectionError("prepared_directory_untrusted", state="needs_review") from None
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            raise PermanentCollectionError("prepared_cache_unreadable", state="needs_review") from None
        document, reason = ops["read_cache_json"](path)
        if reason or document is None:
            raise PermanentCollectionError("prepared_cache_invalid", state="needs_review")
        try:
            _validate_document(document, material_id)
        except PermanentCollectionError:
            raise PermanentCollectionError("prepared_cache_invalid", state="needs_review") from None
        reason = ops["cached_material_reason"](source_record, document, settings)
        if reason:
            raise PermanentCollectionError("prepared_cache_mismatch", state="needs_review")
        return document, path, True, new_path
    if store.has_material(material_id):
        raise PermanentCollectionError("indexed_prepared_cache_missing", state="needs_review")
    return None, new_path, False, new_path


def _new_raw_artifact_bytes(document, baseline):
    revision = document.get("revision", {})
    amount = revision.get("bytes")
    digest = revision.get("sha256")
    if type(amount) is not int or amount <= 0 or not isinstance(digest, str):
        return 0
    return 0 if digest in baseline["raw_files"] else amount


def _new_prepared_cache_bytes(path, settings, baseline):
    relative = Path(path).relative_to(Path(settings.data_root)).as_posix()
    try:
        size = Path(path).stat().st_size
    except OSError:
        return 0
    return max(0, size - int(baseline["prepared_files"].get(relative, 0)))


def _physical_delta(settings):
    try:
        return artifact_inventory_delta(settings)["physical_artifact_bytes_delta"]
    except ResourceCollectionError:
        raise
    except Exception:
        raise ResourceCollectionError("artifact_inventory_unavailable") from None


def _artifact_budget_state(settings, item_metadata):
    baseline = _load_artifact_baseline(settings)
    row_remaining = item_metadata.get("artifact_budget_remaining_bytes")
    if type(row_remaining) is not int or row_remaining < 0:
        raise ResourceCollectionError("artifact_budget_unavailable")
    committed = item_metadata.get("artifact_bytes_committed", 0)
    if type(committed) is not int or committed < 0:
        committed = 0
    budget = item_metadata.get("artifact_budget_bytes")
    if type(budget) is not int or budget < 0:
        budget = row_remaining + committed
    physical_delta = _physical_delta(settings)
    if physical_delta > budget:
        raise ResourceCollectionError("artifact_budget_exceeded")
    return baseline, row_remaining, budget, physical_delta


def _assessment_path(settings, material_id, revision_sha256, ops):
    safe_id = ops["safe_material_id"](material_id)
    return Path(settings.data_root) / _PRIVATE_ROOT / "prepared" / f"{safe_id}.{revision_sha256}.assessment.json"


def _validate_assessment(assessment, document):
    from .knowledge import SOURCE_ROLES
    if not isinstance(assessment, dict):
        raise PermanentCollectionError("role_assessment_invalid", state="needs_review")
    role = assessment.get("role")
    provenance = assessment.get("provenance")
    if role not in SOURCE_ROLES or not isinstance(provenance, dict):
        raise PermanentCollectionError("role_assessment_invalid", state="needs_review")
    if provenance.get("revision_sha256") != document["revision"]["sha256"]:
        raise PermanentCollectionError("role_revision_mismatch", state="needs_review")
    proof_assessment = provenance.get("assessment")
    if not isinstance(proof_assessment, dict) or proof_assessment.get("role") != role:
        raise PermanentCollectionError("role_provenance_invalid", state="needs_review")
    if not isinstance(provenance.get("method"), str) or not isinstance(provenance.get("quality_version"), str):
        raise PermanentCollectionError("role_provenance_invalid", state="needs_review")
    if not isinstance(provenance.get("provider_metadata"), dict):
        raise PermanentCollectionError("role_provenance_invalid", state="needs_review")
    return role, provenance


def _load_assessment_sidecar(settings, material_id, revision_sha256, ops):
    path = _assessment_path(settings, material_id, revision_sha256, ops)
    if not path.parent.exists():
        return None
    try:
        ops["check_private_directory"](path.parent)
    except Exception:
        raise PermanentCollectionError("assessment_directory_untrusted", state="needs_review") from None
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise PermanentCollectionError("assessment_cache_unreadable", state="needs_review") from None
    payload, reason = ops["read_cache_json"](path)
    if reason or not isinstance(payload, dict):
        raise PermanentCollectionError("assessment_cache_invalid", state="needs_review")
    assessment = payload.get("assessment")
    if payload.get("revision_sha256") != revision_sha256:
        raise PermanentCollectionError("assessment_revision_mismatch", state="needs_review")
    _validate_assessment(assessment, {"revision": {"sha256": revision_sha256}})
    return assessment


def _write_assessment_sidecar(settings, material_id, document, assessment, ops):
    _, provenance = _validate_assessment(assessment, document)
    path = _assessment_path(settings, material_id, document["revision"]["sha256"], ops)
    ops["ensure_private_directory"](path.parent)
    ops["save_json"](path, {
        "material_id": material_id,
        "revision_sha256": document["revision"]["sha256"],
        "assessment": assessment,
        "provenance": provenance,
    })
    return path


def _usage_from_provider_metadata(provider_metadata, fallback_provider):
    if (not isinstance(provider_metadata, dict) or provider_metadata.get("cache_hit") is True
            or provider_metadata.get("skipped") is True):
        return {}
    provider = provider_metadata.get("provider")
    if not isinstance(provider, str) or not provider:
        return {}
    usage = {"provider": provider}
    model = provider_metadata.get("model_selected") or provider_metadata.get("model")
    if isinstance(model, str):
        usage["model"] = model
    provider_usage = provider_metadata.get("usage")
    if isinstance(provider_usage, dict):
        for key in ("input_tokens", "output_tokens", "total_tokens", "cached_tokens", "duration_seconds"):
            value = provider_usage.get(key)
            if key == "duration_seconds" and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and value >= 0:
                usage[key] = float(value)
            elif key.endswith("tokens") and type(value) is int and value >= 0:
                usage[key] = value
    return usage


def _sidecar_was_in_baseline(path, settings, baseline):
    relative = Path(path).relative_to(Path(settings.data_root)).as_posix()
    return relative in baseline["prepared_files"]


def _existing_role_proof(store, material_id, role, revision_sha256):
    row = store.one("SELECT role,role_metadata FROM materials WHERE id=%s", (material_id,))
    if not row or row.get("role") != role:
        return False
    metadata = row.get("role_metadata") or {}
    return isinstance(metadata, dict) and metadata.get("revision_sha256") == revision_sha256


def _persist_role_if_needed(store, material_id, role, provenance, revision_sha256):
    if _existing_role_proof(store, material_id, role, revision_sha256):
        return
    if provenance.get("revision_sha256") != revision_sha256:
        raise PermanentCollectionError("role_revision_mismatch", state="needs_review")
    store.assess_material(material_id, role, provenance)


def make_handlers(settings, store=None):
    """Build lazy stage handlers; no provider or database operation runs here."""
    store = store if store is not None else _construct_store(settings)
    prepared_root = Path(settings.data_root) / _PRIVATE_ROOT / "prepared"

    def acquire(record, item_metadata):
        try:
            document, cache_path, cached, new_path = _read_prepared_cache(record, item_metadata, settings, store)
            material_id = _material_id(record)
            baseline, row_remaining, artifact_budget, physical_delta = _artifact_budget_state(settings, item_metadata)
            if cached:
                revision = document["revision"]
                artifact_bytes = (
                    _new_raw_artifact_bytes(document, baseline)
                    + _new_prepared_cache_bytes(cache_path, settings, baseline)
                )
                committed = item_metadata.get("artifact_bytes_committed", 0)
                if type(committed) is not int or committed < 0:
                    committed = 0
                artifact_bytes = max(0, artifact_bytes - committed)
                if artifact_bytes > row_remaining:
                    raise ResourceCollectionError("artifact_budget_exceeded", artifact_bytes=artifact_bytes)
                return {
                    "next_state": "acquired",
                    "metadata": {"prepared_path": str(cache_path), "source_revision_sha256": revision["sha256"]},
                    "usage": {"artifact_bytes": artifact_bytes} if artifact_bytes else {},
                }
            remaining = min(row_remaining, max(0, artifact_budget - physical_delta))
            if remaining < WORST_CASE_ACQUIRE_BYTES:
                raise ResourceCollectionError("artifact_budget_below_worst_case")
            ops = _cache_helpers()
            try:
                document = _prepare_material(_source_record(record, material_id), settings)
            except Exception as exc:
                new_bytes = max(0, _physical_delta(settings) - physical_delta)
                safe = _classify_error(exc, "acquire")
                if isinstance(safe, PermanentCollectionError):
                    raise PermanentCollectionError(
                        safe.code, state=safe.state, artifact_bytes=new_bytes,
                    ) from None
                if isinstance(safe, ResourceCollectionError):
                    raise ResourceCollectionError(safe.code, artifact_bytes=new_bytes) from None
                if isinstance(safe, RetryableCollectionError) and new_bytes:
                    raise ResourceCollectionError("artifact_write_incomplete", artifact_bytes=new_bytes) from None
                raise safe from None
            raw_bytes = _new_raw_artifact_bytes(document, baseline)
            try:
                _validate_document(document, material_id)
            except PermanentCollectionError as exc:
                raise PermanentCollectionError(exc.code, state=exc.state, artifact_bytes=raw_bytes) from None
            reason = ops["cached_material_reason"](_source_record(record, material_id), document, settings)
            if reason:
                raise PermanentCollectionError("prepared_material_invalid", state="failed", artifact_bytes=raw_bytes)
            encoded = json.dumps(document, ensure_ascii=False, indent=2, default=str).encode("utf-8")
            if len(encoded) > MAX_PREPARED_CACHE_BYTES:
                raise ResourceCollectionError("prepared_cache_too_large", artifact_bytes=raw_bytes)
            ops["ensure_private_directory"](prepared_root)
            if new_path.exists():
                cached_document, reason = ops["read_cache_json"](new_path)
                if reason or not isinstance(cached_document, dict) or cached_document.get("revision", {}).get("sha256") != document["revision"]["sha256"]:
                    cache_bytes = _new_prepared_cache_bytes(new_path, settings, baseline)
                    raise PermanentCollectionError("prepared_cache_collision", state="needs_review", artifact_bytes=raw_bytes + cache_bytes)
                document = cached_document
            else:
                try:
                    ops["save_json"](new_path, document)
                except Exception:
                    cache_bytes = _new_prepared_cache_bytes(new_path, settings, baseline)
                    raise ResourceCollectionError("prepared_cache_write_failed", artifact_bytes=raw_bytes + cache_bytes) from None
            cache_bytes = _new_prepared_cache_bytes(new_path, settings, baseline)
            artifact_bytes = raw_bytes + cache_bytes
            if artifact_bytes > row_remaining or _physical_delta(settings) > artifact_budget:
                raise ResourceCollectionError("artifact_budget_exceeded", artifact_bytes=artifact_bytes)
            return {
                "next_state": "acquired",
                "metadata": {"prepared_path": str(new_path), "source_revision_sha256": document["revision"]["sha256"]},
                "usage": {"provider": "source_http", "artifact_bytes": artifact_bytes},
            }
        except (PermanentCollectionError, RetryableCollectionError, ResourceCollectionError):
            raise
        except Exception as exc:
            _raise_classified(exc, "acquire")

    def assess(record, item_metadata):
        try:
            document, path, _cached, _ = _read_prepared_cache(record, item_metadata, settings, store)
            if document is None:
                raise PermanentCollectionError("prepared_cache_missing", state="needs_review")
            material_id = _material_id(record)
            revision = document["revision"]["sha256"]
            expected = item_metadata.get("source_revision_sha256")
            if expected and expected != revision:
                raise PermanentCollectionError("stage_revision_mismatch", state="needs_review")
            ops = _cache_helpers()
            assessment_path = _assessment_path(settings, material_id, revision, ops)
            assessment = _load_assessment_sidecar(settings, material_id, revision, ops)
            sidecar_replay = assessment is not None
            baseline = _load_artifact_baseline(settings) if sidecar_replay else None
            if assessment is None:
                assessment = _assess_role(document, settings, store)
                _validate_assessment(assessment, document)
                _write_assessment_sidecar(settings, material_id, document, assessment, ops)
            role, provenance = _validate_assessment(assessment, document)
            if store.has_material(material_id):
                _persist_role_if_needed(store, material_id, role, provenance, revision)
            result_state = "excluded" if role == "out_of_scope" else "needs_review" if role == "unclassified" else "assessed"
            metadata = {
                "prepared_path": str(path),
                "source_revision_sha256": revision,
                "role": role,
            }
            provider_usage = _usage_from_provider_metadata(provenance.get("provider_metadata"), "decision_models")
            if sidecar_replay and _sidecar_was_in_baseline(assessment_path, settings, baseline):
                provider_usage = {}
            return {"next_state": result_state, "metadata": metadata, "usage": provider_usage}
        except (PermanentCollectionError, RetryableCollectionError, ResourceCollectionError):
            raise
        except Exception as exc:
            _raise_classified(exc, "assess")

    def index(record, item_metadata):
        try:
            document, path, _cached, _ = _read_prepared_cache(record, item_metadata, settings, store)
            if document is None:
                raise PermanentCollectionError("prepared_cache_missing", state="needs_review")
            material_id = _material_id(record)
            revision = document["revision"]["sha256"]
            role = item_metadata.get("role")
            expected = item_metadata.get("source_revision_sha256")
            if expected and expected != revision:
                raise PermanentCollectionError("stage_revision_mismatch", state="needs_review")
            assessment = _load_assessment_sidecar(settings, material_id, revision, _cache_helpers())
            if assessment is None:
                raise PermanentCollectionError("role_assessment_missing", state="needs_review")
            assessed_role, provenance = _validate_assessment(assessment, document)
            if role and role != assessed_role:
                raise PermanentCollectionError("role_assessment_mismatch", state="needs_review")
            role = assessed_role
            if role in {"out_of_scope", "unclassified"}:
                state = "excluded" if role == "out_of_scope" else "needs_review"
                return {"next_state": state, "metadata": {"role": role, "prepared_path": str(path), "source_revision_sha256": revision}, "usage": {}}
            existing = store.has_material(material_id)
            written = 0
            if not existing:
                try:
                    written = _index_materials(settings, [document], store)
                except Exception as exc:
                    if not store.has_material(material_id):
                        _raise_classified(exc, "index")
            if not store.has_material(material_id):
                raise RetryableCollectionError("index_commit_not_visible", provider=False)
            # Persist the advisory only after canonical material/revision commit.
            # Extract retries this idempotently if this separate write fails.
            try:
                _persist_role_if_needed(store, material_id, role, provenance, revision)
            except Exception:
                pass
            usage = {"provider": "deepinfra"} if not existing and type(written) is int and written > 0 else {}
            return {
                "next_state": "indexed",
                "metadata": {"indexed": True, "role": role, "prepared_path": str(path), "source_revision_sha256": revision},
                "usage": usage,
            }
        except (PermanentCollectionError, RetryableCollectionError, ResourceCollectionError):
            raise
        except Exception as exc:
            _raise_classified(exc, "index")

    def extract(record, item_metadata):
        try:
            document, path, _cached, _ = _read_prepared_cache(record, item_metadata, settings, store)
            if document is None:
                raise PermanentCollectionError("prepared_cache_missing", state="needs_review")
            material_id = _material_id(record)
            revision = document["revision"]["sha256"]
            expected = item_metadata.get("source_revision_sha256")
            if expected and expected != revision:
                raise PermanentCollectionError("stage_revision_mismatch", state="needs_review")
            row = store.one("SELECT role,role_metadata FROM materials WHERE id=%s", (material_id,))
            role = item_metadata.get("role") or (row or {}).get("role")
            if not role:
                raise PermanentCollectionError("material_role_missing", state="needs_review")
            assessment = _load_assessment_sidecar(settings, material_id, revision, _cache_helpers())
            if assessment is not None:
                assessed_role, provenance = _validate_assessment(assessment, document)
                if assessed_role != role:
                    raise PermanentCollectionError("role_assessment_mismatch", state="needs_review")
                _persist_role_if_needed(store, material_id, role, provenance, revision)
            elif not _existing_role_proof(store, material_id, role, revision):
                raise PermanentCollectionError("role_provenance_missing", state="needs_review")
            if role in {"source_navigation", "out_of_scope"}:
                return {
                    "next_state": "reference_only",
                    "metadata": {"role": role, "prepared_path": str(path), "source_revision_sha256": revision,
                                 "extraction_version": _quality_version(), "claim_count": 0, "annotation_count": 0},
                    "usage": {},
                }
            if role == "unclassified":
                return {"next_state": "needs_review", "metadata": {"role": role}, "usage": {}}
            claims = store.rows(
                """SELECT cl.* FROM claims cl JOIN revisions r ON r.id=cl.revision_id
                   WHERE cl.material_id=%s AND r.material_id=cl.material_id AND r.sha256=%s ORDER BY cl.id""",
                (material_id, revision),
            )
            if claims:
                result = _enrich_context(document, settings, store)
                claim_count = len(claims)
            else:
                result = _extract_structured(document, settings, store)
                claim_count = result.get("claims") if isinstance(result, dict) else None
            if not isinstance(result, dict) or result.get("material_id") != material_id:
                raise PermanentCollectionError("extraction_result_invalid", state="needs_review")
            status = result.get("status")
            annotation_count = result.get("annotations")
            if type(annotation_count) is not int or annotation_count < 0:
                raise PermanentCollectionError("extraction_result_invalid", state="needs_review")
            if type(claim_count) is not int or claim_count < 0:
                claim_count = len(claims) if claims else 0
            if status in {"complete", "enriched", "already_enriched"}:
                if claim_count <= 0:
                    raise PermanentCollectionError("extraction_empty", state="needs_review")
                next_state = "complete"
            elif status == "reference_only":
                next_state = "reference_only"
            elif status == "needs_review":
                next_state = "needs_review"
            else:
                raise PermanentCollectionError("extraction_status_invalid", state="needs_review")
            return {
                "next_state": next_state,
                "metadata": {
                    "role": role, "prepared_path": str(path), "source_revision_sha256": revision,
                    "extraction_version": _quality_version(), "claim_count": claim_count,
                    "annotation_count": annotation_count,
                },
                "usage": _usage_from_provider_metadata(result.get("provider_metadata"), "codex_cli"),
            }
        except (PermanentCollectionError, RetryableCollectionError, ResourceCollectionError):
            raise
        except Exception as exc:
            _raise_classified(exc, "extract")

    return {"acquire": acquire, "assess": assess, "index": index, "extract": extract}


def _quality_version():
    return QUALITY_VERSION


def add_artifact_inventory_summary(summary, settings):
    """Add physical artifact growth and its row-ledger variance without paths or hashes."""
    result = dict(summary or {})
    try:
        delta = artifact_inventory_delta(settings)
    except ResourceCollectionError as exc:
        result.update({
            "artifact_inventory_available": False,
            "artifact_inventory_error": exc.code,
            "raw_artifact_bytes_delta": None,
            "prepared_cache_bytes_delta": None,
            "physical_artifact_bytes_delta": None,
            "artifact_bytes_ledger_delta": None,
        })
        return result
    except Exception:
        result.update({
            "artifact_inventory_available": False,
            "artifact_inventory_error": "artifact_inventory_unavailable",
            "raw_artifact_bytes_delta": None,
            "prepared_cache_bytes_delta": None,
            "physical_artifact_bytes_delta": None,
            "artifact_bytes_ledger_delta": None,
        })
        return result
    physical = int(delta["physical_artifact_bytes_delta"])
    ledger = int(result.get("artifact_bytes_used", 0))
    result.update({
        "artifact_inventory_available": True,
        "artifact_inventory_error": None,
        "raw_artifact_bytes_delta": int(delta["raw_artifact_bytes_delta"]),
        "prepared_cache_bytes_delta": int(delta["prepared_cache_bytes_delta"]),
        "physical_artifact_bytes_delta": physical,
        "artifact_bytes_ledger_delta": physical - ledger,
        "artifact_inventory_baseline_created_at": delta["baseline_created_at"],
    })
    return result


def run_one_worker(settings, batch_id, worker_id, max_steps=None):
    """Run a single bounded worker process; callers own process-pool orchestration."""
    store = _construct_store(settings)
    handlers = make_handlers(settings, store)
    policy = dict(DEFAULT_COLLECTION_POLICY)
    repository = getattr(store, "collection_repository", None)
    if repository is not None:
        policy["repository"] = repository
    manager = CollectionManager.from_batch(
        store, settings.data_root, handlers, batch_id, policy=policy,
    )
    summary = manager.run_worker(batch_id, worker_id, max_steps=max_steps)
    return add_artifact_inventory_summary(summary, settings)
