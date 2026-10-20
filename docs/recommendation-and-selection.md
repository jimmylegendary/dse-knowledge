# 추천 조합·검토 순서·선정 계약

2026-10-21 현재 dev 제약은 **기존 Supabase 계정 + Linux host/local artifact**, 모델은 **OpenRouter 또는 Codex의 interface·env 선택**이다. AWS를 사용하지 않고 GPU·Neo4j·remote object storage를 초기 필수 자원으로 요구하지 않는다. 아래 제품·cloud 조합 점수는 과거 연구 prior로 보존하며 현재 배치 선택을 덮어쓰지 않는다. 최신 범위는 [2026-10-21-dse-knowledge-architecture.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/superpowers/specs/2026-10-21-dse-knowledge-architecture.md), 준비 조건은 [infra-and-credential-requirements.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/infra-and-credential-requirements.md)를 따른다.

2026-10-17 보완: **P1의 physical graph backend는 PostgreSQL 관계·recursive 조회를 baseline으로, Neo4j를 동일 질의의 challenger로 평가한다.** Typed graph 의미·provenance는 P1부터 필수다. 아래 조합 점수는 기술 조사 prior이며 Neo4j를 즉시 배포하라는 결정이 아니다. 단일 기준은 [0001-graph-backend-selection.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/adr/0001-graph-backend-selection.md)와 [deployment-profiles.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/deployment-profiles.md)다.

상태: P0 설계 추천. 후보의 실제 DSE 성능과 총비용은 아직 측정하지 않았다. 현재 선택은 **무엇을 먼저 검증할지**이며 cloud 설정이나 production 채택 승인과 다르다.

## 1. 먼저 검증할 조합

**검토 후보 A: managed PostgreSQL 정본 + 필요성이 검증된 graph projection + object/columnar artifacts + 단계적 hybrid retrieval.** 초기 PG typed graph baseline과 별도 Neo4j projection 도입 여부를 구분한다.

| 역할 | 먼저 검토할 구성 | 함께 비교할 대안 | 확정 조건 |
|---|---|---|---|
| Canonical ledger | Supabase managed PostgreSQL | 다른 managed PostgreSQL | ACL·outbox·export·backup·region·가격 profile 확인 |
| Dense index | pgvector | Qdrant | 실제 filtered recall·p95·memory·index rebuild 비교 |
| Lexical/exact | PostgreSQL native FTS + exact fields | 독립 BM25/OpenSearch/Vespa | 식별자·단위·영문/한국어 query recall 부족 시 확장 |
| Typed graph 조회/projection | PG 관계·recursive 조회 baseline | Neo4j Aura challenger, 이후 RDF/기타 대안 | 같은 필수 질의의 의미·권한·snapshot parity 후 latency/TCO gate |
| Raw source·run artifacts | ledger/job cloud와 가까운 object store | S3/GCS/Azure Blob | rights·retention·egress·restore 조건 |
| Metric/timeline 분석 | Parquet + DuckDB 방식의 batch 분석 | ClickHouse, Iceberg catalog | scan latency/concurrency·evolution이 필요할 때 확장 |
| Parsing | Docling + native format parser | GROBID/PaddleOCR/Mathpix 등 | 표·수식·code slice 정확도와 license gate |
| Embedding bake-off | BGE-M3, Qwen3 embedding 계열 | 허용된 hosted API 1종 | DSE gold의 recall/근거 정확도→지연→총비용 순 |
| Reranker bake-off | BGE-reranker-v2-m3 | Qwen3/Cohere 계열 | 정확 인용·숫자·version 판단 개선이 입증될 때 |
| Semantic extraction | source span 필수 structured-output 모델 | 상용 API와 pinned local model | schema validity뿐 아니라 span/수치/조건의 정확도 |
| Job/workflow | 선택 cloud의 queue+Batch/workflow | Temporal + container jobs | retry·cancel·idempotency·cost visibility |
| DSE search | enumeration/random control + conditional sampler | BO/evolution/KG-guided beam | 같은 simulation budget의 frontier/정보 획득 평가 |

PostgreSQL native full-text ranking을 BM25라고 부르지 않는다. BM25는 별도 비교 경로이며 정확 field lookup은 두 방식 모두와 분리한다. pgvector에서 BGE-M3를 사용할 때 초기에는 dense representation만 사용하며 sparse/late interaction은 별도 저장·검색 계약을 측정한 뒤 추가한다.

DuckDB는 분석 실행 방식의 제안이다. 상시 서비스가 필요한 경우의 ClickHouse, 대규모 table lifecycle에 필요한 Iceberg와 역할이 다르다. 여러 저장 기술을 첫 phase에 모두 배포하지 않는다.

## 2. 조합 자체의 잠정 점수

아래는 **작은 실제 전체 loop를 먼저 검증하는 맥락**의 root 평가다. 각 제품의 점수를 평균한 값이 아니다. Quality25/Fit20/Provenance20/Operability15/Portability10/Economics10, 각 0–5로 계산한다.

| 검토 순서 | 조합 | Q/F/P/O/T/E | 추천 점수 /100 | 핵심 이유·탈락 조건 |
|---:|---|---|---:|---|
| 1 | A: managed PG + Neo4j projection | 4/5/5/3/4/3 | 83 | 익숙한 관계·graph 경계를 활용하며 ledger export 유지. region/ACL/edition 조합이 안 맞으면 재선정 |
| 2 | B: 한 cloud의 native managed 구성 | 4/4/5/4/2/3 | 78 | IAM/network/운영 일관성. provider-specific graph·고정비·migration 비용 검토 |
| 3 | C: PG ledger + RDF semantic projection | 4/4/5/3/3/3 | 77 | 규격·ontology·shape 요구가 강할 때 유리. RDF mapping과 운영 역량이 필요 |
| 4 | D: portable self-host 중심 | 4/4/4/2/5/3 | 74 | export/control 강점. 현재 운영 인력이 미정이라 day-2 부담이 큼 |

모든 조합의 economics=3은 실제 TCO를 모르기 때문이다. A가 가장 싸다고 결론 내리지 않는다. B는 2026-10-16 당시 cloud 후보 비교의 조사 기록이다. **현재는 AWS가 선택 불가이고 기존 Supabase + Linux host가 dev 기준**이므로 이 표의 AWS 관련 점수·가격을 현재 선택 순위로 사용하지 않는다. 이 표는 component 문서의 범주별 점수나 cloud 단독 점수와 서로 다른 평가 단위를 가진다.

Jev `typesafe/jev-1.13-20260917`도 A를 첫 pilot 검토 대상으로 제안했다. 반환값은 [decision-advice.json](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/decision-advice.json)에 요청·후보·응답과 함께 보존했다. 응답 확률은 실제 최적일 확률이 아니며, 배포 준비도와 성능 검증을 대체하지 않는다.

## 3. 후보 순서대로 검토하는 실제 방법

1. [scorecards.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/scorecards.md)의 **동일 역할 내** 상위 후보를 순서대로 확인한다.
2. hard gate에 실패한 후보는 다음 후보로 넘어가되 reason과 필요한 조건을 남긴다. score만으로 rights/ACL/compatibility gate를 덮지 않는다.
3. 각 역할의 첫 후보와 유력 대조군을 작은 같은 corpus/query/run fixture로 비교한다.
4. 후보를 붙인 조합의 whole-loop 성능·정합성·운영·비용을 검증한다.
5. score 상위가 실제 domain quality에서 열세면 측정 evidence를 추가해 순위를 바꾼다.
6. 모델·service edition·가격·source가 바뀔 때 같은 방식으로 재평가한다.

## 4. 현재 host-dev infra profile

기존 Supabase 계정과 현재 Linux host를 사용한다. CPU worker, local raw/artifact/model cache, 작업 이력과 로그, 별도 backup 위치를 host 환경에 맞춰 설계한다. Supabase의 실제 project·namespace·DB 연결은 아직 미정이며 설정은 [infra-and-credential-requirements.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/infra-and-credential-requirements.md)의 interface·env로 후속 연결한다. AWS 계정·object store·job runner를 초기 준비물로 요구하지 않는다.

초기 public-source pilot은 인증·TLS·권한 필터·backup을 기본으로 설계한다. private connectivity가 반드시 필요한 사내 자료 profile은 별도로 계획하며, private endpoint/RBAC/SSO 지원 tier와 source ACL 연동을 검증하기 전에는 사내 자료를 넣지 않는다. Supabase/Aura의 저가 tier가 enterprise 기능을 제공한다고 가정하지 않는다.

생성 모델은 OpenRouter 또는 Codex interface로 선택한다. Embedding/reranking은 별도 capability와 CPU 대안을 두고 작은 표본에서 품질·CPU 시간·메모리·batch throughput·API 비용을 비교하도록 계획한다. 초기 GPU·새 API key 발급은 요구하지 않으며 실제 호출·모델 다운로드는 아직 수행하지 않는다.

초기에는 canonical ledger와 typed graph 조회를 PG에 두고 local artifact storage·host worker를 연결하도록 설계한다. 별도 graph service, vector DB, lexical engine, analytics service는 명시된 비교 gate가 충족될 때 추가한다. 이 선택은 KG 의미나 전체 flow를 생략하지 않는다. Embedding model의 출력 차원·dtype·ANN method·distance·managed extension version은 [embedding-index-compatibility.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/embedding-index-compatibility.md)로 확인한다.

## 5. 가격·용량 산정에 사용할 입력

구체 산식·공개 가격 근거·서비스 edition은 [03-cloud-operations.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/research/03-cloud-operations.md)를 따른다. 가격 조회일·currency·region·billing unit·replica/standby 조건을 비용 행마다 붙인다.

필수 입력은 documents, 평균 pages/tokens, parse complexity, chunk/overlap, vector dimensions/dtype/replicas/index overhead, graph node/edge 수, reindex rate, QPS/monthly queries, rerank candidates, agent rounds, HAT run hours, artifact retention, backup factor, network egress, extraction/embedding input units다.

총비용은 database/graph base + object/backup + CPU/GPU/job + API tokens/pages + workflow/queue + logs/metrics + network/egress + 재처리 + 운영 부담으로 계산한다. 무료 tier나 단일 service의 최소값을 전체 프로젝트 비용으로 제시하지 않는다.

## 6. 전환 조건

| 전환 | 계기 | 이전 절차 |
|---|---|---|
| pgvector → dedicated vector service | filtered recall/latency/scale gate 지속 미달 | canonical chunk/embedding space export, dual index, shadow query, alias switch |
| native FTS → BM25/hybrid engine | identifier+semantic domain eval에서 부족 | 같은 frozen corpus/query로 A/B, rights/ACL 유지 확인 |
| property graph → RDF 또는 병행 projection | formal ontology/standards interoperability 요구가 확정 | Claim schema mapping, loss report, 동일 evidence query 재현 |
| batch Parquet → analytics service | concurrent interactive queries/retention evolution 필요 | original artifacts 유지, incremental materialization, metric parity |
| API → local model 또는 역전 | domain quality gate 통과 후 비용·지연 우위 | embedding space 분리, shadow comparison, versioned rollback |
| managed → self-host | 예측 가능한 규모와 책임질 운영 조직 확보 | export/restore rehearsal, IAM/network/backup equivalence |

## 7. 선택을 보류한 부분의 처리

최종 embedding·parser·검색 parameter는 실제 DSE gold 비교로 결정한다. 이는 설계가 빠진 것이 아니라 선택 알고리즘·acceptance가 계획에 정의된 실험 변수다. 반면 billing account, 실제 spending cap, private source authority는 실행 전 사용자/조직이 제공해야 하는 운영 입력이다.

아직 전체 설계 패키지를 사용자가 검토하지 않았으므로 실행 단계로 넘기지 않는다. 향후 실행 방식은 이미 요청된 master/worker workflow를 유지한다.
