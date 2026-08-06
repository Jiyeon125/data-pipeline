# 외부검증 기준본

## 기준본 메타데이터

| 항목 | 값 |
|---|---|
| 입력 CSV | `data/analytics/multi_ministry_priority_scenarios/program_year_review_queue.csv` |
| 스키마 버전 | `priority_review_outputs_v5_identity_context_resolution` |
| 분석 버전 | `review_workbench_v5_identity_context_resolution` |
| 분석 단위 | 부처 × 프로그램 × 회계연도 |
| 행 수 | 236 |
| 컬럼 수 | 91 |
| SHA-256 | `d7c59cc14da21f0e669f2e09867766100957ddad68f8600b43d64392c6236a96` |
| Git commit SHA | `9295b276a1110482a026830b5ae8b56d520e9875` |
| Git dirty 상태 | `CLEAN` (기준본 메타데이터 수집 시점) |
| 산출물 생성시각 | `2026-08-06T00:03:18.241365+00:00` |
| 기준본 기록시각 | `2026-08-06T09:42:00.6739207+09:00` |

이 문서는 위 SHA-256의 CSV를 외부검증 입력 기준본으로 고정합니다. 이후 생성된 검토 시트는 등급을 재계산하지 않고 이 파일의 행을 선택해 전사한 것입니다.

## 등급 분포

| 회계연도 | A | B | C | D | H | 합계 |
|---:|---:|---:|---:|---:|---:|---:|
| 전체 | 16 | 14 | 90 | 89 | 27 | 236 |
| 2022 | 0 | 4 | 29 | 36 | 10 | 79 |
| 2023 | 12 | 8 | 26 | 25 | 9 | 80 |
| 2024 | 4 | 2 | 35 | 28 | 8 | 77 |

## `grade_reason_codes` 분포

현재 고정 산출물에서는 프로그램-연도당 `grade_reason_codes`가 하나씩 기록되어 있어 아래 건수는 상호 배타적입니다.

| grade_reason_codes | 프로그램-연도 수 |
|---|---:|
| `NO_STRUCTURED_SIGNAL_DETECTED` | 89 |
| `SINGLE_SIGNAL_REVIEW` | 76 |
| `DATA_OR_COMPARABILITY_HOLD` | 27 |
| `STRONG_OR_REPEATED_SINGLE_SIGNAL` | 14 |
| `LOW_EXECUTION_TARGET_MET` | 14 |
| `REPEATED_REPORTED_TARGET_MISS_WITH_BUDGET_INCREASE` | 12 |
| `REPEATED_LOW_EXECUTION_WITH_REPORTED_TARGET_MISS` | 4 |

## `hold_reasons` 분포

입력 CSV에는 별도 `hold_reasons` 컬럼이 없으므로, H 27행의 기존 `identity_resolution_reason`, `data_validation_signal`, `reported_target_status`, `program_performance_status_conflict`를 그대로 분류해 검증 시트에 기록했습니다. 사유 토큰은 중복될 수 있으며, 실제 중복은 `MISSING_PROGRAM_CODE_UNKNOWN_CONTINUITY`와 `PERFORMANCE_NOT_COMPARABLE`이 함께 나타난 1행입니다.

| hold_reasons 토큰 | 전체 | 2022 | 2023 | 2024 |
|---|---:|---:|---:|---:|
| `UNRESOLVED_EXTENDED_KEY_COLLISION` | 12 | 4 | 4 | 4 |
| `UPSTREAM_DATA_QUALITY` | 11 | 5 | 3 | 3 |
| `MISSING_PROGRAM_CODE_UNKNOWN_CONTINUITY` | 4 | 1 | 2 | 1 |
| `PERFORMANCE_NOT_COMPARABLE` | 1 | 0 | 1 | 0 |
| `PERFORMANCE_INCONSISTENCY` | 0 | 0 | 0 | 0 |

H 프로그램-연도 수는 27행이며, 토큰 합계는 중복 1건 때문에 28입니다.

## 2024년 외부검증 12건 선정 기록

| 층 | 선정 | 선정 기준 |
|---|---:|---|
| A | 4 | 2024년 A 전수 |
| B | 2 | 2024년 B 전수 |
| C | 2 | `LOW_EXECUTION_TARGET_MET` 1건과 `SINGLE_SIGNAL_REVIEW` 1건 |
| D | 2 | 예산 규모가 크고 과거 H 또는 A 이력이 있는 사례를 우선하여 거짓 음성 가능성 확인 |
| H | 2 | upstream 데이터 품질 1건과 프로그램코드 결측 1건; 해결된 base-key reuse 제외 |

12건의 `program_identity_id`는 모두 달라 동일 프로그램 중복은 없습니다. C 층에서는 각 지정 유형을 만족하는 후보 중 예산 규모가 큰 사례를 선택했습니다. D 층에서는 2024년 대규모 프로그램 가운데 과거 연도 등급 이력이 현재 D와 달라 외부자료로 누락 가능성을 확인할 가치가 있는 사례를 선택했습니다. H 층에서는 `RESOLVED_BY_FIELD_SECTOR`를 제외하고 서로 다른 보류 원인을 하나씩 선택했습니다.

제외 사유는 다음과 같습니다.

- A와 B는 전수이므로 제외가 없습니다.
- C의 나머지 후보는 지정한 두 진단 층의 중복 표본이므로 제외했습니다.
- D의 나머지 후보는 예산 규모 또는 과거 신호 이력 우선순위에서 선정 사례보다 뒤에 있어 제외했습니다.
- H의 해결된 base-key reuse 및 확장키 충돌 사례는 요청된 H 표본 조건과 달라 제외했습니다.

`external_validation_result`는 외부자료 검색을 수행하지 않은 현재 상태를 나타내도록 12건 모두 `INSUFFICIENT_EXTERNAL_EVIDENCE`로 초기화했습니다. 허용값은 `SUPPORTED`, `CONTRADICTED`, `INSUFFICIENT_EXTERNAL_EVIDENCE`뿐입니다.

## 블라인드 8쌍 선정 기록

블라인드 시트는 총 8쌍, 16개 서로 다른 `program_identity_id`로 구성했습니다. 검토자용 시트에는 등급, 진단유형, 등급 사유, 기존 정렬 순서를 포함하지 않았습니다. 중립적인 원시 금액·집행률·보고목표 상태·반복 관측·예산변화·데이터 품질 상태와 모델 확인질문만 제공합니다.

| 쌍 | 내부 선정 층 | 선정 방식 |
|---|---|---|
| BP01-BP02 | A 대 C | 서로 다른 프로그램의 A와 C를 짝지음 |
| BP03-BP04 | B 대 D | 서로 다른 프로그램의 B와 D를 짝지음 |
| BP05-BP06 | `LOW_EXECUTION_TARGET_MET` C 대 A/B | 저집행·목표달성 C와 A 또는 B를 짝지음 |
| BP07 | H 대 판단 가능한 등급 | 프로그램코드 결측·성과 비교불가 H와 D를 짝지음 |
| BP08 | 민감도·등급 경계 | 단일 예산-성과 불일치 C와 구조화 신호 미검출 D를 짝지음 |

쌍 선정은 등급 검증용 층화표본이며 모집단 성능 추정치가 아닙니다. 외부검증 12건과 블라인드 16건은 서로 독립된 산출 목적이며 일부 연도·부처 분포를 대표하도록 설계된 확률표본이 아닙니다.
