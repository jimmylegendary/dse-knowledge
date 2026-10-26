# DSE KG retrieval evaluation: 500 diverse held-out questions

사용자 승인 범위는 평가 질문 약 500개로 확장, 난이도·모호성·OOD·corpus 경계 질문의 분별력 검증, 실제 재실행, test set과 결과의 public GitHub 게시다. 기존 KG·검색 순위 정책을 이 평가 정답에 맞춰 바꾸지 않는다.

## 평가 설계

|세트|질문 수|답변 가능|근거 부족·확인 필요|언어|
|---|---:|---:|---:|---|
|Calibration|100|60|40|KO 50 / EN 50|
|Held-out test|500|300|200|KO 250 / EN 250|

Test의 supported 300개는 clear 75, semantic paraphrase 75, implicit/indirect 75, multi-constraint/reasoning 75로 구성한다. 마지막 tier는 실제 근거가 뒷받침하는 질문만 허용하며, 단순히 어렵게 보이도록 미지원 결론을 요구하지 않는다. 여러 source가 필요한 경우 모든 필수 evidence group을 qrels에 명시한다.

Test의 negative/clarify 200개는 OOD 50, near-boundary 100, in-domain missing fact 30, genuinely underspecified 20으로 구성한다. Near-boundary의 목표 분포는 wrong revision 30, unseen feature 25, missing quantity 20, unsupported cross-source derivation 25다. Calibration은 같은 큰 분포를 1/5로 구성한다. 구체적인 소분류는 source 사실에 맞지 않으면 reviewer 근거로 교체하고 변경을 기록한다.

질문은 source에서 확인한 사실을 바탕으로 새로 작성한다. 최소 100개 test source material과 200개 test intent group을 목표로 하고 실제 수를 보고한다. KO/EN은 단순 번역으로 수만 늘리지 않는다. Intent/group별 집계와 질문별 집계를 함께 보존한다. Calibration/test의 material/intent group은 분리한다. 기존 Q2 질문은 재사용하지 않는다.

## 점수의 의미

1. Source Hit@1/5/10, specified-chunk Hit@1/5/10, MRR@5/10은 supported 질문에 대해서만 계산한다. Raw chunk slot 순위를 유지하고 같은 material을 한 행으로 합치지 않는다. Multi-evidence 질문은 any-hit와 all-required-evidence coverage를 구분한다.
2. RRF/weighted rank는 상대 순위 값이며 정답 확률이 아니다. 현재 API에 calibrated answerability confidence가 없으면 `not_provided`로 남긴다. 높은 관련성은 충분한 답변 근거와 다르다.
3. OOD의 낮은 relevance, grey-zone의 낮은 answer sufficiency, 모호한 질문의 clarification 필요를 별도 평가한다. 관련 자료가 있다는 이유로 grey-zone을 answerable로 바꾸거나, ambiguous 질문의 높은 relevance 자체를 실패로 보지 않는다.
4. 실제 API의 `max_technical_rrf_proxy`에 대해 분포·AUROC·AUPRC·dev-only threshold의 TPR/FPR/TNR을 보고한다. 현재 API가 제공하지 않는 dense similarity를 있는 값처럼 만들지 않는다. 점수·threshold 선택은 calibration으로만 고정하고 test 결과에 맞춰 변경하지 않는다. Calibration의 목표 positive coverage와 test에서 달성한 coverage를 구분한다. Sufficiency 판정 도구가 추가되면 기존 production 점수와 별도 offline advisory로 표시한다.
5. Partial qrels이므로 전체 corpus precision/recall/nDCG를 완전한 ground truth처럼 주장하지 않는다. 생성 Pass@k·committee 정확도·B300 성능은 이번 검색 평가에 포함하지 않는다.

### 고정한 판정·score 계약

- `answerability=supported|insufficient|ambiguous`, `expected_action=answer|qualified_answer|abstain|clarify`로 분리한다. Supported는 질문 전체를 충족해야 한다. 일부만 근거가 있는 grey-zone은 `qualified_answer`로 확인된 부분만 말하고 빠진 사실을 명시하는 것이 정답이다. 이를 full-question sufficient로 세지 않는다. Ambiguous의 정답은 필요한 조건을 확인하는 `clarify`다.
- Evidence group은 전체 AND, 각 group의 대체 chunk는 OR다. Any-hit와 모든 required group 충족을 따로 계산한다. Source alternatives와 필수 evidence를 혼동하지 않는다.
- 실제 API에는 cosine distance나 calibrated confidence가 없다. Primary scalar는 technical `items` 전체의 유한한 `trace.rank_score` 최댓값인 `max_technical_rrf_proxy`다. Empty items는 0, malformed/missing score는 실행 오류이며 0으로 대체하지 않는다. 응답 첫 item이 최고 score라는 가정도 하지 않는다.
- Primary binary positive는 supported, negative는 insufficient다. Ambiguous는 binary에서 제외하고 clarification slice로 따로 보고한다. Calibration에서 positive TPR 0.90 이상을 유지하는 가장 큰 threshold를 고르고 `score>=threshold`와 tie를 보존한다. Test에서는 재선택하지 않는다.
- 진단 목표는 test supported TPR≥0.90, OOD FPR≤0.10, near-boundary FPR≤0.20이다. `in_domain_missing`은 nongated subgroup으로 FPR을 별도 보고한다. 이는 root가 정한 사전 진단 목표이며 배포 안전성 보장이 아니다. 실패도 그대로 결과다. 모든 negative의 prevalence는 설계한 challenge 비율이며 실사용 비율이 아니다. Intent-cluster bootstrap CI와 실제 group 수를 함께 보고한다.
- 각 75건 tier는 d1/d3 KO38·EN37, d2/d4 KO37·EN38이고, calibration 15건 tier는 d1/d3 KO8·EN7, d2/d4 KO7·EN8로 고정하여 전체 균형을 맞춘다. 공개 이후 이 세트는 regression set이며 미래의 blind test로 재사용하지 않는다.

## Truth, freeze, privacy

- Author는 검색 결과를 보지 않고 actual source evidence로 질문·정답·난이도·expected_action을 작성한다. 별도 reviewer가 결과를 보기 전에 검토한다. Negative는 전 세계에 답이 없다는 주장이 아니라 고정 corpus의 지원 범위에 대한 label이다. 검증되지 않은 global absence는 `not_established`로 표시한다.
- Case는 ID, split, language, category, difficulty, intent_group, query, answerability, expected_action, ambiguity/boundary type, supporting evidence groups 또는 nearby evidence, gold rationale, review 상태를 가진다. Missing fact·revision·scope를 구체적으로 적는다. 단순 ID·존재 검사로 semantic 정답을 인증하지 않는다.
- Freeze manifest는 case/qrel hash, corpus material/revision/chunk manifest hash·counts, evaluator·production code hash, embedding/model/policy metadata, rubric, score·threshold policy와 실행 시점을 기록한다. Author/reviewer와 결과 실행의 경계를 보존한다.
- Public 산출물은 새 질문·짧은 paraphrased answer fact·근거 locator/ID/revision·hash·점수·판정·오류·버전이다. 원문 문단·긴 quote·모델 생성 답변·vector·credential·사내 자료를 게시하지 않는다. Evidence text packet과 full response는 owner-only private artifact다.
- 재실행은 Linux host의 기존 HTTP/Supabase/external embedding을 사용한다. 기본 concurrency 2, bounded retry/timeout, resumable event journal. 새 GPU·cloud·모델 weight·production DB schema 변경은 없다. 500개를 임의로 drop하거나 실패를 성공/0점으로 덮지 않는다.

## 완료 기준

500개 test + 별도 100개 calibration의 검토·freeze, 실제 API 실행, supported ranking 및 negative 분별력 보고, 난이도·언어·boundary·intent별 breakdown, 실패 case와 raw-score 한계 공개, 재현 가능한 evaluator와 JSON/JSONL/CSV 결과 및 local HTML report, 독립 리뷰, root 검증, GitHub upload까지 완료한다. 평가 품질이 낮거나 score 분별력이 실패해도 사실대로 게시하며 production의 성공으로 포장하지 않는다.
