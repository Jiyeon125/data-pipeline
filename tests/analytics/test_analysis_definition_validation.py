from __future__ import annotations

import math

import pandas as pd

from analytics.analysis_definition_validation import (
    budget_unit_multiplier_validation,
    feedback_cohorts,
    monthly_eligibility_breakdown,
    monthly_formula_validation,
    normalized_program_hhi,
    program_amount_scope,
    ranking_scenario_completeness,
    unknown_budget_coverage,
)


def test_budget_unit_multiplier_identifies_one_x_and_power10() -> None:
    frame = pd.DataFrame(
        {
            "project_id": ["a", "b"],
            "fiscal_year": [2024, 2024],
            "ministry_code": ["019", "075"],
            "account_code": ["1", "1"],
            "program_code": ["1", "1"],
            "activity_code": ["1", "1"],
            "subactivity_code": ["1", "2"],
            "budget_amount": [100, 100],
            "settlement_budget_amount": [100, 1000],
            "current_budget_amount": [120, 120],
            "settlement_current_budget_amount": [120, 120],
        }
    )
    result = budget_unit_multiplier_validation(frame)
    statuses = result.set_index(["amount_type", "project_id"])["unit_multiplier_status"]
    assert statuses[("original_budget", "a")] == "CONSISTENT_1X"
    assert statuses[("original_budget", "b")] == "POSSIBLE_POWER10_UNIT_MULTIPLIER"


def test_monthly_exclusion_primary_sum_matches_excluded() -> None:
    patterns = pd.DataFrame(
        {
            "source_project_year_id": ["a", "b", "c"],
            "classification_project_id": ["pa", "pb", "pc"],
            "monthly_pattern_eligible_final": [True, False, False],
            "execution_denominator_status": ["APPLIED", "MISSING", "APPLIED"],
            "execution_denominator_amount": [100, None, 100],
            "observed_month_count": [12, 11, 12],
            "duplicate_month_key_flag": [False, False, False],
            "master_key_duplicate_flag": [False, False, False],
            "monthly_masked_flag": [False, False, False],
            "review_priority": ["NON_BLOCKING"] * 3,
            "structural_change_type": [None, None, "LEFT_CENSORED"],
            "monthly_pattern_analysis_eligible": [True, False, True],
        }
    )
    core = pd.DataFrame(
        {
            "source_project_year_id": ["a", "b", "c"],
            "classification_project_id": ["pa", "pb", "pc"],
            "original_budget_analysis_amount": [1, 2, 3],
            "current_budget_analysis_amount": [1, 2, 3],
            "settlement_analysis_amount": [1, 2, 3],
        }
    )
    result = monthly_eligibility_breakdown(patterns, core)
    primary = result[result["decomposition_type"].eq("MUTUALLY_EXCLUSIVE_PRIMARY")]
    assert primary["row_count"].sum() == 2
    assert (
        result.loc[
            (result["decomposition_type"] == "FINAL_STATUS")
            & (result["exclusion_rule"] == "EXCLUDED"),
            "row_count",
        ].iloc[0]
        == 2
    )


def test_normalized_hhi_controls_project_count() -> None:
    core = pd.DataFrame(
        {
            "ministry_code": ["019", "019"],
            "analysis_ministry_name": ["고용노동부", "고용노동부"],
            "fiscal_year": [2024, 2024],
            "program_code": ["1", "1"],
            "program_name": ["프로그램", "프로그램"],
            "original_budget_analysis_amount": [50, 50],
        }
    )
    result = normalized_program_hhi(core).iloc[0]
    assert result["hhi_raw"] == 0.5
    assert math.isclose(result["hhi_normalized_for_project_count"], 0)


def test_single_project_normalized_hhi_is_missing() -> None:
    core = pd.DataFrame(
        {
            "ministry_code": ["075"],
            "analysis_ministry_name": ["보건복지부"],
            "fiscal_year": [2024],
            "program_code": ["1"],
            "program_name": ["프로그램"],
            "original_budget_analysis_amount": [50],
        }
    )
    result = normalized_program_hhi(core).iloc[0]
    assert result["single_project_program_flag"]
    assert pd.isna(result["hhi_normalized_for_project_count"])


def test_ranking_scenarios_never_generate_scores_or_ranks() -> None:
    frame = pd.DataFrame(
        {
            "source_project_year_id": ["a"],
            "classification_project_id": ["p"],
            "original_budget_analysis_amount": [100],
            "execution_rate": [0.8],
            "budget_change_rate": [0.1],
            "budget_ranking_eligible": [True],
            "execution_ranking_eligible": [True],
            "trend_ranking_eligible": [True],
            "fiscal_instrument_ranking_eligible": [True],
            "program_ranking_eligible": [True],
            "fiscal_instrument": ["DIRECT"],
            "comparison_group": ["GENERAL|DIRECT|POLICY"],
            "program_code": ["1"],
        }
    )
    result = ranking_scenario_completeness(frame)
    assert not result["final_score_generated"].any()
    assert not result["final_rank_generated"].any()


def test_monthly_quarter_and_single_month_formulas_match() -> None:
    project_key = {
        "fiscal_year": 2024,
        "ministry_code": "019",
        "account_code": "001",
        "program_code": "1000",
        "activity_code": "1100",
        "subactivity_code": "1111",
    }
    patterns = pd.DataFrame(
        [
            {
                **project_key,
                "monthly_pattern_eligible_final": True,
                "execution_denominator_amount": 120,
                "q1_cumulative_execution_rate": 0.25,
                "half_year_cumulative_execution_rate": 0.5,
                "q3_cumulative_execution_rate": 0.75,
                "december_cumulative_execution_rate": 1.0,
                "q4_expenditure_share": 0.25,
                "december_single_month_share": 1 / 12,
            }
        ]
    )
    monthly = pd.DataFrame(
        [
            {
                **project_key,
                "execution_month": 202400 + month,
                "expenditure_amount": 10,
                "cumulative_expenditure_amount": month * 10,
            }
            for month in range(1, 13)
        ]
    )
    result = monthly_formula_validation(patterns, monthly)
    assert result["mismatch_count"].sum() == 0
    assert result["comparable_row_count"].eq(1).all()


def test_program_total_and_analysis_amounts_are_separate() -> None:
    frame = pd.DataFrame(
        {
            "ministry_code": ["019", "019"],
            "ministry_name": ["고용노동부", "고용노동부"],
            "fiscal_year": [2024, 2024],
            "program_code": ["1", "1"],
            "program_name": ["프로그램", "프로그램"],
            "in_core_financial_population": [True, False],
            "analysis_original_budget": [100, 50],
            "analysis_current_budget": [100, 50],
            "analysis_settlement_expenditure": [90, 40],
        }
    )
    result = program_amount_scope(frame).iloc[0]
    assert result["total_original_budget_amount"] == 150
    assert result["analysis_original_budget_amount"] == 100
    assert result["original_budget_analysis_coverage"] == 2 / 3


def test_feedback_cohort_t1_requires_confirmed_chain() -> None:
    v2 = pd.DataFrame(
        [
            {
                "project_id": "p22",
                "fiscal_year": 2022,
                "predecessor_project_id": None,
                "budget_change_analysis_eligible": False,
                "ministry_code": "075",
                "program_code": "1",
                "analysis_original_budget": 100,
            },
            {
                "project_id": "p23",
                "fiscal_year": 2023,
                "predecessor_project_id": "p22",
                "budget_change_analysis_eligible": True,
                "ministry_code": "075",
                "program_code": "1",
                "analysis_original_budget": 110,
            },
        ]
    )
    core = pd.DataFrame({"source_project_year_id": ["p22", "p23"]})
    result = feedback_cohorts(v2, core)
    t1 = result[result["feedback_horizon"].eq("T+1")].iloc[0]
    assert bool(t1["cohort_eligible"])
    assert t1["base_project_id"] == "p22"


def test_unknown_budget_coverage_is_descending_and_cumulative() -> None:
    broad = pd.DataFrame(
        {
            "fiscal_instrument": ["UNKNOWN", "UNKNOWN"],
            "classification_project_id": ["a", "b"],
            "ministry_code": ["019", "075"],
            "analysis_ministry_name": ["고용노동부", "보건복지부"],
            "program_code": ["1", "2"],
            "program_name": ["A", "B"],
            "subactivity_code": ["1", "2"],
            "subactivity_name": ["A사업", "B사업"],
            "fiscal_year": [2024, 2024],
            "source_project_year_id": ["a24", "b24"],
            "original_budget_analysis_amount": [80, 20],
        }
    )
    result = unknown_budget_coverage(broad)
    assert result.iloc[0]["classification_project_id"] == "a"
    assert result.iloc[0]["budget_coverage_order"] == 1
    assert result.iloc[0]["cumulative_budget_share"] == 0.8
    assert result.iloc[-1]["cumulative_budget_share"] == 1.0
