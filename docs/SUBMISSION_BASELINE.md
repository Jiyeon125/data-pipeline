# 제출 기준본

기준 고정일: 2026-08-07

## 저장소 기준

- repository: `Jiyeon125/data-pipeline`
- branch: `main`
- full commit SHA: `609b9db848d7e476e3fcb7d62050fd21c2672bf4`
- 작업트리: dirty. 자동 commit·push·tag는 수행하지 않았습니다.
- 분석 버전: `review_workbench_v5_identity_context_resolution`
- 스키마 버전: `priority_review_outputs_v5_identity_context_resolution`

## 생산 기준본

- 파일: `data/analytics/multi_ministry_priority_scenarios/program_year_review_queue.csv`
- SHA-256: `d7c59cc14da21f0e669f2e09867766100957ddad68f8600b43d64392c6236a96`
- 프로그램-연도 236행, `program_year_id` 중복 0
- 원시 감사행 412행
- 고유 프로그램 80개, UNKNOWN continuity 포함 identity 84개
- 2024년 프로그램 77개
- 전체 등급: A16 B14 C90 D89 H27
- 2024년 등급: A4 B2 C35 D28 H8

## 검증 기준

- 외부검증: SUPPORTED 8, CONTRADICTED 2, INSUFFICIENT 2
- 임계값 A~D 유지율: 93.78%~100.00%
- A+B Jaccard: 0.8824~1.0000
- 2024년 A+B 임계값 안정: 5/6
- 우선 확인 프로그램: 6/77
- 연결 원문 단위: 74/1,080
- 사람검증: 블라인드 쌍대비교 검토표와 연구자 1인의 예비 사용성 점검까지 수행했습니다. 독립 검토자를 확보하지 못해 검토자 간 일치도와 모델-사람 판단 부합도는 산출하지 않았습니다.

## 실행 QA 결과

- 전체 pytest: `309 passed, 3 xfailed`, 경고 2건
- 전체 Ruff: 실패, 기존 범위 9건
  - `notebooks/mss_priority_scenario_stability.ipynb`: 2건
  - `src/analytics/cli.py`: 1건
  - `src/analytics/explanation_need_score.py`: 6건
- 기존 대시보드 AppTest: 전체 pytest 안에서 6건 통과
- A/B/C/D/H 대표사례 별도 AppTest: 위젯 탐색 `StopIteration`으로 미완료, 1회 제한에 따라 재실행하지 않음
- Streamlit 서버 스모크: `/_stcore/health` HTTP 200, 응답 `ok`

## 알려진 한계

- 점검등급은 성과 앵커형 질문형 등급이며 사업 실패·위험·정책효과를 판정하지 않습니다.
- 법률·제도·재원구조 위험은 현재 구조화 신호에 포함되지 않습니다.
- 동료집단 백분위 적격은 10/472로 본편 기준에 사용하지 않습니다.
- 다음 연도 관측은 예측 성능이 아니라 방향적 연관성입니다.
- 독립 사람검증은 완료되지 않았습니다.
- 작업트리가 dirty이므로 현재 full commit SHA만으로 문서·대시보드 변경을 재현할 수 없습니다.

## 제출 판정

**조건부 가능**입니다. 생산 기준본과 전체 pytest·서버 스모크는 통과했으나, 전체 Ruff 9건과 대표사례 AppTest 미완료를 해소하고 제출 대상 dirty 파일을 검토·커밋한 뒤 제출 기준을 다시 고정해야 합니다.

## dirty 파일

기존 운영분석 산출물과 이번 문서·대시보드 변경을 자동 커밋하지 않았습니다.

```text
M README.md
M docs/FINAL_REPORT.md
M docs/FINAL_VALIDATION_REPORT.md
M docs/VALIDATION_PRESENTATION_SUMMARY.md
M src/fiscal_dashboard/app.py
M tests/test_fiscal_dashboard.py
?? docs/CURRENT_PROJECT_CONTEXT.md
?? docs/DATA_ANALYSIS_PRESENTATION_SUMMARY.md
?? docs/FINAL_PRESENTATION_OUTLINE.md
?? docs/FINAL_QA_CHECKLIST.md
?? docs/OPERATIONAL_ANALYSIS_REPORT.md
?? docs/PEER_REFERENCE_REPORT.md
?? docs/PRESENTATION_NUMBERS_SINGLE_SOURCE.md
?? docs/SUBMISSION_BASELINE.md
?? docs/TEMPORAL_FOLLOWUP_REPORT.md
?? docs/WORKLOAD_COMPRESSION_REPORT.md
?? docs/work_in_progress/OPERATIONAL_ANALYSIS_CHECKPOINT.md
?? tests/validation/test_operational_analysis.py
?? validation/analyze_operational_analysis.py
?? validation/figures/peer_reference_examples.png
?? validation/figures/priority_review_stability_2024.png
?? validation/figures/temporal_grade_transition.png
?? validation/figures/workload_compression.png
```
