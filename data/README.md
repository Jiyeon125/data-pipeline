# Data zones

이 디렉터리의 실제 데이터 파일은 Git에 올리지 않습니다. 폴더 구조를 유지하기 위한
`.gitkeep`만 추적합니다.

- `raw/`: 수집한 원본. 수정하거나 덮어쓰지 않습니다.
- `interim/`: OCR, 페이지 분할, LLM 원시 응답 등 재생성 가능한 중간 산출물입니다.
- `processed/`: 검증된 정규화 테이블과 분석용 마스터입니다.
- `analytics/`: 피처, 통계 결과, 순위, 검증 결과 테이블입니다.
- `exports/`: 대시보드 또는 제출 시스템에 전달하는 계약 기반 산출물입니다.

## 사업별결산세출지출현황 CSV

OpenAPI에서 시트 형태로 제공되지 않아 별도로 확보한 CSV는 다음처럼 둡니다.

```text
data/raw/settlement/
  사업별결산세출지출현황_2022.csv
  사업별결산세출지출현황_2023.csv
  사업별결산세출지출현황_2024.csv
```

파일명은 `configs/datasets.yaml`의
`사업별결산세출지출현황_{year}.csv` 패턴을 따릅니다. `.env`에는
`OPEN_FISCAL_SETTLEMENT_DIR=data/raw/settlement`를 설정합니다.
