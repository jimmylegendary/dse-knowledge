"""Hybrid source retrieval with bounded, evidence-grounded reranking."""
from __future__ import annotations

import re
import threading
import time
import uuid
import math
from collections import OrderedDict
from copy import deepcopy

from .db import vector_literal
from .providers import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL


POLICY_VERSION = "retrieval-policy/v2.2"
PURPOSE_POLICY_VERSION = "purpose-policy/v1"
EMBEDDING_CACHE_TTL_SECONDS = 300
EMBEDDING_CACHE_MAX_ITEMS = 128
DENSE_CANDIDATE_LIMIT = 40
DENSE_EXACT_SCAN_CAP = 50_000
_QUERY_EMBEDDINGS: OrderedDict[tuple, tuple[float, list[float], dict]] = OrderedDict()
_QUERY_EMBEDDINGS_LOCK = threading.RLock()

_TOKEN_RE = re.compile(
    r"[A-Za-z0-9]+(?:[./+#:_-][A-Za-z0-9+#-]+)*|[\uac00-\ud7a3]+|[^\W_]+",
    re.UNICODE,
)
_QUOTED_PHRASE_RE = re.compile(r"\"([^\"]{2,240})\"|'([^']{2,240})'")
_STOP_WORDS = frozenset({
    "a", "about", "an", "and", "are", "as", "at", "be", "by", "can", "could",
    "describe", "do", "does", "explain", "find", "for", "from", "give", "how", "i",
    "in", "is", "it", "list", "me", "of", "on", "or", "please", "show", "tell", "that",
    "the", "their", "this", "to", "using", "we", "what", "when", "where", "which", "with",
    "would", "you", "your", "이", "가", "은", "는", "을", "를", "와", "과", "의", "에", "에서",
    "으로", "로", "도", "만", "및", "좀", "어떤", "무엇", "어떻게", "해줘", "해주세요", "설명해줘",
    "찾아줘", "찾아", "있는", "하는", "대한", "관련", "대해", "위한", "있나요", "인가요",
})
_KNOWN_ROLES = frozenset({
    "core_technical", "supporting_method", "integration_operations", "source_navigation",
    "out_of_scope", "unclassified",
})
_BROAD_TOPIC_KEYS = frozenset({
    "ai", "artificial-intelligence", "gpu", "gpus", "llm", "llms", "machine-learning",
    "performance", "software", "hardware", "accelerator", "accelerators",
})
_CHANNEL_WEIGHTS = {"dense": 1.0, "lexical": 0.45, "exact": 0.25, "graph": 0.18}
_DENSE_PAYLOAD_FIELDS = (
    "c.id AS chunk_id,c.material_id,c.revision_id,c.start_offset,c.end_offset,c.text,"
    "m.title,m.url,m.source,m.category,m.scope,m.role,m.role_metadata"
)


class RetrievalCapacityError(RuntimeError):
    """Search cannot run safely within the bounded exact-dense pilot scope."""

    def __init__(self, code: str, *, scope_count=None, scope_cap: int = DENSE_EXACT_SCAN_CAP):
        self.code = code
        self.scope_count = scope_count
        self.scope_cap = scope_cap
        super().__init__(code)


def reciprocal_rank_fusion(channels, limit=12):
    """Compatibility RRF helper retained for existing callers and tests."""
    merged = {}
    for channel, rows in channels.items():
        for rank, row in enumerate(rows, 1):
            item = merged.setdefault(row["chunk_id"], dict(row, scores={}, rank=0))
            item["scores"][channel] = 1 / (60 + rank)
            item["rank"] += 1 / (60 + rank)
    return sorted(merged.values(), key=lambda item: (-item["rank"], item["chunk_id"]))[:limit]


def _normalized_query(query: str) -> str:
    return " ".join(query.split())


def _cache_query(query: str) -> str:
    # Provider embeddings are case-sensitive; only normalize whitespace for cache identity.
    return _normalized_query(query)


def _lexical_features(query: str) -> dict[str, list[str]]:
    """Extract quoted phrases and useful words without requiring every query word."""
    phrases = []
    for match in _QUOTED_PHRASE_RE.finditer(query):
        phrase = " ".join((match.group(1) or match.group(2)).split())
        if phrase and phrase.casefold() not in {value.casefold() for value in phrases}:
            phrases.append(phrase)

    terms = []
    seen = set()
    for token in _TOKEN_RE.findall(query):
        normalized = token.casefold().strip("._:/+-#")
        if not normalized or normalized in _STOP_WORDS or normalized in seen:
            continue
        # Keep one-letter Latin words only when they are explicit code-like identifiers.
        has_hangul = any("\uac00" <= char <= "\ud7a3" for char in token)
        code_like = any(char.isdigit() for char in token) or any(char in ".+/#:_-" for char in token)
        if len(normalized) < 2 and not code_like and not has_hangul:
            continue
        seen.add(normalized)
        terms.append(token)
        if len(terms) >= 12:
            break

    return {"phrases": phrases[:4], "terms": terms}


def _websearch_query(features: dict[str, list[str]]) -> str:
    # Quote each extracted feature so user-supplied OR/NOT syntax cannot alter the plan.
    values = []
    seen = set()
    for phrase in features["phrases"]:
        safe = " ".join(phrase.replace('"', " ").split())
        if safe and safe.casefold() not in seen:
            values.append(f'"{safe}"')
            seen.add(safe.casefold())
    for term in features["terms"]:
        key = term.casefold()
        if key not in seen:
            values.append(f'"{term.replace(chr(34), "")}"')
            seen.add(key)
    return " OR ".join(values)


def _ilike_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _title_patterns(features: dict[str, list[str]]) -> list[str]:
    candidates = features["phrases"] + features["terms"]
    patterns = []
    seen = set()
    for value in candidates:
        if len(value.strip()) < 2 or value.casefold() in seen:
            continue
        seen.add(value.casefold())
        patterns.append(_ilike_pattern(value))
        if len(patterns) == 8:
            break
    return patterns


def _dense_scope_count_query(category: str) -> tuple[str, tuple[str, str]]:
    sql = (
        "WITH latest_revision AS MATERIALIZED ("
        "SELECT DISTINCT ON (r.material_id) r.material_id,r.id AS revision_id "
        "FROM revisions r ORDER BY r.material_id,r.created_at DESC,r.id DESC) "
        "SELECT COUNT(*) AS visible_chunk_count "
        "FROM chunks c JOIN materials m ON m.id=c.material_id "
        "JOIN latest_revision lr ON lr.material_id=c.material_id AND lr.revision_id=c.revision_id "
        "WHERE (%s='' OR m.category=%s) "
        "AND COALESCE(m.role,'unclassified') <> 'out_of_scope' AND c.embedding IS NOT NULL"
    )
    return sql, (category, category)


def _exact_dense_candidates_query(
    category: str,
    embedding_vector: list[float],
    fields: str,
) -> tuple[str, tuple[str, str, str]]:
    """Rank the bounded pilot's visible current-revision IDs before loading payload."""
    vector = vector_literal(embedding_vector)
    sql = (
        "WITH latest_revision AS MATERIALIZED ("
        "SELECT DISTINCT ON (r.material_id) r.material_id,r.id AS revision_id "
        "FROM revisions r ORDER BY r.material_id,r.created_at DESC,r.id DESC), "
        "dense_distances AS MATERIALIZED ("
        "SELECT c.id AS chunk_id,c.material_id,"
        "c.embedding <=> %s::extensions.vector AS distance "
        "FROM chunks c JOIN materials m ON m.id=c.material_id "
        "JOIN latest_revision lr ON lr.material_id=c.material_id AND lr.revision_id=c.revision_id "
        "WHERE (%s='' OR m.category=%s) "
        "AND COALESCE(m.role,'unclassified') <> 'out_of_scope' AND c.embedding IS NOT NULL), "
        "dense_top AS MATERIALIZED ("
        "SELECT chunk_id,material_id,distance FROM dense_distances "
        f"ORDER BY distance,chunk_id LIMIT {DENSE_CANDIDATE_LIMIT}) "
        "SELECT " + fields + " FROM dense_top "
        "JOIN chunks c ON c.id=dense_top.chunk_id AND c.material_id=dense_top.material_id "
        "JOIN materials m ON m.id=c.material_id "
        "ORDER BY dense_top.distance,dense_top.chunk_id"
    )
    return sql, (vector, category, category)


def build_dense_scope_count_query(category: str) -> tuple[str, tuple[str, str]]:
    """Expose the bounded scan scope query for offline EXPLAIN and root verification."""
    return _dense_scope_count_query(category)


def build_exact_dense_candidates_query(
    category: str,
    embedding_vector: list[float],
) -> tuple[str, tuple[str, str, str]]:
    """Build the exact pilot candidate SQL without calling an embedding provider."""
    return _exact_dense_candidates_query(category, embedding_vector, _DENSE_PAYLOAD_FIELDS)


def _canonical_topics(query: str) -> list[dict]:
    """Use only the curated topic registry; do not infer graph nodes from query words."""
    try:
        from .knowledge import canonical_topic_mentions
    except ModuleNotFoundError as error:
        if error.name == f"{__package__}.knowledge":
            return []
        raise

    raw_mentions = canonical_topic_mentions(query)
    if not isinstance(raw_mentions, list):
        return []
    topics = []
    seen = set()
    for mention in raw_mentions:
        if not isinstance(mention, dict):
            continue
        key = mention.get("key")
        if not isinstance(key, str) or not key.strip():
            continue
        key = key.strip()
        if key.casefold() in seen:
            continue
        seen.add(key.casefold())
        aliases = mention.get("alias", [])
        if isinstance(aliases, str):
            aliases = [aliases]
        elif not isinstance(aliases, list):
            aliases = []
        label = mention.get("label")
        if isinstance(label, str):
            aliases = [label, *aliases]
        topics.append({
            "key": key,
            "kind": str(mention.get("kind") or ""),
            "aliases": list(dict.fromkeys(value.strip() for value in aliases
                                          if isinstance(value, str) and len(value.strip()) >= 2)),
        })
    return topics[:12]


def _purpose_decision(query: str, purpose: str) -> dict:
    allowed = {"auto", "design", "operations", "discovery"}
    if purpose not in allowed:
        raise ValueError("Purpose must be auto, design, operations or discovery")
    if purpose != "auto":
        return {
            "requested": purpose,
            "resolved": purpose,
            "rule": "caller_selected_purpose",
            "uncertain": False,
            "version": PURPOSE_POLICY_VERSION,
        }

    folded = query.casefold()
    discovery_patterns = (
        r"\b(?:find|locate|search\s+for|look\s+for|where\s+(?:can|do|are|to)|which)\b.{0,64}\b(?:documents?|docs?|papers?|references?|sources?|bibliograph(?:y|ies)|documentation)\b",
        r"\b(?:list|show|recommend|cite)\b.{0,48}\b(?:docs?|documents?|papers?|references?|sources?|bibliograph(?:y|ies))\b",
        r"\b(?:docs?|documents?|papers?|references?|sources?)\b.{0,40}\b(?:find|search|locate|list|where|recommend|show)\b",
        r"\b(?:papers?|documents?|documentation)\s+(?:about|on|for|regarding)\b",
        r"\bfeature\s+map\b|\bbibliograph(?:y|ies)\b",
        r"(?:자료|문서)\s*(?:를|가|은|는|에|의)?\s*(?:찾(?:아|을|는|기)?|검색|목록|모아|추천|제시|보여|알려|확인)",
        r"(?:논문|참고문헌|레퍼런스)\s*(?:을|를|가|은|는|에|의)?\s*(?:찾(?:아|을|는|기)?|검색|목록|모아|추천|제시|보여|알려|확인)",
        r"(?:어디서|어디에)\s*(?:찾|볼|확인|있|있는)|찾을\s*수\s*있는\s*(?:자료|문서|논문)",
        r"기능\s*지도|참고\s*자료",
    )
    operations_patterns = (
        r"\b(install|setup|configure|configuration|api|ci|reproduce|reproduction|deploy|command|workflow|operations?)\b",
        r"설치|설정|구성|운영|재현|실행|빌드|사용법|명령어|오류|배포",
    )
    design_patterns = (
        r"\b(design|architecture|trade[- ]?off|performance|benchmark|compare|why|mechanism)\b",
        r"설계|아키텍처|성능|비교|원리|구조|효율",
    )
    has_discovery = any(re.search(pattern, folded) for pattern in discovery_patterns)
    has_operations = any(re.search(pattern, folded) for pattern in operations_patterns)
    has_design = any(re.search(pattern, folded) for pattern in design_patterns)
    if has_discovery:
        rule = "auto_explicit_source_find_with_operations_context" if has_operations else "auto_explicit_source_find"
        resolved, uncertain = "discovery", False
    elif has_operations:
        resolved, rule, uncertain = "operations", "auto_operations_intent", False
    elif has_design:
        resolved, rule, uncertain = "design", "auto_design_intent", False
    else:
        resolved, rule, uncertain = "design", "auto_default_design_unclear", True
    return {
        "requested": "auto",
        "resolved": resolved,
        "rule": rule,
        "uncertain": uncertain,
        "version": PURPOSE_POLICY_VERSION,
    }


def _role_policy(role: str, purpose: str, uncertain: bool) -> dict:
    weights = {
        "design": {
            "core_technical": 1.0,
            "supporting_method": 0.9,
            "integration_operations": 0.65,
            "unclassified": 0.25,
            "source_navigation": 1.0,
        },
        "operations": {
            "integration_operations": 1.0,
            "core_technical": 0.8,
            "supporting_method": 0.7,
            "unclassified": 0.25,
            "source_navigation": 1.0,
        },
        "discovery": {
            "core_technical": 1.0,
            "supporting_method": 1.0,
            "integration_operations": 1.0,
            "unclassified": 0.25,
            "source_navigation": 1.0,
        },
    }
    role = role if role in _KNOWN_ROLES else "unclassified"
    policy = {
        "role": role,
        "purpose": purpose,
        "weight": weights[purpose].get(role, 0.25),
        "needs_review": role == "unclassified",
        "is_locator": role == "source_navigation",
        "evidence_authority": 0.0 if role == "source_navigation" else None,
        "evidence_ceiling": "needs_review" if role == "unclassified" else None,
        "use_ceiling": None,
        "auto_uncertain": uncertain,
        "policy_version": POLICY_VERSION,
    }
    if role == "integration_operations" and purpose == "design":
        policy["use_ceiling"] = "workflow_or_interface_reference"
    elif role == "source_navigation":
        policy["use_ceiling"] = "locator"
    elif role == "supporting_method":
        policy["use_ceiling"] = "methodological_context"
    elif role == "core_technical":
        policy["use_ceiling"] = "source_assertion"
    return policy


def _query_relevance(row: dict, features: dict[str, list[str]]) -> int:
    searchable = " ".join(str(row.get(key) or "") for key in ("title", "source", "text")).casefold()
    score = sum(2 for phrase in features["phrases"] if phrase.casefold() in searchable)
    score += sum(1 for term in features["terms"] if term.casefold() in searchable)
    return score


def _graph_idf_by_topic(rows: list[dict]) -> dict[str, float]:
    chunk_ids = {str(row.get("chunk_id")) for row in rows if row.get("chunk_id") is not None}
    if not chunk_ids:
        return {}
    documents_by_topic: dict[str, set[str]] = {}
    for row in rows:
        key = row.get("topic_normalized")
        if not isinstance(key, str) or not key:
            continue
        documents_by_topic.setdefault(key, set()).add(str(row["chunk_id"]))
    denominator = math.log1p(len(chunk_ids))
    if denominator == 0:
        return {}
    return {
        key: max(0.25, min(1.0, math.log1p(len(chunk_ids) / len(document_ids)) / denominator))
        for key, document_ids in documents_by_topic.items() if document_ids
    }


def _graph_specificity(row: dict, topics: list[dict], idf: float = 1.0) -> float:
    key = str(row.get("topic_normalized") or "").removeprefix("topic:v1:")
    topic = next((item for item in topics if item["key"] == key), None)
    specificity = 0.25 if key.casefold() in _BROAD_TOPIC_KEYS or (
        topic and topic["kind"].casefold() in {"generic", "broad"}
    ) else 1.0
    return max(0.1, min(1.0, specificity * idf))


def _collapse_graph_rows(rows: list[dict], max_proofs_per_chunk: int = 2) -> list[dict]:
    """Collapse bounded edge rows into unique chunks while preserving selected provenance."""
    grouped = {}
    for row in rows:
        chunk_id = str(row["chunk_id"])
        candidate = grouped.setdefault(chunk_id, {**row, "_graph_provenance": [], "_graph_total_proofs": 0})
        try:
            candidate["_graph_total_proofs"] = max(
                candidate["_graph_total_proofs"], int(row.get("graph_proof_count") or 0)
            )
        except (TypeError, ValueError, OverflowError):
            pass
        edge_id = row.get("graph_edge_id")
        if edge_id is None:
            continue
        provenance = {
            "relation_kind": row.get("graph_relation_kind"),
            "relation": row.get("graph_relation"),
            "edge_id": str(edge_id),
            "claim_id": str(row["graph_claim_id"]) if row.get("graph_claim_id") is not None else None,
            "evidence_chunk_id": str(row["graph_evidence_chunk_id"]) if row.get("graph_evidence_chunk_id") is not None else None,
            "topic_key": row.get("graph_topic_key"),
        }
        if provenance not in candidate["_graph_provenance"] and len(candidate["_graph_provenance"]) < max_proofs_per_chunk:
            candidate["_graph_provenance"].append(provenance)

    candidates = []
    for candidate in grouped.values():
        proofs = candidate.pop("_graph_provenance")
        total_proofs = max(candidate.pop("_graph_total_proofs"), len(proofs))
        candidate["graph_query_relevance"] = candidate.pop("query_relevance", None)
        for key in ("graph_edge_id", "graph_claim_id", "graph_relation_kind", "graph_relation",
                    "graph_evidence_chunk_id", "graph_topic_key", "graph_proof_rank"):
            candidate.pop(key, None)
        candidate["graph_provenance"] = proofs
        candidate["graph_proof_count"] = total_proofs
        candidate["graph_discarded_link_count"] = max(0, total_proofs - len(proofs))
        candidates.append(candidate)
    return candidates


def _embedding_setting(embedding, names: tuple[str, ...], default=None):
    settings = getattr(embedding, "settings", None)
    getter = getattr(settings, "get", None)
    if callable(getter):
        for name in names:
            try:
                value = getter(name)
            except TypeError:
                value = getter(name, None)
            if value not in (None, ""):
                return value
    for name in names:
        attr = name.lower().replace("dse_", "").replace("embedding_", "")
        value = getattr(embedding, attr, None)
        if value not in (None, ""):
            return value
    metadata = getattr(embedding, "last_metadata", {})
    if isinstance(metadata, dict):
        for name in names:
            short = name.lower().replace("dse_embedding_", "").replace("embedding_", "")
            value = metadata.get(short)
            if value not in (None, ""):
                return value
    return default


def _embedding_identity(embedding, task: str) -> tuple[str, str, int, str]:
    provider = _embedding_setting(embedding, ("DSE_EMBEDDING_PROVIDER", "EMBEDDING_PROVIDER", "provider"), "deepinfra")
    model = _embedding_setting(embedding, ("DSE_EMBEDDING_MODEL_ID", "EMBEDDING_MODEL_ID", "model"), EMBEDDING_MODEL)
    dimensions = _embedding_setting(
        embedding, ("DSE_EMBEDDING_DIMENSIONS", "EMBEDDING_DIMENSIONS", "dimensions"), EMBEDDING_DIMENSIONS
    )
    try:
        dimensions = int(dimensions)
    except (TypeError, ValueError, OverflowError):
        dimensions = EMBEDDING_DIMENSIONS
    return str(provider), str(model), dimensions, task


def _query_embedding(embedding, query: str, store) -> tuple[list[float], bool, dict]:
    task = "search_query"
    identity = _embedding_identity(embedding, task)
    key = (_cache_query(query), *identity)
    now = time.monotonic()
    with _QUERY_EMBEDDINGS_LOCK:
        expired = [cache_key for cache_key, (created, _, _) in _QUERY_EMBEDDINGS.items()
                   if now - created >= EMBEDDING_CACHE_TTL_SECONDS]
        for cache_key in expired:
            _QUERY_EMBEDDINGS.pop(cache_key, None)
        cached = _QUERY_EMBEDDINGS.get(key)
        if cached is not None:
            created, vector, metadata = cached
            if now - created < EMBEDDING_CACHE_TTL_SECONDS:
                _QUERY_EMBEDDINGS.move_to_end(key)
                hit_metadata = {
                    "provider": identity[0], "model": identity[1], "dimensions": identity[2],
                    "task": task, "usage": {}, "cache_hit": True,
                    "provider_usage_recorded": False,
                }
                store.invocation(identity[0], "query", hit_metadata)
                return list(vector), True, hit_metadata
            _QUERY_EMBEDDINGS.pop(key, None)

    vector = embedding.embed([query], task=task)[0]
    metadata = deepcopy(getattr(embedding, "last_metadata", {}) or {})
    metadata.setdefault("provider", identity[0])
    metadata.setdefault("model", identity[1])
    metadata.setdefault("dimensions", identity[2])
    metadata.setdefault("task", task)
    metadata.setdefault("usage", {})
    metadata["cache_hit"] = False
    metadata["provider_usage_recorded"] = True
    # Publish the embedding only after the provider usage has reached the durable ledger.
    store.invocation(str(metadata["provider"]), "query", metadata)
    with _QUERY_EMBEDDINGS_LOCK:
        _QUERY_EMBEDDINGS[key] = (time.monotonic(), list(vector), deepcopy(metadata))
        _QUERY_EMBEDDINGS.move_to_end(key)
        while len(_QUERY_EMBEDDINGS) > EMBEDDING_CACHE_MAX_ITEMS:
            _QUERY_EMBEDDINGS.popitem(last=False)
    return list(vector), False, metadata


def _merge_ranked_channels(channels: dict[str, list[dict]], topics: list[dict], purpose: str,
                           uncertain: bool, features: dict[str, list[str]]) -> list[dict]:
    graph = channels.get("graph", [])
    graph_idf = _graph_idf_by_topic(graph)
    indexed_graph = list(enumerate(graph))
    indexed_graph.sort(key=lambda pair: (-_query_relevance(pair[1], features), pair[0], pair[1]["chunk_id"]))
    channels = {**channels, "graph": [row for _, row in indexed_graph]}

    merged = {}
    for channel, rows in channels.items():
        for rank, row in enumerate(rows, 1):
            chunk_id = str(row["chunk_id"])
            item = merged.setdefault(chunk_id, dict(row, scores={}, trace={"channel_ranks": {}}))
            if channel == "graph":
                item["graph_provenance"] = deepcopy(row.get("graph_provenance", []))
                item["graph_proof_count"] = row.get("graph_proof_count", 0)
                item["graph_discarded_link_count"] = row.get("graph_discarded_link_count", 0)
            item["scores"][channel] = 1 / (60 + rank)
            item["trace"]["channel_ranks"][channel] = rank
            weight = _CHANNEL_WEIGHTS[channel]
            graph_idf_value = 1.0
            if channel == "graph":
                graph_idf_value = graph_idf.get(str(row.get("topic_normalized") or ""), 1.0)
                weight *= _graph_specificity(row, topics, graph_idf_value)
            item.setdefault("_unweighted_score", 0.0)
            item["_unweighted_score"] += weight / (60 + rank)

    ranked = []
    for item in merged.values():
        role_value = item.get("role") or "unclassified"
        role = role_value if role_value in _KNOWN_ROLES else "unclassified"
        policy = _role_policy(role, purpose, uncertain)
        query_relevance = _query_relevance(item, features)
        base_score = item.pop("_unweighted_score")
        item["role"] = role
        item["role_metadata"] = item.get("role_metadata") if isinstance(item.get("role_metadata"), dict) else {}
        item["role_policy"] = policy
        item["retrieval_policy"] = POLICY_VERSION
        item["trace"].update({
            "role_weight": policy["weight"],
            "query_relevance": query_relevance,
            "graph_rank": item["trace"]["channel_ranks"].get("graph"),
            "graph_boost": item["scores"].get("graph", 0.0) * _CHANNEL_WEIGHTS["graph"]
                           * _graph_specificity(item, topics, graph_idf.get(
                               str(item.get("topic_normalized") or ""), 1.0)),
            "graph_topic_idf": graph_idf.get(str(item.get("topic_normalized") or ""), 1.0),
            "graph_proof_count": item.get("graph_proof_count", 0),
            "graph_discarded_link_count": item.get("graph_discarded_link_count", 0),
            "rank_score": base_score * policy["weight"],
        })
        item["rank"] = base_score * policy["weight"]
        ranked.append(item)
    ranked.sort(key=lambda item: (-item["rank"], item["chunk_id"]))
    return ranked


def _diverse_with_backfill(items: list[dict], limit: int, per_material: int = 3) -> list[dict]:
    selected, deferred, counts = [], [], {}
    for item in items:
        material_id = item.get("material_id")
        count = counts.get(material_id, 0)
        if count < per_material:
            selected.append(item)
            counts[material_id] = count + 1
        else:
            deferred.append(item)
    selected.extend(deferred[:max(0, limit - len(selected))])
    return selected[:limit]


def _semantic_anchor_order(candidates: list[dict], dense: list[dict], stream: str,
                           *, include_navigation: bool = False) -> tuple[list[dict], dict]:
    """Choose a dense-ranked source first, then its highest existing hybrid passage."""
    eligible_roles = {"core_technical", "supporting_method", "integration_operations"}
    if include_navigation:
        eligible_roles.add("source_navigation")
    anchor = None
    metadata = {
        "material_id": None,
        "chunk_id": None,
        "original_dense_rank": None,
        "original_hybrid_position": None,
        "promoted": False,
        "selection_basis": "dense_material_then_best_hybrid_passage",
        "authority_changed": False,
    }
    for dense_rank, row in enumerate(dense, 1):
        role_value = row.get("role") or "unclassified"
        role = role_value if role_value in _KNOWN_ROLES else "unclassified"
        material_id = row.get("material_id")
        if role not in eligible_roles or material_id is None:
            continue
        for hybrid_position, candidate in enumerate(candidates, 1):
            candidate_role_value = candidate.get("role") or "unclassified"
            candidate_role = (candidate_role_value if candidate_role_value in _KNOWN_ROLES
                              else "unclassified")
            if candidate.get("material_id") != material_id or candidate_role not in eligible_roles:
                continue
            anchor = candidate
            metadata.update({
                "material_id": material_id,
                "chunk_id": str(candidate["chunk_id"]),
                "original_dense_rank": dense_rank,
                "original_hybrid_position": hybrid_position,
                "promoted": hybrid_position != 1,
            })
            break
        if anchor is not None:
            break
    if anchor is None:
        return list(candidates), metadata
    anchor.setdefault("trace", {}).setdefault("semantic_anchors", {})[stream] = deepcopy(metadata)
    return [anchor, *(item for item in candidates if item is not anchor)], metadata


def _attach_projection(store, items: list[dict]) -> None:
    chunk_ids = list(dict.fromkeys(str(item["chunk_id"]) for item in items))
    if not chunk_ids:
        return
    projections = store.context_projection(chunk_ids, max_per_chunk=2)
    if not isinstance(projections, dict):
        projections = {}
    for item in items:
        contexts = projections.get(str(item["chunk_id"]), [])
        if not isinstance(contexts, list):
            contexts = []
        item["claim_contexts"] = [deepcopy(context) for context in contexts[:2]
                                   if isinstance(context, dict)]

    rows = store.rows(
        """SELECT selected.id AS parent_chunk_id, neighbor.id AS chunk_id,
                  neighbor.material_id,neighbor.revision_id,neighbor.text,
                  neighbor.start_offset,neighbor.end_offset,neighbor.relation
           FROM chunks selected
           JOIN LATERAL (
             (SELECT n.id,n.material_id,n.revision_id,n.text,n.start_offset,n.end_offset,
                     'previous'::text AS relation
                FROM chunks n WHERE n.material_id=selected.material_id
                  AND n.revision_id=selected.revision_id AND n.start_offset<selected.start_offset
                ORDER BY n.start_offset DESC LIMIT 1)
             UNION ALL
             (SELECT n.id,n.material_id,n.revision_id,n.text,n.start_offset,n.end_offset,
                     'next'::text AS relation
                FROM chunks n WHERE n.material_id=selected.material_id
                  AND n.revision_id=selected.revision_id AND n.start_offset>selected.start_offset
                ORDER BY n.start_offset ASC LIMIT 1)
           ) AS neighbor ON TRUE
           WHERE selected.id=ANY(%s::text[])
           ORDER BY selected.id,neighbor.relation""",
        (chunk_ids,),
    )
    by_parent = {}
    primary = {str(item["chunk_id"]): item for item in items}
    for neighbor in rows:
        parent_id = str(neighbor.get("parent_chunk_id") or "")
        item = primary.get(parent_id)
        if item is None:
            continue
        if (neighbor.get("material_id") != item.get("material_id")
                or neighbor.get("revision_id") != item.get("revision_id")
                or str(neighbor.get("chunk_id")) == parent_id
                or not isinstance(neighbor.get("text"), str)
                or type(neighbor.get("start_offset")) is not int
                or type(neighbor.get("end_offset")) is not int
                or neighbor["start_offset"] < 0
                or neighbor["end_offset"] <= neighbor["start_offset"]):
            continue
        by_parent.setdefault(parent_id, []).append({
            "chunk_id": str(neighbor["chunk_id"]),
            "material_id": neighbor["material_id"],
            "revision_id": neighbor["revision_id"],
            "text": neighbor["text"],
            "start_offset": neighbor["start_offset"],
            "end_offset": neighbor["end_offset"],
            "relation": neighbor.get("relation"),
        })
    for item in items:
        item["neighbor_evidence"] = by_parent.get(str(item["chunk_id"]), [])[:2]


class Retriever:
    def __init__(self, store, embedding):
        self.store = store
        self.embedding = embedding

    def search(self, query, category="", limit=12, purpose="auto"):
        limit = max(1, min(int(limit), 30))
        if not isinstance(query, str):
            raise ValueError("Query required")
        query = _normalized_query(query)[:2000]
        if not query:
            raise ValueError("Query required")
        if not isinstance(category, str):
            raise ValueError("Category must be a string")

        purpose_trace = _purpose_decision(query, purpose)
        resolved_purpose = purpose_trace["resolved"]
        features = _lexical_features(query)
        lexical_query = _websearch_query(features)
        title_patterns = _title_patterns(features)
        topics = _canonical_topics(query)
        topic_norms = [f"topic:v1:{topic['key']}" for topic in topics]
        topic_alias_matches = []
        seen_topic_aliases = set()
        for topic in topics:
            for alias in topic["aliases"]:
                pattern = _ilike_pattern(alias).casefold()
                if pattern not in seen_topic_aliases:
                    topic_alias_matches.append((pattern, topic["key"]))
                    seen_topic_aliases.add(pattern)
                if len(topic_alias_matches) >= 24:
                    break
            if len(topic_alias_matches) >= 24:
                break
        topic_alias_patterns = [pattern for pattern, _ in topic_alias_matches]
        topic_alias_keys = [key for _, key in topic_alias_matches]

        fields = _DENSE_PAYLOAD_FIELDS
        common = " FROM chunks c JOIN materials m ON m.id=c.material_id "
        category_args = (category, category)
        visible_role = "COALESCE(m.role,'unclassified') <> 'out_of_scope'"
        with self.store.connection() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            scope_sql, scope_args = build_dense_scope_count_query(category)
            scope_row = connection.execute(scope_sql, scope_args).fetchone()
            scope_count = (
                scope_row.get("visible_chunk_count")
                if isinstance(scope_row, dict) else None
            )
            if type(scope_count) is not int or scope_count < 0:
                raise RetrievalCapacityError(
                    "retrieval_scope_count_invalid", scope_count=scope_count,
                )
            if scope_count > DENSE_EXACT_SCAN_CAP:
                raise RetrievalCapacityError(
                    "retrieval_capacity_exceeded", scope_count=scope_count,
                )

            embedding_vector, cache_hit, embedding_metadata = _query_embedding(
                self.embedding, query, self.store,
            )
            dense_sql, dense_args = build_exact_dense_candidates_query(category, embedding_vector)
            dense = connection.execute(dense_sql, dense_args).fetchall()
        dense_candidate_trace = {
            "method": "exact_dense_scan",
            "scope_count": scope_count,
            "scope_cap": DENSE_EXACT_SCAN_CAP,
            "candidate_limit": DENSE_CANDIDATE_LIMIT,
            "policy_version": POLICY_VERSION,
        }
        lexical = []
        if lexical_query:
            lexical = self.store.rows(
                "SELECT " + fields + common
                + "WHERE (%s='' OR m.category=%s) AND " + visible_role
                + " AND c.search_vector @@ websearch_to_tsquery('english',%s)"
                + " ORDER BY ts_rank_cd(c.search_vector,websearch_to_tsquery('english',%s)) DESC,c.id LIMIT 40",
                (*category_args, lexical_query, lexical_query),
            )
        exact = []
        if title_patterns:
            exact = self.store.rows(
                "SELECT " + fields + common
                + "WHERE (%s='' OR m.category=%s) AND " + visible_role
                + " AND (m.title ILIKE ANY(%s::text[]) OR m.source ILIKE ANY(%s::text[]))"
                + " ORDER BY m.title,c.start_offset,c.id LIMIT 20",
                (*category_args, title_patterns, title_patterns),
            )
        graph = []
        if topics:
            graph_rows = self.store.rows(
                "WITH graph_candidates AS (SELECT " + fields
                + ",CASE WHEN s.normalized=ANY(%s::text[]) THEN s.normalized ELSE t.normalized END AS topic_normalized"
                + ",CASE WHEN s.normalized=ANY(%s::text[]) THEN s.kind ELSE t.kind END AS topic_kind"
                + ",COALESCE(e.relation_kind,'assertion') AS graph_relation_kind,e.relation AS graph_relation"
                + ",e.id AS graph_edge_id,cl.id AS graph_claim_id"
                + ",COALESCE(e.evidence_chunk_id,cl.chunk_id) AS graph_evidence_chunk_id"
                + ",CASE WHEN s.normalized=ANY(%s::text[]) THEN s.metadata->>'topic_key'"
                + " WHEN t.normalized=ANY(%s::text[]) THEN t.metadata->>'topic_key'"
                + " ELSE (SELECT match.topic_key FROM unnest(%s::text[],%s::text[]) AS match(pattern,topic_key)"
                + " WHERE lower(cl.quote) LIKE match.pattern ORDER BY length(match.pattern) DESC,match.topic_key LIMIT 1)"
                + " END AS graph_topic_key"
                + ",ts_rank_cd(c.search_vector,websearch_to_tsquery('english',%s)) AS query_relevance"
                + common
                + " JOIN revisions r ON r.id=c.revision_id"
                + " JOIN edges e ON e.material_id=m.id"
                + " JOIN claims cl ON cl.id=e.claim_id"
                + " JOIN entities s ON s.id=e.source JOIN entities t ON t.id=e.target"
                + " WHERE (%s='' OR m.category=%s) AND " + visible_role
                + " AND ((COALESCE(e.relation_kind,'assertion')='assertion' AND cl.chunk_id=c.id"
                + " AND length(cl.quote)>=16 AND position(cl.quote in c.text)>0"
                + " AND lower(cl.quote) LIKE ANY(%s::text[]))"
                + " OR (e.relation_kind='topic' AND e.relation='mentions' AND e.evidence_chunk_id=c.id"
                + " AND e.metadata->>'scope'='evidence_topic_not_property'"
                + " AND COALESCE(e.metadata->>'quote','')<>''"
                + " AND position(e.metadata->>'quote' in c.text)>0"
                + " AND e.metadata->>'revision_sha256'=r.sha256"
                + " AND CASE WHEN e.metadata->>'source_start' ~ '^[0-9]{1,10}$'"
                + " AND e.metadata->>'source_end' ~ '^[0-9]{1,10}$' THEN"
                + " CASE WHEN (e.metadata->>'source_start')::bigint>=c.start_offset"
                + " AND (e.metadata->>'source_end')::bigint<=c.end_offset THEN"
                + " CASE WHEN (e.metadata->>'source_end')::bigint-(e.metadata->>'source_start')::bigint"
                + " =char_length(e.metadata->>'quote') THEN"
                + " substring(c.text FROM ((e.metadata->>'source_start')::bigint-c.start_offset+1)::integer"
                + " FOR char_length(e.metadata->>'quote'))=e.metadata->>'quote'"
                + " ELSE FALSE END ELSE FALSE END ELSE FALSE END"
                + " AND (s.normalized=ANY(%s::text[]) OR t.normalized=ANY(%s::text[]))))"
                + "), graph_ranked AS (SELECT graph_candidates.*"
                + ",row_number() OVER (PARTITION BY chunk_id ORDER BY query_relevance DESC,CASE WHEN graph_relation_kind='topic' THEN 0 ELSE 1 END,graph_edge_id) AS graph_proof_rank"
                + ",count(*) OVER (PARTITION BY chunk_id) AS graph_proof_count FROM graph_candidates)"
                + ", graph_candidate_pool AS (SELECT DISTINCT ON (chunk_id) chunk_id,query_relevance,graph_edge_id"
                + " FROM graph_ranked ORDER BY chunk_id,query_relevance DESC,graph_edge_id)"
                + ", graph_limited AS (SELECT chunk_id FROM graph_candidate_pool ORDER BY query_relevance DESC,chunk_id LIMIT 31)"
                + " SELECT graph_ranked.* FROM graph_ranked JOIN graph_limited USING (chunk_id)"
                + " WHERE graph_proof_rank<=2 ORDER BY query_relevance DESC,chunk_id,graph_proof_rank",
                (topic_norms, topic_norms, topic_norms, topic_norms, topic_alias_patterns,
                 topic_alias_keys, lexical_query, *category_args, topic_alias_patterns,
                 topic_norms, topic_norms),
            )
            graph_candidates = _collapse_graph_rows(graph_rows)
            graph_truncated = len(graph_candidates) > 30
            graph = graph_candidates[:30]
        else:
            graph_truncated = False

        channels = {"dense": dense, "lexical": lexical, "exact": exact, "graph": graph}
        candidates = _merge_ranked_channels(
            channels, topics, resolved_purpose, purpose_trace["uncertain"], features
        )
        items, locators, source_candidates = [], [], []
        for item in candidates:
            if item.get("role") == "out_of_scope":
                continue
            grounded_graph = bool(item["trace"].get("graph_rank"))
            if item["role"] == "source_navigation":
                item["result_kind"] = "locator"
                locators.append(item)
                source_candidates.append(item)
            elif resolved_purpose == "discovery" and item['role']=='unclassified' and not grounded_graph:
                item["result_kind"] = "locator"
                item["role_policy"]["is_locator"] = True
                item["role_policy"]["evidence_authority"] = 0.0
                item["role_policy"]["use_ceiling"] = "source_locator_until_quote_grounded"
                locators.append(item)
                source_candidates.append(item)
            else:
                if resolved_purpose == "discovery":
                    item["evidence_scope"] = "source_assertion"
                item["result_kind"] = "evidence"
                items.append(item)
                source_candidates.append(item)

        items, item_anchor = _semantic_anchor_order(items, dense, "items")
        items = _diverse_with_backfill(items, limit)
        locators = _diverse_with_backfill(locators, limit)
        source_candidates, source_anchor = _semantic_anchor_order(
            source_candidates, dense, "source_results", include_navigation=True,
        )
        source_results = _diverse_with_backfill(source_candidates, limit)
        all_selected = items + locators + source_results
        _attach_projection(self.store, all_selected)
        for item in all_selected:
            item["trace"].update({
                "query_embedding_cache_hit": cache_hit,
                "query_embedding_task": embedding_metadata.get("task", "search_query"),
                "purpose_rule": purpose_trace["rule"],
                "purpose_uncertain": purpose_trace["uncertain"],
                "dense_candidate_method": dense_candidate_trace["method"],
                "dense_scope_count": dense_candidate_trace["scope_count"],
                "dense_scope_cap": dense_candidate_trace["scope_cap"],
                "dense_candidate_limit": dense_candidate_trace["candidate_limit"],
                "dense_candidate_policy_version": dense_candidate_trace["policy_version"],
                "graph_truncated": graph_truncated,
                "graph_candidate_limit": 30,
                "graph_discarded_link_count": item.get("graph_discarded_link_count", 0),
            })

        return {
            "query": query,
            "purpose": resolved_purpose,
            "purpose_trace": purpose_trace,
            "items": items,
            "locators": locators,
            "source_results": source_results,
            "semantic_anchors": {"items": item_anchor, "source_results": source_anchor},
            "dense_candidate_trace": dense_candidate_trace,
            "channels": {key: len(rows) for key, rows in channels.items()},
            "graph_truncated": graph_truncated,
            "graph_trace": {
                "candidate_limit": 30,
                "fetch_limit": 31,
                "fetched_unique_candidates": len(graph_candidates) if topics else 0,
                "returned_candidates": len(graph),
                "truncated": graph_truncated,
            },
            "policy_version": POLICY_VERSION,
            "trace_id": uuid.uuid4().hex,
            "query_embedding_cache_hit": cache_hit,
            "query_embedding_usage": embedding_metadata.get("usage", {}),
            "limitations": [
                "Retrieval ranks source evidence; it does not establish physical buildability or measured performance.",
                "Unclassified sources are marked needs_review and design use of operations sources is limited to workflow/interface references.",
            ],
        }
