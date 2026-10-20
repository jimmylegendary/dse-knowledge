# DeploymentProfile: host-dev와 자료별 접근 기준

2026-10-21 사용자 선택: **기존 Supabase + 현재 Linux host**를 dev 환경으로 사용한다. AWS를 사용하지 않는다. 모델은 OpenRouter 또는 Codex를 interface·env로 선택하며 초기 GPU·API key 발급은 요구하지 않는다. 아래 `host-dev-v1`이 현재 배치 기준이고, 과거 public-pilot/internal 표는 자료 유형에 따른 접근 조건의 참고다. 실제 project 연결·서비스 설정·runtime은 아직 수행하지 않았다.

| host-dev-v1 항목 | 현재 설계 기준 | 미확정·조건부 |
|---|---|---|
| 지식 정본·index | 기존 계정의 Supabase PostgreSQL, pgvector/FTS·PG typed graph 후보 | 실제 project·DB namespace·연결 방식·extension 확인은 나중에 수행 |
| 실행·artifact | 현재 Linux host의 CPU worker와 local artifact directory | 작업 동시성·RAM/disk 한도·별도 backup 위치를 상세 설계 |
| 모델 | OpenRouter HTTP 또는 Codex CLI provider interface·env | model ID·실행 사용자별 인증·실제 연결은 미확인 |
| Embedding/reranker | provider capability를 별도 정의하고 CPU 경로 포함 | chat 모델을 embedding API로 취급하지 않음. GPU는 초기 필수 아님 |
| 노출 범위 | 개발 서비스는 loopback 접근을 출발 제안으로 둠. Supabase 연결은 인증된 TLS 경로 | 외부 API/UI 공개가 필요해지면 별도 인증·접근 경계 설계 |
| Secret | 실제 값은 env/로컬 인증 interface에서 후속 연결. 문서·public GitHub에는 변수명·참조만 | root credential·새 PAT·AWS credential을 준비물로 요구하지 않음 |
| 조건부 서비스 | Neo4j·별도 vector DB·GPU·remote artifact store는 초기 의존성이 아님 | 지식·질의·자원 평가에서 필요성이 확인될 때 검토 |

서비스별 준비 항목·env 이름은 [infra-and-credential-requirements.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/infra-and-credential-requirements.md), 상위 설계는 [2026-10-21-dse-knowledge-architecture.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/superpowers/specs/2026-10-21-dse-knowledge-architecture.md)를 따른다.

## 자료별 접근 조건 참고

상태: 설계·설정 계획. 실제 cloud 설정은 수행하지 않는다. 이 문서가 추천서와 cloud 조사 문서에 흩어진 network/edition 규칙보다 우선한다. Source 권리·artifact ACL과 network 노출은 서로 다른 조건이다.

| 항목 | public-pilot-v1 | internal-v1 |
|---|---|---|
| 자료 | 공개적으로 접근 가능하고 의도한 수집·처리 용도가 허용된 source, synthetic fixture | 명시적으로 허용된 내부/기밀 source와 동일한 권리·ACL 계약 |
| DB/search endpoint | 인증된 TLS public managed endpoint 허용. Public routing은 anonymous access를 뜻하지 않음 | 승인된 private endpoint/VPC 경로 또는 적용 조직 정책이 허용한 동등 통제 |
| 인증/권한 | service identity, 최소 권한, secret store, source/namespace ACL, deny-by-default | 동일 + 조직이 요구하는 SSO/RBAC/tenant 경계·감사 |
| Network 제한 | provider가 제공하는 allowlist/egress 통제를 적용하고 제공 범위를 manifest에 기록. Anonymous admin/API 금지 | private routing·DNS·egress·접근 주체를 실제 지원 edition에서 확인. 실패 시 public 경로로 자동 fallback 금지 |
| 외부 embedding/LLM API | source의 허용 용도와 provider 데이터 처리 조건을 만족하는 자료만 전송 | 내부 자료의 외부 전송 권한·residency·계약 조건을 확인한 경우만 허용 |
| 허용 edition | 인증/TLS/ACL/backup/export 요구를 충족하는 pilot tier. Private endpoint 지원은 일률적인 필수 조건 아님 | 필요한 private endpoint·RBAC·감사 기능을 제공하는 edition; marketing feature 이름만으로 통과하지 않음 |
| 비용 | account/region/SKU·document/query/retry 비용·명시 spending cap 필요 | 동일 + private connectivity·enterprise/replica/egress/운영 비용 |
| 현재 상태 | profile 명세만 작성; account·region·spending cap 미설정 | 활성화하지 않음; 내부 source/조직 authority 미제공 |

## 적용 규칙

1. DeploymentManifest가 `profile_id/version`, source classes, provider/region/edition, endpoint exposure, identity/ACL, API egress, budget, backup/restore evidence를 명시한다.
2. 각 resource는 이 profile의 필수 기능을 실제로 지원하는지 확인해야 한다. 관리형 제품의 최저 가격이 필요한 모든 기능을 포함한다고 가정하지 않는다.
3. Profile 변경은 별도 reviewable configuration revision이다. 내부 source를 public-pilot에 추가하거나 private 연결 장애를 public network로 우회하지 않는다.
4. Security/finance/org 승인은 적용되는 조직 정책이나 source 조건이 요구하는 경우에만 추가한다. 개인 public pilot에 존재하지 않는 승인 주체를 만들어내지 않는다.
5. B300 native asset/adapter 지원 여부는 cloud와 별개의 gate다. Cloud account가 없어도 pinned source/fixture 확인과 계약 정리는 계속한다. 반대로 cloud 계정이 있어도 native episode 미지원이 해결됐다고 보지 않는다.

## P1 순서

P0에서 pinned source·fixture·native status 계약과 expected oracle를 고정한다. 전체 설계·계획 검토 후 P1의 첫 작업은 허용된 isolated execution site에서 지원 component probe와 adapter conformance를 확인하는 것이다. B300 target의 미지원 조건을 해소할 계획·evidence가 없으면 B300 성공 판정을 하지 않는다.

Cloud 정본/수집/검색/UI의 본격 구축은 이 통합 preflight 결과를 입력으로 진행한다. 최소 local/ephemeral contract harness가 필요할 수 있으나 P0에서는 구현하지 않는다. Cloud 권한 부족 때문에 원문 조사·typed contract·fixture gold까지 blocked로 표시하지 않는다.

## 설정 전 필수 입력

Billing owner, region/SKU, non-null spending cap, source processing authority, HAT/Melete execution site, required endpoint features, retention·RPO/RTO를 DeploymentManifest에 넣는다. 미설정 필드는 현재 계획에서는 `planned/blocked`로 보존하며 실제 apply를 실행하지 않는다.

Cloud 후보·가격 산식은 [03-cloud-operations.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/research/03-cloud-operations.md), 최초 episode의 gate는 [p1-first-episode.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/episodes/p1-first-episode.md)를 따른다.
