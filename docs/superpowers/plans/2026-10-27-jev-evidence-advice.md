# Jev evidence advice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 DSE workbench의 검색과 실제 decision에 Jev 근거 판단 보조를 연결하고 calibration 100건/test 500건으로 효과와 한계를 공개한다.

**Architecture:** PostgreSQL/기존 contextual retrieval/Qwen reranker를 유지한다. 별도 Jev advisor를 search response와 실제 최종 decision evidence에 연결한다. 자료·검색 순위·정답을 변경하지 않는다.

**Tech Stack:** 기존 Python/FastAPI/PG, shared decision-model general profile typesafe/jev-1.13, 기존 eval500 runner와 HTML report.

**Spec:** [2026-10-27-jev-evidence-advice-design.md](/home/jimmy/.paseo/worktrees/06af7m2w/contextual-retrieval-rerank/docs/superpowers/specs/2026-10-27-jev-evidence-advice-design.md)

## Global Constraints

- Neo4j, ontology 재설계, 다른 프로젝트, GPU/weight download는 범위 밖이다.
- Worker는 지정 파일만 수정하며 root 외 commit/DB/credential/API/provider/배포를 하지 않는다. 별도 위임 금지.
- Jev state 24,000 UTF-8 bytes/request 30,000 bytes, 최대 12 primary excerpts. 질문과 required_rules는 절단하지 않는다.
- Advice는 citation/validation/action permission이 아니다. deterministic reject/incomplete와 기존 citation 검증을 보존한다.
- 순위는 그대로이며 새 score는 `jev_direct_support_proxy`, 별도 advice mode identity를 사용한다.
- test gold는 구현·정책 선택 입력으로 사용하지 않는다. calibration 후 policy/threshold freeze, test 후 재튜닝하지 않는다.
- User가 이미 구현·시험·self-host·GitHub 결과 게시 workflow를 승인했다. 작업 완료 전 중간 승인 요청 없이 진행한다.

## Review Focus

- 한국어 multi-byte 질문/원문, 초대형 필수 규칙에서 명시적 byte 경계와 정보 생략 기록.
- advisor 장애·모델 불일치·잘못된 확률에도 existing search/decision이 동작하며 false validated 상태를 만들지 않음.
- source prompt injection 및 조건/수치/ISA 불일치를 advisor가 인증으로 승격하지 않음.
- Codex prompt fitting 이후 advice를 추가해 evidence identity나 전체 budget을 깨뜨리지 않음.
- calibration/test journal·threshold의 advice mode identity, 오류 분모, source/body 비공개, old baseline 호환.

## Task 1: 실제 검색·decision Jev 통합

**Owner:** contextual_rerank_builder. **Files:** 새 `src/dse_knowledge/jev_advice.py`, `tests/test_jev_advice.py`; 수정 `app.py`, `config.py`, `decisions.py`, `tests/test_api.py`, `tests/test_decisions.py`, `deploy/config.env.example`.

**Interfaces:** `JevEvidenceAdvisor(settings).assess(query, evidence, *, kind='knowledge', required_rules=None) -> dict`. design의 envelope와 SearchBody.evidence_advice 계약을 그대로 구현한다. 기존 create_app/DecisionEngine positional 호출을 유지한다.

- [ ] 실패 테스트: bounded Unicode projection·question/rules intact·cache identity·명시적 condition mismatch와 조건 누락 구분·malformed model/probability·timeout/no fallback·safe metadata.
- [ ] 위 테스트가 기능 부재 때문에 실패함을 실행·기록한다.
- [ ] Provider adapter와 API opt-in/override/capability, final-evidence decision advice/snapshot/prompt budget을 구현한다.
- [ ] 검색 순위/원문 불변, disabled/실패 fallback, 실제 citation/mandatory reject/incomplete 우선순위 테스트를 실행한다.
- [ ] 담당 focused tests를 실행하고 명령·결과·파일 범위·남은 사항을 report한다. commit은 root 담당이다.

## Task 2: Advice-aware 평가 계약

**Owner:** quality_v2_retrieval. **Files:** `scripts/eval500_metrics.py`, `scripts/evaluate-retrieval-confidence.py`, `tests/test_retrieval_confidence.py`, `tests/test_evaluation.py`만.

**Consumes:** Task 1의 `evidence_advice` response envelope. **Produces:** 기존 runner의 `--evidence-advice off|jev`(기본 off), `--score-name jev_direct_support_proxy`, advice mode가 포함된 journal/threshold identity와 안전한 result projection. 기존 four modes/scores/old artifact는 계속 읽을 수 있다.

- [ ] 실패 테스트: advice score schema/범위/status, advice mode와 threshold mismatch, 0/0·unavailable case의 실행 분모와 valid-assessed semantic 분모 분리, body 없는 공개 projection. unavailable/skip은 score=null이며 정상 0점과 구별한다.
- [ ] 기대 실패를 실행·기록한다.
- [ ] 새 score/mode와 operational counts를 구현한다. actual action은 기존대로 not_evaluated이며 advisor choice와 구분한다. ranking은 unchanged items로 계산한다.
- [ ] calibration에서만 threshold를 선택하고 test에서 frozen identity를 검증한다. existing off defaults와 기존 summary 계약 회귀를 확인한다.
- [ ] focused tests와 파일 범위·명령·결과를 report한다. gold·실제 provider·DB·배포·commit은 root 담당이다.

## Task 3: Root 실제 평가·UI·공개·배포

**Owner:** root. **Files:** review/spec/plan/ledger, UI에 필요한 기존 search/decision rendering, 새 comparison report generator/test 및 `research/eval500/results/jev-*` 본문 제거 결과, `static` report의 실제 위치, README. Worker 지정 파일은 담당 완료 전 수정하지 않는다.

- [ ] Task 1·2 독립 리뷰와 필요한 fix loop 후 root가 전체 pytest를 실행한다. baseline: 581 passed/1 known warning.
- [ ] 실제 shared Jev 소규모 smoke와 같은 corpora의 preview HTTP를 준비한다. 기존 8080은 실제 검증 완료 전 유지한다.
- [ ] 100 calibration을 실제 실행하고 threshold/policy/source hashes를 동결한다. concurrency는 host를 관측하며 최대 2, retry/fallback 없이 cache/resume 사용.
- [ ] 500 test를 실제 실행하고 baseline 공개 artifact와 독립 집계한다. 오류·skip·표본·비용 상한을 숨기지 않는다.
- [ ] actual supported/missing decision과 required-rule E2E, snapshot·gap·Melete 상태를 확인한다. 500 생성 답변 평가라고 주장하지 않는다.
- [ ] 비교 HTML과 UI advice 표시, README·공개 결과를 생성하고 privacy/hash/link 검증을 한다.
- [ ] 최종 리뷰·검증 후 root commit/push, 승인된 self-host runtime에 반영하고 health/capability/search·기존 경로 회귀를 확인한다.
- [ ] Hit/MRR, grey/OOD/missing, 오류·지연·비용과 quality gate의 실제 pass/fail을 한국어 표로 보고한다.

## 완결 제품 gate와 상한

| Capability | 기존 | 이번 increment 종료 |
|---|---|---|
| 자료→근거→graph | 실제 기존 흐름 | 유지·회귀 |
| 검색 | contextual+rereanker | 같은 검색 + Jev excerpt advice + UI |
| HW/kernel/실험 의사결정 | Codex+근거+기계 규칙 | 최종 evidence의 Jev advice를 추가하고 규칙 우선 유지 |
| Feedback/Melete | 실제 outbox/receipt | advice를 포함한 audit snapshot과 기존 전달 유지 |
| 평가·운영 | 공개 500+HTML/self-host | 실제 Jev 100/500 비교+E2E+공개 HTML/self-host |

미루는 것: Neo4j, 전체 semantic ontology 확장, native HAT simulation, 14만 자료 용량 검증, 500개 생성 답변의 독립 의미 평가.
