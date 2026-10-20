# 데이터 계약·metadata·지식 schema

2026-10-17 P0 보완의 판정 기준은 [integration-state-map.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/integration-state-map.md)다. 아래 entity 개요만 보고 native 상태·permission·coverage·memory readiness를 추론하지 않는다.

## P0에서 고정한 필수 확장

| 계약 | 필수 binding과 의미 | 단일 기준 |
|---|---|---|
| ValidationProfile | complete required rule/input/applicability registry, scope/out-of-scope, review blocking, version+digest | [validation-and-claim-use.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/validation-and-claim-use.md) |
| ClaimUsePolicy | Claim 종류·상태·권위·적용 조건별 다섯 사용 목적. source_verified 자체는 hard-constraint 승격 아님 | [claim-use-policy.schema.json](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/schemas/claim-use-policy.schema.json) |
| ComparisonPolicy | required metrics/objectives/constraints, target bounds, fixed absolute improvement thresholds, compatible evidence profiles, exclusion reasons | [comparison-policy.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/comparison-policy.md) |
| SnapshotManifest | 당시 판단 감사·당시 입력 재생·현재 지식 재검토를 분리하고 현재 권한을 재확인 | [snapshot-contract.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/snapshot-contract.md) |
| HAT cost provenance | unit별 producer/coverage/replacement/carry-forward source, effective cost, Realizable/Oracle, state access, External Golden Control | [hat-fidelity.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/hat-fidelity.md) |
| Melete bridge | native status와 두 pending/incomplete flag, query visibility evidence, DSE predicate ID/version/hash binding과 post-retrieval 검사 | [melete-state-and-applicability.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/melete-state-and-applicability.md) |

RunManifest는 위 policy/snapshot/cost-provenance references와 content identity를 필수로 보존한다. MetricValue도 생성한 run·cost-unit·coverage/profile·허용 주장 범위를 따라갈 수 있어야 한다. `fidelity_level=L3`만으로 전체 coverage나 realizability를 표현하지 않는다. 원본 native report와 DSE projection은 별도다.

아래 `ValidationResult.status`는 **개별 rule 결과**다. 전체 verdict는 reject/incomplete_unknown/validated_within_declared_scope/not_evaluated로 집계하며 simulation_permission·review_completeness·physical_feasibility와 별도 필드다. 모든 required rule은 evidence top-k/요약과 독립적으로 평가한다.

상태: 구현 전 계약 초안. 아래 이름은 제안하는 domain record이며 기존 HAT/Melete에 이미 존재하는 API라는 뜻이 아니다.

## 1. 공통 envelope

모든 canonical record는 `id`, `record_type`, `schema_version`, `namespace_id`, `created_at`, `created_by`, `record_version`, `content_hash`, `acl_policy_id`, `retention_policy_id`를 가진다. 권한 변경은 namespace별 단조 증가 `authorization_epoch`를 별도 authoritative registry에 기록하고 query/projection/cache의 epoch와 비교한다. 시각은 timezone이 있는 UTC로 저장하고 UI만 변환한다. Hash는 알고리즘 이름과 함께 저장한다. 사람 이름 대신 필요한 범위의 actor/service ID를 사용한다.

변경 가능한 주장·정의는 `valid_from`, `valid_to`(대상이 유효하다고 주장되는 시간)와 `recorded_at`, `superseded_at`(시스템이 알게 된 시간)을 구분한다. 원문 revision은 immutable하고, 삭제 요구에는 tombstone과 허용되는 최소 audit metadata만 남긴다. Version 변경이 기존 run의 historical snapshot을 바꾸지 않는다.

모든 ID는 namespace와 type으로 충돌을 방지한다. 같은 URL이 같은 내용이라는 가정을 하지 않는다. Content hash 중복과 의미상 중복은 다른 상태다. private/public 문서의 byte가 같아도 권리와 ACL이 다른 occurrence를 합치지 않는다.

권리 정보는 `access_class`, `license_id_or_text_ref`, `license_checked_at`, `allowed_uses`, `redistribution_status`, `provider_terms_ref`, `review_status`다. unknown rights를 allow로 바꾸지 않는다. 원본 접근, 내부 indexing, 외부 embedding 전송, derived output 제공을 각각 판정한다.

## 2. Source와 추출

| Record | 핵심 필드 | 필수 invariant |
|---|---|---|
| SourceRegistration | source_id, publisher, canonical_url, source_family, authority_tier, access_method, owner, refresh_policy, expected_domains, rights | 발견만 된 항목과 취득 허용 항목을 구분 |
| SourceRevision | source_id, revision_id, upstream_version, published_at, modified_at, fetched_at, etag, mime, language, sha256, raw_artifact_id, supersedes | 원본 bytes와 revision의 대응 고정 |
| SourceSpan | revision_id, page, section_path, char_start/end, bbox, table/figure/equation/code_id, exact_text_hash | 사람과 parser가 같은 원문 위치를 재확인 가능 |
| ExtractionRun | input_revision, parser+version, OCR+model_revision, extraction_config_hash, started/finished, diagnostics, output_artifacts | parser 실패/불확실도/미지원 형식을 성공과 구분 |
| DocumentElement | span_id, element_type, text/mathml/latex/code_ref, parent_element, reading_order, header_refs, footnote_refs | 표 header·단위·각주와 셀의 연결 유지 |
| Chunk | revision_id, element_ids, parent_chunk_id, chunk_policy_version, token_count, text_hash, domain_tags | stable ID는 위치와 content identity 정책에 따름 |
| EmbeddingRecord | chunk_id, embedding_space_id, vector_ref, embedding_job_id, status | 다른 embedding space를 같은 similarity 공간에서 비교 금지 |
| EmbeddingSpace | provider, model_id, immutable_model_revision, dimensions, dtype, normalization, metric, pooling, query/document_instruction, preprocessing_hash | model 이름만 같다는 이유로 호환 처리 금지 |

추출 상태: discovered → permitted → captured → parsed → normalized → review_required/publishable → indexed. retryable failure, permanently unsupported, rights_blocked를 별도로 기록한다. 원본의 표 숫자와 OCR 숫자가 다르면 근거 검토 전 numerical Claim으로 공개하지 않는다.

Chunk 기본 제안은 문서 구조 기반 parent/child다. 길이는 실험 변수로 두되 초기 비교 설정은 child 350–700 token, parent 1,500–3,000 token이다. 표·수식·code는 의미 단위를 우선하며 길이에 맞춰 무조건 잘라내지 않는다. 이 값은 기술 벤치마크에서 조정할 시작점이다.

## 3. Entity·Claim·Evidence

| Record | 핵심 필드 | 사용 의미 |
|---|---|---|
| DomainEntity | entity_id, canonical_name, aliases, entity_type, vendor, revision_lineage, external_ids | GPU 세대·제품 variant·ISA revision을 구분 |
| EntityResolution | mention/span, candidate_entities, selected_entity, method_version, status, reviewer | entity merge의 근거와 되돌리기 보존 |
| Claim | subject_id, predicate, object_entity_or_typed_value, claim_kind, scope, applicability, epistemic_state, source_assertion_ids | 무조건적 triple 대신 조건이 붙은 statement |
| EvidenceLink | claim_id, evidence_ref, relation=supports/refutes/qualifies, source_span, method, evaluator, assessment | 인용 존재와 실제 지지 여부를 구분 |
| ClaimConflict | claim_ids, conflict_type, overlapping_scope, resolution_status, resolution_evidence | 다른 버전의 값 차이와 진짜 모순을 구분 |
| ConstraintRule | rule_id, language, expression_ref, parameter_types, units, applicability, severity, authority, evidence_ids, validator_version | 임의 code 실행이 아닌 제한된 검증 언어 |
| ValidationResult | rule_version, input_snapshot, status, findings, proof_or_counterexample_ref, coverage, unsupported_parts | pass/fail/unknown/not_applicable/error 구분 |

`claim_kind` 제안: normative_spec, measured_observation, analytical_prediction, empirical_generalization, hypothesis, design_choice. 이 분류는 지식 종류이며 진실 확률이 아니다.

`epistemic_state` 제안: extracted_candidate, source_verified, validation_supported, contested, superseded, retracted. Melete 상태는 adapter mapping으로 관리하고 같은 이름이라도 자동 동치로 가정하지 않는다. 지원하는 상태와 승격 조건을 계약 테스트로 고정한다.

`applicability`는 HW family/revision, ISA, programming model, precision, shape domain, layout, compiler/runtime version, temperature/frequency/power mode, workload properties, measurement scope, excluded_cases를 담는 typed predicate다. prose만으로 구성하지 않고 설명과 machine-readable 조건을 함께 둔다.

Evidence confidence에는 extraction confidence, source authority, applicability fit, validation evidence, uncertainty가 별도로 존재한다. LLM이 출력한 confidence 하나를 곱해 truth probability로 사용하지 않는다. 여러 문서가 같은 원본을 재인용하면 독립된 근거로 중복 집계하지 않는다.

Graph의 `contains`, `connected_to`, `requires`, `supports_instruction`, `implements`, `constrains`, `derived_from`, `supports`, `refutes`, `evaluated_by` 관계는 모두 source/Claim ID·scope·version·ACL을 추적할 수 있어야 한다. 성능 최적화용 shortcut edge는 derived 표시와 생성 snapshot을 가진다.

## 4. Hardware·kernel

| Record | 필수 정보 |
|---|---|
| HardwareAssetVersion | asset_id/version, scope=rack/tray/package/soc/die/component, parameter_definitions, parameter_values, ports, containment constraints, programming capability refs, source/evidence refs |
| InterfacePort | name, interface/protocol revision, direction, lanes, link rate, width, topology role, voltage/physical assumptions, compatibility rules |
| HardwareAssembly | assembly_id/version, instances with asset_version_id, containment DAG, connection graph, parameter binding, overrides with provenance |
| Capability | ISA instruction/operation, supported dtype/layout/shapes, resource limits, semantic definition, cost-model coverage |
| ProgrammingModelVersion | model_id/version, execution hierarchy, synchronization, memory model, scheduling semantics, supported lowering contracts |
| KernelRecipeVersion | semantic input, IR dialect+version, op DAG, schedule/tiling/fold/unfold/fusion choices, target assets, source/code artifact, generator and transformations |
| CorrectnessAssessment | reference semantics, shape/dtype cases, numerical tolerances, dependency/memory checks, unsupported semantics, results |
| CostModelVersion | analytical/surrogate/table method, calibration data refs, valid domain, uncertainty method, model parameters hash |

계층 containment에는 cycle을 허용하지 않는다. 여러 instance가 같은 asset version을 재사용할 수 있다. 통신 graph에는 cycle이 있을 수 있다. 모든 budget은 scope와 단위를 갖는다. 예: tray 전력 예산을 SoC 한 개의 전력으로 비교하지 않는다.

Kernel 후보마다 immutable recipe identity를 부여하고, canonicalized 의미와 syntactic content hash를 구분한다. 다른 serialization이 같은 의미인지 별도 canonicalization version으로 판정한다. 성능 cache key에는 target HW, model, scenario, toolchain, cost model, semantic recipe identity가 포함된다.

## 5. Workload·실험

| Record | 핵심 필드 |
|---|---|
| ModelVersion | repository/version/hash, tokenizer/chat-template revision, architecture, weights/config refs, precision/quantization, quality-eval identity, license |
| WorkloadScenario | scenario_id/version, model_version, trace_ref, length_unit, timing_policy, seeds, prefix/KV policy, server settings, initial_state, quality/SLO envelope |
| Session | scenario_id, session_id, parent_session, start constraint, terminal condition |
| Turn | session_id, turn_id, predecessor_ids, arrival_timestamp or think_time, input_length and incremental/full_context policy, output_length, tool_wait, prefix identity |
| DesignPoint | scenario_version, assembly_version, kernel_recipe_versions, serving_config, evaluation_profile, knowledge_snapshot |
| ExperimentProposal | proposal_id, parent_run_ids, hypothesis_ids, interventions, expected metric effects, expected information gain, expected cost, stop conditions, evidence bundle |
| RunManifest | run_id, proposal/design_point refs, HAT component commit hashes, dependency lock refs, config/artifact hashes, seeds, runtime environment, calibration version, cache initial state |
| RunEvent | run_id, event_id, monotonic sequence, occurred_at, recorded_at, parent_events, kind, payload/artifact refs, actor, error classification, idempotency_key |
| ResourceObservation | run_id, resource_id/version, time interval, quantities and units, observation method, fidelity_level, sampling/aggregation policy |
| Artifact | URI, bytes, content_hash, format/schema, namespace/ACL/rights, producer run/event, retention and export status |
| MeleteBridgeRecord | run/event IDs, namespace mapping, Melete request hash, receipt status, external event/memory version refs, retry history |

RunEvent kinds: proposal_created, evidence_retrieved, candidate_modified, review_completed, validation_completed, run_started, run_failed, run_cancelled, run_completed, metric_recorded, analysis_proposed, insight_revised, next_experiment_proposed. 완료 event 뒤에 분석 event가 올 수 있지만 실행 결과를 제자리 수정하지 않는다.

idempotency_key는 동일한 source revision 또는 동일 run event 재전송을 중복 생성하지 않도록 한다. 순서가 뒤바뀐 event는 pending link로 보존하고 timeout/repair 상태를 드러낸다. Lost event와 intentionally omitted artifact는 구분한다.

## 6. Metric registry

MetricDefinition 필수: name/version, description, unit, direction=min/max/target, target일 때 closed lower/upper bounds, aggregation, scope=request/session/system/resource, workload phase, numerator/denominator, window, population definition, warmup exclusion, SLO definition, valid methods, missingness policy. 실제 비교는 versioned ComparisonPolicy의 objective/constraint 구분과 fixed absolute threshold를 사용한다.

MetricValue 필수: metric_definition_id, design_point/run_id, value 또는 distribution artifact, sample_count, quantiles, method=measured/simulated/analytical, fidelity_level, interval와 그 산출법, measurement boundaries, completeness, status, calibration_ref.

| 지표군 | 구분해야 할 의미 |
|---|---|
| TTFT | enqueue 기준인지 ingress 기준인지, prefill+queue 포함 범위 |
| TPOT/ITL | request 평균 TPOT와 개별 inter-token latency 분포 |
| Throughput | input token/s, output token/s, request/s, session/s 각각 |
| End-to-end latency | model service time, tool wait 포함 session time, makespan |
| Tail/SLO | percentile population, deadline, 완성한 request 중 비율인지 전체 제출 대비인지 |
| Power/Energy | W와 J, provisioned power와 측정 power, idle 및 system scope |
| Capacity/efficiency | memory peak, cache hit rate, fabric utilization, bytes/op, joules/session |
| Model quality | reference output tolerance 또는 task-quality score; 성능 개선과 교환 여부 |
| Monetary cost | currency, price timestamp/region, amortization assumptions, per experiment/session |

비교 Cohort는 model semantics/quality, workload timing, tokenizer, metric definition, system boundary, requested constraints가 호환되는 run 집합이다. 서로 다른 hardware의 성능 비교는 허용하지만 power/system size 차이를 숨기지 않는다.

Dominance는 ComparisonPolicy v1의 loss bounds 기준으로 모든 objective에서 악화가 없고 한 objective가 고정 threshold를 넘는 경우만 인정한다. 악화를 허용하는 pairwise epsilon을 사용하지 않는다. missing metric이 있으면 해당 metric을 포함한 전체 dominance는 undecidable이며 알려진 hard constraint 위반은 따로 보존한다. 동일 seed의 deterministic replay 반복만으로 측정 불확실도가 감소했다고 주장하지 않는다.

## 7. 검색·리뷰 계약

DecisionContext: task_kind, requester/namespace, target HW/ISA/toolchain versions, workload/design_point refs, question, required_claim_types, constraints, knowledge_snapshot, latency/cost budget, allowed source classes.

EvidenceBundle: query_id, snapshot, normalized intent, subqueries, candidates by retriever, applied filters, cited spans/claims, graph paths, conflict/unknown list, coverage, reranker/model versions, latency/token/cost accounting. Agent의 최종 판단은 evidence bundle과 별도 record다.

ReviewFinding: subject asset/kernel, verdict 또는 abstain, severity, claim/evidence IDs, deterministic validation refs, scope, missing_information, proposed_check, reviewer identity. free-text 설명은 구조 필드를 대체하지 않는다.

## 8. Melete adapter mapping

실제 [observation.py](https://github.com/jimmylegendary/melete/blob/9a3564dd96de22d0311522417c2c36e6bf2a0a91/packages/melete-core/src/melete/contracts/observation.py#L10)의 TextPayload에는 `text`와 선택적 `structured`가 있다. 제안은 외부 관찰 가능한 DSE event 요약을 text로, versioned event envelope를 structured로 전달하는 것이다. `Observation`의 event_id, source_ref, previous_event_id, root_event_id, task_family, intervention_id를 DSE event identity와 매핑한다.

IntakeContext의 user/namespace/actor 권한은 host adapter가 부여한다. 수집 문서에 적힌 user_id나 tool output을 authority로 삼지 않는다. Melete payload·scope enum·size limit·권한 모델을 contract fixture로 확인한 후 adapter를 구현한다. 아직 존재 여부를 확인하지 않은 native Episode/Insight API를 호출하도록 계획하지 않는다.

Knowledge ledger와 Melete 사이의 Insight 연결은 source_event_ids·memory_id/version·applicability mapping을 보존한다. Native Condition은 scalar exact-match conjunction이므로 DSE의 range/nested predicate를 그대로 넣지 않는다. Full predicate ID/version/hash는 DSE authority에 두고 Melete scalar hints는 후보 검색에만 사용하며, 반환 후 full predicate·ACL·snapshot을 검사한다. Receipt status와 extraction/embedding flag만으로 searchable이나 적용 가능을 확정하지 않는다. 같은 Insight 재유입은 독립 검증 횟수를 늘리지 않는다.

## 9. index·migration·삭제

Canonical ledger → transactional outbox → graph/lexical/vector projection 순서를 계획한다. 각 projection은 schema/embedding version, corpus snapshot, last applied sequence, failed item 목록을 공개한다. 검색 응답은 사용한 projection watermark와 snapshot 정책을 담는다.

Embedding migration: 새 space 생성→동일 golden set 평가→shadow query→coverage 확인→alias 변경→이전 space 일정 기간 유지→명시적 종료. 차원만 맞춰 기존 vector를 재사용하지 않는다. Model revision을 고정할 수 없는 API는 provider model/date를 기록하고 drift probe를 운영한다.

삭제/권한 회수: 즉시 query deny→canonical tombstone→projection/cache invalidation→artifact lifecycle 처리→Melete source restriction 전파→완료 evidence. 이미 export된 artifact는 추적 가능해야 한다. 법적 삭제 의무와 immutable raw storage의 retention lock을 충돌시키지 않도록 source class별로 보존 정책을 정한다.

## 10. 필수 contract 검증 사례

- B300과 다른 제품 variant의 수치, Gb/s와 GB/s, W와 J, chip과 rack scope를 혼동한 입력을 거부한다.
- 같은 ISA instruction의 revision 변경을 조회 시점에 따라 구분한다.
- 표 셀만 추출하고 단위·각주를 잃은 Claim은 quantitative decision에 쓰지 않는다.
- private source와 public source dedup이 ACL을 넓히지 않는다.
- wrong embedding space, stale projection, hash mismatch, source retraction을 숨기지 않는다.
- compile/validator/tool failure를 performance failure와 구분해 기록한다.
- retry·out-of-order event·partial failure 후 experiment/Melete 기록이 중복·누락되지 않는다.
- incomplete metric vector가 완전 우월한 후보로 표시되지 않는다.

## 11. 표준 참조의 사용 범위

출처 관계 표현은 [W3C PROV-O](https://www.w3.org/TR/prov-o/), dataset/distribution metadata 교환은 [DCAT 3](https://www.w3.org/TR/vocab-dcat-3/), RDF 표현을 선택할 경우 shape 검증은 [SHACL](https://www.w3.org/TR/shacl/), quantity/unit vocabulary 후보는 [QUDT](https://www.qudt.org/)를 참고한다. 이 표준을 참고한다는 사실은 특정 DB나 serialization을 채택했다는 뜻이 아니다. DSE 적용 schema·rule·ACL·실험 계약은 별도로 검증한다.
