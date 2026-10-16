# DSE KG 저장·검색 후보 조사

조사 기준일: 2026-10-16 KST. 초기 corpus는 없으며 공식 제품/프로젝트 문서로만 후보를 비교했다. 범위는 저장소와 검색 계층이며, 계정·서비스 생성, 설치, 수집, 성능 실험은 하지 않았다. 대상 요구와 용어는 [README.md](https://github.com/jimmylegendary/dse-knowledge/blob/main/README.md), [CONTEXT.md](https://github.com/jimmylegendary/dse-knowledge/blob/main/CONTEXT.md)를 따른다.

## 권고

정본은 출처 원문과 실험 산출물을 버전이 있는 object storage에 두고, 구조화 claim·HW 제약·실험 지표는 관계형 SQL에 정규화한다. Graph, vector, lexical index, community summary는 다시 만들 수 있는 파생 인덱스로 취급하고 정본 ID와 version을 보존한다. 초기 설계에 그래프 DB를 지식 도메인마다 하나씩 두지 않는다.

세 가지 조합을 비교 대상으로 남긴다.

1. **Relational-first cloud 기준선:** versioned object storage + 관리형 PostgreSQL/pgvector. PostgreSQL에 Claim/Evidence ledger, source registry, authoritative ACL, exact metric query, GIN full-text와 vector retrieval을 둔다. HW hierarchy는 node/edge 테이블과 recursive query로 모델링한다. 멀티홉 검증에 부족할 때만 graph DB를 추가한다. Supabase는 RLS/Auth와 운영 편의가 이득일 때 PostgreSQL의 관리형 선택지다.
2. **Managed property graph 탐색:** object storage + PostgreSQL의 Claim/Evidence/ACL/metric SoR + Neo4j Aura의 재생성 가능한 graph projection. Neo4j에서 evidence ID와 후보 path를 검색하고, 원문/권한은 PostgreSQL authority에서 재검사한다. 별도 vector DB나 OpenSearch는 평가상 필요성이 입증되기 전까지 넣지 않는다. Hybrid 후보 순위 결합은 application의 RRF로 통일한다.
3. **제약 우선 RDF:** object storage + PostgreSQL Claim/Evidence/ACL/metric SoR + Stardog Cloud의 재생성 가능한 RDF/SPARQL/SHACL projection. OWL/rule reasoning 또는 관계의 명시적 제약이 핵심이면 적합하다. Dense retrieval이 실제 query set에서 필요할 때 Qdrant를 파생 인덱스로 붙인다. AWS 고정 시 Neptune Database, 이식 가능한 자체 운영이 우선이면 Apache Jena Fuseki/TDB2를 평가 대안으로 둔다.

사내 Confluence에서 Supabase와 Neo4j를 사용한 경험은 초기 학습 부담을 낮출 수 있지만, 해당 계정·자료·권한을 이 프로젝트에서 쓸 수 있다고 가정하지 않는다.

**주 선택 기준:** all-HW hierarchy의 legality가 초기 gate라면 3번을 우선 설계한다. LLM이 만든 추출 결과만으로 합법성을 정하지 않고, SHACL 또는 결정론적 validator와 HAT 검사로 판정한다. 먼저 1번을 전체 흐름 기준선으로 세우면 2번·3번의 그래프 이득도 같은 query set으로 비교할 수 있다.

## 후보와 점수

점수는 0–5 정수의 **전문가 사전평가**이며, 실측 성능·사실의 확률·가격 견적이 아니다. 총점은 Σ(가중치 × 점수)/5, 100점 만점이다. 품질 25, 요구 적합도 20, provenance 20, 운영성 15, 이식성 10, 경제성 10. 예산·region·workload 규모·CPU/GPU 처리량이 미정이므로 검증되지 않은 총소유비용은 중립 3점으로 둔다. 오픈소스/무 API 과금만으로 경제성을 4–5점으로 올리지 않는다. JSON의 confidence도 candidate 역할과 근거 요약에 대한 작업자 confidence일 뿐, 정답 확률이 아니다. 순위는 아래의 같은 역할 안에서만 읽는다. 서로 다른 역할의 점수끼리 비교하지 않는다.

| 역할 범주 | 후보 | 점수 벡터: 품질/적합/provenance/운영/이식/경제 | 가중 총점 | 근거와 한계 |
|---|---|---:|---:|---|
| 관계형+vector | PostgreSQL + pgvector | 4/4/5/3/5/3 | 81 | 관계형 exact query, GIN lexical, vector 한곳에 둔다. HNSW/IVFFlat은 근사 검색이고 metadata filter 뒤 결과 수·recall을 실제 데이터로 확인해야 한다. [pgvector](https://github.com/pgvector/pgvector), [PostgreSQL GIN](https://www.postgresql.org/docs/current/gin.html) |
| 관계형+vector | Supabase Postgres + pgvector | 4/4/4/5/3/3 | 79 | 관리형 Postgres, RLS, vector와 FTS/RRF 예제가 있어 cloud 시작이 쉽다. Supabase의 client 경로는 vector 연산에 SQL RPC가 필요하며, 계정·지역·요금·RLS 정책은 별도 확인 대상이다. [Vectors](https://supabase.com/docs/guides/ai/vector-columns), [Hybrid search](https://supabase.com/docs/guides/ai/hybrid-search), [RLS](https://supabase.com/docs/guides/database/postgres/row-level-security) |
| Property graph projection | Neo4j Aura | 4/5/4/4/3/3 | 80 | PostgreSQL Claim/Evidence ledger에서 재생성하는 멀티홉 retrieval projection이다. HW·kernel 관계 traversal과 full-text/vector index가 장점이다. Aura tier와 버전별 search/filter 기능을 고정해야 하며, RDF/SHACL 검증은 별도다. [Search indexes](https://neo4j.com/docs/cypher-manual/current/indexes/search-indexes/) |
| Managed graph DB | Amazon Neptune Database | 4/4/5/3/2/3 | 75 | SPARQL 1.1 RDF와 Gremlin/openCypher property graph를 제공한다. AWS/VPC 운영 결합과 제품별 기능 차이가 있으므로 cloud 결정을 선행하지 않는다. [Neptune overview](https://docs.aws.amazon.com/neptune/), [SPARQL](https://docs.aws.amazon.com/neptune/latest/userguide/access-graph-sparql.html) |
| Graph analytics | Amazon Neptune Analytics | 3/3/4/4/2/2 | 63 | 대규모 메모리 graph 분석과 traversal 내 vector similarity에 맞고, Neptune Database/S3에서 적재할 수 있다. Neptune Database와 별개인 분석 서비스이며 vector index는 graph 생성 시 차원 고정, index 업데이트 비원자성 제약을 확인해야 한다. [Analytics overview](https://docs.aws.amazon.com/neptune-analytics/latest/userguide/what-is-neptune-analytics.html), [Vector index](https://docs.aws.amazon.com/neptune-analytics/latest/userguide/vector-index.html) |
| RDF/SPARQL/SHACL | Stardog Cloud | 5/5/5/4/3/2 | 87 | 관리형 RDF KG, SPARQL 및 OWL/rule reasoning, SHACL 제약을 검토할 수 있어 legality 중심에 맞는다. 관리형 제공·라이선스·region·정확한 SHACL/RDF feature matrix는 견적 및 계약 전에 확인한다. [Stardog Cloud](https://docs.stardog.com/stardog-cloud/), [Query](https://docs.stardog.com/query-stardog/), [Reasoning](https://docs.stardog.com/inference-engine/index), [Data quality](https://docs.stardog.com/data-quality-constraints) |
| RDF/SPARQL/SHACL | Apache Jena Fuseki + TDB2 | 4/5/4/2/5/3 | 78 | 오픈 RDF stack으로 SPARQL 서버, persistent triple store, SHACL processor가 있다. 직접 배포·백업·HA·보안 운영을 맡아야 한다. [Jena overview](https://jena.apache.org/documentation/), [Jena SHACL](https://jena.apache.org/documentation/shacl/index.html) |
| Vector search | Qdrant | 4/4/4/4/5/3 | 80 | dense/sparse/hybrid 및 multi-stage rerank, tenant payload filter와 tiered tenancy가 풍부하다. 기본 역할은 vector retrieval이므로 ontology/graph legality와 강한 lexical query는 별도 층에 둔다. [Hybrid queries](https://qdrant.tech/documentation/search/hybrid-queries/), [Multitenancy](https://qdrant.tech/documentation/tutorials/multiple-partitions/) |
| Vector search | Weaviate | 4/4/3/4/4/3 | 74 | BM25F와 vector hybrid, fusion weight와 boost를 조정한다. graph-shaped claims의 제약 검증 SoR로 간주하지 않고, cloud/self-managed 및 release별 동작을 고정한다. [Hybrid search](https://docs.weaviate.io/weaviate/search/hybrid) |
| Vector search | Milvus | 4/4/3/2/4/3 | 68 | dense+sparse 검색, ranker와 pre/iterative metadata filter를 지원한다. 복잡한 filter가 latency를 늘릴 수 있고, 운영·consistency·배포형태를 실측해야 한다. [Hybrid search](https://milvus.io/docs/milvus_hybrid_search_retriever.md), [Filtered search](https://milvus.io/docs/filtered-search.md) |
| Vector search | Pinecone | 4/3/3/5/2/2 | 67 | 완전 관리형이며 namespace와 metadata filtering, sparse+dense 검색을 제공한다. managed convenience는 높지만 vendor/region 결합과 가격은 현재 미정 조건에서 가장 큰 검증 항목이다. [Search overview](https://www.pinecone.io/learn/search-with-pinecone/), [Metadata filters](https://docs.pinecone.io/guides/search/filter-by-metadata) |
| Hybrid search engine | Vespa | 5/5/4/2/4/3 | 81 | BM25와 nearest-neighbor retrieval을 조합하고 phased ranking/reranking을 직접 표현할 수 있어 ranking 실험에 맞는다. schema/rank profile과 distributed 운영 전문성이 요구되어 초기 운영 부담이 높다. [Hybrid search tutorial](https://docs.vespa.ai/en/learn/tutorials/hybrid-search), [Nearest neighbor guide](https://docs.vespa.ai/en/querying/nearest-neighbor-search-guide.html) |
| Hybrid search engine | OpenSearch | 4/4/4/3/5/3 | 77 | keyword+semantic hybrid와 score normalization/RRF를 갖춘 이식성 높은 후보. RRF는 2.19+, hybrid query는 2.11+ 등 버전 gate와 관리형 배포 차이를 고정해야 한다. [Hybrid search](https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/index/), [RRF](https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/rrf/) |
| Hybrid search engine | Elasticsearch / Elastic Cloud | 4/4/4/4/3/2 | 74 | BM25와 dense/vector search를 한 요청에서 결합하고 RRF를 권장한다. serverless/stack/managed tier별 모델·기능·가격을 구분하고 확인해야 한다. [Hybrid search](https://www.elastic.co/docs/solutions/search/hybrid-search), [RRF](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion) |
| Evidence lake | Versioned object storage + Parquet/Iceberg | 4/5/5/3/5/3 | 85 | raw source, HAT trace, experiment artifacts의 canonical evidence에 적합하다. S3 Versioning/Object Lock은 AWS 기능 예시이며, Iceberg snapshot/time travel retention과 object version 보존 비용을 별도로 설계한다. 자체 검색 계층은 아니다. [S3 Versioning](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html), [S3 Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html), [Iceberg snapshots](https://iceberg.apache.org/docs/latest/branching/) |
| Columnar metrics | ClickHouse | 4/4/4/4/4/3 | 78 | 높은 카디널리티 run/event 지표의 SQL 집계 후보이며 S3 Iceberg 데이터를 직접 질의할 수 있다. graph traversal과 claim provenance를 대신하지 않고, object lake와 중복 저장하지 않도록 cache/serving layer인지 정한다. [Iceberg on S3 guide](https://clickhouse.com/docs/use-cases/data-lake/getting-started) |
| Corpus-wide indexing | Microsoft GraphRAG | 4/4/3/3/4/2 | 69 | entity/relationship extraction과 community report를 만들고 global/local/DRIFT/basic retrieval을 제공한다. 전체 corpus 요약 질문에 강점이 있지만, index 생성과 global map-reduce는 자원 소모가 커 raw evidence/exact metric SoR가 될 수 없다. [Indexing overview](https://microsoft.github.io/graphrag/index/overview/), [Global Search](https://microsoft.github.io/graphrag/query/global_search/), [Query modes](https://microsoft.github.io/graphrag/query/overview/) |
| Dynamic graph RAG | LightRAG | 4/4/3/3/4/3 | 71 | graph/vector 이중 retrieval, incremental update와 selective deletion을 표방하고 여러 storage backend를 연결한다. 공식 README는 기본 로컬 persistence를 작은 평가용으로 제한하고 production backend 선택을 요구한다. graph/vector multi-write drift와 embedding 변경 후 재구축을 평가한다. [Project README](https://github.com/HKUDS/LightRAG), [Vector rebuild contract](https://github.com/HKUDS/LightRAG/blob/main/lightrag/tools/README_REBUILD_VDB.md) |

Jev general advisory의 반환 모델은 typesafe/jev-1.13-20260917이었다. 이 1회성 후보 선택의 출력 요약은 relational PostgreSQL 0.97/confidence 0.94, property graph Neo4j Aura 0.82/0.73, RDF Stardog Cloud 0.91/0.82, vector Qdrant 0.92/0.89, hybrid Vespa 0.84/0.76, corpus-wide GraphRAG Microsoft GraphRAG 0.75/0.62였다. 각 쌍은 해당 prompt와 후보 집합에 대한 model probability/confidence 출력이며 보정된 정답 확률, 품질 benchmark, source 검증 또는 실행 승인으로 해석하지 않는다. 결과는 후보 집합과 질문 형식이 바뀌면 달라질 수 있다. API secrets는 저장하지 않았으며 전체 prompt/response 원문도 보존하지 않아 이 선택은 요약 수준으로만 재현 가능하다. JSON의 candidate 점수는 위에 공개한 가중치로 산정한 전문가 prior다.

## 정본·파생 인덱스 계약

**정본 경계**

- 원문, 논문·문서의 원본 파일, capture/trace, HW twin 원본, 실험 input/output와 로그는 object storage에 content hash, URI, source version, acquired_at, publisher/authority, license, parser version으로 보존한다. 삭제보다 새 버전과 tombstone을 만든다.
- PostgreSQL에는 source registry, stable IDs, authoritative ACL/tenant policy와 단조 증가하는 ACL epoch, Claim/Evidence ledger, typed hardware/kernel constraints, run manifest, metric vector를 둔다. 숫자는 value + unit + aggregation/window + uncertainty + scenario_id + design_point_id + tool/HW/model version으로 저장한다. embedding이나 graph summary에서 숫자를 역산하지 않는다.
- Graph store는 typed node/edge의 파생 탐색 인덱스다. 각 fact edge와 extracted claim은 원본 source span, content hash, parser/extractor/model/prompt version, extraction timestamp, valid time, recorded time를 역참조한다.
- Vector/full-text/community report index는 rebuild 가능한 materialized view다. 모든 row/document에 source ID, source version, model ID, index build version, tenant/ACL scope를 붙인다. 권한·valid-time filter를 retrieval 전 단계에서 강제한다.

**Fail-closed ACL revocation:** PostgreSQL ACL authority가 project/resource의 현재 ACL epoch를 소유한다. 모든 snippet hydration, graph expansion, cache hit, answer-context assembly, outbound reranker 전송 직전에 현재 principal의 permission과 epoch를 다시 확인한다. epoch가 projection/cache epoch와 다르거나 authority를 조회할 수 없으면 결과를 거부하고 갱신한다. Neo4j/vector/search의 ACL 필드는 pre-filter 최적화일 뿐 권한 부여 근거가 아니다. Cache key에는 principal, scope, source/version, ACL epoch를 넣고, 진행 중인 검색도 외부 reranker나 사용자 context로 내보내기 직전에 재검사한다. 권한이 철회된 snippet은 reranker를 포함한 어떤 경로로도 전송하지 않는다.

**추출·truth·수정**

Extraction confidence는 모델이 해당 span을 entity/claim으로 추출한 확신도이며 claim의 진실성 점수가 아니다. authority/reliability, evidence strength, extraction confidence를 서로 다른 필드로 두고, proposed, reviewed, supported, contradicted, superseded, retracted 같은 검토 상태도 분리한다. 같은 claim을 지지·반박하는 evidence를 모두 남기며 최신 문서가 과거 사실을 덮어쓰지 않게 한다.

원문 수정/철회는 새 SourceVersion와 retraction/supersession event를 추가한다. 파생 entity/edge/chunk를 source version 기준으로 stale 표시하고, 비동기 재추출·SHACL/typed validation·vector/FTS 재구축 후 versioned alias를 원자적으로 전환한다. 소스가 여러 개 지지한 사실은 한 source의 철회만으로 지우지 않고 남은 provenance를 재평가한다. 실패 시 이전 index build로 rollback할 수 있어야 한다.

**하드웨어 합법성**

Hardware hierarchy와 kernel/recipe 제약은 closed vocabulary, typed units, cardinality, allowed parent/child, interconnect compatibility, memory capacity/placement constraints, ISA/primitive legality로 분해한다. RDF 선택이면 SHACL shape로 선언하고, property graph/SQL 선택이면 같은 규칙을 결정론적 validator에서 검증한다. 추출/요약 모델은 후보 schema를 제안할 수 있지만 legality 통과를 선언하지 않는다.

## 검색 흐름과 질문 분류

항상 project/tenant/ACL, source version, temporal validity, workload/HW version을 첫 필터로 적용한다. Exact identifier·숫자·허용 가능한 HW 조합은 SQL/SPARQL 또는 정형 query로 가져온다. Lexical BM25와 dense search는 별도 후보 집합을 만들고, RRF로 결합한 후 필요하면 cross-encoder/rank profile rerank를 적용한다. 원 점수는 서로 단위가 다르므로 합산하지 않는다. RRF도 순위 결합일 뿐 진실도 점수가 아니다.

초기 agent-turn 검색 예산은 **2개 retrieval round, graph 최대 2-hop, seed 기준 최대 100개 unique node/edge, 최종 rerank 상위 20 evidence span**으로 제한한다. 검색 증거를 통해 다음 edge가 필요한 경우에만 2-hop을 사용하며, 각 hop은 source를 보존한다. 실제 top-k, fan-out, context token 제한은 평가 셋에서 recall과 agent 비용을 측정해 조정한다. 탐색이 evidence chain을 완성하지 못하거나 source끼리 충돌하고 결정 규칙으로 해소할 수 없으면 근거 부족/충돌을 반환한다.

질문 유형별 path를 분리한다.

- **Exact metric/constraint:** SQL/Parquet query에서 값·단위·집계 창·scenario를 확인하고 graph/SPARQL에서 관계 legality를 확인한다. GraphRAG community summary는 사용하지 않는다.
- **특정 recipe/HW 설명:** BM25+dense retrieval → RRF → 최대 1–2 hop graph expansion → rerank → span citation.
- **요약·주제 경향:** GraphRAG community report 또는 사전 계산 summary로 전역 집계하되, 답의 주장을 원 evidence span에 다시 연결한다. “가장 좋은 HW” 같은 결론은 deterministic metric query와 constraint check 없이는 도출하지 않는다.
- **다음 실험 추천:** 실패·성공 trajectory를 source-backed evidence로 조회하고, 후보·가설을 기록한다. recommendation score와 성능 metric vector를 분리하고, 새 실행에서 관측된 metric만 결과값으로 등록한다.

## 중복 조합과 보류 조건

- Supabase와 별도 PostgreSQL을 같은 source registry/metric SoR로 중복 운영하지 않는다. 한 PostgreSQL authority를 택한다. Neo4j, Qdrant 등 검색 plane은 Claim/Evidence/ACL 정본이 아니며, 정본에서 rebuild 가능한 projection으로 둔다.
- Neo4j, Neptune Database, Stardog/Jena 중 graph projection/SHACL store는 한 개만 평가한다. PostgreSQL Claim/Evidence ledger가 정본이며, projection 간 sync를 위해 graph DB 두 개를 나란히 두지 않는다. Neptune Analytics는 선택 시에도 Neptune Database의 분석 companion으로만 검토하고 primary graph projection으로 세지 않는다.
- Qdrant/Weaviate/Milvus/Pinecone 중 vector service는 한 개만 평가한다. Pinecone의 namespace는 ACL 자체가 아니므로 모든 요청에 tenant/ACL 필터를 검증한다.
- OpenSearch+Elasticsearch는 lexical/vector serving plane을 이중 운영하는 중복 후보다. Vespa는 같은 “더 많은 ranking control” 요구가 생길 때 대체 평가한다.
- GraphRAG와 LightRAG를 동시에 같은 source corpus의 graph/vector index owner로 돌리지 않는다. 먼저 retrieval protocol/eval harness를 만들고, global question 비중이 크면 GraphRAG, 업데이트 빈도와 multi-hop local retrieval 문제가 크면 LightRAG를 별도 비교한다.
- ClickHouse와 Iceberg는 목적을 나눈다. Iceberg는 versioned analytical evidence lake, ClickHouse는 반복 집계의 query-serving plane이다. 똑같은 metric을 둘 다 정본으로 쓰지 않는다.

## 평가 계획과 전환 신호

각 phase는 source 획득 → 원문/버전·ACL 등록 → parsing과 claim/evidence 추출 → typed graph/제약 검증 및 lexical+dense 파생 인덱스 → agent retrieval/판단 → HAT experiment → metric/실패·성공 trajectory 환류까지 같은 전체 경로를 유지한다. 다음 phase는 corpus coverage, schema/detail 해상도, 실험 fidelity와 자동화 수준을 높인다. DB나 RAG만 떼어 실험하고 나중에 HAT와 연결하는 단계는 두지 않는다.

Corpus를 받은 후 먼저 작은 held-out question set을 만든다: exact ID/metric/unit, 시간 버전 간 비교, 허용/불허 HW 조합, source가 다른 상충 claim, 2-hop recipe→kernel→ISA 관계, broad theme, source retraction 후 stale index, tenant/ACL 격리. 정답에는 supporting span과 제약 판정 결과를 기록한다.

후보 비교 지표는 recall@k/nDCG@k, exact numeric/unit accuracy, source-span coverage, relation-path precision, abstention precision/recall, conflict handling, retraction freshness lag, p50/p95 latency, ingest/rebuild 비용 및 비용당 query를 함께 보존한다. ACL revoke 후 stale cache/index 거부와 in-flight/outbound reranker 차단을 별도의 zero-tolerance gate로 둔다. ACL leakage는 품질 평균으로 상쇄하지 않는다. 같은 source snapshot, embedding version, query set, concurrency 및 cloud region을 핀한다. 단일 점수로 TTFT·TPOT·throughput·전력 등 HAT Metric Vector를 합치지 않는다.

전환은 도구 유행이 아니라 실패 유형으로 결정한다. recursive relational graph query가 2-hop path 품질/유지보수에서 부족하면 property graph 후보를 시험한다. HW legality를 데이터 스키마와 함께 검증해야 하면 RDF/SHACL 후보를 시험한다. PostgreSQL filtered ANN이 held-out recall 또는 p95를 못 맞추면 vector 서비스 후보를 같은 filter/tail 조건으로 시험한다. lexical analyzer·ranking 단계가 부족하면 OpenSearch/Elastic/Vespa를 추가 비교한다. 대량 metrics의 반복 aggregate가 일반 DB에 과하면 ClickHouse를 serving layer로 시험한다. 전환 전후 모두 동일 full-flow bakeoff를 통과해야 한다.

## 제품·출처 경계

모든 문서는 공식 product/project 문서 또는 공식 repository를 우선 확인했다. 확인 날짜는 2026-10-16 KST이며 rolling latest/current 페이지와 클라우드 edition 기능은 바뀔 수 있다. 인용한 제품 간 가격·region·SLA를 비교하거나 실사용 성능 benchmark를 수행하지 않았다. Neo4j Search/Cypher, OpenSearch RRF, Stardog/Jena SHACL profile 등은 release/edition별 차이를 포함하므로 shortlist 후 정확한 managed tier와 version을 다시 고정해야 한다. AWS S3/Neptune, Supabase, Neo4j Aura, Stardog Cloud는 계정·승인·배포가 준비된 것으로 간주하지 않았다.

이 점수표의 목표는 다음 실험 후보를 줄이는 것이다. 비용 승인·도입 결정이 아니며, 모든 구성요소를 동시에 도입하라는 뜻도 아니다.
