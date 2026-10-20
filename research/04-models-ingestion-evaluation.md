# 04. 모델·수집·평가 후보

기준일: 2026-10-17. 이 문서는 모델·파서의 추천 우선순위를 위한 조사다. 아래 점수는 실측 성능이나 정답 확률이 아니라, 공개 문서에 근거한 잠정 전문가 사전값이다. 가중치는 품질 25%, 요구 적합도 20%, 근거 추적성 20%, 운영성 15%, 이식성 10%, 경제성 10%이며 JSON에 후보별 점수를 둔다. 범주가 다른 후보 간 숫자를 직접 비교하지 않고 같은 범주 안에서만 우선순위를 본다. 외부 MTEB/벤더 점수는 후보 제거에 참고할 수 있어도 DSE의 당첨 모델을 정하지 않는다.

다섯 research JSON은 [research-catalog.schema.json](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/schemas/research-catalog.schema.json) 버전 1.0.0을 따른다. `assessment_confidence`는 이전 후보 검토자의 판단 확신도이며 사실의 확률이 아니다. `evidence_stage`는 `E1`, `proposal`, `prior_review_unlocated`를 구분하고, 각 evidence record의 `verification_status`가 해당 주장별 출처 위치 확인 여부를 기록한다. 기존 E1/proposal 라벨은 보존했고, 위치를 재확인하지 않은 prior는 추정 locator를 만들지 않았다.

## 판단 요약

현재 문서가 한 건도 없으므로 정답 모델은 결정할 수 없다. 초기 비교 세트는 **문서 파서 3종 이상 + 정확 문자열/단위 검색 + BGE-M3 + Qwen3-Embedding-0.6B + 상용 한 종**으로 두고, 동일한 정답 corpus에서 `dense`, `BM25/필드 검색`, `dense+BM25`, `+reranker`, 선택적으로 `+graph`/late-interaction을 각각 분리해 비교한다. Jev choice는 요청 모델 `typesafe/jev-1.13`, 반환 모델 `typesafe/jev-1.13-20260917`, BGE-M3(0.59), Qwen3-Embedding-0.6B(0.41), confidence 0.51, advisory-only였다. request ID는 `internal-request-id-omitted`이며 확률은 정답률이 아니다. 최종 선택은 DSE gold set 실측 뒤에만 한다.

JSON 점수에 명시 가중치를 적용한 범주별 잠정 우선순위(5점 만점)는 다음과 같다. 근접 점수는 동률/실측 필요로 해석한다.

| 범주 | 범주 내부 순위 |
|---|---|
| 파싱 | Docling 4.20 > Mathpix 3.95 > PaddleOCR PP-StructureV3 3.75 > GROBID 3.70 > MinerU 3.55 = Google Document AI 3.55 = Azure Document Intelligence 3.55 > AWS Textract 3.35 > Marker 3.25 |
| Retrieval baseline | BM25 + exact fields 4.55 |
| Embedding | BGE-M3 4.25 > Qwen3-Embedding-4B 4.15 > Cohere Embed 5 Pro 4.05 = Qwen3-Embedding-0.6B 4.05 > Voyage-4-large 4.00 > E5-large-instruct 3.95 > Qwen3-Embedding-8B 3.80 > OpenAI 3-large 3.75 > OpenAI 3-small 3.70 = Gemini Embedding 2 3.70 > Jina v5 small retrieval 3.15 |
| Reranking | BGE-reranker-v2-m3 4.40 > Qwen3-Reranker-0.6B 4.05 > Cohere Rerank v4 pro 3.85 > Cohere Rerank v4 fast 3.75 |
| Deterministic extraction | Native parser/AST/rules 4.65 (typed code/config/log extraction only) |
| Semantic extraction | Gemini schema output 3.60 > local vLLM schema 3.45 > OpenAI Structured Outputs 3.40 |

이 순위는 해당 후보 역할 안에서만 쓰는 잠정 개발 순서이지 정확도 우승 선언이 아니다. Native parser/AST는 typed source에서 사실을 읽고 semantic LLM extraction은 자유 서술에서 후보 주장을 제안하므로 서로 대체 후보가 아니다. 높은 deterministic extraction 점수를 전역 우승 모델로 해석하지 않는다. cloud 가용성·예산·보안 등 미정 사실이 확인되면 재평가한다.

경제성 점수는 단가표가 아니라 workload 비용/TCO에 대한 상대 prior다. CPU/GPU 처리량, VRAM, 유휴율, 저장량, 운영 인력이 확인되지 않은 self-host/local compute 후보에는 중립 3점을 준다. 오픈 라이선스나 무료 가중치는 serving·전력·개발·운영 비용이 0이라는 뜻이 아니다. 실제 금액 비교는 페이지/token 수와 QPS가 채워진 뒤 수행한다.

여러 질문 유형에서 임베딩만으로 수치·식별자를 찾도록 하지 않는다. `B300`, tray/slot, package/SoC, firmware/toolchain 버전, HATIR 연산자, kernel symbol, `µs`, `ms`, `tokens/s`, power/energy 단위는 정규화 값을 별도 저장하고 원문과 단위를 보존한다. RAG는 근거 후보를 모으고, HW 적법성·용량 제약·단위 환산·실험 metric 계산은 결정론적 검증기가 최종 확인하도록 설계한다.

## 파싱·OCR·표·수식 후보

| 후보 | DSE 적합 구간 | 주요 확인점 |
|---|---|---|
| [Docling](https://github.com/docling-project/docling) + [Docling models](https://huggingface.co/docling-project/docling-models) | 로컬 구조 인식, 읽기 순서, 표, 다단 PDF, 이미지 OCR; 페이지/블록 구조를 이후 청크 근거로 보존 | 소프트웨어와 모델 아티팩트의 라이선스를 따로 확인해야 한다. 공개 model repo는 dual license가 표시된다. 수식/병합 셀은 자체 문서셋에서 정확도를 재야 한다. |
| [Marker](https://github.com/datalab-to/marker) | PDF text-layer 우선, 필요 페이지/영역만 OCR/VLM, JSON/Markdown 출력; 수식 비중이 높은 논문 | 코드와 모델 가중치의 권리가 다르다. 모델은 수정 OpenRAIL-M 조건 및 상용 제한이 표시되므로 조직 매출/경쟁/배포 조건에 맞는 권리를 확인한다. fast 설정은 수식 정확도를 의도적으로 낮춘다. |
| [MinerU](https://github.com/opendatalab/MinerU) | PDF 및 오피스 문서, 스캔, LaTeX 수식, HTML 표, 다국어, 멀티모달 파싱 | 최신 저장소는 여러 파싱 tier와 광범위한 파일 지원을 제시한다. 릴리스별 custom license/추가 조건, 모드별 자원과 결과 계약이 달라질 수 있어 commit/tag를 고정한다. |
| [PaddleOCR PP-StructureV3](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/algorithm/PP-StructureV3/PP-StructureV3.en.md) | 로컬 OCR·layout·table·formula·chart 인식, 읽기 순서, 커스텀 학습 | 다국어·2차 개발 경로가 강점이다. 공개 자체 비교표는 입력/데이터 조건이 DSE 문서와 같다는 보장이 없다. OCR 버전·모델 파일·언어별 오류율을 고정한다. |
| [GROBID](https://github.com/grobidOrg/grobid) | 논문 제목·저자·섹션·인용·참고문헌·출판물 metadata를 TEI/XML 구조화 | Apache-2.0. 과학 논문 중심이라 회로 도면·복잡한 표/슬라이드·내부 실험 로그를 범용 파서처럼 처리할 수 없다. 문헌 메타데이터에 특화된 보완 경로다. |
| [Mathpix OCR API](https://mathpix.com/pricing/api) | 수식/LaTeX, 기술 표, 도식과 PDF/DOCX/PPTX; batch 결과를 고객 bucket으로 수신 가능 | 공개 가격 페이지끼리 PDF 변환 단가가 다르게 노출되어 표준 API rate를 확정하지 않는다. 한 페이지는 v3/pdf $0.005/page와 batch $0.0015/page를, 다른 OCR 안내 페이지는 v3/pdf $0.0015/page를 표시한다. 견적 확인이 필요하다. 기본 입력 이미지 보관은 30일, opt-out 시 24시간 내 삭제 안내. private cloud는 별도 고가 계약이다. |
| [Google Document AI Layout Parser](https://docs.cloud.google.com/document-ai/docs/layout-parse-chunk) | managed OCR + paragraph/table/figure/heading 등, context-aware chunk | Layout Parser 가격은 공개 표에서 $10/1,000 pages. PDF는 batch 500 pages 제한, 페이지를 넘는 표가 둘로 나뉠 수 있다. 벤더 종속·데이터 위치/보존 조건을 평가한다. |
| [Azure Document Intelligence `prebuilt-layout`](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/layout?view=doc-intel-4.0.0) | managed OCR, 표, selection mark, 구조/읽기 순서, REST·SDK | 정식 cloud model ID는 `prebuilt-layout`. 실제 DSE region별 단가·OCR 언어·저장/보존·네트워크 조건을 별도 quote로 확인한다. |
| [Amazon Textract AnalyzeDocument](https://docs.aws.amazon.com/textract/latest/APIReference/API_AnalyzeDocument.html) | 이미지/PDF의 line/word, table cell, forms, query, signatures, layout block | 범용 문서 분석에 적합하나 수식 중심의 LaTeX 해석기로 볼 수 없다. 비동기 결과와 page-wise 비용을 검증하고 AWS 계정·region·권한을 확보해야 한다. |

Docling, MinerU, Marker, PaddleOCR를 같은 문서 하위집합으로 비교한다. 출판 PDF, 내부 wiki export, 스캔/저해상도, 다단 논문, merged/continued table, block/inline equation, HATIR 코드, 그래프·그림, run CSV/JSON을 분리한다. 원문 페이지 이미지를 보관하고 토큰 오류 외에 표 셀 좌표·행/열 연결·수식 기호·부호·첨자·축/범례·페이지 경계 누락을 측정한다. `수식 LaTeX 편집거리`만으로 kernel 의미의 동일성을 판정하지 말고 기호 의미, 변수/단위와 식 출처를 별도로 검토한다.

## 임베딩·lexical·reranking 후보

### Dense 및 lexical 후보

| 후보 / 공개 스펙 | 입력 구분·장점 | 한계와 실험 변수 |
|---|---|---|
| 정확 문자열 + BM25/필드 검색 (모델 없음) | 식별자, 버전, 심볼, 숫자, 단위, 표 열 이름에 결정론적 기준선을 제공 | 동의어·질문식 표현 일반화가 제한된다. Claim/asset/kernel/version/metric 필드 가중치를 분리한다. |
| [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) | MIT, 1024차원, 최대 8192 tokens, 100+ 언어; dense+sparse+ColBERT(multivector) 출력 선택 가능 | 3 경로를 항상 다 저장하지 말고 비용·recall gain을 측정한다. 식·열·한국어 약어·코드 검색 품질은 미지수다. |
| [intfloat/multilingual-e5-large-instruct](https://huggingface.co/intfloat/multilingual-e5-large-instruct) | MIT, 1024차원, 100개 언어 지원; query에 `Instruct: ...\nQuery: ...`, document에는 instruction 불필요 | 최대 512 tokens이므로 문서/표를 더 짧게 나누어야 한다. instruction 미적용 시 저하 가능. 긴 기술 문맥/코드 성능을 따로 측정한다. |
| [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) | Apache-2.0, 100+ 언어 및 code retrieval, 32K, 1024차원, instruction-aware; 로컬 배치 적합 | 0.6B여도 GPU/CPU 처리량은 HW에 따라 달라진다. Query prompt와 dimension을 고정해 재현한다. |
| [Qwen3-Embedding-4B](https://huggingface.co/Qwen/Qwen3-Embedding-4B) | Apache-2.0, 32K, 2560차원(32–2560 사용자 정의), multilingual/code, instructions | 품질 상승이 DSE Recall/nDCG에 반영되는지 확인. 메모리와 재색인 비용이 0.6B보다 커진다. |
| [Qwen3-Embedding-8B](https://huggingface.co/Qwen/Qwen3-Embedding-8B) | Apache-2.0, 32K, 기본 4096차원, multilingual/code, MRL | 기본 4096차원은 pgvector `vector` ANN(2,000)과 `halfvec` ANN(4,000) 한계를 넘어 HNSW/IVFFlat 불가지만 exact storage/search는 가능하다. 지원되는 MRL 1024차원은 두 ANN 차원 한도에 들어가지만 별도 index와 DSE retrieval 품질 검증, 배포된 extension version 확인이 필요하다. 공개 MTEB 순위는 사전 screening 정보일 뿐이다. |
| OpenAI [`text-embedding-3-small`](https://developers.openai.com/api/docs/models/text-embedding-3-small) | API, 1536차원, 8192 tokens, dimensions 조절; $0.02/1M input tokens, OpenAI API는 기본적으로 입력을 모델 학습에 쓰지 않음 | API 업로드/기본 abuse logs는 별도 보안 검토가 필요하다. query/document 특수 prefix 없음. |
| OpenAI [`text-embedding-3-large`](https://developers.openai.com/api/docs/guides/embeddings) | API, 기본 3072차원(축소 가능), 8192 tokens, 현 안내 $0.13/1M input tokens | small보다 비용·저장량이 큼. 둘 다 수식·테이블은 먼저 구조를 보존하지 않으면 텍스트 표현 손실을 복구할 수 없다. |
| Google [`gemini-embedding-2`](https://ai.google.dev/gemini-api/docs/embeddings) | 최신 multimodal embedding: text/image/video/audio/PDF, 8192 tokens, 128–3072 dims (768/1536/3072 권장); query/doc task type 대신 task prompt 사용 | PDF 1개 최대 6 pages. Standard text $0.20/1M tokens, Batch $0.10; 무료 tier 데이터는 product improvement 사용 조건이라 금지 자료 업로드 금지. Paid tier와 Vertex 약관도 조직 승인 후 사용한다. |
| Voyage [`voyage-4-large`](https://docs.voyageai.com/docs/embeddings) | API, 32K, 1024 기본 및 256/512/2048, `input_type=query|document`가 각각 prompt 부착; $0.12/1M tokens, 최근 계열 batch/양자화 지원 | 기본 1024는 `vector`/`halfvec` ANN 차원 한도에 맞는다. 대안 2048은 `vector` ANN 한도 초과, `halfvec` ANN 한도 이내이며 half precision 품질은 별도 검증한다. 호스팅 API, 지역/보존/계약 검토. Voyage 4 family 내 호환성을 외부 모델 공간에 확장하지 않는다. |
| Cohere [`embed-v5.0-pro`](https://docs.cohere.com/docs/cohere-embed) | API/Model Vault, 128K, 256–2048 dims, multilingual 100+, mixed text/image/PDF; `search_query`·`search_document`; `fast` 모델과 공유 공간 주장 | 기본 2048은 `vector` ANN 한도 초과, `halfvec` ANN 한도 이내다. 대안 1024는 두 ANN 차원 한도에 맞으며, half precision 사용은 별도 품질 검증이 필요하다. 상용 API의 per-token 단가를 이번 조사에서 확인하지 못했다. Model Vault 공개 인스턴스는 Small $2,000/month, Medium $3,250/month. 128K 하나로 chunk 설계를 생략하지 말 것. |
| Jina [`jina-embeddings-v5-text-small-retrieval`](https://huggingface.co/jinaai/jina-embeddings-v5-text-small-retrieval) | 677M, 32K, 1024차원/MRL, retrieval 전용, query/document prefix, local serving 가능 | 가중치 라이선스 CC BY-NC 4.0이므로 상업적 self-host 조건은 사용 금지에 가까운 중요 제한이다. 상용 API는 별도 서비스 약관을 확인. |

Qwen, Cohere, Jina처럼 query와 document를 다르게 encoding하거나 instruction/task를 넣는 모델은 그 template/version을 index metadata와 함께 저장한다. Query-only text normalization, Unicode 기호·마이너스 부호·Greek letter·소수점·SI 접두사, 코드 토큰 분할은 A/B 변수로 고정한다. 모델별 vector space와 dimension, normalize, quantization은 분리된 인덱스로 취급한다.

pgvector 형식·dimension·distance·HNSW/IVFFlat 적합성은 upstream index 한계와 실제 managed extension version을 반영한 [embedding-index-compatibility.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/embedding-index-compatibility.md)을 따른다. 모델 output dimension이 extension ANN limit을 넘는 후보는 vector store를 바꾸거나 exact-only로 두거나 MRL/quantization 대안을 별도 품질 실험한다.

### Reranker 후보

| 후보 | 적용 | 한계 |
|---|---|---|
| [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) | Apache-2.0, multilingual cross-encoder, local top-N reranking; dense/lexical/graph의 통합 후보를 함께 평가 가능 | 문서 후보 수에 비례한 inference 비용. 긴 query/doc truncation과 language/technical domain fit을 확인한다. |
| [Qwen/Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) | Apache-2.0, 100+ 언어, 32K, task instruction; local reranking | 더 큰 model variant는 compute/latency가 커진다. 결과 score 절대값을 relevance 확률로 간주하지 않는다. |
| Cohere [`rerank-v4.0-pro`](https://docs.cohere.com/v2/docs/rerank) | managed multilingual, semi-structured JSON 지원, 32K context | hosted input/privacy/cost/region 계약. Search API 사용량이나 Model Vault 비용을 candidate count에서 산출한다. |
| Cohere [`rerank-v4.0-fast`](https://docs.cohere.com/v2/docs/rerank) | managed fast/throughput variant, 32K; QPS가 높은 query/agent loop 후보 | pro와 동일 품질을 가정하지 않는다. 미리 정한 top-N, 동일 후보 pool에서만 비교한다. |

Reranking은 1단계 검색의 누락을 복구하지 못하므로 `Recall@50/100`으로 후보 누락과 `nDCG@10` rerank gain을 분리한다. DSE의 표/claim 구조는 YAML/JSON의 키 순서를 보존해 rank input에서 필드 손실을 방지한다.

## 추출 모델·규칙 후보

1. **Native parser + AST/rules (기준 우선 경로).** JSON/YAML/CSV/Parquet/SQL schema, HATIR dialect, build manifest, source code는 포맷/문법 parser로 typed field를 읽는다. [Tree-sitter](https://tree-sitter.github.io/tree-sitter/using-parsers/)는 concrete syntax tree를 만드는 여러 언어 parser generator다. Python AST, JSON Schema, unit registry, version comparator, 그래프 제약/용량 룰을 연결해 `source span → canonical value → checked assertion`을 결정론적으로 남긴다. 없는 구조 parser를 바로 LLM에 맡기지 않는다.
2. **OpenAI Structured Outputs, `gpt-6-astra`.** [OpenAI 공식 가이드](https://developers.openai.com/api/docs/guides/structured-outputs)는 최신 모델의 JSON Schema/Pydantic 출력을 지원하고, 현재 모델 안내의 gpt-6-astra 가격은 input $10 / output $50 per million tokens다. JSON Schema 일치가 출처에 맞는 값·수식 정확성을 보장하지 않으므로 출력마다 evidence span, unit, version, `unknown` 상태를 필수화하고 parser/verifier가 사실 검증을 맡는다.
3. **Gemini structured output (`gemini-3.1-pro-preview`).** [공식 모델 페이지](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-pro-preview)는 정확한 ID 및 Structured Outputs 지원을 명시하고, [Gemini API](https://ai.google.dev/gemini-api/docs/structured-output)는 JSON Schema subset 및 Python Pydantic/JS Zod를 지원한다. 표현 subset, empty/unknown/refusal 처리, paid/free data policy, region/retention을 비교한다. 이미지 입력이 있어도 숫자/표 추출은 정확도 gold set으로 따로 통과해야 한다.
4. **Local constrained generation: vLLM + JSON Schema (`xgrammar`/`guidance`) + pinned compatible model.** [vLLM 문서](https://docs.vllm.ai/en/latest/features/structured_outputs.html)는 schema/regex/grammar 기반 구조 출력을 제공한다. 원자료가 로컬 밖으로 나가지 않는 이점과 GPU/TCO/모델 권리/JSON Schema 지원 subset, 기초 모델의 semantic error를 함께 평가한다.

추출 객체 예: `Claim`에는 `subject`, `predicate`, `value_raw`, `value_canonical`, `unit_raw`, `unit_canonical`, `valid_from/to`, `source_id`, `revision`, `page/line/cell/code_span`, `parser/model/prompt_version`, `confidence`, `status={observed|derived|hypothesis|normative|unknown}`, `supports|contradicts`가 필요하다. 값이 없을 때 null을 자동 추론으로 채우지 말고 `unknown`을 보존한다. 같은 `Claim`이 문서 버전/조건에 따라 충돌하면 하나를 덮어쓰지 않는다.

## 재색인·보안·비용

- 원문 blob, checksum, source revision/URL/페이지와 immutable parsed artifact를 보존한다. 재생성 provenance는 `parser + model revision + OCR mode + prompt/schema + normalization + chunk schema + embedding ID/dimensions/precision`으로 고정한다. 문서/페이지/span ID를 vector/graph/answer citation에서 공유한다.
- 문서 변경은 새 `index generation`으로 처리한다. old/new 인덱스를 side-by-side 구축·평가하고 dual-read shadow 결과와 회귀를 확인한 뒤 alias/routing을 원자적으로 교체하고 rollback을 남긴다. 차원이 다르거나 prefix/model space가 바뀐 벡터를 한 index에 섞지 않는다. Query/document formatter, unit-normalizer, graph ontology migration도 색인 버전이다.
- 후보 순위를 결정하기 전 예상 raw pages, 추출 텍스트 tokens, document churn, query QPS, p95 목표, GPU/region/보안 요구와 API retention 계약을 채운다. self-host 비용은 실제 배치/페이지 처리량, GPU 메모리, idle utilization, 운영 인력으로 환산한다. Cloud per-page/token 표는 이 값을 대체하지 않는다.
- 공개 API/프리 tier에 내부 HW/실험자료를 넣지 않는다. OpenAI API는 기본적으로 API 데이터를 모델 학습에 사용하지 않지만 abuse logs는 기본 최대 30일 보존될 수 있다. Google AI Studio 무료 tier는 입력을 product improvement에 사용할 수 있고 유료 tier는 사용하지 않는다고 가격 문서가 표시한다; Vertex AI는 별도 training restriction 안내가 있다. 각 provider/account별 DPA, region, 보존, subprocessor, audit/log, batch 저장, opt-out 권한을 보안팀이 승인해야 한다. [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data), [Vertex AI data governance](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/vertex-ai-zero-data-retention).

## 골드셋·평가 설계

초기부터 하나의 vertical slice를 유지한다: source 취득 → parser/전처리 → typed claim/evidence → lexical/vector/graph 검색 → answer/claim citation → HW legality 또는 HATIR 판단/실험안 → 실제 측정 결과/Melete trajectory·Insight 기록. phase별로 corpus/출처·검증자 수·자동화만 키운다.

1. **도메인 층화와 split.** 최소 질의·근거 유형은 (a) rack/tray/package/SoC의 호환·구성·용량·금지 조건, (b) HATIR fold/unfold/fusion 전제·코드·kernel 선택, (c) LLM workload session/timing, TTFT·TPOT·throughput·power·energy 등의 다변량 실험, (d) Melete 제안/실행/실패/해석/재실험 trajectory, (e) Insight의 근거·적용 조건·반증 가능성이다. 정답에는 근거 문서 revision 및 페이지/행/셀/코드 span, answerable 여부, 필요한 relation/path, 단위 정답, 권위/유효기간을 붙인다. 같은 파일, 거의 중복된 개정본, 같은 실험 run의 결과를 train/query와 test evidence에 교차 배치하지 않는다. Group holdout(문서 family/source)와 temporal holdout(최신 revision/cutoff 이후 publish·update)을 별도로 둔다.
2. **검색 자체.** `Recall@k`, `MRR`, `nDCG@10`, evidence-span precision/coverage를 전체와 5개 도메인, 언어(한국어/영어 혼합), 구조(표/수식/코드/로그), source class/권위/신선도별 보고한다. Sparse only, dense only, hybrid RRF/score fusion, reranker, BGE sparse/ColBERT, graph neighborhood/path retrieval을 동일 qrels에서 한 요소씩 ablate한다. Exact identifier/version/number/unit queries의 성공률을 일반 semantic queries와 합산 평균으로 가리지 않는다.
3. **근거·답변.** 주장별 citation entailment precision/recall(인용 span이 그 주장을 실제로 지지하는가), unsupported factual claim rate, contradictory-source discovery/attribution, `unknown` 질문의 abstention precision/recall과 risk–coverage를 잰다. 표/수식/로그에서 숫자 원문·sign/decimal/exponent·metric 집계-window·실험 조건·단위를 정확히 옮기는 exact match를 보고 canonical unit conversion은 독립 oracle로 검사한다.
4. **부정·적대·접근통제.** 오래된 HW/firmware/toolchain version만 참인 질의, 개정 후 폐기된 값, 같은 이름의 서로 다른 revision, 반대 Claim이 있는 사례, 권위 낮은 출처가 우세하게 검색되는 사례, 근거가 아예 없는 질의를 포함한다. ACL 허용/차단 pair에서 vector, sparse, graph traversal, reranker cache, summary, telemetry 어느 경로로도 금지 문서 제목/값/존재를 유출하지 않는지 검사한다. 문서 본문에 숨겨진 prompt injection, malformed unicode 단위/마이너스, 잘못된 표 셀, chunk 경계 절단, near-duplicate, 허위 인용을 adversarial set에 넣는다.
5. **사용 결과.** 같은 generator/context budget에서 retrieval 단계만 바꾸는 downstream ablation을 별도 보고한다. HW legality에서는 false-allowed와 false-blocked 구성, 근거 추적률; HATIR에서는 후보 compile/verification 통과, 의미 보존, resource/timing 변화; workload experiment에서는 데이터 재현성·모든 metric vector 보존·조건 일치·Pareto 판단; Melete에는 next-experiment 유용성, 중복 run 억제, 실패 원인/insight evidence를 본다. 이를 단일 점수로 합쳐 TTFT와 power 등 metric preference를 강제하지 않는다.
6. **운영 효율.** parse/OCR 정확도와 pages/sec, 임베딩 tokens/sec, rerank documents/sec, ingest backlog, retrieval p50/p95, end-to-end latency, memory/storage/GPU use, 1k page 및 1M token당 비용, re-embed/changed-doc 비용을 함께 기록한다. 평균 비용만으로 품질 회귀를 상쇄하지 않는다.

질문자는 최소 두 명이 독립으로 claim/evidence gold를 판정하고 불일치는 adjudicate한다. 공개 평가 질문과 데이터는 색인/프롬프트 조정용, temporal/group holdout은 최종 확인용으로 분리한다. 문서가 전혀 없는 현 단계에서는 평가 질문과 합성 입력 예만 설계하고, 실제 corpus 수집과 model fine-tuning은 전체 설계 완료 뒤 별도 승인한다.

## 아직 확정할 수 없는 값

수집 소스/문서 수와 라이선스, 실험 log format, DSE 한국어 대 영어 비중, ACL/기밀등급, cloud account 및 approved region, API 계약·retention, GPU/배치 자원, query QPS/latency SLO, 월간 예산이 미정이다. 따라서 후보 점수는 이들 값이 드러나면 바뀐다. 사내 Confluence RAG에서 Supabase·Neo4j를 썼다는 맥락은 보유 권한을 뜻하지 않으므로 이 조사는 그 시스템/콘텐츠를 사용하지 않는다.
