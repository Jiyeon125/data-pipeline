from __future__ import annotations

from pathlib import Path

import pandas as pd

from master_engineering.quality.financial_followup import (
    analyze_financial_quality_followup,
)


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "project_id": "code:2024:019:01:1000:1100:1110",
        "fiscal_year": 2024,
        "ministry_code": "019",
        "ministry_name": "고용노동부",
        "account_type": "GENERAL_ACCOUNT",
        "account_type_basis": "ACCOUNT_NAME",
        "account_code": "01",
        "account_name": "일반회계",
        "program_code": "1000",
        "program_name": "프로그램",
        "activity_code": "1100",
        "activity_name": "단위사업",
        "subactivity_code": "1110",
        "subactivity_name": "세부사업",
        "latest_execution_month": "202412",
        "settlement_join_status": "BOTH",
        "settlement_reconciliation_status": "MISMATCH",
        "settlement_expenditure_amount": 1_000,
        "cumulative_expenditure_amount": 999,
        "cumulative_net_expenditure_amount": 0,
        "settlement_vs_december_difference": 1,
        "settlement_vs_december_relative_difference": 0.001,
        "execution_rate": 1.1,
        "execution_rate_unit": "ratio",
        "execution_numerator_amount": 1_100,
        "execution_denominator_amount": 1_000,
        "execution_denominator_source": "settlement",
        "execution_denominator_status": "APPLIED",
        "settlement_current_budget_amount": 1_000,
        "current_budget_amount": 1_000,
        "source_file_settlement": "settlement.csv",
        "source_path_settlement": "settlement.csv",
        "quality_issue_reasons": "DECEMBER_SETTLEMENT_MISMATCH;EXECUTION_RATE_OVER_1",
        "manual_review_required_v1": True,
    }
    row.update(overrides)
    return row


def test_followup_prefers_gross_and_makes_small_difference_informational(
    tmp_path: Path,
) -> None:
    source = tmp_path / "financial.parquet"
    pd.DataFrame([_row()]).to_parquet(source, index=False)

    result = analyze_financial_quality_followup(
        input_path=source,
        output_dir=tmp_path / "out",
    )

    assert (
        result.reconciliation.loc[0, "individual_preferred_cumulative_field"]
        == "cumulative_expenditure_amount"
    )
    assert (
        result.reconciliation.loc[0, "recommended_cumulative_field"]
        == "cumulative_expenditure_amount"
    )
    assert result.manual_review.loc[0, "review_priority"] == "INFORMATIONAL"
    assert len(result.execution_rate_over_100) == 1


def test_missing_denominator_remains_blocking(tmp_path: Path) -> None:
    source = tmp_path / "financial.parquet"
    pd.DataFrame(
        [
            _row(
                quality_issue_reasons="SETTLEMENT_MISSING;MISSING_DENOMINATOR",
                settlement_join_status="FINANCIAL_ONLY",
                settlement_reconciliation_status="NOT_COMPARABLE_SOURCE_MISSING",
                settlement_expenditure_amount=None,
                execution_rate=None,
            )
        ]
    ).to_parquet(source, index=False)

    result = analyze_financial_quality_followup(
        input_path=source,
        output_dir=tmp_path / "out",
    )

    assert result.manual_review.loc[0, "review_priority"] == "BLOCKING"
    assert result.summary["blocking_count"] == 1
