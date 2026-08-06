from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from analytics.mss_priority_scenario_analysis import (
    PriorityScenarioError,
    apply_question_review_grades,
    build_program_year_review_queue,
    load_scenario_config,
)
from validation.audit_review_grade_rules import OUTPUT_COLUMNS, _grade, _grade_row, decision_table


def test_decision_table_covers_all_grades_and_precedence() -> None:
    table = decision_table()

    assert set(table["review_grade"]) == {"A", "B", "C", "D", "H"}
    assert table["precedence"].min() == 1
    assert table["precedence"].max() == 6
    assert (
        table[["entry_required", "diagnostic_type", "next_review_question_rule"]]
        .notna()
        .all()
        .all()
    )


def test_adverse_signals_are_monotone_except_documented_target_met_cap() -> None:
    performance = {
        "performance_signal": True,
        "below_target_count": 1,
        "reported_target_status": "ALL_COMPARABLE_BELOW_TARGET",
    }

    assert _grade()["review_grade"] == "D"
    assert _grade(**performance)["review_grade"] == "C"
    assert _grade(**performance, current_execution_severity=0.5)["review_grade"] == "B"
    assert (
        _grade(
            **performance,
            current_execution_severity=0.5,
            repeated_low_execution_signal=True,
        )["review_grade"]
        == "A"
    )
    assert _grade(current_execution_severity=1.0)["diagnostic_type"] == "LOW_EXECUTION_TARGET_MET"


def test_context_and_t1_t2_are_grade_neutral_and_order_invariant() -> None:
    baseline = pd.DataFrame(
        [
            _grade_row(program_code="P1"),
            _grade_row(program_code="P2", budget_increase_context_signal=True),
            _grade_row(program_code="P3", current_execution_severity=0.5),
        ]
    )
    changed = baseline.assign(
        low_performance_budget_increase_t1=True,
        low_performance_budget_increase_t2=True,
    ).sample(frac=1, random_state=29)

    left = apply_question_review_grades(baseline).sort_values("program_code")
    right = apply_question_review_grades(changed).sort_values("program_code")
    pd.testing.assert_frame_equal(
        left[OUTPUT_COLUMNS].reset_index(drop=True),
        right[OUTPUT_COLUMNS].reset_index(drop=True),
    )
    assert left.loc[left["program_code"].eq("P2"), "context_only"].item()
    assert left.loc[left["program_code"].eq("P2"), "review_grade"].item() == "D"


def test_full_program_year_queue_is_deterministic_and_blocks_duplicate_raw_id() -> None:
    account_queue = pd.read_csv(
        "data/analytics/multi_ministry_priority_scenarios/full_population_review_work_queue.csv",
        dtype={"ministry_code": "string", "program_code": "string"},
    )
    config = load_scenario_config(Path("configs/priority_scenarios.yaml"))
    first, _ = build_program_year_review_queue(account_queue, config)
    shuffled, _ = build_program_year_review_queue(
        account_queue.sample(frac=1, random_state=31), config
    )
    columns = [
        "program_year_id",
        "review_grade",
        "diagnostic_type",
        "program_year_queue_order",
        "review_queue_order_within_year",
    ]
    pd.testing.assert_frame_equal(
        first[columns].sort_values("program_year_id").reset_index(drop=True),
        shuffled[columns].sort_values("program_year_id").reset_index(drop=True),
    )
    with pytest.raises(PriorityScenarioError, match="candidate_id가 중복"):
        build_program_year_review_queue(
            pd.concat([account_queue, account_queue.iloc[[0]]], ignore_index=True), config
        )


@pytest.mark.xfail(
    strict=True,
    reason="현재 격리 등급 함수는 identity_unresolved를 직접 읽지 않고 upstream data_validation_signal에 의존합니다.",
)
def test_isolated_grade_holds_unresolved_identity() -> None:
    assert _grade(identity_unresolved=True)["review_grade"] == "H"


@pytest.mark.xfail(
    strict=True,
    reason="현재 격리 등급 함수는 집행 심각도 결측을 무신호로 처리합니다.",
)
def test_isolated_grade_holds_missing_execution_information() -> None:
    assert _grade(current_execution_severity=pd.NA)["review_grade"] == "H"


@pytest.mark.xfail(
    strict=True,
    reason="현재 격리 등급 함수는 program_performance_status_conflict를 직접 읽지 않습니다.",
)
def test_isolated_grade_holds_comparability_conflict() -> None:
    assert _grade(program_performance_status_conflict=True)["review_grade"] == "H"
