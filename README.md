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

Windows PowerShell에서는 다음 명령을 사용해도 됩니다.

```powershell
Copy-Item .env.example .env
```

`.env`에 발급받은 인증키와 열린재정 Open API 상세화면의 실제 요청주소를 입력합니다.

```dotenv
OPEN_FISCAL_API_KEY=발급받은_인증키
OPEN_FISCAL_API_URL=https://실제_API_요청주소
```

인증키는 절대로 GitHub에 커밋하지 않습니다.

## 연결 테스트

```bash
openfiscal smoke-test
```

성공하면 인증키나 전체 응답값을 출력하지 않고 요청시각, 요청주소, 최상위 JSON 키만 표시합니다.

## 시험 수집

현재 초기 CLI는 실제 데이터셋의 검색 파라미터명이 확정되기 전 범용 연결검증용입니다.

```bash
openfiscal collect --max-pages 1
```

회계연도와 소관 파라미터가 실제로 `year`, `ministry`인 데이터셋에서만 다음 옵션을 사용합니다.

```bash
openfiscal collect --max-pages 1 --year 2024 --ministry 중소벤처기업부
```

데이터셋마다 파라미터명과 응답 필드가 다를 수 있으므로, 열린재정 Open API 상세화면의 `요청주소`, `검색 요청인자`, `출력값 명세`를 확인한 뒤 `configs/datasets.example.yaml`에 매핑합니다. 이후 이 설정파일을 읽는 정규화 수집 명령을 추가할 예정입니다.

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

- [x] 공개 저장소 초기화
- [x] `.env` 및 생성데이터 Git 제외
- [x] 범용 Open API 클라이언트
- [x] 인증키·요청주소 연결 테스트 명령
- [x] 원본 JSON 페이지 저장 기능
- [x] 데이터셋 매핑 템플릿
- [ ] 첫 데이터셋 요청주소·파라미터 확정
- [ ] 응답 레코드 경로 및 필드 매핑
- [ ] 중기부 2024년 5개 사업 시험수집
- [ ] 기존 마스터와 코드·금액 대조
- [ ] 전체 수집 및 분류마스터 생성
