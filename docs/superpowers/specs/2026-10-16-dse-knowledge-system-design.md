# DSE 판단 지식·실험 경험 시스템 설계

2026-10-17 P0 보완의 규범적 판정은 [integration-state-map.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/integration-state-map.md)를 따른다. 기존 원칙은 유지하며 permission·validation·review·feasibility를 분리한다. 지정 source에 없는 B300 target/통합 chain은 [p1-first-episode.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/episodes/p1-first-episode.md)의 blocker로 보존한다.

상태: 설계 초안. 사용자 요구에 따라 구현·배포 승인과 분리한다. 모든 수치 목표·기술 추천은 이 문서에서 명시적으로 확정한 사용자 요구 외에는 제안이다.

## 1. 목적과 사용자 요구

새 LLM, 시간 정보를 갖는 agent workload, 비교 기준 hardware를 입력받아 hardware architecture와 HATIR kernel/recipe를 공동 탐색한다. 인간과 AI는 같은 지식·검증·실험 API를 이용하며, 사람이 직접 고른 후보와 agent가 제안한 후보에 동일한 근거 기준을 적용한다.

최소 세 영역은 hardware asset 조합과 buildability 검토, kernel fold/unfold·fusion 탐색, 결과 분석과 다음 실험 제안이다. 목표 범위는 rack–tray–package–SoC와 내부 구성 요소 전부다. 지식 수집, metadata, 검색, infrastructure와 운영도 제품의 일부다.

성능은 Metric Vector로 보존한다. TTFT, TPOT, request/session latency, throughput, tail latency, SLO goodput, 전력, 에너지, 메모리·통신 비용 등을 서로 다른 단위와 측정 범위로 관리한다. 기술 선택용 추천 점수로 실험 성능을 합치지 않는다. Pareto 비교와 사용자가 선택한 제약별 비교를 모두 제공한다. 최적이라는 표현은 탐색 범위·예산·측정 조건을 함께 명시할 때만 사용한다.

초기 자료는 없다. 선호 cloud·region·예산도 정해지지 않았다. 사내 Confluence RAG가 Supabase와 Neo4j를 사용한다는 사실은 친숙도 근거이며, 계정 재사용·private content 접근·네트워크 연결이 허용됐다는 뜻은 아니다.

## 2. 성공 기준

1. 어떤 리뷰·kernel 제안·실험 해석도 사용한 근거, 적용 버전, 알려진 빈틈을 추적할 수 있다.
2. 모든 phase의 demonstrator가 source 발견→취득→추출→Claim→검색→설계 검토→kernel 후보→HAT 실행→지표→Melete 경험→다음 제안까지 이어진다.
3. 근거를 찾지 못함, 제약 위반, simulator 미지원, 실행 실패, 해석 불확실성을 별도 결과로 반환한다.
4. 같은 Design Point를 재평가할 때 workload·HW·kernel·toolchain·KB snapshot·seed·cache 초기 조건을 고정할 수 있다.
5. 새로운 source·model·metric·asset·검색 backend를 추가해도 기존 근거와 실험을 재해석 없이 읽을 수 있다.
6. 기술 추천은 조사 근거와 계산 가능한 점수표를 갖고, 실험으로 검증한 값과 전문가 사전 평가를 구분한다.

## 3. 실패로 보는 상태

- 출처 없는 요약을 물리 제약이나 검증된 성능 사실로 사용한다.
- committee 찬성, retrieval score, embedding 유사도를 buildability 증명으로 사용한다.
- 저장소를 여러 개 쓰면서 어떤 값이 canonical인지 정하지 않는다.
- 관측한 병목의 상관관계를 인과적 insight로 바로 승격한다.
- 이전 RP timeline을 바뀐 architecture/kernel의 성능값으로 재사용한다.
- 실패·중단·근거 부족 후보를 버리고 성공한 결과만 기억한다.
- 특정 HW 계층, kernel, Melete 또는 운영을 이후 phase로 통째로 미룬다.
- 실제 측정하지 않은 지표에 0을 넣거나 simulator 추정을 B300 실측으로 표기한다.

## 4. 논리 구성

| 구성 | 책임 | Canonical 정보 | 재생성 가능한 것 |
|---|---|---|---|
| Source registry + raw artifact store | source 발견·권리·버전·원본 보존 | 원본 hash, 취득 기록, 권리, byte artifact | parser output, chunk |
| Knowledge ledger | Claim·entity·constraint·evidence·revision·ACL | 승인된 statement와 출처 관계 | graph/vector/lexical projection |
| Retrieval service | lexical+dense+graph+정확 조회·rerank | query audit, corpus snapshot | 캐시, community summary |
| Validator service | 정형 제약·단위·타입·적용 여부 검사 | validator 버전, 입력, 결과·근거 | report view |
| HAT adapter | 기존 HAT 의미에 맞는 request·artifact·metric 연결 | 원본 HAT 결과와 run manifest | dashboard aggregates |
| Experiment ledger + artifact lake | 후보·intervention·trial·metric·timeline 보존 | 실험 사건·원자료 | 분석용 Parquet view |
| Melete adapter | 경험·Insight와 기존 Melete 계약 연결 | Melete receipt 및 대응 ID | 전송 cache, 조회 view |
| Agent tools + human interface | 동일한 지식·검증·실험 작업 사용 | proposal와 명시적 결정 기록 | 표시용 설명 |
| Infrastructure/control plane | 권한·예산·job·모니터링·복구 | deployment manifest, audit, quota | ephemeral workers |

Knowledge ledger와 graph projection을 구분한다. Graph에 있는 내용이 canonical Claim보다 오래되면 projection watermark를 표시하고, critical validation은 canonical snapshot을 읽는다. Graph/vector index 업데이트는 outbox+idempotent 소비로 처리하는 설계를 제안한다. cross-store 원자적 transaction을 가정하지 않는다.

RDF/SPARQL·property graph는 대안으로 평가한다. 관계의 출처·시간·적용 조건을 명시할 수 있어야 하며, source와 domain마다 별도 graph DB를 만드는 것을 기본값으로 삼지 않는다. Raw trace는 object/columnar 저장을 사용하고 graph에는 주요 사건과 artifact reference를 연결한다.

## 5. 공통 end-to-end 사건 순서

1. Source registration: 권리·trust tier·업데이트 정책을 확인한다.
2. Capture: source revision과 hash를 고정하고 원본을 보존한다.
3. Parse: 문단·표·수식·그림·code의 위치를 보존한다.
4. Normalize: entity 식별·단위·버전·범위를 정규화한다. 모호한 값은 보류한다.
5. Propose Claim: 관측·규격·가설을 구분하고 source span을 연결한다.
6. Validate/publish: schema·권리·근거·모순 검사를 통과한 상태만 사용 목적에 맞게 공개한다.
7. Retrieve: Decision Context와 권한·버전·범위로 관련 근거를 찾는다.
8. Propose/review Design Point: architecture·kernel·serving 변경과 근거를 명시한다.
9. Validate: constraint와 correctness 검사 결과를 남긴다. 미지원은 통과와 구분한다.
10. Execute HAT: L2 analytical 결과와 L3 temporal replay 결과의 권위를 구분한다.
11. Analyze: metric vector·비교 조건·불확실도·failure를 기록한다.
12. Record/revise: Melete에 관측 사건을 전달하고 Insight는 별도 검증 상태로 보존한다.
13. Propose next experiment: 기대 개선 또는 정보 획득, 비용, 반증 조건을 설명한다.

내부 chain-of-thought 수집은 요구하지 않는다. Trajectory에는 관찰 가능한 tool 호출, 입력·출력 reference, 명시적 짧은 결정 근거, 채택·기각·수정·실패를 기록한다.

## 6. Architecture 판단

Hardware Asset의 hierarchy containment와 통신 topology는 다른 관계다. Rack에 Tray가 있다는 사실만으로 전력·냉각·link·프로토콜·물리 배치가 호환된다고 보지 않는다. 각 asset은 version, parameter domain, ports, units, constraints, supported programming capability, evidence를 갖는다.

Committee는 역할별 subgraph와 원문을 검색하고 query/evidence ID를 남긴다. Native simulation_ready=true는 permission hint이며 buildability·review 완결성·전체 validation 성공이 아니다. 필수 validation은 complete versioned ValidationProfile에서 수행하고 top-k는 설명 evidence에만 적용한다. Profile이 review gap을 비차단으로 정해도 execution/semantic rule 실패를 assumption으로 우회하지 않는다.

정형 validation은 schema, 산술·차원, 연결·수량, 용량, 지원 ISA, 알려진 물리 한계를 검사한다. 수식 검증을 거쳤더라도 thermal closure, signal integrity, manufacturing feasibility 등 모델 밖의 항목은 unknown일 수 있다. Buildability 판정은 검증 coverage와 미확인 항목을 함께 반환한다.

## 7. Kernel 탐색

입력은 logical op semantics, shape·dtype·layout, workload phase, target asset version, programming model/ISA, memory hierarchy, 검증된 resource limits, 선택적으로 runtime state snapshot이다. 생성 대상은 현재 HAT 경계에 맞는 kernel/recipe와 event representation이다.

후보는 tiling, folding, placement, dataflow, scheduling, fusion, spill을 포함한다. shape/타입·의존관계·memory bound·수치 의미 검사를 통과해야 cost/replay에 들어간다. MAC 보존은 일부 검증이며 전체 수치 correctness의 대체가 아니다. 실제 executable kernel 검증이 지원되지 않으면 검증 가능한 의미 범위를 명시한다.

RP snapshot은 시점과 실행 조건을 가진 관측이다. 변경 후보는 새 event DAG와 비용·경합·resource state를 재계산한다. Future architecture에 대한 예측에는 사용한 surrogate/analytical model의 적용 범위와 uncertainty를 붙인다.

## 8. 실험·학습

실험 간 차이는 intervention으로 명시한다. 단일변수 ablation과 복수변수 탐색을 구분한다. 새 architecture에 baseline용 calibration을 무조건 적용하지 않는다. Training/search에 사용한 workload와 평가용 workload를 분리한다.

후속 제안은 Pareto 개선 후보뿐 아니라 불확실도를 줄이는 calibration·반례·재현 실험을 포함한다. 다른 workload·precision·toolchain으로 insight를 일반화할 때 applicability를 확장하는 새 검증이 필요하다.

Melete는 source event와 적용 조건을 가진 기억을 처리하는 접점이다. DSE ledger가 HAT 원자료의 authoritative reference를 보존하고, Melete가 반환한 receipt와 memory/pattern version을 연결한다. 기존 Melete의 epistemic 상태를 의미 변경 없이 매핑한다. 기존 HAT·Melete의 자동 통합이 준비됐다고 가정하지 않는다.

## 9. Workload·성능 계약

사용자의 예시는 1,000 session, session당 10–100 turn, turn당 input 10–512와 output 100–1,000 및 timing이다. 설계 예제의 길이 단위는 token으로 가정하되, 실제 Scenario 등록에는 unit·tokenizer·chat template이 필수다.

다음은 반드시 별도 필드다: input이 새 token인지 전체 누적 context인지, arrival이 고정 시각인지 predecessor 완료 후 think time인지, prefix 공유와 KV cache 조건, tool wait, 중단·timeout, warm/cold cache, serving scheduler, model revision/precision, MoE routing 등 workload를 바꾸는 조건.

고정 arrival replay와 completion-dependent replay는 별도 Scenario 정책이다. 같은 cohort 안에서만 성능을 비교하고, 정책을 바꾼 비교에는 별도 라벨을 단다. SLO와 quality constraints도 cohort의 일부다.

Pareto 비교는 지표 방향과 허용 오차를 명시한다. 측정 누락·불확실도 겹침은 우월함으로 결론 내리지 않는다. 비용·전력 budget이 미정이면 budget이 정해진 것처럼 후보를 제거하지 않고 여러 feasible envelope를 표시한다.

## 10. 단계별 전체 coverage

현재는 P0 설계 단계다. P0 내부에서는 전체의 개념 지도, 근거와 후보, 계약, 실행 계획을 차례로 정교화한다. 이후 P1–P5도 동일한 end-to-end 흐름을 유지한다.

P1은 cloud 구축 전에 pinned model/config/workload/native support와 adapter conformance를 확인한다. 이후 신규 모델 onboarding과 모든 HW 계층·kernel·HAT·Melete·다음 제안을 잇는 실제 target episode를 검증한다. 현재 B200 meta probe는 B300 지원이나 전체 episode를 대체하지 않는다. P2에서 breadth, P3에서 fidelity, P4에서 제한된 자율성, P5에서 운영 규모를 높이되 전체 흐름을 매번 유지한다.

작은 범위는 허용하지만 누락된 기능을 placeholder 성공으로 처리하지 않는다. 외부 서비스나 fidelity가 막히면 해당 capability의 unsupported 상태와 해소 조건을 남기고 phase acceptance를 낮추지 않는다.

## 11. 기존 구현 근거

- HAT L2는 Kernel/Recipe Analytical, L3는 Temporal Replay이다. [CONTEXT.md](https://github.com/jimmylegendary/hat-system/blob/e3048fac5704118b47fd7e2eb21ed36d477742a0/CONTEXT.md#L16)
- committee의 현재 expert KB 전달은 static sheet 중심이다. [committee.py](https://github.com/jimmylegendary/hat-schema/blob/a874d0c2e277e8838ecd95ba16679b774646408e/hat_schema/verify/committee.py#L341)
- FusionPlan은 공유 tiling과 capacity 초과 시 spill/re-cost를 표현한다. [plan.py](https://github.com/jimmylegendary/hatir/blob/1ff4485f2a777d4a54a68e9406a834fc3bddc630/impl/hatir/plan.py#L248)
- Melete Observation과 MemoryVersion에 event/source/version/applicability가 존재한다. [observation.py](https://github.com/jimmylegendary/melete/blob/9a3564dd96de22d0311522417c2c36e6bf2a0a91/packages/melete-core/src/melete/contracts/observation.py#L29), [memory.py](https://github.com/jimmylegendary/melete/blob/9a3564dd96de22d0311522417c2c36e6bf2a0a91/packages/melete-core/src/melete/contracts/memory.py#L25)

읽기 확인 revision: hat-schema a874d0c2e277e8838ecd95ba16679b774646408e; hat-system e3048fac5704118b47fd7e2eb21ed36d477742a0; hatir 1ff4485f2a777d4a54a68e9406a834fc3bddc630; Melete 9a3564dd96de22d0311522417c2c36e6bf2a0a91. 이는 source 확인 기준이며 runtime 통합 통과를 뜻하지 않는다.

## 12. 승인 경계

현재 허용된 작업은 공개 자료 조사와 이 설계 패키지 작성이다. 최종 설계·계획 검토 전 제품 코드, IaC 실행, cloud project 생성, secret 설정, corpus 대량 수집을 시작하지 않는다. 사용자가 요청한 범위에 따른 경계이며 별도 도구의 추정 승인 규칙이 아니다.

기술 추천과 운영 목표는 최종 점수표·가격/region/edition 확인·도메인 평가 결과에 따라 수정될 수 있다. 사용자에게 구현 방식은 이미 master/worker로 지정되어 있으므로 다시 고르게 하지 않는다.
