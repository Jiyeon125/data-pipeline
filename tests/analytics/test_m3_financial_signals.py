from __future__ import annotations

import pandas as pd

from analytics.m3_financial_signals import (
    SIGNAL_COLUMNS,
    TYPE_COLUMNS,
    attach_signal_types,
    build_repeated_signals,
    build_signal_features,
    unknown_manual_review_priority,
)


def _ranking_rows() -> pd.DataFrame:
    rows = []
    for year, rate, change in [
        (2022, 0.75, None),
        (2023, 0.78, -0.2),
        (2024, 0.85, 0.1),
        (2025, 1.05, 0.2),
    ]:
        rows.append(
            {
                "source_project_year_id": f"p{year}",
                "classification_project_id": "p",
                "fiscal_year": year,
                "ministry_code": "019",
                "analysis_ministry_name": "고용노동부",
                "account_type_classified": "GENERAL_ACCOUNT",
                "project_size_bucket": "MEDIUM",
                "comparison_group": "GENERAL|DIRECT|POLICY",
                "program_code": "1000",
                "program_name": "프로그램",
                "subactivity_code": "1111",
                "subactivity_name": "세부사업",
                "original_budget_analysis_amount": 100,
                "current_budget_analysis_amount": 100,
                "settlement_analysis_amount": 80,
                "execution_rate": rate,
                "budget_change_rate": change,
                "execution_ranking_eligible": year != 2025,
                "trend_ranking_eligible": year != 2022,
                "review_priority": "NON_BLOCKING",
                "settlement_join_status": "BOTH",
                "execution_denominator_status": "APPLIED",
                "rank_confidence": "HIGH",
                "project_status": "CONTINUING",
                "source_trace": f"source-{year}",
            }
        )
    return pd.DataFrame(rows)


def _patterns() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_project_year_id": f"p{year}",
                "monthly_pattern_eligible_final": year in [2023, 2024],
                "observed_month_count": 12,
                "q4_expenditure_share": 0.5 if year in [2023, 2024] else 0.2,
                "december_single_month_share": 0.1,
                "cumulative_decrease_count": 1 if year == 2024 else 0,
                "monthly_expenditure_volatility": 0.2,
                "execution_data_quality_flags": (
                    "NONE" if year in [2023, 2024] else "OBSERVATION_BOUNDARY"
                ),
                "duplicate_month_key_flag": False,
                "master_key_duplicate_flag": False,
                "monthly_masked_flag": False,
            }
            for year in [2022, 2023, 2024, 2025]
        ]
    )


def _hhi() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ministry_code": ["019"] * 4,
            "fiscal_year": [2022, 2023, 2024, 2025],
            "program_code": ["1000"] * 4,
            "program_name": ["프로그램"] * 4,
            "positive_budget_project_count": [2] * 4,
            "hhi_raw": [0.82] * 4,
            "hhi_normalized_for_project_count": [0.64] * 4,
            "top1_project_budget_share": [0.9] * 4,
            "top3_project_budget_share": [1.0] * 4,
        }
    )


def test_signal_features_keep_independent_nullable_flags() -> None:
    result = build_signal_features(_ranking_rows(), _patterns(), _hhi())
    assert set(SIGNAL_COLUMNS).issubset(result.columns)
    assert bool(result.loc[result["fiscal_year"].eq(2022), "strong_low_execution_flag"].iloc[0])
    assert bool(
        result.loc[
            result["fiscal_year"].eq(2024),
            "moderate_low_execution_flag",
        ].iloc[0]
    )
    assert pd.isna(result.loc[result["fiscal_year"].eq(2025), "strong_low_execution_flag"].iloc[0])


def test_monthly_boundary_retained_only_as_sensitivity() -> None:
    result = build_signal_features(_ranking_rows(), _patterns(), _hhi())
    boundary = result[result["fiscal_year"].eq(2022)].iloc[0]
    assert not bool(boundary["monthly_signal_eligible_validated"])
    assert bool(boundary["monthly_signal_eligible_boundary_retained"])
    assert pd.isna(boundary["fixed_year_end_concentration_flag"])


def test_repeat_uses_valid_year_denominator_and_consecutive_years() -> None:
    features = build_signal_features(_ranking_rows(), _patterns(), _hhi())
    repeated = build_repeated_signals(features).iloc[0]
    assert repeated["valid_execution_year_count"] == 3
    assert repeated["strong_low_execution_year_count"] == 2
    assert repeated["strong_low_execution_repeat_2plus"]
    assert repeated["strong_low_execution_repeat_50pct"]
    assert repeated["strong_low_execution_consecutive_2"]


def test_types_are_nonexclusive() -> None:
    features = build_signal_features(_ranking_rows(), _patterns(), _hhi())
    repeated = build_repeated_signals(features)
    result = attach_signal_types(features, repeated)
    assert set(TYPE_COLUMNS).issubset(result.columns)
    row = result[result["fiscal_year"].eq(2024)].iloc[0]
    assert bool(row["type_accounting_adjustment_pattern"])
    assert bool(row["type_program_budget_concentration"])
    assert bool(row["type_multiple_financial_signals"])


def test_unknown_candidates_are_not_confirmed() -> None:
    broad = pd.DataFrame(
        {
            "fiscal_instrument": ["UNKNOWN"],
            "classification_project_id": ["p"],
            "ministry_code": ["075"],
            "analysis_ministry_name": ["보건복지부"],
            "account_type_classified": ["GENERAL_ACCOUNT"],
            "program_code": ["1000"],
            "program_name": ["융자 프로그램"],
            "activity_name": ["융자 지원"],
            "subactivity_code": ["1111"],
            "subactivity_name": ["대출 사업"],
            "fiscal_year": [2024],
            "original_budget_analysis_amount": [100],
            "source_project_year_id": ["p24"],
        }
    )
    result = unknown_manual_review_priority(broad).iloc[0]
    assert result["keyword_candidate"] == "LOAN"
    assert pd.isna(result["manual_confirmed_value"])
    assert result["review_status"] == "UNREVIEWED"
