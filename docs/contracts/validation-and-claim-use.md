# 검증 결과와 Claim 사용 계약

이 문서는 설계 후보를 탐색할 때의 시뮬레이션 허가, 검증 상태, 리뷰 완결성, 물리 실현 가능성을 서로 독립된 축으로 기록하는 P0 계약이다. native HAT 결과는 입력 증거의 provenance로 보존하되 DSE 검증의 대체값으로 해석하지 않는다. 프로파일과 fixture의 기대값은 구현 전 고정된 oracle이다.

## 네 가지 독립 축

모든 평가 episode는 아래 네 축을 각각 기록한다. `simulation_ready`, scope verdict, 추천 점수 또는 단일 `ready` 필드로 다른 축을 추론하지 않는다.

| Axis | Values | 의미 |
|---|---|---|
| `simulation_permission` | `denied`, `exploratory_only`, `validated_profile_only` | 이 episode에서 허용되는 다음 실행 범위. 이는 실행 시스템에 대한 허가 입력이며, 실제 실행은 별도 policy enforcement가 필요하다. |
| `validation_verdict` | `reject`, `incomplete_unknown`, `validated_within_declared_scope`, `not_evaluated` | 고정된 ValidationProfile에 대한 결정론적 결과. `not_evaluated`는 검증 자체가 호출되지 않은 경우에만 쓴다. |
| `review_completeness` | `complete`, `partial`, `all_abstain`, `not_run` | 요구된 reviewer seat·scope가 실제 응답했는지 나타낸다. 승인은 완결성의 증거가 아니다. |
| `physical_feasibility` | `feasible_within_declared_scope`, `infeasible`, `unknown`, `not_assessed` | 명시된 모델·근거 범위 안의 물리 가능성. 시뮬레이션 허가나 모델 출력만으로 `feasible`을 만들지 않는다. |

축마다 `basis_refs`, `scope`, `profile_id/version` 또는 `unknown_reasons`를 기록한다. `not_assessed`와 `unknown`을 구분한다. 전자는 검토하지 않았고, 후자는 검토했으나 근거가 부족하거나 상충한다.

## Native HAT 결과의 보존과 매핑

고정된 HAT 입력은 `hat-schema` commit [`a874d0c2e277e8838ecd95ba16679b774646408e`](https://github.com/jimmylegendary/hat-schema/tree/a874d0c2e277e8838ecd95ba16679b774646408e)다. 해당 구현은 네 scope의 verdict, vote, findings와 `simulation_ready`를 반환하며 `simulation_ready`는 scope가 reject되지 않았다는 native 조건이다. [`convene()`의 signature, 기본값, deterministic findings/votes](https://github.com/jimmylegendary/hat-schema/blob/a874d0c2e277e8838ecd95ba16679b774646408e/hat_schema/verify/committee.py#L385-L407), [floor reject, 전원 abstain concern, scope verdict](https://github.com/jimmylegendary/hat-schema/blob/a874d0c2e277e8838ecd95ba16679b774646408e/hat_schema/verify/committee.py#L415-L449).

Adapter는 native 결과를 다음 provenance 봉투에 원형 보존한다.

```json
{
  "provider": "hat-schema",
  "commit": "a874d0c2e277e8838ecd95ba16679b774646408e",
  "invocation_mode": "backend_invoked",
  "backend_configured": true,
  "native_report": {
    "scopes": {"soc": {"verdict": "approved_with_concerns", "votes": {"memory-reviewer": {"verdict": "abstain", "findings": []}}, "findings": []}},
    "simulation_ready": true,
    "revision_requests": [],
    "ppa": {"metrics": {}, "headline_verdict": "not_included_in_fixture_example"}
  },
  "normalized_projection": {
    "scope_verdicts": {"soc": "approved_with_concerns"},
    "votes": {"soc": {"memory-reviewer": "abstain"}},
    "simulation_ready": true,
    "findings": []
  },
  "captured_at": "2026-10-17T00:00:00Z"
}
```

위 `native_report`는 shape를 설명하는 축약 예시다. 실제 어댑터는 HAT가 반환한 전체 native object를 `native_report`로 변경 없이 보존해야 하며, `scopes`, `revision_requests`, `ppa`, 추가 version-specific 필드를 projection으로 덮어쓰지 않는다. `normalized_projection`은 DSE 분류를 위한 별도 계산값이다. validation fixture의 `native_result_projection`은 synthetic 축약 입력이고 캡처된 raw HAT report가 아니다.

`invocation_mode`는 `backend_invoked`, `deterministic_fallback`, `not_run`, `unknown` 중 하나다. native 함수 호출 시 `backend=None`은 reviewer backend를 호출하지 않은 상태와 다르다. 이는 `_deterministic_vote(det, judgments)`가 각 expert 자리에서 실행된 `deterministic_fallback`이다. backend가 설정되어 호출됐지만 비어 있는 응답 또는 모두 abstain한 경우는 `backend_invoked`와 `all_abstain`으로 보존한다. adapter는 이 둘을 같은 “AI review 완료”로 합치지 않는다. DSE profile이 요구하는 evidence-backed reviewer 응답이 없는 deterministic fallback은 native vote를 보존하되 DSE `review_completeness=partial`로 본다.

Native `simulation_ready=true`는 `validated_within_declared_scope`나 물리 가능성을 증명하지 않는다. native verdict는 프로파일 규칙·입력 완전성·review 요구사항을 대신하지 않는다. 어댑터가 네 축 중 일부를 계산할 수 없으면 `not_evaluated`, `not_run`, `not_assessed` 또는 `unknown`을 그대로 둔다.

## ValidationProfile과 결정론적 verdict

ValidationProfile은 `profile_id`와 증가 가능한 `profile_version`을 가진 고정된 검사 계약이다. `digest_contract=canonical-json-v1-excluding-profile_digest`에 따라 profile object에서 `profile_digest`만 빼고 canonical JSON SHA-256을 계산한다. key ordering, UTF-8, compact separators와 숫자 표현은 [snapshot-contract.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/snapshot-contract.md#L39)의 `canonical-json-v1`을 따른다. digest, design/input snapshot, rule-set version을 평가 결과에 묶는다. evaluation 시작 전에 `frozen`이 아니거나 digest가 누락/불일치하면 검증을 시작하지 않고 `incomplete_unknown`으로 기록한다. Profile version이 달라지면 필드를 변경하지 않은 것처럼 보이더라도 새 digest를 계산한다.

`frozen`은 profile bytes가 고정되었다는 뜻이지 실행 가능한 profile로 활성화됐다는 뜻이 아니다. Normative activation 전에 모든 `required_inputs[].schema_ref`와 version이 정확한 불변 artifact로 resolve되어야 하며, activation record는 각 schema의 content SHA-256을 고정해야 한다. 모든 required rule ID/version, applicability predicate ID/version, aggregation/evaluator implementation도 정확한 구현 version과 content SHA-256으로 resolve하고 같은 activation evidence에 결속한다. 참조가 missing/unresolved/unavailable이거나 version/hash가 불일치하면 profile은 activate되지 않는다: `validation_verdict=incomplete_unknown`, 그 profile에 의존하는 실행은 exploratory를 포함해 `simulation_permission=denied`다. registry의 최신 schema나 evaluator로 조용히 대체하지 않는다.

프로파일은 다음 집합을 전부 명시한다.

- 적용 범위와 typed applicability predicate, 각 predicate의 버전·필요 입력·결과 상태. 조건이 누락되거나 판정 불능이면 applicable 여부도 `unknown`이다.
- profile의 **전체** required rule ID/version 집합과 각 규칙의 applicability, blocking class (`execution_semantic`, `physical_feasibility`, `advisory`), 필요한 evidence/input type. UI의 top-k 요약은 검사 집합이 아니다.
- 필수 input ID/schema/version/snapshot 정책, reviewer scope/seat/최소 응답 및 abstention 처리, 각 review requirement의 `blocks_exploration`, coverage denominator, 명시적 out-of-scope 항목.
- aggregation version과 profile hash. evaluation은 모든 required rule에 대해 `pass`, `fail`, `unknown`, `error`, `not_applicable` 중 정확히 하나를 산출한다. profile 밖 규칙의 생략은 적용 제외로 간주하지 않는다.

집계는 아래의 우선순위를 고정한다.

1. 적용 가능한 required rule 하나라도 `fail`이면 `reject`. top-k evidence summary가 해당 규칙을 보여주지 않아도 결과는 바뀌지 않는다.
2. applicable required rule의 입력·판정·evidence가 빠졌거나 상태가 `unknown`/`error`이면 `incomplete_unknown`. applicability 자체가 미해결인 경우도 여기에 포함한다.
3. required reviewer coverage가 부족하거나 필수 응답이 abstain이면 review는 `partial` 또는 `all_abstain`; ValidationProfile이 요구한 검토가 완료되지 않은 이상 verdict는 `incomplete_unknown`이다.
4. 모든 required rule과 input이 완전하고, 적용 규칙이 모두 pass이며, required review/coverage가 완료된 경우에만 `validated_within_declared_scope`. `not_applicable`은 profile의 machine-readable predicate와 근거가 함께 참일 때만 분모에서 제외한다. 적용 규칙이 0개인 vacuous pass는 금지한다.

검증 실패(`reject`)는 execution을 거부한다. 필수 execution/semantic check가 unknown, 누락 또는 error이면도 실행 권한을 주지 않는다. `incomplete_unknown` 상태에서도 **실험적 탐색 실행**은 별도 허용할 수 있다. 모든 blocking execution/semantic check가 통과하고 profile이 요구한 input/applicability가 확보되어야 한다. required reviewer seat가 미응답/abstain이어도 validation verdict는 계속 `incomplete_unknown`이다. 다만 해당 seat의 profile `blocks_exploration=false`일 때는 이 review gap이 exploratory permission을 막지 않는다. profile이 허용한 비실행 물리/비용/열 feasibility unknown만 assumption, 책임자, 재검증 시점, claim/evidence reference로 묶어야 한다. review gap도 소유자와 재검토 시점을 선언해 기록한다. `blocks_exploration=true`인 미완료 reviewer requirement는 실행을 막는다. 어떤 경우에도 이 예외는 검증 통과나 `validated_profile_only` 권한을 만들지 않으며, execution semantics 또는 알려진 required rule의 실패를 가정으로 우회할 수 없다.

`simulation_permission` 정책은 다음과 같다.

- execution/semantic required rule이 fail, unknown, missing, error면 `denied`.
- 해당 blocking rules가 모두 통과하고, 미완료 reviewer requirement마다 profile의 `blocks_exploration=false`이며, profile상 남은 unknown이 허용된 비실행 feasibility이고 모든 unknown이 명시된 assumption/owner/retest와 연결되면 `exploratory_only`.
- 모든 required rules, inputs, review coverage가 통과/완료되고 물리 가능성이 profile 범위의 근거로 확인된 경우에만 `validated_profile_only`.
- 위 어느 조건도 입증되지 않거나 검증을 하지 않았으면 `denied`. 승인된 profile-only 결과는 실행 권한 시스템이 profile/version과 대상 design snapshot을 다시 확인해야 한다.

## ClaimUsePolicy

Claim의 출처 권위와 지식 종류, epistemic state는 별도 필드다. policy 판정 시 claim과 요청된 target의 scope, 대상 revision, 단위, 유효 시간/조건, evidence chain을 함께 비교한다. scope match는 exact/contained/partial/mismatch/unknown 중 하나를 계산하고 자유 문장만으로 `exact`를 주장하지 않는다.

| Use | 허용 게이트 |
|---|---|
| `hard_constraint` | 해당 target에 적용되는 normative source/의무 clause, 정확한 version, 정확히 호환되는 scope와 typed unit, direct evidence 및 applicability 판정이 모두 확인되어야 한다. 공급업체가 관측한 기존 제품 값은 새 architecture의 보편적 상한/하한이 아니다. |
| `verified_parameter` | 같은 target scope/revision와 조건에서 재현 가능하게 관측되었거나 profile 안에서 검증된 typed 값이어야 한다. source verified 상태만으로 검증된 parameter가 되지 않는다. |
| `soft_prior` | 신뢰 가능한 출처와 부분 적용 가능성이 있지만 대상의 exact validity가 입증되지 않은 정량·정성 정보. uncertainty와 원래 scope를 함께 유지한다. |
| `candidate_generation` | hypothesis, analytical candidate, 부분 근거를 아이디어 생성에 쓰되 사실·제약으로 승격하지 않는다. 생성된 candidate는 별도 검증을 거친다. |
| `exploratory_reference` | 실험 설계나 탐색의 참고. provenance, 불확실성, scope mismatch를 결과에 표시하고 acceptance/feasibility gate에 사용하지 않는다. |

`source_verified`는 출처·추출이 확인된 상태이며 claim의 참이나 보편 적용을 뜻하지 않는다. 특히 source_verified `hypothesis`는 hypothesis로 남는다. 이 상태의 일부 적용 vendor hypothesis는 `soft_prior`로 사용할 수 있지만, 원래 scope와 uncertainty를 보존하는 advisory에 한한다. `hard_constraint`와 `verified_parameter`로 승격할 수 없다. ClaimUsePolicy의 결정은 요청된 use별 `allow`, `deny`, `abstain`이며 `allow`가 다른 use 권한을 암묵적으로 열지 않는다. 승인 근거에는 적용된 rule ID와 증거/범위 판정이 필요하다.

P0의 concrete ClaimUsePolicy는 [validation-cases.json](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/fixtures/p0/validation-cases.json)의 `claim_use_policy` object에 ID/version별로 고정한다. Object에는 다섯 gate와 네 example이 모두 들어 있으며, sibling `claim_use_policy_digest`는 전체 policy object의 `canonical-json-v1` SHA-256이다. 각 Claim 사례는 case root에서 동일한 policy ID/version/hash를 참조하므로 runtime에 gate default나 builder 선택이 없다.

## 고정 fixture와 검증 범위

[validation-profile.schema.json](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/schemas/validation-profile.schema.json)과 [claim-use-policy.schema.json](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/schemas/claim-use-policy.schema.json)은 typed wire contract이고 [validation-cases.json](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/fixtures/p0/validation-cases.json)은 엔진 구현 전에 고정한 oracle이다. Fixture wrapper의 `activation_status=synthetic_not_executable`은 이 안의 frozen profile이 실행 가능한 제품 profile이 아님을 명시한다. 이 profiles는 합성 aggregation oracle이며 deployable/activated B300 profile이 아니다. `https://example.invalid/...` schema refs는 의도적인 synthetic placeholder이고 실제 B300 schema를 주장하지 않는다. `rule_results` 값은 oracle case의 합성 입력이며 native 또는 DSE validator를 실행한 출력이 아니다. DSE-R01…DSE-R13은 이 fixture의 **합성 DSE profile 규칙 ID**이며 HAT native R1–R11이나 HAT rule registry를 가리키지 않는다. 특히 R13은 required, execution-blocking rule로 fixture에서 명시한다.

R13 failure case는 모든 13개 규칙이 평가되었지만 사용자가 받은 12개 항목 evidence summary에서 R13이 빠진 상황이다. 결과는 요약이 아닌 complete profile evaluation을 따라 `reject`/`denied`여야 한다. 12개를 넘긴 표시/검색 limit이 계약 coverage denominator를 줄일 수 없다. Oracle은 pass, fail, unknown/missing, all-abstain, `backend=None` deterministic fallback, 탐색 허가와 validated status 분리, ClaimUsePolicy의 source/state/scope/unit/version gates를 포함한다. 이 fixture를 만족하는 runtime은 아직 구현·실행되지 않았다.
