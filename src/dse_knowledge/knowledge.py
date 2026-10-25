"""Deterministic validation for source roles, claim context, and topic mentions."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math
import re
from typing import Any


SOURCE_ROLES = (
    "core_technical",
    "supporting_method",
    "integration_operations",
    "source_navigation",
    "out_of_scope",
    "unclassified",
)

TOPIC_ALIAS_REGISTRY_VERSION = "topic-aliases/v1"

ROLE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["role", "confidence", "rationale"],
    "properties": {
        "role": {"type": "string", "enum": list(SOURCE_ROLES)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string", "minLength": 1, "maxLength": 1200},
    },
}

_SCALAR_SCHEMA = {
    "anyOf": [
        {"type": "number"},
        {"type": "string"},
        {"type": "boolean"},
    ]
}
_VALUE_SCHEMA = {
    "anyOf": [
        _SCALAR_SCHEMA,
        {"type": "array", "minItems": 1, "maxItems": 32, "items": _SCALAR_SCHEMA},
    ]
}
_EVIDENCE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["chunk_id", "quote"],
    "properties": {
        "chunk_id": {"type": "string", "minLength": 1, "maxLength": 160},
        "quote": {"type": "string", "minLength": 1, "maxLength": 1200},
    },
}
_PARAMETER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "value", "unit", "evidence"],
    "properties": {
        "name": {"type": "string", "minLength": 1, "maxLength": 160},
        "value": _VALUE_SCHEMA,
        "unit": {"anyOf": [{"type": "string", "minLength": 1, "maxLength": 80}, {"type": "null"}]},
        "evidence": _EVIDENCE_SCHEMA,
    },
}
_CONDITION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["dimension", "operator", "value", "unit", "evidence"],
    "properties": {
        "dimension": {"type": "string", "minLength": 1, "maxLength": 160},
        "operator": {"type": "string", "enum": ["eq", "in", "between", "gte", "lte"]},
        "value": _VALUE_SCHEMA,
        "unit": {"anyOf": [{"type": "string", "minLength": 1, "maxLength": 80}, {"type": "null"}]},
        "evidence": _EVIDENCE_SCHEMA,
    },
    "allOf": [
        {
            "if": {"properties": {"operator": {"const": "eq"}}, "required": ["operator"]},
            "then": {"properties": {"value": _SCALAR_SCHEMA}},
        },
        {
            "if": {"properties": {"operator": {"const": "in"}}, "required": ["operator"]},
            "then": {"properties": {"value": {
                "type": "array", "minItems": 1, "maxItems": 32, "items": _SCALAR_SCHEMA,
            }}},
        },
        {
            "if": {"properties": {"operator": {"const": "between"}}, "required": ["operator"]},
            "then": {"properties": {"value": {
                "type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "number"},
            }}},
        },
        {
            "if": {
                "properties": {"operator": {"enum": ["gte", "lte"]}},
                "required": ["operator"],
            },
            "then": {"properties": {"value": {"type": "number"}},
                     "required": ["value"]},
        },
    ],
}

CONTEXT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "parameters", "conditions", "source_scope_note"],
    "properties": {
        "schema_version": {"type": "string", "const": "claim-context/v1"},
        "parameters": {"type": "array", "maxItems": 32, "items": _PARAMETER_SCHEMA},
        "conditions": {"type": "array", "maxItems": 32, "items": _CONDITION_SCHEMA},
        "source_scope_note": {"type": "string", "minLength": 1, "maxLength": 2000},
    },
}

_NUMBER_TOKEN = re.compile(
    r"(?<![\w.])([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)(?:[eE]([+-]?\d+))?"
)

# Each factor converts the source literal to a stable base unit. Unit symbols
# remain case-sensitive so mJ, MJ, B, and b can never be silently conflated.
_UNIT_ALIASES: dict[str, tuple[str, Decimal]] = {}


def _register_units(canonical: str, factor: str, *aliases: str) -> None:
    parsed_factor = Decimal(factor)
    for alias in aliases:
        _UNIT_ALIASES[alias] = (canonical, parsed_factor)


_register_units("s", "1", "s", "sec", "secs", "second", "seconds")
_register_units("s", "0.001", "ms", "msec", "millisecond", "milliseconds")
_register_units("s", "0.000001", "us", "µs", "μs", "usec", "microsecond", "microseconds")
_register_units("W", "1", "W", "watt", "watts")
_register_units("W", "1000", "kW", "kilowatt", "kilowatts")
_register_units("J", "1", "J", "joule", "joules")
_register_units("J", "0.001", "mJ", "millijoule", "millijoules")
_register_units("B", "1", "B", "byte", "bytes")
_register_units("B", "1000", "KB", "kB")
_register_units("B", "1024", "KiB")
_register_units("B", "1000000", "MB")
_register_units("B", "1048576", "MiB")
_register_units("B", "1000000000", "GB")
_register_units("B", "1073741824", "GiB")
_register_units("token/s", "1", "token/s", "tokens/s")
_register_units("req/s", "1", "req/s")
_register_units("%", "1", "%")

_TOPIC_ALIASES = (
    ("kv_cache", "KV cache", "concept", re.compile(r"(?<!\w)(?:kv[\s-]+cache|key[\s/-]+value[\s/-]+cache)(?!\w)", re.I)),
    ("vllm", "vLLM", "software", re.compile(r"(?<!\w)vllm(?!\w)", re.I)),
    ("cuda", "CUDA", "software", re.compile(r"(?<!\w)cuda(?!\w)", re.I)),
    ("hbm", "HBM", "interface", re.compile(r"(?<!\w)hbm(?!\w)", re.I)),
    ("gpu", "GPU", "family", re.compile(r"(?<!\w)gpu(?:s)?(?!\w)", re.I)),
)

# Topic identity means a literal software/method/interface mention, never an
# identity merge between physical assets or a compatibility assertion.
_TOPIC_ALIASES += tuple(
    (key,label,kind,re.compile(r'(?<!\w)(?:'+aliases+r')(?!\w)',re.I))
    for key,label,kind,aliases in (
        ('llm','LLM','family',r'LLMs?|large language models?'),
        ('sglang','SGLang','software',r'SGLang'),
        ('pagedattention','PagedAttention','concept',r'PagedAttention'),
        ('continuous_batching','Continuous batching','concept',r'continuous batching'),
        ('speculative_decoding','Speculative decoding','concept',r'speculative decoding'),
        ('flashattention','FlashAttention','software',r'FlashAttention(?:-?[23])?'),
        ('triton','Triton compiler','software',r'Triton'),
        ('mlir','MLIR','software',r'MLIR'),
        ('cutlass','CUTLASS','software',r'CUTLASS'),
        ('tvm','Apache TVM','software',r'(?:Apache )?TVM'),
        ('pytorch','PyTorch','software',r'PyTorch'),
        ('ptx','PTX','interface',r'PTX'),
        ('gemm','GEMM','concept',r'GEMM'),
        ('kernel_fusion','Kernel fusion','concept',r'kernel fusion'),
        ('dram','DRAM','family',r'DRAM'),
        ('sram','SRAM','family',r'SRAM'),
        ('cxl','CXL','interface',r'CXL|Compute Express Link'),
        ('nvlink','NVLink','interface',r'NVLink'),
        ('nccl','NCCL','software',r'NCCL'),
        ('noc','Network on chip','interface',r'network[- ]on[- ]chip'),
        ('risc_v','RISC-V','interface',r'RISC[- ]V'),
        ('chiplet','Chiplet','concept',r'chiplets?'),
        ('gem5','gem5','software',r'gem5'),
        ('ramulator','Ramulator','software',r'Ramulator(?: ?2(?:\.0)?)?'),
        ('accel_sim','Accel-Sim','software',r'Accel[- ]Sim'),
        ('sst','SST Simulator','software',r'SST Simulator|Structural Simulation Toolkit'),
        ('timeloop','Timeloop','software',r'Timeloop'),
        ('accelergy','Accelergy','software',r'Accelergy'),
        ('mcpat','McPAT','software',r'McPAT'),
        ('thermal_model','Thermal model','concept',r'thermal model(?:ing|s)?'),
        ('bayesian_optimization','Bayesian optimization','concept',r'Bayesian optimi[sz]ation'),
        ('pareto','Pareto frontier','concept',r'Pareto(?: frontier| front| optimality|[- ]optimal)?'),
        ('optuna','Optuna','software',r'Optuna'),
        ('botorch','BoTorch','software',r'BoTorch'),
        ('ray_tune','Ray Tune','software',r'Ray Tune'),
        ('ttft','Time to first token','metric',r'TTFT|time[- ]to[- ]first[- ]token'),
        ('tpot','Time per output token','metric',r'TPOT|time per output token'),
        ('energy_efficiency','Energy efficiency','metric',r'energy efficiency'),
        ('mlflow','MLflow','software',r'MLflow'),
        ('opentelemetry','OpenTelemetry','software',r'OpenTelemetry'),
        ('openmetrics','OpenMetrics','interface',r'OpenMetrics'),
        ('provenance','Provenance','concept',r'provenance'),
    )
)


def _invalid(reason: str = "claim_context_invalid") -> None:
    raise ValueError(reason)


def _scalar_kind(value: Any) -> str | None:
    if type(value) is bool:
        return "boolean"
    if type(value) in (int, float):
        if type(value) is float and not math.isfinite(value):
            return None
        return "number"
    if isinstance(value, str):
        return "string"
    return None


def _is_numeric(value: Any) -> bool:
    return type(value) in (int, float) and (type(value) is not float or math.isfinite(value))


def _validate_value(value: Any) -> None:
    if isinstance(value, list):
        if not 1 <= len(value) <= 32:
            _invalid()
        kinds = [_scalar_kind(item) for item in value]
        if None in kinds or len(set(kinds)) != 1:
            _invalid()
    elif _scalar_kind(value) is None:
        _invalid()


def _as_decimal(value: int | float) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        _invalid()


def _json_number(value: Decimal) -> int | float | None:
    if not value.is_finite():
        return None
    if value == value.to_integral_value():
        return int(value)
    try:
        converted = float(value)
    except (OverflowError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def _number_literals(quote: str) -> list[Decimal]:
    matches = list(_NUMBER_TOKEN.finditer(quote))
    expression_operands = set()
    arithmetic_separator = re.compile(r"\s*(?:\*\*|[*/^+×]|[xX])\s*")
    for index, (left, right) in enumerate(zip(matches, matches[1:])):
        if arithmetic_separator.fullmatch(quote[left.end():right.start()]):
            expression_operands.update((index, index + 1))

    found = []
    for index, match in enumerate(matches):
        if index in expression_operands:
            continue
        token = match.group(1).replace(",", "")
        exponent = match.group(2)
        if exponent is not None:
            token += "e" + exponent
        try:
            found.append(Decimal(token))
        except InvalidOperation:
            continue
    return found


def _value_is_literal(value: Any, quote: str) -> bool:
    if type(value) is bool:
        token = "true" if value else "false"
        return re.search(rf"(?<!\w){token}(?!\w)", quote, re.I) is not None
    if _is_numeric(value):
        wanted = _as_decimal(value)
        return any(candidate == wanted for candidate in _number_literals(quote))
    if isinstance(value, str):
        if not value:
            return False
        return re.search(rf"(?<!\w){re.escape(value)}(?!\w)", quote) is not None
    return False


def _value_items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def _validate_unit_literal(unit: str | None, quote: str) -> None:
    if unit is None:
        return
    # Permit symbols directly adjacent to a number ("6.4ms", "25%") while
    # refusing matches embedded in ordinary words ("ms" in "parameters").
    pattern = rf"(?<![^\W\d_]){re.escape(unit)}(?![^\W\d_])"
    if re.search(pattern, quote) is None:
        _invalid("claim_context_unit_not_literal")


def _normalized_values(value: Any, unit: str | None) -> dict[str, Any]:
    values = _value_items(value)
    if not values or not all(_is_numeric(item) for item in values):
        return {"value": None, "unit": None, "status": "not_numeric"}
    if unit is None:
        return {
            "value": value if isinstance(value, list) else values[0],
            "unit": None,
            "status": "unit_unspecified",
        }
    converted = _UNIT_ALIASES.get(unit)
    if converted is None:
        return {"value": None, "unit": None, "status": "unresolved"}
    canonical_unit, factor = converted
    normalized = [_json_number(_as_decimal(item) * factor) for item in values]
    if any(item is None for item in normalized):
        return {"value": None, "unit": None, "status": "unresolved"}
    return {
        "value": normalized if isinstance(value, list) else normalized[0],
        "unit": canonical_unit,
        "status": "normalized",
    }


def _document_evidence(document: Any) -> tuple[str, str, str, dict[str, dict[str, Any]]]:
    if not isinstance(document, dict):
        raise ValueError("claim_context_document_invalid")
    text = document.get("text")
    material = document.get("material")
    revision = document.get("revision")
    chunks = document.get("chunks")
    material_id = material.get("id") if isinstance(material, dict) else None
    digest = revision.get("sha256") if isinstance(revision, dict) else None
    if (not isinstance(material_id, str) or not material_id or len(material_id) > 160
            or not isinstance(text, str) or not text or not isinstance(revision, dict)
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not isinstance(chunks, list) or not chunks):
        raise ValueError("claim_context_document_invalid")
    by_id: dict[str, dict[str, Any]] = {}
    revision_id = revision.get("id")
    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise ValueError("claim_context_document_invalid")
        chunk_id, chunk_text = chunk.get("id"), chunk.get("text")
        start, end = chunk.get("start"), chunk.get("end")
        if (not isinstance(chunk_id, str) or not chunk_id or chunk_id in by_id
                or not isinstance(chunk_text, str) or type(start) is not int or type(end) is not int
                or start < 0 or end <= start or end > len(text) or text[start:end] != chunk_text
                or chunk.get("material_id", material_id) != material_id
                or (revision_id is not None and chunk.get("revision_id", revision_id) != revision_id)
                or chunk.get("revision_sha256", digest) != digest):
            raise ValueError("claim_context_document_invalid")
        by_id[chunk_id] = chunk
    return text, digest, material_id, by_id


def _validate_context_shape(context: Any) -> None:
    if not isinstance(context, dict) or set(context) != {
        "schema_version", "parameters", "conditions", "source_scope_note"
    }:
        _invalid()
    if context.get("schema_version") != "claim-context/v1":
        _invalid()
    if (not isinstance(context.get("parameters"), list) or len(context["parameters"]) > 32
            or not isinstance(context.get("conditions"), list) or len(context["conditions"]) > 32
            or not isinstance(context.get("source_scope_note"), str)
            or not context["source_scope_note"].strip() or len(context["source_scope_note"]) > 2000):
        _invalid()
    for parameter in context["parameters"]:
        if (not isinstance(parameter, dict) or set(parameter) != {"name", "value", "unit", "evidence"}
                or not isinstance(parameter.get("name"), str) or not parameter["name"].strip()
                or len(parameter["name"]) > 160):
            _invalid()
        _validate_value(parameter.get("value"))
        unit = parameter.get("unit")
        if unit is not None and (not isinstance(unit, str) or not unit.strip() or len(unit) > 80):
            _invalid()
        _validate_evidence_shape(parameter.get("evidence"))
    for condition in context["conditions"]:
        if (not isinstance(condition, dict)
                or set(condition) != {"dimension", "operator", "value", "unit", "evidence"}
                or not isinstance(condition.get("dimension"), str)
                or not condition["dimension"].strip() or len(condition["dimension"]) > 160
                or condition.get("operator") not in {"eq", "in", "between", "gte", "lte"}):
            _invalid()
        value = condition.get("value")
        _validate_value(value)
        operator = condition["operator"]
        if operator == "eq" and isinstance(value, list):
            _invalid()
        if operator == "in" and not isinstance(value, list):
            _invalid()
        if operator == "between":
            if not isinstance(value, list) or len(value) != 2 or not all(_is_numeric(item) for item in value):
                _invalid()
            if _as_decimal(value[0]) > _as_decimal(value[1]):
                _invalid()
        if operator in {"gte", "lte"} and not _is_numeric(value):
            _invalid()
        unit = condition.get("unit")
        if unit is not None and (not isinstance(unit, str) or not unit.strip() or len(unit) > 80):
            _invalid()
        _validate_evidence_shape(condition.get("evidence"))


def _validate_evidence_shape(evidence: Any) -> None:
    if (not isinstance(evidence, dict) or set(evidence) != {"chunk_id", "quote"}
            or not isinstance(evidence.get("chunk_id"), str) or not evidence["chunk_id"]
            or len(evidence["chunk_id"]) > 160 or not isinstance(evidence.get("quote"), str)
            or not evidence["quote"] or len(evidence["quote"]) > 1200):
        _invalid()


def _ground_evidence(evidence: dict[str, Any], text: str, digest: str, material_id: str,
                     chunks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    chunk = chunks.get(evidence["chunk_id"])
    quote = evidence["quote"]
    if chunk is None or len(_overlapping_occurrences(text, quote)) != 1 \
            or len(_overlapping_occurrences(chunk["text"], quote)) != 1:
        _invalid("claim_context_quote_invalid")
    source_start = text.find(quote)
    if source_start < chunk["start"] or source_start + len(quote) > chunk["end"]:
        _invalid("claim_context_quote_invalid")
    chunk_local = source_start - chunk["start"]
    if chunk["text"][chunk_local:chunk_local + len(quote)] != quote:
        _invalid("claim_context_quote_invalid")
    return {
        "chunk_id": evidence["chunk_id"],
        "material_id": material_id,
        "quote": quote,
        "source_start": source_start,
        "source_end": source_start + len(quote),
        "revision_sha256": digest,
    }


def _overlapping_occurrences(text: str, quote: str, stop_after: int = 2) -> list[int]:
    found = []
    offset = 0
    while len(found) < stop_after:
        index = text.find(quote, offset)
        if index < 0:
            break
        found.append(index)
        offset = index + 1
    return found


def _validate_literals(value: Any, unit: str | None, quote: str) -> None:
    if any(not _value_is_literal(item, quote) for item in _value_items(value)):
        _invalid("claim_context_value_not_literal")
    _validate_unit_literal(unit, quote)


def validate_claim_context(context: dict, document: dict) -> dict:
    """Validate literal evidence and normalize only explicitly supported units.

    Normalized values describe a source assertion. They do not establish a
    metric association, scientific correctness, or applicability beyond the
    cited material revision.
    """
    _validate_context_shape(context)
    text, digest, material_id, chunks = _document_evidence(document)
    normalized = {
        "schema_version": "claim-context/v1",
        "parameters": [],
        "conditions": [],
        "source_scope_note": context["source_scope_note"].strip(),
    }
    for item in context["parameters"]:
        evidence = _ground_evidence(item["evidence"], text, digest, material_id, chunks)
        _validate_literals(item["value"], item["unit"], evidence["quote"])
        normalized["parameters"].append({
            "name": item["name"].strip(),
            "value_raw": item["value"],
            "unit_raw": item["unit"],
            "normalized": _normalized_values(item["value"], item["unit"]),
            "evidence": evidence,
        })
    for item in context["conditions"]:
        evidence = _ground_evidence(item["evidence"], text, digest, material_id, chunks)
        _validate_literals(item["value"], item["unit"], evidence["quote"])
        normalized["conditions"].append({
            "dimension": item["dimension"].strip(),
            "operator": item["operator"],
            "value_raw": item["value"],
            "unit_raw": item["unit"],
            "normalized": _normalized_values(item["value"], item["unit"]),
            "evidence": evidence,
        })
    normalized.update({
        "use_policy": "source_assertion_only",
        "validation": "literal_grounded_unverified_association",
        "independent_validations": 0,
    })
    return normalized


def validate_role_assessment(payload: dict) -> dict:
    """Normalize an advisory source-role result without granting authority."""
    if not isinstance(payload, dict) or set(payload) != {"role", "confidence", "rationale"}:
        raise ValueError("role_assessment_invalid")
    role, confidence, rationale = payload["role"], payload["confidence"], payload["rationale"]
    if (role not in SOURCE_ROLES or type(confidence) not in (int, float)
            or not math.isfinite(confidence) or not 0 <= confidence <= 1
            or not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 1200):
        raise ValueError("role_assessment_invalid")
    return {
        "schema_version": "source-role/v1",
        "role": role,
        "status": "needs_review" if role == "unclassified" else "assessed",
        "confidence": float(confidence),
        "rationale": rationale.strip(),
        "authority": "curator_annotation",
    }


def canonical_topic_mentions(text: str) -> list[dict[str, Any]]:
    """Find only conservative concept/software/interface aliases with exact spans."""
    if not isinstance(text, str):
        raise ValueError("topic_text_invalid")
    matches = []
    for key, label, kind, pattern in _TOPIC_ALIASES:
        for match in pattern.finditer(text):
            matches.append({
                "key": key,
                "label": label,
                "kind": kind,
                "alias": match.group(0),
                "start": match.start(),
                "end": match.end(),
            })
    matches.sort(key=lambda item: (item["start"], -(item["end"] - item["start"]), item["key"]))
    accepted = []
    for item in matches:
        if accepted and item["start"] < accepted[-1]["end"]:
            continue
        accepted.append(item)
    return accepted
