---
status: proposed
---

# P1은 typed graph 의미를 고정하고 PostgreSQL graph 조회를 기준선으로 둔다

사용자가 요구한 것은 전 영역의 판단 지식·관계·근거를 이용하는 KG이며 특정 graph database의 선배포가 아니다. P1부터 typed nodes/relations, version, source evidence, complete constraint set, ACL, snapshot 의미를 유지하되 **PostgreSQL 관계·recursive 조회를 baseline, Neo4j projection을 같은 질의의 challenger**로 고정한다. 기존 Supabase/Neo4j 운영 경험은 유용한 평가 맥락이지만 필수 배포의 증거는 아니다.

이 결정은 PG 정본과 재생성 가능한 projection이라는 구조를 유지한다. P1의 실제 integration preflight 전에 Neo4j나 다른 별도 graph service를 필수로 provision하지 않는다. 비교 후보 점수의 1–2점 차이를 switch의 근거로 사용하지 않는다.

## 두 backend에 동일하게 요구할 질의

| ID | 질의 | 필수 결과 |
|---|---|---|
| G01 | exact asset/version·parameter 조회 | 동일한 ID·typed value·unit·revision |
| G02 | component에서 SoC/package/tray/rack 전체 containment | 선언된 모든 ancestor, cycle 검출 |
| G03 | ValidationProfile의 전체 required rule 집합 | DSE-R01–R13 모두 반환; R13이 summary 밖이어도 누락 불가 |
| G04 | port/protocol revision 조합 | 호환·불일치·적용 불명과 근거 |
| G05 | source 철회가 영향을 주는 Claim/proposal | 모든 dependency와 상태, 반복 인용 중복 없음 |
| G06 | 과거 decision snapshot 조회 | 현재 graph로 과거 verdict를 덮어쓰지 않음 |
| G07 | 현재 지식으로 같은 설계 재검토 | 새로운 analysis identity와 changed dependencies |
| G08 | ACL revoke 후 graph hop·count·snippet | 권한 없는 존재/metadata가 노출되지 않음 |
| G09 | kernel/ISA/layout/shape applicability | scalar 유사성 대신 typed 조건과 unknown |
| G10 | run metric에서 cost-unit producer/coverage/carry-forward 역추적 | 같은 input/output unit identity와 raw reference |
| G11 | 재유입한 실험/Insight lineage | independent observation count 증가 0 |
| G12 | Melete 경험의 reference와 full predicate | candidate retrieval 이후 DSE 재검증 결과 동일 |

Parity는 같은 canonical snapshot·policy·ACL에서 node/edge/Claim ID **집합과 unknown/denied 이유까지** 같아야 한다. 결과 순서 차이는 정렬 후 비교하고, 누락을 비슷한 자연어 답으로 덮지 않는다. Golden 결과는 validator/episode fixture의 정답 ID에서 고정한다.

## 선택 gate

1. 위 의미·권한·snapshot parity를 모두 통과하는 것이 선행 조건이다.
2. P1 작은 corpus에서는 PG baseline을 유지한다. 확장 필요성은 선언한 P2 규모와 resource envelope에서 평가한다.
3. 초기 graph-query budget 제안은 critical query p95 500ms다. 이 target은 실측이 아니다. PG가 이를 지속적으로 충족하지 못하고 Neo4j가 충족하거나, 동일 budget의 세 번 독립 load trial에서 Neo4j의 p95가 2배 이상 개선되고 운영/TCO가 승인된 cap 안이면 projection 도입을 검토한다.
4. 결과·규모·latency/cost artifact가 없으면 `not_evaluated`이며 Neo4j 승리로 처리하지 않는다. Backend를 바꿔도 canonical Claim/ACL/required rule set은 바꾸지 않는다.

직접 Neo4j를 baseline으로 고정하는 대안은 높은 graph 운영 친숙도나 이미 검증된 질의 요구가 있을 때 가능하지만 현재는 그 도메인 실측이 없다. RDF projection은 ontology/표준 상호운용 요구가 검증될 때 별도 ADR로 평가한다. 이 ADR은 구현 이전 설계 제안이며 실행 승인서가 아니다.
