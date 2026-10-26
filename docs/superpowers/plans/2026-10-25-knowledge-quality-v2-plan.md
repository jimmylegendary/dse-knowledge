# Knowledge quality v2 Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development. No nested delegation. Root owns DB/credentials/live providers/deploy/commit.

**Goal:** 승인된 Write/KG/Read 보완을 실제 제품에 반영하고, 같은 전체 사용자 여정으로1,000개를처리·평가한다.
**Architecture:** 기존PG정본·vector/FTS·topic graph·HTTP/CLI·Codex/embedding·native integrations를유지하고versionedannotation/role/collectionlease를추가한다.
**Tech Stack:** Python3.12/FastAPI/psycopg/PG17/pgvector768, stdlibcache/process/HTTP, 기존modeladapters.
**Spec:** [2026-10-25-knowledge-quality-v2-design.md](https://github.com/jimmylegendary/dse-knowledge/blob/main/docs/superpowers/specs/2026-10-25-knowledge-quality-v2-design.md)

## Global constraints

사용자가보완3단계를실행승인했다. 승인된Linux·Supabase·현재provider만사용한다. 14만일괄실행X; credential/private원문/public답변Git노출X; epoch별originalsource/Claim/decision/audit보존. Phase마다실제UI·실제dependencies·DSE/feedback전체여정을확인한다. Mandatory validation과permission/physicaltruth구분은유지한다.

## Ownership/Review focus

|Task|파일/producer|consumer|검사할interface·위험|
|---|---|---|---|
|A|knowledge.py/ingestion.py, tests|rootdb/pipeline·Btopicquery|literalproof/조건범위/units; 모델조건을hardconstraint로승격금지|
|B|retrieval.py/tests/test_retrieval_v2.py|rootapp/decisions/UI|3positional호환/purpose/role SQL; graphnoise·캐시usage·문맥citationID/단위보존|
|C|collection.py/004_collection.sql/tests|rootpipeline/CLI|leasedstagehandler계약/staleowner/counters/resourceguards·실패분모|
|Root|003migration/db.py/pipeline.py/app.py/decisions.py/cli.py/web/scripts|전체|A/B/C계약순차통합, schema-firstdeploy, snapshot·native boundaries, secrets·명령·실출력|
|Review|각task와전체read-only|root수정|labelblinding·source/Claimimmutable·authority·공개범위·단계별실제제품gate|

## Tasks

- [x] 1. Spec/기존worktree/ledger/preflight builder 검토. Root가minor구현선택을ruling으로고정한다. 기존161testsbaseline이이미verified임을보존한다.
- [x] 2. A TDD: source-role/contextschema, parameter·condition proof/normalization, curatedtopic registry, structuredextract opt-in; backwardtests와반례통과.
- [x] 3. B TDD: nonempty lexical·boundedgraph·role routing/rerank/diversity/neighbor·querycache; fakeStoretests→root실제후보trace검증.
- [x] 4. C TDD: durablecollectionlease·heartbeat·resume·counter·quota/storageguard, offline failurefixtures와DDL contract 검증.
- [x] 5. Root schema/Store/annotationprojection/rolehistory/pipeline/advisoryadapter/modelresultcache 통합. 필요한adminmigration만root적용, runtime권한확인. 기존100curation을revisionproof와함께반영한다.
- [x] 6. Root UI/CLI에서role/typedcontext/topic 표시와purpose선택, DSEsnapshot refs/Melete환류·metric·HAT구조검증회귀. 별도workerreview와root실제E2E후Q1deploy.
- [x] 7. 고정30regression와결과독립새질의/pairedlanguage로Q1평가. 실제3blindmodelprobe·feedback/native역할상한, 재시작/리트라이검증. Q1전체제품gate와정직한한계를공개한다.
- [x] 8. Root rawregistry에서1000용candidate준비, DB/host/공간/quota budget실측. 실제acquire→assess→index→structuredclaim lease workers를안전하게실행. 부분완료를전체완료로세지않는다. 2026-10-25 22:49 UTC: 실제1,000 inventory 고정/active0, 기존100+신규900, 원문hash1,000/벡터18,518 검사·정확한집합검사 오류0. All-eligible KG960/984=97.56%;참고16/검토23/추출실패1은별도보존. Supabase plan/quota와전체청구액은미확인상태로남긴다. Task9·10과Q2전체제품완료는아직열려있다.
- Task8 recovery: ruling12의 provider stage attempt 상한을 C가 TDD로 보완하고 D가 독립 리뷰한다. Root는 실제 PG rollback에서 소진·circuit·resume·stale owner를 확인하고 전체 회귀 후 v0.2.3을 배포한다. 600초 단일 진단의 품질 실패는 유지하며 같은 batch의 collection unit만 600초로 재개한다. 완료된 438개 정본은 보존하고 이후 500개 지점의 상태·사용량·DB/host 공간을 확인한다.
- [x] 9. 실제1000의source/Claim/조건/graph/sourceRole와다른material새질의·같은UI/LLM/nativefeedback/metric/HAT회귀검증. Tokens/time/실패·재개·원문공간·DBindex/throughput평가. 2026-10-26: 새28 source Hit@5 두stream24/24/오류0, 실제blind3 실행·원문대조2 supported+1 unknown, native18/18, 실제UI job·desktop/mobile overflow0, source정본변경0, 18table백업smoke·재시작7record/Melete보존통과. Jev불일치·reviewer probe-trace노출·작은같은corpus표본·HAT구조검증상한은보고에보존한다.
- Task9 preflight: 수집 중 C가 ruling14의 helper-only guard를 TDD로 보완하고 별도 worker가 리뷰한다. Root는 fake HTTP의 accepted-but-ID-unsaved·inventory mismatch·scope mismatch 반례를 실제 helper에 적용해 provider 호출 없이 확인한다. 제품/API/DDL·수집 모델·read policy는 바꾸지 않는다. 실제1,000 완료 후 manifest equality→공개회귀→policy freeze→새gold/retrieval→blind3 실행·의미검토→native E2E/feedback 순서를 지킨다.
- Task8 recovery: 934개 storage block은 ruling15에 따라 실제 atomic writer/scanner 경쟁을 격리 재현하고, bounded full-pass 재확인을 TDD·독립 리뷰·root 실제 파일 검증 후 배포한다. Baseline과 완료 데이터의 hash 보존, old coordinator/active lease 0, 같은 batch reasoned resume를 확인한다. Storage 오류를 provider 실패로 기록하거나 실패한 파일의 byte 수를 누락하지 않는다. Target1,000과 나머지 gate는 유지한다.
- Task8 freeze: ruling16에 맞는 metadata-only freeze helper v2를 별도 파일로 만들고 v1/hash를 보존한다. Native terminal indexed failure는 오류와 함께 inventory에만 포함하며 KG 완료로 세지 않는다. Unindexed failure·active/미종료 stage·canonical/index 누락은 여전히 gate 실패다. 독립 리뷰와 반례 self-test 뒤 실제1,000 고정을 실행하고, all-eligible KG90%와 Task9 평가를 별도로 통과해야 한다.
- Task9 recovery: ruling17의 실제 ANN 누락·mixed-script feature 손실을 TDD로 보완한다. B는 bounded exact dense SQL/trace와 Latin-Hangul features만 고치고, 별도 worker가 trust/scope·snapshot·scan cap·오류·ranking 불변성을 리뷰한다. Root는 실제 PG EXPLAIN/거리순위·cap 반례와 기존30/Q1 paired28을 재검증하고 corpus 불변성을 확인한 후 read policy를 고정한다. 처음20/24 실패와 진단 원자료를 보존하며 새 gold를 먼저 만들거나 qrels·gate를 바꾸지 않는다.
- [x] 10. 별도최종review→root원자료·test·secret검증→README/metadata-only report→authorizedGitHub게시. 2026-10-26: 최종 publication review PASS/차단0, root 공개5파일·secret노출0·frozen code25개 불변·Q1자료불변 확인. 공개main 게시 대상으로 README·자료목록1,000개·질의/검색 metadata·검증 report를 확정했다. Runtimeworktree는서비스경로여서삭제하지않는다.
- Task9 helper recovery 완료: ruling18의 CaptureStore connection/cursor 호환성·실패 CLI gate를 TDD·별도 리뷰 후 4a29d7f로 게시했다. 기존 공개30/paired28을 각각 새 output에 실제 재실행해 요청 오류0, source Hit@5 자료탐색24/24·기술근거23/24 및 두stream24/24를 확인했다. 30개 AttributeError 원보고서와 처음20/24 회귀 결과는 보존했고 production ranking·qrels·분모를 helper 수정으로 바꾸지 않았다.

## Ledger

2026-10-25 start: accepted补완목표와f2e113cbaseline확인. 기존실서비스worktree를재사용하며개별구현선택은master판단으로상기spec에명시했다. 사용자에게재승인이나도메인/HTTPS질문을하지않는다.

2026-10-25 08:51 UTC checkpoint: Tasks1–7/Q1 전체 제품은 실제 검증 후 게시했다(6a3fc9d, e5b90bd). Task8/Q2는 기존100포함1,000 target으로 실행 중이며 아직 미완료다. 반복 provider 오류의 bounded timeout/실패 ledger/repair 진단 보완은382tests와별도리뷰PASS후7dee23a로게시, live0.2.1에서같은batch재개를확인했다. Task9/10 최종평가·전체완료gate는1,000 corpus고정후수행한다. 상세 실행 증거는 private qa/quality-v2와 작업 ledger에 보존한다.
