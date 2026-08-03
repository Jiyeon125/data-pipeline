from pathlib import Path

import pandas as pd

from analytics.real_budget_feedback import (
    RealBudgetFeedbackPaths,
    attach_real_budget_feedback,
    build_real_budget_feedback_sensitivity,
)


def _candidate(candidate_id: str, year: int, gap: float) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "fiscal_year": year,
        "ministry_code": "102",
        "program_code": "1000",
        "account_type": "GENERAL_ACCOUNT",
        "account_original_budget": 100.0,
        "analysis_status": "JOINT_ANALYSIS",
        "comparable_rate_count": 1,
        "performance_gap": gap,
        "performance_signal": gap > 0,
        "execution_review_signal": False,
        "current_execution_severity": 0,
        "repeated_execution_signal": False,
        "accounting_context_signal": False,
        "structure_context_signal": False,
        "budget_increase_context_signal": False,
        "budget_decrease_context_signal": False,
        "data_validation_signal": False,
        "review_intensity": "STRONG_SINGLE" if gap > 0 else "MONITOR",
        "program_total_feedback_complete_t1": True,
        "program_total_budget_change_rate_t1": 0.01,
        "program_total_base_budget_t1": 100.0,
        "program_total_outcome_budget_t1": 101.0,
        "low_performance_budget_increase_t1": gap > 0,
        "good_performance_budget_decrease_t1": False,
        "program_total_feedback_complete_t2": True,
        "program_total_budget_change_rate_t2": 0.05,
        "program_total_base_budget_t2": 100.0,
        "program_total_outcome_budget_t2": 105.0,
        "low_performance_budget_increase_t2": gap > 0,
        "good_performance_budget_decrease_t2": False,
    }


def test_attach_real_budget_feedback_preserves_nominal_and_changes_only_sensitivity() -> None:
    frame = pd.DataFrame(
        [
            _candidate("low", 2022, 1.0),
            _candidate("good", 2022, 0.0),
            _candidate("outside", 2024, 1.0),
        ]
    )
    result = attach_real_budget_feedback(frame)

    assert result["program_total_budget_change_rate_t1"].tolist() == [0.01, 0.01, 0.01]
    assert result.loc[0, "program_total_budget_change_rate_t1_real"] < 0
    assert not result.loc[0, "low_performance_budget_increase_t1_real"]
    assert result.loc[1, "good_performance_budget_decrease_t1_real"]
    assert not result.loc[2, "real_feedback_eligible_t1"]
    assert pd.isna(result.loc[2, "program_total_budget_change_rate_t1_real"])


def test_build_real_budget_feedback_writes_validated_outputs(tmp_path: Path) -> None:
    candidates = tmp_path / "candidate_population.csv"
    pd.DataFrame([_candidate("low", 2022, 1.0)]).to_csv(candidates, index=False)
    paths = RealBudgetFeedbackPaths(
        candidates=candidates,
        output_dir=tmp_path / "output",
        report=tmp_path / "report.md",
    )

    result = build_real_budget_feedback_sensitivity(paths)

    assert result.summary["validation"]["nominal_rates_unchanged"]
    assert result.summary["horizon_summary"]["t1"]["direction_flip_count"] == 1
    assert all(path.exists() for path in result.output_paths)
    assert result.report_path.exists()
