# 추천 점수 전체표

기준: 2026-10-17 P0 보완. 기술·구성·알고리즘 후보 73개와 source family 40개의 prior 점수다. 실제 DSE 성능 또는 최종 배포 선택이 아니다.

연구 JSON schema_version=1.0.0이며 evidence_stage와 nullable assessment_confidence를 분리했다. prior_review_unlocated는 원문 locator를 보존하지 않았던 기존 평가다. 이를 verified_primary evidence처럼 사용하지 않는다. 숫자 confidence는 보정된 확률이 아니고 점수 계산에 사용하지 않는다.

Q/F/P/O/T/E = quality/fit/provenance/operability/portability/economics, 가중치25/20/20/15/10/10, total=Σ(weight×raw/5). Quality 한 단계 차이가 총5점이다. 1–2점 차이는 우월성 증거가 아니며 같은 역할의 5점 이내 후보를 함께 검증한다.

P1 graph 선택은 PG typed graph baseline과 Neo4j challenger 비교를 정한 [0001-graph-backend-selection.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/adr/0001-graph-backend-selection.md)를 따른다. Source priority P0/P1/P2는 수집 우선순위 tier이며 구현 phase와 다르다.

## 기술·알고리즘 후보

### 02-storage-retrieval / columnar_metrics

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 02:clickhouse · ClickHouse | 4/4/4/4/4/3 | 78 | prior_review_unlocated |

### 02-storage-retrieval / corpus_wide_graph_indexing

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 02:microsoft_graphrag · Microsoft GraphRAG | 4/4/3/3/4/2 | 69 | prior_review_unlocated |

### 02-storage-retrieval / dynamic_graph_rag

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 02:lightrag · LightRAG | 4/4/3/3/4/3 | 71 | prior_review_unlocated |

### 02-storage-retrieval / evidence_lake

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 02:object_iceberg · Versioned object storage + Parquet/Iceberg | 4/5/5/3/5/3 | 85 | prior_review_unlocated |

### 02-storage-retrieval / graph_analytics

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 02:neptune_analytics · Amazon Neptune Analytics | 3/3/4/4/2/2 | 63 | prior_review_unlocated |

### 02-storage-retrieval / hybrid_search_engine

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 02:vespa · Vespa | 5/5/4/2/4/3 | 81 | prior_review_unlocated |
| 2 | 02:opensearch · OpenSearch | 4/4/4/3/5/3 | 77 | prior_review_unlocated |
| 3 | 02:elasticsearch · Elasticsearch / Elastic Cloud | 4/4/4/4/3/2 | 74 | prior_review_unlocated |

### 02-storage-retrieval / property_graph

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 02:neo4j_aura · Neo4j Aura | 4/5/4/4/3/3 | 80 | prior_review_unlocated |
| 2 | 02:neptune_database · Amazon Neptune Database | 4/4/5/3/2/3 | 75 | prior_review_unlocated |

### 02-storage-retrieval / rdf_store

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 02:stardog_cloud · Stardog Cloud | 5/5/5/4/3/2 | 87 | prior_review_unlocated |
| 2 | 02:apache_jena · Apache Jena Fuseki + TDB2 | 4/5/4/2/5/3 | 78 | prior_review_unlocated |

### 02-storage-retrieval / relational_vector

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 02:postgres_pgvector · PostgreSQL + pgvector | 4/4/5/3/5/3 | 81 | prior_review_unlocated |
| 2 | 02:supabase_pgvector · Supabase Postgres + pgvector | 4/4/4/5/3/3 | 79 | prior_review_unlocated |

### 02-storage-retrieval / vector_search

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 02:qdrant · Qdrant | 4/4/4/4/5/3 | 80 | prior_review_unlocated |
| 2 | 02:weaviate · Weaviate | 4/4/3/4/4/3 | 74 | prior_review_unlocated |
| 3 | 02:milvus · Milvus | 4/4/3/2/4/3 | 68 | prior_review_unlocated |
| 4 | 02:pinecone · Pinecone | 4/3/3/5/2/2 | 67 | prior_review_unlocated |

### 03-cloud-operations / embedding-execution

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 03:embedding-api · Hosted embedding API, online or batch | 4/5/3/5/3/5 | 83 | E1 |
| 2 | 03:embedding-gpu-batch · Ephemeral batch GPU workers | 4/4/5/2/5/3 | 78 | prior_review_unlocated |

### 03-cloud-operations / graph-store

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 03:gcp-spanner-graph · Cloud Spanner Graph | 5/5/5/4/2/2 | 85 | prior_review_unlocated |
| 2 | 03:neo4j-aura · Neo4j AuraDB | 5/4/4/5/3/3 | 84 | prior_review_unlocated |
| 3 | 03:aws-neptune · Amazon Neptune | 4/4/5/4/2/2 | 76 | prior_review_unlocated |
| 4 | 03:azure-cosmos-gremlin · Azure Cosmos DB for Apache Gremlin | 4/3/4/4/3/3 | 72 | prior_review_unlocated |

### 03-cloud-operations / integrated-cloud-stack

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 03:aws-native · AWS native | 5/5/5/4/2/3 | 87 | prior_review_unlocated |
| 2 | 03:gcp-native · Google Cloud native | 5/5/5/4/2/2 | 85 | prior_review_unlocated |
| 3 | 03:azure-native · Microsoft Azure native | 5/4/4/4/2/3 | 79 | prior_review_unlocated |

### 03-cloud-operations / managed-multi-provider-stack

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 03:supabase-aura · Supabase PostgreSQL/pgvector + Neo4j AuraDB | 4/4/4/3/4/3 | 75 | prior_review_unlocated |

### 03-cloud-operations / object-store

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 03:aws-s3 · Amazon S3 | 5/5/5/5/3/4 | 94 | prior_review_unlocated |
| 2 | 03:azure-blob · Azure Blob Storage | 5/5/5/5/3/4 | 94 | prior_review_unlocated |
| 3 | 03:gcp-gcs · Google Cloud Storage | 5/5/5/5/3/4 | 94 | prior_review_unlocated |

### 03-cloud-operations / portable-managed-self-hosted-stack

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 03:portable-mix · Portable object + PostgreSQL/pgvector + Apache AGE + Temporal/Kubernetes | 4/4/5/2/5/4 | 80 | prior_review_unlocated |

### 03-cloud-operations / queue-workflow-compute

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 03:provider-batch · Provider-managed queue + workflow + Batch jobs | 5/5/5/4/2/4 | 89 | prior_review_unlocated |
| 2 | 03:temporal-kubernetes · Temporal + Kubernetes jobs | 4/4/5/2/5/4 | 80 | prior_review_unlocated |

### 03-cloud-operations / vector-rag-store

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 03:managed-pgvector · Managed PostgreSQL + pgvector | 4/4/5/4/5/4 | 86 | prior_review_unlocated |
| 2 | 03:gcp-spanner-vector · Spanner Vector Search | 5/4/5/4/2/2 | 81 | prior_review_unlocated |
| 3 | 03:azure-ai-search · Azure AI Search | 5/4/4/4/2/3 | 79 | prior_review_unlocated |
| 4 | 03:aws-opensearch-serverless · Amazon OpenSearch Serverless | 4/4/4/4/2/3 | 74 | prior_review_unlocated |

### 04-models-ingestion-evaluation / deterministic_extraction

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 04:tree_sitter_rules · Native parsers + Tree-sitter/AST + unit/schema rules | 5/5/5/4/5/3 | 93 | prior_review_unlocated |

### 04-models-ingestion-evaluation / embedding

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 04:bge_m3 · BAAI/bge-m3 | 4/5/5/3/5/3 | 85 | prior_review_unlocated |
| 2 | 04:qwen3_embedding_4b · Qwen/Qwen3-Embedding-4B | 5/5/4/2/5/3 | 83 | prior_review_unlocated |
| 3 | 04:cohere_embed_v5_pro · Cohere embed-v5.0-pro | 5/5/3/4/3/3 | 81 | E1 |
| 4 | 04:qwen3_embedding_06b · Qwen/Qwen3-Embedding-0.6B | 4/5/4/3/5/3 | 81 | prior_review_unlocated |
| 5 | 04:voyage_4_large · voyage-4-large | 5/4/3/5/3/3 | 80 | E1 |
| 6 | 04:multilingual_e5_large_instruct · intfloat/multilingual-e5-large-instruct | 3/4/5/4/5/3 | 79 | prior_review_unlocated |
| 7 | 04:qwen3_embedding_8b · Qwen/Qwen3-Embedding-8B | 5/4/4/1/5/3 | 76 | E1 |
| 8 | 04:openai_text_embedding_3_large · OpenAI text-embedding-3-large | 4/4/3/5/3/3 | 75 | prior_review_unlocated |
| 9 | 04:gemini_embedding_2 · Google Gemini Embedding 2 | 4/4/3/4/3/4 | 74 | prior_review_unlocated |
| 10 | 04:openai_text_embedding_3_small · OpenAI text-embedding-3-small | 3/4/3/5/3/5 | 74 | prior_review_unlocated |
| 11 | 04:jina_v5_small_retrieval · jina-embeddings-v5-text-small-retrieval | 4/4/2/3/2/3 | 63 | prior_review_unlocated |

### 04-models-ingestion-evaluation / parsing

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 04:docling · Docling + Docling Models | 4/5/4/4/5/3 | 84 | prior_review_unlocated |
| 2 | 04:mathpix_ocr_api · Mathpix OCR API | 5/4/4/4/2/3 | 79 | prior_review_unlocated |
| 3 | 04:paddleocr_pp_structure_v3 · PaddleOCR PP-StructureV3 | 4/4/4/3/4/3 | 75 | prior_review_unlocated |
| 4 | 04:grobid · GROBID | 2/4/5/4/5/3 | 74 | prior_review_unlocated |
| 5 | 04:azure_document_intelligence_layout · Azure Document Intelligence prebuilt-layout | 3/4/4/4/3/3 | 71 | prior_review_unlocated |
| 6 | 04:google_document_ai_layout · Google Document AI Layout Parser | 3/4/4/4/3/3 | 71 | prior_review_unlocated |
| 7 | 04:mineru · MinerU 4.0 | 4/4/3/3/4/3 | 71 | prior_review_unlocated |
| 8 | 04:aws_textract_analyze_document · Amazon Textract AnalyzeDocument | 3/3/4/4/3/3 | 67 | prior_review_unlocated |
| 9 | 04:marker · Marker / Surya | 4/4/2/3/3/3 | 65 | prior_review_unlocated |

### 04-models-ingestion-evaluation / reranker

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 04:bge_reranker_v2_m3 · BAAI/bge-reranker-v2-m3 | 4/5/5/4/5/3 | 88 | prior_review_unlocated |
| 2 | 04:qwen3_reranker_06b · Qwen/Qwen3-Reranker-0.6B | 4/4/5/3/5/3 | 81 | prior_review_unlocated |
| 3 | 04:cohere_rerank_v4_pro · Cohere rerank-v4.0-pro | 5/4/3/4/3/3 | 77 | prior_review_unlocated |
| 4 | 04:cohere_rerank_v4_fast · Cohere rerank-v4.0-fast | 4/4/3/5/3/3 | 75 | prior_review_unlocated |

### 04-models-ingestion-evaluation / retrieval_baseline

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 04:bm25_exact · BM25 + exact identifier/unit/field search | 4/5/5/5/5/3 | 91 | prior_review_unlocated |

### 04-models-ingestion-evaluation / semantic_extraction

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 04:gemini_structured_output · Gemini 3.1 Pro Structured Output | 4/4/3/4/3/3 | 72 | prior_review_unlocated |
| 2 | 04:vllm_local_json_schema · vLLM JSON Schema/XGrammar or Guidance + pinned local model | 3/4/4/2/5/3 | 69 | prior_review_unlocated |
| 3 | 04:openai_gpt6_structured_outputs · OpenAI Structured Outputs + gpt-6-astra | 4/4/3/4/3/1 | 68 | prior_review_unlocated |

### 05-dse-search-candidates / dse_search

| 검토 순서 | 후보 ID · 이름 | Q/F/P/O/T/E | /100 | evidence_stage |
|---:|---|---|---:|---|
| 1 | 05:botorch_mobo · BoTorch multi-objective Bayesian optimization | 4/5/4/3/4/3 | 79 | E1 |
| 2 | 05:optuna_tpe · Optuna conditional TPE | 4/4/4/4/4/3 | 78 | E1 |
| 3 | 05:random_qmc · Seeded random / QMC | 3/3/5/5/5/3 | 78 | E1 |
| 4 | 05:pymoo_nsga · pymoo NSGA-II / NSGA-III | 4/4/4/3/4/3 | 75 | E1 |
| 5 | 05:grid · Finite enumeration / grid | 3/2/5/5/5/3 | 74 | E1 |
| 6 | 05:kg_guided_beam · KG/LLM-guided bounded beam (proposed) | 3/4/3/2/3/3 | 61 | proposal |

## 가중치 민감도

한 차원 ±5 percentage point와 나머지 비례 정규화에서 1위 집합이 변하는 범주다. Raw prior의 타당성이나 도메인 실측을 검증하는 계산이 아니다.

| 역할 | 기본 1위 | 가능한 1위 |
|---|---|---|
| relational_vector | 02:postgres_pgvector | 02:postgres_pgvector,02:supabase_pgvector |
| graph-store | 03:gcp-spanner-graph | 03:gcp-spanner-graph,03:neo4j-aura |
| dse_search | 05:botorch_mobo | 05:botorch_mobo,05:random_qmc |

## Source family 검토 순서

relevance30/authority25/extractability15/rights15/freshness10/diversity5. 전 영역 coverage와 rights gate를 우선하고 source 점수로 권한을 부여하지 않는다.

| 순서 | source ID · 이름 | /100 | evidence_stage | 원출처 |
|---:|---|---:|---|---|
| 1 | 01:benchmark-mlperf · MLCommons MLPerf Inference rules, LoadGen and results | 98 | prior_review_unlocated | [source](https://docs.mlcommons.org/inference/submission/) |
| 2 | 01:trace-otel-genai · OpenTelemetry GenAI/session/agent and hardware conventions | 98 | prior_review_unlocated | [source](https://opentelemetry.io/docs/specs/semconv/gen-ai/) |
| 3 | 01:kernel-triton · Triton language tutorials, API and examples | 97 | prior_review_unlocated | [source](https://triton-lang.org/main/getting-started/tutorials/) |
| 4 | 01:isa-cuda-ptx · CUDA programming and PTX ISA documentation | 96 | prior_review_unlocated | [source](https://docs.nvidia.com/cuda/cuda-programming-guide/) |
| 5 | 01:serving-vllm · vLLM serving, benchmark, scheduler and metric docs | 96 | prior_review_unlocated | [source](https://docs.vllm.ai/en/stable/benchmarking/cli/) |
| 6 | 01:compiler-mlir · MLIR language, dialect, rewrite and pass specifications | 94 | prior_review_unlocated | [source](https://mlir.llvm.org/docs/) |
| 7 | 01:hat-internal · HAT system, hat-schema and HATIR canonical repositories | 94 | prior_review_unlocated | [source](https://github.com/jimmylegendary/hat-system) |
| 8 | 01:hw-nvidia-b300 · NVIDIA B300 / GB300 / DGX B300 primary system documents | 94 | prior_review_unlocated | [source](https://www.nvidia.com/en-us/data-center/gb300-nvl72/) |
| 9 | 01:index-crossref · Crossref DOI metadata/update/deposit REST API | 94 | prior_review_unlocated | [source](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) |
| 10 | 01:kernel-cutlass · NVIDIA CUTLASS/CuTe kernel library and profiler | 94 | prior_review_unlocated | [source](https://github.com/NVIDIA/cutlass) |
| 11 | 01:measure-dcgm · NVIDIA DCGM and DCGM Exporter metrics | 93 | prior_review_unlocated | [source](https://docs.nvidia.com/datacenter/dcgm/latest/reference/dcgm-exporter-metrics.html) |
| 12 | 01:measure-nsight · NVIDIA Nsight Compute profiling guide and metric reference | 93 | prior_review_unlocated | [source](https://docs.nvidia.com/nsight-compute/ProfilingGuide/index.html) |
| 13 | 01:serving-tensorrtllm · NVIDIA TensorRT-LLM serving, benchmark and telemetry docs | 93 | prior_review_unlocated | [source](https://nvidia.github.io/TensorRT-LLM/) |
| 14 | 01:research-arxiv · arXiv metadata/API/OAI and licensed-version preprints | 92 | prior_review_unlocated | [source](https://info.arxiv.org/help/bulk_data.html) |
| 15 | 01:index-openalex · OpenAlex scholarly metadata and citation graph | 89 | prior_review_unlocated | [source](https://help.openalex.org/api/) |
| 16 | 01:dse-ax-botorch · Ax/BoTorch constrained multi-objective optimization | 88 | prior_review_unlocated | [source](https://ax.dev/docs/recipes/multi-objective-optimization/) |
| 17 | 01:experiment-mlflow · MLflow experiment/run/metric/artifact tracking | 88 | prior_review_unlocated | [source](https://www.mlflow.org/docs/latest/tracking/) |
| 18 | 01:publisher-usenix · USENIX proceedings and author-retained research papers | 88 | prior_review_unlocated | [source](https://www.usenix.org/conference/osdi24/technical-sessions) |
| 19 | 01:sim-ramulator · Ramulator 2.1 DRAM/controller simulator | 88 | prior_review_unlocated | [source](https://github.com/CMU-SAFARI/ramulator2) |
| 20 | 01:agent-tau3 · τ³-bench tool-agent-user conversation benchmark | 86 | prior_review_unlocated | [source](https://github.com/sierra-research/tau2-bench) |
| 21 | 01:prov-w3c-provo · W3C PROV-O provenance ontology | 85 | prior_review_unlocated | [source](https://www.w3.org/TR/prov-o/) |
| 22 | 01:sim-sst · Structural Simulation Toolkit and Elements | 84 | prior_review_unlocated | [source](https://sst-simulator.org/sst-docs/docs/guides/start) |
| 23 | 01:std-ocp · OCP Open Rack, OAM/OAI and cooling specifications | 84 | prior_review_unlocated | [source](https://www.opencompute.org/projects/cooling-environments/) |
| 24 | 01:hw-amd-mi350 · AMD MI350/CDNA4 and ROCm technical documentation | 83 | prior_review_unlocated | [source](https://rocm.docs.amd.com/en/develop/reference/gpu-arch/mi350.html) |
| 25 | 01:index-semantic-scholar · Semantic Scholar Academic Graph API | 82 | prior_review_unlocated | [source](https://api.semanticscholar.org/api-docs/) |
| 26 | 01:circuit-openroad-sky130 · OpenROAD RTL-to-GDS flow and SkyWater SKY130 PDK | 81 | prior_review_unlocated | [source](https://openroad-flow-scripts.readthedocs.io/en/latest/) |
| 27 | 01:sim-gem5 · gem5 architecture and memory-system simulator | 80 | prior_review_unlocated | [source](https://www.gem5.org/documentation/) |
| 28 | 01:model-cacti · CACTI cache, memory, 3D and IO model | 79 | prior_review_unlocated | [source](https://github.com/HewlettPackard/cacti) |
| 29 | 01:std-cxl · CXL Consortium specifications, revisions and evaluation terms | 79 | prior_review_unlocated | [source](https://computeexpresslink.org/cxl-specification/) |
| 30 | 01:agent-bfcl · Berkeley Function Calling Leaderboard dataset/evaluator | 78 | E1 | [source](https://github.com/ShishirPatil/gorilla/tree/f7cf7359b7ac615a0b294831c5ba2bc95ee4a000/berkeley-function-call-leaderboard) |
| 31 | 01:model-hf-cards · Hugging Face model cards, dataset cards and Hub revisions | 77 | prior_review_unlocated | [source](https://huggingface.co/docs/hub/model-cards) |
| 32 | 01:std-ieee8023 · IEEE 802.3 Ethernet and PHY standards | 76 | prior_review_unlocated | [source](https://standards.ieee.org/ieee/7003/10422/) |
| 33 | 01:std-ashrae · ASHRAE TC 9.9 data-center thermal guidance | 74 | prior_review_unlocated | [source](https://www.ashrae.org/technical-resources/topics-and-initiatives/ai-data-center/site-planning) |
| 34 | 01:std-ucie · UCIe Consortium die-to-die/package specification family | 74 | prior_review_unlocated | [source](https://www.uciexpress.org/specifications) |
| 35 | 01:agent-agentbench · AgentBench multi-turn environments and evaluation package | 73 | prior_review_unlocated | [source](https://github.com/THUDM/AgentBench) |
| 36 | 01:melete-internal · Melete experience/provenance and conditional-judgment contracts | 73 | prior_review_unlocated | [source](https://github.com/jimmylegendary/melete) |
| 37 | 01:std-jedec · JEDEC HBM/DDR/LPDDR standards registry | 73 | prior_review_unlocated | [source](https://www.jedec.org/) |
| 38 | 01:sim-booksim · BookSim cycle-accurate interconnection network simulator | 72 | prior_review_unlocated | [source](https://github.com/booksim/booksim2) |
| 39 | 01:std-pcisig · PCI-SIG PCIe base/CEM/ECN/compliance specifications | 72 | prior_review_unlocated | [source](https://pcisig.com/specifications) |
| 40 | 01:publisher-acm-ieee · ACM Digital Library and IEEE Xplore article access/rights | 70 | prior_review_unlocated | [source](https://libraries.acm.org/digital-library/platform-and-features) |
