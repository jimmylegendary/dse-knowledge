# 다음 AI 작업 지침

## 현재 mode와 범위

P0 계약 보완이다. U01–U12, 전 phase의 전체 흐름, Metric Vector, PG 정본/projection 분리와 HAT·Melete 책임 경계를 유지한다. 제품 구현·설치·cloud apply·HAT/Melete runtime은 아직 승인되지 않았다. 문서·JSON Schema·합성 oracle와 정적 검증은 허용된다. [AGENTS.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/AGENTS.md)를 먼저 읽는다.

## 읽기 순서

1. [integration-state-map.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/integration-state-map.md): native 값과 DSE 판정 축의 의미.
2. [p1-first-episode.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/episodes/p1-first-episode.md): 실제 pinned component 입력/호출/artifact와 target blocker.
3. [evaluation-oracles.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/evaluation-oracles.md): gold, positive completion, unknown, 독립 증거, budget.
4. [p0-remediation-report.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/p0-remediation-report.md): 실제 검증 결과와 미검증 범위.

## 다음 task

계약·schema·fixture 정합성을 확인하고 B300 target의 누락된 asset/통합 입력을 해결할 **설계·근거**를 준비한다. B200/SmolLM component probe를 B300 baseline으로 바꾸지 않는다. 지정 revision에 없는 native end-to-end 경로를 호출했다고 주장하지 않는다. 새 revision을 사용하려면 변경된 계약·fixture와 증거를 별도로 pin한다.

## Blocker가 막는 범위

- B300 asset/정확한 full chain이 없음: B300 실제 episode acceptance를 막는다. Source·계약·gold·독립 review는 계속할 수 있다.
- Native fixture가 dummy/meta이고 수치 reference가 없음: numeric correctness·장비 성능 주장을 막는다. Capture shape/호출 계약을 읽는 것은 가능하다.
- Cloud account·region·spending cap 미제공: provisioning/유료 실행을 막는다. Local source·문서·schema 작업을 막지 않는다.
- Melete endpoint/runtime 미검증: 실제 ingest/readout PASS를 막는다. Receipt/Condition 타입과 oracle 작성은 가능하다.

## 작업과 보고

Superpowers와 master/worker workflow를 사용한다. 파일 범위를 고정하고 native worker를 재사용하며 재위임하지 않는다. Worker 완료는 원자료·실행 command·결과·commit으로 master가 확인한다. Reviewer는 구현 출력으로 gold를 만들지 않는다.

planned/blocked/verified/complete는 lane별로 쓴다. 문서 정합성, adapter conformance, component probe, integrated episode, B300 target acceptance를 따로 보고한다. Native simulation_ready, 저장 receipt, retrieval 점수, schema PASS를 다음 lane의 완료로 승격하지 않는다.

계약 보완 산출물은 입력·호출·expected 상태와 미지원 부분을 구체적으로 설명해야 한다. **전체 P0의 target episode binding은 B300 입력과 전체 chain이 고정되기 전에는 완료가 아니다.** B300 실행·성능 검증 완료도 실제 target evidence 없이는 주장할 수 없다. 원문/실험/Insight가 순환해도 lineage가 같으면 독립 검증 횟수를 늘리지 않는다.
