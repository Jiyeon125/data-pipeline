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
