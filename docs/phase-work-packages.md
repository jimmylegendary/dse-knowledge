# P2–P5 상세 작업 패키지

이 문서는 [2026-10-16-dse-resolution-plan.md](https://github.com/jimmylegendary/dse-knowledge/blob/main/docs/superpowers/plans/2026-10-16-dse-resolution-plan.md)의 후속 phase를 구현자가 파일·입출력·실패 사례 단위로 볼 수 있게 보완한다. 모두 미래 작업이며 파일 생성·command 실행을 아직 하지 않았다. 경로는 제안 구현 root `<repository-root>` 아래의 경로 표기다.

## 공통 task 실행·검토 계약

각 패키지는 다음 순서를 따르는 독립 review 단위다.

- [ ] 아래 acceptance를 재현하는 의미 있는 failing fixture/test를 정의한다.
- [ ] 해당 test의 실패가 의도한 결손 때문인지 확인한다.
- [ ] 지정 파일과 기존 계약의 호환 범위 안에서 구현한다.
- [ ] 해당 test와 phase 전체 episode를 실행하고 결과·artifact hash를 남긴다.
- [ ] 별도 spec/code reviewer가 확인하고 master가 command·출력·pass/fail·SHA를 검증한다.
- [ ] 통과한 범위만 commit·통합하고 requirement/phase coverage를 갱신한다.

Source·model·실험을 바꾸는 작업에는 pinned manifest와 source rights gate가 공통으로 적용된다. 파일 이름은 계획이며 이미 존재하는 파일로 오해하지 않는다. P1 상세 task는 원 계획에 있다. 후속 phase도 이전 단계의 전체 episode를 유지한다.

## P2: 전 영역 breadth

### P2-A Source·entity·검색 범위 확장

**Files:** `services/intake/source_profiles.py`, `services/knowledge/entity_resolution.py`, `services/retrieval/version_filter.py`, `tests/integration/test_multisource_versions.py`.

**Consumes:** SourceRegistration/Revision, ExtractionRun, Claim, DecisionContext. **Produces:** 여러 source/version에서 같은 계약의 PublishReceipt와 EvidenceBundle.

**Acceptance:** source마다 publisher·rights·revision·span이 보존된다. 같은 제품명/다른 revision의 수치는 합쳐지지 않는다. 표·code·논문 source와 no-answer query를 6개 도메인 모두에서 평가한다. source duplicate가 independent evidence count를 늘리지 않는다.

**Future verification:** `pytest tests/integration/test_multisource_versions.py -q`; frozen `p2-retrieval` manifest의 domain recall·unit/version·ACL 결과.

**Ownership/dependency:** intake/knowledge worker가 수정하고 retrieval worker는 version_filter를 단독 소유하도록 사전 분리한다. P2-B/C는 고정된 fixture snapshot을 소비한다.

### P2-B 여러 HW 계층·kernel·scenario

**Files:** `services/validation/composition_rules.py`, `adapters/hat/asset_mapping.py`, `adapters/hat/recipe_mapping.py`, `tests/integration/test_multilevel_recipes.py`.

**Consumes:** HardwareAssembly, ProgrammingModelVersion, KernelRecipeVersion, WorkloadScenario. **Produces:** ReviewReport, ValidationReport, HAT RunManifest.

**Acceptance:** rack/tray/package/SoC/component 각각 valid/invalid 조합, 지원/미지원 ISA, shape/layout/dtype 및 fold/remainder/fusion spill 사례가 있다. 1,000-session Scenario의 전체/증분 context와 arrival 정책을 고정한다. 범위를 바꾸면 새 scenario revision이 생긴다.

**Future verification:** `pytest tests/integration/test_multilevel_recipes.py -q`; 지원 HAT 경로를 사용한 `p2-cross-domain` run artifact.

### P2-C 지표·trajectory·insight 폭 확대

**Files:** `services/experiments/cohort.py`, `services/experiments/metrics.py`, `adapters/melete/event_mapping.py`, `tests/integration/test_cohort_and_memory.py`.

**Consumes:** RunEvent/Artifact, MetricDefinition/Value, ExperienceReceipt. **Produces:** ComparisonReport, linked Melete events와 candidate Insight.

**Acceptance:** TTFT/TPOT/session/throughput/power/energy의 unit·scope·missing을 구분한다. 불법 설계·runtime failure·성능 regression이 서로 다른 failure다. duplicate/out-of-order event와 Melete transient failure 후 identity가 유지된다.

**Future verification:** `pytest tests/integration/test_cohort_and_memory.py -q`; baseline과 variant, 실패 2종, 미측정 metric을 포함한 comparison report.

### P2-D Stage 운영·인간 검토·전체 회귀

**Files:** `infra/environments/stage/`, `services/knowledge/acl_epoch.py`, `apps/review/evidence_views.*`, `tests/e2e/test_p2_whole_flow.py`.

**Consumes:** frozen P2 source/design/run manifests, ACL epochs. **Produces:** stage deployment evidence, source→next proposal 전체 report.

**Acceptance:** ACL revocation이 graph hop/cache/외부 reranker에서 즉시 반영된다. 사람이 evidence와 metric 분포 및 실패 trajectory를 확인한다. queue retry/reindex/restore 후 전체 episode가 유지된다.

**Future verification:** `pytest tests/e2e/test_p2_whole_flow.py -q`; stage IaC plan review; restore·delete drill. UI 파일 확장자는 기존 HAT plane stack을 따르며 신규 UI framework를 임의 도입하지 않는다.

## P3: 전 영역 fidelity

### P3-A 숫자·표·수식·retrieval 정밀도

**Files:** `services/intake/structured_elements.py`, `services/knowledge/numeric_claims.py`, `services/retrieval/rerank.py`, `tests/integration/test_numeric_evidence.py`.

**Consumes:** DocumentElement/SourceSpan, candidate Claim, EvidenceBundle. **Produces:** 수치·단위·조건이 검증된 Claim과 conflict/unknown.

**Acceptance:** footnote·merged cell·OCR sign·단위 접두어 오류를 검출한다. raw citation이 실제로 수치를 지지하는지 gold span으로 검사한다. lexical/dense/graph/rerank ablation과 embedding shadow migration에서 같은 평가 집합을 사용한다.

**Future verification:** `pytest tests/integration/test_numeric_evidence.py -q`; `p3-structured-evidence`와 `p3-retrieval-ablation` manifests.

### P3-B HW·kernel search와 calibration

**Files:** `services/validation/physical_coverage.py`, `services/experiments/search_policy.py`, `adapters/hat/calibration.py`, `tests/integration/test_search_fidelity.py`.

**Consumes:** ConstraintRule, KernelSearchRequest, CostModelVersion, SearchBudget. **Produces:** feasible candidate set, calibration/error report, Metric Vector frontier.

**Acceptance:** 작은 유한 공간에서 enumeration 정답을 복원한다. random/TPE/BO/evolution/KG-guided를 같은 budget으로 비교한다. old timeline을 새 후보의 성능으로 쓰지 않는다. extrapolation과 model error를 명시한다.

**Future verification:** `pytest tests/integration/test_search_fidelity.py -q`; 작은 exhaustible fixture와 held-out workload campaign. 실제 B300 측정이 없으면 measured gate를 pass하지 않는다.

### P3-C 반례·Insight·다음 실험

**Files:** `services/experiments/hypotheses.py`, `adapters/melete/insight_mapping.py`, `services/knowledge/impact_analysis.py`, `tests/integration/test_insight_revision.py`.

**Consumes:** intervention, run observations, prior Claim, Melete memory versions. **Produces:** scoped hypothesis/Insight revision, affected proposals, next experiment set.

**Acceptance:** 한 번의 상관관계는 causal fact로 승격되지 않는다. 반례가 기존 Insight를 contested/superseded 상태로 만들고 그 근거를 쓴 proposal을 찾아낸다. scope를 넓히려면 새 evidence가 필요하다.

**Future verification:** `pytest tests/integration/test_insight_revision.py -q`; 동일 현상에 대한 경쟁 가설과 반례를 포함한 full episode.

### P3-D 규모·비용·복구를 포함한 전체 평가

**Files:** `evals/manifests/p3.yaml`, `infra/profiles/load/`, `tests/e2e/test_p3_whole_flow.py`, performance runbook.

**Consumes:** P3 golden/held-out sets, selected cloud/model profiles. **Produces:** 6-domain quality, whole-loop DSE utility, cost/latency/restore report.

**Acceptance:** domain별 목표와 critical negative 0 gate, index rebuild completeness, error-bar origin, budget accounting이 충족된다. unmeasured를 개선으로 표시하지 않는다.

**Future verification:** `pytest tests/e2e/test_p3_whole_flow.py -q`; `python -m evals.run --manifest evals/manifests/p3.yaml`.

## P4: 전 영역 bounded autonomy

### P4-A Agent evidence·수집 제안 정책

**Files:** `services/retrieval/agent_tools.py`, `services/intake/collection_proposals.py`, `services/experiments/decision_policy.py`, `tests/integration/test_agent_evidence_budget.py`.

**Consumes:** DecisionContext, QueryPlan, allowed source classes, SearchBudget. **Produces:** cited proposals 또는 explicit missing evidence.

**Acceptance:** agent가 role별 KG를 스스로 찾되 제한된 tool budget을 준수한다. source content instruction이 authority가 되지 않는다. ACL·version filter를 완화해 답을 억지로 만들지 않는다.

**Future verification:** `pytest tests/integration/test_agent_evidence_budget.py -q`; no-answer·malicious source text·budget exhaustion fixture.

### P4-B 자율 공동 설계·실험 제어

**Files:** `services/experiments/campaign_controller.py`, `services/experiments/run_leases.py`, `adapters/hat/cancel.py`, `tests/integration/test_campaign_control.py`.

**Consumes:** proposal set, execution policy, total budget, pinned manifests. **Produces:** run event chain와 campaign status.

**Acceptance:** 같은 mutable design/run을 둘이 동시에 수정하지 않는다. invalid candidate는 실행 gate에서 차단된다. cancel/timeout/kill이 실제 job까지 전달되고 재시도가 중복 과금을 숨기지 않는다.

**Future verification:** `pytest tests/integration/test_campaign_control.py -q`; duplicate lease, partial launch, cancellation race, cost cap fixtures.

### P4-C 경험에서 다음 제안까지 자율 환류

**Files:** `services/experiments/feedback_policy.py`, `adapters/melete/experience_queries.py`, `tests/integration/test_autonomous_feedback.py`.

**Consumes:** actual run/metric/Insight evidence, memory applicability, campaign budget. **Produces:** next proposal 또는 stop rationale.

**Acceptance:** 성공·실패·unknown을 모두 이용한다. 반복된 같은 실험은 새 검증으로 계산하지 않는다. 재현되지 않는 Insight는 accepted constraint가 되지 않는다. 개선이 없을 때도 calibration 또는 가설 반증을 제안할 수 있다.

**Future verification:** `pytest tests/integration/test_autonomous_feedback.py -q`; loop repetition, false insight, stale memory, independent reproduction cases.

### P4-D 사람·optimizer·agent 대조와 운영

**Files:** `evals/manifests/p4_campaigns.yaml`, `apps/review/campaign_views.*`, `tests/e2e/test_p4_whole_flow.py`, autonomous operations runbook.

**Consumes:** 동일 scenario와 budget의 human-guided, optimizer-only, KG 없는 agent, full agent campaigns. **Produces:** feasible frontier, invalid/wasted run, information gain, human effort와 cost comparison.

**Acceptance:** 자율성 확대가 evidence·correctness·운영 gate를 우회하지 않는다. 연구상 개선이 확인되지 않으면 자동화 범위를 줄이고 원인을 기록한다.

**Future verification:** `pytest tests/e2e/test_p4_whole_flow.py -q`; frozen campaign manifest의 예산·실험·근거 검증.

## P5: 전 영역 production lifecycle

### P5-A Source·model·index 지속 변화

**Files:** `services/intake/change_detection.py`, `services/knowledge/retraction.py`, `services/retrieval/index_migration.py`, `tests/integration/test_lifecycle_changes.py`.

**Consumes:** source revisions/retractions, ACL epochs, new embedding spaces. **Produces:** versioned canonical updates와 재생성된 projections.

**Acceptance:** 삭제·권리 회수·model migration이 graph/vector/cache/Melete reference까지 전파된다. old run snapshot은 권리 정책 범위 안에서 재현 가능하다.

**Future verification:** `pytest tests/integration/test_lifecycle_changes.py -q`; delete/retraction/reindex/drift drill.

### P5-B 새 HW·LLM·kernel의 지속 검증

**Files:** `adapters/hat/compatibility_registry.py`, `evals/manifests/continuous_compatibility.yaml`, `tests/integration/test_new_target_onboarding.py`.

**Consumes:** 새 target/model/programming-model revisions, 기존 full-loop fixtures. **Produces:** compatibility coverage와 new target episode.

**Acceptance:** 신규 지원 때문에 기존 결과의 의미가 바뀌지 않는다. 새 ISA/quality/metric이 미지원이면 unknown으로 남긴다. support claim마다 실행·근거 coverage가 있다.

**Future verification:** `pytest tests/integration/test_new_target_onboarding.py -q`; old/new target paired campaign.

### P5-C 경험·artifact 보존·export·복구

**Files:** `services/experiments/retention.py`, `adapters/melete/lifecycle.py`, `infra/backup_restore/`, `tests/integration/test_restore_and_retention.py`.

**Consumes:** retention policy, ledger/object backup, Melete bridge mapping. **Produces:** verified export/restore/deletion evidence.

**Acceptance:** source hash·run identity·metric parity와 Melete links가 복원된다. 삭제 가능한 source에 무단 WORM lock을 설정하지 않는다. restore가 RPO/RTO 제안값을 실제로 만족하는지 측정한다.

**Future verification:** `pytest tests/integration/test_restore_and_retention.py -q`; isolated restore drill와 selected export import parity.

### P5-D 전체 SLO·비용·incident 운영

**Files:** `infra/environments/prod/`, `evals/manifests/p5_regression.yaml`, `tests/e2e/test_p5_whole_flow.py`, 운영 runbook/ADR.

**Consumes:** approved operational profile, production-like load, complete golden suite. **Produces:** SLO/cost/freshness/quality dashboard와 phase acceptance report.

**Acceptance:** 운영 envelope 안에서 source부터 next proposal까지 모든 단계가 정상·실패·복구 경로를 갖는다. provider outage·queue backlog·excess spend와 degraded retrieval을 사용자에게 명확히 표시한다.

**Future verification:** `pytest tests/e2e/test_p5_whole_flow.py -q`; deployment plan review, budget-stop drill, full restore drill. 실제 조직 정책이 요구하는 검토만 추가한다.

## 의존성과 병렬화

동일 phase의 A/B는 고정된 계약과 fixture를 기준으로 독립 파일에서 병렬 작업할 수 있다. C는 B의 event 계약을, D는 A/B/C의 통합 결과를 소비한다. Canonical schema·shared migration·금융 실행·동일 run 상태는 병렬 변경하지 않는다. 각 phase 전체 acceptance 전에 D가 모든 capability 행의 evidence를 확인한다.
