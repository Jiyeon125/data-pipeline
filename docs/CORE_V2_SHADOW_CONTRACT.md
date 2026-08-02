# core_v2 shadow 데이터 계약

## 결론

승인된 A안인 `정규화 Parquet Core + Presentation export`의 첫 shadow batch를
구현했습니다. 현재 대시보드·점수·수기판정·공개 CSV는 변경하지 않았습니다.

이 batch는 기존 `project_year_financial_v2.parquet`의 4개 부처·2022~2024년
6,076행을 entity, year version, account/fund, amount fact, evidence, legacy crosswalk로
분해합니다. legacy 집계행에서 시작한 shadow이므로 raw source fact를 대체하지는
않습니다.

## 실행

```powershell
.venv\Scripts\fiscal-master.exe build-core-v2-shadow --overwrite
```

기본 출력은 `data/processed/core_v2_shadow/`이며 모두 Git 제외 대상입니다.

## ID 계약

| ID | 의미 | 생성 기준 |
|---|---|---|
| `source_observation_id` | legacy project-year-account 관측 | 기존 `project_id` |
| `project_entity_id` | 연도·회계와 분리된 사업 정체성 | 완전 공식 계층코드 |
| provisional `project_entity_id` | 영속 정체성을 확정할 수 없는 관측 | source observation |
| `project_version_id` | 사업 정체성×회계연도 | entity ID·회계연도 |
| `program_entity_id` | 연도와 분리된 프로그램 정체성 | 부처·공식 프로그램코드 |
| `program_version_id` | 프로그램×회계연도 | program entity·회계연도 |
| `account_or_fund_id` | 부처×회계/기금 코드×회계유형 | 공식 회계 맥락 |

이름은 ID 생성에 사용하지 않습니다. 코드가 불완전한 행은 이름 해시로 영속 ID를
만들지 않고 source-bound provisional ID와 resolution case로 남깁니다. 기존
`project_id`와 `classification_project_id`는 crosswalk에서 보존합니다.

## 테이블과 grain

| 테이블 | 한 행의 기준 | 실제 행 수 |
|---|---|---:|
| `source_observation` | legacy project-year-account 관측 | 6,076 |
| `program_entity` | 프로그램 정체성 | 789 |
| `program_version` | 프로그램 정체성×회계연도 | 1,016 |
| `project_entity` | persistent 또는 provisional 사업 정체성 | 2,722 |
| `project_version` | 사업 정체성×회계연도 | 5,970 |
| `hierarchy_assignment` | project version×program version | 5,970 |
| `account_or_fund` | 부처×회계/기금 코드×회계유형 | 714 |
| `budget_fact` | source observation×예산 금액유형 | 10,874 |
| `execution_fact` | source observation×연간 결산지출 | 5,408 |
| `evidence_link` | target 값×source observation | 34,510 |
| `legacy_id_crosswalk` | legacy ID×새 ID 관계 | 14,945 |
| `identity_resolution_case` | provisional 사업 정체성 | 673 |

`schema_contract.csv`는 각 테이블의 grain·PK·FK·품질 gate를,
`manifest.json`은 입력·출력 해시·행 수·금액·검사 결과를 보존합니다.

## 명칭 충돌 처리

같은 공식 사업 코드와 연도에 여러 회계 행이 있는 version 묶음은 102개이고, 이 중
73개는 회계별 명칭이 다릅니다. 회계를 ID에 넣어 사업을 쪼개지 않았으며, 충돌한
명칭 하나도 임의로 선택하지 않았습니다.

- 한 가지 명칭만 관측: `SINGLE_SOURCE_NAME`
- 둘 이상 관측: canonical name은 null, `CONFLICTING_SOURCE_NAMES`
- 모든 원명칭: `source_observation`과 `evidence_link`에 보존

프로그램 성과는 향후 `program_version`에 연결하며 세부사업 성과로 귀속하지
않습니다.

## 금액과 분석 적격성

모든 금액은 섞지 않고 원본 파생 필드별 fact로 분리합니다.

| 범위 | 본예산 | 예산현액 | 결산지출 |
|---|---:|---:|---:|
| 전체 보존값 | 1,070,560,075,800,000 | 1,072,788,061,952,827 | 2,847,850,164,330,652 |
| 현재 변수별 분석 적격값 | 579,852,316,600,000 | 582,636,603,687,359 | 537,016,045,696,669 |

전체 결산지출이 큰 이유는 shadow 중복이 아니라 분석 범위에서 제외된 내부거래,
여유자금·금융자산 운용 등의 지출 2,276,492,680,318,696원이 보존돼 있기 때문입니다.
행은 삭제하지 않고 다음 값을 fact에 함께 둡니다.

- `in_core_financial_population`
- `budget_analysis_eligible`
- `execution_analysis_eligible`
- `settlement_analysis_eligible`
- `analysis_eligible`
- `exclusion_reason`
- `quality_issue_reasons`
- `amount_source`

따라서 전체 재정구조에는 모든 값을 사용할 수 있지만 집행·순위 분석은
`analysis_eligible=true`인 해당 금액유형만 사용해야 합니다.

## 품질검증 결과

- source 6,076행 보존
- 모든 테이블 PK 중복 0
- project/program/account/evidence FK 누락 0
- 금액유형별 합계 차이 0원
- 2025년 관측 0행, cutoff 2024 준수
- 기존 완전 공백 ID 충돌 10행을 10개 provisional ID로 분리
- persistent 사업 entity 2,049개, provisional 673개
- legacy one-to-many 관계 20개 legacy ID에서 명시적으로 관측
- 13개 데이터·계약 파일을 두 번 생성한 SHA-256 일치

## 현재 사용할 수 있는 범위

사용 가능:

- ID·회계·금액 grain의 shadow 검증
- 기존 ID와 새 ID crosswalk 확인
- 전체 구조와 변수별 분석 적격 금액 분리
- 다음 성과·월별집행·분류 assertion batch의 FK 기준

아직 사용 불가:

- 대시보드 입력 대체
- 최종 순위·점수 재산출
- provisional entity의 연도간 추세
- raw 예산 source record를 대체하는 canonical fact
- 프로그램 성과와 월별 집행 연결

## 롤백

현재 소비자는 `data/processed/core_v2_shadow/`를 읽지 않습니다. 실패 시 별도
설정 전환 없이 기존 `data/processed/masters`와 `data/analytics` 경로를 계속
사용하면 됩니다. shadow 출력 삭제나 legacy contraction은 승인 전 수행하지
않습니다.

다음 batch에서도 기존 출력과 새 출력을 병행 생성하고, 행 수·금액·ID·evidence
연결을 대조한 뒤에만 Presentation dual-read를 검토합니다.
