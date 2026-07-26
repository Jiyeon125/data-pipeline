from __future__ import annotations

import pandas as pd

from analytics.analysis_policy_decision_support import (
    execution_ecdf_summary,
    execution_threshold_increment_cases,
    execution_threshold_sensitivity,
    peer_confidence,
    peer_distribution_diagnostics,
    repeated_signal_distribution,
    year_end_pattern_types,
)


def _execution_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "source_project_year_id": ["a-2024", "b-2024"],
            "classification_project_id": ["a", "b"],
            "fiscal_year": [2024, 2024],
            "ministry_code": ["019", "075"],
            "analysis_ministry_name": ["고용노동부", "보건복지부"],
            "account_type_classified": ["GENERAL_ACCOUNT", "GENERAL_ACCOUNT"],
            "project_size_bucket": ["Q1_SMALL", "Q4_VERY_LARGE"],
            "comparison_group": ["GENERAL|DIRECT|POLICY"] * 2,
            "fiscal_instrument": ["DIRECT", "DIRECT"],
            "financial_quality_level": ["INFORMATIONAL", "INFORMATIONAL"],
            "program_code": ["1000", "2000"],
            "program_name": ["프로그램A", "프로그램B"],
            "subactivity_code": ["100", "200"],
            "subactivity_name": ["사업A", "사업B"],
            "execution_rate": [0.5, 0.9],
            "execution_ranking_eligible": [True, True],
            "original_budget_analysis_amount": [100.0, 300.0],
            "current_budget_analysis_amount": [100.0, 300.0],
            "settlement_analysis_amount": [50.0, 270.0],
            "source_trace": ["source-a", "source-b"],
        }
    )


def test_ecdf_preserves_unweighted_and_budget_weighted_meaning() -> None:
    result = execution_ecdf_summary(_execution_rows())
    overall = result[result["dimension"].eq("OVERALL")]
    unweighted = overall[
        overall["weighting"].eq("UNWEIGHTED") & overall["execution_rate"].eq(0.5)
    ].iloc[0]
    weighted = overall[
        overall["weighting"].eq("CURRENT_BUDGET_WEIGHTED") & overall["execution_rate"].eq(0.5)
    ].iloc[0]
    assert unweighted["cumulative_share"] == 0.5
    assert weighted["cumulative_share"] == 0.25


def test_threshold_sensitivity_uses_strict_less_than() -> None:
    result = execution_threshold_sensitivity(_execution_rows())
    at_80 = result[result["dimension"].eq("OVERALL") & result["threshold"].eq(0.8)].iloc[0]
    at_90 = result[result["dimension"].eq("OVERALL") & result["threshold"].eq(0.9)].iloc[0]
    assert at_80["detected_row_count"] == 1
    assert at_90["detected_row_count"] == 1


def test_increment_case_enters_at_first_strict_threshold() -> None:
    frame = _execution_rows().copy()
    frame["execution_rate"] = [0.705, 0.9]
    result = execution_threshold_increment_cases(frame)
    row_a = result[result["classification_project_id"].eq("a")].iloc[0]
    row_b = result[result["classification_project_id"].eq("b")].iloc[0]
    assert row_a["entry_threshold_percent"] == 71
    assert row_b["entry_threshold_percent"] == 91


def test_peer_confidence_uses_expected_tail_observations() -> None:
    assert peer_confidence(1.9) == (False, "NOT_AVAILABLE")
    assert peer_confidence(2.0) == (True, "LOW")
    assert peer_confidence(5.0) == (True, "MEDIUM")
    assert peer_confidence(10.0) == (True, "HIGH")


def test_peer_diagnostics_keep_boundary_ties_visible() -> None:
    rows = pd.concat([_execution_rows()] * 10, ignore_index=True)
    rows["source_project_year_id"] = [f"row-{index}" for index in range(20)]
    rows["classification_project_id"] = [f"project-{index}" for index in range(20)]
    result = peer_distribution_diagnostics(rows)
    bottom10 = result[result["criterion"].eq("EXECUTION_BOTTOM_10")].iloc[0]
    assert bottom10["peer_group_size"] == 20
    assert bottom10["bottom_10_boundary_tie_count"] == 10
    assert bottom10["peer_signal_confidence"] == "LOW"


def test_year_end_patterns_separate_q4_and_december() -> None:
    features = pd.DataFrame(
        {
            "source_project_year_id": ["a", "b", "c"],
            "classification_project_id": ["a", "b", "c"],
            "fiscal_year": [2024] * 3,
            "ministry_code": ["019"] * 3,
            "analysis_ministry_name": ["고용노동부"] * 3,
            "account_type_classified": ["GENERAL_ACCOUNT"] * 3,
            "program_code": ["1000"] * 3,
            "program_name": ["프로그램"] * 3,
            "subactivity_code": ["1", "2", "3"],
            "subactivity_name": ["사업1", "사업2", "사업3"],
            "monthly_signal_eligible_validated": [True] * 3,
            "q4_expenditure_share": [0.5, 0.2, 0.5],
            "december_single_month_share": [0.1, 0.3, 0.3],
            "fixed_q4_40_flag": [True, False, True],
            "fixed_december_20_flag": [False, True, True],
            "original_budget_analysis_amount": [100.0] * 3,
            "current_budget_analysis_amount": [100.0] * 3,
            "settlement_analysis_amount": [90.0] * 3,
            "source_trace": ["source"] * 3,
        }
    )
    peer_flags = pd.DataFrame(
        {
            "source_project_year_id": ["a", "b", "c"],
            "peer_p90_year_end_conservative_tie_block": [False, True, True],
            "peer_p90_group_size": [20] * 3,
        }
    )
    summary, points = year_end_pattern_types(features, peer_flags)
    assert set(points["year_end_fixed_pattern"]) == {
        "Q4_ONLY",
        "DECEMBER_ONLY",
        "BOTH_FIXED",
    }
    overall = summary[summary["dimension"].eq("OVERALL")].set_index("pattern_type")
    assert overall.loc["Q4_ONLY", "detected_row_count"] == 1
    assert overall.loc["DECEMBER_ONLY", "detected_row_count"] == 1
    assert overall.loc["BOTH_FIXED", "detected_row_count"] == 1


def test_recurrence_uses_valid_year_denominator_and_consecutive_years() -> None:
    rows = []
    for year, execution_flag, year_end_flag in [
        (2022, True, None),
        (2023, True, True),
        (2024, False, True),
        (2025, False, None),
    ]:
        rows.append(
            {
                "classification_project_id": "p",
                "fiscal_year": year,
                "ministry_code": "075",
                "analysis_ministry_name": "보건복지부",
                "account_type_classified": "GENERAL_ACCOUNT",
                "program_code": "1000",
                "program_name": "프로그램",
                "subactivity_code": "100",
                "subactivity_name": "사업",
                "original_budget_analysis_amount": 100.0,
                "under_90_combined_flag": execution_flag,
                "fixed_year_end_concentration_flag": year_end_flag,
            }
        )
    result = repeated_signal_distribution(pd.DataFrame(rows)).set_index("signal_name")
    execution = result.loc["UNDER_90_EXECUTION"]
    year_end = result.loc["FIXED_YEAR_END"]
    assert execution["valid_observation_year_count"] == 4
    assert execution["signal_occurrence_year_share"] == 0.5
    assert execution["consecutive_two_year_flag"]
    assert year_end["valid_observation_year_count"] == 2
    assert year_end["signal_occurrence_year_share"] == 1.0
