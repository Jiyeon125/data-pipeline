# Trial 신뢰성 추가 감사 및 확정 반영 기록

작성일: 2026-08-05  
최종 판정: **조건부 진행 → 통과 기준 충족**  
분석 범위: 기존 생산 분석의 경계·표시·감사 보강. 새 점수·DB·PDF·LLM 확대 없음.

## 1부. 실행 요약

### 결론

기존의 as-of 반복신호, T+1·T+2 환류 분리, complete-case 신호점수, 프로그램 성과
비귀속 원칙은 유지했다. 실제 누락이 확인된 사업-연도 중복 차단, 후보별 불변 필드
검증, 불완전 점수 상태 표시, 세부사업 프로그램 맥락 명시, 분석시점·provenance만
최소 수정했다.

Trial은 **서브에이전트 4명**으로 실행했다. 동시 한도 때문에 3명을 병렬 실행하고
네 번째 심사관을 새 서브에이전트로 순차 실행했다. 메인 오케스트레이터 대체는 없었다.
교차반대신문도 같은 4명이 3명 병렬 + 1명 순차로 1회 수행했고, 별도 최종 판정
서브에이전트 1명이 결론을 냈다.

구조화된 판단 신뢰도는 계산 확률이 아니다.

| 축 | 수준 | 근거 |
|---|---|---|
| 사실확실성 | 높음 | 코드·실제 CSV·summary·테스트를 직접 대조했다. |
| 논리확실성 | 높음 | 수정은 확인된 중복·키 재배치·상태 소실·grain 오독 경로만 차단한다. |
| 실행확실성 | 높음 | 실데이터 재생성, 동일 입력 2회 hash, 280개 테스트, AppTest, 수정 범위 Ruff가 통과했다. |

### 핵심 결과

- 후보 412행과 `candidate_id`가 모두 보존됐다. anti-join은 좌우 모두 0행이다.
- 후보별·프로그램×연도×회계별 본예산·현액·지출액 차이는 모두 0행이다.
- `INCOMPLETE_COMPONENTS` 11행은 `signal_score=null`을 유지하고 화면·다운로드에서
  `판단 보류(구성요소 결측)`로 표시된다.
- 세부사업 3,286행의 `project_performance_attributed`는 모두 false다. 모호한
  `performance_signal`과 T+1·T+2 성과필드는 세부사업 CSV에서 제거했고, 통합
  workbench의 세부사업행에서도 모두 null이다.
- 모든 세부사업행은 `program_context_grain=PROGRAM_YEAR_ACCOUNT`와
  `PROGRAM_LEVEL_REFERENCE_NOT_PROJECT_PERFORMANCE`를 보존한다.
- 동일 입력으로 재실행한 분석 CSV 10개의 SHA256이 모두 일치했다.
- 이번 추가 보강으로 레인 수는 변하지 않았다: `MONITOR 130`, `SINGLE_REVIEW 102`,
  `CONTEXT_REVIEW 87`, `REPEATED_OR_MULTIPLE 76`, `DATA_FIRST 15`, `STRONG_SINGLE 2`.

### 남은 위험

- `available_at`이 없어 과거 공개 당시 정보집합은 재현하지 못한다. 현재 의미는
  **필요 자료 공개·구조화 후 회계연도별 연례 사후검토**다.
- 이전 HEAD 산출물과 현재 산출물의 입력 SHA256이 다르다. 아래 67행 전환은 코드
  효과나 정확도 향상이 아니라 `UNVERIFIED_BASELINE / CONCURRENT_INPUT_DRIFT`가
  포함된 스냅샷 차이다.
- 전체 저장소 Ruff는 이번 수정과 무관한 기존 9건 때문에 실패한다. 별도 미완료
  트래커 `quality.full-repository-ruff-cleanup`으로 분리했다.

## 2부. 상세 부록

## A. 항목별 사전 판정과 반영 결과

| 항목 | 조사 판정 | 실제 근거 | 최종 처리 |
|---|---|---|---|
| 1-1 네 번째 독립 심사관 | 수정 필요 | 기존 Trial은 4명 병렬만 규정 | 동시 한도 시 새 서브에이전트 순차 실행·실행 수 공개 추가 |
| 1-2 반대신문 경로 | 수정 필요 | 공격표가 선택적이고 심사관 이력표 없음 | 두 표를 필수화 |
| 1-3 확신도 | 수정 필요 | 단일 0~100 값 | 사실·논리·실행 3축 낮음/중간/높음으로 변경 |
| 1-4 결과 길이 | 수정 필요 | 단층 출력 | 실행 요약과 상세 부록으로 분리 |
| 2-1 가용시점 | 수정 필요 | `fiscal_year` 누적을 회계연도 말로 표현 | 연례 사후검토로 수정, `available_at`은 이번 범위 제외 |
| 2-2 미래행·분모 | 이미 충족 | 미래 append 불변·유효연도 분모 테스트 존재 | 기존 로직 유지 |
| 2-2 누락연도·정렬 | 로직 충족, 테스트 필요 | 숫자 변환·연도차 1 로직 존재 | 명시 회귀 테스트 추가 |
| 2-2 중복 사업연도 | 수정 필요 | 행 수가 반복횟수를 부풀릴 수 있음 | 공유 반복함수 입구에서 오류 처리 |
| 2-3 키 무결성 | 부분 충족, 수정 필요 | one-to-one·집합·총합만으로 값 교환 탐지 불가 | anti-join·후보별 3금액·불변 필드·그룹 대조 추가 |
| 2-4 null 전파 | 값 보존은 충족, 표시 수정 필요 | 원본 null 유지, 간이 표·다운로드에는 상태 없음 | 기존 enum을 표시하고 loader·직렬화 테스트 추가 |
| 2-5 grain | UI는 충족, 산출물 수정 필요 | UI 경고는 있으나 project/workbench에 모호한 필드 | `program_level_*_context`와 disclaimer로 명시 |
| 2-6 인과 표현 | 생산 문제 없음, 계획 수정 필요 | 강한 세 문구는 계획에만 존재 | 계획 문구만 관측 사실형으로 교체 |
| 2-7 provenance | 부분 충족, 수정 필요 | 실행시각·입력 hash는 있으나 version·SHA·시점 의미 없음 | 기존 summary에 최소 메타데이터 추가 |
| 2-8 영향 감사 | 수정 필요 | 전환표 부재, 입력 hash drift 동반 | 이 문서에 미확정 스냅샷 전환표 보존 |
| 2-9 전체 Ruff | 수정 필요—기록만 | 전체 `ruff check .` 기존 9건 | 별도 미완료 트래커, 이번 코드에서는 수정 안 함 |

## B. 증거 원장

| ID | 확인 사실 | 상태 | 강도 |
|---|---|---|---|
| E1 | Trial 문서에 순차 독립 심사·필수 이력표·3축 확실성·2층 출력이 없었다. | VERIFIED | A |
| E2 | as-of는 `fiscal_year` 접두이며 신뢰 가능한 `available_at`이 없다. | VERIFIED | A |
| E3 | 중복 사업-연도 guard가 없었고 일부 경계 테스트만 존재했다. | VERIFIED | A |
| E4 | 후보 집합·총액 검사는 있으나 후보별 값 교환 반례를 잡지 못했다. | VERIFIED | A |
| E5 | 412행 중 11행이 불완전·null이지만 간이 표에 상태가 없었다. | VERIFIED | A |
| E6 | UI는 비귀속을 표시했지만 세부사업 산출물에 모호한 프로그램 성과필드가 있었다. | VERIFIED | A |
| E7 | 강한 인과·효율 문구는 생산이 아니라 계획 문서에만 있었다. | VERIFIED | A |
| E8 | 실행시각·입력 hash·업무대기열 tie key는 있고 version·SHA·시점 기준은 없었다. | VERIFIED | A |
| E9 | HEAD 대비 67행 전환과 약 109.358조 원이 관측됐지만 입력 hash도 달랐다. | PARTIAL | C |
| E10 | 수정 범위 Ruff는 통과하나 전체 Ruff 기존 오류가 남는다. | VERIFIED | A |
| E11 | 변경 전 기준 275 tests·AppTest 5·수정 범위 Ruff가 통과했다. | VERIFIED | A |

## C. 독립 심사와 판정 이력

| 심사관 | 최초 판정 | 핵심 주장 | 받은 공격 | 인정한 오류·누락 | 수정 판정 |
|---|---|---|---|---|---|
| R1 사실·코드 | 조건부 진행 | 중복 guard, per-key 감사, grain, provenance 필요 | 상태 미표시를 종단 값 왜곡으로 과장, 설정 hash 중복 지적 | 새 HOLD 불필요, config hash는 기존 input hash로 충분 | 조건부 진행 유지 |
| R2 의미·UI | 조건부 진행 | project/workbench 오독과 상태 가시성 문제 | stability tie 결함은 재현 전 과도, 영향 CSV+JSON은 과잉 | null→0이 아니라 가시성 문제, 소비자 호환성 누락 | 조건부 진행 유지 |
| R3 운영·provenance | 조건부 진행 | 경계 테스트, 결정성, 영향 원장 필요 | 기존 세부사업 합계 검증을 누락처럼 표현, 구조화 영향파일 과잉 | 기존 내부 검증 인정, Markdown 감사로 축소 | 조건부 진행 유지 |
| R4 적대적 소수의견 | 조건부 진행 | available_at 추정·fillna 제거·맥락 전면삭제 반대 | 카드·loader null 계약과 동일 입력 결정성 검증 누락 | 설정 hash 중복과 전 정렬 수정 불필요 인정 | 조건부 진행 유지 |

## D. 중요한 교차공격

| 공격자 | 대상 | 공격한 주장 | 공격 근거 | 대상의 응답 | 최종 판정 영향 |
|---|---|---|---|---|---|
| R1 | R2 | HOLD 미표시가 값 왜곡이라는 주장 | 실제 enum은 `INCOMPLETE_COMPONENTS`, null은 보존됨 | 상태 가시성 문제로 한정 | 새 HOLD 기각, 기존 상태 노출만 채택 |
| R1 | R4 | 감사 Markdown만으로 충분 | 후보별 재배치는 총액으로 탐지 불가 | 범용 엔진은 과잉 | 생산 per-key 검증 + Markdown 영향표 채택 |
| R2 | R1 | stability tie 결함 확정 | 본 업무대기열은 `candidate_id` tie, 동점은 평균순위 | stability CSV 물리 순서 우려 | 실제 2회 hash 검증 후 추가 정렬 불필요로 판정 |
| R2 | R3 | CSV와 JSON 두 영향 산출물 | 같은 사실 중복 직렬화는 불일치 위험 | 행 상세와 집계 필요 주장 | 신규 구조화 파일 기각, 기존 summary+감사 Markdown 사용 |
| R3 | R4 | available_at 반대가 실제 제안보다 강함 | 공통안은 추정 추가가 아니라 명칭 정정 | 예방 취지였음 | available_at 제외와 시점 명칭 수정을 동시에 채택 |
| R3 | R1 | 후보별 3금액 검증이 전혀 없다는 표현 | 세부사업 합계→후보 검증은 기존 존재 | 전후 후보 불변 검증을 뜻함 | 새 범용 체계 대신 후보→업무대기열 경계만 보강 |
| R4 | R1 | 모든 stability 정렬 수정 | 본 대기열 정렬은 이미 안정적 | stability 파일 자체 우려 | 동일 입력 hash 일치로 선제 수정 기각 |
| R4 | R3 | 영향 구조화 산출물 필수 | baseline 입력 hash가 달라 영구 기준선 오인 위험 | 자동 재감사 장점 | `UNVERIFIED_BASELINE` Markdown만 채택 |

## E. 최종 판정에서 기각한 수정

- 새 `HOLD`·`UNKNOWN` enum과 상태 아키텍처
- 실제 공개일을 추정한 `available_at`
- missing-first 뒤 임시 정렬키의 `fillna(0)` 제거
- 프로그램 수준 참고 맥락의 전면 삭제
- 입력이 다른 67행 전환을 코드 개선 효과로 주장
- 별도 영향 CSV·JSON 및 범용 provenance 시스템
- 결정성 실패가 없는 stability 정렬의 선제 변경
- 기존 전체 Ruff 오류 9건의 혼합 수정

## F. 변경 영향 감사표

아래 표는 **정확도 기준선이나 코드 수정 효과가 아니다**. HEAD 산출물과 현재 산출물의
입력 SHA256이 달라 원자료·중간산출물 재생성 영향이 섞인 감사용 스냅샷 전환이다.

| 이전 레인 | 현재 레인 | 행 수 |
|---|---|---:|
| CONTEXT_REVIEW | MONITOR | 11 |
| REPEATED_OR_MULTIPLE | CONTEXT_REVIEW | 14 |
| REPEATED_OR_MULTIPLE | MONITOR | 14 |
| REPEATED_OR_MULTIPLE | SINGLE_REVIEW | 26 |
| REPEATED_OR_MULTIPLE | STRONG_SINGLE | 2 |
| 합계 |  | 67 |

| 관측 변경 원인 | 행 수 | 현재 본예산 영향 |
|---|---:|---:|
| as-of 반복신호만 | 6 | 6,163,355,000,000원 |
| T+1·T+2 환류 분리만 | 9 | 8,057,016,000,000원 |
| as-of와 환류 분리 동시 | 41 | 94,592,198,800,000원 |
| 그 밖의 동시 입력·맥락 변화 | 11 | 545,426,000,000원 |
| 합계 | 67 | 109,357,995,800,000원 |

대표 관측 사례는 노인생활안정(075, 2022·2023), 기초생활보장(075, 2022),
건강보험제도 운영(075, 2022), 산재보험(019, 2023)이다. 또한 후보 1건의 금액도
동시에 달라졌고 same-year, M3, program financial, config 입력 hash가 모두 바뀌었다.
따라서 상태는 `UNVERIFIED_BASELINE / CONCURRENT_INPUT_DRIFT`이며 의도하지 않은
코드 변경으로 단정하지 않는다.

이번 추가 감사 패치 자체는 수치 산식·레인을 바꾸지 않았고, 재생성 후 412행과 위 레인
분포를 그대로 유지했다. 변경은 입력 검증, 표시, 스키마 명시, metadata에 한정된다.

## G. 테스트 근거

| 검증 | 결과 |
|---|---|
| 반복신호 경계·후보 무결성·grain 단위 테스트 | 23 passed |
| 전체 pytest | 280 passed |
| Streamlit AppTest 포함 대시보드 테스트 | 5 passed |
| 수정 범위 Ruff format/check | PASS |
| 동일 입력 2회 분석 CSV SHA256 | 10개 모두 일치 |
| 실데이터 후보 anti-join | left 0, right 0 |
| 후보별 불변 필드 diff | 전 필드 0 |
| 프로그램×연도×회계 금액 diff | 본예산·현액·지출액 모두 0 |
| 전체 저장소 Ruff | FAIL — 기존 9건, 별도 후속 |

전체 Ruff 기존 오류는 `notebooks/mss_priority_scenario_stability.ipynb` 2건,
`src/analytics/cli.py` 1건, `src/analytics/explanation_need_score.py` 6건이다.
이번 신뢰성 수정의 완료와 구분하며 CI에서 전체 PASS로 표현하지 않는다.
