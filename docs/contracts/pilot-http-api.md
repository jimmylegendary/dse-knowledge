# P1 HTTP API / workflow contract

기준일 2026-10-25. `src/dse_knowledge/app.py`의 Pydantic models와 OpenAPI가 concrete wire schema다. Source, graph, model output은 untrusted data이며 HTML로 실행하지 않는다.

|Scenario|Route|실제 결과|
|---|---|---|
|상태/coverage|GET /api/stats, /api/capabilities|정본 DB counts, source scope, 실제 native 지원 상태|
|수집 자료/인용|GET /api/materials, /api/materials/{id}|actual body chunks, offsets, cited Claim, source revision|
|Hybrid read|POST /api/search {query,category,limit}|lexical/dense/exact/graph RRF, chunk IDs, ranking trace|
|KG 탐색|GET /api/graph?query=&limit=80|source-linked typed entities/edges|
|DSE 판단|POST /api/decisions {kind,question,input}|202 job_id; queued→running→succeeded 또는 failed|
|판단 결과|GET /api/jobs/{id}, /api/decisions/{id}|근거 whitelist, snapshot, gaps, next collection/experiment proposals|
|의견 환류|POST /api/feedback {decision_id,verdict,notes}|PG canonical feedback→Melete observation receipt; incorrect/needs_evidence는 gap 재개방|
|다음 판단|GET /api/experiences?q=; new decision|실제 Melete query 경험을 참고하되 factual authority로 승격하지 않음|
|실험 데이터|POST /api/experiments {name,cohort,method,metrics,context}|user-imported MetricVector, method provenance|
|비교|POST /api/experiments/compare {baseline_id,candidate_id}|동일 cohort/method, 단위 정규화, missing/incompatible 구분, Pareto tradeoff|
|HW 범위 검증|POST /api/validate/hardware {source}|native schema/typed validation; physical feasibility 별도 unknown|

필수 규칙 `input.required_rules`는 검색 top-k 밖에서도 전부 유지한다. P1 LLM review는 이 규칙들을 typed validation 통과로 선언할 수 없다. `value/operator/limit/unit`가 제공된 user-declared arithmetic 규칙만 독립 validator로 평가하며, 13번째 규칙을 포함한 하나라도 실패하면 reject다. 자연어·입력 누락 규칙은 unknown이고 physical feasibility는 검증하지 않는다.

Feedback E2E: cited decision 생성→needs_evidence+구체 부족점 입력→feedback row 저장→Melete receipt 저장→gap 생성→후속 query에서 경험 조회→다음 decision의 snapshot에 경험 사용 범위 기록. Receipt 실패/지연은 pending/unavailable이며 저장 성공으로 꾸미지 않는다.

App DB user는 dse_knowledge_app 전용 role이다. admin DB 환경변수는 runtime override로 수용하지 않는다. Single operator, one HTTP process, one bounded durable decision worker가 P1 지원 범위다.
