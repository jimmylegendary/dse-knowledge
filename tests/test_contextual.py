import json
import hashlib

import pytest

from dse_knowledge.config import Settings
from dse_knowledge.contextual import ContextGenerator
from dse_knowledge import contextual
from dse_knowledge.providers import ProviderError


MODEL = "deepseek-ai/DeepSeek-V4.1-Flash-1017"


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
        self.payloads = list(payload) if isinstance(payload, list) else [payload]
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return Response(self.payloads.pop(0))


def settings(**overrides):
    values = {
        "DSE_CONTEXT_CHAT_BASE_URL": "https://api.deepinfra.com/v1/openai",
        "DSE_CONTEXT_CHAT_MODEL": MODEL,
        "DSE_CONTEXT_CHAT_API_KEY": "private-context-key",
    }
    values.update(overrides)
    return Settings(values)


def completion(content, *, finish_reason="stop", model=MODEL):
    return {
        "model": model,
        "choices": [{
            "index": 0,
            "finish_reason": finish_reason,
            "message": {"role": "assistant", "content": json.dumps(content)},
        }],
        "usage": {"prompt_tokens": 30, "completion_tokens": 55, "total_tokens": 85, "estimated_cost": 0.00002695},
    }


def context_text(count=50):
    return " ".join(f"token{i}" for i in range(count))


def test_generator_sends_whole_document_and_chunk_without_query_then_returns_chunk_bound_context():
    opener = FakeOpener(completion({"contexts": [{"chunk_id": "chunk-7", "context": context_text()}]}))
    generator = ContextGenerator(settings(), opener=opener)
    document = "Complete source document with its earlier and later sections."
    chunks = [{"id": "chunk-7", "start_offset": 12, "end_offset": 29, "text": "specific chunk"}]

    result = generator.generate(document, chunks)

    assert result == [{"chunk_id": "chunk-7", "context": context_text()}]
    request, timeout = opener.requests[0]
    assert request.full_url == "https://api.deepinfra.com/v1/openai/chat/completions"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer private-context-key"
    payload = json.loads(request.data)
    assert payload["model"] == MODEL
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["reasoning_effort"] == "none"
    assert payload["max_tokens"] == 512
    assert timeout > 0
    messages = json.dumps(payload["messages"])
    assert document in messages
    assert "specific chunk" in messages
    assert "query" not in messages.lower()
    assert "test label" not in messages.lower()
    assert generator.last_metadata["usage"] == {
        "prompt_tokens": 30, "completion_tokens": 55, "total_tokens": 85,
        "estimated_cost": 0.00002695,
    }
    assert generator.last_metadata["context_lengths"] == [{
        "chunk_id": "chunk-7", "word_count": 50, "char_count": len(context_text()),
    }]


def test_generator_rejects_truncated_completion_even_when_json_is_valid():
    opener = FakeOpener(completion(
        {"contexts": [{"chunk_id": "chunk-7", "context": context_text()}]},
        finish_reason="length",
    ))

    with pytest.raises(ProviderError, match="context_response_truncated"):
        ContextGenerator(settings(), opener=opener).generate(
            "Whole document", [{"id": "chunk-7", "text": "chunk"}],
        )


def test_generator_rejects_missing_or_duplicate_chunk_ids():
    duplicate = {"contexts": [
        {"chunk_id": "chunk-7", "context": context_text()},
        {"chunk_id": "chunk-7", "context": context_text()},
    ]}
    opener = FakeOpener(completion(duplicate))

    with pytest.raises(ProviderError, match="context_chunk_coverage_invalid"):
        ContextGenerator(settings(), opener=opener).generate(
            "Whole document", [{"id": "chunk-7", "text": "chunk"}],
        )


def test_generator_accepts_short_source_bound_context_below_general_token_target():
    short_context = "This chunk describes API stubs."
    opener = FakeOpener(completion({"contexts": [{"chunk_id": "chunk-7", "context": short_context}]}))

    result = ContextGenerator(settings(), opener=opener).generate(
        "Whole document", [{"id": "chunk-7", "text": "chunk"}],
    )

    assert result == [{"chunk_id": "chunk-7", "context": short_context}]


def test_generator_rejects_context_above_bounded_word_or_character_limit():
    too_many_words = " ".join(f"token{i}" for i in range(121))
    opener = FakeOpener(completion({"contexts": [{"chunk_id": "chunk-7", "context": too_many_words}]}))

    with pytest.raises(ProviderError, match="context_length_invalid"):
        ContextGenerator(settings(), opener=opener).generate(
            "Whole document", [{"id": "chunk-7", "text": "chunk"}],
        )


def test_generator_rejects_context_above_character_limit_with_few_words():
    oversized_context = " ".join(["x" * 160] * 5)
    opener = FakeOpener(completion({"contexts": [{"chunk_id": "chunk-7", "context": oversized_context}]}))

    with pytest.raises(ProviderError, match="context_length_invalid"):
        ContextGenerator(settings(), opener=opener).generate(
            "Whole document", [{"id": "chunk-7", "text": "chunk"}],
        )


def test_generator_bounds_each_request_to_64_chunks_while_repeating_the_whole_document():
    chunks = [{"id": f"chunk-{i}", "text": f"source passage {i}"} for i in range(65)]
    payloads = [
        completion({"contexts": [{"chunk_id": f"chunk-{i}", "context": context_text()} for i in range(64)]}),
        completion({"contexts": [{"chunk_id": "chunk-64", "context": context_text()}]}),
    ]
    opener = FakeOpener(payloads)
    document = "Whole document needed to disambiguate this chunk."

    result = ContextGenerator(settings(), opener=opener).generate(document, chunks)

    assert [item["chunk_id"] for item in result] == [f"chunk-{i}" for i in range(65)]
    assert len(opener.requests) == 2
    assert all(document in json.dumps(json.loads(request.data)["messages"]) for request, _ in opener.requests)
    assert [json.loads(request.data)["max_tokens"] for request, _ in opener.requests] == [8192, 512]


def test_generator_does_not_put_secret_in_error_metadata_or_repr():
    opener = FakeOpener({"error": {"message": "provider rejected request"}})
    generator = ContextGenerator(settings(), opener=opener)

    with pytest.raises(ProviderError):
        generator.generate("Whole document", [{"id": "chunk-7", "text": "chunk"}])

    assert "private-context-key" not in repr(generator)
    assert "private-context-key" not in repr(generator.last_metadata)


def test_settings_loads_contextual_and_rerank_owner_only_files(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir(mode=0o700)
    contextual = config_dir / "contextual.env"
    contextual.write_text("DSE_CONTEXT_CHAT_API_KEY=context-secret\n")
    contextual.chmod(0o600)
    rerank = config_dir / "rerank.env"
    rerank.write_text("DSE_RERANK_API_KEY=rerank-secret\n")
    rerank.chmod(0o600)
    monkeypatch.setenv("DSE_CONFIG_DIR", str(config_dir))

    loaded = Settings.load()

    assert loaded.require("DSE_CONTEXT_CHAT_API_KEY") == "context-secret"
    assert loaded.require("DSE_RERANK_API_KEY") == "rerank-secret"
    assert "context-secret" not in repr(loaded)
    assert "rerank-secret" not in repr(loaded)


def test_context_cache_identity_includes_hash_of_the_actual_prompt_text():
    expected = contextual.CONTEXT_PROMPT_VERSION + ":" + hashlib.sha256(
        contextual._SYSTEM_PROMPT.encode("utf-8"),
    ).hexdigest()

    assert ContextGenerator.prompt_version == expected
