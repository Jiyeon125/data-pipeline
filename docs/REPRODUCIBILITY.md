# 재현 실행 절차

## 전제

- Windows PowerShell
- Python 3.13
- 저장소 루트에서 실행
- 원본 데이터는 Git에 포함되지 않으므로 `data/raw`, `data/manual`에 별도 배치
- 열린재정 API를 다시 수집할 때만 `.env`의 `OPEN_FISCAL_API_KEY` 필요
- 외부 LLM API는 현재 재현 절차에서 사용하지 않음

## 1. 환경 설치

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

환경을 바꿀 때는 활성화 상태에 의존하지 않고 아래처럼
`.\.venv\Scripts\...` 실행 파일을 직접 호출합니다.

## 2. 재정 마스터 재생성

```powershell
.\.venv\Scripts\fiscal-master.exe build-project-analysis-population --overwrite
.\.venv\Scripts\fiscal-master.exe analyze-population-sensitivity --overwrite
.\.venv\Scripts\fiscal-master.exe build-project-continuity --overwrite
.\.venv\Scripts\fiscal-master.exe build-ranking-population-v2 --overwrite
```

## 3. 분석 정의와 재정 신호 재생성

```powershell
.\.venv\Scripts\fiscal-analytics.exe validate-m2-definitions --root .
.\.venv\Scripts\fiscal-analytics.exe build-m3-financial-signals --root .
.\.venv\Scripts\fiscal-analytics.exe audit-m3-methodology --root .
.\.venv\Scripts\fiscal-analytics.exe build-analysis-policy-decision-support --root .
```

## 4. 설정 기반 N개 부처 결합과 탐색 순위 재생성

```powershell
.\.venv\Scripts\fiscal-analytics.exe analyze-priority-scenarios --root . --overwrite
```

분석 부처는 `configs/priority_scenarios.yaml`의 `scope.ministry_codes`에서
읽습니다. 이 명령은 탐색용 복수 시나리오를 생성하며 최종 정책 순위를
만들지 않습니다.

## 5. 품질검사

```powershell
.\.venv\Scripts\ruff.exe check src tests scripts
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest_final
.\.venv\Scripts\python.exe -m pip check
```

## 6. 최종 데이터 패키지

```powershell
.\.venv\Scripts\python.exe scripts\build_final_package.py
```

출력은 Git에서 제외된 `exports/final_package/`에 생성됩니다.
`MANIFEST.json`에는 원본 상대경로, 파일 크기, SHA-256, CSV 행·열 수가
기록되고 `DATA_DICTIONARY.csv`에는 컬럼·자료형·결측 수가 기록됩니다.

## 7. 대시보드

```powershell
.\.venv\Scripts\python.exe -m streamlit run src\fiscal_dashboard\app.py
```

대시보드는 검증된 분석 산출물을 읽기만 하며 화면 안에서 점수나 순위를
재계산하지 않습니다.
