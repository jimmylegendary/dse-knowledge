CREATE TABLE IF NOT EXISTS dse_knowledge.schema_versions(version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS dse_knowledge.materials (
 id text PRIMARY KEY, title text NOT NULL, url text NOT NULL, source text NOT NULL, category text NOT NULL,
 material_type text NOT NULL, summary text NOT NULL DEFAULT '', status text NOT NULL DEFAULT 'registered',
 scope text NOT NULL DEFAULT 'not_ingested', metadata jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS dse_knowledge.revisions (
 id text PRIMARY KEY, material_id text NOT NULL REFERENCES dse_knowledge.materials(id), sha256 text NOT NULL,
 url text NOT NULL, parser text NOT NULL, scope text NOT NULL, artifact_path text NOT NULL,
 content text NOT NULL, metadata jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(material_id,sha256));
CREATE TABLE IF NOT EXISTS dse_knowledge.chunks (
 id text PRIMARY KEY, revision_id text NOT NULL REFERENCES dse_knowledge.revisions(id), material_id text NOT NULL REFERENCES dse_knowledge.materials(id),
 start_offset integer NOT NULL, end_offset integer NOT NULL, text text NOT NULL, search_text text NOT NULL,
 embedding extensions.vector(768) NOT NULL, search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english',search_text)) STORED,
 CHECK(start_offset >= 0 AND end_offset > start_offset));
CREATE INDEX IF NOT EXISTS dse_chunks_fts ON dse_knowledge.chunks USING gin(search_vector);
CREATE INDEX IF NOT EXISTS dse_chunks_embedding ON dse_knowledge.chunks USING hnsw(embedding extensions.vector_cosine_ops);
CREATE TABLE IF NOT EXISTS dse_knowledge.claims (
 id text PRIMARY KEY, material_id text NOT NULL REFERENCES dse_knowledge.materials(id), revision_id text NOT NULL REFERENCES dse_knowledge.revisions(id),
 chunk_id text NOT NULL REFERENCES dse_knowledge.chunks(id), kind text NOT NULL, subject text NOT NULL, predicate text NOT NULL,
 object text NOT NULL, summary text NOT NULL, quote text NOT NULL, scope text NOT NULL, metadata jsonb NOT NULL DEFAULT '{}',
 created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS dse_knowledge.entities (
 id text PRIMARY KEY, label text NOT NULL, kind text NOT NULL DEFAULT 'concept', normalized text NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS dse_knowledge.edges (
 id text PRIMARY KEY, source text NOT NULL REFERENCES dse_knowledge.entities(id), target text NOT NULL REFERENCES dse_knowledge.entities(id),
 relation text NOT NULL, claim_id text NOT NULL REFERENCES dse_knowledge.claims(id), material_id text NOT NULL REFERENCES dse_knowledge.materials(id));
CREATE TABLE IF NOT EXISTS dse_knowledge.decisions (
 id text PRIMARY KEY, kind text NOT NULL, question text NOT NULL, input jsonb NOT NULL, result jsonb NOT NULL,
 evidence jsonb NOT NULL, snapshot jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS dse_knowledge.gaps (
 id text PRIMARY KEY, decision_id text NOT NULL REFERENCES dse_knowledge.decisions(id), reason text NOT NULL,
 next_action text NOT NULL, status text NOT NULL DEFAULT 'open', created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS dse_knowledge.jobs (
 id text PRIMARY KEY, kind text NOT NULL, payload jsonb NOT NULL, status text NOT NULL DEFAULT 'queued', result jsonb,
 error text, attempts integer NOT NULL DEFAULT 0, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS dse_knowledge.feedback (
 id text PRIMARY KEY, decision_id text NOT NULL REFERENCES dse_knowledge.decisions(id), verdict text NOT NULL, notes text NOT NULL,
 melete jsonb NOT NULL DEFAULT '{"status":"pending"}', created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS dse_knowledge.experiments (
 id text PRIMARY KEY, name text NOT NULL, cohort text NOT NULL, method text NOT NULL, metrics jsonb NOT NULL, context jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS dse_knowledge.ingest_events (
 id text PRIMARY KEY, material_id text NOT NULL, status text NOT NULL, detail jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS dse_knowledge.invocations (
 id text PRIMARY KEY, provider text NOT NULL, purpose text NOT NULL, metadata jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
INSERT INTO dse_knowledge.schema_versions(version) VALUES(1) ON CONFLICT DO NOTHING;
