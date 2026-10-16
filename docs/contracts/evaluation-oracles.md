# 정답 fixture·완료·abstention·budget 계약

상태: P0의 평가 설계. Fixture gold와 실제 runtime 관측을 분리한다. 계약·schema의 정적 검증 PASS는 adapter conformance나 실제 episode PASS가 아니다.

## 1. 공통 case envelope

모든 case는 `case_id`, `expected_decision`, `allowed_unknown_reasons`, `required_capability`, `expected_execution_permission`을 갖는다. `required_capability`는 string이며, expected permission은 denied/exploratory_only/validated_profile_only/not_applicable 중 하나다. 별도 simulation 요청이 없는 comparison·Melete 단위 사례는 not_applicable이다.

`expected`는 구현 이전에 작성한 gold이고, `observed`는 별도 evaluation artifact에만 기록한다. Fixture의 expected를 실행 결과로 갱신하지 않는다. Gold 수정에는 새 oracle version, 변경 이유, 독립 review가 필요하다. [oracle-lock.json](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/fixtures/p0/oracle-lock.json)은 현재 fixture bytes와 expected corpus를 고정한다.

Case kind는 supported_positive, known_invalid, unsupported, insufficient_evidence, execution_failure, duplicate_event, delayed_availability, schema_negative로 구분한다. 통과/거부만 있는 이진 표로 축약하지 않는다. Native 상태, DSE 네 판단 축, metric 비교, receipt readiness는 각각 필요한 expected 필드를 가진다.

## 2. 수행 기준

| 항목 | 분모 | 성공/실패 정의 | P1 제안 gate |
|---|---|---|---|
| Critical false acceptance | 고정된 known-invalid critical cases | gold가 금지한 승인·실행 또는 scope 밖의 검증 완료 주장 | 0건 |
| Required-positive completion | 첫 episode와 adapter의 필수 positive ID 집합 | 모든 required artifact·상태·권한·출처를 기대값대로 충족 | 100%; 한 개라도 not_evaluated면 승격 불가 |
| Supported-positive completion | 사전 고정한 held-out supported positives | precondition이 충족된 정상 작업이 기대 terminal state에 도달 | 전체 ≥90%, 도메인별 ≥80% |
| Correct abstention | gold가 unsupported/근거 부족으로 정한 cases | 허용된 unknown reason과 실행 permission을 함께 반환 | ≥95%; critical capability는 fixture 전부 정확 |
| Unnecessary abstention | supported-positive 전체 | 충분한 support/evidence인데 unknown/abstain으로 끝남 | ≤10% |
| Execution error | 실제 시도한 실행 cases | 판단과 별개인 runner/adapter/service 실패 | 별도 실패율; unknown을 정답으로 바꾸지 않음 |

분모가 0이면 value=null, status=not_evaluated다. 0/0=100%로 처리하지 않는다. Environment/API 접근이 없어 required case를 실행하지 못한 것은 해당 test의 blocked이며 passed가 아니다. 사후에 실패한 case를 unsupported로 재분류해 분모에서 빼지 않는다.

P1 held-out query 계획 60개는 6개 도메인마다 supported positive 5개, critical negative 2개, 올바른 unknown 2개, 실행/전송 failure 1개로 고정한다. 실제 corpus에서 독립적으로 정답을 작성하기 전에는 이 평가가 준비됐다고 표시하지 않는다. 첫 native episode 필수 positive와 이 held-out 집합은 별도다.

## 3. 평가 레벨

| evidence lane | 무엇을 확인하는가 | 현재 P0에서 가능한 것 |
|---|---|---|
| document_consistency | JSON schema·점수·산식·링크·fixture oracle 정합성 | 실제 정적 검사 가능 |
| pinned_source_contract | 지정 commit의 type/function/fixture 의미 | source를 읽어 verified_by_source로 기록 가능 |
| adapter_conformance | 신규 adapter가 native 입출력·상태를 보존 | 구현 전 planned |
| native_component_probe | 기존 component fixture의 실제 실행 | 실행하지 않음; 향후 허용된 시험 범위에서만 |
| integrated_episode | source→DSE→HAT→Melete→next proposal 연결 | 존재하지 않는 경로를 PASS로 추정하지 않음 |
| B300_target_acceptance | 실제 B300 target asset·coverage·입출력·metric 기준 | pinned 자료에 없는 dependency가 있으면 blocked |

`planned`는 아직 수행하지 않은 정의된 작업, `blocked`는 명시된 필수 dependency 때문에 수행하지 못함, `verified`는 특정 lane의 관측 evidence가 있음, `complete`는 그 작업의 모든 required gate가 충족됨이다. 이 상태는 lane/requirement마다 기록하며 전체 시스템 readiness로 전파하지 않는다.

## 4. 첫 episode의 최소 반례

- 모든 committee expert가 abstain하지만 native simulation_ready=true.
- backend=None fallback이 unresolved judgment를 warning으로 남기며 approve.
- required DSE-R13이 12개 summary 밖에 있고 fail.
- source_verified hypothesis가 hard constraint로 요청됨.
- Melete stored이지만 embedding_pending=true, 또는 duplicate로 재유입.
- scalar hints는 match하나 전체 shape/version predicate는 false/unknown.
- carry-forward unit 누락·중복, Oracle 결과를 realizable로 표기, future state 접근 위반.
- missing metric, constraint violation, interval overlap, 잘못된 target/unit/cohort.
- 불법 조합·미지원 op/model·runner failure·근거 부족을 서로 다른 상태로 반환.

각 반례의 expected와 허용 unknown reason은 해당 JSON fixture가 기준이다. Native code에 존재하지 않는 synthetic R13이나 합성 metric 수치를 native 사실로 표기하지 않는다.

## 5. BudgetVector와 공정 비교

P3/P4의 같은 budget은 단순 HAT 호출 수가 아니다. Campaign manifest에 다음 cap과 실제 사용량을 모두 기록한다.

| 축 | 기록 단위 |
|---|---|
| Native 평가 | submitted/started/completed/invalid/failed HAT attempts, fidelity별 실행 시간 |
| 모델·검색 | LLM input/output tokens, model/revision, paid calls, retrieval/rerank calls, cache hit/miss |
| 재시도 | retry attempt와 실제 추가 compute/API 과금, idempotent 처리 여부 |
| 시간 | wall-clock, CPU/GPU hours, queue wait, cancel 후 소요 |
| 사람 | review·수정·운영 시간과 개입 횟수 |
| 비용 | currency·가격 확인일·region/SKU·실제 측정 vs 추정·egress/storage |

각 축의 cap이 설정되지 않은 상태에서 유료 autonomous run을 허용하지 않는다. 모든 정책을 단일 score로 합칠 필요는 없지만 비교 표에는 동일 cap vector와 차이를 명시한다. Invalid run과 실패·retry 비용을 숨기거나 success count만으로 효율을 계산하지 않는다.

Model/optimizer-only, KG 없는 agent, 전체 KG agent는 같은 workload/quality/knowledge availability 조건을 사용한다. 외부 golden control은 독립 측정 evidence이며 HAT L4나 real-mode L3로 분류하지 않는다.
