"""예산 API 정규화 결과에서 사업-연도 기준 테이블을 구축합니다."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_DATASETS = {
    "expenditure_budget_init",
    "total_expenditure_project",
    "expenditure_budget_add",
}
CODE_KEY = (
    "fiscal_year",
    "ministry_code",
    "account_code",
    "program_code",
    "activity_code",
    "subactivity_code",
)
NAME_KEY = (
    "fiscal_year",
    "ministry_code",
    "account_name",
    "program_name",
    "activity_name",
    "subactivity_name",
)
DIMENSION_COLUMNS = (
    "ministry_name",
    "account_code",
    "account_name",
    "account_category_name",
    "field_name",
    "sector_name",
    "program_code",
    "program_name",
    "activity_code",
    "activity_name",
    "subactivity_code",
    "subactivity_name",
    "business_class_name",
    "finance_detail_name",
)


@dataclass
class ProjectYearBuildResult:
    project_year: pd.DataFrame
    amount_events: pd.DataFrame
    issues: pd.DataFrame
    summary: dict[str, Any]
    output_paths: list[Path]


@dataclass
class FinancialProjectYearBuildResult:
    project_year: pd.DataFrame
    issues: pd.DataFrame
    summary: dict[str, Any]
    output_paths: list[Path]


def _digest(*values: Any) -> str:
    raw = "\x1f".join("" if value is None else str(value) for value in values)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _first_not_null(series: pd.Series) -> Any:
    values = series.dropna()
    return values.iloc[0] if not values.empty else pd.NA


def _project_id(row: pd.Series) -> str:
    codes = [row.get(column) for column in CODE_KEY]
    if all(pd.notna(value) and str(value) for value in codes):
        return "code:" + ":".join(str(value) for value in codes)
    return f"name:{_digest(*(row.get(column) for column in NAME_KEY))}"


def _status(series: pd.Series) -> str:
    priority = {
        "EXACT_HIERARCHY_UNIQUE": 0,
        "EXACT_PROJECT_NAME_UNIQUE": 1,
        "MULTIPLE_MATCHES": 2,
        "NO_MATCH": 3,
    }
    values = [str(value) for value in series.dropna()]
    return min(values, key=lambda value: priority.get(value, 99)) if values else "NO_MATCH"


def build_project_year_budget_base(
    *,
    budget_records_path: Path,
    amount_events_path: Path,
    output_dir: Path,
    overwrite: bool = False,
) -> ProjectYearBuildResult:
    records = pd.read_parquet(budget_records_path)
    events = pd.read_parquet(amount_events_path)
    project_records = records[records["dataset_id"].isin(PROJECT_DATASETS)].copy()
    project_records["project_id"] = project_records.apply(_project_id, axis=1)

    aggregations: dict[str, Any] = {
        column: (column, _first_not_null) for column in DIMENSION_COLUMNS
    }
    aggregations.update(
        {
            "matching_status": ("matching_status", _status),
            "source_record_count": ("source_record_id", "nunique"),
            "source_dataset_count": ("dataset_id", "nunique"),
            "source_datasets": (
                "dataset_id",
                lambda values: json.dumps(sorted(set(values.dropna())), ensure_ascii=False),
            ),
            "duplicate_source_row_count": ("duplicate_key_flag", "sum"),
            "masked_source_row_count": ("is_masked", "sum"),
            "amount_parse_failure_row_count": ("amount_parse_failed", "sum"),
        }
    )
    project_year = (
        project_records.groupby(
            ["project_id", "fiscal_year", "ministry_code"],
            dropna=False,
            sort=True,
        )
        .agg(**aggregations)
        .reset_index()
    )
    project_year.insert(0, "table_id", "project_year_budget_base")
    project_year["analysis_included"] = True
    project_year["exclusion_reason"] = pd.NA
    project_year["structural_missing_flag"] = False
    project_year["manual_review_required"] = (
        ~project_year["matching_status"].isin(
            {"EXACT_HIERARCHY_UNIQUE", "EXACT_PROJECT_NAME_UNIQUE"}
        )
        | (project_year["duplicate_source_row_count"] > 0)
        | (project_year["masked_source_row_count"] > 0)
        | (project_year["amount_parse_failure_row_count"] > 0)
    )
    project_year["data_confidence_score"] = (
        1.0
        - 0.45
        * ~project_year["matching_status"].isin(
            {"EXACT_HIERARCHY_UNIQUE", "EXACT_PROJECT_NAME_UNIQUE"}
        )
        - 0.2 * (project_year["duplicate_source_row_count"] > 0)
        - 0.2 * (project_year["masked_source_row_count"] > 0)
        - 0.15 * (project_year["amount_parse_failure_row_count"] > 0)
    ).clip(lower=0.0)

    project_source_ids = set(project_records["source_record_id"])
    project_events = events[events["source_record_id"].isin(project_source_ids)].copy()
    source_to_project = project_records[["source_record_id", "project_id"]].drop_duplicates()
    project_events = project_events.merge(
        source_to_project,
        how="left",
        on="source_record_id",
        validate="many_to_one",
    )
    project_events["amount_event_id"] = project_events.apply(
        lambda row: f"amount:{_digest(row['source_record_id'], row['amount_type'])}",
        axis=1,
    )
    project_events["exact_duplicate_flag"] = project_events.duplicated(
        [
            "project_id",
            "dataset_id",
            "fiscal_year",
            "amount_type",
            "amount",
        ],
        keep=False,
    )

    primary_key_duplicate = project_year.duplicated(
        ["ministry_code", "fiscal_year", "project_id"], keep=False
    )
    issues = project_year.loc[
        project_year["manual_review_required"] | primary_key_duplicate,
        [
            "project_id",
            "fiscal_year",
            "ministry_code",
            "matching_status",
            "source_record_count",
            "duplicate_source_row_count",
            "data_confidence_score",
        ],
    ].copy()
    issues.insert(0, "issue_type", "PROJECT_YEAR_MANUAL_REVIEW")

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "budget_record_input_count": len(records),
        "project_level_input_count": len(project_records),
        "project_year_row_count": len(project_year),
        "project_year_primary_key_duplicate_count": int(primary_key_duplicate.sum()),
        "project_amount_event_count": len(project_events),
        "project_amount_exact_duplicate_count": int(project_events["exact_duplicate_flag"].sum()),
        "manual_review_row_count": int(project_year["manual_review_required"].sum()),
        "matching_status_counts": (
            project_year["matching_status"].value_counts().sort_index().to_dict()
        ),
        "note": (
            "예산 API만 반영한 중간 기준 테이블입니다. 결산 CSV와 성과 문서가 "
            "연결되기 전에는 최종 master로 사용하지 않습니다."
        ),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = [
        output_dir / "project_year_budget_base.parquet",
        output_dir / "project_amount_event.parquet",
        output_dir / "project_year_quality_issues.csv",
        output_dir / "project_year_build_summary.json",
    ]
    existing = [path for path in output_paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"출력 파일이 이미 있습니다: {existing[0]}")
    project_year.to_parquet(output_paths[0], index=False)
    project_events.to_parquet(output_paths[1], index=False)
    issues.to_csv(output_paths[2], index=False, encoding="utf-8-sig")
    output_paths[3].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return ProjectYearBuildResult(
        project_year=project_year,
        amount_events=project_events,
        issues=issues,
        summary=summary,
        output_paths=output_paths,
    )


def _monthly_project_id(row: pd.Series) -> str:
    return "code:" + ":".join(str(row.get(column)) for column in CODE_KEY)


def build_project_year_financial_base(
    *,
    budget_base_path: Path,
    monthly_path: Path,
    output_dir: Path,
    overwrite: bool = False,
) -> FinancialProjectYearBuildResult:
    """예산 기준 테이블과 월별 집행을 외부 결합합니다.

    기금 여부와 지출계획현액 분모가 아직 확정되지 않았으므로 집행률은 계산하지
    않습니다. 최신 관측값과 출처만 제공하며, 중복 월은 수기검토 대상으로 둡니다.
    """
    budget = pd.read_parquet(budget_base_path)
    monthly = pd.read_parquet(monthly_path)
    budget["fiscal_year"] = pd.to_numeric(
        budget["fiscal_year"], errors="coerce"
    ).astype("Int64")
    monthly["fiscal_year"] = pd.to_numeric(
        monthly["fiscal_year"], errors="coerce"
    ).astype("Int64")
    for column in CODE_KEY[1:]:
        monthly[column] = monthly[column].astype("string")
    budget["ministry_code"] = budget["ministry_code"].astype("string")
    monthly["project_id"] = monthly.apply(_monthly_project_id, axis=1)

    monthly_key = ["project_id", "fiscal_year", "ministry_code"]
    latest_month = (
        monthly.groupby(monthly_key, dropna=False)["execution_month"]
        .max()
        .rename("latest_execution_month")
        .reset_index()
    )
    latest = monthly.merge(
        latest_month,
        how="inner",
        on=monthly_key,
        validate="many_to_one",
    )
    latest = latest[latest["execution_month"] == latest["latest_execution_month"]].copy()
    latest_counts = (
        latest.groupby(monthly_key, dropna=False)
        .size()
        .rename("latest_month_row_count")
        .reset_index()
    )
    unique_latest = latest.merge(
        latest_counts,
        how="left",
        on=monthly_key,
        validate="many_to_one",
    )
    unique_latest = unique_latest[unique_latest["latest_month_row_count"] == 1].copy()

    monthly_summary = latest_counts.merge(
        unique_latest[
            [
                *monthly_key,
                "latest_execution_month",
                "ministry_name",
                "account_name",
                "program_name",
                "activity_name",
                "subactivity_name",
                "budget_amount",
                "current_budget_amount",
                "cumulative_expenditure_amount",
                "cumulative_net_expenditure_amount",
                "is_masked",
                "manual_review_required",
            ]
        ],
        how="left",
        on=monthly_key,
        validate="one_to_one",
    )
    observation_counts = (
        monthly.groupby(monthly_key, dropna=False)["execution_month"]
        .nunique()
        .rename("observed_month_count")
        .reset_index()
    )
    monthly_summary = monthly_summary.merge(
        observation_counts,
        how="left",
        on=monthly_key,
        validate="one_to_one",
    )
    monthly_summary["monthly_duplicate_review_required"] = (
        monthly_summary["latest_month_row_count"] != 1
    )
    monthly_summary["execution_rate"] = pd.NA
    monthly_summary["execution_rate_status"] = "DENOMINATOR_RULE_NOT_CONFIRMED"

    merged = budget.merge(
        monthly_summary,
        how="outer",
        on=monthly_key,
        suffixes=("_budget_api", "_monthly"),
        indicator="source_join_status",
        validate="one_to_one",
    )
    merged.insert(0, "financial_table_id", "project_year_financial_base")
    merged["source_join_status"] = merged["source_join_status"].map(
        {"both": "BOTH", "left_only": "BUDGET_ONLY", "right_only": "MONTHLY_ONLY"}
    )
    for name in (
        "ministry_name",
        "account_name",
        "program_name",
        "activity_name",
        "subactivity_name",
    ):
        budget_column = f"{name}_budget_api"
        monthly_column = f"{name}_monthly"
        if budget_column in merged and monthly_column in merged:
            merged[name] = merged[budget_column].combine_first(merged[monthly_column])
    budget_review = merged.get(
        "manual_review_required_budget_api",
        pd.Series(False, index=merged.index),
    ).astype("boolean").fillna(False)
    monthly_review = merged.get(
        "manual_review_required_monthly",
        pd.Series(False, index=merged.index),
    ).astype("boolean").fillna(False)
    duplicate_review = (
        merged["monthly_duplicate_review_required"].astype("boolean").fillna(False)
    )
    merged["manual_review_required"] = budget_review | monthly_review | duplicate_review

    primary_duplicate = merged.duplicated(monthly_key, keep=False)
    issue_mask = (
        merged["manual_review_required"]
        | (merged["source_join_status"] != "BOTH")
        | primary_duplicate
    )
    issues = merged.loc[
        issue_mask,
        [
            "project_id",
            "fiscal_year",
            "ministry_code",
            "source_join_status",
            "latest_execution_month",
            "latest_month_row_count",
            "manual_review_required",
        ],
    ].copy()
    issues.insert(0, "issue_type", "FINANCIAL_BASE_REVIEW")
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "budget_base_row_count": len(budget),
        "monthly_project_year_count": len(monthly_summary),
        "financial_base_row_count": len(merged),
        "both_source_count": int((merged["source_join_status"] == "BOTH").sum()),
        "budget_only_count": int((merged["source_join_status"] == "BUDGET_ONLY").sum()),
        "monthly_only_count": int((merged["source_join_status"] == "MONTHLY_ONLY").sum()),
        "latest_month_duplicate_project_count": int(
            monthly_summary["monthly_duplicate_review_required"].sum()
        ),
        "primary_key_duplicate_count": int(primary_duplicate.sum()),
        "manual_review_row_count": int(merged["manual_review_required"].sum()),
        "execution_rate_status": "not_calculated_denominator_rule_not_confirmed",
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = [
        output_dir / "project_year_financial_base.parquet",
        output_dir / "project_year_financial_quality_issues.csv",
        output_dir / "project_year_financial_summary.json",
    ]
    existing = [path for path in output_paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"출력 파일이 이미 있습니다: {existing[0]}")
    merged.to_parquet(output_paths[0], index=False)
    issues.to_csv(output_paths[1], index=False, encoding="utf-8-sig")
    output_paths[2].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return FinancialProjectYearBuildResult(
        project_year=merged,
        issues=issues,
        summary=summary,
        output_paths=output_paths,
    )
