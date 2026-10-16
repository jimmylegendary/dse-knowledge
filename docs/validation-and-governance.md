# 평가·추천 점수 운영·phase 승격·위험 관리

상태: 검증 계획. 숫자는 최초 acceptance 목표 제안이며 측정된 성능이 아니다. source/model benchmark와 실제 DSE 판단 성능을 구분한다.

## 1. 두 종류의 점수

**기술/source Recommendation Score**는 검토 우선순위다. 공식 자료에 근거한 전문가 prior, 근거 신뢰 수준, 도메인 실험 결과를 별도 열로 관리한다. source의 권위나 모델의 인기만으로 기능 검증을 대체하지 않는다.

**DSE Metric Vector**는 설계점의 성능이다. 지표 원값·분포·조건을 보존하고 cohort별 Pareto 비교를 한다. 도구 추천에 쓰는 100점 점수로 HW의 모든 성능을 합치지 않는다.

## 2. 기술 후보 rubric

| 차원 | 가중치 | 평가 질문 |
|---|---:|---|
| quality | 25 | 이 역할의 정확도·표현력·검색/추출 능력을 요구에 맞게 검증할 수 있는가 |
| fit | 20 | DSE의 version·숫자·표·code·graph·HAT/Melete 사용 방식에 맞는가 |
| provenance | 20 | 근거·revision·필터·권한·재현성을 보존할 수 있는가 |
| operability | 15 | cloud 운영·관찰·복구·upgrade·관리 부담을 감당할 수 있는가 |
| portability | 10 | data/model export, 표준 interface, 교체 가능성이 있는가 |
| economics | 10 | 요구 규모에서 총비용과 예측 가능성이 어느 정도인가 |

각 점수는 0–5다. 0=핵심 요구에 부적합, 1=큰 결손, 2=중요한 보완 필요, 3=가능하나 미확인점 있음, 4=문서 근거상 적합, 5=해당 역할에서 매우 강한 근거를 가진 후보라는 사전 판단이다. 5라도 DSE 실측 통과라는 뜻은 아니다. Total = Σ(weight × score / 5), 0–100 범위다.

역할이 다른 후보의 total을 비교하지 않는다. 예를 들어 AST parser는 native code의 구조 추출에 강하므로 높은 점수를 받을 수 있지만 논문의 암묵적 설계 지식을 자동으로 해석하는 LLM을 대체한다는 뜻은 아니다.

미측정 TCO는 neutral 3을 기본으로 둔다. OSS의 라이선스 비용과 CPU/GPU·운영 인건비·idle·network 비용을 분리한다. 문서에 기재된 confidence 숫자는 작성자의 자기 평가이며 calibration된 확률이 아니다. 현재 공통 근거 수준은 `E1=공식 문서/카드 확인`, `E2=우리 fixture 검증`, `E3=우리 held-out 평가`, `E4=운영 관측`으로 표시한다. 이번 조사는 E1이다.

## 3. source rubric

source는 relevance 30, authority 25, extractability 15, rights 15, freshness 10, diversity 5를 사용한다. 동일한 0–5 산식이지만 기술 후보와 점수의 의미가 다르다. Rights가 확인되지 않은 본문은 total이 높아도 취득/index/외부 전송 gate를 통과하지 못한다. 같은 publisher 재인용은 독립 근거 diversity로 중복 가산하지 않는다.

## 4. 추천 운영 절차

1. 후보를 역할별로 넓게 수집한다. 기능·edition·라이선스·가격·공식 근거 URL과 확인일을 기록한다.
2. hard gates(요구 기능, 권리, export/삭제, 권한 보호, 지원 region/edition)를 먼저 표시한다.
3. expert prior를 계산하고 각 category 상위 후보부터 실제 검토한다.
4. 기본 점수 가중치를 한 번에 ±5 percentage point 조정하고 나머지를 비례 정규화해 순위 민감도를 본다. 동일 점수는 공동 순위다.
5. Jev는 compact evidence와 명시적 후보를 받아 bounded 비교·누락 판단을 제안한다. Raw output/model/version/request metadata를 보존하고 authoritative acceptance로 사용하지 않는다.
6. 개별 1위들을 기계적으로 합치지 않고 조합의 region·network·version·canonical ownership·인력·총비용을 별도 검토한다.
7. P1 golden fixture와 최소 부하에서 후보를 비교해 measured_score와 evidence를 추가한다. 기존 prior를 덮어쓰지 않는다.
8. Phase 진입, provider/model 버전 변경, 계약/가격 변경, 품질 회귀 때 재평가한다. 정기 검토 제안은 월간이지만 실제 schedule은 운영 승인 후 설정한다.

## 5. Golden corpus와 leakage 방지

초기 평가 도메인은 (1) rack/tray/network/power, (2) package/SoC/memory, (3) ISA/programming/compiler, (4) kernel/IR, (5) LLM workload/serving/metrics, (6) experiments/provenance/feedback의 6개다. 내부적으로 hardware 계층별 최소 coverage를 추가한다.

| Phase | 평가 query 규모 제안 | 필요한 case |
|---|---:|---|
| P1 | 60개 이상, 각 도메인 10개 | exact fact, evidence location, multi-hop, conflict, no-answer, ACL negative |
| P2 | 300개 이상 | vendor/version/shape/layout별 확장, source freshness/retraction |
| P3 | 1,000개 이상 | 표·수식·code, 깊은 hierarchy, causal hypothesis, held-out workload |
| P4 | budget 고정 campaign 20개 이상 | autonomous/human/baseline 비교, interruption·budget exhaustion |
| P5 | 유지 corpus + drift slice | 신규 source/model와 운영 incident regression |

문서 단위와 family/version/time 기준으로 split한다. 동일 원문을 chunk만 나눠 train/test로 분리하지 않는다. 정답 작성은 원문 위치·단위·적용 조건을 명시하고, 생성 모델이 만든 답만 gold로 채택하지 않는다. 적어도 critical numerical/constraint case는 별도 검토자가 확인한다.

## 6. 최초 gate 제안

| 영역 | P1 목표 | P2/P3 강화 방향 | evidence |
|---|---|---|---|
| Retrieval recall@20 | 전체 ≥0.85, 도메인별 ≥0.75 | 전체 ≥0.90/0.95, domain floor 함께 상향 | query별 relevant evidence ID |
| Citation support | 검토된 answer claim ≥0.95 | ≥0.98, numerical slice 별도 | entailment·span·source revision |
| Critical unit/version/ACL | 정의된 negative fixture 오허용 0 | fixture 확대해 같은 gate 유지 | 실패 입력과 verdict |
| Unknown 처리 | 무근거 critical 판단의 approve 0 | recall/abstention tradeoff 공개 | no-answer/unsupported case |
| Contract provenance | accepted Claim/run의 필수 reference 100% | lineage·삭제·migration 추가 | machine schema checker |
| Index 권한 회수 | authoritative deny 확인 후 결과 노출 0 | cache/graph hop/외부 rerank까지 | ACL epoch·audit |
| HAT/Melete 연결 | 실제 전체 episode+reject+failure | scale·partial failure·versions 확대 | raw artifacts·receipts |
| Reproducibility | 고정 manifest로 동등 결과 또는 명시 tolerance | 시간/모델 불확실도까지 분해 | exact manifests와 diff |
| 비용·지연 | 측정 instrumentation 완비 | 승인 budget/SLO 충족 | provider/host billing·timing |

이 수치는 설계 출발점이다. Fixture가 작으면 confidence interval과 실패 사례를 함께 보고하고 숫자 하나로 production readiness를 주장하지 않는다. gate를 낮추려면 요구 변경으로 문서화하고 사용자 검토를 거친다.

## 7. Ablation과 DSE 효용

Retrieval은 lexical-only, dense-only, hybrid, +reranker, +graph, 전체로 비교한다. Parser와 embedding model을 동시에 바꿔 원인을 알 수 없게 하지 않는다. Metric은 recall/nDCG/MRR뿐 아니라 numeric/unit accuracy, version correctness, contradiction detection, abstention, cost/query, p50/p95 latency다.

Architecture review는 invalid acceptance, valid rejection, missing constraints, evidence-backed concern을 측정한다. Kernel은 legal candidate rate, semantic correctness coverage, cost/replay discrepancy, feasible best-found frontier를 측정한다. Feedback은 재현되는 insight, 반례 발견, 다음 실험의 information gain 또는 실제 improvement를 측정한다.

검색 성능이 좋아져도 불필요한 실험 수가 늘거나 잘못된 architecture가 통과하면 전체 품질은 개선됐다고 보지 않는다. Agent success에는 human review hours, wasted simulation time, duplicated experiment rate도 포함한다.

## 8. Simulator fidelity·calibration

실측 가능한 B300 baseline은 hardware·driver·runtime·power cap·clock·model·tokenizer·KV·scheduler·workload를 함께 고정한다. 실측 자원이 확보되지 않으면 HAT의 지원 범위와 기존 calibration evidence를 사용하되 결과를 simulated로 표시한다.

오차는 metric별·workload slice별로 본다. 평균 오차만으로 tail 또는 energy fidelity를 대체하지 않는다. 새 architecture는 baseline과 다른 적용 영역이므로 model extrapolation으로 표시하고 microbenchmark·공식 수치·higher-fidelity model 등 추가 근거를 계획한다.

## 9. 운영·실패 평가

권한 회수, source 철회, corrupted artifact, parser exception, embedding API failure, partial graph rebuild, queue duplicate/out-of-order, HAT timeout, Melete unavailable, cost limit, region/network failure를 drill한다. 각 drill은 stop/retry/resume/rollback 기준과 결과를 기록한다.

초기 운영 제안은 dev RPO 24시간/RTO 8시간, 중요 experiment ledger 운영 목표 RPO 1시간/RTO 4시간이다. 실제 managed service edition과 restore 실측이 목표를 만족하는지 확인해야 하며, 이 문서만으로 달성했다고 보고하지 않는다.

## 10. Superpowers와 reviewer 운영

Master는 scope·schema·scoring rubric·통합 결정을 소유한다. Worker는 독립 파일/작업 단위만 수정한다. Reviewer는 요구 충족과 evidence를 평가하고 source URL·edition·숫자·API 존재 여부를 점검한다. 분류/선택 모델의 응답은 reviewer의 사실 검증을 대신하지 않는다.

문서 review와 product runtime test를 구분한다. 이번 P0 산출물 검증은 JSON/schema/score arithmetic/local-link/phase-coverage 및 독립 review다. Corpus, HAT campaign, cloud deploy, embedding 성능 test는 아직 실행하지 않는다.

## 11. 남은 운영 결정과 기본 처리

- Cloud account/region: vendor 공통 비교와 추천 profile을 제시한다. 실제 계정 개설·region resource 배치는 실행 직전 비용·접근 조건으로 확정한다.
- Monthly cap: 총비용 산식과 시나리오를 제공한다. cap 미설정 상태에서 유료 autonomous execution을 시작하지 않는다.
- Internal Confluence: connector/ACL 설계만 포함하며 실제 접근은 별도 제공 범위 안에서 수행한다.
- GPU measurement: 미확보 상태를 명시하고 simulated vs measured gate를 유지한다.
- Model/DB final pick: 지정된 비교 절차와 switch condition으로 정한다. 빌더가 임의로 인기 제품을 선택하지 않는다.
