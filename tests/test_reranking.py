import json
import threading
from copy import deepcopy

import pytest

from dse_knowledge.config import Settings
from dse_knowledge.providers import ProviderError
from dse_knowledge.reranking import QwenReranker


class Response:
    status = 200

    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def read(self, size=-1):
        return self.payload if size < 0 else self.payload[:size]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeOpener:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return Response(self.payload)


def settings(**overrides):
    values = {
        "DSE_RERANK_PROVIDER": "deepinfra",
        "DSE_RERANK_MODEL": "Qwen/Qwen3-Reranker-4B",
        "DSE_RERANK_ENDPOINT": "https://api.deepinfra.com/v1/inference/Qwen/Qwen3-Reranker-4B",
        "DSE_RERANK_API_KEY": "private-rerank-key",
    }
    values.update(overrides)
    return Settings(values)


def test_deepinfra_reranker_posts_paired_arrays_and_keeps_input_score_alignment():
    opener = FakeOpener({
        "scores": [0.9954848, 0.0194691, 0.0000816],
        "input_tokens": 271,
        "inference_status": {"runtime_ms": 27, "cost": 0.000006775, "tokens_input": 271},
    })
    reranker = QwenReranker(settings(), opener=opener)
    query = "How does cache locality affect H100 throughput?"
    documents = ["evidence A", "evidence B", "evidence C"]

    scores = reranker.rerank(query, documents)

    assert scores == [0.9954848, 0.0194691, 0.0000816]
    request, timeout = opener.requests[0]
    assert request.full_url == "https://api.deepinfra.com/v1/inference/Qwen/Qwen3-Reranker-4B"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer private-rerank-key"
    assert json.loads(request.data) == {"queries": [query, query, query], "documents": documents}
    assert timeout > 0
    assert reranker.last_metadata["input_tokens"] == 271
    assert reranker.last_metadata["inference_status"]["runtime_ms"] == 27
    assert reranker.last_metadata["estimated_cost"] == pytest.approx(0.000006775)
    assert reranker.last_metadata["score_semantics"] == "relevance_not_answerability"


def test_deepinfra_reranker_accepts_configured_8b_model_and_endpoint():
    endpoint = "https://api.deepinfra.com/v1/inference/Qwen/Qwen3-Reranker-8B"
    opener = FakeOpener({"scores": [0.8], "input_tokens": 80, "inference_status": {"runtime_ms": 100}})
    reranker = QwenReranker(settings(
        DSE_RERANK_MODEL="Qwen/Qwen3-Reranker-8B",
        DSE_RERANK_ENDPOINT=endpoint,
    ), opener=opener)

    assert reranker.rerank("query", ["candidate"]) == [0.8]
    assert opener.requests[0][0].full_url == endpoint
    assert reranker.last_metadata["model"] == "Qwen/Qwen3-Reranker-8B"


def test_deepinfra_reranker_rejects_misaligned_and_nonfinite_scores():
    for payload in (
        {"scores": [0.7], "input_tokens": 12, "inference_status": {}},
        {"scores": [0.7, float("nan")], "input_tokens": 12, "inference_status": {}},
    ):
        reranker = QwenReranker(settings(), opener=FakeOpener(payload))
        with pytest.raises(ProviderError):
            reranker.rerank("query", ["first", "second"])


def test_cohere_compatible_response_indices_are_restored_to_document_order():
    opener = FakeOpener({"results": [
        {"index": 2, "relevance_score": 0.3},
        {"index": 0, "relevance_score": 0.9},
        {"index": 1, "relevance_score": 0.1},
    ], "meta": {"billed_units": {"search_units": 3}}})
    reranker = QwenReranker(settings(
        DSE_RERANK_PROVIDER="cohere-compatible",
        DSE_RERANK_MODEL="company-reranker",
        DSE_RERANK_ENDPOINT="https://ranker.internal.example/rerank",
    ), opener=opener)

    scores = reranker.rerank("query", ["first", "second", "third"])

    assert scores == [0.9, 0.1, 0.3]
    assert json.loads(opener.requests[0][0].data) == {
        "model": "company-reranker", "query": "query",
        "documents": ["first", "second", "third"], "return_documents": False,
    }


def test_cohere_compatible_internal_http_endpoint_requires_explicit_flag():
    opener = FakeOpener({"results": [{"index": 0, "relevance_score": 0.9}]})
    configured = settings(
        DSE_RERANK_PROVIDER="cohere-compatible",
        DSE_RERANK_MODEL="company-reranker",
        DSE_RERANK_ENDPOINT="http://ranker.internal.example/rerank",
        DSE_RERANK_ALLOW_HTTP="true",
    )

    assert QwenReranker(configured, opener=opener).rerank("query", ["candidate"]) == [0.9]
    assert opener.requests[0][0].full_url == "http://ranker.internal.example/rerank"


def test_cohere_http_requires_opt_in_and_deepinfra_stays_https_pinned():
    cohere = QwenReranker(settings(
        DSE_RERANK_PROVIDER="cohere-compatible",
        DSE_RERANK_MODEL="company-reranker",
        DSE_RERANK_ENDPOINT="http://ranker.internal.example/rerank",
        DSE_RERANK_ALLOW_HTTP="false",
    ), opener=FakeOpener({"results": [{"index": 0, "relevance_score": 0.9}]}))
    with pytest.raises(ProviderError, match="rerank_endpoint_configuration_invalid"):
        cohere.rerank("query", ["candidate"])

    deepinfra = QwenReranker(settings(
        DSE_RERANK_ENDPOINT="http://api.deepinfra.com/v1/inference/Qwen/Qwen3-Reranker-4B",
        DSE_RERANK_ALLOW_HTTP="true",
    ), opener=FakeOpener({"scores": [0.9], "input_tokens": 1, "inference_status": {}}))
    with pytest.raises(ProviderError, match="rerank_endpoint_configuration_invalid"):
        deepinfra.rerank("query", ["candidate"])


def test_shared_reranker_keeps_concurrent_query_receipts_thread_local():
    class QuerySpecificOpener:
        def __init__(self):
            self.barrier = threading.Barrier(2)

        def open(self, request, timeout):
            query = json.loads(request.data)["queries"][0]
            self.barrier.wait(timeout=3)
            token_count, runtime = (101, 11) if query == "query-a" else (202, 22)
            return Response({
                "scores": [0.9], "input_tokens": token_count,
                "inference_status": {"runtime_ms": runtime},
            })

    reranker = QwenReranker(settings(), opener=QuerySpecificOpener())
    completed = threading.Barrier(2)
    receipts = {}
    scores = {}

    def invoke(query):
        scores[query] = reranker.rerank(query, ["candidate"])
        completed.wait(timeout=3)
        receipts[query] = deepcopy(reranker.last_metadata)

    threads = [threading.Thread(target=invoke, args=(query,)) for query in ("query-a", "query-b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert scores == {"query-a": [0.9], "query-b": [0.9]}
    assert receipts["query-a"]["input_tokens"] == 101
    assert receipts["query-a"]["inference_status"]["runtime_ms"] == 11
    assert receipts["query-b"]["input_tokens"] == 202
    assert receipts["query-b"]["inference_status"]["runtime_ms"] == 22


def test_cohere_compatible_reranker_rejects_duplicate_or_missing_indices():
    opener = FakeOpener({"results": [
        {"index": 0, "relevance_score": 0.9},
        {"index": 0, "relevance_score": 0.1},
    ]})
    reranker = QwenReranker(settings(
        DSE_RERANK_PROVIDER="cohere-compatible",
        DSE_RERANK_ENDPOINT="https://ranker.internal.example/rerank",
    ), opener=opener)

    with pytest.raises(ProviderError):
        reranker.rerank("query", ["first", "second"])


def test_reranker_does_not_expose_key_in_repr_or_metadata():
    reranker = QwenReranker(settings(), opener=FakeOpener({"scores": [0.8]}))

    with pytest.raises(ProviderError):
        reranker.rerank("query", ["candidate"])

    assert "private-rerank-key" not in repr(reranker)
    assert "private-rerank-key" not in repr(reranker.last_metadata)
