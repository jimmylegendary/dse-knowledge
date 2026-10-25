# DSE Knowledge Workbench 품질 보완 v2

사용자가 승인한 보완: Write에서 source 역할·Claim 단위/revision/조건을 구조화하고, KG 개체 연결과 Read를 개선하며, 같은 실제 전체 여정으로 1,000개 규모를 검증한다. 기존 구현·평가 commit은 f2e113c, 고정된 100-source baseline과 30개 공개 regression qrels를 보존한다.

## 구현 선택과 범위

Master의 구현 선택: 기존 Python/FastAPI/PostgreSQL/pgvector/FTS, host Codex CLI gpt-6.1-sol/max, DeepInfra google/embeddinggemma-2 768차원을 유지한다. 새 DB·GPU·weight 다운로드·AWS를 추가하지 않는다. 모델/검색/자료 판단은 근거와 검토 provenance를 보존하고 unknown을 강제 성공으로 바꾸지 않는다. Public에는 source metadata·집계·코드만 게시한다.

### Phase Q1 — 현재 100개의 더 선명한 전체 제품

사용자는 UI/CLI에서 role이 표시된 자료를 찾고, 조건·parameter·source proof가 있는 Claim과 source 간 topic graph를 검토하고, 개선된 검색으로 DSE source 질문에 답변을 받고, metric 입력·HAT schema 구조검증·Melete feedback/재검색·gap/다음 제안까지 실제로 수행한다. 기존 100개 원문과 101개 Claim은 삭제/조작하지 않는다. 새로운 annotation과 source-grounded Claim을 추가한다. 새 ontology는 물리 조립/ISA/kernel correctness를 인증하지 않는다.

### Phase Q2 — 실제 1,000개 전체 제품

Q1의 같은 UI·DSE·feedback 여정을 유지하며 기존 자료목록에서 source 1,000개를 실제 수집·역할 분류·index·검증된 Claim/조건으로 처리한다. Source navigation은 locator로, 무관/미지원/불충분은 별도 상태로 보존한다. 실패·quota·공간 guard·재개와 실제 처리량/토큰을 측정한다. 단순 1,000개 metadata나 mock으로 phase를 끝내지 않는다. 145,748건은 실행하지 않는다.

| Capability | Q1 | Q2 |
|---|---|---|
| Write | 기존100 role assessment 반영, 새 core3/method2/ops1 Claim 상한과 조건·값·인용 proof | 같은 정책의1,000 실제 자료, source/실패/처리 상태별 집계 |
| Read/KG | lexical 자연어 핵심어, source-role intent, 약한 graph boost, source/chunk rerank, grounded topic links | 같은 경로의 실제 크기·quota·지연과 새 material 질문 평가 |
| DSE/경험 | 실제 source 답변·unknown·gap·proposal·Melete 재조회, metric 비교와 native HAT 구조검증 | 같은 정상/미지원·feedback 여정을1,000 corpus에서 재검증 |
| 운영 | source/model/annotation version과 quote proof, UI 표시, 기존회귀 | durable lease batch, 실패/재개·자원 guard·provider quota, 실제1000 종료 gate |

## Write 계약

Source role enum: core_technical, supporting_method, integration_operations, source_navigation, out_of_scope, unclassified. 역할은 curator annotation이지 scientific authority가 아니다. 기존100의 평가 role은 평가 provenance와 함께 반영한다. 신규자료는 title/head/선택 문맥을 공유 Jev advisory로 분류하고 model/방법/근거 hash/unknown을 남긴다. Role 불명은 검토 필요, out_of_scope는 DSE 근거에서 제외하고 locator는 자료 탐색에 사용한다. Source metadata origin과 실제 acquired fulltext revision scope를 혼동하지 않는다.

Claim context v1 wire shape:

```json
{"schema_version":"claim-context/v1","parameters":[{"name":"metric_or_parameter_name","value":6.4,"unit":"%","evidence":{"chunk_id":"...","quote":"exact source passage"}}],"conditions":[{"dimension":"hardware.from","operator":"eq","value":"V100","unit":null,"evidence":{"chunk_id":"...","quote":"exact source passage"}}],"source_scope_note":"source-specific applicability; unknowns explicit"}
```

Value는 finite scalar 또는 scalar list, operator는 eq/in/between/gte/lte. 조건이 없으면 빈 배열, 값이 근거에 없으면 생성하지 않는다. 단위는 원문값과 normalized representation을 함께 보존하고 알 수 없는 단위는 unresolved로 남긴다. Evidence는 같은 material/revision의 제공 chunk 안의 정확하고 모호하지 않은 인용을 요구한다. validator가 source_start/end와 revision SHA를 계산한다. 숫자·단위/문자값의 literal 근거를 확인하되 이것을 숫자와 metric의 의미 연결/과학적 정확성/일반 적용 가능성 인증으로 바꾸지 않는다. 항상 use_policy=source_assertion_only, validation=literal_grounded_unverified_association, independent_validations=0 상한이다.

기존 claims quote/triple/metadata는 덮어쓰지 않는다. 새 claim_annotations에 context와 extractor/model/proof/version을 append하고 최신 projection을 read에 제공한다. 동일 hash 재처리는 idempotent다. HFpl V100→A100/InfPop와 thermal 동일 capacity/bandwidth 조건 누락은 regression fixture로 둔다. 3/2/1은 최대이며 근거 없는 Claim 수를 강제로 채우지 않는다.

Knowledge pure module interfaces (worker A):
- SOURCE_ROLES, CONTEXT_SCHEMA, ROLE_SCHEMA
- validate_claim_context(context: dict, document: prepared_document) -> normalized dict (proof 포함)
- canonical_topic_mentions(text: str) -> list[{key,label,kind,alias,start,end}]
- validate_role_assessment(payload: dict) -> normalized dict
- ingestion.extract_claims 기존 signature에 structured=False를 추가; True일 때 각 claim.context를 생성/검증하여 반환. 기존 모드는 그대로 호환.

## KG 개체·관계

자유 subject/object phrase를 서로 다른 asset instance로 강제 병합하지 않는다. 기존 assertion edge는 보존한다. 작은 versioned curated alias registry를 이용해 인용에 실제 나타난 KV cache/vLLM/CUDA/HBM/GPU family 등 공통 topic node와 evidence-topic link를 추가한다. H100과 Hopper, A100과 특정 메모리/board revision은 같은 asset으로 합치지 않는다. Topic은 family/concept/interface/metric/software 등 kind를 갖고, quote span·claim/revision을 참조하며 assertion과 별도 relation_kind=topic로 구분한다. `mentions`는 compatibility/causality/inheritance가 아니다. 최대 component 크기를 늘리려고 관계를 만들어내지 않는다.

## Read 계약 (worker B)

Retriever.search(query,category='',limit=12,purpose='auto') 기존3 positional 인수호환. purpose는 auto/design/operations/discovery. Role별 근거 사용을 보존하고 out_of_scope는 일반 DSE 답변에서 제외한다. Auto는 versioned deterministic policy이고 classification uncertainty를 기록한다. Lexical은 full-question AND 대신 quoted phrase/identifier/비stopword 핵심어를 parameterized query로 사용한다. English/Korean 자연어·code token을 지원하되 학습모델 다운로드는 없다.

Dense를 기반으로 lexical/명확한 entity/topic match를 bounded boost하고 흔한 단어 graph OR로 관련없는 source를 올리지 않는다. Graph 후보도 semantic/query relevance로 정렬한다. 후처리 diverse cap은 충분한 candidate pool에 적용하고 빈자리를 채워 evidence가4개로 줄어드는 문제를 피한다. Source 역할·지정 source명·scope·query term과 의미 score를 명시적 deterministic rerank에 사용할 수 있다. 신규 외부 reranker 모델 호출을 필수화하지 않는다. Neighbor 문맥은 원래 chunk ID/text/offset을 유지한 별도 evidence로 추가하며 다른 text를 한 chunk ID에 합치지 않는다.

각 결과는 role/role_metadata와 해당chunk의 최대2 compact claim context ref를 포함한다. Root Store/migration이 이를 제공한다. Snapshot에 retrieval policy/version·context ID·role assessment ref를 보존한다. 필수규칙은 기존처럼 retrieval top-k와 별도다. Embedding-only bounded TTL cache(기본300s/128query)는 exact normalized query+provider/model/dim/task에 묶고 PG 결과는 캐시하지 않는다. Cache hit는 새 provider token으로 과금 기록하지 않는다. Worker는 root DB integration을 기다리지 않고 오프라인 fake Store/Embedding으로 검증한다; 실제모델/DB는 root만 호출한다.

## DB 변경 소유(root)

003_quality: materials.role/role_metadata, claim_annotations(id,claim_id,revision_id,version,context jsonb,metadata jsonb,created_at, UNIQUE content hash identity), entities.metadata, edges.relation_kind(assertion/topic)/metadata 및 필요한 indexes. Material role 변경은 ingest_event와 같은 transaction. 새 context는 source revision에 FK. Runtime role CRUD/USAGE만 추가하고 DDL권한은 주지 않는다. material_detail/retrieval에서 최신 annotation projection을 반환하되 old decision snapshot과 Claim을 보존한다.

## 1,000 collection 계약 (worker C)

worker C는 collection.py, migrations/004_collection.sql, tests/test_collection.py만 소유한다. Root가 기존pipeline·CLI에 real handlers를 연결한다. CollectionManager(store,data_root,handlers,policy), create_batch(batch_id,records,target), run_worker(batch_id,worker_id,max_steps=None), summary(batch_id). Store는 기존 connection/rows/one/execute/ingest_event/invocation 인터페이스다.

Tables: collection_batches(id text PK,target int,policy jsonb,state text,counters jsonb,created_at,updated_at); collection_items(batch_id FK,material_id text,record jsonb,state text,next_stage text,attempts int,next_attempt_at timestamptz,lease_owner text,lease_until timestamptz,last_error jsonb,metadata jsonb,created_at,updated_at,PRIMARY KEY(batch_id,material_id)). item의material_id는fetch실패도기록하므로materials FK를요구하지않는다.

States: pending/acquired/assessed/indexed/complete/reference_only/excluded/needs_review/retry_wait/failed. 단계 handler acquire/assess/index/extract는 (record,item_metadata)->{next_state,metadata,usage?}를 반환한다. 영구 정책 제외·불충분·retryable provider error를 구분한다. Worker DB lease는 SKIP LOCKED/owner fencing으로 확보, heartbeat로 연장, stale owner는 completion 불가. Summary는 row에서재계산하며 completed=성공+reference를 단계별 분모와 함께 보존한다. model/write-before-commit 사고의 paid call exactly-once는 보장하지 않는다; private validated response cache로 완료된 호출의 재사용을 돕는다.

Resource policy: root만실행, fetch최대2, indexing최대2, generation최대4 application workers; host reserve10GiB, 초기추가artifact budget4GiB, source8MiB/request 및기존SSRF/timeout/cookie불사용정책. 안전free reserve안에서만budget확대가능하고ruling기록. 첫3회연속provider/quota오류는batch를blocked로남겨무한재시도금지; credential오류본문/secret은노출하지않는다. acquired와이미committed된index/Claim을재실행하지않는다. lease/status/usage/failed input/receipt를보존한다. 1,000 target의기존100도합쳐중복제거하고source역할및정상적으로index된실제자료수를집계한다. 실패candidates는1,000성공으로세지않는다.

## 실제 종료 gate

Q1: 기존161 unit + 신규meaningful tests, quote/condition grounding, 단위·revision·role·asset false merge 반례, TTL usage0, source API/UI 표시, 실제normal/unknown/Melete/native HAT·metric 비교·재시작 회귀. 기존30은 공개regression: source@5 최소24/24, knownchunk@5 최소14/24, source@1 개선목표20/24. 새로운 결과독립 질의에서source@5>=85%를확인하며부분qrels·표본크기상한을표시. ActualLLMprobe는전부knowledge/input{}만보여label누출방지.

Q2: 실제1,000 ingested fulltext + role outcome + eligible Claim/annotation 처리상태를명시, incomplete는complete라하지않는다. 최소90% core/support/ops 자료에서근거있는Claim이생성돼야지식처리gate이며나머지는이유가있는needs_review로별도표시; locator는Claim0정상. 실제1000 corpus에서새material holdout질의·normal/unknown·feedback·metric·HAT구조검증을다시수행하고기존Q1회귀를유지한다. interrupted batch 재개와동일material/Claim중복0, 자원·provider실제usage·실패/남은작업,GitSHA를보고한다. Provider quota/공간으로멈추면phase미완료로명시하고안전한독립작업은계속한다.

## Builder 검토 후 확정한 ruling — 구현 시 이 절이 우선

1. Q1은 기존101 Claim의 원문·triple을 보존하고 eligible94자료의96 Claim에 context annotation을 backfill한다. Navigation/out-of-scope는 원래 Claim이 있어도 재생성하지 않는다. 새 자료(Q2)는 core3/method2/ops1 Claim 상한의 structured extraction을 사용한다. Worker A는 extract_claim_contexts(document, existing_claims, chat)->list[{claim_id,context}]도 추가한다. API 호출 전에 root가 response cache로 재사용하며 annotation/processing version으로 재개한다.
2. Topic edge는 **기존 Claim과 그 quote/검증된 annotation evidence에만** 붙인다. Claim 없는 chunk의 mention은 이번 phase에 graph assertion으로 만들지 않는다. edges.claim_id FK/NOT NULL을 유지하고 evidence_chunk_id FK와 metadata의 proof quote/source_start/end/revision을 추가한다. relation_kind=topic이면 evidence_chunk_id 필수. Graph read는 topic evidence_chunk_id 또는 기존 assertion의 claim.chunk_id를 사용한다. Claim 없는 locator의 검색은 material/chunk 경로가 담당한다.
3. Context 입력의 value/unit은 source literal raw representation이다. Validator 출력은 이를 value_raw/unit_raw로 보존하고 normalized={value,unit,status}를 별도로 계산한다. 알려진 multiplicative unit(time s/ms/us, W/kW, energy J/mJ, B/KB/KiB/MB/MiB/GB/GiB, token/s·tokens/s·req/s)은 scale을 명시한다. %는 identity로 보존한다. 알 수 없는 단위/offset temperature 변환은 unresolved, 단위 미지정 numeric은 unit_unspecified, 문자/boolean은 not_numeric. unit/value가 source literal에서 확인되지 않으면 자동 추정하지 않는다. parameter는 scalar 또는 동일 scalar type의1..32개 list. condition eq는scalar, in은동일type의1..32 list, between은finite numeric2개/오름차순, gte/lte는finite numeric scalar다. 이 normalization은 semantic association/적용가능성 검증이 아니다.
4. 역할별 policy: design은core(1.0)/method(.9)/ops(.65)를 허용하고 ops의사용상한은workflow/interface reference다. operations는ops(1.0)/core(.8)/method(.7). design/operations의navigation은locators로분리한다. discovery는navigation/core/ops/method를locator 또는source-assertion 범위에서 items로반환하며unclassified는needs_review 표시다. out_of_scope는일반검색에서제외하고 material ledger browse에서는보존한다. auto는문서·목록·어디서찾기/feature-map이면discovery, 설치·설정·API·CI·재현/운영이면operations, 그밖은design. 불명확하면design+role상한을보존하고판정규칙을trace에남긴다. DecisionEngine은기존kind에관계없이기본auto를전달하며 retrieval role policy를LLM에제시한다. required_rules 경로는그대로독립이다.
5. target1000은distinct ingested fulltext 총수로 **기존100을포함**한다. 원문/revision/embedding/기존Claim을재생성하지않고Q1annotation을reuse한다. 후보pool manifest를acquire전에고정하고최종1,000accepted corpus manifest는완료후/평가전에별도로고정한다. 새gold는최종corpus에서새자료를대상으로결과와독립작성하고case IDs는opaque, expected label/source IDs/rationale는모델TASK나SOURCE/EXPERIENCE에주입하지않는다. 실제retrieved source/chunk IDs는인용에필요하므로허용한다. 모든answerabilityprobe는공통kindknowledge,input{}; goldfeedback추가없이전체probe를먼저끝내고그후generic userfeedback/Melete회귀를한다. 사용된gold는공개후regression이며다시blindholdout으로쓰지않는다.
6. collection item metadata 고정키: prepared_path,source_revision_sha256,role,indexed(bool),extraction_version,claim_count,annotation_count. indexed true/이미완료와유효inflight예약을target분모로관리하며영구제외/미분류미index는slot을반환한다. stale owner완료불가, stage cap은fetch2/index2/extract4다. Stage role assessment에Jev를사용하되정본의과학authority로승격하지않는다.
7. 공개30 회귀에서 드러난 source 선택과 passage 재정렬 충돌은 `retrieval-policy/v2.1`의 일반적인 source-then-passage 정책으로 보완한다. 각 stream의 첫 dense material을 semantic anchor로 택하되, 그 material 안에서는 기존 hybrid 점수가 가장 높은 passage를 쓴다. 나머지 채널 가중치·역할별 사용상한·material당3개 다양성 정책은 유지한다. 역할 가중치는 soft relevance prior이며 authority 등급이나 금지 규칙이 아니다. Operations source가 anchor여도 design의 workflow/interface 사용상한을 그대로 보존하고, source 순위로 검증된 물리 규칙으로 승격하지 않는다. 미분류 source는 anchor에서 제외한다. 질문별 예외·qrel lookup은 금지하고 원래 dense/hybrid 순위와 anchor 선택을 API와 평가 artifact 모두에 남긴다. 기술근거 `items`는 locator를 제외하며 DecisionEngine은 계속 이것만 사용한다. 실제 자료찾기/UI의 `source_results`는 evidence와 locator를 typed 결과로 함께 순위화하되 모든 typed locator의 evidence_authority=0과 사용금지를 보존한다. `locators`도 별도 제공한다. 과거 v1 검색에 navigation 자료가 포함됐으므로 기존 source-search 회귀의 production hybrid는 실제 `source_results`를 같은 k개의 chunk slot으로 평가하고, 기술근거 전용 `hybrid_evidence` 점수는 별도로 모두 보고한다. source의 발견을 기술주장의 검증으로 세지 않는다. 최초 v2의 source@5=22/24, chunk@5=16/24 실패 보고서는 보존한다. 이 정책은 새28 holdout retrieval을 처음 실행하기 전에 고정하고 새 결과로 튜닝하지 않는다.
