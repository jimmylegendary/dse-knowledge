"""Offline publication checks against the real public frozen baseline."""
import gzip
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("retrieval_report", ROOT / "scripts/build-retrieval-evaluation-report.py")
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)


@pytest.fixture
def baseline(tmp_path):
    public = ROOT / "research/eval500/results"
    journal = tmp_path / "test.jsonl"
    journal.write_bytes(gzip.decompress((public / "baseline-test.jsonl.gz").read_bytes()))
    summary = tmp_path / "summary.json"
    summary.write_bytes((public / "baseline-summary.json").read_bytes())
    calibration = tmp_path / "calibration.json"
    calibration.write_bytes((public / "baseline-calibration-summary.json").read_bytes())
    destination = tmp_path / "out"
    destination.mkdir()
    cases = [json.loads(line) for line in (ROOT / "research/eval500/test-v1.jsonl").read_text().splitlines()]
    definition = {"id":"baseline", "label":"Baseline", "mode":"baseline", "model":"none",
                  "journal":str(journal), "summary":str(summary), "calibration_summary":str(calibration)}
    return definition, cases, destination


def test_real_baseline_export_recomputes_and_preserves_nonsecret_provenance(baseline):
    definition, cases, destination = baseline
    result = REPORT.public_run(definition, cases, destination)
    exported = gzip.decompress((destination / "baseline-test.jsonl.gz").read_bytes())
    original = Path(definition["journal"]).read_bytes()
    assert exported == original
    assert json.loads(exported.splitlines()[0])["run_id"]
    assert len(result["rows"]) == 500
    assert result["summary"]["rankings"]["items"]["denominator"] == 300
    assert result["summary"]["quality_gates"]["passed"] is False
    assert result["audit"]["profile_type"] == "legacy_pinned_baseline"
    insufficient = [row for row in result["boundary_slices"] if row["meaning"] == "false_positive_rate"]
    assert sum(row["count"] for row in insufficient) == 180
    assert sum(row["above"] for row in insufficient) == result["summary"]["test_metrics"]["fp"] == 98


def test_export_rejects_mislabelled_mode_without_writing_public_files(baseline):
    definition, cases, destination = baseline
    definition.update(mode="rerank", model="Qwen/Qwen3-Reranker-8B")
    with pytest.raises(ValueError, match="mode_mismatch"):
        REPORT.public_run(definition, cases, destination)
    assert not list(destination.iterdir())


def test_export_rejects_stale_pass_badge_even_when_numeric_metrics_match(baseline):
    definition, cases, destination = baseline
    path = Path(definition["summary"])
    summary = json.loads(path.read_text())
    summary["quality_gates"]["passed"] = True
    path.write_text(json.dumps(summary))
    with pytest.raises(ValueError, match="quality_gate_recomputation_mismatch"):
        REPORT.public_run(definition, cases, destination)
    assert not list(destination.iterdir())


def test_export_rejects_calibration_from_another_frozen_cohort(baseline):
    definition, cases, destination = baseline
    path = Path(definition["calibration_summary"])
    calibration = json.loads(path.read_text())
    calibration["case_manifest_sha256"] = "0" * 64
    path.write_text(json.dumps(calibration))
    with pytest.raises(ValueError, match="calibration_case_hash_mismatch"):
        REPORT.public_run(definition, cases, destination)
    assert not list(destination.iterdir())


def test_public_metadata_guard_preserves_ids_but_rejects_credentials_and_raw_bodies():
    REPORT.check_projection({"run_id":"public-experiment-id", "base_url":"http://127.0.0.1:8080",
                             "threshold_file_sha256":"a" * 64})
    for value in [{"api_key":"fake-placeholder"}, {"notes":["https://operator:example-password@example.invalid/"]},
                  {"content":"raw source body"}, {"vector":{"embedding":[0.1,0.2]}}]:
        with pytest.raises(ValueError):
            REPORT.check_projection(value)
