# DSE 의사결정 지식 시스템 상위 아키텍처

작성일 2026-10-21 · 상태: architecture/planning 기준, 기술 선택과 구현 전

이 문서는 2026-10-18 사용자 정정을 반영한 상위 architecture 기준이다. 목적은 특정 HAT episode나 native adapter 준비가 아니라, DSE 결정에 필요한 지식을 식별하고 근거를 모아 실제 설계·실험 결정에 쓰고 부족한 지식을 다시 얻는 시스템을 정의하는 것이다. 기존 [system design](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/superpowers/specs/2026-10-16-dse-knowledge-system-design.md), [data contracts](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/data-contracts.md), [retrieval and decision](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/retrieval-and-decision.md), [source catalog](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/research/01-source-catalog.md), [phase packages](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/phase-work-packages.md)을 연결하고, 아직 없는 `DecisionTask → KnowledgeRequirement → CollectionPlan` 연속체를 제안한다.

최종 DB, retrieval·parser·model 제품 선택은 보류한다. 아래의 storage와 model 조합은 구현 후보의 경계와 trade-off이지 선택 결과가 아니다. source catalog는 수집 후보와 계획이며, raw detailed standards를 수집·보관한 corpus는 아직 없다. 기존 native HAT/Melete 계약은 구체적인 하위 참조 자료이고 이 문서의 중심이 아니다.

## 1. 목적과 사용자 요구

| 누가 / 무엇을 하려는가 | 시스템이 보장할 결과 |
|---|---|
| DSE 설계자: model·workload·hardware·kernel 후보 비교 | 목표와 제약별로 어떤 지식·근거가 필요한지 드러나고, 미충족 조건은 `unknown`과 함께 반환 |
| architecture·kernel reviewer: 자산 조립과 recipe 검토 | versioned interface, capability, scope, 단위, 근거를 따라 합법성·미지원 항목을 검토 |
| experiment owner: 후보의 실제 영향 분석 | 재현 가능한 scenario·intervention·환경·metric vector·실패를 보존하고, 알려진 제약 위반과 성능 열세를 분리 |
| agent/automation: 관련 지식 검색·수집·다음 실험 제안 | task별 knowledge gap을 찾고 허용된 source/근거를 제시하되 사실·권한·실험 승인은 만들어내지 않음 |
| maintainer: 지식과 source 갱신 | revision, rights, ACL, parser/model version, stale/retracted Claim과 그 영향을 downstream까지 추적 |

핵심 동작은 한 번의 답변이 아니라 아래 반복이다.

`결정 task → 필요한 지식 명세 → 현재 coverage 확인 → 수집 또는 실험 계획 → 허용된 취득/구조화 → 검증·결정 → 결과/Insight 기록 → 미충족 지식 재수집`

요청·turn·model call·tool call·실행·결과·시각·실패·retry 등 외부에서 관찰 가능한 event를 기록한다. 숨겨진 chain-of-thought는 대상이 아니다. metric은 단위·scope·시간 경계·집계·불확실성을 보존한 vector로 남기고 선호 점수로 미리 축약하지 않는다.

## 2. 결정 영역, 필요한 지식, source 경로

| DSE 영역 | 대표 결정 | 필요한 지식과 근거 | source·확인 경로 |
|---|---|---|---|
| Workload·model·serving | 어떤 session/scenario를 비교 기준으로 삼을지 | model/tokenizer/chat-template, session/turn·arrival·tool wait·cache semantics, quality/SLO, seed와 warm/cold 조건 | model cards·serving/compiler 공식 문서, 허가된 externally observable trace, MLCommons 및 공개 workload/eval 자료. trace provenance·license 확인 |
| HW asset 조립 | rack/tray/package/die/SoC/component가 결합 가능한지 | identity/revision, containment·port·protocol, topology, capacity, power/thermal, physical assumptions, hard constraint | vendor public manuals/datasheets, 공개 system/board records, IEEE/OCP/UCIe/CXL/JEDEC scope/edition 및 권리 승인된 세부 조항, 이후 승인된 측정 |
| ISA·programming model·compiler | 어떤 operation/dtype/layout/shape가 지원되는지 | semantic contract, memory/synchronization, lowering·code path, version과 unsupported scope | ISA/compiler/MLIR/Triton 공식 문서·소스·tests, versioned config/AST/code span, 해당 HAT/adapter contract |
| kernel/recipe·physical mapping | fold/unfold/fusion/tiling 후보가 semantics·resource 한계를 만족하는지 | op DAG, recipe transforms, correctness cases, resource/cost-model coverage, applicability | recipe/source artifact, compiler output, simulation/measurement evidence, calibration domain; prediction과 measured result는 별도 |
| simulation·circuit·system model | 모델을 어느 범위까지 설명 또는 보정에 쓸지 | equations/parameters, node/package/thermal/network assumptions, calibration residual과 fidelity | 공개 simulator/research/model source 및 허가된 experiment. 문서의 주장·모델 출력·실측을 다른 epistemic class로 분리 |
| 실험·결과·재설계 | 성능·품질·비용 trade-off와 다음 검증은 무엇인지 | frozen cohort, intervention, all metric vectors, uncertainty, failure taxonomy, independent lineage, unresolved hypothesis | authorized RunManifest/Event/Artifact/MetricValue, reproducible replay/measurement, scoped prior Insight와 반례 |

표의 source 범주는 조사 계획이다. 공개 페이지라는 사실은 원문 전체 취득·색인·재배포 권리를 뜻하지 않는다. source 발견, rights/access 검토, 취득, 파싱은 서로 다른 상태다. source별 세부 조항·수치 표를 아직 수집하지 않았다.

## 3. 논리 object와 relationship 후보

`Existing`은 기존 문서에 이미 있는 논리 계약명이며 운영 시스템에 구현됐다는 뜻은 아니다. `Proposed`는 이 architecture에서 명시화할 보완 객체다.

| Object | 상태 | 핵심 역할과 metadata |
|---|---|---|
| `DecisionTask` / `DecisionContext` | Context는 existing, durable Task wrapper는 proposed | task ID/revision, question, target candidates, constraints, requester/namespace, allowed source classes, deadline/budget, policy·knowledge snapshot, final decision record |
| `KnowledgeRequirement` | **Proposed central object** | 요구할 claim/path/value type, target scope·version, unit/measurement boundary, authority·freshness, minimum independent evidence, validation rule, blocking level, satisfaction predicate, resolution path, evidence links, status/reason |
| `CollectionPlan` / `AcquisitionAttempt` | **Proposed** | requirement refs, candidate source families/revisions, rights state, query/extraction plan, expected artifact/evidence, owner/cost/refresh trigger; attempted/blocked/acquired outcome를 계획과 분리 |
| `SourceRegistration`, `SourceRevision`, `SourceSpan`, `Artifact` | Existing | publisher/family/canonical URL/authority/rights, upstream revision/hash, raw artifact, exact page/section/table/figure/code locator |
| `ExtractionRun`, `DocumentElement`, `Chunk`, `EmbeddingRecord` | Existing | parser/OCR/model/config version, reading order·table header·footnote·equation/code span, parent-child segmentation과 derived-index identity |
| `DomainEntity`, `Claim`, `EvidenceLink`, `ClaimConflict` | Existing | canonical identity/alias, typed statement와 claim kind/scope/applicability/epistemic state, source span, supports/refutes/qualifies 및 conflict resolution |
| `ConstraintRule`, `ValidationResult` | Existing | 제한된 typed expression·unit·applicability; pass/fail/unknown/not_applicable/error와 coverage·proof/counterexample |
| `HardwareAssetVersion`, `InterfacePort`, `HardwareAssembly`, `Capability`, `ProgrammingModelVersion` | Existing | versioned asset tree와 instance/port binding, containment DAG, connection graph, supported operations/resources, semantic rules |
| `KernelRecipeVersion`, `CorrectnessAssessment`, `CostModelVersion` | Existing | semantic input/op DAG/transforms/target, correctness scope, model domain/calibration/uncertainty |
| `ModelVersion`, `WorkloadScenario`, `DesignPoint`, `ExperimentProposal` | Existing | tokenization·quality, timing/session semantics, pinned assembly+recipe+serving config, hypothesis/intervention/expected metrics/information gain/cost/stop condition |
| `RunManifest`, `RunEvent`, `MetricDefinition`, `MetricValue`, `Artifact` | Existing | immutable run inputs, ordered/idempotent event/error chain, metric vector definitions and actual/missing values with scope, method, fidelity, sample/uncertainty |
| `EvidenceBundle`, `ReviewFinding`, `DecisionRecord` | Bundle/finding existing; durable decision record is proposed linkage | query/snapshot/filters/cited claims/spans/conflicts/coverage; review and deterministic validation refs; decision outcome, assumptions, unresolved requirements, allowed claims |
| `InsightVersion` / `ExperienceReceipt` | Melete bridge exists; DSE canonical InsightVersion is proposed | derived-from run/evidence, applicability, independent lineage, candidate/reviewed/supported/contested/superseded state; external Melete ID/version/receipt kept as adapter mapping |

모든 relationship는 plain triple로 끝내지 않고 `edge_type/version`, source/Claim/Evidence refs, target scope·revision, validity/recorded time, ACL, method/evaluator와 confidence dimensions를 가진다. 핵심 edge 예시는 `requires`(Task→Requirement), `covered_by`(Requirement→Claim/Evidence), `planned_by`/`attempts`(Requirement→CollectionPlan/Attempt), `derived_from`/`asserted_by`, `supports/refutes/qualifies`, `contains`/`connected_to`/`constrains`, `implements`/`targets`, `evaluates`/`produces`, `satisfies/refutes`(result→Requirement), `informs_next`(Insight→Task/Proposal)다. Identity, scope, unit, time, rights가 다른 관계를 하나의 untyped edge로 합치지 않는다.

`KnowledgeRequirement` 상태는 예를 들어 `uncovered → plan_pending → acquiring → candidate_evidence → review_required → satisfied`로 가고, 다른 말단은 `partial / conflicted / blocked / unknown / stale`이다. `satisfied`는 required evidence predicate와 coverage가 통과해야 하며 LLM 요약·vector score·단순 source 존재로 결정하지 않는다. `CollectionPlan`은 표준 취득, vendor 문서 조회, 코드 추출, 인간 질의, 추가 실험 등 다른 resolution path를 한 모델로 추적한다.

## 4. 저장·수집·모델 조합 후보

| 조합 패턴 | 역할 분리 | 장점 | 설계 검토점 |
|---|---|---|---|
| Versioned canonical ledger + immutable artifact store + graph/lexical/vector projections | ledger가 typed object와 transaction authority, artifact store가 원문·run bytes, projections는 재생성 가능 read model | 권한·revision·transaction 경계를 명확히 하고 retrieval 방식을 교체 가능 | outbox/sequence watermark, projection lag·delete propagation, cross-store closure |
| Graph-centered canonical knowledge + 별도 run/metric ledger + artifact store | entity/claim/constraint 관계는 graph, high-volume event/metric은 ledger/table, 원문은 artifact | 다단계 asset/claim path에 자연스러운 모델 | graph와 실험 상태의 authority 경계, event ordering·joins·migration |
| Append-only source/experiment event ledger + materialized current-state views + artifact store | immutable changes/events가 authority, current claims/requirements/graph/index는 replayable state/projection | lineage, as-of re-evaluation, correction/retraction에 적합 | replay determinism, compaction, ACL/retraction과 오래된 projection invalidation |

현재 dev baseline과 이후 scale 대안을 구분한다.

| 경계 | 현재 dev baseline | 제외·미결 사항 |
|---|---|---|
| DB/data layer | 기존 Supabase account를 사용하도록 기준화 | 계정 조회·연결·구성은 하지 않음; 최종 production layout/scale 비교는 남음 |
| Host/compute | 현재 Linux host의 CPU | GPU는 필수가 아니며 현재 GPU 자원을 요청·확보하지 않음 |
| Artifact | 현재 local artifact store | managed cloud object storage는 scale/운영 근거가 생긴 뒤 선택할 미래 대안이며 초기 필수 dependency가 아님 |
| Model/provider | OpenRouter 또는 Codex를 provider interface 뒤에서 선택하고 environment 설정으로 바꿀 수 있게 준비 | provider/model은 확정하지 않음; API key를 요청·발급·전달하지 않음 |
| Cloud policy | 이번 dev baseline에는 신규 cloud resource 불필요 | AWS 사용 금지 |

이 baseline은 준비 방향이지 계정에 접속하거나 서비스를 배포했다는 뜻이 아니다. 넓은 storage/processing 후보 표는 이후 규모·권리·운영 요구로 재비교할 대안이다. 별도로 parser/OCR, deterministic AST/table extraction, LLM claim-candidate extraction, exact/lexical/dense/graph retrieval, reranker, deterministic validator, reviewer/committee, experiment analytics를 단계별 조합 후보로 둔다. LLM은 claim/requirement/query plan 후보를 만들 수 있지만 claim acceptance·unit arithmetic·coverage·권한·실행 permission은 담당하지 않는다. Retrieval과 DSE search는 다른 평가 대상이다. 최종 production DB, parser, model, embedding/reranker, cloud 조합과 비용은 별도 기술 선택이며 본 문서는 vendor winner를 정하지 않는다.

## 5. 전체 write pipeline과 knowledge-gap 폐루프

| 순서 | Write 단계 | 고정 산출물과 통과 조건 |
|---|---|---|
| 1 | `DecisionTask` intake | 목표·target·scope·제약·budget·권한·snapshot을 고정하고 unknown input을 표시 |
| 2 | Requirement decomposition | task를 requirement DAG로 나누고 each의 acceptance predicate, blocker, claim/path types, unit/version/source criteria를 고정 |
| 3 | Coverage probe & collection plan | canonical ledger를 먼저 확인; 부족·충돌·stale·unauthorized 이유를 구분하고 source/measurement/analysis plan을 작성 |
| 4 | Rights-gated acquisition | source authority/license/access 확인 뒤에만 fetch; immutable SourceRevision, hash, source span/artifact, refresh/retraction event 생성 |
| 5 | Parse & structure | deterministic parser/OCR/AST + optional extraction model; table header/unit/footnote, equation/code, hierarchy/reading order를 구조화; ExtractionRun provenance 저장 |
| 6 | Claim/evidence review | entity resolution은 후보/ambiguity 보존; Claim·EvidenceLink·Conflict candidate 생성; exact span, method, reviewer, applicability 기록; synthetic/OCR ambiguity는 publish gate 전 review |
| 7 | Validate & decide | required coverage를 top-k와 분리해 deterministic validator 실행; human/agent ReviewFinding은 cited evidence와 함께 기록; DecisionRecord에 pass/fail/unknown/assumptions/out-of-scope 저장 |
| 8 | Propose and execute | legal candidate에서 ExperimentProposal 및 stop/cost plan; 별도 authorization 후 immutable RunManifest/Event/Artifact·실패/retry 기록 |
| 9 | Analyze & update | MetricValue vector·cohort·uncertainty를 비교; RunEvent/InsightVersion과 EvidenceLink 생성; 독립 검증·반례 상태에 따라 claim/insight를 유지·승격·contest/supersede |
| 10 | Recollect | 미충족/stale/conflicted requirement를 영향도·결정 blocking·정보가치·취득권리·예상 비용별로 재계획; 새 source/실험 결과를 다음 task revision에 연결 |

모든 입력에 raw provenance, actor/authority, schema·parser·evaluator version, idempotency/lineage, current ACL/retention 상태를 남긴다. Source update·new design scope·failed validator·측정 부족·반례·model/calibration drift는 gap을 다시 여는 trigger다. old DecisionRecord/RunMetric은 덮어쓰지 않는다. 동일 원문의 재수집·Melete 재유입·동일 run의 재분석은 독립 근거 수를 늘리지 않는다.

## 6. 질의 유형별 read·graph·retrieval·decision

각 요청은 권한·snapshot을 먼저 고정하고 `DecisionTask`에서 typed `QueryPlan`과 knowledge requirements를 만든다. 정확 조회와 narrative retrieval은 분리한다. Required validation 집합은 canonical ledger의 전체 applicable rule/input coverage를 사용하며 top-k·reranker·context limit으로 자르지 않는다. lexical/dense/graph 후보는 병렬로 모으고 provenance, contradiction, ACL, applicability를 다시 확인한다.

| 질문 유형 | 우선 read 경로 | 결정/응답 |
|---|---|---|
| 정확한 spec/value/version | entity+revision/metric registry exact lookup → SourceSpan·unit·authority | 답+정확한 span 또는 `unknown`; 유사한 version으로 대체하지 않음 |
| HW assembly legality/capacity | full containment/port/capability path → applicable typed constraint graph | validator coverage + ReviewFinding; invalid/missing/unknown을 분리 |
| kernel/recipe 선택 | ISA/programming semantics+target capability exact lookup → recipe/code/test evidence → scoped prior runs | correctness·unsupported semantics 검토 후 후보/experiment proposal; 유사 recipe가 적법성 증명은 아님 |
| multi-hop 영향 경로 | typed graph traversal→각 edge/Claim의 supporting span retrieval | 영향 경로를 보여주되 `connected_to`만으로 causality 생성 금지 |
| 결과 회귀/후보 비교 | 같은 scenario/model/quality/timing/system boundary·metric definitions로 Run cohort 구성 → full MetricVector/policy compare | hard constraint/metric missing/uncertainty/Pareto 별도; single score로 강제 축약 금지 |
| 과거 실패·Insight 질문 | event/experiment lineage + applicability/scope/independence filter → source/evidence drill-down | 현재 task에 대한 유사도와 적용 차이를 나누고, 반례·재현 없으면 prior/hypothesis로 표시 |
| 열린 research/어떤 지식이 부족한가 | source family 탐색 + community summary/lexical/dense/graph + broad-to-narrow source drill | 답/요약에 각 Claim 근거와 “추가로 필요한 자료”를 분리; unresolved 항목은 CollectionPlan 생성 |

성공한 지식 답변은 `decision/analysis + EvidenceBundle + requirement coverage`를 함께 반환한다. Coverage가 낮거나 source rights/schema가 unresolved이면 답을 강제로 채우지 않고 해당 requirement, 이유, 다음 취득/실험 제안을 반환한다.

## 7. HAT·Melete 책임과 권한

| System boundary | 이 architecture에서 맡는 역할 | canonical authority가 아닌 것 |
|---|---|---|
| HAT/HATIR adapter | versioned asset/recipe/context를 기존 HAT 계약에 맞게 전달하고, native request/result, fold/unfold/fusion status, fidelity·run provenance를 연결 | KG 전체 knowledge authority, arbitrary target legality의 증명, raw experiment data를 대신하는 summary |
| Melete adapter | 외부 관찰 가능한 DSE event/Experience를 허용된 payload로 보내고 receipt·memory ID/version을 연결; Insight 조회를 candidate retrieval로 제공 | Claim truth, applicability, source authorization, independent replication 판정 |
| Canonical DSE ledger | Claim/Requirement/Decision/Run/Metric/Insight ID·scope·revision·rights·lineage·validation state의 최종 authority | 외부 native object 의미를 추측하거나 adapter receipt만으로 status를 승격 |

Adapter는 versioned contract에 격리한다. 기존 [HAT fidelity contract](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/hat-fidelity.md), [Melete applicability mapping](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/melete-state-and-applicability.md), [snapshot contract](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/snapshot-contract.md)은 상세 참조로 유지한다. Native readiness·receipt·검색 순위는 정답 승인, 완전한 review, physical feasibility를 대신하지 않는다.

## 8. 설계 상세도 D1–D5와 전체 흐름 유지

D1–D5는 architecture 설계 상세도 단계이며 기존 구현 phase P1–P5와 다른 축이다. [2026-10-21-knowledge-architecture-plan.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/superpowers/plans/2026-10-21-knowledge-architecture-plan.md)가 각 산출물·의존성·검토 순서를 관리한다. 모든 D phase는 knowledge requirement → source → 저장/모델 → write → read/판단 → 실험/경험/지식 부족의 전체 결정 흐름을 포함하고, 해상도만 높인다.

| 설계 phase | 지식·source | DB/model·schema | Write/read·workflow | Infra·계획 | 완료 증거 |
|---|---|---|---|---|---|
| D1 전체 지도 | 모든 DSE 결정, 필요한 지식 종류와 대표 source | 구성 계층·핵심 객체·후보 모델 역할 | 전체 순환과 agent/HAT/Melete 경계 | 기존 Supabase·Linux host·비밀 아닌 입력 | 모든 영역이 같은 전체 지도에 연결된 표 |
| D2 후보 비교 | 세부 requirement와 source authority·coverage·수집 우선순위 | 역할별 제품·모델·조합 비교 | 추출·검색·graph·수치 분석의 대안 | Supabase edition·host 용량·API/운영 비용 비교 | 근거 있는 추천 순위와 탈락·전환 조건 |
| D3 논리 설계 | 수집 필드·갱신·conflict·충족 조건 | entity·관계·metadata·version·scope | 상태 전이·질의 유형별 QueryPlan·근거/미충족 반환 | 서비스 경계·접근·보존·복구 | 결정→요구→source→schema→read/write 추적표 |
| D4 상세 설계 | source별 connector/parser·chunking·표/수식/code 처리 | 테이블·index·projection·embedding space·모델 설정 | 증분 갱신·중복·재시도·권한·재검색·평가 절차 | sizing·배포 구성·credential scope·비용 산식 | 구현자가 추가 architecture 추측 없이 설명 가능한 명세 |
| D5 실행 계획 | 초기 수집 범위·우선순위·지속 갱신 | 확정 선택·대안·교체·migration 조건 | 작업별 입출력·파일 범위·의존성·검증 | 설정 순서·담당·예산·운영·rollback | 검토 가능한 구현 backlog와 준비 상태표 |

현재 D1 전체 architecture 초안은 작성·게시됐다. D2–D5는 미완료다. 위의 Supabase·Linux CPU·local artifact·provider-interface 설정은 dev baseline이며, production scale의 API·DB·model 조합 비교와 선택은 남아 있다. 어떤 phase도 detailed coverage를 hardware, retrieval, HAT, Melete 또는 운영 한 영역만으로 대체하지 않는다.

## 9. 남은 기술 결정

schema registry mechanism, final production DB/storage layout, parser·extraction/reviewer models, retrieval model·ranker, cloud/network boundary, source collection priority, Melete/HAT adapter release order는 별도 ADR/evaluation set에서 결정한다. 후보는 같은 requirements·rights·gold questions·change/retraction scenarios로 비교하고, 평가 전에 선택 조건을 고정한다. 아직 수집하지 않은 standards나 측정하지 않은 experiment 값은 계획 또는 hypothesis 상태로 남긴다.
