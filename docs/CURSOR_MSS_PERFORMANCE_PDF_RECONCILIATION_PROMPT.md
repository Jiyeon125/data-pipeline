# Cursor AI 작업지시서: 중기부 성과 PDF 별첨과 수기 63행 대조

아래의 `복사해서 사용할 프롬프트` 전체를 Cursor AI에 그대로 전달합니다.
이 문서는 구현 범위와 출력 계약을 고정하기 위한 작업지시서입니다.

## 복사해서 사용할 프롬프트

```text
이 저장소에서 중소벤처기업부의 2022~2024년 성과계획서·성과보고서 PDF
별첨과 기존 수기 구조화 성과지표 63행을 대조해 주세요.

단순히 지표명이 검색되는지만 확인하지 말고, 프로그램, 성과지표명, 단위,
목표치, 실적치, 공식 달성률, 계획서-보고서 변경 여부와 원문 페이지를
행별로 검증해야 합니다.

외부 LLM API는 호출하지 마세요. 로컬 PDF 텍스트 추출과 필요한 페이지의
로컬 OCR은 허용합니다. 원본 PDF와 원본 수기 엑셀은 읽기 전용으로
취급하고 수정하거나 덮어쓰지 마세요.

작업을 시작하기 전에 다음 문서를 읽고 지침을 지켜 주세요.

- AGENTS.md
- docs/PROJECT_PLAN.md
- docs/MENTORING_GUIDE.md
- docs/M2_DATA_REVIEW.md
- docs/MENTORING_IMPLEMENTATION_AUDIT.md
- docs/architecture.md
- docs/WORK_LOG.md
- docs/WORK_TRACKER.md
- docs/work_tracker.json

대응 작업 ID는 다음입니다.

- quality.mss-performance-pdf-reconciliation

코드나 산출물이 존재한다는 이유만으로 이 작업을 완료 처리하지 마세요.
아래 검증 조건을 전부 통과한 뒤 작업 트래커를 완료 처리하고,
docs/WORK_LOG.md에 작업 목적, 입력, 규칙, 실행 결과, 결측·불일치,
테스트, 해석 범위와 남은 한계를 기록하세요.

## 1. 분석 목적

기존 수기 구조화 파일의 63개 성과지표가 PDF 원문과 일치하는지 확인하고,
다음 세 집단으로 분리하는 것이 목적입니다.

1. 원문으로 자동 확인 가능한 행
2. 계획서-보고서 사이에 지표명·목표치 등이 변경된 행
3. OCR 또는 사람 검토가 필요한 행

이 작업에서 성과가 좋다·나쁘다거나 사업이 우수·부실하다는 정책 판정을
하지 마세요. 성과지표를 세부사업 성과로 귀속하지 말고, 프로그램
성과지표 수준에서만 검증하세요.

## 2. 입력 파일

### 2.1 대조 기준 63행

- data/processed/performance/program_kpi_year.parquet
  - 기대 행 수: 63
  - 연도별 기대 행 수:
    - 2022년: 24행
    - 2023년: 26행
    - 2024년: 13행
  - 한 행의 기준:
    부처 × 프로그램 × 성과지표 × 회계연도

### 2.2 수기 원본

- data/manual/LLM_문서구조화_중기부_최종.xlsx
- data/processed/performance/manual_performance_rows.parquet
  - 현재 64행이며 예시 행 1개가 포함돼 있습니다.
  - `is_example=true`인 행은 대조 모집단에서 제외합니다.
  - 예시 행을 삭제하거나 원본 파일에서 제거하지 마세요.

### 2.3 PDF 별첨

- data/raw/performance_docs/appendix/year=2022/ministry_code=102/
  - 2022년도 성과계획서_중소벤처기업부-176-216.pdf
  - 2022년도 성과보고서_중소벤처기업부-170-212.pdf
- data/raw/performance_docs/appendix/year=2023/ministry_code=102/
  - 2023년도 성과계획서_중소벤처기업부-184-224.pdf
  - 2023년도 성과보고서_중소벤처기업부-179-226.pdf
- data/raw/performance_docs/appendix/year=2024/ministry_code=102/
  - 2024년도 성과계획서_중소벤처기업부-188-226.pdf
  - 2024년도 성과보고서_중소벤처기업부-159-208.pdf

2025년도 성과계획서는 파일 인벤토리에는 포함하되 이번 63행 대조
모집단에는 넣지 마세요. 2025년 성과보고서가 없다는 이유로 결측 행을
추가하지도 마세요.

### 2.4 관련 코드

- src/performance_pipeline/manual_performance.py
- src/performance_pipeline/cli.py
- tests/performance_pipeline/test_manual_performance.py

기존 정규화 함수와 파일 읽기 방식을 우선 재사용하세요. 같은 기능을
새로 중복 구현하지 마세요.

## 3. 이미 확인된 PDF 특성

- 별첨 7개 파일은 총 304페이지입니다.
- 각 파일의 페이지 수와 파일명 범위가 일치합니다.
- 모든 페이지가 원본 PDF의 해당 연속 구간과 일치합니다.
- 2022년도 성과계획서 41페이지 중 다음 12페이지는 추출 텍스트가
  100자 미만이지만 화면에는 표가 존재합니다.
  - 분리 PDF 페이지: 1, 2, 3, 4, 5, 6, 29, 30, 33, 38, 40, 41
- 성과보고서에는 문자 방향이 270도인 가로표가 있습니다.
  - 2022년: 30/43페이지
  - 2023년: 35/48페이지
  - 2024년: 39/50페이지

텍스트가 적다는 이유로 빈 페이지로 판정하지 마세요. 페이지를 렌더링해
표 존재 여부를 확인하고 `OCR_REQUIRED`를 사용하세요. 회전된 페이지는
방향을 정규화한 뒤 추출하세요.

## 4. 우선 검토할 별첨 구간

63행의 프로그램 성과지표와 직접 관련된 주 구간은 다음입니다.

- 2022년 성과계획서 분리 PDF 1~3페이지:
  프로그램 성과지표 현황
- 2023년 성과계획서 분리 PDF 1~3페이지:
  프로그램 성과지표 현황
- 2024년 성과계획서 분리 PDF 1~2페이지:
  프로그램 성과지표 현황
- 2022년 성과보고서 분리 PDF 4~9페이지:
  성과 달성도 현황 및 세부현황
- 2023년 성과보고서 분리 PDF 4~9페이지:
  성과 달성도 현황 및 세부현황
- 2024년 성과보고서 분리 PDF 4~7페이지:
  성과 달성도 현황 및 세부현황

위 구간에서 찾지 못한 지표는 즉시 `PDF_NOT_FOUND`로 확정하지 말고,
해당 연도 별첨 전체에서 한 번 더 검색하세요. 별첨 전체에서도 찾지
못했을 때만 미발견 후보로 남기세요.

## 5. 원문 페이지 표기

각 근거에는 다음 세 페이지 값을 분리해서 기록하세요.

- `split_pdf_page`: 분리된 별첨 PDF 안에서 1부터 시작하는 페이지
- `source_pdf_page`: 원본 PDF 파일에서 1부터 시작하는 페이지
- `printed_page`: 페이지 하단에 인쇄된 문서 페이지 번호

파일명의 시작 페이지가 원본 PDF 페이지입니다. 예를 들어
`2024년도 성과보고서_중소벤처기업부-159-208.pdf`의 분리 PDF 1페이지는
원본 PDF 159페이지입니다.

인쇄 페이지 번호는 화면에서 확인되지 않으면 추정하지 말고 null로
두세요.

## 6. 추출해야 할 필드

### 6.1 계획서

- 프로그램목표 번호
- 프로그램명 또는 프로그램목표명
- 성과지표명
- 지표 단위
- 지표 방향 또는 성격
- 해당 연도 목표치
- 계획서 원문 파일
- 계획서 분리 PDF 페이지
- 계획서 원본 PDF 페이지
- 계획서 인쇄 페이지
- 근거가 되는 짧은 원문 텍스트
- 추출 방식: `TEXT`, `OCR`, `MANUAL`

### 6.2 보고서

- 프로그램목표 번호
- 프로그램명 또는 프로그램목표명
- 성과지표명
- 지표 단위
- 보고 목표치
- 실적치
- 공식 달성률
- 달성 여부가 문서에 있으면 원문값
- 보고서 원문 파일
- 보고서 분리 PDF 페이지
- 보고서 원본 PDF 페이지
- 보고서 인쇄 페이지
- 근거가 되는 짧은 원문 텍스트
- 추출 방식: `TEXT`, `OCR`, `MANUAL`

문서에 없는 값은 null로 유지하세요. 다른 값으로부터 추정하거나
채워 넣지 마세요.

## 7. 매칭 규칙

### 7.1 기본 키

다음 정보를 함께 사용하세요.

- ministry_code: 문자열 `"102"`
- fiscal_year
- program_goal_number
- performance_program_name
- indicator_name

부처코드와 기타 코드는 숫자로 바꾸지 말고 문자열로 보존하세요.

### 7.2 지표명 매칭

1. 공백, 줄바꿈, 괄호와 일반적인 문장부호만 제거한 정규화명으로
   정확 일치를 먼저 확인합니다.
2. 계획서와 보고서의 명칭이 다르지만 변경사항 표 또는 원문 근거로
   동일 지표임이 확인되면 `MATCH_AFTER_CHANGE`로 둡니다.
3. 문자열 유사도만으로 동일 지표를 확정하지 마세요.
4. 유사도는 후보 정렬에만 사용하고 공식 근거가 없으면
   `MANUAL_REVIEW`로 둡니다.
5. 하나의 PDF 지표가 수기 행 여러 개에 매칭되거나 반대인 경우
   `AMBIGUOUS`로 둡니다.

### 7.3 숫자 비교

- 쉼표, 앞뒤 공백, `%` 표시는 비교용 정규화에서만 제거합니다.
- 원문 문자열과 숫자 변환값을 둘 다 보존합니다.
- 목표치·실적치·공식 달성률을 서로 다른 필드로 유지합니다.
- 공식 달성률은 문서 표시값을 보존합니다.
- 계산 달성률이 가능한 경우 별도 `computed_achievement_rate`로만
  계산하고 공식 달성률을 덮어쓰지 마세요.
- 계산식:
  - 상향지표: 실적치 ÷ 목표치 × 100
  - 하향지표: 목표치 ÷ 실적치 × 100
- 지표 방향이 불명확하거나 분모가 0이면 계산값은 null입니다.
- 반올림 차이와 실제 불일치를 분리하세요.
  - 절대 차이 0.1%p 이내: `ROUNDING_ONLY`
  - 그보다 큰 차이: `RATE_MISMATCH`
- 이 허용치는 품질검사용 기술 기준일 뿐 정책 기준이 아닙니다.

현재 수기 데이터의 `indicator_direction`에는
`상향66:57`처럼 오염된 값이 있을 수 있습니다. 조용히 `상향`으로
고치지 말고 원본값을 보존한 뒤 `DIRECTION_PARSE_REVIEW`로 표시하세요.

## 8. 행별 판정값

각 판정은 한 필드에 억지로 합치지 말고 다음 필드를 별도로 만드세요.

- `plan_name_match_status`
- `plan_target_match_status`
- `report_name_match_status`
- `report_target_match_status`
- `report_actual_match_status`
- `report_achievement_rate_match_status`
- `page_evidence_status`
- `ocr_status`
- `overall_reconciliation_status`

허용 상태값:

- `EXACT_MATCH`
- `MATCH_AFTER_CHANGE`
- `ROUNDING_ONLY`
- `VALUE_MISMATCH`
- `MANUAL_MISSING_PDF_PRESENT`
- `PDF_MISSING_MANUAL_PRESENT`
- `PDF_NOT_FOUND`
- `OCR_REQUIRED`
- `AMBIGUOUS`
- `MANUAL_REVIEW`
- `NOT_APPLICABLE`

`overall_reconciliation_status` 우선순위:

1. `AMBIGUOUS`
2. `OCR_REQUIRED`
3. `VALUE_MISMATCH`
4. `MANUAL_MISSING_PDF_PRESENT`
5. `PDF_MISSING_MANUAL_PRESENT`
6. `MATCH_AFTER_CHANGE`
7. `EXACT_MATCH`

낮은 우선순위 상태로 높은 우선순위 문제를 숨기지 마세요.

## 9. 최종 행 스키마

최종 대조 테이블은 반드시 수기 63행을 기준으로 한 행씩 유지하고,
최소한 다음 컬럼을 포함하세요.

- source_indicator_id
- ministry_code
- ministry_name
- fiscal_year
- strategic_goal_number
- program_goal_number
- source_program_code
- performance_program_name
- manual_indicator_name_plan
- manual_indicator_name_report
- manual_indicator_unit
- manual_indicator_direction_raw
- manual_planned_target_raw
- manual_actual_value_raw
- manual_official_achievement_rate_raw
- pdf_plan_program_name
- pdf_plan_indicator_name
- pdf_plan_unit
- pdf_plan_direction_raw
- pdf_plan_target_raw
- pdf_report_program_name
- pdf_report_indicator_name
- pdf_report_unit
- pdf_report_target_raw
- pdf_report_actual_raw
- pdf_report_official_achievement_rate_raw
- planned_target_numeric_manual
- planned_target_numeric_pdf
- actual_value_numeric_manual
- actual_value_numeric_pdf
- official_achievement_rate_numeric_manual
- official_achievement_rate_numeric_pdf
- computed_achievement_rate
- plan_name_match_status
- plan_target_match_status
- report_name_match_status
- report_target_match_status
- report_actual_match_status
- report_achievement_rate_match_status
- page_evidence_status
- ocr_status
- overall_reconciliation_status
- review_reason
- reviewer
- review_status
- plan_source_file
- plan_split_pdf_page
- plan_source_pdf_page
- plan_printed_page
- plan_source_text
- report_source_file
- report_split_pdf_page
- report_source_pdf_page
- report_printed_page
- report_source_text
- source_trace

`reviewer`와 `review_status`는 자동으로 사람 이름이나 완료값을 넣지
마세요. 자동 확인 결과와 사람 검수 완료를 구분해야 합니다.

## 10. 출력 파일

다음 파일을 생성하세요.

### 10.1 기계 판독용 기준 파일

- data/processed/performance/pdf_reconciliation/
  mss_performance_pdf_reconciliation.parquet

조건:

- 정확히 63행
- 원본 문자열과 숫자 변환값을 함께 보존
- 한 행은 기존 `source_indicator_id` 하나
- 기본키 중복 0

### 10.2 사람이 검토할 CSV

- data/processed/performance/pdf_reconciliation/
  mss_performance_pdf_manual_review.csv

조건:

- `overall_reconciliation_status != EXACT_MATCH`인 행만 포함
- UTF-8 with BOM으로 저장
- 엑셀에서 한글이 깨지지 않아야 함
- 자동 확정할 수 없는 행을 누락하지 말 것

### 10.3 검증 요약

- data/processed/performance/pdf_reconciliation/
  reconciliation_summary.json

포함 항목:

- 입력 행 수
- 출력 행 수
- 연도별 행 수
- 상태별 행 수
- 계획서 지표명 일치 수
- 보고서 지표명 일치 수
- 목표치 일치·불일치·결측 수
- 실적치 일치·불일치·결측 수
- 공식 달성률 일치·반올림·불일치·결측 수
- OCR 필요 행 수와 페이지 수
- 모호한 매칭 수
- PDF 미발견 수
- 수기에는 없지만 PDF에 있는 값 수
- PDF에는 없지만 수기에 있는 값 수
- 기본키 중복 수
- 원본 파일 SHA-256

### 10.4 사람 검토용 엑셀

- data/exports/performance/
  mss_performance_pdf_reconciliation.xlsx

시트 구성:

1. `README`
   - 목적
   - 입력 파일
   - 한 행의 기준
   - 상태값 정의
   - 숫자 비교 규칙
   - 해석 제한
2. `SUMMARY`
   - 연도별·상태별 건수
   - 일치·불일치·OCR 필요·모호·미발견 건수
   - 수식 또는 기준 데이터 참조로 계산
3. `RECONCILIATION_63`
   - 전체 63행
   - 필터와 첫 행 고정
   - 원본값과 PDF값을 나란히 배치
4. `MANUAL_REVIEW`
   - 자동 확정되지 않은 행만 표시
   - `reviewer`, `review_status`, `review_note`를 사람이 입력할 수 있게 함
5. `PAGE_QA`
   - PDF 파일별 페이지 수, 회전 방향, 저텍스트 페이지, OCR 상태

엑셀 서식:

- 데이터 영역에서 셀 병합 금지
- 식별자와 코드 컬럼은 텍스트 형식
- 상태별 조건부 서식:
  - 초록: `EXACT_MATCH`
  - 파랑: `MATCH_AFTER_CHANGE`, `ROUNDING_ONLY`
  - 노랑: `OCR_REQUIRED`, `MANUAL_REVIEW`
  - 빨강: `VALUE_MISMATCH`, `AMBIGUOUS`, `PDF_NOT_FOUND`
  - 회색: `NOT_APPLICABLE`
- 모든 시트에서 잘린 헤더와 값이 없도록 열 너비와 줄바꿈 조정
- `RECONCILIATION_63`과 `MANUAL_REVIEW`에 자동필터 적용
- `review_status`는 빈 값, `PENDING`, `CONFIRMED`, `CORRECTED`,
  `NOT_RESOLVABLE`만 입력 가능하도록 데이터 검증

### 10.5 방법론 및 결과 문서

- docs/MSS_PERFORMANCE_PDF_RECONCILIATION.md

반드시 포함할 내용:

- 무엇을 대조했는지
- 프로그램·지표 매칭 규칙
- 숫자 변환과 달성률 비교 규칙
- 연도별 결과
- 불일치 유형과 대표 사례
- OCR 필요 범위
- 수기자료를 그대로 쓸 수 있는 행과 쓸 수 없는 행
- 아직 사람이 결정해야 하는 사항
- 성과를 세부사업에 귀속할 수 없다는 제한
- 최종 점수·순위에 아직 사용할 수 없다는 제한

## 11. 구현 위치

확정 로직은 노트북에만 두지 말고 기존 패키지 구조를 재사용해
`src/performance_pipeline/` 아래에 최소한으로 구현하세요.

권장 파일:

- src/performance_pipeline/pdf_reconciliation.py
- tests/performance_pipeline/test_pdf_reconciliation.py

CLI가 필요하면 기존 `src/performance_pipeline/cli.py`에 다음 명령 하나만
추가하세요.

- reconcile-mss-performance-pdfs

불필요한 클래스, 인터페이스, 별도 프레임워크는 만들지 마세요.
페이지 추출, 문자열 정규화, 숫자 비교, 상태 판정에 필요한 최소 함수만
작성하세요.

## 12. 필수 검증

다음을 자동 검증하고 실제 결과를 보고하세요.

1. 입력 `program_kpi_year.parquet`가 63행인지 확인
2. 출력 Parquet가 63행인지 확인
3. 연도별 행 수가 24, 26, 13인지 확인
4. `source_indicator_id` 중복이 0인지 확인
5. 입력 원본 PDF와 수기 엑셀의 SHA-256이 실행 전후 동일한지 확인
6. 모든 비결측 PDF 값에 파일명과 페이지 근거가 있는지 확인
7. 페이지 번호가 해당 PDF 페이지 범위 안인지 확인
8. `PDF_NOT_FOUND`와 `OCR_REQUIRED` 행이 조용히 삭제되지 않았는지 확인
9. 결측을 0으로 변환한 행이 없는지 확인
10. 공식 달성률을 계산 달성률로 덮어쓴 행이 없는지 확인
11. 계획서 목표치와 보고서 목표치를 같은 필드로 덮어쓰지 않았는지 확인
12. 원본 수기값과 PDF값이 별도 컬럼으로 보존되는지 확인
13. 검토 CSV의 행 수가 전체 테이블의 비정확일치 행 수와 같은지 확인
14. 엑셀 SUMMARY의 상태별 합계가 63인지 확인
15. 엑셀 모든 시트를 렌더링해 헤더·한글·숫자·원문 근거가 잘리지 않는지
    육안 확인

작은 수기 테스트 사례를 최소 4개 만드세요.

- 완전일치
- 계획서-보고서 지표명 변경
- 수기 결측이지만 PDF에는 값 존재
- OCR 필요 또는 모호한 매칭

실행 후 다음을 통과해야 합니다.

- 관련 pytest
- Ruff format
- Ruff check
- 실제 63행 전체 실행
- 출력 스키마·행 수·기본키·원본 무변경 검증

Windows 기본 임시폴더 때문에 pytest가 실패하면 저장소 로컬 임시폴더를
사용하세요.

- pytest ... --basetemp=.pytest_tmp

## 13. 중단하고 보고해야 하는 경우

다음은 임의로 확정하지 말고 후보와 근거를 보고한 뒤 판단을 요청하세요.

- 한 PDF 지표가 수기 여러 행에 대응함
- 계획서와 보고서 지표가 변경됐지만 변경사항 근거가 없음
- 프로그램명이 달라 프로그램 단위가 두 가지 이상 가능함
- 단위가 달라 숫자를 직접 비교할 수 없음
- 공식 달성률 산식이 일반 상향·하향 산식과 다름
- OCR 결과가 두 가지 이상으로 읽힘
- PDF와 수기 중 어느 쪽이 맞는지 원문만으로 판단할 수 없음
- 수기 행을 삭제하거나 새 행을 추가해야 63행 계약이 바뀜

질문만 던지지 말고 각 선택지의 영향과 권장안을 함께 제시하세요.

## 14. 완료 보고 형식

최종 답변은 다음 순서로 작성하세요.

1. 결론: 63행 중 그대로 사용 가능, 변경 확인, 값 불일치, OCR 필요,
   모호, 미발견 건수
2. 핵심 근거: 연도별 행 수와 주요 불일치 사례
3. 생성 파일: Parquet, CSV, JSON, Excel, 방법론 문서
4. 검증 결과: pytest, Ruff, 원본 해시, 기본키, 행 수
5. 해석 제한: 어떤 값은 분석에 쓸 수 있고 어떤 값은 아직 쓸 수 없는지
6. 다음 작업: 사람이 확인해야 할 행만 우선순위로 제시

“파일을 생성했습니다” 또는 “테스트가 통과했습니다”만으로 끝내지 마세요.
불일치와 결측이 분석에 미치는 영향을 함께 설명하세요.
```

## 사용자 확인용 핵심 산출물

Cursor AI 작업이 끝나면 먼저 다음 두 파일만 확인하면 됩니다.

1. `data/exports/performance/mss_performance_pdf_reconciliation.xlsx`
   - `SUMMARY`: 전체 결과
   - `MANUAL_REVIEW`: 사람이 확인해야 할 행
2. `docs/MSS_PERFORMANCE_PDF_RECONCILIATION.md`
   - 방법론, 불일치 유형, 분석 사용 가능 범위

Parquet과 JSON은 파이프라인 재현 및 자동 검증용입니다.
