# Contextual Retrieval and Reranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Worker implements scoped files; root owns actual provider/DB/index build, integration, deployment and publication. No nested agents or unmanaged codex exec.

**Goal:** 기존 DSE KG 전체 흐름에서 실제 LLM contextual embedding/BM25와 external Qwen reranking을 사용할 수 있게 하고, 고정 500 test로 기존 방식과 비교해 게시한다.

**Architecture:** PG canonical source는 유지하고 versioned SQLite contextual projection+NumPy exact dense+FTS5 BM25를 재생성 가능한 read index로 둔다. Hybrid 이후 external reranker를 적용하며 evidence authority와 원문 citation은 그대로 유지한다.

**Tech Stack:** Python3.12, existing FastAPI/PG/EmbeddingClient, SQLite FTS5, NumPy, DeepInfra-compatible context/rerank APIs.

**Spec:** [2026-10-26-contextual-retrieval-rerank-design.md](/home/jimmy/.paseo/worktrees/06af7m2w/contextual-retrieval-rerank/docs/superpowers/specs/2026-10-26-contextual-retrieval-rerank-design.md)

## Constraints and review focus

- Existing baseline runtime remains in sibling worktree and is not changed during its evaluation. This worktree starts at `790a77b`; implementer must not open eval500 private cases/qrels/reviews/results.
- Generated contexts are untrusted retrieval hints, never canonical Claim text. Existing source `text`, `claim_contexts`, IDs/revision/role ceilings must survive reranking.
- Real BM25 is SQLite `bm25()`; do not rename PG ts_rank as BM25. Exact normalized vector math has finite/dimension/zero-vector checks; 50k cap remains.
- Whole-document input scope, omitted IDs, truncated model output, wrong-model response, malformed reranker scores, duplicate indices, stale manifests and interrupted activation require explicit handling.
- Root alone reads private env, executes real services/provider/DB, and commits. All tests in worker are isolated fake transports/temp indexes; final completion requires root actual E2E.

## Tasks / approved file ownership

|Task|Worker files|Evidence|
|---|---|---|
|Context generation|create `src/dse_knowledge/contextual.py`; narrow changes `config.py`/`providers.py` only as required|whole-doc+batch JSON validation, cache key/version, prompt injection boundaries, failure/usage metadata tests|
|Derived index|create `src/dse_knowledge/contextual_index.py`, `scripts/build-contextual-index.py`; `pyproject.toml`/`uv.lock` for NumPy only if required|FTS5 BM25 and dense math, canonical bindings, atomic/resume build, finite values, stale/missing/oversize tests|
|Reranker|create `src/dse_knowledge/reranking.py`|DeepInfra 4B/8B and cohere-compatible HTTP contract, cardinality/index/NaN/error tests; secrets redacted|
|API integration|narrow changes `retrieval.py`, `app.py`, optional `db.py` canonical hydration helpers; config examples only|mode off preserves existing tests; on retains policies/citation text; typed provider/index errors; capability/trace metadata|
|Validation|create `tests/test_contextual.py`, `tests/test_contextual_index.py`, `tests/test_reranking.py`, `tests/test_contextual_retrieval.py` as useful|meaningful tests for actual behavior, regression suite; no mirrored/ceremonial tests|
|Root operations|private preflight, context build, new service, ablations, existing 500 evaluator adaptation in original worktree|actual provider/PG/embedding/HTTP; fixed gold/thresholds; public metadata-safe report and GitHub upload|

- [x] Isolated native worktree created; existing baseline untouched; official model/method API docs read; fresh implementer has no test labels.
- [x] Implement above files, focused tests and self-review, then independent code review. Runtime suite 581 passed; meaningful provider/receipt/engine mismatch cases included.
- [x] Root real provider preflight; build complete contextual index with checkpoint/cache and usage accounting. Eligible999/18512, canonical1000/18518; SQLite3.54 profile and strict integrity verified.
- [x] Root compare same frozen dataset across baseline/context/rerank/combined, calibration-only model selection; report failures and latency as observed. Each test500/cal100 completed without execution errors; grey-zone quality gate remains FAIL.
- [ ] Activate reviewed implementation for actual UI/API; verify baseline regression+new real E2E; publish tests/results/code/HTML to GitHub.

This is one complete product upgrade phase, ending with the whole application and actual dependencies, not an index-only demo. Corpus authoring/evaluation continues in the sibling worktree and is not replaced by this task.
