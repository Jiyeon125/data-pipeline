from __future__ import annotations

import pandas as pd

from master_engineering.build_masters.core_v2_shadow import build_core_v2_shadow


def _input() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "project_id": ["legacy-a", "legacy-b", "legacy-c", "legacy-d"],
            "classification_project_id": ["class-a", "class-a", "blank", "blank"],
            "fiscal_year": [2022, 2022, 2022, 2023],
            "ministry_code": ["019", "019", "019", "019"],
            "account_code": ["110", "120", "110", "110"],
            "account_type": [
                "GENERAL_ACCOUNT",
                "SPECIAL_ACCOUNT",
                "GENERAL_ACCOUNT",
                "GENERAL_ACCOUNT",
            ],
            "account_name": ["일반회계", "특별회계", "일반회계", "일반회계"],
            "program_code": ["1000", "1000", pd.NA, pd.NA],
            "activity_code": ["1010", "1010", pd.NA, pd.NA],
            "subactivity_code": ["300", "300", pd.NA, pd.NA],
            "program_name": ["프로그램", "프로그램", pd.NA, pd.NA],
            "activity_name": ["단위사업 A", "단위사업 B", pd.NA, pd.NA],
            "subactivity_name": ["세부사업 A", "세부사업 B", pd.NA, pd.NA],
            "analysis_original_budget": [100, 200, 300, 400],
            "analysis_current_budget": [110, 210, 310, 410],
            "analysis_settlement_expenditure": [90, 180, 250, 350],
            "analysis_original_budget_source": ["budget"] * 4,
            "analysis_current_budget_source": ["current"] * 4,
            "analysis_settlement_expenditure_source": ["settlement"] * 4,
            "in_broad_population": [True, True, False, False],
            "in_core_financial_population": [True, True, False, False],
            "budget_analysis_eligible": [True] * 4,
            "execution_analysis_eligible": [True, True, False, False],
            "settlement_analysis_eligible": [True] * 4,
            "ranking_analysis_eligible": [True, True, False, False],
            "exclusion_reason": [pd.NA, pd.NA, "TEST_EXCLUSION", "TEST_EXCLUSION"],
            "project_category": ["PROGRAM_EXPENDITURE"] * 4,
            "quality_issue_reasons": [pd.NA] * 4,
            "source_trace": ["a.csv", "b.csv", "c.csv", "d.csv"],
        }
    )


def test_core_v2_shadow_separates_identity_account_and_amount_grains(tmp_path) -> None:
    input_path = tmp_path / "input.parquet"
    _input().to_parquet(input_path, index=False)

    result = build_core_v2_shadow(
        input_path=input_path,
        output_dir=tmp_path / "shadow",
        ministry_codes=("019",),
        fiscal_years=(2022, 2023),
    )

    tables = result.tables
    assert len(tables["source_observation"]) == 4
    assert len(tables["project_entity"]) == 3
    assert len(tables["project_version"]) == 3
    assert len(tables["account_or_fund"]) == 2
    assert len(tables["budget_fact"]) == 8
    assert len(tables["execution_fact"]) == 4
    assert len(tables["identity_resolution_case"]) == 2
    assert (
        tables["project_version"]["name_resolution_status"].eq("CONFLICTING_SOURCE_NAMES").sum()
        == 1
    )
    assert tables["identity_resolution_case"]["project_entity_id"].nunique() == 2
    assert result.summary["amount_sums"] == {
        "original_budget": 1000,
        "current_budget": 1040,
        "settlement_expenditure": 870,
    }
    assert result.summary["analysis_eligible_amount_sums"] == {
        "original_budget": 300,
        "current_budget": 320,
        "settlement_expenditure": 270,
    }
    assert all(result.summary["checks"].values())


def test_core_v2_shadow_is_deterministic_for_same_input(tmp_path) -> None:
    input_path = tmp_path / "input.parquet"
    _input().to_parquet(input_path, index=False)

    first = build_core_v2_shadow(
        input_path=input_path,
        output_dir=tmp_path / "first",
        ministry_codes=("019",),
        fiscal_years=(2022, 2023),
    )
    second = build_core_v2_shadow(
        input_path=input_path,
        output_dir=tmp_path / "second",
        ministry_codes=("019",),
        fiscal_years=(2022, 2023),
    )

    for name in first.tables:
        pd.testing.assert_frame_equal(
            first.tables[name].reset_index(drop=True),
            second.tables[name].reset_index(drop=True),
        )
