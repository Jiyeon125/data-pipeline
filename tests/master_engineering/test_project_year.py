from __future__ import annotations

from pathlib import Path

import pandas as pd

from master_engineering.build_masters.project_year import (
    build_project_year_budget_base,
    build_project_year_financial_base,
)


def test_build_project_year_keeps_amount_types_separate(tmp_path: Path) -> None:
    records_path = tmp_path / "budget_records.parquet"
    events_path = tmp_path / "amount_events.parquet"
    base_record = {
        "dataset_id": "expenditure_budget_init",
        "fiscal_year": 2024,
        "ministry_code": "019",
        "ministry_name": "고용노동부",
        "account_code": "01",
        "account_name": "일반회계",
        "account_category_name": None,
        "field_name": "사회복지",
        "sector_name": "고용",
        "program_code": "1000",
        "program_name": "프로그램",
        "activity_code": "1100",
        "activity_name": "단위사업",
        "subactivity_code": "1110",
        "subactivity_name": "세부사업",
        "business_class_name": None,
        "finance_detail_name": None,
        "matching_status": "EXACT_HIERARCHY_UNIQUE",
        "source_record_id": "record:1",
        "duplicate_key_flag": False,
        "is_masked": False,
        "amount_parse_failed": False,
    }
    pd.DataFrame([base_record]).to_parquet(records_path, index=False)
    pd.DataFrame(
        [
            {
                "source_record_id": "record:1",
                "dataset_id": "expenditure_budget_init",
                "fiscal_year": 2024,
                "amount_type": "Y_YY_MEDI_KCUR_AMT",
                "amount": 100,
            },
            {
                "source_record_id": "record:1",
                "dataset_id": "expenditure_budget_init",
                "fiscal_year": 2024,
                "amount_type": "Y_YY_DFN_MEDI_KCUR_AMT",
                "amount": 90,
            },
        ]
    ).to_parquet(events_path, index=False)

    result = build_project_year_budget_base(
        budget_records_path=records_path,
        amount_events_path=events_path,
        output_dir=tmp_path / "masters",
    )

    assert len(result.project_year) == 1
    assert result.summary["project_year_primary_key_duplicate_count"] == 0
    assert set(result.amount_events["amount_type"]) == {
        "Y_YY_MEDI_KCUR_AMT",
        "Y_YY_DFN_MEDI_KCUR_AMT",
    }
    assert result.project_year.loc[0, "data_confidence_score"] == 1.0


def test_financial_base_does_not_guess_execution_rate_denominator(
    tmp_path: Path,
) -> None:
    budget_path = tmp_path / "budget_base.parquet"
    monthly_path = tmp_path / "monthly.parquet"
    pd.DataFrame(
        [
            {
                "table_id": "project_year_budget_base",
                "project_id": "code:2024:019:01:1000:1100:1110",
                "fiscal_year": 2024,
                "ministry_code": "019",
                "ministry_name": "고용노동부",
                "account_name": "일반회계",
                "program_name": "프로그램",
                "activity_name": "단위사업",
                "subactivity_name": "세부사업",
                "manual_review_required": False,
            }
        ]
    ).to_parquet(budget_path, index=False)
    pd.DataFrame(
        [
            {
                "fiscal_year": 2024,
                "execution_month": "202412",
                "ministry_code": "019",
                "ministry_name": "고용노동부",
                "account_code": "01",
                "account_name": "일반회계",
                "program_code": "1000",
                "program_name": "프로그램",
                "activity_code": "1100",
                "activity_name": "단위사업",
                "subactivity_code": "1110",
                "subactivity_name": "세부사업",
                "budget_amount": 1000,
                "current_budget_amount": 900,
                "cumulative_expenditure_amount": 800,
                "cumulative_net_expenditure_amount": 790,
                "is_masked": False,
                "manual_review_required": False,
            }
        ]
    ).to_parquet(monthly_path, index=False)

    result = build_project_year_financial_base(
        budget_base_path=budget_path,
        monthly_path=monthly_path,
        output_dir=tmp_path / "financial",
    )

    assert result.summary["both_source_count"] == 1
    assert result.summary["primary_key_duplicate_count"] == 0
    assert pd.isna(result.project_year.loc[0, "execution_rate"])
    assert result.project_year.loc[0, "execution_rate_status"] == "DENOMINATOR_RULE_NOT_CONFIRMED"
