from __future__ import annotations

import pandas as pd

from master_engineering.quality.refactor_gate_d import _suppress_future_outcomes


def test_future_outcome_only_context_moves_to_monitor() -> None:
    frame = pd.DataFrame(
        {
            "fiscal_year": [2024],
            "performance_signal": [False],
            "execution_review_signal": [False],
            "low_performance_budget_increase_t1": [False],
            "low_performance_budget_increase_t2": [False],
            "good_performance_budget_decrease_t1": [True],
            "good_performance_budget_decrease_t2": [False],
            "program_total_feedback_complete_t1": [True],
            "feedback_budget_complete_t1": [False],
            "continuous_project_feedback_complete_t1": [False],
            "program_total_feedback_complete_t2": [False],
            "feedback_budget_complete_t2": [False],
            "continuous_project_feedback_complete_t2": [False],
            "accounting_context_signal": [False],
            "structure_context_signal": [False],
            "budget_increase_context_signal": [False],
            "budget_decrease_context_signal": [False],
            "performance_gap": [0.0],
            "current_execution_severity": [0.0],
            "repeated_execution_signal": [False],
            "data_validation_signal": [False],
        }
    )

    result = _suppress_future_outcomes(frame)

    assert result.loc[0, "review_intensity"] == "MONITOR"
    assert not bool(result.loc[0, "review_candidate"])
