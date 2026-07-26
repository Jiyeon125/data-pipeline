from __future__ import annotations

import pandas as pd

from analytics.financial_eda import (
    build_monthly_patterns,
    ministry_year_summary,
    repeated_execution_review,
)


def _core_row() -> dict[str, object]:
    return {
        "fiscal_year": 2023,
        "ministry_code": "019",
        "account_code": "001",
        "program_code": "1000",
        "activity_code": "1100",
        "subactivity_code": "1111",
        "source_project_year_id": "row-1",
        "classification_project_id": "project-1",
        "ministry_name": "고용노동부",
        "program_name": "프로그램",
        "subactivity_name": "세부사업",
        "project_status": "CONTINUING",
        "structural_change_type": None,
        "execution_denominator_amount": 100.0,
        "execution_denominator_status": "APPLIED",
        "execution_rate": 0.8,
        "execution_rate_over_100_flag": False,
        "review_priority": "NON_BLOCKING",
        "monthly_pattern_analysis_eligible": True,
    }


def test_monthly_pattern_rates_and_year_end_signal() -> None:
    core = pd.DataFrame([_core_row()])
    monthly = pd.DataFrame(
        [
            {
                **{
                    key: _core_row()[key]
                    for key in [
                        "fiscal_year",
                        "ministry_code",
                        "account_code",
                        "program_code",
                        "activity_code",
                        "subactivity_code",
                    ]
                },
                "execution_month": 202300 + month,
                "expenditure_amount": 5.0 if month < 12 else 25.0,
                "cumulative_expenditure_amount": 5.0 * month if month < 12 else 80.0,
                "is_masked": False,
                "manual_review_required": False,
            }
            for month in range(1, 13)
        ]
    )
    result = build_monthly_patterns(core, monthly).iloc[0]
    assert result["q1_cumulative_execution_rate"] == 0.15
    assert result["december_cumulative_execution_rate"] == 0.8
    assert bool(result["year_end_concentration_flag"])
    assert bool(result["monthly_pattern_eligible_final"])


def test_duplicate_month_key_is_not_summed_and_is_ineligible() -> None:
    core = pd.DataFrame([_core_row()])
    row = {
        **{
            key: _core_row()[key]
            for key in [
                "fiscal_year",
                "ministry_code",
                "account_code",
                "program_code",
                "activity_code",
                "subactivity_code",
            ]
        },
        "execution_month": 202301,
        "expenditure_amount": 10.0,
        "cumulative_expenditure_amount": 10.0,
        "is_masked": False,
        "manual_review_required": False,
    }
    result = build_monthly_patterns(core, pd.DataFrame([row, row])).iloc[0]
    assert bool(result["duplicate_month_key_flag"])
    assert not bool(result["monthly_pattern_eligible_final"])
    assert pd.isna(result["q1_cumulative_amount"])


def test_observation_boundary_is_limited_for_repeated_pattern() -> None:
    row = _core_row()
    row["structural_change_type"] = "LEFT_CENSORED"
    core = pd.DataFrame([row])
    monthly = pd.DataFrame(
        [
            {
                **{
                    key: row[key]
                    for key in [
                        "fiscal_year",
                        "ministry_code",
                        "account_code",
                        "program_code",
                        "activity_code",
                        "subactivity_code",
                    ]
                },
                "execution_month": 202300 + month,
                "expenditure_amount": 5.0,
                "cumulative_expenditure_amount": 5.0 * month,
                "is_masked": False,
                "manual_review_required": False,
            }
            for month in range(1, 13)
        ]
    )
    result = build_monthly_patterns(core, monthly)
    assert not bool(result.iloc[0]["monthly_pattern_eligible_final"])


def test_ministry_summary_separates_broad_and_core() -> None:
    frame = pd.DataFrame(
        [
            {
                "ministry_code": "075",
                "ministry_name": "보건복지부",
                "fiscal_year": 2024,
                "classification_project_id": "a",
                "program_code": "1",
                "in_broad_population": True,
                "in_core_financial_population": True,
                "analysis_original_budget": 100,
                "analysis_current_budget": 120,
                "analysis_settlement_expenditure": 90,
                "settlement_carryover_amount": 5,
                "settlement_unused_amount": 25,
            },
            {
                "ministry_code": "075",
                "ministry_name": "보건복지부",
                "fiscal_year": 2024,
                "classification_project_id": "b",
                "program_code": "1",
                "in_broad_population": True,
                "in_core_financial_population": False,
                "analysis_original_budget": 50,
                "analysis_current_budget": 50,
                "analysis_settlement_expenditure": 0,
                "settlement_carryover_amount": 0,
                "settlement_unused_amount": 0,
            },
        ]
    )
    result = ministry_year_summary(frame).iloc[0]
    assert result["sample_size"] == 2
    assert result["core_sample_size"] == 1
    assert result["analysis_target_original_budget_share"] == 2 / 3


def test_repeated_flag_requires_repetition_or_over_100() -> None:
    patterns = pd.DataFrame(
        [
            {
                **_core_row(),
                "fiscal_year": year,
                "monthly_pattern_eligible_final": True,
                "year_end_concentration_flag": False,
                "cumulative_decrease_count": 0,
            }
            for year in [2023, 2024]
        ]
    )
    result = repeated_execution_review(patterns, pd.DataFrame())
    project = result[result["entity_level"].eq("PROJECT")].iloc[0]
    assert project["execution_rate_under_90_year_count"] == 2
    assert bool(project["repeated_execution_explanation_needed_flag"])
