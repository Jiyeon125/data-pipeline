# 설명 precedence 결함

## 결론

제출 전 수정 우선순위는 **권장**입니다. 생산 등급과 대기열 순서는 정확히 유지되지만,
복수 A 근거 중 하나가 설명 필드에서 소실되어 원문 검토자가 근거를 불완전하게 볼 수 있습니다.

## 영향 3행

| program_year_id | 등급 | 동시에 성립한 A 조건 1 | 동시에 성립한 A 조건 2 | 최종 표시 진단 |
|---|---|---|---|---|
| `075:3800:2023` | A | 반복 저집행+목표미달 | 연속 목표미달+예산 증가 | `REPEATED_REPORTED_TARGET_MISS_WITH_BUDGET_INCREASE` |
| `075:4100:2023` | A | 반복 저집행+목표미달 | 연속 목표미달+예산 증가 | `REPEATED_REPORTED_TARGET_MISS_WITH_BUDGET_INCREASE` |
| `075:4000:2023` | A | 반복 저집행+목표미달 | 연속 목표미달+예산 증가 | `REPEATED_REPORTED_TARGET_MISS_WITH_BUDGET_INCREASE` |

세 행 모두 `REPEATED_LOW_EXECUTION_WITH_REPORTED_TARGET_MISS`와
`REPEATED_REPORTED_TARGET_MISS_WITH_BUDGET_INCREASE`가 동시에 성립합니다. 코드의 후행
할당 때문에 최종 `diagnostic_type`과 이를 복사한 `grade_reason_codes`에는 두 번째 사유만
남습니다.

## 영향 범위

- `review_grade`: 영향 없음
- 등급 precedence: 영향 없음
- 대기열 순서: 영향 없음
- `diagnostic_type`: 앞선 사유 소실
- `grade_reason_codes`: `diagnostic_type` 복사값이므로 앞선 사유 소실
- `next_review_question`: 현재 세 행은 A 공통 질문을 사용하므로 영향 없음
- 특례 C: 복수 조건이 겹치면 후행 다년도 진단이 질문까지 덮어쓸 잠재 가능성이 있으나 현재 생산 236행 중복 사례는 0건

## 생산 CSV를 바꾸지 않는 보존안

현재 제출 기준 CSV는 유지합니다. 후속 UI에서는 원시 신호 필드로 두 A 조건을 각각 표시하고
기존 `diagnostic_type`을 primary 진단으로 유지할 수 있습니다. 다음 출력 스키마에서는
`grade_reason_codes_all`을 순서가 있는 배열로 추가하거나, `program_year_id × reason_code`
하위 테이블에 `is_primary`와 `precedence_order`를 두는 방식이 더 안전합니다. UI에서 문자열만
재추론하는 방식은 코드와 표시 로직이 다시 어긋날 수 있으므로 임시 방편으로만 사용합니다.
