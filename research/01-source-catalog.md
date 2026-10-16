# DSE 지식 시스템 source catalog

기준일은 2026-10-16이다. 이 문서는 향후 수집할 source family와 정보·취득·권리·검증 계획만 정한다. 초기 corpus가 있다고 가정하지 않으며, 웹에서 확인한 공개 원문 페이지를 넘어 대량 수집·보관·색인·배포를 시작하지 않는다. 기계 판독용 후보 목록과 잠정 점수는 [01-source-catalog.json](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/research/01-source-catalog.json)에 있다.

범위는 사용자가 정한 [README.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/README.md)와 용어 초안 [CONTEXT.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/CONTEXT.md)를 따른다. 핵심 대상은 재현 가능한 Workload Scenario, 버전 고정 Design Point, 조합 가능하고 근거가 있는 Hardware Asset, 검토 가능한 Claim과 Evidence, 외부에서 관찰 가능한 Experiment Trajectory 및 비축약형 Metric Vector다. trajectory에는 요청·turn·model call·tool call·결과·시각·실패·재시도 같은 외부 사건을 담고 숨겨진 chain-of-thought는 수집 대상으로 삼지 않는다.

## 전체 흐름과 해상도

각 Resolution Phase가 매번 같은 폐루프를 포함한다.

1. 모델·toolchain·agent 설정과 입력·출력 길이·시간·도구 의존을 고정한 workload/session scenario를 만든다.
2. 그 scenario에 맞춰 rack→tray/node→package→die/SoC→compute·memory·fabric 자산, kernel/recipe, serving 설정을 하나의 Design Point로 묶는다. 자산 조립은 표준·제품 구성·connector·전력·열·토폴로지 제약의 정확한 버전과 출처를 가진 legality edge로 검사한다.
3. schema의 결정론적 validator가 ID·scope·부모/자식 참조·단위·용량·전력/대역폭 폐합 등 명시 규칙을 판정한다. hat-schema committee agent는 Knowledge Graph에서 적용 가능한 근거를 찾아 인용하고, 모순·불확실·미지원 조합을 보고한다. committee 의견은 deterministic PASS나 사실을 대신하지 않는다.
4. HATIR의 fold 결과, unfold event cardinality, fusion/tiling 후보, 대상 programming model/recipe를 보존한다. 모델링·계측의 fidelity와 provenance를 별도 기록하고, 분석 예측과 실행 결과를 분리한다.
5. metric vector와 정확도·품질·제약 위반을 함께 계산하고, 가설·실험·seed·실행환경·결과·오차·원인 분석을 남긴다.
6. 다음 실험·근거·설계 후보를 제안하고, 승인된 다음 run과 그 결과를 기존 trajectory에 연결한다. 원문 evidence에서 산출된 값까지 출처 chain을 유지한다.

| 단계 | 전 흐름을 유지하며 올리는 해상도 |
|---|---|
| R0 — baseline | NVIDIA B300 계열의 특정 서버/구성을 고정하고 공개 datasheet로 HW twin을 만든다. agent session은 우선 합성·공개 benchmark scenario로 표현하며, 한 번의 전체 흐름을 schema/문서 근거, folded 비용, event 계수, 다중 metric 보고, 실험 기록까지 연결한다. |
| R1 — first closed loop | 허가된 B300 실행 환경의 실제 session과 tool boundary를 계측한다. 동일 workload·model·serving·kernel recipe를 pin하고 HAT legality, HATIR fold/unfold/fusion 후보, replay 또는 측정, metric vector와 다음 실험 제안을 끝까지 연결한다. |
| R2 — breadth/depth | 여러 workload·model·kernel·정밀도와 합법적인 card/tray/package/rack 구성으로 넓힌다. device·fabric·power/thermal profile의 측정 및 시뮬레이션을 동일 Design Point/trace에 붙이고 불확실성·Pareto trade-off를 비교한다. |
| R3 — controlled automation | rights-gated standard 및 더 깊은 circuit/package·kernel 자료, schema committee의 KG retrieval, 반복 측정·불일치 분석·실험 제안을 자동화한다. 전체 chain과 metric을 유지하고 fidelity/coverage만 높인다. |

한 단계도 hardware만, compiler만, graph만 따로 완성하는 단계로 정의하지 않는다. 자동화 수준이 낮은 단계도 전체 경로의 명시적인 stub·unknown·carry-forward를 기록한다.

## 무엇을 보존할지

metric 이름만 같다고 같은 측정으로 취급하지 않는다. 각 값은 값·단위·대상 scope(요청/session/turn/kernel/device/tray/rack/site)·시간 경계·집계법·표본 수·분위수/신뢰구간·성공/품질 조건·부하와 concurrency·warm/cold 상태·seed·측정 overhead·환경 및 원출처를 함께 가진다.

metric vector 후보에는 TTFT, TPOT, inter-token latency, end-to-end/session/turn latency, queue wait, tool-call latency, request goodput, request·output-token throughput, task/tool success, 정확도·응답 품질, timeout/error/retry, prompt/output token 수, cache hit/활용/압력, GPU/CPU 사용률·occupancy·클럭·stall·메모리 트래픽, HBM/DRAM/계층별 용량·대역폭·지연·에너지, NVLink/CXL/PCIe/Ethernet 링크·집합체 대역폭/지연, SM/Tensor utilization, datatype별 성능, board/tray/rack 전력·에너지·온도·열 throttling, area/timing slack 및 facility cooling 관련 값을 포함한다. 각 항목은 적절한 source·instrument에서 얻을 수 있는지 단계별로 표시한다.

서로 다른 metric을 한 scalar로 미리 합치지 않는다. feasible/quality constraints를 먼저 보이고, vector와 Pareto 집합을 보존한다. 선호나 가중치가 나중에 정해지면 별도 Decision Context에 기록한다. 제품 광고 peak, 표준 상한, 시뮬레이터 출력, 계측 결과와 근거 없는 가설은 각각 다른 Claim type이다.

## source별 취득·검수 기준

JSON의 각 후보는 공식 URL, 뽑을 항목, 예상 표현 형식, source/버전 metadata, 접근·권리 처리, 갱신·quality check, P0/P1/P2 및 R0–R3 사용 구간을 갖는다. 이 표는 우선순위 지도를 제공한다. 우선순위는 실제 수집 권한·환경을 부여하지 않는다.

| ID / source family | 가져올 사실과 형식 | 접근·갱신·결정론적 검수 | 우선순위 |
|---|---|---|---|
| hw-nvidia-b300 | NVIDIA GB300 NVL72/HGX B300/DGX B300 datasheet·user guide·rack RA의 SKU, 구성표, block/topology, power/cooling, 성능 각주. HTML/PDF 표·그림/BOM | 구성 이름/수량·SKU·버전·footnote를 모델별로 분리하고 광고값은 advertised로 표시. 월간 및 errata/구성 변경마다 재검토 | P0, R0–R3 |
| isa-cuda-ptx | CUDA guide·PTX ISA의 execution/memory/synchronization·datatype·instruction semantics. HTML/PDF·명령 표·예제 코드 | CUDA/PTX/SM 버전을 같이 pin하고 target별 지원 여부 확인; release마다 | P0, R0–R3 |
| measure-nsight | Nsight Compute metric 정의·scope·aggregation·수집 replay overhead·kernel report. HTML/PDF·표·CLI/report | metric ID와 CUDA/GPU 버전·수집 모드를 연결하고 프로파일링 overhead를 time measurement와 분리; toolkit release마다 | P0, R1–R3 |
| measure-dcgm | DCGM/DCGM Exporter field ID·GPU/CPU/temp/power/energy/traffic 및 interval semantics. HTML·CSV metric table | exporter 설정과 실제 지원 field를 대조하고 interval average를 kernel trace로 해석하지 않음; release/driver 변경 시 | P0, R1–R3 |
| hw-amd-mi350 | AMD CDNA4/MI350/ROCm의 chiplet·HBM·partition·counter·system topology. HTML/PDF·표·figure·ISA/코드 | MI350X/X355/P 등 form factor/partition을 분리하고 vendor peak와 독립 측정을 구분; release·SKU 변경 시 | P1, R1–R3 |
| std-ocp | ORV3, OAM/OAI, UBB/tray, PSU/management, cold plate/CDU/coolant 자료. PDF/도면/표/JSON CAD가 있을 경우 version | 각 PDF front matter의 OWF/OCP/CC 라이선스와 표준 revision을 확인; connector·전력·치수·cooling interface를 deterministic cross-check; release마다 | P1, R0–R3 |
| std-ucie | UCIe die-to-die PHY/protocol/package·compliance 및 3D packaging 변경. 우선 landing-page metadata; 허가된 표준은 PDF 표/그림 | spec은 요청 기반. 권리·AI/TDM 범위 확인 전 metadata-only; spec/ECN 공개 trigger에 재검토 | P2, R2–R3 |
| std-cxl | CXL revision·ECN·memory/fabric feature와 access agreement. 허가된 경우만 규범 표/상태도 | evaluation agreement와 2026-02 AI policy를 별도 확인. 허가 전 metadata-only, 규격 본문을 agent/KG에 전달하지 않음 | P2, R2–R3 |
| std-jedec | HBM/DDR/LPDDR standard ID·revision·발행일·관련 scope | JEDEC access/licensing 범위가 확인될 때까지 metadata-only. 1차 표준 값은 구매/회원 접근 이후 법무 검토 뒤 인용 | P2, R1–R3 |
| std-pcisig | PCIe Base/CEM/ECN의 revision·link rate·protocol scope·errata metadata | 표준 전문/표/도면을 긁거나 AI 입력에 넣지 않는다. PCI-SIG 공개 AI/TDM 제한에 따라 서면 동의 전 metadata만; 승인 revision 변경 시 갱신 | P2, R1–R3 |
| std-ieee8023 | IEEE 802.3 Ethernet/PHY/MIB amendment의 ID·scope·상태·revision | IEEE Xplore의 robots·AI 사용 제한을 준수한다. licensed/open item별 허가 없으면 metadata-only; 매년/ECN trigger | P2, R1–R3 |
| std-ashrae | TC 9.9 thermal envelope, liquid W classes, ambient·humidity measurement scope. public article metadata/표 | 전문 접근은 Datacom/계약 경로 확인 후; 공개 OCP 교차인용은 secondary. 구매/edition/errata 때 갱신 | P2, R1–R3 |
| circuit-openroad-sky130 | OpenROAD RTL-to-GDS PPA flow·SKY130 공개 PDK의 cell/lib/DRC·timing·power report. Tcl/Verilog/LEF/DEF/Liberty/CSV | 실제 license/file license, PDK corner·units·flow commit pin. 선단 공정/Blackwell 면적으로 직접 외삽하지 않음; release/PDK 변경 시 | P1, R2–R3 |
| model-cacti | CACTI cache/memory/3D/IO의 입력 파라미터·access/cycle/area/power equations. C++·config·CSV/figure | supported node·memory model·calibration domain 확인; 출력은 model-relative. release 또는 parameter model 변화 때 | P1, R2–R3 |
| sim-gem5 | CPU·cache·coherence·memory SimObject와 timing/queue semantics. 문서·Python config·C++·stats | gem5 commit/config/trace/system mode를 묶고 configuration example을 paper fact와 구분; release/paper 재현 때 | P1, R1–R3 |
| sim-ramulator | DDR/HBM timing·controller/queue·trace frontend·validation. YAML/C++/Python·trace·stats·visualizer | DRAM preset과 trace source/license pin; 표준 규격을 자동으로 대체하지 않고 real-system calibration 잔차 기록; release 때 | P1, R2–R3 |
| sim-booksim | router/topology/routing/traffic·cycle-level latency/throughput. C++ config·CSV/figure | 각 구현의 license 확인 후 code reuse; topology/traffic assumptions와 version을 결과에 보존; release/paper study 때 | P2, R2–R3 |
| sim-sst | processors/memory/network components·events·statistics·configuration. XML/Python config·C++ component·stats | SST core와 element model 버전/clock/fidelity, topology와 partition을 검수; release·model integration 변경 시 | P1, R2–R3 |
| compiler-mlir | dialect semantics, operation constraints, rewrite/fusion/lowering pass·IR serialization. MLIR text/TableGen/C++ pass/ODS | dialect/pass commit·target backend·legality assertion을 pin; generated docs를 source definition과 대조; LLVM release마다 | P0, R0–R3 |
| kernel-triton | tile/layout/pipeline, Blackwell primitive·kernel tutorial·benchmark code. Python/Jupyter·tables/figures | tutorial code와 API/release/SM 조건 pin; 수치 예제는 별도 실행·계측 전 참고 사실로만 둠; release마다 | P0, R0–R3 |
| kernel-cutlass | CuTe/CUTLASS kernel registry, profiler, fusion/epilogue, datatype/layout/shape constraints. C++/Python/CUDA·CSV/JUnit | kernel config·GPU SM·compiler·warmup/iteration/verification 결과 및 라이선스 기록; tag release마다 | P0, R0–R3 |
| hat-internal | hat-schema/hardware twin, composition·legality, HATIR folded cost·unfold event·fusion status, HAT system contracts. repo Markdown/YAML/JSON/Python/C++/tests | private remote+commit SHA와 문서상 implemented/design-only 범위를 pin. HATIR은 analytical event stream이지 executable ISA trace 아님; commit마다 | P0, R0–R3 |
| melete-internal | 조건부 Claim/Evidence/SourceEvent/Experience·revision·source/deletion provenance contract 및 검증기록. repo docs·JSONL schema·tests | private remote+commit, 허용된 design docs/synthetic/redacted fixture만 allowlist. 사용자 원문 경험·prompt를 기본 수집하지 않음; commit/contract change 때 | P1, R0–R3 |
| benchmark-mlperf | Inference rules, scenarios, loadgen, workload/dataset/quality, results/change log. YAML/JSON/code/XLSX/PDF/표 | round/model/config/scenario·submission division·dataset license pin; revised/invalidated result은 별 revision으로 보존; round release 때 | P0, R0–R3 |
| serving-vllm | request queue/scheduler/KV behavior, TTFT/TPOT/ITL/throughput formulas·benchmark controls. HTML/Python/CSV | benchmark client, cache state, random seed, version·measurement point를 pin; 동일 결과 반복 시 cache contamination 검사; release마다 | P0, R0–R3 |
| serving-tensorrtllm | trtllm-bench/serve, model recipes, metrics, profiler/telemetry, fusion·cache/scheduling features. HTML/Python/C++/CSV | Blackwell 지원 matrix·commit·engine/config·dataset/version·profiler를 함께 고정; NVIDIA vendor performance claim은 measured와 분리; release마다 | P1, R1–R3 |
| model-hf-cards | model/dataset card의 architecture, tokenizer, context, intended use, training/eval, data lineage, license metadata. README YAML/JSON/config/weights manifest | card revision SHA, model/dataset artifact hash, actual license file 확인; card의 license label을 weights/data 이용허락과 동일시하지 않음; revision마다 | P1, R0–R3 |
| agent-agentbench | AgentBench의 multi-turn tasks, environment/action interface, scoring·failure classes. Git/JSON/MD/code | benchmark release·task hash·judge model/prompt·tool version pin; task code license와 third-party environment/data 권리 별도 확인; release 때 | P1, R0–R3 |
| agent-tau3 | τ³-bench의 conversation/tool/API/policy/voice tasks, trajectory artifacts·pass^k. Git/JSON/trace/report | exact tag와 task data license를 고정. 2026-07 v1.0.1에서 score/grade가 바뀐 것처럼 version change는 run 비교를 막는 breaking trigger; release마다 | P1, R0–R3 |
| agent-bfcl | BFCL V1–V4의 tool schema/calls, multi-turn backend, agent memory/web tasks, JSONL category data. JSONL/Python/results | benchmark tag, split, backend, evaluator, dataset license, tool/model versions pin; V1 single-call 점수와 V4 trajectory task를 구분; release마다 | P1, R0–R3 |
| dse-ax-botorch | noisy/multi-objective search space, constraints, trial/result/history, Pareto and hypervolume method. Python/JSON/CSV/plot/equations | API/library version와 direction/unit/noise/constraint/reference point을 pin. Pareto/hypervolume은 user metric vector를 대체하지 않음; release/policy 변화 시 | P1, R0–R3 |
| trace-otel-genai | session/agent/model/tool span·event, token/latency/error metrics·semantic-convention version. YAML/JSON/OTLP schema | convention schema_url/stability를 pin. prompts, outputs, tool args/results may contain PII; default content off, opt-in allowlist·redaction·retention required; spec release마다 | P0, R0–R3 |
| experiment-mlflow | experiment/run/params/metrics/artifact/code version·run status. REST/JSON/DB schema/artifact URI | run ID·config hash·artifact checksum·experiment ID pin; retries/replicas/replays distinct from independent experiments; release/schema change 때 | P1, R0–R3 |
| prov-w3c-provo | entity/activity/agent/derivation/attribution provenance model. OWL/RDF/Turtle/PROV-DM | source/derivation/version/time link consistency와 domain extension을 검수; raw PII content가 아닌 lineage IDs 기록; errata/namespace change 때 | P1, R0–R3 |
| research-arxiv | submission/version/DOI/category/abstract/author metadata, license, only allowed preprint full text. Atom XML/OAI-PMH/TeX/PDF | arXiv id와 vN, per-version license, DOI/journal version, source hash pin. OAI metadata daily; CC0 metadata != full-text reuse permission | P0, R0–R3 |
| index-openalex | works/authors/venues/citations/related IDs and open-access metadata. REST JSON/quarterly snapshot | ID/DOI resolution, RELEASE_NOTES, snapshot/API vintage, schema/license pin; metadata discovery index, not full text authority; quarterly snapshot/API monitor | P1, R0–R3 |
| index-semantic-scholar | paper/author/citation/reference/API fields, OA locations, recommendation metadata. REST JSON/OpenAPI | paperId/CorpusId/DOI/arXiv crosswalk, rate limit/field selection/time pin. OA flag is discovery, not permission; API/schema change 때 | P1, R0–R3 |
| index-crossref | DOI/member/funder/license/update/deposit metadata. REST JSON/content negotiation | DOI/registration agency, deposited license/update/deposit date; abstract copyright may persist. polite pool/rate guidelines; API schema/change 때 | P0, R0–R3 |
| publisher-acm-ieee | [ACM Digital Library platform](https://libraries.acm.org/digital-library/platform-and-features) + [IEEE Xplore Terms](https://ieeexplore.ieee.org/Xplorehelp/overview-of-ieee-xplore/terms-of-use) | ACM publication/DOI/item-license metadata; IEEE standards/article metadata and rights boundaries | ACM: full OA since 2026, but item and bulk/API/TDM rights unverified; metadata-only. IEEE: licensed-content robot/AI restrictions; metadata-only absent explicit permission | P2, R0–R3 |
| publisher-usenix | Open proceedings metadata, paper/slide/video, author-retained copyright notice. HTML/PDF/slides/video | check venue consent/copyright and excerpts within each paper; cite canonical proceedings page, don't redistribute publisher bundles by default; each conference release | P1, R0–R3 |

## 40개 source family index

표의 URL은 각 family의 primary landing page다. 각 source의 세부 형식·metadata·권리 처리·refresh·quality check·점수는 JSON의 동일 ID에 고정했다.

| ID | primary source | 주 extraction | 우선순위 |
|---|---|---|---|
| hw-nvidia-b300 | [NVIDIA GB300 NVL72](https://www.nvidia.com/en-us/data-center/gb300-nvl72/) | B300/GB300 variants, rack/tray composition, power/cooling | P0 |
| isa-cuda-ptx | [CUDA Programming Guide](https://docs.nvidia.com/cuda/cuda-programming-guide/) | GPU programming, PTX ISA, synchronization/memory legality | P0 |
| measure-nsight | [Nsight Compute Profiling Guide](https://docs.nvidia.com/nsight-compute/ProfilingGuide/index.html) | kernel counters, profiles, collection overhead | P0 |
| measure-dcgm | [DCGM Exporter Metrics](https://docs.nvidia.com/datacenter/dcgm/latest/reference/dcgm-exporter-metrics.html) | GPU power/energy/temperature/utilization/traffic | P0 |
| hw-amd-mi350 | [AMD MI350 microarchitecture](https://rocm.docs.amd.com/en/develop/reference/gpu-arch/mi350.html) | MI350X/MI355X/MI350P variants, chiplets, HBM, partitions and counters | P1 |
| std-ocp | [OCP Cooling Environments](https://www.opencompute.org/projects/cooling-environments/) | rack/OAM/tray/cooling interfaces and requirements | P1 |
| std-ucie | [UCIe Specifications](https://www.uciexpress.org/specifications) | package die-to-die PHY/protocol/compatibility | P2, gated |
| std-cxl | [CXL Specification](https://computeexpresslink.org/cxl-specification/) | memory/fabric revisions and licensed protocol rules | P2, gated |
| std-jedec | [JEDEC](https://www.jedec.org/) | HBM/DDR/LPDDR standards metadata; body gated | P2, gated |
| std-pcisig | [PCI-SIG Specifications](https://pcisig.com/specifications) | PCIe revision/ECN metadata; body gated | P2, gated |
| std-ieee8023 | [IEEE 802.3-2022](https://standards.ieee.org/ieee/7003/10422/) | Ethernet PHY/MIB scope and amendment metadata | P2, gated |
| std-ashrae | [ASHRAE AI Data Center Site Planning](https://www.ashrae.org/technical-resources/topics-and-initiatives/ai-data-center/site-planning) | thermal envelope and licensed thermal-guideline scope | P2, gated |
| circuit-openroad-sky130 | [OpenROAD Flow Scripts](https://openroad-flow-scripts.readthedocs.io/en/latest/) | open RTL-to-GDS reports plus SKY130 cell/process proxy | P1 |
| model-cacti | [CACTI](https://github.com/HewlettPackard/cacti) | memory/cache timing, area, leakage and dynamic power | P1 |
| sim-gem5 | [gem5 Documentation](https://www.gem5.org/documentation/) | CPU/cache/coherence/memory timing models | P1 |
| sim-ramulator | [Ramulator 2](https://github.com/CMU-SAFARI/ramulator2) | DDR/HBM timing/controller/trace models | P1 |
| sim-booksim | [BookSim 2](https://github.com/booksim/booksim2) | router, routing, topology and network traffic | P2 |
| sim-sst | [SST Getting Started](https://sst-simulator.org/sst-docs/docs/guides/start) | system components, event links and multi-fidelity simulation | P1 |
| compiler-mlir | [MLIR Documentation](https://mlir.llvm.org/docs/) | dialect, rewrite, fusion and lowering legality | P0 |
| kernel-triton | [Triton Tutorials](https://triton-lang.org/main/getting-started/tutorials/) | kernel tile/layout/pipeline and fusion examples | P0 |
| kernel-cutlass | [NVIDIA CUTLASS](https://github.com/NVIDIA/cutlass) | kernel registry, CuTe, profiler and verification | P0 |
| hat-internal | [HAT System](https://github.com/jimmylegendary/hat-system) | HAT schema/HATIR/contract implementation and design boundary | P0, private |
| melete-internal | [Melete](https://github.com/jimmylegendary/melete) | experience, claim/evidence/source and deletion provenance | P1, private |
| benchmark-mlperf | [MLPerf Inference Submission Guide](https://docs.mlcommons.org/inference/submission/) | scenarios, loadgen, latency/throughput and quality rules | P0 |
| serving-vllm | [vLLM Benchmark CLI](https://docs.vllm.ai/en/stable/benchmarking/cli/) | TTFT/TPOT/ITL and serving benchmark controls | P0 |
| serving-tensorrtllm | [TensorRT-LLM Documentation](https://nvidia.github.io/TensorRT-LLM/) | model recipes, serve/bench, profiler and telemetry | P1 |
| model-hf-cards | [Hugging Face Model Cards](https://huggingface.co/docs/hub/model-cards) | model/dataset context, revision and license metadata | P1 |
| agent-agentbench | [AgentBench](https://github.com/THUDM/AgentBench) | multi-turn environments, tools and task failures | P1 |
| agent-tau3 | [τ³-bench repository](https://github.com/sierra-research/tau2-bench) | user-agent-tool conversations, policy and pass-k | P1 |
| agent-bfcl | Authority chain: Berkeley-hosted [BFCL V4 leaderboard](https://gorilla.cs.berkeley.edu/leaderboard.html) → ShishirPatil/gorilla [BFCL evaluator/code/data at commit `f7cf7359b7ac615a0b294831c5ba2bc95ee4a000`](https://github.com/ShishirPatil/gorilla/tree/f7cf7359b7ac615a0b294831c5ba2bc95ee4a000/berkeley-function-call-leaderboard) | Official leaderboard names this reproduction checkpoint and `bfcl-eval==2025.12.17`; pin task split and verify dataset-specific rights | P1 |
| dse-ax-botorch | [Ax Multi-Objective Optimization](https://ax.dev/docs/recipes/multi-objective-optimization/) | constrained/noisy trials and Pareto/hypervolume search | P1 |
| trace-otel-genai | [OpenTelemetry GenAI Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) | session/agent/model/tool spans and metric semantics | P0 |
| experiment-mlflow | [MLflow Tracking](https://www.mlflow.org/docs/latest/tracking/) | run parameters, metrics, code and artifact identity | P1 |
| prov-w3c-provo | [W3C PROV-O](https://www.w3.org/TR/prov-o/) | entity/activity/agent and derivation provenance | P1 |
| research-arxiv | [arXiv Bulk Data Access](https://info.arxiv.org/help/bulk_data.html) | versioned paper metadata and per-version full-text license | P0 |
| index-openalex | [OpenAlex API](https://help.openalex.org/api/) | works/authors/citation graph and OA metadata | P1 |
| index-semantic-scholar | [Semantic Scholar API](https://api.semanticscholar.org/api-docs/) | paper/reference graph and OA discovery metadata | P1 |
| index-crossref | [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) | DOI/deposit/license/correction metadata | P0 |
| publisher-acm-ieee | [ACM Digital Library platform](https://libraries.acm.org/digital-library/platform-and-features) + [IEEE Xplore Terms](https://ieeexplore.ieee.org/Xplorehelp/overview-of-ieee-xplore/terms-of-use) | ACM current OA/platform and per-item rights; IEEE publisher access/TDM boundaries | P2, gated |
| publisher-usenix | [USENIX OSDI proceedings](https://www.usenix.org/conference/osdi24/technical-sessions) | open systems/DSE proceedings and artifact links | P1 |

## 탐색 질문과 seed literature

seed는 검토 시작점이지 corpus를 구성하거나 결론을 고정하지 않는다. full text를 얻을 때도 개별 license와 access terms를 확인한다.

| 질문 | 시작 검색식 및 확인할 대표 seed |
|---|---|
| B300 rack/tray/package/device 사실과 vendor-claim/measurement 경계는 무엇인가? | site:nvidia.com GB300 NVL72 B300 datasheet; site:docs.nvidia.com DGX B300 user guide power rack; site:docs.nvidia.com NVL72 AI factory components/network topology |
| session trace와 GPU/hardware queue·contention·service latency가 어떻게 결합되는가? | agentic serving trace replay job-level metrics; serving TTFT TPOT inter-token latency goodput; τ-bench tool-agent-user interaction; DistServe OSDI 2024: https://www.usenix.org/conference/osdi24/presentation/zhong-yinmin |
| fused kernel search, tiling, fold/unfold event 수와 측정된 실행의 잔차를 어떻게 비교할까? | tensor program search hierarchical schedule fusion cost model; Roofline authors’ eScholarship record: https://escholarship.org/uc/item/5tz795vq; Ansor OSDI 2020: https://www.usenix.org/conference/osdi20/presentation/zheng |
| memory/fabric/package constraints의 모델 오차는 어디서 오는가? | HBM refresh/banks/thermal power per bit; UCIe die-to-die package PHY; CXL memory pooling performance; Ramulator 2.1 real-system modeling validation; OCP cooling loop power capacity alignment |
| 어떤 optimizer가 noisy, costly, multi-objective exploration을 잘 보조하는가? | multi-objective noisy BO Pareto preference Ax BoTorch; cost-aware/decoupled objectives; hierarchical search of accelerator mapping; seed마다 validation set을 잠그고 prior와 measurement를 분리 |
| session scenario의 representative coverage와 privacy를 어떻게 검수할까? | τ³/AgentBench/BFCL multi-turn tool policies and state; GAIA as auxiliary broad-task source; no hidden reasoning; expose only permitted outer event boundaries and minimal content |
| source conflict·retraction·version을 어떻게 보존할까? | arXiv per-version license/DOI; Crossref update metadata; OpenAlex/S2 metadata drift; provenance model entity/activity/derivation; supersede, never silently overwrite |

## 검색·중복 제거·권리 판정 절차

1. family별 query를 versioned allowlist에 둔다. authoritative hostname + exact product/standard/model/revision + power, bandwidth, latency, thermal, fusion, trace, metric, license, errata 조합으로 검색하고 각 결과를 publisher/maintainer site에서 재확인한다. OpenAlex/S2/Crossref/arXiv는 discovery와 metadata reconciliation용이고, 원문이 필요한 주장에는 실제 publisher/maintainer/repository version을 따른다.
2. identity 우선순위는 DOI → arXiv ID/version → standard number/revision/ECN → SKU/part number → git remote + commit/tag → canonical URL + checksum이다. preprint/publisher version·errata·vendor product variants는 서로 병합하지 않고 related/supersedes edges로 연결한다.
3. 다운로드 전에 source URL·publisher·공식 문서 ID·revision·출판/수정일·access class·license/TDM/AI conditions·retrieved_at을 기록한다. 허용된 바이트만 checksum과 parser version으로 보존한다. 허용되지 않은 source는 identifier/최소 metadata/citation/rights decision만 둔다. 의문이면 자동 추출·모델 질의 없이 metadata-only 상태로 격리한다.
4. 표는 열·행·footnote·단위와 page/table ID를 같이 추출한다. 식은 원 기호와 normalization을 함께 보존한다. Figure의 값은 그림 ID·축·pixel/digitization confidence를 남겨 출처 본문/표로 교차 확인한다. code는 repository commit·file path·line 범위·license를 보존한다. OCR/LLM extraction은 제안이고 source anchor 및 결정론적 parser/수기 review가 검증한다.
5. 추출 단위는 source-anchored evidence와 claim type·적용 scope·valid time·기기/환경·measurement method·불확실도다. spec/marketing/standard/measurement/simulation/hypothesis를 분리하고, 서로 다른 버전/측정이 충돌하면 두 Claim과 Evidence를 남겨 committee에 conflict를 제공한다. 독립성이 없는 재인용·동일 run replay를 독립 증거로 세지 않는다.
6. refresh는 page/API/commit/standard errata·model card license change·benchmark correction·metric semantic version change 때 즉시 재평가한다. 기준 cadence는 JSON에 source별 기록했다. 이전 artifact는 checksum·retracted/superseded 관계로 보존하고 영향받은 Design Point의 재검토를 열어둔다.

공통 quality gate는 (a) source identity/version·per-work rights, (b) 정확한 unit/scope/time/measurement boundary, (c) 표 footnote·equation·figure anchors, (d) 독립 comparator/known limits, (e) license-specific retention/redaction, (f) parser/schema regression이다. 측정은 run hash·config·random seed·device/driver/firmware/clocks/power cap·ambient·warm-up·concurrency·workload manifest·sample count·percentiles/confidence interval·measurement overhead를 묶는다. 누락 정보는 추정값으로 채우지 않고 unknown과 다음 검증 질문으로 남긴다.

## 권리, 우선순위 점수, 검증 범위

“웹에 공개”는 원문 재배포·대량 수집·LLM/AI 입력 권리를 자동으로 뜻하지 않는다. 특히 UCIe는 spec request, CXL은 evaluation copy agreement와 AI policy, JEDEC은 표준 접근권, PCI-SIG는 AI/TDM와 systematic access 제한, IEEE Xplore는 robot/AI 금지, ASHRAE는 유료 Datacom 접근을 별도로 확인한다. ACM은 2026-01-01부터 ACM publications를 full Open Access로 전환했다고 알렸지만, 이는 개별 article license나 bulk/API/TDM 권한을 일괄 허가한다고 해석하지 않는다. 이 검토에서 ACM의 현재 플랫폼 안내와 canonical usage-policy 경로는 확인했지만, 정책 본문/API terms는 fetch되지 않아 unverified다. 따라서 ACM 전문도 per-item rights 확인 전 metadata-only로 둔다. DOI 대량 discovery는 Crossref API 후보를 쓰고, ACM의 item identity/version/license는 publisher landing에서 확인한다. legacy usage-old 경로는 2026 정책 판단의 권위 있는 근거로 쓰지 않는다. OCP·USENIX·arXiv·GitHub 또한 각 spec/article/file/version의 license와 attribution을 점검한다. model/dataset card의 license field만으로 artifact 권리를 추정하지 않는다.

source recommendation rubric은 tool·제품 성능 평가와 별개인 expert prior다. 축별 raw score는 0–5 정수다: relevance 30, authority 25, extractability 15, rights 15, freshness 10, diversity 5. total은 Σ(weight × raw_score) / 5, 즉 /100이다. rights 점수가 낮거나 terms가 미해결인 source는 높은 총점이어도 P2/metadata-only로 게이트한다. confidence는 이 source 평가의 확신이지 claim의 진실 확률이 아니다. 출처 추천점수는 benchmark 점수·설계점 성능·물리 법칙 검증 PASS가 아니다.

Jev 1.13 advisory 선택은 첫 factual anchor로 hw-nvidia-b300을 골랐다(확률 1.0, advisory only, 비용 $0.000037842). 결과를 raw source scores나 성능 근거에 넣지 않았다. 이후 선택은 authority·rights 검토와 JSON의 결정론적 계산이 관리한다.

40개 후보 family는 기본 reference set이며 exhaustive 목록이나 승인된 ingest inventory가 아니다. 공개 1차 문서의 페이지·scope·access 조건을 웹에서 확인했고, internal HAT/Melete는 remote URL 존재만 확인했다. 초기 파일 수집, 대규모 API harvest, licensed standards 접근, 실제 hardware measurement는 수행하지 않았다. JEDEC host의 자동 fetch는 robots에 막혀 공식 landing page만 확인했으므로 그 전문·revision detail의 상태는 미확인이다.
