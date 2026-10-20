# DSE 지식·실험 시스템: 아키텍처와 구현 준비

상태: **architecture·planning + 실제 수집 대상 목록** · 기준일: 2026-10-21 KST · 보고용 webapp·metadata 목록 제공. RAG runtime·embedding·KG 등록 pipeline은 미실행.

이 README는 DSE 결정별 지식 요구를 만들고, 허가된 source에서 evidence를 취득·구조화하며, hardware/kernel/experiment 결정에 쓰고 부족한 지식을 다시 수집하는 전체 구조를 설명한다. 2026-10-18 사용자 정정에 맞춘 상위 기준은 [2026-10-21-dse-knowledge-architecture.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/superpowers/specs/2026-10-21-dse-knowledge-architecture.md)와 [2026-10-21-knowledge-architecture-plan.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/superpowers/plans/2026-10-21-knowledge-architecture-plan.md)다. 이전 HAT native episode/adapter 계약은 세부 참고이며 이 architecture의 중심 gate가 아니다.

## 실제 자료 목록 수집 결과 — 2026-10-21

**중복 제거 후 145,748건 등록**, 100,000건 목표 달성. Source 검토 범위는 초기 40개에서 **77개 family**로 확장했다.

| 단계 | 실제 결과 |
|---|---|
| STEP 1 | CPU/ISA/RTL, GPU simulation, compiler/kernel, power/thermal, serving/trace, 측정·최적화 source 누락을 보완해 77개 family의 entrypoint·발견 경로를 확인 |
| STEP 2 | arXiv 공식 metadata snapshot 3,215,335개 record를 확인하고, 분야 선별·scholarly index를 합쳐 1,146,381개 후보 관측을 처리. Source 간 중복 포함 |
| STEP 3 | 제목과 공개 초록/문서 앞부분 약 10줄을 자동 규칙으로 선별하고 DOI·arXiv ID·원문 링크·동일 긴 제목으로 중복 정리. 최종 145,748건 |
| STEP 4 | source·제목·category·1줄 요약·link·자료 type의 6열 CSV와 집계·source 접근 상태를 제공 |

- [자료 목록 webapp](https://dse-knowledge-atlas.nocode-jimmy.chatgpt.site/materials.html) — 본인 ChatGPT 로그인, 전체 목록 검색·필터·page 탐색
- [materials.csv.gz](https://github.com/jimmylegendary/dse-knowledge/raw/refs/heads/main/research/materials/materials.csv.gz) — 등록 자료 전체
- [manifest.json](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/materials/manifest.json) — 실제 건수·policy/code hash·snapshot version
- [sources.csv](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/materials/sources.csv) — 77개 source의 개별 접근 상태와 등록 수

**판정의 범위:** 제목과 실제 관측한 공개 초록 또는 문서 앞부분을 기준으로 한 자동 선별이다. 자료별 본문 전체를 LLM이 읽어 검증한 결과가 아니다. 논문 PDF의 개별 열람·재배포 권한, 과학적 품질·주장 수용, embedding 및 KG 등록은 하지 않았다. 제약·private source는 비인증 entrypoint 응답과 실제 미확인 상태를 유지하며, 77개 source의 모든 자료를 완전 크롤링했다는 뜻은 아니다. 최적화·모델 방법론의 배경 자료도 모든 DSE 단계의 판단을 돕는 수집 대상으로 포함한다.

| Category | 등록 자료 |
|---|---:|
| Compiler / kernel | 4,830 |
| DSE / optimization | 21,034 |
| HW architecture / ISA | 13,590 |
| LLM / model / workload | 89,979 |
| Memory / interconnect | 3,817 |
| Power / thermal / packaging | 3,179 |
| Provenance / experiment | 584 |
| Serving / scheduling | 2,995 |
| Simulation / measurement | 5,740 |

등록 예시 — 공개 HEAD에서 뽑은 한 줄 요약이며 전체 본문 분석이 아니다.

| Source | 제목 | Category | 1줄 요약 | Link | 자료 type |
|---|---|---|---|---|---|
| Semantic Scholar | "A New Old Approach to Teaching Microprocessors: Update and Lessons Learned" | hardware_architecture | The construction of the microprocessor system was accompanied by lectures in a variety of topics including computer organization, instruction set architectures, the Intel family… | [원문](https://www.semanticscholar.org/paper/147b8a0719e818581be20eeee0730c6a058b405a) | scholarly_work |
| arXiv | $MC^2RAM$: Markov Chain Monte Carlo Sampling in SRAM for Fast Bayesian Inference | memory_interconnect | We show a novel architecture of SRAM by embedding it with random number generators (RNGs), digital-to-analog converters (DACs), and analog-to-digital converters (ADCs) so that… | [원문](https://arxiv.org/abs/2003.02629v1) | research_paper |
| arXiv | "Is Low Power Enough?" Rethinking Energy Efficiency in High-Fidelity Sensing | power_thermal_packaging | Scientists now want higher fidelity data from the field, such as images and audio, and these observations break that rule: a low-power microcontroller stays… | [원문](https://arxiv.org/abs/2610.14714v1) | research_paper |
| arXiv | $P_1$--nonconforming polyhedral finite elements in high dimensions | compiler_kernel | The $P_1$--nonconforming polyhedral finite element is introduced for any high dimension. | [원문](https://arxiv.org/abs/1910.04585v2) | research_paper |
| arXiv | !MSA at BAREC Shared Task 2025: Ensembling Arabic Transformers for Readability Assessment | llm_model_workload | We present MSAs winning system for the BAREC 2025 Shared Task on fine-grained Arabic readability assessment, achieving first place in six of six tracks. | [원문](https://arxiv.org/abs/2509.10040v1) | research_paper |
| arXiv | (Almost) Perfect Discrete Iterative Load Balancing | serving_scheduling | We present results for a general class of simple local balancing schemes where the tokens are balanced via matchings. | [원문](https://arxiv.org/abs/2510.15473v1) | research_paper |
| arXiv | "I Strongly Suspect This Website Is a Scam": Benchmarking PII Leakage and Detection without Defense in Autonomous Web Agents | simulation_measurement | In this paper, we show that social-engineering attacks are highly effective at extracting critical-tier PII from frontier web agents, posing a severe risk to… | [원문](https://arxiv.org/abs/2606.00497v1) | research_paper |
| arXiv | "Efficient Complexity": a Constrained Optimization Approach to the Evolution of Natural Intelligence | dse_optimization | A novel approach in the description of the information processes of natural learning is proposed in the framework of constrained optimization, where the objective… | [원문](https://arxiv.org/abs/2410.13881v2) | research_paper |
| Semantic Scholar | "Get in Researchers; We're Measuring Reproducibility": A Reproducibility Study of Machine Learning Papers in Tier 1 Security Conferences | provenance_experiment | While the Security community has recently increased its attention on reproducibility, an independent and comprehensive measurement of the current state of reproducibility has not… | [원문](https://www.semanticscholar.org/paper/d0ee37d9e5ae942fce2c48db468738e014cb6a3c) | scholarly_work |

추가 source 37개(초기 40개는 아래 설계 catalog에 유지). HTTP 상태는 entrypoint의 이번 관측이며 모든 하위 자료의 열람을 뜻하지 않는다.

| ID | 추가 source | Entry point | 등록 자료 |
|---|---|---|---:|
| s41 | [RISC-V ISA specs + ratified extensions + profiles](https://riscv.org/technical/specifications/) | HTTP 200 | 135 |
| s42 | [Apache TVM / Relax / TensorIR](https://api.github.com/repos/apache/tvm) | HTTP 200 | 139 |
| s43 | [SGLang (RadixAttention, HiCache) docs + repo](https://api.github.com/repos/sgl-project/sglang) | HTTP 200 | 351 |
| s44 | [Accelergy (energy/area model generator)](https://api.github.com/repos/Accelergy-Project/accelergy) | HTTP 200 | 2 |
| s45 | [Timeloop (dataflow mapping explorer)](https://api.github.com/repos/NVLabs/timeloop) | HTTP 200 | 4 |
| s46 | [ARM Architecture Reference Manual (A-profile) + ARM system IP docs](https://developer.arm.com/documentation/ddi0487/latest/) | HTTP 200 | 0 |
| s47 | [Intel SDM (x86-64 ISA + platform)](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html) | HTTP 200 | 0 |
| s48 | [PTX ISA (NVIDIA Parallel Thread Execution)](https://docs.nvidia.com/cuda/parallel-thread-execution/) | HTTP 200 | 1 |
| s49 | [Khronos registry (SPIR-V, OpenCL, SYCL, Vulkan)](https://registry.khronos.org/spir/) | HTTP 200 | 2 |
| s50 | [Accel-Sim / GPGPU-Sim](https://api.github.com/repos/accel-sim/accel-sim-framework) | HTTP 200 | 3 |
| s51 | [Vidur (LLM serving simulator)](https://api.github.com/repos/microsoft/vidur) | HTTP 200 | 4 |
| s52 | [Power/thermal models (HotSpot, 3D-ICE, McPAT, Accelergy)](https://api.github.com/repos/HewlettPackard/mcpat) | HTTP 200 | 1 |
| s53 | [Predictive PDKs (ASAP7, FreePDK45) + open RTL flow](https://api.github.com/repos/The-OpenROAD-Project/asap7) | HTTP 200 | 1 |
| s54 | [KV-cache reuse & PD-disaggregation (LMCache, Mooncake, NIXL)](https://api.github.com/repos/kvcache-ai/Mooncake) | HTTP 200 | 1 |
| s55 | [Azure LLM inference trace + BurstGPT (session traces)](https://api.github.com/repos/microsoft/AzurePublicDataset) | HTTP 200 | 1 |
| s56 | [Long-context & agentic evaluation suites (RULER, LongBench, SWE-bench)](https://api.github.com/repos/NVIDIA/RULER) | HTTP 200 | 1 |
| s57 | [OpenXLA / XLA HLO operation semantics](https://openxla.org/xla/operation_semantics) | HTTP 200 | 1 |
| s58 | [Kernel benchmark suites (KernelBench, TritonBench, AITer)](https://api.github.com/repos/ScalingIntelligence/KernelBench) | HTTP 200 | 1 |
| s59 | [NCCL + collective communication docs](https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/) | HTTP 200 | 126 |
| s60 | [Nsight Systems + CUPTI (timeline + counter APIs)](https://docs.nvidia.com/nsight-systems/) | HTTP 200 | 1 |
| s61 | [UALink Consortium specification](https://ualinkconsortium.org/) | HTTP 200 | 2 |
| s62 | [Ultra Ethernet Consortium specification](https://ultraethernet.org/) | HTTP 200 | 0 |
| s63 | [IBTA InfiniBand architecture specification](https://www.infinibandta.org/specs/) | HTTP 200 | 0 |
| s64 | [OCP Open Rack V3 / power delivery + contribution repository](https://www.opencompute.org/projects/open-rack-v3) | HTTP 200 | 1 |
| s65 | [HBM/DRAM vendor datasheets (SK hynix, Micron, Samsung)](https://www.skhynix.com/) | HTTP 200 | 2 |
| s66 | [Cloud instance & price catalogs (AWS EC2 price list, GCP, Azure)](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/region_index.json) | HTTP 200 | 0 |
| s67 | [MLPerf results repositories (measured submissions)](https://api.github.com/repos/mlcommons/inference_results_v5.0) | HTTP 200 | 0 |
| s68 | [OpenReview API (submissions, reviews, decisions)](https://api2.openreview.net/notes?limit=1) | HTTP 403 | 0 |
| s69 | [DBLP (venue/author bibliography, bulk XML)](https://dblp.org/search/publ/api?q=llm%20serving&format=json&h=1) | HTTP 202 | 0 |
| s70 | [IETF Datatracker (RFC + drafts)](https://datatracker.ietf.org/api/v1/doc/document?limit=1) | HTTP 200 | 0 |
| s71 | [Metric/provenance metadata specs (OpenMetrics, Croissant, DCAT)](https://prometheus.io/docs/instrumenting/exposition_formats/) | HTTP 200 | 2 |
| s72 | [Industry engineering blogs with measured numbers (NVIDIA technical blog, Meta/Google infra blogs)](https://developer.nvidia.com/blog/) | HTTP 200 | 2 |
| s73 | [PyTorch Inductor (torch.compile fusion/lowering)](https://api.github.com/repos/pytorch/pytorch) | HTTP 200 | 1 |
| s74 | [IREE (MLIR-based compiler/runtime for accelerators)](https://api.github.com/repos/iree-org/iree) | HTTP 200 | 90 |
| s75 | [Constrained DSE/HPO tooling (Optuna, Ray Tune)](https://docs.ray.io/en/latest/tune/index.html) | HTTP 200 | 0 |
| s76 | [SPEC benchmark results and power/energy methodology](https://www.spec.org/power_ssj2008/results/) | HTTP 200 | 3 |
| s77 | [CUDA math libraries + attention kernels (cuBLAS, cuDNN, CCCL/CUB, FlashAttention, FlashInfer)](https://docs.nvidia.com/cuda/cublas/index.html) | HTTP 200 | 74 |

## 한눈에 보기

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#f6f8fa'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  T[DecisionTask + requirements] --> P[CollectionPlan + QueryPlan]
  P --> S[Rights-gated sources]
  S --> X[Immutable revision + structured extraction]
  X --> L[Canonical ledger + outbox]
  L --> Q[Exact + hybrid + graph reads]
  Q --> D[Validation + DecisionRecord]
  D --> E[Experiment + MetricVector]
  E --> G[Insight + reopened gaps]
  G --> T
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class T,D focal;
  class S,E external;
  class P,X,L,Q,G normal;
```

| 구간 | 책임 | authority / 결과 |
|---|---|---|
| DecisionTask → KnowledgeRequirement | 어떤 결정에 어떤 근거·scope·완료조건이 필요한지 분해 | user decision와 unresolved requirement |
| CollectionPlan → SourceRevision | source discovery, rights gate, acquisition, extraction | revision-pinned source/artifact와 parser provenance |
| Canonical ledger | typed Claim/Evidence, asset/recipe, rules, workload, experiment/event/metric | versioned knowledge and experiment authority |
| Read paths | exact/lexical/dense/graph retrieval과 full required-rule coverage | cited EvidenceBundle, coverage, conflict, unknown |
| Validator/reviewer | deterministic unit/version/scope/legality checks와 evidence-backed review | pass/fail/unknown, review finding, scoped DecisionRecord |
| Experiment/Insight feedback | proposal, run, MetricVector, failure, scoped Insight | 다음 요구·수집계획·실험 proposal 또는 stop 이유 |

원문 조회·색인 rank·committee vote는 그 자체로 truth나 buildability를 증명하지 않는다. MetricVector는 TTFT, TPOT, throughput, tail/SLO, quality, power, energy, memory/network cost 등을 단위·scope·method·uncertainty와 함께 보존한다. 결측 지표를 0으로 채우거나 모든 지표를 단일 성능점수로 합치지 않는다.

## 현재 dev baseline과 infra 경계

아래는 이번 설계 준비에서 확인된 dev baseline이다. Supabase account 존재는 project·namespace 권한이나 연결 완료를 뜻하지 않는다. 이 README를 위해 계정에 접속하거나 host 설정을 바꾸지 않았다.

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#ffffff'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  U[User or agent] --> W[Linux CPU worker<br/>수집·파싱·검색·분석]
  W --> PG[Existing Supabase PostgreSQL<br/>정본·Job/Outbox·pgvector·FTS·typed graph]
  W --> A[Local artifact storage]
  W --> PI[Configurable provider interface]
  PI --> OR[OpenRouter option]
  PI --> CX[Host Codex CLI option<br/>원격 모델 추론]
  W --> LC[Optional CPU-local embedding/rerank]
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class W,PG focal;
  class U,A,PI,LC normal;
  class OR,CX external;
```

| 영역 | 현재 설계 기준 | 확인·준비 상태 |
|---|---|---|
| Canonical data layer | Existing Supabase account; PostgreSQL, pgvector/FTS, typed-graph representation in PG | Dev baseline only; project ref, database route, schema permission, migration authority unconfirmed; Neo4j remains a later challenger, not the dev default |
| Compute / job state | Current Linux host의 CPU worker; durable job state와 transactional outbox는 canonical ledger와 같은 PostgreSQL에 보존 | No service/configuration installed. Read-only observation dated 2026-10-21: 16 logical CPUs, 27.2 GiB total RAM. 가용 메모리는 변동하며 실제 parse/embedding 처리량은 미측정 |
| Raw/document/run artifacts | Local artifact store on the current host | No dedicated backup mount/quota confirmed. Workspace free space is not backup capacity. Managed object storage is a future scale/recovery option, not an initial dependency |
| Chat/model provider | OpenRouter or Codex through a configurable provider interface and existing environment names | Provider/model ID, account entitlement and auth mode remain unselected. No API key is requested, issued or pasted |
| Embedding/reranking | Separate interfaces; CPU-local route possible; remote route optional | No GPU required or requested now. CPU throughput and retrieval quality are unmeasured |
| Cloud and exposure | No new cloud resource; local development boundary | AWS is prohibited. Namespace, TTL/retention, CPU worker count, request/source size limits and query budgets are proposals, not active settings |
| Internal data | Confluence, internal runs and HAT/Melete artifacts only through owner-approved allowlist | No private corpus or experiment log has been connected or bulk-collected |

All 48 existing names in [.env.example](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/.env.example) are configuration-contract names only; values there are blank/proposals and are not instructions to request credentials. No new environment key is introduced.

| Group | Existing environment names |
|---|---|
| Supabase / namespace | <code>SUPABASE_PROJECT_REF</code>, <code>SUPABASE_DB_MODE</code>, <code>SUPABASE_AUTH_MODE</code>, <code>SUPABASE_DB_URL_REF</code>, <code>SUPABASE_DB_URL</code>, <code>SUPABASE_DB_SCHEMA</code>, <code>DSE_NAMESPACE</code>, <code>SUPABASE_DB_HOST</code>, <code>SUPABASE_DB_PORT</code>, <code>SUPABASE_DB_NAME</code>, <code>SUPABASE_DB_PASSWORD_REF</code>, <code>SUPABASE_DB_PASSWORD</code>, <code>SUPABASE_URL</code>, <code>SUPABASE_PUBLISHABLE_KEY_REF</code>, <code>SUPABASE_PUBLISHABLE_KEY</code> |
| Linux worker / local paths | <code>DSE_SERVICE_MODE</code>, <code>DSE_SERVICE_USER</code>, <code>DSE_DATA_ROOT</code>, <code>DSE_ARTIFACT_ROOT</code>, <code>DSE_MODEL_CACHE_ROOT</code>, <code>DSE_LOG_ROOT</code>, <code>DSE_BACKUP_ROOT</code>, <code>DSE_CPU_WORKERS</code>, <code>DSE_BIND_HOST</code>, <code>DSE_ALLOWED_CIDRS</code> |
| Chat | <code>CHAT_PROVIDER</code>, <code>CHAT_BASE_URL</code>, <code>CHAT_MODEL_ID</code>, <code>CHAT_AUTH_MODE</code>, <code>CHAT_API_KEY_REF</code>, <code>OPENROUTER_API_KEY</code>, <code>CODEX_EXECUTABLE</code>, <code>CODEX_AUTH_MODE</code>, <code>CODEX_API_KEY_REF</code>, <code>CODEX_API_KEY</code> |
| Embedding | <code>EMBEDDING_PROVIDER</code>, <code>EMBEDDING_BASE_URL</code>, <code>EMBEDDING_MODEL_ID</code>, <code>EMBEDDING_DIMENSIONS</code>, <code>EMBEDDING_AUTH_MODE</code>, <code>EMBEDDING_API_KEY_REF</code>, <code>DSE_EMBEDDING_API_KEY</code> |
| Reranker | <code>RERANKER_PROVIDER</code>, <code>RERANKER_BASE_URL</code>, <code>RERANKER_MODEL_ID</code>, <code>RERANKER_AUTH_MODE</code>, <code>RERANKER_API_KEY_REF</code>, <code>DSE_RERANKER_API_KEY</code> |

Secrets stay in an owner-approved secret manager or untracked local environment. The README names existing references only; it contains no secret value, private path, or provider credential request.

### 요청·자원 한도와 설정 상태

| Input | Decision | Current status |
|---|---|---|
| Namespace | Existing key <code>DSE_NAMESPACE</code>; example namespace is a proposal only | Not finalized |
| Worker count | Existing <code>DSE_CPU_WORKERS</code>; two workers is a proposal only | No service running |
| TTL/retention | Separate raw, derived, index, cache, event and backup retention | Policy and durations are unselected proposals |
| Work limits | Per-task budget, source bytes/pages, queue depth, parse timeout, retrieval budget, max result payload | Contract requirements to design; no active limiting settings |
| Memory | 모델별 peak RAM을 측정하고 worker concurrency·cache 한도를 설정; remote/cpu-local route는 교체 가능 | CPU 경로의 용량·처리량 평가 전이며 GPU나 RAM 증설을 요구하지 않음 |
| Credential timing | Provider auth reference can be set later if an approved route needs it | No API key is requested or issued |

## DSE 결정별 필요한 지식

Each task creates requirements before it creates a confident answer. A requirement has a target scope/version, required claim and relationship types, authority/freshness, units/measurement boundary, evidence completeness, blocking level, accepted source routes and an explicit satisfaction predicate. Its state can be uncovered, partial, satisfied, conflicted, blocked, unknown or stale.

| DSE decision domain | Decisions | Data/evidence required |
|---|---|---|
| Model, agent and workload | Which model/serving/session conditions are comparable? | Model/tokenizer/chat-template revision, prompt/turn/tool events visible to the user, arrival/timing/KV/cache policy, quality/SLO, seeds; hidden chain-of-thought is not collected |
| Hardware assembly | Can assets form a legal, usable system across rack/tray/package/die/SoC/component? | Exact asset revision, ports/protocols, containment and connection, lanes/rates, capacity, power/thermal/cooling envelope, compatibility constraints, units and source spans |
| ISA, compiler and kernel | Does a recipe preserve semantics and fit target capability? | ISA and programming model, operation/dtype/shape/layout, compiler/dialect/pass version, synchronization/memory behavior, fold/unfold/fusion transforms, correctness and resource bounds |
| Simulation/circuit/system models | Which claims are analytic, simulated, calibrated or measured? | Equations/parameters, valid domain, calibration evidence/residuals, fidelity level, assumptions, uncertainty and unsupported dimensions |
| Experiment analysis | Did an intervention improve the selected outcomes without hiding regression? | Run manifest/event chain, cohort compatibility, all MetricVector components, metric definitions, sample/quantiles, missingness, failure taxonomy, measurement boundaries and independent lineage |
| Next action | What source, measurement or experiment resolves the highest-impact gap? | Open KnowledgeRequirements, decision criticality, rights/access state, expected information gain, collection/run cost, owner and stop condition |

## 필요 AI 모델과 역할별 후보

모델은 파싱·검색·후보 생성을 돕고, 채택 여부는 명시적 규칙과 근거 검토로 판단한다. 아래는 역할별 모델 연결도이며 실제로 검증한 serving topology는 아니다.

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#ffffff'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  T[문서·질문·DSE 작업] --> R[Role and capability router]
  R --> P[CPU parser<br/>Docling·AST·config/log parser]
  R --> L[생성·추론 모델<br/>OpenRouter 또는 Codex]
  R --> D[Embedding model<br/>BGE-M3 또는 Qwen3 후보]
  R --> X[Reranker model<br/>BGE 또는 Qwen3 후보]
  P --> C[구조화 요소·Claim 후보·근거 위치]
  L --> C
  D --> V[버전별 vector space]
  X --> E[재정렬한 evidence 후보]
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class R,C focal;
  class T external;
  class P,L,D,X,V,E normal;
```

| 역할 | 우선 평가·비교 후보 | 사용 범위와 준비 상태 |
|---|---|---|
| Chat and candidate extraction | OpenRouter or Codex behind provider interface; model ID uses existing environment names | Interface-first. Output is candidate Claim/query plan or cited explanation, never acceptance. No model ID or credential tested |
| Embedding | [BGE-M3](https://huggingface.co/BAAI/bge-m3), 1024차원 reference; [Qwen3-Embedding-4B](https://huggingface.co/Qwen/Qwen3-Embedding-4B), 1024차원 출력 profile challenger | Prior candidates only. CPU/remote capability·RAM·품질을 비교하며 model revision·출력 차원·정규화·index 호환성을 함께 고정 |
| Reranking | [BGE-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) reference; [Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) challenger; disabled is allowed | Evaluate on same held-out evidence queries, with CPU/memory and remote route measured separately |
| Document parsing | Docling candidate for documents/PDF layout; deterministic AST/code/config/log parsers | Exact source spans and extraction uncertainty remain available; parser name is not an accuracy claim |
| Finite classification | Existing shared Jev interface as optional source/query/rubric candidate classifier | Advisory finite choice only; no new credential and no fact, rule, rights or execution authority |
| Validation and metric calculation | Deterministic typed validator and programmatic unit/cohort/metric logic | Not an LLM role. Missing applicability/evidence stays unknown |

Candidate priorities are not benchmark results. No model inference or provider credential call was run. Final choices require the same DSE gold queries, source spans, negative/no-answer cases, CPU/remote profiles, privacy and cost boundary.

## Source별 수집 data: 40개 family

The catalog is a **collection plan**, not a captured corpus. Each row states the material to acquire and the decisions it can support. Revision/hash, source span, rights, acquisition method, refresh trigger and quality checks remain in the linked [01-source-catalog.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/research/01-source-catalog.md) and [01-source-catalog.json](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/research/01-source-catalog.json).

Access tags: <code>PUBLIC</code> means public discovery/selected facts with attribution, not bulk redistribution permission; <code>REPO</code> means pin repository/model/data revisions and check each license; <code>META</code> means metadata/public abstracts only until full-text terms explicitly permit use; <code>LICENSE</code> means metadata-only until item/spec/license and AI/TDM terms are approved; <code>INTERNAL</code> means allowlisted design docs or synthetic/redacted fixtures only; <code>AUTHORIZED</code> means user or experiment-owner approval is required. Standards are not imported as raw full text by default. Product marketing claims are never relabeled measured performance.

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#f6f8fa'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  T[DecisionTask] --> R[KnowledgeRequirement router]
  R --> H[Hardware + standards]
  R --> K[ISA/compiler/kernel]
  R --> M[Model/serving/agent workload]
  R --> S[Simulation/measurement]
  R --> L[Literature/experiment/provenance]
  H --> G[Rights + scope gate]
  K --> G
  M --> G
  S --> G
  L --> G
  G --> V[Versioned SourceRevision]
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class T,R,G focal;
  class H,K,M,S,L external;
  class V normal;
```

| Source group | Example families | Typical decision / collection gate |
|---|---|---|
| Hardware + standards | NVIDIA/AMD, OCP, UCIe, CXL, JEDEC, PCI-SIG, IEEE, ASHRAE | Asset hierarchy, interface legality, bandwidth/power/thermal; standards detail stays metadata-only until access approval |
| ISA/compiler/kernel | CUDA/PTX, MLIR, Triton, CUTLASS, OpenROAD/SKY130, CACTI | Operation/dtype/layout legality, code and transform semantics, circuit/memory model domain |
| Model/serving/agent workload | MLPerf, vLLM, TensorRT-LLM, HF cards, AgentBench, τ-bench, BFCL, OpenTelemetry | Model/license, session/tool/timing/SLO semantics, serving metrics; user traces need explicit authorization |
| Simulation/measurement | Nsight, DCGM, gem5, Ramulator, BookSim, SST | Instrument boundary, counters, model assumptions, calibration and fidelity; measurement is separate from simulator output |
| Literature/experiment/provenance/experience | arXiv/OpenAlex/Semantic Scholar/Crossref, ACM/IEEE, USENIX, MLflow, PROV-O, Ax/BoTorch, HAT/Melete references | Research discovery, trials/lineage, prior failure and Insight; per-item rights and internal allowlists apply |

| # / family | Primary source | Collect and structure | Supports | Gate |
|---:|---|---|---|---|
| 01 NVIDIA system docs | [NVIDIA GB300/NVL72](https://www.nvidia.com/en-us/data-center/gb300-nvl72/) | SKU/configuration variants, rack/tray/GPU/CPU/network composition, power, thermal, memory, links, claim footnotes | HW asset composition, capacity and budget questions | PUBLIC; attribute vendor claims |
| 02 CUDA/PTX | [CUDA Programming Guide](https://docs.nvidia.com/cuda/cuda-programming-guide/) | Execution/memory/synchronization/datatype semantics, instruction constraints, architecture support | ISA and kernel legality | PUBLIC; pin guide/ISA revision |
| 03 Nsight Compute | [Profiling Guide](https://docs.nvidia.com/nsight-compute/ProfilingGuide/index.html) | Metric definitions/scope/aggregation, replay/sampling, report fields, profiler overhead | Metric interpretation and experiment setup | PUBLIC; workload reports need local controls |
| 04 DCGM | [DCGM Exporter metrics](https://docs.nvidia.com/datacenter/dcgm/latest/reference/dcgm-exporter-metrics.html) | Field IDs for power, clocks, temperature, utilization, memory, PCIe/NVLink | Telemetry mapping and resource observations | PUBLIC docs; telemetry may expose infrastructure |
| 05 AMD MI350/ROCm | [MI350 architecture](https://rocm.docs.amd.com/en/develop/reference/gpu-arch/mi350.html) | XCD/IOD/chiplets, HBM, partitioning, ISA/counters, topology, power/cooling | Cross-vendor HW and software comparisons | PUBLIC; vendor claims remain attributed |
| 06 OCP | [OCP cooling environments](https://www.opencompute.org/projects/cooling-environments/) | Rack/tray/module/connector/power interfaces, OAM/OAI/UBB, cold plate/CDU/coolant | Rack/tray/package composition and cooling | LICENSE; check each document’s terms |
| 07 UCIe | [UCIe specifications](https://www.uciexpress.org/specifications) | PHY/protocol/software stack, package class, rates, topology, compliance and revisions | Die/package interconnect compatibility | LICENSE; metadata first |
| 08 CXL | [CXL specifications](https://computeexpresslink.org/cxl-specification/) | Revision/ECN, memory/fabric feature scope; licensed timing/protocol tables only if authorized | Memory/fabric topology constraints | LICENSE; agreement and AI/TDM terms |
| 09 JEDEC | [JEDEC standards](https://www.jedec.org/) | Standard ID/revision/title/date/public scope; licensed timing/organization/test tables only after entitlement | HBM/DDR capability and limits | LICENSE; metadata only by default |
| 10 PCI-SIG | [PCI-SIG specifications](https://pcisig.com/specifications) | Public revision/status/errata; licensed lane, encoding, protocol/compliance details only if allowed | PCIe connectivity and link constraints | LICENSE; no systematic/AI access without permission |
| 11 IEEE 802.3 | [IEEE 802.3 working group](https://www.ieee802.org/3/) | Amendment/status/revision, PHY scope, speed/reach, MIB/YANG metadata | Ethernet/fabric link compatibility | META; no robots/systematic or licensed-content AI processing |
| 12 ASHRAE | [ASHRAE site planning](https://www.ashrae.org/technical-resources/topics-and-initiatives/ai-data-center/site-planning) | Public air/liquid envelope summaries, W-classes, humidity, facility/IT measurement boundaries | Thermal/facility feasibility | LICENSE; full Datacom guide requires rights |
| 13 OpenROAD/SKY130 | [OpenROAD Flow Scripts](https://openroad-flow-scripts.readthedocs.io/en/latest/) | RTL-to-GDS flow, cells/libraries/DRC, area/timing/power report method | Circuit-design methodology and early proxy studies | REPO; SKY130 is not advanced-node B300 evidence |
| 14 CACTI | [CACTI repository](https://github.com/HewlettPackard/cacti) | Model inputs/equations for access/cycle time, area, leakage/dynamic power and IO | Memory/cache model estimates | REPO; pin model/data license and valid domain |
| 15 gem5 | [gem5 documentation](https://www.gem5.org/documentation/) | CPU/cache/coherence/ports/timing object semantics, configuration and stats | Architecture and system simulation | REPO; model claims remain configuration-relative |
| 16 Ramulator 2 | [Ramulator 2 repository](https://github.com/CMU-SAFARI/ramulator2) | DDR/HBM presets, controller policy, trace frontends, validation tests and output stats | DRAM timing and controller studies | REPO; trace license separate |
| 17 BookSim | [BookSim 2 repository](https://github.com/booksim/booksim2) | Router/topology/routing/traffic and cycle-level latency/throughput | Network/interconnect simulation | REPO; check bundled models/data |
| 18 SST | [SST getting started](https://sst-simulator.org/sst-docs/docs/guides/start) | Processor/memory/network components, events, clocks, stats and configuration | Multi-component simulation | REPO; check each third-party model |
| 19 MLIR | [MLIR docs](https://mlir.llvm.org/docs/) | Operation/type/attribute constraints, pass legality, rewrite/fusion/lowering and IR serialization | Compiler semantics and kernel lowering | PUBLIC/REPO; pin dialect/pass revisions |
| 20 Triton | [Triton tutorials](https://triton-lang.org/main/getting-started/tutorials/) | Kernel algorithms, tiles/layouts, fusion/pipeline, launch config and supported hardware | Kernel recipe candidates | REPO; examples are not measurements |
| 21 CUTLASS/CuTe | [CUTLASS repository](https://github.com/NVIDIA/cutlass) | Kernel registry, tile/layout/datatype/SM constraints, fusion/epilogue, profiler inputs/results | Targeted kernel selection and profiling | REPO; results apply only to matching config |
| 22 HAT internal | [hat-system reference](https://github.com/jimmylegendary/hat-system) | Allowlisted schema/system contracts, composition/legality, HATIR fold/unfold/fusion semantics and limitations | Native hardware/kernel adapter scope | INTERNAL; no unrelated data or code redistribution |
| 23 Melete internal | [Melete reference](https://github.com/jimmylegendary/melete) | Allowlisted event/Experience/Claim/Evidence mappings, revision/deletion provenance and synthetic fixtures | Failure experience and feedback linkage | INTERNAL; no user prompts/experience without consent |
| 24 MLPerf | [MLPerf Inference submission rules](https://docs.mlcommons.org/inference/submission/) | Scenarios, LoadGen, latency/throughput definitions, quality targets, result history | Benchmark cohort and metric semantics | PUBLIC rules/results; model/dataset rights separate |
| 25 vLLM | [vLLM benchmarking docs](https://docs.vllm.ai/en/stable/benchmarking/cli/) | Scheduler/KV behavior, TTFT/TPOT/ITL, throughput, cache and client measurement controls | Serving/workload questions | PUBLIC/REPO; prompt/output data off by default |
| 26 TensorRT-LLM | [TensorRT-LLM docs](https://nvidia.github.io/TensorRT-LLM/) | Hardware/model support, benchmark controls, telemetry, scheduling/KV/fusion features | Serving and kernel/recipe options | PUBLIC; code/CUDA/model rights separate |
| 27 Hugging Face cards | [Model cards documentation](https://huggingface.co/docs/hub/model-cards) | Architecture/tokenizer/context, intended use, evaluations, lineage, license, limitations | Model/quality and source-eligibility checks | PER-MODEL; card is not a blanket weight grant |
| 28 AgentBench | [AgentBench repository](https://github.com/THUDM/AgentBench) | Environment/task prompts, tool schema, state transitions, scores and failure classes | Agent workload scenarios | REPO; task/environment data licenses vary |
| 29 τ-bench family | [tau2-bench repository](https://github.com/sierra-research/tau2-bench) | Multi-turn tool/API/policy traces, final state, reliability/pass^k and modality | Tool-agent session and policy workloads | REPO; call this τ-bench family; do not imply τ3 |
| 30 BFCL | [Berkeley Function Calling Leaderboard](https://github.com/ShishirPatil/gorilla/tree/f7cf7359b7ac615a0b294831c5ba2bc95ee4a000/berkeley-function-call-leaderboard) | Tool schemas/calls, task categories, multi-turn backends and memory/web tasks | Function-calling evaluation scenarios | REPO; benchmark/data rights check |
| 31 Ax/BoTorch | [Ax multi-objective recipe](https://ax.dev/docs/recipes/multi-objective-optimization/) | Search spaces, constraints, noisy trials, Pareto/hypervolume and cost-aware evaluations | DSE search strategy | PUBLIC/REPO; suggestions do not establish HW truth |
| 32 OpenTelemetry GenAI | [GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) | Session/agent/model/tool spans, tokens/latency/errors and hardware/resource attributes | Observable agent trace schema | PUBLIC; content/PII off by default, redaction/retention needed |
| 33 MLflow | [MLflow tracking](https://www.mlflow.org/docs/latest/tracking/) | Experiment/run IDs, params, metrics, code version, artifacts/status/times and dataset lineage | Experiment reproducibility | REPO; prompts/secrets/proprietary data need controls |
| 34 W3C PROV-O | [PROV-O recommendation](https://www.w3.org/TR/prov-o/) | Entity/activity/agent, attribution, derivation, generation/use and time relations | Provenance relationship semantics | PUBLIC; do not expose proprietary source bodies in triples |
| 35 arXiv | [arXiv bulk data](https://info.arxiv.org/help/bulk_data.html) | Daily metadata/version/DOI/category/abstract/license; full text only if permitted | Research discovery and source revision | META; CC0 metadata does not relicense full text |
| 36 OpenAlex | [OpenAlex API](https://help.openalex.org/api/) | Works/authors/venues/institutions/topics/citation links/OA locations/update history | Scholarly source discovery | META; OA location is not a full-text license |
| 37 Semantic Scholar | [Academic Graph API](https://api.semanticscholar.org/api-docs/) | Paper/author/citation/reference graph, OA locations and selected metadata | Citation-path discovery | META; limits/terms apply; OA flag does not license text |
| 38 Crossref | [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) | DOI/title/authors/venue/dates/references/license deposits/post-publication updates | Canonical literature metadata and refresh | META; abstracts may be copyrighted |
| 39 ACM + IEEE publishers | [ACM Digital Library policy](https://libraries.acm.org/digital-library/platform-and-features) · [IEEE Xplore](https://ieeexplore.ieee.org/) | DOI/version/item rights, abstracts and full text only when item terms authorize extraction | Publisher source resolution and rights decisions | META/LICENSE; no blanket bulk/AI/TDM rights |
| 40 USENIX | [USENIX OSDI proceedings](https://www.usenix.org/conference/osdi24/technical-sessions) | Proceedings metadata/papers/slides, equations/tables/figures and linked artifacts | Systems/serving research | PUBLIC selectively; open access is not public domain |

Separate user/internal inputs are not counted as acquired source families.

| Input lane | What it may contain | Gate and current state |
|---|---|---|
| User-authorized workload/session | `session_id`, `turn_id`, arrival/start/end와 time unit, turn/tool 의존성·대기 시간, model/tokenizer revision, 새 input 길이와 누적 context 길이, output 길이, prefix/KV 정책, 결과·error·retry. 외부에서 관찰 가능한 사건을 보존 | 사용자 제공 시 범위·보존 조건을 정해 연결. 실제 session corpus는 아직 제공·연결된 것으로 확인하지 않음 |
| Internal Confluence | space/page ID, title, page version, body·table·attachment, labels·links, 수정 시각, source span, page/space ACL | 사내 owner가 허용한 space·namespace·자료만 후속 연결. 현재 미연결 |
| Internal HAT/experiment artifacts | workload·architecture·recipe/IR·toolchain revision, fold/unfold/fusion 변경, RP resource timeline 참조, run inputs·outputs, 전체 metric vector·단위, 실패·retry, artifact hash, Insight·반례와 lineage | 실제 실험 후 허용된 artifact를 연결. 대형 trace는 columnar/raw로 저장하고 검색용 요약·지식·원본 참조를 분리 |

A source row is a plan, not a promise that the source was fetched. Every acquired revision needs a hash/locator/access class and refresh/retraction policy. Standards and publishers remain metadata-only until rights authorize full text/AI processing. Do not infer a universal physical limit from a vendor's product claim or a model's simulated output.

## 논리 schema와 공통 metadata

Canonical objects are the versioned records used for decisions. Search indexes and summaries are derived projections and are never the sole authority.

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#ffffff'}}}%%
erDiagram
  DecisionTask {
    string task_id
    string revision
  }
  KnowledgeRequirement {
    string requirement_id
    string satisfaction_state
  }
  CollectionPlan {
    string plan_id
    string rights_state
  }
  SourceRevision {
    string source_id
    string revision_id
    string content_hash
  }
  Claim {
    string claim_id
    string epistemic_state
  }
  EvidenceLink {
    string evidence_id
    string source_span_ref
  }
  HardwareAssetVersion {
    string asset_version_id
    string scope
  }
  DesignPoint {
    string design_point_id
    string snapshot_id
  }
  DecisionTask ||--|{ KnowledgeRequirement : requires
  KnowledgeRequirement ||--o{ CollectionPlan : plans
  CollectionPlan }o--o{ SourceRevision : acquires_or_reuses
  SourceRevision ||--o{ EvidenceLink : cited_by
  Claim ||--o{ EvidenceLink : supported_by
  KnowledgeRequirement }o--o{ Claim : covered_by
  HardwareAssetVersion }o--o{ Claim : scoped_to
  DesignPoint }o--o{ HardwareAssetVersion : assembles
  DesignPoint }o--o{ KnowledgeRequirement : assessed_by
```

ER view에는 8 entity만 표시해 읽기 쉽게 만들었다. Recipe, Experiment, Insight와 기타 record들은 아래 표 및 supporting contracts에 정의돼 있다.

| Object | 핵심 필드 / metadata | 판단에서의 역할 |
|---|---|---|
| DecisionTask | task ID/revision, goal, candidate scope, constraints, requester/namespace, knowledge snapshot, budget/status | 질의를 오래가는 결정/분석 context로 고정 |
| KnowledgeRequirement | task ref, expected claim/path/value, scope/version, unit, source authority/freshness, evidence completeness, blocker, validator, satisfaction predicate/status | 부족·충돌·stale·blocked 상태를 explicit하게 추적 |
| CollectionPlan / AcquisitionAttempt | requirement refs, source family/revision candidates, rights gate, query/parser version, expected evidence, owner/cost/refresh, outcome | 문서 수집·user input·experiment를 같은 gap-resolution flow에 연결 |
| SourceRegistration / SourceRevision / SourceSpan / Artifact | publisher/family, rights, revision/hash, raw artifact, page/section/table/figure/code locator | 원문과 정확한 근거 위치를 고정 |
| ExtractionRun / DocumentElement / Chunk | parser/OCR/model/config version, reading order, table header/footnote, equations/code refs, parent-child IDs | byte source에서 structured candidate를 만든 provenance |
| Claim / EvidenceLink / Conflict | subject/predicate/object, claim kind, applicability, epistemic state, support/refute/qualify, conflicts | claim과 인용 존재를 “실제 지지” 여부와 분리 |
| ConstraintRule / ValidationResult | versioned expression, parameters/unit, applicability, authority, validator version, result/coverage/counterexample | pass/fail/unknown/not_applicable/error를 결정론적으로 반환 |
| HardwareAssetVersion / Port / Assembly / Capability | scope and revision, instances/containment/connection, port compatibility, resources, supported operation | rack/tray/package/SoC/component 조합과 legality 표현 |
| KernelRecipeVersion / CorrectnessAssessment / CostModelVersion | op DAG, dialect/transform/fold-unfold/fusion, target, test scope, calibration domain/uncertainty | recipe 의미와 model coverage를 보존 |
| ModelVersion / WorkloadScenario / DesignPoint | weights/tokenizer/chat-template license, session/timing/KV/SLO, assembly+recipe+serving snapshot | 같은 비교 cohort의 대상 고정 |
| ExperimentProposal / RunManifest / RunEvent / MetricVector | hypothesis/intervention/stop, commits/config/seeds, ordered events/errors/retries, all metrics+units+method+fidelity | 결과와 실패의 재현·비교 |
| EvidenceBundle / ReviewFinding / DecisionRecord | query/snapshot/filters/spans/graph paths/coverage, reviewer/verdict, decision/assumptions/gaps | 감사 가능한 설명과 결과의 연결 |
| InsightVersion / MeleteBridgeRecord | source run/event IDs, scope/applicability, lineage, candidate/reviewed/supported/contested/superseded, external receipt refs | 반복 경험을 다시 찾고 반례로 낮출 수 있게 함 |

모든 object는 id, record type/schema version, namespace/ACL, record revision, content identity, created/recorded time, valid time, provenance와 retention/rights를 갖는다. Relationship에도 type/version, scope, validity, source refs, evaluator/method, ACL이 붙는다. Containment은 DAG; network graph는 cycle을 허용한다. 동일 source 재인용·동일 run 재생·Insight 재전송은 독립 evidence 수를 늘리지 않는다.

## 시나리오 1 — Source 등록·insert

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#f6f8fa'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  T[Task + requirement] --> P[CollectionPlan]
  P --> G[Rights + acquisition]
  G --> S[Immutable SourceRevision]
  S --> X[Parse + source spans]
  X --> C[Claim/Evidence candidates]
  C --> V[Review + validation]
  V --> L[PG transaction + outbox]
  L --> I[Search projections]
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class T,V focal;
  class G,S external;
  class P,X,C,L,I normal;
```

| Write stage | Persisted input/output | Failure/acceptance rule |
|---|---|---|
| Decision intake and decomposition | DecisionTask, KnowledgeRequirement DAG, scopes, policies and budgets | Missing target/source scope is unknown; do not silently assume |
| Coverage probe and collection plan | Current Claim/Evidence coverage, rights-aware CollectionPlan, expected output/cost | Licensed, blocked or stale source becomes an explicit unfulfilled requirement |
| Rights-gated acquisition | Immutable raw artifact and SourceRevision with checksum, license/access class and time | Failed/partial fetch retains its attempt; never replace with the latest revision silently |
| Parse and structure | ExtractionRun, DocumentElement, SourceSpan, table/cell/code/equation links and Chunk version | OCR/table/unit ambiguity remains review_required; unsupported format is not parse success |
| Candidate Claim review | Entity/Claim candidates, applicability, evidence method and exact source span | LLM/AST output remains a candidate until deterministic or human review |
| Validate and publish | Typed rule results, conflict record, reviewer evidence, then canonical PG transaction | Error/unknown/missing coverage remains visible; vector similarity cannot publish facts |
| Project and recover | Transactional outbox to exact/FTS/graph/vector generation with watermark and idempotency key | Failed projection retries without duplicate Claim/Event; ledger remains authoritative |
| Large session/run artifact | Raw or columnar artifact plus typed event/metric summaries linked to raw spans | Do not embed every event by default; artifact/chunk rights and retention remain separate |

## 시나리오 2 — Retrieval

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#f6f8fa'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  Q[Question] --> A[ACL + snapshot gate]
  A --> P[Typed QueryPlan]
  P --> F[Exact lookup + full required-rule coverage]
  P --> H[Lexical + dense + graph retrieval]
  F --> E[EvidenceBundle + coverage]
  H --> E
  E --> V[Validator + scoped review]
  V --> O[Answer, abstain or gap plan]
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class A,V focal;
  class F,H external;
  class Q,P,E,O normal;
```

| Question/read route | Required retrieval and graph path | Decision output / forbidden shortcut |
|---|---|---|
| Exact spec/value/version | ID/revision/field/unit lookup then authoritative SourceSpan | Answer with citation or unknown; no similar-version substitution |
| Asset composition/legality | Full containment/port/capability traversal plus constraint expansion | Full required checks; never vector-only approval |
| Kernel/recipe choice | ISA/dialect/shape/layout exact lookup, code/test spans and scoped runs | Candidate plus correctness/cost/unsupported semantics |
| Multi-hop/system impact | Typed graph paths and evidence retrieval per edge | Explain path; relation presence alone is not causality |
| Metric comparison | Compatible workload/model/quality/timing/system-boundary cohort and all MetricVector fields | Constraint, uncertainty and Pareto relation; no forced single score |
| Past failure/Insight | Run/Event/Insight lineage with applicability and independence filters | Stale/unverified experience remains advisory |
| Open research/no evidence | Broad lexical/dense/graph search and community summary, then source drill-down | Cite alternatives and create CollectionPlan for remaining gap |
| No authorized evidence/provider unavailable | Preserve ACL/coverage error and partial service state | Never relax filters, leak private title/count, or silently drop graph completeness |

Required rule/input completeness is a separate exact path that top-k, rerank and context limits never cut. Top-k limits narrative candidates only. Filter by current ACL, version and scope before retrieval, then recheck before sending evidence to a provider. Missing/conflicting coverage returns the reason and a collection/experiment plan rather than weakened filters.

## 시나리오 3 — 부족한 지식의 추가 수집

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#f6f8fa'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  D[DecisionRecord] --> C[Coverage check]
  C --> R[Open requirement]
  R --> G[Classify gap]
  G --> P[CollectionPlan]
  P --> S[Rights-approved source or experiment]
  S --> E[New evidence]
  E --> V[Re-evaluate requirement]
  V --> N[Satisfy or reopen]
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class R,V focal;
  class S,E external;
  class D,C,G,P,N normal;
```

| Gap type | New work item | Stop rule |
|---|---|---|
| Source missing/stale | discover revision, rights check, acquire exact span | rights or owner access unavailable → blocked |
| Conflicting Claims | find revision, scope difference, authority and counter-evidence | keep both until resolution evidence exists |
| Unmeasured feasibility | ExperimentProposal or authorized instrumented run | no run without approval/budget/stop condition |
| Unsupported model domain | calibration or alternative evidence source | do not extrapolate as a physical guarantee |

## 시나리오 4 — Source 갱신·상충 처리

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#f6f8fa'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  T[Release / errata / retraction] --> S[New SourceRevision]
  S --> X[Re-extract changed spans]
  X --> C[New Claim candidates]
  C --> K[Conflict / supersession]
  K --> R[Affected requirements]
  R --> V[Revalidate linked decisions]
  V --> D[New DecisionRecord revision]
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class S,K focal;
  class T external;
  class X,C,R,V,D normal;
```

| Event | Mutation | Audit invariant |
|---|---|---|
| New version/erratum | add revision and derived spans/claims | old revision/run/decision remains unchanged |
| Claim conflict | create ClaimConflict and mark overlapping scopes | do not overwrite the losing value |
| Retraction/rights change | mark source/claim state and identify downstream users | immediately block affected reads; reopen dependent requirements |
| Revalidation | create a new decision snapshot | preserve which policy/evidence version produced each verdict |

## 시나리오 5 — 실험·실패·Melete 경험 환류

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#f6f8fa'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  P[ExperimentProposal] --> A[Authorized RunManifest]
  A --> E[RunEvent chain]
  E --> M[MetricVector or Failure]
  M --> I[Analysis / Insight candidate]
  I --> L[Lineage + applicability check]
  L --> B[Melete bridge + receipt]
  B --> R[Requirement / next proposal]
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class P,I focal;
  class A,E,M external;
  class L,B,R normal;
```

| Result | Evidence update | Feedback rule |
|---|---|---|
| Success | measured MetricValue plus complete workload/HW/kernel/toolchain snapshot | use only in compatible cohort and its recorded scope |
| Performance regression | preserve full metrics and intervention | do not reduce to single failure label |
| Compile/semantic/runtime failure | preserve classified error, artifact and stage | not a performance result; may form a new KnowledgeRequirement |
| Melete receipt/Insight | link external memory/version to source events | receipt is not truth or independent replication; unsupported Insight stays candidate |

## 시나리오 6 — 권한 철회·삭제

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#f6f8fa'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  R[Rights revoked / delete request] --> D[Fail-closed query deny]
  D --> T[Canonical tombstone]
  T --> I[Invalidate graph/vector/cache]
  I --> A[Artifact retention action]
  A --> M[Melete source restriction]
  M --> E[Completion audit evidence]
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class R,D focal;
  class A,M external;
  class T,I,E normal;
```

| Ordering | Required action | Evidence |
|---|---|---|
| First | authoritative current ACL check fails closed before graph hop/snippet/cache/provider | denied query event without private title/count leakage |
| Then | tombstone canonical record and invalidate all projections/caches | projection watermark and invalidation receipt |
| Retention | delete or preserve only legally allowed hash/minimal metadata | source-class policy and deletion result |
| External memory | propagate source restriction where applicable | Melete reference status; historical access never bypasses current ACL |

## 시나리오 7 — Embedding·index 교체

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#f6f8fa'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  S[Frozen corpus snapshot] --> N[New index generation]
  N --> G[Same golden queries]
  G --> H[Shadow dual-read]
  H --> C[Coverage + quality gate]
  C --> R[Atomic route change]
  R --> B[Retain old space / rollback]
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class S,C focal;
  class H,R external;
  class N,G,B normal;
```

| Migration field | Must be pinned |
|---|---|
| Embedding space | model/provider revision, dimensions, dtype, normalization, metric, preprocessing and query/document formatter |
| Index generation | corpus snapshot, source/ACL filter version, chunk policy, parser version, last applied outbox sequence |
| Promotion | exact qrels and slices, recall/evidence coverage, latency/memory, regression and rollback threshold |
| Invariant | different embedding spaces are never mixed as comparable vectors; old generations remain until approval/retention expiry |

## 시나리오 8 — 실패 재시도·중복 방지·복구

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#f6f8fa'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  W[Persisted write intent] --> F[Worker failure]
  F --> K[Idempotency-key retry]
  K --> O[Outbox reconciliation]
  O --> B[DB + local artifact backup]
  B --> R[Isolated restore]
  R --> H[Hash + closure verification]
  H --> C[Resume or dead-letter]
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class W,H focal;
  class F,B external;
  class K,O,R,C normal;
```

| Failure/recovery point | Record and behavior | Acceptance |
|---|---|---|
| Retry/out-of-order event | stable idempotency key, pending link, retry count and terminal error | no duplicate RunEvent, MetricValue, Claim or external receipt |
| Queue/job restart | persisted job state plus outbox sequence; reprocess only not-yet-applied projection items | canonical and derived sequence reconcile |
| Backup | Supabase database and local artifact bytes tracked as separate backup domains | DB backup does not imply artifact backup |
| Restore | isolated restore then verify root hashes, required refs, schema versions and permissions | resume only after consistency report; otherwise remain degraded/blocked |

## 설계 단계와 준비 상태

D1–D5 are architecture design-detail phases, not implementation phases P1–P5. Every design phase keeps all DSE domains and the requirement→source→schema→write/read→decision→experiment/feedback loop.

| 설계 phase | Full-scope increase | Status |
|---|---|---|
| D1 — 전체 지도 | DSE decision map, source families, dev boundary, object schema, write/read and scenarios | Draft published in this README |
| D2 — 후보 비교 | Source authority/coverage, storage/retrieval/model combinations, rejection and migration conditions | Not complete |
| D3 — 논리 설계 | KnowledgeRequirement/CollectionPlan, entity/relation/version/scope/state metadata, QueryPlan | Not complete |
| D4 — 상세 설계 | Table/index/projection, parser/connectors, budgets, retries, permission and evaluation detail | Not complete |
| D5 — 실행 계획 | Reviewed backlog, owner/input/dependency, safe credential prep, validation and rollback plans | Not complete |

The implementation phase references P0–P5 in [phase-work-packages.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/phase-work-packages.md) are kept separate. No phase treats B300 native readiness as a gate for designing this wider knowledge system.

## 검증 범위와 상세 참고

| Reference | What it contains |
|---|---|
| [2026-10-21-dse-knowledge-architecture.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/superpowers/specs/2026-10-21-dse-knowledge-architecture.md) | Upper architecture and logical object/feedback loop |
| [2026-10-21-knowledge-architecture-plan.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/superpowers/plans/2026-10-21-knowledge-architecture-plan.md) | D1–D5 design plan and inputs |
| [infra-and-credential-requirements.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/infra-and-credential-requirements.md) | Conditional connection/credential and host resource contract; no setup performed |
| [01-source-catalog.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/research/01-source-catalog.md) | Detailed source access, extraction, refresh and quality gates |
| [data-contracts.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/data-contracts.md) | Existing source/claim/asset/experiment record proposals |
| [retrieval-and-decision.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/retrieval-and-decision.md) | Question routing, evidence retrieval, validation boundaries |
| [recommendation-and-selection.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/recommendation-and-selection.md) | Candidate comparisons; scores are priors, not benchmarks |
| [deployment-profiles.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/deployment-profiles.md) | Safe profile and environment boundaries |
| [integration-state-map.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/integration-state-map.md) | Detailed HAT/Melete/native-result interpretation only |

**Not yet done:** no raw standards or internal corpus imported; no Supabase project queried; no AWS used; no GPU acquired; no API key requested/issued; no service, adapter, model inference, index migration or experiment runtime executed. README diagrams are Mermaid for GitHub rendering. Colors use the supplied github-primer-light profile: paper #f6f8fa, ink #1f2328, muted #59636e, accent #0969da, border #d1d9e0. GitHub controls final font/layout; no SVG export or pixel-level typography proof is claimed.

## Diagram 스타일 프로필

GitHub의 [awesome-design-systems](https://github.com/alexpate/awesome-design-systems)와 [Colorful](https://github.com/Siddharth11/Colorful)로 후보를 탐색하고 원본 palette를 확인해, host의 `~/.diagram-design/profiles/`에 아래 6종과 기본 복구 프로필을 저장했다. 이번 README는 `github-primer-light`를 선택한다. 색상은 diagram용 semantic role과 대비에 맞게 조정했으며 원본 사이트의 폰트·pixel layout을 복제했다고 주장하지 않는다.

| 프로필 | 권장 용도 | 원본 palette |
|---|---|---|
| github-primer-light | README, API 및 architecture 문서 | [GitHub Primer Light](https://github.com/primer/primitives/blob/66e78d332cc536e471bcaeb3f8ad08dc16cfbb8a/src/tokens/base/color/light/light.json5) |
| carbon-enterprise | 기업 시스템, infra 및 운영 구조 | [Carbon Enterprise](https://github.com/carbon-design-system/carbon/blob/c3d6496efd2f3092ef4bdc8753c8211b61e5eb26/packages/colors/tokens/colors.tokens.json) |
| nord-editorial | 연구·기술 문서와 차분한 overview | [Nord Editorial](https://github.com/nordtheme/nord/blob/1cef71605416a222e57225b544540ce0fcec18d4/src/nord.scss) |
| catppuccin-latte | 교육·탐색·부드러운 밝은 문서 | [Catppuccin Latte](https://github.com/catppuccin/palette/blob/07d02aa110ef9eb7e7427afca5c73ba9cf7f8ebd/palette.json) |
| solarized-paper | 인쇄·긴 연구 문서·따뜻한 paper | [Solarized Paper](https://github.com/altercation/solarized/blob/62f656a02f93c5190a8753159e34b385588d5ff3/README.md) |
| dracula-technical | 어두운 기술 자료·terminal 인접 diagram | [Dracula Technical](https://github.com/dracula/dracula-theme/blob/e22ebcc048b8aff586f9bc94db30ff5347070b42/README.md) |

README는 GitHub가 지원하는 Mermaid로 구성한다. Diagram Design의 정보 분할·역할 구분·diagram별 node/edge 한도와 palette를 적용하고, 최종 font·배치는 GitHub renderer에 맡긴다.
