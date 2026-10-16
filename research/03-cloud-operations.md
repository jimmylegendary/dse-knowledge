# DSE 지식·실험 플랫폼: cloud 운영 후보와 구축 순서

기준일: **2026-10-16 KST** · 상태: **설계 조사 전용**. cloud 설정·계정 조회·설치·provisioning은 실행하지 않았다.

## 목적과 결정 경계

[README.md](https://github.com/jimmylegendary/dse-knowledge/blob/main/README.md)와 [CONTEXT.md](https://github.com/jimmylegendary/dse-knowledge/blob/main/CONTEXT.md)를 기준으로 한다. 소스 corpus, cloud 접근권, region, 공급자, monthly budget이 아직 없다. 사내 Confluence RAG의 Supabase·Neo4j 경험은 참고 배경일 뿐, 이 프로젝트에 계정·credential·내부 자료가 제공됐다는 뜻이 아니다. 새 corpus는 수집하지 않는다.

이 문서는 AWS/GCP/Azure native, Supabase+Neo4j Aura 관리형 혼합, portable 관리형/자체 운영 혼합을 비교하지만 vendor·region·monthly cap을 선택하지 않는다. 점수는 요구가 채워질 때 재평가할 상대 우선순위다. component 범주가 다르면 가중점수를 서로 더해 최종 순위를 만들지 않는다.

운영 기본은 canonical source/manifest/trajectory를 내보낼 수 있게 보존하고 managed graph/vector/search는 재생성 가능한 projection으로 취급하는 것이다. Source ACL은 ingestion부터 query까지 적용한다. 근거가 없으면 결과는 unknown이다. 실험 원문·artifact·metric vector·derived claim의 provenance를 연결하되 retrieval score나 insight 추천 점수를 실측 성능·사실 확률로 해석하지 않는다.

## 후보 점수

가중치는 quality 25, fit 20, provenance 20, operability 15, portability 10, economics 10이다. 각 항목은 0–5점이며 가중점수는 Σ(weight × score) / 5, 0–100이다. Quality는 service/security/availability 성숙도, fit은 전체 DSE 흐름, provenance는 version/artifact/audit/export, operability는 day-2 부담, portability는 이동성, economics는 최소·사용량 과금 조건을 뜻한다. Embedding relevance나 HW 성능 benchmark 점수는 포함하지 않는다. 상세 근거·제한·공식 출처는 [03-cloud-operations.json](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/03-cloud-operations.json)에 있다.

| 후보 | 범주 | Q/F/P/O/Port/Econ | 가중점수 |
|---|---|---:|---:|
| aws-native | 통합 stack | 5/5/5/4/2/3 | 87 |
| gcp-native | 통합 stack | 5/5/5/4/2/2 | 85 |
| azure-native | 통합 stack | 5/4/4/4/2/3 | 79 |
| supabase-aura | 관리형 혼합 | 4/4/4/3/4/3 | 75 |
| portable-mix | portable 혼합 | 4/4/5/2/5/4 | 80 |
| aws-neptune | graph | 4/4/5/4/2/2 | 76 |
| gcp-spanner-graph | graph | 5/5/5/4/2/2 | 85 |
| azure-cosmos-gremlin | graph | 4/3/4/4/3/3 | 72 |
| neo4j-aura | graph | 5/4/4/5/3/3 | 84 |
| managed-pgvector | vector/RAG | 4/4/5/4/5/4 | 86 |
| aws-opensearch-serverless | vector/RAG | 4/4/4/4/2/3 | 74 |
| gcp-spanner-vector | vector/RAG | 5/4/5/4/2/2 | 81 |
| azure-ai-search | vector/RAG | 5/4/4/4/2/3 | 79 |
| provider-batch | queue/workflow/compute | 5/5/5/4/2/4 | 89 |
| temporal-kubernetes | queue/workflow/compute | 4/4/5/2/5/4 | 80 |
| embedding-api | embedding 실행 | 4/5/3/5/3/5 | 83 |
| embedding-gpu-batch | embedding 실행 | 4/4/5/2/5/3 | 78 |
| aws-s3 | object store | 5/5/5/5/3/4 | 94 |
| gcp-gcs | object store | 5/5/5/5/3/4 | 94 |
| azure-blob | object store | 5/5/5/5/3/4 | 94 |

Jev 1.13의 제한된 후보 검토는 portable-mix 0.57, AWS native 0.26을 제안했고 confidence는 0.46이었다. 낮은 신뢰도의 advisory로 기록한다. 판단 대상이 가중 component rubric과 다르고 region·residency·budget·운영 책임자가 미정이므로 vendor 선택이나 승인으로 취급하지 않는다.

### 통합 platform 후보

- **AWS native:** S3 raw source/artifact, RDS PostgreSQL+pgvector 또는 OpenSearch vector/hybrid retrieval, Neptune graph, SQS/Step Functions/AWS Batch, CloudTrail/CloudWatch/KMS. IAM, audit, queue, network가 결합되고 S3 gateway endpoint는 추가 endpoint charge 없이 VPC에서 연결된다. Neptune과 OpenSearch는 별도 운영단위다. OpenSearch Serverless 비용은 collection generation과 standby mode에 따라 다르다. Classic redundant 첫 collection/account은 2 OCU, dev-test no-standby는 1 OCU이며, NextGen은 min=0/scale-to-zero를 지원한다. AWS API와 infra schema에 lock-in이 있다.
- **GCP native:** GCS, Cloud SQL/AlloyDB 또는 Spanner Enterprise Graph+Vector, Pub/Sub, Workflows, Cloud Batch, Cloud Audit Logs/KMS. Spanner는 relational+graph+vector 통합 후보지만 Graph와 Vector Search는 Enterprise 이상, Graph는 GoogleSQL dialect이며 PostgreSQL interface가 아니다. 운영 통합성이 강하고 compute/replica edition floor를 확인해야 한다.
- **Azure native:** Blob, Azure Database for PostgreSQL+pgvector, Cosmos DB for Apache Gremlin, Azure AI Search, Service Bus/Azure Batch, Entra ID/Key Vault/Monitor. Private endpoint와 workload identity federation이 있다. Cosmos Gremlin과 Search/PostgreSQL이 분리된다. Gremlin driver 제한을 검증하고 Azure AI Search Serverless Developer preview는 비-SLA라 production 후보에 넣지 않는다.
- **Supabase + Neo4j Aura:** Supabase PostgreSQL/pgvector/RLS를 event/vector store로, Aura를 graph projection으로 쓴다. 관리 단순성과 사용 경험은 장점이다. Supabase Pro는 $25/month, Team은 $599/month이며 SSO/backup 차이가 있다. Aura Professional은 $0.09/GB-hour, 최소 1GB이고 pricing chart상 private endpoint와 fine-grained RBAC/SSO가 없다. VPC 격리는 custom-priced Aura VDC 조건이다. Supabase/Aura region 일치, private path, egress, ACL propagation을 SKU/계약서로 확인하지 않으면 private source에 쓰지 않는다.
- **Portable managed/self-hosted mix:** cloud object store + PostgreSQL/pgvector + Apache AGE graph extension 또는 별도 graph store + Temporal/Kubernetes jobs. Export/schema 이동성은 좋지만 Kubernetes, graph extension, patching, failover, secrets, backup/restore, GPU scheduling을 운영자가 소유한다. Apache AGE repository license는 Apache-2.0, Temporal server license는 MIT로 확인했다. Transitive dependencies, notices, hosted Temporal Cloud contract, Kubernetes distribution/support는 별도 검토한다.

## 운영 목표 구조

### Account, environment, region

실제 provider 선택 뒤 account tree를 native 경계로 번역한다. AWS는 Organizations management account에 workload를 두지 않고 Security/LogArchive, Platform, DSE-NonProd, DSE-Prod OU 아래 dev/stage/prod workload accounts를 분리한다. GCP는 Organization 아래 Platform, NonProd, Prod folders, 별도 audit/log project, environment별 projects를 둔다. Azure는 Entra tenant의 management groups 아래 Platform/Landing Zone/Sandbox를 두고 권한·billing 요구에 맞춰 dev/stage/prod subscriptions를 나눈다. Azure guidance는 environment마다 management group을 만드는 것을 기본 권고하지 않는다.

각 environment는 ingestion→index→cited query→HAT validation/simulation→analysis→next experiment의 전체 flow를 유지한다. Dev는 synthetic/public-approved data와 작은 quota, stage는 sanitized fixture와 release candidate, prod는 승인된 source ACL/retention에 한한다. 환경별 DB와 bucket은 공유하지 않는다.

기본 비교는 단일 primary cloud/region이지만 region은 미정이다. Data residency/사내 정책, HAT의 B300 baseline 실행 경로와 cloud/accelerator zone capacity, managed service availability/edition, quota, backup-region 요구를 확인한 뒤 고른다. HAT simulation이 cloud GPU를 쓴다고 전제하지 않는다. Object store, DB, graph, vector, queue worker, batch job, audit sink를 colocate한다. 다른 provider/API로 나가는 bytes는 cross-provider/region egress, private endpoint, NAT와 제3자 network를 별도 산정한다.

### IAM, secret, network, ACL

- Workforce SSO/MFA를 IAM에 연동하고 평소 역할을 read, deploy, data access, billing으로 분리한다. Persistent admin은 break-glass만 둔다.
- CI는 GitHub Actions OIDC 또는 조직 CI의 workload identity federation으로 짧은 수명 credentials를 받는다. Long-lived cloud keys를 repository secret으로 저장하지 않는다. Trust subject는 repository, branch/tag, protected environment로 제한한다.
- API/DB/encryption key는 secret manager/Key Vault에서 회전한다. Logs, trace, URL, prompt에 secret이나 private corpus를 기록하지 않는다.
- DB/graph/vector public ingress를 닫고 private subnet/service endpoint/PrivateLink/Private Service Connect를 쓴다. Region, cross-account/project, DNS, edition, hourly+GB charge를 SKU별 확인한다. Aura Pro private endpoint 미포함, Aura VDC 조건, Supabase private-network 지원, GCP PSC producer 지원을 문서로 검증하기 전에는 mixed provider 경로를 승인하지 않는다.
- Manifest와 derived chunks/vectors/claims/edges에 tenant/workspace, source owner/ID/version, classification, allowed principal/group, retention, deletion state를 연결한다. ACL을 retrieval 이후가 아니라 vector/graph candidate 생성 전 적용한다. 여러 source가 claim에 연결돼도 unauthorized evidence를 노출하지 않는다. Access deny를 audit하고 HAT/Melete로 넘기는 excerpt/artifact URI에도 같은 ACL을 적용한다.

### Provenance, retention, deletion, export

Source manifest에는 URI/external ID, source version/content digest, owner/license/ACL/retention, fetch time, parser/OCR/normalizer, chunking, embedding model/version/dimension, graph/schema version을 둔다. Trajectory에는 experiment/run/attempt/step/parent ID, design-point ID, HW/ISA/toolchain/compiler/kernel/workload version, seed, validation method/version, artifact/input digest, command, metric vector(unit/aggregation/uncertainty), success/fail/error/retry/cancel reason, analysis/citation, next candidate를 잇는다. Raw bytes는 object URI, append-only event는 hash/reference만 갖는다. 모든 simulation step/실패를 기록하고 hidden chain-of-thought는 저장하지 않는다.

초기는 object versioning + bounded lifecycle로 설계한다. WORM/Object Lock/locked bucket은 보존기간을 줄이거나 지울 수 없게 하므로 legal/contract deletion 검토 전에는 켜지 않는다. 필요하면 raw artifact와 audit manifest를 다른 bucket/key policy로 나누고 PII/credential을 event/hash에 넣지 않는다. 삭제 시 source/version/chunk/graph/vector/cache/local copy/job input-output/index/replay projection을 dependency manifest로 찾아 tombstone/delete한다. Legal hold/WORM으로 삭제가 막히면 사전 표시하고 owner 승인 없이 immutable archival에 넣지 않는다.

Portable export는 JSONL manifest/events/claims/metrics, raw/simulation object, schema/version/ACL mapping, embedding model+dimension, graph node/edge dictionary, retention/deletion ledger로 한다. Hosted search/graph index는 canonical data에서 재생성 가능하게 둔다. Migration/rollback은 새 schema/index를 side-by-side 만들고 citation·ACL·unknown/contradiction 검증 후 alias/read path를 바꾼다. 이전 model/schema/index manifest로 복구하고 experiment writes는 idempotent event ID로 중복 적용을 막는다.

### Jobs, IaC, CI, observability

Parsing/OCR/normalization/embedding/index build/HAT simulation/replay/report는 idempotent job이다. Queue에는 job ID와 source version을, payload에는 URI/hash 참조를 둔다. CPU는 provider Batch/Jobs, 단발 GPU embedding은 AWS Batch/GCP Batch/Azure Batch 또는 portable Kubernetes/Temporal 비교 대상이다. Batch control plane 사용료가 없어도 VM/GPU/disk/object/network/logging 요금은 남는다. Image/toolchain digest를 고정하고 GPU queue에 max concurrency/wall-clock/disk/output quota를 설정한다. Spot/preemptible은 checkpoint/retry 및 중복 방지를 검증한 경우에만 선택한다.

IaC는 CloudFormation/CDK, Terraform provider/Config Connector, Bicep/ARM, OpenTofu/Terraform cross-cloud을 비교한다. 선택 후 encrypted remote state, locking, least-privilege OIDC, version pin, plan artifact, approval, drift detection을 정한다. State에 secret/private data를 저장하지 않는다. Prod apply는 protected environment reviewer 승인 뒤만 허용한다.

Cloud audit는 CloudTrail/CloudWatch, Cloud Audit Logs/Monitoring, Azure Activity/Resource Logs/Monitor를 central security account/project/subscription으로 보낸다. App trace는 OpenTelemetry로 run→step→source→retrieval→citation→HAT result를 trace ID로 연결한다. Retrieval trace에는 query ID, ACL decision, source/version, lexical/vector/graph branch, index/schema version, citation IDs, unknown/contested reason, latency/token/cost를 담는다. Prompt body/private excerpt/hidden reasoning은 기본 기록에서 제외한다. Queue lag, parser/embedding/job error, GPU retry/OOM, missing evidence, ACL deny, delete lag, index freshness, backup age, restore result, per-tag spend를 모니터링한다.

### Backup, restore, RPO/RTO

운영자와 consumer SLA가 미정이므로 아래는 governance 초안의 **UNVERIFIED planning targets**이며 승인된 SLA가 아니다. Dev/stage는 RPO ≤24h, RTO ≤8h; production-candidate는 RPO ≤1h, RTO ≤4h다. 이 조사에서는 restore drill을 실행하지 않았다. Snapshot frequency/retention이 목표를 지원하지 않으면 higher tier/export/checkpoint 비용을 반영하고, 담당 owner가 목표를 승인하기 전에는 보장값으로 사용하지 않는다.

Canonical object와 event ledger의 encrypted secondary-region export를 계획한다. Postgres는 managed PITR/snapshot과 logical export, graph는 supported consistent export, queue는 replayable event IDs, vector/search는 source manifest에서 재생성한다. KMS key recovery와 secondary-region availability를 함께 시험한다. Incident runbook은 region outage, accidental deletion/corruption, credential leak, runaway GPU/egress, source-owner revocation, model/schema/index migration failure를 다룬다. 분기 restore drill에서 object/event/graph/vector/citation+ACL/experiment artifacts를 다른 test account/project로 복구해 RPO/RTO와 hash parity를 기록한다. Data residency와 stale-writer fencing 검증 전 자동 failover는 사용하지 않는다.

### Budgets, quotas, caps

모든 resource에 project/environment/owner/source_class/run_id/schema_version/cost_center/expiry tags를 붙인다. Monthly budget/anomaly alerts는 50/75/90/100%에서 보내되, budget alerts 자체가 사용을 막지 않는 provider가 있으므로 hard cap으로 착각하지 않는다. 승인 monthly ceiling B를 정하면 GPU quota/allowed family, per-run wall-time, concurrency, queue backpressure, lifecycle, API quota, IAM deny/kill switch를 결합한다. 90% alert는 신규 nonessential jobs를 pause하고 예상 100% 초과에는 enqueue를 막는다. Billing disable은 backup/incident 비용에 영향을 줄 수 있어 사전 side-effect 검토가 필요하다. Supabase Pro spend cap은 다른 provider/Aura/API/egress를 포함하는 전체 cap이 아니다.

Monthly dollar cap은 정하지 않았다. 미래의 예시 planning cap은 승인된 값 B/month이며 price estimate나 quote가 아니다. Project owner가 region/SKU/retention/query/job-hour를 채운 뒤 승인한다; company finance policy가 적용되면 해당 budget authority도 확인한다. GPU/API rate limit, regional GPU quota와 capacity를 launch gate로 둔다.

## Cost model: small / medium / large

다음은 invoice 견적이 아니라 계산용 workload envelopes다. Corpus/artifact size, retention, query distribution, graph degree, latency target, replica policy가 미정이라 total monthly invoice는 산출하지 않는다. Generation model/HAT hardware/human operation/tax/support/discount 비용도 제외한다.

### 데이터와 요청 가정

Chunk 512 tokens, overlap 64, float32, dimension 1536은 비교용이다. N_chunks = docs × ceil((tokens_per_doc - overlap)/(chunk_size - overlap)); V_raw_GiB = N_chunks × dimension × 4 / 2^30. Serving bytes = V_raw × pilot-measured index overhead × replica count. Index overhead는 vendor universal constant로 가정하지 않는다.

| Scale | Docs × tokens/doc | Source tokens | Chunks | Raw vectors | Index copies sensitivity | Queries/mo × tokens/query | Monthly content delta |
|---|---:|---:|---:|---:|---:|---:|---:|
| Small | 10k × 4k | 40M | 90k | 0.515 GiB | 1 | 10k × 1k = 10M | 5% = 2M tokens |
| Medium | 100k × 8k | 800M | 1.8M | 10.30 GiB | 2 | 250k × 1k = 250M | 10% = 80M |
| Large | 1M × 12k | 12B | 27M | 154.5 GiB | 3 | 2M × 1k = 2B | 20% = 2.4B |

Index copies 1/2/3은 storage sensitivity 입력일 뿐 provider HA/replica 구성이나 운영 목표가 아니다. 실제 service replica semantics와 minimum floor는 선택 후 다시 산정한다. Initial embedding tokens는 source tokens이고 monthly tokens는 changed-document + query embeddings: 12M/330M/4.4B다. Retry/dual-index/re-embed는 별도 더한다. OpenAI text-embedding-3은 dimensions를 줄일 수 있고 Titan Embeddings V2는 256/512/1024를 지원하지만 quality gate 전 채택하지 않는다.

### Public price anchors (2026-10-16 확인, USD, before tax)

| Component | Published price and boundary |
|---|---|
| GCS Standard, Iowa us-central1 | $0.000027397/GiB-hour ≈ $0.02/GiB-month at 730h; operations/retrieval/replication/egress extra. PAYG, no minimum stated. [Pricing](https://cloud.google.com/storage/pricing) |
| AWS OpenSearch Serverless, us-east-1 example | Current pricing page example is $0.24/OCU-hour and $0.02/GB-month managed storage. The first Classic redundant collection in an account has 2 OCU minimum total (1 indexing including primary+standby, 1 search including replica): $0.48 × 730h = $350.40/month before storage. Classic dev-test without redundant standby uses 1 OCU total: $175.20/month. Subsequent collections may share OCUs when allowed by collection/key topology. NextGen collection groups can configure min=0 and scale to zero after 10 idle minutes, with 10–30s wake latency; collection type, region, capacity sharing, and configured minimum alter actual billing. These are mode-specific examples, not a platform quote. [Pricing](https://aws.amazon.com/opensearch-service/pricing/) · [scale-to-zero](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-scale-to-zero.html) |
| AWS Neptune, us-east-1 example | I/O-Optimized db.r5.large $0.4698/hour = $342.95/730h, plus $0.225/GB-month storage. Standard vs I/O-Optimized changes I/O charges; replica/backup extra. On-demand example. [Pricing](https://aws.amazon.com/neptune/pricing/) |
| Cloud Spanner Enterprise, regional example | Starting Enterprise rate is $0.041 per 100 processing units/hour/replica. A base regional configuration has 3 read-write replicas; at the documented granular 100 PU capacity, arithmetic at the starting rate is $0.041 × (100/100) × 3 × 730h = $89.79/month compute only. This is not a quote: selected region/edition can cost more; storage, backup, Data Boost, network, and workload capacity are additional. Intra-region replication is listed as free; multi-region/inter-region replication has separate pricing. Optional 1/3-year CUD excluded. [Pricing](https://cloud.google.com/spanner) · [replication](https://docs.cloud.google.com/spanner/docs/replication) · [compute capacity](https://docs.cloud.google.com/spanner/docs/compute-capacity) · [editions](https://docs.cloud.google.com/spanner/docs/editions-overview) |
| Supabase | Pro $25/month; 8GB/project and 250GB bandwidth, $10/month compute credit for first Micro. Team starts $599/month; SSO and 14-day backups vs Pro 7 days. Add-ons/overage and Aura excluded. [Pricing](https://supabase.com/pricing) |
| Neo4j AuraDB | Professional $0.09/GB-hour, minimum 1GB = $65.70/730h; Business Critical $0.20/GB-hour, minimum 2GB = $292/730h. Pro excludes private endpoint and fine-grained RBAC/SSO; VDC custom-priced. PAYG/prepaid available; no reservation assumed. [Pricing](https://neo4j.com/pricing/) |
| OpenAI embeddings | Per 1M input tokens: text-embedding-3-small $0.02, large $0.13. Batch API 50% discount and up to 24h; embeddings max 50,000 inputs per batch. No minimum stated; region/residency contract check needed. [Model pricing](https://developers.openai.com/api/docs/models/text-embedding-3-large) · [Batch](https://developers.openai.com/api/docs/guides/batch) |
| Vertex AI Gemini Embedding | Current USD/global pricing table shows $0.00015 per 1,000 count online and $0.00012 per 1,000 count batch. The visible table labels the billing unit only as “count”; do not convert it to tokens without checking the selected model/SKU usage meter. No minimum stated. [Pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing) |
| S3, Azure Blob/AI Search/VM, managed DB, GPUs, private endpoints | Region/SKU/currency/offer-dependent. Exact quote not captured; do not infer one. Capture current [AWS S3 pricing](https://aws.amazon.com/s3/pricing/) and [AWS Price List](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-aws-price-list-bulk-api.html), [Azure Blob pricing](https://azure.microsoft.com/en-us/pricing/details/storage/blobs/), [Azure AI Search tier price details](https://learn.microsoft.com/en-us/azure/search/search-sku-tier), [Azure retail prices API](https://prices.azure.com/api/retail/prices), and the provider compute/GPU calculator after region selection. PAYG modeled; discounts/commitments excluded. |

Future price evidence must save official URL, region/zone, SKU/edition, OS/license, currency, date, on-demand/spot/commitment, taxes, calculator/quote export. USD public price is not a company quote. Azure pricing is offer/region/currency-dependent; GCP/Spanner/AWS examples are sample/starting prices, not guaranteed deployment floors.

### Embedding API vs batch GPU

API-only figures below are calculated from the explicit assumptions, not total platform monthly cost. Initial corpus load is one-time; monthly cost is changed documents plus query embeddings. OpenAI Batch uses the official 50% discount. No generation/reranking or model quality comparison is included. Google’s current public table exposes an input price per 1,000 count but not the unit definition in the visible pricing row, so these token-based envelopes are not converted to a Vertex total.

| Scale | OpenAI small initial sync/batch | OpenAI large initial sync/batch | OpenAI small monthly sync/batch | OpenAI large monthly sync/batch |
|---|---:|---:|---:|---:|
| Small | $0.80 / $0.40 | $5.20 / $2.60 | $0.24 / $0.12 | $1.56 / $0.78 |
| Medium | $16 / $8 | $104 / $52 | $6.60 / $3.30 | $42.90 / $21.45 |
| Large | $240 / $120 | $1,560 / $780 | $88 / $44 | $572 / $286 |

GPU batch equation: C_gpu = GPU_hours × selected-region-SKU rate + CPU/memory/disk + artifact storage + transfer + logs + retries/preemption + operator cost. GPU-hours cannot be inferred without model, GPU, container, throughput, and region; no GPU price/benchmark is invented. API equation: C_api = provider-billed input units × public API price; OpenAI’s cited embedding API meters input tokens, while the current Vertex price row needs unit confirmation before token-envelope conversion. Batch GPU is cheaper only if measured all-in C_gpu < C_api and meets the same privacy, throughput, failure-recovery, and separate relevance gates. Price sources: [AWS EC2 On-Demand](https://aws.amazon.com/ec2/pricing/on-demand/), [GCP GPU pricing](https://cloud.google.com/compute/gpus-pricing), [Azure Linux VM pricing](https://azure.microsoft.com/en-us/pricing/details/virtual-machines/linux/). Region/zone capacity and GPU quotas are unknown.

### Full monthly equation (no total)

~~~text
C_month = object + DB + graph + vector/search + queue/workflow + CPU jobs
        + GPU jobs + embedding API + egress/private network + audit/logs
        + backup/replication + support/license + tax
object = storage GiB-month × regional rate + operations + retrieval + egress
vector = raw vectors × measured index overhead × replicas + serving hours/units
jobs = Σ count × (vCPU-hour + RAM-hour + GPU-hour + disk/network/logs)
embedding = metered input units × API rate
~~~

Run artifacts can dominate vectors. Model retained artifacts as runs/month × artifact GiB/run × retained months × backup copies. Unknowns to measure: original bytes/doc, chars/token, metadata bytes/vector, index overhead, graph degree, retries, queries, GPU-hours, cross-zone/region egress, object ops, retention, replicas. Always-on managed graph/vector endpoints can have a fixed hourly floor even with small corpus.

## Whole-flow setup order (future plan only)

Every stage keeps the same end-to-end slice: source approval→parse/version/provenance→graph/vector/RAG indexing→cited retrieval/unknown handling→DSE proposal→manifest/seed/fidelity-controlled HAT validation and execution→trajectory/metrics/errors/insight→next experiment. Reproducibility must be tested after pinning the input, toolchain, seed, and measurement fidelity; HAT runs are not assumed deterministic. Later phases increase source coverage, scale, and automation. This is not deployment authorization.

| Order/gate | Plan | Verification evidence |
|---|---|---|
| 0. Decision inputs | Project/source owner, ACL/privacy/retention, cloud organization owner if a company account is used, region/data residency, HAT location, monthly B, GPU allowance/quota, RPO/RTO, WORM need, support owner. Apply security/finance/org approval only where company policy or source terms require it. | Owner decision record; source/license register; price export; service/region/quota table. No credential or production corpus required. |
| 1. Foundation (dev only) | Org tree, environment isolation, audit, billing tags, SSO/MFA, OIDC CI, secret/KMS, budget alerts, hard GPU/job quotas, encrypted IaC state. | OIDC short-lived credential; trust denies other branch/env; dev cannot write prod; audit event visible; tag and budget/quota kill-switch dry run. |
| 2. Network/data boundary | Private VPC/VNet, private DB/search endpoint, egress allowlist/DNS, source ACL policies; owner-approved connector only. | No public DB; access allow/deny matrix passes at API/retrieval/graph; endpoint edition, DNS, egress, fees recorded. |
| 3. Canonical stores | Versioned source/artifact object, manifest/event ledger, lifecycle, stage-only DB/graph/vector projections, public/synthetic fixture. Keep immutable lock off pending legal approval. | Source/run ID maps to hash/version; duplicate ingest idempotent; deletion/supersede cascades; portable export restores in clean dev with citations. |
| 4. First full-flow stage | Representative B300 baseline workload: cited retrieval, missing proof=unknown, candidate Design Point, legality validation, HAT run with pinned manifest/seed/fidelity, all steps/errors/retries/hashes, metric vector, insight/evidence distinction, next experiment. | Independent replay attempts and records reproducibility outcome; partial/failing runs visible; changed HW/kernel triggers new timeline; metric units/uncertainty/citations/ACL proven; no claim that B300 or a cloud GPU is faster without calibration. |
| 5. Reliability/cost gate | Queue backpressure, replay, index rebuild, deletion, API/GPU quotas, export/rollback, backup and incident drills. Update envelope from measured invoice/hours. | RPO/RTO drill; hash parity; delete evidence across stores/projections; observed cost against envelope; stop procedure verified. |
| 6. Production approval | For company/internal sources or company cloud accounts, obtain source-owner and security/finance/org approvals where applicable policy requires them. For a personal public-data pilot, no third-party signoff is assumed; the project/account owner still confirms source terms, region, retention/WORM, support edition, budget, RPO/RTO, recovery keys, and retrieval/experiment acceptance before production use. | Applicable policy decision record; data-flow review where required; citation/ACL/evidence gate; restore and spend-cap evidence. No automatic insight promotion. |
| 7. Increase resolution | Add sources, replicas/region redundancy, GPU pools, graph/search coverage, reranker/automation by rerunning full flow. | Provenance and unit-cost delta; price/quota refresh; capacity and rollback drill; no unsupported global optimality or hardware-superiority claim. |

## Official source register

Official source pages checked on 2026-10-16 KST; pricing pages are live and must be reopened at approval. [AWS account isolation](https://docs.aws.amazon.com/wellarchitected/latest/security-pillar/aws-account-management-and-separation.html), [GCP hierarchy](https://docs.cloud.google.com/resource-manager/docs/cloud-platform-resource-hierarchy), [Azure management groups](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ready/landing-zone/design-area/resource-org-management-groups), [GCP Workload Identity Federation](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines), [Azure GitHub OIDC](https://learn.microsoft.com/en-us/azure/azure-functions/functions-how-to-github-actions), [S3 Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html), [GCS Bucket Lock](https://docs.cloud.google.com/storage/docs/bucket-lock), [Azure immutable Blob](https://learn.microsoft.com/en-us/azure/storage/blobs/immutable-storage-overview), [GCP Private Service Connect](https://docs.cloud.google.com/vpc/docs/private-service-connect), [Azure Private Link](https://learn.microsoft.com/en-us/azure/private-link/private-endpoint-overview), [AWS S3 VPC endpoint](https://docs.aws.amazon.com/vpc/latest/privatelink/vpc-endpoints-s3.html), [AWS Batch pricing](https://aws.amazon.com/batch/pricing/), [GCP Batch pricing](https://cloud.google.com/batch/pricing), [Azure Batch cost](https://learn.microsoft.com/en-us/azure/batch/plan-to-manage-costs), [GCP budgets](https://docs.cloud.google.com/billing/docs/how-to/budgets), [Azure cost management](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/overview-cost-management), [Spanner Graph editions](https://docs.cloud.google.com/spanner/docs/graph/overview), [Spanner vector index](https://docs.cloud.google.com/spanner/docs/vector-indexes), [Cosmos Gremlin limits](https://learn.microsoft.com/en-us/azure/cosmos-db/gremlin/faq), [Azure AI Search tier/preview](https://learn.microsoft.com/en-us/azure/search/search-sku-tier), [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security), and [OpenTelemetry](https://opentelemetry.io/docs/).

No cloud account, project/subscription, resource, identity, secret, service, plugin, package, or billing setting was inspected or changed.
