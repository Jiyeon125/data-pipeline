"""financial v1 후속 대조 분석과 수기검토 우선순위를 생성합니다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

GROUP_KEY = ["ministry_code", "fiscal_year", "account_type"]
BLOCKING_REASONS = {
    "V1_PRIMARY_KEY_DUPLICATE",
    "SETTLEMENT_DUPLICATE_KEY",
    "SETTLEMENT_CODE_NO_MATCH",
    "SETTLEMENT_CODE_MULTIPLE_MATCHES",
    "FINANCIAL_BASE_MISSING",
    "UNSUPPORTED_ACCOUNT_TYPE",
}
# 결산 미연결·분모 없음은 행 전체 BLOCKING이 아니라 결산·집행률 분석만 제한한다.
ANALYSIS_RESTRICTED_REASONS = {
    "SETTLEMENT_MISSING",
    "MISSING_DENOMINATOR",
}
INFORMATIONAL_REASONS = {
    "ZERO_DENOMINATOR",
    "EXECUTION_RATE_OVER_1",
}
TOLERANCE_ABSOLUTE = 1_000
TOLERANCE_RELATIVE = 0.000001
SMALL_DIFFERENCE_RELATIVE = 0.001


@dataclass
class FinancialQualityFollowupResult:
    reconciliation: pd.DataFrame
    execution_rate_over_100: pd.DataFrame
    manual_review: pd.DataFrame
    summary: dict[str, Any]
    output_paths: list[Path]


def _reason_set(value: Any) -> set[str]:
    if pd.isna(value):
        return set()
    return {reason for reason in str(value).split(";") if reason}


def _difference_status(
    settlement: pd.Series,
    cumulative: pd.Series,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    absolute = (settlement - cumulative).abs().astype("Int64")
    relative = (absolute / settlement.abs().clip(lower=1)).astype("Float64")
    within = (absolute <= TOLERANCE_ABSOLUTE) | (relative <= TOLERANCE_RELATIVE)
    return absolute, relative, within


def _group_comparison(frame: pd.DataFrame) -> pd.DataFrame:
    comparable = frame[
        frame["settlement_join_status"].eq("BOTH")
        & frame["latest_execution_month"].astype("string").str.endswith("12")
        & frame["settlement_expenditure_amount"].notna()
        & frame["cumulative_expenditure_amount"].notna()
        & frame["cumulative_net_expenditure_amount"].notna()
    ].copy()
    comparable["gross_absolute_difference"] = (
        comparable["settlement_expenditure_amount"] - comparable["cumulative_expenditure_amount"]
    ).abs()
    comparable["net_absolute_difference"] = (
        comparable["settlement_expenditure_amount"]
        - comparable["cumulative_net_expenditure_amount"]
    ).abs()
    comparable["gross_better"] = (
        comparable["gross_absolute_difference"] < comparable["net_absolute_difference"]
    )
    comparable["net_better"] = (
        comparable["net_absolute_difference"] < comparable["gross_absolute_difference"]
    )
    comparable["equal_difference"] = (
        comparable["gross_absolute_difference"] == comparable["net_absolute_difference"]
    )
    comparable["net_zero"] = comparable["cumulative_net_expenditure_amount"].eq(0)
    comparable["gross_within_tolerance"] = (
        comparable["gross_absolute_difference"] <= TOLERANCE_ABSOLUTE
    ) | (
        comparable["gross_absolute_difference"]
        / comparable["settlement_expenditure_amount"].abs().clip(lower=1)
        <= TOLERANCE_RELATIVE
    )
    comparable["net_within_tolerance"] = (
        comparable["net_absolute_difference"] <= TOLERANCE_ABSOLUTE
    ) | (
        comparable["net_absolute_difference"]
        / comparable["settlement_expenditure_amount"].abs().clip(lower=1)
        <= TOLERANCE_RELATIVE
    )
    grouped = (
        comparable.groupby(GROUP_KEY, dropna=False)
        .agg(
            group_observation_count=("project_id", "size"),
            group_gross_better_count=("gross_better", "sum"),
            group_net_better_count=("net_better", "sum"),
            group_equal_difference_count=("equal_difference", "sum"),
            group_gross_mean_absolute_difference=(
                "gross_absolute_difference",
                "mean",
            ),
            group_net_mean_absolute_difference=("net_absolute_difference", "mean"),
            group_gross_tolerance_rate=("gross_within_tolerance", "mean"),
            group_net_tolerance_rate=("net_within_tolerance", "mean"),
            group_cumulative_net_zero_rate=("net_zero", "mean"),
        )
        .reset_index()
    )
    grouped["group_preferred_cumulative_field"] = "EQUAL"
    grouped.loc[
        grouped["group_gross_mean_absolute_difference"]
        < grouped["group_net_mean_absolute_difference"],
        "group_preferred_cumulative_field",
    ] = "cumulative_expenditure_amount"
    grouped.loc[
        grouped["group_net_mean_absolute_difference"]
        < grouped["group_gross_mean_absolute_difference"],
        "group_preferred_cumulative_field",
    ] = "cumulative_net_expenditure_amount"
    return grouped


def _cause_type(row: pd.Series) -> str:
    reasons = _reason_set(row.get("quality_issue_reasons"))
    if reasons & {
        "SETTLEMENT_DUPLICATE_KEY",
        "SETTLEMENT_CODE_NO_MATCH",
        "SETTLEMENT_CODE_MULTIPLE_MATCHES",
        "MONTHLY_LATEST_DUPLICATE",
    }:
        return "MATCHING_OR_GRAIN_ISSUE"
    if row.get("account_type") == "FUND":
        return "FUND_ACCOUNTING_BASIS_DIFFERENCE"
    relative = row.get("gross_relative_difference")
    if pd.isna(relative):
        return "AMOUNT_NOT_COMPARABLE"
    if float(relative) <= SMALL_DIFFERENCE_RELATIVE:
        return "SMALL_CLOSING_DIFFERENCE"
    if float(relative) <= 0.01:
        return "MODERATE_CLOSING_DIFFERENCE"
    return "MATERIAL_SCOPE_OR_CLOSING_DIFFERENCE"


def _priority(row: pd.Series) -> str:
    reasons = _reason_set(row.get("quality_issue_reasons"))
    if reasons & BLOCKING_REASONS:
        return "BLOCKING"
    relative = row.get("settlement_vs_december_relative_difference")
    if reasons and reasons <= INFORMATIONAL_REASONS:
        return "INFORMATIONAL"
    if (
        row.get("settlement_reconciliation_status") == "MISMATCH"
        and pd.notna(relative)
        and float(relative) <= SMALL_DIFFERENCE_RELATIVE
    ):
        return "INFORMATIONAL"
    return "NON_BLOCKING"


def _auto_resolution(row: pd.Series) -> str:
    priority = row["review_priority"]
    reasons = _reason_set(row.get("quality_issue_reasons"))
    if priority == "BLOCKING":
        return "NOT_AUTO_RESOLVED"
    if "SETTLEMENT_MISSING" in reasons:
        return "RESTRICT_SETTLEMENT_AND_EXECUTION_RATE_KEEP_BUDGET_SCOPE"
    if "MISSING_DENOMINATOR" in reasons:
        return "EXCLUDE_EXECUTION_RATE_MISSING_DENOMINATOR"
    if "ZERO_DENOMINATOR" in reasons:
        return "EXCLUDE_EXECUTION_RATE_DENOMINATOR_ZERO"
    if row.get("settlement_reconciliation_status") == "MISMATCH":
        return "USE_SETTLEMENT_ANNUAL_KEEP_GROSS_CUMULATIVE_MONTHLY"
    if "DECEMBER_CUMULATIVE_MISSING" in reasons:
        return "USE_SETTLEMENT_ANNUAL_MONTHLY_RECONCILIATION_UNAVAILABLE"
    if reasons & {"EXECUTION_RATE_OVER_1", "EXECUTION_RATE_EXTREME"}:
        return "KEEP_RATE_AND_FLAG_NO_AUTOMATIC_CLIPPING"
    if "MONTHLY_LATEST_DUPLICATE" in reasons:
        return "USE_SETTLEMENT_ANNUAL_EXCLUDE_MONTHLY_PATTERN"
    return "KEEP_ORIGINAL_VALUES_WITH_INFORMATIONAL_FLAG"


def analyze_financial_quality_followup(
    *,
    input_path: Path,
    output_dir: Path,
    overwrite: bool = False,
) -> FinancialQualityFollowupResult:
    frame = pd.read_parquet(input_path)
    group_comparison = _group_comparison(frame)

    mismatch = frame[frame["settlement_reconciliation_status"].eq("MISMATCH")].copy()
    (
        mismatch["gross_absolute_difference"],
        mismatch["gross_relative_difference"],
        mismatch["gross_within_tolerance"],
    ) = _difference_status(
        mismatch["settlement_expenditure_amount"],
        mismatch["cumulative_expenditure_amount"],
    )
    (
        mismatch["net_absolute_difference"],
        mismatch["net_relative_difference"],
        mismatch["net_within_tolerance"],
    ) = _difference_status(
        mismatch["settlement_expenditure_amount"],
        mismatch["cumulative_net_expenditure_amount"],
    )
    mismatch["individual_preferred_cumulative_field"] = "EQUAL"
    mismatch.loc[
        mismatch["gross_absolute_difference"] < mismatch["net_absolute_difference"],
        "individual_preferred_cumulative_field",
    ] = "cumulative_expenditure_amount"
    mismatch.loc[
        mismatch["net_absolute_difference"] < mismatch["gross_absolute_difference"],
        "individual_preferred_cumulative_field",
    ] = "cumulative_net_expenditure_amount"
    mismatch["cumulative_net_zero_flag"] = mismatch["cumulative_net_expenditure_amount"].eq(0)
    mismatch["recommended_cumulative_field"] = mismatch["individual_preferred_cumulative_field"]
    mismatch["cumulative_recommendation_basis"] = "LOWER_ABSOLUTE_DIFFERENCE"
    mismatch.loc[mismatch["cumulative_net_zero_flag"], "recommended_cumulative_field"] = (
        "cumulative_expenditure_amount"
    )
    mismatch.loc[mismatch["cumulative_net_zero_flag"], "cumulative_recommendation_basis"] = (
        "NET_CUMULATIVE_ZERO_UNAVAILABLE"
    )
    mismatch["reconciliation_cause_type"] = mismatch.apply(_cause_type, axis=1)
    mismatch["annual_analysis_resolution"] = "USE_SETTLEMENT_EXPENDITURE_AMOUNT"
    mismatch["monthly_pattern_resolution"] = "KEEP_CUMULATIVE_EXPENDITURE_AMOUNT_WITH_QUALITY_FLAG"
    reconciliation = mismatch.merge(
        group_comparison,
        how="left",
        on=GROUP_KEY,
        validate="many_to_one",
    )

    rate_columns = [
        "project_id",
        "fiscal_year",
        "ministry_code",
        "ministry_name",
        "account_type",
        "account_type_basis",
        "account_code",
        "account_name",
        "program_code",
        "program_name",
        "activity_code",
        "activity_name",
        "subactivity_code",
        "subactivity_name",
        "execution_rate",
        "execution_rate_unit",
        "execution_numerator_amount",
        "execution_denominator_amount",
        "execution_denominator_source",
        "execution_denominator_status",
        "settlement_expenditure_amount",
        "settlement_current_budget_amount",
        "current_budget_amount",
        "source_file_settlement",
        "source_path_settlement",
        "quality_issue_reasons",
    ]
    available_rate_columns = [column for column in rate_columns if column in frame]
    execution_rate_over_100 = frame.loc[
        frame["execution_rate"].gt(1), available_rate_columns
    ].copy()
    execution_rate_over_100["over_100_class"] = "OVER_100_TO_200"
    execution_rate_over_100.loc[execution_rate_over_100["execution_rate"] > 2, "over_100_class"] = (
        "OVER_200"
    )
    execution_rate_over_100["automatic_action"] = "KEEP_ORIGINAL_RATE_NO_CLIPPING_REVIEW_SOURCES"

    manual_review = frame[frame["manual_review_required_v1"]].copy()
    manual_review["review_priority"] = manual_review.apply(_priority, axis=1)
    manual_review["automatic_resolution_rule"] = manual_review.apply(_auto_resolution, axis=1)
    manual_review["blocks_annual_financial_analysis"] = manual_review["review_priority"].eq(
        "BLOCKING"
    )
    manual_review["priority_reason"] = manual_review["quality_issue_reasons"]
    prioritized_columns = [
        "project_id",
        "fiscal_year",
        "ministry_code",
        "ministry_name",
        "account_type",
        "program_name",
        "activity_name",
        "subactivity_name",
        "review_priority",
        "blocks_annual_financial_analysis",
        "automatic_resolution_rule",
        "priority_reason",
        "settlement_join_status",
        "settlement_reconciliation_status",
        "execution_denominator_status",
        "execution_rate",
        "settlement_vs_december_difference",
        "settlement_vs_december_relative_difference",
        "quality_issue_reasons",
    ]
    manual_review = manual_review[
        [column for column in prioritized_columns if column in manual_review]
    ].sort_values(
        ["review_priority", "fiscal_year", "ministry_code", "project_id"],
        key=lambda series: (
            series.map({"BLOCKING": 0, "NON_BLOCKING": 1, "INFORMATIONAL": 2})
            if series.name == "review_priority"
            else series
        ),
    )

    priority_counts = manual_review["review_priority"].value_counts().sort_index().to_dict()
    individual_preference_counts = (
        reconciliation["individual_preferred_cumulative_field"]
        .value_counts()
        .sort_index()
        .to_dict()
    )
    recommended_field_counts = (
        reconciliation["recommended_cumulative_field"].value_counts().sort_index().to_dict()
    )
    group_preference_counts = (
        group_comparison["group_preferred_cumulative_field"].value_counts().sort_index().to_dict()
    )
    cause_counts = reconciliation["reconciliation_cause_type"].value_counts().sort_index().to_dict()
    group_records = json.loads(group_comparison.to_json(orient="records", force_ascii=False))
    blocking_count = int(manual_review["review_priority"].eq("BLOCKING").sum())
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source_file": str(input_path),
        "source_row_count": len(frame),
        "mismatch_input_count": len(mismatch),
        "reconciliation_output_count": len(reconciliation),
        "individual_preferred_cumulative_field_counts": individual_preference_counts,
        "recommended_cumulative_field_counts": recommended_field_counts,
        "group_preferred_cumulative_field_counts": group_preference_counts,
        "cumulative_net_zero_count_in_mismatch": int(
            reconciliation["cumulative_net_zero_flag"].sum()
        ),
        "reconciliation_cause_type_counts": cause_counts,
        "group_comparison": group_records,
        "execution_rate_over_100_count": len(execution_rate_over_100),
        "execution_rate_over_200_count": int(execution_rate_over_100["execution_rate"].gt(2).sum()),
        "original_manual_review_count": len(manual_review),
        "manual_review_priority_counts": priority_counts,
        "blocking_count": blocking_count,
        "blocking_rate_of_original_manual_review": (
            blocking_count / len(manual_review) if len(manual_review) else 0.0
        ),
        "auto_resolved_or_nonblocking_count": len(manual_review) - blocking_count,
        "rules": {
            "annual_amount_authority": (
                "결산 지출금액을 연간 분석값으로 사용하며 원본 월별 누계는 수정하지 않음"
            ),
            "monthly_cumulative_choice": (
                "개별·그룹 절대오차가 작은 누계 후보를 표시하되 값을 대체하지 않음"
            ),
            "net_cumulative_zero": ("순누계가 0인 경우 대체값으로 자동 채택하지 않음"),
            "blocking": sorted(BLOCKING_REASONS),
            "informational": sorted(INFORMATIONAL_REASONS),
            "small_difference_relative_threshold": SMALL_DIFFERENCE_RELATIVE,
            "reconciliation_absolute_tolerance": TOLERANCE_ABSOLUTE,
            "reconciliation_relative_tolerance": TOLERANCE_RELATIVE,
            "execution_rate": "1 초과 값을 자르지 않고 원본 분자·분모와 함께 분리",
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = [
        output_dir / "financial_reconciliation_analysis.csv",
        output_dir / "execution_rate_over_100.csv",
        output_dir / "manual_review_prioritized.csv",
        output_dir / "reconciliation_summary.json",
    ]
    existing = [path for path in output_paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"출력 파일이 이미 있습니다: {existing[0]}")
    reconciliation.to_csv(output_paths[0], index=False, encoding="utf-8-sig")
    execution_rate_over_100.to_csv(output_paths[1], index=False, encoding="utf-8-sig")
    manual_review.to_csv(output_paths[2], index=False, encoding="utf-8-sig")
    output_paths[3].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return FinancialQualityFollowupResult(
        reconciliation,
        execution_rate_over_100,
        manual_review,
        summary,
        output_paths,
    )
