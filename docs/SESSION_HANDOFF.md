# Codex 작업 인수인계

최종 갱신: 2026-07-27 KST

## 현재 목적

멘토링 기준에 맞지 않게 분석 모집단에 남아 있던 내부거래·여유자금운용·
금융자산 운용·원금상환 등을 바로잡고, 영향받는 M2·M3·의사결정 지원
산출물을 재검증합니다. 이후 현재 결과물 전체를 멘토링 기준과 대조합니다.

## 발견한 원인

- 기존 제외 규칙에 채권·주식·금융기관 예치가 명시돼 있지 않았습니다.
- 제외 규칙이 둘 이상 적중하면 같은 제외 방향임에도 “충돌”로 처리해 분석에
  다시 포함했습니다.
- M3·의사결정 지원·M2 검증에 기존 모집단 행 수 6,290이 하드코딩돼 있었습니다.
- M3 층화 그룹화가 결측 범주에서 실패했고, M2 Spearman 계산이 선언되지 않은
  SciPy에 의존했습니다.
- 기존 UNKNOWN 16개 검수표는 잘못된 범위 모집단에서 만들어졌습니다.

## 현재까지 반영한 수정

- `FINANCIAL_ASSET_OPERATION` 규칙에 국채·채권매입, 주식매입,
  금융기관예치를 추가했습니다.
- 복수 제외 규칙 적중은 `MULTIPLE_SCOPE_EXCLUSIONS`로 제외합니다.
- 범위 제외는 2,057행에서 2,236행으로 179행 증가했습니다.
- 전체 원천 9,366행과 원본 금액은 변경하지 않았습니다.
- broad/core/ranking v2는 각각 6,181/6,134/6,134행으로 갱신했습니다.
- M2와 M3는 새 모집단으로 재생성했습니다.
- UNKNOWN 본예산 80% 커버리지 대상은 16개가 아니라 18개로 바뀌었습니다.
- 새 검수표는 실제 관측연도만 포함하도록 동적으로 변경했습니다.

## 사용자 입력 보존

- 기존 파일 `data/manual/unknown_top16_fiscal_instrument_review.xlsx`는
  삭제하거나 덮어쓰지 않았습니다.
- 기존 16개 중 8개는 새 우선목록과 겹치고, 8개는 새 범위 규칙으로 제외됐습니다.
- 새 파일 `data/manual/unknown_priority_fiscal_instrument_review.xlsx`을 생성했고,
  겹치는 8개 사업의 기존 입력 14개 셀을 이관했습니다.
- 새 워크북 검증과 시각 검수는 아직 완료 전입니다.

## 남은 작업

1. 새 18개 검수표의 행·사업·관측연도·이관값·드롭다운을 검증합니다.
2. 기존 입력 중 `회계기금간거래(전출금)=IN_SCOPE` 1건은 멘토링 기준과
   충돌하므로 사용자 판단 이력은 보존하되 자동 범위에서는 제외한 사실을 기록합니다.
3. 멘토링 기준과 코드·M2·M3·의사결정 지원·방법론 감사 문서를 전수 대조합니다.
4. 남은 하드코딩·과장 표현·부적절한 모집단 사용을 수정합니다.
5. 전체 pytest, Ruff, 입력 해시·행 수·금액 보존을 검증합니다.
6. `docs/WORK_LOG.md`와 작업 트래커를 갱신합니다.

## 주요 재실행 명령

```powershell
python -m master_engineering.cli build-project-analysis-population --overwrite
python -m master_engineering.cli analyze-population-sensitivity --overwrite
python -m master_engineering.cli build-project-continuity --overwrite
python -m master_engineering.cli build-ranking-population-v2 --overwrite
python -m analytics.cli build-m2-data-review --root .
python -m analytics.cli build-m3-financial-signals --root .
python -m analytics.cli build-analysis-policy-decision-support --root .
python -m analytics.cli audit-m3-methodology --root .
python -m analytics.cli validate-unknown-priority-review --root .
```

## 현재 완료로 처리하지 않은 작업

- `quality.financial-transaction-scope-audit`
- `classification.unknown-top16-manual-review`
- `analysis.m3-minimal-review-refresh`
- `deliver.provisional-analysis-policy`

실제 18개 사람 검수와 전체 멘토링 기준 감사가 끝나기 전에는 완료 처리하지 않습니다.
