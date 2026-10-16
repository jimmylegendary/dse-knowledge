# DSE 지식·실험 시스템 설계 패키지

공개 저장소: [jimmylegendary/dse-knowledge](https://github.com/jimmylegendary/dse-knowledge). 2026-10-17에 설계·계획 패키지를 게시했다. 제품 구현과 cloud 배포는 아직 시작하지 않았다.

문서 내부 링크는 GitHub 공개본을 가리킨다. HAT·Melete 통합 근거의 일부는 별도 접근 권한이 필요한 저장소를 참조하며, 해당 저장소의 코드를 이 저장소에 복사하지 않았다.


상태: **v0.2 P0 판정 계약 보완안 / 제품 구현·runtime·infrastructure 변경 미실행**. 기준일: 2026-10-17 KST. 검토 baseline은 `2a460a0`이다. 지정 source에 B300 target twin과 전체 native chain이 없어 **B300 episode binding과 실행 acceptance는 blocked**다.

## P0 보완부터 읽기

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

이 디렉터리의 설계 문서·조사표·계획만 작성한다. 기존 HAT·Melete 저장소는 읽기 전용이다. 공개 공식 문서 조회는 설계를 위한 조사이며 corpus 구축을 시작한 것이 아니다.

## 문서 책임

Root: 전체 설계, 데이터 계약·검색 설계, 점수 통합, phase 계획, 검증 및 결정 기록.

관리형 worker: source catalog, 저장·검색 후보, cloud·운영 후보, parsing·embedding·reranking·평가 후보. 각 worker는 지정된 문서만 작성하고 재위임하지 않는다.

## 먼저 볼 결론

초기 논리 구조는 **managed PostgreSQL 정본 + typed graph 의미 + object/columnar artifacts + exact/lexical/dense/graph 검색**이다. P1은 PG 관계·recursive graph 조회를 기준선으로 두고 Neo4j를 같은 필수 질의의 challenger로 비교한다. [0001-graph-backend-selection.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/adr/0001-graph-backend-selection.md)와 [deployment-profiles.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/deployment-profiles.md)가 graph/network 선택의 단일 기준이다. 기존 사내 계정이나 자료 접근은 가정하지 않는다.

조사 범위는 **source family 40개와 기술·구성·알고리즘 후보 평가 73개**다. 같은 제품을 다른 역할에서 평가한 항목이 있으므로 73개를 모두 설치하거나 독립 제품 73개라는 뜻은 아니다. 추천 점수는 역할별 검토 우선순위이며 실제 DSE 성능 점수가 아니다.

## 읽기 순서

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

## 전체가 선명해지는 phase

| Phase | 높아지는 해상도 | 모든 phase에서 유지할 것 |
|---|---|---|
| P0 | 개념→근거→계약→상세 실행 계획 | 전체 요구와 설계·평가·infra 경계 |
| P1 | 작은 실제 end-to-end loop | 신규 모델 등록·수집·검색·모든 HW 계층·kernel·HAT·metric·Melete·다음 제안 |
| P2 | source·vendor·workload·asset breadth | 동일 전체 흐름 + 더 다양한 사례 |
| P3 | 추출·검증·검색·simulation fidelity | 동일 전체 흐름 + calibration·uncertainty·ablation |
| P4 | 제한된 예산 안의 자율성 | 동일 전체 흐름 + agent 제어·취소·실패·반례 처리 |
| P5 | 운영 규모와 지속 갱신 | 동일 전체 흐름 + SLO·복구·삭제·migration·비용 |

P1 이후 작업은 모두 미실행이다. 실제 corpus, cloud 자원, 제품 코드, IaC apply, HAT/Melete runtime은 만들거나 실행하지 않았다. P0에서는 pinned source 확인, 판정표·JSON Schema·합성 oracle 작성, 산식·schema·provenance·링크의 정적 검증과 독립 review를 수행한다. B300 target positive가 아직 bound/실행되지 않았으므로 전체 P0 target binding 또는 P1 완료를 주장하지 않는다.

## 바로 결정하지 않은 항목

Cloud account/region·spending cap·HAT/Melete test execution site·private source 접근·retention 최종 기준은 실제 설정 전에 필요하다. 선호가 미정이라는 답을 반영해 지금은 대안과 선택 절차를 제공한다. Embedding/검색 모델의 최종 선택은 계획에 정의된 동일 DSE gold 비교로 확정하며, 추천 점수를 실측처럼 취급하지 않는다.

전체 설계·계획에 대한 사용자 검토 전에는 구현 단계로 전환하지 않는다. 실행 방식은 지정된 Superpowers + master/worker workflow를 유지한다.
