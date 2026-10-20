# HAT 실행 주장·fidelity 계약

상태: **P0 설계 계약**. 아래 pinned source는 읽기 확인만 했으며 HAT/HATTorch/Melete runtime, test, simulation은 실행하지 않았다. 이 문서는 HAT source가 허용하는 claim 경계와 DSE episode의 fail-closed 표기를 정한다. P1 후보와 실제 pin은 [p1-first-episode.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/episodes/p1-first-episode.md), [episode-manifest.json](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/fixtures/p0/episode-manifest.json)에 기록한다.

## 1. 판정 축

HAT canonical language에서 L1은 Op Analytical, L2는 Kernel/Recipe Analytical, L3는 Temporal Replay다. L2는 logical graph를 Programming Model과 Architecture Recipe로 lowering한 kernel/event의 analytical cost, L3는 그 event DAG를 queue·contention·mutable resource state에서 시간축으로 재생한다. Fidelity level은 한 run에서 허용할 claim과 required/forbidden artifacts를 함께 정한다. [HAT language](https://github.com/jimmylegendary/hat-system/blob/e3048fac5704118b47fd7e2eb21ed36d477742a0/CONTEXT.md#L8), [fidelity matrix](https://github.com/jimmylegendary/hat-system/blob/e3048fac5704118b47fd7e2eb21ed36d477742a0/docs/architecture/fidelity-level-feature-matrix.md#L7)

DSE는 사실 검증과 실행 권한을 분리한다.

| 축 | 허용 값 | 의미 |
|---|---|---|
| source_status | source_verified, source_missing, source_conflict | Pinned source/artifact의 존재와 내용 확인. Runtime PASS를 뜻하지 않는다. |
| runtime_status | not_run, run_pass, run_fail, skipped, blocked | 같은 pin/config의 실제 실행 상태. Test 존재나 opt-in test의 skip은 PASS가 아니다. |
| validation_verdict | pass, fail, incomplete_unknown | 결정론적 gates의 결과. 필수 producer가 없거나 미실행이면 incomplete_unknown이다. |
| review_completeness | complete, partial, all_abstain, not_run | DSE run의 native reviewer 결과로 요청된 Claim·제약·Metric coverage를 판정한 상태. Pinned source를 읽은 audit는 이 run-level 축의 review evidence가 아니므로 reviewer/report가 없으면 not_run이다. |
| physical_feasibility | feasible_within_declared_scope, infeasible, unknown, not_assessed | 선언한 twin/scope의 feasibility. B200 결과를 B300에 대입하지 않는다. |
| simulation_permission | denied, exploratory_only, validated_profile_only | 실행 권한 정책. Model confidence/source status만으로 승격하지 않는다. |

각 run에는 이 축을 별도 필드로 기록한다. Target B300에 pinned twin과 capability/legality evidence가 없으면 permission은 denied, verdict는 incomplete_unknown, feasibility는 not_assessed다. P0에서는 B200 probe도 현재 permission이 denied다. 별도 진단 profile과 grant가 마련되면 그 범위에 한해서 exploratory_only를 기대할 수 있으며, B300 acceptance나 baseline을 대체하지 않는다. HAT System도 required producer가 없으면 빈 PASS가 아니라 unsupported/blocked로 fail closed하도록 정의한다. [Gate applicability](https://github.com/jimmylegendary/hat-system/blob/e3048fac5704118b47fd7e2eb21ed36d477742a0/docs/architecture/fidelity-level-feature-matrix.md#L129)

## 2. Fidelity별 허용 claim

| Profile | 실행 의미 | 필수 artifact | 금지 claim |
|---|---|---|---|
| L1 Op Analytical | HATTorch가 requested logical ops, tensor extents, dependencies의 op-level analytical baseline을 만든다. HATIR/Kernelization/Replay는 포함하지 않는다. | call-ledger, op graph, l1-cost.json, coarse RP logical state, L1 gate | accelerator kernel selection, fused-kernel timing, temporal queue behavior, actual device latency |
| L2 Kernel/Recipe Analytical | L1 graph를 pinned target twin의 Programming Model/Architecture Recipe로 lowering하여 resolved kernel instances, launch/memory event DAG와 analytical cost를 만든다. Replay는 포함하지 않는다. | Programming Model, Recipe, kernelization.json, resolved instances, event DAG, hatrp-events.jsonl, hatir-cost.json, effective-cost-l2.json, L2 gate | replayed TTFT/TPOT, live arbitration, physical accelerator execution, PTX/SASS/binary |
| L3 Temporal Replay | L2 event DAG의 dependency, queue, contention, arbitration, mutable resource state를 시간축에서 실행한다. | HAT Replay, replay/final state, effective-cost-l3.json, L3 gate | actual accelerator result |
| External Golden Control | 동일 workload/config을 실제 device에서 독립 실행해 HAT와 비교한다. HAT fidelity level이 아니다. | device identity, run/config/source pins, same-scenario metrics와 uncertainty | HAT simulation output으로 가장 |

HAT System의 cost substitution은 E1=L1, E2=L2-covered unit + L1 carry-forward, E3=L3-covered unit + effective-L2 carry-forward다. 상위 level은 하위 artifact와 미대체 unit의 provenance를 보존하며, L1 run에 HATIR를 켜거나 L2 run에 Replay를 섞지 않는다. [E1/E2/E3 contract](https://github.com/jimmylegendary/hat-system/blob/e3048fac5704118b47fd7e2eb21ed36d477742a0/docs/architecture/fidelity-level-feature-matrix.md#L9)

Pinned HAT System 문서는 L2 serving을 planned/blocked로 표시하고 L3는 HAT_REPLAY_NOT_IMPLEMENTED, planned/non-runnable이라며 PASS를 금지한다. 별도 phase 계획은 P2 L2 slice를 recorded PASS이나 seal defect/partial로 분류하고, P8에 B300 twin/result와 integrated DSE run/verdict가 없다고 적는다. 일부 component code나 historical test가 존재해도 이 범위를 넘어 claim하지 않는다. [Fidelity status](https://github.com/jimmylegendary/hat-system/blob/e3048fac5704118b47fd7e2eb21ed36d477742a0/docs/architecture/fidelity-level-feature-matrix.md#L152), [phase status](https://github.com/jimmylegendary/hat-system/blob/e3048fac5704118b47fd7e2eb21ed36d477742a0/docs/plans/master-phase-plan.md#L143)

## 3. Covered Unit과 effective cost

Cost unit은 “지원되는 op”라는 제품 이름이 아니라 재현 가능한 accounting identity여야 한다. CostUnit record는 아래를 보존한다.

- stable unit ID와 scope: request, phase, logical op, kernel instance, launch 또는 memory event
- producer/version, source_refs, WorkloadScenario, ModelVersion, DesignPoint, twin 및 calibration refs
- cost kind, value/unit, method/fidelity, uncertainty/completeness
- source logical op IDs, resolved kernel IDs, event IDs, coverage gate와 replacement/carry-forward lineage

Effective cost는 unit별로 계산한다. L1 cost는 E1이다. E2에서 L2가 unit을 완전히 대체하고 L2 gate가 통과한 경우에만 해당 unit의 L2 cost를 쓴다. 덮이지 않은 모든 unit은 동일 identity/provenance로 L1에서 carry forward한다. E3도 L3 replay evidence와 gate가 없는 unit은 effective-L2에서 carry forward한다. 같은 unit을 여러 producer가 중복 집계하지 않으며, fused kernel cost와 대체 대상 L1 op cost를 동시에 더하지 않는다. Unit coverage, byte/operation conservation, dependency critical path가 닫혀야 한다. Missing cost는 unknown/not_evaluated다. null duration을 0µs로 채우지 않는다. HAT의 정의상 Covered Unit은 상위 level producer와 gate가 완전한 replacement evidence를 가진 accounting unit이다. [Covered Unit definitions](https://github.com/jimmylegendary/hat-system/blob/e3048fac5704118b47fd7e2eb21ed36d477742a0/CONTEXT.md#L25), [cost gates](https://github.com/jimmylegendary/hat-system/blob/e3048fac5704118b47fd7e2eb21ed36d477742a0/docs/architecture/fidelity-level-feature-matrix.md#L138)

## 4. Fold/unfold, fusion, kernelization 입력 경계

HATIR의 Kernel Pattern IR은 HW-independent algorithm structure, Folded Mapping Plan은 compact tile/loop/spatial/memory mapping, Architecture Recipe는 mapping을 target atom/resource/layout/pipeline에 결합한 strategy, Event IR은 Replay input이다. 이것들은 executable CUDA/ISA binary가 아니다. HATIR은 codegen/register allocation/binary emission 책임을 갖지 않는다. [HATIR language and product boundary](https://github.com/jimmylegendary/hatir/blob/1ff4485f2a777d4a54a68e9406a834fc3bddc630/CONTEXT.md#L8)

P1 candidate adapter가 바인딩해야 할 inputs:

| Input | 필수 필드와 의미 |
|---|---|
| KernelPattern | operation identity, iteration/reduction dimensions, operand affine access dimensions, dtype |
| FoldedMappingPlan | target LevelStack, per-level tile factors, loop/spatial mapping, explicit fold/remainder tails |
| FusionPlan | ordered producer/consumer ops, HW, shared tiling levels, fuse_level, ephemeral intermediates |
| ArchitectureRecipe | ProgrammingModel ID/stages, source-bearing KernelTemplates, logical op ID mapping, execution target, queue/stream, launch costs/resources, compute/memory accesses, dependencies |
| TargetTwin | immutable twin ID/revision/hash, memory/fabric/compute path, execution atoms와 legality constraints |

FusionPlan은 producer/consumer ops가 같은 tiling stack을 공유한다. Ephemeral intermediate는 backing storage traffic을 없앨 수 있지만 fuse-level working set을 계속 차지한다. Capacity 초과 시 cost model은 일부 intermediate를 spill하고 재계산한다. 이것은 명시적 plan evaluation이지 자동 fusion candidate generation을 증명하지 않는다. [FusionPlan fields and spill behavior](https://github.com/jimmylegendary/hatir/blob/1ff4485f2a777d4a54a68e9406a834fc3bddc630/impl/hatir/plan.py#L247)

별도 Kernelization API인 resolve_kernelization은 caller가 준 logical_ops, ProgrammingModel, ArchitectureRecipe를 검증해 source-bearing N:M kernel instances와 launch/memory event DAG를 만든다. 함수 자체는 recipe search를 하지 않는다. [resolve_kernelization inputs](https://github.com/jimmylegendary/hatir/blob/1ff4485f2a777d4a54a68e9406a834fc3bddc630/impl/hatir/kernelization.py#L392)

Standalone hat-trace-convert CLI는 twin/root와 explicit kernel spec을 받아 count 또는 emit을 수행한다. Registry op는 kernel name, input/output shapes, attrs, dtype로 입력하며 GEMM은 M/N/K/levels를 입력한다. Output format은 hatir_isa_v1 또는 chakra, granularity는 tile 또는 isa다. Unfold input은 affine dimensions/operands, tile factors, fold와 remainder를 명시한 plan이다. Event에는 seq/kind/tier/target/bytes/macs/coord가 있지만 unfold module은 timing을 할당하지 않는다. 이는 model/session runner가 아니다. [CLI entrypoint and options](https://github.com/jimmylegendary/hatir/blob/1ff4485f2a777d4a54a68e9406a834fc3bddc630/impl/hatir/trace_cli.py#L181), [unfold contract](https://github.com/jimmylegendary/hatir/blob/1ff4485f2a777d4a54a68e9406a834fc3bddc630/impl/hatir/unfold.py#L1)

HATTorch의 L1 op-roofline은 HATIR을 거치지 않고, L2 analytical cost/fusion은 named kernel registry를 경유한다. 온라인 transaction lowering은 선언된 semantic window(KV update와 attention)에 대해 ProgrammingModel과 KernelTemplate 하나를 만들고 resolve_kernelization을 호출한다. 이 경계는 제한된 lowering 예시다. 전체 kernel/fusion 후보 탐색이나 FoldedMappingPlan→unfold→Replay 연결을 입증하지 않는다. [HATTorch L1/L2 boundary](https://github.com/jimmylegendary/hattorch/blob/05a4b1889d1f68cade396b40340111ccd8bdd826/hattorch/vllm26/resources.py#L140), [L2 registry consumer](https://github.com/jimmylegendary/hattorch/blob/05a4b1889d1f68cade396b40340111ccd8bdd826/hattorch/vllm26/resources.py#L3954), [online transaction lowering](https://github.com/jimmylegendary/hattorch/blob/05a4b1889d1f68cade396b40340111ccd8bdd826/hattorch/vllm26/online_transaction.py#L1847)

## 5. RP state, online/offline information boundary

HAT RP owns authoritative allocation, reservation, residency, placement, ownership and lifetime. HATIR/recipe dispatch must use an immutable frozen view; live state queries during a recipe decision are forbidden by the L2 source contract. HAT RP client code explicitly distinguishes the runtime live-query client from the frozen snapshot view used by HATIR. [HAT RP state owner](https://github.com/jimmylegendary/hat-system/blob/e3048fac5704118b47fd7e2eb21ed36d477742a0/CONTEXT.md#L47), [client grade](https://github.com/jimmylegendary/hat-rp/blob/2be990e5d7d05f1dcb450c41a0c0d54262ee7a26/hatos/client.py#L16), [frozen view](https://github.com/jimmylegendary/hat-rp/blob/2be990e5d7d05f1dcb450c41a0c0d54262ee7a26/hatos/instance.py#L468)

이 source interface가 P1에 쓸 수 있는 특정 keyframe/WAL, frozen snapshot, 또는 target twin별 state vector를 제공한다는 증거는 아직 없다. 이전 RP timeline이 발견되더라도 diagnostic evidence로만 취급한다. Kernel, fusion, Recipe 또는 HW revision이 바뀌면 이전 resource timeline과 cost를 그대로 재사용하지 말고 해당 입력 pin으로 kernelization·event DAG·RP replay·metric을 다시 계산한다. 이전 run은 provenance와 비교용으로 연결하되 새 run의 입력 state를 대신하지 않는다.

An online/realizable policy may observe and act only on state the current/past Programming Model exposes at decision time. Mode 4A is a model-relative current-state causal oracle; it knows current state but not the future. Mode 4B is clairvoyant about future workload/state and is only an offline lower bound. Keep both separate from realizable L3. If a complete trace is supplied to offline DSE, record that future visibility as an explicit offline profile; never reuse it as an online chooser. [Mode 3/4A/4B](https://github.com/jimmylegendary/hatir/blob/1ff4485f2a777d4a54a68e9406a834fc3bddc630/CONTEXT.md#L16)

## 6. Metrics and unsupported claims

| Producer | Source-backed output | Not implied |
|---|---|---|
| HATTorch L1 | captured logical-op/tensor-extent graph and op-level analytical cost | kernel schedule, device execution, session latency |
| HATIR plan/kernelization | MACs, per-tier bytes/cost terms and source-bearing duration_us when recipe supplies timing terms | actual measured B300 throughput/power, time-varying arrivals |
| HATIR unfold CLI | ordered tile/ISA event seq/kind/tier/target/bytes/macs/coord | timestamps or event duration; downstream simulator assigns time |
| HAT RP event ledger/reducer | event provenance, counts, memory/DMA bytes, kernel start/end lifecycle | request TTFT/TPOT, session latency, measured power |
| Qwen MTP exact-runtime probe | if run: 3 generated token IDs, resolved-config.json, call-ledger.jsonl, guard-report.json; physical payload remains zero | model answer quality, B300 performance, L3 timeline or a token/session MetricVector |

HAT RP event schema requires duration_us and timing_status but allows null duration with not_evaluated. Its execution-state reducer aggregates event_count/read_bytes/write_bytes/dma_bytes and kernel lifecycle, not latency. Therefore null timing is not zero; it must remain not_evaluated. [event duration contract](https://github.com/jimmylegendary/hat-rp/blob/2be990e5d7d05f1dcb450c41a0c0d54262ee7a26/schema/hatrp-event-v2.schema.json#L7), [reducer outputs](https://github.com/jimmylegendary/hat-rp/blob/2be990e5d7d05f1dcb450c41a0c0d54262ee7a26/hatos/execution_state.py#L11)

TTFT, TPOT/inter-token latency, input/output tokens/s, request/s, session/s, tool wait를 포함한 E2E latency는 pinned arrival/context/KV 정책과 같은 scope의 producer가 있어야 계산한다. HATIR의 kernel별 analytical microseconds를 더해 request metric이라고 부르지 않는다. Analytical twin의 power/energy는 독립적인 물리 측정이 뒷받침되지 않으면 model estimate다. External Golden Control은 같은 scenario를 실제 device에서 별도로 실행하는 것이며 HAT simulation level이 아니다. [data-contracts.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/data-contracts.md#L91)

## 7. Fail-closed negative paths

| Condition | Required result |
|---|---|
| No pinned B300 twin/capability/legality profile | permission denied; verdict incomplete_unknown; feasibility not_assessed |
| Only B200/GB300 fixture, heuristic or benchmark anchor | reference/diagnostic only; never substitute for B300 or scale its metrics |
| Model/tokenizer/chat-template/config registration or required file is missing | model support incomplete; no quality/performance claim |
| Arrival, turn context, prefix or KV semantics unresolved | scenario not frozen; no TTFT/TPOT/session-throughput claim |
| Required fidelity producer/artifact is absent | unsupported/blocked, not blank PASS |
| HATIR intent outside L2, unknown registry kernel, unmapped logical op, cyclic/invalid recipe | reject; no silent generic fallback |
| Scalar cost is passed to ISA-trace emitter, or trace timing is absent | no ISA timeline or zero-duration claim |
| Melete request/readout query_id, host principal/authorization witness, scope/context, expected `(memory_id, version)`, or snapshot_seq is absent or mismatched; or ACL/source/predicate check fails | `confirmed_visible` 금지; retrieval을 candidate only로 두고 decision에 적용하지 않는다. Flat exact Condition이 DSE predicate를 표현하지 못하면 DSE validator에서 fail closed한다. |

Source pin, component probe 정의와 P1 blocker는 [p1-first-episode.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/episodes/p1-first-episode.md)에 있다. B300 대상 episode와 별도 B200/Qwen 진단 입력은 [episode-manifest.json](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/fixtures/p0/episode-manifest.json)에 있다.

## 8. Pinned source references

- HAT System: [fidelity and artifacts](https://github.com/jimmylegendary/hat-system/blob/e3048fac5704118b47fd7e2eb21ed36d477742a0/docs/architecture/fidelity-level-feature-matrix.md#L7), [P8 B300 gap](https://github.com/jimmylegendary/hat-system/blob/e3048fac5704118b47fd7e2eb21ed36d477742a0/docs/plans/master-phase-plan.md#L152).
- HATIR: [language/state modes](https://github.com/jimmylegendary/hatir/blob/1ff4485f2a777d4a54a68e9406a834fc3bddc630/CONTEXT.md#L8), [FusionPlan](https://github.com/jimmylegendary/hatir/blob/1ff4485f2a777d4a54a68e9406a834fc3bddc630/impl/hatir/plan.py#L248), [recipe resolver](https://github.com/jimmylegendary/hatir/blob/1ff4485f2a777d4a54a68e9406a834fc3bddc630/impl/hatir/kernelization.py#L392), [unfold](https://github.com/jimmylegendary/hatir/blob/1ff4485f2a777d4a54a68e9406a834fc3bddc630/impl/hatir/unfold.py#L1), [trace CLI](https://github.com/jimmylegendary/hatir/blob/1ff4485f2a777d4a54a68e9406a834fc3bddc630/impl/hatir/trace_cli.py#L181).
- HATTorch: [Qwen MTP test](https://github.com/jimmylegendary/hattorch/blob/05a4b1889d1f68cade396b40340111ccd8bdd826/tests/vllm26/runtime/test_qwen36_mtp_engine_serverless.py#L12), [model source lock](https://github.com/jimmylegendary/hattorch/blob/05a4b1889d1f68cade396b40340111ccd8bdd826/hattorch/vllm26/contracts/qwen36-model-sources.lock.json#L1), [model semantic lock](https://github.com/jimmylegendary/hattorch/blob/05a4b1889d1f68cade396b40340111ccd8bdd826/hattorch/vllm26/contracts/qwen36-model-semantics.lock.json#L1), [W1 meta-only probe](https://github.com/jimmylegendary/hattorch/blob/05a4b1889d1f68cade396b40340111ccd8bdd826/tests/vllm26/runtime/test_w1_forward.py#L1).
- HAT RP: [state/event contract](https://github.com/jimmylegendary/hat-rp/blob/2be990e5d7d05f1dcb450c41a0c0d54262ee7a26/README.md#L32), [event v2 timing](https://github.com/jimmylegendary/hat-rp/blob/2be990e5d7d05f1dcb450c41a0c0d54262ee7a26/schema/hatrp-event-v2.schema.json#L7), [execution-state reducer](https://github.com/jimmylegendary/hat-rp/blob/2be990e5d7d05f1dcb450c41a0c0d54262ee7a26/hatos/execution_state.py#L11).
- HAT Schema: [DGX B200 x8 fixture](https://github.com/jimmylegendary/hat-schema/blob/a874d0c2e277e8838ecd95ba16679b774646408e/examples/dgx-b200-x8.hw#L1), [single B200 component profile](https://github.com/jimmylegendary/hat-schema/blob/a874d0c2e277e8838ecd95ba16679b774646408e/examples/b200.hw#L1).
- Melete: [Observation/IntakeContext/receipt](https://github.com/jimmylegendary/melete/blob/9a3564dd96de22d0311522417c2c36e6bf2a0a91/packages/melete-core/src/melete/contracts/observation.py#L29), [ingest entrypoint](https://github.com/jimmylegendary/melete/blob/9a3564dd96de22d0311522417c2c36e6bf2a0a91/packages/melete-core/src/melete/engine.py#L343), [flat exact Condition](https://github.com/jimmylegendary/melete/blob/9a3564dd96de22d0311522417c2c36e6bf2a0a91/packages/melete-core/src/melete/patterns/conditions.py#L8).
