# DSE 판단 지식과 실험 경험

지식과 실험 근거를 이용해 workload에 맞는 hardware와 kernel의 설계 공간을 탐색하는 맥락이다. 개념 정의는 설계 초안이며 사용자 검토에 따라 변경할 수 있다.

## Language

**Workload Scenario**: session, turn, 요청 의존관계, 입력·출력 길이 및 시간 의미를 정의한 재현 가능한 작업 부하이다.

**Design Point**: 특정 workload와 평가 조건 아래 함께 비교하는 hardware, kernel/recipe, serving 설정의 버전 고정 조합이다.

**Hardware Asset**: 다른 설계 요소와 조합할 수 있으며 범위·연결 조건·근거가 명시된 hardware 설계 요소이다.

**Claim**: 출처와 적용 조건을 갖고 참·거짓 또는 지지 정도를 검토할 수 있는 명시적 주장이다. 관측, 가설, 규범적 제약을 같은 것으로 취급하지 않는다.

**Evidence**: 특정 Claim의 지지 또는 반박에 사용되는 식별 가능한 원자료·관측·검증 결과이다.

**Decision Context**: 판단 대상, workload, hardware와 toolchain 버전, 제약, 필요한 근거의 종류를 정한 맥락이다.

**Experiment Trajectory**: 실험의 제안·검토·변경·실행·실패·해석과 다음 선택이 연결된 외부에서 관찰 가능한 사건 이력이다. 모델의 숨겨진 내부 추론을 뜻하지 않는다.

**Insight**: 관측과 기존 지식을 해석해 얻은 적용 조건·근거·반례 가능성이 명시된 주장이다.

**Recommendation Score**: 기술·source·조합 후보의 검토 우선순위를 정하기 위한 근거 기반 잠정 평가이다. 실측 성능이나 사실의 확률이 아니다.

**Metric Vector**: 하나의 설계점에서 평가한 각 성능 지표의 값·단위·집계·불확실도를 보존한 집합이다. 기술 선정용 Recommendation Score와 별개이다.

**Resolution Phase**: 수집부터 판단·실험·경험 환류까지 전체 흐름을 유지하면서 정밀도, coverage, 자동화 또는 운영 수준을 높이는 단계이다.
