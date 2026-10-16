# DeploymentProfile v1: public pilot과 internal의 단일 기준

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
