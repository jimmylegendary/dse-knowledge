# Pilot 품질·검색·처리량 평가 계획

> **For agentic workers:** Use superpowers:dispatching-parallel-agents. Root owns live dependencies, verification and publication. No nested delegation.

**Goal:** 고정된 100-source P1을 실제로 평가하고 145,748건 확장의 허용 범위·blocker를 수치로 보고한다. 제품 기능을 확대하는 별도 phase가 아니라 P1 품질 검토다.
**Architecture:** 4fda593의 corpus/claim/decision/usage snapshot을 고정한다. 독립 worker가 source/claim 품질과 검색 partial qrels를 먼저 작성한다. Root는 실제 production retrieval·HTTP·model을 실행하고 결과/비용을 집계한다.
**Tech Stack:** 기존 Python/PG/embedding/Codex/HTTP + advisory Jev, native managed workers.
**Spec:** 사용자의 “평가 ㄱㄱ”; 직전 보고의 자료 적합성·추출 품질·처리량·비용 평가 제안.

## 고정 범위와 판정

- Production corpus/Claim/검색 알고리즘과 model 설정은 평가 중 변경하지 않는다. Benchmark에 맞춰 결과를 수정하지 않는다.
- 모든 gold는 결과를 보기 전에 hash로 고정한다. 24 answerable + 6 unsupported 질의, 9개 category와 한국어/영어를 포함한다.
- Source 100개와 Claim 101개를 전체 audit한다. Jev는 advisory이며 독립 과학 검증 횟수가 늘어나지 않는다.
- 원문 hash/quote offset은 재검사하고 semantic support, DSE 적합성, 조건/단위 보존을 별도로 보고한다.
- 검색의 known-source Hit@1/5/10·MRR, known-chunk Hit, language/category 결과를 보고한다. Partial qrels이므로 전체 relevance recall/precision으로 부르지 않는다.
- Dense/lexical/full hybrid/graph 제외 조합을 같은 query vector와 후보 trace에서 비교한다. Production full hybrid와 별도 ablation을 구분한다.
- Unsupported 질의에서 검색 결과가 있다는 것만으로 오류를 판정하지 않는다. 실제 DSE 답변의 불확실성/허위 주장과 supported-positive 완료를 구분한다.
- 실제 추가 DSE probe는 최대 3개(지원되는 정상 질문 2개, 미지원 질문 1개), 기존 3개 결과도 검토한다. 별도 리뷰에서 최초 3개 probe의 model-visible pos/neg case ID 누출을 발견해 독립평가에서 제외하고, 동일 질문 3개를 모두 kind=knowledge/input={}로 재실행한다(총 추가6호출 중 유효3, 초기3 보존). 재실행 프로토콜은 source/case/rationale/expected label을 model input에 전달하지 않으며 회귀 테스트로 강제한다. 새 feedback으로 gold를 Melete에 학습시키지 않는다.
- 초기 확장 gate(통계적 인증 아님): critical 무근거 성능/feasibility 승인 0, offset 정합성 100%, Claim의 의미 불지지 severe 0, known-source Hit@5 >= 85%, 정상 probe의 지원 범위 답변 완료, 미지원 probe의 적절한 unknown. 미평가나 작은 표본은 보장으로 바꾸지 않는다.
- Host 부하를 확인하고 root retrieval concurrency 1, worker advisory 각각 1로 제한한다. 원문 재수집·재embedding·전체 재추출은 하지 않는다.
- Embedding 비용은 실제 provider usage × 조회한 공식 단가의 추정치로 표시한다. CLI token은 subscription 청구액으로 환산하지 않는다. 실패/timeout의 누락 usage를 별도 표시한다.
- 14만건 선형 외삽은 같은 문서 크기/발췌 정책/동시성 가정의 scenario이며 capacity 약속이 아니다.

## 작업 및 소유 파일

- [x] Root: frozen private snapshot, 계획, 실제 benchmark runner/metrics 단위검증, usage/DB/host profile.
- [x] Source worker: source-quality.json/md, 100개 역할·적합성·category audit, 누락 지식 분석.
- [x] Claim worker: claim-quality.json, decision-quality.json, quality-review.md; 101개 support와 기존3답변 검토.
- [x] Query worker: retrieval-cases.json/notes; 결과를 보기 전 hash, 실제 corpus quote 검증.
- [x] Root: 실제 production 검색/HTTP/3개 이하 DSE probe, ablation·latency·비용·scale 분석.
- [x] 별도 review worker: 고정 gold/분모·누락·한계/결과 과장 검토; root 원자료·실행 출력 재검증.
- [x] Root: README 요약표, 공개 metadata-only evaluation 집계와 재현 script, 테스트·secret scan·GitHub publication. Private 본문·답변·설정은 게시하지 않는다.

완료 보고는 채팅 표로도 제공한다. 낮은 점수는 그대로 보고하고 개선 구현으로 평가를 대신하지 않는다.

## 실행 증거와 결론

고정 system commit 4fda593, private qrels SHA 34bedaf0eb6efe539a5de172f1ffe013e8b8c8364db58c8637714c563797cb6e. Source100·Claim101 검토, 독립 작성30질의와42exactquote 검증, 실제retrieval30·HTTP6 호출 완료. 최초3label-contaminated probe는제외하고입력빈dict·동일knowledge kind의blind3으로교정. 최종2supported/1scopedunknown, 허위B300수치0(작은표본AI보조검토). 부분qrels Hybrid source@5 24/24·source@1 16/24·knownchunk@5 14/24, dense23/24·24/24·10/24. 원문/quote정합101/101. 모든role/verdict/decision/category×role/flaggedcounter를원행에서재계산;source35core/30ops/29method/5navigation/1out. Graph97 weakcomponents, 최대4node. 초기방법오류·수정·실패기록보존. 전체pytest161passed, deprecation warning1. 실제DB/model/검색설정은평가중수정하지않음.

독립리뷰상P1평가결과보고가능,145748전면KG생성은hold. 같은표본분포의artifact132GB가host여유58GB를넘고, 생성quota·대형index·typedDSEknowledgecoverage를아직검증하지못했다. 상세공개표는README와 [evaluation-2026-10-25.json](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/pilot100/evaluation-2026-10-25.json). Public에는metadata와집계만, 원문·vector·workbench답변·credential은private에남긴다. 최종GitHub게시SHA는발행receipt로확인한다.
