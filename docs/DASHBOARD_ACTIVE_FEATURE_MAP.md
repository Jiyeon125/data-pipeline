# 대시보드 활성 기능 지도

## 시작 필수입력

| 입력 | 분류 | 현재 역할 | 시작 필수 |
|---|---|---|---|
| `program_year_review_queue.csv` | ACTIVE_UI | 기본 대기열·프로그램 상세·연도 타임라인 | 예 |
| `full_population_review_work_queue.csv` | ACTIVE_UI | candidate별 회계 감사행·회계유형 대조 | 예 |
| `full_population_project_review_queue.csv` | ACTIVE_UI | 전체 프로그램 세부사업 재정 드릴다운 | 예 |
| `analysis_summary.json` | ACTIVE_UI | 기준연도·방법론 요약 | 예 |
| `validation` 강건성·압축·시간외·외부검증 파일 | ACTIVE_UI | 내부 분석·검증 화면 | 예 |
| PDF reconciliation Parquet·수기 확인 CSV | ACTIVE_UI | PDF 원문 검수 화면에서 지연 로드 | 앱 시작에는 아니오 |

## 시작 필수에서 제외한 산출물

| 입력·데이터 | 분류 | 판단 | 시작 필수 |
|---|---|---|---|
| `stable_top5_project_drilldown.csv` (`drilldown`) | LEGACY_UNUSED | 74행 안정 후보용 부분집합; 전체 상세 원천으로 사용하지 않음 | 아니오 |
| `review_workbench_queue.csv` (`review_queue`) | LEGACY_UNUSED | 과거 통합 작업대용; 현재 프로그램-연도 화면에서 미사용 | 아니오 |
| `scenario_scores.csv` (`scores`) | VALIDATION_ONLY | 오프라인 시나리오 검증 산출물 | 아니오 |
| `rank_stability.csv` (`stability`) | VALIDATION_ONLY | 오프라인 순위 안정성 산출물 | 아니오 |
| `scenario_spearman.csv` (`spearman`) | VALIDATION_ONLY | 오프라인 시나리오 상관 검증 | 아니오 |
| `top_k_overlap.csv` (`overlap`) | VALIDATION_ONLY | 오프라인 시나리오 중첩 검증 | 아니오 |
| 대표사례 `case_review`, `case_indicators`, `case_projects`, `case_t1_direction` | VALIDATION_ONLY | 대표사례 보고·검증용; 일반 상세 데이터 원천이 아님 | 아니오 |
| `candidate_population.csv` | REMOVE_FROM_REQUIRED_INPUT | 현재 `work_queue`와 중복된 시작 계약 | 아니오 |

## 함수 상태

| 함수 | 분류 | 현재 판단 |
|---|---|---|
| `_program_year_project_rows()` | ACTIVE_UI | `raw_candidate_ids` 전체 연결·회계유형·비귀속 검증 |
| `_project_focus_rows()` | ACTIVE_UI | 재정·데이터 확인 및 금액 기여 상위 최대 8개 선택 |
| `_project_table_view()` | ACTIVE_UI | 세부사업 재정표 한글 표시 |
| `_render_program_year_detail()` | ACTIVE_UI | 프로그램-연도 상세과 세부사업·원문 경로 통합 |
| `_render_candidate_detail()` | LEGACY_UNUSED | 회계후보 단위 과거 화면; 호출되지 않으며 docstring으로 표시 |
| `_project_budget_figure()` | LEGACY_UNUSED | 과거 Matplotlib 세부사업 차트; 현재 표가 같은 정보를 제공 |
| `_rank_range_figure()` | LEGACY_UNUSED | 과거 시나리오 UI 차트 |
| `_spearman_figure()` | LEGACY_UNUSED | 과거 시나리오 UI 차트 |
| `_scenario_top_figure()` | LEGACY_UNUSED | 과거 시나리오 UI 차트 |
| `_workbench_table()` | LEGACY_UNUSED | 과거 통합 작업대 표 |
| `_data_review_table()` | LEGACY_UNUSED | 과거 데이터 검증 표 helper |
| `_review_worklist()` | LEGACY_UNUSED | 과거 데이터 검증 작업표 helper |
| `stable_program_summary()` | LEGACY_UNUSED | 과거 안정 후보 요약 helper |

현재 작업에서는 생산 분석 산출물과 판정 로직을 변경하지 않았습니다. 레거시 helper의 일괄 삭제는 활성 기능 복구와 무관하므로 수행하지 않았고, 앱 시작 필수입력에서만 분리했습니다.
