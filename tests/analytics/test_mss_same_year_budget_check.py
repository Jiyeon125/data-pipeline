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
                "program_goal_number": "Ⅰ-1",
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
                "program_goal_number": "Ⅰ-1",
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
                "program_goal_number": "Ⅰ-1",
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
                "field_name": "산업·중소기업및에너지",
                "sector_name": "산업혁신지원",
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
                "field_name": "산업·중소기업및에너지",
                "sector_name": "산업혁신지원",
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
                "field_name": "산업·중소기업및에너지",
                "sector_name": "산업혁신지원",
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
    assert result.loc[0, "reported_target_status"] == "MIXED_COMPARABLE"
    assert (
        result.loc[0, "reported_target_status_interpretation"]
        == "OFFICIAL_REPORTED_TARGET_STATUS_NOT_POLICY_EFFECT"
    )
    assert result.loc[0, "indicator_coverage_status"] == "PARTIAL_REPORTED_RATE_COVERAGE"
    assert not result.loc[0, "performance_effect_eligible"]
    assert not any("average" in column or "mean" in column for column in result.columns)


def test_program_aggregation_normalizes_stray_whitespace_within_same_goal() -> None:
    indicators = _indicator_rows()
    indicators.loc[0, "performance_program_name"] = "프로 그램A"

    result = aggregate_program_year_performance(indicators)

    assert len(result) == 1
    assert result.loc[0, "indicator_count"] == 3


def test_program_aggregation_merges_goal_numbers_only_for_same_program_code() -> None:
    indicators = pd.concat([_indicator_rows(), _indicator_rows()], ignore_index=True)
    indicators["source_indicator_id"] = [f"id-{index}" for index in range(len(indicators))]
    indicators.loc[:2, "program_goal_number"] = "Ⅲ-2"
    indicators.loc[3:, "program_goal_number"] = "Ⅲ-3"
    indicators["source_program_code"] = "1300"

    same_program = aggregate_program_year_performance(indicators)
    indicators.loc[3:, "source_program_code"] = "2200"
    different_programs = aggregate_program_year_performance(indicators)
    indicators["source_program_code"] = "1300"
    indicators.loc[:2, "source_field_name"] = "교육"
    indicators.loc[:2, "source_sector_name"] = "교육일반"
    indicators.loc[3:, "source_field_name"] = "통신"
    indicators.loc[3:, "source_sector_name"] = "방송통신"
    different_hierarchies = aggregate_program_year_performance(indicators)

    assert len(same_program) == 1
    assert same_program.loc[0, "program_goal_number"] == "Ⅲ-2;Ⅲ-3"
    assert len(different_programs) == 2
    assert len(different_hierarchies) == 2


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


def test_join_does_not_mix_reused_program_codes_with_different_names() -> None:
    performance = aggregate_program_year_performance(_indicator_rows())
    other = {
        **_account_financial()[0:1].iloc[0].to_dict(),
        "program_name": "다른 프로그램",
        "original_budget": 999,
    }
    account_financial = pd.concat(
        [_account_financial(), pd.DataFrame([other])],
        ignore_index=True,
    )

    result = join_performance_and_financial(
        performance,
        _overall_financial(),
        account_financial,
        ministry_code="102",
    )

    assert len(result) == 2
    assert set(result["account_financial_program_name"]) == {"프로그램A"}
    assert result["account_original_budget"].sum() == 300


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
