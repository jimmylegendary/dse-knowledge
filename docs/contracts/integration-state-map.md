# HAT·Melete 통합 상태 매핑의 진입점

상태: P0 normative contract. 검토 baseline은 DSE `2a460a0a57d13db6753481a26074e3fb3b4f2aa9`다. 기존 HAT/Melete type과 의미를 보존하고 adapter가 만드는 DSE 상태를 구분한다. Source로 확인한 의미와 실제 runtime PASS는 다른 evidence lane이다.

## 1. HAT 네 축

| DSE 축 | 판정 근거 | Native simulation_ready=true로 확정 가능한가 |
|---|---|---|
| simulation_permission | 실행/semantic prerequisite, declared review blocking, assumptions, 실제 action authority | 아니오. Native permission hint일 뿐 |
| validation_verdict | complete frozen ValidationProfile의 required rule/input/applicability 결과 | 아니오 |
| review_completeness | 요구된 seat·evidence·검토 범위와 invocation mode | 아니오 |
| physical_feasibility | 선언한 물리 scope의 근거와 out-of-scope 목록 | 아니오 |

Native committee의 raw scope verdict·vote·findings·simulation_ready와 backend invocation mode를 그대로 기록한다. `backend=None`을 전달해 deterministic fallback을 실행한 경우와 committee를 호출하지 않은 경우는 다르다.

| 입력/상황 | validation | review | 실행 허용 | 물리적 의미 |
|---|---|---|---|---|
| Native ready=true, 전원 abstain, strict profile의 review가 blocking | incomplete_unknown | all_abstain | denied | unknown |
| Native ready=true, backend=None fallback, blocking expert review 미충족 | incomplete_unknown | partial | denied | unknown |
| 전원 abstain, profile이 그 review gap을 비차단으로 선언, 모든 execution/semantic check pass, feasibility assumptions가 bounded | incomplete_unknown | all_abstain | exploratory_only | 검증된 physical design 아님 |
| Required DSE-R13 fail, evidence summary에는 R1–R12만 있음 | reject | 별도 보존 | denied | 알려진 required 위반 |
| Required rule/input/applicability 누락·validator error | incomplete_unknown | 별도 보존 | blocking 여부에 따른 denied/exploratory_only | pass로 보간 금지 |
| 선언 범위의 required rules와 review 전부 충족 | validated_within_declared_scope | complete | validated_profile_only | 명시 scope에 한정; 범위 밖 항목은 남음 |

이 표의 상세 profile·aggregation·Claim 사용 규칙과 gold는 [validation-and-claim-use.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/validation-and-claim-use.md)가 기준이다. 실제 실행 authority는 이 비교/검증 결과와 별도로 확인한다.

## 2. Cost·fidelity·정보 접근

L2/L3 라벨 하나로 전체 trace의 fidelity를 표현하지 않는다. Cost unit의 producer·coverage·완전한 replacement evidence, carry-forward 원본과 composition을 기록한다. 누락·중복 비용이나 부분 covered 결과를 전체 covered처럼 보고하지 않는다.

Realizable와 Oracle profile, offline design의 workload visibility, online controller의 state cutoff를 보존한다. 실제 장비의 External Golden Control은 독립 증거이고 HAT L4 또는 real-mode L3가 아니다. 상세 native 의미와 artifact binding은 [hat-fidelity.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/hat-fidelity.md), snapshot 목적은 [snapshot-contract.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/snapshot-contract.md)를 따른다.

## 3. Melete 상태는 직교한다

Pinned IngestReceipt의 `status`는 stored/trace_only/duplicate이고 `extraction_incomplete`, `embedding_pending`은 별도 flag다. Native scalar Condition은 exact typed equality conjunction이며 range/nested predicate를 표현하지 않는다.

| Native 관측 | 허용되는 해석 | 금지하는 추론 |
|---|---|---|
| stored | 수집 경로의 저장 응답을 받음; ID/revision 보존 | memory 추출·embedding·검색·DSE 적용 가능이 모두 완료됐다고 판단 |
| trace_only | trace/event 기록 경로 | 유용한 검색 memory가 만들어졌다고 판단 |
| duplicate | 기존 event identity와 dedup 결과를 확인 | 독립 실험/검증 횟수 +1 |
| extraction_incomplete=true | 추출 상태 미완료를 보존 | 부분 추출을 전체 episode 지식 완료로 판단 |
| embedding_pending=true | embedding readiness 미완료 | 모든 검색이 불가능하거나 반대로 모두 준비됐다고 판단 |
| fresh authorized exact query hit | 해당 readout item·scope·version의 관측된 visibility | DSE의 복합 applicability·source validity 검사를 생략 |

DSE predicate의 ID/version/hash를 DSE ledger의 authoritative binding에 두고, Melete에는 지원되는 scalar hints만 사용한다. Retrieval 후 full predicate, source/ACL, snapshot, event ordering을 다시 검사한다. 상태·query·receipt fields와 call path는 [melete-state-and-applicability.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/melete-state-and-applicability.md)가 기준이다.

## 4. 판정 기준 연결

필수 규칙 집합은 retrieval top-k와 독립이다. Claim의 원문 확인은 hard constraint 승격과 다르다. 성능 비교는 [comparison-policy.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/comparison-policy.md), 완료·abstention·gold는 [evaluation-oracles.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/evaluation-oracles.md)를 따른다.

현재 pinned source에는 B300 target twin 및 요청한 전체 native chain의 검증 evidence가 없다. 구체 component probe와 missing adapter/asset은 [p1-first-episode.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/episodes/p1-first-episode.md)에 고정한다. 문서/schema 검증만으로 이 target을 완료 처리하지 않는다.
