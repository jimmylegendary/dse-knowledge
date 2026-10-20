# P0 보완: 최초 DSE episode와 판정 계약

기준: 공개 저장소 `2a460a0`에 대한 사용자 검토. 보완 branch: `docs/p0-episode-contracts`. 이 작업은 문서·schema·합성 gold·원자료 정정이다.

**판정 계약과 정정 산출물은 검토 가능한 상태다. 전체 P0의 B300 target episode binding은 완료되지 않았다.** 지정 revision에는 B300 twin과 요청한 전체 native chain이 없으며, B200/SmolLM2 probe로 대체하지 않았다. 제품 구현·HAT/Melete runtime·cloud 설정은 수행하지 않았다.

## 1. 이번에 고정한 판정

아래는 승인된 실행 범위와 활성화된 profile이 주어진 경우의 **expected gold**다. 현재 P0의 실제 실행 authority는 denied이며 native 실행 결과를 관측한 표가 아니다.

| 입력/반례 | 고정한 판정 |
|---|---|
| simulation_ready=true + 전원 abstain + strict blocking review | incomplete_unknown / all_abstain / denied; buildability 성공 아님 |
| 같은 abstain이나 profile이 review gap을 비차단으로 선언하고 모든 execution/semantic check와 bounded assumption 충족 | exploratory_only; validation은 incomplete_unknown이고 검토 미완료를 보존 |
| backend=None deterministic fallback | 실제 agent review로 집계하지 않음; 미호출과도 구분 |
| Required DSE-R13 fail, narrative summary에는 앞 12개만 있음 | reject / denied; complete rule 집합은 top-k와 독립 |
| source_verified hypothesis | hard_constraint·verified_parameter로 승격 금지; 조건에 맞는 advisory 용도만 허용 |
| Melete stored/duplicate/trace_only와 pending/incomplete flags | 저장·추출·embedding·visibility를 별도 기록; duplicate의 독립 증거 증가 0 |
| Fresh readout의 query ID·권한·scope·memory/version·snapshot 불일치 | visibility 근거로 인정하지 않음; DSE 적용 차단 |
| Scalar hint는 match하나 DSE range/version predicate는 false/unknown | 후보 이력은 보존하되 full predicate로 적용 거부/보류 |
| Required metric 누락·constraint 위반·bound 중첩 | incomplete / infeasible / inconclusive를 구분; 전체 우월 주장 금지 |
| tolerance를 허용 악화로 해석해 순환하는 세 후보 | 고정 non-worsening + strict improvement 규칙에서는 순환 없음 |
| Oracle 결과·future state를 realizable online 결과로 전달 | profile 또는 information-access 위반 |
| 같은 실험/Insight 재유입 또는 현재 지식 재해석 | 원래 lineage 유지; 새 독립 실험으로 계산하지 않음 |

상세 기준은 [integration-state-map.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/integration-state-map.md), [validation-and-claim-use.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/validation-and-claim-use.md), [comparison-policy.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/comparison-policy.md), [snapshot-contract.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/snapshot-contract.md), [melete-state-and-applicability.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/contracts/melete-state-and-applicability.md)다.

ValidationProfile 두 개는 frozen **synthetic aggregation oracle**다. 입력 schema의 example.invalid refs와 supplied rule_results를 실제 native validator로 착각하지 않도록 activation_status를 분리했다. 실제 activation에는 schema·rule·predicate·evaluator의 version/content hash resolution이 필요하다. Comparison fixture의 1000W/0.99 등도 합성 threshold이며 사용자 budget이나 B300 제약이 아니다.

## 2. 최초 episode에서 확인한 사실과 한계

| 항목 | 구체 binding | 상태 |
|---|---|---|
| 사용자가 원하는 target | NVIDIA B300, 전체 HW 계층과 session→kernel→RP→Melete 흐름 | blocked |
| 별도 구조 진단 fixture | DGX B200 x8 resource tree + SmolLM2-135M-Instruct | source_verified / runtime not_run |
| Model revision | `12fd25f77366fa6b3b4b768ec3050bf629380bac` | pinned multi-model lock의 /models/0 |
| Diagnostic shape | 9-token prefill + 1-token decode, 30 layers, hidden 576, vocab 49152, meta/dummy | Native test assertions의 입력; 실제 device 성능 아님 |
| HW scope | rack switch→tray fabric→8 memory/compute branches | package/SoC/die 전체 조립·legality 입증 없음 |
| vLLM source | v0.26.0, `568afb3a13806beb53bb2e6bd518269357b237c0` | runtime_image/vllm-source.lock.json과 일치 |
| Image/model artifact | image digest, 개별 model file checksum/weights identity | unbound/unknown; 임의 hash 생성 안 함 |
| Kernel/RP | fold/unfold/fusion 관련 component와 state API는 존재 | 같은 session의 통합된 native lane·snapshot 충분성 미입증 |
| Melete | Engine/CognitionKernel/CLI의 ingest/read 계약과 request binding | source 확인만; 실제 ingest/query 실행 없음 |

SmolLM2 lock 인용은 파일명만 보고 틀렸다고 판단하지 않았다. `qwen36-model-sources.lock.json`은 실제로 SmolLM2를 포함한 multi-model lock이며, 원문과 JSON pointer를 확인했다. 없는 checksum은 추가로 추정하지 않았다.

정확한 entrypoint·source line·artifact·미연결 adapter I/O는 [p1-first-episode.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/episodes/p1-first-episode.md), [episode-manifest.json](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/fixtures/p0/episode-manifest.json)에 있다. [episode-cases.json](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/fixtures/p0/episode-cases.json)의 target positive requirement는 blocked_unbound이며 평가 완료 분모에 몰래 포함하지 않는다.

## 3. 확인된 조사 정정

- BFCL: Berkeley 공식 leaderboard→ShishirPatil/gorilla→재현 commit `f7cf7359b7ac615a0b294831c5ba2bc95ee4a000`으로 수정했다. URL 문자열 일치와 authority 확인을 구분했다.
- Embedding input: source 40M/800M/12B를 overlap 포함 **45.12M/908.8M/13.664B**로 계산한다. N=0, N<overlap인 짧은 문서도 별도 gold로 고정했다. 문서 Batch·실시간 query·retry/re-embedding 비용을 분리했다.
- Index compatibility: pgvector의 vector ANN 2000 / halfvec ANN 4000 한계를 모델·출력 차원·dtype·index·distance·managed extversion과 결합했다. 2048차원 vector ANN Yes 오류도 수정했다. Qwen8B 기본4096을 기본 ANN에 바로 넣지 않으며 축소/half precision은 품질 gate가 필요하다.
- Network: [deployment-profiles.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/deployment-profiles.md)를 public-pilot/internal의 단일 기준으로 정했다.
- Graph: [0001-graph-backend-selection.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/adr/0001-graph-backend-selection.md)에서 PG typed graph baseline과 동일 질의 Neo4j challenger를 고정했다.
- Research JSON: schema_version, evidence_stage, nullable assessment_confidence, 구조화된 claim/source revision/locator/evidence를 구분했다. 기존 미기록 locator는 prior_review_unlocated로 남겼으며 새로 검증한 것처럼 표시하지 않았다.

## 4. 실제 정적 검증

검증 시각: 2026-10-16 21:32:35 UTC. 실제 결과는 [p0-verification.json](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/p0-verification.json)에 기록했다.

| 검증 | 실제 결과 | 의미의 한계 |
|---|---:|---|
| Draft 2020-12 schema 자체 | 7개 유효 | runtime conformance 아님 |
| Research catalog / 후보 / CSV | 5개 / 113개 / 113행, 오류 0 | 사전 평가와 source metadata의 정합성 |
| Evidence record | 199개 | 102개 후보는 prior_review_unlocated, E1 10개, proposal 1개 |
| 공통 oracle envelope·ID·permission enum | 103개, 오류 0 | 103개 실제 실행 성공이라는 뜻 아님 |
| Frozen validation profiles / ClaimUsePolicy | 2개 / 1개, schema와 canonical digest 일치 | synthetic profile activation은 미완료 |
| Comparison 계산 | 15개, 순서 변경 41회, 오류 0 | 합성 값의 규범 산식 검산 |
| Invalid comparison policy | 7개 예상대로 거부 | bound·unit/ID/registry 검사 |
| Snapshot | 목적 template 3개, 의미 사례 13개, 오류 0 | 실제 artifact replay 아님 |
| Melete query binding | confirmed 4개와 identity/auth negative 6개 정합 | 21개 전체 fixture schema 유효; 실제 query 아님 |
| 비용 / index 경계 | 12개 / 9개, 오류 0 | 운영비·검색 품질 실측 아님 |
| Native source parity | twin hash·model revision/files·vLLM source 4개 확인 | code/fixture reading, runtime 미호출 |
| Oracle lock | 15개 artifact hash 일치 | 구현 출력으로 expected를 바꾸지 않도록 고정 |
| Phase coverage | 11영역×5phase = 55칸 유지 | 각 phase 실행 완료가 아님 |

원문은 `git show <pin>:<path>`로 읽었고, static checks는 context-mode Python에서 `jsonschema.Draft202012Validator`, `Decimal`, `hashlib.sha256`, JSON/CSV 대조로 수행했다. Comparator/snapshot 산식은 임시 sandbox에서 검산했으며 제품 engine/module로 작성하거나 저장하지 않았다. HAT/Melete runtime·제품 test·cloud provisioning은 **0회**다.

Oracle 구성: validation 14, Melete 21, comparison 15 + policy negative 7, snapshot 13, cost 12, index 9, episode boundary 12 = 103개. 내용과 schema hash는 [oracle-lock.json](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/fixtures/p0/oracle-lock.json)에 고정했다.

## 5. 독립 review와 범위

서로 다른 worker가 native contracts, cost/source/index 정정, comparison/snapshot, 첫 episode를 교차 검토했다. Root가 원문·digest·산식·request binding을 다시 확인했다. Review에서 발견한 raw/projection 혼동, policy/digest 누락, ClaimUse 예시 충돌, snapshot closure/time/independence, request identity 누락, 짧은 문서 chunk 계산, 2048차원 ANN 오류를 수정했다. Native 미지원 사항은 성공으로 바꾸지 않고 blocker로 남겼다.

## 6. 다음 작업과 완료 경계

| 작업 | 현재 상태 | 막히는 범위 |
|---|---|---|
| 판정표·schema·합성 gold·조사 정정 | verified_static / source 확인 | 코드·runtime 성공으로 승격 불가 |
| Target B300 asset/전체 hierarchy/primitive support 고정 | blocked | B300 positive input binding |
| Capture→kernel/recipe→RP→Melete 전체 adapter 연결 | planned, native integrated lane 미확인 | 실제 integrated episode |
| 실제 diagnostic image/model file identity와 test site | unbound / not_run | 재현 가능한 component execution |
| Cloud account/region/spending cap | 미제공 | 실제 provisioning·유료 실행 |
| Source/계약/fixture 검토 | 계속 가능 | 위 운영 blocker와 독립 |

현재 패키지를 곧바로 **전체 구현 완료 가능 상태**라고 인계하지 않는다. P1은 native-first preflight로 순서를 바꾸었고, 필요한 target 입력·지원이 확보될 때까지 B300 acceptance는 닫혀 있다. 다음 AI는 [AGENTS.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/AGENTS.md)와 [handoff.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/handoff.md)의 mode와 lane별 완료 기준을 따른다.
