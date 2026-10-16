# DSE knowledge project 작업 계약

- 현재 mode는 **P0 설계·계약 보완**이다. 사용자 확정 요구 U01–U12와 모든 phase의 전체 흐름을 유지한다.
- 현재 허용 범위는 문서, JSON Schema, 합성 oracle fixture, 조사 자료 정정, 정적 산식·schema·링크 검증이다. 제품 코드·adapter 구현·cloud 설정·설치·HAT/Melete runtime 실행은 아직 승인되지 않았다. 이후 사용자의 명시적 범위 변경을 따른다.
- Superpowers를 사용한다. 피드백은 receiving-code-review로 source와 대조하고, 설계·계획은 brainstorming/writing-plans, 완료 보고는 verification-before-completion을 적용한다. 이미 정한 master/worker 방식을 다시 선택하게 하지 않는다.
- Master는 범위·계약·통합·실제 검증을 책임진다. Worker는 지정 파일만 수정하고 재위임하지 않는다. 기존 worker를 재사용하고 별도 reviewer가 원자료·command·결과·commit을 확인한다.
- Native 이름이 비슷해도 의미를 추측하지 않는다. 해석이 갈리는 상태·규칙은 판정표와 expected fixture로 먼저 고정한다. simulation_ready를 buildability 증명으로, Melete receipt를 searchable 상태로, E1 근거를 실측으로 승격하지 않는다.
- Gold는 제품 구현 전에 고정한다. Reviewer가 구현 결과를 expected 값으로 재사용하지 않는다. 변경 시 oracle version·이유·독립 검토를 남긴다.
- `planned`, `blocked`, `verified`, `complete`를 requirement/evidence lane별로 보고한다. 문서 정합성 PASS, adapter conformance PASS, component probe PASS, integrated episode PASS, B300 acceptance PASS를 분리한다.
- Cloud 입력 부족이 막는 task만 blocked로 둔다. 계약·source·fixture 검토 등 독립 작업을 계속한다. B200 진단을 B300 baseline으로 대체하지 않는다.
- 원문·실험·Insight의 재유입은 lineage를 보존하며 독립 검증 횟수를 자동으로 늘리지 않는다.
- 보고는 한국어로 하며 기술 식별자는 원문을 유지한다. 로컬 파일 링크는 절대 경로와 파일명 라벨을 쓴다. 공개 문서의 repo 링크는 절대 GitHub URL과 파일명 라벨을 사용한다.

다음 작업과 현재 blocker는 [handoff.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/handoff.md), 판정의 단일 기준은 [integration-state-map.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/integration-state-map.md)다.
