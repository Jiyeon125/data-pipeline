# 전면 구조개선 Gate B 미니 PT

> 상태: A안과 영속 entity·연도 version·source provisional·legacy crosswalk ID
> 정책을 사용자 승인받았습니다. 기존 공개 스키마와 대시보드 의미는 아직 변경하지
> 않았습니다.

## 1. 현재 문제

현재 파이프라인은 실행되지 않는 구조가 아닙니다. Parquet·CSV와 CLI로 재현되며
대시보드 응답도 빠릅니다. 문제는 저장 엔진보다 다음 네 가지입니다.

1. 연도를 포함한 `project_id`를 영속 사업 ID처럼 사용합니다.
2. 성과, 예산, 집행, 회계의 서로 다른 grain이 wide table과 bridge에서 반복됩니다.
3. 기준연도와 T+1·T+2 결과연도가 분리되지 않아 2025년 결과가 과거 분석에
   노출됩니다.
4. 회계·재원, 재정지원방식, 사업특성이 한 축에 섞여 UNKNOWN과 잘못된 비교집단을
   만듭니다.

따라서 “DB로 바꾸기”가 아니라 먼저 논리 모델과 ID·시간 계약을 고쳐야 합니다.

## 2. 확인한 데이터와 코드 근거

### 현재 성능

동일 Windows `.venv`에서 실데이터로 측정했습니다. 시간은 단일 장비 관측값이므로
절대 성능 보장치가 아니라 대안 비교 기준선입니다.

| 작업 | 대상 | 시간 중앙값 또는 1회 | Python peak |
|---|---|---:|---:|
| core Parquet 읽기 | 6,130행×146열 | 0.080초 | 12.7MB |
| M3 feature Parquet 읽기 | 6,118행×239열 | 0.100초 | 14.3MB |
| 후보 CSV 읽기 | 412행×155열 | 0.020초 | 1.9MB |
| 대시보드 데이터 계약 전체 로드 | 13개 CSV·JSON | 0.202초 | 7.5MB |
| 중기부 2024 후보 필터·정렬 | 20행 결과 | 0.0027초 | 0.12MB |
| PDF 검수 큐 | 361행×83열 | 캐시 후 0.0078초 | 2.5MB |
| Streamlit AppTest 첫 렌더 | 전체 첫 화면 | 6.74초 | 96.9MB |

첫 렌더 지연은 파일 조회보다 Streamlit 실행·렌더링 쪽입니다. 현재 자료량에서
DuckDB를 추가해도 0.20초 데이터 로딩을 크게 줄이는 것은 사용자 체감 개선으로
이어지기 어렵습니다.

### 재산출 시간

운영 산출물과 분리된 `artifacts/refactor/gate_b/shadow/`에 재실행했습니다.

| 단계 | 시간 |
|---|---:|
| 사업 분류·모집단 생성 | 8.71초 |
| 모집단 민감도 | 1.50초 |
| 사업 연속성·재정 파생·프로그램 집계 | 64.27초 |
| ranking population v2 | 1.51초 |
| 합계 | 75.98초 |
| 우선순위 시나리오 재산출 | 7.50초 |

핵심 4단계 시간의 84.6%가 `project_continuity.py`에 집중됩니다. 현재 병목은 저장
조회가 아니라 Python 변환 로직입니다.

### 규모와 확장

- 4부처×3년 기준 project-year 6,076행입니다.
- 현재 전체 처리물은 이미 5부처×4년, project-year 9,366행입니다.
- 50부처×10년을 단순 선형 가정해도 project-year 약 25.3만행, 월별 집행 약
  275만행 수준입니다. Parquet·pandas로 처리 가능한 범위입니다.
- 원본 PDF는 전체본 38개와 분리본을 포함해 66개·14,504쪽입니다.
- 저장공간 2.72GB 중 `data/interim`이 2.02GB·11,252파일입니다. 향후 실제 병목은
  정형 fact 조회보다 PDF/OCR 중간물의 증분 처리와 보존 정책입니다.

### 식별자·회계 근거

- 4부처×3년 6,076행 중 계층 코드를 모두 가진 행은 5,403행, 하나 이상 없는 행은
  673행입니다.
- 완전한 공식 계층 코드키 2,049개 중 1,777개가 여러 해에 관측되고, 143개는 같은
  코드키에서 명칭이 바뀝니다. 이름 해시는 영속 ID로 부적합합니다.
- 코드와 이름이 모두 비어 있는 10행이 현재 하나의 분류 ID로 충돌합니다.
- 공식 코드 기준 동일 사업이 여러 계정코드에 나타나는 경우가 67개, 여러
  회계유형에 나타나는 경우가 63개입니다. 회계는 사업 ID의 일부가 아니라 별도
  fact 맥락이어야 합니다.
- 재정수단 UNKNOWN은 3,185 사업-연도행·1,375 분류 ID입니다. UNKNOWN끼리 상대
  순위를 매기기보다 속성 단위 미확정으로 보존해야 합니다.
- 사람 검수는 PDF 큐 361행 중 29행이 필수이며, 재정수단은 예산 커버리지 순으로
  검수 범위를 줄여야 합니다.

### 유지보수 근거

2,000행을 넘는 주요 모듈이 4개이며, 대시보드도 1,936행입니다. 현재 merge와
재실행 위험은 데이터 파일 형식보다 `pdf_reconciliation.py`,
`m3_financial_signals.py`, `mss_priority_scenario_analysis.py`,
`analysis_policy_decision_support.py`, `app.py`의 책임 집중에서 큽니다.

## 3. 선택지 A/B/C

### A. 정규화 Parquet Core + Presentation export

```text
Raw/Manual → Normalized Parquet → Core fact/entity Parquet
           → Feature/Analysis Parquet → Dashboard CSV/Parquet export
```

- 현재 pandas·PyArrow·Streamlit을 그대로 사용합니다.
- 작은 정규화 테이블, schema contract, manifest, crosswalk를 추가합니다.
- 대시보드는 검증된 wide presentation export만 읽습니다.
- 수기 입력은 사람이 편집 가능한 Excel/CSV를 source-of-truth로 유지하고 Parquet로
  정규화합니다.

장점: 가장 빠른 shadow 이행, 롤백 쉬움, 새 의존성 없음, 현 대시보드 유지.

단점: 외래키를 저장 엔진이 강제하지 않으므로 계약 테스트가 필수이며, 동시 편집에는
적합하지 않습니다.

### B. SQLite 관계형 Core

```text
Raw/Manual → SQLite normalized/core/review tables
           → SQL view → Parquet/CSV presentation export
```

- Python 표준 라이브러리 SQLite로 entity·fact·review·lineage를 관리합니다.
- 트랜잭션과 외래키로 무결성을 강제합니다.

장점: 관계·검토 이력·증분 upsert가 명확하고 새 패키지가 필요 없습니다.

단점: 기존 pandas 파이프라인을 대폭 바꿔야 하고, 단일 DB 파일 충돌로 Git 협업이 더
나빠질 수 있으며, Streamlit 쓰기와 다중 사용자 운영에는 결국 서버 DB가 필요합니다.

### C. Parquet 저장 + DuckDB query 계층

```text
Raw/Manual → versioned Parquet facts
           → DuckDB views/query → presentation export
```

- Parquet는 그대로 두고 조인·집계를 DuckDB SQL view로 제공합니다.
- 대용량 분석과 ad-hoc query를 빠르게 확장할 수 있습니다.

장점: Parquet 재현성과 SQL 분석 성능을 함께 얻고 파일 복사 없이 조회할 수 있습니다.

단점: 현재 설치되지 않은 의존성·SQL 계층·배포 절차가 추가됩니다. DuckDB view만으로
영속 ID와 수기검토 무결성이 해결되지는 않으며, 현재 0.20초 로딩에서는 성능 이득이
작습니다.

## 4. 의사결정 매트릭스

마스터 지시서의 가중치를 그대로 사용했습니다. 현재는 정확성·유지보수·롤백이 모두
중요해 임의로 바꿀 근거가 부족합니다. 점수는 1~5점입니다.

| 평가 기준 | 가중치 | A Parquet | B SQLite | C Parquet+DuckDB |
|---|---:|---:|---:|---:|
| 데이터 의미·grain·조인 안전성 | 20 | 4 | 5 | 4 |
| 팀 이해·유지보수 | 15 | 5 | 3 | 3 |
| 마이그레이션·롤백 | 15 | 5 | 3 | 4 |
| 증분·재현성·lineage | 15 | 4 | 5 | 4 |
| Streamlit·기존 분석 연동 | 10 | 5 | 3 | 4 |
| 구현·운영 복잡도 | 10 | 5 | 3 | 3 |
| 테스트·품질검증 | 5 | 4 | 5 | 4 |
| 성능·증가 대응 | 5 | 4 | 3 | 5 |
| 새 의존성·배포 부담 | 5 | 5 | 5 | 2 |
| 가중평균 | 100 | **4.55** | **3.90** | **3.70** |

점수보다 중요한 탈락 사유는 다음과 같습니다.

- B는 현재 Git·단일 분석자 작업에서 binary DB가 협업과 롤백을 악화시킵니다.
- C는 측정된 조회 병목이 없는데 새 의존성과 SQL 이중 경로를 만듭니다.
- A는 저장 엔진 무결성은 없지만, shadow 계약 테스트로 현재 P0를 해결할 수 있고
  가장 작은 blast radius를 가집니다.

## 5. 권장 목표 논리 모델

물리 저장 방식과 무관하게 다음 계약은 유지합니다. 한 개의 wide Core가 아니라
관계별 최소 테이블을 두고, 대시보드용 wide view는 마지막에 생성합니다.

| 엔터티 | 한 행의 의미 | 핵심 연결 |
|---|---|---|
| `source_document` | 원본 파일 1개 | hash·문서종류·발행일·대상연도 |
| `source_observation` | 원본의 표/행/셀 관측 1개 | document·페이지·원문·추출방식 |
| `program_entity` | 연도와 무관한 프로그램 정체성 1개 | 영속 ID·공식코드 alias |
| `program_version` | 프로그램×회계연도 버전 1개 | 명칭·계층·effective date |
| `project_entity` | 연도와 무관한 세부사업 정체성 1개 | 영속 ID·resolution 상태 |
| `project_version` | 세부사업×회계연도 버전 1개 | 명칭·관측경계·entity FK |
| `hierarchy_assignment` | project version과 program version 관계 1개 | 이관·분할·통합 관계 보존 |
| `account_or_fund` | 공식 회계·기금 코드 1개 | 회계유형·재원 속성 |
| `budget_fact` | source record×금액유형 1개 | project version·회계·편성단계 |
| `execution_fact` | source record×집행월×금액유형 1개 | 누계/단월·분모 출처 분리 |
| `performance_indicator` | 프로그램 성과지표 정체성 1개 | 프로그램 수준, 세부사업에 귀속 금지 |
| `performance_measure` | 지표×대상연도×측정유형 1개 | 목표·실적·달성률 분리 |
| `classification_assertion` | 대상×분류축×값 1개 | 지원방식·사업특성·상태·근거 |
| `review_decision` | 판정 변경 이벤트 1개 | 자동 후보와 사람 확정 분리 |
| `evidence` | 대상 필드와 원문 위치 연결 1개 | observation·rule·review FK |
| `legacy_id_crosswalk` | 구 ID와 새 ID의 매핑 1개 | 1:1·1:N·N:1·미확정 상태 |
| `pipeline_run` / `artifact_manifest` | 실행과 산출물 버전 1개 | cutoff·코드버전·입출력 hash |

## 6. 권장 ID·시간·재정 계약

### ID

- `project_entity_id`: 한 번 발급해 mapping에 저장하는 비의미 영속 ID입니다.
- 공식 코드는 ID 자체가 아니라 유효기간을 가진 alias로 연결합니다.
- `project_version_id`: entity×회계연도 버전이며 source observation과 분리합니다.
- 코드·이름이 불완전하면 `source_observation_id` 기반 provisional ID를 쓰고 영속
  entity로 자동 승격하지 않습니다.
- 기존 `project_id`, `classification_project_id`, `candidate_id`는 crosswalk로
  보존합니다.

공식 코드만 영속 ID로 쓰지 않는 이유는 같은 코드에서 명칭 변경 143건이 있고,
향후 코드 변경·분할·통합을 별도 관계로 표현해야 하기 때문입니다.

### 시간

`fiscal_year`, `document_target_year`, `document_published_at`,
`performance_plan_year`, `performance_report_year`, `execution_month`,
`observed_at`, `available_at`, `analysis_cutoff`을 구분합니다.

과거 재현은 `available_at <= analysis_cutoff`인 관측만 허용하고 T+1·T+2는
`feedback_base_year`, `feedback_budget_year`, `feedback_horizon`으로 분리합니다.

### 회계·재원·분류

- 사업 정체성과 회계·기금을 분리합니다. 복수 회계 사업 63개를 한 사업으로
  유지하되 fact마다 회계 FK를 둡니다.
- 본예산·추경·현액은 `appropriation_stage`, 예산·집행·불용 등은 `amount_type`으로
  나눕니다.
- 재정지원방식과 사업특성은 서로 다른 `classification_dimension`으로 저장합니다.
- 값, 판정상태, 검토상태, 근거상태, 분석적격을 각각 분리합니다.

## 7. 권장안과 마이그레이션 영향

권장안은 **A: 정규화 Parquet Core + Presentation export**입니다.

```text
Gate A snapshot
  → 기존 경로 P0 오류 회귀테스트·수정
  → core_v2 shadow 생성
  → legacy/new crosswalk와 금액·행·근거 reconciliation
  → presentation_v2 병행 생성
  → 설정 포인터로 대시보드 dual-read 검증
  → 승인 후 switch
  → 안정화 뒤에만 legacy contract 검토
```

- 기존 `data/raw`, `data/manual`, 현재 마스터와 대시보드 입력은 그대로 둡니다.
- 새 Core는 별도 version 경로에 생성하고 금액 합계·행 수·ID 매핑·근거 연결을
  매 실행 비교합니다.
- 전환 실패 시 presentation 포인터를 기존 경로로 되돌립니다.
- legacy 삭제와 공개 CSV 변경은 별도 승인 전 하지 않습니다.

가장 큰 단점은 외래키가 엔진에서 강제되지 않는다는 점입니다. 모든 Core 테이블에
grain·PK·FK·허용중복·금액보존 계약 테스트를 두고, 한 건이라도 실패하면 export를
막는 것으로 완화합니다.

### 재검토 조건

- core fact 100만행 이상이 되고 측정된 주요 query 중앙값이 1초를 넘을 때:
  DuckDB query 계층(C)을 재검토합니다.
- 여러 사용자가 대시보드에서 동시에 검수·수정해야 하거나 React 쓰기 API를 만들
  때: SQLite가 아니라 서버형 DB를 포함한 B를 재검토합니다.
- Parquet 계약 테스트로 FK·증분 갱신 오류를 반복적으로 막지 못할 때:
  관계형 Core를 재검토합니다.

## 8. 사용자께 필요한 결정 한 가지

**A안과 위 ID 정책을 기준으로 `core_v2` shadow 구현을 시작해도 되는지** 결정이
필요합니다. 승인 전에는 현재 점수·수기판정·공개 CSV·대시보드 의미를 바꾸지 않고,
P0 회귀테스트와 되돌릴 수 있는 shadow 계약만 준비합니다.
