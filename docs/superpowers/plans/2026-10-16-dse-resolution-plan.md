# DSE Knowledge System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task after the full design and plan have been reviewed. Steps use checkbox syntax. 현재는 계획 작성만 허용되며 아래 실행 항목은 모두 미실행이다.

**Goal:** 모든 HW 계층·kernel·실험 환류를 포괄하는 DSE 지식 시스템을 전체 흐름의 해상도를 높이는 방식으로 구축한다.

**Architecture:** versioned source/Claim/experiment ledger를 중심으로 object artifact, lexical/vector/graph projections, deterministic validation, HAT 및 Melete adapter를 연결한다. Human과 agent는 같은 evidence와 run 계약을 사용한다. 모든 phase는 전체 흐름을 통과한다.

**Tech Stack:** 논리 구조는 확정 제안, 제품 조합은 [recommendation-and-selection.md](https://github.com/jimmylegendary/dse-knowledge/blob/main/docs/recommendation-and-selection.md)의 검토 순서와 gate에 따른다. 추천 조합을 실행 승인으로 간주하지 않는다.

**Spec:** [2026-10-16-dse-knowledge-system-design.md](https://github.com/jimmylegendary/dse-knowledge/blob/main/docs/superpowers/specs/2026-10-16-dse-knowledge-system-design.md)

## Global Constraints

- 모든 설계·계획 검토 완료 전 제품 코드·IaC apply·cloud 설정·유료 자원·corpus 대량 수집 금지.
- 매 phase는 source→knowledge→retrieval→HW review→kernel→HAT→metrics→Melete→next proposal와 infra·평가를 전부 포함한다.
- all-level 표현은 P1부터 필수이며 breadth/depth/automation은 점진적으로 높인다.
- 모델 생성, bounded advisory 판단, deterministic 검증, 실행 권한을 분리한다.
- multi-metric vector를 유지하고 실험 성능을 기술 추천 점수와 혼합하지 않는다.
- master/worker workflow, 별도 reviewer, master 실제 검증을 사용한다. worker 재위임 금지.
- local Markdown 링크는 절대 경로와 파일명 라벨을 사용한다.
- 기존 HAT/Melete는 현재 읽기 전용이다. 아래 미래 수정 대상도 승인된 phase 작업 범위가 고정된 후에만 변경한다.

## Review Focus

1. 같은 이름의 다른 HW/ISA/toolchain revision이 잘못 합쳐지는 경우: version-aware retrieval·검증이 unknown 또는 정확한 revision을 반환해야 한다.
2. private source의 ACL이 바뀌고 index가 뒤처지는 경우: snippet·graph hop·reranker input까지 즉시 차단해야 한다.
3. HAT/Melete 부분 실패·재전송·event 순서 뒤집힘: run identity와 기록이 중복·누락되지 않아야 한다.
4. Metric 누락·단위 차이·simulated vs measured 혼합: 비교 불가 상태가 우월 판정에 들어가지 않아야 한다.
5. 전체 flow 일부만 준비된 phase: mock 성공이나 문서만으로 phase acceptance를 통과시키지 않아야 한다.

---

## 1. 계획 단계 P0도 전체를 정교화한다

| P0 내부 단계 | 전체를 보는 수준 | 산출물과 완료 증거 |
|---|---|---|
| P0.A 개념 지도 | 전 영역과 사용자 요구·모호함 연결 | 요구-ID, glossary, 전체 흐름, 위험·가정 목록 |
| P0.B 근거 지도 | source·도구·infra·모델·검색 후보 비교 | source catalog, 공식 근거, category별 추천 점수, 조합 후보 |
| P0.C 계약 지도 | 데이터·권한·API·metric·failure·비용 경계 | schema, retrieval/validation, HAT/Melete mapping, infra setup runbook |
| P0.D 실행 지도 | 각 phase 전체의 구체 작업·test·review·승격 | phase×capability matrix, 파일/API ownership, 검증·rollback·운영 계획 |

P0.D의 종료는 문서의 형식 검사만으로 결정하지 않는다. 독립 builder check의 중요 질문을 해결하고, 사용자가 최종 설계·계획의 핵심 선택을 검토한 후 implementation phase를 시작한다. 현재 미정인 실제 월 예산·region·서비스 edition은 provisioning 전 확인 항목이며 무단으로 계정 설정하지 않는다.

## 2. Phase × 전체 capability

| 영역 | P1 작은 실제 전체 loop | P2 넓어진 전체 | P3 정밀한 전체 | P4 자율적인 전체 | P5 운영되는 전체 |
|---|---|---|---|---|---|
| Source/수집 | 모든 지식 영역의 허용 source 표본 | vendor·논문·version breadth | 수식·표·그림 정확도/충돌 처리 | coverage gap 기반 수집 제안 | 지속 갱신·철회·장기 보존 |
| Schema/metadata | 필수 envelope·Claim·run 계약 | ontology/asset 확장 | bitemporal·entity 충돌 정밀화 | Insight lifecycle 자동 감시 | migration·schema governance |
| Embedding/parsing | parser 1+대조군, dense 2종 비교 | 영역별 routing | multi-vector/late interaction 검증 | drift에 따른 재평가 제안 | shadow migration·비용 최적화 |
| Retrieval | exact+lexical+dense+작은 graph | cross-domain·version·multi-hop | rerank·coverage·contradiction 정밀화 | agent query planning budget | 규모별 SLA·cache/검색 품질 유지 |
| HW/committee | rack~component 전 계층 1개 이상 asset | 계층별 대안·연결 규약 확대 | formal/physical rule coverage | 제약 내 새 조합 제안 | asset lifecycle·외부 지식 갱신 |
| Kernel | 실제 fold/unfold·fusion 소수 후보 | shape/layout/ISA 범위 확대 | resource-aware joint search | 비용 제한 autonomous candidate search | 장기 regression·model 전환 |
| HAT 실행 | 신규 모델 등록·지원 확인·작은 실 workload | model family·B300 scenario 규모 확대 | fidelity/calibration 깊이 확대 | 여러 실험의 비동기 제어 | 지속 검증·capacity planning |
| Metric 비교 | 등록된 전 지표군과 missing 상태 | 분포·cohort·Pareto views | uncertainty·오차/quality gate | constraint-profile별 탐색 | drift·장기 추세·예산 관리 |
| Melete/경험 | 실제 최소 event ingest/조회 | 실패·변경·insight lineage 확대 | 반례·재현·scope 승격 | next proposal와 memory 환류 | retention·삭제·재학습 통제 |
| Infra/운영 | 작은 dev 배포·backup/restore | stage·queue·권한 분리 | scale/failure drill | run budget·cancel·kill switch | prod SLO·DR·비용/보안 운영 |
| 평가 | 전 영역 golden slice+한 바퀴 | domain coverage 확대 | ablation·held-out transfer | autonomous vs human/baseline | 지속 regression·incident 복기 |

P1에서 모든 성능 항목을 정확히 측정할 수 있다는 뜻은 아니다. metric registry와 비교 기능은 전체를 다루되, HAT가 제공하지 못한 값은 unsupported/missing으로 반환한다. 해당 값에 대한 우월함은 주장하지 않는다.

## 3. 미래 파일 구조와 공통 interface

제안 구현 root는 `<repository-root>`다. 현재 생성하지 않았다. 이름은 작업명이며 사용자의 naming 결정으로 변경할 수 있다.

| 미래 경로 | 책임 |
|---|---|
| `contracts/` | versioned record·API·event schemas와 fixtures |
| `services/intake/` | source registry, acquisition, parse, normalize |
| `services/knowledge/` | Claim/evidence ledger, publishing, outbox |
| `services/retrieval/` | policy filter, exact/lexical/dense/graph, evidence bundle |
| `services/validation/` | schema/unit/constraint validation과 coverage |
| `services/experiments/` | DesignPoint, proposal, run lifecycle, metric comparison |
| `adapters/hat/` | HAT schema/HATIR/RP contract mapping |
| `adapters/melete/` | Observation/IntakeContext/receipt mapping |
| `apps/review/` | 사람이 evidence·review·Pareto·trajectory를 살펴보는 기능 |
| `infra/` | 선택 cloud의 IaC·environment manifest·budget·backup 설정 |
| `evals/` | frozen golden sets, retrieval·decision·E2E·cost evaluation |
| `tests/contracts/`, `tests/integration/`, `tests/e2e/` | compatibility·partial failure·전체 흐름 검증 |

언어 기본 제안은 Python service와 typed schema, SQL canonical ledger다. Web UI stack은 P0의 UX 범위에 맞춰 별도 확정하며 기존 HAT plane UI를 재사용할 수 있으면 중복 앱을 만들지 않는다. API 계약은 UI framework에 의존하지 않는다.

| Interface | 정확한 논리 signature |
|---|---|
| register_source | `(SourceRegistration) -> SourceRegistrationReceipt` |
| capture_revision | `(SourceId, CapturePolicy) -> SourceRevisionReceipt` |
| publish_claims | `(ExtractionBatch, ReviewPolicy) -> PublishReceipt` |
| search_evidence | `(DecisionContext, QueryPlan) -> EvidenceBundle` |
| review_assembly | `(AssemblyReviewRequest) -> ReviewReport` |
| propose_recipes | `(KernelSearchRequest, SearchBudget) -> RecipeCandidateSet` |
| validate_candidate | `(DesignPoint, ValidationPolicy) -> ValidationReport` |
| submit_run | `(RunManifest, ExecutionBudget) -> RunHandle` |
| compare_runs | `(ComparisonCohort, MetricSelection) -> ComparisonReport` |
| record_experience | `(DSEEvent, AuthorizedIntakeContext) -> ExperienceReceipt` |
| propose_next | `(ExperimentContext, EvidenceBundle, SearchBudget) -> ExperimentProposalSet` |

위 type의 field는 [data-contracts.md](https://github.com/jimmylegendary/dse-knowledge/blob/main/docs/data-contracts.md)에 정의한다. Receipt/Report/Handle은 request ID·schema version·status·result reference·error/unknown list를 공통 envelope로 갖는다. P1 Task 1이 실제 serialization 및 service transport를 확정한다.

## 4. 모든 phase의 작업 방식

- [ ] `using-superpowers`로 적용 skill을 확인하고, 요구 변화가 있으면 `brainstorming`으로 기존 spec과 차이를 먼저 정리한다.
- [ ] `writing-plans`로 해당 phase의 승인된 범위·정확한 file ownership·interface·fixture·commands를 freeze한다.
- [ ] 구현 시작 때만 `using-git-worktrees`로 격리한다. 현재 문서 작업에서 product worktree를 만들지 않는다.
- [ ] `subagent-driven-development`로 독립 작업을 Luna/max 기본 worker에 위임한다. 기존 worker를 재사용하되 본인 산출물의 유일한 reviewer로 배정하지 않는다.
- [ ] 필요한 의미 검증에는 TDD를 적용한다. 구현을 그대로 따라하는 test나 저위험 문서 변경용 test는 만들지 않는다.
- [ ] `requesting-code-review`/`receiving-code-review`로 별도 spec·code 검토를 진행하고 근거로 수정한다.
- [ ] Master가 `verification-before-completion`으로 실제 command·출력·pass/fail·commit SHA를 확인한다.
- [ ] 전체 coverage matrix와 실패/unknown 목록을 업데이트한 뒤 승인 범위에서만 통합한다. Cloud 배포는 계획 검토·실제 계정/예산 확인 후 수행한다.
- [ ] 새 사실로 계획이 바뀌면 ADR/scorecard/phase task를 함께 갱신하고 이미 완료한 작업은 evidence를 확인해 재실행하지 않는다.

## 5. P1 — 작은 실제 전체 loop

대상: 허용 source 약 50–200문서(계획용 크기), 모든 지식 영역에서 최소 2개 독립 source family, rack/tray/package/SoC/component를 모두 표현한 하나의 기준 설계와 계층별 작은 대안. workload는 전체 semantics를 보존한 작은 session trace. 지식 양만 줄이고 데이터 계약을 생략하지 않는다.

### Task 1. 한 실험을 수용할 계약·infra·fixture

**Files:** 미래 `contracts/`, `infra/environments/dev/`, `tests/contracts/`, `evals/fixtures/minimal_episode/`.

**Interfaces:** 공통 record/API envelope를 생산한다. SourceRevision→DesignPoint→RunEvent→Melete receipt의 ID 연결을 소비/검증한다.

- [ ] 실패 fixture를 정의한다: 잘못된 단위, 누락 provenance, 다른 ISA revision, 권한 없는 evidence, unsupported metric.
- [ ] 계약 검증이 해당 fixture를 거부하는지 확인한다.
- [ ] 승인된 dev cloud profile에 최소 object/ledger/graph/job/secrets/observability를 설정하는 IaC를 작성한다.
- [ ] future plan/apply 리뷰에서 비용 estimate, IAM, region/edition, backup·delete·rollback 항목을 확인한 후 배포한다.
- [ ] dev backup 복원 및 secret/ACL deny smoke check를 수행한다.
- [ ] 계약/schema/IaC reviewer와 master 확인 후 commit한다.

**Acceptance:** 전 영역 record를 담은 fixture가 통과하고 5개 negative fixture가 각각 올바른 status로 실패한다. 배포 evidence는 config hash·실제 resource IDs·비용 profile·restore 결과다.

### Task 2. 수집부터 근거 검색까지 연결

**Files:** `services/intake/`, `services/knowledge/`, `services/retrieval/`, `tests/integration/test_evidence_roundtrip.py`.

**Interfaces:** register_source/capture_revision/publish_claims/search_evidence를 생산하고 Task 1 contracts를 소비한다.

- [ ] source URL→revision/hash/span→Claim→EvidenceBundle round-trip test를 먼저 작성한다.
- [ ] source catalog에서 권리 허용과 전 영역 coverage를 만족하는 표본을 선택한다.
- [ ] parser·embedding·graph projection을 연결하고 exact/lexical/dense 대조군을 만든다.
- [ ] 인용 span·version·unit·ACL·projection watermark를 검증한다.
- [ ] held-out query에서 추천 후보와 baseline의 recall·오인용·비용을 비교한다.
- [ ] 다른 worker 검토와 master command 확인 후 commit한다.

**Acceptance:** 최소 각 영역 10개 query의 evidence가 원문으로 역추적된다. critical negative case 오허용은 0건이어야 한다. 점수 기준은 [validation-and-governance.md](https://github.com/jimmylegendary/dse-knowledge/blob/main/docs/validation-and-governance.md)를 따른다.

### Task 3. HW·kernel·HAT·Melete 한 바퀴

**Files:** `services/validation/`, `services/experiments/`, `adapters/hat/`, `adapters/melete/`, `tests/e2e/test_minimal_dse_episode.py`.

**Interfaces:** review_assembly/propose_recipes/validate_candidate/submit_run/record_experience/propose_next. 기존 HAT·Melete 계약을 adapter에서 유지한다.

- [ ] 지식 시스템에 미등록된 supported model의 ModelVersion/config/tokenizer/chat-template·workload onboarding과 미지원 model/op negative fixture를 정의한다.
- [ ] 신규 모델 등록·HAT 지원 여부·context/timing 의미를 검증한 뒤 기준 설계와 불법 조합 fixture, fold/unfold와 fusion 후보 및 failure case를 정의한다.
- [ ] committee backend가 evidence tool을 조회하고 근거 ID를 남기는 경로를 검증한다.
- [ ] HATIR recipe resolve와 supported correctness 검사를 거쳐 실제 HAT 평가를 실행한다.
- [ ] metric vector의 실제 값·missing·fidelity와 baseline cohort 비교를 저장한다.
- [ ] Melete의 실제 최소 ingest/조회 왕복과 idempotent receipt를 검증한다.
- [ ] 분석·다음 실험 proposal을 생성하고 아직 실행되지 않은 상태로 기록한다.
- [ ] timeout·잘못된 recipe·중복 event·Melete 일시 장애를 주입해 재시도를 확인한다.
- [ ] spec/code reviewer와 master가 원자료를 확인한 뒤 commit한다.

**Acceptance:** 신규 ModelVersion onboarding부터 source와 next proposal까지 끊기지 않은 실제 episode 1개, 미지원 모델/연산 1개, 설계 reject 1개, 실행 실패 1개가 같은 계약으로 보존된다. 전체 단계가 stub이면 통과가 아니다. HAT 또는 Melete 실행 환경이 확보되지 않으면 이 task는 blocked이며 P1 완료로 표시하지 않는다.

### Task 4. 인간과 agent가 보는 동일 결과

**Files:** `apps/review/` 또는 승인된 기존 HAT plane UI extension, `tests/e2e/test_review_flow.py`, phase evidence report.

- [ ] source citation, 검토 finding, metric 표/분포, Pareto 후보, trajectory의 사용자 흐름을 정의한다.
- [ ] 같은 backend 계약을 쓰는 최소 화면/CLI를 연결한다.
- [ ] 사람이 근거 원문·실패·다음 proposal까지 이동할 수 있는지 확인한다.
- [ ] P1 matrix 전 행에 실제 evidence를 연결하고 남은 unsupported capability를 명시한다.

후속 단계의 파일·입출력·acceptance·검증 command별 세부 패키지는 [phase-work-packages.md](https://github.com/jimmylegendary/dse-knowledge/blob/main/docs/phase-work-packages.md)에 정의한다. 새로운 설계 결정을 구현 중 임의로 추가하기 위한 문서가 아니라 이 계획의 일부다.

## 6. P2 — 전체의 폭 확대

**Files:** 기존 모든 service의 registry/adapter 확장, `evals/datasets/p2/`, stage infra, `tests/e2e/test_cross_domain_episode.py`.

**Inputs/Outputs:** P1 interfaces는 유지한다. 여러 model/workload/vendor/ISA/source revision을 지원하는 registry와 run cohort를 생산한다.

- [ ] source 표본을 계획상 1,000–10,000문서 범위로 넓히며 분야별 coverage·권리·freshness gate를 유지한다.
- [ ] rack/tray/package/SoC/component 각 계층의 대안과 조합 제약을 최소 3개 사례로 확장한다.
- [ ] kernel shape/layout/dtype 범위를 확장하고 fold/unfold·fusion legal/illegal 쌍을 늘린다.
- [ ] 사용자 예시 1,000 session의 timing·context 정책을 명시해 HAT scenario로 검증한다.
- [ ] cohort·분포·Pareto·Melete failure/insight 조회를 확대한다.
- [ ] stage 환경, event queue, permission revocation, retry/reindex를 연결한다.
- [ ] 전 영역 held-out case를 늘리고 human·lexical baseline 대비 실제 판단 개선을 측정한다.

**Verification:** 전체 integration/contract/e2e 평가와 index rebuild·ACL revocation test. 이전 P1 golden episode도 재실행한다. 새로운 변경·문제가 없으면 불필요한 반복 test를 늘리지 않는다.

**Promotion:** broad corpus 수 자체가 아니라 영역별 retrieval/decision coverage와 HAT/Melete round-trip가 통과해야 한다.

## 7. P3 — 전체의 정밀도 확대

**Files:** 수식·표 parser adapters, constraint rules, retrieval reranking, cost/calibration models, experiment search adapters, `evals/datasets/p3/`.

- [ ] 표·수식·그림·code의 extraction error를 정량화하고 source-span 검토 경로를 강화한다.
- [ ] 정확 조회+graph+reranker ablation과 embedding shadow migration을 실행한다.
- [ ] hardware physical rule coverage와 kernel semantic 검증 범위를 확장한다.
- [ ] 이전 RP state의 진단 활용과 변경 후보의 새 replay를 분리해 검증한다.
- [ ] random/enumeration, conditional sampler, BO/evolution, KG-guided 제안을 같은 budget에서 비교한다.
- [ ] calibrated baseline을 확보 가능한 실측과 비교하고, 새로운 HW에는 extrapolation uncertainty를 표시한다.
- [ ] Melete Insight의 반례·재현·supersession과 downstream 재검토를 실행한다.
- [ ] latency/cost/projection freshness와 restore 목표를 phase 규모에서 다시 검증한다.

**Promotion:** 기존 전체 loop를 유지한 채 source·version·unit 정확도와 실제 실험 선택 효율이 개선돼야 한다. 실측 자원이 없으면 simulated exploration은 계속할 수 있지만 real-hardware superiority gate는 닫힌 상태로 남긴다.

## 8. P4 — 전체의 제한된 자율성 확대

**Files:** agent tool/controller policies, experiment budget scheduler, insight review/promotion workflow, autonomous eval suite.

- [ ] user가 설정한 execution budget과 allowed action policy를 fixture로 고정한다.
- [ ] agent가 source gap→검색→검토→recipe→실험→분석→다음 proposal을 예산 안에서 반복한다.
- [ ] 같은 run/asset을 병렬 worker가 수정하지 않도록 lease와 idempotency를 검증한다.
- [ ] cost/시간/실패율 stop condition, cancel propagation, kill switch, dead-letter recovery를 시험한다.
- [ ] false insight·잘못된 citation·unknown constraint를 주입해 자율 controller의 중단/추가 검증을 확인한다.
- [ ] human-guided·random/optimizer-only·KG 없는 agent·전체 agent를 같은 scenario budget에서 비교한다.
- [ ] 자동 수집·자동 insight 승격은 별도 policy를 만족하는 경우에만 수행한다.

**Promotion:** 실험 수 증가 자체가 아니라 invalid run 감소, 재현성, budget 준수, evidence-backed frontier 개선 또는 정보 획득을 입증한다.

## 9. P5 — 전체의 운영 규모 확대

**Files:** prod infra, SLO/DR runbooks, lifecycle/migration tooling, continuous evaluation schedules, cost dashboards.

- [ ] source 변경·철회·권한 회수에서 canonical/index/Melete/cache까지 전파를 검증한다.
- [ ] scale envelope별 처리량·지연·비용·embedding drift를 측정하고 임계값에 따라 확장한다.
- [ ] backup/restore, region 장애, queue backlog, stale graph, provider outage를 연습한다.
- [ ] 신규 model·ISA·hardware·metric을 기존 실험 재현성을 유지하며 추가한다.
- [ ] 실험·Insight의 장기 보존·삭제·export와 open format 복구를 검증한다.
- [ ] 운영 incident도 동일 trajectory/evidence로 기록하고 규칙·추천 점수를 갱신한다.

**Promotion:** 설정한 prod SLO와 cost ceiling에서 전 영역 correctness가 유지되는 경우만 운영 완료로 본다.

## 10. 실행 command와 evidence 형식

다음은 미래 구현에서 만들 검사 interface의 계획이며 현재 실행 가능한 제품 command로 보고하지 않는다.

- `pytest tests/contracts -q`: schema/version/ACL/unit/enum 호환 결과.
- `pytest tests/integration -q`: ingestion/index/validator/adapter failure와 idempotency 결과.
- `pytest tests/e2e -q -m phase_pN`: 해당 phase 전체 episode와 회귀 결과.
- `python -m evals.run --manifest <frozen-manifest>`: query/decision/DSE/cost 지표 및 bootstrap interval.
- 선택 IaC의 plan command: 실제 변경 목록과 비용 입력, apply 전 review artifact.

각 phase evidence: exact command, stdout/stderr artifact hash, pass/fail/skip 이유, git commit SHA, tool/model/schema/KB snapshot, source licenses, infra manifest, cost 측정·추정 구분, reviewer findings와 처리, 전체 capability matrix. 테스트 수를 계획값과 실제값으로 분리한다.

## 11. 일정·의존성

달력 일정은 팀 규모·실측 자원·서비스 edition이 없으므로 확정하지 않는다. Critical path는 권리 확인→schema/golden fixture→source/knowledge pipeline→HAT/Melete adapter→실제 end-to-end→calibration→자율 budget control이다. Source 조사·infra 설계·모델 평가 준비는 독립 문서/fixture 범위에서 병렬화할 수 있다.

범위 확대는 phase를 feature silo로 쪼개는 방식이 아니라 전체 loop의 corpus·asset·query·metric·automation envelope를 조정한다. Budget이 작으면 소규모 전체 loop를 유지하고 rollout을 늦춘다.
