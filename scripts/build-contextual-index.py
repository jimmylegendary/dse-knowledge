#!/usr/bin/env python3
"""Build the private derived contextual index from current PostgreSQL sources."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from dse_knowledge.config import Settings
from dse_knowledge.contextual import CONTEXT_CHAT_MODEL, ContextGenerator
from dse_knowledge.contextual_index import (
    ContextualIndexBuilder, ContextualIndexError, source_revision_manifest_hash,
)
from dse_knowledge.db import Store
from dse_knowledge.providers import EmbeddingClient, ProviderError


def build_contextual_index(settings, store, contextualizer, embedding):
    initial = store.contextual_corpus_manifest()
    references = store.contextual_document_refs()
    if len(references) != initial["source_count"]:
        raise ContextualIndexError("contextual_corpus_manifest_invalid")
    normalized_manifest = store.contextual_normalized_content_manifest()
    source_revision_manifest = source_revision_manifest_hash(references)
    dimensions_text = settings.get("DSE_EMBEDDING_DIMENSIONS", settings.get("EMBEDDING_DIMENSIONS", "768"))
    try:
        dimensions = int(dimensions_text)
    except (TypeError, ValueError, OverflowError):
        raise ContextualIndexError("contextual_embedding_profile_unsupported") from None
    if dimensions != 768:
        raise ContextualIndexError("contextual_embedding_profile_unsupported")
    provider = settings.get("DSE_EMBEDDING_PROVIDER", settings.get("EMBEDDING_PROVIDER", "deepinfra"))
    model = settings.get("DSE_EMBEDDING_MODEL_ID", settings.get("EMBEDDING_MODEL_ID", "google/embeddinggemma-2"))
    embedding_fingerprint = f"{provider}:{model}:{dimensions}"
    context_model = settings.get("DSE_CONTEXT_CHAT_MODEL", CONTEXT_CHAT_MODEL)
    prompt_version = contextualizer.prompt_version
    default_path = settings.data_root / "contextual-index"
    index_path = Path(settings.get("DSE_CONTEXT_INDEX_PATH", str(default_path))).expanduser()
    builder = ContextualIndexBuilder(
        index_path,
        expected_corpus_hash=initial["corpus_hash"],
        expected_source_count=initial["source_count"],
        expected_chunk_count=initial["chunk_count"],
        expected_source_revision_manifest_sha256=source_revision_manifest,
        expected_normalized_content_manifest_sha256=normalized_manifest,
        canonical_source_count=initial["canonical_source_count"],
        canonical_chunk_count=initial["canonical_chunk_count"],
        embedding_fingerprint=embedding_fingerprint,
        context_model=context_model,
        prompt_version=prompt_version,
    )
    for reference in references:
        document = store.contextual_document(reference["material_id"], reference["revision_id"])
        if (document.get("revision_sha256") != reference["revision_sha256"]
                or document.get("category") != reference["category"]
                or (reference.get("stored_normalized_content_sha256")
                    and document.get("normalized_content_sha256") != reference["stored_normalized_content_sha256"])):
            raise ContextualIndexError("contextual_source_changed_during_build")
        builder.add_document(document, contextualizer, embedding)
    final = store.contextual_corpus_manifest()
    if any(final.get(key) != initial.get(key) for key in ("corpus_hash", "source_count", "chunk_count")):
        raise ContextualIndexError("contextual_corpus_changed_during_build")
    return builder.activate()


def main() -> int:
    settings = Settings.load(admin=True)
    store = Store(settings)
    contextualizer = ContextGenerator(settings)
    embedding = EmbeddingClient(settings)
    try:
        manifest = build_contextual_index(settings, store, contextualizer, embedding)
    except (ContextualIndexError, ProviderError, ValueError) as exc:
        code = getattr(exc, "code", getattr(exc, "reason", str(exc)))
        print(json.dumps({"status": "failed", "code": code}, separators=(",", ":")), file=sys.stderr)
        return 2
    print(json.dumps({
        "status": "complete", "generation_id": manifest["generation_id"],
        "corpus_hash": manifest["corpus_hash"], "source_count": manifest["source_count"],
        "chunk_count": manifest["chunk_count"],
        "eligible_source_count": manifest["eligible_source_count"],
        "eligible_chunk_count": manifest["eligible_chunk_count"],
        "canonical_source_count": manifest["canonical_source_count"],
        "canonical_chunk_count": manifest["canonical_chunk_count"],
        "embedding_fingerprint": manifest["embedding_fingerprint"],
        "source_hashes": manifest["source_hashes"],
        "context_model": manifest["context_model"], "prompt_version": manifest["prompt_version"],
        "context_lengths": manifest["context_lengths"], "usage": manifest["usage"],
        "cost_is_estimate": True,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
