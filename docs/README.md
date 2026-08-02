# 문서 안내

문서가 많지만, 새로 참여한 사람은 아래 네 파일만 먼저 읽으면 됩니다.

1. [프로젝트 계획](PROJECT_PLAN.md): 목적, 분석 범위와 금지사항
2. [아키텍처](architecture.md): 패키지 경계, 데이터 흐름과 실행 명령
3. [분석 결정](ANALYSIS_DECISIONS.md): 현재 채택한 기준과 아직 확정하지 않은 기준
4. [현재 인수인계](SESSION_HANDOFF.md): 검증된 현재 상태와 바로 다음 작업

## 현재 결과와 품질 근거

| 문서 | 용도 |
|---|---|
| [중기부 PDF 대조](MSS_PERFORMANCE_PDF_RECONCILIATION.md) | 중기부 63행 성과지표 원문 검수 결과 |
| [3개 부처 PDF 대조](THREE_MINISTRY_PDF_RECONCILIATION.md) | 고용노동부·복지부·과기정통부 361행의 자동 대조와 사람 검토 대상 |
| [OCR·LLM 기능명세](OCR_LLM_PERFORMANCE_PIPELINE_PLAN_AND_FUNCTIONAL_SPEC.md) | 로컬 우선 추출, 외부 API 비용과 승인 조건 |
| [M2 데이터 점검](M2_DATA_REVIEW.md) | 재정 모집단·품질·기초 분포 |
| [M3 재정 신호](M3_FINANCIAL_INSIGHTS.md) | 집행·연말집중·반복·환류 탐색 |
| [M3 방법론 감사](M3_METHODOLOGY_AUDIT.md) | 동률·신호 단위·군집 검증 |
| [분석정책 의사결정 지원](ANALYSIS_POLICY_DECISION_SUPPORT.md) | 임계값과 순위 기준을 정하기 위한 근거 |
| [전면 구조개선 Gate A 감사](REFACTOR_GATE_A_AUDIT.md) | 현재 저장소·데이터·실행 기준선과 P0 구조 위험 |
| [전면 구조개선 Gate B 미니 PT](REFACTOR_GATE_B_MINI_PT.md) | 저장구조 3안 실측 비교와 목표 grain·ID 권장안 |
| [전면 구조개선 Gate D P0 영향도](REFACTOR_GATE_D_P0_IMPACT_MINI_PT.md) | 운영 변경 전 P0 오류별 후보·순위 영향과 권장 수정안 |
| [core_v2 shadow 계약](CORE_V2_SHADOW_CONTRACT.md) | 승인된 Parquet Core의 grain·ID·금액·lineage와 실제 검증 결과 |

## 참고·이력 문서

아래 문서는 현재 상태 자체가 아니라 작업 배경, 재사용 절차 또는 과거 판단 근거입니다.

| 문서 | 용도 |
|---|---|
| [중기부 PDF 대조 플레이북](MSS_PDF_RECONCILIATION_TIMELINE_AND_PLAYBOOK.md) | 다른 부처로 확장할 때의 절차와 함정 |
| [Cursor 작업지시서](CURSOR_MSS_PERFORMANCE_PDF_RECONCILIATION_PROMPT.md) | 중기부 대조 작업의 외부 AI 실행 계약 |
| [원기획 대비 차이 감사](ORIGINAL_PROPOSAL_PIPELINE_GAP_AUDIT.md) | 최초 제안과 현재 구현의 차이 |
| [멘토링 반영 감사](MENTORING_IMPLEMENTATION_AUDIT.md) | 멘토링 요구사항별 구현 근거와 미반영 항목 |
| [UNKNOWN 검수 안내](UNKNOWN_PRIORITY_REVIEW_GUIDE.md) | 재정수단 수기검수 워크북 사용법 |

`MENTORING_GUIDE.md`, `WORK_LOG.md`, `WORK_TRACKER.md`,
`work_tracker.json`은 로컬 작업 기록이며 GitHub 공개 대상이 아닙니다.
