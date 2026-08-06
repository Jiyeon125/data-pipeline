# 점검등급 강건성 분석 체크포인트

## 시작 상태

- 시작일: 2026-08-07
- HEAD: `6dc0bd96e1beac66b6cdbd4900286b671f54e1ec`
- 기준 CSV: `data/analytics/multi_ministry_priority_scenarios/program_year_review_queue.csv`
- 기준 CSV SHA-256: `d7c59cc14da21f0e669f2e09867766100957ddad68f8600b43d64392c6236a96`
- 기준 크기: 236행 × 91열
- 시작 `git status --short`:
  - `?? docs/REVIEW_GRADE_RULEBOOK.md`
  - `?? tests/validation/test_review_grade_rule_contract.py`
  - `?? validation/audit_review_grade_rules.py`
  - `?? validation/figures/`

## 작업 범위

- H 27행과 identity·comparability·결측·data-validation 상태를 고정합니다.
- A~D의 생산 기준 shadow 재현 후 안전하게 재계산 가능한 기존 수치 임계값만 OAT 분석합니다.
- execution, reported_performance, budget_performance_mismatch, repetition을 한 계열씩 제거합니다.
- 설명 precedence 결함은 문서화하되 생산 코드·생산 CSV·생산 등급은 수정하지 않습니다.

## 읽은 파일

- `data/analytics/multi_ministry_priority_scenarios/program_year_review_queue.csv`
- `data/analytics/multi_ministry_priority_scenarios/analysis_summary.json`
- `src/analytics/mss_priority_scenario_analysis.py`
- `src/analytics/mss_same_year_budget_check.py`
- `src/analytics/m3_financial_signals.py`
- `src/analytics/m3_methodology_audit.py`
- `configs/mss_priority_scenarios.yaml`
- `configs/priority_scenarios.yaml`
- `tests/analytics/test_mss_priority_scenario_analysis.py`
- `docs/PROJECT_PLAN.md`
- `docs/MENTORING_GUIDE.md`
- `docs/M2_DATA_REVIEW.md`
- `docs/architecture.md`
- `docs/WORK_LOG.md`
- `docs/WORK_TRACKER.md`
- `docs/REVIEW_GRADE_RULEBOOK.md`
- `C:/Users/0215w/.codex/plugins/cache/openai-curated-remote/data-analytics/0.2.8-13ceeea1f599/skills/validate-data/SKILL.md`
- `C:/Users/0215w/.codex/memories/MEMORY.md` 관련 키워드 검색 결과 없음

## 완료된 하위 작업

- [x] 저장소 루트 확인
- [x] 기준 HEAD 확인
- [x] 시작 dirty 상태 기록
- [x] 기준 CSV SHA·236행·기본키 중복 0 확인
- [x] shadow 기준 재현: 236행 불일치 0
- [x] 임계값 목록 조사: 분석 4개, 제외 7개
- [x] OAT 임계값 민감도 분석: 6개 변형
- [x] 신호 제거 분석: 4개 계열
- [x] 보고서·설명 결함 문서화
- [x] 관련 테스트 `32 passed, 3 xfailed`; Ruff·`git diff --check` 통과
- [x] 생산 CSV SHA·236행·생산 등급 불변 재확인

## 생성된 산출물

- `docs/work_in_progress/GRADE_ROBUSTNESS_CHECKPOINT.md`
- `validation/analyze_grade_robustness.py`
- `tests/validation/test_grade_robustness.py`
- `validation/shadow_baseline_reproduction.csv`
- `validation/grade_threshold_inventory.csv`
- `validation/grade_sensitivity_scenarios.csv`
- `validation/program_grade_stability.csv`
- `validation/grade_transition_matrices.csv`
- `validation/grade_boundary_cases.csv`
- `validation/signal_ablation_summary.csv`
- `validation/signal_ablation_cases.csv`
- `docs/GRADE_ROBUSTNESS_REPORT.md`
- `docs/DATA_ANALYSIS_UPGRADE_SUMMARY.md`
- `docs/EXPLANATION_PRECEDENCE_ISSUE.md`

## 중단 시 재개 위치

작업 완료. 재검토가 필요하면 `validation/grade_sensitivity_scenarios.csv`와
`validation/signal_ablation_summary.csv`의 요약에서 사례 CSV로 추적합니다.

## 최종 검증

- shadow 기준 재현: 236/236 일치
- A~D 유지율: 0.9378~1.0000
- A+B Jaccard: 0.8824~1.0000
- A↔D 이동: 0
- 신호 제거 등급 변경: execution 20, reported performance 56, budget mismatch 50, repetition 24
- 생산 경로 diff: 없음
- 기준 CSV SHA-256: 시작·종료 동일
