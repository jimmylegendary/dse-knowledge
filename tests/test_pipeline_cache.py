from __future__ import annotations

import json
import os
from pathlib import Path
import stat

import pytest

from dse_knowledge import ingestion, pipeline, providers


class Settings:
    def __init__(self, root: Path, values: dict | None = None):
        self.data_root = root / 'data'
        self.artifact_root = root / 'artifacts'
        self.values = values or {}

    def get(self, name: str, default=None):
        return self.values.get(name, default)


def _record() -> dict:
    return {
        'id': 'mat-cache-001',
        'category': 'compiler_kernel',
        'title': 'Synthetic compiler cache record',
        'link': 'https://docs.nvidia.com/cuda/synthetic-cache-guide',
        'head_sha256': 'a' * 64,
    }


def _prepared(settings: Settings, record: dict, *, text: str | None = None) -> dict:
    text = text or ('Synthetic cache body covers compiler kernels and tiled memory movement.\n' * 12).strip()
    raw = text.encode('utf-8')
    digest, artifact_path = ingestion._store_artifact(raw, settings)
    material = dict(record)
    material['id'] = str(record['id'])
    return {
        'material': material,
        'text': text,
        'chunks': ingestion._chunk_text(text, str(record['id']), digest),
        'revision': {
            'sha256': digest,
            'bytes': len(raw),
            'artifact_path': artifact_path,
            'source_url': record['link'],
            'url': record['link'],
            'scope': 'public_fulltext',
            'parser': 'plain-text-v1',
            'content_type': 'text/plain',
        },
    }


def _write_cache(settings: Settings, record: dict, doc: dict) -> Path:
    cache = settings.data_root / 'pilot100' / 'prepared' / f"{record['id']}.json"
    cache.parent.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    cache.parent.mkdir(exist_ok=True, mode=0o700)
    cache.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    os.chmod(cache, 0o600)
    return cache


def test_acquire_accepts_cache_only_when_selected_identity_and_artifacts_match(monkeypatch, tmp_path):
    settings = Settings(tmp_path)
    record = _record()
    doc = _prepared(settings, record)
    _write_cache(settings, record, doc)
    monkeypatch.setattr(ingestion, 'prepare_material', lambda *_args: pytest.fail('valid cache must not refetch'))

    result = pipeline.acquire(settings, [record], target=1)

    assert [item['material']['id'] for item in result] == [record['id']]
    assert result[0]['revision']['sha256'] == doc['revision']['sha256']


@pytest.mark.parametrize(('corruption', 'reason'), [
    ('material_id', 'cache_identity_mismatch'),
    ('category', 'cache_identity_mismatch'),
    ('source_url', 'cache_identity_mismatch'),
    ('selected_head_hash', 'cache_identity_mismatch'),
    ('revision_hash', 'cache_content_hash_mismatch'),
    ('chunk_span', 'cache_chunk_span_mismatch'),
    ('chunk_span_bool', 'cache_chunk_span_mismatch'),
    ('artifact_bytes', 'cache_content_hash_mismatch'),
])
def test_acquire_rejects_invalid_cache_and_refetches_with_safe_reason(
        monkeypatch, tmp_path, corruption, reason):
    settings = Settings(tmp_path)
    record = _record()
    cached = _prepared(settings, record)
    cache = _write_cache(settings, record, cached)
    fresh = _prepared(settings, record, text='Refetched synthetic body has a distinct verified content hash.\n' * 16)
    if corruption == 'material_id':
        cached['material']['id'] = 'mat-wrong-cache'
    elif corruption == 'category':
        cached['material']['category'] = 'hardware_architecture'
    elif corruption == 'source_url':
        cached['revision']['source_url'] = 'https://docs.nvidia.com/cuda/other-guide'
    elif corruption == 'selected_head_hash':
        cached['material']['head_sha256'] = 'b' * 64
    elif corruption == 'revision_hash':
        cached['revision']['sha256'] = 'c' * 64
    elif corruption == 'chunk_span':
        cached['chunks'][0]['start'] += 1
    elif corruption == 'chunk_span_bool':
        cached['chunks'][0]['start'] = False
    elif corruption == 'artifact_bytes':
        Path(cached['revision']['artifact_path']).write_bytes(b'corrupted cached artifact')
        fresh = _prepared(settings, record, text='Fresh replacement artifact with new identity.\n' * 20)
    cache.write_text(json.dumps(cached, ensure_ascii=False), encoding='utf-8')
    os.chmod(cache, 0o600)
    calls = []
    monkeypatch.setattr(ingestion, 'prepare_material', lambda selected, _settings: calls.append(selected) or fresh)

    result = pipeline.acquire(settings, [record], target=1)

    assert calls == [record]
    assert [item['material']['id'] for item in result] == [record['id']]
    state = json.loads((settings.data_root / 'pilot100' / 'acquisition-state.json').read_text())
    rejected = [event for event in state['events'] if event['status'] == 'cache_rejected']
    assert rejected == [{'id': record['id'], 'category': record['category'],
                         'status': 'cache_rejected', 'reason': reason}]
    assert json.loads(cache.read_text())['revision']['sha256'] == fresh['revision']['sha256']


def test_save_json_uses_private_atomic_file_and_ignores_fixed_temp_symlink(monkeypatch, tmp_path):
    directory = tmp_path / 'private'
    directory.mkdir(mode=0o700)
    target = directory / 'state.json'
    canary = directory / 'canary.txt'
    canary.write_text('preserve this content', encoding='utf-8')
    fixed_temp = target.with_suffix(target.suffix + '.tmp')
    fixed_temp.symlink_to(canary)
    real_open = os.open
    temp_flags = []

    def observe_open(path, flags, mode=0o777, *, dir_fd=None):
        if isinstance(path, str) and path.startswith('.dse-json-'):
            temp_flags.append(flags)
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(pipeline.os, 'open', observe_open)

    pipeline.save_json(target, {'status': 'safe'})

    assert json.loads(target.read_text(encoding='utf-8')) == {'status': 'safe'}
    assert canary.read_text(encoding='utf-8') == 'preserve this content'
    assert fixed_temp.is_symlink()
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert len(temp_flags) == 1
    assert temp_flags[0] & os.O_EXCL
    assert temp_flags[0] & os.O_NOFOLLOW
    assert list(directory.glob('.dse-json-*.tmp')) == []


def test_save_json_rejects_unowned_or_nonprivate_parent_directory(tmp_path):
    directory = tmp_path / 'shared'
    directory.mkdir(mode=0o700)
    os.chmod(directory, 0o755)

    with pytest.raises(ValueError, match='json_output_directory_untrusted'):
        pipeline.save_json(directory / 'state.json', {'status': 'must not write'})

    assert not (directory / 'state.json').exists()


def test_publish_manifest_allows_owner_controlled_0755_directory_without_raw_body(tmp_path):
    settings = Settings(tmp_path)
    directory = tmp_path / 'research' / 'pilot100'
    directory.mkdir(parents=True, mode=0o700)
    os.chmod(directory, 0o755)
    manifest_path = directory / 'manifest.json'
    raw_body_sentinel = 'synthetic raw source body must stay out of public manifest'
    document = {
        'material': {
            'id': 'mat-public-manifest-001', 'title': 'Synthetic public metadata',
            'source': 'Synthetic source', 'category': 'compiler_kernel',
            'summary': 'Public metadata summary.', 'link': 'https://docs.example.org/guide',
            'material_type': 'technical_documentation',
        },
        'revision': {
            'sha256': 'a' * 64, 'url': 'https://docs.example.org/guide',
            'scope': 'public_fulltext', 'parser': 'html-text-v1',
        },
        'text': raw_body_sentinel,
        'chunks': [{'text': raw_body_sentinel}],
    }

    pipeline.publish_manifest(settings, [document], manifest_path)

    payload = json.loads(manifest_path.read_text(encoding='utf-8'))
    serialized = manifest_path.read_text(encoding='utf-8')
    assert payload['count'] == 1
    assert payload['items'][0]['id'] == 'mat-public-manifest-001'
    assert payload['items'][0]['chunks'] == 1
    assert raw_body_sentinel not in serialized
    assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o644


def test_public_manifest_rejects_group_writable_directory(tmp_path):
    directory = tmp_path / 'group-writable'
    directory.mkdir(mode=0o700)
    os.chmod(directory, 0o775)

    with pytest.raises(ValueError, match='json_output_directory_untrusted'):
        pipeline.save_json(directory / 'manifest.json', {'public': True}, private=False)

    assert not (directory / 'manifest.json').exists()


def test_save_json_keeps_previous_file_when_serialization_fails(tmp_path):
    directory = tmp_path / 'private'
    directory.mkdir(mode=0o700)
    target = directory / 'state.json'
    target.write_text('{"old": true}', encoding='utf-8')
    os.chmod(target, 0o600)
    cycle = {}
    cycle['cycle'] = cycle

    with pytest.raises(ValueError):
        pipeline.save_json(target, cycle)

    assert target.read_text(encoding='utf-8') == '{"old": true}'
    assert list(directory.glob('*.tmp')) == []


def _extract_batches(monkeypatch, tmp_path, values: dict | None = None) -> list[int]:
    batch_sizes = []

    class FakeStore:
        def __init__(self, _settings):
            pass

        def has_material(self, _material_id):
            return True

        def one(self, *_args):
            return None

        def put_claims(self, _material_id, _claims, _metadata):
            return 0

        def ingest_event(self, *_args):
            pass

        def invocation(self, *_args):
            pass

    class FakeChat:
        def __init__(self, _settings):
            pass

        def close(self):
            pass

    def fake_extract(batch, _chat, **_kwargs):
        batch_sizes.append(len(batch))
        return [{'material_id': doc['material']['id'], 'claims': []} for doc in batch]

    settings = Settings(tmp_path, values)
    docs = [{'material': {'id': f'mat-extract-{i}'}} for i in range(3)]
    monkeypatch.setattr(pipeline, 'Store', FakeStore)
    monkeypatch.setattr(providers, 'ChatClient', FakeChat)
    monkeypatch.setattr(ingestion, 'extract_claims', fake_extract)
    pipeline.extract_materials(settings, docs)
    return batch_sizes


def test_extraction_batch_size_defaults_to_one(monkeypatch, tmp_path):
    assert _extract_batches(monkeypatch, tmp_path) == [1, 1, 1]


@pytest.mark.parametrize(('value', 'expected'), [('2', [2, 1]), ('5', [3])])
def test_extraction_batch_size_setting_controls_sequential_batching(monkeypatch, tmp_path, value, expected):
    assert _extract_batches(monkeypatch, tmp_path, {'DSE_EXTRACTION_BATCH_SIZE': value}) == expected


@pytest.mark.parametrize('value', ['0', '6', 'not-an-integer'])
def test_extraction_batch_size_rejects_out_of_range_configuration(monkeypatch, tmp_path, value):
    with pytest.raises(ValueError, match='extraction_batch_size'):
        _extract_batches(monkeypatch, tmp_path, {'DSE_EXTRACTION_BATCH_SIZE': value})
