"""Private, resumable SQLite projection for contextual hybrid retrieval."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Iterable

import numpy as np


INDEX_SCHEMA_VERSION = 2
EMBEDDING_DIMENSIONS = 768
MAX_INDEX_CHUNKS = 50_000
MAX_EMBED_TEXT_CHARS = 16_384
BUILD_BATCH_SIZE = 64
_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class ContextualIndexError(RuntimeError):
    """A safe, typed failure for missing, stale, or incomplete projections."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_text(value: str, algorithm="md5") -> str:
    return hashlib.new(algorithm, value.encode("utf-8")).hexdigest()


def _private_directory(path: Path, *, create: bool) -> Path:
    path = path.expanduser()
    try:
        info = path.lstat()
    except FileNotFoundError:
        if not create:
            raise ContextualIndexError("contextual_index_missing") from None
        try:
            path.mkdir(mode=0o700, parents=True, exist_ok=False)
            info = path.lstat()
        except FileExistsError:
            try:
                info = path.lstat()
            except OSError:
                raise ContextualIndexError("contextual_index_directory_unavailable") from None
        except OSError:
            raise ContextualIndexError("contextual_index_directory_unavailable") from None
    except OSError:
        raise ContextualIndexError("contextual_index_directory_unavailable") from None
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise ContextualIndexError("contextual_index_directory_untrusted")
    return path


def _check_private_file(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError:
        raise ContextualIndexError("contextual_index_file_missing") from None
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise ContextualIndexError("contextual_index_file_untrusted")


def _connect(path: Path, *, readonly=False) -> sqlite3.Connection:
    _check_private_file(path)
    try:
        if readonly:
            uri = "file:" + urllib.parse.quote(path.as_posix(), safe="/") + "?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=5, isolation_level=None)
        else:
            connection = sqlite3.connect(path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        return connection
    except sqlite3.Error:
        raise ContextualIndexError("contextual_index_open_failed") from None


def _write_private_file(path: Path, content: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    fd = None
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb", closefd=True) as stream:
            fd = None
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        if fd is not None:
            os.close(fd)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ContextualIndexError("contextual_index_manifest_write_failed") from None


def _validate_document(document: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ContextualIndexError("contextual_document_invalid")
    fields = ("material_id", "revision_id", "revision_sha256", "category", "content", "chunks")
    if any(key not in document for key in fields):
        raise ContextualIndexError("contextual_document_invalid")
    for key in fields[:4]:
        if not isinstance(document[key], str) or not document[key]:
            raise ContextualIndexError("contextual_document_invalid")
    content = document["content"]
    if not isinstance(content, str) or not content.strip() or len(content) > 1_000_000:
        raise ContextualIndexError("contextual_document_invalid")
    revision_sha256 = document["revision_sha256"]
    if not re.fullmatch(r"[0-9a-f]{64}", revision_sha256):
        raise ContextualIndexError("contextual_revision_hash_invalid")
    normalized_content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    supplied_normalized_sha256 = document.get("normalized_content_sha256")
    if supplied_normalized_sha256 not in (None, normalized_content_sha256):
        raise ContextualIndexError("contextual_normalized_content_hash_mismatch")
    chunks = document["chunks"]
    if not isinstance(chunks, list) or not chunks:
        raise ContextualIndexError("contextual_document_chunks_invalid")
    seen = set()
    normalized = []
    previous_start = -1
    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise ContextualIndexError("contextual_chunk_invalid")
        chunk_id = chunk.get("chunk_id", chunk.get("id"))
        start, end, text = chunk.get("start_offset"), chunk.get("end_offset"), chunk.get("text")
        if (not isinstance(chunk_id, str) or not chunk_id or len(chunk_id) > 256 or chunk_id in seen
                or type(start) is not int or type(end) is not int or start < 0 or end <= start
                or start < previous_start or not isinstance(text, str) or not text.strip()
                or len(text) != end - start):
            raise ContextualIndexError("contextual_chunk_invalid")
        if content[start:end] != text:
            raise ContextualIndexError("contextual_chunk_source_mismatch")
        seen.add(chunk_id)
        previous_start = start
        normalized.append({"id": chunk_id, "start_offset": start, "end_offset": end, "text": text})
    return {
        "material_id": document["material_id"], "revision_id": document["revision_id"],
        "revision_sha256": revision_sha256,
        "normalized_content_sha256": normalized_content_sha256,
        "normalized_content_md5": _hash_text(content),
        "category": document["category"],
        "content": content, "chunks": normalized,
    }


def _corpus_piece(document: dict[str, Any], chunk: dict[str, Any]) -> str:
    return "\x1f".join([
        document["material_id"], document["revision_id"], document["revision_sha256"],
        document["normalized_content_md5"], document["category"], chunk["id"], str(chunk["start_offset"]),
        str(chunk["end_offset"]),
    ])


def corpus_hash(documents: Iterable[dict[str, Any]]) -> str:
    """Return the same ordered MD5 fingerprint used by Store's PG freshness query."""
    normalized = [_validate_document(document) for document in documents]
    normalized.sort(key=lambda item: item["material_id"])
    pieces = []
    for document in normalized:
        chunks = sorted(document["chunks"], key=lambda item: (item["start_offset"], item["id"]))
        pieces.extend(_corpus_piece(document, chunk) for chunk in chunks)
    return _hash_text("\x1e".join(pieces))


def source_revision_manifest_hash(sources: Iterable[dict[str, Any]]) -> str:
    rows = [dict(row) if not isinstance(row, dict) and hasattr(row, "keys") else row for row in sources]
    if any(not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key]
           for key in ("material_id", "revision_id", "revision_sha256")) for row in rows):
        raise ContextualIndexError("contextual_source_manifest_invalid")
    if any(not re.fullmatch(r"[0-9a-f]{64}", row["revision_sha256"]) for row in rows):
        raise ContextualIndexError("contextual_source_manifest_invalid")
    rows.sort(key=lambda row: row["material_id"])
    pieces = ["\x1f".join((row["material_id"], row["revision_id"], row["revision_sha256"])) for row in rows]
    return hashlib.sha256("\x1e".join(pieces).encode("utf-8")).hexdigest()


def normalized_content_manifest_hash(sources: Iterable[dict[str, Any]]) -> str:
    rows = []
    for source in sources:
        if not isinstance(source, dict) and hasattr(source, "keys"):
            source = dict(source)
        if not isinstance(source, dict):
            raise ContextualIndexError("contextual_normalized_manifest_invalid")
        if "content" in source and "chunks" in source:
            row = _validate_document(source)
        else:
            row = dict(source)
            if any(not isinstance(row.get(key), str) or not row[key] for key in
                   ("material_id", "revision_id", "revision_sha256", "normalized_content_sha256")):
                raise ContextualIndexError("contextual_normalized_manifest_invalid")
            if (not re.fullmatch(r"[0-9a-f]{64}", row["revision_sha256"])
                    or not re.fullmatch(r"[0-9a-f]{64}", row["normalized_content_sha256"])):
                raise ContextualIndexError("contextual_normalized_manifest_invalid")
        rows.append(row)
    rows.sort(key=lambda row: row["material_id"])
    pieces = ["\x1f".join((row["material_id"], row["revision_id"], row["revision_sha256"],
                           row["normalized_content_sha256"])) for row in rows]
    return hashlib.sha256("\x1e".join(pieces).encode("utf-8")).hexdigest()


def _profile_generation_id(corpus: str, source_count: int, chunk_count: int,
                           source_revision_manifest_sha256: str,
                           normalized_content_manifest_sha256: str,
                           fts_sqlite_version: str, embedding_fingerprint: str,
                           context_model: str, prompt_version: str) -> str:
    key = _json([INDEX_SCHEMA_VERSION, corpus, source_count, chunk_count,
                 source_revision_manifest_sha256, normalized_content_manifest_sha256,
                 fts_sqlite_version, embedding_fingerprint, context_model, prompt_version])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def _cache_key(document: dict[str, Any], chunk: dict[str, Any], model: str, prompt_version: str) -> tuple[str, str]:
    chunk_hash = _hash_text(chunk["text"])
    identity = _json([
        document["material_id"], document["revision_id"], document["revision_sha256"],
        document["normalized_content_sha256"], chunk["id"], chunk_hash, model, prompt_version,
    ])
    return hashlib.sha256(identity.encode("utf-8")).hexdigest(), chunk_hash


def _normalized_vector(vector: Any) -> np.ndarray:
    if isinstance(vector, (str, bytes)):
        raise ContextualIndexError("contextual_embedding_invalid")
    try:
        raw = list(vector)
    except (TypeError, ValueError):
        raise ContextualIndexError("contextual_embedding_invalid") from None
    if (len(raw) != EMBEDDING_DIMENSIONS
            or any(isinstance(value, bool) or not isinstance(value, (int, float, np.number)) for value in raw)):
        raise ContextualIndexError("contextual_embedding_invalid")
    try:
        values = np.asarray(raw, dtype=np.float32)
    except (TypeError, ValueError, OverflowError):
        raise ContextualIndexError("contextual_embedding_invalid") from None
    if not np.isfinite(values).all():
        raise ContextualIndexError("contextual_embedding_invalid")
    norm = float(np.sqrt(np.einsum("i,i->", values, values, optimize=False)))
    if not math.isfinite(norm) or norm <= 0:
        raise ContextualIndexError("contextual_embedding_invalid")
    return np.asarray(values / norm, dtype="<f4")


class ContextualIndexBuilder:
    """Checkpointed generation builder; active.json changes only after full validation."""

    def __init__(self, directory: str | Path, *, expected_corpus_hash: str,
                 expected_source_count: int, expected_chunk_count: int,
                 expected_source_revision_manifest_sha256: str,
                 expected_normalized_content_manifest_sha256: str,
                 embedding_fingerprint: str, context_model: str, prompt_version: str,
                 canonical_source_count: int | None = None,
                 canonical_chunk_count: int | None = None):
        canonical_source_count = expected_source_count if canonical_source_count is None else canonical_source_count
        canonical_chunk_count = expected_chunk_count if canonical_chunk_count is None else canonical_chunk_count
        if (not isinstance(expected_corpus_hash, str) or not re.fullmatch(r"[0-9a-f]{32}", expected_corpus_hash)
                or type(expected_source_count) is not int or expected_source_count <= 0
                or type(expected_chunk_count) is not int or expected_chunk_count <= 0
                or type(canonical_source_count) is not int or canonical_source_count < expected_source_count
                or type(canonical_chunk_count) is not int or canonical_chunk_count < expected_chunk_count
                or not isinstance(expected_source_revision_manifest_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected_source_revision_manifest_sha256)
                or not isinstance(expected_normalized_content_manifest_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected_normalized_content_manifest_sha256)
                or any(not isinstance(item, str) or not item for item in
                       (embedding_fingerprint, context_model, prompt_version))):
            raise ContextualIndexError("contextual_build_manifest_invalid")
        if expected_chunk_count > MAX_INDEX_CHUNKS:
            raise ContextualIndexError("retrieval_capacity_exceeded")
        self.directory = _private_directory(Path(directory), create=True)
        self.expected_corpus_hash = expected_corpus_hash
        self.expected_source_count = expected_source_count
        self.expected_chunk_count = expected_chunk_count
        self.canonical_source_count = canonical_source_count
        self.canonical_chunk_count = canonical_chunk_count
        self.expected_source_revision_manifest_sha256 = expected_source_revision_manifest_sha256
        self.expected_normalized_content_manifest_sha256 = expected_normalized_content_manifest_sha256
        self.embedding_fingerprint = embedding_fingerprint
        self.context_model = context_model
        self.prompt_version = prompt_version
        self.generation_id = _profile_generation_id(
            expected_corpus_hash, expected_source_count, expected_chunk_count,
            expected_source_revision_manifest_sha256, expected_normalized_content_manifest_sha256,
            sqlite3.sqlite_version, embedding_fingerprint, context_model, prompt_version,
        )
        self.staging_path = self.directory / f"staging-{self.generation_id}.sqlite3"
        self.final_path = self.directory / f"generation-{self.generation_id}.sqlite3"
        self._already_complete = self.final_path.exists()
        self._manifest = self._base_manifest()
        if self._already_complete:
            stored = self._load_db_manifest(self.final_path)
            expected = self._manifest | {"complete": True, "usage": stored.get("usage", {})}
            if not stored.get("complete") or any(stored.get(key) != value for key, value in expected.items()):
                raise ContextualIndexError("contextual_index_generation_invalid")
            self._manifest = stored
        else:
            self._prepare_staging()

    def _base_manifest(self) -> dict[str, Any]:
        return {
            "schema_version": INDEX_SCHEMA_VERSION, "generation_id": self.generation_id,
            "corpus_hash": self.expected_corpus_hash,
            "source_count": self.expected_source_count, "chunk_count": self.expected_chunk_count,
            "eligible_source_count": self.expected_source_count,
            "eligible_chunk_count": self.expected_chunk_count,
            "source_revision_manifest_sha256": self.expected_source_revision_manifest_sha256,
            "normalized_content_manifest_sha256": self.expected_normalized_content_manifest_sha256,
            "embedding_fingerprint": self.embedding_fingerprint,
            "embedding_dimensions": EMBEDDING_DIMENSIONS,
            "fts_sqlite_version": sqlite3.sqlite_version,
            "context_model": self.context_model, "prompt_version": self.prompt_version,
            "complete": False, "usage": {},
        }

    @staticmethod
    def _load_db_manifest(path: Path) -> dict[str, Any]:
        connection = _connect(path, readonly=True)
        try:
            row = connection.execute("SELECT value FROM index_meta WHERE key='manifest'").fetchone()
            if row is None:
                raise ContextualIndexError("contextual_index_manifest_missing")
            manifest = json.loads(row["value"])
            if not isinstance(manifest, dict):
                raise ValueError
            return manifest
        except (sqlite3.Error, json.JSONDecodeError, ValueError):
            raise ContextualIndexError("contextual_index_manifest_invalid") from None
        finally:
            connection.close()

    def _prepare_staging(self) -> None:
        if not self.staging_path.exists():
            try:
                fd = os.open(self.staging_path, os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
                os.close(fd)
            except OSError:
                raise ContextualIndexError("contextual_index_staging_create_failed") from None
        _check_private_file(self.staging_path)
        try:
            connection = sqlite3.connect(self.staging_path, timeout=30, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=30000")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS index_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sources(
                    material_id TEXT PRIMARY KEY, revision_id TEXT NOT NULL, revision_sha256 TEXT NOT NULL,
                    normalized_content_sha256 TEXT NOT NULL, normalized_content_md5 TEXT NOT NULL,
                    category TEXT NOT NULL, chunk_count INTEGER NOT NULL,
                    complete INTEGER NOT NULL DEFAULT 0 CHECK(complete IN (0,1))
                );
                CREATE TABLE IF NOT EXISTS context_cache(
                    cache_key TEXT PRIMARY KEY, material_id TEXT NOT NULL, revision_id TEXT NOT NULL,
                    chunk_id TEXT NOT NULL, revision_sha256 TEXT NOT NULL,
                    normalized_content_sha256 TEXT NOT NULL, chunk_md5 TEXT NOT NULL,
                    context_model TEXT NOT NULL, prompt_version TEXT NOT NULL, context_text TEXT NOT NULL,
                    word_count INTEGER NOT NULL, char_count INTEGER NOT NULL, usage_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS passages(
                    chunk_id TEXT PRIMARY KEY, material_id TEXT NOT NULL, revision_id TEXT NOT NULL,
                    start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL, category TEXT NOT NULL,
                    chunk_md5 TEXT NOT NULL, cache_key TEXT NOT NULL REFERENCES context_cache(cache_key),
                    embedding BLOB NOT NULL CHECK(length(embedding)=3072)
                );
                CREATE INDEX IF NOT EXISTS passages_category ON passages(category, chunk_id);
                CREATE INDEX IF NOT EXISTS passages_material_revision ON passages(material_id, revision_id);
                CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(chunk_id UNINDEXED, content, tokenize='unicode61');
            """)
            stored = connection.execute("SELECT value FROM index_meta WHERE key='identity'").fetchone()
            identity = {key: self._manifest[key] for key in (
                "schema_version", "generation_id", "corpus_hash", "source_count", "chunk_count",
                "source_revision_manifest_sha256", "normalized_content_manifest_sha256",
                "embedding_fingerprint", "embedding_dimensions", "fts_sqlite_version",
                "context_model", "prompt_version",
            )}
            if stored is None:
                connection.execute("INSERT INTO index_meta(key,value) VALUES('identity',?)", (_json(identity),))
                connection.execute("INSERT INTO index_meta(key,value) VALUES('manifest',?)", (_json(self._manifest),))
            elif json.loads(stored["value"]) != identity:
                raise ContextualIndexError("contextual_index_staging_identity_mismatch")
        except ContextualIndexError:
            raise
        except (sqlite3.Error, OSError, json.JSONDecodeError):
            raise ContextualIndexError("contextual_index_staging_invalid") from None
        finally:
            try:
                connection.close()
            except (UnboundLocalError, sqlite3.Error):
                pass
        try:
            self.staging_path.chmod(0o600)
        except OSError:
            raise ContextualIndexError("contextual_index_file_untrusted") from None

    def _write_manifest(self, connection: sqlite3.Connection) -> None:
        row = connection.execute("SELECT value FROM index_meta WHERE key='manifest'").fetchone()
        manifest = json.loads(row["value"]) if row else self._manifest.copy()
        manifest["usage"] = manifest.get("usage", {})
        connection.execute("INSERT OR REPLACE INTO index_meta(key,value) VALUES('manifest',?)", (_json(manifest),))
        self._manifest = manifest

    def add_document(self, document: dict[str, Any], contextualizer, embedding) -> None:
        if self._already_complete:
            return
        doc = _validate_document(document)
        model = getattr(contextualizer, "model", self.context_model)
        prompt_version = getattr(contextualizer, "prompt_version", self.prompt_version)
        if model != self.context_model or prompt_version != self.prompt_version:
            raise ContextualIndexError("contextual_build_profile_mismatch")
        connection = _connect(self.staging_path)
        try:
            existing = connection.execute(
                "SELECT revision_id,revision_sha256,normalized_content_sha256,normalized_content_md5,category,chunk_count,complete FROM sources WHERE material_id=?",
                (doc["material_id"],),
            ).fetchone()
            normalized_content_md5 = _hash_text(doc["content"])
            if existing is not None:
                same = (existing["revision_id"] == doc["revision_id"]
                        and existing["revision_sha256"] == doc["revision_sha256"]
                        and existing["normalized_content_sha256"] == doc["normalized_content_sha256"]
                        and existing["normalized_content_md5"] == normalized_content_md5
                        and existing["category"] == doc["category"]
                        and existing["chunk_count"] == len(doc["chunks"]))
                if not same:
                    raise ContextualIndexError("contextual_staging_source_mismatch")
                if existing["complete"]:
                    self._verify_document_passages(connection, doc)
                    return
            else:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO sources(material_id,revision_id,revision_sha256,normalized_content_sha256,normalized_content_md5,category,chunk_count,complete) VALUES(?,?,?,?,?,?,?,0)",
                    (doc["material_id"], doc["revision_id"], doc["revision_sha256"],
                     doc["normalized_content_sha256"], normalized_content_md5,
                     doc["category"], len(doc["chunks"])),
                )
                connection.commit()
            for offset in range(0, len(doc["chunks"]), BUILD_BATCH_SIZE):
                batch = doc["chunks"][offset:offset + BUILD_BATCH_SIZE]
                self._add_batch(connection, doc, batch, contextualizer, embedding)
            self._verify_document_passages(connection, doc)
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("UPDATE sources SET complete=1 WHERE material_id=?", (doc["material_id"],))
            self._write_manifest(connection)
            connection.commit()
        except Exception:
            try:
                connection.rollback()
            except sqlite3.Error:
                pass
            raise
        finally:
            connection.close()
        try:
            self.staging_path.chmod(0o600)
        except OSError:
            raise ContextualIndexError("contextual_index_file_untrusted") from None

    def _verify_document_passages(self, connection: sqlite3.Connection, doc: dict[str, Any]) -> None:
        rows = connection.execute(
            "SELECT chunk_id,revision_id,start_offset,end_offset,category,chunk_md5 FROM passages WHERE material_id=?",
            (doc["material_id"],),
        ).fetchall()
        indexed = {row["chunk_id"]: row for row in rows}
        if len(indexed) != len(doc["chunks"]):
            raise ContextualIndexError("contextual_staging_document_incomplete")
        for chunk in doc["chunks"]:
            row = indexed.get(chunk["id"])
            if (row is None or row["revision_id"] != doc["revision_id"]
                    or row["start_offset"] != chunk["start_offset"] or row["end_offset"] != chunk["end_offset"]
                    or row["category"] != doc["category"] or row["chunk_md5"] != _hash_text(chunk["text"])):
                raise ContextualIndexError("contextual_staging_binding_mismatch")

    def _add_batch(self, connection, doc, chunks, contextualizer, embedding) -> None:
        entries = []
        for chunk in chunks:
            key, chunk_hash = _cache_key(doc, chunk, self.context_model, self.prompt_version)
            existing = connection.execute(
                "SELECT cache_key FROM passages WHERE chunk_id=?", (chunk["id"],),
            ).fetchone()
            if existing is not None:
                if existing["cache_key"] != key:
                    raise ContextualIndexError("contextual_staging_binding_mismatch")
                continue
            cached = connection.execute(
                "SELECT context_text,material_id,revision_id,chunk_id,revision_sha256,normalized_content_sha256,chunk_md5,word_count,char_count FROM context_cache WHERE cache_key=?",
                (key,),
            ).fetchone()
            if cached is not None and (cached["material_id"] != doc["material_id"]
                    or cached["revision_id"] != doc["revision_id"] or cached["chunk_id"] != chunk["id"]
                    or cached["revision_sha256"] != doc["revision_sha256"]
                    or cached["normalized_content_sha256"] != doc["normalized_content_sha256"]
                    or cached["chunk_md5"] != chunk_hash):
                raise ContextualIndexError("contextual_cache_binding_mismatch")
            if cached is not None:
                count = len(cached["context_text"].split())
                if (count != cached["word_count"] or len(cached["context_text"]) != cached["char_count"]
                        or not 5 <= count <= 120 or cached["char_count"] > 800):
                    raise ContextualIndexError("contextual_cache_content_invalid")
            entries.append({"chunk": chunk, "cache_key": key, "chunk_hash": chunk_hash,
                            "context": cached["context_text"] if cached is not None else None})
        missing = [entry for entry in entries if entry["context"] is None]
        if missing:
            request_chunks = [entry["chunk"] for entry in missing]
            generated = contextualizer.generate(doc["content"], request_chunks)
            if not isinstance(generated, list) or len(generated) != len(missing):
                raise ContextualIndexError("contextual_response_coverage_invalid")
            contexts = {}
            for item in generated:
                if (not isinstance(item, dict) or set(item) != {"chunk_id", "context"}
                        or not isinstance(item["chunk_id"], str) or item["chunk_id"] in contexts
                        or not isinstance(item["context"], str)):
                    raise ContextualIndexError("contextual_response_coverage_invalid")
                value = item["context"].strip()
                word_count = len(value.split())
                if not 5 <= word_count <= 120 or len(value) > 800:
                    raise ContextualIndexError("contextual_response_length_invalid")
                contexts[item["chunk_id"]] = value
            expected = {entry["chunk"]["id"] for entry in missing}
            if set(contexts) != expected:
                raise ContextualIndexError("contextual_response_coverage_invalid")
            usage = getattr(contextualizer, "last_metadata", {}).get("usage", {})
            if not isinstance(usage, dict):
                usage = {}
            connection.execute("BEGIN IMMEDIATE")
            for entry in missing:
                chunk = entry["chunk"]
                value = contexts[chunk["id"]]
                connection.execute(
                    "INSERT OR IGNORE INTO context_cache(cache_key,material_id,revision_id,chunk_id,revision_sha256,normalized_content_sha256,chunk_md5,context_model,prompt_version,context_text,word_count,char_count,usage_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (entry["cache_key"], doc["material_id"], doc["revision_id"], chunk["id"],
                     doc["revision_sha256"], doc["normalized_content_sha256"],
                     entry["chunk_hash"], self.context_model,
                     self.prompt_version, value, len(value.split()), len(value), _json(usage)),
                )
                entry["context"] = value
            self._add_usage(connection, usage)
            connection.commit()
        if any(entry["context"] is None for entry in entries):
            raise ContextualIndexError("contextual_cache_missing")
        text_entries = []
        for entry in entries:
            text = entry["context"] + "\n\n" + entry["chunk"]["text"]
            if len(text) > MAX_EMBED_TEXT_CHARS:
                raise ContextualIndexError("contextual_embedding_text_too_large")
            text_entries.append(text)
        if not text_entries:
            return
        vectors = embedding.embed(text_entries, task="document")
        if not isinstance(vectors, list) or len(vectors) != len(entries):
            raise ContextualIndexError("contextual_embedding_count_mismatch")
        encoded = [_normalized_vector(vector).tobytes(order="C") for vector in vectors]
        connection.execute("BEGIN IMMEDIATE")
        try:
            for entry, text, vector in zip(entries, text_entries, encoded, strict=True):
                chunk = entry["chunk"]
                connection.execute(
                    "INSERT INTO passages(chunk_id,material_id,revision_id,start_offset,end_offset,category,chunk_md5,cache_key,embedding) VALUES(?,?,?,?,?,?,?,?,?)",
                    (chunk["id"], doc["material_id"], doc["revision_id"], chunk["start_offset"],
                     chunk["end_offset"], doc["category"], entry["chunk_hash"], entry["cache_key"], vector),
                )
                connection.execute("INSERT INTO passages_fts(chunk_id,content) VALUES(?,?)", (chunk["id"], text))
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    @staticmethod
    def _add_usage(connection, usage: dict[str, Any]) -> None:
        row = connection.execute("SELECT value FROM index_meta WHERE key='manifest'").fetchone()
        manifest = json.loads(row["value"])
        total = manifest.setdefault("usage", {})
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(key)
            if type(value) is int and value >= 0:
                total[key] = total.get(key, 0) + value
        cost = usage.get("estimated_cost")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool) and math.isfinite(float(cost)) and cost >= 0:
            total["estimated_cost"] = round(float(total.get("estimated_cost", 0.0)) + float(cost), 12)
        connection.execute("INSERT OR REPLACE INTO index_meta(key,value) VALUES('manifest',?)", (_json(manifest),))

    def activate(self) -> dict[str, Any]:
        if self._already_complete:
            manifest = self._manifest
            self._activate_file(self.final_path, manifest)
            return self._reported_manifest(manifest)
        connection = _connect(self.staging_path)
        try:
            complete_sources = connection.execute("SELECT COUNT(*) FROM sources WHERE complete=1").fetchone()[0]
            complete_chunks = connection.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
            if complete_sources != self.expected_source_count or complete_chunks != self.expected_chunk_count:
                raise ContextualIndexError("contextual_index_incomplete")
            rows = connection.execute("""SELECT s.material_id,s.revision_id,s.revision_sha256,
                s.normalized_content_md5,s.category,
                p.chunk_id,p.start_offset,p.end_offset
                FROM passages p JOIN sources s ON s.material_id=p.material_id
                ORDER BY s.material_id,p.start_offset,p.chunk_id""").fetchall()
            pieces = ["\x1f".join([
                row["material_id"], row["revision_id"], row["revision_sha256"],
                row["normalized_content_md5"], row["category"],
                row["chunk_id"], str(row["start_offset"]), str(row["end_offset"]),
            ]) for row in rows]
            actual_hash = _hash_text("\x1e".join(pieces))
            if actual_hash != self.expected_corpus_hash:
                raise ContextualIndexError("contextual_index_stale")
            source_rows = connection.execute("""SELECT material_id,revision_id,revision_sha256,
                normalized_content_sha256 FROM sources ORDER BY material_id""").fetchall()
            source_revision_hash = source_revision_manifest_hash(source_rows)
            normalized_content_hash = normalized_content_manifest_hash(source_rows)
            if (source_revision_hash != self.expected_source_revision_manifest_sha256
                    or normalized_content_hash != self.expected_normalized_content_manifest_sha256):
                raise ContextualIndexError("contextual_index_source_hash_mismatch")
            fts_count = connection.execute("SELECT COUNT(*) FROM passages_fts").fetchone()[0]
            if fts_count != self.expected_chunk_count:
                raise ContextualIndexError("contextual_index_incomplete")
            lengths = connection.execute("""SELECT COUNT(*) AS count,SUM(c.word_count) AS word_count_total,
                MIN(c.word_count) AS word_count_min,MAX(c.word_count) AS word_count_max,
                SUM(c.char_count) AS char_count_total,MIN(c.char_count) AS char_count_min,
                MAX(c.char_count) AS char_count_max
                FROM passages p JOIN context_cache c ON c.cache_key=p.cache_key""").fetchone()
            if lengths["count"] != self.expected_chunk_count:
                raise ContextualIndexError("contextual_index_context_missing")
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ContextualIndexError("contextual_index_integrity_failed")
            row = connection.execute("SELECT value FROM index_meta WHERE key='manifest'").fetchone()
            manifest = json.loads(row["value"])
            manifest.update(complete=True, corpus_hash=actual_hash,
                            source_count=complete_sources, chunk_count=complete_chunks,
                            fts_sqlite_version=sqlite3.sqlite_version,
                            eligible_source_count=complete_sources, eligible_chunk_count=complete_chunks,
                            source_hashes={
                                "revision_manifest_sha256": source_revision_hash,
                                "normalized_content_manifest_sha256": normalized_content_hash,
                            },
                            context_lengths={key: lengths[key] for key in (
                                "count", "word_count_total", "word_count_min", "word_count_max",
                                "char_count_total", "char_count_min", "char_count_max",
                            )})
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("INSERT OR REPLACE INTO index_meta(key,value) VALUES('manifest',?)", (_json(manifest),))
            connection.commit()
            self._manifest = manifest
        except ContextualIndexError:
            raise
        except (sqlite3.Error, json.JSONDecodeError):
            raise ContextualIndexError("contextual_index_activation_failed") from None
        finally:
            connection.close()
        try:
            self.staging_path.chmod(0o600)
            os.replace(self.staging_path, self.final_path)
            self._activate_file(self.final_path, self._manifest)
        except OSError:
            raise ContextualIndexError("contextual_index_activation_failed") from None
        return self._reported_manifest(self._manifest)

    def _reported_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        """Add current canonical totals for build reporting without keying the projection on them."""
        reported = manifest.copy()
        reported.update(
            eligible_source_count=self.expected_source_count,
            eligible_chunk_count=self.expected_chunk_count,
            canonical_source_count=self.canonical_source_count,
            canonical_chunk_count=self.canonical_chunk_count,
        )
        return reported

    def _activate_file(self, path: Path, manifest: dict[str, Any]) -> None:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    digest.update(block)
        except OSError:
            raise ContextualIndexError("contextual_index_file_missing") from None
        manifest_hash = hashlib.sha256(_json(manifest).encode("utf-8")).hexdigest()
        pointer = {
            "schema_version": INDEX_SCHEMA_VERSION, "generation_id": self.generation_id,
            "file": path.name, "file_sha256": digest.hexdigest(),
            "manifest": manifest, "manifest_sha256": manifest_hash,
        }
        _write_private_file(self.directory / "active.json", _json(pointer).encode("utf-8"))


class ContextualIndex:
    """Read-only active generation with local exact cosine and real FTS5 BM25."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory).expanduser()
        self._verified_generation: str | None = None

    def _active(self):
        directory = _private_directory(self.directory, create=False)
        pointer_path = directory / "active.json"
        _check_private_file(pointer_path)
        try:
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise ContextualIndexError("contextual_index_manifest_invalid") from None
        if not isinstance(pointer, dict) or pointer.get("schema_version") != INDEX_SCHEMA_VERSION:
            raise ContextualIndexError("contextual_index_manifest_invalid")
        generation_id = pointer.get("generation_id")
        filename = pointer.get("file")
        if (not isinstance(generation_id, str) or not _ID_PATTERN.fullmatch(generation_id)
                or filename != f"generation-{generation_id}.sqlite3"):
            raise ContextualIndexError("contextual_index_manifest_invalid")
        path = directory / filename
        _check_private_file(path)
        manifest = pointer.get("manifest")
        if (not isinstance(manifest, dict) or not manifest.get("complete")
                or manifest.get("generation_id") != generation_id
                or hashlib.sha256(_json(manifest).encode("utf-8")).hexdigest() != pointer.get("manifest_sha256")):
            raise ContextualIndexError("contextual_index_manifest_invalid")
        if manifest.get("fts_sqlite_version") != sqlite3.sqlite_version:
            raise ContextualIndexError("contextual_index_fts_version_mismatch")
        if self._verified_generation != generation_id:
            digest = hashlib.sha256()
            try:
                with path.open("rb") as stream:
                    while block := stream.read(1024 * 1024):
                        digest.update(block)
            except OSError:
                raise ContextualIndexError("contextual_index_file_missing") from None
            if digest.hexdigest() != pointer.get("file_sha256"):
                raise ContextualIndexError("contextual_index_checksum_mismatch")
            db_manifest = ContextualIndexBuilder._load_db_manifest(path)
            if db_manifest != manifest:
                raise ContextualIndexError("contextual_index_manifest_mismatch")
            self._verified_generation = generation_id
        return path, manifest

    def search(self, query: str, vector: Any, category: str, limit: int, *,
               expected_corpus_hash: str, embedding_fingerprint: str,
               context_model: str, prompt_version: str) -> dict[str, Any]:
        path, manifest = self._active()
        if expected_corpus_hash != manifest.get("corpus_hash"):
            raise ContextualIndexError("contextual_index_stale")
        if (manifest.get("embedding_fingerprint") != embedding_fingerprint
                or manifest.get("context_model") != context_model
                or manifest.get("prompt_version") != prompt_version
                or manifest.get("embedding_dimensions") != EMBEDDING_DIMENSIONS):
            raise ContextualIndexError("contextual_index_profile_mismatch")
        if (not isinstance(query, str) or not isinstance(category, str)
                or type(limit) is not int or not 1 <= limit <= 100):
            raise ContextualIndexError("contextual_search_input_invalid")
        if isinstance(vector, (str, bytes)):
            raise ContextualIndexError("contextual_query_vector_invalid")
        try:
            raw_vector = list(vector)
        except (TypeError, ValueError):
            raise ContextualIndexError("contextual_query_vector_invalid") from None
        if (len(raw_vector) != EMBEDDING_DIMENSIONS
                or any(isinstance(value, bool) or not isinstance(value, (int, float, np.number)) for value in raw_vector)):
            raise ContextualIndexError("contextual_query_vector_invalid")
        try:
            query_vector = _normalized_vector(raw_vector)
        except ContextualIndexError:
            raise ContextualIndexError("contextual_query_vector_invalid") from None
        connection = _connect(path, readonly=True)
        try:
            count = connection.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
            if count != manifest.get("chunk_count") or count > MAX_INDEX_CHUNKS:
                raise ContextualIndexError("contextual_index_incomplete")
            dense = self._dense_candidates(connection, query_vector, category, limit)
            bm25 = self._bm25_candidates(connection, query, category, limit)
            ids = list(dict.fromkeys(row["chunk_id"] for row in dense + bm25))
            contexts = {}
            if ids:
                placeholders = ",".join("?" for _ in ids)
                rows = connection.execute(
                    f"SELECT p.chunk_id,c.context_text FROM passages p JOIN context_cache c ON c.cache_key=p.cache_key WHERE p.chunk_id IN ({placeholders})",
                    ids,
                ).fetchall()
                contexts = {row["chunk_id"]: row["context_text"] for row in rows}
            if set(contexts) != set(ids):
                raise ContextualIndexError("contextual_index_context_missing")
            return {"dense": dense, "bm25": bm25, "contexts": contexts, "manifest": manifest.copy()}
        except ContextualIndexError:
            raise
        except sqlite3.Error:
            raise ContextualIndexError("contextual_index_query_failed") from None
        finally:
            connection.close()

    @staticmethod
    def _dense_candidates(connection, query_vector, category, limit):
        sql = "SELECT chunk_id,material_id,revision_id,chunk_md5,embedding FROM passages"
        args: tuple[Any, ...] = ()
        if category:
            sql += " WHERE category=?"
            args = (category,)
        sql += " ORDER BY chunk_id"
        cursor = connection.execute(sql, args)
        scored = []
        while rows := cursor.fetchmany(512):
            ids = [row["chunk_id"] for row in rows]
            try:
                matrix = np.frombuffer(b"".join(row["embedding"] for row in rows), dtype="<f4").reshape(len(rows), EMBEDDING_DIMENSIONS)
            except (TypeError, ValueError):
                raise ContextualIndexError("contextual_index_embedding_invalid") from None
            if not np.isfinite(matrix).all():
                raise ContextualIndexError("contextual_index_embedding_invalid")
            scores = np.einsum("ij,j->i", matrix, query_vector, optimize=False)
            scored.extend((float(score), row["chunk_id"], row["material_id"], row["revision_id"], row["chunk_md5"])
                          for score, row in zip(scores, rows, strict=True))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [{"chunk_id": chunk_id, "material_id": material_id, "revision_id": revision_id,
                 "chunk_md5": chunk_md5, "score": score, "rank": rank}
                for rank, (score, chunk_id, material_id, revision_id, chunk_md5) in enumerate(scored[:limit], 1)]

    @staticmethod
    def _bm25_candidates(connection, query, category, limit):
        terms = re.findall(r"[\w]+", query, flags=re.UNICODE)
        if not terms:
            return []
        match = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms[:64])
        sql = """SELECT f.chunk_id,p.material_id,p.revision_id,p.chunk_md5,bm25(passages_fts) AS score
            FROM passages_fts f JOIN passages p ON p.chunk_id=f.chunk_id
            WHERE passages_fts MATCH ?"""
        args: list[Any] = [match]
        if category:
            sql += " AND p.category=?"
            args.append(category)
        sql += " ORDER BY score ASC,f.chunk_id LIMIT ?"
        args.append(limit)
        rows = connection.execute(sql, args).fetchall()
        return [{"chunk_id": row["chunk_id"], "material_id": row["material_id"],
                 "revision_id": row["revision_id"], "chunk_md5": row["chunk_md5"],
                 "score": float(row["score"]), "rank": rank}
                for rank, row in enumerate(rows, 1)]
