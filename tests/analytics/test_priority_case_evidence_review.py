from __future__ import annotations

import pandas as pd
import pytest

from analytics.priority_case_evidence_review import (
    add_program_total_feedback,
    review_intensity_summary,
    select_review_cases,
    t1_direction_summary,
)


def _candidates() -> pd.DataFrame:
    rows = [
        ("019", "DATA_FIRST", "DATA_BLOCKED", 0, 0, False, None, 500.0, 0, 1),
        ("019", "REPEATED_OR_MULTIPLE", "LIMITED", 1, 2, True, 0.10, 400.0, 2, 3),
        ("075", "REPEATED_OR_MULTIPLE", "CONFIRMED", 1, 2, True, 0.20, 300.0, 3, 3),
        ("102", "STRONG_SINGLE", "LIMITED", 1, 2, True, 0.30, 200.0, 0, 2),
        ("162", "SINGLE_REVIEW", "CONFIRMED", 1, 2, True, 0.40, 100.0, 0, 1),
        ("162", "REPEATED_OR_MULTIPLE", "CONFIRMED", 1, 2, True, -0.30, 90.0, 1, 2),
        ("075", "MONITOR", "CONFIRMED", 0, 2, True, 0.05, 80.0, 0, 0),
    ]
    records = []
    order = {
        "DATA_FIRST": 1,
        "REPEATED_OR_MULTIPLE": 2,
        "STRONG_SINGLE": 3,
        "SINGLE_REVIEW": 4,
        "CONTEXT_REVIEW": 5,
        "MONITOR": 6,
    }
    for index, (
        ministry,
        intensity,
        evidence,
        below,
        reported,
        complete,
        change,
        budget,
        repeated,
        independent,
    ) in enumerate(rows):
        records.append(
            {
                "candidate_id": f"c{index}",
                "ministry_code": ministry,
                "ministry_name": f"부처{ministry}",
                "fiscal_year": 2023,
                "program_goal_number": f"Ⅰ-{index + 1}",
                "field_name": "분야",
                "sector_name": "부문",
                "program_code": f"P{index}",
                "financial_program_name": f"프로그램{index}",
                "performance_program_name": f"프로그램{index}",
                "account_type": "GENERAL_ACCOUNT",
                "evidence_status": evidence,
                "below_target_count": below,
                "reported_rate_count": reported,
                "feedback_budget_complete_t1": complete,
                "feedback_budget_change_rate_t1": change,
                "program_total_feedback_complete_t1": complete,
                "program_total_budget_change_rate_t1": change,
                "budget_direction_reconciled": complete and change is not None,
                "low_performance_budget_increase_t1": bool(below and change and change > 0),
                "low_performance_program_total_budget_increase_t1": bool(
                    below and change and change > 0
                ),
                "review_intensity": intensity,
                "review_intensity_order": order[intensity],
                "review_item_type": (
                    "PROGRAM_DATA_TASK" if intensity == "DATA_FIRST" else "DETAILED_PROJECT_REVIEW"
                ),
                "repeated_signal_family_count": repeated,
                "independent_signal_family_count": independent,
                "account_original_budget": budget,
                "data_validation_signal": intensity == "DATA_FIRST",
            }
        )
    return pd.DataFrame(records)


def test_select_review_cases_keeps_four_ministries_and_counterexamples() -> None:
    result = select_review_cases(_candidates())

    assert set(result["ministry_code"]) == {"019", "075", "102", "162"}
    assert result["candidate_id"].is_unique
    assert "DATA_BLOCKER" in set(result["case_role"])
    assert "MISS_THEN_T1_INCREASE" in set(result["case_role"])
    assert "MISS_THEN_T1_DECREASE_COUNTEREXAMPLE" in set(result["case_role"])
    assert "ALL_MET_THEN_T1_INCREASE_CONTEXT" in set(result["case_role"])


def test_t1_direction_summary_does_not_mix_incomplete_rows() -> None:
    frame = _candidates()
    frame.loc[1, "program_total_feedback_complete_t1"] = False
    result = t1_direction_summary(frame)

    assert result["program_account_rows"].sum() == 4
    assert set(result["t1_budget_direction"]) == {"INCREASE", "DECREASE"}


def test_review_intensity_summary_preserves_rows_and_budget() -> None:
    frame = _candidates()
    result = review_intensity_summary(frame)

    assert result["program_account_rows"].sum() == len(frame)
    assert result["original_budget"].sum() == frame["account_original_budget"].sum()
    assert result["row_share"].sum() == pytest.approx(1.0)
    assert result["budget_share"].sum() == pytest.approx(1.0)


def test_program_total_feedback_keeps_total_and_analysis_subset_separate() -> None:
    candidates = _candidates().iloc[[5]].copy()
    candidates["feedback_budget_change_rate_t1"] = -0.03
    programs = pd.DataFrame(
        [
            {
                "ministry_code": "162",
                "field_name": "분야",
                "sector_name": "부문",
                "program_code": "P5",
                "program_name": "프로그램5",
                "fiscal_year": 2023,
                "program_total_original_budget": 220,
                "program_analysis_original_budget": 73,
                "account_type_count": 1,
                "account_types": '["GENERAL_ACCOUNT"]',
            },
            {
                "ministry_code": "162",
                "field_name": "분야",
                "sector_name": "부문",
                "program_code": "P5",
                "program_name": "프로그램5",
                "fiscal_year": 2024,
                "program_total_original_budget": 241,
                "program_analysis_original_budget": 70,
                "account_type_count": 1,
                "account_types": '["GENERAL_ACCOUNT"]',
            },
        ]
    )

    result = add_program_total_feedback(candidates, programs).iloc[0]

    assert result["program_total_budget_change_rate_t1"] == pytest.approx(21 / 220)
    assert result["feedback_budget_change_rate_t1"] == pytest.approx(-0.03)
    assert not bool(result["budget_direction_reconciled"])
