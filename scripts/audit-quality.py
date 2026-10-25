#!/usr/bin/env python3
"""Owner-only metadata audit for canonical source and knowledge-quality records."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT / "src"))

from dse_knowledge.knowledge import SOURCE_ROLES, validate_claim_context


TECHNICAL_ROLES = ("core_technical", "supporting_method", "integration_operations")
REFERENCE_ROLES = ("source_navigation", "out_of_scope")
KNOWN_CATEGORIES = {
    "llm_model_workload", "dse_optimization", "hardware_architecture",
    "simulation_measurement", "compiler_kernel", "memory_interconnect",
    "serving_scheduling", "power_thermal_packaging", "provenance_experiment",
}
NORMALIZATION_STATUSES = {"normalized", "unresolved", "unit_unspecified", "not_numeric"}
MAX_ERROR_DETAILS = 50000
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_BASELINE_TOTAL_BYTES = 512 * 1024 * 1024
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
_SAFE_CODE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
_SAFE_MATERIAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _safe_code(value, fallback="audit_validation_error"):
    if isinstance(value, str) and _SAFE_CODE.fullmatch(value):
        return value
    return fallback


def _append_error(errors, *, entity_type, code, material_id=None, entity_id=None, annotation_id=None):
    error = {"entity_type": entity_type, "code": _safe_code(code)}
    if isinstance(material_id, str):
        error["material_id"] = material_id
    if isinstance(entity_id, str):
        error["entity_id"] = entity_id
    if isinstance(annotation_id, str):
        error["annotation_id"] = annotation_id
    errors.append(error)


def reconstruct_raw_context(stored_context):
    """Rebuild validator input only from persisted raw values and evidence."""
    if not isinstance(stored_context, dict):
        raise ValueError("annotation_context_invalid")

    def evidence_for(item):
        evidence = item.get("evidence") if isinstance(item, dict) else None
        if not isinstance(evidence, dict):
            raise ValueError("annotation_evidence_invalid")
        chunk_id, quote = evidence.get("chunk_id"), evidence.get("quote")
        if not isinstance(chunk_id, str) or not chunk_id or not isinstance(quote, str) or not quote:
            raise ValueError("annotation_evidence_invalid")
        return {"chunk_id": chunk_id, "quote": quote}

    parameters = stored_context.get("parameters")
    conditions = stored_context.get("conditions")
    if not isinstance(parameters, list) or not isinstance(conditions, list):
        raise ValueError("annotation_context_shape_invalid")
    raw_parameters = []
    for item in parameters:
        if not isinstance(item, dict):
            raise ValueError("annotation_parameter_invalid")
        raw_parameters.append({
            "name": item.get("name"),
            "value": item.get("value_raw"),
            "unit": item.get("unit_raw"),
            "evidence": evidence_for(item),
        })
    raw_conditions = []
    for item in conditions:
        if not isinstance(item, dict):
            raise ValueError("annotation_condition_invalid")
        raw_conditions.append({
            "dimension": item.get("dimension"),
            "operator": item.get("operator"),
            "value": item.get("value_raw"),
            "unit": item.get("unit_raw"),
            "evidence": evidence_for(item),
        })
    return {
        "schema_version": stored_context.get("schema_version"),
        "parameters": raw_parameters,
        "conditions": raw_conditions,
        "source_scope_note": stored_context.get("source_scope_note"),
    }


def _row_start(row):
    return row.get("start", row.get("start_offset"))


def _row_end(row):
    return row.get("end", row.get("end_offset"))


def _metadata(row):
    value = row.get("metadata")
    return value if isinstance(value, dict) else {}


def audit_claims(materials, revisions, chunks, claims):
    material_by_id = {row.get("id"): row for row in materials if isinstance(row.get("id"), str)}
    revision_by_id = {row.get("id"): row for row in revisions if isinstance(row.get("id"), str)}
    chunk_by_id = {row.get("id"): row for row in chunks if isinstance(row.get("id"), str)}
    valid_ids = set()
    errors = []
    for claim in claims:
        claim_id = claim.get("id")
        material_id = claim.get("material_id")
        reasons = []
        material = material_by_id.get(material_id)
        revision = revision_by_id.get(claim.get("revision_id"))
        chunk = chunk_by_id.get(claim.get("chunk_id"))
        if material is None:
            reasons.append("claim_material_missing")
        if revision is None:
            reasons.append("claim_revision_missing")
        elif revision.get("material_id") != material_id:
            reasons.append("claim_revision_material_mismatch")
        if chunk is None:
            reasons.append("claim_chunk_missing")
        elif chunk.get("material_id") != material_id or chunk.get("revision_id") != claim.get("revision_id"):
            reasons.append("claim_chunk_material_revision_mismatch")

        quote = claim.get("quote")
        if not isinstance(quote, str) or not quote:
            reasons.append("claim_quote_missing")
        elif revision is not None and chunk is not None:
            content = revision.get("content")
            stored_chunk_text = chunk.get("text")
            start, end = _row_start(chunk), _row_end(chunk)
            offsets_valid = (
                isinstance(content, str) and type(start) is int and type(end) is int
                and start >= 0 and end > start and end <= len(content)
            )
            chunk_text = stored_chunk_text if isinstance(stored_chunk_text, str) else (
                content[start:end] if offsets_valid and chunk.get("source_text_matches") is True else None
            )
            source_matches = (
                offsets_valid and chunk.get("source_text_matches") is not False and (
                    content[start:end] == stored_chunk_text
                    if isinstance(stored_chunk_text, str)
                    else chunk.get("source_text_matches") is True
                )
            )
            if not source_matches:
                reasons.append("claim_chunk_source_mismatch")
            meta = _metadata(claim)
            source_start, source_end = meta.get("source_start"), meta.get("source_end")
            if (type(source_start) is not int or type(source_end) is not int
                    or source_end - source_start != len(quote)
                    or type(start) is not int or type(end) is not int
                    or source_start < start or source_end > end
                    or not isinstance(chunk_text, str)
                    or chunk_text[source_start - start:source_end - start] != quote
                    or not isinstance(content, str)
                    or content[source_start:source_end] != quote):
                reasons.append("claim_source_offset_mismatch")

        if reasons:
            for reason in dict.fromkeys(reasons):
                _append_error(errors, entity_type="claim", code=reason, material_id=material_id,
                              entity_id=claim_id if isinstance(claim_id, str) else None)
        elif isinstance(claim_id, str):
            valid_ids.add(claim_id)
    return {"valid_ids": valid_ids, "errors": errors}


def _document_for_revision(material_id, revision, chunks):
    content = revision.get("content")
    normalized_chunks = []
    for row in chunks:
        start, end = _row_start(row), _row_end(row)
        chunk_text = row.get("text")
        if (not isinstance(chunk_text, str) and isinstance(content, str)
                and type(start) is int and type(end) is int
                and row.get("source_text_matches") is True):
            chunk_text = content[start:end]
        normalized_chunks.append({
            "id": row.get("id"), "material_id": row.get("material_id"),
            "revision_id": row.get("revision_id"), "revision_sha256": revision.get("sha256"),
            "text": chunk_text, "start": start, "end": end,
        })
    return {
        "material": {"id": material_id},
        "text": content,
        "revision": {"id": revision.get("id"), "sha256": revision.get("sha256")},
        "chunks": normalized_chunks,
    }


def _normalization_differences(stored, recalculated):
    return [] if stored == recalculated else ["canonical_context"]


def audit_annotations(materials, revisions, chunks, claims, annotations):
    material_ids = {row.get("id") for row in materials}
    revision_by_id = {row.get("id"): row for row in revisions if isinstance(row.get("id"), str)}
    claims_by_id = {row.get("id"): row for row in claims if isinstance(row.get("id"), str)}
    chunk_groups = defaultdict(list)
    for chunk in chunks:
        chunk_groups[(chunk.get("material_id"), chunk.get("revision_id"))].append(chunk)

    valid_latest = set()
    latest_by_key = {}
    valid_by_id = {}
    parameter_count = condition_count = norm_errors = valid_count = invalid_count = ignored_count = 0
    status_counts = Counter()
    errors = []

    def order_key(annotation):
        return (str(annotation.get("created_at") or ""), str(annotation.get("id") or ""))

    for annotation in annotations:
        annotation_id = annotation.get("id")
        claim_id = annotation.get("claim_id")
        version = annotation.get("version")
        if version != "claim-context/v1":
            ignored_count += 1
            continue
        claim = claims_by_id.get(claim_id)
        material_id = claim.get("material_id") if claim else None
        reasons = []
        if claim is None:
            reasons.append("annotation_claim_missing")
        if claim is not None and annotation.get("revision_id") != claim.get("revision_id"):
            reasons.append("annotation_revision_mismatch")
        if material_id not in material_ids:
            reasons.append("annotation_material_missing")
        revision = revision_by_id.get(annotation.get("revision_id"))
        if revision is None:
            reasons.append("annotation_revision_missing")
        elif material_id is not None and revision.get("material_id") != material_id:
            reasons.append("annotation_revision_material_mismatch")

        stored = annotation.get("context")
        try:
            raw = reconstruct_raw_context(stored)
            if revision is None or material_id is None:
                raise ValueError("annotation_canonical_revision_missing")
            document = _document_for_revision(material_id, revision, chunk_groups[(material_id, revision.get("id"))])
            recalculated = validate_claim_context(raw, document)
            differences = _normalization_differences(stored, recalculated)
            if differences:
                reasons.append("annotation_normalization_mismatch")
                norm_errors += 1
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            reason = str(exc) if exc.args else "annotation_validation_error"
            reasons.append(_safe_code(reason, "annotation_validation_error"))

        if isinstance(stored, dict):
            parameters = stored.get("parameters")
            conditions = stored.get("conditions")
            parameter_count += len(parameters) if isinstance(parameters, list) else 0
            condition_count += len(conditions) if isinstance(conditions, list) else 0
            for group in (parameters, conditions):
                if not isinstance(group, list):
                    continue
                for item in group:
                    normalized = item.get("normalized") if isinstance(item, dict) else None
                    status = normalized.get("status") if isinstance(normalized, dict) else None
                    if status in NORMALIZATION_STATUSES:
                        status_counts[status] += 1
                    else:
                        norm_errors += 1
                        reasons.append("annotation_normalization_status_invalid")

        valid = not reasons
        if valid:
            valid_count += 1
        else:
            invalid_count += 1
            for reason in dict.fromkeys(reasons):
                _append_error(errors, entity_type="annotation", code=reason, material_id=material_id,
                              entity_id=claim_id if isinstance(claim_id, str) else None,
                              annotation_id=annotation_id if isinstance(annotation_id, str) else None)
        key = (claim_id, annotation.get("revision_id"))
        old = latest_by_key.get(key)
        if old is None or order_key(annotation) > order_key(old):
            latest_by_key[key] = annotation
            valid_by_id[key] = valid

    for key, valid in valid_by_id.items():
        if valid:
            valid_latest.add(key)
    return {
        "valid_latest": valid_latest,
        "valid_count": valid_count,
        "invalid_count": invalid_count,
        "ignored_version_count": ignored_count,
        "parameter_count": parameter_count,
        "condition_count": condition_count,
        "normalization_status_counts": dict(sorted(status_counts.items())),
        "normalization_status_errors": norm_errors,
        "errors": errors,
    }


def _ratio(numerator, denominator):
    if denominator == 0:
        return None
    return numerator / denominator


def _current_revisions(revisions):
    current = {}
    for revision in revisions:
        material_id = revision.get("material_id")
        if not isinstance(material_id, str):
            continue
        candidate_key = (str(revision.get("created_at") or ""), str(revision.get("id") or ""))
        previous = current.get(material_id)
        if previous is None or candidate_key > previous[0]:
            current[material_id] = (candidate_key, revision)
    return {material_id: value[1] for material_id, value in current.items()}


def build_audit_report(snapshot, *, generated_at=None, baseline_report=None, artifact_report=None, code_tree_sha256=None):
    materials = snapshot.get("materials", [])
    revisions = snapshot.get("revisions", [])
    chunks = snapshot.get("chunks", [])
    claims = snapshot.get("claims", [])
    annotations = snapshot.get("annotations", [])
    edges = snapshot.get("edges", [])
    source_audit = audit_claims(materials, revisions, chunks, claims)
    annotation_audit = audit_annotations(materials, revisions, chunks, claims, annotations)
    valid_claim_ids = source_audit["valid_ids"]
    valid_annotation_keys = annotation_audit["valid_latest"]
    current_revisions = _current_revisions(revisions)
    claims_by_material = defaultdict(list)
    for claim in claims:
        claims_by_material[claim.get("material_id")].append(claim)
    by_role_materials = defaultdict(list)
    material_role_errors = []
    for material in materials:
        role = material.get("role") or "unclassified"
        if role not in SOURCE_ROLES:
            _append_error(material_role_errors, entity_type="material", code="material_role_unknown",
                          material_id=material.get("id"))
            role = "unclassified"
        by_role_materials[role].append(material)

    role_report = {}
    role_evidence_materials = {}
    role_fully_annotated = {}
    for role in SOURCE_ROLES:
        role_material_list = by_role_materials[role]
        role_claim_count = 0
        current_claim_count = 0
        source_valid_claim_count = 0
        evidence_material_count = 0
        current_claim_material_count = 0
        fully_annotated_count = 0
        for material in role_material_list:
            material_id = material.get("id")
            all_claims = claims_by_material.get(material_id, [])
            role_claim_count += len(all_claims)
            current_revision = current_revisions.get(material_id)
            revision_id = current_revision.get("id") if current_revision else None
            current_claims = [claim for claim in all_claims if claim.get("revision_id") == revision_id]
            current_claim_count += len(current_claims)
            valid_claims = [claim for claim in current_claims if claim.get("id") in valid_claim_ids]
            source_valid_claim_count += len(valid_claims)
            if current_claims:
                current_claim_material_count += 1
            if valid_claims:
                evidence_material_count += 1
            if role not in REFERENCE_ROLES and role != "unclassified" and current_claims and len(valid_claims) == len(current_claims):
                if all((claim.get("id"), revision_id) in valid_annotation_keys for claim in current_claims):
                    fully_annotated_count += 1
        denominator = len(role_material_list)
        role_evidence_materials[role] = evidence_material_count
        role_fully_annotated[role] = fully_annotated_count
        is_reference = role in REFERENCE_ROLES
        is_unknown = role == "unclassified"
        role_status = (
            "not_applicable" if is_reference else
            ("needs_review" if denominator else "not_evaluated") if is_unknown else
            "evaluated" if denominator else "not_evaluated"
        )
        coverage_rate = None if is_reference or is_unknown else _ratio(evidence_material_count, denominator)
        annotation_rate = None if is_reference or is_unknown else _ratio(fully_annotated_count, current_claim_material_count)
        role_report[role] = {
            "status": role_status,
            "kg_eligible": not is_reference and not is_unknown,
            "material_count": denominator,
            "claim_count_all_revisions": role_claim_count,
            "current_revision_claim_count": current_claim_count,
            "source_valid_current_claim_count": source_valid_claim_count,
            "materials_with_source_valid_claims": evidence_material_count,
            "current_claim_material_count": current_claim_material_count,
            "fully_annotated_material_count": fully_annotated_count,
            "claim_material_coverage_rate": coverage_rate,
            "fully_annotated_material_rate": annotation_rate,
            "kg_complete_count": 0 if is_reference or is_unknown else fully_annotated_count,
        }

    eligible_material_count = sum(len(by_role_materials[role]) for role in TECHNICAL_ROLES)
    eligible_evidence_material_count = sum(role_evidence_materials[role] for role in TECHNICAL_ROLES)
    eligible_claim_material_count = sum(
        role_report[role]["current_claim_material_count"] for role in TECHNICAL_ROLES
    )
    eligible_fully_annotated = sum(role_fully_annotated[role] for role in TECHNICAL_ROLES)
    eligible_claim_rate = _ratio(eligible_evidence_material_count, eligible_material_count)
    eligible_annotation_rate = _ratio(eligible_fully_annotated, eligible_claim_material_count)
    role_claim_complete = eligible_claim_rate is not None and eligible_claim_rate >= 0.90

    current_content_chars = sum(
        len(revision.get("content")) for revision in current_revisions.values()
        if isinstance(revision.get("content"), str)
    )
    all_revision_chars = sum(
        len(revision.get("content")) for revision in revisions if isinstance(revision.get("content"), str)
    )
    category_counts = Counter(
        category if category in KNOWN_CATEGORIES else "unknown"
        for category in (material.get("category") for material in materials)
    )
    dimension_counts = {
        str(row.get("dimension") if row.get("dimension") is not None else "unknown"): int(row.get("count") or 0)
        for row in snapshot.get("vector_dimension_counts", [])
    }
    vector_count = sum(dimension_counts.values())
    vector_768 = dimension_counts.get("768", 0)

    errors = source_audit["errors"] + annotation_audit["errors"] + material_role_errors
    if artifact_report:
        errors.extend(artifact_report.get("errors", []))
    if baseline_report:
        errors.extend(baseline_report.get("errors", []))
    visible_errors = errors[:MAX_ERROR_DETAILS]
    report = {
        "schema_version": "knowledge-quality-audit/v1",
        "status": "complete_with_findings" if errors else "complete",
        "generated_at": generated_at or dt.datetime.now(dt.timezone.utc).isoformat(),
        "code_tree_sha256": code_tree_sha256,
        "corpus": {
            "material_count": len(materials), "revision_count": len(revisions),
            "current_revision_characters": current_content_chars,
            "all_revision_characters": all_revision_chars,
            "chunk_count": len(chunks), "claim_count": len(claims),
            "annotation_count": len(annotations),
            "category_counts": dict(sorted(category_counts.items())),
        },
        "roles": role_report,
        "technical_eligible": {
            "roles": list(TECHNICAL_ROLES), "status": "evaluated" if eligible_material_count else "not_evaluated",
            "material_count": eligible_material_count,
            "materials_with_source_valid_claims": eligible_evidence_material_count,
            "current_claim_material_count": eligible_claim_material_count,
        "fully_annotated_material_count": eligible_fully_annotated,
            "claim_material_coverage_rate": eligible_claim_rate,
            "fully_annotated_material_rate": eligible_annotation_rate,
        "kg_complete_count": eligible_fully_annotated,
            "claim_coverage_threshold": 0.90,
            "claim_coverage_target_met": role_claim_complete if eligible_material_count else None,
        },
        "claims": {
            "count": len(claims), "valid_source_count": len(valid_claim_ids),
            "invalid_count": len(claims) - len(valid_claim_ids),
        },
        "annotations": {
            "count": len(annotations), "valid_count": annotation_audit["valid_count"],
            "invalid_count": annotation_audit["invalid_count"],
            "ignored_version_count": annotation_audit["ignored_version_count"],
            "parameter_count": annotation_audit["parameter_count"],
            "condition_count": annotation_audit["condition_count"],
            "normalization_status_counts": annotation_audit["normalization_status_counts"],
            "normalization_status_errors": annotation_audit["normalization_status_errors"],
        },
        "vectors": {
            "dimension_counts": dimension_counts, "count": vector_count,
            "chunk_count": len(chunks), "missing_vector_count": max(0, len(chunks) - vector_count),
            "dimension_768_count": vector_768,
            "dimension_mismatch_count": vector_count - vector_768,
        },
        "graph": graph_metrics(edges, snapshot.get("entity_ids", [])),
        "baseline_pilot": baseline_report or {"status": "not_evaluated", "material_count": 0,
                                               "matched_count": 0, "mismatched_count": 0,
                                               "match_rate": None, "errors": []},
        "artifacts": artifact_report or {"status": "not_requested", "revision_count": 0,
                                          "verified_revision_count": 0, "files_hashed": 0,
                                          "errors": []},
        "error_count": len(errors),
        "error_details_omitted": max(0, len(errors) - len(visible_errors)),
        "errors": visible_errors,
        "assurance_limit": "Deterministic source/shape/normalization audit only; it does not establish scientific entailment or applicability.",
    }
    return report


def graph_metrics(edges, entity_ids=()):
    adjacency = {entity_id: set() for entity_id in entity_ids if isinstance(entity_id, str)}
    node_materials = defaultdict(set)
    edge_kind_counts = Counter()
    invalid_edge_count = 0
    for edge in edges:
        relation_kind = edge.get("relation_kind") or "assertion"
        edge_kind_counts[str(relation_kind)] += 1
        source, target = edge.get("source"), edge.get("target")
        if not isinstance(source, str) or not source or not isinstance(target, str) or not target:
            invalid_edge_count += 1
            continue
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set()).add(source)
        material_id = edge.get("material_id")
        if isinstance(material_id, str):
            node_materials[source].add(material_id)
            node_materials[target].add(material_id)
    seen = set()
    components = []
    for root in sorted(adjacency):
        if root in seen:
            continue
        pending = [root]
        members = set()
        sources = set()
        seen.add(root)
        while pending:
            node = pending.pop()
            members.add(node)
            sources.update(node_materials[node])
            for neighbor in adjacency[node]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    pending.append(neighbor)
        components.append((len(members), len(sources)))
    largest = max(components, default=(0, 0), key=lambda x: (x[0], x[1]))
    multisource = [component for component in components if component[1] > 1]
    largest_multisource = max(multisource, default=(0, 0), key=lambda x: (x[0], x[1]))
    return {
        "node_count": len(adjacency), "edge_count": len(edges),
        "invalid_edge_count": invalid_edge_count, "component_count": len(components),
        "largest_component_node_count": largest[0], "largest_component_source_count": largest[1],
        "multisource_component_count": len(multisource),
        "largest_multisource_component_node_count": largest_multisource[0],
        "largest_multisource_component_source_count": largest_multisource[1],
        "edge_kind_counts": dict(sorted(edge_kind_counts.items())),
    }


def compare_baseline_documents(baseline_documents, revisions, chunks):
    revisions_by_key = {
        (row.get("material_id"), row.get("sha256")): row
        for row in revisions
    }
    chunks_by_revision = defaultdict(dict)
    for chunk in chunks:
        chunks_by_revision[chunk.get("revision_id")][chunk.get("id")] = chunk
    errors = []
    matched = mismatched = missing = 0
    for document in baseline_documents:
        material = document.get("material") if isinstance(document, dict) else None
        material_id = material.get("id") if isinstance(material, dict) else None
        revision_info = document.get("revision") if isinstance(document, dict) else None
        digest = revision_info.get("sha256") if isinstance(revision_info, dict) else None
        if not isinstance(material_id, str) or not isinstance(digest, str):
            mismatched += 1
            _append_error(errors, entity_type="baseline", code="baseline_document_invalid", material_id=material_id)
            continue
        revision = revisions_by_key.get((material_id, digest))
        if revision is None:
            missing += 1
            _append_error(errors, entity_type="baseline", code="baseline_revision_missing", material_id=material_id)
            continue
        document_errors = []
        if document.get("text") != revision.get("content"):
            document_errors.append(("baseline_text_mismatch", None))
        expected_chunks = document.get("chunks")
        if not isinstance(expected_chunks, list):
            document_errors.append(("baseline_chunks_invalid", None))
            expected_chunks = []
        db_chunks = chunks_by_revision[revision.get("id")]
        baseline_by_id = {}
        for item in expected_chunks:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                document_errors.append(("baseline_chunk_invalid", None))
                continue
            if item["id"] in baseline_by_id:
                document_errors.append(("baseline_chunk_duplicate", item["id"]))
            baseline_by_id[item["id"]] = item
        for chunk_id, item in baseline_by_id.items():
            db_chunk = db_chunks.get(chunk_id)
            db_text = db_chunk.get("text") if db_chunk else None
            if (db_chunk is not None and not isinstance(db_text, str)
                    and db_chunk.get("source_text_matches") is True
                    and isinstance(revision.get("content"), str)
                    and type(_row_start(db_chunk)) is int and type(_row_end(db_chunk)) is int):
                db_text = revision["content"][_row_start(db_chunk):_row_end(db_chunk)]
            if db_chunk is None or db_chunk.get("source_text_matches") is False or any((
                item.get("text") != db_text,
                item.get("start") != _row_start(db_chunk),
                item.get("end") != _row_end(db_chunk),
            )):
                document_errors.append(("baseline_chunk_mismatch", chunk_id))
        for chunk_id in set(db_chunks) - set(baseline_by_id):
            document_errors.append(("baseline_chunk_missing_from_prepared", chunk_id))
        if document_errors:
            mismatched += 1
            for code, chunk_id in document_errors:
                _append_error(errors, entity_type="baseline", code=code, material_id=material_id,
                              entity_id=chunk_id)
        else:
            matched += 1
    denominator = len(baseline_documents)
    return {
        "status": "evaluated" if denominator else "not_evaluated",
        "material_count": denominator, "matched_count": matched,
        "mismatched_count": mismatched, "missing_in_db_count": missing,
        "match_rate": _ratio(matched, denominator), "errors": errors,
    }


def _private_directory(path):
    path = Path(os.path.abspath(os.fspath(path)))
    try:
        info = os.lstat(path)
        if path.resolve(strict=True) != path:
            raise ValueError
    except (OSError, ValueError):
        raise ValueError("private_directory_untrusted") from None
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError("private_directory_untrusted")
    return path


def verify_artifact_file(stored_path, digest, artifact_root, cache=None):
    cache = cache if cache is not None else {}
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        return {"status": "error", "code": "artifact_digest_invalid", "size_bytes": None, "cached": False}
    root = Path(os.path.abspath(os.fspath(artifact_root)))
    expected = root / digest[:2] / digest
    try:
        candidate = Path(os.path.abspath(os.fspath(stored_path)))
    except (TypeError, ValueError, OSError):
        return {"status": "error", "code": "artifact_path_invalid", "size_bytes": None, "cached": False}
    if candidate != expected:
        return {"status": "error", "code": "artifact_path_mismatch", "size_bytes": None, "cached": False}
    if digest in cache:
        prior = cache[digest]
        return {**prior, "cached": True}
    try:
        _private_directory(root)
        _private_directory(expected.parent)
        initial = os.lstat(expected)
        if (not stat.S_ISREG(initial.st_mode) or initial.st_uid != os.getuid()
                or stat.S_IMODE(initial.st_mode) & 0o077 or initial.st_size > MAX_ARTIFACT_BYTES):
            raise ValueError("artifact_file_untrusted")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        fd = os.open(expected, flags)
        hasher = hashlib.sha256()
        try:
            opened = os.fstat(fd)
            if ((opened.st_dev, opened.st_ino) != (initial.st_dev, initial.st_ino)
                    or not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.getuid()
                    or stat.S_IMODE(opened.st_mode) & 0o077 or opened.st_size > MAX_ARTIFACT_BYTES):
                raise ValueError("artifact_file_untrusted")
            with os.fdopen(fd, "rb") as stream:
                fd = -1
                bytes_read = 0
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    hasher.update(block)
                    bytes_read += len(block)
                    if bytes_read > MAX_ARTIFACT_BYTES:
                        raise ValueError("artifact_too_large")
        finally:
            if fd >= 0:
                os.close(fd)
        if hasher.hexdigest() != digest:
            raise ValueError("artifact_hash_mismatch")
        result = {"status": "verified", "code": None, "size_bytes": int(initial.st_size), "cached": False}
    except (OSError, ValueError) as exc:
        code = _safe_code(str(exc), "artifact_unreadable")
        result = {"status": "error", "code": code, "size_bytes": None, "cached": False}
    cache[digest] = result
    return dict(result)


def _read_owner_json(path, *, max_bytes=MAX_JSON_BYTES):
    path = Path(path)
    try:
        initial = os.lstat(path)
    except OSError:
        raise ValueError("private_json_unreadable") from None
    if (not stat.S_ISREG(initial.st_mode) or initial.st_uid != os.getuid()
            or stat.S_IMODE(initial.st_mode) & 0o077 or initial.st_size > max_bytes):
        raise ValueError("private_json_untrusted")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            if ((opened.st_dev, opened.st_ino) != (initial.st_dev, initial.st_ino)
                    or not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.getuid()
                    or stat.S_IMODE(opened.st_mode) & 0o077 or opened.st_size > max_bytes):
                raise ValueError("private_json_untrusted")
            with os.fdopen(fd, "rb") as stream:
                fd = -1
                payload = stream.read(max_bytes + 1)
        finally:
            if fd >= 0:
                os.close(fd)
    except OSError:
        raise ValueError("private_json_unreadable") from None
    if len(payload) > max_bytes:
        raise ValueError("private_json_too_large")
    try:
        return json.loads(payload.decode("utf-8")), len(payload)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise ValueError("private_json_invalid") from None


def load_baseline_pilot(path):
    errors = []
    try:
        root = _private_directory(path)
        selected, selected_bytes = _read_owner_json(root / "selected.json")
        if not isinstance(selected, list) or len(selected) > 10000:
            raise ValueError("baseline_manifest_invalid")
        prepared_root = _private_directory(root / "prepared")
    except ValueError as exc:
        return [], {"status": "error", "material_count": 0, "loaded_count": 0,
                    "total_bytes": 0, "errors": [{"entity_type": "baseline", "code": _safe_code(str(exc))}]}
    documents = []
    total_bytes = selected_bytes
    for material_id in selected:
        if not isinstance(material_id, str) or not _SAFE_MATERIAL_ID.fullmatch(material_id):
            _append_error(errors, entity_type="baseline", code="baseline_material_id_invalid")
            continue
        path = prepared_root / f"{material_id}.json"
        try:
            document, size = _read_owner_json(path)
            total_bytes += size
            if total_bytes > MAX_BASELINE_TOTAL_BYTES:
                raise ValueError("baseline_total_too_large")
            if (not isinstance(document, dict) or not isinstance(document.get("material"), dict)
                    or document["material"].get("id") != material_id):
                raise ValueError("baseline_material_mismatch")
            documents.append(document)
        except ValueError as exc:
            _append_error(errors, entity_type="baseline", code=_safe_code(str(exc)), material_id=material_id)
    return documents, {
        "status": "loaded_with_findings" if errors else "loaded",
        "material_count": len(selected), "loaded_count": len(documents),
        "total_bytes": total_bytes, "errors": errors,
    }


def load_canonical_snapshot(store):
    with store.connection() as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")

        def rows(sql):
            return connection.execute(sql).fetchall()

        materials = rows(
            "SELECT id,category,status,scope,role FROM materials WHERE status='ingested' ORDER BY id"
        )
        revisions = rows(
            """SELECT r.id,r.material_id,r.sha256,r.content,r.artifact_path,r.scope,r.created_at
               FROM revisions r JOIN materials m ON m.id=r.material_id
               WHERE m.status='ingested' ORDER BY r.material_id,r.created_at,r.id"""
        )
        chunks = rows(
            """SELECT c.id,c.revision_id,c.material_id,c.start_offset AS start,c.end_offset AS end,
                      (c.text=substring(r.content FROM c.start_offset+1 FOR c.end_offset-c.start_offset)) AS source_text_matches
               FROM chunks c JOIN materials m ON m.id=c.material_id
               JOIN revisions r ON r.id=c.revision_id AND r.material_id=c.material_id
               WHERE m.status='ingested' ORDER BY c.material_id,c.revision_id,c.start_offset,c.id"""
        )
        claims = rows(
            """SELECT cl.id,cl.material_id,cl.revision_id,cl.chunk_id,cl.quote,cl.metadata
               FROM claims cl JOIN materials m ON m.id=cl.material_id
               WHERE m.status='ingested' ORDER BY cl.material_id,cl.revision_id,cl.id"""
        )
        annotations = rows(
            """SELECT a.id,a.claim_id,a.revision_id,a.version,a.context,a.created_at
               FROM claim_annotations a JOIN claims cl ON cl.id=a.claim_id
               JOIN materials m ON m.id=cl.material_id
               WHERE m.status='ingested' ORDER BY a.claim_id,a.revision_id,a.created_at,a.id"""
        )
        edges = rows("SELECT id,source,target,material_id,relation_kind FROM edges ORDER BY id")
        entity_ids = [row["id"] for row in rows("SELECT id FROM entities ORDER BY id")]
        vector_dimension_counts = rows(
            """SELECT vector_dims(c.embedding) AS dimension,count(*) AS count
               FROM chunks c JOIN materials m ON m.id=c.material_id WHERE m.status='ingested'
               GROUP BY vector_dims(c.embedding) ORDER BY dimension"""
        )
    return {
        "materials": materials, "revisions": revisions, "chunks": chunks, "claims": claims,
        "annotations": annotations, "edges": edges, "entity_ids": entity_ids,
        "vector_dimension_counts": vector_dimension_counts,
    }


def _code_tree_sha256(root=SCRIPT_ROOT):
    paths = sorted(Path(root, "src", "dse_knowledge").rglob("*.py"))
    paths.extend(sorted(Path(root, "migrations").glob("*.sql")))
    script = Path(root, "scripts", "audit-quality.py")
    if script.exists() and script not in paths:
        paths.append(script)
    hasher = hashlib.sha256()
    try:
        for path in sorted(paths):
            relative = path.relative_to(root).as_posix().encode("utf-8")
            hasher.update(relative + b"\0")
            file_hasher = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    file_hasher.update(block)
            hasher.update(file_hasher.digest())
        return hasher.hexdigest()
    except OSError:
        return None


def _artifact_audit(revisions, settings):
    cache = {}
    errors = []
    verified_count = 0
    for revision in revisions:
        result = verify_artifact_file(revision.get("artifact_path"), revision.get("sha256"), settings.artifact_root, cache)
        if result["status"] == "verified":
            verified_count += 1
        else:
            _append_error(errors, entity_type="revision", code=result["code"] or "artifact_unverified",
                          material_id=revision.get("material_id"), entity_id=revision.get("id"))
    return {
        "status": "evaluated" if revisions else "not_evaluated",
        "revision_count": len(revisions), "verified_revision_count": verified_count,
        "distinct_digest_count": len(cache),
        "files_hashed": sum(1 for value in cache.values() if value.get("status") == "verified"),
        "errors": errors,
    }


def run_audit(settings, *, baseline_path=None, verify_artifacts=False):
    from dse_knowledge.db import Store

    snapshot = load_canonical_snapshot(Store(settings))
    baseline_report = None
    baseline_documents = []
    if baseline_path is not None:
        baseline_documents, baseline_load = load_baseline_pilot(baseline_path)
        baseline_report = compare_baseline_documents(baseline_documents, snapshot["revisions"], snapshot["chunks"])
        baseline_report.update({"load_status": baseline_load["status"], "loaded_count": baseline_load["loaded_count"],
                                "total_bytes": baseline_load["total_bytes"], "errors": baseline_load["errors"] + baseline_report["errors"]})
    artifact_report = _artifact_audit(snapshot["revisions"], settings) if verify_artifacts else None
    return build_audit_report(
        snapshot, baseline_report=baseline_report, artifact_report=artifact_report,
        code_tree_sha256=_code_tree_sha256(),
    )


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="owner-only JSON report path (default: data_root/quality-audit.json)")
    baseline = parser.add_mutually_exclusive_group()
    baseline.add_argument("--baseline-pilot", type=Path, help="pilot100 prepared-cache directory")
    baseline.add_argument("--no-baseline-pilot", action="store_true", help="skip comparison with data_root/pilot100")
    parser.add_argument("--verify-artifacts", action="store_true", help="hash each distinct content-addressed source artifact once")
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    try:
        from dse_knowledge.config import Settings
        from dse_knowledge.pipeline import save_json
        settings = Settings.load()
        baseline_path = None if args.no_baseline_pilot else (args.baseline_pilot or settings.data_root / "pilot100")
        report = run_audit(settings, baseline_path=baseline_path, verify_artifacts=args.verify_artifacts)
        output = args.output or settings.data_root / "quality-audit.json"
        save_json(output, report, private=True)
    except Exception as exc:
        # The report can contain private source identifiers, so runtime failures stay generic here.
        print(json.dumps({"status": "failed", "code": "quality_audit_runtime_failed",
                          "error_type": type(exc).__name__}), file=sys.stderr)
        return 2
    print(json.dumps({"status": report["status"], "output": str(output),
                      "material_count": report["corpus"]["material_count"],
                      "claim_errors": report["claims"]["invalid_count"],
                      "annotation_errors": report["annotations"]["invalid_count"],
                      "error_count": report["error_count"]}, ensure_ascii=False))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
