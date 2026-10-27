# DSE Knowledge Workbench — 지식·설계 판단·경험 환류

상태: **실제 1,000개 Workbench · LLM 문맥 보강 + Qwen 8B 적용 · Jev 근거 판단 보조 추가, 500건 재평가 품질 gate PASS** · runtime v0.2.6 / retrieval-policy v2.3 / jev-evidence-advice v1 · 기준일: 2026-10-27 KST. 145,748건은 수집 대상 목록이며 전체 본문 분석·KG 등록은 실행하지 않았다. 아래의 기존 Q2 소규모 결과와 500건 결과들을 구분한다.

## Jev 근거 판단 보조 — 500건 재평가 (v0.2.6, 2026-10-27)

검색(문맥 보강 + Qwen 8B reranker)과 순위는 그대로 두고, 검색된 근거가 질문을 **직접 뒷받침하는지** 공용 판단 모델 Jev(`typesafe/jev-1.13`)가 판정하는 보조 신호를 추가했다. 결과는 검색 응답과 hardware/kernel/experiment 판단 snapshot에 `evidence_advice`로 남고, Workbench 검색·판단 화면에 "검토 제안"으로 표시된다. Jev 판단은 인용 검증·필수 규칙 판정·답변 허가를 대체하지 않는다. Jev 호출 실패는 "근거 없음(0점)"이 아니라 별도 상태로 남긴다. Neo4j graph는 검토 후 이번 범위에서 제외했다.

Threshold **0.3**은 calibration 100건에서만 정해 고정했고, test 500건 결과로 prompt·threshold를 바꾸지 않았다. "기존"은 2026-10-26에 같은 500건으로 평가한 문맥 + Qwen 8B 결과다(최대 reranker 점수, threshold 0.981).

| 항목 | 기존: 문맥 + Qwen 8B | Jev 추가 | 목표 |
|---|---:|---:|---:|
| 정상 TPR | 95.7% (287/300) | 91.3% (274/300) | ≥ 90% |
| OOD FPR | 0.0% (0/50) | 0.0% (0/50) | ≤ 10% |
| Grey-zone FPR | 39.0% (39/100) | **11.0% (11/100)** | ≤ 20% |
| In-domain missing FPR | 20.0% (6/30) | **6.7% (2/30)** | — |
| 근거 부족 전체 FPR | 25.0% (45/180) | **7.2% (13/180)** | — |
| Precision | 86.4% | **95.5%** | — |
| AUROC (95% 구간) | 0.931 (0.905–0.954) | **0.977 (0.966–0.987)** | — |
| Average Precision (95% 구간) | 0.945 (0.917–0.970) | **0.987 (0.979–0.992)** | — |
| 모호 20건 중 threshold 이상 | 70% (14/20) | 50% (10/20) | 참고값 |
| 품질 gate | FAIL: grey-zone | **PASS** | 위 3개 목표 |
| Source Hit@5 / Chunk Hit@5 | 99.3% / 95.7% | 99.3% / 95.7% | 순위 불변 |
| Chunk MRR@5 | 0.880 | 0.881 | — |

같은 질문끼리 비교하면 기존 grey-zone 오탐 39건 중 32건을 Jev가 걸러냈고, 기존에 맞던 grey-zone 4건을 새로 오탐했다. 정상 질문은 22건을 새로 놓치고 9건을 새로 찾아 TPR이 4.4%p 낮아졌지만 목표 90% 안이다. 95% 구간은 intent 378개 단위 bootstrap 1,000회이며 source 간 상관은 반영하지 않는다. 같은 공개 test 500건을 다시 쓴 회귀 평가이고 새 blind holdout이 아니다. 모호 질문 수치는 실제 clarify 행동을 평가한 값이 아니며, 500개 생성 답변의 품질도 평가하지 않았다. 지표는 원 journal과 공개 qrels로 별도 재계산해 요약값과 모두 일치함을 확인했다.

같은 질문을 다시 검색하면 315/500건에서 반환 순서가 2026-10-26 기록과 달랐다. Jev는 순위를 바꾸지 않으며(자동 테스트로 확인), 원인은 reranker 점수의 실행 간 변동이다. 공유 item 3,708개 중 3,707개의 점수가 달랐고 중앙값 |Δ|는 0.0004, 최대 0.044다. Hit@k는 같고 Chunk MRR@5만 0.8803 → 0.8808로 바뀌었다. 오늘 점수로 기존 threshold 판정을 다시 내리면 480건 중 1건만 바뀌므로 비교 결론에는 영향이 없다.

**실행 기록.** 최초 test 실행은 500건 중 **88건만 성공**했다. EmbeddingGemma2(DeepInfra)가 잔액 부족으로 HTTP 402를 반환해 411건이 HTTP 503, 1건이 Jev 호출 실패로 끝났다. 충전 후 같은 정책으로 실패한 412건만 다시 실행해 **412/412 성공**했다. 최초 실패 기록과 재실행 journal을 hash로 연결해 함께 공개한다. 따라서 최초 실행 gate는 FAIL, 최종 유효 점수의 품질 gate는 PASS로 따로 표시한다. Calibration도 HTTP 503 1건만 재실행해 100/100을 채웠다.

| 운영 항목 | 값 |
|---|---:|
| Jev 호출 (test / calibration) | 500 / 98회 (calibration 2건은 cache) |
| Jev 입력 token (test) | 4,226,751 |
| 응답에 보고된 Jev 비용 (test / calibration) | $0.178 / $0.035 (비용 미보고 1회) |
| Jev 지연 p50 / p95 | 480 ms / 680 ms |
| 검색 HTTP 전체 지연 p50 / p95 | 9.6 s / 18.2 s (최초 실행의 성공 88건 기준) |

**실제 연동.** HTTP·Supabase·Codex CLI·HAT schema·Melete 경로에서 **17/18 통과**했다. hardware·kernel·experiment 판단 3건 모두 Jev 판단이 생성기에 전달되고 snapshot과 결과에 같은 값으로 남았다. hardware 판단은 필수 규칙 위반으로 거절(`constraint_rejected`)되어, 규칙 판정이 Jev보다 우선함을 확인했다. 실패 1건: 새 피드백은 저장과 별도 조회에 성공했지만, 일반적인 후속 실험 질문에서 상위 경험으로 선택되지 않았다. 이 실패는 판정을 바꾸지 않고 그대로 기록했다. HAT는 구조 검증이며 B300 simulation·실측은 범위 밖이다.

공개 파일: [jev-evaluation-2026-10-27.html](https://github.com/jimmylegendary/dse-knowledge/blob/main/web/reports/jev-evaluation-2026-10-27.html)(실행 중인 Workbench의 **Jev 근거 판단 평가** 메뉴에서도 열림), [jev-index-2026-10-27.json](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/results/jev-index-2026-10-27.json)(파일 hash 목록), [jev-test-summary.json](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/results/jev-test-summary.json), [jev-test.jsonl.gz](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/results/jev-test.jsonl.gz), [jev-test-initial.jsonl.gz](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/results/jev-test-initial.jsonl.gz)(최초 실패 포함), [jev-operations-2026-10-27.json](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/results/jev-operations-2026-10-27.json), [jev-integration-2026-10-27.json](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/results/jev-integration-2026-10-27.json), [jev-frozen-policy.json](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/results/jev-frozen-policy.json). 설계·계획: [2026-10-27-jev-evidence-advice-design.md](https://github.com/jimmylegendary/dse-knowledge/blob/main/docs/superpowers/specs/2026-10-27-jev-evidence-advice-design.md), [2026-10-27-jev-evidence-advice.md](https://github.com/jimmylegendary/dse-knowledge/blob/main/docs/superpowers/plans/2026-10-27-jev-evidence-advice.md). 원문 본문·생성 문맥·벡터·credential은 포함하지 않는다.

이 README는 DSE 결정별 지식 요구를 만들고, 허가된 source에서 evidence를 취득·구조화하며, hardware/kernel/experiment 결정에 쓰고 부족한 지식을 다시 수집하는 전체 구조를 설명한다. 2026-10-18 사용자 정정에 맞춘 상위 기준은 [2026-10-21-dse-knowledge-architecture.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/superpowers/specs/2026-10-21-dse-knowledge-architecture.md)와 [2026-10-21-knowledge-architecture-plan.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/superpowers/plans/2026-10-21-knowledge-architecture-plan.md)다. 이전 HAT native episode/adapter 계약은 세부 참고이며 이 architecture의 중심 gate가 아니다.

## 고정 500건 검색 평가 — 문맥 보강·Qwen reranker 비교

동일한 질문과 정답으로 baseline/contextual-only/Qwen 8B/combined를 각각 test 500건과 별도 calibration 100건에서 평가했다. Qwen 4B/8B 선택에도 calibration만 사용했다. 모든 근거 그룹 Hit@5 → Chunk MRR@5 → 낮은 grey-zone FPR 순으로 **8B를 선택**했고, 네 구성의 calibration으로 기본 구성을 **문맥 보강 + Qwen 8B**로 정한 뒤 test를 열었다. Test 결과로 질문·정답·prompt·ranking·threshold를 바꾸지 않았다.

| 항목 | Baseline | LLM 문맥 보강 | Qwen 8B | 문맥 + Qwen 8B |
|---|---:|---:|---:|---:|
| Source Hit@5 | 95.0% | 98.0% | 97.7% | **99.3%** |
| Chunk Hit@5 | 66.7% | 76.3% | 93.7% | **95.7%** |
| Chunk MRR@5 | 0.533 | 0.624 | 0.859 | **0.880** |
| 모든 chunk 근거 그룹 Hit@5 | 63.3% | 73.0% | 89.3% | **90.3%** |
| AUROC | 0.693 | 0.681 | 0.922 | **0.931** |
| Average Precision | 0.765 | 0.743 | **0.947** | 0.945 |
| 정상 TPR | 83.7% | 88.0% | 94.3% | **95.7%** |
| OOD FPR | 16.0% | 12.0% | **0.0%** | **0.0%** |
| Grey-zone FPR | 71.0% | 83.0% | 40.0% | **39.0%** |
| In-domain missing FPR | 63.3% | 73.3% | 26.7% | **20.0%** |
| 진단 gate | FAIL | FAIL | FAIL | **FAIL: grey-zone 목표 20% 초과** |

각 test는 **500/500 성공·오류 0**, calibration도 구성마다 100/100 성공했다. 별도 4B calibration 100건까지 유효 case 실행은 2,500건이다. 이는 같은 500개 test 질문을 네 번 평가한 결과이며 2,000개의 독립 질문 표본은 아니다. Hit·MRR은 지원 가능한 300건의 items stream, binary 분별력은 모호 20건을 제외한 480건, OOD 50건·grey-zone 100건·in-domain missing 30건을 기준으로 한다. Source relevance와 질문 전체의 답변 가능성을 구분해야 한다. 문맥만 추가하면 검색은 개선돼도 grey-zone 분별력은 나빠질 수 있다.

LLM Contextual Retrieval의 전체 eligible 인덱스 **999개 자료·18,512개 chunk**를 구축했다. 정본 1,000개·18,518개 중 `out_of_scope` 1개·6 chunks는 검색 인덱스에서 제외한다. Whole document와 각 chunk로 만든 짧은 문맥을 원문에 붙여 embedding 및 실제 FTS5 BM25를 구성한다. 문맥은 검색 힌트이며, PostgreSQL 원문·Claim·인용을 대체하지 않는다. 기본 구성은 실제 검색 UI뿐 아니라 hardware/kernel/experiment 판단의 공통 retriever에도 적용했다.

실제 HTTP·Supabase·Codex CLI·HAT schema·Melete 연동은 rerank-only와 combined에서 각각 **18/18 통과**했다. 첫 rerank-only 검증의 Codex 360초 timeout은 보존하고, 완료한 판단 두 건을 재사용하며 실패한 호출만 600초로 재시도했다. 서비스 재시작 후 corpus·index pointer·판단 snapshot 3건의 hash가 같고 Codex 재호출은 0건이었다. 자동 테스트 **581 passed**, 기존 warning 1개이며 report 전용 5개와 실제 contextual 500건의 재계산·잘못된 index receipt 거부도 별도 확인했다. [실제 연동 기록](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/results/integration-2026-10-26.json), [재시작 검증](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/results/service-restart-2026-10-26.json). HAT는 구조검증이며 native committee/B300 simulation·실측·compiled kernel correctness는 이 실행 범위 밖이다.

인덱스 구축과 서비스는 같은 SQLite 엔진을 사용한다. 실제 개발/서비스 Python의 SQLite 3.50.4/3.54.0 차이로 FTS 무결성 오류가 발생한 것을 최소 재현하고, 서비스 엔진에서 FTS만 재구성했다. 원문 binding·생성 문맥·vector·FTS content digest를 보존했으며 복구 시 LLM/embedding 재호출은 0이다. 이후 engine version을 generation ID·manifest에 포함하고, 다른 engine의 인덱스를 reader가 거부한다. [구축 기록](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/results/context-index-build.json), [호환성·복구 기록](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/results/fts-compatibility-recovery.json)을 공개했다. Generation에 기록된 추정 비용 약 $5.23은 실패·진단·다른 profile·평가·Codex·infra·전체 청구서를 제외한 범위다.

Standalone HTML: [retrieval-evaluation-2026-10-26.html](https://github.com/jimmylegendary/dse-knowledge/blob/main/web/reports/retrieval-evaluation-2026-10-26.html). 실행 중인 Workbench의 **500건 검색 평가** 메뉴에서도 열 수 있다. 질문별 검색 순위·정답·FP/FN, 난이도·언어·경계 유형을 필터로 검토한다.

### Baseline 세부 결과와 평가 범위

test **500건(정상 300 · 근거 부족 180 · 모호 20)**과 별도 calibration **100건**을 원문 검토 후 고정했다. test는 한국어 250/영어 250, 정상 질문은 난이도 4개×75건이다. 모델·threshold 선택에는 calibration만 사용한다. 모든 실제 검색 호출 **600/600 HTTP 성공, 오류 0**이며, 실행 성공과 품질 진단 gate는 구분한다.

| 측정 항목 | Baseline 결과 | 분모·의미 |
|---|---:|---|
| Source Hit@1 / Hit@5 | **87.0% / 95.0%** | 정상 300건, items stream, 지정한 근거 중 하나 |
| Chunk Hit@1 / Hit@5 | **43.3% / 66.7%** | 원문 근거 chunk를 정확히 찾았는지 |
| Chunk MRR@5 | **0.533** | 첫 지정 chunk의 reciprocal rank 평균 |
| 모든 chunk 근거 그룹 Hit@5 | **63.3%** | 질문에 필요한 AND 그룹 모두 충족 |
| AUROC / Average Precision | **0.693 / 0.765** | 정상 300 + 근거 부족 180; 모호 20건 제외 |
| 고정 threshold에서 정상 TPR | **83.7% (251/300)** | calibration에서 TPR≥90%로 정한 RRF proxy threshold |
| OOD / Grey-zone FPR | **16.0% (8/50) / 71.0% (71/100)** | 근거 부족인데 threshold 이상인 질문 비율 |
| In-domain missing FPR | **63.3% (19/30)** | 같은 분야지만 필요한 자료가 없는 질문 |
| 사전 진단 gate | **FAIL: 3개 목표 모두 미달** | 보고 가능한 실험 결과이며 실행 실패가 아님 |

Source relevance만으로 전체 질문의 답변 가능성을 판단하기 어렵다는 결과다. Score는 확률이 아니며 실제 답변·abstention 정책, HAT committee/B300 simulation을 평가하지 않았다. qrels는 지정한 근거 일부이며 완전한 corpus relevance 판정이 아니다. intent 398개·관련 material 120개의 상관관계를 고려해 intent-cluster bootstrap을 기록한다.

공개 파일: [test 500건](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/test-v1.jsonl), [calibration 100건](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/calibration-v1.jsonl), [protocol](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/protocol-v1.json), [freeze](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/freeze-v1.json), [결과·metadata journal](https://github.com/jimmylegendary/dse-knowledge/tree/main/research/eval500/results), [재현 안내](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/README.md). 원문 본문·생성 문맥·벡터·credential은 포함하지 않는다.

## 기존 Q2 — 실제 1,000개 전체 제품, v0.2.5

Linux HTTP UI·기존 Supabase PostgreSQL·host Codex CLI `gpt-6.1-sol/max`·외부 `google/embeddinggemma-2`를 연결한 실제 제품이다. 원문 취득 → chunk/vector/FTS/KG → 출처 검색 → 하드웨어·커널 검토/실험 제안 → 판단 snapshot → feedback·Melete 조회를 실제 의존성으로 확인했다. UI에서도 질문을 직접 제출해 모델 응답과 이력의 원문 인용 링크까지 확인했다.

| 항목 | 실제 결과 | 해석 범위 |
|---|---|---|
| 자료 | **1,000개 = 기존 100개 보존 + 신규 900개**, 9개 분야·28개 source family | fulltext 50,118,994자·18,518 chunks/768차원 vectors; 145,748개 전체 실행은 아님 |
| 처리 상태 | 구조화 추출 완료 **960**, 참고 **16**, 검토 필요 **23**, 추출 실패 **1** | indexed inventory와 KG 완료를 구분하며, 실패를 성공으로 바꾸지 않음 |
| KG 완료 gate | 전체 기술 역할 자료 **960/984 = 97.56%**, 기준 90% 통과 | Claim 없는 자료와 failed도 분모에 포함; 문서 전체 사실을 빠짐없이 추출했다는 뜻은 아님 |
| Claim·문맥 | Claim **2,383**, annotation **2,374행** / annotation을 가진 distinct current Claim **2,373개** | parameters 2,048·conditions 2,711; annotation version 증가를 독립 검증 증가로 세지 않음 |
| 단위·범위 | normalized 245 · not_numeric 3,836 · unit_unspecified 300 · unresolved 378 | 원문 값·조건·revision을 보존하며 미확인 단위를 추정하지 않음 |
| Graph | **4,452 nodes · 4,506 edges**, 최대 component 635 sources | assertion 2,383 + topic 2,123; 주제 연결은 호환성·인과성·물리 검증이 아님 |
| 원자료 검사 | raw artifact hash **1,000/1,000**, source/revision/chunk 집합·literal 감사 오류 **0** | 평가·feedback 후에도 1,000 material/revision과 기존 Claim/annotation의 변경·누락 0 |
| 현재 검색 | `retrieval-policy/v2.2`: dense exact top40 + lexical/exact/graph fusion + 역할 상한 | 같은 read-only repeatable-read scope에서 count/거리순위 계산; 50,000 chunks 초과 시 embedding 전에 typed 503, ANN fallback 없음 |
| 기존 공개 30개 회귀 | 정상 source Hit@5: 자료 탐색 **24/24**, 기술 근거 **23/24**, 오류 0 | 기존 navigation qrel 1건을 기술 근거로 승격하지 않고 분모에 유지 |
| 기존 Q1 한·영 28개 회귀 | 정상 source Hit@1·Hit@5: 두 stream 모두 **24/24**, 오류 0 | 1,000 확장 직후 20/24였던 첫 결과와 수정 과정을 보존 |
| 결과 독립 새 28개 질의 | 정상 source Hit@1 **23/24**, Hit@5 **24/24**, 지정 chunk Hit@5 **16/24**; 두 stream 동일 | source KO 12/12·EN 12/12, 지정 chunk KO 9/12·EN 7/12; 정상 12개 intent의 상관된 번역쌍 |
| 새 검색 시간 | 28개 순차 질의 p50 **2.31s**·p95 **3.02s**; HTTP 6건 p50 **2.29s**·p95 **2.79s** | 작은 순차 표본이며 생산 용량·latency SLA가 아님 |
| 실제 모델 시험 | 정답·expected ID 없이 `knowledge/input={}` 3건 성공; AI 원문 대조 **정상 2·적절한 unknown 1** | 36개 근거 occurrence/35개 current chunk와 인용 ID를 재검사. 사람·과학 검증 0 |
| 전체 HTTP 흐름 | 실제 Supabase·Codex·embedding·HAT schema·Melete **18/18 통과** | HAT는 구조검증; native committee/runtime simulation·B300 실측·compiled kernel correctness는 미실행 |
| UI·재시작 | desktop 1440 / mobile 요청 375(실제 376)에서 검색·판단 이력 수평 overflow **0**; UI 실제 모델 job 완료·원문 링크 **11개** | 재시작 후 판단 7건·feedback hash 동일, Melete feedback 재검색, 새 provider invocation 0 |
| 자동 검사·백업 | `pytest` **458 passed**, 기존 warning 1; allow-list **18개 table**의 logical gzip/SQLite serialization·row count·integrity smoke 통과 | 원문 파일·Melete store·PG DDL/role·전체 PG restore/off-host 복구는 이 백업 검사 범위 밖 |

새 질의는 최종 corpus·검색 코드·정책 hash를 먼저 고정한 뒤, 신규 900개 중 사전 제외집합과 겹치지 않는 자료에서 원문만 보고 작성했다. 14개 anchor의 revision/chunk/인용을 별도 검사하고 정상 12쌍·미지원 2쌍을 고정했다. 실제 모델 3건을 모두 마친 뒤 새 검색 결과를 열었고, 결과로 질문·정책·모델·prompt·통과 기준을 조정하지 않았다. **같은 corpus의 fresh-query 평가이며 new-document holdout이나 모든 agent의 절대적 source blindness를 주장하지 않는다.** 사용한 질문은 이제 회귀 자료다.

모델 답변의 AI 원문 대조 판정과 Jev 보조 판정은 구분한다. Jev의 2개 batch/6개 per-case choice는 모두 `correct_unknown`이었고, 명시적인 current-source 근거가 있는 정상 2건에서 원문 대조와 불일치했다. 원문 근거를 우선했으며 Jev가 정상 응답을 확인했다고 보고하지 않는다. Reviewer는 답변·gold·rubric 고정 후 일부 probe trace를 열람했으므로 rank-blind 검토도 주장하지 않는다. 새 28개 raw 검색 결과는 reviewer가 열지 않았다.

| 운영·사용량 | 실제 관측 | 상한·누락 |
|---|---|---|
| 수집 작업 시간창 | 신규 900개에 약 **15시간 12분**, 중단·보완 포함 약 **59.2개/시간** | 순수 엔진 throughput 또는 생산 SLA가 아님 |
| 공간 | 수집 artifact 추가 약 **1.80GB**, 관측 PG database **410,867,379 bytes**, disk free 약 **61.1GB** | PG 수치는 전체 database이며 Supabase commercial plan/quota·청구서는 미확인 |
| Host 제어 | 수집 전체 worker 최대 4·acquire 1·index 2, 서비스 CPU 200%·MemoryMax 4GiB·TasksMax 256 | 현재 app service lifetime peak 약 **340MiB**; 과거 collector 전체 peak를 이 값으로 대체하지 않음 |
| 최종 시간창의 기록된 Codex 토큰 | 입력 **20,489,106**·출력 **5,164,671**·캐시 입력 **11,832,576** | 캐시는 입력의 부분집합; 일부 실패 응답의 사용량 미상 22건 |
| Embedding·role 판단 | DeepInfra 입력 **14,870,244 tokens**, decision_models 입력 **3,162,317 tokens** | embedding prompt/total은 같은 값; 미상 embedding 응답 8건, provider별 tokenizer를 합산하지 않음 |
| 호출·비용 | PG 기록 8,870행 중 stage receipt 4,066행 제외; provider operation 4,804행·관측 응답 하한 4,928 | wrapper attempt·operation·HTTP/모델 응답은 다름. source_role의 보고된 부분 비용 $0.132817314만 있으며 전체 지출은 미확인 |

사용량 시간창은 batch 생성부터 `2026-10-26T00:36:39Z`까지의 모든 purpose를 포함하며 row별 batch 귀속을 증명하지 않는다. 개발 agent 사용량·외부 Jev QA·별도 직접 embedding 진단과 전체 infra/provider 청구서는 포함하지 않는다. Missing usage/cost를 0이나 무료로 바꾸지 않았다.

공개 자료는 본문·인용·vector·생성 답변·credential을 제외한 metadata projection이다: [1,000개 자료 목록](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/pilot1000/corpus-2026-10-26.json), [전체 수치와 검증 범위](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/pilot1000/quality-v2-2026-10-26.json), [새 한·영 질의와 검색 결과](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/pilot1000/retrieval-paired-2026-10-26.json). Literal quote는 hash로 대체했다. 평가 기준 code commit은 `4a29d7f57e4cd599401fbcaec91104663bd761b8`이며 이후 변경은 보고용 문서·metadata다.

**현재 50,000-chunk exact scan 상한을 14만 개 자료에 대한 지원으로 확대 해석하지 않는다.** 더 큰 corpus의 ANN은 exact 기준 대비 recall·비용·latency를 별도로 검증해야 한다. 아래 Q1/v0.1 수치는 당시 기록으로 유지한다.

## 과거 Q1 기록 — v0.2, 실제 100개 전체 제품

이 절은 100개 단계에서 검증한 당시 결과다. 현재 규모와 검색 정책은 위 Q2 표를 기준으로 한다.

기존 Linux HTTP UI·Supabase·host Codex CLI·외부 `google/embeddinggemma-2`를 그대로 사용한다. 원문/embedding/기존 Claim을 다시 생성하지 않고 source 역할, source-grounded 값·조건, topic 연결과 검색을 보완했다. 기존 회귀·새 holdout·실제 모델 판단·전체 연결 및 snapshot 저장을 확인했다.

| 항목 | 현재 실제 결과 | 보장과 상한 |
|---|---|---|
| 원자료 보존 | 100 materials · 1,912 chunks · 기존 Claim 101개 전체 필드 보존 | artifact hash·chunk span·인용 연결 검사; 새 과학 검증 횟수는 0 |
| 역할별 사용 | core 35 · method 29 · operations 30 · navigation 5 · out-of-scope 1을 정본에 반영 | operations의 설계 사용은 workflow/interface, navigation은 locator, 미분류는 검토 필요 |
| 조건과 값 | 기술 역할 94개 자료 중 89개에 annotation 91개; parameters 89 · conditions 116 | literal/revision/단위 표기 확인; 5개 자료는 `needs_review`, metric과 값의 의미 연결은 독립 검증 전 |
| 단위 정규화 | 3 normalized · 165 not_numeric · 11 unit_unspecified · 26 unresolved | 알려진 단위만 변환; 문자 값·불명 단위를 숫자나 확정 단위로 추정하지 않음 |
| KG | 226 nodes · 197 edges = assertion 101 + topic 96 | `mentions`는 인용에 나타난 공통 주제이며 compatibility/causality 증명이 아님 |
| 연결성 | components 97→60 · 최대 component 4→65 nodes/26 sources · 여러 source component 3→8 | source 연결 증가 자체를 답변 정확도나 물리 검증으로 해석하지 않음 |
| 검색 | `retrieval-policy/v2.1`: dense로 source를 선택하고 해당 source의 hybrid passage를 우선 | typed `source_results`는 UI 자료 탐색, `items`는 LLM 근거, 모든 locator의 authority는 0 |
| 공개 회귀 30개 | 정상 24개 source Hit@1 **23/24**, Hit@5 **24/24**, 지정 chunk Hit@5 **17/24**, 요청 오류 0 | v0.1은 16/24·24/24·14/24. 같은 k개의 chunk slot; 부분 qrels이며 정밀도/전체 recall은 아님 |
| 기술 근거 전용 회귀 | `hybrid_evidence`: source Hit@1 22/24 · Hit@5 23/24 · chunk Hit@5 16/24 | 기존 qrel의 navigation 1건도 분모에 유지하되 기술 근거에서 제외한 결과를 별도로 표시 |
| 새 한·영 번역쌍 | 정상 12쌍의 source Hit@1·Hit@5 **24/24**, chunk Hit@5 **23/24**, 요청 오류 0 | 한국어/영어 source 각각 12/12, chunk는 11/12·12/12; 결과 독립으로 만든 작은 부분 정답셋 |
| 검색 시간 | 공개 회귀 실제 30건 p50 9.62s · p95 23.08s; HTTP 6건 p50 6.69s · p95 15.53s | 작은 순차 표본이며 provider 지연/동시 job 영향 포함; latency 개선·용량 보장으로 주장하지 않음 |
| 전체 실행 | 실제 Supabase·Codex·embedding·HAT schema·Melete의 HTTP E2E **18/18** | HAT는 구조검증만; native committee/runtime/B300 실측 및 kernel correctness는 미연결 |
| 최종 정책 모델 probe | 공통 `kind=knowledge`, `input={}`로 실제 3건 성공: 정상 2건 `evidence_supported`, 미지원 1건 `insufficient_evidence` | expected label·evaluator case ID를 생성 모델에 보내지 않음; Jev 보조 검토도 faithful 2·correct unknown 1, human/scientific 검증 0 |
| 자동·데이터 검증 | `pytest -q` **345 passed**, warning 1; canonical 원문/Claim/context/graph/vector 감사 오류 **0** | actual dependency E2E와 offline tests를 별도로 유지 |
| UI | 실제 자료 탐색 12개 결과/4개 locator, desktop 1440 및 mobile 요청 375에서 수평 overflow 0 | 긴 proof ID를 자르지 않고 줄바꿈; 한 실제 검색 시나리오의 화면 확인 |
| 판단 기록 | 재시작 후 실제 새 판단의 12개 근거와 11개 primary trace 저장, 제외 후보 1개도 구분 | trace는 감사 snapshot에만 저장; 생성 모델 입력은 유지. 기존 trace 없는 기록을 사후 추정해 덮어쓰지 않음 |
| 확장 실행 | durable batch/lease·heartbeat·fencing·재개·provider 실패 정지, 5,000개 후보 고정, 실제 supervisor worker 3개 | 기존 100개 포함 target 1,000; 가져오기 1·index 2·generation 최대 4, host reserve 10 GiB·추가 artifact budget 4 GiB. Q2 완료를 뜻하지 않음 |

공개 회귀의 최초 v2는 source Hit@5 22/24로 실패했다. 기존 hybrid 채널 순위가 의미상 적절한 source를 밀어내고 locator를 별도 분리한 결과를 평가에서 누락한 것을 확인했다. source 선택과 source 내 passage 선택을 구분하고, 실제 UI 검색과 기술근거 스트림을 나눠 위 결과를 얻었다. 이 정책과 새 한·영 14개 번역쌍(정상 12쌍·미지원 2쌍)을 먼저 고정했으며, 새 결과로 정책을 튜닝하지 않는다. Graph 유무만 바꾼 통제 실험이 아니므로 개선을 graph의 단독 효과로 주장하지 않는다.

1,000개 단계는 **기존 100개 포함** 실제 ingested fulltext 1,000개와 기술 역할 자료의 grounded Claim/annotation coverage 90% 이상을 목표로 한다. KG coverage의 분모는 Claim이 없는 자료도 포함한 전체 기술 역할 자료이며, Claim 자료만을 분모로 한 조건부 annotation 비율은 별도 표시한다. 빈 분모는 `null`이다. 정상·미지원 판단, HAT 구조검증, metric 비교, Melete 환류, 재개와 같은 전체 제품 경로를 다시 확인해야 종료한다. metadata 1,000개나 provider 실패를 성공으로 세지 않는다. 145,748개 전체 실행은 이 작업 범위가 아니다.

공개 재현 자료: [quality-v2-2026-10-25.json](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/pilot100/quality-v2-2026-10-25.json), [retrieval-paired-2026-10-25.json](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/pilot100/retrieval-paired-2026-10-25.json). 새 질문셋도 결과를 공개한 이후에는 regression이며 다시 blind holdout으로 사용하지 않는다. 본문 quote는 hash로 대체했고 모델 답변·vector·private 설정은 게시하지 않는다.

## 기존 v0.1 P1 기록 — 100개 자료로 전체 경로를 확인

이 절부터 다음 실행/설정 절 전까지의 P1·평가 수치는 `f2e113c` 시점의 기록이다. v0.2의 현재 역할·graph·검색 결과는 위 표를 기준으로 한다.

Linux host에서 HTTP UI와 CLI를 실행하고 기존 Supabase project에 정본·검색·KG·job을 보존한다. 공개 원문 100개를 확보해 **1,912 chunks / 768차원 실제 embedding**을 저장했다. **99개 자료에서 Claim 101개·Entity 198개·Edge 101개**를 생성했다. 목차로 구성된 1개 자료는 검색 가능한 reference로 남기고 Claim을 만들지 않았다. Claim은 발췌에서 원문 인용과 절대 offset을 검증한 `source_assertion`이다. 원문 전체의 과학적 타당성을 검증한 결과는 아니다.

```mermaid
flowchart LR
  S[100 source materials] --> I[Fetch · parse · revision/hash]
  I --> C[Chunks + exact citation spans]
  C --> E[DeepInfra embeddinggemma-2]
  C --> L[Host Codex CLI]
  E --> P[("Supabase PostgreSQL<br/>pgvector · FTS · claims · graph")]
  L --> P
  U[HTTP UI / CLI] --> R[Hybrid retrieval + RRF]
  R <--> P
  R --> D[Hardware · kernel · experiment review]
  D --> Q[Evidence / unknown / gaps / proposals]
  Q --> P
  Q --> O[Transactional outbox]
  O --> M[Native Melete trace / feedback memory]
  M --> D
  U --> V[Native HAT schema validation]
  V --> Q
```

| 기능 | 실제 P1 경로 | 결과의 상한 |
|---|---|---|
| Insert | `sample → acquire → index → extract` CLI, 9개 분야 quota, 공개 원문·hash·revision·offset | 접근 실패·abstract-only는 전문 자료로 포함하지 않음; extraction은 기본 4개 분산 발췌(각 900자), 기본 1 claim/자료; 설정 상한 8개·각 1,400자·3 claims |
| Read | UI 자료 목록·상세·인용, lexical + dense + exact + source-linked graph의 RRF | ranking은 근거 탐색이며 물리적 가능성의 증명이 아님 |
| KG | PG의 Claim·Entity·Edge와 원문 연결, graph UI | P1 entity는 `concept` 분류; 관계/Claim kind와 source scope 보존. 정교한 HW ontology는 후속 해상도 |
| DSE 판단 | 실제 Codex job, hardware/kernel/experiment 질문, citation whitelist, snapshot·gap·다음 제안 | 설계·kernel 제안은 실행·정확성·성능 검증 전 |
| 필수 규칙 | 검색 top-k와 독립적인 전체 arithmetic rule 검사 | 제공된 숫자·단위의 연산만 검사; authority·physical feasibility는 미검증 |
| 실험 | MetricVector 입력, 단위 정규화·cohort/method 검사·Pareto 비교 | 사용자 입력값 비교; HAT 성능 실행이나 B300 실측을 생성하지 않음 |
| HAT | host의 실제 `hat-schema` 구조 검증 | component/assembly는 bundle 필요; committee·runtime simulation은 아직 미연결 |
| Melete | 실제 native observe/query, canonical feedback·outbox·receipt | assistant 판단은 현재 native gate상 `trace_only`; user feedback의 검색 가능 여부는 실제 receipt로 구분 |
| 복구 | durable jobs, 안정 decision ID, 단일 worker lock, outbox 재시도, local logical backup | 단일 host/process; off-host backup·PostgreSQL 재해복구·HA는 미검증 |

브라우저: host에서 `http://127.0.0.1:8080`. LAN 접근 주소는 실행 host의 IP와 같은 port를 사용한다. 현재 profile은 단일 운영자용 HTTP self-host다. UI에 로그인·사용자별 권한 경계는 없으며 다중 사용자 배포 검증은 별도다.

100개 목록과 공개 metadata/hash는 [manifest.json](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/pilot100/manifest.json)에 보존한다. 본문·embedding·모델 응답·private 설정은 public Git에 올리지 않는다.

### 실제 검증 결과 — 2026-10-25

| 검증 | 실제 결과 | 해석 |
|---|---|---|
| Corpus/원문 연결 | 100 artifact hash · 1,912 chunk span · 101 quote/offset 검사 통과, 끊긴 graph reference 0 | 원문 인용의 정합성 확인; 과학적 사실 검증과 구분 |
| Offline suite | `pytest -q`: 148 passed, deprecation warning 1 | env/provider/citation/retrieval/policy/API/recovery/운영 회귀 |
| 실제 HTTP E2E | 18/18 gates 통과 | 실제 Supabase·embedding API·Codex·native HAT schema·Melete 사용 |
| Hardware 판단 | `constraint_rejected`, 인용 4개 | 필수 arithmetic rule 13개 중 13번째 위반을 검색 top-k와 무관하게 거부 |
| Kernel 판단 | `insufficient_evidence`, 인용 3개 | 확인된 근거와 미지원 ISA/정확성/성능 검증 gap을 분리 |
| Experiment 판단 | `insufficient_evidence`, 인용 3개 | MetricVector 조건·tradeoff·추가 실험 제안; B300 수치 추측 없음 |
| Melete 환류 | user feedback 저장·검색, 다음 experiment snapshot에서 동일 memory 참조 확인 | assistant 판단은 native `trace_only` 유지 |
| 재시작/재전달 | 동일 decision ID 복구, 추가 LLM 호출 0; feedback 재전달 시 동일 memory ID·정본 receipt 유지 | 제어된 재시작/재전달 시험; 실제 네트워크 장애 주입은 아님 |
| Browser | desktop 1440 / mobile 390·375의 22개 화면 상태, overflow·HTTP/network/console/page 오류 0 | 검색·인용·graph·판단 이력/상세·시스템 상태 확인 |
| Local snapshot | 15개 table 행 직렬화·SQLite 행 수/무결성 smoke 통과 | 전체 제품 복구나 PostgreSQL restore 검증은 아님 |

코드/공개 집계는 [verification.json](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/pilot100/verification.json)에 있다. 실제 3개 판단은 모두 tool call 0인 결과만 저장했다. 초기 시험 중 timeout·host tool 설정 혼입은 실패로 남겼고, per-call instruction/skill/MCP 설정을 격리한 뒤 같은 미완료 job ID를 재시도했다. Codex의 JSONL이 backend model revision을 보고하지 않아 model ID는 요청 설정값으로 기록한다.

자료 적합성은 별도 과제다. 100개 제목·요약·앞 700자를 Jev로 보조 검토했으며, 56개는 직접 DSE, 35개는 보조 방법론, 9개는 navigation 유사 자료로 표시됐다. 앞부분만 본 분류이므로 RISC-V 소개·API 설명·설치 version mapping처럼 실제 본문이 있는 자료도 flag된다. 이 수치를 전체 본문 품질 인증으로 사용하지 않는다. 문서/운영 reference가 섞인 pilot이며, 14만건 확장 전 source 역할 분류와 적합성 평가를 강화한다.

### 품질·검색·규모 평가 — 2026-10-25

**판정: 현재 100개 Workbench는 계속 사용하면서 개선할 수 있다. 145,748건의 전면 KG 생성은 보류한다.** 아래 값은 고정된 P1과 편의·분야별 표본의 관측이며 전체 corpus 정확도나 처리량 보장이 아니다. 평가 중 source/Claim/검색/model 설정은 바꾸지 않았다.

| 평가 | 실제 결과 | 해석 |
|---|---|---|
| 자료 100개 역할 | 핵심기술 35 · 보조방법 29 · 운영/연동 30 · 목차 5 · 범위밖 1 | 같은 retrieval·판단 목적으로 모두 사용하면 안 됨. 역할 분류는 평가 artifact이며 정본에는 아직 미반영 |
| Claim 101개 | 명확한 원문지지 99 · 조건/요약 보완 2 · 불지지 0, quote/offset 101/101 | AI 보조 문맥 검토. 논문 주장의 독립 과학 검증은 0이며, 두 보완 건도 원문 의미가 틀렸다는 판정은 아님 |
| Graph | 198 nodes · 101 edges · 97개 연결 묶음, 최대 4 nodes, 여러 자료가 연결된 묶음 3 | entity는 모두 concept, relation 92종. 약 1 Claim/자료의 얇은 graph로 모든 DSE 단계의 typed reasoning을 약속하지 못함 |
| 정답 자료 Hit@5 | Hybrid 24/24, dense 24/24 | 결과를 보기 전에 만든 부분 정답 기준. 검색 정확도 100%라는 뜻이 아님 |
| 정답 자료 Hit@1 / MRR | Hybrid 16/24·0.814, dense 23/24·0.979 | graph를 합치면 원래 정답 자료의 첫 순위가 내려가는 사례가 있음. 최종 답변 정확도 비교는 별도 |
| 지정 근거 chunk Hit@5 | Hybrid 14/24, dense 10/24 | graph가 일부 근거 위치를 더 찾음. 반면 놓친 10건의 사후 AI 검토는 관련 대체 passage 6 · 부분 근거 3 · 핵심 메커니즘 누락 1; 이를 새 gold/precision으로 승격하지 않음 |
| Lexical / exact | 30건 모두 후보 0 | 전체 자연어 질문을 AND 조건·title substring으로 쓰는 방식의 한계. Query decomposition·task별 fusion/reranking 실험 필요 |
| Blind 판단 3건 | 정상 source 질문 2/2 완료, B300 미지원 실측 질문 1/1 unknown, 수치 날조 0 | 두 factual 질문과 한 미지원 질문의 AI 보조 검토. 6개 미지원 질의 전부의 최종 답변을 평가한 것은 아님 |
| 검색 지연 | 실제 Retriever 30건 p50 8.62s / p95 12.11s; HTTP 6건 p50 9.06s / p95 15.41s | 성공 요청 기준의 작은 순차 표본. Embedding median 8.00s, DB 네 질의 합 median 0.49s; saturation 시험 아님 |
| 100개 embedding | 1,956,001 input tokens, 현재 단가 적용 추정 $0.03912 | provider invoice가 아니며 overlap·반복 title 등 실제 usage에 포함된 입력 기준 |
| 생성 처리량 | 기록된 추출 성공 96호출의 합계 2,767.51s, p50 27.50s | 실패 usage 누락·수동 대기·전체 coordinator 비용을 포함하지 않은 하한. CLI token을 API 청구액으로 환산하지 않음 |
| 145,748건 가정 | 약 279만 chunks · 원문 artifact 132GB · 현 layout PG schema 약 58GB; ideal 4-worker 생성 약 11.7일 | 같은 자료 크기/추출 깊이의 선형 scenario. 현재 host 여유 약 58GB는 원문 예상량보다 작고 quota·대형 index·실패 재시도·더 깊은 추출은 미검증 |

Embedding 비용의 기준은 [DeepInfra 공식 단가](https://deepinfra.com/google/embeddinggemma-2/api)의 $0.020 / 1M tokens다(2026-10-25 확인). 같은 분포의 전체 문서 embedding scenario는 약 $57이지만, 생성·review·DB·storage 비용 전체를 뜻하지 않는다.

정답셋은 24개 정상 질의(한국어/영어 각 12, 9개 category마다 최소 2개)와 6개 미지원 질의로 먼저 고정했다. Unsupported의 source 참조는 근접 문맥을 설명하는 boundary이지 정답이 아니다. 미지원 질의에서 검색 결과가 나오는 것만으로 실패로 처리하지 않는다. 한국어와 영어 질문이 서로 달라 subgroup 차이를 embedding의 언어 성능 차이로 단정하지 않는다.

초기 판단 probe 3개는 입력 case ID의 pos/neg prefix가 모델에 보여 독립 평가에서 제외했다. 같은 질문을 공통 kind=knowledge, model-visible input={}로 다시 실행했고 **blind 결과 3개만** 위 성적에 사용했다. 기존 결과는 지우지 않고 invalidation audit와 함께 보존했다. 새 gold feedback은 Melete에 추가하지 않았다. Semantic review는 AI worker/root가 수행했고 reviewer model/revision은 artifact에 기록되지 않았으므로 독립 human benchmark로 보지 않는다. 공개된 30개 qrels는 이후 blind holdout으로 사용할 수 없다. 재현 helper는 metadata·expected label을 model input에 싣지 않는 회귀 테스트를 가진다.

169건 acquisition 시도 중 69건은 allowlist 63 · revision pin 4 · 크기 제한 2로 제외됐다. 이를 전체 자료의 원문 접근 가능률로 해석하지 않는다. source metadata의 title/abstract origin과 실제 PDF fulltext revision도 구분한다. 예를 들어 Glacierware는 abstract-origin catalog record지만 실제 PDF를 확보했다. Lithography hotspot은 thermal hotspot과 다르므로 category 보완 대상으로 기록했다.

| 다음 보완 우선순위 | 전체 제품에서 높일 해상도 |
|---|---|
| 1. Write 품질 | source 역할/지식 수요별 수집·사용 정책, Claim의 값·단위·대상 revision·적용 조건, 조건부 연구결과의 scope 보존 |
| 2. KG와 read | typed entity/관계·alias·source 간 연결, 핵심어 분해, 역할별 검색·근거 reranking/이웃 문맥 확장; 현재 30개는 회귀용으로 두고 새 held-out/번역쌍도 평가 |
| 3. 규모 검증 | artifact 공간, durable batch/재개·quota·budget·대형 index를 확인하면서 같은 UI→DSE 판단→feedback 여정으로 1,000개 수준 재평가 |

공개 재현 자료: [평가 집계](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/pilot100/evaluation-2026-10-25.json), [자료별 역할](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/pilot100/source-roles-2026-10-25.json), [본문/quote를 제외한 qrels](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/pilot100/retrieval-cases-2026-10-25.json). 실제 채팅 답변·source 본문·query vector·credential은 공개하지 않는다.

```bash
"$HOME/.local/share/dse-knowledge/app-venv/bin/python" scripts/evaluate-pilot.py --cases research/pilot100/retrieval-cases-2026-10-25.json --output "$HOME/.local/share/dse-knowledge/qa/evaluation-next/retrieval-results.json"
"$HOME/.local/share/dse-knowledge/app-venv/bin/python" scripts/evaluate-decision-probes.py --cases research/pilot100/retrieval-cases-2026-10-25.json --case-id pos-compiler-en-fused-attention --case-id pos-serving-en-blockserve --case-id neg-ko-b300-serving-measurement --output "$HOME/.local/share/dse-knowledge/qa/evaluation-next/decision-probes.json"
```

두 command는 같은 100개 source snapshot이 적재된 runtime에서 실제 provider를 호출한다. Public qrels는 본문 quote를 hash로 대체한 projection이므로 original frozen private qrels SHA와 파일 SHA는 다르다. 평가 helper는 현재 24/6 구성을 검증하며, 이 결과를 HAT 실행·kernel correctness·physical feasibility·B300 우월성 평가로 해석하지 않는다.

### 실행과 설정

Python 3.12+, `uv`, 기존 Supabase project, 로그인된 host Codex CLI, 선택된 embedding API가 필요하다. `uv.lock`으로 Python dependencies를 고정한다.

```bash
UV_PROJECT_ENVIRONMENT="$HOME/.local/share/dse-knowledge/app-venv" uv sync --frozen --extra test --python 3.12
# owner-only 설정을 준비한 뒤 기존 project에 schema/최소권한 role을 설정한다.
"$HOME/.local/share/dse-knowledge/app-venv/bin/python" scripts/bootstrap-database.py
"$HOME/.local/share/dse-knowledge/app-venv/bin/dse-knowledge" serve
```

| 설정 파일 | 필요한 항목 | 보관 |
|---|---|---|
| `database.env` | 기존 Supabase pooler의 관리자 user/password, DB/schema, `verify-full`, 공식 CA 경로 | `~/.config/dse-knowledge`, 디렉터리 0700·파일 0600; bootstrap 전용 |
| `runtime-database.env` | bootstrap이 생성한 `dse_knowledge_app.<ref>` 전용 자격증명 | HTTP runtime은 관리자 DB 설정을 사용하지 않음 |
| `llm.env` | `CHAT_PROVIDER=codex_cli`, `CHAT_MODEL_ID=gpt-6.1-sol`, reasoning `max`, `CODEX_EXECUTABLE`, `CODEX_WORKDIR`, `CHAT_TIMEOUT_SECONDS` (1–600초; 기본 180초, 현재 profile 360초) | API key 복사 없이 기존 host CLI 로그인 사용 |
| `embedding.env` | `EMBEDDING_PROVIDER=deepinfra`, `EMBEDDING_MODEL_ID=google/embeddinggemma-2`, 768차원, API key | document/query task 분리, provider의 task prefix 사용 |
| `app.env` | data/artifact root, bind/port, extraction batch 1–5·발췌 2–8·발췌 길이 100–1,400·claim 1–3 | 기본 bind는 loopback; 현재 host profile은 `0.0.0.0:8080` |

실제 지원하는 설정 예시는 [config.env.example](https://github.com/jimmylegendary/dse-knowledge/blob/main/deploy/config.env.example)에 있다. 이 P1은 Codex CLI + DeepInfra adapter 조합을 실행한다. OpenRouter·다른 model/embedding/reranker는 architecture 후보이며 현재 adapter에서 검증하지 않은 설정은 거부한다.

문서와 검색 embedding의 socket timeout은 `DSE_EMBEDDING_DOCUMENT_TIMEOUT_SECONDS`와 `DSE_EMBEDDING_QUERY_TIMEOUT_SECONDS`로 각각 설정한다(정수 1..120초, 기본 25초). 전체 wall-clock deadline과는 다르다. 실패 ledger에는 안전한 예외 class·error kind·제한 시간·소요 시간과 보고된 token usage를 남기며, invoice를 확인하지 않은 비용은 `unreported`로 유지한다. Q2의 운영 시험은 문서 60초/검색 25초이며 batch 크기 8과 index 병렬도 2는 유지한다. 반복 transport 오류의 근본 원인은 아직 확정하지 않았다.

값·단위·인용 검증에 실패한 structured extraction은 최대 8개 field path와 reason code로 한 번만 repair한다. 이전 typed 응답은 전체 또는 실패 entry 단위로 prompt budget 안에서 private 교정 문맥으로 제공한다. 초기 추출과 repair 모두 identifier의 부분 문자열이나 추론한 숫자를 값으로 쓰지 않도록 안내하고, 같은 원문 검증기로 다시 검사한다. 총 모델 호출은 최대 2회이며 재실패는 `needs_review`다. 실패한 structured 응답은 별도 owner-only `quality-cache/failures`에 최대 1 MiB까지 남기고, 초과 응답은 hash·크기·생략 이유만 보존한다. 이 진단 파일은 검증된 응답 cache로 읽지 않는다.

서비스 설치: `python scripts/install-user-service.py`. systemd user service가 HTTP process와 자식의 CPU 200%, RAM 4 GiB, stop timeout을 제한한다. 수집은 2개 fetch worker, 생성은 process별 1개 호출로 제한한다. 이번 일회성 100개 추출은 ID가 겹치지 않는 4개 application process로 분할했고, HTTP 판단 worker는 1개다. 로그는 `journalctl --user -u dse-knowledge.service -f`로 확인한다. 자동 로그인 없이 부팅 시 user manager를 유지하는 linger/OS 정책은 host 설정에 따른다.

CLI 작업은 동일 venv의 `dse-knowledge`로 실행한다.

```bash
dse-knowledge sample --registry /absolute/path/to/registry.sqlite --count 240 --output /absolute/path/to/candidates.json
dse-knowledge acquire --candidates /absolute/path/to/candidates.json
dse-knowledge index
dse-knowledge extract
dse-knowledge status
python scripts/verify-live.py
python scripts/backup-pilot.py
```

`acquire/index/extract`는 실제 원문/API/모델/DB를 사용한다. index는 이미 ingested인 자료, extract는 이미 Claim이 있는 자료를 건너뛴다. P1은 고정된 한 source revision을 기준으로 하며, 변경 감지·revision 교체·권한 철회·대량 재색인은 아래 확장 설계를 구현할 때 추가한다.

| 해상도 | 종료 때 가능한 전체 여정 | 후속 확장 |
|---|---|---|
| P1 | 100개 원문→KG/검색→근거 있는 DSE 보조→실험 입력/비교→feedback/경험 | 단일 운영자·bounded extraction·native 지원 범위 명시 |
| P2 | 같은 여정을 조직 corpus와 더 많은 자료에서 반복 | incremental version/권한, batch 재개·평가, HAT run orchestration, ontology/committee 확대 |
| P3 | 같은 여정에서 자동 탐색과 검증의 깊이를 높임 | architecture/kernel 후보 실행·정확성/성능 검증, optimizer 비교·대규모 운영 |

P2에서 145,748개를 처리하기 전 source 권한·원문 가용성·추출 품질·비용/처리량·index 용량을 검증한다. 100개 E2E 성공이 전체 자료의 가용성이나 동일한 품질을 보장하지 않는다. `backup-pilot.py`는 DB 행의 local logical serialization과 SQLite smoke check만 검증한다. 원문 artifact bytes와 native Melete DB, off-host 보관 및 PostgreSQL 재해복구는 이 snapshot에 포함하지 않는다.

## 실제 자료 목록 수집 결과 — 2026-10-21

**중복 제거 후 145,748건 등록**, 100,000건 목표 달성. Source 검토 범위는 초기 40개에서 **77개 family**로 확장했다.

| 단계 | 실제 결과 |
|---|---|
| STEP 1 | CPU/ISA/RTL, GPU simulation, compiler/kernel, power/thermal, serving/trace, 측정·최적화 source 누락을 보완해 77개 family의 entrypoint·발견 경로를 확인 |
| STEP 2 | arXiv 공식 metadata snapshot 3,215,335개 record를 확인하고, 분야 선별·scholarly index를 합쳐 1,146,381개 후보 관측을 처리. Source 간 중복 포함 |
| STEP 3 | 제목과 공개 초록/문서 앞부분 약 10줄을 자동 규칙으로 선별하고 DOI·arXiv ID·원문 링크·동일 긴 제목으로 중복 정리. 최종 145,748건 |
| STEP 4 | source·제목·category·1줄 요약·link·자료 type의 6열 CSV와 집계·source 접근 상태를 제공 |

- [자료 목록 webapp](https://dse-knowledge-atlas.nocode-jimmy.chatgpt.site/materials.html) — 본인 ChatGPT 로그인, 전체 목록 검색·필터·page 탐색
- [materials.csv.gz](https://github.com/jimmylegendary/dse-knowledge/raw/refs/heads/main/research/materials/materials.csv.gz) — 등록 자료 전체
- [manifest.json](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/materials/manifest.json) — 실제 건수·policy/code hash·snapshot version
- [sources.csv](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/materials/sources.csv) — 77개 source의 개별 접근 상태와 등록 수

**판정의 범위:** 제목과 실제 관측한 공개 초록 또는 문서 앞부분을 기준으로 한 자동 선별이다. 자료별 본문 전체를 LLM이 읽어 검증한 결과가 아니다. 논문 PDF의 개별 열람·재배포 권한, 과학적 품질·주장 수용, embedding 및 KG 등록은 하지 않았다. 제약·private source는 비인증 entrypoint 응답과 실제 미확인 상태를 유지하며, 77개 source의 모든 자료를 완전 크롤링했다는 뜻은 아니다. 최적화·모델 방법론의 배경 자료도 모든 DSE 단계의 판단을 돕는 수집 대상으로 포함한다.

| Category | 등록 자료 |
|---|---:|
| Compiler / kernel | 4,809 |
| DSE / optimization | 21,034 |
| HW architecture / ISA | 13,590 |
| LLM / model / workload | 89,979 |
| Memory / interconnect | 3,817 |
| Power / thermal / packaging | 3,179 |
| Provenance / experiment | 584 |
| Serving / scheduling | 2,995 |
| Simulation / measurement | 5,761 |

등록 예시 — 공개 HEAD에서 뽑은 한 줄 요약이며 전체 본문 분석이 아니다.

| Source | 제목 | Category | 1줄 요약 | Link | 자료 type |
|---|---|---|---|---|---|
| Semantic Scholar | "A New Old Approach to Teaching Microprocessors: Update and Lessons Learned" | hardware_architecture | The construction of the microprocessor system was accompanied by lectures in a variety of topics including computer organization, instruction set architectures, the Intel family… | [원문](https://www.semanticscholar.org/paper/147b8a0719e818581be20eeee0730c6a058b405a) | scholarly_work |
| arXiv | $MC^2RAM$: Markov Chain Monte Carlo Sampling in SRAM for Fast Bayesian Inference | memory_interconnect | We show a novel architecture of SRAM by embedding it with random number generators (RNGs), digital-to-analog converters (DACs), and analog-to-digital converters (ADCs) so that… | [원문](https://arxiv.org/abs/2003.02629v1) | research_paper |
| arXiv | "Is Low Power Enough?" Rethinking Energy Efficiency in High-Fidelity Sensing | power_thermal_packaging | Scientists now want higher fidelity data from the field, such as images and audio, and these observations break that rule: a low-power microcontroller stays… | [원문](https://arxiv.org/abs/2610.14714v1) | research_paper |
| arXiv | $\epsilon$-Approximate Coded Matrix Multiplication is Nearly Twice as Efficient as Exact Multiplication | compiler_kernel | As an additional contribution, we develop an optimization framework based on alternating minimization that enables the discovery of new codes for approximate matrix multiplication. | [원문](https://arxiv.org/abs/2105.01973v1) | research_paper |
| arXiv | !MSA at BAREC Shared Task 2025: Ensembling Arabic Transformers for Readability Assessment | llm_model_workload | We present MSAs winning system for the BAREC 2025 Shared Task on fine-grained Arabic readability assessment, achieving first place in six of six tracks. | [원문](https://arxiv.org/abs/2509.10040v1) | research_paper |
| arXiv | (Almost) Perfect Discrete Iterative Load Balancing | serving_scheduling | We present results for a general class of simple local balancing schemes where the tokens are balanced via matchings. | [원문](https://arxiv.org/abs/2510.15473v1) | research_paper |
| arXiv | "I Strongly Suspect This Website Is a Scam": Benchmarking PII Leakage and Detection without Defense in Autonomous Web Agents | simulation_measurement | In this paper, we show that social-engineering attacks are highly effective at extracting critical-tier PII from frontier web agents, posing a severe risk to… | [원문](https://arxiv.org/abs/2606.00497v1) | research_paper |
| arXiv | "Efficient Complexity": a Constrained Optimization Approach to the Evolution of Natural Intelligence | dse_optimization | A novel approach in the description of the information processes of natural learning is proposed in the framework of constrained optimization, where the objective… | [원문](https://arxiv.org/abs/2410.13881v2) | research_paper |
| Semantic Scholar | "Get in Researchers; We're Measuring Reproducibility": A Reproducibility Study of Machine Learning Papers in Tier 1 Security Conferences | provenance_experiment | While the Security community has recently increased its attention on reproducibility, an independent and comprehensive measurement of the current state of reproducibility has not… | [원문](https://www.semanticscholar.org/paper/d0ee37d9e5ae942fce2c48db468738e014cb6a3c) | scholarly_work |

추가 source 37개(초기 40개는 아래 설계 catalog에 유지). HTTP 상태는 entrypoint의 이번 관측이며 모든 하위 자료의 열람을 뜻하지 않는다.

| ID | 추가 source | Entry point | 등록 자료 |
|---|---|---|---:|
| s41 | [RISC-V ISA specs + ratified extensions + profiles](https://riscv.org/technical/specifications/) | HTTP 200 | 135 |
| s42 | [Apache TVM / Relax / TensorIR](https://api.github.com/repos/apache/tvm) | HTTP 200 | 139 |
| s43 | [SGLang (RadixAttention, HiCache) docs + repo](https://api.github.com/repos/sgl-project/sglang) | HTTP 200 | 351 |
| s44 | [Accelergy (energy/area model generator)](https://api.github.com/repos/Accelergy-Project/accelergy) | HTTP 200 | 2 |
| s45 | [Timeloop (dataflow mapping explorer)](https://api.github.com/repos/NVLabs/timeloop) | HTTP 200 | 4 |
| s46 | [ARM Architecture Reference Manual (A-profile) + ARM system IP docs](https://developer.arm.com/documentation/ddi0487/latest/) | HTTP 200 | 0 |
| s47 | [Intel SDM (x86-64 ISA + platform)](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html) | HTTP 200 | 0 |
| s48 | [PTX ISA (NVIDIA Parallel Thread Execution)](https://docs.nvidia.com/cuda/parallel-thread-execution/) | HTTP 200 | 1 |
| s49 | [Khronos registry (SPIR-V, OpenCL, SYCL, Vulkan)](https://registry.khronos.org/spir/) | HTTP 200 | 2 |
| s50 | [Accel-Sim / GPGPU-Sim](https://api.github.com/repos/accel-sim/accel-sim-framework) | HTTP 200 | 3 |
| s51 | [Vidur (LLM serving simulator)](https://api.github.com/repos/microsoft/vidur) | HTTP 200 | 4 |
| s52 | [Power/thermal models (HotSpot, 3D-ICE, McPAT, Accelergy)](https://api.github.com/repos/HewlettPackard/mcpat) | HTTP 200 | 1 |
| s53 | [Predictive PDKs (ASAP7, FreePDK45) + open RTL flow](https://api.github.com/repos/The-OpenROAD-Project/asap7) | HTTP 200 | 1 |
| s54 | [KV-cache reuse & PD-disaggregation (LMCache, Mooncake, NIXL)](https://api.github.com/repos/kvcache-ai/Mooncake) | HTTP 200 | 1 |
| s55 | [Azure LLM inference trace + BurstGPT (session traces)](https://api.github.com/repos/microsoft/AzurePublicDataset) | HTTP 200 | 1 |
| s56 | [Long-context & agentic evaluation suites (RULER, LongBench, SWE-bench)](https://api.github.com/repos/NVIDIA/RULER) | HTTP 200 | 1 |
| s57 | [OpenXLA / XLA HLO operation semantics](https://openxla.org/xla/operation_semantics) | HTTP 200 | 1 |
| s58 | [Kernel benchmark suites (KernelBench, TritonBench, AITer)](https://api.github.com/repos/ScalingIntelligence/KernelBench) | HTTP 200 | 1 |
| s59 | [NCCL + collective communication docs](https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/) | HTTP 200 | 126 |
| s60 | [Nsight Systems + CUPTI (timeline + counter APIs)](https://docs.nvidia.com/nsight-systems/) | HTTP 200 | 1 |
| s61 | [UALink Consortium specification](https://ualinkconsortium.org/) | HTTP 200 | 2 |
| s62 | [Ultra Ethernet Consortium specification](https://ultraethernet.org/) | HTTP 200 | 0 |
| s63 | [IBTA InfiniBand architecture specification](https://www.infinibandta.org/specs/) | HTTP 200 | 0 |
| s64 | [OCP Open Rack V3 / power delivery + contribution repository](https://www.opencompute.org/projects/open-rack-v3) | HTTP 200 | 1 |
| s65 | [HBM/DRAM vendor datasheets (SK hynix, Micron, Samsung)](https://www.skhynix.com/) | HTTP 200 | 2 |
| s66 | [Cloud instance & price catalogs (AWS EC2 price list, GCP, Azure)](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/region_index.json) | HTTP 200 | 0 |
| s67 | [MLPerf results repositories (measured submissions)](https://api.github.com/repos/mlcommons/inference_results_v5.0) | HTTP 200 | 0 |
| s68 | [OpenReview API (submissions, reviews, decisions)](https://api2.openreview.net/notes?limit=1) | HTTP 403 | 0 |
| s69 | [DBLP (venue/author bibliography, bulk XML)](https://dblp.org/search/publ/api?q=llm%20serving&format=json&h=1) | HTTP 202 | 0 |
| s70 | [IETF Datatracker (RFC + drafts)](https://datatracker.ietf.org/api/v1/doc/document?limit=1) | HTTP 200 | 0 |
| s71 | [Metric/provenance metadata specs (OpenMetrics, Croissant, DCAT)](https://prometheus.io/docs/instrumenting/exposition_formats/) | HTTP 200 | 2 |
| s72 | [Industry engineering blogs with measured numbers (NVIDIA technical blog, Meta/Google infra blogs)](https://developer.nvidia.com/blog/) | HTTP 200 | 2 |
| s73 | [PyTorch Inductor (torch.compile fusion/lowering)](https://api.github.com/repos/pytorch/pytorch) | HTTP 200 | 1 |
| s74 | [IREE (MLIR-based compiler/runtime for accelerators)](https://api.github.com/repos/iree-org/iree) | HTTP 200 | 90 |
| s75 | [Constrained DSE/HPO tooling (Optuna, Ray Tune)](https://docs.ray.io/en/latest/tune/index.html) | HTTP 200 | 0 |
| s76 | [SPEC benchmark results and power/energy methodology](https://www.spec.org/power_ssj2008/results/) | HTTP 200 | 3 |
| s77 | [CUDA math libraries + attention kernels (cuBLAS, cuDNN, CCCL/CUB, FlashAttention, FlashInfer)](https://docs.nvidia.com/cuda/cublas/index.html) | HTTP 200 | 74 |

## 한눈에 보기

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#f6f8fa'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  T[DecisionTask + requirements] --> P[CollectionPlan + QueryPlan]
  P --> S[Rights-gated sources]
  S --> X[Immutable revision + structured extraction]
  X --> L[Canonical ledger + outbox]
  L --> Q[Exact + hybrid + graph reads]
  Q --> D[Validation + DecisionRecord]
  D --> E[Experiment + MetricVector]
  E --> G[Insight + reopened gaps]
  G --> T
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class T,D focal;
  class S,E external;
  class P,X,L,Q,G normal;
```

| 구간 | 책임 | authority / 결과 |
|---|---|---|
| DecisionTask → KnowledgeRequirement | 어떤 결정에 어떤 근거·scope·완료조건이 필요한지 분해 | user decision와 unresolved requirement |
| CollectionPlan → SourceRevision | source discovery, rights gate, acquisition, extraction | revision-pinned source/artifact와 parser provenance |
| Canonical ledger | typed Claim/Evidence, asset/recipe, rules, workload, experiment/event/metric | versioned knowledge and experiment authority |
| Read paths | exact/lexical/dense/graph retrieval과 full required-rule coverage | cited EvidenceBundle, coverage, conflict, unknown |
| Validator/reviewer | deterministic unit/version/scope/legality checks와 evidence-backed review | pass/fail/unknown, review finding, scoped DecisionRecord |
| Experiment/Insight feedback | proposal, run, MetricVector, failure, scoped Insight | 다음 요구·수집계획·실험 proposal 또는 stop 이유 |

원문 조회·색인 rank·committee vote는 그 자체로 truth나 buildability를 증명하지 않는다. MetricVector는 TTFT, TPOT, throughput, tail/SLO, quality, power, energy, memory/network cost 등을 단위·scope·method·uncertainty와 함께 보존한다. 결측 지표를 0으로 채우거나 모든 지표를 단일 성능점수로 합치지 않는다.

## 현재 dev baseline과 infra 경계

| 영역 | 실제 사용 구성 | 확인 범위 |
|---|---|---|
| Compute | 기존 Linux host CPU, self-host HTTP/systemd | AWS와 local GPU는 사용하지 않음 |
| Canonical / retrieval / graph | Supabase PostgreSQL, pgvector 768/HNSW, FTS, relational typed graph | 정본 15 tables와 최소권한 role; Neo4j는 후속 challenger |
| Artifact | host의 content-addressed raw files와 local logical backup | remote object storage·off-host 복구 미연결 |
| Chat | host Codex CLI / selected gpt-6.1-sol, max | 실제 structured generation, 완료 이벤트·tool call 없음·인용 검증 |
| Embedding | DeepInfra google/embeddinggemma-2 | document/query task, 768차원/finite/norm/index 검증 |
| Native | host의 hat-schema + Melete core | 구조 검증·observe/query; HAT 성능 simulation 미연결 |
| 사내 자료 | 연결하지 않음 | Confluence 권한·corpus·사내 run은 후속 범위 |

host→Supabase pooler 연결은 공식 CA의 `verify-full`이다. pooler 내부→PostgreSQL 구간까지 end-to-end TLS를 검증했다는 뜻은 아니다. 실제 key와 비밀번호는 owner-only 설정에만 있고 public repo에는 placeholder만 보존한다.

## DSE 결정별 필요한 지식

Each task creates requirements before it creates a confident answer. A requirement has a target scope/version, required claim and relationship types, authority/freshness, units/measurement boundary, evidence completeness, blocking level, accepted source routes and an explicit satisfaction predicate. Its state can be uncovered, partial, satisfied, conflicted, blocked, unknown or stale.

| DSE decision domain | Decisions | Data/evidence required |
|---|---|---|
| Model, agent and workload | Which model/serving/session conditions are comparable? | Model/tokenizer/chat-template revision, prompt/turn/tool events visible to the user, arrival/timing/KV/cache policy, quality/SLO, seeds; hidden chain-of-thought is not collected |
| Hardware assembly | Can assets form a legal, usable system across rack/tray/package/die/SoC/component? | Exact asset revision, ports/protocols, containment and connection, lanes/rates, capacity, power/thermal/cooling envelope, compatibility constraints, units and source spans |
| ISA, compiler and kernel | Does a recipe preserve semantics and fit target capability? | ISA and programming model, operation/dtype/shape/layout, compiler/dialect/pass version, synchronization/memory behavior, fold/unfold/fusion transforms, correctness and resource bounds |
| Simulation/circuit/system models | Which claims are analytic, simulated, calibrated or measured? | Equations/parameters, valid domain, calibration evidence/residuals, fidelity level, assumptions, uncertainty and unsupported dimensions |
| Experiment analysis | Did an intervention improve the selected outcomes without hiding regression? | Run manifest/event chain, cohort compatibility, all MetricVector components, metric definitions, sample/quantiles, missingness, failure taxonomy, measurement boundaries and independent lineage |
| Next action | What source, measurement or experiment resolves the highest-impact gap? | Open KnowledgeRequirements, decision criticality, rights/access state, expected information gain, collection/run cost, owner and stop condition |

## 필요 AI 모델과 역할별 후보

모델은 파싱·검색·후보 생성을 돕고, 채택 여부는 명시적 규칙과 근거 검토로 판단한다. 아래는 역할별 모델 연결도이며 실제로 검증한 serving topology는 아니다.

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#ffffff'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  T[문서·질문·DSE 작업] --> R[Role and capability router]
  R --> P[CPU parser<br/>Docling·AST·config/log parser]
  R --> L[생성·추론 모델<br/>OpenRouter 또는 Codex]
  R --> D[Embedding model<br/>BGE-M3 또는 Qwen3 후보]
  R --> X[Reranker model<br/>BGE 또는 Qwen3 후보]
  P --> C[구조화 요소·Claim 후보·근거 위치]
  L --> C
  D --> V[버전별 vector space]
  X --> E[재정렬한 evidence 후보]
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class R,C focal;
  class T external;
  class P,L,D,X,V,E normal;
```

| 역할 | 우선 평가·비교 후보 | 사용 범위와 준비 상태 |
|---|---|---|
| Chat and candidate extraction | OpenRouter or Codex behind provider interface; model ID uses existing environment names | Interface-first. Output is candidate Claim/query plan or cited explanation, never acceptance. No model ID or credential tested |
| Embedding | [BGE-M3](https://huggingface.co/BAAI/bge-m3), 1024차원 reference; [Qwen3-Embedding-4B](https://huggingface.co/Qwen/Qwen3-Embedding-4B), 1024차원 출력 profile challenger | Prior candidates only. CPU/remote capability·RAM·품질을 비교하며 model revision·출력 차원·정규화·index 호환성을 함께 고정 |
| Reranking | [BGE-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) reference; [Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) challenger; disabled is allowed | Evaluate on same held-out evidence queries, with CPU/memory and remote route measured separately |
| Document parsing | Docling candidate for documents/PDF layout; deterministic AST/code/config/log parsers | Exact source spans and extraction uncertainty remain available; parser name is not an accuracy claim |
| Finite classification | Existing shared Jev interface as optional source/query/rubric candidate classifier | Advisory finite choice only; no new credential and no fact, rule, rights or execution authority |
| Validation and metric calculation | Deterministic typed validator and programmatic unit/cohort/metric logic | Not an LLM role. Missing applicability/evidence stays unknown |

Candidate priorities are not benchmark results. No model inference or provider credential call was run. Final choices require the same DSE gold queries, source spans, negative/no-answer cases, CPU/remote profiles, privacy and cost boundary.

## Source별 수집 data: 40개 family

The catalog is a **collection plan**, not a captured corpus. Each row states the material to acquire and the decisions it can support. Revision/hash, source span, rights, acquisition method, refresh trigger and quality checks remain in the linked [01-source-catalog.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/research/01-source-catalog.md) and [01-source-catalog.json](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/research/01-source-catalog.json).

Access tags: <code>PUBLIC</code> means public discovery/selected facts with attribution, not bulk redistribution permission; <code>REPO</code> means pin repository/model/data revisions and check each license; <code>META</code> means metadata/public abstracts only until full-text terms explicitly permit use; <code>LICENSE</code> means metadata-only until item/spec/license and AI/TDM terms are approved; <code>INTERNAL</code> means allowlisted design docs or synthetic/redacted fixtures only; <code>AUTHORIZED</code> means user or experiment-owner approval is required. Standards are not imported as raw full text by default. Product marketing claims are never relabeled measured performance.

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#f6f8fa'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  T[DecisionTask] --> R[KnowledgeRequirement router]
  R --> H[Hardware + standards]
  R --> K[ISA/compiler/kernel]
  R --> M[Model/serving/agent workload]
  R --> S[Simulation/measurement]
  R --> L[Literature/experiment/provenance]
  H --> G[Rights + scope gate]
  K --> G
  M --> G
  S --> G
  L --> G
  G --> V[Versioned SourceRevision]
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class T,R,G focal;
  class H,K,M,S,L external;
  class V normal;
```

| Source group | Example families | Typical decision / collection gate |
|---|---|---|
| Hardware + standards | NVIDIA/AMD, OCP, UCIe, CXL, JEDEC, PCI-SIG, IEEE, ASHRAE | Asset hierarchy, interface legality, bandwidth/power/thermal; standards detail stays metadata-only until access approval |
| ISA/compiler/kernel | CUDA/PTX, MLIR, Triton, CUTLASS, OpenROAD/SKY130, CACTI | Operation/dtype/layout legality, code and transform semantics, circuit/memory model domain |
| Model/serving/agent workload | MLPerf, vLLM, TensorRT-LLM, HF cards, AgentBench, τ-bench, BFCL, OpenTelemetry | Model/license, session/tool/timing/SLO semantics, serving metrics; user traces need explicit authorization |
| Simulation/measurement | Nsight, DCGM, gem5, Ramulator, BookSim, SST | Instrument boundary, counters, model assumptions, calibration and fidelity; measurement is separate from simulator output |
| Literature/experiment/provenance/experience | arXiv/OpenAlex/Semantic Scholar/Crossref, ACM/IEEE, USENIX, MLflow, PROV-O, Ax/BoTorch, HAT/Melete references | Research discovery, trials/lineage, prior failure and Insight; per-item rights and internal allowlists apply |

| # / family | Primary source | Collect and structure | Supports | Gate |
|---:|---|---|---|---|
| 01 NVIDIA system docs | [NVIDIA GB300/NVL72](https://www.nvidia.com/en-us/data-center/gb300-nvl72/) | SKU/configuration variants, rack/tray/GPU/CPU/network composition, power, thermal, memory, links, claim footnotes | HW asset composition, capacity and budget questions | PUBLIC; attribute vendor claims |
| 02 CUDA/PTX | [CUDA Programming Guide](https://docs.nvidia.com/cuda/cuda-programming-guide/) | Execution/memory/synchronization/datatype semantics, instruction constraints, architecture support | ISA and kernel legality | PUBLIC; pin guide/ISA revision |
| 03 Nsight Compute | [Profiling Guide](https://docs.nvidia.com/nsight-compute/ProfilingGuide/index.html) | Metric definitions/scope/aggregation, replay/sampling, report fields, profiler overhead | Metric interpretation and experiment setup | PUBLIC; workload reports need local controls |
| 04 DCGM | [DCGM Exporter metrics](https://docs.nvidia.com/datacenter/dcgm/latest/reference/dcgm-exporter-metrics.html) | Field IDs for power, clocks, temperature, utilization, memory, PCIe/NVLink | Telemetry mapping and resource observations | PUBLIC docs; telemetry may expose infrastructure |
| 05 AMD MI350/ROCm | [MI350 architecture](https://rocm.docs.amd.com/en/develop/reference/gpu-arch/mi350.html) | XCD/IOD/chiplets, HBM, partitioning, ISA/counters, topology, power/cooling | Cross-vendor HW and software comparisons | PUBLIC; vendor claims remain attributed |
| 06 OCP | [OCP cooling environments](https://www.opencompute.org/projects/cooling-environments/) | Rack/tray/module/connector/power interfaces, OAM/OAI/UBB, cold plate/CDU/coolant | Rack/tray/package composition and cooling | LICENSE; check each document’s terms |
| 07 UCIe | [UCIe specifications](https://www.uciexpress.org/specifications) | PHY/protocol/software stack, package class, rates, topology, compliance and revisions | Die/package interconnect compatibility | LICENSE; metadata first |
| 08 CXL | [CXL specifications](https://computeexpresslink.org/cxl-specification/) | Revision/ECN, memory/fabric feature scope; licensed timing/protocol tables only if authorized | Memory/fabric topology constraints | LICENSE; agreement and AI/TDM terms |
| 09 JEDEC | [JEDEC standards](https://www.jedec.org/) | Standard ID/revision/title/date/public scope; licensed timing/organization/test tables only after entitlement | HBM/DDR capability and limits | LICENSE; metadata only by default |
| 10 PCI-SIG | [PCI-SIG specifications](https://pcisig.com/specifications) | Public revision/status/errata; licensed lane, encoding, protocol/compliance details only if allowed | PCIe connectivity and link constraints | LICENSE; no systematic/AI access without permission |
| 11 IEEE 802.3 | [IEEE 802.3 working group](https://www.ieee802.org/3/) | Amendment/status/revision, PHY scope, speed/reach, MIB/YANG metadata | Ethernet/fabric link compatibility | META; no robots/systematic or licensed-content AI processing |
| 12 ASHRAE | [ASHRAE site planning](https://www.ashrae.org/technical-resources/topics-and-initiatives/ai-data-center/site-planning) | Public air/liquid envelope summaries, W-classes, humidity, facility/IT measurement boundaries | Thermal/facility feasibility | LICENSE; full Datacom guide requires rights |
| 13 OpenROAD/SKY130 | [OpenROAD Flow Scripts](https://openroad-flow-scripts.readthedocs.io/en/latest/) | RTL-to-GDS flow, cells/libraries/DRC, area/timing/power report method | Circuit-design methodology and early proxy studies | REPO; SKY130 is not advanced-node B300 evidence |
| 14 CACTI | [CACTI repository](https://github.com/HewlettPackard/cacti) | Model inputs/equations for access/cycle time, area, leakage/dynamic power and IO | Memory/cache model estimates | REPO; pin model/data license and valid domain |
| 15 gem5 | [gem5 documentation](https://www.gem5.org/documentation/) | CPU/cache/coherence/ports/timing object semantics, configuration and stats | Architecture and system simulation | REPO; model claims remain configuration-relative |
| 16 Ramulator 2 | [Ramulator 2 repository](https://github.com/CMU-SAFARI/ramulator2) | DDR/HBM presets, controller policy, trace frontends, validation tests and output stats | DRAM timing and controller studies | REPO; trace license separate |
| 17 BookSim | [BookSim 2 repository](https://github.com/booksim/booksim2) | Router/topology/routing/traffic and cycle-level latency/throughput | Network/interconnect simulation | REPO; check bundled models/data |
| 18 SST | [SST getting started](https://sst-simulator.org/sst-docs/docs/guides/start) | Processor/memory/network components, events, clocks, stats and configuration | Multi-component simulation | REPO; check each third-party model |
| 19 MLIR | [MLIR docs](https://mlir.llvm.org/docs/) | Operation/type/attribute constraints, pass legality, rewrite/fusion/lowering and IR serialization | Compiler semantics and kernel lowering | PUBLIC/REPO; pin dialect/pass revisions |
| 20 Triton | [Triton tutorials](https://triton-lang.org/main/getting-started/tutorials/) | Kernel algorithms, tiles/layouts, fusion/pipeline, launch config and supported hardware | Kernel recipe candidates | REPO; examples are not measurements |
| 21 CUTLASS/CuTe | [CUTLASS repository](https://github.com/NVIDIA/cutlass) | Kernel registry, tile/layout/datatype/SM constraints, fusion/epilogue, profiler inputs/results | Targeted kernel selection and profiling | REPO; results apply only to matching config |
| 22 HAT internal | [hat-system reference](https://github.com/jimmylegendary/hat-system) | Allowlisted schema/system contracts, composition/legality, HATIR fold/unfold/fusion semantics and limitations | Native hardware/kernel adapter scope | INTERNAL; no unrelated data or code redistribution |
| 23 Melete internal | [Melete reference](https://github.com/jimmylegendary/melete) | Allowlisted event/Experience/Claim/Evidence mappings, revision/deletion provenance and synthetic fixtures | Failure experience and feedback linkage | INTERNAL; no user prompts/experience without consent |
| 24 MLPerf | [MLPerf Inference submission rules](https://docs.mlcommons.org/inference/submission/) | Scenarios, LoadGen, latency/throughput definitions, quality targets, result history | Benchmark cohort and metric semantics | PUBLIC rules/results; model/dataset rights separate |
| 25 vLLM | [vLLM benchmarking docs](https://docs.vllm.ai/en/stable/benchmarking/cli/) | Scheduler/KV behavior, TTFT/TPOT/ITL, throughput, cache and client measurement controls | Serving/workload questions | PUBLIC/REPO; prompt/output data off by default |
| 26 TensorRT-LLM | [TensorRT-LLM docs](https://nvidia.github.io/TensorRT-LLM/) | Hardware/model support, benchmark controls, telemetry, scheduling/KV/fusion features | Serving and kernel/recipe options | PUBLIC; code/CUDA/model rights separate |
| 27 Hugging Face cards | [Model cards documentation](https://huggingface.co/docs/hub/model-cards) | Architecture/tokenizer/context, intended use, evaluations, lineage, license, limitations | Model/quality and source-eligibility checks | PER-MODEL; card is not a blanket weight grant |
| 28 AgentBench | [AgentBench repository](https://github.com/THUDM/AgentBench) | Environment/task prompts, tool schema, state transitions, scores and failure classes | Agent workload scenarios | REPO; task/environment data licenses vary |
| 29 τ-bench family | [tau2-bench repository](https://github.com/sierra-research/tau2-bench) | Multi-turn tool/API/policy traces, final state, reliability/pass^k and modality | Tool-agent session and policy workloads | REPO; call this τ-bench family; do not imply τ3 |
| 30 BFCL | [Berkeley Function Calling Leaderboard](https://github.com/ShishirPatil/gorilla/tree/f7cf7359b7ac615a0b294831c5ba2bc95ee4a000/berkeley-function-call-leaderboard) | Tool schemas/calls, task categories, multi-turn backends and memory/web tasks | Function-calling evaluation scenarios | REPO; benchmark/data rights check |
| 31 Ax/BoTorch | [Ax multi-objective recipe](https://ax.dev/docs/recipes/multi-objective-optimization/) | Search spaces, constraints, noisy trials, Pareto/hypervolume and cost-aware evaluations | DSE search strategy | PUBLIC/REPO; suggestions do not establish HW truth |
| 32 OpenTelemetry GenAI | [GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) | Session/agent/model/tool spans, tokens/latency/errors and hardware/resource attributes | Observable agent trace schema | PUBLIC; content/PII off by default, redaction/retention needed |
| 33 MLflow | [MLflow tracking](https://www.mlflow.org/docs/latest/tracking/) | Experiment/run IDs, params, metrics, code version, artifacts/status/times and dataset lineage | Experiment reproducibility | REPO; prompts/secrets/proprietary data need controls |
| 34 W3C PROV-O | [PROV-O recommendation](https://www.w3.org/TR/prov-o/) | Entity/activity/agent, attribution, derivation, generation/use and time relations | Provenance relationship semantics | PUBLIC; do not expose proprietary source bodies in triples |
| 35 arXiv | [arXiv bulk data](https://info.arxiv.org/help/bulk_data.html) | Daily metadata/version/DOI/category/abstract/license; full text only if permitted | Research discovery and source revision | META; CC0 metadata does not relicense full text |
| 36 OpenAlex | [OpenAlex API](https://help.openalex.org/api/) | Works/authors/venues/institutions/topics/citation links/OA locations/update history | Scholarly source discovery | META; OA location is not a full-text license |
| 37 Semantic Scholar | [Academic Graph API](https://api.semanticscholar.org/api-docs/) | Paper/author/citation/reference graph, OA locations and selected metadata | Citation-path discovery | META; limits/terms apply; OA flag does not license text |
| 38 Crossref | [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) | DOI/title/authors/venue/dates/references/license deposits/post-publication updates | Canonical literature metadata and refresh | META; abstracts may be copyrighted |
| 39 ACM + IEEE publishers | [ACM Digital Library policy](https://libraries.acm.org/digital-library/platform-and-features) · [IEEE Xplore](https://ieeexplore.ieee.org/) | DOI/version/item rights, abstracts and full text only when item terms authorize extraction | Publisher source resolution and rights decisions | META/LICENSE; no blanket bulk/AI/TDM rights |
| 40 USENIX | [USENIX OSDI proceedings](https://www.usenix.org/conference/osdi24/technical-sessions) | Proceedings metadata/papers/slides, equations/tables/figures and linked artifacts | Systems/serving research | PUBLIC selectively; open access is not public domain |

Separate user/internal inputs are not counted as acquired source families.

| Input lane | What it may contain | Gate and current state |
|---|---|---|
| User-authorized workload/session | `session_id`, `turn_id`, arrival/start/end와 time unit, turn/tool 의존성·대기 시간, model/tokenizer revision, 새 input 길이와 누적 context 길이, output 길이, prefix/KV 정책, 결과·error·retry. 외부에서 관찰 가능한 사건을 보존 | 사용자 제공 시 범위·보존 조건을 정해 연결. 실제 session corpus는 아직 제공·연결된 것으로 확인하지 않음 |
| Internal Confluence | space/page ID, title, page version, body·table·attachment, labels·links, 수정 시각, source span, page/space ACL | 사내 owner가 허용한 space·namespace·자료만 후속 연결. 현재 미연결 |
| Internal HAT/experiment artifacts | workload·architecture·recipe/IR·toolchain revision, fold/unfold/fusion 변경, RP resource timeline 참조, run inputs·outputs, 전체 metric vector·단위, 실패·retry, artifact hash, Insight·반례와 lineage | 실제 실험 후 허용된 artifact를 연결. 대형 trace는 columnar/raw로 저장하고 검색용 요약·지식·원본 참조를 분리 |

A source row is a plan, not a promise that the source was fetched. Every acquired revision needs a hash/locator/access class and refresh/retraction policy. Standards and publishers remain metadata-only until rights authorize full text/AI processing. Do not infer a universal physical limit from a vendor's product claim or a model's simulated output.

## 논리 schema와 공통 metadata

Canonical objects are the versioned records used for decisions. Search indexes and summaries are derived projections and are never the sole authority.

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#ffffff'}}}%%
erDiagram
  DecisionTask {
    string task_id
    string revision
  }
  KnowledgeRequirement {
    string requirement_id
    string satisfaction_state
  }
  CollectionPlan {
    string plan_id
    string rights_state
  }
  SourceRevision {
    string source_id
    string revision_id
    string content_hash
  }
  Claim {
    string claim_id
    string epistemic_state
  }
  EvidenceLink {
    string evidence_id
    string source_span_ref
  }
  HardwareAssetVersion {
    string asset_version_id
    string scope
  }
  DesignPoint {
    string design_point_id
    string snapshot_id
  }
  DecisionTask ||--|{ KnowledgeRequirement : requires
  KnowledgeRequirement ||--o{ CollectionPlan : plans
  CollectionPlan }o--o{ SourceRevision : acquires_or_reuses
  SourceRevision ||--o{ EvidenceLink : cited_by
  Claim ||--o{ EvidenceLink : supported_by
  KnowledgeRequirement }o--o{ Claim : covered_by
  HardwareAssetVersion }o--o{ Claim : scoped_to
  DesignPoint }o--o{ HardwareAssetVersion : assembles
  DesignPoint }o--o{ KnowledgeRequirement : assessed_by
```

ER view에는 8 entity만 표시해 읽기 쉽게 만들었다. Recipe, Experiment, Insight와 기타 record들은 아래 표 및 supporting contracts에 정의돼 있다.

| Object | 핵심 필드 / metadata | 판단에서의 역할 |
|---|---|---|
| DecisionTask | task ID/revision, goal, candidate scope, constraints, requester/namespace, knowledge snapshot, budget/status | 질의를 오래가는 결정/분석 context로 고정 |
| KnowledgeRequirement | task ref, expected claim/path/value, scope/version, unit, source authority/freshness, evidence completeness, blocker, validator, satisfaction predicate/status | 부족·충돌·stale·blocked 상태를 explicit하게 추적 |
| CollectionPlan / AcquisitionAttempt | requirement refs, source family/revision candidates, rights gate, query/parser version, expected evidence, owner/cost/refresh, outcome | 문서 수집·user input·experiment를 같은 gap-resolution flow에 연결 |
| SourceRegistration / SourceRevision / SourceSpan / Artifact | publisher/family, rights, revision/hash, raw artifact, page/section/table/figure/code locator | 원문과 정확한 근거 위치를 고정 |
| ExtractionRun / DocumentElement / Chunk | parser/OCR/model/config version, reading order, table header/footnote, equations/code refs, parent-child IDs | byte source에서 structured candidate를 만든 provenance |
| Claim / EvidenceLink / Conflict | subject/predicate/object, claim kind, applicability, epistemic state, support/refute/qualify, conflicts | claim과 인용 존재를 “실제 지지” 여부와 분리 |
| ConstraintRule / ValidationResult | versioned expression, parameters/unit, applicability, authority, validator version, result/coverage/counterexample | pass/fail/unknown/not_applicable/error를 결정론적으로 반환 |
| HardwareAssetVersion / Port / Assembly / Capability | scope and revision, instances/containment/connection, port compatibility, resources, supported operation | rack/tray/package/SoC/component 조합과 legality 표현 |
| KernelRecipeVersion / CorrectnessAssessment / CostModelVersion | op DAG, dialect/transform/fold-unfold/fusion, target, test scope, calibration domain/uncertainty | recipe 의미와 model coverage를 보존 |
| ModelVersion / WorkloadScenario / DesignPoint | weights/tokenizer/chat-template license, session/timing/KV/SLO, assembly+recipe+serving snapshot | 같은 비교 cohort의 대상 고정 |
| ExperimentProposal / RunManifest / RunEvent / MetricVector | hypothesis/intervention/stop, commits/config/seeds, ordered events/errors/retries, all metrics+units+method+fidelity | 결과와 실패의 재현·비교 |
| EvidenceBundle / ReviewFinding / DecisionRecord | query/snapshot/filters/spans/graph paths/coverage, reviewer/verdict, decision/assumptions/gaps | 감사 가능한 설명과 결과의 연결 |
| InsightVersion / MeleteBridgeRecord | source run/event IDs, scope/applicability, lineage, candidate/reviewed/supported/contested/superseded, external receipt refs | 반복 경험을 다시 찾고 반례로 낮출 수 있게 함 |

모든 object는 id, record type/schema version, namespace/ACL, record revision, content identity, created/recorded time, valid time, provenance와 retention/rights를 갖는다. Relationship에도 type/version, scope, validity, source refs, evaluator/method, ACL이 붙는다. Containment은 DAG; network graph는 cycle을 허용한다. 동일 source 재인용·동일 run 재생·Insight 재전송은 독립 evidence 수를 늘리지 않는다.

## 시나리오 1 — Source 등록·insert

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#f6f8fa'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  T[Task + requirement] --> P[CollectionPlan]
  P --> G[Rights + acquisition]
  G --> S[Immutable SourceRevision]
  S --> X[Parse + source spans]
  X --> C[Claim/Evidence candidates]
  C --> V[Review + validation]
  V --> L[PG transaction + outbox]
  L --> I[Search projections]
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class T,V focal;
  class G,S external;
  class P,X,C,L,I normal;
```

| Write stage | Persisted input/output | Failure/acceptance rule |
|---|---|---|
| Decision intake and decomposition | DecisionTask, KnowledgeRequirement DAG, scopes, policies and budgets | Missing target/source scope is unknown; do not silently assume |
| Coverage probe and collection plan | Current Claim/Evidence coverage, rights-aware CollectionPlan, expected output/cost | Licensed, blocked or stale source becomes an explicit unfulfilled requirement |
| Rights-gated acquisition | Immutable raw artifact and SourceRevision with checksum, license/access class and time | Failed/partial fetch retains its attempt; never replace with the latest revision silently |
| Parse and structure | ExtractionRun, DocumentElement, SourceSpan, table/cell/code/equation links and Chunk version | OCR/table/unit ambiguity remains review_required; unsupported format is not parse success |
| Candidate Claim review | Entity/Claim candidates, applicability, evidence method and exact source span | LLM/AST output remains a candidate until deterministic or human review |
| Validate and publish | Typed rule results, conflict record, reviewer evidence, then canonical PG transaction | Error/unknown/missing coverage remains visible; vector similarity cannot publish facts |
| Project and recover | Transactional outbox to exact/FTS/graph/vector generation with watermark and idempotency key | Failed projection retries without duplicate Claim/Event; ledger remains authoritative |
| Large session/run artifact | Raw or columnar artifact plus typed event/metric summaries linked to raw spans | Do not embed every event by default; artifact/chunk rights and retention remain separate |

## 시나리오 2 — Retrieval

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#f6f8fa'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  Q[Question] --> A[ACL + snapshot gate]
  A --> P[Typed QueryPlan]
  P --> F[Exact lookup + full required-rule coverage]
  P --> H[Lexical + dense + graph retrieval]
  F --> E[EvidenceBundle + coverage]
  H --> E
  E --> V[Validator + scoped review]
  V --> O[Answer, abstain or gap plan]
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class A,V focal;
  class F,H external;
  class Q,P,E,O normal;
```

| Question/read route | Required retrieval and graph path | Decision output / forbidden shortcut |
|---|---|---|
| Exact spec/value/version | ID/revision/field/unit lookup then authoritative SourceSpan | Answer with citation or unknown; no similar-version substitution |
| Asset composition/legality | Full containment/port/capability traversal plus constraint expansion | Full required checks; never vector-only approval |
| Kernel/recipe choice | ISA/dialect/shape/layout exact lookup, code/test spans and scoped runs | Candidate plus correctness/cost/unsupported semantics |
| Multi-hop/system impact | Typed graph paths and evidence retrieval per edge | Explain path; relation presence alone is not causality |
| Metric comparison | Compatible workload/model/quality/timing/system-boundary cohort and all MetricVector fields | Constraint, uncertainty and Pareto relation; no forced single score |
| Past failure/Insight | Run/Event/Insight lineage with applicability and independence filters | Stale/unverified experience remains advisory |
| Open research/no evidence | Broad lexical/dense/graph search and community summary, then source drill-down | Cite alternatives and create CollectionPlan for remaining gap |
| No authorized evidence/provider unavailable | Preserve ACL/coverage error and partial service state | Never relax filters, leak private title/count, or silently drop graph completeness |

Required rule/input completeness is a separate exact path that top-k, rerank and context limits never cut. Top-k limits narrative candidates only. Filter by current ACL, version and scope before retrieval, then recheck before sending evidence to a provider. Missing/conflicting coverage returns the reason and a collection/experiment plan rather than weakened filters.

## 시나리오 3 — 부족한 지식의 추가 수집

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#f6f8fa'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  D[DecisionRecord] --> C[Coverage check]
  C --> R[Open requirement]
  R --> G[Classify gap]
  G --> P[CollectionPlan]
  P --> S[Rights-approved source or experiment]
  S --> E[New evidence]
  E --> V[Re-evaluate requirement]
  V --> N[Satisfy or reopen]
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class R,V focal;
  class S,E external;
  class D,C,G,P,N normal;
```

| Gap type | New work item | Stop rule |
|---|---|---|
| Source missing/stale | discover revision, rights check, acquire exact span | rights or owner access unavailable → blocked |
| Conflicting Claims | find revision, scope difference, authority and counter-evidence | keep both until resolution evidence exists |
| Unmeasured feasibility | ExperimentProposal or authorized instrumented run | no run without approval/budget/stop condition |
| Unsupported model domain | calibration or alternative evidence source | do not extrapolate as a physical guarantee |

## 시나리오 4 — Source 갱신·상충 처리

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#f6f8fa'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  T[Release / errata / retraction] --> S[New SourceRevision]
  S --> X[Re-extract changed spans]
  X --> C[New Claim candidates]
  C --> K[Conflict / supersession]
  K --> R[Affected requirements]
  R --> V[Revalidate linked decisions]
  V --> D[New DecisionRecord revision]
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class S,K focal;
  class T external;
  class X,C,R,V,D normal;
```

| Event | Mutation | Audit invariant |
|---|---|---|
| New version/erratum | add revision and derived spans/claims | old revision/run/decision remains unchanged |
| Claim conflict | create ClaimConflict and mark overlapping scopes | do not overwrite the losing value |
| Retraction/rights change | mark source/claim state and identify downstream users | immediately block affected reads; reopen dependent requirements |
| Revalidation | create a new decision snapshot | preserve which policy/evidence version produced each verdict |

## 시나리오 5 — 실험·실패·Melete 경험 환류

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#f6f8fa'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  P[ExperimentProposal] --> A[Authorized RunManifest]
  A --> E[RunEvent chain]
  E --> M[MetricVector or Failure]
  M --> I[Analysis / Insight candidate]
  I --> L[Lineage + applicability check]
  L --> B[Melete bridge + receipt]
  B --> R[Requirement / next proposal]
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class P,I focal;
  class A,E,M external;
  class L,B,R normal;
```

| Result | Evidence update | Feedback rule |
|---|---|---|
| Success | measured MetricValue plus complete workload/HW/kernel/toolchain snapshot | use only in compatible cohort and its recorded scope |
| Performance regression | preserve full metrics and intervention | do not reduce to single failure label |
| Compile/semantic/runtime failure | preserve classified error, artifact and stage | not a performance result; may form a new KnowledgeRequirement |
| Melete receipt/Insight | link external memory/version to source events | receipt is not truth or independent replication; unsupported Insight stays candidate |

## 시나리오 6 — 권한 철회·삭제

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#f6f8fa'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  R[Rights revoked / delete request] --> D[Fail-closed query deny]
  D --> T[Canonical tombstone]
  T --> I[Invalidate graph/vector/cache]
  I --> A[Artifact retention action]
  A --> M[Melete source restriction]
  M --> E[Completion audit evidence]
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class R,D focal;
  class A,M external;
  class T,I,E normal;
```

| Ordering | Required action | Evidence |
|---|---|---|
| First | authoritative current ACL check fails closed before graph hop/snippet/cache/provider | denied query event without private title/count leakage |
| Then | tombstone canonical record and invalidate all projections/caches | projection watermark and invalidation receipt |
| Retention | delete or preserve only legally allowed hash/minimal metadata | source-class policy and deletion result |
| External memory | propagate source restriction where applicable | Melete reference status; historical access never bypasses current ACL |

## 시나리오 7 — Embedding·index 교체

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#f6f8fa'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  S[Frozen corpus snapshot] --> N[New index generation]
  N --> G[Same golden queries]
  G --> H[Shadow dual-read]
  H --> C[Coverage + quality gate]
  C --> R[Atomic route change]
  R --> B[Retain old space / rollback]
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class S,C focal;
  class H,R external;
  class N,G,B normal;
```

| Migration field | Must be pinned |
|---|---|
| Embedding space | model/provider revision, dimensions, dtype, normalization, metric, preprocessing and query/document formatter |
| Index generation | corpus snapshot, source/ACL filter version, chunk policy, parser version, last applied outbox sequence |
| Promotion | exact qrels and slices, recall/evidence coverage, latency/memory, regression and rollback threshold |
| Invariant | different embedding spaces are never mixed as comparable vectors; old generations remain until approval/retention expiry |

## 시나리오 8 — 실패 재시도·중복 방지·복구

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#f6f8fa','primaryColor':'#f6f8fa','primaryTextColor':'#1f2328','primaryBorderColor':'#d1d9e0','lineColor':'#59636e','secondaryColor':'#ffffff','tertiaryColor':'#f6f8fa'},'flowchart':{'curve':'stepAfter'}}}%%
flowchart LR
  W[Persisted write intent] --> F[Worker failure]
  F --> K[Idempotency-key retry]
  K --> O[Outbox reconciliation]
  O --> B[DB + local artifact backup]
  B --> R[Isolated restore]
  R --> H[Hash + closure verification]
  H --> C[Resume or dead-letter]
  classDef normal fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;
  classDef focal fill:#0969da,stroke:#0969da,color:#ffffff;
  classDef external fill:#ffffff,stroke:#d1d9e0,color:#59636e;
  class W,H focal;
  class F,B external;
  class K,O,R,C normal;
```

| Failure/recovery point | Record and behavior | Acceptance |
|---|---|---|
| Retry/out-of-order event | stable idempotency key, pending link, retry count and terminal error | no duplicate RunEvent, MetricValue, Claim or external receipt |
| Queue/job restart | persisted job state plus outbox sequence; reprocess only not-yet-applied projection items | canonical and derived sequence reconcile |
| Backup | Supabase database and local artifact bytes tracked as separate backup domains | DB backup does not imply artifact backup |
| Restore | isolated restore then verify root hashes, required refs, schema versions and permissions | resume only after consistency report; otherwise remain degraded/blocked |

## 설계 단계와 준비 상태

다음 D1–D5 표는 2026-10-21의 architecture 설계 이력이다. 현재 실행 상태와 P1–P3 해상도는 위 실제 P1 표가 우선한다. D1–D5 are architecture design-detail phases, not implementation phases P1–P5. Every design phase keeps all DSE domains and the requirement→source→schema→write/read→decision→experiment/feedback loop.

| 설계 phase | Full-scope increase | Status |
|---|---|---|
| D1 — 전체 지도 | DSE decision map, source families, dev boundary, object schema, write/read and scenarios | Draft published in this README |
| D2 — 후보 비교 | Source authority/coverage, storage/retrieval/model combinations, rejection and migration conditions | Not complete |
| D3 — 논리 설계 | KnowledgeRequirement/CollectionPlan, entity/relation/version/scope/state metadata, QueryPlan | Not complete |
| D4 — 상세 설계 | Table/index/projection, parser/connectors, budgets, retries, permission and evaluation detail | Not complete |
| D5 — 실행 계획 | Reviewed backlog, owner/input/dependency, safe credential prep, validation and rollback plans | Not complete |

The implementation phase references P0–P5 in [phase-work-packages.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/phase-work-packages.md) are kept separate. No phase treats B300 native readiness as a gate for designing this wider knowledge system.

## 검증 범위와 상세 참고

| Reference | What it contains |
|---|---|
| [2026-10-21-dse-knowledge-architecture.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/superpowers/specs/2026-10-21-dse-knowledge-architecture.md) | Upper architecture and logical object/feedback loop |
| [2026-10-21-knowledge-architecture-plan.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/superpowers/plans/2026-10-21-knowledge-architecture-plan.md) | D1–D5 design plan and inputs |
| [infra-and-credential-requirements.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/infra-and-credential-requirements.md) | Conditional connection/credential and host resource contract; no setup performed |
| [01-source-catalog.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/research/01-source-catalog.md) | Detailed source access, extraction, refresh and quality gates |
| [data-contracts.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/data-contracts.md) | Existing source/claim/asset/experiment record proposals |
| [retrieval-and-decision.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/retrieval-and-decision.md) | Question routing, evidence retrieval, validation boundaries |
| [recommendation-and-selection.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/recommendation-and-selection.md) | Candidate comparisons; scores are priors, not benchmarks |
| [deployment-profiles.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/deployment-profiles.md) | Safe profile and environment boundaries |
| [integration-state-map.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/integration-state-map.md) | Detailed HAT/Melete/native-result interpretation only |

**현재 경계:** 위 P1 표와 실제 검증 기록을 실행 사실의 기준으로 삼는다. 아래 상세 architecture는 확장 설계를 포함하며, 사내 corpus·HAT 성능 orchestration·B300 실측·자동 kernel 실행은 아직 수행하지 않았다. README diagrams are Mermaid for GitHub rendering. Colors use the supplied github-primer-light profile: paper #f6f8fa, ink #1f2328, muted #59636e, accent #0969da, border #d1d9e0. GitHub controls final font/layout; no SVG export or pixel-level typography proof is claimed.

## Diagram 스타일 프로필

GitHub의 [awesome-design-systems](https://github.com/alexpate/awesome-design-systems)와 [Colorful](https://github.com/Siddharth11/Colorful)로 후보를 탐색하고 원본 palette를 확인해, host의 `~/.diagram-design/profiles/`에 아래 6종과 기본 복구 프로필을 저장했다. 이번 README는 `github-primer-light`를 선택한다. 색상은 diagram용 semantic role과 대비에 맞게 조정했으며 원본 사이트의 폰트·pixel layout을 복제했다고 주장하지 않는다.

| 프로필 | 권장 용도 | 원본 palette |
|---|---|---|
| github-primer-light | README, API 및 architecture 문서 | [GitHub Primer Light](https://github.com/primer/primitives/blob/66e78d332cc536e471bcaeb3f8ad08dc16cfbb8a/src/tokens/base/color/light/light.json5) |
| carbon-enterprise | 기업 시스템, infra 및 운영 구조 | [Carbon Enterprise](https://github.com/carbon-design-system/carbon/blob/c3d6496efd2f3092ef4bdc8753c8211b61e5eb26/packages/colors/tokens/colors.tokens.json) |
| nord-editorial | 연구·기술 문서와 차분한 overview | [Nord Editorial](https://github.com/nordtheme/nord/blob/1cef71605416a222e57225b544540ce0fcec18d4/src/nord.scss) |
| catppuccin-latte | 교육·탐색·부드러운 밝은 문서 | [Catppuccin Latte](https://github.com/catppuccin/palette/blob/07d02aa110ef9eb7e7427afca5c73ba9cf7f8ebd/palette.json) |
| solarized-paper | 인쇄·긴 연구 문서·따뜻한 paper | [Solarized Paper](https://github.com/altercation/solarized/blob/62f656a02f93c5190a8753159e34b385588d5ff3/README.md) |
| dracula-technical | 어두운 기술 자료·terminal 인접 diagram | [Dracula Technical](https://github.com/dracula/dracula-theme/blob/e22ebcc048b8aff586f9bc94db30ff5347070b42/README.md) |

README는 GitHub가 지원하는 Mermaid로 구성한다. Diagram Design의 정보 분할·역할 구분·diagram별 node/edge 한도와 palette를 적용하고, 최종 font·배치는 GitHub renderer에 맡긴다.
