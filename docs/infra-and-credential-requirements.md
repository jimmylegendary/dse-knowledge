# Infra 및 credential 준비 요구사항

상태: **design-only configuration contract**다. Config loader와 provider adapters는 구현되지 않았다. 계정·credential을 조회하거나 설정하지 않았고, 제품 코드·service·backup을 만들거나 실행하지 않는다. 이 문서는 비밀 아닌 결정, 이후 필요한 역할과 `secretref`, 조건부 자원을 나눈다. Secret 값은 chat이나 public repository에 적지 않는다.

## Baseline과 현재 결정 상태

Baseline proposal은 **기존 Supabase 계정의 managed PostgreSQL + pgvector + PostgreSQL FTS**와 **사용자가 이미 보유한 Linux host의 CPU worker**다. Artifact와 model cache는 owner가 정할 local path에 둔다. Off-host object storage, durable workflow service, Neo4j, GPU, hosted model call은 현재 필수가 아니다. Chat provider는 OpenRouter 또는 Codex CLI로 설정하고, embedding/reranking은 별도 provider interface와 CPU-local 경로를 둔다. Chat endpoint를 embedding/rerank endpoint로 자동 대체하지 않는다.

아래 host 수치는 master의 2026-10-21 read-only 관찰값이며 host ID와 개인 경로는 기록하지 않았다. 이는 throughput·배포 성능·전용 가용량 측정이 아니다.

| 항목 | 확정된 방향·관찰 | 미정 또는 의미 |
|---|---|---|
| 실행 host | 기존 Linux host 사용. 2026-10-21 관찰값은 logical CPU 16, memory total 27.2 GiB, available 16.6 GiB, workspace filesystem free 98.8/936.8 GiB. 초기 `DSE_CPU_WORKERS=2`와 `DSE_BIND_HOST=127.0.0.1`은 template용 proposal이다. | 배포판/version, service manager 지원, dedicated service user, artifact·cache·backup용 실제 mount와 quota는 미확인. Disk free는 backup 전용 여유분으로 간주하지 않는다. 동시성 제안은 성능 측정이 아니다. |
| Cloud | AWS와 cloud account는 baseline에 쓰지 않는다. | 향후 off-host storage/backup이 필요해져도 별도 선택 전에는 cloud 자원이나 권한을 요구하지 않는다. |
| Supabase | 기존 계정 사용 방향. `SUPABASE_DB_SCHEMA=dse_knowledge`, `DSE_NAMESPACE=dev`는 template에 넣을 미확정 제안값이다. | Account 존재가 특정 project 사용 허가를 뜻하지 않는다. project ref, 신규/기존 project 선택, DB 연결 경로와 인증 방식은 미정이다. |
| Chat | OpenRouter 또는 Codex CLI를 provider interface 뒤에서 선택한다. | 실제 provider, endpoint, model ID, 인증 방식은 미정. OpenRouter API key 발급·전달은 지금 요청하지 않는다. Codex CLI 0.163.0이 설치된 사실과 `exec`/`login` 명령 존재만 관찰됐고 login 상태·entitlement·model 호출은 확인하지 않았다. |
| Embedding/reranking | Chat과 분리한 interface 및 CPU-local 대안을 둔다. Template allowed values는 `local_cpu`/`remote_embedding`와 `local_cpu`/`remote_reranker`/`disabled`로 제안한다. | Provider/model/dimension은 미정. OpenRouter는 별도 embeddings·rerank API를 문서화하지만 각 모델의 지원·권리·비용·DSE 품질은 선택 후 확인한다. CPU throughput도 아직 측정하지 않았다. |
| GPU | 지금 필요한 조건이 아니다. | Self-hosted model이나 simulation이 CPU 경로의 평가 목표를 충족하지 못할 때만 host/GPU 사용 여부를 재검토한다. 구매·대여 요청은 없다. |
| GitHub | 현재 `gh` publication 경로를 사용할 수 있다. | PAT를 다시 요청하지 않는다. 향후 CI 설정에 필요한 repo/environment 권한은 workflow 결정 뒤 별도로 검토한다. |
| Budget·source 권한 | Budget 답은 미정 상태로 유지한다. 사내 Confluence, 기존 회사 Supabase/Neo4j 또는 licensed standards access는 제공된 것으로 보지 않는다. | 금액을 추정하지 않는다. 내부 source/기존 DB 연결은 owner·namespace·read-only 범위를 별도로 허가받은 뒤에만 검토한다. |

## 실제 연결 단계에서 owner가 채울 비밀 아닌 설정

아래는 사용자가 지금 다시 답해야 하는 질문이 아니다. 실제 연결을 승인하고 준비할 때 owner가 `.env.example`의 blank settings를 채운다. 미정값은 비워 두고 credential은 전달하지 않는다.

| 설정 | 연결 때 채울 값 | 목적 |
|---|---|---|
| Supabase 경계 | Supabase project ref, 새 project를 만들지 기존 project의 승인된 별도 schema를 쓸지, namespace. `dse_knowledge`/`dev`는 template default proposal일 뿐이다. | 기존 project 권한·data와 분리하고 source/claim/run 경계를 정한다. Project ref와 schema 이름은 secret이 아니다. |
| DB 접속·auth route | Direct PostgreSQL/pooler 선택, `postgres_role` direct connection + grants 또는 Data API + Auth JWT/RLS 선택. DB URL secret reference를 쓰면 host/port/name은 중복 입력하지 않는다. | DB connection string, auth/RLS, 개발·runtime role을 분리한다. Split-field route에서만 host/port/name을 받고 Supabase Connect 화면에서 읽는다. |
| Linux 실행 방식 | Host 배포판/version을 사용자 측에서 확인하고, native systemd service 또는 rootless Podman + systemd 중 승인할 운영자 경로; service UID/GID의 owner | root login 없이 worker를 운영한다. Host를 대신 조회하거나 service를 설치하지 않는다. |
| Local data layout | raw input, derived artifact, model cache, logs, backup의 경로 placeholder와 각각의 quota; backup이 같은 disk인지 별도 mount인지 | 관찰된 98.8 GiB free space를 source/model/backup이 함께 차지한다고 전제하지 않는다. 값과 retention은 owner가 정한다. |
| Exposure 범위 | local-only, 승인된 LAN/VPN, 또는 TLS reverse proxy 뒤의 정해진 client 범위 중 선택 | Default proposal은 loopback/local-only다. Network bind, firewall, proxy/auth 경로는 선택 전 열지 않는다. |
| Model interface | Chat provider `openrouter`/`codex_cli`/`unset`; embedding `local_cpu`/`remote_embedding`/`unset`; reranker `local_cpu`/`remote_reranker`/`disabled` 중 설정 가능하게 둔다. | Interface/env 이름만 정한다. API key, Codex access token, OAuth/session file의 값은 지금 발급·전달하지 않는다. |
| Source·보존·비용 | 우선 synthetic/public-authorized source인지, internal connector를 나중에 신청할지; backup disk/retention 목표 | Budget은 답이 없으므로 다시 요구하지 않고 미정으로 남긴다. Paid API, off-host backup 또는 production 조건이 생길 때 비용을 공식 단가와 실제 사용 가정으로 계산한다. |

## Interface와 environment variable 이름 초안

아래는 코드에 구현된 환경변수가 아니라 설정 계약의 제안이다. Variable name과 allowed values만 정하고, 값은 선택된 경로의 non-secret 설정이나 secret reference로 연결한다. [.env.example](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/.env.example)은 design-only skeleton이며 actual secret env values는 blank다. `*_REF=env:VARIABLE_NAME`은 template의 제안 mapping syntax이고, secret manager 내부 reference URI는 아직 정하지 않았다.

| 영역 | 제안 이름 | 의미·경계 |
|---|---|---|
| Supabase connection | `SUPABASE_PROJECT_REF`, `SUPABASE_DB_MODE`, `SUPABASE_AUTH_MODE`, `SUPABASE_DB_SCHEMA`, `DSE_NAMESPACE`; split-field route일 때만 `SUPABASE_DB_HOST/PORT/NAME` | `SUPABASE_DB_MODE=direct|pooler_session|pooler_transaction|unset`; `SUPABASE_AUTH_MODE=postgres_role|data_api_rls|unset`. Template proposal은 `SUPABASE_DB_SCHEMA=dse_knowledge`, `DSE_NAMESPACE=dev`다. |
| Supabase credential | `SUPABASE_DB_URL_REF=env:SUPABASE_DB_URL`; split-field route일 때 `SUPABASE_DB_PASSWORD_REF=env:SUPABASE_DB_PASSWORD`; Data API path일 때 `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY_REF=env:SUPABASE_PUBLISHABLE_KEY` | DB URL ref를 설정하면 host/port/name/password fields가 불필요하다. Otherwise secret DB password ref만 추가한다. Actual secret env values는 `.env.example`에서 blank다. `SUPABASE_SECRET_KEY`는 RLS bypass admin task를 별도 승인한 경우에만 다루고 권장/default key로 두지 않는다. |
| Chat interface | `CHAT_PROVIDER=openrouter|codex_cli|unset`, `CHAT_BASE_URL`, `CHAT_MODEL_ID`, `CHAT_AUTH_MODE=openrouter_api_key|codex_cli|unset`, `CHAT_API_KEY_REF` | OpenRouter일 때 `CHAT_API_KEY_REF=env:OPENROUTER_API_KEY`가 proposal mapping이다. Codex CLI에서는 `CHAT_BASE_URL`과 `CHAT_API_KEY_REF`를 사용하지 않는다. |
| Codex CLI auth | `CODEX_EXECUTABLE=codex`, `CODEX_AUTH_MODE=saved_cli_auth|api_key|unset`; optional API-key mode일 때만 `CODEX_API_KEY_REF=env:CODEX_API_KEY` | CLI auth readiness는 별도 검사한다. API key route는 optional이며 template의 actual `CODEX_API_KEY`는 blank다. Saved CLI auth와 workspace access token은 API key/embedding credential이 아니다. Token/cache를 생성·복사·전달하지 않는다. Workspace access-token route는 eligibility·permission 확인 뒤 별도 결정한다. |
| Embedding | `EMBEDDING_PROVIDER=local_cpu|remote_embedding|unset`, `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL_ID`, `EMBEDDING_DIMENSIONS`, `EMBEDDING_AUTH_MODE`, `EMBEDDING_API_KEY_REF=env:DSE_EMBEDDING_API_KEY` | `EMBEDDING_AUTH_MODE=provider_api_key|provider_other|none|unset`. Provider, model/dimension, auth를 독립 설정한다. Provider capability/quality 검증 전에는 route가 미확정이다. |
| Reranking | `RERANKER_PROVIDER=local_cpu|remote_reranker|disabled`, `RERANKER_BASE_URL`, `RERANKER_MODEL_ID`, `RERANKER_AUTH_MODE`, `RERANKER_API_KEY_REF=env:DSE_RERANKER_API_KEY` | `RERANKER_AUTH_MODE=provider_api_key|provider_other|none|unset`. Reranker가 없거나 미검증이면 `disabled`. Retrieval/embedding endpoint를 자동 대체하지 않는다. |
| Local worker | `DSE_SERVICE_MODE=systemd|rootless_podman|unset`, `DSE_SERVICE_USER`, `DSE_DATA_ROOT`, `DSE_ARTIFACT_ROOT`, `DSE_MODEL_CACHE_ROOT`, `DSE_LOG_ROOT`, `DSE_BACKUP_ROOT`, `DSE_CPU_WORKERS`, `DSE_BIND_HOST`, `DSE_ALLOWED_CIDRS` | Template proposal은 `DSE_CPU_WORKERS=2`, `DSE_BIND_HOST=127.0.0.1`. Paths와 service UID는 owner가 고르며 host 설정은 아직 바꾸지 않는다. |

OpenRouter의 `/api/v1/chat/completions`, `/api/v1/embeddings`, `/api/v1/rerank`는 서로 다른 API route다. Embedding/rerank는 각 선택 model의 input type, output dimension, availability, privacy terms와 DSE retrieval quality를 확인해야 한다. Chat API 지원만으로 embedding/rerank 지원을 추론하지 않는다. [OpenRouter embeddings](https://openrouter.ai/docs/api/api-reference/embeddings/create-embeddings), [OpenRouter rerank](https://openrouter.ai/docs/api/api-reference/rerank/create-rerank), [OpenRouter RAG guide](https://openrouter.ai/docs/guides/evaluate-and-optimize/rag)

CPU-local path는 [04-models-ingestion-evaluation.md](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/research/04-models-ingestion-evaluation.md)의 후보(예: BGE-M3, Qwen3-Embedding-0.6B, multilingual E5, BGE-reranker-v2-m3)를 별도 비교 대상으로 삼을 수 있다. Model file을 내려받거나 실행하지 않았다. CPU candidate gate는 DSE gold retrieval quality, latency, peak memory, context/token limits, license와 reindex 비용을 함께 측정해야 한다. 제공된 host 관찰값만으로 속도·처리량·지원 model을 주장하지 않는다.

## 서비스별 권한·credential 발급 책임

| Service / 조건 | 필요한 권한·credential | 누가 만들고 전달하는가 | 연결 task와 제한 |
|---|---|---|---|
| Existing Supabase project — baseline | Project owner/admin이 project access와 DB role을 관리한다. Dev/migration용 DDL role과 runtime용 최소 grants role을 분리한다. Direct PG path는 해당 role의 password/connection string이 필요하고, Data API path는 publishable key + Auth identity/RLS 정책이 필요하다. | Supabase account/project owner가 project ref와 non-secret endpoint/mode를 확인하고 role을 생성한다. 필요하면 초대된 named identity나 DB role을 부여한다. Plan에 따라 project-scoped dashboard role 기능이 다르므로 edition에서 먼저 확인한다. | DSE schema, claims/evidence, vector/FTS, retrieval API. `postgres`/organization Owner credential을 runtime에 주지 않는다. Direct PG 연결에는 Data API 경로의 RLS가 자동 적용된다고 가정하지 않는다. |
| GitHub repo / CI — Actions 사용 시 | 현재 publication 경로가 동작하므로 새 PAT가 필요하지 않다. Workflow에는 필요한 repository permissions만 둔다. | Repo maintainer가 Actions/environment 설정을 관리한다. User 확인대로 `gh` publish 사용 가능하며 PAT를 다시 만들거나 전달하지 않는다. | CI checks와 승인된 문서 publication. Local Linux worker는 GitHub credential 없이 실행할 수 있다. Cloud deployment credential/OIDC는 baseline에 없음. |
| Linux CPU host — baseline | Dedicated unprivileged service UID/GID, 선택된 local path에 대한 좁은 filesystem 권한, process/service lifecycle 권한만 필요하다. Root password, host account credential 또는 sudo token은 공유하지 않는다. | Host owner/admin이 service user와 path ACL을 구성하고 systemd 또는 rootless container 운영법을 승인한다. Worker가 자체적으로 root 권한을 요구하지 않도록 설계한다. | Parser, metadata extraction, local embedding/rerank 후보와 queued job 처리. `systemd` native service 또는 rootless Podman + systemd/Quadlet은 검토 후보이며 현재 설치 여부는 미확인이다. [systemd service](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html), [Podman systemd/Quadlet](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html) |
| Chat provider — 선택 후 | OpenRouter 선택 시 provider API token; Codex CLI 선택 시 CLI가 지원하는 auth mode. 두 값은 서로 교환 가능한 key가 아니다. Provider project, model access, billing/data terms를 먼저 확정한다. | OpenRouter account owner가 key를 생성해 본인 secret manager에 보관하고 reference만 제공한다. Codex route는 user/workspace owner가 local CLI sign-in 또는 eligible workspace access token을 관리한다. 지금 token/API key를 만들거나 전달하지 않는다. | Chat/analysis task만 연결한다. Codex CLI 설치·`exec` 도움말과 saved auth readiness는 별개다. OpenAI official docs는 ChatGPT sign-in과 API key를 다른 usage/access path로 설명하며, Codex access token은 workspace permission/eligibility가 필요한 별도 credential이다. Auth mode와 service-user entitlement는 연결 검증 때 확인한다. |
| Embedding/rerank provider — 선택 후 | 해당 endpoint가 지원하는 operation/model scope의 API credential이 필요할 수 있다. Embedding과 rerank는 각자 독립적으로 credential, base URL, model ID를 둔다. | 사용자가 선택한 provider의 owner가 필요한 project/limited key를 생성한다. Value는 provider/OS secret manager 또는 user-local untracked env에 넣고 private `*_KEY_REF`만 configuration에 매핑한다. 지금 발급을 요구하지 않는다. | Ingest/query embedding과 rerank task만 연결한다. OpenRouter endpoint 존재만으로 특정 model 지원·차원·품질이 확정되지는 않는다. CPU-local route를 고르면 외부 API credential은 필요 없고 model license/cache path를 확인한다. |
| Host secret delivery — 연결 단계에서만 | Supabase DB password/URL, 선택된 `OPENROUTER_API_KEY`, provider key, 또는 승인된 Codex credential은 secret이다. | 우선순위는 (1) host가 이미 제공하는 approved secret manager/keyring, (2) user가 설정한 repository 밖 local env file (permissions 제한, untracked)이다. Public repository에는 generic env name만 두고 actual value나 개인 secretref를 쓰지 않는다. | Worker process가 선택된 secret reference를 읽도록 owner가 구성한다. Secret은 chat, issue, log, command transcript, code, GitHub Actions 일반 output에 넣지 않는다. Codex local auth cache에는 access tokens가 포함될 수 있어 파일 복사/공유하지 않는다. |
| Existing Confluence / corporate Supabase / corporate Neo4j — optional source | Data owner가 승인한 exact site/project/database/schema/space IDs와 read-only operation scope. Source ACL을 재현할 수 있는 principal이 필요하다. | 각 서비스 owner/admin이 별도 integration identity를 생성한다. Confluence Cloud는 organization-approved OAuth app/resource grant와 minimum read/search scopes를 사용하고, Data Center는 별도 admin-approved auth 방식이 필요하다. 개인 API token을 요청하거나 기존 계정 access를 추정하지 않는다. | Source ingestion/read-only retrieval. New DSE project credential과 분리한다. Confluence app scopes만으로 user/space ACL을 넘지 않으며 site/user permission도 확인한다. Source owner 승인 전 internal content를 수집하지 않는다. |
| Neo4j graph challenger — optional | Separate test instance/database의 limited user와 connection URI; no production/corporate graph privilege. | Graph-query comparison 필요가 확인된 뒤 project owner가 isolated challenger를 만들고 read/write scope를 제한한 user를 발급한다. Existing corporate Neo4j를 재사용할 때는 owner가 별도 read-only namespace/user를 승인해야 한다. | PostgreSQL typed/recursive query baseline과 동일 query set을 비교할 때만 연결한다. Neo4j account, Aura API key, existing graph secret은 지금 필요하지 않다. [Neo4j Aura connect](https://neo4j.com/docs/aura/getting-started/connect-instance/) |

### Secret과 user session의 처리

- 실제 value는 chat과 public repo에 전달하지 않는다. 필요해지는 시점에 owner가 secret manager에 넣거나 repository 밖의 user-local untracked env에 직접 설치하고, 이 repo에는 generic variable name만 둔다.
- Secret value가 필요한 업무는 secret reference만 configuration에 매핑한다. Public 문서에는 real secret name/path도 넣지 않고 placeholder/reference convention만 둔다.
- Supabase의 current API-key docs는 신규 key를 publishable/secret으로 구분하고 legacy `anon`/`service_role` 명칭의 deprecation 일정을 안내한다. Supabase `secret` key는 RLS를 bypass하는 elevated server key이므로 일반 worker DB credential로 자동 선택하지 않는다. [Supabase API keys](https://supabase.com/docs/guides/getting-started/api-keys), [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security)
- Codex CLI docs는 `codex exec`가 saved CLI auth를 재사용할 수 있고 API key route는 `CODEX_API_KEY`, ChatGPT-managed/workspace auth는 별도 route라고 구분한다. Workspace Codex access token은 Business/Enterprise 설정·owner permission에 따라 사용할 수 있지만 actual entitlement은 모른다. 어떤 auth cache/token도 embedding provider key로 재사용하지 않는다. Public CI에 personal session file을 복사하는 방식은 baseline에서 제외한다. [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode), [Codex authentication](https://learn.chatgpt.com/docs/auth), [Codex access tokens](https://learn.chatgpt.com/docs/enterprise/access-tokens)

## 조건부·나중 항목

| 선택 항목 | 추가할 조건 | 현재 요구 여부 |
|---|---|---|
| GPU/self-hosted embedding 또는 reranker | CPU-local 평가에서 승인된 품질 기준은 만족하지만 latency/memory/throughput 기준을 만족하지 못하고 local inference가 필요한 경우. | 현재 필요 없음. 구매/대여/새 GPU credential 없음. |
| OpenRouter API token 또는 Codex workspace/API credential | 특정 provider/model로 합성 fixture를 테스트하고 privacy/billing/auth mode를 정한 경우. Chat과 embedding/rerank는 endpoint별로 따로 결정한다. | Interface만 명시. Provider key 발급·전달은 요청하지 않음. |
| Object storage / off-host backup | Raw files/run artifacts가 local quota를 넘거나 host-loss recovery를 요구할 때. Provider/region/budget은 그때 선택한다. | AWS 포함 cloud account는 baseline에서 제외. Supabase database backup은 Storage API의 object payload backup을 대신하지 않으므로 local object backup과 DB backup을 따로 계획한다. |
| Queue/workflow engine | Long-running parse/embedding jobs, retry/idempotence, fan-out/queue backlog가 local scheduler를 넘을 때. | 초기 worker에서 별도 managed service는 요구하지 않음. |
| Neo4j challenger | PG graph query latency/expressiveness가 정해진 비교 기준을 못 넘고, 동일 query corpus로 challenger 평가할 때. | 선택형; baseline credential 없음. |
| Internal Confluence/DB connector·licensed technical standards | Source owner, exact ACL/namespace, AI/TDM/retention rights, required licensed account가 승인된 뒤. | 미승인·미연결. Standards metadata 조회와 licensed full-text 처리를 구분한다. |
| Remote access/production reliability | 사용자가 LAN/VPN/reverse proxy exposure, retention, backup/restore objective를 정한 뒤. | Local-only proposal. Internet/public bind, multi-host HA와 remote storage를 현재 가정하지 않음. |

## 계정·resource 준비 순서

| 순서 | 작업 owner가 준비할 것 | 연결 확인 기준 |
|---|---|---|
| 1. Non-secret configuration | Supabase project ref/DB route/schema/namespace; host distro/version; service user; data/artifact/cache/backup roots와 quotas; local-only vs approved network exposure; provider interface choices. Budget은 unanswered로 유지한다. | 운영 상태표에 confirmed/unknown을 분리한다. Secret values는 받지 않는다. |
| 2. Resource boundary | Supabase owner가 dev/test project 또는 approved isolated schema를 정하고 pgvector/FTS availability와 backup edition을 확인한다. Host admin은 dedicated non-root service user와 local paths를 준비한다. | Actual project/database object를 만들거나 host를 바꾸는 작업은 owner가 별도 승인한 뒤 수행한다. |
| 3. Identity와 permission | Supabase runtime/migration DB roles; local filesystem ACL; `systemd` native 또는 rootless-container service boundary; 필요 시 provider-specific API account; optional internal-source readonly principal. | `postgres`/organization-owner 계정을 runtime에 두지 않고, 각각의 task가 필요한 schema, path, API operation만 허용한다. |
| 4. Secret reference wiring | Supabase DB connection secret 등 선택된 secret을 owner가 approved secret manager 또는 local untracked env에 넣고 reference를 private config에 매핑한다. OpenRouter/Codex/embedding keys는 해당 route가 선택된 경우에만 준비한다. | Repo diff, logs, chat, process output에 값이 없어야 한다. Codex auth mode와 workspace permissions는 access check 시 확인한다. |
| 5. Dev-only connection verification | Synthetic fixture로 Supabase `current_user`/database/schema, grants/RLS allow-deny, pgvector `extversion`/index creation, CPU worker read/write scope, object path permissions (if any), provider endpoint/model entitlement을 확인한다. | Connection success는 internal source permission, production approval, model quality, backup readiness를 의미하지 않는다. Public/internal content는 owner authorization 전 보내지 않는다. |
| 6. Recovery/operations gate | Host log/metric rotation, secret redaction, DB backup, artifact/object backup, disk alert, rollback, isolated restore rehearsal을 준비한다. | Supabase database backups에는 Storage API object payload가 포함되지 않으므로 object와 DB restore를 각각 시험한다. Backup retention은 사용 plan에 맞춰 확인한다. |

Supabase 문서에 따르면 pooler/direct connection choice는 worker topology와 IP family에 달려 있고 connection host/username은 Dashboard Connect 화면에서 가져와야 한다. Custom runtime role의 privileges와 RLS policy는 선택한 access path에 맞춰 설계한다. [Supabase database connections](https://supabase.com/docs/guides/database/connecting-to-postgres), [Supabase access control](https://supabase.com/docs/guides/platform/access-control), [Supabase backups](https://supabase.com/docs/guides/platform/backups)

## 실제 연결 단계 설정 checklist

이 표는 지금 답을 다시 요청하는 목록이 아니라, owner가 실제 local connection을 승인할 때 `.env.example`에서 채울 항목이다. Unknown은 blank로 둘 수 있다. Secret 발급·전달이나 host 변경은 이 문서만으로 시작하지 않는다.

| 설정 group | 연결 시 채울 값 | Unset일 때 |
|---|---|---|
| Supabase | `SUPABASE_PROJECT_REF`, DB mode/auth mode, 승인된 schema/namespace. `dse_knowledge`와 `dev`는 proposal default다. | Project access/connection이 허가될 때까지 refs와 credentials는 blank. DB URL ref를 쓰면 host/port/name을 생략할 수 있다. |
| Host worker | User가 확인한 distro/version, service user, `DSE_SERVICE_MODE`, data/artifact/cache/log/backup paths와 quotas | `.env.example`의 workers=2와 loopback bind는 proposal이며 성능 결과나 외부 노출 승인이 아니다. |
| Network/source boundary | Local-only vs approved LAN/VPN/proxy, CIDRs, 선택된 sources와 ACL namespace | Local-only proposal 유지. Internal source는 owner scope/ACL이 허가되기 전 disabled다. |
| Chat | `CHAT_PROVIDER`, `CHAT_MODEL_ID`, 선택한 provider auth mode; OpenRouter면 `CHAT_API_KEY_REF` | Provider/model은 unset 가능. OpenRouter key value는 요청하지 않는다. Codex auth entitlement는 연결 때 확인한다. |
| Embedding/rerank | 각 provider/model/dimension/auth와 CPU-local 또는 remote route | `EMBEDDING_PROVIDER=unset`, `RERANKER_PROVIDER=disabled` 가능. Remote route 선택 전 API key가 필요하지 않다. |
| Storage/backup/budget | Path capacity, 별도 backup mount 여부, retention/restore 목표와 budget | Off-host/cloud destination은 implied되지 않는다. Budget은 unanswered 상태로 유지한다. |

Budget은 현재 미정으로 보존하며 다시 요청하지 않는다. 비용이 붙는 API key, storage, GPU 또는 production path를 선택할 때만 그 선택과 사용량 가정을 함께 산정한다. Host 관찰값은 초기 CPU capacity를 생각하는 단서일 뿐이고 parser/embedding throughput이나 latency 결과가 아니다.

공식 access reference: [GitHub Actions OIDC](https://docs.github.com/en/actions/concepts/security/openid-connect), [OpenRouter embeddings](https://openrouter.ai/docs/api/api-reference/embeddings/create-embeddings), [OpenRouter rerank](https://openrouter.ai/docs/api/api-reference/rerank/create-rerank), [OpenRouter chat API](https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request), [Atlassian Confluence OAuth scopes](https://developer.atlassian.com/cloud/confluence/scopes-for-oauth-2-3LO-and-forge-apps/), [Atlassian OAuth 2.0 (3LO)](https://developer.atlassian.com/cloud/confluence/oauth-2-3lo-apps/). Internal reference: [deployment profiles](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/docs/deployment-profiles.md), [storage/retrieval candidates](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/research/02-storage-retrieval.md), [cloud operations research](https://github.com/jimmylegendary/dse-knowledge/blob/docs/p0-episode-contracts/research/03-cloud-operations.md).
