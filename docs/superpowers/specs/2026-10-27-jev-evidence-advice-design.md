# Jev evidence advice 설계

사용자 승인: 2026-10-27 “그방향으로 시스템을 고치고 테스트 다시해봐”. 기존 PostgreSQL graph, contextual retrieval, EmbeddingGemma 2, Qwen3 reranker를 유지하고 Jev의 온라인 판단 보조 효과를 분리해 확인한다. 기존 검토의 Jev advisory 방향을 구현하는 작업이며 Neo4j나 새로운 graph ontology는 범위에 포함하지 않는다.

## 사용자 여정과 범위

HTTP 검색 → 기존 hybrid/contextual/rerank → Jev의 조건부 근거 검토 → 검색 결과와 판단 보조 표시가 실제 provider로 동작한다. 의사결정 job은 실제 최종 LLM evidence에 대한 같은 Jev 검토를 사용하고, Codex 답변·PG snapshot·gap·Melete feedback 흐름을 유지한다. Jev는 citation이나 검증 결과가 아니다.

이번 변경은 하나의 완결 제품 increment다. 종료 gate는 실제 검색과 decision E2E, 기존 회귀 테스트, 실제 Jev calibration 100건과 test 500건, 비교 HTML과 공개 재현 artifact다. P1의 HAT 구조 검증 및 simulator 미연동 상한은 유지한다. 14만 자료 처리량이나 physical feasibility를 보장하지 않는다.

## 판단 역할

생성 LLM은 기존과 같이 추출·설계·답변을 생성한다. Jev는 주어진 excerpt가 질문의 요구를 직접 다루는지 다음 유한 후보 중 하나를 선택한다.

- `direct_support_candidate`: 요청한 사실과 명시 조건을 직접 뒷받침하는 근거 후보가 있다.
- `partial_support`: 일부는 뒷받침하지만 요청의 중요한 부분이 빠진다.
- `condition_mismatch`: 주제는 관련 있지만 발췌문에 version, workload, 수치 의미, dtype/shape 등 요청과 명시적으로 다른 조건이 있다. 조건이 단순히 언급되지 않은 경우는 mismatch로 판정하지 않고 partial_support/no_support/uncertain 중 해당 후보를 쓴다.
- `conflicting_evidence`: 제시된 근거가 요청과 관련해 충돌한다.
- `no_support`: 제시된 excerpt에 요청을 뒷받침하는 근거가 없다.
- `uncertain`: 질문이 모호하거나 제공 context만으로 판별할 수 없다.

이는 excerpt에 한정한 제안이다. `direct_support_candidate`도 전체 corpus의 완전성, 과학적 사실, HW legality, 수치 계산, 실제 성능이나 답변 허가를 뜻하지 않는다. 필수 규칙의 deterministic reject/incomplete와 기존 citation 검증을 완화하지 않는다. Jev 오류는 기존 답변 경로를 막지 않으며 사용 불가 상태를 명시한다.

## Provider와 입력

새 `JevEvidenceAdvisor(settings)`는 기존 shared `decision-model` CLI의 general profile을 사용한다. 기본 CLI는 `/home/jimmy/.local/bin/decision-model`, 설정 override는 `DSE_DECISION_MODEL_CLI`, timeout은 `DSE_JEV_TIMEOUT_SECONDS`(기본 120)다. 모델은 `typesafe/jev-1.13`으로 확인한다. 자동 재시도·모델 fallback·새 credential 복사는 없다. subprocess는 argv, stdin DEVNULL, stderr 미노출, bounded stdout을 사용한다.

공개 인터페이스:

`assess(query: str, evidence: list[dict], *, kind: str = 'knowledge', required_rules: list | None = None) -> dict`

입력에는 질문과 전체 required_rules, 최종 source들의 canonical chunk/revision ID, title·role·scope·원문 excerpt가 들어간다. gold, expected label, 정답 citation, 평가 difficulty/category는 전달하지 않는다. source는 untrusted data다.

서비스가 자동 절단하게 하지 않는다. 호출자가 versioned projection으로 source excerpt를 명시적으로 구성한다. UTF-8 state는 24,000 bytes 이하, 전체 request는 30,000 bytes 이하로 검증한다. 질문과 required_rules는 절단하지 않는다. source별 text excerpt에는 제공 byte 수·원문 byte 수·truncation 여부를 기록한다. 최소 ID/metadata와 질문·규칙도 못 담으면 `skipped_over_budget`이다. 긴 원문 때문에 매 요청을 전부 skip하지 않도록 source별 excerpt 예산을 나누되, 생략 source 및 잘린 내용을 숨기지 않는다. 최대 12개 primary evidence를 검토하며 추가 neighbor/후순위 source의 생략 수를 기록한다. 적합성 판단은 제공된 excerpt 범위에만 한정한다.

API 및 decision은 source의 원문이나 순위를 바꾸지 않는다. one aggregate choice question의 validated probability distribution에서 `direct_support_candidate` 확률을 `support_score`로 노출한다. 이 값은 DSE 정답 확률이 아니며 calibration 전에는 action threshold로 사용하지 않는다. 다른 confidence를 정답 확률로 변환하지 않는다.

## 출력 계약

모든 경로는 다음 envelope를 반환한다.

```json
{
  "schema_version": "jev-evidence-advice/v1",
  "status": "assessed|disabled|unavailable|skipped_over_budget|skipped_prompt_budget",
  "advisory_only": true,
  "choice": "uncertain",
  "support_score": null,
  "score_kind": "uncalibrated_direct_support_probability",
  "policy_version": "jev-evidence-advice/v1",
  "evidence_ids": [],
  "projection": {},
  "metadata": {}
}
```

`assessed`만 실제 provider의 유효한 판단이며 유한한 0..1 support_score를 가진다. unavailable/skip/disabled는 support_score=null로 두고 정상적인 0점과 구분한다. 전체 실행 표본·운영 실패 분모는 유지하되 semantic AUC/AP/threshold 등은 valid-assessed 표본으로만 계산하고 그 조건부 분모를 명시한다. unavailable/skip이 하나라도 있으면 전체 품질 gate PASS를 주장하지 않는다. metadata에는 안전한 error code, 모델, latency/cache/usage 등만 보존한다. provider stderr/raw response/설정 값은 공개하지 않는다. 모델 불일치, 알 수 없는 choice, nonfinite/out-of-range/불완전한 확률, malformed envelope는 unavailable이다. 가능하면 provider request ID를 보존한다.

Owner-only cache는 full query/rules/evidence identity와 source text hash, projection/prompt/model/schema version에 묶인다. 동일 입력은 재사용하고 입력·revision·policy가 바뀌면 재사용하지 않는다. thread-safe atomic replace와 기존 private-path 규칙을 따른다. raw excerpt와 private prompt는 Git에 내보내지 않는다.

## Runtime 연결

- 설정 `DSE_JEV_EVIDENCE_ENABLED` 기본 false. `Settings.load`는 기존 owner-only 파일 규칙으로 `jev.env`도 읽는다.
- `create_app(..., evidence_advisor=None)`에서 주입 가능하다. 활성화했을 때 실제 advisor를 구성한다.
- `SearchBody.evidence_advice`는 `off|jev|null`. null은 설정을 따르고 per-request 변경은 기존 `DSE_RETRIEVAL_ALLOW_MODE_OVERRIDE`가 허용할 때만 가능하다. 활성화되지 않은 jev 요청은 명시적으로 거절한다.
- `/api/search`는 기존 Retriever 결과를 보존하고 top-level `evidence_advice`를 추가한다. off는 disabled envelope다. `/api/capabilities`에 설정과 advisory 상한을 표시한다.
- DecisionEngine에는 optional evidence_advisor를 주입한다. `fit_decision_prompt`가 고른 실제 최종 evidence를 assess하고, `JEV_ADVISORY_ONLY` 블록을 최종 prompt에 붙인다. 추가 블록으로 prompt 전체 한도를 넘으면 source/task/rules를 줄이지 않고 advice만 `skipped_prompt_budget`로 표시한다. Jev가 본 evidence와 실제 LLM evidence가 달라지지 않는다.
- decision result와 snapshot에 advice 및 `consumed_by_generator` 여부를 남긴다. 현재 RESULT_SCHEMA는 생성 응답에 그대로 사용하고 advisory는 runtime이 따로 덧붙인다. citation·deterministic rule·transaction·outbox·Melete 경로는 유지한다.

## 평가와 채택

현재 contextual_rerank 결과는 ranking baseline이다. Jev는 ranking을 바꾸지 않으므로 Hit/MRR 변화는 기대하지 않으며 회귀 여부를 확인한다. 새 score는 `jev_direct_support_proxy`, API request의 `evidence_advice=jev`와 결합한다. 기존 score/threshold는 의미가 다르므로 덮어쓰지 않는다. 모든 journal/threshold identity에 evidence_advice를 넣는다.

100건 calibration → threshold freeze → 동일 policy의 500건 test를 순서대로 실행한다. test 결과로 prompt·score·threshold를 조정하지 않는다. 이전 500건은 공개된 회귀 세트이므로 독립적인 새 일반화 검증이라고 표현하지 않는다. 기존 baseline artifact를 재사용하고 같은 retrieval mode/자료 snapshot/정책을 확인한다. actual LLM answer/action은 500 검색 score에서 추정하지 않는다.

보고: Source/Chunk Hit@k, MRR, evidence-group coverage, score ROC-AUC/AP, supported TPR, OOD/grey/missing FPR, 운영 오류·skip·cache 비율, latency 및 provider usage/cost(제공되는 경우), supported 질문의 불필요한 보류 proxy를 분리한다. ambiguous 질문은 기존 binary denominator 규칙을 유지한다. gate는 기존 TPR ≥ .90, OOD FPR ≤ .10, grey FPR ≤ .20이며 필수 표본 0이면 not_evaluated다. 모든 test case가 유효한 provider 판단이어야 품질 gate PASS를 주장한다.

실제 HTTP/decision E2E에서는 supported와 missing/grey 질문을 실제 모델로 실행해 citation·snapshot·필수 rule precedence·Melete 전달 상태를 확인한다. 이는 전체 500개 생성 답변의 의미 정확도 평가가 아니라고 표시한다. default 활성화는 actual integration과 calibration에서 검토하고 test gate 실패도 숨기지 않는다. 검증된 개선을 주장하지 못해도 기능·사용 가능한 mode와 한계를 정직하게 보고한다.

공개 대상은 코드·case 계약·기존 공개 test/calibration의 참조·본문 제거된 결과·비교 HTML·README다. private source body, owner 설정, API key, 원문 prompt/cache는 공개하지 않는다.
