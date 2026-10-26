# Frozen retrieval challenge evaluation

2026-10-26: 원문 근거와 질문 label을 먼저 고정한 test 500건 + calibration 100건. 같은 corpus 안의 fresh-query 평가이며 new-document holdout을 주장하지 않는다. Source/intent별 변형 질문은 독립 표본이 아니다.

| 구성 | Test | Calibration |
|---|---:|---:|
| Supported | 300 | 60 |
| Insufficient | 180 | 36 |
| Ambiguous | 20 | 4 |
| 한국어 / 영어 | 250 / 250 | 50 / 50 |
| 정상 난이도 D1 / D2 / D3 / D4 | 각 75 | 각 15 |
| OOD | 50 | 10 |
| Wrong revision | 30 | 6 |
| Unseen feature | 25 | 5 |
| Missing quantity | 20 | 4 |
| Unsupported derivation | 25 | 5 |
| In-domain missing | 30 | 6 |
| Underspecified | 20 | 4 |

파일: [test-v1.jsonl](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/test-v1.jsonl), [calibration-v1.jsonl](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/calibration-v1.jsonl), [case-contract-v1.json](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/case-contract-v1.json), [protocol-v1.json](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/protocol-v1.json), [freeze-v1.json](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/freeze-v1.json).

`evidence_groups` 사이는 AND, 그룹 안 `alternatives`는 OR다. `nearby_evidence`는 관련된 자료를 표시하며 전체 질문의 정답 근거를 뜻하지 않는다. Insufficient는 frozen corpus의 근거 부족이며 세계의 사실이 거짓이라는 label이 아니다. 원문에서 지정한 일부 근거를 qrel로 사용하므로 retrieval miss가 corpus 전체의 무관함을 증명하지 않는다.

## 실제 baseline 결과

[baseline-summary.json](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/results/baseline-summary.json), [baseline-calibration-summary.json](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/results/baseline-calibration-summary.json), [baseline-test.jsonl.gz](https://github.com/jimmylegendary/dse-knowledge/blob/main/research/eval500/results/baseline-test.jsonl.gz).

각 stream의 source/chunk Hit@1/5/10, all-groups Hit@1/5/10, MRR@5/10과 score AUROC/AP, confusion/FPR, intent bootstrap을 포함한다. Ranking 분모는 정상 300건이다. Binary 분모는 supported 300 + insufficient 180 =480, ambiguous 20은 별도 표시한다. RRF proxy는 확률이 아니다. Threshold는 calibration TPR≥0.90인 가장 높은 값이고 test에서는 다시 맞추지 않는다. 진단 gate 미달은 유효한 실험 결과이며 HTTP 실행 실패와 다르다.

최초 100건 attempt는 HTTP 200 응답의 optional `graph_rank=null`을 평가기가 잘못 거부해 무효 처리했다. 이 attempt를 검색 품질 0이나 검색 실패 100건으로 세지 않았다. 호환 수정 후 새 journal로 calibration 100건과 test 500건을 오류 없이 실행했다. Preflight와 무효 attempt는 query cache를 예열할 수 있으므로 HTTP 시간은 cache·외부 provider 상태를 포함한 관측값이며 latency SLA가 아니다.

## 재실행

이 저장소의 dependency 설치와 실제 corpus/API 연결이 필요하다. 다음 명령은 calibration과 test를 순서대로 실행한다. 새 owner-only 출력 경로를 사용하며 기존 journal을 덮어쓰지 않는다.

```bash
python scripts/evaluate-retrieval-confidence.py --stage calibration --cases research/eval500/calibration-v1.jsonl --journal /absolute/private/path/calibration.jsonl --threshold-output /absolute/private/path/threshold.json --corpus-manifest-sha256 4de7a9d2b59dad4ae31bb4a33c20ce9e4ebfa113f647111211d747eb2f56179d --base-url http://127.0.0.1:8080
python scripts/evaluate-retrieval-confidence.py --stage test --cases research/eval500/test-v1.jsonl --journal /absolute/private/path/test.jsonl --threshold-input /absolute/private/path/threshold.json --corpus-manifest-sha256 4de7a9d2b59dad4ae31bb4a33c20ce9e4ebfa113f647111211d747eb2f56179d --base-url http://127.0.0.1:8080
```

Corpus가 달라지면 gold의 revision/chunk binding을 다시 검증해야 한다. 위 manifest hash를 새 corpus에 임의로 붙이지 않는다. 공개 metadata journal의 SHA는 summary에 기록돼 있으며 gzip을 해제한 payload 기준이다. 정본 원문 본문·모델 응답 본문·생성 문맥·embedding vector·API credential은 공개하지 않는다.
