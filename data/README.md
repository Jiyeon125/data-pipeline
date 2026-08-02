# Data zones

이 디렉터리의 실제 데이터 파일은 Git에 올리지 않습니다. 폴더 구조를 유지하기 위한
`.gitkeep`만 추적합니다.

저장소 실행에 필요한 최소 합성 테스트 픽스처만 `tests/fixtures/`에서
추적할 수 있습니다. 실제 원자료나 실제 행을 테스트 픽스처로 복사하지 않습니다.

- `raw/`: 수집한 원본. 수정하거나 덮어쓰지 않습니다.
- `interim/`: OCR, 페이지 분할, LLM 원시 응답 등 재생성 가능한 중간 산출물입니다.
- `processed/`: 검증된 정규화 테이블과 분석용 마스터입니다.
- `analytics/`: 피처, 통계 결과, 순위, 검증 결과 테이블입니다.
- `exports/`: 대시보드 또는 제출 시스템에 전달하는 계약 기반 산출물입니다.

`processed/core_v2_shadow/`는 기존 마스터를 바꾸지 않고 entity·year version·
account/fund·금액 fact·evidence·legacy crosswalk를 병행 검증하는 재생성 가능
shadow입니다. 현재 대시보드 입력이 아니며, `manifest.json`의 모든 계약 검사가
통과한 경우에만 다음 migration 단계의 입력으로 사용합니다.

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
