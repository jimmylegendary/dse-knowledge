-- Additive projections: original claims and revision content stay immutable.
ALTER TABLE dse_knowledge.materials ADD COLUMN IF NOT EXISTS role text NOT NULL DEFAULT 'unclassified';
ALTER TABLE dse_knowledge.materials ADD COLUMN IF NOT EXISTS role_metadata jsonb NOT NULL DEFAULT '{}';
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='dse_material_role' AND conrelid='dse_knowledge.materials'::regclass) THEN
  ALTER TABLE dse_knowledge.materials ADD CONSTRAINT dse_material_role CHECK(role IN ('core_technical','supporting_method','integration_operations','source_navigation','out_of_scope','unclassified'));
 END IF;
END $$;
CREATE TABLE IF NOT EXISTS dse_knowledge.claim_annotations (
 id text PRIMARY KEY, claim_id text NOT NULL REFERENCES dse_knowledge.claims(id),
 revision_id text NOT NULL REFERENCES dse_knowledge.revisions(id), version text NOT NULL,
 context jsonb NOT NULL, metadata jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS dse_annotations_claim ON dse_knowledge.claim_annotations(claim_id,created_at DESC,id);
CREATE UNIQUE INDEX IF NOT EXISTS dse_revision_identity ON dse_knowledge.revisions(id,material_id);
CREATE UNIQUE INDEX IF NOT EXISTS dse_chunk_identity ON dse_knowledge.chunks(id,revision_id,material_id);
CREATE UNIQUE INDEX IF NOT EXISTS dse_claim_revision_identity ON dse_knowledge.claims(id,revision_id);
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='dse_chunk_revision_material' AND conrelid='dse_knowledge.chunks'::regclass) THEN
  ALTER TABLE dse_knowledge.chunks ADD CONSTRAINT dse_chunk_revision_material FOREIGN KEY(revision_id,material_id) REFERENCES dse_knowledge.revisions(id,material_id);
 END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='dse_claim_chunk_material' AND conrelid='dse_knowledge.claims'::regclass) THEN
  ALTER TABLE dse_knowledge.claims ADD CONSTRAINT dse_claim_chunk_material FOREIGN KEY(chunk_id,revision_id,material_id) REFERENCES dse_knowledge.chunks(id,revision_id,material_id);
 END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='dse_annotation_claim_revision' AND conrelid='dse_knowledge.claim_annotations'::regclass) THEN
  ALTER TABLE dse_knowledge.claim_annotations ADD CONSTRAINT dse_annotation_claim_revision FOREIGN KEY(claim_id,revision_id) REFERENCES dse_knowledge.claims(id,revision_id);
 END IF;
END $$;
ALTER TABLE dse_knowledge.entities ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}';
ALTER TABLE dse_knowledge.edges ADD COLUMN IF NOT EXISTS relation_kind text NOT NULL DEFAULT 'assertion';
ALTER TABLE dse_knowledge.edges ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}';
ALTER TABLE dse_knowledge.edges ADD COLUMN IF NOT EXISTS evidence_chunk_id text REFERENCES dse_knowledge.chunks(id);
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='dse_edge_evidence' AND conrelid='dse_knowledge.edges'::regclass) THEN
  ALTER TABLE dse_knowledge.edges ADD CONSTRAINT dse_edge_evidence CHECK(relation_kind IN ('assertion','topic') AND (relation_kind<>'topic' OR evidence_chunk_id IS NOT NULL));
 END IF;
END $$;
CREATE INDEX IF NOT EXISTS dse_edges_evidence ON dse_knowledge.edges(evidence_chunk_id);
CREATE INDEX IF NOT EXISTS dse_edges_topics ON dse_knowledge.edges(source,target) WHERE relation_kind='topic';
INSERT INTO dse_knowledge.schema_versions(version) VALUES(3) ON CONFLICT DO NOTHING;
