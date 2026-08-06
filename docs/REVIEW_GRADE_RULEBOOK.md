# 생산 점검등급 및 대기열 규칙서

## 기준과 범위

- 기준 HEAD: `6dc0bd96e1beac66b6cdbd4900286b671f54e1ec`
- 생산 CSV SHA-256: `d7c59cc14da21f0e669f2e09867766100957ddad68f8600b43d64392c6236a96`
- 분석 버전: `review_workbench_v5_identity_context_resolution`
- 출력 스키마: `priority_review_outputs_v5_identity_context_resolution`
- 최종 단위: 프로그램×연도 236행, 원시 감사 단위: 프로그램×연도×회계유형 412행
- 이 문서는 현재 생산 코드의 계약을 설명하며 생산 등급·CSV를 변경하지 않습니다.

등급은 사업평가나 위험확률이 아니라 원문 검토 순서입니다. A–D만 검토 우선순위 축이고 H는 데이터·식별자·비교가능성 문제로 판단을 보류하는 별도 축입니다.

## 결정 precedence

1. **H**: `data_validation_signal`, 성과정보 결측이면서 집행 신호도 없음, 또는 프로그램 식별키 불완전
2. **특례 C**: 저집행+보고목표 달성, 저집행+성과정보 없음, 확인된 다년도 맥락의 단년도 저집행
3. **A**: 반복 저집행+보고목표 미달, 또는 연속 목표미달+예산 증가
4. **B**: 성과미달+집행 신호의 두 영역 결합, 강한 현재 저집행, 반복 저집행, 연속 목표미달
5. **일반 C**: 단일 성과·집행·예산불일치·목표적정성 신호
6. **D**: 위 조건이 없으며 context만 있거나 현재 구조화 신호가 없음

세부 조합과 진단·질문·결측·제외조건은 [`validation/review_grade_decision_table.csv`](../validation/review_grade_decision_table.csv)에 있습니다. 같은 행에서 A 진단 두 개가 동시에 성립하면 코드의 후행 할당 때문에 `REPEATED_REPORTED_TARGET_MISS_WITH_BUDGET_INCREASE`가 primary diagnostic이 됩니다. 특례 C에서는 다년도 진단이 후행하여 다른 특례 C 진단을 덮어쓸 수 있습니다.

## 신호와 context

- 등급 신호계열: `data_quality`, `execution`, `reported_performance`, `budget_performance_mismatch`, `target_or_trend`.
- context: 예산 증가·감소, 회계조정, 프로그램 구조, 반복 연말집중. context만 있으면 D이며 `grade_trigger_signal_families`를 늘리지 않습니다.
- `LOW_EXECUTION_TARGET_MET`는 명시적 충돌 특례로 C입니다. 저집행만으로 A가 되지 않습니다.
- 반복은 전년과 회계연도가 정확히 1 차이일 때만 성립합니다. 2022와 2024만 있으면 반복이 아닙니다.
- `grade_reason_codes`는 현재 별도 다중코드가 아니라 primary `diagnostic_type`의 복사값입니다.

## identity·comparability와 결측

프로그램-연도 집계기는 식별자 미해소, 프로그램명·성과상태 충돌, 금액 결측, 비공동분석 행을 `data_validation_signal`로 승격한 뒤 등급 함수에 전달합니다. 따라서 현재 236행에서는 해당 사례가 H입니다. 다만 격리된 등급 함수는 `identity_unresolved`와 `program_performance_status_conflict`를 직접 읽지 않고 upstream 플래그에 의존합니다.

성과 비교가능 건수가 없고 집행 신호도 없으면 H, 저집행 신호가 있으면 특례 C입니다. 숫자 신호 결측은 다수 조건에서 0/False처럼 처리되므로 격리 호출에서 집행 심각도 결측이 D로 완화되는 속성 위반이 있습니다. 생산 집계기의 upstream 검증이 일부를 막지만 함수 자체의 완전한 정보악화 계약은 아닙니다.

## 대기열 정렬 계약

최종 `program_year_queue_order`는 다음의 안정 정렬입니다.

1. `fiscal_year` 오름차순
2. `review_grade_order`: H, A, B, C, D — H 선두는 데이터 확인 업무를 먼저 처리하기 위한 queue precedence이며 위험서열이 아닙니다.
3. `signal_strength`: STRONG, MODERATE, AMBIGUOUS, NONE, NOT_ASSESSED
4. `independent_signal_family_count` 내림차순
5. `program_original_budget` 내림차순 — 등급 변경 없이 동률 정리·업무영향 참고만
6. `program_year_id` 오름차순 최종 tie-break

`review_queue_order_within_year`는 위 정렬 후 연도별로 다시 1부터 부여합니다. `repeated_signal_family_count`, `evidence_strength`, `signal_score`, T+1·T+2는 최종 236행 정렬키가 아닙니다.

## 자동검증 결과

- 236행 계약: PASS 13, FAIL 0
- 규칙 속성: PASS 26, FAIL 3
- dominance 위반: 0

속성 실패는 생산 CSV를 바꾸지 않았습니다. 상세 반례는 [`validation/review_grade_property_audit.csv`](../validation/review_grade_property_audit.csv)에 기록했습니다.

## legacy lane과 signal_score 부록

- legacy 여섯 lane은 412행 감사·하위호환용이며 최종 UI 등급체계가 아닙니다.
- legacy 업무큐는 lane, 반복 신호 수, 독립 신호 수, evidence, complete-case `signal_score`, 본예산, candidate_id를 사용합니다.
- `signal_score`는 성과·집행·예산불일치 세 구성요소가 모두 있을 때만 산술평균하며 부분 결측을 0점으로 보충하지 않습니다. legacy 정렬 구현은 결측 여부를 먼저 분리한 뒤 내부 정렬용 값에만 0을 사용합니다.
- 최종 236행 등급 함수와 CSV 스키마에는 `signal_score`가 없으며 등급·정렬에 사용되지 않습니다.
- 가중치 시나리오는 고급 민감도 산출물에만 남고 생산 판정에 사용되지 않습니다.
