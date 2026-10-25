from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from dse_knowledge import retrieval
from dse_knowledge.retrieval import Retriever


class FakeEmbedding:
    provider = "test-provider"
    model = "test-model"
    dimensions = 768

    def __init__(self):
        self.calls = []
        self.last_metadata = {}

    def embed(self, texts, task="document"):
        self.calls.append((list(texts), task))
        self.last_metadata = {
            "provider": self.provider,
            "model": self.model,
            "dimensions": self.dimensions,
            "task": task,
            "usage": {"prompt_tokens": 7, "total_tokens": 7},
        }
        return [[0.0] * 768 for _ in texts]


class FakeStore:
    def __init__(self, *, dense=(), lexical=(), exact=(), graph=(), neighbors=(), contexts=None):
        self.dense = list(dense)
        self.lexical = list(lexical)
        self.exact = list(exact)
        self.graph = list(graph)
        self.neighbors = list(neighbors)
        self.contexts = contexts or {}
        self.queries = []
        self.invocations = []
        self.context_projection_calls = []

    def rows(self, sql, args=()):
        self.queries.append((sql, args))
        if "JOIN edges e" in sql:
            return deepcopy(self.graph)
        if "c.embedding <=>" in sql:
            return deepcopy(self.dense)
        if "c.search_vector @@" in sql:
            return deepcopy(self.lexical)
        if "m.title ILIKE ANY" in sql:
            return deepcopy(self.exact)
        if "LATERAL" in sql:
            return deepcopy(self.neighbors)
        return []

    def context_projection(self, chunk_ids, max_per_chunk=2):
        self.context_projection_calls.append((list(chunk_ids), max_per_chunk))
        return deepcopy(self.contexts)

    def invocation(self, provider, purpose, metadata):
        self.invocations.append((provider, purpose, deepcopy(metadata)))


def row(chunk_id, *, role="core_technical", material_id=None, text=None, **extra):
    return {
        "chunk_id": chunk_id,
        "material_id": material_id or f"material-{chunk_id}",
        "revision_id": f"revision-{chunk_id}",
        "start_offset": 0,
        "end_offset": 40,
        "text": text or f"Evidence passage for {chunk_id} including KV cache throughput details.",
        "title": f"Title {chunk_id}",
        "url": f"https://example.test/{chunk_id}",
        "category": "compiler_kernel",
        "scope": "fulltext",
        "role": role,
        "role_metadata": {"assessment": "fixture"},
        **extra,
    }


@pytest.fixture(autouse=True)
def clear_query_embedding_cache(monkeypatch):
    cache = getattr(retrieval, "_QUERY_EMBEDDINGS", None)
    if cache is not None:
        cache.clear()
    yield
    cache = getattr(retrieval, "_QUERY_EMBEDDINGS", None)
    if cache is not None:
        cache.clear()


def test_lexical_query_uses_core_terms_phrase_and_identifiers_not_full_question():
    store = FakeStore(dense=[row("dense")])
    embedding = FakeEmbedding()
    Retriever(store, embedding).search(
        'Which official source explains "KV cache" throughput on H100 with vLLM?'
    )

    lexical_sql, lexical_args = next(
        (sql, args) for sql, args in store.queries if "c.search_vector @@" in sql
    )
    lexical_query = lexical_args[-1]
    assert '"KV cache"' in lexical_query
    assert "H100" in lexical_query
    assert "vLLM" in lexical_query
    assert "Which official source explains" not in lexical_query
    assert "OR" in lexical_query
    assert "%s" in lexical_sql
    assert "Which official source explains" not in lexical_sql


def test_purpose_auto_routes_and_excludes_out_of_scope_with_versioned_trace():
    store = FakeStore(
        dense=[
            row("core", role="core_technical"),
            row("ops", role="integration_operations"),
            row("oos", role="out_of_scope"),
        ]
    )
    result = Retriever(store, FakeEmbedding()).search(
        "How do I install the API and reproduce this in CI?", purpose="auto"
    )

    assert result["purpose"] == "operations"
    assert result["purpose_trace"]["resolved"] == "operations"
    assert result["policy_version"]
    assert {item["chunk_id"] for item in result["items"]} == {"core", "ops"}
    assert all(item["role"] != "out_of_scope" for item in result["items"])
    assert result["items"][0]["role"] == "core_technical"
    assert result["semantic_anchors"]["items"]["material_id"] == "material-core"
    assert next(item for item in result["items"] if item["role"] == "integration_operations")["role_policy"]["weight"] == 1.0
    retrieval_sql = [sql for sql, _ in store.queries if "FROM chunks c" in sql]
    assert retrieval_sql and all("out_of_scope" in sql for sql in retrieval_sql)


def test_ambiguous_auto_defaults_to_design_and_marks_uncertainty():
    result = Retriever(FakeStore(dense=[row("core")]), FakeEmbedding()).search(
        "Tell me about the result"
    )

    assert result["purpose"] == "design"
    assert result["purpose_trace"]["uncertain"] is True
    assert result["purpose_trace"]["rule"]


def test_auto_routes_document_discovery_and_korean_operations_queries():
    discover = Retriever(FakeStore(dense=[row("paper", role="core_technical")]), FakeEmbedding()).search(
        "List papers about KV cache"
    )
    operate = Retriever(FakeStore(dense=[row("setup", role="integration_operations")]), FakeEmbedding()).search(
        "CUDA 설치 방법"
    )

    assert discover["purpose"] == "discovery"
    assert discover["purpose_trace"]["uncertain"] is False
    assert operate["purpose"] == "operations"
    assert operate["purpose_trace"]["uncertain"] is False


def test_korean_technical_compound_is_not_discovery_and_explicit_mixed_doc_intent_is_versioned():
    technical = Retriever(FakeStore(dense=[row("core")]), FakeEmbedding()).search("한국어 자료구조의 캐시 효율")
    mixed = Retriever(FakeStore(dense=[row("guide")]), FakeEmbedding()).search(
        "Find API docs for installing CUDA"
    )

    assert technical["purpose"] == "design"
    assert technical["purpose_trace"]["uncertain"] is False
    assert mixed["purpose"] == "discovery"
    assert mixed["purpose_trace"]["rule"] == "auto_explicit_source_find_with_operations_context"
    assert mixed["purpose_trace"]["version"] == "purpose-policy/v1"


def test_operations_role_policy_is_preserved_after_dense_material_anchor():
    result = Retriever(
        FakeStore(dense=[
            row("core", role="core_technical"),
            row("method", role="supporting_method"),
            row("ops", role="integration_operations"),
        ]),
        FakeEmbedding(),
    ).search("install a kernel", purpose="operations")

    assert [item["chunk_id"] for item in result["items"]] == ["core", "ops", "method"]
    assert [item["role_policy"]["weight"] for item in result["items"]] == [0.8, 1.0, 0.7]


def test_design_moves_navigation_to_locators_and_caps_operations_use():
    store = FakeStore(
        dense=[
            row("ops", role="integration_operations"),
            row("nav", role="source_navigation"),
            row("method", role="supporting_method"),
            row("core", role="core_technical"),
        ]
    )
    result = Retriever(store, FakeEmbedding()).search("kernel design", purpose="design")

    assert [item["chunk_id"] for item in result["items"]] == ["ops", "core", "method"]
    assert [item["chunk_id"] for item in result["locators"]] == ["nav"]
    ops = next(item for item in result["items"] if item["chunk_id"] == "ops")
    assert ops["role_policy"]["use_ceiling"] == "workflow_or_interface_reference"
    assert ops["role_policy"]["weight"] == 0.65
    assert result["semantic_anchors"]["items"]["material_id"] == "material-ops"
    assert result["semantic_anchors"]["items"]["authority_changed"] is False
    nav = result["locators"][0]
    assert nav["role_policy"]["evidence_authority"] == 0.0
    assert nav["chunk_id"] not in {item["chunk_id"] for item in result["items"]}
    assert ops["retrieval_policy"] == result["policy_version"]
    assert ops["trace"]["role_weight"] == 0.65


def test_locator_order_uses_query_relevance_while_evidence_authority_stays_zero():
    generic = row("a-generic", role="source_navigation", title="General index", text="General reference index.")
    relevant = row("z-relevant", role="source_navigation", title="H100 memory bandwidth guide",
                   text="H100 memory bandwidth and capacity reference.")
    store = FakeStore(dense=[generic, relevant], exact=[relevant])
    result = Retriever(store, FakeEmbedding()).search("H100 memory bandwidth", purpose="design")

    assert [item["chunk_id"] for item in result["locators"]] == ["z-relevant", "a-generic"]
    policy = result["locators"][0]["role_policy"]
    assert policy["weight"] > 0
    assert policy["evidence_authority"] == 0.0
    assert policy["is_locator"] is True


def test_discovery_marks_unclassified_needs_review_and_returns_navigation_as_locator():
    result = Retriever(
        FakeStore(dense=[row("unknown", role="unclassified"), row("nav", role="source_navigation")]),
        FakeEmbedding(),
    ).search("list feature map", purpose="discovery")

    unknown = next(item for item in result["locators"] if item["chunk_id"] == "unknown")
    assert unknown["role_policy"]["needs_review"] is True
    assert unknown["role_policy"]["evidence_ceiling"] == "needs_review"
    assert unknown["role_policy"]["evidence_authority"] == 0.0
    assert {item["chunk_id"] for item in result["locators"]} == {"nav", "unknown"}


def test_discovery_keeps_substantive_source_passages_without_requiring_graph_membership():
    result=Retriever(FakeStore(dense=[row('core'),row('nav',role='source_navigation')]),FakeEmbedding()).search('papers about kernels',purpose='discovery')
    assert [x['chunk_id'] for x in result['items']]==['core']
    assert result['items'][0]['evidence_scope']=='source_assertion'
    assert [x['chunk_id'] for x in result['locators']]==['nav']


def test_semantic_anchor_selects_dense_material_then_its_best_hybrid_passage(monkeypatch):
    topic = {"key": "kv-cache", "label": "KV cache", "kind": "concept", "alias": "KV cache"}
    monkeypatch.setitem(__import__("sys").modules, "dse_knowledge.knowledge",
                        SimpleNamespace(canonical_topic_mentions=lambda query: [topic]))
    dense = [
        row("a-dense", material_id="source-a"),
        row("a-hybrid", material_id="source-a"),
        row("b-hybrid", material_id="source-b"),
    ]
    lexical = [dense[2], dense[1], dense[0]]
    exact = [dense[2], dense[1]]
    graph = [row("b-hybrid", material_id="source-b", topic_normalized="topic:v1:kv-cache",
                 topic_kind="concept", graph_edge_id="edge-b", graph_claim_id="claim-b",
                 graph_relation_kind="topic", graph_relation="mentions",
                 graph_evidence_chunk_id="proof-b", graph_topic_key="kv-cache")]

    result = Retriever(FakeStore(dense=dense, lexical=lexical, exact=exact, graph=graph),
                       FakeEmbedding()).search("KV cache throughput")

    assert result["items"][0]["chunk_id"] == "a-hybrid"
    anchor = result["semantic_anchors"]["items"]
    assert anchor == {
        "material_id": "source-a", "chunk_id": "a-hybrid",
        "original_dense_rank": 1, "original_hybrid_position": 2,
        "promoted": True, "selection_basis": "dense_material_then_best_hybrid_passage",
        "authority_changed": False,
    }
    assert result["items"][0]["trace"]["semantic_anchors"]["items"] == anchor
    assert result["policy_version"] == "retrieval-policy/v2.1"


def test_mixed_source_results_anchor_navigation_safely_with_unique_top_k_slots():
    store = FakeStore(dense=[
        row("unknown", role="unclassified", material_id="source-unknown"),
        row("nav", role="source_navigation", material_id="source-nav"),
        row("technical", role="core_technical", material_id="source-tech"),
        row("out", role="out_of_scope", material_id="source-out"),
    ])

    result = Retriever(store, FakeEmbedding()).search("KV cache source", limit=2)

    assert [item["chunk_id"] for item in result["source_results"]] == ["nav", "technical"]
    assert result["source_results"][0]["result_kind"] == "locator"
    assert result["source_results"][0]["role_policy"]["evidence_authority"] == 0.0
    assert result["semantic_anchors"]["source_results"] == {
        "material_id": "source-nav", "chunk_id": "nav",
        "original_dense_rank": 2, "original_hybrid_position": 1,
        "promoted": False, "selection_basis": "dense_material_then_best_hybrid_passage",
        "authority_changed": False,
    }
    assert result["items"][0]["chunk_id"] == "technical"
    assert result["semantic_anchors"]["items"]["material_id"] == "source-tech"
    unknown = next(item for item in result["items"] if item["chunk_id"] == "unknown")
    assert unknown["role_policy"]["needs_review"] is True
    assert "items" not in unknown["trace"].get("semantic_anchors", {})
    chunk_ids = [item["chunk_id"] for item in result["source_results"]]
    assert len(chunk_ids) == len(set(chunk_ids)) == 2
    assert all(item["role"] != "out_of_scope" for item in result["source_results"])


def test_topic_graph_query_is_canonical_bounded_and_quote_grounded(monkeypatch):
    topic = {"key": "kv-cache", "label": "KV cache", "kind": "concept", "alias": "KV cache"}
    monkeypatch.setitem(
        __import__("sys").modules,
        "dse_knowledge.knowledge",
        SimpleNamespace(canonical_topic_mentions=lambda query: [topic]),
    )
    store = FakeStore(dense=[row("dense")], graph=[row("topic-hit")])
    result = Retriever(store, FakeEmbedding()).search("KV cache throughput")

    graph_sql, graph_args = next((sql, args) for sql, args in store.queries if "JOIN edges e" in sql)
    assert graph_args[0] == ["topic:v1:kv-cache"]
    assert graph_sql.count("%s") == len(graph_args)
    assert "relation_kind" in graph_sql
    assert "e.evidence_chunk_id=c.id" in graph_sql
    assert "e.metadata->>'scope'='evidence_topic_not_property'" in graph_sql
    assert "position(e.metadata->>'quote' in c.text)>0" in graph_sql
    assert "source_start" in graph_sql and "source_end" in graph_sql
    assert "revision_sha256" in graph_sql
    assert "query_relevance DESC" in graph_sql
    assert "limit 31" in graph_sql.lower()
    graph_result = next(item for item in result["items"] if item["chunk_id"] == "topic-hit")
    assert graph_result["trace"]["graph_rank"] == 1
    assert result["graph_trace"]["truncated"] is False
    assert result["graph_truncated"] is False


def test_graph_channel_is_skipped_without_canonical_topic_mentions(monkeypatch):
    monkeypatch.setitem(
        __import__("sys").modules,
        "dse_knowledge.knowledge",
        SimpleNamespace(canonical_topic_mentions=lambda query: []),
    )
    store = FakeStore(dense=[row("dense")])
    result = Retriever(store, FakeEmbedding()).search("GPU LLM design details")

    assert not any("JOIN edges e" in sql for sql, _ in store.queries)
    assert result["channels"]["graph"] == 0


def test_diversity_cap_backfills_to_requested_limit():
    dense = [row(f"a-{i}", material_id="source-a") for i in range(4)]
    dense += [row(f"b-{i}", material_id="source-b") for i in range(4)]
    result = Retriever(FakeStore(dense=dense), FakeEmbedding()).search("kernel", limit=6)

    assert len(result["items"]) == 6
    assert sum(item["material_id"] == "source-a" for item in result["items"]) == 3
    assert sum(item["material_id"] == "source-b" for item in result["items"]) == 3

    backfilled = Retriever(FakeStore(dense=dense), FakeEmbedding()).search("kernel", limit=7)
    assert len(backfilled["items"]) == 7


def test_result_has_two_compact_context_refs_and_separate_citation_safe_neighbors():
    contexts = {
        "main": [
            {"claim_id": "claim-1", "context": {"schema_version": "claim-context/v1"}},
            {"claim_id": "claim-2", "context": {"schema_version": "claim-context/v1"}},
            {"claim_id": "claim-3", "context": {"schema_version": "claim-context/v1"}},
        ]
    }
    neighbors = [
        {
            "parent_chunk_id": "main",
            "chunk_id": "previous",
            "material_id": "material-main",
            "revision_id": "revision-main",
            "text": "Previous chunk text.",
            "start_offset": 0,
            "end_offset": 55,
            "relation": "previous",
        },
        {
            "parent_chunk_id": "main",
            "chunk_id": "next",
            "material_id": "material-main",
            "revision_id": "revision-main",
            "text": "Next chunk text.",
            "start_offset": 60,
            "end_offset": 100,
            "relation": "next",
        },
    ]
    store = FakeStore(dense=[row("main", material_id="material-main", revision_id="revision-main",
                                start_offset=40, end_offset=80, text="Main chunk text.")],
                      neighbors=neighbors, contexts=contexts)
    result = Retriever(store, FakeEmbedding()).search("main")
    item = result["items"][0]

    assert store.context_projection_calls == [(["main"], 2)]
    assert len(item["claim_contexts"]) == 2
    assert item["text"] == "Main chunk text."
    assert [neighbor["chunk_id"] for neighbor in item["neighbor_evidence"]] == ["previous", "next"]
    assert all(neighbor["chunk_id"] != item["chunk_id"] for neighbor in item["neighbor_evidence"])
    assert all("start_offset" in neighbor and "end_offset" in neighbor for neighbor in item["neighbor_evidence"])
    neighbor_sql = next(sql for sql, _ in store.queries if "LATERAL" in sql)
    assert "n.start_offset<selected.start_offset" in neighbor_sql
    assert "n.start_offset>selected.start_offset" in neighbor_sql
    assert "n.end_offset<=selected.start_offset" not in neighbor_sql


def test_query_embedding_cache_hit_has_zero_usage_and_does_not_call_provider(monkeypatch):
    store = FakeStore(dense=[row("main")])
    embedding = FakeEmbedding()
    retriever = Retriever(store, embedding)
    first = retriever.search("  KV   cache  ")
    second = retriever.search("KV cache")

    assert len(embedding.calls) == 1
    assert first["trace_id"] != second["trace_id"]
    assert store.invocations[0][2]["usage"]["total_tokens"] == 7
    assert store.invocations[1][2]["cache_hit"] is True
    assert store.invocations[1][2]["usage"] == {}
    assert store.invocations[1][2]["provider_usage_recorded"] is False
    assert sum("c.embedding <=>" in sql for sql, _ in store.queries) == 2


def test_query_embedding_cache_preserves_case_sensitive_unit_tokens():
    store = FakeStore(dense=[row("main")])
    embedding = FakeEmbedding()
    retriever = Retriever(store, embedding)

    first = retriever.search("mJ energy")
    second = retriever.search("MJ energy")

    assert len(embedding.calls) == 2
    assert first["query_embedding_cache_hit"] is False
    assert second["query_embedding_cache_hit"] is False


def test_failed_usage_ledger_write_does_not_publish_paid_embedding_to_cache():
    class FailingInvocationStore(FakeStore):
        def __init__(self):
            super().__init__(dense=[row("main")])
            self.fail_next_provider_usage = True

        def invocation(self, provider, purpose, metadata):
            if not metadata.get("cache_hit") and self.fail_next_provider_usage:
                self.fail_next_provider_usage = False
                raise OSError("usage ledger unavailable")
            super().invocation(provider, purpose, metadata)

    store = FailingInvocationStore()
    embedding = FakeEmbedding()
    retriever = Retriever(store, embedding)
    with pytest.raises(OSError, match="usage ledger unavailable"):
        retriever.search("durable usage first")
    assert len(retrieval._QUERY_EMBEDDINGS) == 0

    second = retriever.search("durable usage first")
    third = retriever.search("durable usage first")
    assert len(embedding.calls) == 2
    assert second["query_embedding_cache_hit"] is False
    assert third["query_embedding_cache_hit"] is True
    assert store.invocations[0][2]["usage"]["total_tokens"] == 7
    assert store.invocations[1][2]["usage"] == {}


def test_graph_candidates_return_bounded_provenance_and_discard_count(monkeypatch):
    topic = {"key": "kv-cache", "label": "KV cache", "kind": "concept", "alias": "KV cache"}
    monkeypatch.setitem(__import__("sys").modules, "dse_knowledge.knowledge",
                        SimpleNamespace(canonical_topic_mentions=lambda query: [topic]))
    graph_rows = [row("same-chunk", topic_normalized="topic:v1:kv-cache", topic_kind="concept",
                      graph_proof_rank=rank, graph_proof_count=3,
                      graph_edge_id=f"edge-{rank}", graph_claim_id=f"claim-{rank}",
                      graph_relation_kind="topic", graph_relation="mentions", graph_evidence_chunk_id="proof-chunk",
                      graph_topic_key="kv-cache") for rank in (1, 2, 3)]
    store = FakeStore(dense=[row("same-chunk")], graph=graph_rows)

    result = Retriever(store, FakeEmbedding()).search("KV cache throughput")
    item = next(item for item in result["items"] if item["chunk_id"] == "same-chunk")

    assert len(item["graph_provenance"]) == 2
    assert item["graph_provenance"][0] == {
        "relation_kind": "topic", "relation": "mentions", "edge_id": "edge-1", "claim_id": "claim-1",
        "evidence_chunk_id": "proof-chunk", "topic_key": "kv-cache",
    }
    assert item["trace"]["graph_discarded_link_count"] == 1


def test_graph_fetches_one_extra_unique_candidate_and_reports_truncation(monkeypatch):
    topic = {"key": "kv-cache", "label": "KV cache", "kind": "concept", "alias": "KV cache"}
    monkeypatch.setitem(__import__("sys").modules, "dse_knowledge.knowledge",
                        SimpleNamespace(canonical_topic_mentions=lambda query: [topic]))
    graph_rows = [row(f"graph-{index:02}", topic_normalized="topic:v1:kv-cache", topic_kind="concept",
                      graph_proof_rank=1, graph_proof_count=1, graph_edge_id=f"edge-{index:02}",
                      graph_claim_id=f"claim-{index:02}", graph_relation_kind="topic", graph_relation="mentions",
                      graph_evidence_chunk_id=f"proof-{index:02}", graph_topic_key="kv-cache")
                  for index in range(31)]
    store = FakeStore(graph=graph_rows)

    result = Retriever(store, FakeEmbedding()).search("KV cache throughput")

    graph_sql = next(sql for sql, _ in store.queries if "JOIN edges e" in sql)
    assert "limit 31" in graph_sql.lower()
    assert result["channels"]["graph"] == 30
    assert result["graph_truncated"] is True
    assert result["graph_trace"]["truncated"] is True
    assert result["graph_trace"]["fetched_unique_candidates"] == 31
    assert all(item["trace"]["graph_truncated"] is True for item in result["items"])


def test_query_embedding_cache_expires_and_separates_model_and_dimensions(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(retrieval.time, "monotonic", lambda: now[0])
    store = FakeStore(dense=[row("main")])
    embedding = FakeEmbedding()
    retriever = Retriever(store, embedding)

    retriever.search("same query")
    retriever.search("same query")
    embedding.model = "other-model"
    retriever.search("same query")
    embedding.dimensions = 384
    retriever.search("same query")
    now[0] += 301
    retriever.search("same query")

    assert len(embedding.calls) == 4
    assert all(task == "search_query" for _, task in embedding.calls)


def test_query_embedding_cache_is_bounded_lru_of_128(monkeypatch):
    store = FakeStore()
    embedding = FakeEmbedding()
    retriever = Retriever(store, embedding)

    for index in range(128):
        retriever.search(f"cache query {index}")
    retriever.search("cache query 0")  # Refresh the least recently used candidate.
    retriever.search("cache query 128")  # Evicts query 1.
    retriever.search("cache query 0")  # Still cached after its LRU refresh.
    retriever.search("cache query 1")  # The evicted query must call the provider again.

    assert len(embedding.calls) == 130
    assert len(retrieval._QUERY_EMBEDDINGS) == 128
