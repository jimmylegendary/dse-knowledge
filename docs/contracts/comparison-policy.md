# ComparisonPolicy v1: 재현 가능한 다중 지표 판정

상태: **규범적 설계 계약 / runtime 미구현**. 기존 Metric Vector를 유지한다. 이 문서와 [comparison-policy.schema.json](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/schemas/comparison-policy.schema.json), [comparison-cases.json](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/fixtures/p0/comparison-cases.json)이 P1 비교 의미의 기준이다. Fixture의 수치는 합성 정답 데이터이며 B300/B200 측정값이 아니다.

## 1. 고정하는 정보

ComparisonPolicy는 `policy_id`, `version`, `required_metrics`, objective definitions, constraint definitions, cohort keys, 허용 method/profile, uncertainty mode, missingness 정책, tolerance와 허용 주장 범위를 갖는다. `unit_registry_ref`는 registry ID/version/content SHA-256을 묶고, `semantic_validation_version=comparison-policy-validation-v1`은 아래 의미 검사를 필수화한다. Run은 policy ID·version·content hash와 사용한 MetricDefinition revision을 남긴다.

JSON Schema만으로 비교할 수 없는 decimal-string/참조 불변식은 **policy activation 전에 결정론적으로 검사**한다: target/within의 lower≤upper, objective metric ID 중복 없음, constraint metric ID 중복 없음, required_metrics가 두 역할 metric ID의 정확한 합집합, 같은 metric의 역할 간 canonical unit 일치, registry에 등록된 unit/dimension만 사용, registry content hash 일치. 한 metric이 objective와 constraint 두 역할을 갖는 것은 허용한다. Observe-only metric은 registry/report에 보존하지만 active comparison의 required 집합 밖이다. 실패 시 invalid_policy이며 compare_runs를 시작하지 않는다.

| 필드 | P1 의미 |
|---|---|
| required_metrics | 값과 단위·scope·method·출처가 반드시 필요한 metric ID 목록. Objective와 constraint의 합집합을 포함 |
| objectives | 각 metric의 min/max/target, canonical unit, absolute improvement threshold |
| constraints | metric, `le`/`ge`/`within`, inclusive bounds, canonical unit |
| cohort_keys | model/scenario/tokenizer/quality/timing/cache/system-boundary 및 비교 맥락 identity |
| evidence_compatibility_keys | fidelity/profile, cost coverage/replacement policy, decision-time mode, state-access policy와 assumption snapshot |
| allowed_method_profiles | analytical/replay/measured와 realizable/oracle 등의 허용 **조합**. 같은 라벨만으로 호환 판정하지 않음 |
| uncertainty_mode | P1은 `point_observation` 또는 `declared_bounds`를 구분. 서로 다른 mode를 한 비교에 혼합하지 않음 |
| missing_policy | required metric 누락을 0으로 채우거나 좋은 결과로 보간하지 않음 |
| performance_claim_scope | 기록된 동일 조건의 비교 또는 제시된 bounds에 조건부인 비교. 실장 성능·물리 feasibility의 증명 아님 |

Hardware/recipe identity는 DSE의 변경 대상이므로 cohort의 동일성 조건에 넣지 않는다. 변경하지 않기로 한 model semantics, workload, serving/quality 조건은 고정한다. MetricDefinition 집합의 digest도 evidence compatibility에 포함해 TTFT에 queue를 포함하는지 등 정의가 다른 값을 같은 이름·단위만 보고 비교하지 않는다. Intervention과 metric 정의를 명시하며 정밀도·quantization 변경에는 quality equivalence gate와 별도 cohort가 필요하다.

## 2. 숫자·단위·target

숫자는 finite decimal 문자열로 직렬화한다. 계산은 decimal/rational 방식으로 재현하며 NaN·infinity·알 수 없는 단위를 거부한다. 단위 registry revision과 변환식을 고정한다. v1 fixture 변환은 s→ms ×1000, kW→W ×1000, kJ/session→J/session ×1000, 나머지는 identity다. 시간·전력·energy·count는 서로 변환하지 않는다.

Objective를 모두 **작을수록 좋은 loss**로 정규화한다.

- min: `loss(x)=x`.
- max: `loss(x)=-x`.
- target closed interval `[a,b]`: `loss(x)=max(a-x, 0, x-b)`. 정확 target은 `a=b`로 표현한다.

Target의 lower/upper와 unit은 필수다. 목표 범위 안의 값들은 해당 objective에서 loss=0이다. 범위 중심에 더 가깝다는 이유로 추가 가점을 만들지 않는다.

Point observation은 `[x,x]`로 비교하되 실제 불확실도가 0이라는 뜻이 아니다. `point_observation` 결과의 주장은 그 **기록된 run 값**에 한정한다. Declared bound `[l,u]`는 그 bound의 producer·방법·scope를 함께 보존하며, confidence interval이나 물리적 보장으로 바꾸어 부르지 않는다.

min loss bounds는 `[l,u]`, max는 `[-u,-l]`다. target의 최소 loss는 두 interval이 겹치면 0이고 그렇지 않으면 가까운 끝점의 loss다. 최대 loss는 두 끝점 loss의 최대값이다.

## 3. 판정 순서

1. Policy/schema/metric-definition 및 숫자·단위·candidate ID의 유효성을 검사한다. 실패하면 `invalid_input`이고 frontier를 만들지 않는다.
2. Cohort와 evidence compatibility를 검사한다. 불일치하면 `incompatible_cohort`; 조용히 다른 cohort를 섞거나 일부만 남겨 전체 비교로 보고하지 않는다.
3. Required metric의 누락을 표시하되 이미 관측된 hard constraint 위반을 숨기지 않는다. 알려진 constraint 위반이 없는 누락 후보는 `comparison_incomplete`이며 어떤 후보에 대해서도 전체 우월함이 확정되지 않는다.
4. Hard metric constraint를 판정한다. `le c`: upper≤c이면 pass, lower>c이면 violation, 나머지는 unknown. `ge c`: lower≥c pass, upper<c violation. `within[a,b]`: interval 전체가 안이면 pass, 완전히 밖이면 violation, 부분 중첩이면 unknown.
5. 후보 상태 우선순위는 알려진 `constraint_violated` → required metric 누락의 `comparison_incomplete` → bound 경계의 `constraint_unknown` → `feasible`이다. 알려진 위반은 다른 metric의 누락으로 희석하지 않는다. 이 상태들을 성능 열세인 `dominated`와 구분한다.
6. 모든 required metric이 있고 constraint pass인 후보에만 아래 dominance를 적용한다.
7. Policy-relative frontier, pairwise relation, 제외 이유와 전체 비교의 완결성을 반환한다.

ValidationProfile이 허용한 exploratory run도 metric 분석은 가능하다. 단, 그 결과는 exploratory cohort에 속하며 physical feasibility 또는 validated-design 성과로 승격하지 않는다. 실행 허용 상태와 비교 가능성은 별도 필드다.

## 4. Tolerance와 순환하지 않는 dominance

각 objective i에 고정된 nonnegative 절대 threshold `tau_i`를 둔다. Threshold는 **의미 있는 개선**을 표시하기 위한 것이며 악화를 허용하는 epsilon이 아니다. 상대 tolerance와 pair-dependent scale은 P1에서 사용하지 않는다.

Loss interval이 A=`[L_Ai,U_Ai]`, B=`[L_Bi,U_Bi]`일 때:

`A dominates B` iff 모든 i에서 `U_Ai <= L_Bi`이고, 적어도 한 i에서 `L_Bi - U_Ai > tau_i`.

따라서 어떤 objective에서도 악화를 허용하지 않는다. Bound가 겹쳐 이 조건을 만족하지 않으면 우열을 확정하지 않는다. 작은 개선만 있으면 dominant로 표시하지 않는다. 서로 tolerance 안에 있다는 pairwise 표시를 동치관계처럼 합치거나 후보를 삭제하지 않는다.

순환이 없는 이유: A→B와 B→C이면 모든 i에서 `U_Ai <= L_Bi <= U_Bi <= L_Ci`이다. A→B에서 threshold를 넘은 objective의 개선 폭은 A→C에서 줄지 않는다. 따라서 관계가 추이적이며 자기 자신을 strict-dominant로 만들 수 없다. Pairwise epsilon으로 악화를 허용하는 방식은 사용하지 않는다.

같은 feasible input 집합의 순서를 바꿔도 frontier set은 같다. 출력 정렬만 candidate ID로 고정한다. 동일 값의 서로 다른 candidate는 모두 남고, 동일 candidate ID 중복은 invalid input이다.

## 5. Report

ComparisonReport 필수 필드: `policy_ref/hash`, `cohort_digest`, `metric_definition_refs`, `candidate_states`, `excluded_reasons`, `dominance_edges`, `non_dominated_under_policy`, `overall_completeness`, `uncertainty_mode`, `allowed_claims`, 원본 metric references.

| 조건 | 전체 상태·출력 |
|---|---|
| Input/schema/unit 오류 | invalid_input, frontier 없음 |
| Cohort/method/profile/coverage/state-access 불일치 | incompatible_cohort, frontier 없음 |
| Required metric 누락 또는 constraint unknown | incomplete; 알려진 feasible subset frontier는 별도 표시, 전체 우월 주장 금지 |
| Feasible 후보와 알려진 constraint violation만 있음 | complete_within_policy_scope; infeasible 후보는 frontier 대상 밖 |
| Bound 중첩으로 dominance 없음 | 판정 수행은 complete, 양쪽을 non_dominated_under_policy에 유지; 실제 참값의 우열은 inconclusive |
| 후보 0개 | invalid_input/empty_population. 성공률 100%로 처리하지 않음 |

`non_dominated_under_policy`는 무한한 설계 공간의 최적 집합이라는 뜻이 아니다. 평가한 후보·policy·정보 접근·지원 범위에 한정한다.

## 6. P1 target와 diagnostic policy

`cmp-p1-workload-v1`은 TTFT/TPOT/output throughput/energy를 objective, power와 quality를 constraint로 가지는 합성 계약 검증 profile이다. 실제 target episode에서 해당 required metric이 생성되지 않으면 `incomplete`가 정답이다. P1 B300 성공을 위해 임의의 값을 채워 넣지 않는다.

Fixture의 power≤1000W, quality≥0.99 및 threshold 값은 **검증 산식을 시험하기 위한 합성값이며 사용자 예산·B300 설계 제약이 아니다**. 실제 target policy로 복사하지 않는다. 사용자가 performance budget을 지정하지 않은 현재 기본 설계는 power도 objective로 보존하고 임의의 수치 budget constraint를 추가하지 않는 것이다. 실제 target의 MetricDefinition/quality cohort/threshold와 native coverage를 binding한 새 policy revision이 필요하며, 아직 그 binding을 완료하지 않았다.

기존 native component probe에는 그 probe가 실제 산출하는 metric만 요구하는 별도 diagnostic policy를 사용할 수 있다. 그러면 allowed claim은 해당 component 범위로 제한하며, workload/B300 전체 비교를 통과했다고 보고하지 않는다. Native episode metric binding은 [p1-first-episode.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/episodes/p1-first-episode.md)가 기준이다.

## 7. Hypervolume

P1은 `hypervolume.enabled=false`로 고정한다. P3에서 추가할 때 objective subset·loss transform·normalization lower/upper·고정 reference point·constraint filtering·uncertainty 처리·algorithm/version을 모두 policy에 기록해야 한다. 다른 reference/normalization의 값을 같은 개선량으로 비교하지 않는다.

## 8. 필수 정답 사례

단위 변환 불변, 입력 순서 불변, missing metric의 전체 우월 금지, constraint violation과 dominated의 분리, bound 중첩, closed target 범위, epsilon cycle 반례, method/profile 불일치, empty population, malformed unit을 JSON fixture로 고정한다. 정답은 제품 비교 함수를 구현하기 전에 기록하며, runtime 결과로 정답표를 덮어쓰지 않는다.
