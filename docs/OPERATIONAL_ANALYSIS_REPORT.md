# 프로그램-연도 운영 분석 보고서

## 기술 요약

2024년 77개 중 생산 A+B는 6개(7.79%)이며, 5개가 모든 OAT 변형에서 A+B를 유지했습니다. 정확 등급까지 유지한 사례는 2개이고 업무그룹 경계 사례는 `소록도병원` 1개입니다. 생산 등급은 변경하지 않았습니다.

reported performance 의존성은 `RULE_STRUCTURAL_DEPENDENCY`입니다. A의 두 경로는 현재 또는 연속 성과미달을 직접 요구합니다. B에는 집행 단독 조건식이 존재하지만 생산 입력의 성과 상태 완전분할과 특례 C precedence 때문에 일관된 입력에서는 성과 앵커 없는 B가 성립하지 않습니다.

## 임계값 안정성과 신호 의존성은 서로 다른 질문이다

- A~D 정확 등급 유지율: 93.78%~100.00%
- A+B Jaccard: 0.8824~1.0000
- A↔D: 0건
- 2024 A+B: 업무그룹 유지 5/6, 정확 등급 유지 2/6, 경계 1/6

| 제거 신호 | 등급 변경 | A/B 이탈 | C↔D |
|---|---:|---:|---:|
| execution | 20 | 9 | 10 |
| reported_performance | 56 | 30 | 26 |
| budget_performance_mismatch | 50 | 0 | 41 |
| repetition | 24 | 15 | 0 |

ablation은 신호 제거 시 규칙이 얼마나 반응하는지 보여주며 독립 기여율이나 feature importance가 아닙니다. 설명 precedence 결함 3행은 원시 `repeated_low_execution_signal`, `performance_signal`, `reported_target_miss_consecutive`, `budget_increase_context_signal`과 `grade_trigger_signal_families`로 판독했습니다.

## 범위와 정의

- 단위: 프로그램×연도 236행, 압축 분석은 2024년 77행
- `threshold_stable_ab`: 6개 OAT 변형 모두 A 또는 B
- `threshold_boundary`: 하나 이상의 OAT 변형에서 기준 업무그룹 이탈
- `signal_dependency_signature`: 등급을 바꾼 제거 신호 계열 목록
- 원문 검토단위: `raw_candidate_ids → candidate_id → project_id`의 명시적 연결

## 한계와 다음 단계

등급은 성과판정이나 위험확률이 아니라 원문 검토 순서입니다. 안정 핵심군은 보조 설명일 뿐 새 생산등급이 아닙니다. 대시보드·발표에는 생산 A+B와 안정/경계를 나란히 표시하되 정렬은 바꾸지 않는 것이 적절합니다.
