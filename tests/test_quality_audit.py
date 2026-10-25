from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

from dse_knowledge.knowledge import validate_claim_context


SCRIPT = Path(__file__).parents[1] / "scripts" / "audit-quality.py"
SPEC = importlib.util.spec_from_file_location("quality_audit", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def _fixture_snapshot():
    text = "Latency was measured at 12 ms for this synthetic source."
    material_id = "material-private-1"
    revision = {
        "id": "revision-1", "material_id": material_id, "sha256": "a" * 64,
        "content": text, "scope": "public_fulltext", "created_at": "2026-10-25T00:00:00+00:00",
    }
    chunk = {
        "id": "chunk-1", "revision_id": "revision-1", "material_id": material_id,
        "start": 0, "end": len(text), "text": text,
    }
    claim_quote = "Latency was measured at 12 ms"
    claim_start = text.index(claim_quote)
    claim = {
        "id": "claim-private-1", "material_id": material_id, "revision_id": "revision-1",
        "chunk_id": "chunk-1", "quote": claim_quote,
        "metadata": {"source_start": claim_start, "source_end": claim_start + len(claim_quote)},
    }
    raw = {
        "schema_version": "claim-context/v1",
        "parameters": [{
            "name": "latency", "value": 12, "unit": "ms",
            "evidence": {"chunk_id": "chunk-1", "quote": "12 ms"},
        }],
        "conditions": [], "source_scope_note": "Synthetic scoped source statement.",
    }
    document = {
        "material": {"id": material_id}, "text": text,
        "revision": {"id": "revision-1", "sha256": "a" * 64}, "chunks": [chunk],
    }
    context = validate_claim_context(raw, document)
    annotation = {
        "id": "annotation-private-1", "claim_id": "claim-private-1",
        "revision_id": "revision-1", "version": "claim-context/v1", "context": context,
    }
    return {
        "materials": [{"id": material_id, "role": "core_technical", "status": "ingested", "category": "test"}],
        "revisions": [revision], "chunks": [chunk], "claims": [claim],
        "annotations": [annotation], "edges": [], "entity_ids": [],
        "vector_dimension_counts": [{"dimension": 768, "count": 1}],
    }


def _expanded_snapshot(material_count, claim_material_count, annotated_material_count):
    snapshot = _fixture_snapshot()
    base_material = snapshot["materials"][0]
    base_revision = snapshot["revisions"][0]
    base_chunk = snapshot["chunks"][0]
    base_claim = snapshot["claims"][0]
    base_annotation = snapshot["annotations"][0]
    for index in range(2, material_count + 1):
        material_id = f"material-private-{index}"
        snapshot["materials"].append({**deepcopy(base_material), "id": material_id})
        if index > claim_material_count:
            continue
        revision_id = f"revision-{index}"
        chunk_id = f"chunk-{index}"
        claim_id = f"claim-private-{index}"
        snapshot["revisions"].append({**deepcopy(base_revision), "id": revision_id, "material_id": material_id})
        snapshot["chunks"].append({
            **deepcopy(base_chunk), "id": chunk_id, "revision_id": revision_id, "material_id": material_id,
        })
        snapshot["claims"].append({
            **deepcopy(base_claim), "id": claim_id, "material_id": material_id,
            "revision_id": revision_id, "chunk_id": chunk_id,
        })
        if index <= annotated_material_count:
            annotation = {
                **deepcopy(base_annotation), "id": f"annotation-private-{index}",
                "claim_id": claim_id, "revision_id": revision_id,
            }
            for group in ("parameters", "conditions"):
                for item in annotation["context"][group]:
                    item["evidence"]["chunk_id"] = chunk_id
                    item["evidence"]["material_id"] = material_id
            snapshot["annotations"].append(annotation)
    return snapshot


def test_reconstruct_raw_context_preserves_raw_value_unit_and_evidence_id():
    snapshot = _fixture_snapshot()
    normalized = snapshot["annotations"][0]["context"]

    raw = audit.reconstruct_raw_context(normalized)

    assert raw["parameters"][0] == {
        "name": "latency", "value": 12, "unit": "ms",
        "evidence": {"chunk_id": "chunk-1", "quote": "12 ms"},
    }
    assert raw["conditions"] == []
    assert "measured at 12 ms" not in json.dumps(raw)


def test_audit_revalidates_annotation_and_reports_normalization_drift_without_source_text():
    snapshot = _fixture_snapshot()
    snapshot["annotations"][0]["context"]["parameters"][0]["normalized"]["status"] = "unresolved"

    report = audit.build_audit_report(snapshot, generated_at="2026-10-25T00:00:00+00:00")

    assert report["claims"]["valid_source_count"] == 1
    assert report["annotations"]["valid_count"] == 0
    assert report["annotations"]["normalization_status_errors"] == 1
    assert any(error["code"] == "annotation_normalization_mismatch" for error in report["errors"])
    serialized = json.dumps(report)
    assert "Latency was measured" not in serialized
    assert "12 ms" not in serialized


def test_valid_current_revision_claim_and_annotation_count_as_quality_complete():
    report = audit.build_audit_report(_fixture_snapshot())

    assert report["claims"]["valid_source_count"] == 1
    assert report["annotations"]["valid_count"] == 1
    assert report["roles"]["core_technical"]["fully_annotated_material_count"] == 1
    assert report["technical_eligible"]["claim_material_coverage_rate"] == 1.0
    assert report["technical_eligible"]["fully_annotated_material_rate"] == 1.0
    assert report["technical_eligible"]["claim_coverage_target_met"] is True
    assert report["technical_eligible"]["kg_complete_material_rate"] == 1.0
    assert report["technical_eligible"]["kg_coverage_target_met"] is True
    assert report["roles"]["core_technical"]["kg_complete_material_rate"] == 1.0
    assert report["roles"]["core_technical"]["kg_coverage_target_met"] is True


def test_conditional_annotation_rate_is_distinct_from_all_eligible_kg_coverage():
    report = audit.build_audit_report(_expanded_snapshot(104, 102, 97))
    technical = report["technical_eligible"]

    assert technical["fully_annotated_material_count"] == 97
    assert technical["current_claim_material_count"] == 102
    assert technical["material_count"] == 104
    assert technical["fully_annotated_material_rate"] == 97 / 102
    assert technical["fully_annotated_among_claim_materials_rate"] == 97 / 102
    assert technical["fully_annotated_material_rate_basis"] == "eligible_materials_with_current_revision_claims"
    assert technical["kg_complete_count"] == 97
    assert technical["kg_complete_material_rate"] == 97 / 104
    assert technical["kg_complete_material_rate_basis"] == "kg_eligible_materials"
    assert technical["claim_coverage_target_met"] is True
    assert technical["kg_coverage_target_met"] is True
    role = report["roles"]["core_technical"]
    assert role["fully_annotated_material_rate"] == 97 / 102
    assert role["kg_complete_material_rate"] == 97 / 104


def test_few_annotated_materials_do_not_pass_all_eligible_kg_coverage_gate():
    report = audit.build_audit_report(_expanded_snapshot(104, 104, 80))
    technical = report["technical_eligible"]

    assert technical["materials_with_source_valid_claims"] == 104
    assert technical["current_claim_material_count"] == 104
    assert technical["fully_annotated_material_count"] == 80
    assert technical["fully_annotated_material_rate"] == 80 / 104
    assert technical["kg_complete_material_rate"] == 80 / 104
    assert technical["kg_coverage_target_met"] is False
    assert report["roles"]["core_technical"]["kg_complete_material_rate"] == 80 / 104
    assert report["roles"]["core_technical"]["kg_coverage_target_met"] is False


def test_canonical_audit_can_validate_chunk_text_against_revision_without_retaining_duplicate_body():
    snapshot = _fixture_snapshot()
    snapshot["chunks"][0]["text"] = None
    snapshot["chunks"][0]["source_text_matches"] = True

    report = audit.build_audit_report(snapshot)

    assert report["claims"]["valid_source_count"] == 1
    assert report["annotations"]["valid_count"] == 1


def test_claim_audit_requires_matching_revision_chunk_and_absolute_offsets():
    snapshot = _fixture_snapshot()
    snapshot["claims"][0]["metadata"]["source_start"] += 1

    report = audit.build_audit_report(snapshot)

    assert report["claims"]["invalid_count"] == 1
    assert any(error["code"] == "claim_source_offset_mismatch" for error in report["errors"])


def test_graph_metrics_compute_id_components_and_multisource_size():
    result = audit.graph_metrics([
        {"source": "entity-a", "target": "entity-b", "material_id": "m1", "relation_kind": "assertion"},
        {"source": "entity-b", "target": "entity-c", "material_id": "m2", "relation_kind": "topic"},
        {"source": "entity-x", "target": "entity-y", "material_id": "m3", "relation_kind": "topic"},
    ], entity_ids=["isolated"])

    assert result["component_count"] == 3
    assert result["largest_component_node_count"] == 3
    assert result["largest_multisource_component_node_count"] == 3
    assert result["largest_multisource_component_source_count"] == 2
    assert result["multisource_component_count"] == 1
    assert result["edge_kind_counts"] == {"assertion": 1, "topic": 2}


def test_empty_technical_cohort_is_not_evaluated_and_rate_is_null():
    snapshot = _fixture_snapshot()
    snapshot["materials"][0]["role"] = "source_navigation"

    report = audit.build_audit_report(snapshot)
    technical = report["technical_eligible"]

    assert technical["status"] == "not_evaluated"
    assert technical["claim_material_coverage_rate"] is None
    assert technical["fully_annotated_material_rate"] is None
    assert report["roles"]["source_navigation"]["kg_complete_count"] == 0
    assert technical["kg_complete_material_rate"] is None
    assert technical["kg_coverage_target_met"] is None
    assert report["roles"]["source_navigation"]["kg_complete_material_rate"] is None
    assert report["roles"]["source_navigation"]["kg_coverage_target_met"] is None


def test_artifact_verification_checks_content_addressed_path_before_read_and_caches_digest(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir(mode=0o700)
    payload = b"private source bytes"
    digest = hashlib.sha256(payload).hexdigest()
    directory = root / digest[:2]
    directory.mkdir(mode=0o700)
    target = directory / digest
    target.write_bytes(payload)
    target.chmod(0o600)
    cache = {}

    verified = audit.verify_artifact_file(str(target), digest, root, cache)
    wrong_path = audit.verify_artifact_file(str(tmp_path / "other"), digest, root, cache)

    assert verified == {"status": "verified", "code": None, "size_bytes": len(payload), "cached": False}
    assert wrong_path["status"] == "error"
    assert wrong_path["code"] == "artifact_path_mismatch"
    assert audit.verify_artifact_file(str(target), digest, root, cache)["cached"] is True


def test_artifact_verification_rejects_symlink_at_expected_hash_path(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir(mode=0o700)
    external = tmp_path / "source"
    payload = b"private source bytes"
    external.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    directory = root / digest[:2]
    directory.mkdir(mode=0o700)
    target = directory / digest
    target.symlink_to(external)

    result = audit.verify_artifact_file(str(target), digest, root)

    assert result["status"] == "error"
    assert result["code"] == "artifact_file_untrusted"


def test_baseline_comparison_checks_existing_text_and_exact_chunk_identity_offsets():
    snapshot = _fixture_snapshot()
    material_id = snapshot["materials"][0]["id"]
    revision = snapshot["revisions"][0]
    chunk = snapshot["chunks"][0]
    baseline = [{
        "material": {"id": material_id},
        "text": revision["content"],
        "revision": {"sha256": revision["sha256"]},
        "chunks": [{key: chunk[key] for key in ("id", "text", "start", "end")}],
    }]

    matching = audit.compare_baseline_documents(baseline, snapshot["revisions"], snapshot["chunks"])
    baseline[0]["chunks"][0]["start"] = 1
    mismatching = audit.compare_baseline_documents(baseline, snapshot["revisions"], snapshot["chunks"])

    assert matching["matched_count"] == 1
    assert mismatching["mismatched_count"] == 1
    assert any(error["code"] == "baseline_chunk_mismatch" for error in mismatching["errors"])
