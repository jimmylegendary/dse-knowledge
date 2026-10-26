#!/usr/bin/env python3
"""Publish metadata-only, recomputed eval500 artifacts and a standalone report.

The owner supplies a private manifest containing completed run paths. No source
body, context hint, vector, credential, or unprojected provider response is read.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import statistics
import tempfile
import urllib.parse

import eval500_metrics as metrics

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {"text", "content", "context_text", "claim_contexts", "neighbor_evidence",
             "embedding", "embeddings", "authorization", "api_key", "password", "private_key",
             "access_token", "refresh_token"}
SECRET_LITERAL = re.compile(r"(?:sk-or-v1-[A-Za-z0-9_-]{20,}|\bsk-[A-Za-z0-9_-]{30,}|\bdi_[A-Za-z0-9_-]{24,}|Bearer\s+[A-Za-z0-9._-]{20,})")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_projection(value):
    if isinstance(value, dict):
        if FORBIDDEN.intersection(key.lower() for key in value):
            raise ValueError("unprojected_source_or_secret_field")
        for child in value.values():
            check_projection(child)
    elif isinstance(value, list):
        for child in value:
            check_projection(child)
    elif isinstance(value, str):
        if SECRET_LITERAL.search(value):
            raise ValueError("credential_literal_in_public_metadata")
        for raw in re.findall(r"https?://[^\s<>]+", value):
            parsed = urllib.parse.urlsplit(raw)
            if parsed.username is not None or parsed.password is not None:
                raise ValueError("credential_in_public_url")
            if any(key.casefold() in {"api_key", "access_token", "auth_token", "password"}
                   for key, _ in urllib.parse.parse_qsl(parsed.query)):
                raise ValueError("credential_in_public_url")


def read_journal(path, cases):
    records = [json.loads(line) for line in path.read_text().splitlines() if line]
    header, rows = records[0], records[1:]
    expected = {case["id"] for case in cases}
    if (len(rows) != len(cases) or {r["case_id"] for r in rows} != expected
            or any(r.get("status") != "ok" for r in rows)):
        raise ValueError("incomplete_or_invalid_execution")
    by_id = {case["id"]: case for case in cases}
    for row in rows:
        case = by_id[row["case_id"]]
        for key in ("query", "split", "answerability", "boundary_type", "intent_group", "language", "category", "difficulty", "expected_action"):
            if row.get(key) != case.get(key):
                raise ValueError("journal_frozen_case_metadata_mismatch")
        check_projection(row)
    check_projection(header)
    return header, rows


def near(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(near(a[k], b[k]) for k in a)
    if isinstance(a, (float, int)) and isinstance(b, (float, int)):
        return abs(a - b) < 1e-12
    return a == b


def ranking_slices(cases, rows):
    by_id = {row["case_id"]: row for row in rows}
    result = []
    for axis in ("language", "difficulty", "category"):
        for value in sorted({case[axis] for case in cases if case["answerability"] == "supported"}):
            subset = [case for case in cases if case["answerability"] == "supported" and case[axis] == value]
            result.append({"axis": axis, "value": value, "count": len(subset),
                           "metrics": metrics.aggregate_ranking(subset, {
                               case["id"]: by_id[case["id"]]["result"] for case in subset
                           }, stream="items")["metrics"]})
    return result


def boundary_slices(rows, threshold):
    result = []
    for boundary in sorted({row["boundary_type"] for row in rows if row["answerability"] != "supported"}):
        group = [row for row in rows if row["boundary_type"] == boundary and row["answerability"] != "supported"]
        above = sum(row["score"] >= threshold for row in group)
        ambiguous = all(row["answerability"] == "ambiguous" for row in group)
        result.append({"boundary_type":boundary, "count":len(group), "above":above,
                       "rate":above/len(group), "meaning":"ambiguous_above_proxy_rate" if ambiguous else "false_positive_rate"})
    return result


def public_run(definition, cases, destination):
    summary_path = Path(definition["summary"])
    summary = json.loads(summary_path.read_text())
    if (summary.get("stage") != "test" or not summary.get("execution_gate_passed")
            or summary.get("success_count") != len(cases)):
        raise ValueError("summary_not_a_completed_test")
    journal_path = Path(definition["journal"])
    header, rows = read_journal(journal_path, cases)
    mode = definition.get("mode", "baseline" if definition["id"] == "baseline" else None)
    if mode not in metrics.RETRIEVAL_MODES:
        raise ValueError("report_mode_required")
    legacy = mode == "baseline" and definition["id"] == "baseline" and "retrieval_mode" not in header
    for key in ("stage", "case_manifest_sha256", "case_contract_sha256", "corpus_manifest_sha256",
                "policy_version", "runner_version", "score_name", "request", "threshold_file_sha256"):
        if header.get(key) != summary.get(key):
            raise ValueError("journal_summary_identity_mismatch")
    if not legacy and (header.get("retrieval_mode") != mode or summary.get("retrieval_mode") != mode):
        raise ValueError("report_mode_mismatch")
    expected_model = None if definition.get("model", "none") == "none" else definition["model"]
    if (mode in {"rerank", "contextual_rerank"}) != (expected_model is not None):
        raise ValueError("report_model_mode_mismatch")
    if legacy and summary["score_name"] != metrics.SCORE_NAME:
        raise ValueError("legacy_baseline_score_mismatch")
    for row in rows:
        result = row["result"]
        if not legacy and (row.get("retrieval_mode") != mode or result.get("retrieval_mode") != mode):
            raise ValueError("case_returned_mode_mismatch")
        if "score_name" in row and row["score_name"] != summary["score_name"]:
            raise ValueError("case_score_name_mismatch")
        if not near(metrics.primary_score(result, score_name=summary["score_name"]), row["score"]):
            raise ValueError("case_score_derivation_mismatch")
        trace = result.get("reranker_trace") or {}
        if expected_model:
            empty = not result["items"] and trace.get("candidate_count") == 0
            if not empty and (trace.get("model") != expected_model or trace.get("provider") != "deepinfra"):
                raise ValueError("case_model_provider_mismatch")
        elif trace.get("model") is not None:
            raise ValueError("unexpected_reranker_in_unranked_mode")
    audit = {"profile_type": "legacy_pinned_baseline"}
    context_model = None
    if not legacy:
        profile_path = Path(definition["profile"])
        profile = json.loads(profile_path.read_text())
        before = profile["before"]
        if (not profile.get("verified") or profile["after"] != before
                or before["mode"] != mode or before["model"] != expected_model
                or profile["case_count"] != len(cases)
                or profile["threshold_sha256"] != summary["threshold_file_sha256"]
                or profile["summary_sha256"] != digest(summary_path)
                or profile["journal_sha256"] != digest(journal_path)):
            raise ValueError("pinned_profile_receipt_mismatch")
        audit = {"profile_type": "verified_actual_runtime", "receipt_sha256": digest(profile_path),
                 "runtime_source_hashes": before["source_code"], "evaluator_source_hashes": before["evaluator_code"],
                 "provider": before["provider"], "model": before["model"], "mode": before["mode"],
                 "embedding_profile": before["embedding"]}
        if mode in {"contextual", "contextual_rerank"}:
            index = before.get("index")
            active = index.get("active", {}) if isinstance(index, dict) else {}
            index_manifest = active.get("manifest", {})
            if (index_manifest.get("complete") is not True
                    or not isinstance(index_manifest.get("context_model"), str)
                    or not index_manifest.get("context_model")
                    or not index_manifest.get("prompt_version")
                    or not index_manifest.get("fts_sqlite_version")
                    or type(index_manifest.get("source_count")) is not int
                    or index_manifest["source_count"] <= 0
                    or type(index_manifest.get("chunk_count")) is not int
                    or index_manifest["chunk_count"] <= 0
                    or not all(isinstance(active.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", active[key])
                               for key in ("file_sha256", "manifest_sha256"))):
                raise ValueError("contextual_active_index_profile_required")
            expected_index = definition.get("expected_index_file_sha256")
            if not isinstance(expected_index, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_index):
                raise ValueError("contextual_index_artifact_binding_required")
            if active["file_sha256"] != expected_index:
                raise ValueError("contextual_index_artifact_binding_mismatch")
        if before["index"]:
            active = before["index"]["active"]
            audit.update(index_generation_id=active["generation_id"], index_file_sha256=active["file_sha256"],
                         index_manifest_sha256=active["manifest_sha256"],
                         index_fts_sqlite_version=active["manifest"]["fts_sqlite_version"],
                         index_context_prompt_version=active["manifest"]["prompt_version"],
                         index_eligible_sources=active["manifest"]["source_count"],
                         index_eligible_chunks=active["manifest"]["chunk_count"])
            context_model = active["manifest"]["context_model"]
    results = {row["case_id"]: row["result"] for row in rows}
    per_case_ranking = {
        case["id"]: {stream: metrics.ranking_metrics(case, results[case["id"]], stream=stream)
                     for stream in ("items", "source_results")}
        for case in cases if case["answerability"] == "supported"
    }
    for row in rows:
        if row["case_id"] in per_case_ranking and not near(row.get("ranking"), per_case_ranking[row["case_id"]]):
            raise ValueError("per_case_ranking_mismatch")
    recalculated = {stream: metrics.aggregate_ranking(cases, results, stream=stream)
                    for stream in ("items", "source_results")}
    if not near(recalculated, summary["rankings"]):
        raise ValueError("ranking_summary_recomputation_mismatch")
    if (not near(metrics.roc_auc(rows), summary["score_metrics"]["roc_auc"])
            or not near(metrics.average_precision(rows), summary["score_metrics"]["average_precision"])):
        raise ValueError("score_summary_recomputation_mismatch")
    cutoff = summary["threshold"]["threshold"]
    classification = metrics.confusion_metrics(rows, cutoff)
    boundary = metrics.challenge_false_positive_rates(rows, cutoff)
    for key, value in (classification | boundary).items():
        if not near(value, summary["test_metrics"][key]):
            raise ValueError("threshold_summary_recomputation_mismatch")
    gates = metrics.quality_gates(classification, boundary)
    if (not near(gates, summary["quality_gates"])
            or not near(gates, summary["test_metrics"]["quality_gates"])):
        raise ValueError("quality_gate_recomputation_mismatch")
    if digest(journal_path) != summary["journal_sha256"]:
        raise ValueError("journal_hash_mismatch")
    if digest(ROOT / "research/eval500/test-v1.jsonl") != summary["case_manifest_sha256"]:
        raise ValueError("test_manifest_mismatch")
    calibration = json.loads(Path(definition["calibration_summary"]).read_text())
    if (not calibration.get("execution_gate_passed") or calibration.get("stage") != "calibration"
            or calibration.get("success_count") != 100 or calibration.get("threshold") != summary["threshold"]):
        raise ValueError("calibration_threshold_binding_mismatch")
    for key in ("policy_version", "corpus_manifest_sha256", "case_contract_sha256", "score_name", "request"):
        if calibration.get(key) != summary.get(key):
            raise ValueError("calibration_test_identity_mismatch")
    if (calibration["case_manifest_sha256"] != summary["threshold"]["calibration_case_manifest_sha256"]
            or calibration["case_manifest_sha256"] != digest(ROOT/"research/eval500/calibration-v1.jsonl")):
        raise ValueError("calibration_case_hash_mismatch")
    if not legacy and calibration.get("retrieval_mode") != mode:
        raise ValueError("calibration_mode_mismatch")
    check_projection(calibration)
    check_projection(summary)
    check_projection(audit)
    identifier = definition["id"]
    if not identifier.replace("-", "").replace("_", "").isalnum():
        raise ValueError("invalid_run_identifier")
    payload = journal_path.read_bytes()
    with (destination / f"{identifier}-test.jsonl.gz").open("wb") as handle:
        with gzip.GzipFile(fileobj=handle, mode="wb", filename="", mtime=0) as archive:
            archive.write(payload)
    safe_summary = {key: value for key, value in summary.items()
                    if key not in {"case_results", "errors"}}
    (destination / f"{identifier}-summary.json").write_text(
        json.dumps(safe_summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    for stage in ("calibration",):
        value = calibration
        value = {key: item for key, item in value.items() if key not in {"case_results", "errors"}}
        (destination / f"{identifier}-{stage}-summary.json").write_text(
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    latencies = [row["latency_seconds"] for row in rows]
    counts = Counter((row["answerability"], row["boundary_type"]) for row in rows)
    compact = [{
        "id": row["case_id"], "score": row["score"], "latency": row["latency_seconds"],
        "ranking": per_case_ranking.get(row["case_id"], {}), "status": row["status"],
        "top": [{key: item.get(key) for key in ("chunk_id", "material_id", "revision_id", "role")}
                for item in row["result"].get("items", [])[:5]],
    } for row in rows]
    return {"id": identifier, "label": definition["label"], "mode": mode,
            "model": definition.get("model", "none"), "context_model": context_model,
            "audit": audit, "summary": safe_summary,
            "rows": compact, "slices": ranking_slices(cases, rows),
            "boundary_slices": boundary_slices(rows, cutoff),
            "latency_median": statistics.median(latencies),
            "latency_p95": sorted(latencies)[max(0, int(len(latencies) * .95 + .999999) - 1)],
            "cohorts": [{"answerability": a, "boundary_type": b, "count": n}
                        for (a, b), n in sorted(counts.items())],
            "journal_payload_sha256": digest(journal_path),
            "journal_gzip_sha256": digest(destination / f"{identifier}-test.jsonl.gz")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "web/reports/retrieval-evaluation-2026-10-26.html")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    case_file = ROOT / "research/eval500/test-v1.jsonl"
    cases = [json.loads(line) for line in case_file.read_text().splitlines()]
    metrics.validate_cases(cases, "test")
    destination = ROOT / "research/eval500/results"
    destination.mkdir(parents=True, exist_ok=True)
    # Validate every run in a private staging directory. No partially validated
    # public package is left behind when a later run or manifest is rejected.
    staging = tempfile.TemporaryDirectory(prefix=".report-stage-", dir=destination.parent)
    staged_destination = Path(staging.name)
    runs = [public_run(run, cases, staged_destination) for run in manifest["runs"]]
    for run in runs:
        # These are separately recomputed and tied to the identical frozen test.
        if run["summary"]["case_manifest_sha256"] != digest(case_file):
            raise ValueError("cross_run_case_hash_mismatch")
    payload = {
        "schema_version": "retrieval-evaluation-report/v1", "date": "2026-10-26",
        "case_sha256": digest(case_file), "freeze": json.loads((case_file.parent / "freeze-v1.json").read_text()),
        "notes": manifest.get("notes", []), "selected_run": manifest.get("selected_run", runs[0]["id"]),
        "model_selection": manifest.get("model_selection", {}),
        "operating_mode_selection": manifest.get("operating_mode_selection", {}),
        "infra": manifest.get("infra", {}), "runs": runs,
        "cases": [{key: case.get(key) for key in (
            "id", "language", "difficulty", "category", "query", "answerability", "boundary_type",
            "expected_action", "intent_group", "gold_rationale", "missing_information", "evidence_groups",
            "nearby_evidence")} for case in cases],
    }
    if payload["selected_run"] not in {run["id"] for run in runs}:
        raise ValueError("selected_run_not_in_report")
    operating = payload["operating_mode_selection"]
    if operating and (operating.get("uses_test_results") is not False
                      or operating.get("selected", {}).get("id") != payload["selected_run"]
                      or not {candidate["id"] for candidate in operating.get("candidates", [])}
                          .issubset({run["id"] for run in runs})):
        raise ValueError("operating_selection_binding_mismatch")
    check_projection(payload)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    # HTML parsing must never interpret query content as a script terminator.
    escaped = data.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    template = (ROOT / "web/reports/retrieval-evaluation-template.html").read_text()
    if template.count("__REPORT_DATA__") != 1:
        raise ValueError("report_template_placeholder_invalid")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    staged_html = staged_destination / "report.html"
    staged_html.write_text(template.replace("__REPORT_DATA__", escaped))
    index = {"schema_version": payload["schema_version"], "test_sha256": payload["case_sha256"],
             "case_count": len(cases), "selected_run": payload["selected_run"],
             "runs": [{key: run[key] for key in ("id", "label", "model", "journal_payload_sha256", "journal_gzip_sha256")}
                      for run in runs], "report_sha256": digest(staged_html),
             "notes": payload["notes"], "model_selection": payload["model_selection"]}
    index["operating_mode_selection"] = payload["operating_mode_selection"]
    for artifact in sorted(staged_destination.iterdir()):
        if artifact != staged_html:
            artifact.replace(destination / artifact.name)
    staged_html.replace(args.output)
    # Completion index is written last, after all validated artifacts exist.
    (destination / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n")
    staging.cleanup()
    print(json.dumps({"status": "complete", "variants": len(runs), "test_cases": len(cases),
                      "ranking_recomputation": "PASS", "report": str(args.output),
                      "bytes": args.output.stat().st_size, "sha256": digest(args.output)}))


if __name__ == "__main__":
    main()
