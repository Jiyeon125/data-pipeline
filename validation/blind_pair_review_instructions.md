# 블라인드 쌍대비교 검토 안내

## 목적

이 검토는 사업의 성과등급을 평가하는 작업이 아닙니다. 제공된 두 사례 중 어떤 사례의 원문을 먼저 확인할지 판단하는 작업입니다.

## 진행 순서

1. 먼저 `blind_pair_stage1_anonymous.csv`만 보고 사례당 3~5분 안에 독립적으로 판단합니다.
2. 정책 맥락이 없어 판단할 수 없는 경우에만 `blind_pair_stage1_named.csv`의 같은 `pair_id`를 확인합니다.
3. 8쌍의 1단계 입력을 모두 끝낸 뒤에만 `blind_pair_stage2_question_review.csv`를 열어 모델 질문을 평가합니다.
4. 검토 중 외부검색은 하지 않고 제공된 사실만 사용합니다. 검토자끼리 상의하지 말고 각자 먼저 작성합니다.

## 1단계 입력 규칙

- `first_review_choice`: `CASE_A`, `CASE_B`, `BOTH`, `NEITHER`, `UNABLE_TO_DECIDE` 중 하나
- `confidence_level`: `LOW`, `MEDIUM`, `HIGH` 중 하나
- 둘 다 우선·둘 다 후순위·판단 불가를 선택한 경우 대응 사유 필드를 작성합니다.
- 정보가 부족하면 억지로 선택하지 말고 `UNABLE_TO_DECIDE`와 필요한 추가 자료를 적습니다.
- 모델의 등급·진단·이유 코드·확인질문·정답키는 1단계 종료 전 확인하지 않습니다.

## 2단계 입력 규칙

`reviewer_question_rating`은 `APPROPRIATE`, `PARTIALLY_APPROPRIATE`, `INAPPROPRIATE`, `UNABLE_TO_EVALUATE` 중 하나입니다. 빠진 쟁점, 과도한 표현, 대체 질문을 필요한 범위에서 기록합니다.

## 정보 공개 원칙

익명판은 프로그램과 부처를 가립니다. 명칭 공개판은 부처·프로그램명만 추가하며 모델 판정은 계속 숨깁니다. `blind_pair_answer_key.csv`는 검토자가 모든 입력을 제출하기 전 열지 않습니다.

예산 규모 구간은 `SMALL`(100억 원 미만), `MEDIUM`(100억 원 이상 1,000억 원 미만), `LARGE`(1,000억 원 이상 1조 원 미만), `VERY_LARGE`(1조 원 이상), `UNKNOWN`으로 표시했습니다.
