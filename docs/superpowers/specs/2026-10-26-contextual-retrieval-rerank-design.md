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

Secret 값은 root만 owner-only env에 연결한다. Runtime env keys는 `DSE_CONTEXTUAL_ENABLED`, `DSE_CONTEXT_INDEX_PATH`, `DSE_CONTEXT_CHAT_BASE_URL`, `DSE_CONTEXT_CHAT_MODEL`, `DSE_CONTEXT_CHAT_API_KEY`, `DSE_RERANK_ENABLED`, `DSE_RERANK_PROVIDER`, `DSE_RERANK_MODEL`, `DSE_RERANK_ENDPOINT`, `DSE_RERANK_API_KEY`, `DSE_RERANK_CANDIDATES`를 사용한다. 환경 파일은 기존 app.env 또는 추가 contextual.env/rerank.env 중 Settings에서 명시적으로 읽고 owner-only를 강제한다. 다른 provider에 credential을 자동 전송하는 fallback은 없다.

## 실제 평가와 적용

기존 API·source corpus baseline을 먼저 기록한다. Frozen 500 test와 별도100 calibration으로 baseline/contextual-only/rerank-only/combined를 비교한다. Reranker 4B/8B 선택과 threshold는 calibration으로만 정한다. Test 결과를 보고 query·label·prompt·ranking을 조정하지 않는다. 신규 index와 full integration을 root가 실제 API로 검증하고 UI에 적용한다. 결과·test set·새 code와 HTML 보고서를 GitHub에 게시한다.

공개 report에는 원문·generated context·vectors·credentials를 넣지 않고 metadata·hash·점수·비용 범위만 넣는다. Reranker high relevance를 HW 타당성·답변 충분성·세계 사실 검증으로 변환하지 않는다.
