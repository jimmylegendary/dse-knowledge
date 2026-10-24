# DSE KG HTTP self-host 100-material pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Root owns integration and live verification. No nested delegation.

**Goal:** 100 real materials를 근거가 추적되는 KG로 저장하고, HTTP UI에서 검색·graph·DSE 의사결정·experiment/feedback·Melete 환류를 실제로 수행한다.

**Architecture:** Supabase PostgreSQL canonical ledger와 vector(768)/FTS/typed graph projection을 사용한다. Linux FastAPI HTTP app, bounded job loop, local content-addressed artifacts, Codex CLI와 DeepInfra adapters를 연결한다. Private HAT/Melete 코드는 복사·게시하지 않고 설치된 로컬 package 경계로 호출한다.

**Tech Stack:** Python 3.12, FastAPI/Uvicorn, psycopg 3, PostgreSQL 17 + pgvector, HTML/CSS/vanilla JS, user systemd.

**Spec:** 기존 README의 DSE 지식 architecture와 사용자의 100개 실제 구축·HTTP self-host 승인. 새 단계는 조사 단계 D1–D5를 제품 phase로 오해하지 않는다.

## Global Constraints

- HTTP self-host, env configurable; no AWS/GPU/model-weight download.
- P1은 실제 UI/LLM/embedding/DB와 전체 흐름을 제공하며 infra-only phase로 종료하지 않는다.
- Credentials only private owner files. Public API/health는 secret 값을 노출하지 않는다. App DB role은 schema-scoped, admin migration과 분리한다.
- 외부 source는 public allowlist URL만 수집, size/time/concurrency bounded, redirects 재검사, HTML/script 미실행. 실패는 실패로 남기고 100건을 성공으로 꾸미지 않는다.
- source revision/hash/span과 model/method/version을 저장한다. Claim은 cited assertion이며 독립 검증/물리 feasibility 증명이 아니다.
- Native HAT simulation과 B300 실측은 아직 지원을 확인한 범위만 보고한다. Fixture simulation을 제품 실측으로 쓰지 않는다.

## Capability × phase resolution

|Capability|P1 실제 100개 전체 제품|P2 확장|P3 심화|
|---|---|---|---|
|수집/write|100개 stratified public 자료, revision/span, bounded ingestion|14만 후보의 resumable incremental ingestion|권한/다중 parser/변경 감지|
|KG/read|PG entities/claims, lexical+dense+graph, citation UI|source/version conflict 비교·확장 graph|평가 기반 retrieval/router 학습|
|DSE 결정|hardware/kernel/experiment 질문, 근거·unknown·gap·proposal|다중 agent committee와 typed predicates 확대|자동 architecture/kernel 탐색|
|실험/경험|MetricVector 비교, 실제 local HAT schema·Melete 지원 경계|HAT run orchestration과 trajectory 확대|동일 budget optimizer 비교|
|운영|HTTP UI, 실제 providers, durable jobs, restart, local backup|조직 배포/권한/대량 큐|HA/DR·회귀 평가|

P1 상한: 100개에 대한 source-grounded 의사결정 보조다. 논문의 주장을 physical validation이나 B300 우월성으로 바꾸지 않는다. P2/P3는 이 사용자 여정을 유지하며 단계 시작 때 상세화한다.

## Locked interfaces / file ownership

- Root: pyproject/config/db/schema/retrieval/decision/service/CLI, migrations, deployment, root tests, README.
- Provider/ingestion worker: providers.py, ingestion.py, sampling.py, tests/test_providers.py, tests/test_ingestion.py, tests/test_sampling.py. Settings dataclass와 Store methods 계약을 소비한다.
- Native integration worker: integrations.py, tests/test_integrations.py. Public source에 private native code나 fixture 내용을 복사하지 않는다.
- UI worker: web/* only. API 계약을 소비하고 가짜 제품 data를 넣지 않는다.
- Reviewer: 지정 범위 읽기·정적검토/안전한 unit tests만 수행. Root live DB/credential runs.

Concrete HTTP/Store/provider wire contracts: docs/contracts/pilot-http-api.md, config.py, db.py and worker task briefs. Feedback is canonical PG row → Melete observation → reopened gap → later experience retrieval.

## Review Focus

- Source prompt injection/HTML, invalid citation span, provider result count/dimensions, network/CLI timeout, duplicate/restart idempotency.
- Missing knowledge/metrics is unknown, not success; mandatory validation cannot disappear through retrieval top-k.
- Unsafe URL/redirect/path/SQL injection, secret exposure, process group cleanup, graph user text escaping.
- Native unavailable and receipt delayed states must be honest and retained.
- Worker jobs survive service restart and failed batch can resume without duplicating revisions/claims.

## Tasks and gates

### Task 1 — Source-grounded storage and providers
- [x] Fix stratified sampling policy before code; 9 categories, diverse authoritative sources, non-stub titles, canonical dedup.
- [x] Write failing tests for env validation, bounded providers, citation offsets, ingest idempotency; implement and verify.
- [x] PG migrations + least-privilege app role; 100 material manifest, actual fetch/parse, embedding, Codex claim extraction; failed/unavailable separate.
- [x] Store source revisions/chunks/claims/entities/edges with provenance, exact offsets and model invocation IDs. Raw artifacts stay local.

### Task 2 — Whole HTTP user journey
- [x] Implement search + material detail + graph APIs with real PG/embedding, traced ranking channels.
- [x] Implement durable decision jobs using real Codex, citation whitelist, missing-knowledge gap, next collection/experiment proposal.
- [x] Hardware/kernel/experiment views + MetricVector comparison + native schema validation/Melete observation where runtime supports it.
- [x] Worker UI consumes actual API and error/loading/unknown states; no fabricated run metrics.

### Task 3 — Integration, independent review, operation
- [x] Separate worker review, root fixes and real unit/integration/E2E tests.
- [x] Complete actual 100-material counts and three DSE decision types with citation/feedback, native integration evidence and explicit limitations.
- [x] systemd user HTTP app with restart/resource caps + local logical backup and serialization smoke check; health/restart checks.
- [x] Public repo secret scan, reproducible setup docs, commit and authorized push; report actual URL, counts, checks, SHA.

## Execution ledger

2026-10-25: P1 실제 제품 gate 완료. Supabase 15개 table과 schema 전용 app role, Linux HTTP service, Codex CLI와 DeepInfra 768차원 embedding을 연결했다. 원문 100개/1,912 chunks; Claim 101개가 99개 자료를 덮으며 navigation-only 1개는 reference로 유지한다. 원문 hash·chunk span·quote offset 검사와 graph 참조 정합성 통과. 전체 pytest 148 passed(기존 deprecation warning 1), 실제 HTTP E2E 18/18, desktop/mobile 22개 화면 검증 통과. Hardware/kernel/experiment 결과는 각각 constraint_rejected/insufficient_evidence/insufficient_evidence로 실제 미검증 범위를 드러냈다. Melete feedback 저장·재조회·후속 snapshot 연결, 제어된 restart에서 추가 LLM 호출 0, 같은 feedback event 재전달 시 memory ID 유지 확인. Local 15-table 행 snapshot/SQLite serialization smoke 통과; artifact/native Melete/off-host/PG DR은 제외. 초기 실패와 재시도 원자료는 private data root에 보존한다.

공개 검증 집계: [verification.json](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/pilot100/verification.json). GitHub publication의 최종 SHA는 공개 commit receipt로 확인한다. 서비스 작업 경로인 worktree는 보존한다.

다음 phase를 시작할 때 source role/relevance와 extraction 품질·처리량·비용을 먼저 평가하고, 같은 전체 사용자 여정을 유지한 채 incremental source version·조직 corpus·HAT run orchestration의 해상도를 올린다. 현재 P1을 자동 architecture/kernel 성능 탐색 완료로 간주하지 않는다.
