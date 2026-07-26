# UNKNOWN 예산 80% 커버리지 사람 검수 안내

## 목적

이 검수는 재정수단이 `UNKNOWN`인 대규모 사업을 임의로 자동 분류하지 않고,
공식 근거를 바탕으로 다음 순서로 판단하기 위한 작업입니다.

1. 점검 우선순위 분석 범위에 포함되는 정책사업인가
2. 재정수단 분류를 적용할 수 있는가
3. 적용할 수 있다면 어떤 재정수단인가
4. 해당 사업의 모든 관측연도에 같은 판단이 적용되는가

검수 파일:

```text
data/manual/unknown_priority_fiscal_instrument_review.xlsx
```

## 작성할 시트

### 사업검수

노란색 칸만 입력합니다.

| 컬럼 | 입력 방법 |
|---|---|
| `analysis_scope_status` | `IN_SCOPE`, `OUT_OF_SCOPE`, `REVIEW_REQUIRED` 중 선택 |
| `scope_exclusion_reason` | `OUT_OF_SCOPE`이면 구체적 제외 사유 선택. `IN_SCOPE`이면 비워 둠 |
| `fiscal_instrument_applicability` | `APPLICABLE`, `NOT_APPLICABLE`, `REVIEW_REQUIRED` 중 선택 |
| `fiscal_instrument` | `APPLICABLE`일 때만 재정수단 선택. 적용 불가이면 비워 둠 |
| `all_years_same_classification` | 해당 사업의 모든 관측연도에 동일하면 `YES`, 다르면 `NO`, 확인 중이면 `REVIEW_REQUIRED` |
| `classification_evidence` | 어떤 공식 내용 때문에 해당 판단을 했는지 한두 문장으로 작성 |
| `evidence_source` | 공식 자료명·연도·페이지 또는 URL |
| `confidence` | 직접 근거면 `HIGH`, 복수 간접 근거면 `MEDIUM`, 명칭 중심이면 `LOW` |
| `reviewer` | 검수자 이름 |
| `reviewed_at` | 검수일을 `YYYY-MM-DD`로 입력 |
| `review_status` | 검수 전 `UNREVIEWED`, 진행 중 `IN_PROGRESS`, 완료 `CONFIRMED`, 보류 `REVIEW_REQUIRED` |
| `review_note` | 애매한 점, 추가 확인 대상, 연도별 차이 등을 기록 |

다음 컬럼은 입력하지 않습니다.

```text
comparison_group
ranking_population_impact
input_check
```

검수 반영 단계에서 코드가 계산하는 값입니다.

### 연도별확인

`all_years_same_classification=NO`인 사업만 작성합니다.

- 실제 관측된 연도를 모두 확인하고 `year_review_status=CONFIRMED`로 기록합니다.
- 기본판정과 달라지는 연도에만 범위·제외 사유·적용성·재정수단 override를 입력합니다.
- 적어도 한 연도에는 실제 변경값이 있어야 합니다.
- 연도별 판단이 달라진 근거와 출처를 함께 기록합니다.

## 판단 순서

### 1. 분석 범위

다음 성격이 공식 근거로 확인되면 재정수단보다 범위 판단을 먼저 합니다.

- 회계·기금 간 내부거래 또는 전출
- 국채·주식·예치 등 금융자산 운용
- 차입금·원금 상환
- 여유자금·잉여금 운용
- 정책사업 순위와 성격이 다른 행정·관리 항목

예시:

```text
analysis_scope_status = OUT_OF_SCOPE
scope_exclusion_reason = FINANCIAL_ASSET_OPERATION
fiscal_instrument_applicability = NOT_APPLICABLE
fiscal_instrument = 빈칸
```

### 2. 재정수단 적용성

`IN_SCOPE`이라고 해서 반드시 재정수단을 확정할 수 있는 것은 아닙니다.

- 공식 사업설명에서 수단이 명확함: `APPLICABLE`
- 재정수단 분류가 사업 성격에 부적절함: `NOT_APPLICABLE`
- 자료가 부족하거나 복합 수단임: `REVIEW_REQUIRED`

### 3. 재정수단

`APPLICABLE`인 경우에만 `코드값` 시트에서 재정수단을 선택합니다.
명칭 키워드만으로 확정하지 않습니다. 확정할 수 없으면
`fiscal_instrument=UNKNOWN`, `review_status=REVIEW_REQUIRED`로 남깁니다.

### 4. 근거와 확정

`CONFIRMED`에는 최소한 다음이 필요합니다.

```text
범위 판단
재정수단 적용성
연도 동일성
판단 근거
공식 출처
확신도
검수자
검수일
```

## 검증 명령

작성 중 구조와 허용값 확인:

```powershell
fiscal-analytics validate-unknown-priority-review --root .
```

현재 80% 커버리지 대상 모두 완료됐는지 최종 확인:

```powershell
fiscal-analytics validate-unknown-priority-review --root . --require-complete
```

두 번째 명령이 통과하기 전에는 비교집단과 M3 결과를 갱신하지 않습니다.

## 주의

- 생성 명령은 기존 검수 파일을 기본적으로 덮어쓰지 않습니다.
- `--overwrite`는 사용자 입력을 모두 지울 수 있으므로 새로 시작할 때만 사용합니다.
- 검수 완료는 정책적 타당성 판정이 아니라 분석 범위와 비교 가능성 확인입니다.
- 낮은 집행률이나 연말집중 신호를 실패·낭비·삭감 대상으로 해석하지 않습니다.
