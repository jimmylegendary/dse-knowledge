# 검색·판단·실험 탐색 설계

상태: 구현 전 설계. 설정값은 최초 비교 실험을 위한 제안이며 성능 측정값이 아니다. 기술별 후보와 근거는 [02-storage-retrieval.md](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/02-storage-retrieval.md), [04-models-ingestion-evaluation.md](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/04-models-ingestion-evaluation.md)를 함께 읽는다.

## 1. 검색 문제를 나누는 기준

| 질의 | 우선 경로 | 결과가 되어서는 안 되는 것 |
|---|---|---|
| 특정 ISA revision의 지원 dtype/shape | version-aware exact lookup + 원문 | 비슷한 제품 설명으로 보완한 숫자 |
| 자산 A와 B의 조합 가능성 | entity/port binding + constraint expansion + validator | 가까운 vector 결과만 보고 approve |
| 긴 문서에서 관련 방법 탐색 | lexical+dense + rerank + 원문 위치 | 요약만 있고 출처 위치 없음 |
| 여러 계층의 영향 경로 | typed graph traversal + evidence retrieval | 관계가 있다는 이유로 causal claim 생성 |
| 이전 실패와 비슷한 상황 | scoped experiment + Melete + applicability filter | 다른 workload 경험을 무조건 재사용 |
| 연구 지형·설계 대안 개괄 | community/global summary + source drill-down | summary를 physical fact의 최종 근거로 사용 |

## 2. 최초 hybrid pipeline

1. **권한·snapshot 고정:** requester의 namespace/ACL과 공개 가능한 source만 선택한다. Query cache key에 권한·snapshot·model version을 포함한다.
2. **질의 구조화:** task, entity, HW scope, ISA/toolchain version, required claim type, numerical vs exploratory intent를 추출한다. structured input을 우선하고 LLM routing은 제안으로 검증한다.
3. **Entity resolution:** canonical ID와 alias를 찾는다. ambiguity가 남으면 후보를 분리한 채 반환한다. B300의 이름 유사성을 다른 제품 수치의 동치 근거로 사용하지 않는다.
4. **정확 조회:** binding된 entity·version의 규격·constraint·measurement를 조회한다. critical constraints는 retrieval top-k로 탈락시키지 않는다.
5. **병렬 후보 수집:** 최초 비교 설정은 lexical top-40, dense top-40, scoped graph seed top-20이다. 이 수는 recall/latency sweep의 출발점이다.
6. **Graph 확장:** typed relation과 applicability를 따라 evidence-bearing Claim을 찾는다. hierarchy 조회는 필요한 전체 계층을 명시적으로 traverse한다. 일반 탐색은 기본 depth 3, 최대 6, expanded node 200과 비용 budget을 두며, 잘린 경로는 truncation으로 보고한다.
7. **Rank fusion:** lexical·dense·graph 순위를 RRF(k=60 시작값)로 병합한다. raw similarity score를 서로 같은 척도로 가정하지 않는다. exact matching은 별도 우선 그룹으로 유지한다.
8. **중복·다양성:** 같은 source를 재인용한 후보를 lineage 기준으로 묶고, conflicting/alternative evidence를 한 개 요약으로 합치지 않는다.
9. **Rerank:** 상위 60개 후보를 DSE evidence relevance 기준으로 재평가하고 최대 12개 evidence item을 초기 bundle에 넣는다. 길이·표·code 처리와 비용을 함께 측정한다.
10. **Coverage·충돌 확인:** 요청된 판단 항목과 evidence mapping을 대조한다. 누락된 핵심 항목은 2회 이내 query expansion/parent retrieval을 수행한다. query rewriting은 entity와 version을 바꾸지 않는다.
11. **출력 검증:** Claim과 인용 span의 의미·수치·단위를 검사하고 conflict/unknown을 표시한다. 모델 답변보다 evidence bundle을 먼저 구조화한다.
12. **기록:** retriever/reranker/model versions, top-k, filter, query expansion, 선택 evidence, latency/token/cost, denied/stale 결과를 audit한다. 민감 원문을 관찰 로그에 중복 저장하지 않는다.

초기 interactive 목표는 retrieval-only p95 3초, 확장된 evidence bundle p95 10초다. 생성 모델 지연은 별도로 기록한다. 이 목표는 corpus 규모별 실측으로 조정하며 초과하면 silent truncation 대신 결과의 completeness를 반환한다.

## 3. 검색 실패와 fallback

Strict version/ACL filter에서 결과가 없다고 필터를 자동 해제하지 않는다. 범위 밖 참고 자료는 사용자가/agent policy가 허용한 경우 별도 section으로 제공하며 validation 근거로 승격하지 않는다.

Graph unavailable 시 lexical+dense fallback은 가능하지만 graph-dependent completeness를 false로 표시한다. vector index migration 중에는 old/new spaces를 각각 검색하고 결과 순위를 합칠 수 있으나 vector 자체를 혼합하지 않는다. stale projection에서 hard constraint 검증은 canonical ledger를 읽거나 unknown으로 중단한다.

권한이 없는 문서의 제목, graph degree, result count, snippet이 노출되지 않도록 filter-before-retrieval이 가능한 경로를 우선한다. backend가 이를 보장하지 못하면 namespace 분리 index를 사용한다. public/private가 섞인 summary에도 동일한 제약을 적용한다. Graph hop, cache hit, snippet 반환, 외부 reranker 전송 직전에 authoritative authorization_epoch를 재확인한다. epoch가 오래됐거나 권한 authority를 조회할 수 없으면 해당 자료를 fail-closed 처리한다. Index의 ACL metadata만 신뢰하지 않는다.

## 4. Agent tool 계약

아래는 신규 service의 제안 API 이름이며 현재 callable tool 목록이 아니다.

| Interface | 입력 | 출력 |
|---|---|---|
| search_evidence | DecisionContext, query, budget | EvidenceBundle |
| get_source_span | authorized source revision/span IDs | 위치가 고정된 원문·권리 metadata |
| get_asset_contract | asset version + target composition | ports/parameters/constraints/capability |
| validate_candidate | DesignPoint + evidence snapshot | ValidationResult + missing coverage |
| compare_runs | cohort + selected metrics + uncertainty policy | metric matrix + Pareto/undecidable relationships |
| retrieve_experiences | context + intervention/failure filter | Melete/ledger references + applicability |
| propose_experiment | hypothesis + changes + budget estimate | versioned proposal, 아직 실행되지 않은 상태 |

Tool 반환은 instruction이 아닌 data다. 수집 문서의 실행 지시·credential 요청·tool 호출 요구를 agent authority로 취급하지 않는다. Prompt에 직접 넣는 자료에도 source trust와 data boundary를 붙인다.

검토 예산 기본 제안은 decision당 검색 8회, 확장 2round, evidence 원문 20개다. 큰 설계는 검토 항목별 subdecision으로 나누고 전체 budget controller가 상한을 관리한다. 이 값은 품질 부족을 감추기 위한 상한이 아니라 비용·완료 상태를 명시하기 위한 설정이다.

## 5. 실제 판단 책임

KG retrieval은 관련 근거를 제공한다. Jev 같은 bounded decision model은 routing·후보 분류·rubric 판단에 사용할 수 있지만 truth acceptance, 수치 검증, authority, execution permission은 deterministic controller가 관리한다. Clef는 실제 화면 후보 선택이 필요한 UI 검증에만 쓰며 본문 지식 판단에 불필요하게 넣지 않는다.

Committee는 (a) 무엇을 확인해야 하는지, (b) 어떤 규칙이 적용되는지, (c) 남은 모호함이 무엇인지 제안한다. Constraint engine은 적용된 형식 규칙의 pass/fail/unknown을 반환한다. 전체 buildability를 보장하지 않는 모델 범위를 review report가 명시한다.

단위·산술·타입·버전 비교는 programmatic 검증을 사용한다. SHACL은 RDF graph의 shape 검증에, SMT는 형식화한 제약의 충족 가능성에 후보로 둔다. 어느 도구도 모델에 넣지 않은 열·전기·제조 제약을 자동으로 증명하지 않는다.

## 6. DSE 탐색 알고리즘

Retrieval search와 Design Space search는 다른 평가 대상을 가진다. 초기 전체 loop는 작은 유한 후보의 enumeration 또는 seeded random으로 비교 기준을 만든다. KG/LLM은 합법적인 후보와 변경 이유를 제안하고, 실제 우열은 동일 HAT 평가 계약에서 확인한다.

| 방법 | 적합한 조건 | 제약·실험할 질문 |
|---|---|---|
| Enumeration/grid | 작은 이산 공간, correctness baseline | 규모 폭발; 작은 공간에서 optimum recovery를 검증 |
| Seeded random/QMC | 넓은 공간의 unbiased baseline | 조건부·불법 조합을 sampler 앞/뒤에서 처리 |
| TPE/conditional sampling | 혼합 categorical·conditional 변수 | 제약 표현과 많은 objective의 효율을 domain 실험으로 확인 |
| Multi-objective Bayesian optimization | 평가가 비싸고 surrogate가 유효한 영역 | calibration/domain shift/차원 증가에 대한 sensitivity 필요 |
| NSGA-II/III 계열 | 복수 목표의 비선형·혼합 공간 | population 평가 비용·feasible repair 편향 관리 |
| KG/LLM-guided beam | ISA·설계 구조를 바꾸는 후보 생성 | novelty, hallucination, 반복 후보를 제어하고 above baseline 개선 검증 |

공식 구현 후보: [Optuna samplers](https://optuna.readthedocs.io/en/stable/reference/samplers/index.html), [BoTorch multi-objective tutorial](https://botorch.org/docs/v0.17.2/tutorials/multi_objective_bo), [pymoo NSGA-II](https://www.pymoo.org/algorithms/moo/nsga2.html). 특정 논문의 우월성을 HAT workload에 일반화하지 않는다.

소수 objective에서 쓰는 hypervolume은 비교 cohort·normalization·reference point를 고정해야 한다. 모든 metric을 무조건 acquisition objective로 넣지 않고 전체 metric은 보존하면서 선택한 Pareto projection/constraint profile별 탐색을 지원한다. 지표 선택은 사용자가 바꿀 수 있고 나머지 값은 계속 보고한다.

## 7. 실험 제안·환류

Proposal에는 성능 개선 기대와 정보 획득 기대를 구분한다. 예: throughput이 좋아질 후보, tail 병목 가설을 반증할 후보, cost model을 보정할 calibration 후보. 각각 예상 비용·실행 시간·근거·stop condition을 포함한다.

Failure taxonomy: invalid composition, unsupported ISA/IR, semantic mismatch, compiler/resolver error, timeout, resource exhaustion, simulation engine error, metric incomplete, performance regression, evidence insufficient. infrastructure failure를 설계 열등성 training label로 쓰지 않는다.

Insight 승격은 원자료 검토, applicability 확인, 독립 재현/ablation 또는 명시적 제한에 따른다. 단일 run에서 도출한 해석은 candidate 상태로 남길 수 있다. 새로운 반례는 supersession/conflict record를 만들고 이미 그 Insight를 쓴 downstream proposal을 재검토 대상으로 표시한다.

## 8. 비교 실험 계획

- lexical-only / dense-only / hybrid / hybrid+rerank / hybrid+graph / full pipeline을 같은 corpus snapshot과 query set에서 비교한다.
- parent-child chunk, 표 단위 chunk, graph depth, top-k, RRF parameter, reranker를 한 번에 한 요소씩 또는 사전 정의 factorial design으로 비교한다.
- entity exact-match, cross-version contradiction, no-answer, multi-hop hierarchy, kernel legality, historical failure retrieval을 별도 slice로 보고한다.
- agent의 좋은 답변 수만 세지 않고 invalid acceptance, missed constraint, citation entailment, correct abstention, downstream experiment waste를 측정한다.
- 비용·지연을 줄였을 때 critical correctness가 낮아지면 품질 gate에서 탈락시킨다.

## 9. 최초 사용 예

질문: 특정 package 조합에서 decode kernel을 fuse하면 session tail latency가 개선되는가.

먼저 package/SoC/ISA와 workload revision을 resolve한다. port·capacity 제약을 정확 조회하고, fusion의 적용 조건·working-set 근거와 관련 실패 경험을 검색한다. Candidate recipe는 correctness와 capacity/spill 검사를 통과한 뒤 새로운 L2 비용·L3 timeline을 만든다. 동일 cohort baseline과 TTFT/TPOT/throughput/energy/tail을 비교한다. 개선과 악화를 각각 기록하고, 불확실한 spill 원인은 다음 ablation의 가설로 연결한다.
