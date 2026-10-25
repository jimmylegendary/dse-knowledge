"""Durable, lease-based collection of source materials into the knowledge ledger."""
from __future__ import annotations

import math
import hashlib
import re
import shutil
import threading
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from psycopg.types.json import Jsonb
except ImportError:  # Keep transition tests runnable without the optional DB runtime installed.
    class Jsonb:  # type: ignore[no-redef]
        def __init__(self, obj):
            self.obj = obj


ITEM_STATES = {
    "pending", "acquired", "assessed", "indexed", "complete", "reference_only",
    "excluded", "needs_review", "retry_wait", "failed",
}
STAGES = ("acquire", "assess", "index", "extract")
TERMINAL_STATES = {"complete", "reference_only", "excluded", "needs_review", "failed"}
METADATA_KEYS = (
    "prepared_path", "source_revision_sha256", "role", "indexed",
    "extraction_version", "claim_count", "annotation_count",
)
DEFAULT_STAGE_CAPS = {"acquire": 1, "assess": None, "index": 2, "extract": 4}
DEFAULT_HOST_RESERVE_BYTES = 10 * 1024**3
DEFAULT_ARTIFACT_BUDGET_BYTES = 4 * 1024**3
PROVIDER_FAILURE_LIMIT = 3
_SAFE_CODE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_code(value: Any, fallback: str) -> str:
    if isinstance(value, str) and _SAFE_CODE.fullmatch(value):
        return value
    return fallback


class CollectionError(Exception):
    """Base class for safe collection control errors."""


class RetryableCollectionError(CollectionError):
    """Retry a stage later without retaining provider error text."""

    def __init__(
        self,
        code: str = "retryable_error",
        *,
        provider: bool | str | None = False,
        retry_after_seconds: float | None = None,
        detail: str | None = None,
    ):
        # detail is intentionally ignored; callers may pass provider text here.
        super().__init__("Collection stage may be retried")
        self.code = _safe_code(code, "retryable_error")
        self.provider = provider if type(provider) is bool or isinstance(provider, str) else False
        self.retry_after_seconds = retry_after_seconds


class PermanentCollectionError(CollectionError):
    """A source or policy outcome that must not be retried automatically."""

    def __init__(self, code: str = "permanent_failure", *, state: str = "failed", detail: str | None = None, artifact_bytes: int = 0):
        # detail is intentionally ignored; callers may pass raw source/provider text here.
        super().__init__("Collection stage permanently failed")
        if state not in {"failed", "excluded", "needs_review", "reference_only"}:
            raise ValueError("Permanent collection error requires a terminal state")
        if type(artifact_bytes) is not int or artifact_bytes < 0:
            raise ValueError("artifact_bytes must be a nonnegative integer")
        self.code = _safe_code(code, "permanent_failure")
        self.state = state
        self.artifact_bytes = artifact_bytes


class CollectionCooldownError(CollectionError):
    """A provider-blocked batch has not reached its manual resume time."""


class ResourceCollectionError(CollectionError):
    """Stop the batch for an injected resource guard without consuming provider retries."""

    def __init__(self, code: str = "resource_budget_exhausted", *, artifact_bytes: int = 0):
        super().__init__("Collection batch blocked by a resource guard")
        if type(artifact_bytes) is not int or artifact_bytes < 0:
            raise ValueError("artifact_bytes must be a nonnegative integer")
        self.code = _safe_code(code, "resource_budget_exhausted")
        self.artifact_bytes = artifact_bytes


class _PostgresRepository:
    """PostgreSQL implementation; unit fixtures use a separate transition repository."""

    _CLAIM_LOCK_KEY = 20261025
    durable_stage_events = True

    def __init__(self, store):
        self.store = store

    def create_batch(self, batch_id, target, policy, items):
        with self.store.connection() as connection:
            inserted = connection.execute(
                """INSERT INTO dse_knowledge.collection_batches(id,target,policy,state,counters,provider_failures)
                   VALUES(%s,%s,%s,'running','{}'::jsonb,'{}'::jsonb)
                   ON CONFLICT(id) DO NOTHING RETURNING id""",
                (batch_id, target, Jsonb(policy)),
            ).fetchone()
            if inserted is None:
                existing = connection.execute(
                    "SELECT id,target FROM dse_knowledge.collection_batches WHERE id=%s FOR UPDATE",
                    (batch_id,),
                ).fetchone()
                if not existing:
                    raise RuntimeError("Collection batch disappeared during create")
                if int(existing["target"]) != target:
                    raise ValueError("Batch target is immutable")
                return existing
            for item in items:
                connection.execute(
                    """INSERT INTO dse_knowledge.collection_items
                       (batch_id,material_id,record,state,next_stage,attempts,next_attempt_at,lease_owner,
                        lease_until,last_error,metadata)
                       VALUES(%s,%s,%s,%s,%s,0,NULL,NULL,NULL,NULL,%s)""",
                    (
                        batch_id, item["material_id"], Jsonb(item["record"]), item["state"],
                        item["next_stage"], Jsonb(item["metadata"]),
                    ),
                )
            self._promote_in_connection(connection, batch_id, target)
        return self.get_batch(batch_id)

    def get_batch(self, batch_id):
        return self.store.one(
            "SELECT id,target,policy,state,counters,provider_failures,created_at,updated_at "
            "FROM dse_knowledge.collection_batches WHERE id=%s", (batch_id,),
        )

    def list_items(self, batch_id):
        return self.store.rows(
            """SELECT batch_id,material_id,state,next_stage,attempts,artifact_bytes,next_attempt_at,
                      lease_owner,lease_until,last_error,metadata,created_at,updated_at
               FROM dse_knowledge.collection_items WHERE batch_id=%s ORDER BY created_at,material_id""",
            (batch_id,),
        )

    def progress(self, batch_id, now):
        row = self.store.one(
            """SELECT
                 count(*) AS candidate_count,
                 count(*) FILTER (WHERE COALESCE((metadata->>'indexed')::boolean,false)) AS indexed_count,
                 count(*) FILTER (WHERE COALESCE((metadata->>'indexed')::boolean,false)
                   OR (next_stage IS NOT NULL AND state NOT IN ('complete','reference_only','excluded','needs_review','failed'))) AS reserved_count,
                 count(*) FILTER (WHERE state='complete') AS complete_count,
                 count(*) FILTER (WHERE state='reference_only') AS reference_count,
                 count(*) FILTER (WHERE state='needs_review' AND COALESCE((metadata->>'indexed')::boolean,false)) AS indexed_needs_review_count,
                 count(*) FILTER (WHERE state='excluded') AS excluded_count,
                 count(*) FILTER (WHERE state='needs_review') AS needs_review_count,
                 count(*) FILTER (WHERE state='retry_wait') AS retry_wait_count,
                 count(*) FILTER (WHERE state='failed') AS failed_count,
                 count(*) FILTER (WHERE lease_until>%s) AS active_lease_count,
                 count(*) FILTER (WHERE next_stage IS NOT NULL AND state NOT IN ('complete','reference_only','excluded','needs_review','failed')) AS unfinished_count,
                 count(*) FILTER (WHERE state='pending' AND next_stage IS NULL) AS pending_unreserved_count,
                 count(*) FILTER (WHERE state IN ('acquired','assessed','indexed','complete')
                   OR COALESCE((metadata->>'indexed')::boolean,false)) AS acquire_completed_count,
                 count(*) FILTER (WHERE state IN ('assessed','indexed','complete')
                   OR COALESCE((metadata->>'indexed')::boolean,false)) AS assess_completed_count,
                 count(*) FILTER (WHERE COALESCE((metadata->>'indexed')::boolean,false)) AS index_completed_count,
                 count(*) FILTER (WHERE state IN ('complete','reference_only')
                   OR (state='needs_review' AND COALESCE((metadata->>'indexed')::boolean,false))) AS extract_completed_count,
                 COALESCE(sum(artifact_bytes),0) AS artifact_bytes_used,
                 COALESCE((SELECT jsonb_object_agg(error_code,n) FROM (
                   SELECT COALESCE(last_error->>'code','unknown_error') AS error_code,count(*) AS n
                   FROM dse_knowledge.collection_items
                   WHERE batch_id=%s AND last_error IS NOT NULL GROUP BY 1
                 ) error_summary),'{}'::jsonb) AS error_counts,
                 (SELECT last_error FROM dse_knowledge.collection_items
                  WHERE batch_id=%s AND last_error IS NOT NULL
                  ORDER BY updated_at DESC,material_id LIMIT 1) AS last_error
               FROM dse_knowledge.collection_items WHERE batch_id=%s""",
            (now, batch_id, batch_id, batch_id),
        ) or {}
        return {**row, "error_counts": _as_mapping(row.get("error_counts")),
                "last_error": _as_mapping(row.get("last_error")) if row.get("last_error") else None}

    @staticmethod
    def _promote_in_connection(connection, batch_id, target):
        batch = connection.execute(
            "SELECT target FROM dse_knowledge.collection_batches WHERE id=%s FOR UPDATE", (batch_id,),
        ).fetchone()
        if not batch:
            raise KeyError(batch_id)
        target = int(batch["target"] if target is None else target)
        occupied = connection.execute(
            """SELECT count(*) AS n FROM dse_knowledge.collection_items
               WHERE batch_id=%s AND (
                 COALESCE((metadata->>'indexed')::boolean,false)
                 OR (next_stage IS NOT NULL AND state NOT IN ('complete','reference_only','excluded','needs_review','failed')))""",
            (batch_id,),
        ).fetchone()["n"]
        remaining = max(0, target - int(occupied))
        if not remaining:
            return
        candidates = connection.execute(
            """SELECT material_id FROM dse_knowledge.collection_items
               WHERE batch_id=%s AND state='pending'
                 AND NOT COALESCE((metadata->>'indexed')::boolean,false)
                 AND next_stage IS NULL
               ORDER BY COALESCE((record->>'_collection_ordinal')::integer,2147483647),material_id
               LIMIT %s FOR UPDATE SKIP LOCKED""",
            (batch_id, remaining),
        ).fetchall()
        for candidate in candidates:
            connection.execute(
                "UPDATE dse_knowledge.collection_items SET next_stage='acquire',updated_at=now() "
                "WHERE batch_id=%s AND material_id=%s",
                (batch_id, candidate["material_id"]),
            )

    def promote(self, batch_id):
        with self.store.connection() as connection:
            self._promote_in_connection(connection, batch_id, None)

    def claim_next(self, batch_id, worker_id, owner, now, lease_seconds, stage_caps, max_workers):
        with self.store.connection() as connection:
            # Serialize capacity checks so concurrent workers cannot overbook global stage caps.
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (self._CLAIM_LOCK_KEY,))
            batch = connection.execute(
                "SELECT state,target FROM dse_knowledge.collection_batches WHERE id=%s FOR UPDATE",
                (batch_id,),
            ).fetchone()
            if not batch or batch["state"] in {"blocked", "complete", "incomplete"}:
                return None
            self._promote_in_connection(connection, batch_id, int(batch["target"]))
            live_workers = connection.execute(
                """SELECT count(DISTINCT split_part(lease_owner,':',1)) AS n
                   FROM dse_knowledge.collection_items
                   WHERE lease_owner IS NOT NULL AND lease_until>%s""", (now,),
            ).fetchone()["n"]
            same_worker = connection.execute(
                """SELECT 1 FROM dse_knowledge.collection_items
                   WHERE lease_owner IS NOT NULL AND lease_until>%s
                     AND split_part(lease_owner,':',1)=%s LIMIT 1""", (now, worker_id),
            ).fetchone()
            if same_worker or int(live_workers) >= max_workers:
                return None
            active = connection.execute(
                """SELECT next_stage,count(*) AS n FROM dse_knowledge.collection_items
                   WHERE lease_owner IS NOT NULL AND lease_until>%s GROUP BY next_stage""", (now,),
            ).fetchall()
            active_by_stage = {row["next_stage"]: int(row["n"]) for row in active}
            eligible_stages = [
                stage for stage in STAGES
                if stage_caps.get(stage) is None or active_by_stage.get(stage, 0) < stage_caps[stage]
            ]
            if not eligible_stages:
                return None
            selected = connection.execute(
                """SELECT material_id FROM dse_knowledge.collection_items
                   WHERE batch_id=%s AND next_stage=ANY(%s)
                     AND state NOT IN ('complete','reference_only','excluded','needs_review','failed')
                     AND (next_attempt_at IS NULL OR next_attempt_at<=%s)
                     AND (lease_until IS NULL OR lease_until<=%s)
                   ORDER BY COALESCE((record->>'_collection_ordinal')::integer,2147483647),material_id
                   LIMIT 1 FOR UPDATE SKIP LOCKED""",
                (batch_id, eligible_stages, now, now),
            ).fetchone()
            if selected is None:
                return None
            return connection.execute(
                """UPDATE dse_knowledge.collection_items
                   SET lease_owner=%s,lease_until=%s + make_interval(secs=>%s),attempts=attempts+1,updated_at=%s
                   WHERE batch_id=%s AND material_id=%s
                     AND (lease_until IS NULL OR lease_until<=%s)
                   RETURNING *""",
                (owner, now, lease_seconds, now, batch_id, selected["material_id"], now),
            ).fetchone()

    def heartbeat(self, batch_id, material_id, owner, now, lease_seconds):
        with self.store.connection() as connection:
            row = connection.execute(
                """UPDATE dse_knowledge.collection_items
                   SET lease_until=%s + make_interval(secs=>%s),updated_at=%s
                   WHERE batch_id=%s AND material_id=%s AND lease_owner=%s AND lease_until>%s
                   RETURNING material_id""",
                (now, lease_seconds, now, batch_id, material_id, owner, now),
            ).fetchone()
            return row is not None

    def complete(self, batch_id, material_id, owner, now, state, next_stage, metadata, usage, current_stage, artifact_bytes=0):
        with self.store.connection() as connection:
            batch = connection.execute(
                "SELECT provider_failures FROM dse_knowledge.collection_batches WHERE id=%s FOR UPDATE",
                (batch_id,),
            ).fetchone()
            if not batch:
                return False
            changed = connection.execute(
                """UPDATE dse_knowledge.collection_items
                   SET state=%s,next_stage=%s,attempts=CASE WHEN %s THEN 0 ELSE attempts END,
                       metadata=metadata || %s::jsonb,artifact_bytes=artifact_bytes+%s,
                       last_error=NULL,next_attempt_at=NULL,
                       lease_owner=NULL,lease_until=NULL,updated_at=%s
                   WHERE batch_id=%s AND material_id=%s AND lease_owner=%s AND lease_until>%s
                   RETURNING material_id""",
                (
                    state, next_stage, next_stage != current_stage, Jsonb(metadata), artifact_bytes, now,
                    batch_id, material_id, owner, now,
                ),
            ).fetchone()
            if changed is None:
                return False
            provider = usage.get("provider") if usage else None
            if isinstance(provider, str) and provider:
                key = f"{current_stage}:{provider}"
                connection.execute(
                    """UPDATE dse_knowledge.collection_batches
                       SET provider_failures=provider_failures-%s,updated_at=%s WHERE id=%s""",
                    (key, now, batch_id),
                )
            reported_usage = CollectionManager._safe_usage(_as_mapping(usage))
            receipt = {
                "record_kind": "stage_receipt",
                "authoritative_provider_usage": False,
                "reported_provider": reported_usage.get("provider"),
                "reported_usage": reported_usage,
            }
            invocation_id = self._event_id("collection-stage-receipt", batch_id, material_id, current_stage)
            connection.execute(
                """INSERT INTO dse_knowledge.invocations(id,provider,purpose,metadata,created_at)
                   VALUES(%s,'collection_stage','stage_receipt',%s,%s) ON CONFLICT(id) DO NOTHING""",
                (invocation_id, Jsonb(receipt), now),
            )
            event_id = self._event_id("collection-stage", batch_id, material_id, current_stage, state)
            connection.execute(
                """INSERT INTO dse_knowledge.ingest_events(id,material_id,status,detail,created_at)
                   VALUES(%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING""",
                (event_id, material_id, f"collection_{current_stage}_{state}",
                 Jsonb({"batch_id": batch_id, "stage": current_stage, "state": state, "usage": usage}), now),
            )
        return True

    @staticmethod
    def _event_id(*parts):
        value = "\x1f".join(str(part) for part in parts).encode("utf-8")
        return hashlib.sha256(value).hexdigest()[:32]

    def fail(self, batch_id, material_id, owner, now, *, state, next_stage, next_attempt_at, error, provider_key=None, cooldown=PROVIDER_FAILURE_LIMIT, artifact_bytes=0):
        with self.store.connection() as connection:
            batch = connection.execute(
                "SELECT provider_failures FROM dse_knowledge.collection_batches WHERE id=%s FOR UPDATE",
                (batch_id,),
            ).fetchone()
            if not batch:
                return False
            item = connection.execute(
                """SELECT metadata FROM dse_knowledge.collection_items
                   WHERE batch_id=%s AND material_id=%s AND lease_owner=%s AND lease_until>%s FOR UPDATE""",
                (batch_id, material_id, owner, now),
            ).fetchone()
            if item is None:
                return False
            metadata = _as_mapping(item["metadata"])
            if state in TERMINAL_STATES and not metadata.get("indexed"):
                next_stage = None
            connection.execute(
                """UPDATE dse_knowledge.collection_items
                   SET state=%s,next_stage=%s,next_attempt_at=%s,last_error=%s,metadata=%s,
                       artifact_bytes=artifact_bytes+%s,lease_owner=NULL,lease_until=NULL,updated_at=%s
                   WHERE batch_id=%s AND material_id=%s AND lease_owner=%s AND lease_until>%s""",
                (
                    state, next_stage, next_attempt_at, Jsonb(error), Jsonb(metadata), artifact_bytes, now,
                    batch_id, material_id, owner, now,
                ),
            )
            provider_failures = _as_mapping(batch["provider_failures"])
            if provider_key:
                count = int(provider_failures.get(provider_key, 0)) + 1
                provider_failures[provider_key] = count
                batch_state = "blocked" if count >= cooldown else None
                connection.execute(
                    """UPDATE dse_knowledge.collection_batches
                       SET provider_failures=%s,state=COALESCE(%s,state),updated_at=%s
                       WHERE id=%s""",
                    (Jsonb(provider_failures), batch_state, now, batch_id),
                )
                if batch_state == "blocked":
                    connection.execute(
                        """INSERT INTO dse_knowledge.ingest_events(id,material_id,status,detail,created_at)
                           VALUES(%s,%s,'collection_blocked',%s,%s)""",
                        (uuid.uuid4().hex, f"batch:{batch_id}", Jsonb({"batch_id": batch_id, "code": "provider_cooldown", "stage_provider_key": provider_key}), now),
                    )
            self._promote_in_connection(connection, batch_id, None)
        return True

    def block(self, batch_id, material_id, owner, now, error, artifact_bytes=0):
        with self.store.connection() as connection:
            batch = connection.execute(
                "SELECT id FROM dse_knowledge.collection_batches WHERE id=%s FOR UPDATE", (batch_id,),
            ).fetchone()
            if not batch:
                return False
            updated = connection.execute(
                """UPDATE dse_knowledge.collection_items SET state='retry_wait',next_attempt_at=NULL,last_error=%s,
                     artifact_bytes=artifact_bytes+%s,
                     lease_owner=NULL,lease_until=NULL,updated_at=%s
                   WHERE batch_id=%s AND material_id=%s AND lease_owner=%s AND lease_until>%s""",
                (Jsonb(error), artifact_bytes, now, batch_id, material_id, owner, now),
            ).rowcount
            if not updated:
                return False
            connection.execute(
                "UPDATE dse_knowledge.collection_batches SET state='blocked',updated_at=%s WHERE id=%s",
                (now, batch_id),
            )
            connection.execute(
                """INSERT INTO dse_knowledge.ingest_events(id,material_id,status,detail,created_at)
                   VALUES(%s,%s,'collection_blocked',%s,%s)""",
                (uuid.uuid4().hex, f"batch:{batch_id}", Jsonb({"batch_id": batch_id, "code": error["code"]}), now),
            )
        return True

    def resume(self, batch_id, now, reason, cooldown_seconds):
        with self.store.connection() as connection:
            batch = connection.execute(
                "SELECT state,provider_failures FROM dse_knowledge.collection_batches WHERE id=%s FOR UPDATE",
                (batch_id,),
            ).fetchone()
            if not batch or batch["state"] != "blocked":
                return False
            provider_block = connection.execute(
                """SELECT created_at FROM dse_knowledge.ingest_events
                   WHERE material_id=%s AND status='collection_blocked' AND detail->>'batch_id'=%s
                     AND detail->>'code'='provider_cooldown'
                   ORDER BY created_at DESC,id DESC LIMIT 1""",
                (f"batch:{batch_id}", batch_id),
            ).fetchone()
            if provider_block and now < provider_block["created_at"] + timedelta(seconds=cooldown_seconds):
                raise CollectionCooldownError("provider_cooldown_active")
            connection.execute(
                """UPDATE dse_knowledge.collection_batches
                   SET state='running',provider_failures='{}'::jsonb,updated_at=%s WHERE id=%s""",
                (now, batch_id),
            )
            connection.execute(
                """UPDATE dse_knowledge.collection_items SET next_attempt_at=%s,updated_at=%s
                   WHERE batch_id=%s AND state='retry_wait'""", (now, now, batch_id),
            )
            connection.execute(
                """INSERT INTO dse_knowledge.ingest_events(id,material_id,status,detail,created_at)
                   VALUES(%s,%s,'collection_resumed',%s,%s)""",
                (uuid.uuid4().hex, f"batch:{batch_id}", Jsonb({"batch_id": batch_id, "reason": reason}), now),
            )
        return True

    def set_batch_state(self, batch_id, state, now):
        self.store.execute(
            "UPDATE dse_knowledge.collection_batches SET state=%s,updated_at=%s WHERE id=%s",
            (state, now, batch_id),
        )

    def update_counters(self, batch_id, counters):
        self.store.execute(
            "UPDATE dse_knowledge.collection_batches SET counters=%s,updated_at=now() WHERE id=%s",
            (Jsonb(counters), batch_id),
        )


class CollectionManager:
    """Coordinate durable acquire/assess/index/extract work with PostgreSQL leases."""

    def __init__(self, store, data_root, handlers, policy):
        self.store = store
        self.data_root = Path(data_root)
        self.handlers = dict(handlers or {})
        missing = [stage for stage in STAGES if not callable(self.handlers.get(stage))]
        if missing:
            raise ValueError(f"Missing collection handlers: {', '.join(missing)}")
        self.policy = dict(policy or {})
        self.repository = self.policy.get("repository") or _PostgresRepository(store)
        self.clock = self.policy.get("clock") or _utcnow
        self.disk_usage = self.policy.get("disk_usage") or shutil.disk_usage
        self.lease_seconds = self._positive_number(self.policy.get("lease_seconds", 120), "lease_seconds")
        heartbeat_default = max(0.1, self.lease_seconds / 3)
        self.heartbeat_interval = self.policy.get("heartbeat_interval_seconds", heartbeat_default)
        if self.heartbeat_interval is not None:
            self.heartbeat_interval = self._positive_number(self.heartbeat_interval, "heartbeat_interval_seconds")
        self.host_reserve_bytes = self._nonnegative_int(
            self.policy.get("host_reserve_bytes", DEFAULT_HOST_RESERVE_BYTES), "host_reserve_bytes"
        )
        self.initial_artifact_budget = self._nonnegative_int(
            self.policy.get("initial_artifact_budget_bytes", DEFAULT_ARTIFACT_BUDGET_BYTES), "initial_artifact_budget_bytes"
        )
        self.artifact_budget = self._nonnegative_int(
            self.policy.get("artifact_budget_bytes", self.initial_artifact_budget), "artifact_budget_bytes"
        )
        if self.artifact_budget > self.initial_artifact_budget and not str(self.policy.get("artifact_budget_ruling", "")).strip():
            raise ValueError("Expanded artifact budget requires artifact_budget_ruling")
        self.provider_cooldown_seconds = self._positive_number(
            self.policy.get("provider_cooldown_seconds", 300), "provider_cooldown_seconds"
        )
        self.retry_base_seconds = self._positive_number(self.policy.get("retry_base_seconds", 5), "retry_base_seconds")
        self.retry_max_seconds = self._positive_number(self.policy.get("retry_max_seconds", 3600), "retry_max_seconds")
        self.retry_max_attempts = self._positive_int(self.policy.get("retry_max_attempts", 3), "retry_max_attempts")
        self.max_workers = min(4, self._positive_int(self.policy.get("max_workers", 4), "max_workers"))
        self.stage_caps = dict(DEFAULT_STAGE_CAPS)
        requested_caps = _as_mapping(self.policy.get("stage_caps"))
        for stage in STAGES:
            if stage not in requested_caps or requested_caps[stage] is None:
                continue
            self.stage_caps[stage] = min(int(DEFAULT_STAGE_CAPS.get(stage) or requested_caps[stage]), self._positive_int(requested_caps[stage], f"{stage}_cap"))

    @classmethod
    def from_batch(cls, store, data_root, handlers, batch_id, policy=None):
        """Construct a manager using the durable policy frozen when the batch was created."""
        supplied = dict(policy or {})
        repository = supplied.get("repository") or _PostgresRepository(store)
        batch = repository.get_batch(batch_id)
        if not batch:
            raise KeyError(batch_id)
        persisted = _as_mapping(batch.get("policy"))
        supplied.update(persisted)
        if isinstance(policy, Mapping):
            for injection in ("repository", "clock", "disk_usage", "heartbeat_interval_seconds"):
                if injection in policy:
                    supplied[injection] = policy[injection]
        return cls(store, data_root, handlers, supplied)

    def _apply_batch_policy(self, batch):
        persisted = _as_mapping(batch.get("policy"))
        if not persisted:
            return
        effective = dict(persisted)
        effective.update({
            "repository": self.repository,
            "clock": self.clock,
            "disk_usage": self.disk_usage,
            "heartbeat_interval_seconds": self.heartbeat_interval,
        })
        configured = CollectionManager(self.store, self.data_root, self.handlers, effective)
        for attribute in (
            "policy", "lease_seconds", "heartbeat_interval", "host_reserve_bytes",
            "initial_artifact_budget", "artifact_budget", "provider_cooldown_seconds",
            "retry_base_seconds", "retry_max_seconds", "retry_max_attempts", "max_workers", "stage_caps",
        ):
            setattr(self, attribute, getattr(configured, attribute))

    @staticmethod
    def _positive_number(value, name):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value <= 0:
            raise ValueError(f"{name} must be positive")
        return float(value)

    @staticmethod
    def _positive_int(value, name):
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
        return value

    @staticmethod
    def _nonnegative_int(value, name):
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a nonnegative integer")
        return value

    def _persisted_policy(self):
        return {
            "host_reserve_bytes": self.host_reserve_bytes,
            "initial_artifact_budget_bytes": self.initial_artifact_budget,
            "artifact_budget_bytes": self.artifact_budget,
            "artifact_budget_ruling": str(self.policy.get("artifact_budget_ruling", ""))[:300],
            "lease_seconds": self.lease_seconds,
            "max_workers": self.max_workers,
            "stage_caps": self.stage_caps,
            "provider_cooldown_seconds": self.provider_cooldown_seconds,
            "retry_base_seconds": self.retry_base_seconds,
            "retry_max_seconds": self.retry_max_seconds,
            "retry_max_attempts": self.retry_max_attempts,
        }

    @staticmethod
    def _material_id(record):
        for key in ("material_id", "id", "mid"):
            value = record.get(key) if isinstance(record, Mapping) else None
            if isinstance(value, (str, int)) and str(value).strip():
                return str(value).strip()
        raise ValueError("Each collection record needs a material_id")

    @staticmethod
    def _initial_stage(state, metadata):
        if state == "pending" or state == "retry_wait":
            return "acquire"
        if state == "acquired":
            return "assess"
        if state == "assessed":
            return "index"
        if state == "indexed":
            return "extract"
        return None

    def _normalize_record(self, ordinal, record):
        if not isinstance(record, Mapping):
            raise ValueError("Collection records must be mappings")
        material_id = self._material_id(record)
        source_metadata = _as_mapping(record.get("metadata"))
        metadata = {key: source_metadata.get(key) for key in METADATA_KEYS}
        if metadata["role"] is None:
            metadata["role"] = record.get("role")
        metadata["indexed"] = metadata.get("indexed") is True
        metadata["claim_count"] = max(0, int(metadata.get("claim_count") or 0))
        metadata["annotation_count"] = max(0, int(metadata.get("annotation_count") or 0))
        state = record.get("state") or record.get("initial_state")
        if state is None:
            state = "complete" if metadata["indexed"] else "pending"
        if state not in ITEM_STATES:
            raise ValueError(f"Invalid initial collection state: {state}")
        if state == "complete" and not metadata["indexed"]:
            raise ValueError("A complete seed must already be indexed")
        if state == "indexed":
            metadata["indexed"] = True
        next_stage = record.get("next_stage")
        if next_stage is None:
            next_stage = self._initial_stage(state, metadata)
        if next_stage is not None and next_stage not in STAGES:
            raise ValueError("Invalid next collection stage")
        if state in TERMINAL_STATES and next_stage is not None:
            raise ValueError("Terminal collection items cannot have a next_stage")
        if state not in TERMINAL_STATES and next_stage is None:
            raise ValueError("Nonterminal collection items need a next_stage")
        stored_record = deepcopy(dict(record))
        stored_record["_collection_ordinal"] = ordinal
        return {
            "ordinal": ordinal,
            "material_id": material_id,
            "record": stored_record,
            "state": state,
            "next_stage": next_stage,
            "metadata": metadata,
        }

    def create_batch(self, batch_id, records, target):
        if not isinstance(batch_id, str) or not batch_id.strip():
            raise ValueError("batch_id must be a non-empty string")
        target = self._positive_int(target, "target")
        if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
            raise ValueError("records must be a sequence")
        normalized = []
        seen = set()
        for record in records:
            item = self._normalize_record(len(normalized), record)
            if item["material_id"] in seen:
                continue
            seen.add(item["material_id"])
            normalized.append(item)
        indexed_count = sum(bool(item["metadata"]["indexed"]) for item in normalized)
        if indexed_count > target:
            raise ValueError("Indexed seed count exceeds collection target")
        remaining = target - indexed_count
        for item in normalized:
            if item["metadata"]["indexed"]:
                continue
            if item["state"] in TERMINAL_STATES:
                continue
            if remaining > 0:
                remaining -= 1
            else:
                # Pending rows with no next_stage remain in the fixed candidate manifest
                # but do not occupy one of the target slots yet.
                item["next_stage"] = None
        self.repository.create_batch(batch_id.strip(), target, self._persisted_policy(), normalized)
        return self.summary(batch_id.strip())

    def _artifact_capacity(self, batch_id):
        try:
            free = int(self.disk_usage(self.data_root).free)
        except Exception:
            return 0, "storage_check_failed"
        if free <= self.host_reserve_bytes:
            return 0, "storage_reserve"
        used = int(self._progress(batch_id).get("artifact_bytes_used", 0))
        return max(0, min(self.artifact_budget - used, free - self.host_reserve_bytes)), None

    def _progress(self, batch_id):
        reader = getattr(self.repository, "progress", None)
        now = self.clock()
        if callable(reader):
            return reader(batch_id, now)
        items = self.repository.list_items(batch_id)
        metadata = [_as_mapping(item.get("metadata")) for item in items]
        indexed = sum(meta.get("indexed") is True for meta in metadata)
        complete = sum(item.get("state") == "complete" for item in items)
        reference = sum(item.get("state") == "reference_only" for item in items)
        indexed_needs_review = sum(item.get("state") == "needs_review" and meta.get("indexed") is True for item, meta in zip(items, metadata))
        active = sum(bool(item.get("lease_until") and item["lease_until"] > now) for item in items)
        unfinished = sum(item.get("next_stage") is not None and item.get("state") not in TERMINAL_STATES for item in items)
        pending_unreserved = sum(item.get("state") == "pending" and item.get("next_stage") is None for item in items)
        reserved = sum(
            meta.get("indexed") is True or (item.get("next_stage") is not None and item.get("state") not in TERMINAL_STATES)
            for item, meta in zip(items, metadata)
        )
        errors = Counter(
            _safe_code(_as_mapping(item.get("last_error")).get("code"), "unknown_error")
            for item in items if item.get("last_error")
        )
        latest = next((item.get("last_error") for item in sorted(items, key=lambda row: row.get("updated_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True) if item.get("last_error")), None)
        return {
            "candidate_count": len(items), "indexed_count": indexed, "reserved_count": reserved,
            "complete_count": complete, "reference_count": reference,
            "indexed_needs_review_count": indexed_needs_review,
            "excluded_count": sum(item.get("state") == "excluded" for item in items),
            "needs_review_count": sum(item.get("state") == "needs_review" for item in items),
            "retry_wait_count": sum(item.get("state") == "retry_wait" for item in items),
            "failed_count": sum(item.get("state") == "failed" for item in items),
            "active_lease_count": active, "unfinished_count": unfinished,
            "pending_unreserved_count": pending_unreserved,
            "acquire_completed_count": sum(item.get("state") in {"acquired", "assessed", "indexed", "complete"} or meta.get("indexed") is True for item, meta in zip(items, metadata)),
            "assess_completed_count": sum(item.get("state") in {"assessed", "indexed", "complete"} or meta.get("indexed") is True for item, meta in zip(items, metadata)),
            "index_completed_count": indexed, "extract_completed_count": complete + reference + indexed_needs_review,
            "artifact_bytes_used": sum(max(0, int(item.get("artifact_bytes") or 0)) for item in items),
            "error_counts": dict(errors), "last_error": latest,
        }

    @staticmethod
    def _result(stage, value, current_metadata):
        if not isinstance(value, Mapping):
            raise ValueError("Collection handler must return a mapping")
        state = value.get("next_state")
        metadata = value.get("metadata", {})
        usage = value.get("usage", {})
        if not isinstance(metadata, Mapping) or not isinstance(usage, Mapping):
            raise ValueError("Handler metadata and usage must be mappings")
        allowed = {
            "acquire": {"acquired", "excluded", "needs_review", "reference_only", "failed"},
            "assess": {"assessed", "excluded", "needs_review", "reference_only", "failed"},
            "index": {"indexed", "needs_review", "reference_only", "failed"},
            "extract": {"complete", "needs_review", "reference_only", "failed"},
        }
        if state not in allowed[stage]:
            raise ValueError("Handler returned an invalid next_state for the current stage")
        merged = {key: value for key, value in _as_mapping(current_metadata).items() if key in METADATA_KEYS}
        for key in METADATA_KEYS:
            if key in metadata:
                merged[key] = metadata[key]
        if state == "indexed":
            merged["indexed"] = True
        elif _as_mapping(current_metadata).get("indexed") is True:
            merged["indexed"] = True
        else:
            merged["indexed"] = False
        for key in ("claim_count", "annotation_count"):
            if type(merged.get(key)) is not int or merged.get(key) < 0:
                raise ValueError(f"Handler metadata {key} must be a nonnegative integer")
        if state == "acquired":
            next_stage = "assess"
        elif state == "assessed":
            next_stage = "index"
        elif state == "indexed":
            next_stage = "extract"
        else:
            next_stage = None
        return state, next_stage, merged, dict(usage)

    @staticmethod
    def _safe_usage(usage):
        safe = {}
        for key in ("provider", "model", "input_tokens", "output_tokens", "total_tokens", "cached_tokens", "duration_seconds"):
            value = usage.get(key)
            if key in {"provider", "model"} and isinstance(value, str) and len(value) <= 120:
                safe[key] = value
            elif key.endswith("tokens") and type(value) is int and value >= 0:
                safe[key] = value
            elif key == "duration_seconds" and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and value >= 0:
                safe[key] = float(value)
        return safe

    def _event(self, item, status, detail):
        writer = getattr(self.store, "ingest_event", None)
        if callable(writer):
            safe = {key: value for key, value in detail.items() if key in {"batch_id", "stage", "state", "code", "usage", "worker_id"}}
            try:
                writer(item["material_id"], status, safe)
            except Exception:
                # The durable item row remains the source of truth if diagnostic logging fails.
                pass

    def _invocation(self, stage, usage):
        safe = self._safe_usage(usage)
        provider = safe.get("provider")
        writer = getattr(self.store, "invocation", None)
        if provider and callable(writer):
            try:
                writer(provider, f"collection_{stage}", safe)
            except Exception:
                pass

    def _heartbeat_loop(self, batch_id, item, owner, stop, lost):
        if self.heartbeat_interval is None:
            return
        while not stop.wait(self.heartbeat_interval):
            try:
                ok = self.repository.heartbeat(
                    batch_id, item["material_id"], owner, self.clock(), self.lease_seconds,
                )
            except Exception:
                ok = False
            if not ok:
                lost.set()
                return

    def _retry_time(self, attempts, requested):
        exponent = min(max(0, int(attempts) - 1), 30)
        delay = min(self.retry_max_seconds, self.retry_base_seconds * (2**exponent))
        if isinstance(requested, (int, float)) and not isinstance(requested, bool) and math.isfinite(float(requested)):
            delay = min(self.retry_max_seconds, max(delay, max(1.0, float(requested))))
        return self.clock() + timedelta(seconds=delay)

    def _provider_key(self, stage, provider):
        if type(provider) is bool:
            provider_name = "unknown" if provider else None
        elif isinstance(provider, str) and provider.strip():
            provider_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", provider.strip())[:80] or "unknown"
        else:
            provider_name = None
        return f"{stage}:{provider_name}" if provider_name else None

    def _record_retry(self, batch_id, item, owner, stage, exc, worker_id):
        provider_key = self._provider_key(stage, exc.provider)
        if provider_key is None and int(item.get("attempts", 1)) >= self.retry_max_attempts:
            self._record_permanent(
                batch_id, item, owner, stage,
                PermanentCollectionError("retry_exhausted", state="failed"), worker_id,
            )
            return
        error = {
            "code": _safe_code(exc.code, "provider_error" if provider_key else "retryable_error"),
            "kind": "provider_retry" if provider_key else "retryable",
            "stage": stage,
        }
        now = self.clock()
        next_attempt_at = self._retry_time(item.get("attempts", 1), exc.retry_after_seconds)
        accepted = self.repository.fail(
            batch_id, item["material_id"], owner, now,
            state="retry_wait", next_stage=stage, next_attempt_at=next_attempt_at, error=error,
            provider_key=provider_key, cooldown=PROVIDER_FAILURE_LIMIT,
        )
        if accepted:
            self.repository.promote(batch_id)
            self._event(item, "collection_retry_wait", {"batch_id": batch_id, "stage": stage, "code": error["code"], "worker_id": worker_id})

    def _record_permanent(self, batch_id, item, owner, stage, exc, worker_id):
        error = {"code": _safe_code(exc.code, "permanent_failure"), "kind": "permanent", "stage": stage}
        state = exc.state
        now = self.clock()
        accepted = self.repository.fail(
            batch_id, item["material_id"], owner, now,
            state=state, next_stage=None, next_attempt_at=None, error=error,
            artifact_bytes=exc.artifact_bytes,
        )
        if accepted:
            self.repository.promote(batch_id)
            self._event(item, f"collection_{state}", {"batch_id": batch_id, "stage": stage, "state": state, "code": error["code"], "worker_id": worker_id})

    def _finish(self, batch_id, item, owner, stage, result, worker_id):
        try:
            state, next_stage, metadata, usage = self._result(stage, result, item.get("metadata"))
        except Exception:
            self._record_permanent(
                batch_id, item, owner, stage,
                PermanentCollectionError("handler_contract_error", state="failed"), worker_id,
            )
            return False
        safe_usage = self._safe_usage(usage)
        if stage == "acquire":
            artifact_bytes = usage.get("artifact_bytes", 0)
            remaining = item.get("metadata", {}).get("artifact_budget_remaining_bytes")
            if type(artifact_bytes) is not int or artifact_bytes < 0 or (isinstance(remaining, int) and artifact_bytes > remaining):
                self.repository.block(
                    batch_id, item["material_id"], owner, self.clock(),
                    {"code": "artifact_budget_exceeded", "kind": "storage", "stage": stage},
                    artifact_bytes,
                )
                return False
        else:
            artifact_bytes = 0
        accepted = self.repository.complete(
            batch_id, item["material_id"], owner, self.clock(), state, next_stage,
            metadata, safe_usage, stage, artifact_bytes,
        )
        if not accepted:
            self._event(item, "collection_stale_completion", {"batch_id": batch_id, "stage": stage, "code": "lease_lost", "worker_id": worker_id})
            return False
        if not getattr(self.repository, "durable_stage_events", False):
            self._invocation(stage, safe_usage)
            self._event(item, f"collection_{stage}_{state}", {"batch_id": batch_id, "stage": stage, "state": state, "usage": safe_usage, "worker_id": worker_id})
        if state == "indexed" or (state == "needs_review" and metadata.get("indexed")):
            self.repository.promote(batch_id)
        return True

    def _maybe_finalize(self, batch_id):
        batch = self.repository.get_batch(batch_id)
        if not batch or batch.get("state") == "blocked":
            return
        progress = self._progress(batch_id)
        target = int(batch["target"])
        indexed = int(progress.get("indexed_count", 0))
        if indexed >= target:
            if int(progress.get("unfinished_count", 0)) == 0:
                self.repository.set_batch_state(batch_id, "complete", self.clock())
            return
        self.repository.promote(batch_id)
        progress = self._progress(batch_id)
        if int(progress.get("active_lease_count", 0)) or int(progress.get("unfinished_count", 0)):
            return
        if int(progress.get("pending_unreserved_count", 0)):
            self.repository.promote(batch_id)
            progress = self._progress(batch_id)
            if int(progress.get("unfinished_count", 0)):
                return
        self.repository.set_batch_state(batch_id, "incomplete", self.clock())

    def run_worker(self, batch_id, worker_id, max_steps=None):
        if not isinstance(worker_id, str) or not worker_id.strip() or ":" in worker_id:
            raise ValueError("worker_id must be a non-empty string without ':'")
        if max_steps is not None and (type(max_steps) is not int or max_steps < 0):
            raise ValueError("max_steps must be a nonnegative integer or None")
        if max_steps == 0:
            return self.summary(batch_id)
        batch = self.repository.get_batch(batch_id)
        if not batch:
            raise KeyError(batch_id)
        self._apply_batch_policy(batch)
        if batch.get("state") in {"blocked", "complete", "incomplete"}:
            return self.summary(batch_id)
        self.repository.promote(batch_id)
        steps = 0
        while max_steps is None or steps < max_steps:
            batch = self.repository.get_batch(batch_id)
            if not batch or batch.get("state") in {"blocked", "complete", "incomplete"}:
                break
            progress = self._progress(batch_id)
            indexed = int(progress.get("indexed_count", 0))
            if indexed >= int(batch["target"]):
                if int(progress.get("unfinished_count", 0)) == 0:
                    self.repository.set_batch_state(batch_id, "complete", self.clock())
                    break
            now = self.clock()
            owner = f"{worker_id}:{uuid.uuid4().hex}"
            item = self.repository.claim_next(
                batch_id, worker_id, owner, now, self.lease_seconds, self.stage_caps, self.max_workers,
            )
            if item is None:
                self._maybe_finalize(batch_id)
                break
            stage = item["next_stage"]
            item["_stage"] = stage
            item_metadata = _as_mapping(item.get("metadata"))
            if stage == "acquire":
                remaining, code = self._artifact_capacity(batch_id)
                if not remaining:
                    blocked = self.repository.block(
                        batch_id, item["material_id"], owner, self.clock(),
                        {"code": code or "artifact_budget_exhausted", "kind": "storage", "stage": stage},
                    )
                    if blocked is not False and not getattr(self.repository, "durable_stage_events", False):
                        self._event(item, "collection_blocked", {"batch_id": batch_id, "stage": stage, "code": code or "artifact_budget_exhausted", "worker_id": worker_id})
                    break
                item_metadata["artifact_budget_remaining_bytes"] = remaining
                item_metadata["artifact_budget_bytes"] = self.artifact_budget
                item_metadata["artifact_bytes_committed"] = int(item.get("artifact_bytes") or 0)
            item["metadata"] = item_metadata
            stop = threading.Event()
            lost = threading.Event()
            heartbeat = None
            resource_blocked = False
            if self.heartbeat_interval is not None:
                heartbeat = threading.Thread(
                    target=self._heartbeat_loop, args=(batch_id, item, owner, stop, lost), daemon=True,
                )
                heartbeat.start()
            try:
                handler_record = deepcopy(dict(item.get("record", {})))
                handler_record.pop("_collection_ordinal", None)
                result = self.handlers[stage](handler_record, deepcopy(item_metadata))
            except ResourceCollectionError as exc:
                error = {"code": exc.code, "kind": "storage", "stage": stage}
                blocked = self.repository.block(batch_id, item["material_id"], owner, self.clock(), error, exc.artifact_bytes)
                if blocked is not False and not getattr(self.repository, "durable_stage_events", False):
                    self._event(item, "collection_blocked", {"batch_id": batch_id, "stage": stage, "code": exc.code, "worker_id": worker_id})
                resource_blocked = True
            except RetryableCollectionError as exc:
                self._record_retry(batch_id, item, owner, stage, exc, worker_id)
            except PermanentCollectionError as exc:
                self._record_permanent(batch_id, item, owner, stage, exc, worker_id)
            except Exception:
                self._record_permanent(
                    batch_id, item, owner, stage,
                    PermanentCollectionError("handler_error", state="failed"), worker_id,
                )
            else:
                self._finish(batch_id, item, owner, stage, result, worker_id)
            finally:
                if heartbeat is not None:
                    stop.set()
                    heartbeat.join(timeout=max(1.0, self.heartbeat_interval * 2))
            steps += 1
            if lost.is_set():
                # Completion is still fenced by lease owner and expiry in the repository update.
                self._event(item, "collection_lease_lost", {"batch_id": batch_id, "stage": stage, "code": "lease_lost", "worker_id": worker_id})
            current = self.repository.get_batch(batch_id)
            if resource_blocked or (current and current.get("state") == "blocked"):
                break
        self._maybe_finalize(batch_id)
        return self.summary(batch_id)

    def resume_batch(self, batch_id, reason):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("A non-empty audit reason is required to resume a batch")
        reason = reason.strip()[:500]
        batch = self.repository.get_batch(batch_id)
        if not batch:
            raise KeyError(batch_id)
        self._apply_batch_policy(batch)
        resumed = self.repository.resume(
            batch_id, self.clock(), reason, self.provider_cooldown_seconds,
        )
        return resumed

    def summary(self, batch_id):
        batch = self.repository.get_batch(batch_id)
        if not batch:
            raise KeyError(batch_id)
        progress = self._progress(batch_id)
        target = int(batch["target"])
        candidate_count = int(progress.get("candidate_count", 0))
        indexed_count = int(progress.get("indexed_count", 0))
        reserved_count = int(progress.get("reserved_count", 0))
        complete_count = int(progress.get("complete_count", 0))
        reference_count = int(progress.get("reference_count", 0))
        completed_count = complete_count + reference_count
        acquire_completed = int(progress.get("acquire_completed_count", 0))
        assess_completed = int(progress.get("assess_completed_count", 0))
        index_completed = int(progress.get("index_completed_count", indexed_count))
        extract_completed = int(progress.get("extract_completed_count", complete_count))
        success_rate = None if not candidate_count else completed_count / candidate_count
        indexed_rate = indexed_count / target if target else None
        errors = {
            _safe_code(code, "unknown_error"): int(count)
            for code, count in _as_mapping(progress.get("error_counts")).items()
        }
        raw_last_error = progress.get("last_error")
        if raw_last_error:
            raw_last_error = _as_mapping(raw_last_error)
            last_error = {
                key: raw_last_error[key]
                for key in ("code", "kind", "stage")
                if isinstance(raw_last_error.get(key), str)
            }
        else:
            last_error = None
        counters = {
            "candidate_count": candidate_count,
            "indexed_count": indexed_count,
            "reserved_count": reserved_count,
            "remaining_target_slots": max(0, target - indexed_count),
            "complete_count": complete_count,
            "reference_only_count": reference_count,
            "completed_count": completed_count,
            "full_kg_complete_count": complete_count,
            "indexed_needs_review_count": int(progress.get("indexed_needs_review_count", 0)),
            "excluded_count": int(progress.get("excluded_count", 0)),
            "needs_review_count": int(progress.get("needs_review_count", 0)),
            "retry_wait_count": int(progress.get("retry_wait_count", 0)),
            "failed_count": int(progress.get("failed_count", 0)),
            "active_lease_count": int(progress.get("active_lease_count", 0)),
            "artifact_bytes_used": int(progress.get("artifact_bytes_used", 0)),
            "success_rate": success_rate,
            "indexed_rate": indexed_rate,
            "stage_progress": {
                "acquire": {"completed": acquire_completed, "denominator": candidate_count},
                "assess": {"completed": assess_completed, "denominator": acquire_completed},
                "index": {"completed": index_completed, "denominator": assess_completed},
                "extract": {"completed": extract_completed, "denominator": indexed_count},
            },
            "error_counts": dict(errors),
            "last_error": last_error,
        }
        cache = getattr(self.repository, "update_counters", None)
        if callable(cache):
            try:
                cache(batch_id, counters)
            except Exception:
                pass
        return {
            "batch_id": batch_id,
            "batch_state": batch.get("state"),
            "target": target,
            "target_met": indexed_count >= target,
            "policy": {
                **_as_mapping(batch.get("policy")),
                "artifact_budget_basis": "new source artifact bytes plus private prepared JSON bytes; preflight requires 8 MiB source plus 32 MiB prepared-cache headroom",
            },
            **counters,
        }
