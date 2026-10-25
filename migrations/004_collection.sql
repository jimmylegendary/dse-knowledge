CREATE TABLE IF NOT EXISTS dse_knowledge.collection_batches (
 id text PRIMARY KEY,
 target integer NOT NULL CHECK(target > 0),
 policy jsonb NOT NULL DEFAULT '{}'::jsonb,
 state text NOT NULL DEFAULT 'running',
 counters jsonb NOT NULL DEFAULT '{}'::jsonb,
 provider_failures jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dse_knowledge.collection_items (
 batch_id text NOT NULL REFERENCES dse_knowledge.collection_batches(id) ON DELETE CASCADE,
 material_id text NOT NULL,
 record jsonb NOT NULL,
 state text NOT NULL,
 next_stage text,
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts >= 0),
 artifact_bytes bigint NOT NULL DEFAULT 0 CHECK(artifact_bytes >= 0),
 next_attempt_at timestamptz,
 lease_owner text,
 lease_until timestamptz,
 last_error jsonb,
 metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(batch_id,material_id),
 CHECK ((lease_owner IS NULL) = (lease_until IS NULL))
);

CREATE INDEX IF NOT EXISTS dse_collection_items_ready
 ON dse_knowledge.collection_items(batch_id,next_attempt_at,created_at,material_id)
 WHERE next_stage IS NOT NULL;

CREATE INDEX IF NOT EXISTS dse_collection_items_active_leases
 ON dse_knowledge.collection_items(lease_until,next_stage)
 WHERE lease_owner IS NOT NULL;

INSERT INTO dse_knowledge.schema_versions(version) VALUES(4) ON CONFLICT DO NOTHING;
