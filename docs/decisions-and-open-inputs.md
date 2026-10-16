# 요구·설계 결정·운영 입력 기록

2026-10-17 추가 결정: P0 계약·actual source support 상태는 [p0-remediation-report.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/p0-remediation-report.md)가 기준이다. 아래 과거 기술 추천은 조사 prior로 보존하며, P1 graph baseline은 [0001-graph-backend-selection.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/adr/0001-graph-backend-selection.md)로 갱신한다.

기준일: 2026-10-16. 사용자 확정 사항, root의 제안, 앞으로 실행할 때 필요한 입력을 분리한다. 이 기록은 구현 승인서가 아니다.

## 1. 사용자 확정 사항

| ID | 내용 | 반영 위치 |
|---|---|---|
| U01 | 모든 HW 계층의 asset 조합 검토 | 전체 spec, schema, phase matrix |
| U02 | agent가 필요한 KG를 스스로 찾아 검토·생성에 이용 | retrieval tool 계약, committee adapter, P1/P4 |
| U03 | HATIR fold/unfold·fusion과 RP resource state 활용 | kernel schema, 새 replay 원칙, P1/P3 |
| U04 | 실험 분석·feedback·다음 제안과 모든 시행착오·Insight | Experiment Trajectory, Melete mapping, P1부터 전체 loop |
| U05 | 다양한 LLM 성능 지표를 모두 비교 | Metric Vector, registry, cohort/Pareto |
| U06 | 수집 자료 없음; source별 수집 계획부터 | 40-family source catalog와 권리/갱신/QC |
| U07 | RAG/graph/DB/infra/model/search/schema를 넓게 비교하고 추천점수 순 검토 | 73개 기술·알고리즘 후보, rubric, scorecards, 조합 평가 |
| U08 | 대부분 cloud 예상, 특정 cloud/region/예산 없음 | multi-cloud 비교, 비용 산식·scale envelope |
| U09 | 사내 Confluence RAG의 Supabase/Neo4j 경험 | 후보 적합성 맥락; 실제 접근권/재사용은 가정하지 않음 |
| U10 | 구현은 전체 설계·계획 완료 전 금지 | P0 boundary, 모든 미래 command 미실행 |
| U11 | 모든 phase가 전체를 점점 선명하게 | phase×capability matrix, P1–P5 전체 episode acceptance |
| U12 | Superpowers와 master/worker workflow | phase skill checklist, 독립 review, master 실제 검증 |

## 2. Root 제안으로 표시하는 결정

| ID | 제안 | 이유·변경 조건 |
|---|---|---|
| D01 | managed PG ledger/typed graph baseline + 동일 질의 Neo4j challenger | 의미·권한·snapshot parity 이후 성능/TCO gate. Neo4j 선배포를 가정하지 않음 |
| D02 | canonical knowledge/experiment record와 graph/vector view 분리 | 권위 충돌과 stale projection을 드러내고 재구성 가능하게 함 |
| D03 | 초기 data profile은 공개 사용 허용 자료, 사용자 소유 HAT/Melete 계약의 필요한 범위, synthetic workload | 사내 Confluence 연결은 현재 요구에 포함하지 않고 future connector로 둠 |
| D04 | 초기 model은 BGE/Qwen/허용 API의 비교 절차로 선정 | domain gold 없이 특정 embedding이 최상이라고 단정하지 않음 |
| D05 | 전력·energy 등 미지원 metric은 missing/unsupported로 등록 | 지표를 볼 수 있는 기능과 정확히 계산 가능한 범위를 구분 |
| D06 | dev/stage RPO24h/RTO8h, 중요 experiment-ledger 운영 후보 RPO1h/RTO4h | 아직 검증되지 않은 planning target. 비용·복구 실측으로 조정 |
| D07 | WORM/irreversible retention lock은 기본 비활성 | 삭제 정책과 운영 필요가 확정되기 전 되돌릴 수 없는 설정을 만들지 않음 |
| D08 | cloud knowledge plane과 execution site를 adapter로 분리 | HAT/Melete가 local/on-prem/cloud 어디에 있어도 같은 manifest/event 계약 유지 |
| D09 | 초기 scheduling은 managed queue/Batch부터 검토 | 상시 GPU·Kubernetes 운영을 필수 전제로 만들지 않음 |
| D10 | 모든 score는 prior/E1와 measured/E2+를 분리 | 수치가 실제 benchmark나 진실 확률처럼 읽히는 것을 방지 |

## 3. 실행 위치의 제안 기본값

현재 확인한 것은 로컬 HAT/Melete 저장소와 계약이며 실행 중인 서비스나 cloud endpoint를 확인한 것이 아니다. P1에서는 승인된 **격리된 test execution site**를 먼저 정한다.

기본 연결 설계는 HAT/Melete 가까이에 둔 adapter worker가 cloud job manifest를 받아 로컬 계약으로 실행하고, artifact hash와 events를 cloud ledger에 전달하는 방식이다. 작업은 signed/authorized manifest와 허용된 runner entrypoint로 제한한다. source 문서나 agent가 임의 shell command를 job으로 주입하지 않는다. 외부에서 private host 포트를 여는 것을 기본값으로 삼지 않는다.

ExecutionSite record에는 site ID, region/location class, trust boundary, supported HAT/Melete versions, queue binding, artifact endpoint, resource quotas, identity, allowed workloads, retention을 기록한다. 완전 cloud 실행을 선택해도 같은 계약을 쓴다. 실제 네트워크 연결·credential·daemon 설치는 수행하지 않았다.

P1에서도 **이 지식 시스템에 처음 들어오는 모델의 실제 onboarding**을 수행한다. ModelVersion 신규 등록, model/config·tokenizer/chat-template revision과 권리 확인, workload 의미 구성, HAT 지원 여부 검증을 생략하지 않는다. 첫 positive fixture는 기존 HAT runtime이 이미 지원하지만 이 지식 시스템에는 아직 등록되지 않은 작은 pinned model/shape로 선택한다. 지원되지 않는 op/model revision의 negative fixture도 함께 등록해 unknown/unsupported 경로를 검증한다. 모델 명칭을 미리 invent하지 않는다.

P2는 onboarding 기능을 새로 시작하는 단계가 아니라 모델 family·shape·ISA·vendor·규모를 확대하는 단계다. 사용자 지정 새 LLM과 1,000-session scenario도 P1에서 검증한 같은 경로를 사용한다. 실제 최신 모델이 기존 HAT에 없는 semantics를 요구하면 별도 HAT 지원 확장 계약이 필요하며, adapter가 지원을 만들어낸 것처럼 처리하지 않는다. B300은 시뮬레이션 target과 실제 측정 장비를 별도 resource로 취급한다.

## 4. 실제 설정 직전에 필요한 운영 입력

| 입력 | 현재 상태 | 없을 때 동작 |
|---|---|---|
| billing account와 resource owner | 미제공 | cloud resource 생성하지 않음 |
| region/실제 service edition | 선호 없음, 비교 완료 | co-location·가용성·egress·권한 요구에 맞는 profile 제시 후 설정 |
| 월간 비용 상한·campaign budget | 미제공 | 유료 자동 실행 불가; 계획 비용 산식만 유지 |
| HAT/Melete test execution site | 저장소 위치만 확인 | 실제 E2E gate를 완료로 표시하지 않음 |
| private data 접근·외부 API 전송 권한 | 미제공 | public/허용 자료 profile 유지, private connector 활성화하지 않음 |
| retention·복구 목표의 최종 수용 | 제안값만 있음 | irreversible lock 비활성, 제안 비용/restore profile 검토 |

사용자가 cloud·예산이 미정이라고 답한 사실을 반복 질문으로 되묻지 않는다. 지금은 선택 기준·대안·비용 산식·setup 절차를 완성하고, 실제 설정 단계에서 필요한 최소 입력만 확인한다.

## 5. 독립 검토와 수정

| 검토 | 발견 | 반영 |
|---|---|---|
| storage ← model worker | Neo4j 정본/파생 표현 충돌 | PG Claim/Evidence/ACL 정본과 재생성 graph로 통일 |
| storage ← model worker | ACL revocation 중 stale index 경계 부족 | authoritative epoch와 graph/cache/rerank 직전 fail-closed 확인 |
| models ← storage worker | 무료 model의 economics 과대평가 | 미측정 local compute TCO를 중립 3으로 재산정 |
| sources ← infra worker | ACM legacy usage URL | canonical 플랫폼/정책과 item별 rights gate로 수정 |
| infra ← source worker | OpenSearch mode별 OCU 비용 차이 | Classic redundant/dev-test/NextGen을 구분 |
| infra ← source worker | Spanner per-replica를 전체처럼 해석할 위험 | regional replica 수와 compute-only 산식 명시 |
| fresh builder check | 전체 phase coverage 확인; 운영 입력 4군 제시 | 이 문서의 public profile·execution site·budget·retention 계약으로 분리 |
| final builder check | P1의 신규 모델 onboarding이 P2로 미뤄지는 것처럼 읽힘 | P1 positive 신규 등록과 unsupported negative fixture를 acceptance에 추가; reviewer 재확인 closed |

Builder check에서 phase를 기능별 silo로 나눈 결손은 발견되지 않았다. 이 검토는 HAT/Melete runtime integration이나 source/domain quality가 통과했다는 뜻이 아니다.
