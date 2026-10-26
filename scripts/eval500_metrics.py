"""Deterministic, offline metrics for the frozen retrieval eval500 contract."""
from __future__ import annotations

import hashlib
import math
import random
import re
from collections import Counter, defaultdict


POLICY_VERSION = "retrieval-policy/v2.2"
SCORE_NAME = "max_technical_rrf_proxy"
SUPPORTED = "supported"
INSUFFICIENT = "insufficient"
AMBIGUOUS = "ambiguous"

STAGE_COUNTS = {
    "calibration": {SUPPORTED: 60, INSUFFICIENT: 36, AMBIGUOUS: 4},
    "test": {SUPPORTED: 300, INSUFFICIENT: 180, AMBIGUOUS: 20},
}
STAGE_LANGUAGES = {"calibration": {"ko": 50, "en": 50}, "test": {"ko": 250, "en": 250}}
POSITIVE_TIER_COUNTS = {
    "calibration": {"d1_clear": 15, "d2_semantic": 15, "d3_implicit": 15, "d4_multiconstraint": 15},
    "test": {"d1_clear": 75, "d2_semantic": 75, "d3_implicit": 75, "d4_multiconstraint": 75},
}
POSITIVE_TIER_LANGUAGE_COUNTS = {
    "calibration": {
        "d1_clear": {"ko": 8, "en": 7}, "d2_semantic": {"ko": 7, "en": 8},
        "d3_implicit": {"ko": 8, "en": 7}, "d4_multiconstraint": {"ko": 7, "en": 8},
    },
    "test": {
        "d1_clear": {"ko": 38, "en": 37}, "d2_semantic": {"ko": 37, "en": 38},
        "d3_implicit": {"ko": 38, "en": 37}, "d4_multiconstraint": {"ko": 37, "en": 38},
    },
}
BOUNDARY_COUNTS = {
    "calibration": {
        "ood": 10, "wrong_revision": 6, "unseen_feature": 5, "missing_quantity": 4,
        "unsupported_derivation": 5, "in_domain_missing": 6, "underspecified": 4,
    },
    "test": {
        "ood": 50, "wrong_revision": 30, "unseen_feature": 25, "missing_quantity": 20,
        "unsupported_derivation": 25, "in_domain_missing": 30, "underspecified": 20,
    },
}
NEAR_BOUNDARY_TYPES = frozenset({"wrong_revision", "unseen_feature", "missing_quantity", "unsupported_derivation"})
ALLOWED_ACTIONS = frozenset({"answer", "qualified_answer", "abstain", "clarify"})
CASE_REQUIRED_FIELDS = frozenset({
    "id", "split", "language", "category", "difficulty", "intent_group", "query",
    "answerability", "expected_action", "boundary_type", "evidence_groups",
    "nearby_evidence", "gold_rationale", "missing_information",
})
EVIDENCE_LOCATOR_FIELDS = frozenset({"material_id", "revision_id", "chunk_id", "source_url", "text_sha256"})


class EvalContractError(ValueError):
    """The case manifest does not satisfy the frozen eval500 contract."""


class EvalScoreError(ValueError):
    """A score or response is missing or malformed; it must not be coerced to zero."""


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-fA-F0-9]{64}", value) is not None


def _validate_locator(locator: object, *, context: str) -> None:
    if not isinstance(locator, dict):
        raise EvalContractError(f"{context}: locator must be an object")
    for field in EVIDENCE_LOCATOR_FIELDS - {"text_sha256"}:
        if not _nonempty_string(locator.get(field)):
            raise EvalContractError(f"{context}: missing {field}")
    if not _valid_sha256(locator.get("text_sha256")):
        raise EvalContractError(f"{context}: invalid text_sha256")


def _validate_case(case: object, *, stage: str, seen_ids: set[str]) -> dict:
    if not isinstance(case, dict):
        raise EvalContractError("case must be an object")
    missing = sorted(CASE_REQUIRED_FIELDS - set(case))
    if missing:
        raise EvalContractError("case missing required fields")
    case_id = case.get("id")
    if not _nonempty_string(case_id) or case_id in seen_ids:
        raise EvalContractError("case ids must be unique nonempty strings")
    seen_ids.add(case_id)
    if case.get("split") != stage:
        raise EvalContractError("case split does not match stage")
    if case.get("language") not in {"ko", "en"}:
        raise EvalContractError("case language must be ko or en")
    if not _nonempty_string(case.get("category")):
        raise EvalContractError("case category is required")
    if not _nonempty_string(case.get("difficulty")):
        raise EvalContractError("case difficulty is required")
    if not _nonempty_string(case.get("intent_group")):
        raise EvalContractError("case intent_group is required")
    query = case.get("query")
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise EvalContractError("case query must be a nonempty string of at most 2000 characters")
    label = case.get("answerability")
    action = case.get("expected_action")
    if label not in {SUPPORTED, INSUFFICIENT, AMBIGUOUS}:
        raise EvalContractError("invalid answerability")
    if action not in ALLOWED_ACTIONS:
        raise EvalContractError("invalid expected_action")
    if label == SUPPORTED and action != "answer":
        raise EvalContractError("supported cases require expected_action=answer")
    if label == AMBIGUOUS and action != "clarify":
        raise EvalContractError("ambiguous cases require expected_action=clarify")
    if label == INSUFFICIENT and action not in {"qualified_answer", "abstain"}:
        raise EvalContractError("insufficient cases require qualified_answer or abstain")
    if not _nonempty_string(case.get("boundary_type")):
        raise EvalContractError("case boundary_type is required")
    if not isinstance(case.get("gold_rationale"), str):
        raise EvalContractError("case gold_rationale must be a string")
    missing_information = case.get("missing_information")
    if isinstance(missing_information, list):
        if any(not isinstance(item, str) for item in missing_information):
            raise EvalContractError("case missing_information must contain only strings")
    elif not isinstance(missing_information, str):
        raise EvalContractError("case missing_information must be a string or array of strings")

    groups = case.get("evidence_groups")
    if not isinstance(groups, list):
        raise EvalContractError("evidence_groups must be an array")
    if label == SUPPORTED and not groups:
        raise EvalContractError("supported cases require evidence_groups")
    group_ids = set()
    for group in groups:
        if not isinstance(group, dict) or not all(_nonempty_string(group.get(k)) for k in ("group_id", "requirement", "answer_fact")):
            raise EvalContractError("invalid evidence group")
        if group["group_id"] in group_ids:
            raise EvalContractError("duplicate evidence group id")
        group_ids.add(group["group_id"])
        alternatives = group.get("alternatives")
        if not isinstance(alternatives, list) or not alternatives:
            raise EvalContractError("evidence groups need at least one alternative")
        for locator in alternatives:
            _validate_locator(locator, context="alternative")

    nearby = case.get("nearby_evidence")
    if isinstance(nearby, dict):
        nearby = [nearby]
    if not isinstance(nearby, list):
        raise EvalContractError("nearby_evidence must be an array or locator object")
    for locator in nearby:
        _validate_locator(locator, context="nearby_evidence")
    return case


def validate_cases(cases: object, stage: str) -> dict:
    """Validate the exact 100/500 split distribution and case evidence contract."""
    if stage not in STAGE_COUNTS:
        raise EvalContractError("stage must be calibration or test")
    if not isinstance(cases, list):
        raise EvalContractError("cases must be a JSONL-derived array")
    seen_ids: set[str] = set()
    validated = [_validate_case(case, stage=stage, seen_ids=seen_ids) for case in cases]
    counts = Counter(case["answerability"] for case in validated)
    if dict(counts) != STAGE_COUNTS[stage]:
        raise EvalContractError("case answerability distribution mismatch")
    languages = Counter(case["language"] for case in validated)
    if dict(languages) != STAGE_LANGUAGES[stage]:
        raise EvalContractError("case language distribution mismatch")
    positive_tiers = Counter(case["difficulty"] for case in validated if case["answerability"] == SUPPORTED)
    if dict(positive_tiers) != POSITIVE_TIER_COUNTS[stage]:
        raise EvalContractError("supported difficulty tier distribution mismatch")
    positive_tier_languages = defaultdict(Counter)
    for case in validated:
        if case["answerability"] == SUPPORTED:
            positive_tier_languages[case["difficulty"]][case["language"]] += 1
    positive_tier_languages = {
        tier: dict(positive_tier_languages[tier])
        for tier in POSITIVE_TIER_COUNTS[stage]
    }
    if positive_tier_languages != POSITIVE_TIER_LANGUAGE_COUNTS[stage]:
        raise EvalContractError("supported tier-language distribution mismatch")
    boundaries = Counter(case["boundary_type"] for case in validated if case["answerability"] != SUPPORTED)
    if dict(boundaries) != BOUNDARY_COUNTS[stage]:
        raise EvalContractError("negative boundary distribution mismatch")
    if any(case["answerability"] == AMBIGUOUS and case["boundary_type"] != "underspecified" for case in validated):
        raise EvalContractError("ambiguous cases must use the underspecified boundary type")
    if any(case["answerability"] != AMBIGUOUS and case["boundary_type"] == "underspecified" for case in validated):
        raise EvalContractError("underspecified cases must be ambiguous")
    return {
        "count": len(validated),
        "counts": dict(counts),
        "languages": dict(languages),
        "categories": dict(Counter(case["category"] for case in validated)),
        "difficulty": dict(Counter(case["difficulty"] for case in validated)),
        "positive_tiers": dict(positive_tiers),
        "positive_tier_languages": positive_tier_languages,
        "boundary_types": dict(boundaries),
        "intent_group_count": len({case["intent_group"] for case in validated}),
        "source_material_count": len(_case_material_ids(validated)),
    }


def validate_split_isolation(calibration_cases: list[dict], test_cases: list[dict]) -> dict:
    calibration_groups = {case["intent_group"] for case in calibration_cases}
    test_groups = {case["intent_group"] for case in test_cases}
    if calibration_groups & test_groups:
        raise EvalContractError("calibration/test intent_group overlap")
    calibration_case_ids = {case["id"] for case in calibration_cases}
    test_case_ids = {case["id"] for case in test_cases}
    if calibration_case_ids & test_case_ids:
        raise EvalContractError("calibration/test case id overlap")
    calibration_materials = _case_material_ids(calibration_cases)
    test_materials = _case_material_ids(test_cases)
    if calibration_materials & test_materials:
        raise EvalContractError("calibration/test source material overlap")
    return {
        "calibration_intent_group_count": len(calibration_groups),
        "test_intent_group_count": len(test_groups),
        "intent_overlap_count": 0,
        "calibration_case_id_count": len(calibration_case_ids),
        "test_case_id_count": len(test_case_ids),
        "case_id_overlap_count": 0,
        "calibration_source_material_count": len(calibration_materials),
        "test_source_material_count": len(test_materials),
        "source_material_overlap_count": 0,
    }


def intent_group_hashes(cases: list[dict]) -> list[str]:
    return sorted({hashlib.sha256(case["intent_group"].encode("utf-8")).hexdigest() for case in cases})


def case_id_hashes(cases: list[dict]) -> list[str]:
    return sorted(hashlib.sha256(case["id"].encode("utf-8")).hexdigest() for case in cases)


def _case_material_ids(cases: list[dict]) -> set[str]:
    ids = set()
    for case in cases:
        for group in case.get("evidence_groups", []):
            for alternative in group.get("alternatives", []):
                if isinstance(alternative.get("material_id"), str):
                    ids.add(alternative["material_id"])
        nearby = case.get("nearby_evidence", [])
        if isinstance(nearby, dict):
            nearby = [nearby]
        if isinstance(nearby, list):
            for locator in nearby:
                if isinstance(locator, dict) and isinstance(locator.get("material_id"), str):
                    ids.add(locator["material_id"])
    return ids


def source_material_hashes(cases: list[dict]) -> list[str]:
    return sorted(hashlib.sha256(material_id.encode("utf-8")).hexdigest() for material_id in _case_material_ids(cases))


def primary_score(search_result: object) -> float:
    """Return max finite item.trace.rank_score, with the contract's empty/error distinction."""
    if not isinstance(search_result, dict):
        raise EvalScoreError("search result must be an object")
    items = search_result.get("items")
    if not isinstance(items, list):
        raise EvalScoreError("search result items must be an array")
    if not items:
        return 0.0
    scores = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("trace"), dict):
            raise EvalScoreError("nonempty items must have trace.rank_score")
        value = item["trace"].get("rank_score")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise EvalScoreError("rank_score must be finite and nonnegative")
        scores.append(float(value))
    return max(scores)


def _finite_scalar(value: object, *, field: str):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise EvalScoreError(f"{field} must be a finite number")
    return value


def _copy_if_type(source: dict, key: str, target: dict, *, types: tuple[type, ...], required: bool = False) -> None:
    if key not in source:
        if required:
            raise EvalScoreError(f"missing metadata field {key}")
        return
    value = source[key]
    if bool not in types and isinstance(value, bool):
        raise EvalScoreError(f"invalid metadata field {key}")
    if not isinstance(value, types):
        raise EvalScoreError(f"invalid metadata field {key}")
    if isinstance(value, float) and not math.isfinite(value):
        raise EvalScoreError(f"nonfinite metadata field {key}")
    target[key] = value


def _project_item(item: object, *, slot: int) -> dict:
    if not isinstance(item, dict):
        raise EvalScoreError("result item must be an object")
    output = {"slot": slot}
    for key in ("chunk_id", "material_id", "revision_id", "result_kind", "role"):
        _copy_if_type(item, key, output, types=(str,), required=True)
    if "category" in item:
        _copy_if_type(item, "category", output, types=(str,))
    output["rank"] = _finite_scalar(item.get("rank"), field="rank")
    scores = item.get("scores")
    if not isinstance(scores, dict):
        raise EvalScoreError("scores must be an object")
    output["scores"] = {str(k): _finite_scalar(v, field=f"scores.{k}") for k, v in scores.items() if k in {"dense", "lexical", "exact", "graph"}}
    role_policy = item.get("role_policy")
    if isinstance(role_policy, dict):
        allowed_policy = ("role", "purpose", "weight", "needs_review", "is_locator", "evidence_authority", "evidence_ceiling", "use_ceiling", "auto_uncertain", "policy_version")
        policy = {}
        for key in allowed_policy:
            if key not in role_policy:
                continue
            value = role_policy[key]
            if isinstance(value, float) and not math.isfinite(value):
                raise EvalScoreError(f"nonfinite role_policy.{key}")
            if isinstance(value, (str, int, float, bool)) or value is None:
                policy[key] = value
        output["role_policy"] = policy
    trace = item.get("trace")
    if not isinstance(trace, dict):
        raise EvalScoreError("trace must be an object")
    if "rank_score" not in trace:
        raise EvalScoreError("trace.rank_score is required")
    numeric = ("role_weight", "query_relevance", "graph_rank", "graph_boost", "graph_topic_idf", "graph_proof_count", "graph_discarded_link_count", "rank_score", "dense_scope_count", "dense_scope_cap", "dense_candidate_limit", "graph_candidate_limit")
    booleans = ("query_embedding_cache_hit", "purpose_uncertain", "graph_truncated")
    strings = ("purpose_rule", "query_embedding_task", "dense_candidate_method", "dense_candidate_policy_version")
    projected_trace = {}
    for key in numeric:
        if key in trace:
            # A result without a graph-derived rank carries null. Preserve
            # that optional-channel state; it is distinct from rank_score,
            # which remains required and finite.
            if key == "graph_rank" and trace[key] is None:
                projected_trace[key] = None
                continue
            projected_trace[key] = _finite_scalar(trace[key], field=f"trace.{key}")
    for key in booleans:
        if key in trace:
            _copy_if_type(trace, key, projected_trace, types=(bool,))
    for key in strings:
        if key in trace:
            _copy_if_type(trace, key, projected_trace, types=(str,))
    channel_ranks = trace.get("channel_ranks")
    if isinstance(channel_ranks, dict):
        projected_trace["channel_ranks"] = {
            channel: rank for channel, rank in channel_ranks.items()
            if channel in {"dense", "lexical", "exact", "graph"}
            and isinstance(rank, int) and not isinstance(rank, bool)
        }
    anchors = trace.get("semantic_anchors")
    if isinstance(anchors, dict):
        anchor_fields = ("material_id", "chunk_id", "original_dense_rank", "original_hybrid_position", "promoted", "selection_basis", "authority_changed")
        projected_anchors = {}
        for stream, anchor in anchors.items():
            if stream not in {"items", "source_results"} or not isinstance(anchor, dict):
                continue
            projected_anchors[stream] = {key: anchor[key] for key in anchor_fields if key in anchor and isinstance(anchor[key], (str, int, bool))}
        if projected_anchors:
            projected_trace["semantic_anchors"] = projected_anchors
    output["trace"] = projected_trace
    return output


def project_search_result(search_result: object, *, limit: int = 12) -> dict:
    """Allowlist API result metadata; raw chunk text, URLs, answers, and vectors never pass through."""
    if not isinstance(search_result, dict):
        raise EvalScoreError("search result must be an object")
    if search_result.get("policy_version") != POLICY_VERSION:
        raise EvalScoreError("retrieval policy version mismatch")
    projected = {
        "policy_version": POLICY_VERSION,
        "actual_confidence": "not_provided",
        "actual_action": "not_evaluated",
        "actual_abstention": "not_evaluated",
        "threshold_is_proxy_only": True,
    }
    for key in ("purpose", "trace_id"):
        if key in search_result and isinstance(search_result[key], str):
            projected[key] = search_result[key]
    purpose_trace = search_result.get("purpose_trace")
    if isinstance(purpose_trace, dict):
        allowed = ("requested", "resolved", "rule", "uncertain", "version")
        projected["purpose_trace"] = {key: purpose_trace[key] for key in allowed if isinstance(purpose_trace.get(key), (str, bool))}
    for field in ("items", "source_results", "locators"):
        rows = search_result.get(field)
        if not isinstance(rows, list):
            raise EvalScoreError(f"search result {field} must be an array")
        projected[field] = [_project_item(item, slot=i + 1) for i, item in enumerate(rows[:limit])]
    semantic_anchors = search_result.get("semantic_anchors")
    if isinstance(semantic_anchors, dict):
        fields = ("material_id", "chunk_id", "original_dense_rank", "original_hybrid_position", "promoted", "selection_basis", "authority_changed")
        projected["semantic_anchors"] = {stream: {k: v[k] for k in fields if isinstance(v, dict) and k in v and isinstance(v[k], (str, int, bool))} for stream, v in semantic_anchors.items() if stream in {"items", "source_results"}}
    for source, target, keys in (
        ("dense_candidate_trace", "dense_candidate_trace", ("method", "scope_count", "scope_cap", "candidate_limit", "policy_version")),
        ("graph_trace", "graph_trace", ("candidate_limit", "fetch_limit", "fetched_unique_candidates", "returned_candidates", "truncated")),
    ):
        value = search_result.get(source)
        if isinstance(value, dict):
            projected[target] = {key: value[key] for key in keys if key in value and isinstance(value[key], (str, int, bool))}
    channels = search_result.get("channels")
    if isinstance(channels, dict):
        projected["channels"] = {str(k): v for k, v in channels.items() if k in {"dense", "lexical", "exact", "graph"} and isinstance(v, int) and not isinstance(v, bool)}
    for key in ("graph_truncated", "query_embedding_cache_hit"):
        if key in search_result and isinstance(search_result[key], bool):
            projected[key] = search_result[key]
    return projected


def _alternative_matches(candidate: dict, alternative: dict, *, chunk: bool) -> bool:
    if candidate.get("material_id") != alternative.get("material_id") or candidate.get("revision_id") != alternative.get("revision_id"):
        return False
    return not chunk or candidate.get("chunk_id") == alternative.get("chunk_id")


def ranking_metrics(case: dict, search_result: dict, *, stream: str, limit: int = 12) -> dict:
    if case.get("answerability") != SUPPORTED:
        raise EvalContractError("ranking metrics are defined for supported cases only")
    if stream not in {"items", "source_results"}:
        raise ValueError("unsupported result stream")
    groups = case.get("evidence_groups")
    if not isinstance(groups, list) or not groups:
        raise EvalContractError("supported ranking case lacks evidence groups")
    rows = search_result.get(stream, []) if isinstance(search_result, dict) else []
    rows = rows[:limit] if isinstance(rows, list) else []

    def hit(candidate: dict, group: dict, *, chunk: bool) -> bool:
        return any(_alternative_matches(candidate, alternative, chunk=chunk) for alternative in group["alternatives"])

    output = {}
    for k in (1, 5, 10):
        head = rows[:k]
        for level, chunk in (("source", False), ("chunk", True)):
            group_hits = [any(hit(candidate, group, chunk=chunk) for candidate in head if isinstance(candidate, dict)) for group in groups]
            output[f"{level}_any_hit_at_{k}"] = int(any(group_hits))
            output[f"{level}_all_groups_hit_at_{k}"] = int(all(group_hits))
    for level, chunk in (("source", False), ("chunk", True)):
        hit_positions = [
            index for index, candidate in enumerate(rows, 1)
            if isinstance(candidate, dict) and any(hit(candidate, group, chunk=chunk) for group in groups)
        ]
        first = hit_positions[0] if hit_positions else None
        for k in (5, 10):
            output[f"{level}_mrr_at_{k}"] = 1.0 / first if first is not None and first <= k else 0.0
    return output


def _binary_records(records: list[dict]) -> list[dict]:
    return [record for record in records if record.get("answerability") in {SUPPORTED, INSUFFICIENT} and record.get("score") is not None]


def roc_auc(records: list[dict]) -> float | None:
    rows = _binary_records(records)
    positives = sum(row["answerability"] == SUPPORTED for row in rows)
    negatives = sum(row["answerability"] == INSUFFICIENT for row in rows)
    if not positives or not negatives:
        return None
    ordered = sorted(rows, key=lambda row: row["score"])
    concordant = 0.0
    negatives_below = 0
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end]["score"] == ordered[index]["score"]:
            end += 1
        group = ordered[index:end]
        group_pos = sum(row["answerability"] == SUPPORTED for row in group)
        group_neg = len(group) - group_pos
        concordant += group_pos * (negatives_below + 0.5 * group_neg)
        negatives_below += group_neg
        index = end
    return concordant / (positives * negatives)


def average_precision(records: list[dict]) -> float | None:
    rows = _binary_records(records)
    positives = sum(row["answerability"] == SUPPORTED for row in rows)
    if not positives or not any(row["answerability"] == INSUFFICIENT for row in rows):
        return None
    ordered = sorted(rows, key=lambda row: row["score"], reverse=True)
    true_positives = false_positives = 0
    previous_recall = 0.0
    average_precision = 0.0
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end]["score"] == ordered[index]["score"]:
            end += 1
        group = ordered[index:end]
        true_positives += sum(row["answerability"] == SUPPORTED for row in group)
        false_positives += sum(row["answerability"] == INSUFFICIENT for row in group)
        recall = true_positives / positives
        precision = true_positives / (true_positives + false_positives)
        average_precision += (recall - previous_recall) * precision
        previous_recall = recall
        index = end
    return average_precision


def select_threshold(records: list[dict], *, target_tpr: float = 0.90) -> dict:
    if not 0 < target_tpr <= 1:
        raise ValueError("target_tpr must be in (0, 1]")
    rows = _binary_records(records)
    positives = [row for row in rows if row["answerability"] == SUPPORTED]
    if not positives:
        raise EvalScoreError("calibration has no scored supported cases")
    thresholds = sorted({float(row["score"]) for row in rows}, reverse=True)
    chosen = None
    for threshold in thresholds:
        tpr = sum(row["score"] >= threshold for row in positives) / len(positives)
        if tpr >= target_tpr:
            chosen = {"threshold": threshold, "supported_tpr": tpr, "target_tpr": target_tpr, "comparison": ">="}
            break
    if chosen is None:
        raise EvalScoreError("no calibration threshold meets target supported TPR")
    return chosen


def confusion_metrics(records: list[dict], threshold: float) -> dict:
    rows = _binary_records(records)
    tp = fp = tn = fn = 0
    for row in rows:
        predicted = row["score"] >= threshold
        actual = row["answerability"] == SUPPORTED
        if predicted and actual:
            tp += 1
        elif predicted and not actual:
            fp += 1
        elif not predicted and actual:
            fn += 1
        else:
            tn += 1
    precision_denominator = tp + fp
    positive_denominator = tp + fn
    negative_denominator = tn + fp
    return {
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "scored_denominator": len(rows),
        "precision": tp / precision_denominator if precision_denominator else None,
        "supported_tpr": tp / positive_denominator if positive_denominator else None,
        "specificity": tn / negative_denominator if negative_denominator else None,
        "fpr": fp / negative_denominator if negative_denominator else None,
    }


def challenge_false_positive_rates(records: list[dict], threshold: float) -> dict:
    insufficient = [row for row in records if row.get("answerability") == INSUFFICIENT and row.get("score") is not None]
    ood = [row for row in insufficient if row.get("boundary_type") == "ood"]
    near = [row for row in insufficient if row.get("boundary_type") in NEAR_BOUNDARY_TYPES]
    in_domain_missing = [row for row in insufficient if row.get("boundary_type") == "in_domain_missing"]
    ambiguous = [row for row in records if row.get("answerability") == AMBIGUOUS and row.get("score") is not None]

    def rate(rows):
        return sum(row["score"] >= threshold for row in rows) / len(rows) if rows else None

    return {
        "ood_fpr": rate(ood), "ood_denominator": len(ood),
        "near_boundary_fpr": rate(near), "near_boundary_denominator": len(near),
        "in_domain_missing_fpr": rate(in_domain_missing),
        "in_domain_missing_denominator": len(in_domain_missing),
        "ambiguous_predicted_supported_rate": rate(ambiguous), "ambiguous_denominator": len(ambiguous),
    }


def quality_gates(classification: dict, challenge: dict) -> dict:
    tpr = classification.get("supported_tpr")
    ood_fpr = challenge.get("ood_fpr")
    near_fpr = challenge.get("near_boundary_fpr")
    checks = {
        "supported_tpr": tpr is not None and tpr >= 0.90,
        "ood_fpr": ood_fpr is not None and ood_fpr <= 0.10,
        "near_boundary_fpr": near_fpr is not None and near_fpr <= 0.20,
    }
    return {"targets": {"supported_tpr_min": 0.90, "ood_fpr_max": 0.10, "near_boundary_fpr_max": 0.20}, "checks": checks, "passed": all(checks.values())}


def aggregate_ranking(cases: list[dict], results_by_id: dict[str, dict], *, stream: str, limit: int = 12) -> dict:
    supported = [case for case in cases if case["answerability"] == SUPPORTED]
    metrics_by_case = []
    for case in supported:
        result = results_by_id.get(case["id"], {})
        metrics_by_case.append(ranking_metrics(case, result, stream=stream, limit=limit))
    names = sorted({name for row in metrics_by_case for name in row})
    return {
        "denominator": len(supported),
        "metrics": {name: sum(row[name] for row in metrics_by_case) / len(supported) if supported else None for name in names},
    }


def _percentile(sorted_values: list[float], fraction: float) -> float | None:
    if not sorted_values:
        return None
    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    portion = position - lower
    return sorted_values[lower] * (1 - portion) + sorted_values[upper] * portion


def intent_cluster_bootstrap(records: list[dict], *, replicates: int = 1000, seed: int = 500,
                             source_material_count: int | None = None) -> dict:
    if replicates < 1:
        raise ValueError("replicates must be positive")
    if source_material_count is not None and source_material_count < 0:
        raise ValueError("source_material_count must be nonnegative")
    groups = defaultdict(list)
    for record in records:
        group = record.get("intent_group")
        if isinstance(group, str) and record.get("answerability") in {SUPPORTED, INSUFFICIENT} and record.get("score") is not None:
            groups[group].append(record)
    group_names = sorted(groups)
    if not group_names:
        return {
            "seed": seed, "replicates_requested": replicates, "valid_replicates": 0,
            "intent_group_count": 0, "source_material_group_count": source_material_count,
            "ci_grouping": "intent_group_only", "does_not_cover_source_correlations": True,
            "intervals": {},
        }
    rng = random.Random(seed)
    metric_samples = {"roc_auc": [], "average_precision": []}
    valid_replicates = 0
    for _ in range(replicates):
        sampled = []
        for _draw in range(len(group_names)):
            sampled.extend(groups[rng.choice(group_names)])
        auc = roc_auc(sampled)
        ap = average_precision(sampled)
        if auc is None or ap is None:
            continue
        valid_replicates += 1
        metric_samples["roc_auc"].append(auc)
        metric_samples["average_precision"].append(ap)
    intervals = {}
    for name, values in metric_samples.items():
        values.sort()
        intervals[name] = {"lower_95": _percentile(values, 0.025), "upper_95": _percentile(values, 0.975)}
    return {
        "seed": seed, "replicates_requested": replicates, "valid_replicates": valid_replicates,
        "skipped_replicates": replicates - valid_replicates, "intent_group_count": len(group_names),
        "source_material_group_count": source_material_count,
        "ci_grouping": "intent_group_only", "does_not_cover_source_correlations": True,
        "intervals": intervals,
    }
