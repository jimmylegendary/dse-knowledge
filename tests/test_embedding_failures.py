from __future__ import annotations

import pytest

from dse_knowledge import pipeline, providers
from dse_knowledge.config import Settings
from dse_knowledge.providers import ProviderError


class FailingEmbedding:
    def __init__(self, error, usage=None):
        self.error = error
        self.last_metadata = {
            'provider': 'deepinfra', 'model': 'google/embeddinggemma-2',
            'task': 'document', 'http_status': None, 'latency_seconds': 25.001,
            'timeout_seconds': 25, 'usage': usage or {}, 'vectors_observed': 0,
            'exception_class': 'TimeoutError', 'error_kind': 'timeout',
            'private_error_text': 'private response body',
            'authorization': 'private credential',
        }

    def embed(self, texts, task='document'):
        assert len(texts) == 8
        assert task == 'document'
        raise self.error


class FakeStore:
    def __init__(self, invocation_error=None):
        self.invocation_error = invocation_error
        self.invocations = []
        self.put_calls = []
        self.ingest_events = []

    def has_material(self, material_id):
        return False

    def invocation(self, provider, purpose, metadata):
        self.invocations.append((provider, purpose, metadata))
        if self.invocation_error is not None:
            raise self.invocation_error

    def put_material(self, document, vectors):
        self.put_calls.append((document, vectors))

    def ingest_event(self, material_id, status, detail):
        self.ingest_events.append((material_id, status, detail))


def _document():
    return {
        'material': {'id': 'material-private-1', 'title': 'Synthetic source'},
        'revision': {'scope': 'public_fulltext', 'sha256': 'a' * 64},
        'chunks': [{'id': f'chunk-{index}', 'text': f'synthetic chunk text {index}'} for index in range(9)],
        'text': 'synthetic source body',
    }


def _run_failure(monkeypatch, store, provider_error, usage=None):
    embedding = FailingEmbedding(provider_error, usage=usage)
    monkeypatch.setattr(providers, 'EmbeddingClient', lambda settings: embedding)
    with pytest.raises(ProviderError) as raised:
        pipeline.index_materials(Settings({}), [_document()], store=store)
    return raised.value


@pytest.mark.parametrize(('usage', 'expected_usage_status', 'expected_usage'), [
    ({}, 'unreported', {}),
    ({'input_tokens': 19, 'total_tokens': 19, 'secret': 'private'}, 'reported',
     {'input_tokens': 19, 'total_tokens': 19}),
])
def test_failed_document_embedding_is_ledgered_once_and_material_is_not_written(
        monkeypatch, usage, expected_usage_status, expected_usage):
    provider_error = ProviderError('embedding_timeout')
    store = FakeStore()

    raised = _run_failure(monkeypatch, store, provider_error, usage=usage)

    assert raised is provider_error
    assert len(store.invocations) == 1
    provider, purpose, metadata = store.invocations[0]
    assert (provider, purpose) == ('deepinfra', 'ingest_embedding_failed')
    assert metadata['status'] == 'failed'
    assert metadata['error_code'] == 'embedding_timeout'
    assert metadata['usage_status'] == expected_usage_status
    assert metadata['billing_status'] == 'unreported'
    assert metadata['usage'] == expected_usage
    assert 'usage_billing_unreported' not in metadata
    assert metadata['timeout_seconds'] == 25
    assert metadata['exception_class'] == 'TimeoutError'
    assert metadata['error_kind'] == 'timeout'
    assert 'private' not in repr(metadata)
    assert store.put_calls == []
    assert store.ingest_events == []


def test_embedding_failure_preserves_original_error_when_ledger_write_fails(monkeypatch):
    provider_error = ProviderError('embedding_transport_error')
    ledger_error = RuntimeError('private ledger failure')
    store = FakeStore(invocation_error=ledger_error)

    raised = _run_failure(monkeypatch, store, provider_error)

    assert raised is provider_error
    assert len(store.invocations) == 1
    assert store.put_calls == []
    assert store.ingest_events == []
