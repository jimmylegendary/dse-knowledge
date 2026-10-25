from __future__ import annotations

import hashlib
import json
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

from dse_knowledge.knowledge import validate_claim_context
from dse_knowledge import cli


def _seed_fixture(role="core_technical", *, annotation_valid=True):
    material_id = "seed-1"
    text = "Latency was measured at 12 ms for this synthetic source."
    digest = hashlib.sha256(text.encode()).hexdigest()
    revision = {
        "id": "revision-current", "material_id": material_id, "sha256": digest,
        "content": text, "created_at": "2026-10-25T00:00:00+00:00",
    }
    chunk = {
        "id": "chunk-current", "material_id": material_id, "revision_id": "revision-current",
        "text": text, "start": 0, "end": len(text),
    }
    quote = "Latency was measured at 12 ms"
    source_start = text.index(quote)
    claim = {
        "id": "claim-current", "material_id": material_id, "revision_id": "revision-current",
        "chunk_id": "chunk-current", "quote": quote,
        "metadata": {"source_start": source_start, "source_end": source_start + len(quote)},
    }
    raw_context = {
        "schema_version": "claim-context/v1",
        "parameters": [{
            "name": "latency", "value": 12, "unit": "ms",
            "evidence": {"chunk_id": "chunk-current", "quote": "12 ms"},
        }],
        "conditions": [], "source_scope_note": "Synthetic scoped assertion.",
    }
    document = {
        "material": {"id": material_id}, "text": text,
        "revision": {"id": "revision-current", "sha256": digest}, "chunks": [chunk],
    }
    normalized = validate_claim_context(raw_context, document)
    if not annotation_valid:
        normalized["parameters"][0]["normalized"]["status"] = "unresolved"
    annotation = {
        "id": "annotation-current", "claim_id": "claim-current", "revision_id": "revision-current",
        "claim_revision_id": "revision-current", "version": "claim-context/v1", "context": normalized,
        "created_at": "2026-10-25T00:00:00+00:00",
    }
    prepared = {
        "material": {"id": material_id, "title": "Seed", "category": "compiler_kernel"},
        "revision": {"sha256": digest}, "text": text, "chunks": [chunk],
    }
    snapshot = {
        "materials": [{"id": material_id, "role": role, "status": "ingested"}],
        "revisions": [revision], "chunks": [chunk], "claims": [claim], "annotations": [annotation],
    }
    return prepared, snapshot


def test_collection_batch_paths_are_safe_and_disjoint(tmp_path, monkeypatch):
    settings = SimpleNamespace(data_root=tmp_path)
    monkeypatch.setattr(cli, "_safe_collection_batch_id", lambda value: value)

    first = cli._collection_batch_paths(settings, "batch-a")
    second = cli._collection_batch_paths(settings, "batch-b")

    assert first["input"] == tmp_path / "pilot1000/batches/batch-a/batch-input.json"
    assert first["receipt"] == tmp_path / "pilot1000/batches/batch-a/batch-receipt.json"
    assert first["progress"] == tmp_path / "pilot1000/batches/batch-a/progress.json"
    assert first["input"] != second["input"]


def test_progress_persists_per_batch_and_explicit_latest_copy(tmp_path, monkeypatch):
    settings = SimpleNamespace(data_root=tmp_path)
    monkeypatch.setattr(cli, "_safe_collection_batch_id", lambda value: value)
    calls = []
    summary = {"batch_id": "batch-a", "indexed_count": 3}

    cli._save_collection_progress(settings, "batch-a", summary, lambda path, value: calls.append((Path(path), value)))

    assert calls == [
        (tmp_path / "pilot1000/batches/batch-a/progress.json", summary),
        (tmp_path / "pilot1000/progress.json", summary),
    ]


def test_private_collection_json_is_create_once_and_owner_only(tmp_path, monkeypatch):
    target = tmp_path / "private" / "batch-input.json"
    target.parent.mkdir(mode=0o700)
    monkeypatch.setattr(cli, "_ensure_private_directory", lambda path: Path(path))

    assert cli._write_private_json_once(target, [{"material_id": "first"}]) is True
    original = target.read_bytes()
    assert cli._write_private_json_once(target, [{"material_id": "second"}]) is False

    assert target.read_bytes() == original
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_pilot_seed_completes_only_with_currently_revalidated_context(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_safe_collection_batch_id", lambda value: value)
    prepared, snapshot = _seed_fixture()
    snapshot["annotations"][0]["context"]["parameters"][0]["normalized"]["status"] = "unresolved"

    records = cli._build_pilot_seed_records([prepared], snapshot, tmp_path)

    assert records[0]["state"] == "needs_review"
    assert records[0]["metadata"]["indexed"] is True
    assert records[0]["metadata"]["claim_count"] == 1
    assert records[0]["metadata"]["annotation_count"] == 0


def test_pilot_seed_is_complete_when_all_current_claim_contexts_validate(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_safe_collection_batch_id", lambda value: value)
    prepared, snapshot = _seed_fixture()

    records = cli._build_pilot_seed_records([prepared], snapshot, tmp_path)

    assert records[0]["state"] == "complete"
    assert records[0]["metadata"]["source_revision_sha256"] == snapshot["revisions"][0]["sha256"]
    assert records[0]["metadata"]["claim_count"] == 1
    assert records[0]["metadata"]["annotation_count"] == 1


def test_pilot_seed_filters_annotations_to_current_claim_revision(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_safe_collection_batch_id", lambda value: value)
    prepared, snapshot = _seed_fixture()
    snapshot["annotations"][0]["revision_id"] = "revision-old"

    records = cli._build_pilot_seed_records([prepared], snapshot, tmp_path)

    assert records[0]["state"] == "needs_review"
    assert records[0]["metadata"]["annotation_count"] == 0


def test_pilot_seed_rejects_claim_quote_not_present_at_its_absolute_source_offsets(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_safe_collection_batch_id", lambda value: value)
    prepared, snapshot = _seed_fixture()
    snapshot["claims"][0]["quote"] = "A different fabricated source quote"

    record = cli._build_pilot_seed_records([prepared], snapshot, tmp_path)[0]

    assert record["state"] == "needs_review"
    assert record["metadata"]["annotation_count"] == 0


def test_pilot_seed_rejects_claim_pointing_to_a_different_chunk(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_safe_collection_batch_id", lambda value: value)
    prepared, snapshot = _seed_fixture()
    snapshot["claims"][0]["chunk_id"] = "other-chunk"

    record = cli._build_pilot_seed_records([prepared], snapshot, tmp_path)[0]

    assert record["state"] == "needs_review"
    assert record["metadata"]["annotation_count"] == 0


def test_pilot_seed_rejects_claim_with_inconsistent_revision_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_safe_collection_batch_id", lambda value: value)
    prepared, snapshot = _seed_fixture()
    snapshot["claims"][0]["revision_id"] = "revision-old"

    record = cli._build_pilot_seed_records([prepared], snapshot, tmp_path)[0]

    assert record["state"] == "needs_review"
    assert record["metadata"]["claim_count"] == 0


def test_pilot_seed_can_calculate_unique_missing_claim_offset_without_mutating_proof(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_safe_collection_batch_id", lambda value: value)
    prepared, snapshot = _seed_fixture()
    snapshot["claims"][0]["metadata"] = {}

    record = cli._build_pilot_seed_records([prepared], snapshot, tmp_path)[0]

    assert record["state"] == "complete"


def test_navigation_and_out_of_scope_pilot_seeds_are_reference_only(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_safe_collection_batch_id", lambda value: value)
    for role in ("source_navigation", "out_of_scope"):
        prepared, snapshot = _seed_fixture(role)
        snapshot["annotations"] = []

        record = cli._build_pilot_seed_records([prepared], snapshot, tmp_path)[0]

        assert record["state"] == "reference_only"
        assert record["metadata"]["indexed"] is True


def test_existing_batch_create_does_not_rewrite_its_canonical_input(monkeypatch, tmp_path, capsys):
    settings = SimpleNamespace(data_root=tmp_path, values={}, get=lambda _key, default="": default)
    canonical = tmp_path / "pilot1000/batches/batch-existing/batch-input.json"
    canonical.parent.mkdir(parents=True, mode=0o700)
    canonical.write_text('[{"material_id":"already-frozen"}]', encoding="utf-8")
    canonical.chmod(0o600)
    original = canonical.read_bytes()

    class FakeStore:
        def one(self, _sql, _args=()):
            return {"id": "batch-existing"}

    class FakeManager:
        def __init__(self, *_args):
            pass

        def summary(self, _batch_id):
            return {"batch_id": "batch-existing", "batch_state": "running", "artifact_bytes_used": 0}

    fake_expansion = SimpleNamespace(
        make_handlers=lambda *_args: {},
        freeze_artifact_baseline=lambda *_args: (_ for _ in ()).throw(AssertionError("existing batch must not refreeze")),
        add_artifact_inventory_summary=lambda summary, _settings: summary,
        DEFAULT_COLLECTION_POLICY={"max_workers": 4, "stage_caps": {"acquire": 1, "index": 2}},
    )
    fake_pipeline = SimpleNamespace(
        load_prepared=lambda *_args: (_ for _ in ()).throw(AssertionError("existing batch must not reload candidates")),
        save_json=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("existing batch must not write")),
        safe_material_id=lambda value: value,
    )
    monkeypatch.setattr(cli.Settings, "load", lambda: settings)
    monkeypatch.setitem(sys.modules, "dse_knowledge.db", SimpleNamespace(Store=lambda _settings: FakeStore()))
    monkeypatch.setitem(sys.modules, "dse_knowledge.collection", SimpleNamespace(CollectionManager=FakeManager))
    monkeypatch.setitem(sys.modules, "dse_knowledge.expansion", fake_expansion)
    monkeypatch.setitem(sys.modules, "dse_knowledge.pipeline", fake_pipeline)
    monkeypatch.setattr(sys, "argv", [
        "dse-knowledge", "collection-create", "--id", "batch-existing",
        "--candidates", str(tmp_path / "never-read.json"), "--target", "1000",
    ])

    cli.main()

    assert canonical.read_bytes() == original
    assert not (canonical.parent / "batch-receipt.json").exists()
    assert capsys.readouterr().out


def test_new_batch_create_writes_canonical_per_batch_input_and_receipt(monkeypatch, tmp_path, capsys):
    settings = SimpleNamespace(data_root=tmp_path / "data", values={}, get=lambda _key, default="": default)
    events = []
    created = {}

    class FakeStore:
        def one(self, _sql, _args=()):
            return None

        def ingest_event(self, *args):
            events.append(args)

    class FakeManager:
        def __init__(self, *_args):
            created["policy"] = _args[-1]

        def create_batch(self, batch_id, records, target):
            created.update(batch_id=batch_id, records=records, target=target)
            return {"batch_id": batch_id, "batch_state": "running", "target": target, "artifact_bytes_used": 0}

    def ensure_private(path):
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
        return path

    candidate = [{"id": "new-doc", "category": "compiler_kernel", "title": "Candidate"}]
    candidate_path = tmp_path / "candidates.json"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    candidate_path.chmod(0o600)
    freeze_calls = []
    fake_expansion = SimpleNamespace(
        make_handlers=lambda *_args: {},
        freeze_artifact_baseline=lambda *_args: freeze_calls.append(True),
        add_artifact_inventory_summary=lambda summary, _settings: summary,
        DEFAULT_COLLECTION_POLICY={
            "max_workers": 4,
            "stage_caps": {"acquire": 1, "assess": None, "index": 2, "extract": 4},
            "host_reserve_bytes": 10 * 1024**3,
            "initial_artifact_budget_bytes": 4 * 1024**3,
            "artifact_budget_bytes": 4 * 1024**3,
        },
    )
    fake_pipeline = SimpleNamespace(
        load_prepared=lambda _settings: [],
        safe_material_id=lambda value: value,
    )
    monkeypatch.setattr(cli.Settings, "load", lambda: settings)
    monkeypatch.setattr(cli, "_ensure_private_directory", ensure_private)
    monkeypatch.setitem(sys.modules, "dse_knowledge.db", SimpleNamespace(Store=lambda _settings: FakeStore()))
    monkeypatch.setitem(sys.modules, "dse_knowledge.collection", SimpleNamespace(CollectionManager=FakeManager))
    monkeypatch.setitem(sys.modules, "dse_knowledge.expansion", fake_expansion)
    monkeypatch.setitem(sys.modules, "dse_knowledge.pipeline", fake_pipeline)
    monkeypatch.setattr(sys, "argv", [
        "dse-knowledge", "collection-create", "--id", "batch-new",
        "--candidates", str(candidate_path), "--target", "1",
    ])

    cli.main()

    batch_root = settings.data_root / "pilot1000/batches/batch-new"
    input_path = batch_root / "batch-input.json"
    receipt_path = batch_root / "batch-receipt.json"
    assert freeze_calls == [True]
    assert created["batch_id"] == "batch-new"
    assert created["target"] == 1
    assert created["policy"]["max_workers"] == 4
    assert created["policy"]["stage_caps"]["acquire"] == 1
    assert created["policy"]["stage_caps"]["index"] == 2
    assert created["policy"]["host_reserve_bytes"] == 10 * 1024**3
    assert created["policy"]["artifact_budget_bytes"] == 4 * 1024**3
    assert json.loads(input_path.read_text(encoding="utf-8"))[0]["id"] == "new-doc"
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["batch_id"] == "batch-new"
    assert stat.S_IMODE(input_path.stat().st_mode) == stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    assert not (settings.data_root / "pilot1000/batch-input.json").exists()
    assert not (settings.data_root / "pilot1000/batch-receipt.json").exists()
    assert len(events) == 1
    assert capsys.readouterr().out
