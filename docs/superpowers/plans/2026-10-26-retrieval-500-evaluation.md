# Retrieval 500 Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Root manages credentials, actual API/DB access, integration, and publication; workers own only explicitly assigned files. No nested agents or separate codex exec.

**Goal:** 500개의 다양한 held-out 검색 질문과 100개의 calibration 질문으로 현재 시스템의 ranking·OOD·grey-zone 분별력을 실제 평가하고 test set과 결과를 GitHub에 게시한다.

**Architecture:** 기존 production 검색 정책과 corpus를 고정한다. Source-bound 질문 작성/독립 검토 → calibration → 고정 threshold → 500 test → metadata-safe 결과/HTML → 검증·게시를 하나의 완결된 평가 흐름으로 제공한다. Raw ranking score와 답변 근거의 충분성을 분리한다.

**Tech Stack:** Python 3.12, existing FastAPI HTTP service, Supabase read-only corpus export, external embedding, deterministic metrics, optional Jev advisory, standalone HTML.

**Spec:** [2026-10-26-retrieval-500-evaluation-design.md](/home/jimmy/.paseo/worktrees/06af7m2w/http-selfhost-pilot100/docs/superpowers/specs/2026-10-26-retrieval-500-evaluation-design.md)

## Global Constraints

- Existing isolated worktree, branch `feat/http-selfhost-pilot100`, initial HEAD `69c18f863cfc28a524913b5a4e7a68e7d26be07b`. Baseline: 458 passed, 1 existing warning in 2.28s.
- 500 test (300 supported, 200 insufficient/ambiguous) + 100 calibration (60/40), KO/EN balanced. Corpus/intent groups split; partial qrels and actual group count always reported.
- Production code/weights/index policy are frozen; evaluator code only. No thresholds fit on test and no post-result label/ranking changes hidden as the first run.
- Root-only actual DB/API/config access and git/publish. Workers cannot read owner config/credentials. Metadata-safe public artifacts only. Host concurrency 2, resumable journal, bounded retries.

## Review Focus

- Ambiguous question with multiple valid answers must allow alternatives or require clarification; one arbitrary chunk is not exclusive truth.
- A nearby relevant document does not support an invented revision/measurement; high relevance and low sufficiency can coexist.
- RRF maxima are not comparable probabilities; missing confidence must remain missing.
- Calibration/test question variants or source/intent groups must not leak; raw error rows remain in output and exclusion denominators.
- Large raw API responses/private evidence and generated answers must not enter public files or huge tool output.

## Tasks and file ownership

|Task|Owner|Files / output|Gate|
|---|---|---|---|
|1 Corpus snapshot and evidence packets|root|private `.superpowers/sdd/eval500/` export; public metadata manifest later|Actual read-only export, counts/hash, material split, no private source|
|2 Supported cases|worker D `quality_v2_holdout`|private draft JSONL, 300 test +60 calibration|Evidence-backed qrels and paraphrased answer facts; language/tier/group checks; no retrieval results|
|3 Negative/clarify cases|worker C `quality_v2_collection`|private draft JSONL, 200 test +40 calibration|Boundary rationale and nearby evidence; no unsupported global absence or arbitrary hard rejection|
|4 Evaluator/metrics|worker B `quality_v2_retrieval`|exact script/module/test paths fixed after recon|Meaningful synthetic ranking/score/threshold/split/error/resume tests, production unchanged|
|5 Independent dataset/rubric review|worker A `quality_v2_builder`|private review JSON; optional bounded Jev advisory|Before results: label/evidence/difficulty/alternatives/negative rationale review; root adjudicates findings|
|6 Freeze and actual execution|root|public `research/eval500/` frozen inputs, private raw journal, metadata-safe results|Calibration precedes threshold freeze, 500 test complete or explicit error counts, corpus/code checked|
|7 Report and publication|worker after prior task finishes, root integration|standalone HTML, README, CSV/JSON summaries, public case/result artifacts|Independent review, actual HTML/browser/HTTP, git checks, GitHub push and remote SHA/files verification|

## Execution steps

- [x] Read repo instructions, confirm existing worktree/clean scope, baseline tests; dispatch separate recon/author/reviewer roles.
- [ ] Export bounded source evidence packets and metadata-only corpus manifest; freeze authoring schema and split.
- [ ] Author and independently review 600 cases, validate IDs/revisions/evidence spans and distributions, freeze.
- [ ] Implement and independently review evaluator/metrics, run focused meaningful tests.
- [ ] Execute 100 calibration, freeze score/threshold policy, then execute 500 test through actual API. Preserve retries/errors and provider usage scope.
- [ ] Build full report with ranking, negative score distributions, actual threshold tradeoffs, subgroup/group counts and limits; include local HTML.
- [ ] Root verifies results/code/corpus, independent final review, GitHub upload and actual remote verification.

## Phase outcome

This is one evaluation phase: it ends with a runnable whole evaluator + the actual test set/results + a usable HTML report. Dataset preparation and recon are tasks within this phase, not separately completed products. It raises breadth (500 questions, boundary/OOD/ambiguity) and depth (chunk/source metrics, difficulty and negative discrimination) together. It does not promise calibrated production abstention, full-corpus relevance truth, generation correctness, or DSE hardware performance.

## Working ledger

Private per-task state and corrections are recorded in `.superpowers/sdd/eval500/progress.md`. User explicitly authorized execution and GitHub publication; no repeated approval question is needed. Scope/rubric implementation choices are root decisions and will be reported with actual counts and limitations.
