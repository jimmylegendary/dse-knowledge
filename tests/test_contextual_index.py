import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import stat
from types import SimpleNamespace

import pytest

from dse_knowledge.contextual_index import ContextualIndex, ContextualIndexBuilder, ContextualIndexError, corpus_hash
import dse_knowledge.contextual_index as contextual_index_module


def unit_vector(position):
    vector = [0.0] * 768
    vector[position] = 1.0
    return vector


def context(needle):
    return " ".join([needle] + [f"support{i}" for i in range(49)])


def document(material_id, revision_id, content, chunks, *, category="compiler_kernel", source_revision_sha256=None):
    return {
        "material_id": material_id,
        "revision_id": revision_id,
        "revision_sha256": source_revision_sha256 or hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "normalized_content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "category": category,
        "content": content,
        "chunks": chunks,
    }


def chunk(chunk_id, text, start=0):
    return {"id": chunk_id, "start_offset": start, "end_offset": start + len(text), "text": text}


def reference_corpus_hash(documents):
    pieces = []
    for doc in documents:
        for item in doc["chunks"]:
            pieces.append("\x1f".join([
                doc["material_id"], doc["revision_id"], doc["revision_sha256"],
                hashlib.md5(doc["content"].encode("utf-8")).hexdigest(), doc["category"],
                item["id"], str(item["start_offset"]), str(item["end_offset"]),
            ]))
    return hashlib.md5("\x1e".join(pieces).encode("utf-8")).hexdigest()


def reference_source_revision_manifest_hash(documents):
    rows = sorted(documents, key=lambda doc: doc["material_id"])
    pieces = ["\x1f".join([doc["material_id"], doc["revision_id"], doc["revision_sha256"]]) for doc in rows]
    return hashlib.sha256("\x1e".join(pieces).encode("utf-8")).hexdigest()


def reference_normalized_content_manifest_hash(documents):
    rows = sorted(documents, key=lambda doc: doc["material_id"])
    pieces = ["\x1f".join([
        doc["material_id"], doc["revision_id"], doc["revision_sha256"], doc["normalized_content_sha256"],
    ]) for doc in rows]
    return hashlib.sha256("\x1e".join(pieces).encode("utf-8")).hexdigest()


class FakeContextualizer:
    model = "context-test-model"
    prompt_version = "test-context-prompt/v1"

    def __init__(self):
        self.calls = []
        self.last_metadata = {"usage": {}}

    def generate(self, whole_document, chunks):
        ids = [item.get("id", item.get("chunk_id")) for item in chunks]
        self.calls.append((whole_document, ids))
        return [
            {"chunk_id": chunk_id, "context": context(
                "stitching signature" if chunk_id.endswith("a") else "warmup interval",
            )}
            for chunk_id in ids
        ]


class ShortContextualizer(FakeContextualizer):
    def generate(self, whole_document, chunks):
        ids = [item.get("id", item.get("chunk_id")) for item in chunks]
        self.calls.append((whole_document, ids))
        self.last_metadata = {"usage": {
            "prompt_tokens": 100, "completion_tokens": 12, "total_tokens": 112,
            "estimated_cost": 0.0001,
        }}
        return [{"chunk_id": chunk_id, "context": "This chunk describes API stubs."} for chunk_id in ids]


class FakeEmbedding:
    def __init__(self, *, fail_on_call=None):
        self.calls = []
        self.fail_on_call = fail_on_call

    def embed(self, texts, task="document"):
        self.calls.append((list(texts), task))
        if self.fail_on_call == len(self.calls):
            raise RuntimeError("injected embedding interruption")
        return [unit_vector(1 if "warmup interval" in text else 0) for text in texts]


def build_index(path, docs, contextualizer, embedding, *, expected_hash=None):
    expected_hash = expected_hash or reference_corpus_hash(docs)
    builder = ContextualIndexBuilder(
        path,
        expected_corpus_hash=expected_hash,
        expected_source_count=len(docs),
        expected_chunk_count=sum(len(doc["chunks"]) for doc in docs),
        expected_source_revision_manifest_sha256=reference_source_revision_manifest_hash(docs),
        expected_normalized_content_manifest_sha256=reference_normalized_content_manifest_hash(docs),
        embedding_fingerprint="deepinfra:google/embeddinggemma-2:768",
        context_model=contextualizer.model,
        prompt_version=contextualizer.prompt_version,
    )
    for doc in docs:
        builder.add_document(doc, contextualizer, embedding)
    return builder.activate()


def test_completed_generation_reopens_without_repeating_provider_calls(tmp_path):
    doc = document("material-a", "revision-a", "Alpha source passage.",
                   [chunk("chunk-a", "Alpha source passage.")])
    contextualizer, embedding = FakeContextualizer(), FakeEmbedding()
    first = build_index(tmp_path / "index", [doc], contextualizer, embedding)
    pointer = (tmp_path / "index/active.json").read_bytes()
    calls = (len(contextualizer.calls), len(embedding.calls))

    second = build_index(tmp_path / "index", [doc], contextualizer, embedding)

    assert second == first
    assert (len(contextualizer.calls), len(embedding.calls)) == calls
    assert (tmp_path / "index/active.json").read_bytes() == pointer


def test_raw_revision_and_normalized_content_hashes_are_distinct_and_rekey_generations(tmp_path):
    raw_artifact_sha256 = hashlib.sha256(b"raw HTML artifact that is normalized before indexing").hexdigest()
    first_doc = document(
        "material-a", "revision-same", "Alpha source passage.",
        [chunk("chunk-a", "Alpha source passage.")],
        source_revision_sha256=raw_artifact_sha256,
    )
    second_doc = document(
        "material-a", "revision-same", "Omega source passage.",
        [chunk("chunk-a", "Omega source passage.")],
        source_revision_sha256=raw_artifact_sha256,
    )
    first_contextualizer = FakeContextualizer()
    first = build_index(tmp_path / "index", [first_doc], first_contextualizer, FakeEmbedding())
    second_contextualizer = FakeContextualizer()
    second = build_index(tmp_path / "index", [second_doc], second_contextualizer, FakeEmbedding())

    assert first_doc["revision_sha256"] == raw_artifact_sha256
    assert first_doc["normalized_content_sha256"] == hashlib.sha256(b"Alpha source passage.").hexdigest()
    assert first["source_hashes"]["revision_manifest_sha256"] == reference_source_revision_manifest_hash([first_doc])
    assert first["source_hashes"]["normalized_content_manifest_sha256"] == reference_normalized_content_manifest_hash([first_doc])
    assert first["normalized_content_manifest_sha256"] != second["normalized_content_manifest_sha256"]
    assert first["generation_id"] != second["generation_id"]
    assert second_contextualizer.calls


def test_index_builds_real_fts5_bm25_and_dense_candidates_from_context_plus_original_chunk(tmp_path):
    first = "The simulator predicts memory traffic."
    second = "Warmup samples are excluded from timing."
    source = first + " " + second
    docs = [document("material-a", "revision-a", source, [
        chunk("chunk-a", first), chunk("chunk-b", second, len(first) + 1),
    ])]
    contextualizer = FakeContextualizer()
    embedding = FakeEmbedding()
    manifest = build_index(tmp_path / "index", docs, contextualizer, embedding)

    result = ContextualIndex(tmp_path / "index").search(
        "stitching signature", unit_vector(0), "compiler_kernel", 10,
        expected_corpus_hash=manifest["corpus_hash"],
        embedding_fingerprint="deepinfra:google/embeddinggemma-2:768",
        context_model=contextualizer.model,
        prompt_version=contextualizer.prompt_version,
    )

    assert result["bm25"][0]["chunk_id"] == "chunk-a"
    assert result["dense"][0]["chunk_id"] == "chunk-a"
    assert result["contexts"]["chunk-a"].startswith("stitching signature")
    assert embedding.calls[0][1] == "document"
    assert embedding.calls[0][0][0].startswith("stitching signature")
    assert embedding.calls[0][0][0].endswith("The simulator predicts memory traffic.")
    assert manifest["chunk_count"] == 2
    assert manifest["complete"] is True


def test_corpus_fingerprint_orders_chunk_offsets_numerically():
    chunks = [
        chunk("chunk-0", "zero", 0),
        chunk("chunk-32", "thirty two", 32),
        chunk("chunk-128", "one twenty eight", 128),
    ]
    source = "zero" + " " * 28 + "thirty two" + " " * 86 + "one twenty eight"
    docs = [document("material-a", "revision-a", source, chunks)]

    assert corpus_hash(docs) == reference_corpus_hash(docs)


def test_corpus_fingerprint_rejects_chunk_text_that_does_not_match_source_revision():
    docs = [document("material-a", "revision-a", "Source passage.", [chunk("chunk-a", "Source pAssage.")])]

    with pytest.raises(ContextualIndexError, match="contextual_chunk_source_mismatch"):
        corpus_hash(docs)


def test_short_context_is_kept_with_word_char_and_provider_usage_metadata(tmp_path):
    docs = [document("material-a", "revision-a", "API stub source.", [chunk("chunk-a", "API stub source.")])]
    contextualizer = ShortContextualizer()

    manifest = build_index(tmp_path / "index", docs, contextualizer, FakeEmbedding())

    assert manifest["context_lengths"] == {
        "count": 1, "word_count_total": 5, "word_count_min": 5, "word_count_max": 5,
        "char_count_total": len("This chunk describes API stubs."),
        "char_count_min": len("This chunk describes API stubs."),
        "char_count_max": len("This chunk describes API stubs."),
    }
    assert manifest["usage"]["prompt_tokens"] == 100
    assert manifest["usage"]["total_tokens"] == 112
    assert manifest["usage"]["estimated_cost"] == 0.0001


def test_manifest_reports_eligible_index_cohort_and_canonical_corpus_counts(tmp_path):
    docs = [document("material-a", "revision-a", "Eligible source.", [chunk("chunk-a", "Eligible source.")])]
    contextualizer = FakeContextualizer()
    builder = ContextualIndexBuilder(
        tmp_path / "index", expected_corpus_hash=reference_corpus_hash(docs),
        expected_source_count=1, expected_chunk_count=1,
        expected_source_revision_manifest_sha256=reference_source_revision_manifest_hash(docs),
        expected_normalized_content_manifest_sha256=reference_normalized_content_manifest_hash(docs),
        canonical_source_count=2, canonical_chunk_count=4,
        embedding_fingerprint="deepinfra:google/embeddinggemma-2:768",
        context_model=contextualizer.model, prompt_version=contextualizer.prompt_version,
    )
    builder.add_document(docs[0], contextualizer, FakeEmbedding())

    manifest = builder.activate()

    assert manifest["eligible_source_count"] == 1
    assert manifest["eligible_chunk_count"] == 1
    assert manifest["canonical_source_count"] == 2
    assert manifest["canonical_chunk_count"] == 4
    assert manifest["fts_sqlite_version"] == sqlite3.sqlite_version


def test_active_reader_rejects_index_created_by_another_sqlite_engine(tmp_path, monkeypatch):
    docs = [document("material-a", "revision-a", "Source passage.", [chunk("chunk-a", "Source passage.")])]
    contextualizer = FakeContextualizer()
    manifest = build_index(tmp_path / "index", docs, contextualizer, FakeEmbedding())
    assert manifest["fts_sqlite_version"] == sqlite3.sqlite_version
    monkeypatch.setattr(contextual_index_module.sqlite3, "sqlite_version", "different-engine-version")

    with pytest.raises(ContextualIndexError, match="contextual_index_fts_version_mismatch"):
        ContextualIndex(tmp_path / "index").search(
            "passage", unit_vector(0), "", 5,
            expected_corpus_hash=manifest["corpus_hash"],
            embedding_fingerprint="deepinfra:google/embeddinggemma-2:768",
            context_model=contextualizer.model,
            prompt_version=contextualizer.prompt_version,
        )


def test_engine_version_change_uses_new_generation_and_preserves_old_complete_file(tmp_path, monkeypatch):
    docs = [document("material-a", "revision-a", "Source passage.", [chunk("chunk-a", "Source passage.")])]
    contextualizer = FakeContextualizer()
    index_dir = tmp_path / "index"
    old_manifest = build_index(index_dir, docs, contextualizer, FakeEmbedding())
    old_final = index_dir / f"generation-{old_manifest['generation_id']}.sqlite3"
    monkeypatch.setattr(contextual_index_module.sqlite3, "sqlite_version", "different-engine-version")

    new_builder = ContextualIndexBuilder(
        index_dir, expected_corpus_hash=reference_corpus_hash(docs),
        expected_source_count=1, expected_chunk_count=1,
        expected_source_revision_manifest_sha256=reference_source_revision_manifest_hash(docs),
        expected_normalized_content_manifest_sha256=reference_normalized_content_manifest_hash(docs),
        embedding_fingerprint="deepinfra:google/embeddinggemma-2:768",
        context_model=contextualizer.model, prompt_version=contextualizer.prompt_version,
    )

    assert new_builder.generation_id != old_manifest["generation_id"]
    assert new_builder.final_path != old_final
    assert new_builder.staging_path.exists()
    assert old_final.exists()
    assert ContextualIndexBuilder._load_db_manifest(old_final)["fts_sqlite_version"] == old_manifest["fts_sqlite_version"]
    pointer = json.loads((index_dir / "active.json").read_text(encoding="utf-8"))
    assert pointer["generation_id"] == old_manifest["generation_id"]


def test_engine_version_change_does_not_reuse_partial_stage(tmp_path, monkeypatch):
    docs = [document("material-a", "revision-a", "Source passage.", [chunk("chunk-a", "Source passage.")])]
    contextualizer = FakeContextualizer()
    path = tmp_path / "index"
    old_builder = ContextualIndexBuilder(
        path, expected_corpus_hash=reference_corpus_hash(docs),
        expected_source_count=1, expected_chunk_count=1,
        expected_source_revision_manifest_sha256=reference_source_revision_manifest_hash(docs),
        expected_normalized_content_manifest_sha256=reference_normalized_content_manifest_hash(docs),
        embedding_fingerprint="deepinfra:google/embeddinggemma-2:768",
        context_model=contextualizer.model, prompt_version=contextualizer.prompt_version,
    )
    old_builder.add_document(docs[0], contextualizer, FakeEmbedding())
    old_stage = old_builder.staging_path
    old_digest = hashlib.sha256(old_stage.read_bytes()).hexdigest()
    original_sqlite_version = sqlite3.sqlite_version
    monkeypatch.setattr(contextual_index_module.sqlite3, "sqlite_version", "different-engine-version")

    new_builder = ContextualIndexBuilder(
        path, expected_corpus_hash=reference_corpus_hash(docs),
        expected_source_count=1, expected_chunk_count=1,
        expected_source_revision_manifest_sha256=reference_source_revision_manifest_hash(docs),
        expected_normalized_content_manifest_sha256=reference_normalized_content_manifest_hash(docs),
        embedding_fingerprint="deepinfra:google/embeddinggemma-2:768",
        context_model=contextualizer.model, prompt_version=contextualizer.prompt_version,
    )

    assert new_builder.generation_id != old_builder.generation_id
    assert new_builder.staging_path != old_stage
    assert old_stage.exists() and new_builder.staging_path.exists()
    assert hashlib.sha256(old_stage.read_bytes()).hexdigest() == old_digest

    def read_identity(stage_path):
        connection = sqlite3.connect(stage_path)
        try:
            return json.loads(connection.execute(
                "SELECT value FROM index_meta WHERE key='identity'",
            ).fetchone()[0])
        finally:
            connection.close()

    old_identity = read_identity(old_stage)
    new_identity = read_identity(new_builder.staging_path)
    assert old_identity["fts_sqlite_version"] == original_sqlite_version
    assert new_identity["fts_sqlite_version"] == "different-engine-version"


def test_legacy_partial_stage_gets_engine_version_only_when_strict_activation_completes(tmp_path):
    docs = [document("material-a", "revision-a", "Source passage.", [chunk("chunk-a", "Source passage.")])]
    contextualizer = FakeContextualizer()
    embedding = FakeEmbedding()
    path = tmp_path / "index"
    expected_hash = reference_corpus_hash(docs)
    builder = ContextualIndexBuilder(
        path, expected_corpus_hash=expected_hash, expected_source_count=1, expected_chunk_count=1,
        expected_source_revision_manifest_sha256=reference_source_revision_manifest_hash(docs),
        expected_normalized_content_manifest_sha256=reference_normalized_content_manifest_hash(docs),
        embedding_fingerprint="deepinfra:google/embeddinggemma-2:768",
        context_model=contextualizer.model, prompt_version=contextualizer.prompt_version,
    )
    builder.add_document(docs[0], contextualizer, embedding)

    connection = sqlite3.connect(builder.staging_path)
    stored_identity = connection.execute("SELECT value FROM index_meta WHERE key='identity'").fetchone()
    assert json.loads(stored_identity[0])["fts_sqlite_version"] == sqlite3.sqlite_version
    stored = connection.execute("SELECT value FROM index_meta WHERE key='manifest'").fetchone()
    staged_manifest = json.loads(stored[0])
    staged_manifest.pop("fts_sqlite_version", None)
    connection.execute("UPDATE index_meta SET value=? WHERE key='manifest'", (json.dumps(staged_manifest, sort_keys=True, separators=(",", ":")),))
    connection.commit()
    connection.close()

    resumed = ContextualIndexBuilder(
        path, expected_corpus_hash=expected_hash, expected_source_count=1, expected_chunk_count=1,
        expected_source_revision_manifest_sha256=reference_source_revision_manifest_hash(docs),
        expected_normalized_content_manifest_sha256=reference_normalized_content_manifest_hash(docs),
        embedding_fingerprint="deepinfra:google/embeddinggemma-2:768",
        context_model=contextualizer.model, prompt_version=contextualizer.prompt_version,
    )
    resumed.add_document(docs[0], contextualizer, embedding)
    manifest = resumed.activate()

    assert manifest["complete"] is True
    assert manifest["fts_sqlite_version"] == sqlite3.sqlite_version


def test_builder_rejects_unsafe_directory_without_changing_its_permissions(tmp_path):
    path = tmp_path / "public-index-dir"
    path.mkdir(mode=0o700)
    path.chmod(0o755)

    with pytest.raises(ContextualIndexError, match="contextual_index_directory_untrusted"):
        ContextualIndexBuilder(
            path, expected_corpus_hash="a" * 32, expected_source_count=1,
            expected_chunk_count=1, expected_source_revision_manifest_sha256="b" * 64,
            expected_normalized_content_manifest_sha256="c" * 64,
            embedding_fingerprint="e", context_model="c", prompt_version="p",
        )

    assert stat.S_IMODE(path.stat().st_mode) == 0o755


def test_builder_rejects_symlink_without_changing_target_permissions(tmp_path):
    target = tmp_path / "target-dir"
    target.mkdir(mode=0o700)
    target.chmod(0o755)
    link = tmp_path / "index-link"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(ContextualIndexError, match="contextual_index_directory_untrusted"):
        ContextualIndexBuilder(
            link, expected_corpus_hash="a" * 32, expected_source_count=1,
            expected_chunk_count=1, expected_source_revision_manifest_sha256="b" * 64,
            expected_normalized_content_manifest_sha256="c" * 64,
            embedding_fingerprint="e", context_model="c", prompt_version="p",
        )

    assert stat.S_IMODE(target.stat().st_mode) == 0o755


def test_read_only_index_connection_quotes_uri_special_characters_in_path(tmp_path):
    path = tmp_path / "index # with spaces"
    docs = [document("material-a", "revision-a", "Source passage.", [chunk("chunk-a", "Source passage.")])]
    contextualizer = FakeContextualizer()
    manifest = build_index(path, docs, contextualizer, FakeEmbedding())

    result = ContextualIndex(path).search(
        "passage", unit_vector(0), "", 5,
        expected_corpus_hash=manifest["corpus_hash"],
        embedding_fingerprint="deepinfra:google/embeddinggemma-2:768",
        context_model=contextualizer.model,
        prompt_version=contextualizer.prompt_version,
    )

    assert result["dense"][0]["chunk_id"] == "chunk-a"


def test_index_rejects_complex_embeddings_instead_of_silently_dropping_imaginary_parts(tmp_path):
    docs = [document("material-a", "revision-a", "Source passage.", [chunk("chunk-a", "Source passage.")])]

    class ComplexEmbedding(FakeEmbedding):
        def embed(self, texts, task="document"):
            self.calls.append((list(texts), task))
            return [[complex(1.0, 1.0)] + [0.0] * 767 for _ in texts]

    contextualizer = FakeContextualizer()
    builder = ContextualIndexBuilder(
        tmp_path / "index", expected_corpus_hash=reference_corpus_hash(docs),
        expected_source_count=1, expected_chunk_count=1,
        expected_source_revision_manifest_sha256=reference_source_revision_manifest_hash(docs),
        expected_normalized_content_manifest_sha256=reference_normalized_content_manifest_hash(docs),
        embedding_fingerprint="deepinfra:google/embeddinggemma-2:768",
        context_model=contextualizer.model, prompt_version=contextualizer.prompt_version,
    )

    with pytest.raises(ContextualIndexError, match="contextual_embedding_invalid"):
        builder.add_document(docs[0], contextualizer, ComplexEmbedding())


def test_admin_build_script_activates_only_when_canonical_corpus_stays_unchanged(tmp_path):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "build-contextual-index.py"
    spec = importlib.util.spec_from_file_location("build_contextual_index_script", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    docs = [document("material-a", "revision-a", "Source passage.", [chunk("chunk-a", "Source passage.")])]
    fingerprint = reference_corpus_hash(docs)
    refs = [{"material_id": "material-a", "revision_id": "revision-a",
             "revision_sha256": docs[0]["revision_sha256"], "category": docs[0]["category"]}]

    class FakeStore:
        def __init__(self, changed=False):
            self.manifest_calls = 0
            self.changed = changed

        def contextual_corpus_manifest(self):
            self.manifest_calls += 1
            current = fingerprint if self.manifest_calls == 1 or not self.changed else "0" * 32
            return {
                "corpus_hash": current, "source_count": 1, "chunk_count": 1,
                "canonical_source_count": 2, "canonical_chunk_count": 3,
            }

        def contextual_normalized_content_manifest(self):
            return reference_normalized_content_manifest_hash(docs)

        def contextual_document_refs(self):
            return refs

        def contextual_document(self, material_id, revision_id):
            return docs[0]

    settings = SimpleNamespace(
        data_root=tmp_path,
        get=lambda key, default="": {
            "DSE_CONTEXT_INDEX_PATH": str(tmp_path / "index"),
            "DSE_CONTEXT_CHAT_MODEL": "context-test-model",
            "DSE_EMBEDDING_PROVIDER": "deepinfra",
            "DSE_EMBEDDING_MODEL_ID": "google/embeddinggemma-2",
            "DSE_EMBEDDING_DIMENSIONS": "768",
        }.get(key, default),
    )

    complete = module.build_contextual_index(settings, FakeStore(), FakeContextualizer(), FakeEmbedding())
    assert complete["complete"] is True
    assert complete["eligible_source_count"] == 1
    assert complete["eligible_chunk_count"] == 1
    assert complete["canonical_source_count"] == 2
    assert complete["canonical_chunk_count"] == 3
    assert (tmp_path / "index" / "active.json").exists()

    changed_path = tmp_path / "changed-index"
    settings.get = lambda key, default="": str(changed_path) if key == "DSE_CONTEXT_INDEX_PATH" else {
        "DSE_CONTEXT_CHAT_MODEL": "context-test-model",
        "DSE_EMBEDDING_PROVIDER": "deepinfra",
        "DSE_EMBEDDING_MODEL_ID": "google/embeddinggemma-2",
        "DSE_EMBEDDING_DIMENSIONS": "768",
    }.get(key, default)
    with pytest.raises(ContextualIndexError, match="contextual_corpus_changed_during_build"):
        module.build_contextual_index(settings, FakeStore(changed=True), FakeContextualizer(), FakeEmbedding())
    assert not (changed_path / "active.json").exists()


def test_interrupted_generation_is_not_activated_and_retry_reuses_context_and_completed_vectors(tmp_path):
    chunks = []
    source_parts = []
    offset = 0
    for i in range(65):
        text = f"Source passage number {i}."
        chunks.append(chunk(f"chunk-{i:02}", text, offset))
        source_parts.append(text)
        offset += len(text) + (1 if i < 64 else 0)
    docs = [document("material-a", "revision-a", " ".join(source_parts), chunks)]
    contextualizer = FakeContextualizer()
    embedding = FakeEmbedding(fail_on_call=2)
    path = tmp_path / "index"

    builder = ContextualIndexBuilder(
        path,
        expected_corpus_hash=reference_corpus_hash(docs),
        expected_source_count=1,
        expected_chunk_count=65,
        expected_source_revision_manifest_sha256=reference_source_revision_manifest_hash(docs),
        expected_normalized_content_manifest_sha256=reference_normalized_content_manifest_hash(docs),
        embedding_fingerprint="deepinfra:google/embeddinggemma-2:768",
        context_model=contextualizer.model,
        prompt_version=contextualizer.prompt_version,
    )
    with pytest.raises(RuntimeError, match="injected embedding interruption"):
        builder.add_document(docs[0], contextualizer, embedding)
    assert not (path / "active.json").exists()
    assert [len(ids) for _, ids in contextualizer.calls] == [64, 1]

    resumed_manifest = build_index(path, docs, contextualizer, FakeEmbedding())

    assert resumed_manifest["complete"] is True
    assert resumed_manifest["chunk_count"] == 65
    assert len(contextualizer.calls) == 2
    result = ContextualIndex(path).search(
        "passage", unit_vector(0), "", 5,
        expected_corpus_hash=resumed_manifest["corpus_hash"],
        embedding_fingerprint="deepinfra:google/embeddinggemma-2:768",
        context_model=contextualizer.model,
        prompt_version=contextualizer.prompt_version,
    )
    assert result["dense"][0]["chunk_id"] == "chunk-00"


def test_failed_replacement_build_keeps_previous_active_generation_searchable(tmp_path):
    path = tmp_path / "index"
    first_doc = document("material-a", "revision-a", "Old original passage.", [chunk("chunk-a", "Old original passage.")])
    first_contextualizer = FakeContextualizer()
    first_manifest = build_index(path, [first_doc], first_contextualizer, FakeEmbedding())
    replacement = document("material-a", "revision-b", "New original passage.", [chunk("chunk-b", "New original passage.")])
    bad_builder = ContextualIndexBuilder(
        path,
        expected_corpus_hash=reference_corpus_hash([replacement]),
        expected_source_count=1,
        expected_chunk_count=1,
        expected_source_revision_manifest_sha256=reference_source_revision_manifest_hash([replacement]),
        expected_normalized_content_manifest_sha256=reference_normalized_content_manifest_hash([replacement]),
        embedding_fingerprint="deepinfra:google/embeddinggemma-2:768",
        context_model=first_contextualizer.model,
        prompt_version=first_contextualizer.prompt_version,
    )

    with pytest.raises(RuntimeError, match="injected embedding interruption"):
        bad_builder.add_document(replacement, first_contextualizer, FakeEmbedding(fail_on_call=1))

    current = ContextualIndex(path).search(
        "old passage", unit_vector(0), "", 5,
        expected_corpus_hash=first_manifest["corpus_hash"],
        embedding_fingerprint="deepinfra:google/embeddinggemma-2:768",
        context_model=first_contextualizer.model,
        prompt_version=first_contextualizer.prompt_version,
    )
    assert [row["chunk_id"] for row in current["bm25"]] == ["chunk-a"]


def test_index_fails_closed_on_stale_corpus_profile_or_invalid_query_vector(tmp_path):
    docs = [document("material-a", "revision-a", "Source passage.", [chunk("chunk-a", "Source passage.")])]
    contextualizer = FakeContextualizer()
    manifest = build_index(tmp_path / "index", docs, contextualizer, FakeEmbedding())
    index = ContextualIndex(tmp_path / "index")
    common = {
        "embedding_fingerprint": "deepinfra:google/embeddinggemma-2:768",
        "context_model": contextualizer.model,
        "prompt_version": contextualizer.prompt_version,
    }

    with pytest.raises(ContextualIndexError, match="contextual_index_stale"):
        index.search("passage", unit_vector(0), "", 5, expected_corpus_hash="changed", **common)
    with pytest.raises(ContextualIndexError, match="contextual_index_profile_mismatch"):
        index.search("passage", unit_vector(0), "", 5,
                     expected_corpus_hash=manifest["corpus_hash"],
                     embedding_fingerprint="other-model:768", context_model=contextualizer.model,
                     prompt_version=contextualizer.prompt_version)
    with pytest.raises(ContextualIndexError, match="contextual_query_vector_invalid"):
        index.search("passage", [0.0] * 768, "", 5,
                     expected_corpus_hash=manifest["corpus_hash"], **common)
