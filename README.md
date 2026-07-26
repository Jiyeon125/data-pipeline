# Open Fiscal Data Pipeline

열린재정 Open API 원본을 수집하는 Python 파이프라인입니다.

## 프로젝트 범위와 구조

이 프로젝트는 OpenAPI 수집뿐 아니라 성과계획서·성과보고서 LLM 파싱,
성과·재정 마스터 테이블 엔지니어링, 애널리틱스, BI·시각화까지 단계적으로
확장합니다.

```text
open_fiscal_pipeline   열린재정 OpenAPI 수집·정규화
performance_pipeline   성과 문서 수집·LLM 추출·검증
master_engineering     전처리·조인·마스터·품질
fiscal_analytics       피처·순위·민감도·보고
fiscal_dashboard       BI 앱·차트·데이터 계약
```

상세한 의존 방향, 데이터 계층과 팀 공유 마일스톤은
[프로젝트 아키텍처](docs/architecture.md)를 참고합니다.

## 설치

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
```

`.env`에 발급받은 `OPEN_FISCAL_API_KEY`를 입력합니다. 인증키는 저장소에
커밋하지 않습니다.

## 월별 지출운용상황 일괄 수집

기본 명령은 설정된 5개 부처의 2022~2025년 전체 월을 수집합니다.

```powershell
openfiscal collect-monthly-all
```

범위와 부처를 제한할 수 있습니다. 소관코드는 문자열이며 `019`, `075`의
앞자리 0을 그대로 입력합니다.

```powershell
openfiscal collect-monthly-all `
  --start-year 2024 `
  --end-year 2025 `
  --ministry-code 019 `
  --page-size 1000
```

동일 부처·연월에 `page_*.json`이 하나라도 있으면 기본적으로 해당 월을
건너뜁니다.

- `--resume`: 기존 페이지의 메타데이터를 읽고 미완료된 다음 페이지부터 수집
- `--overwrite`: 기존 페이지 파일을 삭제하고 해당 부처·연월을 처음부터 재수집

두 옵션은 동시에 사용할 수 없습니다. 한 부처·연월의 API 요청이 실패해도
나머지 작업은 계속되며, 전체 작업 종료 시 실패가 있었다면 종료 코드는 1입니다.

원본은 다음과 같이 분리 저장됩니다.

```text
data/raw/monthly_expenditure/
  year=2024/
    ministry_code=102/
      execution_month=202412/
        page_0001_<timestamp>.json
```

각 파일에는 요청시각, 데이터셋 ID, 회계연도, 집행연월, 소관코드, 페이지 번호,
페이지 크기, 전체 건수, 결과 코드와 원본 API 응답이 포함됩니다. 실행별 전체
결과와 실패 목록은 같은 루트의 `collection_summary_<timestamp>.json`에
기록됩니다. 실패는 발생 즉시 `collection_failures_<timestamp>.jsonl`에도
한 줄씩 기록됩니다.

부처 목록은 [configs/ministries.yaml](configs/ministries.yaml), API 데이터셋
명세는 [configs/datasets.yaml](configs/datasets.yaml)에서 관리합니다.

## 월별 지출운용상황 정규화

수집된 원본 JSON을 분석용 테이블로 변환합니다. 원본 파일은 수정하지 않습니다.

```powershell
openfiscal normalize-monthly
```

기본 입력은 `data/raw/monthly_expenditure/`, 기본 출력은
`data/processed/monthly_expenditure/`이며 기본 형식은 Parquet입니다.

```powershell
openfiscal normalize-monthly `
  --input-dir data/raw/monthly_expenditure `
  --output-dir data/processed/monthly_expenditure `
  --format both `
  --start-year 2022 `
  --end-year 2025 `
  --ministry-code 019 `
  --overwrite
```

- `--format`: `parquet`(기본), `csv`, `both`
- `--overwrite`: 기존 출력 파일이 있으면 덮어쓰기

출력 구조 예시:

```text
data/processed/monthly_expenditure/
  monthly_expenditure_2022_2025.parquet
  monthly_expenditure_2022_2025.csv          # --format csv|both
  year=2022/monthly_expenditure.parquet
  year=2023/monthly_expenditure.parquet
  year=2024/monthly_expenditure.parquet
  year=2025/monthly_expenditure.parquet
  data_dictionary.csv
  normalization_summary.json
  validation_issues.csv
```

마스킹 금액(`180310*******` 등)은 숫자로 추정하지 않습니다. 해당 금액 컬럼은
null로 두고, `is_masked=true`, `masked_fields`, `masked_raw_values`,
`amount_missing_reasons=MASKED_SOURCE_VALUE`로 원문과 결측사유를 보존합니다.
누계 감소 등은 실패·낭비 판정이 아니라 `집행설명필요` 신호로만 표시합니다.

논리 테이블 ID는 멘토링 지침(§22.4)의 `project_month`이며, 금액 컬럼은
본예산·예산현액·지출·누계총계·누계순계를 혼합하지 않고 별도 보존합니다.

검증 파일:

- `validation_issues.csv`: 회계연도·집행연월 불일치, 누계 감소(집행설명필요),
  당월·누계 검산, 마스킹, 복합키 중복 등 표시(값은 수정하지 않음)
- `normalization_summary.json`: 읽은 파일·레코드 수, 부처·연도별 행 수, 마스킹·
  이상 플래그 집계, 수기검증 대상 수, 실패 파일 목록
- `data_dictionary.csv`: 컬럼 설명, 원본 필드 매핑, 멘토링 금액유형 잠정 대응

분석 원칙의 상세는 [docs/MENTORING_GUIDE.md](docs/MENTORING_GUIDE.md)를
따릅니다.

## 예산 API 일괄 수집·정규화

5개 부처의 2022~2025년 세부사업·세목 예산 API 원본을 수집합니다.
이미 완료된 파티션은 건너뛰며, 실패와 무자료 조합은 실행 요약에 남깁니다.

```powershell
openfiscal collect-budget-all --start-year 2022 --end-year 2025
```

수집된 원본은 데이터셋·연도·소관코드별로 보존합니다.

```text
data/raw/budget/<dataset_id>/year=2024/ministry_code=102/page_*.json
```

예산 레코드와 금액 이벤트를 분리해 정규화하고, 월별 집행 테이블의 이름-코드
대응을 사용해 유일한 후보만 자동 매칭합니다.

```powershell
openfiscal normalize-budget
```

`amount_type`은 API 원본 필드명을 그대로 사용합니다. 금액 단위는 공식 명세를
추가 확인하기 전까지 `unit_confirmed=false`로 유지하며, 미매칭·복수 후보·마스킹·
파싱 실패·중복은 `manual_review.csv`에 남깁니다.

예산 API만 반영한 사업-연도 중간 기준 테이블은 다음 명령으로 만듭니다.

```powershell
fiscal-master build-project-year-budget
fiscal-master build-project-year-financial
```

이 결과는 `data/processed/masters/project_year_budget_base.parquet`에 저장됩니다.
두 번째 명령은 월별 집행을 외부 결합한
`project_year_financial_base.parquet`를 생성합니다. 기금의 지출계획현액 분모가
확정되기 전에는 집행률을 계산하지 않습니다. 결산 CSV와 성과 문서가 연결되기
전에는 어느 결과도 최종 분석 마스터로 사용하지 않습니다.

## 결산 정규화 및 재정 사업-연도 v1

사업별결산세출지출현황 CSV 디렉터리를 지정해 대상 부처 자료를 정규화합니다.

```powershell
openfiscal normalize-settlement `
  --input-dir "<사업별결산세출지출현황 CSV 디렉터리>"
```

정규화된 결산을 예산·월별 집행 기준 테이블에 연결하고, 12월 누계 대조와
회계유형별 집행률 분모 규칙을 적용합니다.

```powershell
fiscal-master build-project-year-financial-v1
```

- 일반회계·특별회계: 결산 세출예산현액을 분모로 사용
- 기금: 월별 집행의 지출계획현액 대응 컬럼을 분모로 사용
- 분모 누락·0, 회계유형 미확정, 집행률 1 초과는 수기검토 목록에 기록
- 원본 결산과 12월 누계가 다르면 값을 덮어쓰지 않고 대조 상태와 차이를 보존

후속 품질검증은 다음 명령으로 실행합니다.

```powershell
fiscal-master analyze-financial-v1-quality --overwrite
```

이 명령은 원본 금액을 수정하지 않고 12월 누계·결산 불일치 원인, 부처·연도·
회계유형별 총누계·순누계 대응도, 집행률 1 초과, 수기검토 우선순위를
`data/processed/masters/quality/` 아래에 생성합니다.

- `financial_reconciliation_analysis.csv`
- `execution_rate_over_100.csv`
- `manual_review_prioritized.csv`
- `reconciliation_summary.json`

## 사업분류 및 재정분석 모집단

LLM이나 외부 API 없이 financial v1의 코드·명칭·구조화 필드와 기존 품질검증
결과를 사용해 사업분류 마스터와 분석 모집단을 생성합니다.

```powershell
fiscal-master build-project-analysis-population --overwrite
```

- 책임운영기관 회계코드 4xx는 `RESPONSIBLE_OPERATION_ACCOUNT`로 분리
- 재정수단 명칭 키워드 단일 적중은 `RULE_CANDIDATE`
- 복수 재정수단 키워드와 근거 부족은 자동 확정하지 않고 수기검토
- 인건비·기본경비·내부거래 등 제외 행도 삭제하지 않고 별도 모집단에 보존
- `NON_BLOCKING`·`INFORMATIONAL`은 일반 재정분석 적격을 유지
- 집행률 1 초과·분모 미확정·중대한 대조 차이는 해당 지표 적격 플래그로 제한
- 비교집단 크기 5 미만은 병합하지 않고 `small_group_flag=true`

주요 출력:

```text
data/processed/masters/
  project_classification.parquet
  project_year_analysis_population.parquet
  project_year_analysis_excluded.parquet
  classification/
    classification_summary.json
    classification_manual_review.csv
    analysis_population_summary.json
    exclusion_summary.csv
```

기존 포함·제외 모집단의 과도한 제외 여부와 분석별 적격성을 다시 검증합니다.

```powershell
fiscal-master analyze-population-sensitivity --overwrite
```

이 명령은 예산·집행·결산·월별패턴·추세·순위 분석 적격 플래그를 각각 생성하고,
`broad_population ⊇ core_financial_population ⊇ strict_ranking_population`
관계를 검증합니다. 소표본 비교집단은 병합하지 않고 순위 제한 플래그로 남깁니다.

출력은 `data/processed/masters/population_sensitivity/`에 저장됩니다.

사업 연속성 후보, 세부사업-연도 재정 파생변수, 프로그램-연도 재정 테이블을
생성합니다.

```powershell
fiscal-master build-project-continuity --overwrite
```

- `broad_population`: 전체 재정구조와 일반 기술통계
- `core_financial_population`: 재정·집행률·추세·프로그램 집계
- `strict_ranking_population`: 비교집단 내부 점검 순위에만 사용
- 신규·종료·통합·분할·이관 및 연속성 미확정 사업은 일반 예산 증감률에서 제외
- 2022년 시작과 2025년 종료 경계는 신규·종료로 단정하지 않고
  `LEFT_CENSORED`·`RIGHT_CENSORED` 정보성 관계로 관리
- `PARTIAL`/`UNMATCHED` 프로그램은 부분 집행률을 전체값처럼 계산하지 않음

주요 출력은 `project_relation.parquet`, `project_year_financial_v2.parquet`,
`program_year_financial.parquet` 및 대응 품질 요약 파일입니다.

기존 strict 순위 모집단의 과도한 행 제외를 변수별 적격 정책으로 재설계합니다.

```powershell
fiscal-master build-ranking-population-v2 --overwrite
```

- core 6,290행을 기본 순위 모집단으로 유지
- UNKNOWN 재정수단은 재정수단 구성요소만 제한
- 집행률 1 초과는 집행 구성요소만 제한
- 관측경계·관계 후보는 추세 구성요소만 제한
- 소표본 비교집단은 행을 유지하고 `rank_confidence=LOW`로 표시
- 모든 핵심 변수가 무효이거나 복구 불가능한 키·파싱 문제만 행 전체 제외

출력은 `data/processed/masters/population_sensitivity/`의
`ranking_population_v2.parquet` 및 strict 제외 규칙·비교·요약 파일입니다.

## 기타 명령

## M2 재정 데이터 EDA

외부 API·LLM·PDF 파싱 없이 현재 재정 마스터를 이용해 5개 부처의 데이터 품질,
재정구조, 월별 집행 패턴과 모집단 대표성을 점검합니다.

```powershell
fiscal-analytics build-m2-data-review --root .
```

실행 결과:

- 분석표 9개: `data/analytics/eda/`
- 그래프 9개: `artifacts/figures/eda/`
- 팀 중간점검 보고서: `docs/M2_DATA_REVIEW.md`

`broad_population`은 전체 구조, `core_financial_population`은 금액·집행 분석,
`strict_ranking_population`은 기존 순위 모집단의 대표성 진단에만 사용합니다.
새 `ranking_population_v2`는 core 행을 유지하고 분석 변수별 적격 플래그를 적용합니다.

최종 점수·순위를 만들기 전 분석 정의와 대표성을 검증합니다.

```powershell
fiscal-analytics validate-m2-definitions --root .
```

- 검증표 12개: `data/analytics/definition_validation/`
- 분석 기준 확정 보고서: `docs/M2_ANALYSIS_DEFINITION_VALIDATION.md`
- 최종 점수·최종 순위·정책 결론은 생성하지 않음

## M3 재정 신호와 예산 환류 탐색

검증된 재정지표에서 집행률·연말집중 기준을 비교하고, 독립 재정 신호와
T+1·T+2 예산변화의 연관성을 탐색합니다. 최종 복합점수나 전체 순위는 생성하지 않습니다.

```powershell
fiscal-analytics build-m3-financial-signals --root .
```

- 분석표와 피처: `data/analytics/m3/`
- 판단용 그래프 8개: `artifacts/figures/m3/`
- 분석 및 권장안 보고서: `docs/M3_FINANCIAL_INSIGHTS.md`
- 임계값은 사용자·팀 결정 전까지 확정 설정으로 저장하지 않음

## M3 방법론 감사

상대 분위수의 경계 동률, 신호 분석 단위, 동일 사업 반복관측과
UNKNOWN 분류 검토 효과를 기존 M3 산출물과 분리해 감사합니다.

```powershell
fiscal-analytics audit-m3-methodology --root .
```

- 감사표와 단위별 피처: `data/analytics/m3_audit/`
- 감사 보고서: `docs/M3_METHODOLOGY_AUDIT.md`
- 기존 M3 산출물과 원본 금액은 덮어쓰지 않음

## 분석 기준 의사결정 자료

집행률 70~95% 임계값, 비가중·예산가중 ECDF, 집단별 탐지 편향,
상대기준 표본 안정성, 연말집중 유형과 반복 신호를 비교합니다.
이 명령은 최종 임계값·복합점수·전체 순위를 저장하지 않습니다.

```powershell
fiscal-analytics build-analysis-policy-decision-support --root .
```

- 편집 가능한 분석표: `data/analytics/decision_support/`
- 발표용 정적 그래프: `artifacts/figures/decision_support/`
- 그래프 읽는 법과 질의응답 근거: `docs/ANALYSIS_POLICY_DECISION_SUPPORT.md`

```powershell
openfiscal doctor
openfiscal probe monthly_expenditure `
  --year 2024 `
  --execution-month 202412 `
  --ministry-code 102
openfiscal collect expenditure_budget_init --year 2024 --ministry "중소벤처기업부"
```

## 품질 검사

```powershell
pytest -q
ruff check src tests
```
