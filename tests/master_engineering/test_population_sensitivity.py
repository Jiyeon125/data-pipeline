from __future__ import annotations

from pathlib import Path

import pandas as pd

from master_engineering.quality.population_sensitivity import (
    add_analysis_eligibility_flags,
    analyze_population_sensitivity,
    classify_exclusion_review_type,
)


def _row(
    project_id: str,
    year: int,
    *,
    scope: bool = True,
    quality: str = "CLEAR",
    exclusion_reason: str | None = None,
    classification_status: str = "RULE_CANDIDATE",
    comparison_group_size: int = 10,
    over_100: bool = False,
    account_code: str | None = "110",
) -> dict[str, object]:
    return {
        "source_project_year_id": f"{project_id}:{year}",
        "project_id": f"{project_id}:{year}",
        "classification_project_id": project_id,
        "fiscal_year": year,
        "ministry_code": "019",
        "ministry_name": "고용노동부",
        "account_code": account_code,
        "program_code": "1000" if account_code else None,
        "activity_code": "1001" if account_code else None,
        "subactivity_code": "1002" if account_code else None,
        "account_type_classified": "GENERAL_ACCOUNT",
        "fiscal_instrument": (
            "UNKNOWN" if classification_status == "MANUAL_REVIEW" else "SUBSIDY"
        ),
        "project_category": "PROGRAM_EXPENDITURE",
        "classification_status": classification_status,
        "comparison_group": "GENERAL_ACCOUNT|SUBSIDY|PROGRAM_EXPENDITURE",
        "comparison_group_size": comparison_group_size,
        "small_group_flag": comparison_group_size < 5,
        "analysis_included_classified": scope,
        "financial_quality_level": quality,
        "population_exclusion_reason": exclusion_reason,
        "is_masked": False,
        "masked_source_row_count": 0,
        "amount_parse_failure_row_count": 0,
        "settlement_duplicate_key_flag": False,
        "monthly_duplicate_review_required": False,
        "settlement_matching_status": "EXACT_HIERARCHY_UNIQUE",
        "settlement_budget_amount": 100,
        "budget_amount": 100,
        "settlement_current_budget_amount": 120,
        "current_budget_amount": 120,
        "settlement_expenditure_amount": 90,
        "execution_rate": 0.75 if not over_100 else 1.2,
        "execution_denominator_status": "APPLIED",
        "execution_rate_over_100_flag": over_100,
        "cumulative_expenditure_amount": 90,
        "cumulative_net_expenditure_amount": 0,
        "observed_month_count": 12,
        "required_project_hierarchy_available": account_code is not None,
        "reconciliation_analysis_eligible": True,
        "source_trace": f"source:{project_id}:{year}",
        "settlement_net_expenditure_amount": 90,
        "settlement_carryover_amount": 0,
        "settlement_unused_amount": 30,
        "execution_numerator_amount": 90,
        "execution_denominator_amount": 120,
    }


def test_excluded_rows_are_reclassified_into_three_types() -> None:
    scope = pd.Series(_row("scope", 2024, scope=False))
    blocking = pd.Series(_row("block", 2024, quality="BLOCKING"))
    limited = pd.Series(
        _row(
            "limited",
            2024,
            exclusion_reason="REQUIRED_PROJECT_HIERARCHY_MISSING",
            account_code=None,
        )
    )
    assert classify_exclusion_review_type(scope) == "SCOPE_EXCLUDED"
    assert classify_exclusion_review_type(blocking) == "DATA_QUALITY_BLOCKING"
    assert classify_exclusion_review_type(limited) == "ANALYSIS_SPECIFIC_LIMITATION"


def test_analysis_specific_flags_preserve_general_uses() -> None:
    frame = pd.DataFrame(
        [
            _row("good", 2023),
            _row("good", 2024),
            _row("over", 2024, over_100=True),
        ]
    )
    result = add_analysis_eligibility_flags(frame).set_index("classification_project_id")
    over = result.loc["over"]
    assert bool(over["budget_analysis_eligible"])
    assert bool(over["settlement_analysis_eligible"])
    assert not bool(over["execution_analysis_eligible"])
    assert not bool(over["ranking_analysis_eligible"])
    assert result.loc["good", "trend_analysis_eligible"].all()


def test_small_comparison_group_is_not_merged_and_cannot_rank() -> None:
    frame = pd.DataFrame([_row("small", 2024, comparison_group_size=2)])
    result = add_analysis_eligibility_flags(frame).iloc[0]
    assert result["comparison_group"] == "GENERAL_ACCOUNT|SUBSIDY|PROGRAM_EXPENDITURE"
    assert bool(result["ranking_small_group_limited_flag"])
    assert not bool(result["ranking_analysis_eligible"])


def _run(tmp_path: Path):
    included = pd.DataFrame(
        [
            _row("good", 2023),
            _row("good", 2024),
            _row("small", 2024, comparison_group_size=2),
        ]
    )
    excluded = pd.DataFrame(
        [
            _row(
                "scope",
                2024,
                scope=False,
                exclusion_reason="CLASSIFICATION_EXCLUSION:BASIC_OPERATION",
            ),
            _row(
                "block",
                2024,
                quality="BLOCKING",
                exclusion_reason="BLOCKING_FINANCIAL_QUALITY",
            ),
            _row(
                "limited",
                2024,
                account_code=None,
                exclusion_reason="REQUIRED_PROJECT_HIERARCHY_MISSING",
            ),
        ]
    )
    included_path = tmp_path / "included.parquet"
    excluded_path = tmp_path / "excluded.parquet"
    included.to_parquet(included_path, index=False)
    excluded.to_parquet(excluded_path, index=False)
    result = analyze_population_sensitivity(
        population_path=included_path,
        excluded_path=excluded_path,
        output_dir=tmp_path / "out",
        overwrite=True,
    )
    return included, excluded, result


def test_three_populations_are_nested_and_broad_recovers_limited_rows(
    tmp_path: Path,
) -> None:
    _, _, result = _run(tmp_path)
    broad_ids = set(result.broad_population["classification_project_id"])
    core_ids = set(result.core_financial_population["classification_project_id"])
    strict_ids = set(result.strict_ranking_population["classification_project_id"])
    assert "limited" in broad_ids
    assert strict_ids <= core_ids <= broad_ids
    assert result.summary["validation"]["population_nested"] is True


def test_amount_coverage_and_source_amounts_are_preserved(tmp_path: Path) -> None:
    included, excluded, result = _run(tmp_path)
    source = pd.concat([included, excluded])
    source["ministry_code"] = source["ministry_code"].astype("string")
    source = source.set_index(["source_project_year_id", "fiscal_year", "ministry_code"])
    augmented = result.full_frame.set_index(
        ["source_project_year_id", "fiscal_year", "ministry_code"]
    )
    for column in [
        "budget_amount",
        "current_budget_amount",
        "settlement_budget_amount",
        "settlement_current_budget_amount",
        "settlement_expenditure_amount",
    ]:
        pd.testing.assert_series_equal(
            source[column].sort_index(),
            augmented[column].sort_index(),
            check_names=False,
        )
    type_rows = result.amount_coverage.query("group_level == 'EXCLUSION_TYPE'")
    assert type_rows["row_count"].sum() == len(excluded)
    assert result.summary["validation"]["source_amount_changed_cell_count"] == 0


def test_bias_diagnostics_contains_required_group_dimensions(tmp_path: Path) -> None:
    _, _, result = _run(tmp_path)
    assert {
        "ministry_code",
        "fiscal_year",
        "account_type_classified",
        "project_size_bucket",
        "inclusion_rate",
        "exclusion_rate",
        "large_project_over_exclusion_flag",
    } <= set(result.bias_diagnostics.columns)
