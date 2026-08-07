# 최종 대시보드 대표사례 스모크 테스트

검증일: 2026-08-07

## 이전 실패 원인

분류: `TEST_HARNESS_LIMITATION`

이전 1회성 `python -` 하네스는 초기 AppTest 렌더 성공을 확인하지 않은 채 label 기반 위젯 탐색부터 수행해 `StopIteration`으로 종료됐습니다. 저장소의 기존 AppTest는 같은 UI 위젯을 정상 탐색했고 실제 필터·화면 이동 결함은 재현되지 않았습니다. UI는 수정하지 않았습니다.

복구 테스트는 위젯 순번이나 특정 데이터 행 순번 대신 다음 안정 식별자를 사용합니다.

- 위젯 `key`: `queue_filter`, `main_tab`, `selected_program_year`
- 사례 선택: `fiscal_year=2024`, 생산등급, C의 `LOW_EXECUTION_TARGET_MET`
- 선택값: 실제 `program_year_id`

## 대표 사례

| 등급 | program_year_id | 프로그램 | 사례 조건 | 결과 |
|---|---|---|---|---|
| A | `075:3300:2024` | 국민건강생활실천 | 2024년 A | PASS |
| B | `019:1100:2024` | 직업능력개발 | 2024년 B | PASS |
| C | `019:1000:2024` | 고용창출 | `LOW_EXECUTION_TARGET_MET` | PASS |
| D | `019:1200:2024` | 고용안전망확충 | 2024년 D | PASS |
| H | `075:1300:2024` | 아동보호 및 복지 강화 | 2024년 H | PASS |

각 사례에서 대기열 선택 가능, 한글 점검등급, 한 문장 진단, 다음 확인질문, 연도 타임라인, 회계유형 감사정보를 확인했습니다. H는 데이터 보완 업무그룹으로 분리됐고 원시 진단·context 영문 코드는 기본 화면에 노출되지 않았습니다. 회계유형 감사행은 상세 요약 아래의 expander에 위치합니다.

## 실행 결과

- 대표사례 AppTest: `5 passed`
- 기존 Streamlit AppTest: `6 passed, 5 deselected`
- UI 변경: 없음
