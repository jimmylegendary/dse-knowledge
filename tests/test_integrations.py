from __future__ import annotations

import json

import pytest

from dse_knowledge.config import Settings
from dse_knowledge.integrations import NativeIntegrations


def _minimal_twin() -> str:
    return json.dumps(
        {
            "level_id": "test-dram",
            "role": "dram",
            "capacity_bytes": 1_073_741_824,
            "bandwidth_bps": 1_000_000_000,
            "line_bytes": 64,
            "children": [{
                "level_id": "test-compute",
                "role": "compute",
                "peak_macs_per_s": 1_000_000_000,
                "children": [],
            }],
        }
    )


def test_hardware_validation_reports_schema_scope_without_claiming_physical_feasibility():
    result = NativeIntegrations(Settings({})).validate_hardware(_minimal_twin())

    assert result["status"] == "structurally_valid"
    assert result["validation_scope"] == "hat-schema-structural"
    assert result["physical_feasibility"] == "not_assessed"
    assert result["diagnostics"]["errors"] == 0


def test_hardware_validation_keeps_component_bundle_requirement_explicit():
    source = json.dumps({
        "schema_version": "hat-component/v1",
        "document_kind": "component",
        "component_id": "synthetic-test-component",
        "component_class": "compute_cluster",
        "resources": [],
        "instances": [],
        "ports": [],
        "links": [],
    })

    result = NativeIntegrations(Settings({})).validate_hardware(source)

    assert result["status"] == "requires_bundle"
    assert result["physical_feasibility"] == "not_assessed"


def test_melete_observe_returns_real_persistence_and_searchability_receipts(tmp_path):
    integration = NativeIntegrations(Settings({"DSE_DATA_ROOT": str(tmp_path)}))
    payload = {
        "event_id": "decision-event-001",
        "decision_id": "decision-001",
        "event_type": "decision",
        "text": "Choose the tiled kernel candidate after source review; validate memory traffic next.",
        "source_event_ids": ["source-revision-001"],
    }

    result = integration.observe(payload)

    # Melete 0.1 stores assistant notes as trace-only, not searchable memory.
    assert result["receipt"]["status"] == "trace_only"
    assert result["receipt"]["event_id"] == payload["event_id"]
    assert result["receipt"]["memory_ids"] == []
    assert result["searchability"]["status"] == "trace_only"
    assert payload["event_id"] in result["provenance"]["source_event_ids"]
    assert result["provenance"]["actor"] == "assistant"
    assert result["provenance"]["reference_status"] == "provided_references_unverified"
    assert result["dse_embedding_fallback"] is False

    for value in ("tool", [], None):
        invalid_actor = {
            **payload, "event_id": "decision-event-invalid-actor", "actor": value,
        }
        with pytest.raises(ValueError, match="actor"):
            integration.observe(invalid_actor)


def test_melete_observe_rejects_feedback_with_wrong_scope_before_claiming_linked(tmp_path):
    integration = NativeIntegrations(Settings({"DSE_DATA_ROOT": str(tmp_path)}))
    payload = {
        "event_id": "feedback-event-001",
        "decision_id": "decision-001",
        "event_type": "feedback",
        "text": "The evidence did not cover the target ISA revision.",
        "source_event_ids": ["source-revision-001"],
        "frame_feedback": {
            "feedback_id": "feedback-001",
            "frame_id": "frame-001",
            "task_id": "task-001",
            "scope": {"user_id": "different-user", "namespace": "dse_knowledge"},
            "criteria_applied": [],
            "assumptions_used": [],
            "evidence_refs": [],
            "disagreement_kind": "evidence_conflict",
            "objection": "wrong scope",
            "next_action": "recheck sources",
        },
    }

    with pytest.raises(ValueError, match="scope"):
        integration.observe(payload)

    payload["frame_feedback"]["scope"] = {
        "user_id": "dse-knowledge", "namespace": "dse_knowledge",
    }
    result = integration.observe(payload)
    assert result["provenance"]["actor"] == "user"
