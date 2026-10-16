# SnapshotManifest v1: 감사·재생·현재 지식 재검토

상태: 설계 계약. Snapshot ID 하나로 서로 다른 재현 목적을 숨기지 않는다. [snapshot-manifest.schema.json](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/schemas/snapshot-manifest.schema.json)의 `purpose`와 `manifest_state`가 필수다.

## 1. 세 가지 목적

| purpose | 고정하는 것 | 다시 실행하는 것 | 허용되는 결론 |
|---|---|---|---|
| audit_decision | 당시 입력·근거 bundle·전체 rule 결과·native status·policy version·명시적 결정 | 원래 판단 자체를 다시 생성하지 않고 기록 검토 | 당시 무엇을 알고 어떤 판정을 했는지 |
| replay_original_inputs | 당시 workload/asset/recipe/toolchain/cost model/환경/seed/초기 상태와 input artifact | 원래 입력으로 선언된 native 실행 경로 | 같은 입력에서 결과가 어느 범위까지 재현되는지 |
| reevaluate_current_knowledge | 원래 design/run/metric은 보존, 새 KB·ClaimUse/Validation/Comparison 정책을 별도 고정 | 새 정책에 따른 분석·검증. 필요 시 새로운 run은 별도 proposal | 현재 지식으로 해석이 어떻게 달라졌는지 |

현재 지식 재검토는 새 analysis/decision ID를 만들고 `derived_from_snapshot`과 바뀐 dependency를 기록한다. 이전 run의 metric이나 당시 verdict를 덮어쓰지 않는다. 재검토·요약·Melete 재유입은 새로운 독립 실험이 아니다.

## 2. Manifest가 닫아야 하는 dependency

- source revision/span·권리/ACL policy와 원본 artifact hash.
- entity/asset/assembly/ModelVersion, tokenizer/chat-template, shape/dtype/layout, workload·timing/prefix/KV 의미.
- required-rule registry·ValidationProfile·ClaimUsePolicy·ComparisonPolicy의 ID/version/hash.
- 실제 사용한 EvidenceBundle, 전체 validator result set, committee raw votes/flags, invocation mode, DSE 네 판정 축.
- HAT/Melete/adapter source commit, dependency/environment lock, entrypoint와 argument/config hashes.
- unit별 producer·coverage·carry-forward/replacement provenance, information-access profile와 mutable state cutoff.
- raw event/metric/artifact, failure와 retry, Melete receipt/readiness observations, next proposal.

Graph/vector index 전체 bytes를 반드시 저장하는 대신 canonical corpus snapshot, projection version/watermark, 실제 사용한 검색 결과·rank·span을 보존한다. ANN 검색이나 외부 LLM을 다시 호출해 같은 결과가 나온다고 가정하지 않는다. 감사는 실제 사용한 bundle을 읽고, 검색 재현 실험은 별도 실행으로 다룬다.

## 3. State 접근과 시간

Manifest는 `design_mode`(offline/online), `workload_visibility`(full scenario/prefix), `controller_profile`(realizable/oracle), `state_access_policy`를 각각 가진다. Offline 설계자가 전체 workload trace를 참고하는 것과 online controller가 아직 생성되지 않은 RP state를 읽는 것은 다르다.

Realizable online decision의 각 사용 observation은 `observed_at <= decision_time`과 `available_at <= decision_time`를 모두 만족해야 한다. 미래 결과로 계산한 파생값도 원본의 availability cutoff를 계승한다. Oracle에서 future state를 허용했다면 같은 cohort의 realizable result로 승격할 수 없다. 원래 native profile과 adapter 해석을 둘 다 보존한다.

Offline-only 정보의 사용은 허용 조건을 명시한 design study일 수 있지만, online 실행 가능한 scheduler 성능이라는 주장에는 사용할 수 없다. Input trace 자체가 알려진 경우의 workload visibility도 별도 필드로 남긴다.

## 4. Digest와 closure

`closure`는 purpose별 typed reference-ID map이다. Audit에는 decision_record/decision_input/evidence_bundle/native_report/validation_report/policy_bundle, replay에는 run_manifest/workload/assembly/recipe/toolchain/initial_state/calibration/policy_bundle, current reevaluation에는 original_decision/original_design/original_run/current_knowledge/new_policy_bundle이 필수다. 각 ID는 dependency_refs 또는 policy_refs의 **동일 kind** record로 resolve되어야 한다. Dangling ID·kind mismatch·중복 ID는 invalid_snapshot_closure다. Captured 상태의 모든 required closure artifact에는 content hash가 있어야 하며 plan_template의 null hash를 실행 증거로 쓰지 않는다.

`semantic_validation_version=snapshot-semantic-validation-v1`은 reference join, digest, 현재 artifact resolution·ACL, 시간 cutoff, independence 검사를 필수화한다. JSON Schema 통과만으로 cross-reference·숫자 순서·authority를 검증했다고 보지 않는다.

Closure slot→artifact kind mapping도 고정한다. Audit의 decision_record/decision_input/evidence_bundle/native_report/validation_report/policy_bundle은 동일 이름의 kind다. Replay는 run_manifest→run_manifest, workload→workload, assembly→hardware_assembly, recipe→kernel_recipe, toolchain→toolchain_lock, initial_state→runtime_state_snapshot, calibration→calibration_profile, policy_bundle→policy_bundle이다. Current reevaluation은 original_decision→decision_record, original_design→design_point, original_run→run_manifest, current_knowledge→knowledge_snapshot, new_policy_bundle→policy_bundle이다. 같은 slot의 이름을 임의 type alias로 해석하지 않는다.

`temporal_access`는 run_monotonic_us clock의 typed decision/observation 기록이다. 각 decision_tick과 observation의 observed_at_tick/available_at_tick/source_ref/derived_from_observation_ids를 보존한다. Inline 기록 또는 hash가 고정되고 temporal-access-events-v1 schema를 가진 artifact reference를 허용한다. Artifact encoding은 전체 로그를 읽어 검증하며 summary/top-k로 줄이지 않는다. Realizable profile은 두 timestamp 모두 decision_tick 이하인지, 파생 observation이 dependency의 availability를 앞당기지 않는지 검사한다. Captured runtime profile에서 temporal 기록이 없으면 incomplete다.

Clock 값은 nonnegative finite decimal 문자열이며 분수 microsecond를 정수로 반올림하지 않는다. Native unit/value와 무손실 변환 provenance를 source artifact에 보존한다. Clock origin이 다르거나 무손실 변환을 확인하지 못하면 cutoff를 임의 비교하지 않고 incompatible_clock으로 표시한다.

각 artifact는 content SHA-256, byte length, media/schema version, producer 및 availability를 가진다. Git source는 repository·commit·path·blob identity를 기록한다. Tag/branch 이름만으로 immutable input을 고정하지 않는다.

Snapshot root digest의 `canonical-json-v1`은 ASCII object key의 사전순 정렬, UTF-8, 공백 없는 JSON separators, finite integer 또는 decimal-string 숫자, duplicate key 금지로 정의한다. Root digest 필드 자체와 외부 위치의 가변 URL은 계산에서 제외하고 content identity를 사용한다. 다른 canonicalization을 쓰면 별도 policy version이다.

`manifest_state=plan_template`이면 예상 reference를 기술할 수 있지만 실행 재현 증거가 아니다. `captured`는 required dependency와 content hash가 모두 고정된 상태다. Source가 삭제됐거나 특정 closed-model revision을 다시 사용할 수 없으면 availability에 원인을 남긴다. 같은 이름의 최신 artifact로 몰래 대체하지 않는다.

## 5. 권한과 보존

과거 snapshot의 ACL은 감사 근거다. 현재 접근 권한을 우회하는 authorization token이 아니다. 현재 권한과 retention policy를 먼저 검사한다. 삭제로 본문이 없으면 허용되는 hash·metadata로만 감사하고 exact replay는 `blocked_artifact_unavailable`로 표시한다. 법적 삭제와 WORM 정책의 충돌을 snapshot으로 무시하지 않는다.

## 6. Independence

모든 observation은 `primary_observation_id`, `lineage_root_id`, `independence_class`를 가진다. Class는 original_measurement, independent_replication, deterministic_replay, reinterpretation, duplicate_copy 중 하나다. 단순히 새 event ID나 새 Insight ID가 생겼다고 independent_replication으로 지정하지 않는다.

검증 횟수는 검증된 primary observation lineage의 독립성 정책으로 계산한다. 동일 trace의 재수집, Melete duplicate, 현재 KB 재해석, source 재인용은 같은 root로 묶는다. 새로운 실제 측정은 별도 실행 provenance를 요구한다. 같은 deterministic simulation을 반복한 횟수로 hardware uncertainty가 줄었다고 주장하지 않는다.

`independent_replication`에는 primary_measurement_run_ref, replicates_run_ref, new_capture_ref, assessment_ref와 replicates_lineage_root_id가 필수다. 새 primary run과 기존 run, 새 lineage root와 원래 root가 각각 달라야 한다. 참조는 실제 device capture와 권한 있는 independence assessment의 typed/hash-bound artifact로 resolve되어야 한다. 단순한 새 UUID나 self-declared flag는 충분하지 않다. 같은 root/run을 독립 복제로 표시하거나 assessment가 없으면 invalid_independence다.

Manifest의 availability/authorization epoch는 capture 당시 기록이다. 현재 삭제·권한 상태는 별도 resolution/access report로 확인하고 원본 manifest를 수정하지 않는다. Snapshot의 과거 allow를 현재 실행 권한으로 사용하지 않는다.

## 7. 정답 사례

| Case | 입력 | expected_decision |
|---|---|---|
| SNAP-01 | 과거 bundle/policy/native result가 보존되고 현재 열람 권한 있음 | audit_available; 원래 judge 재호출 불필요 |
| SNAP-02 | required original artifact 하나가 삭제됨 | replay_blocked; latest artifact로 교체 금지 |
| SNAP-03 | 같은 design에 새 KB/policy로 검토 | new_analysis_required; old verdict 불변 |
| SNAP-04 | online realizable decision이 available_at 이후의 state 사용 | information_access_violation |
| SNAP-05 | offline full workload를 참고하되 online controller는 과거 state만 사용 | allowed_with_declared_scope |
| SNAP-06 | Oracle trace를 realizable cohort에 넣음 | incompatible_profile |
| SNAP-07 | 원래 ACL은 allow였으나 현재 revoke | access_denied; hash metadata도 현재 정책 적용 |
| SNAP-08 | 같은 source/experiment/Insight가 Melete를 거쳐 재유입 | same_independence_root; independent count 증가 0 |

이 표는 미래 구현의 gold다. 현재 artifact 감사와 JSON schema 검사 외에 실제 HAT/Melete replay를 실행하지 않는다.
