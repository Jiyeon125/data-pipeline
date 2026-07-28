from __future__ import annotations

import pandas as pd

from analytics.mss_same_year_budget_check import (
    aggregate_program_year_performance,
    build_coverage,
    build_signal_summary,
    join_performance_and_financial,
)


def _indicator_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_indicator_id": "id-1",
                "ministry_name": "중소벤처기업부",
                "fiscal_year": 2024,
                "performance_program_name": "프로그램A",
                "source_program_code": None,
                "analysis_actual_value_numeric": 109.0,
                "analysis_official_achievement_rate_numeric": 7077.9,
                "analysis_achievement_rate_formula_review_required": False,
                "analysis_achievement_rate_formula_eligible": True,
            },
            {
                "source_indicator_id": "id-2",
                "ministry_name": "중소벤처기업부",
                "fiscal_year": 2024,
                "performance_program_name": "프로그램A",
                "source_program_code": None,
                "analysis_actual_value_numeric": 90.0,
                "analysis_official_achievement_rate_numeric": 90.0,
                "analysis_achievement_rate_formula_review_required": False,
                "analysis_achievement_rate_formula_eligible": True,
            },
            {
                "source_indicator_id": "id-3",
                "ministry_name": "중소벤처기업부",
                "fiscal_year": 2024,
                "performance_program_name": "프로그램A",
                "source_program_code": None,
                "analysis_actual_value_numeric": 10.0,
                "analysis_official_achievement_rate_numeric": 500.0,
                "analysis_achievement_rate_formula_review_required": True,
                "analysis_achievement_rate_formula_eligible": False,
            },
        ]
    )


def _overall_financial() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fiscal_year": 2024,
                "ministry_code": "102",
                "ministry_name": "중소벤처기업부",
                "program_code": "1200",
                "program_name": "프로그램A",
                "original_budget": 300,
                "current_budget": 330,
                "settlement_expenditure": 300,
                "execution_rate": 0.91,
                "financial_linkage_status": "COMPLETE",
                "financial_quality_level": "HIGH",
            }
        ]
    )


def _account_financial() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ministry_code": "102",
                "fiscal_year": 2024,
                "program_code": "1200",
                "account_type": "GENERAL_ACCOUNT",
                "program_name": "프로그램A",
                "original_budget": 100,
                "current_budget": 100,
                "settlement_expenditure": 95,
                "execution_rate": 0.95,
                "financial_linkage_status": "COMPLETE",
                "financial_quality_level": "HIGH",
                "project_count": 1,
                "analysis_included_project_count": 1,
                "execution_review_project_count": 0,
                "source_project_ids": '["p1"]',
            },
            {
                "ministry_code": "102",
                "fiscal_year": 2024,
                "program_code": "1200",
                "account_type": "FUND",
                "program_name": "프로그램A",
                "original_budget": 200,
                "current_budget": 230,
                "settlement_expenditure": 160,
                "execution_rate": 0.80,
                "financial_linkage_status": "COMPLETE",
                "financial_quality_level": "HIGH",
                "project_count": 1,
                "analysis_included_project_count": 1,
                "execution_review_project_count": 0,
                "source_project_ids": '["p2"]',
            },
        ]
    )


def test_program_aggregation_uses_counts_not_rate_average() -> None:
    result = aggregate_program_year_performance(_indicator_rows())

    assert len(result) == 1
    assert result.loc[0, "reported_rate_count"] == 3
    assert result.loc[0, "comparable_rate_count"] == 2
    assert result.loc[0, "below_target_count"] == 1
    assert result.loc[0, "at_or_above_target_count"] == 1
    assert result.loc[0, "formula_review_count"] == 1
    assert result.loc[0, "reported_performance_signal"] == "MIXED_COMPARABLE"
    assert not any("average" in column or "mean" in column for column in result.columns)


def test_join_keeps_account_types_separate() -> None:
    performance = aggregate_program_year_performance(_indicator_rows())
    result = join_performance_and_financial(
        performance,
        _overall_financial(),
        _account_financial(),
        ministry_code="102",
    )

    assert len(result) == 2
    assert set(result["account_type"]) == {"GENERAL_ACCOUNT", "FUND"}
    assert result["analysis_status"].eq("JOINT_ANALYSIS").all()
    assert result.loc[result["account_type"].eq("FUND"), "execution_below_90"].item()
    assert not result.loc[result["account_type"].eq("GENERAL_ACCOUNT"), "execution_below_90"].item()


def test_join_keeps_multiple_unmatched_programs_as_review_rows() -> None:
    matched = aggregate_program_year_performance(_indicator_rows())
    matched["source_program_code"] = "1200"
    performance = pd.concat(
        [
            matched,
            pd.DataFrame(
                [
                    {
                        **matched.iloc[0].to_dict(),
                        "performance_program_name": name,
                        "program_name_normalized": name,
                        "source_program_code": None,
                    }
                    for name in ("미매칭A", "미매칭B")
                ]
            ),
        ],
        ignore_index=True,
    )
    result = join_performance_and_financial(
        performance,
        _overall_financial(),
        _account_financial(),
        ministry_code="102",
    )

    review = result.loc[result["analysis_status"].eq("PROGRAM_MATCH_REVIEW")]
    assert set(review["performance_program_name"]) == {"미매칭A", "미매칭B"}
    assert review["account_type"].isna().all()


def test_coverage_and_signal_summary_do_not_mix_account_types() -> None:
    performance = aggregate_program_year_performance(_indicator_rows())
    analysis = join_performance_and_financial(
        performance,
        _overall_financial(),
        _account_financial(),
        ministry_code="102",
    )

    coverage = build_coverage(_account_financial(), analysis)
    signals = build_signal_summary(analysis)

    assert len(coverage) == 2
    assert coverage["original_budget_coverage"].eq(1).all()
    assert set(signals["account_type"]) == {"GENERAL_ACCOUNT", "FUND"}
    assert signals["program_year_account_count"].eq(1).all()
