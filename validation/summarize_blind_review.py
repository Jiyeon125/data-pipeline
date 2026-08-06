"""Aggregate completed two-stage blind-review CSV files.

Templates with no human responses fail with NO_HUMAN_RESPONSES; the script never
manufactures reviewer answers.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

CHOICES = {"CASE_A", "CASE_B", "BOTH", "NEITHER", "UNABLE_TO_DECIDE"}
RATINGS = {
    "APPROPRIATE",
    "PARTIALLY_APPROPRIATE",
    "INAPPROPRIATE",
    "UNABLE_TO_EVALUATE",
}
GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def reviewer_name(path: Path, rows: list[dict[str, str]]) -> str:
    names = {row.get("reviewer_id", "").strip() for row in rows if row.get("reviewer_id", "").strip()}
    if len(names) > 1:
        raise ValueError(f"multiple reviewer_id values in {path}")
    return next(iter(names), path.stem)


def load_stage1(paths: list[Path]) -> tuple[dict[tuple[str, str], str], Counter[str]]:
    responses: dict[tuple[str, str], str] = {}
    requested_information: Counter[str] = Counter()
    for path in paths:
        rows = read_rows(path)
        reviewer = reviewer_name(path, rows)
        by_pair: dict[str, set[str]] = defaultdict(set)
        information_by_pair: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            choice = row.get("first_review_choice", "").strip()
            if choice:
                if choice not in CHOICES:
                    raise ValueError(f"invalid first_review_choice {choice!r} in {path}")
                by_pair[row["pair_id"]].add(choice)
            information = row.get("additional_information_needed", "").strip()
            if information:
                information_by_pair[row["pair_id"]].add(information)
        for pair_id, choices in by_pair.items():
            if len(choices) != 1:
                raise ValueError(f"conflicting choices for {reviewer}/{pair_id}")
            responses[(reviewer, pair_id)] = choices.pop()
            requested_information.update(information_by_pair[pair_id])
    return responses, requested_information


def load_stage2(paths: list[Path]) -> list[tuple[str, str, str, str]]:
    responses = []
    for path in paths:
        rows = read_rows(path)
        reviewer = reviewer_name(path, rows)
        for row in rows:
            rating = row.get("reviewer_question_rating", "").strip()
            if not rating:
                continue
            if rating not in RATINGS:
                raise ValueError(f"invalid reviewer_question_rating {rating!r} in {path}")
            responses.append((reviewer, row["pair_id"], row["case_label"], rating))
    return responses


def load_key(path: Path) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    cases: dict[str, dict[str, str]] = defaultdict(dict)
    strata: dict[str, str] = {}
    for row in read_rows(path):
        cases[row["pair_id"]][row["case_label"]] = row["review_grade"]
        strata[row["pair_id"]] = row["selection_stratum"]
    if any(set(pair) != {"CASE_A", "CASE_B"} for pair in cases.values()):
        raise ValueError("answer key must contain CASE_A and CASE_B for every pair")
    return dict(cases), strata


def higher_grade_choice(grades: dict[str, str]) -> str | None:
    left, right = grades["CASE_A"], grades["CASE_B"]
    if left not in GRADE_ORDER or right not in GRADE_ORDER:
        return None
    if GRADE_ORDER[left] == GRADE_ORDER[right]:
        return None
    return "CASE_A" if GRADE_ORDER[left] < GRADE_ORDER[right] else "CASE_B"


def summarize(
    stage1: dict[tuple[str, str], str],
    stage2: list[tuple[str, str, str, str]],
    cases: dict[str, dict[str, str]],
    strata: dict[str, str],
    requested_information: Counter[str],
) -> tuple[list[dict[str, str]], list[str]]:
    reviewers = sorted({reviewer for reviewer, _ in stage1})
    metrics: list[dict[str, str]] = []

    def add(metric: str, dimension: str, value: int, notes: str = "") -> None:
        metrics.append({"metric": metric, "dimension": dimension, "value": str(value), "notes": notes})

    add("reviewer_count", "ALL", len(reviewers))
    add("completed_reviewer_pair_count", "ALL", len(stage1))
    for reviewer in reviewers:
        selected = Counter(choice for (name, _), choice in stage1.items() if name == reviewer)
        add("completed_pair_count", reviewer, sum(selected.values()))
        for choice in sorted(CHOICES):
            add("reviewer_choice_count", f"{reviewer}:{choice}", selected[choice])

    same_pairs = 0
    disagreements = []
    for pair_id in sorted(cases):
        pair_choices = [choice for (reviewer, pair), choice in stage1.items() if pair == pair_id]
        if len(pair_choices) >= 2 and len(set(pair_choices)) == 1:
            same_pairs += 1
        elif len(pair_choices) >= 2:
            disagreements.append(pair_id)
        add("completed_response_count_by_stratum", strata[pair_id], len(pair_choices), pair_id)
    add("same_choice_pair_count", "ALL", same_pairs, "two or more reviewers completed the pair")

    model_higher = 0
    model_disagreements = []
    for (reviewer, pair_id), choice in stage1.items():
        expected = higher_grade_choice(cases[pair_id])
        model_higher += int(expected is not None and choice == expected)
        if expected is not None and choice in {"CASE_A", "CASE_B"} and choice != expected:
            model_disagreements.append(f"{reviewer}:{pair_id}")
    add("model_higher_grade_case_selected_count", "ALL", model_higher, "H combinations excluded")

    for choice in ("BOTH", "NEITHER", "UNABLE_TO_DECIDE"):
        add("special_choice_count", choice, sum(value == choice for value in stage1.values()))

    ratings = Counter(rating for _, _, _, rating in stage2)
    for rating in sorted(RATINGS):
        add("question_rating_count", rating, ratings[rating])
    for information, count in requested_information.most_common():
        add("additional_information_request_count", information, count)

    lines = [
        "# 블라인드 사람 검토 결과",
        "",
        f"- 검토자 수: {len(reviewers)}",
        f"- 완료된 검토자-쌍 수: {len(stage1)}",
        f"- 두 명 이상이 같은 선택을 한 쌍: {same_pairs}",
        f"- 모델 상위등급 사례 선택 수(H 조합 제외): {model_higher}",
        f"- 불일치 쌍: {', '.join(disagreements) if disagreements else '없음'}",
        f"- 모델 상위등급과 다른 단일 사례 선택: {', '.join(model_disagreements) if model_disagreements else '없음'}",
        "",
        "단순 선택 일치는 기술통계이며 모집단 성능을 뜻하지 않습니다.",
        "",
        "## 질문 평가 분포",
        "",
    ]
    lines.extend(f"- {rating}: {ratings[rating]}" for rating in sorted(RATINGS))
    lines.extend(["", "## 검토자가 추가로 요구한 자료", ""])
    lines.extend(
        [f"- {information}: {count}" for information, count in requested_information.most_common()]
        or ["- 별도 요구 없음"]
    )
    lines.extend(["", "서술형 선택 이유와 질문 수정안은 원문 응답 CSV에서 사례별로 함께 검토해야 합니다."])
    return metrics, lines


def write_outputs(metrics: list[dict[str, str]], lines: list[str], csv_path: Path, report_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "dimension", "value", "notes"])
        writer.writeheader()
        writer.writerows(metrics)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage1", nargs="+", type=Path, required=True)
    parser.add_argument("--stage2", nargs="*", type=Path, default=[])
    parser.add_argument("--answer-key", type=Path, default=Path("validation/blind_pair_answer_key.csv"))
    parser.add_argument("--summary-csv", type=Path, default=Path("validation/blind_review_summary.csv"))
    parser.add_argument("--report", type=Path, default=Path("docs/BLIND_REVIEW_RESULTS.md"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    stage1, requested_information = load_stage1(args.stage1)
    if not stage1:
        print("NO_HUMAN_RESPONSES")
        return 2
    stage2 = load_stage2(args.stage2)
    cases, strata = load_key(args.answer_key)
    unknown_pairs = {pair for _, pair in stage1} - set(cases)
    if unknown_pairs:
        raise ValueError(f"pair_id missing from answer key: {sorted(unknown_pairs)}")
    metrics, lines = summarize(stage1, stage2, cases, strata, requested_information)
    write_outputs(metrics, lines, args.summary_csv, args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
