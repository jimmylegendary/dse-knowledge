# Q2 local HTML report and HAT committee knowledge flow

요청: 기존 Q2 실험 결과를 로컬 HTML로 열어 보고, HAT schema committee가 KG를 어떻게 사용할지 실제 코드에 근거해 설명한다.

범위: 이미 검증·게시한 Q2 snapshot을 재표현하는 정적 HTML 한 개와 committee 연결 설계다. 기존 Workbench의 navy/blue/밝은 카드 스타일을 재사용한다. HTML은 CSS/JS/data를 내장해 file://에서도 열리고 현재 Linux HTTP 서비스의 /static/reports/로도 제공한다. Backend·DB·model·retrieval policy·HAT/Melete repository는 수정하지 않는다. Committee의 실제 KG 호출 구현이나 모델 실행을 이번 보고서에 이미 연결된 기능처럼 표시하지 않는다.

완료 때: 사용자가 전체 Q2 결과, 한·영/stream별 검색 표본, 실패·수정 이력, 비용·scope 한계, current-vs-proposed committee 흐름을 하나의 responsive HTML에서 확인한다. 원문·인용·vector·생성 답변·credential을 새로 포함하지 않는다.

## 작업과 소유

|작업|소유/파일|검증|
|---|---|---|
|자료·route 확인|root, 기존 public JSON·app route 읽기|b1dea82 snapshot, /static existing route, 현재 core 불변|
|전체 HTML report|worker C, web/reports/q2-results-2026-10-26.html 한 개|standalone/no CDN·fetch, 정확한 분모·filter, source-safe JSON|
|Committee recon|worker D, HAT schema 및 DSE adapter read-only; .superpowers/sdd/q2-html-report/hat-committee-recon.json/md|실제 role/type/function/call path·HEAD/file hash·현재 retrieval 유무·필요 adapter 경계|
|통합·별도 review|root가 committee 설명을 HTML에 순차 추가; 별도 worker A read-only review|현재와 제안 구분, simulation permission≠buildability, mandatory rules≠top-k|
|실제 열기·로컬 전달|root|HTTP200, desktop/mobile overflow0, JS controls·표 수치 확인, 기존 runtime core 불변, 로컬 commit·파일/HTTP 링크 제공; 외부 게시 없음|

HTML 보고서는 public metadata만 사용한다: research/pilot1000/quality-v2-2026-10-26.json, retrieval-paired-2026-10-26.json, corpus-2026-10-26.json. 1,000 indexed≠1,000 full KG; 960/984, source hit24/24와 chunk16/24, AI 원문 대조2+1과 Jev 불일치, trace 노출·same-corpus 표본·HAT structural-only·50k cap·미확인 invoice를 보존한다.

## 상태

- [x] 사용자 요청과 기존 결과·route·수정 범위 확정.
- [x] 전체 HTML과 committee 코드 근거 통합.
- [x] 독립 review·실제 browser/HTTP 검증.
- [x] 로컬 경로·HTTP 링크·committee 설명을 한국어로 전달할 산출물 확정.

## 실제 검증 기록 — 2026-10-26

최종 HTML: [q2-results-2026-10-26.html](/home/jimmy/.paseo/worktrees/06af7m2w/http-selfhost-pilot100/web/reports/q2-results-2026-10-26.html), 210,880 bytes, SHA-256 `2b22048848b50a1ed1fed34b75148447815a36940612f740f9bbffb72ad08607`.

|검증|실제 결과|
|---|---|
|기존 static route, Python urllib HTTP GET|`200 text/html`; served bytes와 파일 bytes·SHA 동일. Backend 수정·재시작 없음.|
|Node `--check -`, 내장 JSON 파싱|exit 0. HTML ID 42개 중복 0, label target 누락 0.|
|Public snapshot 대조|3개 원본 JSON SHA 일치. 28개 질문·언어·category·answerability·latency 1:1 일치. 각 분포 합계 1,000.|
|실제 브라우저 표시|28개 질문, 280개 raw slot, metric 4행. NaN/undefined/Infinity 0, 외부 resource 0, console 0.|
|실제 필터 조작|KO 14, KO+unsupported 2, compiler_kernel 4, 질문 검색 1, 빈 결과 0, reset 28. Mobile EN 14, EN+unsupported 2, reset 28.|
|Desktop / mobile|1440px: client=scroll=1425. Mobile 요청 375px에서 실제 inner 376, client=scroll=361. Overflow 0. 사례의 양쪽 stream 및 committee API/판정 details를 펼친 상태도 확인.|
|HAT 코드 독립 대조|AST에서 expert 9개와 scope별 5/6/6/5/3석 확인; recon의 committee/engine hash 일치. 현재 validate_twin-only와 향후 KG tool loop를 분리.|

초기 실제 브라우저가 찾아낸 `comparison_rows` 경로 불일치, `window` 전역 shadow, physical-growth key 불일치를 수정했다. 긴 backup status의 mobile overflow도 실제 원인인 flex item wrapping과 표시 문구를 고쳐 해결했다. Jev의 positive disagreement는 2건으로 고정했다.

458은 기존 pytest 한 실행의 passed test 수다. Private local `q2-r17-r18-release-verification.json`의 `root_verification.full_tests`에서 command·exit 0·`458 passed, 1 warning in 2.18s`를 확인했다. 해당 receipt SHA는 `5982edb157dab4b09ce9a4b6b5e577dd5272ca8e5cb43c01e6ecf3d18703d0ab`이며 root tool 출력의 전사다. Raw log 보존·해시 또는 이번 HTML 작업에서 suite 재실행을 주장하지 않는다.

이번 변경은 로컬 보고서와 이 계획뿐이다. HAT/Melete·DB schema·모델·retrieval policy는 변경하지 않았고 새 LLM/embedding/committee 실험은 실행하지 않았다. 현재 HTTP 서비스로 로컬에서 전달하며 외부 GitHub에 새로 게시하지 않는다.

독립 worker 최종 review는 같은 HTML SHA를 기준으로 PASS, blocking/important/minor 0이다. Owner-only `final-review.json` SHA는 `a1045435ffc88acb0a572e64768948649774ad082801fd1fcaeb7ed5a76d1583`이다. Root가 파일·hash·PASS·finding 목록을 재확인했고, HTTP/browser는 root의 실제 검증이다. Review 이후 변경은 이 계획의 종료 기록뿐이며 HTML은 그대로다.
