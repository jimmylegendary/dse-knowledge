# DSE knowledge project 작업 계약

- 현재 mode는 **DSE 의사결정용 지식 시스템 architecture·planning와 구현 준비 입력 수집**이다. 사용자 확정 요구 U01–U12와 모든 phase의 전체 흐름을 유지한다.
- 2026-10-18 사용자 정정에 따라 **DSE 단계별 결정 → 필요한 지식 → 수집 내용·source → DB·model 조합 → schema → write/read algorithm·workflow**를 설계의 중심으로 둔다. 첫 native episode의 상태를 전체 설계의 선행 조건으로 삼지 않는다.
- 2026-10-21 확정 dev 환경은 기존 Supabase 계정과 현재 Linux host, local artifact storage다. AWS를 사용하지 않는다. 모델 provider는 OpenRouter 또는 Codex를 interface·env로 설정하게 설계한다. GPU와 새 credential 발급은 현재 필수가 아니며, Codex CLI 인증과 OpenRouter API key를 같은 credential로 취급하지 않는다.
- 현재 허용 범위는 설계·계획 문서 게시, infra·계정·권한·credential 요구 정의, 조사와 정적 검증이다. 제품 코드·adapter 구현·cloud 설정·설치·HAT/Melete runtime 실행은 아직 승인되지 않았다. 계정 정보나 credential 준비는 그 자체로 유료 자원 생성·구현 승인이 아니다. 이후 사용자의 명시적 범위 변경을 따른다.
- Superpowers를 사용한다. 피드백은 receiving-code-review로 source와 대조하고, 설계·계획은 brainstorming/writing-plans, 완료 보고는 verification-before-completion을 적용한다. 이미 정한 master/worker 방식을 다시 선택하게 하지 않는다.
- Master는 범위·계약·통합·실제 검증을 책임진다. Worker는 지정 파일만 수정하고 재위임하지 않는다. 기존 worker를 재사용하고 별도 reviewer가 원자료·command·결과·commit을 확인한다.
- Native 이름이 비슷해도 의미를 추측하지 않는다. 해석이 갈리는 상태·규칙은 판정표와 expected fixture로 먼저 고정한다. simulation_ready를 buildability 증명으로, Melete receipt를 searchable 상태로, E1 근거를 실측으로 승격하지 않는다.
- Gold는 제품 구현 전에 고정한다. Reviewer가 구현 결과를 expected 값으로 재사용하지 않는다. 변경 시 oracle version·이유·독립 검토를 남긴다.
- `planned`, `blocked`, `verified`, `complete`를 지식 수요·source·조합 선정·schema/workflow·infra 준비·실제 실행의 범위별로 보고한다. 설계 초안, 제품 선정, credential 준비, cloud 연결, runtime 성공을 서로의 완료로 승격하지 않는다. 통합 검증을 보고할 때는 문서 정합성·adapter·component·episode·target acceptance를 구분한다.
- Cloud 입력 부족이 막는 task만 blocked로 둔다. 계약·source·fixture 검토 등 독립 작업을 계속한다. B200 진단을 B300 baseline으로 대체하지 않는다.
- 원문·실험·Insight의 재유입은 lineage를 보존하며 독립 검증 횟수를 자동으로 늘리지 않는다.
- Credential 값은 채팅·public repo·PR·문서·log에 넣지 않는다. 실제 준비에는 선택된 서비스의 scoped role/SSO/OIDC 또는 secret manager를 우선하며, 로컬 비추적 파일을 쓰면 경로·변수명만 보고한다. 기존 사용 가능한 GitHub 인증에 새 PAT를 불필요하게 요구하지 않는다.
- 보고는 한국어로 하며 기술 식별자는 원문을 유지한다. 로컬 파일 링크는 절대 경로와 파일명 라벨을 쓴다. 공개 문서의 repo 링크는 절대 GitHub URL과 파일명 라벨을 사용한다.

상위 설계는 [2026-10-21-dse-knowledge-architecture.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/superpowers/specs/2026-10-21-dse-knowledge-architecture.md), 다음 작업은 [handoff.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/handoff.md), 준비 입력은 [infra-and-credential-requirements.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/infra-and-credential-requirements.md)다. Native 판정 의미는 [integration-state-map.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/integration-state-map.md)를 상세 참고로 사용한다.
