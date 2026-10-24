"""Offline checks for safe logical backups and service log routing."""
from __future__ import annotations

import importlib.util
import gzip
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'backup-pilot.py'
UNIT = Path(__file__).resolve().parents[1] / 'deploy' / 'dse-knowledge.service.in'
TABLES = (
    'schema_versions', 'materials', 'revisions', 'chunks', 'claims', 'entities',
    'edges', 'decisions', 'gaps', 'jobs', 'feedback', 'experiments', 'outbox',
    'ingest_events', 'invocations',
)


def load_backup_module(monkeypatch):
    """Import the CLI without allowing it to read settings or open a DB."""
    import dse_knowledge.config as config
    import dse_knowledge.db as db

    def forbidden(*_args, **_kwargs):
        raise AssertionError('import must not load settings or connect to a database')

    monkeypatch.setattr(config.Settings, 'load', forbidden)
    monkeypatch.setattr(db, 'Store', forbidden)
    spec = importlib.util.spec_from_file_location('backup_pilot_under_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeSettings:
    def __init__(self, data_root: Path):
        self.data_root = data_root


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class FakeConnection:
    def execute(self, statement):
        if statement.startswith('SET TRANSACTION'):
            return FakeCursor([])
        prefix = 'SELECT * FROM '
        assert statement.startswith(prefix)
        table = statement[len(prefix):]
        if table == 'schema_versions':
            return FakeCursor([{'version': 2, 'applied_at': '2026-10-25T00:00:00Z'}])
        return FakeCursor([{'id': f'{table}-1', 'content': f'row for {table}'}])


class FakeStore:
    @contextmanager
    def connection(self):
        yield FakeConnection()


def make_backup(module, root, *, moment=None):
    return module.run_backup(
        FakeSettings(root), FakeStore(),
        now=moment or datetime(2026, 10, 25, 1, 2, 3, tzinfo=timezone.utc),
    )


def test_backup_cli_import_is_side_effect_free(monkeypatch):
    module = load_backup_module(monkeypatch)

    assert callable(getattr(module, 'run_backup', None))


def test_backup_is_unique_private_and_declares_its_real_scope(monkeypatch, tmp_path):
    module = load_backup_module(monkeypatch)
    root = tmp_path / 'private-data'

    first = make_backup(module, root)
    archive_path = Path(first['backup'])
    original = archive_path.read_bytes()
    raw = gzip.decompress(original)
    payload = json.loads(raw)
    second = make_backup(module, root)

    assert first['backup'] != second['backup']
    assert archive_path.read_bytes() == original
    assert hashlib.sha256(original).hexdigest() == first['archive_sha256']
    assert hashlib.sha256(raw).hexdigest() == first['payload_sha256']
    assert set(payload['tables']) == set(TABLES)
    assert first['rows']['schema_versions'] == 1
    assert set(first['rows']) == set(TABLES)
    assert first['restore_check'] == 'sqlite_serialization_row_count_integrity_smoke_passed'
    assert first['archive_sha256']
    assert first['payload_sha256']

    for key in ('backup', 'restore_check_file', 'verification'):
        assert Path(first[key]).stat().st_mode & 0o777 == 0o600
    verification = json.loads(Path(first['verification']).read_text(encoding='utf-8'))
    assert verification['verification'] == first['verification']
    assert verification['scope'] == first['scope']
    assert (root.stat().st_mode & 0o777) == 0o700
    assert (root / 'backups').stat().st_mode & 0o777 == 0o700

    exclusions = ' '.join(first['scope']['excluded']).lower()
    assert 'artifact bytes' in exclusions
    assert 'melete' in exclusions
    assert 'off-host' in exclusions
    assert 'postgresql' in exclusions
    assert 'logical' in first['scope']['included'].lower()


def test_atomic_backup_writer_never_replaces_a_name(monkeypatch, tmp_path):
    module = load_backup_module(monkeypatch)
    root, directory_fd = module._open_private_directory(tmp_path / 'private')
    try:
        existing = root / 'kept.json.gz'
        existing.write_bytes(b'original')

        with pytest.raises(FileExistsError):
            module._atomic_write_new(directory_fd, existing.name, b'replacement')

        assert existing.read_bytes() == b'original'
        module._atomic_write_new(directory_fd, 'new.json.gz', b'complete payload')
        created = root / 'new.json.gz'
        assert created.read_bytes() == b'complete payload'
        assert created.stat().st_mode & 0o777 == 0o600
        assert sorted(path.name for path in root.iterdir()) == ['kept.json.gz', 'new.json.gz']
    finally:
        os.close(directory_fd)


def test_backup_rejects_symlinked_data_or_backup_directory(monkeypatch, tmp_path):
    module = load_backup_module(monkeypatch)
    real = tmp_path / 'real-data'
    real.mkdir(mode=0o700)
    data_link = tmp_path / 'data-link'
    data_link.symlink_to(real, target_is_directory=True)

    with pytest.raises(module.BackupError):
        module.run_backup(FakeSettings(data_link), FakeStore())

    backup_link = real / 'backups'
    external = tmp_path / 'external'
    external.mkdir(mode=0o700)
    backup_link.symlink_to(external, target_is_directory=True)
    with pytest.raises(module.BackupError):
        module.run_backup(FakeSettings(real), FakeStore())


def test_backup_refuses_existing_non_private_data_directory(monkeypatch, tmp_path):
    module = load_backup_module(monkeypatch)
    root = tmp_path / 'shared-data'
    root.mkdir(mode=0o755)
    root.chmod(0o755)

    with pytest.raises(module.BackupError):
        module.run_backup(FakeSettings(root), FakeStore())


def test_backup_refuses_existing_non_private_backup_directory(monkeypatch, tmp_path):
    module = load_backup_module(monkeypatch)
    root = tmp_path / 'private-data'
    root.mkdir(mode=0o700)
    backups = root / 'backups'
    backups.mkdir(mode=0o755)
    backups.chmod(0o755)

    with pytest.raises(module.BackupError):
        module.run_backup(FakeSettings(root), FakeStore())


def test_service_routes_logs_to_journal_without_a_local_log_directory():
    unit = UNIT.read_text()

    assert 'StandardOutput=journal' in unit
    assert 'StandardError=journal' in unit
    assert 'append:%h/.local/share/dse-knowledge/logs/' not in unit
