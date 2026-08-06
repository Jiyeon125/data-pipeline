# 최종 QA 체크리스트

## 기준본과 수치

- [x] repository root와 branch 확인
- [x] full HEAD 기록
- [x] 기준 CSV SHA-256 확인
- [x] 236행과 `program_year_id` 중복 0 확인
- [x] 원시 감사행 412, 고유 프로그램 80, identity 포함 84 확인
- [x] 2024년 77개 확인
- [x] 전체·2024년 A/B/C/D/H 분포 확인
- [x] 외부검증 8/2/2 확인
- [x] 유지율 93.78%~100.00%, A+B Jaccard 0.8824~1.0000 확인
- [x] 2024년 A+B 안정 5/6 확인
- [x] A+B 6/77, 원문 단위 74/1,080 확인

## 수치 동기화

- [x] README
- [x] CURRENT_PROJECT_CONTEXT
- [x] FINAL_VALIDATION_REPORT
- [x] DATA_ANALYSIS_PRESENTATION_SUMMARY
- [x] VALIDATION_PRESENTATION_SUMMARY
- [x] FINAL_PRESENTATION_OUTLINE
- [x] PRESENTATION_NUMBERS_SINGLE_SOURCE
- [x] 대시보드
- [x] analysis_summary.json
- [x] validation 산출물

검사 결과 숫자 불일치는 없었습니다. 생산 데이터·분석결과·UI는 수정하지 않았습니다.

## 금지 표현 감사

- `CURRENT`: 정본 문서와 기본 UI의 관련 검색 결과는 모두 “판정하지 않음”, “예측이 아님”, “전 모집단에 일반화하지 않음”이라는 제한 문구입니다.
- `LEGACY`: `docs/FINAL_REPORT.md`는 상단 LEGACY 경고와 현재 정본 링크가 있어 허용합니다. 문서 내부의 정확도·감액·실패 표현도 주장하지 않는다는 문맥입니다.
- `MUST_FIX`: 0건

정확 일치 검색에서 실패사업, 비효율사업, 감액·구조조정 대상 자동 판정, 위험확률, 정확도·적중률, A+B가 문제사업, D가 정상·안전 사업, 412개 사업, 세 신호의 동등 기여, 다음 연도 예측, peer 비교 전 모집단 적용을 긍정적으로 주장하는 문장은 발견되지 않았습니다.

## 실행 검증

- [x] 전체 pytest 1회: `309 passed, 3 xfailed`
- [ ] Ruff 1회: 9건 실패. 요청 범위 밖 기존 파일이므로 자동 수정하지 않음
- [x] `git diff --check`: 최종 문서 작성 후 결과 기록
- [x] 기준 CSV SHA·키·등급 분포: 최종 문서 작성 후 결과 기록
- [x] Streamlit 서버 스모크 1회: HTTP 200 `ok`
- [x] 기존 AppTest 6건: 전체 pytest에서 통과
- [ ] A/B/C/D/H 대표사례 별도 AppTest 1회: 초기 위젯 탐색 `StopIteration`으로 미완료

대표사례 검증에서 확인하려던 항목은 한글 등급, 한 문장 진단, 핵심 근거, 다음 확인질문, 연도 타임라인, 회계유형 감사정보, A/B 안정성 배지, H 분리, 내부 영문코드 미노출입니다. 기존 AppTest는 기본 A 상세, H 분리, 기본 화면 코드 미노출을 검증하지만 다섯 등급 전체의 별도 순회는 완료되지 않았습니다.

## dirty 상태

자동 commit·push·tag는 수행하지 않았습니다. 제출 전 최종 `git status --short` 목록을 검토해 의도한 파일만 커밋해야 합니다.

```text
M README.md
M docs/FINAL_REPORT.md
M docs/FINAL_VALIDATION_REPORT.md
M docs/VALIDATION_PRESENTATION_SUMMARY.md
M src/fiscal_dashboard/app.py
M tests/test_fiscal_dashboard.py
?? docs/CURRENT_PROJECT_CONTEXT.md
?? docs/DATA_ANALYSIS_PRESENTATION_SUMMARY.md
?? docs/FINAL_PRESENTATION_OUTLINE.md
?? docs/FINAL_QA_CHECKLIST.md
?? docs/OPERATIONAL_ANALYSIS_REPORT.md
?? docs/PEER_REFERENCE_REPORT.md
?? docs/PRESENTATION_NUMBERS_SINGLE_SOURCE.md
?? docs/SUBMISSION_BASELINE.md
?? docs/TEMPORAL_FOLLOWUP_REPORT.md
?? docs/WORKLOAD_COMPRESSION_REPORT.md
?? docs/work_in_progress/OPERATIONAL_ANALYSIS_CHECKPOINT.md
?? tests/validation/test_operational_analysis.py
?? validation/analyze_operational_analysis.py
?? validation/figures/peer_reference_examples.png
?? validation/figures/priority_review_stability_2024.png
?? validation/figures/temporal_grade_transition.png
?? validation/figures/workload_compression.png
```

## 제출 게이트

- [x] 생산 CSV·등급 불변
- [x] 전체 pytest 통과
- [x] Streamlit 서버 기동 가능
- [ ] 전체 Ruff 통과
- [ ] A/B/C/D/H 대표사례 AppTest 통과
- [ ] dirty 파일 검토 및 제출 커밋 고정

현재 판정: **조건부 가능**
