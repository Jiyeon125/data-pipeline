# 발표 수치 단일 출처

발표·대시보드·GitHub 문서는 아래 값만 사용합니다. 값은 기존 검증 CSV에서 확인했으며 새 분석이나 생산등급 재계산을 하지 않았습니다.

| 영역 | 발표 수치 | 출처 |
|---|---:|---|
| 생산 기준 | 236행 × 91열, A16 B14 C90 D89 H27 | `program_year_review_queue.csv` |
| 2024년 | 77개, A4 B2 C35 D28 H8 | `program_year_review_queue.csv` |
| 우선 확인군 | 6/77, 7.79% | `workload_compression_summary.csv` |
| A+B 본예산 | 3.91% | `workload_compression_summary.csv` |
| D 본예산 | 81.84% | `workload_by_grade_and_budget.csv` |
| 원문 단위 | 74/1,080, 6.85% | `workload_compression_summary.csv` |
| 안정 핵심군 | 5개·70 원문 단위 | `priority_review_2024_stability.csv` |
| 경계군 | 소록도병원 1개·4 원문 단위 | `priority_review_2024_stability.csv` |
| A~D 유지율 | 93.78%~100.00% | `grade_sensitivity_scenarios.csv` |
| A+B Jaccard | 0.8824~1.0000 | `grade_sensitivity_scenarios.csv` |
| 정확 등급 유지 | 2024년 A+B 중 2/6 | `priority_review_2024_stability.csv` |
| 극단 이동 | A↔D 0건 | `grade_sensitivity_scenarios.csv` |
| 신호 제거 | 집행 20·9, 성과 56·30, 예산괴리 50·0, 반복 24·15 | `signal_ablation_summary.csv` |
| A+B 다음 연도 | 연결 24/24, 동일 신호 14/24(58.33%), A+B 유지 8/24(33.33%) | `temporal_followup_summary.csv` |
| 등급 이동 | C→A/B 15/53(28.30%), D→A/B 2/59(3.39%) | `temporal_followup_summary.csv` |
| 외부검증 | SUPPORTED 8, CONTRADICTED 2, INSUFFICIENT 2 | `external_validation_cases.csv` |
| peer | 적격 10/472, 본편 기준 미채택 | `peer_group_eligibility_audit.csv` |

## 고정 문구

“점검등급은 구조화 신호의 확인 우선도이며, 재정규모는 별도 영향 참고값입니다.”

“이는 예측 성능이 아니라 다음 연도 관측과의 방향적 연관성입니다.”

신호 제거는 독립 변수 중요도가 아니라 등급규칙의 신호 의존성입니다.

## 금지 해석

A+B를 재정위험·문제사업·포착 결과로 부르지 않습니다. D를 정상·안전으로 부르지 않습니다. 세 신호를 단순 합산하거나 동등 가중했다고 설명하지 않습니다. peer 결과를 전 모집단에 일반화하지 않습니다.
