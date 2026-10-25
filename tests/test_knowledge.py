import math

import pytest
from jsonschema import Draft202012Validator

from dse_knowledge.knowledge import (
    CONTEXT_SCHEMA,
    ROLE_SCHEMA,
    SOURCE_ROLES,
    canonical_topic_mentions,
    validate_claim_context,
    validate_role_assessment,
)


def prepared_document(text):
    return {
        "material": {"id": "mat-test", "title": "Synthetic DSE source"},
        "text": text,
        "revision": {"sha256": "a" * 64, "scope": "public_fulltext"},
        "chunks": [{"id": "chunk-test", "text": text, "start": 0, "end": len(text)}],
    }


def parameter(name, value, unit, quote):
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "evidence": {"chunk_id": "chunk-test", "quote": quote},
    }


def context(*, parameters=(), conditions=(), source_scope_note="The quoted configuration only."):
    return {
        "schema_version": "claim-context/v1",
        "parameters": list(parameters),
        "conditions": list(conditions),
        "source_scope_note": source_scope_note,
    }


def test_role_assessment_marks_unclassified_for_review_without_granting_authority():
    result = validate_role_assessment({
        "role": "unclassified",
        "confidence": 0.2,
        "rationale": "The title and excerpt do not establish a DSE role.",
    })

    assert result["role"] == "unclassified"
    assert result["status"] == "needs_review"
    assert result["authority"] == "curator_annotation"


def test_role_assessment_rejects_unknown_role_and_extra_authority_claims():
    with pytest.raises(ValueError, match="role_assessment_invalid"):
        validate_role_assessment({
            "role": "physical_authority",
            "confidence": 1.0,
            "rationale": "unsupported",
        })

    with pytest.raises(ValueError, match="role_assessment_invalid"):
        validate_role_assessment({
            "role": "core_technical",
            "confidence": 1.0,
            "rationale": "A role label does not certify scientific correctness.",
            "certifies_physics": True,
        })


def test_context_preserves_raw_literal_and_records_multiplicative_normalization():
    quote = "On V100, request latency was 6.4 ms per request."
    doc = prepared_document(quote)
    raw = context(parameters=[parameter("request latency", 6.4, "ms", quote)])

    result = validate_claim_context(raw, doc)
    item = result["parameters"][0]

    assert item["value_raw"] == 6.4
    assert item["unit_raw"] == "ms"
    assert item["normalized"] == {"value": 0.0064, "unit": "s", "status": "normalized"}
    assert item["evidence"] == {
        "chunk_id": "chunk-test",
        "material_id": "mat-test",
        "quote": quote,
        "source_start": 0,
        "source_end": len(quote),
        "revision_sha256": "a" * 64,
    }
    assert result["use_policy"] == "source_assertion_only"
    assert result["validation"] == "literal_grounded_unverified_association"
    assert result["independent_validations"] == 0


@pytest.mark.parametrize(
    ("raw_value", "raw_unit", "expected_value", "expected_unit"),
    [
        (2, "kW", 2000.0, "W"),
        (4, "mJ", 0.004, "J"),
        (2, "KiB", 2048.0, "B"),
        (2, "KB", 2000.0, "B"),
        (2, "MiB", 2097152.0, "B"),
        (2, "GB", 2000000000.0, "B"),
        (2, "GiB", 2147483648.0, "B"),
        (8, "tokens/s", 8.0, "token/s"),
        (8, "token/s", 8.0, "token/s"),
        (8, "req/s", 8.0, "req/s"),
        (25, "%", 25.0, "%"),
    ],
)
def test_context_normalizes_only_curated_multiplicative_units(
    raw_value, raw_unit, expected_value, expected_unit
):
    quote = f"The measured value is {raw_value} {raw_unit}."
    raw = context(parameters=[parameter("measured value", raw_value, raw_unit, quote)])

    result = validate_claim_context(raw, prepared_document(quote))

    assert result["parameters"][0]["value_raw"] == raw_value
    assert result["parameters"][0]["unit_raw"] == raw_unit
    assert result["parameters"][0]["normalized"] == {
        "value": expected_value,
        "unit": expected_unit,
        "status": "normalized",
    }


def test_context_accepts_numeric_values_with_adjacent_unit_symbols():
    quote = "Latency was 6.4ms and the target utilization was 25%."
    raw = context(parameters=[
        parameter("latency", 6.4, "ms", "6.4ms"),
        parameter("utilization", 25, "%", "25%"),
    ])

    result = validate_claim_context(raw, prepared_document(quote))

    assert [item["normalized"] for item in result["parameters"]] == [
        {"value": 0.0064, "unit": "s", "status": "normalized"},
        {"value": 25, "unit": "%", "status": "normalized"},
    ]


def test_context_marks_unknown_units_and_offset_temperatures_unresolved():
    quote = "The value is 20 furlongs and 35 C in the source configuration."
    raw = context(parameters=[
        parameter("distance", 20, "furlongs", quote),
        parameter("temperature", 35, "C", quote),
    ])

    result = validate_claim_context(raw, prepared_document(quote))

    assert [item["normalized"]["status"] for item in result["parameters"]] == [
        "unresolved",
        "unresolved",
    ]
    assert [item["normalized"]["value"] for item in result["parameters"]] == [None, None]


def test_context_does_not_infer_a_missing_unit_or_treat_text_as_numeric():
    quote = "The source names V100 and reports a value of 12; true is enabled."
    raw = context(parameters=[
        parameter("unitted value", 12, None, "reports a value of 12"),
        parameter("hardware", "V100", None, "names V100"),
        parameter("enabled", True, None, "true is enabled"),
    ])

    result = validate_claim_context(raw, prepared_document(quote))

    normalized = [item["normalized"] for item in result["parameters"]]
    assert normalized == [
        {"value": 12, "unit": None, "status": "unit_unspecified"},
        {"value": None, "unit": None, "status": "not_numeric"},
        {"value": None, "unit": None, "status": "not_numeric"},
    ]


def test_context_validates_condition_operator_shapes_and_normalizes_between_bounds():
    quote = "The V100 run used batch sizes 2 through 8; the allowed set was [2, 4, 8]."
    raw = context(conditions=[
        {
            "dimension": "hardware.from",
            "operator": "eq",
            "value": "V100",
            "unit": None,
            "evidence": {"chunk_id": "chunk-test", "quote": "V100 run"},
        },
        {
            "dimension": "batch_size",
            "operator": "between",
            "value": [2, 8],
            "unit": None,
            "evidence": {"chunk_id": "chunk-test", "quote": "batch sizes 2 through 8"},
        },
        {
            "dimension": "allowed_batch_size",
            "operator": "in",
            "value": [2, 4, 8],
            "unit": None,
            "evidence": {"chunk_id": "chunk-test", "quote": "allowed set was [2, 4, 8]"},
        },
    ])

    result = validate_claim_context(raw, prepared_document(quote))

    assert result["conditions"][0]["value_raw"] == "V100"
    assert result["conditions"][0]["normalized"]["status"] == "not_numeric"
    assert result["conditions"][1]["value_raw"] == [2, 8]
    assert result["conditions"][1]["normalized"] == {
        "value": [2, 8],
        "unit": None,
        "status": "unit_unspecified",
    }
    assert result["conditions"][2]["value_raw"] == [2, 4, 8]


@pytest.mark.parametrize(
    "condition",
    [
        {"dimension": "x", "operator": "between", "value": [8, 2], "unit": None,
         "evidence": {"chunk_id": "chunk-test", "quote": "values 2 and 8"}},
        {"dimension": "x", "operator": "between", "value": [2], "unit": None,
         "evidence": {"chunk_id": "chunk-test", "quote": "value 2"}},
        {"dimension": "x", "operator": "in", "value": [2, "4"], "unit": None,
         "evidence": {"chunk_id": "chunk-test", "quote": "values 2 and 4"}},
        {"dimension": "x", "operator": "eq", "value": [2, 4], "unit": None,
         "evidence": {"chunk_id": "chunk-test", "quote": "values 2 and 4"}},
        {"dimension": "x", "operator": "gte", "value": math.inf, "unit": None,
         "evidence": {"chunk_id": "chunk-test", "quote": "threshold 4"}},
    ],
)
def test_context_rejects_invalid_condition_shapes(condition):
    with pytest.raises(ValueError, match="claim_context_invalid"):
        validate_claim_context(
            context(conditions=[condition]),
            prepared_document("The values 2 and 4 are shown; threshold 4."),
        )


def test_context_rejects_values_or_units_not_literally_supported_by_quote():
    quote = "Request latency measured 6.4 ms on V100."
    raw = context(parameters=[parameter("request latency", 64, "ms", quote)])

    with pytest.raises(ValueError, match="claim_context_value_not_literal"):
        validate_claim_context(raw, prepared_document(quote))

    raw = context(parameters=[parameter("request latency", 6.4, "us", quote)])
    with pytest.raises(ValueError, match="claim_context_unit_not_literal"):
        validate_claim_context(raw, prepared_document(quote))


def test_context_rejects_string_identifier_substrings():
    quote = "Peak on H1000 was 6.4 ms."
    raw = context(conditions=[{
        "dimension": "hardware.from",
        "operator": "eq",
        "value": "H100",
        "unit": None,
        "evidence": {"chunk_id": "chunk-test", "quote": quote},
    }])

    with pytest.raises(ValueError, match="claim_context_value_not_literal"):
        validate_claim_context(raw, prepared_document(quote))


@pytest.mark.parametrize(
    ("quote", "value", "unit"),
    [
        ("Peak rate is 2^10 tokens/s.", 10, "tokens/s"),
        ("The fraction is 1/2.", 1, None),
        ("The fraction is 1/2.", 2, None),
    ],
)
def test_context_rejects_numeric_operands_inside_expressions(quote, value, unit):
    raw = context(parameters=[parameter("rate", value, unit, quote)])

    with pytest.raises(ValueError, match="claim_context_value_not_literal"):
        validate_claim_context(raw, prepared_document(quote))


@pytest.mark.parametrize(
    ("quote", "value", "unit", "expected_normalized"),
    [
        (
            "The capacity is 1,000KiB.",
            1000,
            "KiB",
            {"value": 1024000, "unit": "B", "status": "normalized"},
        ),
        (
            "The capacity is 1e3 KiB.",
            1000,
            "KiB",
            {"value": 1024000, "unit": "B", "status": "normalized"},
        ),
        (
            "The latency is 1.25e-3s.",
            0.00125,
            "s",
            {"value": 0.00125, "unit": "s", "status": "normalized"},
        ),
    ],
)
def test_context_keeps_complete_grouped_scientific_and_adjacent_literals(
    quote, value, unit, expected_normalized
):
    raw = context(parameters=[parameter("measurement", value, unit, quote)])

    result = validate_claim_context(raw, prepared_document(quote))

    assert result["parameters"][0]["value_raw"] == value
    assert result["parameters"][0]["unit_raw"] == unit
    assert result["parameters"][0]["normalized"] == expected_normalized


def test_context_requires_unique_quote_in_its_declared_chunk_and_document():
    quote = "Request latency measured 6.4 ms."
    raw = context(parameters=[parameter("request latency", 6.4, "ms", quote)])
    repeated = quote + " The same quote appears again: " + quote

    with pytest.raises(ValueError, match="claim_context_quote_invalid"):
        validate_claim_context(raw, prepared_document(repeated))

    wrong_chunk = context(parameters=[{
        **parameter("request latency", 6.4, "ms", quote),
        "evidence": {"chunk_id": "not-this-revision", "quote": quote},
    }])
    with pytest.raises(ValueError, match="claim_context_quote_invalid"):
        validate_claim_context(wrong_chunk, prepared_document(quote))


def test_context_rejects_overlapping_duplicate_quote_occurrences():
    raw = context(parameters=[parameter("state", "AAA", None, "AAA")])

    with pytest.raises(ValueError, match="claim_context_quote_invalid"):
        validate_claim_context(raw, prepared_document("AAAA"))


def test_context_rejects_revision_or_chunk_span_mismatch():
    quote = "Request latency measured 6.4 ms."
    doc = prepared_document(quote)
    doc["revision"]["sha256"] = "bad"
    with pytest.raises(ValueError, match="claim_context_document_invalid"):
        validate_claim_context(
            context(parameters=[parameter("request latency", 6.4, "ms", quote)]), doc
        )

    doc = prepared_document(quote)
    doc["chunks"][0]["end"] -= 1
    with pytest.raises(ValueError, match="claim_context_document_invalid"):
        validate_claim_context(
            context(parameters=[parameter("request latency", 6.4, "ms", quote)]), doc
        )


def test_context_requires_the_prepared_material_identity_for_its_proof():
    quote = "Request latency measured 6.4 ms."
    doc = prepared_document(quote)
    doc.pop("material")

    with pytest.raises(ValueError, match="claim_context_document_invalid"):
        validate_claim_context(
            context(parameters=[parameter("request latency", 6.4, "ms", quote)]), doc
        )


def test_topic_mentions_use_conservative_aliases_with_source_offsets():
    text = "Paged KV cache and key/value cache are served by vLLM with CUDA and HBM."

    mentions = canonical_topic_mentions(text)

    assert [item["key"] for item in mentions] == [
        "kv_cache", "kv_cache", "vllm", "cuda", "hbm"
    ]
    assert text[mentions[0]["start"]:mentions[0]["end"]] == "KV cache"
    assert text[mentions[1]["start"]:mentions[1]["end"]] == "key/value cache"
    assert all(item["kind"] in {"family", "concept", "interface", "metric", "software"}
               for item in mentions)


def test_topic_mentions_never_merge_gpu_models_or_architecture_names():
    mentions = canonical_topic_mentions("H100 and A100 are discussed alongside Hopper architecture.")

    assert mentions == []


def test_topic_aliases_require_token_boundaries():
    assert canonical_topic_mentions("myvLLM CUDAized HBMx GPUTest") == []


def test_topic_registry_covers_dse_domains_without_merging_physical_assets():
    text='RISC-V chiplet CXL Triton SGLang gem5 thermal modeling Pareto MLflow TTFT'
    keys={x['key'] for x in canonical_topic_mentions(text)}
    assert {'risc_v','chiplet','cxl','triton','sglang','gem5','thermal_model','pareto','mlflow','ttft'}<=keys
    assert canonical_topic_mentions('H100 A100 Hopper')==[]


def test_public_schemas_and_roles_match_the_bounded_contract():
    assert set(SOURCE_ROLES) == {
        "core_technical", "supporting_method", "integration_operations",
        "source_navigation", "out_of_scope", "unclassified",
    }
    assert ROLE_SCHEMA["additionalProperties"] is False
    assert CONTEXT_SCHEMA["additionalProperties"] is False
    Draft202012Validator.check_schema(ROLE_SCHEMA)
    Draft202012Validator.check_schema(CONTEXT_SCHEMA)


def test_context_schema_rejects_condition_shapes_that_cannot_be_normalized():
    validator = Draft202012Validator(CONTEXT_SCHEMA)
    malformed = context(conditions=[{
        "dimension": "latency",
        "operator": "between",
        "value": [1],
        "unit": "ms",
        "evidence": {"chunk_id": "chunk-test", "quote": "latency 1 ms"},
    }])

    assert not validator.is_valid(malformed)



def test_provider_context_schema_uses_supported_subset_and_local_validator_stays_strict():
    import json
    from dse_knowledge.ingestion import _provider_context_schema

    provider_schema = _provider_context_schema()
    serialized = json.dumps(provider_schema)
    assert '"oneOf"' not in serialized
    assert '"allOf"' not in serialized
    assert '"if"' not in serialized
    assert '"then"' not in serialized
    assert '"else"' not in serialized
    assert '"const"' not in serialized
    assert '"anyOf"' in serialized

    malformed = context(conditions=[{
        "dimension": "latency",
        "operator": "between",
        "value": [1],
        "unit": "ms",
        "evidence": {"chunk_id": "chunk-test", "quote": "latency 1 ms"},
    }])
    assert Draft202012Validator(provider_schema).is_valid(malformed)
    with pytest.raises(ValueError, match="claim_context_invalid"):
        validate_claim_context(
            malformed, prepared_document("latency 1 ms"),
        )
