# 최종 QA 체크리스트

## 기준본과 수치

- [x] repository root·branch·full HEAD 확인
- [x] 기준 CSV SHA-256 확인
- [x] 236행과 `program_year_id` 중복 0 확인
- [x] 원시 감사행 412, 2024년 프로그램 77 확인
- [x] 전체 A16 B14 C90 D89 H27 확인
- [x] 2024년 A4 B2 C35 D28 H8 확인
- [x] 외부검증 8/2/2 확인
- [x] 유지율 93.78%~100.00%, A+B Jaccard 0.8824~1.0000 확인
- [x] 2024년 A+B 안정 5/6 확인
- [x] A+B 6/77, 원문 단위 74/1,080 확인

## 대표사례 UI

- [x] A/B/C/D/H 2024년 대표사례가 대기열에서 선택 가능
- [x] 한글 점검등급·진단·다음 확인질문 표시
- [x] 연도 타임라인 표시
- [x] H가 A~D와 별도 업무그룹으로 표시
- [x] 내부 영문 context 코드 기본 화면 미노출
- [x] 회계유형 감사행이 기본 요약 아래에 위치
- [x] 안정적인 widget key와 `program_year_id`를 사용하고 행 순번에 의존하지 않음

과거 `StopIteration`은 초기 화면 렌더 성공을 확인하지 않은 일회성 AppTest harness에서 발생한 `TEST_HARNESS_LIMITATION`으로 분류했습니다. UI 변경 없이 대표사례 테스트 `5 passed`, 나머지 기존 AppTest `6 passed, 5 deselected`로 확인했습니다.

## Ruff와 테스트

- [x] 알려진 Ruff 오류는 안전한 import 정렬·미사용 import 삭제·불필요 형변환 제거만 적용
- [x] 대상 파일 Ruff 통과
- [x] 전체 `ruff check .` 통과
- [x] 관련 분석 테스트 `26 passed`
- [x] 전체 pytest `314 passed, 3 xfailed`
- [x] `git diff --check` 통과

pytest 경고 2건은 기존 pandas FutureWarning 1건과 pytest cache 접근 경고 1건입니다.

## 변경범위와 보호 대상

- [x] 모든 dirty 파일을 직접 diff 검토하고 `FINAL_CHANGE_MANIFEST.md`에 분류
- [x] 완료된 WIP 체크포인트는 `TEMPORARY_REMOVE`로 삭제
- [x] `program_year_review_queue.csv` 무변경
- [x] 생산 `review_grade` 무변경
- [x] 등급 판정 함수·분석 설정 무변경
- [x] `analysis_summary.json` 무변경
- [x] 새 분석 산출물 없음
- [x] 2025년도 성과계획서는 현재 등급 산정 제외 참고자료라고 범위 고정

## 제출 게이트

- [x] 데이터 무결성
- [x] 대표사례 UI 계약
- [x] 전체 pytest
- [x] 전체 Ruff
- [x] 변경범위 감사
- [ ] 제출 대상 변경 stage·commit

현재 판정: **조건부 가능**. 남은 조건은 manifest에 포함 대상으로 분류한 변경을 검토·커밋하는 일뿐입니다. 자동 stage·commit·push·tag는 수행하지 않았습니다.
