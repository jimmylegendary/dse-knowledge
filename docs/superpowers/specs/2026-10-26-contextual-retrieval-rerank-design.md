# LLM Contextual Retrieval and external reranking

사용자가 Anthropic의 LLM 기반 Contextual Retrieval 및 좋은 reranker의 실제 적용을 승인했다. 기존 500 test +100 calibration 평가와 GitHub 게시 요구도 유지한다. 새 구현은 독립 worktree에서 진행하여 기존 서비스 baseline을 보존한다. 구현 worker는 test/qrels/results를 읽지 않는다.

## 구조와 경계

- Anthropic 방식: whole document와 각 chunk를 LLM에 제공해 짧은 chunk-specific context를 만들고, context+원문으로 embedding과 **실제 BM25**를 만든다. 일반 문서 요약만 복사하는 방식으로 대체하지 않는다. [공식 설명](https://www.anthropic.com/research/contextual-retrieval)
- Source·Claim·원본 chunk·citation의 정본은 기존 PostgreSQL이다. LLM context는 별도 generated retrieval hint이고 원문 증거/검증된 Claim이 아니다. API의 기존 `text`와 `claim_contexts`는 원래 값을 유지한다.
- Linux host에 versioned SQLite derived projection을 둔다: chunk-specific context, exact source/revision/chunk bindings, contextual embeddings(768d float32), FTS5 BM25. NumPy exact cosine으로 context dense 후보를 구하고 원래 PG canonical rows로 hydrate한 뒤 existing role/purpose/active-revision 정책을 적용한다. 로컬 GPU·모델 weights·Torch·새 cloud/DB 서비스는 사용하지 않는다.
- Index manifest에는 corpus hash, 모든 chunk/revision, embedding fingerprint/dimension, context model/prompt/version, completeness·usage를 기록한다. 캐시와 resumable build는 document+chunk+model+prompt hash로 묶고 atomic activation한다. 누락·stale binding·부분 index를 complete로 가장하지 않는다. 50k eligible chunk cap과 typed errors를 유지한다.
- Whole source documents는 현재 최대 926,396 chars, 총 50,118,994 chars다. Document당 ≤64 chunk batch, context 목표 50–100 tokens, strict JSON/ID coverage/length/finish validation. Source instructions는 untrusted이며 tools를 주지 않는다. Source 밖 값·가정·새 numeric constraint를 만들어 넣지 않도록 prompt·metadata에 명시한다.
- Hybrid candidate pool 기본 40, final limit 기본 12. Rerank는 technical evidence 후보에 적용하고 source-navigation locator를 authoritative evidence로 승격하지 않는다. Same-source chunk를 한 자료로 collapse하지 않는다. API trace에 original RRF와 reranker relevance를 구분한다.

## Provider 인터페이스

|용도|초기 연결|설정·보장|
|---|---|---|
|Context LLM|DeepInfra OpenAI-compatible, `deepseek-ai/DeepSeek-V4.1-Flash-1017`|별도 model/base URL/key env; 전체 source 문맥+chunk의 JSON 생성; query/test label을 입력하지 않음|
|Embedding|기존 외부 EmbeddingGemma client|768d와 fingerprint 검증 재사용, context+원문만 embed|
|Rerank|`Qwen/Qwen3-Reranker-4B`, 비교용 8B|DeepInfra queries/documents endpoint; finite aligned scores 검증; 사내 HTTP endpoint용 cohere-compatible adapter 설정 가능|

Qwen3 Reranker는 다국어·code 검색과 instruction-aware ranking을 지원한다. API가 주는 relevance/logit·yes-score는 calibrated answerability가 아니다. 4B와 8B를 calibration으로 비교하고 선택 이유·지연·usage를 기록한다. [Qwen model card](https://huggingface.co/Qwen/Qwen3-Reranker-4B), [4B API](https://deepinfra.com/Qwen/Qwen3-Reranker-4B/api), [8B API](https://deepinfra.com/Qwen/Qwen3-Reranker-8B/api), [Context model API](https://deepinfra.com/deepseek-ai/DeepSeek-V4.1-Flash-1017/api)

Secret 값은 root만 owner-only env에 연결한다. Runtime env keys는 `DSE_CONTEXTUAL_ENABLED`, `DSE_CONTEXT_INDEX_PATH`, `DSE_CONTEXT_CHAT_BASE_URL`, `DSE_CONTEXT_CHAT_MODEL`, `DSE_CONTEXT_CHAT_API_KEY`, `DSE_RERANK_ENABLED`, `DSE_RERANK_PROVIDER`, `DSE_RERANK_MODEL`, `DSE_RERANK_ENDPOINT`, `DSE_RERANK_API_KEY`, `DSE_RERANK_CANDIDATES`, `DSE_RERANK_ALLOW_HTTP`를 사용한다. HTTP opt-in은 cohere-compatible endpoint에만 적용하고 DeepInfra는 HTTPS endpoint를 고정한다. 환경 파일은 기존 app.env 또는 추가 contextual.env/rerank.env 중 Settings에서 명시적으로 읽고 owner-only를 강제한다. 다른 provider에 credential을 자동 전송하는 fallback은 없다.

## 실제 평가와 적용

기존 API·source corpus baseline을 먼저 기록한다. Frozen 500 test와 별도100 calibration으로 baseline/contextual-only/rerank-only/combined를 비교한다. Reranker 4B/8B 선택과 threshold는 calibration으로만 정한다. Test 결과를 보고 query·label·prompt·ranking을 조정하지 않는다. 신규 index와 full integration을 root가 실제 API로 검증하고 UI에 적용한다. 결과·test set·새 code와 HTML 보고서를 GitHub에 게시한다.

공개 report에는 원문·generated context·vectors·credentials를 넣지 않고 metadata·hash·점수·비용 범위만 넣는다. Reranker high relevance를 HW 타당성·답변 충분성·세계 사실 검증으로 변환하지 않는다.

### Calibration으로만 고정하는 선택 규칙

첫 reranker calibration 결과를 열기 전에 다음 순서를 고정한다. 동일한 rerank-only calibration 100건에서 4B/8B를 비교한다: 정상 질문의 `chunk_all_groups_hit_at_5`가 높은 모델 → 동률이면 `chunk_mrr_at_5`가 높은 모델 → 다시 동률이면 고정 TPR≥0.90 threshold에서 near-boundary FPR이 낮은 모델 → 완전 동률이면 4B. 지연·usage는 별도로 보고하며 품질을 속도·가격과 임의의 단일 점수로 합치지 않는다. 선택한 동일 모델로 rerank-only와 combined의 test를 수행한다. 운영 기본 모드도 각 모드의 calibration에 같은 품질 우선순위를 적용해 정하고 test로 재선정하지 않는다.

`max_reranker_relevance_proxy`의 지원 domain은 normalized relevance `[0,1]`다. 실제 rerank를 받은 후보 subset의 최대값을 쓴다. `reranker_candidate_rank`와 `reranker_relevance_score`가 모두 없는 항목은 role과 무관하게 미평가 backfill로 제외한다. 한쪽만 있거나 rank가 정수 1..40이 아니거나 score가 비유한·범위 밖이면 오류다. 비어 있는 items는 0이지만 nonempty에 scored 후보가 전혀 없는 경우는 미측정 오류다. Semantic-anchor 보충 때문에 최종 12개 모두가 rerank됐다고 주장하지 않는다. Signed logits를 이 proxy에 그대로 넣거나 임의 sigmoid·clipping으로 변환하지 않는다. `[0,1]`은 표현 범위이며 답변 가능성의 확률을 뜻하지 않는다.

Runner의 mode/score/request/corpus/case identity 외에 root matrix workflow가 model을 고정한다. 각 run 시작·종료의 `/api/capabilities`에서 provider/model/config를 확인하고 모든 row의 returned mode·`reranker_trace.model`을 검증한다. calibration과 test의 provider/model/index profile이 같은지 확인한 뒤만 비교한다. Generic CLI만 별도로 호출하면 model pin이 자동 보장되지 않는 상한을 명시한다. 새 identity 필드가 없는 기존 journal의 암묵적 resume는 허용하지 않는다.

### 실제 연결에서 발견한 형식·운영 보완

Raw artifact SHA와 normalized-content SHA를 구분하고 양쪽 source manifest/cache binding을 보존한다. `out_of_scope`는 baseline과 동일하게 top-k와 capacity 제한 전에 제외한다. Canonical corpus 수와 eligible index 수는 별도로 보고한다. Reranker receipt는 thread-local로 격리한다.

### 실제 provider·transport 선택 기록

실제 context 구축에는 env에 명시한 `deepseek-ai/DeepSeek-V4.1-Flash` 기본 endpoint를 사용한다. 1017 endpoint의 반복 지연은 보존하고 새 model profile로 다시 구축했으며, 서로 다른 모델의 context cache를 섞지 않는다. 전체 source를 제공하므로 가장 큰 자료를 잘라서 모델 한도에 맞추지 않는다.

긴 canonical chunk ID를 모델이 한 글자 틀리게 반환한 응답은 거부했다. 요청마다 `c0…cN-1` transport alias를 만들고 exact coverage·중복·미지 alias를 검증한 뒤 사전에 만든 일대일 매핑으로 canonical ID를 복원한다. Adaptive subbatch는 alias를 새로 시작한다. 이는 ID의 직렬화 변경이며 system prompt 의미·source text·offset·canonical cache key는 유지한다. 이미 검증된 canonical-ID 응답 cache와 이후 alias 응답 cache를 보존하지만, 이전 응답이 새 transport를 사용했다고 기록하지 않는다. 잘못된 ID의 유사도 복구나 누락 context의 생략은 하지 않는다.

실제 64-chunk 응답의 truncation·ID 누락은 strict validation으로 거부한다. 출력 예산은 chunk당 최대 256 tokens, 요청당 최대64다. 잘림·잘못된 JSON·ID coverage 오류에 한해 같은 whole-document를 유지해 64→32→16→8로 나눠 재요청하며, 실패한 smallest batch는 그대로 오류다. 잘못된 응답을 잘라 쓰거나 ID를 채워 넣지 않는다. 수신한 실패 응답의 usage도 보존한다. 전송 중단·응답을 받지 못한 호출 비용은 provider 청구와 일치함을 보장하지 않는다.
