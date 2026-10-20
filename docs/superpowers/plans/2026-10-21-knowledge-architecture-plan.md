# DSE 지식 시스템 Architecture·구현 준비 계획

> **For agentic workers:** 설계·검토는 Superpowers와 지정된 master/worker workflow를 따른다. 향후 구현에는 superpowers:subagent-driven-development를 사용한다. 아래 checkbox는 설계 산출물의 확인 항목이며 현재 제품 구현을 실행하라는 지시가 아니다.

**Goal:** DSE 전 과정의 결정별 지식 요구와 source 수집, DB/model 조합, schema, 전체 write/read workflow, infra 준비를 연결한 설계와 실행 계획을 완성한다.

**Architecture:** DecisionTask가 KnowledgeRequirement를 만들고, 요구가 CollectionPlan과 QueryPlan을 함께 구동한다. Versioned 지식 정본과 raw artifact를 기반으로 SQL·typed graph·lexical·dense 검색과 분석을 연결하며, 실험·경험·지식 부족을 다음 수집과 결정에 환류한다.

**Tech Stack:** 기존 Supabase의 PostgreSQL·pgvector/FTS, 현재 Linux host의 CPU worker와 local artifact storage를 dev baseline으로 설계한다. 모델은 OpenRouter 또는 Codex를 interface·env로 선택하며 embedding/reranking의 capability와 CPU 대안을 별도로 설계한다. Neo4j 및 대체 검색·모델 조합은 동일한 DSE 질문으로 비교한다. AWS는 사용하지 않는다. 실제 Supabase project·model ID·host 배치 방식은 미확정이다.

**Spec:** [2026-10-21-dse-knowledge-architecture.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/superpowers/specs/2026-10-21-dse-knowledge-architecture.md)

## 전체 범위와 진행 규칙

- 모든 설계 phase는 목표·workload/model·rack/tray·package/SoC/하위 요소·조합·serving·kernel·simulation 해석·실험 분석·다음 제안의 전체 결정 범위를 다룬다.
- 각 phase는 지식 요구 → source → 저장/모델 → write → read/판단 → 실험/경험/지식 부족의 환류 전체를 더 구체적으로 만든다. 기능별 silo phase로 바꾸지 않는다.
- 구현 전 전체 설계·계획을 검토한다는 사용자 요구를 유지한다. Credential 준비와 계정 정보 제공은 cloud apply·유료 실행 승인이 아니다.
- 사용자의 추가 답변에 따라 새 AWS 계정·GPU·모델 API key 발급을 지금 요구하지 않는다. 기존 Supabase 계정과 Linux host를 기준으로 준비 명세를 작성하고 실제 credential은 나중에 env/인증 interface로 연결한다.
- Root는 파일 범위·작업 분할·통합과 실제 검증, native worker는 지정 산출물, 별도 reviewer는 요구 충족 검토를 맡는다. Worker 재위임은 하지 않는다.
- 실제값이 없는 규모·성능·가격·모델 품질은 제안 또는 미정으로 표시한다. 추천 점수와 DSE Metric Vector를 분리한다.

## 설계 phase별 전체 coverage

| 설계 phase | 지식·source | DB/model·schema | Write/read·workflow | Infra·계획 | 완료 증거 |
|---|---|---|---|---|---|
| D1 전체 지도 | 모든 DSE 결정, 필요한 지식 종류와 대표 source | 구성 계층·핵심 객체·후보 모델 역할 | 전체 순환과 agent/HAT/Melete 경계 | 기존 Supabase·Linux host·비밀 아닌 입력 | 모든 영역이 같은 전체 지도에 연결된 표 |
| D2 후보 비교 | 세부 requirement와 source authority·coverage·수집 우선순위 | 역할별 제품·모델·조합 비교 | 추출·검색·graph·수치 분석의 대안 | Supabase edition·host 용량·API/운영 비용 비교 | 근거 있는 추천 순위와 탈락·전환 조건 |
| D3 논리 설계 | 수집 필드·갱신·conflict·충족 조건 | entity·관계·metadata·version·scope | 상태 전이·질의 유형별 QueryPlan·근거/미충족 반환 | 서비스 경계·접근·보존·복구 | 결정→요구→source→schema→read/write 추적표 |
| D4 상세 설계 | source별 connector/parser·chunking·표/수식/code 처리 | 테이블·index·projection·embedding space·모델 설정 | 증분 갱신·중복·재시도·권한·재검색·평가 절차 | sizing·배포 구성·credential scope·비용 산식 | 구현자가 추가 architecture 추측 없이 설명 가능한 명세 |
| D5 실행 계획 | 초기 수집 범위·우선순위·지속 갱신 | 확정 선택·대안·교체·migration 조건 | 작업별 입출력·파일 범위·의존성·검증 | 설정 순서·담당·예산·운영·rollback | 검토 가능한 구현 backlog와 준비 상태표 |

D1–D5는 기존 구현 P1–P5와 다른 **설계 상세도 단계**다. 2026-10-21 현재 D1의 전체 architecture 초안을 게시하고 infra 입력을 요청했으며, D2–D5 완료나 전체 설계 확정을 주장하지 않는다.

## 현재 작업과 다음 작업

| 순서 | 작업 | 입력 | 산출물 | 의존성 |
|---:|---|---|---|---|
| 1 | 상위 architecture 게시와 문서 우선순위 정리 | 사용자 정정·화면 표·기존 조사 | 새 spec, README/AGENTS/handoff 연결 | 현재 승인 범위 |
| 2 | 구현 준비 요구 정의 | Supabase·Linux host·OpenRouter/Codex 선택과 기존 조사 | infra·credential·env 표, 후속 연결에 필요한 입력, 조건부 준비 | 계정에 접속하지 않고 작성 가능 |
| 3 | 결정별 지식 요구 상세화 | 모든 DSE 결정 목록 | 요구별 지식 종류·scope·충족 기준·공식 source 대응 | cloud 입력과 독립 |
| 4 | source·DB·model·조합 추천 정리 | 기존 조사·동일 DSE 질문 집합 | 후보별 prior, 공식 근거, 평가 계획, 선택/전환 조건 | 유료 성능 평가는 별도 실행 범위 필요 |
| 5 | 논리·물리 schema와 알고리즘 상세화 | knowledge requirement·선정 후보 | write/read 상태·metadata·projection·QueryPlan·갱신 명세 | 확정/미정 선택을 명시 |
| 6 | 환경별 준비 계획 구체화 | 확정 환경과 예산·자료 범위·Supabase project 입력 | host sizing·권한·env·인증 참조·설정/검증 순서 | 답변이 없는 해당 연결 항목만 대기 |
| 7 | 전체 설계·계획 검토와 구현 backlog 확정 | D1–D5 산출물 | 역할·파일 범위·검증·비용을 포함한 실행 계획 | 사용자 요구에 따른 설계 검토 |

## Infra 입력과 계속할 수 있는 작업

요구 입력과 서비스별 credential 준비는 [infra-and-credential-requirements.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/infra-and-credential-requirements.md)가 기준이다. 사용자에게 실제 secret을 채팅이나 public repository에 제출하도록 요청하지 않는다.

| 미정 입력 | 해당 입력이 필요한 작업 | 답변 없이 계속할 작업 |
|---|---|---|
| 기존 Supabase의 실제 project·DB namespace | 해당 DB 연결·migration·권한 설정 | 지식 수요, source 조사, 논리 schema, Linux 배치 설계 |
| 월 비용·API/GPU 상한 | edition·상시/배치 자원·quota 확정 | 비용 산식·시나리오·권한 요구 정의 |
| 사내 자료 범위·외부 모델 전송 조건 | Confluence 수집·사내 corpus 처리 | 공개 source 조사·도메인 schema·read/write 설계 |
| OpenRouter/Codex의 model ID·실행 사용자·인증 상태 | 해당 adapter 연결·실제 생성 평가 | provider interface·env 항목·모델 역할·평가 질문 |
| embedding/reranker backend·host 자원 상한 | 실제 index 생성·모델 평가 | CPU/remote 후보·embedding space·호환 조건 |
| B300 asset·native chain | 해당 target의 실제 실험과 성능 주장 | 현재 지식 시스템 architecture·수집·DB/model·workflow 설계 |

## Review focus와 문서 검증

- [ ] 모든 DSE 영역에 결정 질문·필요 지식·source·저장 객체·읽기 경로가 연결되는지 확인한다.
- [ ] KnowledgeRequirement의 충족·부족·충돌·오래됨 상태가 수집 계획과 QueryPlan에 반영되는지 확인한다.
- [ ] DB·model·cloud 후보를 이미 선정·배포한 것처럼 표시하지 않는다.
- [ ] Credential마다 사용 작업·최소 범위·준비 시점·전달 경로를 기록하고, 조건부 서비스를 필수 준비물로 오인하지 않게 한다.
- [ ] 원문/실험/Insight 순환이 독립 근거를 늘리지 않고 원문 위치·version·scope를 보존하는지 확인한다.
- [ ] Root가 링크 대상·공개 문서 내 비밀/개인 경로·변경 범위와 `git diff --check`를 확인한다. 제품 runtime 테스트 수는 별도로 보고한다.

과거 native 판정 계약은 [integration-state-map.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/integration-state-map.md), 기존 기술 후보는 [recommendation-and-selection.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/recommendation-and-selection.md)를 상세 참고로 유지한다.
