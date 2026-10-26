from contextlib import contextmanager
from copy import deepcopy
import hashlib
from types import SimpleNamespace

import pytest

from dse_knowledge.config import Settings
from dse_knowledge.db import Store
from dse_knowledge.retrieval import Retriever, RetrievalModeError, RetrievalUnavailableError


class FakeConnection:
    def __init__(self, manifest=None, hydration=()):
        self.manifest = manifest or {
            "corpus_hash": "a" * 32, "source_count": 1, "chunk_count": 2,
            "canonical_source_count": 2, "canonical_chunk_count": 3,
        }
        self.hydration = list(hydration)
        self.queries = []

    def execute(self, sql, args=()):
        self.queries.append((sql, deepcopy(args)))
        if "contextual_corpus_manifest" in sql:
            return FakeCursor(self.manifest)
        if "contextual_candidate_hydration" in sql:
            return FakeCursor(rows=self.hydration)
        raise AssertionError("unexpected SQL in contextual store test")


class FakeCursor:
    def __init__(self, row=None, rows=()):
        self.row = deepcopy(row)
        self.rows = deepcopy(list(rows))

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class StoreConnection:
    def __init__(self, connection):
        self.connection_obj = connection

    @contextmanager
    def connection(self):
        yield self.connection_obj


def test_store_exposes_current_revision_manifest_and_hydrates_bound_candidates():
    current_rows = [{
        "chunk_id": "chunk-a", "material_id": "material-a", "revision_id": "revision-a",
        "start_offset": 0, "end_offset": 19, "text": "Canonical source text.",
        "title": "Canonical title", "url": "https://example.test/source", "source": "publisher",
        "category": "compiler_kernel", "scope": "fulltext", "role": "core_technical",
        "role_metadata": {"status": "reviewed"},
    }]
    connection = FakeConnection(hydration=current_rows)
    store = StoreConnection(connection)

    manifest = Store.contextual_corpus_manifest(store, connection=connection)
    hydrated = Store.contextual_hydrate_candidates(store, [{
        "chunk_id": "chunk-a", "material_id": "material-a", "revision_id": "revision-a",
    }], connection=connection)

    assert manifest == {
        "corpus_hash": "a" * 32, "source_count": 1, "chunk_count": 2,
        "canonical_source_count": 2, "canonical_chunk_count": 3,
    }
    assert hydrated == current_rows
    fingerprint_sql, _ = connection.queries[0]
    hydration_sql, hydration_args = connection.queries[1]
    assert "latest_revision" in fingerprint_sql and "latest_content AS MATERIALIZED" in fingerprint_sql
    assert "md5(r.content)" in fingerprint_sql and "JOIN latest_content" in fingerprint_sql
    assert "COALESCE(role,'unclassified') <> 'out_of_scope'" in fingerprint_sql
    assert "canonical_source_count" in fingerprint_sql and "canonical_chunk_count" in fingerprint_sql
    assert "md5(c.text)" not in fingerprint_sql
    assert "latest_revision" in hydration_sql
    assert "c.text" in hydration_sql and "m.role" in hydration_sql and "m.role_metadata" in hydration_sql
    assert "COALESCE(m.role,'unclassified') <> 'out_of_scope'" in hydration_sql
    assert "c.id=ANY(%s::text[])" in hydration_sql
    assert hydration_args == (["chunk-a"], ["chunk-a"])


def test_store_rejects_invalid_manifest_shape_instead_of_accepting_partial_corpus():
    connection = FakeConnection(manifest={"corpus_hash": "bad", "source_count": -1, "chunk_count": 0})
    store = StoreConnection(connection)

    with pytest.raises(ValueError, match="contextual_corpus_manifest_invalid"):
        Store.contextual_corpus_manifest(store, connection=connection)


def test_store_computes_normalized_content_sha_without_replacing_raw_revision_sha():
    content = "Parsed normalized content."
    raw_revision_sha = hashlib.sha256(b"raw HTML artifact").hexdigest()
    normalized_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()

    class SourceStore:
        def one(self, sql, args):
            return {
                "material_id": "material-a", "revision_id": "revision-a",
                "revision_sha256": raw_revision_sha, "normalized_content_sha256": None,
                "category": "compiler_kernel", "content": content,
            }

        def rows(self, sql, args):
            return [{"id": "chunk-a", "start_offset": 0, "end_offset": len(content), "text": content}]

    document = Store.contextual_document(SourceStore(), "material-a", "revision-a")

    assert document["revision_sha256"] == raw_revision_sha
    assert document["normalized_content_sha256"] == normalized_sha
    assert document["revision_sha256"] != document["normalized_content_sha256"]


class FakeSourceCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.sql = None
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def execute(self, sql):
        self.sql = sql

    def fetchmany(self, size):
        batch = self.rows[:size]
        del self.rows[:size]
        return batch


class FakeSourceConnection:
    def __init__(self, rows):
        self.cursor_value = FakeSourceCursor(rows)
        self.cursor_name = None

    def cursor(self, name=None):
        self.cursor_name = name
        return self.cursor_value


def test_store_streams_normalized_hashes_and_detects_stale_stored_hash_metadata():
    content = "Parsed normalized content."
    raw_revision_sha = hashlib.sha256(b"raw HTML artifact").hexdigest()
    normalized_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    rows = [{
        "material_id": "material-a", "revision_id": "revision-a",
        "revision_sha256": raw_revision_sha, "normalized_content_sha256": None,
        "content": content,
    }]
    connection = FakeSourceConnection(rows)
    store = StoreConnection(connection)

    manifest_hash = Store.contextual_normalized_content_manifest(store)

    piece = "\x1f".join(["material-a", "revision-a", raw_revision_sha, normalized_sha])
    assert manifest_hash == hashlib.sha256(piece.encode("utf-8")).hexdigest()
    assert connection.cursor_name == "dse_contextual_normalized_manifest"
    assert connection.cursor_value.closed
    assert "normalized_content_sha256" in connection.cursor_value.sql
    assert "COALESCE(m.role,'unclassified') <> 'out_of_scope'" in connection.cursor_value.sql

    mismatched = dict(rows[0], normalized_content_sha256="0" * 64)
    with pytest.raises(ValueError, match="contextual_normalized_content_hash_mismatch"):
        Store.contextual_normalized_content_manifest(StoreConnection(FakeSourceConnection([mismatched])))


def test_contextual_document_refs_share_baseline_eligible_role_filter():
    class SourceStore:
        def rows(self, sql, args=()):
            self.sql = sql
            return []

    store = SourceStore()

    assert Store.contextual_document_refs(store) == []
    assert "COALESCE(m.role,'unclassified') <> 'out_of_scope'" in store.sql


class SearchConnection:
    def __init__(self, store):
        self.store = store
        self.queries = []

    def execute(self, sql, args=()):
        self.queries.append((sql, deepcopy(args)))
        if "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY" in sql:
            return FakeCursor()
        if "visible_chunk_count" in sql:
            return FakeCursor({"visible_chunk_count": 3})
        raise AssertionError("unexpected PostgreSQL query for contextual-only mode")


class SearchStore:
    def __init__(self, rows):
        self.canonical = {row["chunk_id"]: deepcopy(row) for row in rows}
        self.connection_queries = []
        self.hydration_calls = []
        self.context_projection_calls = []
        self.invocations = []
        self.contexts = {
            "chunk-a": [{"claim_id": "claim-a", "context": {"conditions": ["original condition"]}}],
            "chunk-b": [{"claim_id": "claim-b", "context": {"conditions": ["original condition B"]}}],
        }

    @contextmanager
    def connection(self):
        connection = SearchConnection(self)
        self.connection_queries.append(connection)
        yield connection

    def contextual_corpus_manifest(self, connection=None):
        return {"corpus_hash": "a" * 32, "source_count": 1, "chunk_count": 3}

    def contextual_hydrate_candidates(self, candidates, connection=None):
        self.hydration_calls.append(deepcopy(candidates))
        hydrated = []
        for candidate in candidates:
            row = self.canonical.get(candidate["chunk_id"])
            if row is None:
                raise ValueError("contextual_candidate_stale")
            if (row["material_id"], row["revision_id"]) != (candidate["material_id"], candidate["revision_id"]):
                raise ValueError("contextual_candidate_stale")
            hydrated.append(deepcopy(row))
        return hydrated

    def rows(self, sql, args=()):
        if "LATERAL" in sql or "JOIN edges e" in sql or "c.search_vector @@" in sql or "m.title ILIKE ANY" in sql:
            return []
        raise AssertionError("unexpected PostgreSQL query in fixture")

    def context_projection(self, chunk_ids, max_per_chunk=2):
        self.context_projection_calls.append(list(chunk_ids))
        return {chunk_id: deepcopy(self.contexts.get(chunk_id, [])) for chunk_id in chunk_ids}

    def invocation(self, provider, purpose, metadata):
        self.invocations.append((provider, purpose, deepcopy(metadata)))


class SearchEmbedding:
    provider = "deepinfra"
    model = "google/embeddinggemma-2"
    dimensions = 768

    def __init__(self):
        self.last_metadata = {}

    def embed(self, texts, task="document"):
        self.last_metadata = {
            "provider": self.provider, "model": self.model, "dimensions": self.dimensions,
            "task": task, "usage": {"total_tokens": 3},
        }
        return [[1.0] + [0.0] * 767 for _ in texts]


def canonical_rows():
    return [
        {
            "chunk_id": "chunk-a", "material_id": "material-a", "revision_id": "revision-a",
            "start_offset": 0, "end_offset": 22, "text": "Canonical evidence A text.",
            "title": "Canonical title A", "url": "https://example.test/a", "source": "publisher A",
            "category": "compiler_kernel", "scope": "fulltext", "role": "core_technical",
            "role_metadata": {"reviewed": True},
        },
        {
            "chunk_id": "chunk-b", "material_id": "material-b", "revision_id": "revision-b",
            "start_offset": 0, "end_offset": 22, "text": "Canonical evidence B text.",
            "title": "Canonical title B", "url": "https://example.test/b", "source": "publisher B",
            "category": "compiler_kernel", "scope": "fulltext", "role": "core_technical",
            "role_metadata": {"reviewed": True},
        },
        {
            "chunk_id": "chunk-c", "material_id": "material-c", "revision_id": "revision-c",
            "start_offset": 0, "end_offset": 22, "text": "Canonical locator C text.",
            "title": "Canonical locator C", "url": "https://example.test/c", "source": "publisher C",
            "category": "compiler_kernel", "scope": "fulltext", "role": "source_navigation",
            "role_metadata": {"reviewed": True},
        },
    ]


class SearchIndex:
    def __init__(self):
        self.calls = []
        self.contexts = {
            "chunk-a": "generated hint A must stay private to ranking",
            "chunk-b": "generated hint B must stay private to ranking",
            "chunk-c": "generated locator hint must stay private",
        }

    def search(self, query, vector, category, limit, **kwargs):
        self.calls.append((query, list(vector), category, limit, kwargs))
        dense = [
            {"chunk_id": "chunk-a", "material_id": "material-a", "revision_id": "revision-a", "chunk_md5": hashlib.md5(b"Canonical evidence A text.").hexdigest(), "score": 0.9, "rank": 1},
            {"chunk_id": "chunk-b", "material_id": "material-b", "revision_id": "revision-b", "chunk_md5": hashlib.md5(b"Canonical evidence B text.").hexdigest(), "score": 0.8, "rank": 2},
            {"chunk_id": "chunk-c", "material_id": "material-c", "revision_id": "revision-c", "chunk_md5": hashlib.md5(b"Canonical locator C text.").hexdigest(), "score": 0.7, "rank": 3},
        ]
        bm25 = [dense[1], dense[0], dense[2]]
        return {"dense": dense, "bm25": bm25, "contexts": deepcopy(self.contexts),
                "manifest": {"generation_id": "generation-a"}}


class SearchReranker:
    last_metadata = {
        "provider": "deepinfra", "model": "Qwen/Qwen3-Reranker-4B",
        "input_tokens": 66, "inference_status": {"runtime_ms": 12, "cost": 0.000001},
        "estimated_cost": 0.000001, "cost_is_estimate": True,
        "score_semantics": "relevance_not_answerability",
    }

    def __init__(self):
        self.calls = []

    def rerank(self, query, documents):
        self.calls.append((query, list(documents)))
        return [0.2, 0.9]


@pytest.fixture(autouse=True)
def clear_query_embedding_cache():
    from dse_knowledge import retrieval
    retrieval._QUERY_EMBEDDINGS.clear()
    yield
    retrieval._QUERY_EMBEDDINGS.clear()


def test_contextual_mode_hydrates_original_source_and_keeps_generated_hint_out_of_results():
    store = SearchStore(canonical_rows())
    index = SearchIndex()
    retriever = Retriever(
        store, SearchEmbedding(), contextual_index=index, default_mode="contextual",
        context_model="context-test-model", prompt_version="whole-document-chunk-context/v1",
    )

    result = retriever.search("stitching signature", limit=3)

    assert result["retrieval_mode"] == "contextual"
    assert result["channels"]["context_dense"] == 3
    assert result["channels"]["context_bm25"] == 3
    assert result["items"][0]["chunk_id"] == "chunk-a"
    assert result["items"][0]["text"] == "Canonical evidence A text."
    assert result["items"][0]["claim_contexts"] == store.contexts["chunk-a"]
    assert "generated hint" not in repr(result["items"])
    assert len(store.hydration_calls) == 1
    assert index.calls[0][4]["expected_corpus_hash"] == "a" * 32
    assert result["dense_candidate_trace"]["method"] == "contextual_index_numpy_exact_cosine"


def test_contextual_hydration_fails_closed_when_current_chunk_text_differs_from_index_binding():
    store = SearchStore(canonical_rows())
    store.canonical["chunk-a"]["text"] = "Changed canonical evidence A."
    retriever = Retriever(
        store, SearchEmbedding(), contextual_index=SearchIndex(), default_mode="contextual",
        context_model="context-test-model", prompt_version="whole-document-chunk-context/v1",
    )

    with pytest.raises(RetrievalUnavailableError, match="contextual_candidate_stale"):
        retriever.search("stitching signature")


def test_reranking_reorders_only_technical_candidates_and_preserves_original_evidence_fields():
    store = SearchStore(canonical_rows())
    index = SearchIndex()
    reranker = SearchReranker()
    retriever = Retriever(
        store, SearchEmbedding(), contextual_index=index, reranker=reranker,
        default_mode="contextual_rerank", context_model="context-test-model",
        prompt_version="whole-document-chunk-context/v1", rerank_candidate_limit=40,
    )

    result = retriever.search("stitching signature", limit=3)

    query, documents = reranker.calls[0]
    assert query == "stitching signature"
    assert len(documents) == 2
    assert "generated hint A" in documents[0] and "Canonical evidence A text." in documents[0]
    assert all("locator" not in text for text in documents)
    assert [item["chunk_id"] for item in result["items"]] == ["chunk-b", "chunk-a"]
    assert result["locators"][0]["chunk_id"] == "chunk-c"
    assert result["items"][0]["text"] == "Canonical evidence B text."
    assert result["items"][0]["claim_contexts"] == store.contexts["chunk-b"]
    assert result["items"][0]["trace"]["rank_score"] > 0
    assert result["items"][0]["trace"]["original_rrf_score"] == result["items"][0]["trace"]["rank_score"]
    assert result["items"][0]["trace"]["reranker_relevance_score"] == 0.9
    assert result["reranker_trace"]["score_semantics"] == "relevance_not_answerability"
    assert result["reranker_trace"]["cost_is_estimate"] is True
    assert "generated hint" not in repr(result["items"])


def test_client_cannot_change_server_mode_without_experiment_override():
    store = SearchStore(canonical_rows())
    retriever = Retriever(store, SearchEmbedding(), default_mode="baseline", allow_mode_override=False)

    with pytest.raises(RetrievalModeError, match="retrieval_mode_override_disabled"):
        retriever.search("stitching signature", retrieval_mode="contextual")
    with pytest.raises(RetrievalModeError, match="retrieval_mode_invalid"):
        retriever.search("stitching signature", retrieval_mode=[])

    unavailable = Retriever(store, SearchEmbedding(), default_mode="contextual")
    with pytest.raises(RetrievalUnavailableError, match="contextual_retrieval_unavailable"):
        unavailable.search("stitching signature")


class FakeChat:
    def close(self):
        pass


class FakeNative:
    def capabilities(self):
        return {"available": True}


def test_search_api_uses_server_configured_mode_and_exposes_experiment_override():
    from fastapi.testclient import TestClient
    from dse_knowledge.app import create_app

    store = SearchStore(canonical_rows())
    index = SearchIndex()
    settings = Settings({
        "DSE_RETRIEVAL_MODE": "contextual",
        "DSE_CONTEXTUAL_ENABLED": "true",
        "DSE_CONTEXT_CHAT_MODEL": "context-test-model",
        "DSE_RETRIEVAL_ALLOW_MODE_OVERRIDE": "false",
    })
    app = create_app(settings, store=store, embedding=SearchEmbedding(), chat=FakeChat(),
                     native=FakeNative(), contextual_index=index, run_jobs=False)

    with TestClient(app) as client:
        default = client.post("/api/search", json={"query": "stitching signature"})
        denied = client.post("/api/search", json={
            "query": "stitching signature", "retrieval_mode": "baseline",
        })
        invalid = client.post("/api/search", json={
            "query": "stitching signature", "retrieval_mode": "invented",
        })

    assert default.status_code == 200
    assert default.json()["retrieval_mode"] == "contextual"
    assert default.json()["items"][0]["text"] == "Canonical evidence A text."
    assert denied.status_code == 400
    assert denied.json()["code"] == "retrieval_mode_override_disabled"
    assert invalid.status_code == 422


def test_search_api_maps_stale_context_index_to_typed_service_unavailable():
    from fastapi.testclient import TestClient
    from dse_knowledge.app import create_app
    from dse_knowledge.contextual_index import ContextualIndexError

    class StaleIndex(SearchIndex):
        def search(self, *args, **kwargs):
            raise ContextualIndexError("contextual_index_stale")

    app = create_app(
        Settings({"DSE_RETRIEVAL_MODE": "contextual", "DSE_CONTEXTUAL_ENABLED": "true",
                  "DSE_CONTEXT_CHAT_MODEL": "context-test-model"}),
        store=SearchStore(canonical_rows()), embedding=SearchEmbedding(), chat=FakeChat(),
        native=FakeNative(), contextual_index=StaleIndex(), run_jobs=False,
    )

    with TestClient(app) as client:
        response = client.post("/api/search", json={"query": "stitching signature"})

    assert response.status_code == 503
    assert response.json()["code"] == "contextual_index_stale"
