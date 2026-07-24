# Open Fiscal Data Pipeline

열린재정 Open API 원본을 수집하는 Python 파이프라인입니다.

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

## 기타 명령

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
