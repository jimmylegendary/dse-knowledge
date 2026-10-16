# Public repository publication preparation

기준일: 2026-10-17 KST. 사용자가 public GitHub 저장소 생성과 설계 패키지 게시를 요청했다. 범위는 기존 설계·계획 문서와 조사 점수 데이터이며 제품 구현이나 cloud infrastructure 배포는 포함하지 않는다.

## 공개본 조정

- 원본 설계 패키지 24개 파일을 별도 publication checkout에 복사했다. 원본의 검증 hash 23개가 모두 일치해 원본 보존을 확인했다.
- 로컬 문서 링크 42개를 절대 GitHub URL로 바꿨다. 패키지 내 파일은 이 저장소를 가리키고, HAT·Melete의 코드 근거 6개는 확인 당시 commit에 고정된 별도 저장소 링크다.
- HAT·Melete는 접근 권한이 필요한 통합 대상이다. 해당 저장소의 코드·실험 데이터·credential은 이 저장소에 포함하지 않는다.
- 개인 작업 경로를 portable placeholder로 바꾸고, 판단 자문의 내부 request ID·usage·billing·latency metadata를 공개본에서 제외했다. 판단 입력·advisory 결과·model identity와 기술별 가격 조사 내용은 유지했다.
- 원본 검증 보고서는 역사적 기록으로 표시했다. 링크와 metadata가 바뀐 공개본에 원본 파일 hash를 적용하지 않는다.
- 환경 파일·private raw data·secret directory의 실수로 인한 추가를 줄이기 위해 `.gitignore`를 추가했다. License 선택이나 제품 scaffold는 추가하지 않았다.

## 게시 전 실제 검사 결과

| 항목 | 결과 |
|---|---|
| JSON 파싱 | 6/6 성공 |
| 후보 점수 재계산 | 113/113 일치 |
| CSV 행 대조 | 113/113 일치 |
| 패키지 내 GitHub 문서 링크 | 37개 대상 확인; 이 보고서 경로는 생성 후 최종 확인 |
| 고정 revision의 통합 코드 참조 | 6개, private 저장소 접근 필요 |
| Credential 형태·개인 작업 경로·내부 호출 telemetry 검사 | 발견 사항 0건 |
| 원본 artifact 보존 검사 | 23/23 SHA-256 일치 |

위 수치는 context-mode Python으로 publication copy와 원본을 직접 읽어 얻었다. 공개본은 설계 패키지 24개와 `.gitignore`, 이 보고서의 총 26개 파일이다. JSON/CSV/링크 검증은 runtime 성능이나 HAT·Melete 연동 시험을 대체하지 않는다.

GitHub 공개 여부, 기본 branch와 실제 commit SHA는 게시 후 repository metadata와 remote ref로 확인한다. 실제 게시 commit은 Git history가 기준이다.
