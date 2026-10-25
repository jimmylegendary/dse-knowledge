from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from dse_knowledge.collection import (
    CollectionManager,
    CollectionCooldownError,
    PermanentCollectionError,
    RetryableCollectionError,
    ResourceCollectionError,
    _PostgresRepository,
)


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 25, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


class MemoryRepository:
    """A transition fixture for manager behavior; it does not emulate PostgreSQL SQL."""

    def __init__(self):
        self.batches = {}
        self.items = {}

    def create_batch(self, batch_id, target, policy, items):
        if batch_id in self.batches:
            if self.batches[batch_id]["target"] != target:
                raise ValueError("Batch target is immutable")
            return deepcopy(self.batches[batch_id])
        self.batches[batch_id] = {
            "id": batch_id,
            "target": target,
            "policy": deepcopy(policy),
            "state": "running",
            "provider_failures": {},
            "blocked_at": None,
            "resume_reason": None,
        }
        self.items[batch_id] = {}
        for item in items:
            row = deepcopy(item)
            row.update({"attempts": 0, "artifact_bytes": 0, "next_attempt_at": None, "lease_owner": None, "lease_until": None, "last_error": None, "updated_at": datetime(2026, 10, 25, tzinfo=timezone.utc)})
            self.items[batch_id][row["material_id"]] = row
        return deepcopy(self.batches[batch_id])

    def get_batch(self, batch_id):
        return deepcopy(self.batches.get(batch_id))

    def list_items(self, batch_id):
        return [deepcopy(row) for row in self.items.get(batch_id, {}).values()]

    def _occupied(self, batch_id):
        return sum(
            bool(row["metadata"].get("indexed") or (row.get("next_stage") is not None and row["state"] not in {"complete", "reference_only", "excluded", "needs_review", "failed"}))
            for row in self.items[batch_id].values()
        )

    def promote(self, batch_id):
        batch = self.batches[batch_id]
        remaining = max(0, batch["target"] - self._occupied(batch_id))
        for row in self.items[batch_id].values():
            if remaining <= 0:
                break
            if row["state"] == "pending" and not row["metadata"].get("indexed") and row.get("next_stage") is None:
                row["next_stage"] = "acquire"
                remaining -= 1

    def claim_next(self, batch_id, worker_id, owner, now, lease_seconds, stage_caps, max_workers, retry_max_attempts=3):
        batch = self.batches[batch_id]
        if batch["state"] == "blocked" or batch["state"] in {"complete", "incomplete"}:
            return None
        for row in self.items[batch_id].values():
            lease_expired = row.get("lease_owner") is None or row.get("lease_until") is None or row["lease_until"] <= now
            if (row.get("next_stage") is None or row["state"] in {"complete", "reference_only", "excluded", "needs_review", "failed"}
                    or row.get("attempts", 0) < retry_max_attempts or not lease_expired):
                continue
            previous_error = row.get("last_error") or {}
            stage = row["next_stage"]
            provider_outcome_unknown = previous_error.get("kind") == "provider_retry" and previous_error.get("stage") == stage
            row["state"] = "failed"
            row["next_stage"] = None
            row["next_attempt_at"] = None
            row["last_error"] = {
                "code": "provider_retry_exhausted" if provider_outcome_unknown else "retry_exhausted",
                "kind": "permanent",
                "stage": stage,
                "cause_code": "provider_attempt_outcome_unknown" if provider_outcome_unknown else "attempt_outcome_unknown",
            }
            row["lease_owner"] = None
            row["lease_until"] = None
            row["updated_at"] = now
        live = [
            row for rows in self.items.values() for row in rows.values()
            if row.get("lease_until") and row["lease_until"] > now
        ]
        if len({row.get("_worker_id") for row in live}) >= max_workers:
            return None
        if any(row.get("_worker_id") == worker_id for row in live):
            return None
        self.promote(batch_id)
        candidates = sorted(self.items[batch_id].values(), key=lambda item: item["ordinal"])
        for row in candidates:
            if row["next_stage"] is None:
                continue
            if row["state"] in {"complete", "reference_only", "excluded", "needs_review", "failed"}:
                continue
            if row.get("next_attempt_at") and row["next_attempt_at"] > now:
                continue
            if row.get("lease_until") and row["lease_until"] > now:
                continue
            cap = stage_caps.get(row["next_stage"])
            if cap is not None and sum(1 for other in live if other["next_stage"] == row["next_stage"]) >= cap:
                continue
            row["lease_owner"] = owner
            row["_worker_id"] = worker_id
            row["lease_until"] = now + timedelta(seconds=lease_seconds)
            row["attempts"] += 1
            return deepcopy(row)
        return None

    def heartbeat(self, batch_id, material_id, owner, now, lease_seconds):
        row = self.items[batch_id][material_id]
        if row.get("lease_owner") != owner or not row.get("lease_until") or row["lease_until"] <= now:
            return False
        row["lease_until"] = now + timedelta(seconds=lease_seconds)
        return True

    def complete(self, batch_id, material_id, owner, now, state, next_stage, metadata, usage, current_stage, artifact_bytes=0):
        row = self.items[batch_id][material_id]
        if row.get("lease_owner") != owner or not row.get("lease_until") or row["lease_until"] <= now:
            return False
        row["state"] = state
        row["next_stage"] = next_stage
        row["metadata"].update(deepcopy(metadata))
        row["artifact_bytes"] += artifact_bytes
        row["attempts"] = 0 if next_stage != current_stage else row["attempts"]
        row["last_error"] = None
        row["lease_owner"] = None
        row["lease_until"] = None
        row["next_attempt_at"] = None
        batch = self.batches[batch_id]
        provider = usage.get("provider") if usage else None
        if provider:
            batch["provider_failures"].pop(f"{current_stage}:{provider}", None)
        return True

    def fail(self, batch_id, material_id, owner, now, *, state, next_stage, next_attempt_at, error, provider_key=None, cooldown=3, artifact_bytes=0):
        row = self.items[batch_id][material_id]
        if row.get("lease_owner") != owner or not row.get("lease_until") or row["lease_until"] <= now:
            return False
        row["state"] = state
        row["next_stage"] = next_stage
        row["last_error"] = deepcopy(error)
        row["artifact_bytes"] += artifact_bytes
        row["next_attempt_at"] = next_attempt_at
        row["lease_owner"] = None
        row["lease_until"] = None
        if state in {"failed", "excluded", "needs_review", "reference_only"} and not row["metadata"].get("indexed"):
            row["next_stage"] = None
        batch = self.batches[batch_id]
        if provider_key:
            batch["provider_failures"][provider_key] = batch["provider_failures"].get(provider_key, 0) + 1
            if batch["provider_failures"][provider_key] >= cooldown:
                batch["state"] = "blocked"
                batch["blocked_at"] = now
        self.promote(batch_id)
        return True

    def block(self, batch_id, material_id, owner, now, error, artifact_bytes=0):
        row = self.items[batch_id][material_id]
        if row.get("lease_owner") == owner:
            row["state"] = "retry_wait"
            row["last_error"] = deepcopy(error)
            row["artifact_bytes"] += artifact_bytes
            row["next_attempt_at"] = None
            row["lease_owner"] = None
            row["lease_until"] = None
        self.batches[batch_id]["state"] = "blocked"
        self.batches[batch_id]["blocked_at"] = now

    def resume(self, batch_id, now, reason, cooldown_seconds):
        batch = self.batches[batch_id]
        if batch["state"] != "blocked":
            return False
        if batch["blocked_at"] and now < batch["blocked_at"] + timedelta(seconds=cooldown_seconds):
            raise CollectionCooldownError("cooldown_active")
        batch["state"] = "running"
        batch["provider_failures"] = {}
        batch["blocked_at"] = None
        batch["resume_reason"] = reason
        for row in self.items[batch_id].values():
            if row["state"] == "retry_wait" and row["next_attempt_at"] is None:
                row["next_attempt_at"] = now
        return True

    def set_batch_state(self, batch_id, state, now=None):
        self.batches[batch_id]["state"] = state


def _manager(handlers, *, records=None, target=10, clock=None, disk_free=20 * 1024**3, policy=None, repository=None):
    repository = repository or MemoryRepository()
    clock = clock or Clock()
    configured = {
        "repository": repository,
        "clock": clock,
        "disk_usage": lambda _path: SimpleNamespace(free=disk_free),
        "lease_seconds": 60,
        "heartbeat_interval_seconds": None,
        "host_reserve_bytes": 10 * 1024**3,
        "initial_artifact_budget_bytes": 4 * 1024**3,
        "provider_cooldown_seconds": 30,
        "retry_base_seconds": 1,
        "retry_max_seconds": 60,
        **(policy or {}),
    }
    manager = CollectionManager(repository, "/tmp/collection-test", handlers, configured)
    if records is not None:
        manager.create_batch("batch-1", records, target)
    return manager, repository, clock


def _handlers(*, acquire=None, assess=None, index=None, extract=None):
    defaults = {
        "acquire": lambda record, metadata: {"next_state": "acquired", "metadata": {"prepared_path": f"/tmp/{record['material_id']}.txt"}},
        "assess": lambda record, metadata: {"next_state": "assessed", "metadata": {"role": "core"}},
        "index": lambda record, metadata: {"next_state": "indexed", "metadata": {"source_revision_sha256": "a" * 64}, "usage": {"provider": "embedder", "input_tokens": 10}},
        "extract": lambda record, metadata: {"next_state": "complete", "metadata": {"extraction_version": "v2", "claim_count": 1, "annotation_count": 0}, "usage": {"provider": "codex", "input_tokens": 20}},
    }
    defaults.update({key: value for key, value in {"acquire": acquire, "assess": assess, "index": index, "extract": extract}.items() if value is not None})
    return defaults


def _records(*ids):
    return [{"material_id": material_id, "title": material_id} for material_id in ids]


def test_create_batch_is_idempotent_deduplicates_and_seeds_indexed_sources():
    records = [
        {"material_id": "existing-1", "metadata": {"indexed": True}, "state": "complete"},
        {"material_id": "new-1"},
        {"material_id": "new-1", "title": "duplicate"},
        {"material_id": "new-2"},
    ]
    manager, repository, clock = _manager(_handlers(), records=records, target=2)

    first = manager.summary("batch-1")
    manager.create_batch("batch-1", _records("different-input"), target=2)
    second = manager.summary("batch-1")

    assert first["candidate_count"] == 3
    assert first["indexed_count"] == 1
    assert first["reserved_count"] == 2
    assert second["candidate_count"] == 3
    assert repository.items["batch-1"]["existing-1"]["next_stage"] is None


def test_target_replacement_uses_released_slot_and_never_counts_failures():
    attempted = []

    def acquire(record, metadata):
        attempted.append(record["material_id"])
        if record["material_id"] == "bad-source":
            raise PermanentCollectionError("source_not_found", state="failed")
        return {"next_state": "acquired", "metadata": {"prepared_path": f"/tmp/{record['material_id']}.txt"}}

    manager, repository, _ = _manager(
        _handlers(acquire=acquire), records=_records("bad-source", "good-1", "replacement"), target=2
    )

    manager.run_worker("batch-1", "worker-1")
    summary = manager.summary("batch-1")

    assert summary["indexed_count"] == 2
    assert summary["reserved_count"] == 2
    assert summary["target_met"] is True
    assert summary["full_kg_complete_count"] == 2
    assert summary["completed_count"] == 2
    assert "bad-source" in attempted
    assert repository.items["batch-1"]["bad-source"]["next_stage"] is None


def test_restart_resumes_at_next_stage_without_repeating_acquire_or_index():
    calls = {stage: [] for stage in ("acquire", "assess", "index", "extract")}
    base = _handlers()
    handlers = {
        stage: (lambda record, metadata, stage=stage: (calls[stage].append(record["material_id"]) or base[stage](record, metadata)))
        for stage in calls
    }
    manager, repository, clock = _manager(handlers, records=_records("source-1"), target=1)

    manager.run_worker("batch-1", "worker-1", max_steps=1)
    assert repository.items["batch-1"]["source-1"]["state"] == "acquired"
    resumed = CollectionManager(repository, "/tmp/collection-test", handlers, {"repository": repository, "clock": clock})
    resumed.run_worker("batch-1", "worker-2")

    assert calls == {"acquire": ["source-1"], "assess": ["source-1"], "index": ["source-1"], "extract": ["source-1"]}
    assert resumed.summary("batch-1")["full_kg_complete_count"] == 1


def test_stale_owner_cannot_complete_after_expiry_and_reclaim():
    clock = Clock()
    repository = MemoryRepository()
    lease_owner_seen = []

    def acquire(record, metadata):
        clock.advance(61)
        row = repository.claim_next(
            "batch-1", "worker-new", "worker-new:nonce", clock(), 60,
            {"acquire": 2, "index": 2, "extract": 4}, 4,
        )
        lease_owner_seen.append(row["lease_owner"] if row else None)
        return {"next_state": "acquired", "metadata": {"prepared_path": "/tmp/stale.txt"}}

    manager, repository, _ = _manager(
        _handlers(acquire=acquire), records=_records("source-1"), target=1,
        clock=clock, repository=repository,
        policy={"lease_seconds": 60, "heartbeat_interval_seconds": None},
    )

    manager.run_worker("batch-1", "worker-old", max_steps=1)
    row = repository.items["batch-1"]["source-1"]

    assert lease_owner_seen == ["worker-new:nonce"]
    assert row["lease_owner"] == "worker-new:nonce"
    assert row["state"] == "pending"


def test_heartbeat_keeps_long_handler_lease_alive():
    repository = MemoryRepository()
    started = Event()
    finish = Event()

    def acquire(record, metadata):
        started.set()
        assert finish.wait(2)
        return {"next_state": "acquired", "metadata": {"prepared_path": "/tmp/slow.txt"}}

    manager, repository, _ = _manager(
        _handlers(acquire=acquire), records=_records("source-1"), target=1,
        policy={"lease_seconds": 0.06, "heartbeat_interval_seconds": 0.01},
    )
    thread = Thread(target=lambda: manager.run_worker("batch-1", "worker-1", max_steps=1))
    thread.start()
    assert started.wait(1)
    # The handler runs longer than its original lease; the heartbeat must keep it owned.
    import time
    time.sleep(0.1)
    finish.set()
    thread.join(2)

    assert not thread.is_alive()
    assert repository.items["batch-1"]["source-1"]["state"] == "acquired"


def test_second_worker_cannot_claim_an_item_while_its_lease_is_live():
    started = Event()
    finish = Event()
    calls = []

    def acquire(record, metadata):
        calls.append(record["material_id"])
        started.set()
        assert finish.wait(2)
        return {"next_state": "acquired", "metadata": {"prepared_path": "/tmp/contended.txt"}}

    manager, repository, clock = _manager(
        _handlers(acquire=acquire), records=_records("source-1"), target=1,
        policy={"heartbeat_interval_seconds": None},
    )
    first = Thread(target=lambda: manager.run_worker("batch-1", "worker-1", max_steps=1))
    first.start()
    assert started.wait(1)
    competing = CollectionManager(repository, "/tmp/collection-test", _handlers(acquire=acquire), {
        "repository": repository, "clock": clock, "heartbeat_interval_seconds": None,
    })
    competing.run_worker("batch-1", "worker-2", max_steps=1)
    finish.set()
    first.join(2)

    assert not first.is_alive()
    assert calls == ["source-1"]
    assert repository.items["batch-1"]["source-1"]["state"] == "acquired"


def test_storage_reserve_blocks_acquire_before_handler_runs():
    calls = []
    manager, repository, _ = _manager(
        _handlers(acquire=lambda record, metadata: calls.append(record["material_id"]) or {"next_state": "acquired", "metadata": {}}),
        records=_records("source-1"), target=1, disk_free=9 * 1024**3,
    )

    manager.run_worker("batch-1", "worker-1")

    assert calls == []
    assert manager.summary("batch-1")["batch_state"] == "blocked"
    assert repository.items["batch-1"]["source-1"]["last_error"]["code"] == "storage_reserve"


def test_resource_exception_blocks_batch_without_consuming_target_or_provider_streak():
    def acquire(_record, _metadata):
        raise ResourceCollectionError("artifact_budget_below_worst_case", artifact_bytes=17)

    manager, repository, _ = _manager(_handlers(acquire=acquire), records=_records("source-1"), target=1)

    manager.run_worker("batch-1", "worker-1")

    assert manager.summary("batch-1")["batch_state"] == "blocked"
    assert repository.items["batch-1"]["source-1"]["state"] == "retry_wait"
    assert repository.items["batch-1"]["source-1"]["last_error"]["code"] == "artifact_budget_below_worst_case"
    assert manager.summary("batch-1")["artifact_bytes_used"] == 17
    assert repository.batches["batch-1"]["provider_failures"] == {}


def test_additional_artifact_budget_is_cumulative_and_passed_to_acquire_handler():
    received = []

    def acquire(record, metadata):
        received.append(metadata["artifact_budget_remaining_bytes"])
        return {
            "next_state": "acquired",
            "metadata": {"prepared_path": f"/tmp/{record['material_id']}.txt"},
            "usage": {"artifact_bytes": 50},
        }

    manager, _, _ = _manager(
        _handlers(acquire=acquire), records=_records("one", "two", "three"), target=3,
        disk_free=10 * 1024**3 + 100,
        policy={"initial_artifact_budget_bytes": 100, "artifact_budget_bytes": 100},
    )

    manager.run_worker("batch-1", "worker-1")
    summary = manager.summary("batch-1")

    assert received == [100, 50]
    assert summary["artifact_bytes_used"] == 100
    assert summary["batch_state"] == "blocked"
    assert summary["last_error"]["code"] == "artifact_budget_exhausted"


def test_provider_quota_failures_block_after_three_and_resume_requires_cooldown_reason():
    calls = []
    clock = Clock()

    def acquire(record, metadata):
        calls.append(record["material_id"])
        if record["material_id"] != "fixed-after-resume":
            raise RetryableCollectionError("provider_quota", provider="codex", detail="secret raw body")
        return {"next_state": "acquired", "metadata": {"prepared_path": "/tmp/fixed.txt"}}

    manager, repository, clock = _manager(
        _handlers(acquire=acquire), records=_records("source-1", "source-2", "source-3"), target=3, clock=clock,
        policy={"provider_cooldown_seconds": 30, "retry_base_seconds": 1},
    )
    manager.run_worker("batch-1", "worker-1", max_steps=3)

    assert len(calls) == 3
    assert manager.summary("batch-1")["batch_state"] == "blocked"
    assert "secret raw body" not in repr(manager.summary("batch-1"))
    assert all("secret raw body" not in repr(row["last_error"]) for row in repository.items["batch-1"].values())
    with pytest.raises(CollectionCooldownError):
        manager.resume_batch("batch-1", "quota fix requested")

    clock.advance(31)
    repository.items["batch-1"]["source-1"]["record"]["material_id"] = "fixed-after-resume"
    assert manager.resume_batch("batch-1", "provider quota replenished") is True
    manager.run_worker("batch-1", "worker-2", max_steps=1)

    assert repository.batches["batch-1"]["resume_reason"] == "provider quota replenished"
    assert manager.summary("batch-1")["batch_state"] == "running"


def test_reference_only_is_an_extract_terminal_without_counting_as_full_kg_complete():
    manager, _, _ = _manager(
        _handlers(extract=lambda _record, _metadata: {
            "next_state": "reference_only",
            "metadata": {"extraction_version": "v2", "claim_count": 0, "annotation_count": 0},
        }),
        records=_records("nav-source"), target=1,
    )

    manager.run_worker("batch-1", "worker-1", max_steps=4)
    summary = manager.summary("batch-1")

    assert summary["reference_only_count"] == 1
    assert summary["completed_count"] == 1
    assert summary["full_kg_complete_count"] == 0
    assert summary["stage_progress"]["extract"] == {"completed": 1, "denominator": 1}


def test_postgres_resume_honors_provider_cooldown_after_later_resource_block():
    provider_blocked_at = datetime(2026, 10, 25, tzinfo=timezone.utc)
    resource_blocked_at = provider_blocked_at + timedelta(seconds=5)

    class Cursor:
        def __init__(self, row=None, rowcount=1):
            self.row = row
            self.rowcount = rowcount

        def fetchone(self):
            return self.row

    class Connection:
        def __init__(self):
            self.statements = []

        def execute(self, sql, params=()):
            self.statements.append((sql, params))
            if "SELECT state,provider_failures" in sql:
                return Cursor({"state": "blocked", "provider_failures": {"extract:codex_cli": 3}})
            if "SELECT created_at FROM dse_knowledge.ingest_events" in sql:
                if "provider_cooldown" in sql:
                    return Cursor({"code": "provider_cooldown", "created_at": provider_blocked_at})
                return Cursor({"code": "storage_reserve", "created_at": resource_blocked_at})
            return Cursor()

    class Store:
        def __init__(self):
            self.connection_value = Connection()

        @contextmanager
        def connection(self):
            yield self.connection_value

    store = Store()
    repository = _PostgresRepository(store)

    with pytest.raises(CollectionCooldownError, match="provider_cooldown_active"):
        repository.resume(
            "batch-1", provider_blocked_at + timedelta(seconds=10), "quota fix requested", 30,
        )

    assert repository.resume(
        "batch-1", provider_blocked_at + timedelta(seconds=31), "provider quota replenished", 30,
    ) is True
    resume_statement = next(
        params for sql, params in store.connection_value.statements if "collection_resumed" in sql
    )
    assert resume_statement[2].obj == {
        "batch_id": "batch-1", "reason": "provider quota replenished",
    }


def test_provider_failure_streak_is_scoped_to_extract_provider_and_stage():
    calls = {stage: 0 for stage in ("acquire", "assess", "index", "extract")}

    def count(stage, result):
        def handler(record, metadata):
            calls[stage] += 1
            if stage == "extract":
                raise RetryableCollectionError("provider_quota", provider="codex")
            return result(record, metadata)
        return handler

    base = _handlers()
    handlers = {
        "acquire": count("acquire", lambda record, metadata: {"next_state": "acquired", "metadata": {}, "usage": {"provider": "http_fetch"}}),
        "assess": count("assess", lambda record, metadata: {"next_state": "assessed", "metadata": {}, "usage": {"provider": "jev"}}),
        "index": count("index", lambda record, metadata: {"next_state": "indexed", "metadata": {}, "usage": {"provider": "embedder"}}),
        "extract": count("extract", base["extract"]),
    }
    manager, repository, _ = _manager(handlers, records=_records("one", "two", "three"), target=3)

    manager.run_worker("batch-1", "worker-1")

    assert calls == {"acquire": 3, "assess": 3, "index": 3, "extract": 3}
    assert repository.batches["batch-1"]["provider_failures"] == {"extract:codex": 3}
    assert manager.summary("batch-1")["batch_state"] == "blocked"


def _ready_for_extract(repository, batch_id, *material_ids):
    for material_id in material_ids:
        row = repository.items[batch_id][material_id]
        row["state"] = "indexed"
        row["next_stage"] = "extract"
        row["metadata"]["indexed"] = True


class RecordingMemoryRepository(MemoryRepository):
    def __init__(self):
        super().__init__()
        self.events = []

    def ingest_event(self, material_id, status, detail):
        self.events.append((material_id, status, deepcopy(detail)))


def test_provider_retry_cap_exhausts_item_even_when_other_successes_reset_streak():
    calls = []

    def extract(record, _metadata):
        material_id = record["material_id"]
        calls.append(material_id)
        if material_id == "retrying-source":
            raise RetryableCollectionError("codex_timeout", provider="codex_cli")
        return {
            "next_state": "complete",
            "metadata": {"claim_count": 1, "annotation_count": 1},
            "usage": {"provider": "codex_cli"},
        }

    ids = ("retrying-source", "success-one", "success-two", "success-three")
    manager, repository, clock = _manager(
        _handlers(extract=extract), records=_records(*ids), target=len(ids),
        policy={"retry_max_attempts": 3},
    )
    _ready_for_extract(repository, "batch-1", *ids)

    for worker_id in ("worker-one", "worker-two", "worker-three"):
        manager.run_worker("batch-1", worker_id, max_steps=2)
        clock.advance(2)

    item = repository.items["batch-1"]["retrying-source"]
    summary = manager.summary("batch-1")
    assert calls.count("retrying-source") == 3
    assert item["attempts"] == 3
    assert item["state"] == "failed"
    assert item["next_stage"] is None
    assert item["last_error"] == {
        "code": "provider_retry_exhausted",
        "kind": "permanent",
        "stage": "extract",
        "cause_code": "codex_timeout",
    }
    assert summary["last_error"]["cause_code"] == "codex_timeout"
    assert repository.batches["batch-1"]["provider_failures"] == {}

    manager.run_worker("batch-1", "worker-four", max_steps=1)
    assert calls.count("retrying-source") == 3


def test_third_provider_retry_exhaustion_still_records_and_trips_circuit():
    calls = []

    def extract(_record, _metadata):
        calls.append(1)
        raise RetryableCollectionError("codex_timeout", provider="codex_cli")

    manager, repository, clock = _manager(
        _handlers(extract=extract), records=_records("source-1"), target=1,
        policy={"retry_max_attempts": 3}, repository=RecordingMemoryRepository(),
    )
    _ready_for_extract(repository, "batch-1", "source-1")

    for worker_id in ("worker-one", "worker-two", "worker-three"):
        manager.run_worker("batch-1", worker_id, max_steps=1)
        clock.advance(2)

    item = repository.items["batch-1"]["source-1"]
    assert calls == [1, 1, 1]
    assert item["state"] == "failed"
    assert item["last_error"]["code"] == "provider_retry_exhausted"
    assert item["last_error"]["cause_code"] == "codex_timeout"
    assert repository.batches["batch-1"]["provider_failures"] == {"extract:codex_cli": 3}
    assert manager.summary("batch-1")["batch_state"] == "blocked"
    assert ("source-1", "collection_failed", {
        "batch_id": "batch-1", "stage": "extract", "state": "failed",
        "code": "provider_retry_exhausted", "cause_code": "codex_timeout", "worker_id": "worker-three",
    }) in repository.events

    manager.run_worker("batch-1", "worker-four", max_steps=1)
    assert calls == [1, 1, 1]


def test_provider_exhaustion_is_not_resurrected_by_explicit_batch_resume():
    calls = []

    def extract(_record, _metadata):
        calls.append(1)
        raise RetryableCollectionError("codex_timeout", provider="codex_cli")

    manager, repository, clock = _manager(
        _handlers(extract=extract), records=_records("source-1"), target=1,
        policy={"retry_max_attempts": 3, "provider_cooldown_seconds": 30},
    )
    _ready_for_extract(repository, "batch-1", "source-1")
    for worker_id in ("worker-one", "worker-two", "worker-three"):
        manager.run_worker("batch-1", worker_id, max_steps=1)
        clock.advance(2)
    clock.advance(31)

    assert manager.resume_batch("batch-1", "operator reviewed retry policy") is True
    assert repository.batches["batch-1"]["provider_failures"] == {}
    manager.run_worker("batch-1", "worker-after-resume", max_steps=1)

    item = repository.items["batch-1"]["source-1"]
    assert calls == [1, 1, 1]
    assert item["state"] == "failed"
    assert item["next_stage"] is None
    assert item["last_error"]["code"] == "provider_retry_exhausted"


def test_stale_owner_cannot_commit_provider_retry_exhaustion_or_circuit_count():
    calls = []
    clock = Clock()

    def extract(_record, _metadata):
        calls.append(1)
        clock.advance(61)
        raise RetryableCollectionError("codex_timeout", provider="codex_cli")

    manager, repository, _ = _manager(
        _handlers(extract=extract), records=_records("source-1"), target=1,
        clock=clock, policy={"retry_max_attempts": 3, "lease_seconds": 60},
    )
    _ready_for_extract(repository, "batch-1", "source-1")
    repository.items["batch-1"]["source-1"]["attempts"] = 2

    manager.run_worker("batch-1", "worker-stale", max_steps=1)

    item = repository.items["batch-1"]["source-1"]
    assert calls == [1]
    assert item["state"] == "indexed"
    assert item["last_error"] is None
    assert item["lease_owner"].startswith("worker-stale:")
    assert repository.batches["batch-1"]["provider_failures"] == {}

    manager.run_worker("batch-1", "worker-after-expiry", max_steps=1)

    item = repository.items["batch-1"]["source-1"]
    assert calls == [1]
    assert item["attempts"] == 3
    assert item["state"] == "failed"
    assert item["next_stage"] is None
    assert item["last_error"] == {
        "code": "retry_exhausted",
        "kind": "permanent",
        "stage": "extract",
        "cause_code": "attempt_outcome_unknown",
    }
    assert repository.batches["batch-1"]["provider_failures"] == {}


def test_expired_third_provider_lease_is_terminalized_before_fourth_handler_attempt():
    calls = []
    clock = Clock()

    def extract(_record, _metadata):
        calls.append(1)
        if len(calls) == 3:
            clock.advance(61)
        raise RetryableCollectionError("codex_timeout", provider="codex_cli")

    manager, repository, _ = _manager(
        _handlers(extract=extract), records=_records("source-1"), target=1,
        clock=clock, policy={"retry_max_attempts": 3, "lease_seconds": 60},
    )
    _ready_for_extract(repository, "batch-1", "source-1")

    for worker_id in ("worker-one", "worker-two"):
        manager.run_worker("batch-1", worker_id, max_steps=1)
        clock.advance(2)
    assert repository.items["batch-1"]["source-1"]["attempts"] == 2
    assert repository.batches["batch-1"]["provider_failures"] == {"extract:codex_cli": 2}

    manager.run_worker("batch-1", "worker-stale-third", max_steps=1)
    stale_row = repository.items["batch-1"]["source-1"]
    assert calls == [1, 1, 1]
    assert stale_row["attempts"] == 3
    assert stale_row["state"] == "retry_wait"
    assert stale_row["lease_until"] <= clock()
    assert repository.batches["batch-1"]["provider_failures"] == {"extract:codex_cli": 2}

    manager.run_worker("batch-1", "worker-after-expiry", max_steps=1)

    item = repository.items["batch-1"]["source-1"]
    assert calls == [1, 1, 1]
    assert item["attempts"] == 3
    assert item["state"] == "failed"
    assert item["next_stage"] is None
    assert item["lease_owner"] is None
    assert item["last_error"] == {
        "code": "provider_retry_exhausted",
        "kind": "permanent",
        "stage": "extract",
        "cause_code": "provider_attempt_outcome_unknown",
    }
    assert repository.batches["batch-1"]["provider_failures"] == {"extract:codex_cli": 2}


def test_active_attempt_at_retry_cap_is_not_terminalized_before_owner_finishes():
    started = Event()
    finish = Event()
    calls = []

    def extract(_record, _metadata):
        calls.append(1)
        started.set()
        assert finish.wait(2)
        raise RetryableCollectionError("codex_timeout", provider="codex_cli")

    manager, repository, clock = _manager(
        _handlers(extract=extract), records=_records("source-1"), target=1,
        policy={"retry_max_attempts": 3, "lease_seconds": 60},
    )
    _ready_for_extract(repository, "batch-1", "source-1")
    repository.items["batch-1"]["source-1"]["attempts"] = 2
    worker = Thread(target=lambda: manager.run_worker("batch-1", "worker-active", max_steps=1))
    worker.start()
    assert started.wait(1)

    manager.run_worker("batch-1", "worker-observer", max_steps=1)

    active_item = repository.items["batch-1"]["source-1"]
    assert calls == [1]
    assert active_item["attempts"] == 3
    assert active_item["state"] == "indexed"
    assert active_item["lease_until"] > clock()
    assert active_item["lease_owner"].startswith("worker-active:")

    finish.set()
    worker.join(2)
    assert not worker.is_alive()
    item = repository.items["batch-1"]["source-1"]
    assert item["state"] == "failed"
    assert item["last_error"]["code"] == "provider_retry_exhausted"
    assert item["last_error"]["cause_code"] == "codex_timeout"


@pytest.mark.parametrize("retry_cap", [1, 2])
def test_expired_lease_at_nondefault_retry_cap_never_starts_an_extra_handler(retry_cap):
    calls = []
    clock = Clock()

    def extract(_record, _metadata):
        calls.append(1)
        clock.advance(61)
        raise RetryableCollectionError("codex_timeout", provider="codex_cli")

    manager, repository, _ = _manager(
        _handlers(extract=extract), records=_records("source-1"), target=1,
        clock=clock, policy={"retry_max_attempts": retry_cap, "lease_seconds": 60},
    )
    _ready_for_extract(repository, "batch-1", "source-1")
    repository.items["batch-1"]["source-1"]["attempts"] = retry_cap - 1

    manager.run_worker("batch-1", "worker-first", max_steps=1)
    manager.run_worker("batch-1", "worker-after-expiry", max_steps=1)

    item = repository.items["batch-1"]["source-1"]
    assert calls == [1]
    assert item["attempts"] == retry_cap
    assert item["state"] == "failed"
    assert item["next_stage"] is None
    assert item["last_error"]["code"] == "retry_exhausted"
    assert item["last_error"]["cause_code"] == "attempt_outcome_unknown"
    assert repository.batches["batch-1"]["provider_failures"] == {}


def test_non_provider_transient_retries_have_a_finite_attempt_limit():
    calls = []

    def acquire(_record, _metadata):
        calls.append(1)
        raise RetryableCollectionError("database_transient", provider=False, retry_after_seconds=1)

    manager, repository, clock = _manager(
        _handlers(acquire=acquire), records=_records("source-1"), target=1,
        policy={"retry_max_attempts": 3},
    )
    for _ in range(2):
        manager.run_worker("batch-1", f"worker-{len(calls)}", max_steps=1)
        clock.advance(2)
    manager.run_worker("batch-1", "worker-final", max_steps=1)

    assert len(calls) == 3
    assert manager.summary("batch-1")["batch_state"] == "incomplete"
    assert repository.items["batch-1"]["source-1"]["last_error"]["code"] == "retry_exhausted"
    assert repository.batches["batch-1"]["provider_failures"] == {}


def test_empty_success_rate_has_no_zero_denominator_division():
    manager, _, _ = _manager(_handlers(), records=[], target=10)

    result = manager.summary("batch-1")

    assert result["candidate_count"] == 0
    assert result["completed_count"] == 0
    assert result["success_rate"] is None
    assert result["indexed_count"] == 0
    assert result["indexed_rate"] == 0.0


def test_extraction_needs_review_stays_in_indexed_denominator_without_claiming_kg_complete():
    manager, repository, _ = _manager(
        _handlers(extract=lambda _record, _metadata: {"next_state": "needs_review", "metadata": {"claim_count": 0}}),
        records=_records("source-1"), target=1,
    )

    manager.run_worker("batch-1", "worker-1")
    result = manager.summary("batch-1")

    assert result["indexed_count"] == 1
    assert result["full_kg_complete_count"] == 0
    assert result["indexed_needs_review_count"] == 1
    assert result["target_met"] is True
    assert repository.items["batch-1"]["source-1"]["metadata"]["indexed"] is True


def test_permanent_policy_exclusion_does_not_count_as_provider_failure():
    def acquire(_record, _metadata):
        raise PermanentCollectionError("policy_excluded", state="excluded")

    manager, repository, _ = _manager(
        _handlers(acquire=acquire), records=_records("source-1"), target=1,
    )

    manager.run_worker("batch-1", "worker-1")

    assert manager.summary("batch-1")["indexed_count"] == 0
    assert manager.summary("batch-1")["batch_state"] == "incomplete"
    assert repository.batches["batch-1"]["provider_failures"] == {}


def test_collection_schema_declares_skip_locked_tables_and_fenced_lease_fields():
    from pathlib import Path

    sql = (Path(__file__).parents[1] / "migrations" / "004_collection.sql").read_text().lower()

    assert "collection_batches" in sql
    assert "collection_items" in sql
    assert "provider_failures jsonb" in sql
    assert "artifact_bytes bigint" in sql
    assert "lease_owner text" in sql
    assert "lease_until timestamptz" in sql


def test_from_batch_keeps_frozen_budget_and_summary_explains_budget_basis():
    manager, repository, clock = _manager(
        _handlers(), records=_records("source-1"), target=1,
        policy={"initial_artifact_budget_bytes": 100, "artifact_budget_bytes": 100},
    )

    resumed = CollectionManager.from_batch(
        repository, "/tmp/collection-test", _handlers(), "batch-1",
        {"repository": repository, "clock": clock, "initial_artifact_budget_bytes": 1000, "artifact_budget_bytes": 900},
    )
    summary = resumed.summary("batch-1")

    assert resumed.artifact_budget == 100
    assert summary["policy"]["artifact_budget_bytes"] == 100
    assert "8 MiB source plus 32 MiB prepared-cache" in summary["policy"]["artifact_budget_basis"]


def test_postgres_item_listing_omits_record_payload_and_progress_uses_aggregates():
    class QueryStore:
        def __init__(self):
            self.statements = []

        def rows(self, sql, args=()):
            self.statements.append(sql)
            return []

        def one(self, sql, args=()):
            self.statements.append(sql)
            if "count(*) FILTER" in sql:
                return {key: 0 for key in (
                    "candidate_count", "indexed_count", "reserved_count", "complete_count", "reference_count",
                    "indexed_needs_review_count", "excluded_count", "needs_review_count", "retry_wait_count",
                    "failed_count", "active_lease_count", "unfinished_count", "pending_unreserved_count",
                    "acquire_completed_count", "assess_completed_count", "index_completed_count",
                    "extract_completed_count", "artifact_bytes_used",
                )}
            return None

    from dse_knowledge.collection import _PostgresRepository

    store = QueryStore()
    repository = _PostgresRepository(store)
    repository.list_items("batch-1")
    progress = repository.progress("batch-1", datetime(2026, 10, 25, tzinfo=timezone.utc))

    assert "record" not in store.statements[0].lower()
    assert any("count(*) FILTER" in sql and "sum(artifact_bytes)" in sql for sql in store.statements)
    assert progress["candidate_count"] == 0


def test_postgres_claim_next_returns_selected_row_with_fenced_lease():
    class Cursor:
        def __init__(self, row=None, rows=None):
            self.row = row
            self.rows = rows or []

        def fetchone(self):
            return self.row

        def fetchall(self):
            return self.rows

    class Connection:
        def __init__(self):
            self.statements = []

        def execute(self, sql, params=()):
            normalized = " ".join(sql.split())
            self.statements.append((normalized, params))
            if normalized.startswith("SELECT state,target FROM dse_knowledge.collection_batches"):
                return Cursor({"state": "running", "target": 1})
            if normalized.startswith("SELECT target FROM dse_knowledge.collection_batches"):
                return Cursor({"target": 1})
            if "COALESCE((metadata->>'indexed')" in normalized and "count(*) AS n" in normalized:
                return Cursor({"n": 1})
            if normalized.startswith("SELECT count(DISTINCT split_part"):
                return Cursor({"n": 0})
            if normalized.startswith("SELECT 1 FROM dse_knowledge.collection_items"):
                return Cursor()
            if "GROUP BY next_stage" in normalized:
                return Cursor(rows=[])
            if normalized.startswith("SELECT material_id FROM dse_knowledge.collection_items"):
                return Cursor({"material_id": "doc-1"})
            if normalized.startswith("UPDATE dse_knowledge.collection_items") and "RETURNING *" in normalized:
                return Cursor({
                    "batch_id": "batch-1", "material_id": "doc-1", "record": {"id": "doc-1"},
                    "state": "pending", "next_stage": "acquire", "lease_owner": params[0],
                })
            return Cursor()

    class Store:
        def __init__(self):
            self.connection_value = Connection()

        @contextmanager
        def connection(self):
            yield self.connection_value

    from dse_knowledge.collection import _PostgresRepository

    store = Store()
    repository = _PostgresRepository(store)
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    row = repository.claim_next(
        "batch-1", "worker-1", "worker-1:token", now, 60,
        {"acquire": 1, "assess": None, "index": 2, "extract": 4}, 4,
    )

    assert row["material_id"] == "doc-1"
    assert row["lease_owner"] == "worker-1:token"
    selected_sql = next(sql for sql, _ in store.connection_value.statements if sql.startswith("SELECT material_id FROM"))
    assert "FOR UPDATE SKIP LOCKED" in selected_sql
    lease_sql = next(sql for sql, _ in store.connection_value.statements if sql.startswith("UPDATE dse_knowledge.collection_items") and "RETURNING *" in sql)
    assert "lease_until<=%s" in lease_sql


def test_postgres_completion_and_stage_receipt_share_one_fenced_transaction():
    class Cursor:
        def __init__(self, row=None, rowcount=1):
            self.row = row
            self.rowcount = rowcount

        def fetchone(self):
            return self.row

    class TransactionStore:
        def __init__(self):
            self.transactions = []
            self.invocations = []

        @contextmanager
        def connection(self):
            statements = []
            self.transactions.append(statements)
            yield self.Connection(statements)

        class Connection:
            def __init__(self, statements):
                self.statements = statements

            def execute(self, sql, args=()):
                normalized = " ".join(sql.split())
                self.statements.append(normalized)
                if normalized.startswith("INSERT INTO dse_knowledge.invocations"):
                    self.statements_owner.invocations.append((normalized, args))
                if normalized.startswith("SELECT provider_failures"):
                    return Cursor({"provider_failures": {}})
                if normalized.startswith("UPDATE dse_knowledge.collection_items") and "RETURNING material_id" in normalized:
                    return Cursor({"material_id": "source-1"})
                return Cursor(rowcount=1)

            @property
            def statements_owner(self):
                return store

    from dse_knowledge.collection import _PostgresRepository

    store = TransactionStore()
    repository = _PostgresRepository(store)
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)

    assert repository.complete(
        "batch-1", "source-1", "worker:token", now, "complete", None,
        {"indexed": True}, {"provider": "codex_cli", "input_tokens": 8}, "extract",
    ) is True
    assert repository.complete(
        "batch-1", "source-2", "worker:token", now, "reference_only", None,
        {"indexed": True}, {}, "extract",
    ) is True
    statements = store.transactions[0]

    item_update = next(i for i, sql in enumerate(statements) if sql.startswith("UPDATE dse_knowledge.collection_items"))
    invocation_insert = next(i for i, sql in enumerate(statements) if sql.startswith("INSERT INTO dse_knowledge.invocations"))
    stage_event_insert = next(i for i, sql in enumerate(statements) if sql.startswith("INSERT INTO dse_knowledge.ingest_events"))
    assert item_update < invocation_insert < stage_event_insert
    assert any("lease_owner=%s AND lease_until>%s" in sql for sql in statements if sql.startswith("UPDATE dse_knowledge.collection_items"))
    first_receipt_sql, first_receipt_args = store.invocations[0]
    assert "'collection_stage','stage_receipt'" in first_receipt_sql
    assert first_receipt_args[1].obj == {
        "record_kind": "stage_receipt",
        "authoritative_provider_usage": False,
        "reported_provider": "codex_cli",
        "reported_usage": {"provider": "codex_cli", "input_tokens": 8},
    }
    second_receipt = store.invocations[1][1][1].obj
    assert second_receipt["reported_provider"] is None
    assert second_receipt["reported_usage"] == {}


def test_postgres_resource_block_locks_batch_before_item_to_match_completion_order():
    class Cursor:
        def __init__(self, row=None, rowcount=1):
            self.row = row
            self.rowcount = rowcount

        def fetchone(self):
            return self.row

    class TransactionStore:
        def __init__(self):
            self.statements = []

        @contextmanager
        def connection(self):
            yield self

        def execute(self, sql, _args=()):
            normalized = " ".join(sql.split())
            self.statements.append(normalized)
            if normalized.startswith("SELECT id FROM dse_knowledge.collection_batches"):
                return Cursor({"id": "batch-1"})
            return Cursor(rowcount=1)

    from dse_knowledge.collection import _PostgresRepository

    store = TransactionStore()
    repository = _PostgresRepository(store)

    assert repository.block(
        "batch-1", "source-1", "worker:token", datetime(2026, 10, 25, tzinfo=timezone.utc),
        {"code": "storage_reserve"},
    ) is True

    assert store.statements[0].startswith("SELECT id FROM dse_knowledge.collection_batches")
    assert store.statements[1].startswith("UPDATE dse_knowledge.collection_items")
