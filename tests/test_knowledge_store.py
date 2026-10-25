from contextlib import contextmanager
import pytest
from dse_knowledge.config import Settings
from dse_knowledge.db import Store


class Cursor:
    def __init__(self, rows): self.rows = rows
    def fetchone(self): return self.rows[0] if self.rows else None
    def fetchall(self): return self.rows


class LedgerConnection:
    def __init__(self): self.writes = []
    def execute(self, sql, args=()):
        if 'FROM materials WHERE id=' in sql:
            return Cursor([{'id': 'm1', 'role': 'unclassified', 'role_metadata': {}}])
        if 'FROM revisions WHERE material_id=' in sql:
            return Cursor([{'id': 'r1', 'sha256': 'a' * 64}])
        self.writes.append((sql, args))
        return Cursor([])


def fake_store():
    store = Store(Settings({})); conn = LedgerConnection()
    @contextmanager
    def connect(): yield conn
    store.connection = connect
    return store, conn


def test_role_assessment_is_bound_to_actual_revision_and_has_an_audit_event():
    store, conn = fake_store()
    assessment = store.assess_material('m1', 'core_technical',
        {'revision_sha256': 'a' * 64, 'method': 'curator_annotation'})
    assert assessment['revision_sha256'] == 'a' * 64
    assert assessment['assessment_id']
    assert any(sql.startswith('UPDATE materials') for sql, _ in conn.writes)
    assert any(sql.startswith('INSERT INTO ingest_events') for sql, _ in conn.writes)


def test_role_from_another_revision_cannot_be_applied():
    store, conn = fake_store()
    with pytest.raises(ValueError, match='revision'):
        store.assess_material('m1', 'core_technical', {'revision_sha256': 'b' * 64})
    assert conn.writes == []


def test_unknown_role_is_not_silently_treated_as_core():
    store, conn = fake_store()
    with pytest.raises(ValueError, match='role'):
        store.assess_material('m1', 'authoritative', {'revision_sha256': 'a' * 64})
    assert conn.writes == []
