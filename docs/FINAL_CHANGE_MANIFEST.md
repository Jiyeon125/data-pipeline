# 최종 변경 매니페스트

감사 기준 HEAD: `586a8444dea033e71a9a19f60b3ce075b717c7a6`

시작 작업트리는 clean이었습니다. 아래 표는 이번 release gate로 생긴 현재 dirty 파일 전부를 직접 diff·내용으로 검토한 결과입니다.

| 파일 | 분류 | 변경 목적 | 제출 포함 | 위험도 | 검토 결과 |
|---|---|---|---|---|---|
| `docs/CURRENT_PROJECT_CONTEXT.md` | SUBMISSION_REQUIRED | 2022~2024 생산 분석과 2025 계획자료 범위 고정 | 예 | 낮음 | 2025 등급·성과·환류 계산 없음 |
| `docs/FINAL_PRESENTATION_OUTLINE.md` | SUBMISSION_REQUIRED | 정본 범위 링크 추가 | 예 | 낮음 | 13장 구조·기존 수치 불변 |
| `docs/FINAL_QA_CHECKLIST.md` | SUBMISSION_REQUIRED | release gate 실행 결과 고정 | 예 | 낮음 | 실제 테스트 결과 반영 |
| `docs/SUBMISSION_BASELINE.md` | SUBMISSION_REQUIRED | HEAD·dirty 상태·기준 수치·제출 판정 고정 | 예 | 낮음 | 생산 기준과 일치 |
| `docs/work_in_progress/OPERATIONAL_ANALYSIS_CHECKPOINT.md` | TEMPORARY_REMOVE | 완료 전 진행 체크포인트 제거 | 아니요 | 낮음 | 최종 보고서와 중복되어 삭제 |
| `notebooks/mss_priority_scenario_stability.ipynb` | SUBMISSION_REQUIRED | Ruff import 정리 | 예 | 낮음 | 미사용 import 삭제·정렬만 수행 |
| `src/analytics/cli.py` | SUBMISSION_REQUIRED | Ruff import 정렬 | 예 | 낮음 | 명령·API 변경 없음 |
| `src/analytics/explanation_need_score.py` | SUBMISSION_REQUIRED | Ruff 미사용 코드·중복 형변환 정리 | 예 | 낮음 | 산식·반환·출력 동일 |
| `tests/test_fiscal_dashboard.py` | SUBMISSION_REQUIRED | 대표 A/B/C/D/H UI 계약 검증 | 예 | 낮음 | key·조건·`program_year_id` 기반, 행 순번 비의존 |
| `docs/FINAL_CHANGE_MANIFEST.md` | SUBMISSION_REQUIRED | dirty 제출 범위와 위험 분류 | 예 | 낮음 | 현재 status 전체 반영 |
| `docs/FINAL_DASHBOARD_SMOKE_TEST.md` | SUPPORTING_EVIDENCE | 대표사례 release 증거 | 예 | 낮음 | 대표 5건·기존 AppTest 결과 기록 |

## 별도 확인한 직전 통합 커밋

- `README.md`와 정본 문서의 수치는 기준 산출물과 일치합니다.
- `docs/FINAL_REPORT.md`는 본문 변경 없이 LEGACY 경고와 정본 링크만 추가됐습니다.
- `src/fiscal_dashboard/app.py`는 UI 표현·검증 탭 범위이며 생산 판정 함수가 없습니다.
- `validation/analyze_operational_analysis.py`는 기준 CSV 해시를 검사해 읽고 validation·docs 산출물만 기록합니다.
- 최신 그림 4개는 해당 validation 수치와 시각적으로 일치합니다.

## 분류 요약

- `SUBMISSION_REQUIRED`: 9개
- `SUPPORTING_EVIDENCE`: 1개
- `LEGACY_WARNING_UPDATE`: 현재 dirty 0개
- `TEMPORARY_REMOVE`: 1개
- `UNINTENDED_CHANGE`: 0개

자동 stage·commit·push·tag는 수행하지 않았습니다.
