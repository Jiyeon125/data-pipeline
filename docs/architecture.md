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
                                  analytics
                         피처·비교집단·순위·민감도
                                      ↓
                              data/analytics
                                      ↓
                              data/exports
                                      ↓
                       대시보드(다부처 MVP)
```

## 코드 경계

### `open_fiscal_pipeline`

기존 OpenAPI 수집과 월별 지출 정규화를 담당합니다. API 응답과 분석 테이블의
경계를 유지하며 다른 분석 패키지를 import하지 않습니다.

### `performance_pipeline`

성과계획서·성과보고서와 사람이 구조화한 성과지표 자료만 다룹니다. 외부 LLM을
호출하지 않는 중기부 파일럿은 다음 단계까지 구현돼 있습니다.

- `ingest`: 문서 목록, 유형 분류, 페이지 분할
- `manual_performance`: 수기 구조화 엑셀을 원본 그대로 읽어 성과지표·
  프로그램-연도 마스터 생성
- `pdf_reconciliation`: 수기 63행과 계획서·보고서 PDF를 대조하고 페이지
  근거와 사람 검수 상태 보존. 별첨에 상세 수치가 없는 부처는 같은 파일명의
  전체 보고서 본문에서 목표·실적·달성률이 모두 있는 표만 보강 근거로 사용
- `analysis_ready_performance`: 원본 수기값을 변경하지 않고, 수기 결측이면서
  PDF 원문 검수가 `CONFIRMED`인 실적·공식 달성률만 별도 분석값으로 채택

LLM 응답은 최종 정답이 아니라 `data/interim/llm_extractions`의 원시 추출값입니다.
문서에 없는 값은 추정하지 않고 `null`과 검토 상태로 남깁니다.

중기부 분석용 성과지표 마스터는
`data/processed/performance/analysis_ready/program_kpi_year_analysis_ready.parquet`
에 생성합니다. 계획 목표와 보고서 개정 목표를 분리하고, 공식 달성률을
재계산값으로 덮어쓰지 않습니다. 일반 산식으로 재현되지 않는 달성률은 원문값을
보존하되 산식 검토 플래그를 남깁니다.

### `master_engineering`

문서 추출값과 OpenAPI 정규화 자료를 결합합니다.

- `build_masters`: 분석 기준 테이블 생성
- `quality`: 결측사유, 매칭상태, 중복과 수동검토 플래그

이 계층은 이름만 같은 사업을 자동 확정하지 않으며, 미매칭 행도 삭제하지 않습니다.

### `analytics`

마스터 테이블만 읽어 동년도 점검, 환류, 집행설명필요 신호, 비교집단,
민감도와 보고서 입력을 생성합니다.

탐색 코드는 `notebooks/`에 둘 수 있지만, 확정된 계산은 이 패키지로 옮깁니다.

- `mss_same_year_budget_check`: 검수 확정 성과지표를 프로그램-연도로 집계하고
  일반회계·특별회계·기금을 분리한 재정 마스터와 결합합니다. 공식 달성률의
  평균·합산은 만들지 않고 산식 비교 적격 지표의 100% 미만·이상 건수만
  프로그램 신호로 사용합니다.
- `mss_priority_scenario_analysis`: 설정된 N개 부처의 결합표와 기존 M3 재정 신호를
  프로그램-연도-회계유형으로 연결해 점검 후보군을 만들고, 균등·성과중심·
  집행중심·재정영향 보정 시나리오의 Spearman 순위상관, 상위 K 중복,
  후보별 전체·부처내 순위 범위를 산출합니다. 전체 또는 부처내 전 시나리오
  Top 5 후보는 부처·프로그램·연도·회계유형 키로 M3 세부사업 재정 신호와
  연결하며, 성과를 세부사업에 귀속하지 않습니다. 최종 복합점수나 정책
  판정은 만들지 않습니다.

### 대시보드

`fiscal_dashboard`는 검증 완료된 분석 산출물과 PDF 대조 산출물만 읽는
Streamlit 소비자입니다. 분석 파이프라인의 정식 다부처 출력은
`data/analytics/multi_ministry_priority_scenarios/`이며, 화면도 이 경로만
읽습니다. `eligible_candidate_project_review_queue.csv`는 순위 적격
프로그램 후보 아래의 모든 세부사업을 재정신호와 예산규모 기준으로
검토할 순서만 제공합니다.
후보 생성·가중치·순위 계산을 화면에 복사하지 않고, 다음 기능만 담당합니다.

- 시작 → 데이터 확인 → 후보 분석 → 기준 비교 → 원문 검수 단계 이동
- 부처·연도·회계유형·점검단계 공통 필터
- 후보별 시나리오 순위 범위
- 시나리오 순위상관과 상위 K 중복
- 후보 구성요소와 근거 상세
- 안정 상위 후보의 세부사업 예산구성·집행·이월·불용 드릴다운
- 데이터 검증 큐 분리
- 선택 프로그램의 성과지표 PDF 검수 연결과 감사 CSV 저장
- 현재 필터 후보표 다운로드

현재 분석 MVP는 고용노동부·보건복지부·중소벤처기업부·
과학기술정보통신부 4개 부처의 2022~2024년 표본입니다. 최종 제출용 데이터
계약이 승인되면 입력 경로만 `data/exports` 계약으로 교체하고 화면의 분석
정의는 늘리지 않습니다.

## 의존 방향

```text
open_fiscal_pipeline ─┐
                      ├→ master_engineering → analytics → fiscal_dashboard
performance_pipeline ─┘                          ↓
                                           data/exports(승인 후)
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
- `configs/priority_scenarios.yaml`: 다부처 분석범위·시나리오·임계값

API 키와 모델 자격증명은 설정 파일에 쓰지 않고 환경변수로만 전달합니다.

## CLI 전략

운영 명령 `openfiscal`은 OpenAPI 수집·정규화를 담당하고, `fiscal-master`는
검증된 정규화 결과로 분석 기준 테이블을 만듭니다. 현재 구현된 경계는 다음과
같습니다.

- `openfiscal collect-budget-all`: 예산 API 원본 일괄 수집
- `openfiscal normalize-budget`: 예산 레코드·금액 이벤트 정규화와 코드 매칭
- `fiscal-master build-project-year-budget`: 예산 기준 사업-연도 중간 테이블 구축
- `fiscal-master build-project-year-financial`: 월별 집행 외부 결합

외부 LLM을 사용하지 않는 성과자료 명령은 다음과 같습니다.

- `fiscal-performance normalize-manual`
- `fiscal-performance build-verified-manual-analysis-ready`
- `fiscal-performance prepare-program-match-review`
- `fiscal-performance reconcile-ministry-performance-pdfs <019|075|162> --overwrite`
- `fiscal-performance reconcile-mss-performance-pdfs`
- `fiscal-performance build-mss-analysis-ready`
- `fiscal-analytics analyze-mss-same-year-budget --root . --overwrite`
- `fiscal-analytics analyze-manual-same-year-budget`
- `fiscal-analytics analyze-mss-priority-scenarios --root . --overwrite`
- `fiscal-analytics analyze-priority-scenarios --root . --overwrite`

이 명령들은 OpenAI API 키 없이 로컬 파일만으로 실행합니다. 수기 골드셋 경로는
보고서 최종 목표가 없으면 계획 목표로 대체하지 않고 결측으로 유지합니다. 향후 LLM 추출
명령은 사용자가 외부 호출을 명시적으로 허용한 뒤 별도 경계로 추가합니다.
예산 기준 중간 테이블은 결산·성과 자료가 결합되기 전에는 최종 마스터로
간주하지 않습니다.

## 팀 공유 마일스톤

1. **파이프라인·엔지니어링 통합 시연**: LLM 추출, 검증, 계획·보고 매칭,
   OpenAPI 조인, 마스터 테이블과 미매칭 목록
2. **애널리틱스 데이터 점검**: 모집단, 결측·중복·이상치, 제외 기준, 비교집단
3. **1차 인사이트 공유**: 효과 크기와 표본 수가 확인된 초기 인사이트
4. **분석 검증 리뷰**: T/T+1/T+2, 민감도, 순위 안정성, 채택·폐기 인사이트
5. **BI 프로토타입 피드백**: 탐색 흐름, 필터, 차트, 출처, 다운로드
6. **최종 시연**: 데이터 패키지, 보고서, 대시보드, 재현 절차와 최종 QA
