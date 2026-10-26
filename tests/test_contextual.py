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
    opener = FakeOpener(completion({"contexts": [{"chunk_id": "c0", "context": context_text()}]}))
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
    sent_chunks = json.loads(payload["messages"][1]["content"])["chunks"]
    assert sent_chunks == [{"chunk_id": "c0", "text": "specific chunk", "start_offset": 12, "end_offset": 29}]
    assert generator.last_metadata["wire_id_format"] == "request_local_ordinal/v1"
    assert generator.last_metadata["usage"] == {
        "prompt_tokens": 30, "completion_tokens": 55, "total_tokens": 85,
        "estimated_cost": 0.00002695,
    }
    assert generator.last_metadata["context_lengths"] == [{
        "chunk_id": "chunk-7", "word_count": 50, "char_count": len(context_text()),
    }]


def test_generator_rejects_truncated_completion_even_when_json_is_valid():
    opener = FakeOpener(completion(
        {"contexts": [{"chunk_id": "c0", "context": context_text()}]},
        finish_reason="length",
    ))

    with pytest.raises(ProviderError, match="context_response_truncated"):
        ContextGenerator(settings(), opener=opener).generate(
            "Whole document", [{"id": "chunk-7", "text": "chunk"}],
        )


def test_generator_rejects_missing_or_duplicate_chunk_ids():
    duplicate = {"contexts": [
        {"chunk_id": "c0", "context": context_text()},
        {"chunk_id": "c0", "context": context_text()},
    ]}
    opener = FakeOpener(completion(duplicate))

    with pytest.raises(ProviderError, match="context_chunk_coverage_invalid"):
        ContextGenerator(settings(), opener=opener).generate(
            "Whole document", [{"id": "chunk-7", "text": "chunk"}],
        )


def test_generator_accepts_short_source_bound_context_below_general_token_target():
    short_context = "This chunk describes API stubs."
    opener = FakeOpener(completion({"contexts": [{"chunk_id": "c0", "context": short_context}]}))

    result = ContextGenerator(settings(), opener=opener).generate(
        "Whole document", [{"id": "chunk-7", "text": "chunk"}],
    )

    assert result == [{"chunk_id": "chunk-7", "context": short_context}]


def test_generator_rejects_context_above_bounded_word_or_character_limit():
    too_many_words = " ".join(f"token{i}" for i in range(121))
    opener = FakeOpener(completion({"contexts": [{"chunk_id": "c0", "context": too_many_words}]}))

    with pytest.raises(ProviderError, match="context_length_invalid"):
        ContextGenerator(settings(), opener=opener).generate(
            "Whole document", [{"id": "chunk-7", "text": "chunk"}],
        )


def test_generator_rejects_context_above_character_limit_with_few_words():
    oversized_context = " ".join(["x" * 160] * 5)
    opener = FakeOpener(completion({"contexts": [{"chunk_id": "c0", "context": oversized_context}]}))

    with pytest.raises(ProviderError, match="context_length_invalid"):
        ContextGenerator(settings(), opener=opener).generate(
            "Whole document", [{"id": "chunk-7", "text": "chunk"}],
        )


def test_generator_bounds_each_request_to_64_chunks_while_repeating_the_whole_document():
    chunks = [{"id": f"chunk-{i}", "text": f"source passage {i}"} for i in range(65)]
    payloads = [
        completion({"contexts": [{"chunk_id": f"c{i}", "context": context_text()} for i in range(64)]}),
        completion({"contexts": [{"chunk_id": "c0", "context": context_text()}]}),
    ]
    opener = FakeOpener(payloads)
    document = "Whole document needed to disambiguate this chunk."

    result = ContextGenerator(settings(), opener=opener).generate(document, chunks)

    assert [item["chunk_id"] for item in result] == [f"chunk-{i}" for i in range(65)]
    assert len(opener.requests) == 2
    assert all(document in json.dumps(json.loads(request.data)["messages"]) for request, _ in opener.requests)
    assert [json.loads(request.data)["max_tokens"] for request, _ in opener.requests] == [16384, 512]
    wire_chunks = [json.loads(json.loads(request.data)["messages"][1]["content"])["chunks"]
                   for request, _ in opener.requests]
    assert [[chunk["chunk_id"] for chunk in batch] for batch in wire_chunks] == [
        [f"c{i}" for i in range(64)], ["c0"],
    ]


def test_generator_resubmits_truncated_batch_as_smaller_exact_id_batches():
    chunks = [{"id": f"chunk-{i}", "text": f"source passage {i}"} for i in range(16)]
    opener = FakeOpener([
        completion({"contexts": []}, finish_reason="length"),
        completion({"contexts": [{"chunk_id": f"c{i}", "context": context_text()} for i in range(8)]}),
        completion({"contexts": [{"chunk_id": f"c{i}", "context": context_text()} for i in range(8)]}),
    ])
    generator = ContextGenerator(settings(), opener=opener)
    document = "Whole source document retained across every retry."

    result = generator.generate(document, chunks)

    assert [row["chunk_id"] for row in result] == [c["id"] for c in chunks]
    sent = [json.loads(json.loads(request.data)["messages"][1]["content"])
            for request, _ in opener.requests]
    assert [len(payload["chunks"]) for payload in sent] == [16, 8, 8]
    assert [[chunk["chunk_id"] for chunk in payload["chunks"]] for payload in sent] == [
        [f"c{i}" for i in range(16)], [f"c{i}" for i in range(8)], [f"c{i}" for i in range(8)],
    ]
    assert all(payload["document"] == document for payload in sent)
    assert generator.last_metadata["chunks_observed"] == 16
    assert generator.last_metadata["usage"]["total_tokens"] == 255
    assert generator.last_metadata["batch_fallbacks"][0]["reason"] == "context_response_truncated"


def test_generator_never_repairs_or_drops_ids_when_smaller_batch_still_invalid():
    chunks = [{"id": f"chunk-{i}", "text": f"source passage {i}"} for i in range(16)]
    wrong = completion({"contexts": [{"chunk_id": "invented", "context": context_text()}]})
    opener = FakeOpener([wrong, wrong])
    generator = ContextGenerator(settings(), opener=opener)

    with pytest.raises(ProviderError, match="context_chunk_coverage_invalid"):
        generator.generate("Whole source document", chunks)

    assert len(opener.requests) == 2
    assert generator.last_metadata["chunks_observed"] == 0


def test_generator_rebinds_reversed_alias_responses_to_original_uuid_chunk_ids():
    first_id = "chunk-ed1dcd3ba9ee6456d71646b495c86b0a"
    second_id = "chunk-8d7cefae03f04f2b8c5b551ddc2d9c11"
    first_context = context_text() + " first-context"
    second_context = context_text() + " second-context"
    opener = FakeOpener(completion({"contexts": [
        {"chunk_id": "c1", "context": second_context},
        {"chunk_id": "c0", "context": first_context},
    ]}))
    generator = ContextGenerator(settings(), opener=opener)
    chunks = [
        {"id": first_id, "start_offset": 0, "end_offset": 10, "text": "first source"},
        {"id": second_id, "start_offset": 11, "end_offset": 23, "text": "second source"},
    ]

    result = generator.generate("Complete UUID source", chunks)

    assert result == [
        {"chunk_id": first_id, "context": first_context},
        {"chunk_id": second_id, "context": second_context},
    ]
    wire = json.loads(json.loads(opener.requests[0][0].data)["messages"][1]["content"])
    assert wire == {
        "document": "Complete UUID source",
        "chunks": [
            {"chunk_id": "c0", "text": "first source", "start_offset": 0, "end_offset": 10},
            {"chunk_id": "c1", "text": "second source", "start_offset": 11, "end_offset": 23},
        ],
    }


@pytest.mark.parametrize("wire_ids", [["c0", "unknown"], ["c0", "c0"]])
def test_generator_rejects_unknown_or_duplicate_request_local_aliases(wire_ids):
    opener = FakeOpener(completion({"contexts": [
        {"chunk_id": wire_ids[0], "context": context_text()},
        {"chunk_id": wire_ids[1], "context": context_text()},
    ]}))
    chunks = [{"id": "chunk-uuid-a", "text": "first"}, {"id": "chunk-uuid-b", "text": "second"}]

    with pytest.raises(ProviderError, match="context_chunk_coverage_invalid"):
        ContextGenerator(settings(), opener=opener).generate("Whole document", chunks)


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
