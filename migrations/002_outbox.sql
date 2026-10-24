CREATE TABLE IF NOT EXISTS dse_knowledge.outbox (
 id text PRIMARY KEY, payload jsonb NOT NULL, status text NOT NULL DEFAULT 'pending', receipt jsonb,
 attempts integer NOT NULL DEFAULT 0, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
INSERT INTO dse_knowledge.schema_versions(version) VALUES(2) ON CONFLICT DO NOTHING;
