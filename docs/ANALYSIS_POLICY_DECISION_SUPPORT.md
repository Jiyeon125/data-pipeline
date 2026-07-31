# 분석 기준 의사결정 지원 보고서

## 기술 요약

집행률 분석 적격·100% 초과 제외 모집단은 6,102행입니다. 80% 미만은 253행(4.1%), 90% 미만은 510행(8.4%)입니다. 80%와 90%는 분포가 자동으로 발견한 절단점이 아니라, 탐지 강도를 두 단계로 설명하기 위한 잠정 운영 기준입니다.

권장안은 `<80%`를 강한 집행설명필요, `80~90%`를 주의 신호로 구분하고, 보수적 하위 10%는 신뢰도 등급이 있는 보조 신호로 사용하는 것입니다. 연말집중은 4분기 40% 또는 12월 20%를 주 탐색 기준 후보로 두되 두 유형을 분리하며, 보수적 P90은 비교집단 맥락만 제공합니다. 반복은 같은 신호가 2회 이상이면서 유효 관측연도의 50% 이상일 때 주 반복 후보로 봅니다.

이 문서는 최종 임계값이나 전체 순위를 저장하지 않습니다. 모든 표·그림은 `data/analytics/decision_support/`의 CSV를 직접 수정·재분석할 수 있게 구성했고, 기존 M3와 원본 데이터는 덮어쓰지 않았습니다.

## 1. 집행률 분포를 읽는 법

ECDF의 파란 실선은 사업-연도 수 기준, 주황 점선은 예산현액 가중 기준입니다. 같은 집행률에서 주황선이 더 높으면 저집행 구간이 차지하는 예산 비중이 사업 수 비중보다 크다는 뜻입니다. 80%·90% 수직선은 후보 기준이며, 그래프는 전체·회계유형·부처·연도·사업규모별로 분리했습니다.

![execution_ecdf_overall.png](../artifacts/figures/decision_support/execution_ecdf_overall.png)

![execution_ecdf_by_account_type.png](../artifacts/figures/decision_support/execution_ecdf_by_account_type.png)

![execution_ecdf_by_ministry.png](../artifacts/figures/decision_support/execution_ecdf_by_ministry.png)

![execution_ecdf_by_year.png](../artifacts/figures/decision_support/execution_ecdf_by_year.png)

![execution_ecdf_by_project_size.png](../artifacts/figures/decision_support/execution_ecdf_by_project_size.png)

발표 시에는 전체 ECDF로 기준 위치를 설명하고, 질의응답에서는 회계·부처별 패널로 특정 집단 편향 여부를 답하는 방식이 적절합니다.

## 2. 70~95% 민감도는 기준 변경의 영향을 보여줍니다

80% 기준은 고유 사업 168개와 예산현액 1.8%를 탐지합니다. 90% 기준은 고유 사업 290개와 예산현액 3.0%를 탐지합니다. 두 값을 합쳐 하나의 정책 판정으로 쓰지 않고 강한 신호와 주의 신호로 나누는 이유입니다.

![execution_threshold_sensitivity.png](../artifacts/figures/decision_support/execution_threshold_sensitivity.png)

그래프의 기울기는 임계값을 1%p 높였을 때 새로 포함되는 사업·금액의 크기입니다. 가장 큰 1%p 증가 구간 세 개는 자동 임계값이 아니라 추가 확인 후보로만 표시했습니다.

| 증가순위 | 임계값 | 추가 행 | 추가 행 비율 | 추가 예산현액 비율 |
|---:|---:|---:|---:|---:|
| 1 | 95% | 95 | 1.6% | 1.6% |
| 2 | 94% | 79 | 1.3% | 2.0% |
| 3 | 93% | 72 | 1.2% | 1.3% |

89%에서 90%로 이동할 때 새로 포함되는 행은 39개지만 예산현액 비중은 0.2%p 증가합니다. 90% 기준의 금액 영향은 소수 대규모 사업에 민감하므로 해당 구간 원자료를 별도 보존했습니다.

| 부처 | 프로그램 | 세부사업 | 연도 | 집행률 | 예산현액 |
|---|---|---|---:|---:|---:|
| 고용노동부 | 고용안전망확충 | 조기재취업수당 | 2022 | 89.2% | 0.52조원 |
| 고용노동부 | 고용창출 | 청년내일채움공제(고보) | 2022 | 89.5% | 0.43조원 |
| 행정안전부 | 전자정부 | 국가정보관리원대구센터신축(정보화) | 2023 | 89.9% | 0.09조원 |
| 보건복지부 | 응급의료체계운영지원 | 응급의료기관지원발전프로그램 | 2025 | 90.0% | 0.08조원 |
| 과학기술정보통신부 | 과학기술기반조성 | 국제과학비즈니스벨트조성(R&D) | 2024 | 89.4% | 0.06조원 |

예산현액 상위 두 행 가운데 재정수단 `UNKNOWN`은 2행, 현재 분석 포함 분류는 2행입니다. 따라서 90% 기준의 금액 비중을 발표하기 전에는 이 대규모 사업들의 정책사업 범위와 재정수단을 먼저 확인해야 합니다. 이 표는 기준을 폐기하는 근거가 아니라 금액가중 결과가 분류 검토에 민감하다는 근거입니다.

현재 범위에서 90% 미만 탐지 예산현액 비중은 3.0%이며, 보통교부세를 민감도에서 제외하면 3.0%입니다. 국채·채권매입은 범위 규칙 적용 후 현재 M3에 0행입니다.

## 3. 같은 기준이라도 집단별 탐지율이 다릅니다

편향 배수는 `집단 탐지율 / 전체 탐지율`입니다. 2배 이상 또는 0.5배 이하는 원인을 확인하기 위한 진단 표시이며 해당 집단을 제외하거나 기준을 바꾸는 정책 규칙이 아닙니다. 표본 20행 미만은 별도 소표본으로 표시했습니다.

![threshold_group_bias_heatmap.png](../artifacts/figures/decision_support/threshold_group_bias_heatmap.png)

### 80% 기준에서 우선 확인할 집단

| 차원 | 집단 | 적격 행 | 탐지율 | 전체 대비 배수 |
|---|---|---:|---:|---:|
| ACCOUNT_TYPE | RESPONSIBLE_OPERATION_ACCOUNT | 182 | 23.1% | 5.57x |
| FISCAL_INSTRUMENT | GUARANTEE | 44 | 22.7% | 5.48x |
| DATA_QUALITY | RESTRICTED | 255 | 12.9% | 3.12x |
| FISCAL_INSTRUMENT | LOAN | 60 | 11.7% | 2.81x |
| FISCAL_INSTRUMENT | FACILITY | 141 | 10.6% | 2.57x |
| FISCAL_INSTRUMENT | OPERATION | 684 | 10.4% | 2.50x |

### 90% 기준에서 우선 확인할 집단

| 차원 | 집단 | 적격 행 | 탐지율 | 전체 대비 배수 |
|---|---|---:|---:|---:|
| ACCOUNT_TYPE | RESPONSIBLE_OPERATION_ACCOUNT | 182 | 44.5% | 5.32x |
| DATA_QUALITY | RESTRICTED | 255 | 36.9% | 4.41x |
| FISCAL_INSTRUMENT | GUARANTEE | 44 | 27.3% | 3.26x |
| FISCAL_INSTRUMENT | FACILITY | 141 | 20.6% | 2.46x |
| FISCAL_INSTRUMENT | OPERATION | 684 | 19.9% | 2.38x |
| PROJECT_SIZE | Q1_SMALL | 778 | 17.7% | 2.12x |

## 4. 상대 기준은 적용 가능성과 신뢰도를 분리합니다

하위 10% 기준의 비교집단-연도 128개 중 NOT_AVAILABLE 80개, LOW 21개, MEDIUM 13개, HIGH 14개입니다.

![peer_distribution_diagnostics.png](../artifacts/figures/decision_support/peer_distribution_diagnostics.png)

| 기대 꼬리 관측 수 | 적용 가능 | 잠정 신뢰도 | 사용 원칙 |
|---:|---|---|---|
| 2개 미만 | 아니오 | NOT_AVAILABLE | 상대 신호를 산출하지 않음 |
| 2~4개 | 예 | LOW | 단독 근거로 사용하지 않음 |
| 5~9개 | 예 | MEDIUM | 절대 기준의 보조 근거 |
| 10개 이상 | 예 | HIGH | 비교집단 보조 신호로 표시 |

이 등급은 잠정 후보입니다. 비교집단이 크더라도 고유 집행률 값이 적거나 최대 동률 블록이 크면 상대순위 해석을 낮춰야 합니다. `peer_distribution_diagnostics.csv`에서 집단별 경계값·동률 수를 직접 확인할 수 있습니다.

## 5. 연말집중은 4분기형과 12월형을 분리해야 합니다

검증된 월별 패턴에서 4분기 기준만 충족한 행은 77행, 12월 기준만 충족한 행은 202행, 두 기준을 모두 충족한 행은 172행입니다. 고정 기준은 충족하지 않지만 보수적 P90인 행은 90행이고, 고정 기준과 P90을 모두 충족한 행은 325행입니다.

![year_end_pattern_scatter.png](../artifacts/figures/decision_support/year_end_pattern_scatter.png)

세로선 오른쪽은 4분기 집중, 가로선 위는 12월 집중입니다. 우상단은 두 기준을 모두 충족합니다. 점 크기는 예산현액의 로그이므로 큰 점은 금액 영향도 확인 대상이지만 정책 실패를 의미하지 않습니다.

일부 점의 4분기·12월 비중이 0보다 작은 것은 순지출 환수·정산 등 회계 조정 패턴일 수 있습니다. 이 행은 연말집중으로 해석하지 않고 누계 감소·회계 조정 신호와 원자료를 별도로 확인해야 합니다.

![year_end_pattern_by_ministry.png](../artifacts/figures/decision_support/year_end_pattern_by_ministry.png)

부처별 점 구름이 다르면 지급 일정이나 사업구성 차이일 수 있으므로, 고정 기준 탐지율의 차이를 곧바로 성과 차이로 해석하지 않습니다.

## 6. 반복 신호는 유효 관측연도 수와 함께 봅니다

동일 신호가 2회 이상이면서 유효연도의 50% 이상인 사업은 집행률 90% 미만 기준 133개, 고정 연말집중 기준 109개입니다.

![repeated_signal_distribution.png](../artifacts/figures/decision_support/repeated_signal_distribution.png)

x축이 2이고 y축이 100%인 사업은 2년 중 2회이며, x축이 4이고 y축이 50%인 사업은 4년 중 2회입니다. 두 사업은 주 반복 조건을 모두 충족하지만 증거의 두께가 다르므로 유효 관측연도 수를 함께 표시합니다. 주황색 연속 2회는 강화 정보입니다.

고정 연말집중 반복 후보 109개는 현재 모두 유효 월별 관측 2년에서 연속 2회 발생한 사업입니다. 월별 관측 가능한 연도가 제한되어 있으므로 집행률 반복보다 증거가 약하며, 발표에서는 '2년 연속 관찰'로 표현해야 합니다.

## 7. 후보 기준별 의사결정표

![analysis_policy_options.png](../artifacts/figures/decision_support/analysis_policy_options.png)

| 후보 | 분석 단위 | 탐지 행 | 탐지 사업 | 본예산 비중 | 권장 역할 | 안정성 |
|---|---|---:|---:|---:|---|---|
| 집행률 80% 미만 단일 기준 | project_year | 253 | 168 | 1.8% | STRONG_SIGNAL | HIGH_FOR_ABSOLUTE_RULE |
| 집행률 90% 미만 단일 기준 | project_year | 510 | 290 | 2.9% | SENSITIVITY_OR_SUMMARY | HIGH_FOR_ABSOLUTE_RULE |
| 80%·90% 2단계 기준 | project_year | 510 | 290 | 2.9% | PRIMARY_POLICY | HIGH_FOR_ABSOLUTE_RULE |
| 절대 기준과 상대 기준 병행 | project_year | 695 | 387 | 3.6% | PRIMARY_PLUS_AUXILIARY | CONDITIONAL_ON_PEER_CONFIDENCE |
| 연말집중 고정 기준 | project_year | 451 | 342 | 8.9% | PRIMARY_EXPLORATION | MEDIUM |
| 고정 기준과 보수적 P90 병행 | project_year | 541 | 413 | 9.4% | PRIMARY_PLUS_AUXILIARY | CONDITIONAL_ON_PEER_CONFIDENCE |
| 반복 2회 이상 | project | 543 | 212 | 9.3% | SENSITIVITY | LOW_WHEN_VALID_YEAR_COUNT_IS_SMALL |
| 반복 2회 이상 및 유효연도 50% 이상 | project | 543 | 212 | 9.3% | PRIMARY_RECURRENCE | MEDIUM_TO_HIGH_BY_VALID_YEAR_COUNT |
| 연속 2회 강화 신호 | project | 506 | 195 | 9.3% | REINFORCED_SIGNAL | MEDIUM |

### 분석 담당자의 권장안

1. **권장 주 기준:** 집행률 80%·90% 2단계 기준.
2. **권장 강한 신호:** 집행률 80% 미만.
3. **권장 보조 기준:** 신뢰도 등급을 통과한 보수적 하위 10%, 고정 연말집중의 보수적 P90.
4. **권장 민감도 기준:** 집행률 90% 단일 기준, 하위 20%, 연말집중 P80·P95.
5. **권장 반복 기준:** 동일 신호 2회 이상이면서 유효연도의 50% 이상.
6. **권장 강화 정보:** 동일 신호 연속 2회.

### 적용하지 말아야 할 집단

- 집행률 분모가 미확정이거나 100% 초과로 품질 검토가 필요한 행
- 상대 기준 기대 꼬리 관측 수가 2개 미만인 비교집단
- 경계 동률 블록이 커서 상대순위가 사실상 구분되지 않는 비교집단
- 월별 패턴 적격이 아니거나 4분기·12월 비중을 계산할 수 없는 행
- 유효 관측연도 1년 사업의 반복 판정
- 프로그램 집중도를 세부사업 수로 집계하는 방식

### 기준 변경 시 예상 영향

80%에서 90%로 완화하면 탐지 행은 257행, 고유 사업은 122개 늘어납니다. 이는 강한 신호의 확대가 아니라 주의 신호를 추가하는 변화로 해석해야 합니다.

절대 기준과 보수적 상대 기준을 병행하면 탐지 고유 사업 비율은 19.0%입니다. 다만 상대 신호 LOW 집단까지 동일하게 강조하면 비교집단 소표본이 다시 결과를 지배할 수 있습니다.

## 8. 산식과 재현 방법

```powershell
fiscal-analytics build-analysis-policy-decision-support --root .
```

주요 산식:

- 비가중 ECDF: 집행률 이하 사업-연도 누적 수 / 전체 유효 사업-연도 수
- 예산가중 ECDF: 집행률 이하 예산현액 누적 합 / 전체 유효 예산현액 합
- 편향 배수: 집단 탐지율 / 전체 탐지율
- 기대 꼬리 관측 수: 비교집단 크기 × 꼬리비율
- 반복률: 신호 발생연도 수 / 유효 관측연도 수

CSV는 그래프에 표시된 값보다 더 많은 집단·임계값을 포함합니다. 임계값을 바꿔 검토하려면 `execution_threshold_sensitivity.csv`에서 원하는 threshold 행을 필터링하면 됩니다. `execution_threshold_increment_cases.csv`에서 각 1%p 구간에 새로 포함되는 실제 사업을 확인할 수 있습니다. 그래프 원자료와 읽는 법은 `decision_support_chart_map.csv`에 연결했습니다.

## 9. 발표 및 질의응답 대비

### 왜 80%와 90%입니까?

분포가 하나의 자연 절단점을 자동으로 제시해서가 아닙니다. 80% 미만과 80~90%가 탐지 강도와 설명 가능성에서 구분되고, 70~95% 민감도에서 기준 변경 영향을 공개할 수 있기 때문에 두 단계 운영 기준으로 제안했습니다.

### 왜 평균과 표준편차를 사용하지 않았습니까?

집행률은 100% 부근 동률과 경계값이 많고 정규분포가 아니므로 ECDF·분위수·동률 구조를 사용했습니다.

### 왜 사업 수 분포와 예산가중 분포를 같이 봅니까?

사업 수는 탐지 범위를, 예산가중 분포는 재정 규모 노출을 답합니다. 어느 하나로 다른 하나를 대체하지 않습니다.

### 편향 배수 2배와 0.5배는 정책 기준입니까?

아닙니다. 특정 집단의 사업구성·회계특성·품질문제를 확인하는 진단 표시입니다.

### 연말집중은 낭비입니까?

아닙니다. 계약·보조금 지급 일정 등 정상 사유가 있을 수 있어 원문 설명이 필요한 집행 패턴으로만 표시합니다.

### 최종 순위를 왜 만들지 않았습니까?

성과자료가 아직 연결되지 않았고 기준별 표본·편향·신뢰도 검증이 우선이기 때문입니다.

## 10. 한계와 강건성

- 2022~2025년 관측창 때문에 반복 신호의 유효연도가 최대 4년입니다.
- 예산가중 ECDF는 예산현액이 양수로 확인된 행만 사용합니다.
- 집행률 100% 초과 행은 주 ECDF에서 제외하고 별도 품질 검토 대상으로 유지합니다.
- 부처·회계별 분포 차이는 정책성과가 아니라 사업구성과 회계적 분모 차이일 수 있습니다.
- 상대 신뢰도 구간은 잠정 후보이며 팀 결정 전 최종 설정이 아닙니다.
- 이 분석은 기술통계와 운영 기준 검토이며 인과효과를 추정하지 않습니다.

## 11. 실험 진행 기록

- **입력·분석 단위 확인** — 완료: M3 6,118행 보존, 주 ECDF 6,102행
- **집행률 분포·민감도** — 완료: ECDF 29,154행, 70~95% 민감도 468행
- **집단 편향·상대 안정성** — 완료: 편향 858행, 상대 진단 256행
- **연말집중·반복 신호** — 완료: 월별 점 3,242행, 사업-신호 반복 4,080행
- **정책 후보 비교·시각화** — 완료: 후보 9개, PNG 12개

## 12. 권장 다음 단계

1. 이 문서의 잠정 권장안을 발표용 기준으로 검토합니다.
2. UNKNOWN 본예산 80% 커버리지 검토집합을 실제 근거로 수기 분류합니다.
3. 분류 결과를 반영해 비교집단 크기와 상대 신호만 최소 재실행합니다.
4. 실제 공유·피드백 후 확정된 기준만 설정파일과 의사결정 기록에 저장합니다.

## 13. 추가 확인 질문

- 80~90%를 대시보드에서 별도 색상으로 표시할지, 필터로만 제공할지?
- 상대 신호 LOW 등급을 화면에 표시할지, 상세표에만 남길지?
- 정상 연말 지급이 예상되는 사업유형을 별도 설명 태그로 관리할지?
- UNKNOWN 80% 커버리지 검수 후 추가 검수 범위를 어디까지 둘지?

## 부록. 차트 원자료 연결

| 그림 | 분석 질문 | 원자료 | 읽는 법 |
|---|---|---|---|
| execution_ecdf_overall.png | OVERALL에서 사업 수와 예산가중 분포가 다른가 | `execution_ecdf_summary.csv` | 같은 x에서 주황선이 파란선보다 높으면 저집행 구간의 예산 비중이 사업 수 비중보다 큼 |
| execution_ecdf_by_account_type.png | ACCOUNT_TYPE에서 사업 수와 예산가중 분포가 다른가 | `execution_ecdf_summary.csv` | 같은 x에서 주황선이 파란선보다 높으면 저집행 구간의 예산 비중이 사업 수 비중보다 큼 |
| execution_ecdf_by_ministry.png | MINISTRY에서 사업 수와 예산가중 분포가 다른가 | `execution_ecdf_summary.csv` | 같은 x에서 주황선이 파란선보다 높으면 저집행 구간의 예산 비중이 사업 수 비중보다 큼 |
| execution_ecdf_by_year.png | FISCAL_YEAR에서 사업 수와 예산가중 분포가 다른가 | `execution_ecdf_summary.csv` | 같은 x에서 주황선이 파란선보다 높으면 저집행 구간의 예산 비중이 사업 수 비중보다 큼 |
| execution_ecdf_by_project_size.png | PROJECT_SIZE에서 사업 수와 예산가중 분포가 다른가 | `execution_ecdf_summary.csv` | 같은 x에서 주황선이 파란선보다 높으면 저집행 구간의 예산 비중이 사업 수 비중보다 큼 |
| execution_threshold_sensitivity.png | 70~95%에서 탐지 행·사업·금액이 얼마나 달라지는가 | `execution_threshold_sensitivity.csv` | 기울기가 큰 구간은 1%p 변경에 민감한 구간이며 자동 절단점이 아님 |
| threshold_group_bias_heatmap.png | 80%·90% 기준이 특정 집단을 과대표집하는가 | `threshold_group_bias.csv` | 2배 이상 또는 0.5배 이하는 원인 확인 대상이며 정책상 제외 기준이 아님 |
| peer_distribution_diagnostics.png | 비교집단 표본과 동률이 상대 신호를 지지하는가 | `peer_distribution_diagnostics.csv` | 동률 블록이 크거나 기대 꼬리 관측이 2개 미만이면 상대 신호를 사용하지 않음 |
| year_end_pattern_scatter.png | 4분기형과 12월형 집중은 분리되는가 | `year_end_pattern_points.csv` | 세로선 오른쪽은 4분기형, 가로선 위는 12월형, 우상단은 두 기준 동시 충족 |
| year_end_pattern_by_ministry.png | 부처별 지급 구조 차이가 고정 기준에 영향을 주는가 | `year_end_pattern_points.csv` | 부처별 점 구름의 위치와 기준선 주변 밀도를 비교 |
| repeated_signal_distribution.png | 같은 반복 횟수가 유효 관측연도 수에 따라 어떻게 다른가 | `repeated_signal_distribution.csv` | 50%선 위이면서 2회 이상인 사업이 주 반복 후보, 연속 여부는 색으로 구분 |
| analysis_policy_options.png | 후보 기준별 탐지 범위와 권장 역할은 무엇인가 | `analysis_policy_options.csv` | 반복 기준은 project grain이라 행 기준 옵션과 직접 순위 비교하지 않음 |
