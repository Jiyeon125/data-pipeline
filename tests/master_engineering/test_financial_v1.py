from __future__ import annotations

from pathlib import Path

import pandas as pd

from master_engineering.build_masters.financial_v1 import build_financial_v1


def test_financial_v1_reconciles_and_applies_general_account_rule(
    tmp_path: Path,
) -> None:
    financial_path = tmp_path / "financial.parquet"
    settlement_path = tmp_path / "settlement.parquet"
    project_id = "code:2024:019:01:1000:1100:1110"
    pd.DataFrame(
        [
            {
                "project_id": project_id,
                "fiscal_year": 2024,
                "ministry_code": "019",
                "account_name": "일반회계",
                "latest_execution_month": "202412",
                "current_budget_amount": 1_100,
                "cumulative_expenditure_amount": 900,
                "monthly_duplicate_review_required": False,
            }
        ]
    ).to_parquet(financial_path, index=False)
    pd.DataFrame(
        [
            {
                "project_id": project_id,
                "fiscal_year": 2024,
                "ministry_code": "019",
                "ministry_name": "고용노동부",
                "account_name": "일반회계",
                "account_category_name": None,
                "field_name": "사회복지",
                "sector_name": "고용",
                "program_name": "프로그램",
                "activity_name": "단위사업",
                "subactivity_name": "세부사업",
                "matching_status": "EXACT_HIERARCHY_UNIQUE",
                "source_file": "settlement.csv",
                "source_path": "settlement.csv",
                "settlement_budget_amount": 1_000,
                "settlement_adjustment_amount": 100,
                "settlement_current_budget_amount": 1_100,
                "settlement_expenditure_amount": 900,
                "settlement_net_expenditure_amount": 890,
                "settlement_carryover_amount": 50,
                "settlement_unused_amount": 150,
            }
        ]
    ).to_parquet(settlement_path, index=False)

    result = build_financial_v1(
        financial_base_path=financial_path,
        settlement_path=settlement_path,
        output_dir=tmp_path / "out",
    )

    row = result.frame.iloc[0]
    assert row["settlement_reconciliation_status"] == "EXACT"
    assert row["execution_denominator_amount"] == 1_100
    assert row["execution_rate"] == 900 / 1_100
    assert result.summary["primary_key_duplicate_count"] == 0
    assert result.summary["data_dictionary_column_count"] == result.summary["table_column_count"]


def test_financial_v1_uses_monthly_current_amount_for_fund(tmp_path: Path) -> None:
    financial_path = tmp_path / "financial.parquet"
    settlement_path = tmp_path / "settlement.parquet"
    project_id = "code:2024:019:02:1000:1100:1110"
    pd.DataFrame(
        [
            {
                "project_id": project_id,
                "fiscal_year": 2024,
                "ministry_code": "019",
                "account_name": "고용보험기금",
                "latest_execution_month": "202412",
                "current_budget_amount": 2_000,
                "cumulative_expenditure_amount": 1_000,
                "monthly_duplicate_review_required": False,
            }
        ]
    ).to_parquet(financial_path, index=False)
    pd.DataFrame(
        [
            {
                "project_id": project_id,
                "fiscal_year": 2024,
                "ministry_code": "019",
                "ministry_name": "고용노동부",
                "account_name": "고용보험기금",
                "account_category_name": None,
                "field_name": "사회복지",
                "sector_name": "고용",
                "program_name": "프로그램",
                "activity_name": "단위사업",
                "subactivity_name": "세부사업",
                "matching_status": "EXACT_HIERARCHY_UNIQUE",
                "source_file": "settlement.csv",
                "source_path": "settlement.csv",
                "settlement_budget_amount": 1_500,
                "settlement_adjustment_amount": 0,
                "settlement_current_budget_amount": 1_500,
                "settlement_expenditure_amount": 1_000,
                "settlement_net_expenditure_amount": 1_000,
                "settlement_carryover_amount": 0,
                "settlement_unused_amount": 500,
            }
        ]
    ).to_parquet(settlement_path, index=False)

    result = build_financial_v1(
        financial_base_path=financial_path,
        settlement_path=settlement_path,
        output_dir=tmp_path / "out",
    )

    row = result.frame.iloc[0]
    assert row["account_type"] == "FUND"
    assert row["execution_denominator_amount"] == 2_000
    assert row["execution_rate"] == 0.5
