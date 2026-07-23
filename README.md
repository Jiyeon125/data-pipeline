# Open Fiscal Data Pipeline

열린재정 Open API와 공식 다운로드 자료를 수집·검증하여 재정사업 분류마스터를 만드는 파이프라인입니다.

## 현재 구현 범위

- 열린재정 API 명세 6종의 정확한 요청인자 반영
- `Key`, `Type=json`, `pIndex`, `pSize` 기본인자 자동 적용
- 데이터셋별 필수인자·기본값 검증
- 첫 페이지 응답 구조와 출력 필드 점검
- 전체 페이지 원본 JSON 보존
- 인증키가 없어도 실행되는 단위테스트와 GitHub Actions

## 설치

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
```

`.env`에는 실제 인증키와 로컬 결산 CSV 경로만 입력합니다.

```dotenv
OPEN_FISCAL_API_KEY=발급받은_인증키
OPEN_FISCAL_SETTLEMENT_DIR="C:/.../사업별결산세출지출현황"
OPEN_FISCAL_MINISTRY_CODE=
OPEN_FISCAL_TIMEOUT=30
OPEN_FISCAL_PAGE_SIZE=1000
```

인증키는 GitHub에 커밋하지 않습니다.

## 1. 로컬 단위테스트

네트워크와 인증키 없이 실행됩니다.

```powershell
pytest -q
ruff check src tests
```

## 2. 환경설정 검사

네트워크 호출 없이 `.env`와 `configs/datasets.yaml`을 검사합니다.

```powershell
openfiscal doctor
```

## 3. 첫 API 시험 호출

```powershell
openfiscal probe expenditure_budget_init `
  --year 2024 `
  --ministry "중소벤처기업부"
```

성공 시 다음만 출력합니다.

- API 결과 코드
- 전체 건수와 첫 페이지 건수
- 최상위 JSON 키
- 실제 레코드 필드
- 명세 대비 누락·추가 필드

인증키와 전체 응답 본문은 콘솔에 출력하지 않습니다.

## 4. 전체 API 시험

```powershell
openfiscal probe-all `
  --year 2024 `
  --ministry "중소벤처기업부" `
  --supplementary-round 1 `
  --execution-month 12
```

`monthly_expenditure`는 `OFFC_CD`가 필수입니다. `.env`의 `OPEN_FISCAL_MINISTRY_CODE`가 비어 있으면 오류가 아니라 `skipped`로 표시됩니다.

준비된 PowerShell 스크립트를 실행해도 됩니다.

```powershell
.\scripts\test_api.ps1
```

## 5. 원본 데이터 수집

한 데이터셋을 마지막 페이지까지 수집합니다.

```powershell
openfiscal collect expenditure_budget_init `
  --year 2024 `
  --ministry "중소벤처기업부"
```

시험 수집은 페이지 수를 제한합니다.

```powershell
openfiscal collect expenditure_budget_init `
  --year 2024 `
  --ministry "중소벤처기업부" `
  --max-pages 1 `
  --page-size 10
```

원본 응답은 다음에 저장됩니다.

```text
data/raw/<dataset_id>/year=<year>/page_0001_<timestamp>.json
```

메타데이터에는 요청시각·데이터셋·페이지·필터·건수를 저장하지만 인증키는 저장하지 않습니다.

## 데이터셋별 필수입력

| 데이터셋 ID | 필수 입력 | 자동 기본값 |
|---|---|---|
| `expenditure_budget_init` | `--year` | 없음 |
| `total_expenditure_project` | `--year` | 전체 예산·기금, 총지출 |
| `expenditure_budget_add` | `--year`, `--supplementary-round` | 없음 |
| `monthly_expenditure` | `--year`, `--execution-month`, 소관코드 | 없음 |
| `total_expenditure_item` | `--year` | 전체 예산·기금, 총지출 |
| `expenditure_budget_init_item` | `--year` | 없음 |

명세에 없는 실험 인자는 `--param KEY=VALUE`로 추가할 수 있습니다.

```powershell
openfiscal probe expenditure_budget_init `
  --year 2024 `
  --param FSCL_NM=일반회계
```

## 수집 원칙

- API에 존재하는 값만 저장하고 누락값을 추정하지 않습니다.
- 본예산·총지출·추경·예산현액·결산을 구분합니다.
- 원본 응답을 먼저 보존한 뒤 정규화합니다.
- 낮은 집행률은 실패 판정이 아니라 설명이 필요한 점검 신호로 사용합니다.
