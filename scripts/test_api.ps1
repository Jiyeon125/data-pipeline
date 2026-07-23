$ErrorActionPreference = "Stop"

Write-Host "[1/4] 환경 및 설정 검사"
openfiscal doctor

Write-Host "[2/4] 세부사업 총액 API 시험"
openfiscal probe expenditure_budget_init --year 2024 --ministry "중소벤처기업부"

Write-Host "[3/4] 총지출 API 시험"
openfiscal probe total_expenditure_project --year 2024 --ministry "중소벤처기업부"

Write-Host "[4/4] 전체 API 시험"
Write-Host "월별 지출운용상황은 OPEN_FISCAL_MINISTRY_CODE가 비어 있으면 skipped로 표시됩니다."
openfiscal probe-all --year 2024 --ministry "중소벤처기업부" --supplementary-round 1 --execution-month 12
