# Codex 작업 인수인계

최종 갱신: 2026-07-27 KST

## 현재 목적과 상태

금융거래성 비정책 행의 범위 누락과 기존 고정 행 수를 바로잡고, 영향받는
모집단·M2·M3·의사결정 지원·방법론 감사 결과를 멘토링 기준으로 재생성했습니다.
코드 수정과 자동 검증은 완료됐고, 다음 병목은 UNKNOWN 본예산 80% 커버리지
18개 사업의 사람 검수입니다.

재현 경로 정리도 완료했습니다. 호출되지 않는 빈 패키지 뼈대와 월별 CSV
중복본을 제거했고, 실제 분석 패키지명은 `analytics`로 문서와 구조 테스트를
일치시켰습니다. 원본·수기검수·현재 M2/M3 결과는 보존했습니다.

## 발견한 원인

- 기존 제외 규칙에 채권·주식·금융기관 예치가 명시돼 있지 않았습니다.
- 제외 규칙이 둘 이상 적중하면 같은 제외 방향임에도 “충돌”로 처리해 분석에
  다시 포함했습니다.
- 구조화 사업비 분류가 비어 있는 행정 인건비·기본경비는 명칭 보완 규칙이
  없어 core에 남았습니다.
- M3·의사결정 지원·M2 검증에 기존 모집단 행 수 6,290이 하드코딩돼 있었습니다.
- M2 월별 정의 검증에 과거 적격 3,328행·제외 2,962행이 하드코딩돼 있었습니다.
- M3 층화 그룹화가 결측 범주에서 실패했고, M2 Spearman 계산이 선언되지 않은
  SciPy에 의존했습니다.
- 기존 UNKNOWN 16개 검수표는 잘못된 범위 모집단에서 만들어졌습니다.

## 현재까지 반영한 수정

- `FINANCIAL_ASSET_OPERATION` 규칙에 국채·채권매입, 주식매입,
  통화·비통화 금융기관예치를 추가했습니다.
- 복수 제외 규칙 적중은 `MULTIPLE_SCOPE_EXCLUSIONS`로 제외합니다.
- 구조화 분류가 빈 행의 `소속기관인건비`·`본부 기본경비`만 좁게 보완하고,
  정책지원 성격의 인건비 사업은 유지했습니다.
- 범위 제외는 2,057행에서 2,240행으로 183행 증가했습니다.
- 전체 원천 9,366행과 원본 금액은 변경하지 않았습니다.
- broad/core/ranking v2는 각각 6,177/6,130/6,130행입니다.
- M2·M3·M2 정의 검증·의사결정 지원·M3 방법론 감사를 새 모집단으로
  재생성했습니다.
- 현재 core에 같은 범위 제외 함수를 재적용한 결과 누출은 0행입니다.
- 90% 미만 예산현액 비중은 현재 범위 9.7%, 보통교부세 제외 민감도
  4.6%이며 국채·채권매입은 M3에 0행입니다.
- UNKNOWN 본예산 80% 커버리지 대상은 16개가 아니라 18개로 바뀌었습니다.
- 새 검수표는 실제 관측연도 66행만 포함하도록 동적으로 변경했습니다.
- 방법론은 `docs/ANALYSIS_DECISIONS.md`에 잠정 분석정책으로 기록했습니다.

## 사용자 입력 보존

- 기존 파일 `data/manual/unknown_top16_fiscal_instrument_review.xlsx`는
  삭제하거나 덮어쓰지 않았습니다.
- 기존 16개 중 8개는 새 우선목록과 겹치고, 8개는 새 범위 규칙으로 제외됐습니다.
- 새 파일 `data/manual/unknown_priority_fiscal_instrument_review.xlsx`을 생성했고,
  겹치는 8개 사업의 기존 입력 14개 셀을 이관했습니다.
- 기존 목록에서 빠진 `회계기금간거래(전출금)=IN_SCOPE` 입력은 사용자 판단
  이력으로 기존 파일에 남겼지만, 멘토링 자동 범위에서는 전출금으로 제외했습니다.
- 새 워크북은 18개·66행, 구조 오류 0건, 드롭다운 12개, 수식 오류 0건,
  선행 0 보존으로 검증했습니다. 5개 시트의 Excel 렌더링도 확인했습니다.
- 현재 사람 검수 확정은 0개이므로 상태는 `INCOMPLETE`입니다.

## 2026-07-27 저장소 정리와 실행환경

- Python 3.13 기반 실행파일이 사라져 `.venv`, CLI와 작업 트래커 훅이
  실행되지 않던 상태였습니다. 사용자 Python 3.13.14를 복구했고
  `.venv\Scripts\python.exe`, 주요 의존성 import, 트래커 `sync`를
  확인했습니다.
- 실행 기능이 없는 `src/fiscal_analytics`, `src/fiscal_dashboard`,
  빈 `clean/join/extract/prompts/validate` 뼈대와 빈 노트북 분류 폴더를
  삭제했습니다.
- 후속 코드가 읽지 않는 월별 CSV 중복본 5개와 접근 가능한 테스트·Python
  캐시를 포함해 117.00 MiB를 삭제했습니다. 월별 Parquet은 유지했습니다.
- 샌드박스 ACL 때문에 일반 권한에서 삭제가 거부됐던 과거 `.pytest_*`
  폴더 23개도 Windows UAC 승인 후 정확한 경로로 삭제했습니다. 현재 루트의
  `.pytest_*` 잔존 수는 0개입니다.
- 정리 후 핵심 모집단을 실제 재실행해 원천 9,366행, 일반 모집단 6,107행,
  제외 3,259행, core/ranking v2 6,130행, 금액 변경 0을 재확인했습니다.
- Ruff와 전체 pytest 122개, M2 정의 검증이 통과했습니다.

## 남은 작업

1. 사용자가 새 워크북의 `사업검수` 18행을 공식 근거와 함께 작성합니다.
2. `all_years_same_classification=NO`인 사업만 `연도별확인`을 작성합니다.
3. 다음 명령이 `PASS`할 때까지 비교집단·M3를 갱신하지 않습니다.

```powershell
fiscal-analytics validate-unknown-priority-review --root . --require-complete
```

4. 검수 완료 뒤 오버레이 반영 경로를 구현하거나 확인하고, 분류 커버리지,
   비교집단 표본 수, 신뢰도 등급, 하위 10%·20%, 80~90% 금액비중,
   대규모 사업 민감도와 관련 M3 표만 최소 재실행합니다.
5. 잠정 분석정책은 실제 검수 결과와 팀 피드백이 생긴 뒤에만 수정합니다.

## 주요 재실행 명령

```powershell
.venv\Scripts\python.exe -m master_engineering.cli build-project-analysis-population --overwrite
.venv\Scripts\python.exe -m master_engineering.cli analyze-population-sensitivity --overwrite
.venv\Scripts\python.exe -m master_engineering.cli build-project-continuity --overwrite
.venv\Scripts\python.exe -m master_engineering.cli build-ranking-population-v2 --overwrite
.venv\Scripts\python.exe -m analytics.cli build-m2-data-review --root .
.venv\Scripts\python.exe -m analytics.cli validate-m2-definitions --root .
.venv\Scripts\python.exe -m analytics.cli build-m3-financial-signals --root .
.venv\Scripts\python.exe -m analytics.cli build-analysis-policy-decision-support --root .
.venv\Scripts\python.exe -m analytics.cli audit-m3-methodology --root .
.venv\Scripts\python.exe -m analytics.cli validate-unknown-priority-review --root .
```

## 현재 완료로 처리하지 않은 작업

- `classification.unknown-priority-manual-review`
- `analysis.m3-minimal-review-refresh`
- `deliver.provisional-analysis-policy`

범위 감사와 동적 검수표 준비는 완료 처리했습니다. 위 세 항목은 실제 18개 사람
검수, 검수값 반영, 팀 피드백이 각각 끝나기 전에는 완료 처리하지 않습니다.

## 최종 자동 검증

- 원천 9,366행, 금액 변경 0, 기본키 중복 0
- core/ranking v2/M3 6,130행
- 범위 규칙 누출 0행
- Ruff 전체 통과
- pytest 122 passed
- M2 정의 검증·의사결정 지원·M3 방법론 감사 `PASS`
