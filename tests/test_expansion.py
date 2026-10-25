from __future__ import annotations

import json
import os
import re
import stat
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from dse_knowledge import expansion
from dse_knowledge.collection import (
    PermanentCollectionError,
    ResourceCollectionError,
    RetryableCollectionError,
)


class Settings:
    def __init__(self, root):
        self.data_root = Path(root) / "data"
        self.artifact_root = Path(root) / "artifacts"
        self.values = {"CHAT_MODEL_ID": "test-codex"}

    def get(self, key, default=""):
        return self.values.get(key, default)


class Ops(SimpleNamespace):
    def __getitem__(self, key):
        return getattr(self, key)


class FakeStore:
    def __init__(self):
        self.materials = {}
        self.claims = {}
        self.annotations = set()
        self.events = []

    def has_material(self, material_id):
        return material_id in self.materials

    def assess_material(self, material_id, role, provenance):
        if material_id not in self.materials:
            raise ValueError("material_not_found")
        self.events.append(("assess", material_id))
        self.materials[material_id]["role"] = role
        self.materials[material_id]["role_metadata"] = dict(provenance)
        return dict(provenance)

    def one(self, sql, args=()):
        if "FROM materials" in sql and args:
            row = self.materials.get(str(args[0]))
            if not row:
                return None
            return {"role": row.get("role"), "role_metadata": row.get("role_metadata", {})}
        raise AssertionError(f"Unexpected one(): {sql}")

    def rows(self, sql, args=()):
        if "FROM claims" in sql:
            rows = list(self.claims.get(str(args[0]), []))
            if len(args) > 1:
                rows = [row for row in rows if row.get("revision_sha256", args[1]) == args[1]]
            return rows
        if "FROM claim_annotations" in sql:
            return [{"claim_id": claim_id} for claim_id in self.annotations]
        raise AssertionError(f"Unexpected rows(): {sql}")

    def material_detail(self, material_id):
        material = self.materials.get(material_id)
        if not material:
            return None
        return {"material": material, "claims": list(self.claims.get(material_id, [])), "chunks": []}


def _ops():
    def safe_material_id(value):
        value = str(value)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", value):
            raise ValueError("Invalid material identifier")
        return value

    def check_private_directory(path):
        path = Path(path)
        info = path.lstat()
        if path.is_symlink() or not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("private_directory_untrusted")
        return path

    def ensure_private_directory(path):
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.is_symlink():
            raise ValueError("private_directory_untrusted")
        path.chmod(0o700)
        return check_private_directory(path)

    def read_cache_json(path):
        path = Path(path)
        try:
            info = path.lstat()
        except FileNotFoundError:
            return None, "cache_unreadable"
        if path.is_symlink() or not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            return None, "cache_file_untrusted"
        if info.st_size > 32 * 1024 * 1024:
            return None, "cache_too_large"
        try:
            return json.loads(path.read_text(encoding="utf-8")), None
        except (OSError, ValueError):
            return None, "cache_unreadable"

    def save_json(path, value, *, private=True):
        path = Path(path)
        ensure_private_directory(path.parent)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        path.chmod(0o600 if private else 0o644)

    def cached_material_reason(record, document, settings):
        material = document.get("material", {})
        revision = document.get("revision", {})
        if material.get("id") != str(record.get("id") or record.get("mid")):
            return "cache_identity_mismatch"
        if material.get("url") != (record.get("url") or record.get("link")):
            return "cache_identity_mismatch"
        if material.get("category") != record.get("category"):
            return "cache_identity_mismatch"
        if revision.get("source_url") != (record.get("url") or record.get("link")):
            return "cache_identity_mismatch"
        return None

    return Ops(
        safe_material_id=safe_material_id,
        check_private_directory=check_private_directory,
        ensure_private_directory=ensure_private_directory,
        read_cache_json=read_cache_json,
        save_json=save_json,
        cached_material_reason=cached_material_reason,
    )


def _document(record, settings, *, scope="public_fulltext", chars=600, artifact_created=True):
    material_id = str(record.get("id") or record.get("mid") or record.get("material_id"))
    text = "DSE source detail. " * (chars // 19 + 1)
    text = text[:chars]
    digest = ("a" if material_id.endswith("1") else "b") * 64
    artifact = settings.artifact_root / digest[:2] / digest
    artifact.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    artifact.parent.chmod(0o700)
    if artifact_created:
        artifact.write_bytes(b"r" * 1024)
        artifact.chmod(0o600)
    chunk = {"id": f"chunk-{material_id}", "text": text, "start": 0, "end": len(text), "sha256": "c" * 64}
    material = {
        "id": material_id,
        "title": record.get("title", material_id),
        "url": record.get("url") or record.get("link"),
        "category": record.get("category", "technical"),
        "source": record.get("source", "registry"),
        "head_sha256": record.get("head_sha256"),
    }
    revision = {
        "sha256": digest,
        "source_url": record.get("url") or record.get("link"),
        "scope": scope,
        "bytes": 1024,
        "artifact_path": str(artifact),
    }
    return {"material": material, "text": text, "chunks": [chunk], "revision": revision}


def _assessment(document, role="core_technical", *, cache_hit=False):
    revision = document["revision"]["sha256"]
    provenance = {
        "revision_sha256": revision,
        "method": "jev_advisory",
        "assessment": {"role": role, "confidence": 0.91, "rationale": "bounded source review"},
        "provider_metadata": {
            "provider": "decision_models", "model_selected": "typesafe/jev-1.13",
            "usage": {"input_tokens": 100}, "cache_hit": cache_hit,
        },
        "quality_version": "knowledge-quality/v2",
    }
    return {
        "schema_version": "source-role/v1", "role": role,
        "status": "needs_review" if role == "unclassified" else "assessed",
        "confidence": 0.91, "rationale": "bounded source review", "authority": "curator_annotation",
        "provenance": provenance,
    }


def _record(material_id="doc-1", **extra):
    return {"id": material_id, "title": f"Title {material_id}", "url": f"https://docs.example/{material_id}",
            "category": "technical", "source": "registry", **extra}


def _install(monkeypatch, *, prepare=None, assess=None, index=None, enrich=None, extract=None):
    monkeypatch.setattr(expansion, "_cache_helpers", _ops)
    if prepare is not None:
        monkeypatch.setattr(expansion, "_prepare_material", prepare)
    if assess is not None:
        monkeypatch.setattr(expansion, "_assess_role", assess)
    if index is not None:
        monkeypatch.setattr(expansion, "_index_materials", index)
    if enrich is not None:
        monkeypatch.setattr(expansion, "_enrich_context", enrich)
    if extract is not None:
        monkeypatch.setattr(expansion, "_extract_structured", extract)


def test_make_handlers_builds_lazy_real_stage_functions_without_running_providers(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    store = FakeStore()
    calls = []
    _install(monkeypatch, prepare=lambda *_args: calls.append("prepare"))

    handlers = expansion.make_handlers(settings, store)

    assert set(handlers) == {"acquire", "assess", "index", "extract"}
    assert calls == []
    assert not (settings.data_root / "pilot1000").exists()


def test_acquire_saves_private_prepared_cache_and_reuse_does_not_fetch_or_recount(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    monkeypatch.setattr(expansion, "_cache_helpers", _ops)
    expansion.freeze_artifact_baseline(settings)
    record = _record("doc-1")
    calls = []

    def prepare(selected, current_settings):
        calls.append(selected)
        return _document(selected, current_settings)

    _install(monkeypatch, prepare=prepare)
    acquire = expansion.make_handlers(settings, FakeStore())["acquire"]
    first = acquire(record, {"artifact_budget_remaining_bytes": 40 * 1024 * 1024})
    path = Path(first["metadata"]["prepared_path"])

    assert path.parent == settings.data_root / "pilot1000" / "prepared"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert first["usage"]["artifact_bytes"] == 1024 + path.stat().st_size
    second = acquire(record, {
        "prepared_path": str(path), "artifact_budget_remaining_bytes": 40 * 1024 * 1024,
        "artifact_bytes_committed": first["usage"]["artifact_bytes"],
    })

    assert len(calls) == 1
    assert second["usage"] == {}
    assert second["metadata"]["source_revision_sha256"] == first["metadata"]["source_revision_sha256"]


def test_seeded_old100_prepared_path_reuses_fulltext_without_reacquire(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    record = _record("old100-1")
    old_path = settings.data_root / "pilot100" / "prepared" / "old100-1.json"
    ops = _ops()
    doc = _document(record, settings)
    ops.save_json(old_path, doc)
    monkeypatch.setattr(expansion, "_cache_helpers", _ops)
    expansion.freeze_artifact_baseline(settings)
    store = FakeStore()
    store.materials["old100-1"] = {"role": "core_technical", "role_metadata": {}}
    _install(monkeypatch, prepare=lambda *_args: pytest.fail("seeded material must not reacquire"))

    result = expansion.make_handlers(settings, store)["acquire"](
        record, {"prepared_path": str(old_path), "artifact_budget_remaining_bytes": 40 * 1024 * 1024}
    )

    assert result["metadata"]["prepared_path"] == str(old_path)
    assert result["usage"] == {}


def test_acquire_checks_worst_case_budget_before_prepare(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    _install(monkeypatch, prepare=lambda *_args: pytest.fail("fetch must not start without worst-case headroom"))
    expansion.freeze_artifact_baseline(settings)
    acquire = expansion.make_handlers(settings, FakeStore())["acquire"]

    with pytest.raises(ResourceCollectionError) as error:
        acquire(_record(), {"artifact_budget_remaining_bytes": 40 * 1024 * 1024 - 1})

    assert error.value.code == "artifact_budget_below_worst_case"


def test_abstract_or_short_source_is_permanent_failure_with_new_raw_bytes_accounted(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    monkeypatch.setattr(expansion, "_cache_helpers", _ops)
    expansion.freeze_artifact_baseline(settings)

    def prepare(record, current_settings):
        return _document(record, current_settings, scope="abstract_only", chars=120)

    _install(monkeypatch, prepare=prepare)
    acquire = expansion.make_handlers(settings, FakeStore())["acquire"]

    with pytest.raises(PermanentCollectionError) as error:
        acquire(_record(), {"artifact_budget_remaining_bytes": 40 * 1024 * 1024})

    assert error.value.state == "failed"
    assert error.value.code == "source_fulltext_unavailable"
    assert error.value.artifact_bytes == 1024


def test_crash_after_acquire_replays_new_artifact_bytes_from_frozen_baseline(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    monkeypatch.setattr(expansion, "_cache_helpers", _ops)
    expansion.freeze_artifact_baseline(settings)
    record = _record("doc-1")
    calls = []

    def prepare(selected, current_settings):
        calls.append(selected)
        return _document(selected, current_settings)

    _install(monkeypatch, prepare=prepare)
    acquire = expansion.make_handlers(settings, FakeStore())["acquire"]
    first = acquire(record, {
        "artifact_budget_bytes": 40 * 1024 * 1024,
        "artifact_budget_remaining_bytes": 40 * 1024 * 1024,
        "artifact_bytes_committed": 0,
    })
    expected = first["usage"]["artifact_bytes"]

    # Simulate process death after the files were durable but before item.complete committed.
    resumed = acquire(record, {
        "artifact_budget_bytes": 40 * 1024 * 1024,
        "artifact_budget_remaining_bytes": 40 * 1024 * 1024,
        "artifact_bytes_committed": 0,
    })

    assert len(calls) == 1
    assert resumed["usage"] == {"artifact_bytes": expected}
    assert expansion.artifact_inventory_delta(settings)["physical_artifact_bytes_delta"] == expected
    committed = acquire(record, {
        "prepared_path": resumed["metadata"]["prepared_path"],
        "artifact_budget_bytes": 40 * 1024 * 1024,
        "artifact_budget_remaining_bytes": 40 * 1024 * 1024,
        "artifact_bytes_committed": expected,
    })
    assert committed["usage"] == {}


def test_raw_artifact_orphan_is_charged_even_when_reused_without_new_mtime(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    monkeypatch.setattr(expansion, "_cache_helpers", _ops)
    expansion.freeze_artifact_baseline(settings)
    record = _record("doc-1")
    orphan = _document(record, settings)
    _install(monkeypatch, prepare=lambda *_args: _document(record, settings, artifact_created=False))
    acquire = expansion.make_handlers(settings, FakeStore())["acquire"]
    budget = 40 * 1024 * 1024 + 1024

    result = acquire(record, {
        "artifact_budget_bytes": budget,
        "artifact_budget_remaining_bytes": budget,
        "artifact_bytes_committed": 0,
    })

    prepared_bytes = Path(result["metadata"]["prepared_path"]).stat().st_size
    assert result["usage"]["artifact_bytes"] == orphan["revision"]["bytes"] + prepared_bytes


def test_artifact_baseline_is_create_once_and_does_not_rebase_new_cache(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    monkeypatch.setattr(expansion, "_cache_helpers", _ops)
    original = expansion.freeze_artifact_baseline(settings)
    _document(_record("doc-1"), settings)

    resumed = expansion.freeze_artifact_baseline(settings)

    assert resumed == original
    delta = expansion.artifact_inventory_delta(settings)
    assert delta["raw_artifact_bytes_delta"] == 1024
    assert delta["physical_artifact_bytes_delta"] == 1024


def test_artifact_inventory_counts_growth_of_existing_content_addressed_file(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    monkeypatch.setattr(expansion, "_cache_helpers", _ops)
    document = _document(_record("doc-1"), settings)
    expansion.freeze_artifact_baseline(settings)
    artifact_path = Path(document["revision"]["artifact_path"])
    artifact_path.write_bytes(b"r" * 2048)
    artifact_path.chmod(0o600)

    delta = expansion.artifact_inventory_delta(settings)

    assert delta["raw_artifact_bytes_delta"] == 1024
    assert delta["physical_artifact_bytes_delta"] == 1024


def test_acquire_preflight_subtracts_physical_delta_before_fetch(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    monkeypatch.setattr(expansion, "_cache_helpers", _ops)
    expansion.freeze_artifact_baseline(settings)
    orphan_record = _record("orphan-1")
    orphan_document = _document(orphan_record, settings)
    orphan_path = settings.data_root / "pilot1000" / "prepared" / "orphan-1.json"
    _ops().save_json(orphan_path, orphan_document)
    physical = expansion.artifact_inventory_delta(settings)["physical_artifact_bytes_delta"]
    budget = physical + expansion.WORST_CASE_ACQUIRE_BYTES - 1
    _install(monkeypatch, prepare=lambda *_args: pytest.fail("physical orphan bytes consume preflight headroom"))

    with pytest.raises(ResourceCollectionError) as error:
        expansion.make_handlers(settings, FakeStore())["acquire"](
            _record("doc-1"), {
                "artifact_budget_bytes": budget,
                "artifact_budget_remaining_bytes": budget,
                "artifact_bytes_committed": 0,
            },
        )

    assert error.value.code == "artifact_budget_below_worst_case"


def test_assessment_sidecar_replay_preserves_uncommitted_provider_usage(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    record = _record()
    document = _document(record, settings, artifact_created=False)
    path = settings.data_root / "pilot1000" / "prepared" / "doc-1.json"
    _ops().save_json(path, document)
    monkeypatch.setattr(expansion, "_cache_helpers", _ops)
    expansion.freeze_artifact_baseline(settings)
    assessment = _assessment(document)
    calls = []

    def assess(*_args, **_kwargs):
        calls.append("assess")
        return assessment

    _install(monkeypatch, assess=assess)
    handler = expansion.make_handlers(settings, FakeStore())["assess"]
    first = handler(record, {
        "prepared_path": str(path), "source_revision_sha256": document["revision"]["sha256"],
    })
    # Simulate a crash after the sidecar write but before the fenced item completion.
    replay = handler(record, {
        "prepared_path": str(path), "source_revision_sha256": document["revision"]["sha256"],
    })

    assert calls == ["assess"]
    assert first["usage"] == {"provider": "decision_models", "model": "typesafe/jev-1.13", "input_tokens": 100}
    assert replay["usage"] == first["usage"]


def test_preexisting_assessment_sidecar_cache_hit_does_not_report_provider_success(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    record = _record()
    document = _document(record, settings, artifact_created=False)
    path = settings.data_root / "pilot1000" / "prepared" / "doc-1.json"
    ops = _ops()
    ops.save_json(path, document)
    assessment = _assessment(document)
    monkeypatch.setattr(expansion, "_cache_helpers", _ops)
    expansion._write_assessment_sidecar(
        settings, "doc-1", document, assessment, ops,
    )
    expansion.freeze_artifact_baseline(settings)
    _install(monkeypatch, assess=lambda *_args, **_kwargs: pytest.fail("baseline sidecar is reusable"))

    result = expansion.make_handlers(settings, FakeStore())["assess"](
        record, {"prepared_path": str(path), "source_revision_sha256": document["revision"]["sha256"]},
    )

    assert result["next_state"] == "assessed"
    assert result["usage"] == {}


def test_out_of_scope_assessment_is_sidecar_only_and_releases_before_index(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    record = _record()
    document = _document(record, settings, artifact_created=False)
    ops = _ops()
    prepared_path = settings.data_root / "pilot1000" / "prepared" / "doc-1.json"
    ops.save_json(prepared_path, document)
    assessment = _assessment(document, "out_of_scope")
    _install(monkeypatch, assess=lambda *_args, **_kwargs: assessment)
    store = FakeStore()
    assess = expansion.make_handlers(settings, store)["assess"]

    result = assess(record, {"prepared_path": str(prepared_path), "source_revision_sha256": document["revision"]["sha256"]})

    assert result["next_state"] == "excluded"
    assert result["metadata"]["role"] == "out_of_scope"
    assert not store.materials
    sidecar = settings.data_root / "pilot1000" / "prepared" / "doc-1.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.assessment.json"
    assert sidecar.exists()
    assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600


def test_unclassified_role_needs_review_without_indexing(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    record = _record()
    document = _document(record, settings, artifact_created=False)
    path = settings.data_root / "pilot1000" / "prepared" / "doc-1.json"
    _ops().save_json(path, document)
    _install(monkeypatch, assess=lambda *_args, **_kwargs: _assessment(document, "unclassified"))

    result = expansion.make_handlers(settings, FakeStore())["assess"](
        record, {"prepared_path": str(path), "source_revision_sha256": document["revision"]["sha256"]}
    )

    assert result["next_state"] == "needs_review"


def test_index_commits_role_after_ingested_material_and_noop_skip_does_not_claim_provider_success(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    record = _record()
    document = _document(record, settings, artifact_created=False)
    ops = _ops()
    path = settings.data_root / "pilot1000" / "prepared" / "doc-1.json"
    ops.save_json(path, document)
    assessment = _assessment(document)
    _install(monkeypatch, assess=lambda *_args, **_kwargs: assessment)
    store = FakeStore()
    handlers = expansion.make_handlers(settings, store)
    assessed = handlers["assess"](record, {"prepared_path": str(path), "source_revision_sha256": document["revision"]["sha256"]})
    events = []

    def index(settings_arg, documents, store_arg):
        events.append("index")
        store_arg.materials["doc-1"] = {"role": None, "role_metadata": {}}
        return 1

    monkeypatch.setattr(expansion, "_index_materials", index)
    indexed = handlers["index"](record, {**assessed["metadata"], "prepared_path": str(path)})
    events.extend(event[0] for event in store.events)

    assert indexed["next_state"] == "indexed"
    assert indexed["metadata"]["indexed"] is True
    assert indexed["usage"]["provider"] == "deepinfra"
    assert events == ["index", "assess"]

    skip_calls = []
    monkeypatch.setattr(expansion, "_index_materials", lambda *_args: skip_calls.append(1) or pytest.fail("existing source must skip reindex"))
    skipped = handlers["index"](record, {**assessed["metadata"], "prepared_path": str(path), "indexed": True})
    assert not skip_calls
    assert skipped["usage"] == {}


def test_extract_routes_existing_claims_to_context_enrichment_and_new_docs_to_structured(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    record = _record()
    document = _document(record, settings, artifact_created=False)
    path = settings.data_root / "pilot1000" / "prepared" / "doc-1.json"
    _ops().save_json(path, document)
    assessment = _assessment(document)
    store = FakeStore()
    store.materials["doc-1"] = {"role": None, "role_metadata": {}}
    calls = []
    _install(
        monkeypatch,
        assess=lambda *_args, **_kwargs: assessment,
        enrich=lambda *_args, **_kwargs: calls.append("enrich") or {"material_id": "doc-1", "status": "enriched", "annotations": 2, "provider_metadata": {"provider": "codex_cli", "usage": {}}},
        extract=lambda *_args, **_kwargs: calls.append("structured") or {"material_id": "doc-1", "status": "complete", "claims": 1, "annotations": 1, "provider_metadata": {"provider": "codex_cli", "usage": {}}},
    )
    store.claims["doc-1"] = [{"id": "claim-old", "revision_id": "revision-old"}]
    handlers = expansion.make_handlers(settings, store)
    handlers["assess"](record, {"prepared_path": str(path), "source_revision_sha256": document["revision"]["sha256"]})
    result_existing = handlers["extract"](record, {"prepared_path": str(path), "source_revision_sha256": document["revision"]["sha256"], "role": "core_technical", "indexed": True})

    store.claims["doc-1"] = []
    result_new = handlers["extract"](record, {"prepared_path": str(path), "source_revision_sha256": document["revision"]["sha256"], "role": "core_technical", "indexed": True})

    assert calls == ["enrich", "structured"]
    assert result_existing["next_state"] == "complete"
    assert result_existing["usage"]["provider"] == "codex_cli"
    assert result_new["next_state"] == "complete"
    assert result_new["metadata"]["claim_count"] == 1


def test_navigation_extract_is_reference_only_and_never_calls_model(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    record = _record()
    document = _document(record, settings, artifact_created=False)
    path = settings.data_root / "pilot1000" / "prepared" / "doc-1.json"
    _ops().save_json(path, document)
    _install(monkeypatch, extract=lambda *_args, **_kwargs: pytest.fail("navigation sources have no claims"))
    store = FakeStore()
    store.materials["doc-1"] = {"role": "source_navigation", "role_metadata": {"revision_sha256": document["revision"]["sha256"]}}

    result = expansion.make_handlers(settings, store)["extract"](
        record, {"prepared_path": str(path), "source_revision_sha256": document["revision"]["sha256"], "role": "source_navigation", "indexed": True}
    )

    assert result["next_state"] == "reference_only"


def test_structured_extraction_needs_review_is_not_reported_complete(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    record = _record()
    document = _document(record, settings, artifact_created=False)
    path = settings.data_root / "pilot1000" / "prepared" / "doc-1.json"
    _ops().save_json(path, document)
    store = FakeStore()
    store.materials["doc-1"] = {"role": "core_technical", "role_metadata": {}}
    _install(monkeypatch, assess=lambda *_args, **_kwargs: _assessment(document), extract=lambda *_args, **_kwargs: {"material_id": "doc-1", "status": "needs_review", "claims": 0, "annotations": 0, "provider_metadata": {"skipped": True, "usage": {}}})
    handlers = expansion.make_handlers(settings, store)
    handlers["assess"](record, {"prepared_path": str(path), "source_revision_sha256": document["revision"]["sha256"]})

    result = handlers["extract"](
        record, {"prepared_path": str(path), "source_revision_sha256": document["revision"]["sha256"], "role": "core_technical", "indexed": True}
    )

    assert result["next_state"] == "needs_review"


def test_old_revision_annotation_with_same_claim_id_does_not_suppress_new_provider_usage(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    record = _record()
    document = _document(record, settings, artifact_created=False)
    path = settings.data_root / "pilot1000" / "prepared" / "doc-1.json"
    _ops().save_json(path, document)
    revision = document["revision"]["sha256"]
    store = FakeStore()
    store.materials["doc-1"] = {
        "role": "core_technical", "role_metadata": {"revision_sha256": revision},
    }
    store.claims["doc-1"] = [{"id": "stable-claim", "revision_id": "old-rev", "revision_sha256": "b" * 64}]
    store.annotations.add("stable-claim")  # Annotation exists for the old revision only.
    calls = []
    _install(
        monkeypatch,
        enrich=lambda *_args, **_kwargs: pytest.fail("old revision claims must not use context enrichment"),
        extract=lambda *_args, **_kwargs: calls.append("structured") or {
            "material_id": "doc-1", "status": "complete", "claims": 1, "annotations": 1,
            "provider_metadata": {"provider": "codex_cli", "provider_attempt_count": 1, "usage": {"input_tokens": 8}},
        },
    )

    result = expansion.make_handlers(settings, store)["extract"](
        record, {"prepared_path": str(path), "source_revision_sha256": revision, "role": "core_technical", "indexed": True}
    )

    assert calls == ["structured"]
    assert result["next_state"] == "complete"
    assert result["usage"] == {"provider": "codex_cli", "input_tokens": 8}


def test_safe_classification_distinguishes_source_404_provider_quota_and_invalid_schema():
    class IngestionError(Exception):
        __module__ = "dse_knowledge.ingestion"

        def __init__(self, reason, http_status=None):
            self.reason = reason
            self.http_status = http_status

    class ProviderError(Exception):
        __module__ = "dse_knowledge.providers"

        def __init__(self, reason, http_status=None):
            self.reason = reason
            self.http_status = http_status

    not_found = expansion._classify_error(IngestionError("source_http_error", 404), "acquire")
    quota = expansion._classify_error(ProviderError("provider_failed", 429), "extract")
    invalid = expansion._classify_error(ValueError("raw schema text"), "extract")

    assert isinstance(not_found, PermanentCollectionError)
    assert not_found.code == "source_not_found"
    assert isinstance(quota, RetryableCollectionError)
    assert quota.provider == "codex_cli"
    assert isinstance(invalid, PermanentCollectionError)
    assert invalid.state == "needs_review"
    assert "raw schema text" not in str(invalid)


def test_run_one_worker_constructs_manager_with_bounded_policy_without_cli_or_provider_calls(monkeypatch, tmp_path):
    settings = Settings(tmp_path)
    store = FakeStore()
    repository = SimpleNamespace(
        get_batch=lambda _batch_id: {
            "id": "batch-1", "target": 1, "state": "complete",
            "policy": dict(expansion.DEFAULT_COLLECTION_POLICY),
        },
        list_items=lambda _batch_id: [{
            "material_id": "seed-1", "state": "complete", "next_stage": None,
            "metadata": {"indexed": True, "role": "core_technical"},
            "artifact_bytes": 0, "last_error": None,
        }],
    )
    store.collection_repository = repository

    monkeypatch.setattr(expansion, "_construct_store", lambda _settings: store)
    monkeypatch.setattr(expansion, "_cache_helpers", lambda: pytest.fail("runner must not execute handlers"))
    monkeypatch.setattr(expansion, "artifact_inventory_delta", lambda _settings: {
        "raw_artifact_bytes_delta": 10,
        "prepared_cache_bytes_delta": 15,
        "physical_artifact_bytes_delta": 25,
        "baseline_created_at": "2026-10-25T00:00:00+00:00",
    })

    result = expansion.run_one_worker(settings, "batch-1", "worker-2", max_steps=1)

    assert result["batch_id"] == "batch-1"
    assert result["batch_state"] == "complete"
    assert result["target_met"] is True
    assert result["policy"]["max_workers"] == 4
    assert result["policy"]["stage_caps"] == {"acquire": 1, "assess": None, "index": 2, "extract": 4}
    assert result["artifact_inventory_available"] is True
    assert result["physical_artifact_bytes_delta"] == 25
    assert result["artifact_bytes_ledger_delta"] == 25
