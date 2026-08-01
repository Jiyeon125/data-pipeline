# 4개 부처 TRUE_UNKNOWN 전수감사와 v3 데이터모델 권고안

## 1. 결론

현재 UNKNOWN이 많은 가장 큰 이유는 원자료가 전부 비어 있어서가 아니라, 서로 다른
개념과 상태를 한 열에 합쳐 저장했기 때문입니다. 따라서 기존 데이터를 지우거나 처음부터
다시 수집할 필요는 없습니다.

가장 안전한 해법은 다음과 같습니다.

1. 기존 원본·정규화·금액 이벤트·월별 자료는 그대로 보존합니다.
2. 분석 범위를 4개 부처·2022~2024년으로 명시적으로 동결합니다.
3. `재정지원방식`과 `사업특성`을 분리하고 복수 지원방식을 허용합니다.
4. 값, 값의 상태, 근거를 분리합니다.
5. 기존 wide master를 즉시 폐기하지 않고 얇은 v3 core/feature를 병행 생성합니다.
6. 대시보드는 검증된 export만 읽게 한 뒤 기존 산출물을 단계적으로 퇴역시킵니다.

현재 767개 UNKNOWN을 전부 수기검수 대상으로 보내는 것은 잘못입니다. 반대로
“사업명 텍스트가 있으니 진짜 UNKNOWN은 0개”라고 보는 것도 잘못입니다. 최종 판단에는
아래 세 숫자를 구분해야 합니다.

| 질문 | 답 |
|---|---:|
| 현재 대시보드 정책사업 중 `fiscal_instrument=UNKNOWN` | 767개 사업, 1,852행 |
| 그중 보조·출연·융자·출자·이차보전 명칭 신호가 있는 사업 | 627개 |
| 명칭 신호가 1개인 사업 / 2개 이상인 사업 | 581개 / 46개 |
| 명칭 신호 없이 재료비·학교운영비로만 직접수행 후보가 된 사업 | 5개 |
| 현재 규칙에서 어떤 후보 신호도 없는 잔여 | 135개 |
| 보수적으로 명시적 지원방식을 확정할 수 없는 현재 잔여 | 140개 |
| 로컬 세목자료 자체가 없는 사업 | 1개 |
| 분류축을 바로잡은 뒤 broad 전체에서 명시적 지원방식 근거가 없는 조사 백로그 | 306개 사업, 796행 |

즉, **로컬 자료가 아예 없는 최소 잔여는 1개**이지만, **현재 근거만으로 명시적
지원방식을 설명 가능하게 확정할 수 없는 대시보드 잔여는 140개**입니다. 140개 중
5개는 재료비·학교운영비를 근거로 한 약한 직접수행 후보이고, 나머지 135개는 현재
규칙 후보 자체가 없습니다. 또한 기존 열에 R&D·시설·
정보화·운영 같은 사업특성이 값으로 들어간 행까지 재정지원방식 관점에서 다시 보면,
전체 조사 백로그는 306개로 늘어납니다. 이 세 숫자는 질문과 분모가 다르므로 서로
대체해서 사용하면 안 됩니다.

## 2. 감사 범위와 기준 단위

### 2.1 범위

- 부처: 고용노동부 `019`, 보건복지부 `075`, 중소벤처기업부 `102`,
  과학기술정보통신부 `162`
- 연도: 2022~2024년
- 제외: 행정안전부 `101`, 분석연도 2025년
- 2025년 자료: 원본·정규화 계층에는 보존하되 이번 feature와 dashboard 산출에는 사용하지 않음

### 2.2 기준 grain

| 도메인 | 한 행의 기준 | 권장 PK |
|---|---|---|
| 세부사업 재정 | 부처 × 연도 × 회계 × 프로그램 × 단위사업 × 세부사업 | `project_year_id` |
| 프로그램 재정 | 부처 × 연도 × 회계유형 × 프로그램 | `program_year_account_id` |
| 성과 | 부처 × 성과목표 × 성과지표 × 연도 | `source_indicator_id` |
| 월별 집행 | 세부사업 × 집행연월 × 회계 | `project_month_id` |
| 사업 연속성 | 선행 사업-연도 × 후행 사업-연도 | `relation_id` |

기존 `project_id`는 어떤 테이블에서는 연도 포함 ID이고, 다른 테이블에서는 연도 간
안정 ID입니다. v3에서는 의미를 다음처럼 고정합니다.

- `project_id`: 연도 간 안정 사업 식별자
- `project_year_id`: 사업-연도 식별자
- 안정 ID를 만들 근거가 없으면 억지 해시를 만들지 않고 `identity_status=UNRESOLVED`

### 2.3 실제 범위 규모

| 모집단 | 행 | 고유 안정 사업 | 본예산 |
|---|---:|---:|---:|
| 전체 project-year master | 6,076 | 안전 ID 기준 2,740 | 1,070.560조 원 |
| broad | 3,974 | 1,638 | 581.964조 원 |
| core | 3,939 | 1,626 | 579.852조 원 |
| 현행 M3 정책사업 신호 범위 | 3,927 | 1,616 | 575.800조 원 |

모집단별 목적이 다르므로 행 수와 금액을 서로 합산하지 않습니다.

## 3. TRUE_UNKNOWN의 운영 정의

TRUE_UNKNOWN은 행 전체의 낙인이 아니라 **필드별 상태**여야 합니다.

### 3.1 채택한 상태 체계

| 상태 | 의미 | 분석 처리 |
|---|---|---|
| `PRESENT` | 값과 근거가 있음 | 해당 분석에 사용 |
| `CANDIDATE` | 자동 규칙이 단일 후보를 냈으나 확정 전 | 절대값 설명 가능, 동료집단 비교 제한 |
| `AMBIGUOUS` | 복수 후보 또는 출처 충돌 | 후보 보존, 임의 단일화 금지 |
| `REVIEW_REQUIRED` | 근거는 있으나 의미 판단 필요 | 우선순위 높은 건만 사람 검수 |
| `RECOVERABLE` | 현재 저장소의 다른 표에서 결정적으로 복구 가능 | 자동 조인·재산출 |
| `STRUCTURAL_MISSING` | 관측창 경계나 비적용처럼 구조적으로 값이 없음 | 결측 오류로 집계하지 않음 |
| `NOT_APPLICABLE` | 해당 개념이 적용되지 않음 | 해당 분석만 제외 |
| `TRUE_UNKNOWN` | 정한 공식 출처 범위를 확인했지만 값을 결정할 근거가 없음 | 필드별 분석 제한 |
| `CONFLICT` | 공식 출처가 서로 다른 값을 제시 | 출처·후보 보존 후 검수 |

저장 계약은 다음처럼 단순화합니다.

```text
value       = 실제 값 또는 null
status      = 위 상태 중 하나
evidence_id = 근거 레코드 참조
```

문자열 `UNKNOWN`을 실제 값으로 저장하지 않습니다. 결측을 0으로 바꾸지도 않습니다.

### 3.2 “TRUE_UNKNOWN 0건” 정의를 채택하지 않은 이유

사업명이나 프로그램명이 존재한다는 사실은 “텍스트 근거가 있다”는 뜻일 뿐,
보조·출연·융자·출자 같은 재정지원방식을 판별할 수 있다는 뜻은 아닙니다. 따라서
텍스트가 하나라도 있으면 TRUE_UNKNOWN이 아니라고 보는 정의는 이 프로젝트의
의사결정 목적에 맞지 않습니다.

반대로 `fiscal_instrument=UNKNOWN` 767개를 모두 진짜 근거 부재로 보는 것도 과장입니다.
공식 세목자료에 지원방식이 명시된 단일·복수 후보가 632개이기 때문입니다.

## 4. 재정지원방식 감사

### 4.1 현행 대시보드 정책사업 767개

세부사업 예산과 총지출 세목 원천을 함께 연결한 결과입니다.

| 분류 | 사업 수 | 처리 |
|---|---:|---|
| 단일 세목 규칙 후보 | 578 | `CANDIDATE`; 소규모 골드·상위 후보부터 확인 후 확정 |
| 복수 세목 규칙 후보 | 54 | 복수 행으로 보존; 하나로 강제하지 않음 |
| 기타 이전성 세목군 | 74 | `REVIEW_REQUIRED`; 세목명만으로 보조/출연을 단정하지 않음 |
| 운영성·기타 로컬 세목군 | 60 | `REVIEW_REQUIRED`; “이전성 세목 없음 = DIRECT” 자동확정 금지 |
| 로컬 세목자료 없음 | 1 | `TRUE_UNKNOWN` 후보; 외부 공식 근거 추가 확인 |
| 합계 | 767 |  |

위 표는 현재 후보 규칙을 그대로 재현한 상호배타적 버킷입니다. 이 규칙은
`재료비|학교운영비`를 `DIRECT_EXPLICIT` 후보로 취급하므로 단일·복수 후보 632개 중
13개에 이 신호가 포함되고, 그중 5개는 이 신호만 있습니다. 재료비가 있다는 사실만으로
DIRECT를 확정하는 것은 강하므로, 도메인 해석에서는 다음 보수적 수를 함께 사용합니다.

- 이름에 보조·출연·융자·출자·이차보전이 직접 나타난 사업: 627개
- 이 중 단일 명칭 후보: 581개
- 복수 명칭 후보: 46개
- 명시적 지원방식 명칭이 없는 사업: 140개

따라서 대시보드의 현재 후보 규칙을 검증할 때는 `578/54/74/60/1`을 사용하고,
재정지원방식의 실제 근거 공백을 설명할 때는 `627/140`을 사용합니다.

로컬 세목자료가 없는 1개는 중소벤처기업부 2022년 `소상공인 방역지원금`입니다.
중소벤처기업부의 [공식 시행 공고](https://www.mss.go.kr/common/board/Download.do?bcIdx=1030739&cbIdx=126&streFileNm=ded761b1-70f7-48c8-b7c6-9b8007534948.pdf)는
직접 지원사업이라는 성격을 확인해 주지만, 현재 저장소에서
필요한 정확한 예산 세목·회계상 지원방식까지 확정하지는 못하므로 외부 설명자료 근거를
추가하기 전에는 단일 지원방식으로 확정하지 않습니다.

### 4.2 현재 scalar UNKNOWN과 실제 지원방식 공백의 차이

현행 `fiscal_instrument` 열에는 다음 두 축이 섞여 있습니다.

- 재정지원방식: `SUBSIDY`, `CONTRIBUTION`, `LOAN`, `GUARANTEE`, `EQUITY`,
  `INTEREST_SUBSIDY`
- 사업특성: `RND`, `FACILITY`, `INFORMATIZATION`, `OPERATION`, `DIRECT`

전체 6,076행 중 지원방식 값이 실제로 들어간 행은 134행뿐이며, 사업특성 값은
2,757행입니다. 따라서 현재 scalar UNKNOWN만 메우면 “분류 완료”처럼 보이지만 실제
지원방식 축은 대부분 비어 있게 됩니다.

| 기준 | 행 | 안전 ID 기준 사업 | 본예산 |
|---|---:|---:|---:|
| 현행 broad scalar UNKNOWN | 1,922 | 800 | - |
| 그중 어느 관측연도에도 명시적 지원방식 근거가 없는 잔여 | 399 | 158 | 12.084조 원 |
| 축 분리 후 broad 지원방식 결측 | 3,852 | - | - |
| 축 분리 후 어느 관측연도에도 명시적 지원방식 근거가 없는 잔여 | 796 | 306 | 171.083조 원 |

306개는 바로 “정책적으로 지원방식이 없는 사업”이라고 확정한 수가 아닙니다.
현재 정한 로컬 원천과 규칙에서 **명시적 지원방식 근거가 나오지 않은 조사 백로그**입니다.
DIRECT·자체수행·복합사업의 도메인 규칙을 정하면 일부는 `NOT_APPLICABLE` 또는
`PRESENT`로 이동할 수 있습니다.

### 4.3 완료 수기 워크북의 역할

완료된 `data/manual/unknown_priority_fiscal_instrument_review.xlsx`는 현재 범위에서
15개 사업·44개 사업-연도를 고신뢰 근거로 제공합니다.

- 단일 지원방식 확정 13개
- 범위 제외 1개
- 공식 복합수단 1개

세목 단일 후보가 나온 골드 8개는 모두 수기 확정값과 일치했지만, 검증 표본이 작고
복합수단의 일부만 포착한 반례가 있으므로 모든 단일 후보를 자동확정하는 근거로는
부족합니다. `unknown_top16_fiscal_instrument_review.xlsx`는 확정 0건인 과거 미완료본이므로
근거로 사용하지 않습니다.

## 5. 다른 필드의 진짜 잔여

### 5.1 빠른 요약

| 필드·문제 | 현재 관측 | 판단 | 권장 처리 |
|---|---:|---|---|
| KPI 분석준비본 | 424행 | PK 중복 0 | 유지 |
| 019·075·162 PDF 상태 null | 361행 | 별도 reconciliation과 1:1 연결 가능 | `RECOVERABLE` |
| KPI 실적 숫자 결측 | 8행 | 종료 2, 범주형 1, 공식 미보고 5 | raw/value_type/status 분리 |
| KPI 달성률 결측 | 5행 | 공식 미보고·비수치 | 결측을 0점 처리 금지 |
| KPI 특수 산식 | 3행 | 단순 목표/실적 산식으로 재현 불가 | 수식 검수 |
| 계층코드 없는 2024 사업 | 9행 | 1개는 2025 참고자료로 복구, 8개 로컬 잔여 | 분석자료와 참고자료 분리 |
| 안정 ID 충돌 | 10행 | 모든 계층값 null인데 같은 해시로 합쳐짐 | `identity_status=UNRESOLVED` |
| 기금 집행분모 부재 | 16행 | 월별 지출계획현액 0, 결산값 대체 금지 | 집행률만 제한 |
| 후보 큐의 UNMATCHED 프로그램 | 4개 | 회계 세부구분을 중복으로 오인한 grain 문제 | 자동 재집계 |
| 전체 program master UNMATCHED | 348행 | 구조적 172, 로컬복구 167, 복수 2, 근거없음 7 | 상태 분해 |
| 관계 literal UNKNOWN | 0 | 다만 검증 전 후보 801건 존재 | 후보와 확정 분리 |

### 5.2 성과 데이터

성과지표 424행은 `source_indicator_id` 기준 중복이 없습니다. 문제는 값 부재보다
근거 연결 계약입니다.

- 019·075·162의 361행은 분석준비본에서 `pdf_reconciliation_status=null`이지만,
  별도 PDF 대조 Parquet 361행과 모두 1:1로 연결됩니다.
- 중소벤처기업부 63행만 현재 분석준비본에 PDF 상태가 함께 들어 있습니다.
- 보고서 목표 결측 361건 중 354건은 기존 로컬 PDF reconciliation로 복구됩니다.
- 실적값 숫자 결측 8건은 종료·범주형·공식 미보고가 섞여 있습니다. 이는 “값 0”이나
  “파싱 실패”로 통합하면 안 됩니다.
- 고용평등증진과 중소기업성장안정지원은 하나의 재정 프로그램에 복수 성과목표가
  연결됩니다. 성과 bridge에 재정금액을 복사해 합산하면 5.263조 원이 중복될 수 있습니다.

따라서 성과 fact에는 raw/text/numeric/value_type을 보존하고, 프로그램 재정금액은
성과 bridge에 저장하지 않습니다.

### 5.3 프로그램 연결

현재 후보 큐에서 DATA_BLOCKED로 보이는 특별회계 UNMATCHED 4개는 원천 부재가 아닙니다.
같은 사업 계층키에 여러 `account_category_name`이 존재하는 것을 중복으로 처리해 금액을
null로 만든 grain 오류입니다. 회계 세부구분을 원천 grain에 포함하거나, 정식 프로그램
단위로 합산한 뒤 중복 여부를 판정하면 복구됩니다.

전체 program master의 UNMATCHED 348행도 다음처럼 분해됩니다.

- 로컬 복구 167
- 구조적 비대상 172
- 복수 후보 2
- 공식 근거 없음 7

따라서 348행 전체를 사람 검수로 보내지 않습니다.

### 5.4 집행분모와 누락값

보건복지부 2022년 연금기금 16행은 본예산·예산현액·결산 지출액이 있지만 월별 원천의
기금 지출계획현액이 0입니다. 결산 예산현액을 대신 넣으면 멘토링에서 정한 기금 분모
원칙을 위반하므로 다음처럼 처리합니다.

- 예산규모 분석: 포함
- 결산 지출액 분석: 포함
- 기금 집행률: `TRUE_UNKNOWN` 또는 `SOURCE_MISSING` 상태로 제한
- 행 전체: 삭제하지 않음

계층코드가 모두 빠진 9행은 현재 M3에서 본예산 0처럼 보이지만 실제로는 원천 금액이
없다는 뜻입니다. v3에서는 `amount=null`, `status=SOURCE_MISSING`으로 저장합니다.

### 5.5 관측창과 2025년 누출

2024년 사업상태와 환류 신호 일부가 2025년 자료의 영향을 받습니다.

- 2023년 T+2→2025년 신호·맥락: 후보 19개
- 2024년 T+1→2025년 신호·맥락: 후보 16개
- 합계: 후보 35개

이번 분석창에서는 2024년을 종료 여부가 관측되지 않은 `RIGHT_CENSORED`로 두어야 합니다.
2025년 원자료는 삭제하지 않고 참고 evidence 영역에만 남깁니다. 향후 2025년을 환류
결과연도로 사용할 때는 `base_years`와 `support_outcome_years`를 별도 설정으로 명시합니다.

또한 2022년 1,291행이 관측창 시작이라는 이유만으로 월별 패턴 부적격이 되어 있습니다.
관측창 경계는 추세만 제한해야 하므로, 월별 자료가 12개월 존재하는 행은 월별 패턴
분석에 복구합니다.

## 6. 현재 순위에 직접 영향을 주는 오류

### 6.1 UNKNOWN을 동료집단으로 사용

ranking v2는 UNKNOWN 재정수단 비교를 부적격으로 표시하지만 M3는 적격 플래그를 확인하지
않고 UNKNOWN끼리 상대순위를 계산합니다.

그 결과 UNKNOWN 행에 다음 상대신호가 이미 생성되었습니다.

- 집행률 하위 10%: 184행
- 집행률 하위 20%: 340행
- 예산 급증: 50행
- 예산 급감: 49행

확정 지원방식이 없으면 UNKNOWN 집단을 만들지 않고 `연도 × 회계유형`으로 후퇴해야
합니다. 이때 `peer_definition`, `peer_n`, `fallback_level`, `reliability`를 함께 저장합니다.

### 6.2 무관한 조건이 T+1·T+2 환류를 차단

2022~2024 안에서 완결되는 코호트 중 base/outcome 예산은 존재하지만 후속 종료,
집행률 결측, 연속성 후보 등의 무관한 조건으로 465행·92.114조 원의 base 예산이
환류 분석에서 제외됩니다.

예산 환류 적격성은 다음처럼 독립적으로 정의합니다.

```text
budget_feedback_eligible
= base_original_budget 존재
AND outcome_original_budget 존재
AND predecessor chain이 유일하게 연결됨
```

집행률·결산·재정수단 적격성은 각 분석의 별도 플래그로 둡니다.

### 6.3 전역 evidence 상태

현재 후보 412행의 전역 `evidence_status`는 PDF 근거 상태가 아니라 세부사업의 최악
`rank_confidence`를 요약한 값입니다.

- CONFIRMED 37
- LIMITED 360
- DATA_BLOCKED 15

재정수단 하나가 불명확하다는 이유로 성과·절대집행·환류 근거 전체가 LIMITED처럼
보입니다. 다음처럼 신호별 신뢰도를 분리합니다.

- `performance_reliability`
- `execution_reliability`
- `feedback_reliability_t1`
- `feedback_reliability_t2`
- `structure_reliability`

## 7. 권장 v3 데이터모델

새 DB·ORM·웨어하우스를 도입할 필요는 없습니다. 기존 Parquet와 pandas를 유지하고
논리적 계약만 정리합니다.

```text
raw / normalized                     evidence
  budget, monthly, settlement, PDF     evidence_record
              │                        quality_issue
              └─────────┬──────────────────┘
                        ▼
                       core
  project ─ project_year ─ project_month ─ amount_event
      │           │
      │           ├─ project_financing_mechanism (복수 행 허용)
      │           └─ project_characteristic       (복수 행 허용)
      │
  program_year_account ─ performance_goal_program ─ kpi_year
                        │
                        ▼
                      feature
       project_year_features / program_year_account_features
                        │
                        ▼
                      exports
       project_review_queue / program_review_queue / workbench
```

### 7.1 최소 핵심 테이블

| 테이블 | 한 행 | 핵심 역할 |
|---|---|---|
| `dim_project` | 안정 사업 1개 | 안정 ID와 명칭 이력 |
| `fact_project_year_financial` | 사업-연도 1개 | 금액과 필드별 적격성 |
| `fact_program_year_account` | 프로그램-연도-회계유형 1개 | 공식 전체와 분석대상 금액 분리 |
| `fact_kpi_year` | 성과지표-연도 1개 | raw/text/numeric/type/근거 |
| `bridge_performance_goal_program` | 성과목표-프로그램 연결 1개 | 연결근거만 저장, 금액 없음 |
| `project_financing_mechanism` | 사업-연도-지원방식 assertion 1개 | 복수 지원방식과 후보 보존 |
| `project_characteristic` | 사업-연도-특성 assertion 1개 | R&D·시설·정보화·운영 분리 |
| `evidence_record` | 근거 조각 1개 | 파일·페이지·행·필드·원문 추적 |
| `quality_issue` | 엔터티-필드-이슈 1개 | 중복 umbrella flag 제거 |

월별 집행과 금액 이벤트의 기존 long 구조는 재사용합니다. 현행 138~239열짜리 wide
master를 새 이름으로 복사하지 않습니다.

### 7.2 `quality_issue` 최소 계약

```text
entity_type
entity_id
field_name
issue_code
status
candidate_count
evidence_id
blocks_analysis_type
```

`manual_review_required`, `analysis_eligible`, `classification_status`는 이 테이블에서
파생한 view로 제공합니다. 같은 원인을 UNKNOWN·manual·unmatched로 세 번 집계하지 않습니다.

### 7.3 재정지원방식과 사업특성

```text
project_financing_mechanism
- project_year_id
- mechanism_code
- amount
- amount_share
- classification_status
- evidence_id
- review_status

project_characteristic
- project_year_id
- characteristic_code
- classification_status
- evidence_id
```

`출연 + R&D`, `직접 + 보조`를 오류로 처리하지 않습니다. 금액배분 근거가 없으면
대표 지원방식을 임의 선택하지 않고 더 넓은 회계유형 동료집단으로 후퇴합니다.

## 8. 마이그레이션 계획

### 단계 0. 기준선 동결

- 4개 부처·2022~2024년의 입력 해시, 행 수, PK, 금액 합계를 기록합니다.
- 2025년 영향을 제거한 후보·신호 기준선을 별도로 저장합니다.
- 기존 결과는 삭제하지 않습니다.

### 단계 1. 결과를 왜곡하는 P0 오류 수정

1. 2025년 feature 영향 35개 후보 제거
2. UNKNOWN 동료집단 비교 중단
3. 코드 없는 9행의 금액 0을 null+상태로 변경
4. 모든 계층값 null인 10행의 안정 ID 충돌 해소
5. 2022 관측창 시작 행의 월별 패턴 과잉제외 해소
6. 4개 특별회계 UNMATCHED의 grain 집계 수정

### 단계 2. 이미 있는 근거 연결

1. 019·075·162 PDF reconciliation 361행 연결
2. 중소벤처기업부 성과-프로그램 매핑을 최신 프로그램 master로 재생성
3. 성과 bridge에서 반복 금액 제거
4. 완료 수기 재정수단 근거 15개 사업 반영

### 단계 3. 분류축 분리

1. 지원방식과 사업특성을 별도 다중값 테이블로 생성
2. 세목 단일 578개는 `CANDIDATE`, 복수 54개는 복수 assertion으로 적재
3. 기타 이전성 74개·운영성·기타 60개와 약한 직접수행 후보 5개는 예산영향과
   최종 점검후보 여부로 검수 우선순위화
4. 306개 조사 백로그는 전체 수기검수하지 않고 공식 세목·사업설명자료 자동 연결을 먼저 수행

### 단계 4. slim core와 feature 병행 생성

- 기존 v2 산출물을 유지한 채 core·evidence·feature를 병행 생성합니다.
- 신호마다 별도 적격성과 reliability를 계산합니다.
- UNKNOWN 동료집단을 제거하고 fallback 경로를 기록합니다.
- budget feedback 적격성에서 집행·결산 조건을 분리합니다.

### 단계 5. 호환 어댑터와 대시보드 전환

- v3에서 현재 dashboard 입력을 재생성하는 임시 adapter를 둡니다.
- 행 수·금액·절대신호·후보 수를 비교합니다.
- 의도적으로 달라지는 상대신호와 2025 영향만 별도 diff로 승인합니다.
- 대시보드는 compact `data/exports`만 읽도록 바꿉니다.

### 단계 6. 레거시 퇴역

대시보드 전환과 수치 대조가 끝난 뒤에만 다음을 퇴역합니다.

- wide `ranking_population_v2`
- wide `financial_signal_features`
- candidate 전체를 복제한 program queue
- 전역 `rank_confidence`, `evidence_status`
- 문자열 `comparison_group`
- 중복 상태·사유 열과 세미콜론 목록

원본, 수기검수 파일, PDF reconciliation, 금액 이벤트, 월별 Parquet는 삭제하지 않습니다.

## 9. 검증 게이트

v3는 아래를 모두 만족한 뒤에만 기존 결과를 대체합니다.

1. 각 테이블 선언 grain의 PK 중복 0
2. 분석 feature·export에 행안부와 기준연도 2025 행 0
3. 이번 엄격 범위에서 2025 outcome을 사용하는 후보 0
4. 핵심 null은 모두 필드별 상태를 가짐
5. `PRESENT/CANDIDATE/AMBIGUOUS/TRUE_UNKNOWN/CONFLICT`는 근거를 가짐
6. business value 열의 literal `UNKNOWN` 0
7. 지원방식과 사업특성 동시 존재를 오류로 처리한 행 0
8. 미확정 지원방식으로 UNKNOWN 동료집단을 만든 행 0
9. 금액유형별 합계와 프로그램-세부사업 합계 차이 허용오차 0.5원 이하
10. 성과지표 424행과 근거 레코드 연결, `source_indicator_id` 중복 0
11. 성과 bridge를 통한 재정금액 중복 합산 0
12. 기존 ID에서 새 ID와 원본 파일까지 역추적 가능
13. 절대신호는 기존과 동일하고, 상대신호 변경은 의도적 diff로 설명됨
14. 대시보드는 `data/exports`에서만 읽고 산식을 복제하지 않음

## 10. 사람 검수는 무엇만 남길 것인가

전체 767개나 306개를 사람이 처음부터 읽는 방식은 권장하지 않습니다.

검수 순서는 다음과 같습니다.

1. 최종 점검후보에 실제로 올라온 사업
2. 예산 커버리지가 큰 사업
3. 복수 지원방식 54개 중 상대비교 결과에 영향을 주는 사업
4. 기타 이전성 74개·운영성·기타 60개와 약한 직접수행 후보 5개 중
   동료집단 선택이 바뀌는 사업
5. 로컬 세목자료가 없는 1개

사람이 확인할 화면에는 다음만 보여주면 됩니다.

- 현재 후보와 후보가 나온 이유
- 원문 세목명·사업명·페이지 또는 원천 행
- 후보별 근거
- 확정 시 바뀌는 동료집단과 신호
- `확정 / 복수 유지 / 비적용 / 근거 부족` 네 가지 결정

근거가 있는 자동후보는 기본적으로 evidence와 함께 수용하고, 최종 우선순위나 동료집단이
실제로 달라지는 건만 표본 검수합니다.

## 11. 지금 하지 않을 것

- 원본·수기파일·기존 v2 산출물을 일괄 삭제하지 않습니다.
- 4개 부처 PDF를 다시 전부 파싱하지 않습니다.
- 767개를 전부 수기분류하지 않습니다.
- UNKNOWN을 0점이나 안전으로 처리하지 않습니다.
- 재정수단·사업특성·회계유형을 하나의 복합코드로 만들지 않습니다.
- 프로그램 성과를 세부사업 성과로 귀속하지 않습니다.
- v3 검증 전에 대시보드 산식을 동시에 다시 쓰지 않습니다.

## 12. 권장 바로 다음 작업

다음 구현은 전체 리팩터링이 아니라 **단계 0~1의 호환성 유지 수정**이어야 합니다.

1. 현재 4개 부처·2022~2024 기준선을 동결합니다.
2. 2025 feature 누출과 UNKNOWN 동료집단을 먼저 차단합니다.
3. ID 충돌·missing-as-zero·월별 과잉제외·특별회계 grain 오류를 수정합니다.
4. 동일 dashboard 입력을 재생성해 수치 차이를 검토합니다.

이 네 작업이 통과하면 단계 2의 PDF 근거 연결과 분류축 분리를 진행합니다. 이 순서가
현재 결과를 잃지 않으면서도 가장 큰 왜곡부터 제거하는 최소 경로입니다.

## 13. 재현에 사용한 주요 파일

- `data/processed/masters/project_year_financial_v2.parquet`
- `data/processed/masters/population_sensitivity/ranking_population_v2.parquet`
- `data/analytics/m3/financial_signal_features.parquet`
- `data/processed/masters/program_year_financial.parquet`
- `data/processed/budget/budget_records.parquet`
- `data/processed/amount_event/budget_amount_events.parquet`
- `data/processed/monthly_expenditure/monthly_expenditure_2022_2025.parquet`
- `data/processed/settlement/project_settlement.parquet`
- `data/processed/masters/project_relation.parquet`
- `data/processed/performance/analysis_ready/program_kpi_year_analysis_ready.parquet`
- `data/processed/performance/by_ministry/ministry_code=*/analysis_ready/program_kpi_year_analysis_ready.parquet`
- `data/processed/performance/pdf_reconciliation/**/*.parquet`
- `data/manual/unknown_priority_fiscal_instrument_review.xlsx`
- `data/analytics/multi_ministry_priority_scenarios/candidate_population.csv`
- `data/analytics/multi_ministry_priority_scenarios/full_population_project_review_queue.csv`
- `data/analytics/multi_ministry_priority_scenarios/review_workbench_queue.csv`

검수용 원천과 evidence는 별도 테이블로 유지하며, 과거 미완료 CSV·워크북을 확정 근거로
사용하지 않습니다.

### 13.1 재정지원방식 버킷 재현 규칙

정확 조인 키는 다음 6개입니다.

```text
fiscal_year
ministry_code
account_code
program_code
activity_code
subactivity_code
```

세목 원천은 `expenditure_budget_init_item`과 `total_expenditure_item`만 사용합니다.
`item_name + subitem_name`에서 사업별로 다음 규칙 신호를 고유 집계합니다.

```text
SUBSIDY            = 보조
CONTRIBUTION       = 출연
LOAN               = 융자
EQUITY             = 출자 또는 지분취득
INTEREST_SUBSIDY   = 이차보전
DIRECT_EXPLICIT    = 재료비 또는 학교운영비  # 약한 후보, 자동확정 금지
```

신호가 1개면 단일 후보 578개, 2개 이상이면 복수 후보 54개입니다. 나머지에서
`민간이전·자치단체이전·해외이전·보전금·반환금및손실금`의 합집합은 74개,
다른 로컬 세목이 있는 잔여는 60개, 세목 조인행이 없는 잔여는 1개입니다.

기타 이전성 집계에서는 `item_name` 집합 73개와 `반환금및손실금` 집합 3개를
단순 합산하지 않습니다. 정책자금지원성과향상과 우편집배업무 2개가 두 집합에 동시에
속하므로 합집합은 74개입니다.
