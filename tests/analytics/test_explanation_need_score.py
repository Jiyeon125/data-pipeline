from __future__ import annotations

import math

import pandas as pd

from analytics.explanation_need_score import (
    assign_score_lane,
    assign_scores,
    estimate_log_lift_weights,
    rank_explanation_need,
)


def test_log_lift_weight_formula() -> None:
    panel = pd.DataFrame(
        {
            "x_repeated_execution": [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            "x_execution_low": [0] * 20,
            "x_performance_gap": [0] * 20,
            "x_feedback_increase": [0] * 20,
            "x_multiple_independent": [0] * 20,
            "future_confirmed_strict": [
                1,
                1,
                1,
                1,
                1,
                1,
                1,
                1,
                0,
                0,
                1,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
            ],
        }
    )
    weights, table = estimate_log_lift_weights(panel)
    assert weights["x_repeated_execution"] == math.log(8.0)
    assert table.loc[table["column"].eq("x_repeated_execution"), "status"].iloc[0] == "active"
    assert weights["x_performance_gap"] == 0.0


def test_score_is_share_of_validated_weight() -> None:
    weights = {
        "x_repeated_execution": math.log(2),
        "x_execution_low": 0.0,
        "x_performance_gap": math.log(1.5),
        "x_feedback_increase": 0.0,
        "x_multiple_independent": 0.0,
    }
    frame = pd.DataFrame(
        [
            {
                "candidate_id": "a",
                "ministry_code": "075",
                "fiscal_year": 2023,
                "account_execution_rate": 0.95,
                "performance_gap": 0.5,
                "repeated_execution_signal": True,
                "low_performance_budget_increase_t1": False,
                "low_performance_budget_increase_t2": False,
                "data_validation_signal": False,
                "evidence_status": "CONFIRMED",
                "account_original_budget": 1e9,
                "independent_signal_family_count": 1,
            }
        ]
    )
    scored = assign_scores(frame, weights)
    expected = 100.0
    assert abs(scored.iloc[0]["explanation_need_score"] - expected) < 1e-9


def test_data_queue_and_rank_order() -> None:
    weights = {
        "x_repeated_execution": 1.0,
        "x_execution_low": 0.5,
        "x_performance_gap": 0.2,
        "x_feedback_increase": 0.0,
        "x_multiple_independent": 0.0,
    }
    frame = pd.DataFrame(
        [
            {
                "candidate_id": "data_problem",
                "ministry_code": "075",
                "fiscal_year": 2023,
                "account_execution_rate": 0.5,
                "performance_gap": 1.0,
                "repeated_execution_signal": True,
                "low_performance_budget_increase_t1": False,
                "low_performance_budget_increase_t2": False,
                "data_validation_signal": True,
                "evidence_status": "DATA_BLOCKED",
                "account_original_budget": 1e9,
                "independent_signal_family_count": 2,
                "review_intensity": "DATA_FIRST",
                "work_queue_order": 1,
            },
            {
                "candidate_id": "urgent_ok",
                "ministry_code": "075",
                "fiscal_year": 2023,
                "account_execution_rate": 0.5,
                "performance_gap": 1.0,
                "repeated_execution_signal": True,
                "low_performance_budget_increase_t1": False,
                "low_performance_budget_increase_t2": False,
                "data_validation_signal": False,
                "evidence_status": "CONFIRMED",
                "account_original_budget": 1e8,
                "independent_signal_family_count": 2,
                "review_intensity": "REPEATED_OR_MULTIPLE",
                "work_queue_order": 2,
            },
            {
                "candidate_id": "monitor",
                "ministry_code": "075",
                "fiscal_year": 2023,
                "account_execution_rate": 0.99,
                "performance_gap": 0.0,
                "repeated_execution_signal": False,
                "low_performance_budget_increase_t1": False,
                "low_performance_budget_increase_t2": False,
                "data_validation_signal": False,
                "evidence_status": "CONFIRMED",
                "account_original_budget": 1e13,
                "independent_signal_family_count": 0,
                "review_intensity": "MONITOR",
                "work_queue_order": 3,
            },
        ]
    )
    scored = rank_explanation_need(assign_score_lane(assign_scores(frame, weights)))
    assert list(scored["candidate_id"]) == ["data_problem", "urgent_ok", "monitor"]
    assert scored.iloc[0]["score_lane"] == "DATA_QUEUE"
    assert scored.iloc[2]["explanation_need_score"] == 0
