# Open Fiscal Data Pipeline

열린재정 Open API와 공식 다운로드 자료를 수집·정규화하여 재정사업 분류마스터를 생성하는 파이프라인입니다.

## 목표

1. 열린재정 API 응답 원본을 수정하지 않고 저장
2. 세부사업 단위 표준 컬럼으로 정규화
3. 기존 중기부 분석마스터와 코드 중심으로 연결
4. 회계구분·정책수단·사업유형 분류 후보 생성
5. 자동분류 결과에 신뢰도와 수기검증 여부 부여

## 초기 실행

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -e .
cp .env.example .env
```

`.env`에 발급받은 인증키와 열린재정 상세통계 화면의 API 요청주소를 입력합니다.

```dotenv
OPEN_FISCAL_API_KEY=발급받은_인증키
OPEN_FISCAL_API_URL=https://요청주소
```

인증키는 절대로 GitHub에 커밋하지 않습니다.

## 연결 테스트

```bash
openfiscal smoke-test
```

## 데이터 수집

```bash
openfiscal collect \
  --dataset configs/datasets.example.yaml \
  --year 2024 \
  --ministry 중소벤처기업부
```

수집 결과는 다음에 저장됩니다.

- `data/raw/`: API 원본 JSON
- `data/interim/`: 정규화 중간 CSV
- `data/processed/`: 분류마스터 후보
- `logs/`: 호출 및 검증 로그

## 원칙

- API에 존재하는 값만 저장하고 누락값을 추정하지 않습니다.
- 원본 응답, 요청시각, 요청 파라미터, 데이터셋 식별자를 함께 보존합니다.
- 본예산·예산현액·집행액·결산액을 혼용하지 않습니다.
- 자동분류는 확정값이 아니라 후보값이며 수기검증 상태를 유지합니다.
- 낮은 집행률은 실패 판정이 아니라 설명이 필요한 점검 신호로 사용합니다.

## 현재 단계

초기 저장소는 특정 API 데이터셋의 요청주소와 응답 필드가 확정되기 전에도 연결 테스트가 가능하도록 범용 클라이언트로 구성되어 있습니다. 열린재정 상세통계에서 사용할 데이터셋의 `요청주소`, `검색 요청인자`, `출력값 명세`를 확인한 뒤 `configs/` 파일에 매핑을 추가합니다.
