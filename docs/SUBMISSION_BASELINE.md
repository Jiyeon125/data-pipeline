# 제출 기준본

기준 고정일: 2026-08-07

## 저장소 기준

- repository: `Jiyeon125/data-pipeline`
- branch: `main`
- 최종 full commit SHA: `9beefea7dfdf497f1ec326f38dcd44d665747ed0`
- 기준 고정 직전 작업트리: clean (`git status --short` 출력 없음)
- 자동 commit·push·tag 미수행
- 분석 버전: `review_workbench_v5_identity_context_resolution`
- 스키마 버전: `priority_review_outputs_v5_identity_context_resolution`

## 생산 기준본

- 파일: `data/analytics/multi_ministry_priority_scenarios/program_year_review_queue.csv`
- SHA-256: `d7c59cc14da21f0e669f2e09867766100957ddad68f8600b43d64392c6236a96`
- 프로그램-연도 236행, `program_year_id` 중복 0
- 원시 감사행 412행
- 고유 프로그램 80개, UNKNOWN continuity 포함 identity 84개
- 2024년 프로그램 77개
- 전체 등급: A16 B14 C90 D89 H27
- 2024년 등급: A4 B2 C35 D28 H8

## 검증 기준

- 외부검증: SUPPORTED 8, CONTRADICTED 2, INSUFFICIENT 2
- 임계값 A~D 유지율: 93.78%~100.00%
- A+B Jaccard: 0.8824~1.0000
- 2024년 A+B 임계값 안정: 5/6
- 우선 확인 프로그램: 6/77
- 연결 원문 단위: 74/1,080
- 사람검증: 블라인드 쌍대비교 검토표와 연구자 1인의 예비 사용성 점검까지 수행했습니다. 독립 검토자를 확보하지 못해 검토자 간 일치도와 모델-사람 판단 부합도는 산출하지 않았습니다.

## 실행 QA 결과

- 대표 A/B/C/D/H AppTest: `5 passed`
- 나머지 기존 Streamlit AppTest: `6 passed, 5 deselected`
- 관련 분석 테스트: `26 passed`
- 전체 pytest: `314 passed, 3 xfailed`, 경고 2건
- 대상 파일 Ruff: 통과
- 전체 Ruff: 통과
- `git diff --check`: 통과
- 대표사례 과거 `StopIteration` 원인: `TEST_HARNESS_LIMITATION`
- UI 수정: 없음

## 알려진 한계

- 점검등급은 성과 앵커형 질문형 등급이며 사업 실패·위험·정책효과를 판정하지 않습니다.
- 법률·제도·재원구조 위험은 현재 구조화 신호에 포함되지 않습니다.
- 동료집단 백분위 적격은 10/472로 본편 기준에 사용하지 않습니다.
- 다음 연도 관측은 예측 성능이 아니라 방향적 연관성입니다.
- 독립 사람검증은 완료되지 않았습니다.

## 제출 판정

**제출 가능**입니다. 데이터·등급·UI·테스트 gate가 통과했고, release gate 변경은 위 full commit SHA에 포함되어 있습니다.

## 기준 고정 직전 dirty 파일

```text
없음
```
