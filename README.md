# DSE 지식·실험 시스템 설계 패키지

공개 저장소: [jimmylegendary/dse-knowledge](https://github.com/jimmylegendary/dse-knowledge). 2026-10-17에 설계·계획 패키지를 게시했다. 제품 구현과 cloud 배포는 아직 시작하지 않았다.

문서 내부 링크는 GitHub 공개본을 가리킨다. HAT·Melete 통합 근거의 일부는 별도 접근 권한이 필요한 저장소를 참조하며, 해당 저장소의 코드를 이 저장소에 복사하지 않았다.


상태: **v0.3 DSE 의사결정용 지식 시스템 architecture·planning / 구현 준비 입력 수집**. 기준일: 2026-10-21 KST. 현재 설계의 중심은 **DSE 단계별 결정 → 필요한 지식 → 수집 내용·source → DB·model 조합 → schema → write/read algorithm·workflow → 지식 부족의 환류**다. 제품 구현·runtime·cloud provisioning은 미실행이다.

현재 dev 환경은 **기존 Supabase 계정 + 현재 Linux host + local artifact storage**로 설계한다. 모델은 **OpenRouter 또는 Codex**를 provider interface와 환경변수로 선택하게 계획한다. AWS는 사용하지 않으며, GPU는 초기 필수 자원이 아니다. 계정·API key를 지금 발급하거나 제출하도록 요구하지 않는다.

## 현재 설계부터 읽기

2026-10-18 사용자 방향 정정과 2026-10-21 게시 요청을 반영했다. 아래 architecture와 설계 계획이 상위 기준이며, 이전 native 판정 계약·episode 문서는 통합 상세 참고다. B300 native 준비 상태는 지식 수요·source·DB·model·schema 설계의 선행 조건이 아니다.

| 문서 | 내용 |
|---|---|
| [2026-10-21-dse-knowledge-architecture.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/superpowers/specs/2026-10-21-dse-knowledge-architecture.md) | DSE 결정별 지식·source, 시스템 조합, 논리 schema, 전체 write/read와 환류 |
| [2026-10-21-knowledge-architecture-plan.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/superpowers/plans/2026-10-21-knowledge-architecture-plan.md) | 모든 설계 phase에서 전체 흐름의 상세도를 높이는 작업 계획 |
| [infra-and-credential-requirements.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/infra-and-credential-requirements.md) | 구현 전 infra·계정·권한·credential 준비, 지금 필요한 입력과 조건부 항목 |
| [handoff.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/handoff.md) | 현재 범위·우선순위·다음 작업과 의존성 |

## 기존 통합 계약·검증 참고

| 문서 | 내용 |
|---|---|
| [integration-state-map.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/integration-state-map.md) | HAT 네 판정 축, cost/fidelity, Melete receipt/readiness의 정확한 의미 |
| [p1-first-episode.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/episodes/p1-first-episode.md) | 실제 pinned component input/call/artifact와 B300 미지원 경계 |
| [evaluation-oracles.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/evaluation-oracles.md) | 정상·거부·unknown·실행 실패 gold, positive completion, 독립 증거·budget |
| [p0-remediation-report.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/p0-remediation-report.md) | 보완 결과·실제 정적 검증·남은 blocker |
| [handoff.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/handoff.md) | 현재 mode, 다음 task, 승인 범위, 계속할 작업과 완료 판정 |

P1의 실제 작업 순서는 native integration preflight → 그 결과에 따른 cloud/data-plane 구축이다. B200/SmolLM2 dummy/meta probe는 source에서 확인한 구조적 진단 입력이며 B300 성능·전체 hierarchy·수치 정확성 또는 통합 episode의 성공을 뜻하지 않는다.

## 사용자가 정한 요구

- 새 LLM과 timing을 포함한 agent session workload를 HAT plane에서 B300 기준으로 평가하고, 모든 HW 계층과 kernel을 함께 탐색한다.
- HW asset 조합 검토, KG를 스스로 검색하는 schema committee, HATIR fold/unfold·fusion 후보 생성, 실험 분석·다음 실험 제안을 전부 포함한다.
- TTFT·TPOT·throughput·전력 등 여러 성능 지표를 보존·비교한다. 하나의 성능 목표나 가중 점수를 미리 강제하지 않는다.
- 초기 수집 자료는 없다. 수집할 source와 정보, 취득 방법, metadata, 갱신·검증 정책부터 설계한다.
- RAG·graph·추가 저장 형태, 검색 알고리즘, embedding/reranker, cloud infrastructure를 넓게 조사하고 추천 점수 순으로 검토해 조합한다.
- 선호 cloud·region·예산은 미정이다. 사내 Confluence RAG에서 Supabase와 Neo4j를 사용한 경험은 있으나, 이 프로젝트에 해당 계정·데이터·권한이 제공된 것으로 간주하지 않는다.
- 모든 phase는 전체 흐름을 포함한다. 기능별로 끊어 만들지 않고 같은 전체 흐름의 해상도·정밀도·자동화 수준을 점진적으로 높인다.
- 전체 설계·계획 완료 전에는 제품 코드, infrastructure 배포·설정, 유료 자원 생성, 대규모 데이터 수집을 시작하지 않는다.
- Superpowers를 매 phase의 계획·실행·검토에 적용한다. Master/worker 분담, 별도 검토, master 실제 검증을 포함한다.

## 현재 작업 범위

이 디렉터리의 설계 문서·조사표·계획과 비밀 값 없는 설정 계약 예제만 작성한다. 기존 HAT·Melete 저장소는 읽기 전용이다. 공개 공식 문서 조회는 설계를 위한 조사이며 corpus 구축을 시작한 것이 아니다.

## 문서 책임

Root: 전체 설계, 데이터 계약·검색 설계, 점수 통합, phase 계획, 검증 및 결정 기록.

관리형 worker: source catalog, 저장·검색 후보, cloud·운영 후보, parsing·embedding·reranking·평가 후보. 각 worker는 지정된 문서만 작성하고 재위임하지 않는다.

## 먼저 볼 결론

초기 논리 구조는 **managed PostgreSQL 정본 + typed graph 의미 + object/columnar artifacts + exact/lexical/dense/graph 검색**이다. P1은 PG 관계·recursive graph 조회를 기준선으로 두고 Neo4j를 같은 필수 질의의 challenger로 비교한다. [0001-graph-backend-selection.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/adr/0001-graph-backend-selection.md)와 [deployment-profiles.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/deployment-profiles.md)가 graph/network 선택의 단일 기준이다. 기존 사내 계정이나 자료 접근은 가정하지 않는다.

조사 범위는 **source family 40개와 기술·구성·알고리즘 후보 평가 73개**다. 같은 제품을 다른 역할에서 평가한 항목이 있으므로 73개를 모두 설치하거나 독립 제품 73개라는 뜻은 아니다. 추천 점수는 역할별 검토 우선순위이며 실제 DSE 성능 점수가 아니다.

## 주제별 상세 참고

| 순서 | 문서 | 볼 내용 |
|---:|---|---|
| 1 | [recommendation-and-selection.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/recommendation-and-selection.md) | 추천 조합, 검토 순서, 대안·전환 조건 |
| 2 | [2026-10-16-dse-knowledge-system-design.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/superpowers/specs/2026-10-16-dse-knowledge-system-design.md) | 전체 설계와 HAT·Melete 책임 경계 |
| 3 | [scorecards.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/scorecards.md) | 전체 후보 추천 순서·점수·가중치 민감도 |
| 4 | [01-source-catalog.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/research/01-source-catalog.md) | 어디에서 무엇을 어떤 방법으로 수집하고 검증·갱신할지 |
| 5 | [data-contracts.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/data-contracts.md) | source·Claim·asset·kernel·metric·trajectory metadata/schema |
| 6 | [retrieval-and-decision.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/retrieval-and-decision.md) | hybrid 검색, agent 도구, 검증, DSE 탐색 알고리즘 |
| 7 | [2026-10-16-dse-resolution-plan.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/superpowers/plans/2026-10-16-dse-resolution-plan.md) | P0–P5 전체 coverage와 phase acceptance |
| 8 | [phase-work-packages.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/phase-work-packages.md) | P2–P5 세부 작업·파일·입출력·검증 command |
| 9 | [03-cloud-operations.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/research/03-cloud-operations.md) | cloud 비교, 설정 순서, 용량·비용 산식, 복구·운영 |
| 10 | [validation-and-governance.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/validation-and-governance.md) | 추천 운영, gold/eval/ablation, 단계 승격·품질 기준 |
| 11 | [decisions-and-open-inputs.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/decisions-and-open-inputs.md) | 사용자 요구, root 제안, 실행 전 운영 입력, 검토 반영 |
| 12 | [verification-report.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/verification-report.md) | 실제 문서 검증과 한계 |

상세 대안: [02-storage-retrieval.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/research/02-storage-retrieval.md), [04-models-ingestion-evaluation.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/research/04-models-ingestion-evaluation.md). 용어는 [CONTEXT.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/CONTEXT.md)에 있다.

## 설계 이후 구현을 위한 기존 phase 참고

현재 수행할 설계 phase는 [2026-10-21-knowledge-architecture-plan.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/superpowers/plans/2026-10-21-knowledge-architecture-plan.md)를 따른다. 아래 P1–P5는 설계·계획이 완료된 뒤의 구현 범위를 설명하는 기존 참고다.

| Phase | 높아지는 해상도 | 모든 phase에서 유지할 것 |
|---|---|---|
| P0 | 개념→근거→계약→상세 실행 계획 | 전체 요구와 설계·평가·infra 경계 |
| P1 | 작은 실제 end-to-end loop | 신규 모델 등록·수집·검색·모든 HW 계층·kernel·HAT·metric·Melete·다음 제안 |
| P2 | source·vendor·workload·asset breadth | 동일 전체 흐름 + 더 다양한 사례 |
| P3 | 추출·검증·검색·simulation fidelity | 동일 전체 흐름 + calibration·uncertainty·ablation |
| P4 | 제한된 예산 안의 자율성 | 동일 전체 흐름 + agent 제어·취소·실패·반례 처리 |
| P5 | 운영 규모와 지속 갱신 | 동일 전체 흐름 + SLO·복구·삭제·migration·비용 |

P1 이후 작업은 모두 미실행이다. 실제 corpus, cloud 자원, 제품 코드, IaC apply, HAT/Melete runtime은 만들거나 실행하지 않았다. 이전 P0 판정표·JSON Schema·합성 oracle는 상세 근거로 보존한다. 당시 B300 episode binding이 미완료라는 사실은 유지하며, 이를 현재 지식 시스템 architecture 설계의 완료 조건으로 사용하지 않는다.

## 바로 결정하지 않은 항목

기존 Supabase의 실제 project·DB namespace, host의 data/backup 경로와 자원 한도, model ID·인증 연결, private source 범위와 retention은 후속 연결 시 구체화한다. 설정 항목은 [.env.example](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/.env.example)에 제시하며 loader·adapter는 미구현이다. AWS 계정·GPU·API key를 지금 준비하도록 요구하지 않는다. Embedding/검색 모델의 최종 선택은 동일 DSE 질문으로 평가하며 추천 점수를 실측처럼 취급하지 않는다.

전체 설계·계획에 대한 사용자 검토 전에는 구현 단계로 전환하지 않는다. 실행 방식은 지정된 Superpowers + master/worker workflow를 유지한다.
