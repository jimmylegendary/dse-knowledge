# 다음 AI 작업 지침

## 현재 mode와 범위

DSE 의사결정용 지식 시스템의 architecture·planning과 구현 준비 명세다. 중심은 **DSE 결정 → 필요한 지식 → 수집 내용·source → DB·model 조합 → schema → 전체 write/read algorithm·workflow**다. U01–U12, 모든 phase의 전체 coverage, Metric Vector, provenance와 HAT·Melete 책임 경계를 유지한다. 사용자 요청은 수정 방향의 GitHub 게시와 infra·credential 요구 정리까지이며, 전체 설계·계획 검토 전 제품 구현·설치·서비스 설정·runtime을 시작하지 않는다. [AGENTS.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/AGENTS.md)를 먼저 읽는다.

2026-10-21 확정 환경은 **기존 Supabase 계정 + 현재 Linux host + local artifact storage**, 모델은 **OpenRouter 또는 Codex**다. Interface·env를 설계하며 AWS·GPU·새 API key를 초기 필수 준비물로 요구하지 않는다. 예산·Supabase project·data scope·모델 ID·인증 연결은 아직 미확정이다. 확정되지 않은 항목이 현재 문서 작업을 막지 않는다.

## 읽기 순서

1. [2026-10-21-dse-knowledge-architecture.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/superpowers/specs/2026-10-21-dse-knowledge-architecture.md): 상위 설계와 DSE 결정별 지식·source·저장·검색 흐름.
2. [2026-10-21-knowledge-architecture-plan.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/superpowers/plans/2026-10-21-knowledge-architecture-plan.md): 모든 설계 단계에서 전체 흐름의 상세도를 높이는 D1–D5와 작업 의존성.
3. [infra-and-credential-requirements.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/infra-and-credential-requirements.md): 확정 host/Supabase/provider 조건과 env·후속 준비 요구.
4. [recommendation-and-selection.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/recommendation-and-selection.md), source/model 연구: 후보별 기존 조사와 추천 prior. 현재 host 환경에 맞춰 재평가한다.

Native 통합을 상세 설계할 때 [integration-state-map.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/integration-state-map.md), [p1-first-episode.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/episodes/p1-first-episode.md), [evaluation-oracles.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/evaluation-oracles.md)를 참고한다. 이 문서들을 상위 architecture의 진입점으로 되돌리지 않는다.

## 다음 task

지식 요구를 DSE 결정 질문 단위로 상세화하고 각 요구를 source·schema·write/read 경로와 연결한다. 역할별 DB/model과 조합의 평가 질문·점수·선택/전환 조건을 정리한다. Host·Supabase·모델 provider interface/env, credential scope, 수집·갱신·검색의 상세 알고리즘을 D2–D5에서 구체화한다. 실제 제품 연결과 모델 호출은 아직 수행하지 않는다.

## Blocker가 막는 범위

- Supabase project·namespace·접속 정보 없음: 해당 DB 연결을 막는다. 지식 수요·source·논리 schema·workflow 설계는 계속한다.
- 예산·embedding/reranker backend 미정: 실제 유료 호출·대량 index 생성 범위를 정할 수 없다. CPU/remote 후보와 자원·비용 산식은 계속 설계한다.
- 사내 자료 범위 미정: Confluence 실제 수집을 막는다. 공개 source 수집 계획과 전체 domain 설계는 계속한다.
- B300 asset/native full chain 또는 Melete runtime 미검증: 해당 target의 실험·성능·통합 완료 주장을 막는다. 현재 지식 시스템 architecture 설계의 blocker가 아니다.

## 작업과 보고

Superpowers와 master/worker workflow를 사용한다. 파일 범위를 고정하고 native worker를 재사용하며 재위임하지 않는다. Worker 완료는 원자료·실행 command·결과·commit으로 master가 확인한다. Reviewer는 구현 출력으로 gold를 만들지 않는다.

planned/blocked/verified/complete는 지식 요구·source·조합 선정·schema/workflow·infra 준비·실제 실행의 범위별로 쓴다. D1 초안 게시를 D2–D5 완료·실제 credential 연결·제품 runtime 성공으로 승격하지 않는다. Native 통합 검증을 보고할 때는 문서·adapter·component·episode·target acceptance를 구분한다.

현재 산출물은 어떤 DSE 결정에 어떤 지식이 필요하고, 어디서 확보해 어떻게 저장·조회·사용하는지 전체 시스템 수준에서 설명해야 한다. Credential 값은 chat·public repo·PR·log에 넣지 않고, 실제 연결 시 env 또는 CLI 인증 interface를 사용한다. 원문/실험/Insight가 순환해도 lineage가 같으면 독립 검증 횟수를 늘리지 않는다.
