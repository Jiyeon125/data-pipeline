# 프로젝트 아키텍처

## 목적

이 저장소는 부처별 성과계획서·성과보고서의 비정형 정보를 구조화하고, 열린재정
OpenAPI 자료와 결합해 분석용 마스터 테이블을 만든 뒤, 검증된 분석 결과를
대시보드로 전달합니다.

## 전체 흐름

```text
성과계획서·성과보고서 원본
  → performance_pipeline
      문서 인벤토리·페이지 분할
      LLM 구조화 추출
      스키마·단위·근거 페이지·골드셋 검증
                    ┐
                    ├→ master_engineering
열린재정 OpenAPI    │    추출값 정제
  → open_fiscal_pipeline
      원본 수집·정규화 ┘    단계별 조인·매칭상태
                         program_year / kpi_year / project_year
                         project_month / amount_event / masters
                                      ↓
                              fiscal_analytics
                         피처·비교집단·순위·민감도
                                      ↓
                              data/analytics
                                      ↓
                              data/exports
                                      ↓
                              fiscal_dashboard
```

## 코드 경계

### `open_fiscal_pipeline`

기존 OpenAPI 수집과 월별 지출 정규화를 담당합니다. API 응답과 분석 테이블의
경계를 유지하며 다른 분석 패키지를 import하지 않습니다.

### `performance_pipeline`

성과계획서·성과보고서만 다룹니다.

- `ingest`: 문서 목록, 유형 분류, 페이지 분할
- `extract`: 성과지표명, 단위, 목표, 실적, 공식 달성률과 근거 추출
- `validate`: JSON 스키마, 수치·단위, 원문 근거, 골드셋 평가
- `prompts`: 버전이 명시된 프롬프트

LLM 응답은 최종 정답이 아니라 `data/interim/llm_extractions`의 원시 추출값입니다.
문서에 없는 값은 추정하지 않고 `null`과 검토 상태로 남깁니다.

### `master_engineering`

문서 추출값과 OpenAPI 정규화 자료를 결합합니다.

- `clean`: 원본과 정제값을 분리하는 비파괴 정제
- `join`: `configs/join_keys.yaml` 기반 단계별 매칭
- `build_masters`: 분석 기준 테이블 생성
- `quality`: 결측사유, 매칭상태, 중복과 수동검토 플래그

이 계층은 이름만 같은 사업을 자동 확정하지 않으며, 미매칭 행도 삭제하지 않습니다.

### `fiscal_analytics`

마스터 테이블만 읽어 분석합니다. 일반적인 외부 패키지명과 충돌할 수 있는
`analytics` 대신 `fiscal_analytics`를 사용합니다.

- `features`: 동년도 점검, 환류, 집행설명필요 등 지표
- `ranking`: 비교집단과 복수 가중치 시나리오
- `validation`: 시차, 변수 제거, 민감도, 순위 안정성, 외부 타당성
- `reporting`: 검증된 표·그림·보고서 입력 생성

탐색 코드는 `notebooks/`에 둘 수 있지만, 확정된 계산은 이 패키지로 옮깁니다.

### `fiscal_dashboard`

`data/exports`의 명시된 데이터 계약만 읽습니다. 원본 문서, LLM 응답 또는
정규화 내부 테이블을 직접 읽지 않습니다.

- `app`: BI 런타임
- `charts`: 재사용 가능한 시각화
- `data_contracts`: 필수 열, 타입, 갱신 규칙

대시보드 기술은 데이터 계약 확정 후 Streamlit, Dash, Power BI 등에서 선택합니다.

## 의존 방향

```text
open_fiscal_pipeline ─┐
                      ├→ master_engineering → fiscal_analytics → fiscal_dashboard
performance_pipeline ─┘
```

역방향 import는 허용하지 않습니다. 공통 계약이 필요하면 소비자 패키지에 복사하지
말고, 실제 중복이 확인된 시점에 별도 공통 패키지를 도입합니다.

## 데이터 계층

| 계층 | 용도 | 수정·재생성 정책 |
|---|---|---|
| `data/raw` | PDF/HWP/DOCX, OpenAPI 원본 | 수정·덮어쓰기 금지 |
| `data/interim` | OCR, 페이지 텍스트, LLM 원시 추출 | 원본에서 재생성 가능 |
| `data/processed` | 검증된 정규화·마스터 테이블 | 코드와 설정으로 재생성 |
| `data/analytics` | 피처·통계·순위·검증 결과 | 분석 코드로 재생성 |
| `data/exports` | 대시보드·제출용 계약 산출물 | 승인된 결과에서 생성 |
| `artifacts` | 실행 로그·평가·그림·캐시 | 로컬 전용 |

모든 실제 데이터와 artifacts는 Git에서 제외합니다. 디렉터리 구조와 설명만
저장소에 남깁니다.

## 설정

- `configs/ministries.yaml`: 분석 대상 부처 코드와 이름
- `configs/datasets.yaml`: OpenAPI·로컬 데이터셋 명세
- `configs/llm.yaml`: 환경변수 이름, 프롬프트·스키마 버전, 추출·검토 정책
- `configs/join_keys.yaml`: 마스터 키, 코드 정규화, 단계별 매칭 규칙

API 키와 모델 자격증명은 설정 파일에 쓰지 않고 환경변수로만 전달합니다.

## CLI 전략

현재 운영 명령 `openfiscal`은 기존 OpenAPI 파이프라인에 유지합니다.
`performance_pipeline.cli`와 `master_engineering.cli`는 패키지 경계 확인용으로만
준비했으며, 첫 실제 워크플로가 구현될 때 명령 이름과 입력·출력 계약을 확정한 뒤
`pyproject.toml`에 등록합니다.

## 팀 공유 마일스톤

1. **파이프라인·엔지니어링 통합 시연**: LLM 추출, 검증, 계획·보고 매칭,
   OpenAPI 조인, 마스터 테이블과 미매칭 목록
2. **애널리틱스 데이터 점검**: 모집단, 결측·중복·이상치, 제외 기준, 비교집단
3. **1차 인사이트 공유**: 효과 크기와 표본 수가 확인된 초기 인사이트
4. **분석 검증 리뷰**: T/T+1/T+2, 민감도, 순위 안정성, 채택·폐기 인사이트
5. **BI 프로토타입 피드백**: 탐색 흐름, 필터, 차트, 출처, 다운로드
6. **최종 시연**: 데이터 패키지, 보고서, 대시보드, 재현 절차와 최종 QA
