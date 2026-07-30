from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from master_engineering.build_masters.project_continuity import (
    build_program_year_financial,
)
from performance_pipeline.manual_performance import (
    match_program_year,
    normalize_program_name,
)

ACCOUNT_TYPES = (
    "GENERAL_ACCOUNT",
    "SPECIAL_ACCOUNT",
    "RESPONSIBLE_OPERATION_ACCOUNT",
    "FUND",
)
PROGRAM_KEY = [
    "ministry_code",
    "fiscal_year",
    "field_name",
    "sector_name",
    "program_code",
]
FINANCIAL_PROGRAM_KEY = [*PROGRAM_KEY, "program_name"]
ACCOUNT_PROGRAM_KEY = [*FINANCIAL_PROGRAM_KEY, "account_type"]
PERFORMANCE_KEY = [
    "ministry_name",
    "fiscal_year",
    "program_name_normalized",
    "source_program_code",
]


class SameYearBudgetCheckError(ValueError):
    """동년도 성과·재정 점검의 입력 또는 보존 조건이 깨졌을 때 발생합니다."""


@dataclass(frozen=True)
class SameYearBudgetCheckResult:
    performance_program_year: pd.DataFrame
    account_type_financial: pd.DataFrame
    analysis: pd.DataFrame
    coverage: pd.DataFrame
    signal_summary: pd.DataFrame
    summary: dict[str, Any]
    output_paths: tuple[Path, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise SameYearBudgetCheckError(f"{label}에 필수 컬럼이 없습니다: {missing}")


def aggregate_program_year_performance(indicators: pd.DataFrame) -> pd.DataFrame:
    _require_columns(
        indicators,
        {
            "source_indicator_id",
            "ministry_name",
            "fiscal_year",
            "program_goal_number",
            "performance_program_name",
            "source_program_code",
            "analysis_actual_value_numeric",
            "analysis_official_achievement_rate_numeric",
            "analysis_achievement_rate_formula_review_required",
            "analysis_achievement_rate_formula_eligible",
        },
        "분석용 성과지표 마스터",
    )
    if (
        indicators["source_indicator_id"].isna().any()
        or indicators["source_indicator_id"].duplicated().any()
    ):
        raise SameYearBudgetCheckError("성과지표 행ID는 결측 없이 유일해야 합니다.")

    working = indicators.copy()
    if "program_mapping_status" not in working:
        working["program_mapping_status"] = pd.NA
    working["program_name_normalized"] = working["performance_program_name"].map(
        normalize_program_name
    )
    working["source_program_code"] = working["source_program_code"].astype("string")
    rows: list[dict[str, Any]] = []
    for key, part in working.groupby(PERFORMANCE_KEY, dropna=False, sort=True):
        comparable = part.loc[
            part["analysis_achievement_rate_formula_eligible"].fillna(False)
            & part["analysis_official_achievement_rate_numeric"].notna()
        ]
        below_target_count = int(
            comparable["analysis_official_achievement_rate_numeric"].lt(100).sum()
        )
        at_or_above_target_count = int(
            comparable["analysis_official_achievement_rate_numeric"].ge(100).sum()
        )
        if comparable.empty:
            signal = "NO_COMPARABLE_RATE"
        elif below_target_count == 0:
            signal = "ALL_COMPARABLE_AT_OR_ABOVE_TARGET"
        elif at_or_above_target_count == 0:
            signal = "ALL_COMPARABLE_BELOW_TARGET"
        else:
            signal = "MIXED_COMPARABLE"
        goal_numbers = sorted(part["program_goal_number"].dropna().astype(str).unique())
        rows.append(
            {
                "ministry_name": key[0],
                "fiscal_year": key[1],
                "program_goal_number": ";".join(goal_numbers) if goal_numbers else pd.NA,
                "performance_program_name": (
                    part["performance_program_name"].dropna().astype(str).mode().iloc[0]
                ),
                "source_program_code": key[3],
                "program_mapping_status": (
                    part["program_mapping_status"].dropna().iloc[0]
                    if part["program_mapping_status"].notna().any()
                    else pd.NA
                ),
                "program_name_normalized": key[2],
                "indicator_count": len(part),
                "reported_indicator_count": int(
                    part["analysis_actual_value_numeric"].notna().sum()
                ),
                "reported_rate_count": int(
                    part["analysis_official_achievement_rate_numeric"].notna().sum()
                ),
                "comparable_rate_count": len(comparable),
                "formula_review_count": int(
                    part["analysis_achievement_rate_formula_review_required"].sum()
                ),
                "below_target_count": below_target_count,
                "at_or_above_target_count": at_or_above_target_count,
                "reported_performance_signal": signal,
                "source_indicator_ids": json.dumps(
                    part["source_indicator_id"].astype(str).tolist(),
                    ensure_ascii=False,
                ),
            }
        )
    result = pd.DataFrame(rows).convert_dtypes()
    if result.duplicated(PERFORMANCE_KEY).any():
        raise SameYearBudgetCheckError("성과 프로그램-연도 기본키가 중복되었습니다.")
    return result


def build_account_type_financial(project_financial: pd.DataFrame) -> pd.DataFrame:
    _require_columns(
        project_financial,
        {
            "ministry_code",
            "fiscal_year",
            "account_type_classified",
            "in_core_financial_population",
            "analysis_original_budget",
            "analysis_current_budget",
            "analysis_settlement_expenditure",
        },
        "세부사업-연도 재정 마스터",
    )
    core_rows = project_financial["in_core_financial_population"].fillna(False)
    invalid_types = set(
        project_financial.loc[core_rows, "account_type_classified"].dropna().astype(str)
    ) - set(ACCOUNT_TYPES)
    if invalid_types:
        raise SameYearBudgetCheckError(
            f"지원하지 않는 회계유형이 있습니다: {sorted(invalid_types)}"
        )

    parts: list[pd.DataFrame] = []
    for account_type in ACCOUNT_TYPES:
        source = project_financial.loc[
            project_financial["account_type_classified"].eq(account_type)
        ]
        if source.empty:
            continue
        aggregated, _ = build_program_year_financial(source)
        aggregated["account_type"] = account_type
        parts.append(aggregated)
    if not parts:
        raise SameYearBudgetCheckError("회계유형별로 집계할 재정행이 없습니다.")
    result = pd.concat(parts, ignore_index=True).convert_dtypes()
    if result.duplicated(ACCOUNT_PROGRAM_KEY).any():
        raise SameYearBudgetCheckError("회계유형별 프로그램-연도 기본키가 중복되었습니다.")

    core = project_financial.loc[project_financial["in_core_financial_population"]]
    for source_column, output_column in (
        ("analysis_original_budget", "original_budget"),
        ("analysis_current_budget", "current_budget"),
        ("analysis_settlement_expenditure", "settlement_expenditure"),
    ):
        source_totals = (
            core.groupby(["fiscal_year", "account_type_classified"])[source_column]
            .sum()
            .sort_index()
        )
        source_totals.index.names = ["fiscal_year", "account_type"]
        output_totals = (
            result.groupby(["fiscal_year", "account_type"])[output_column].sum().sort_index()
        )
        comparison = pd.concat(
            [source_totals.rename("source"), output_totals.rename("output")],
            axis=1,
        ).fillna(0)
        if not comparison["source"].eq(comparison["output"]).all():
            raise SameYearBudgetCheckError(f"회계유형별 집계 전후 금액이 다릅니다: {source_column}")
    source_projects = (
        core.groupby(["fiscal_year", "account_type_classified"])["project_id"]
        .nunique()
        .sort_index()
    )
    source_projects.index.names = ["fiscal_year", "account_type"]
    output_projects = (
        result.groupby(["fiscal_year", "account_type"])["analysis_included_project_count"]
        .sum()
        .sort_index()
    )
    project_comparison = pd.concat(
        [source_projects.rename("source"), output_projects.rename("output")],
        axis=1,
    ).fillna(0)
    if not project_comparison["source"].eq(project_comparison["output"]).all():
        raise SameYearBudgetCheckError("회계유형별 집계 전후 세부사업 수가 다릅니다.")
    return result


def join_performance_and_financial(
    performance: pd.DataFrame,
    overall_financial: pd.DataFrame,
    account_type_financial: pd.DataFrame,
    *,
    ministry_code: str,
) -> pd.DataFrame:
    matched = match_program_year(
        performance,
        overall_financial,
        ministry_code=ministry_code,
    )
    match_columns = [
        *performance.columns,
        "ministry_code",
        "program_match_status",
        "program_match_eligible",
        "field_name",
        "sector_name",
        "program_code",
        "financial_program_name",
    ]
    matched = matched.loc[:, match_columns]
    financial_columns = [
        *ACCOUNT_PROGRAM_KEY,
        "original_budget",
        "current_budget",
        "settlement_expenditure",
        "execution_rate",
        "financial_linkage_status",
        "financial_quality_level",
        "project_count",
        "analysis_included_project_count",
        "execution_review_project_count",
        "source_project_ids",
    ]
    matched_rows = matched["program_match_eligible"].fillna(False)
    analysis = matched.loc[matched_rows].merge(
        account_type_financial.loc[:, financial_columns],
        how="left",
        left_on=[*PROGRAM_KEY, "financial_program_name"],
        right_on=FINANCIAL_PROGRAM_KEY,
        validate="one_to_many",
    )
    unmatched = matched.loc[~matched_rows].copy()
    for column in financial_columns:
        if column not in PROGRAM_KEY:
            unmatched[column] = pd.NA
    if not unmatched.empty:
        analysis = pd.concat(
            [analysis, unmatched.dropna(axis=1, how="all")],
            ignore_index=True,
        )
    analysis = analysis.rename(
        columns={
            "program_name": "account_financial_program_name",
            "original_budget": "account_original_budget",
            "current_budget": "account_current_budget",
            "settlement_expenditure": "account_settlement_expenditure",
            "execution_rate": "account_execution_rate",
            "financial_linkage_status": "account_financial_linkage_status",
            "financial_quality_level": "account_financial_quality_level",
            "project_count": "account_project_count",
            "analysis_included_project_count": "account_analysis_included_project_count",
            "execution_review_project_count": "account_execution_review_project_count",
        }
    )
    analysis["analysis_status"] = "JOINT_ANALYSIS"
    analysis.loc[~analysis["program_match_eligible"].fillna(False), "analysis_status"] = (
        "PROGRAM_MATCH_REVIEW"
    )
    analysis.loc[
        analysis["program_mapping_status"].eq("DELETED_TRANSFERRED"),
        "analysis_status",
    ] = "STRUCTURAL_PROGRAM_DELETED_TRANSFERRED"
    analysis.loc[
        analysis["program_match_eligible"].fillna(False) & analysis["account_type"].isna(),
        "analysis_status",
    ] = "FINANCIAL_ACCOUNT_TYPE_MISSING"
    analysis.loc[
        analysis["program_match_eligible"].fillna(False)
        & analysis["account_type"].notna()
        & ~analysis["account_financial_linkage_status"].eq("COMPLETE"),
        "analysis_status",
    ] = "FINANCIAL_LINKAGE_LIMITED"
    analysis.loc[
        analysis["program_match_eligible"].fillna(False)
        & analysis["account_financial_linkage_status"].eq("COMPLETE")
        & analysis["comparable_rate_count"].eq(0),
        "analysis_status",
    ] = "PERFORMANCE_RATE_NOT_COMPARABLE"
    analysis["reporting_completeness"] = "PARTIALLY_REPORTED"
    analysis.loc[
        analysis["reported_rate_count"].eq(analysis["indicator_count"]),
        "reporting_completeness",
    ] = "FULLY_REPORTED"
    analysis["formula_comparison_completeness"] = "PARTIALLY_COMPARABLE"
    analysis.loc[
        analysis["comparable_rate_count"].eq(analysis["indicator_count"]),
        "formula_comparison_completeness",
    ] = "FULLY_COMPARABLE"
    joint = analysis["analysis_status"].eq("JOINT_ANALYSIS")
    analysis["execution_below_80"] = joint & analysis["account_execution_rate"].lt(0.80)
    analysis["execution_below_90"] = joint & analysis["account_execution_rate"].lt(0.90)
    if analysis.duplicated(
        [
            "ministry_code",
            "fiscal_year",
            "program_goal_number",
            "performance_program_name",
            "account_type",
        ]
    ).any():
        raise SameYearBudgetCheckError("결합 결과의 프로그램-연도-회계유형 키가 중복되었습니다.")
    return analysis.convert_dtypes()


def build_coverage(
    account_type_financial: pd.DataFrame,
    analysis: pd.DataFrame,
) -> pd.DataFrame:
    complete = account_type_financial.loc[
        account_type_financial["financial_linkage_status"].eq("COMPLETE")
    ]
    denominator = (
        complete.groupby(["fiscal_year", "account_type"], as_index=False)
        .agg(
            complete_financial_program_year_accounts=("program_code", "size"),
            complete_financial_original_budget=("original_budget", "sum"),
        )
        .convert_dtypes()
    )
    joint = analysis.loc[analysis["analysis_status"].eq("JOINT_ANALYSIS")]
    numerator = (
        joint.groupby(["fiscal_year", "account_type"], as_index=False)
        .agg(
            joint_program_year_accounts=("program_code", "size"),
            joint_original_budget=("account_original_budget", "sum"),
        )
        .convert_dtypes()
    )
    coverage = denominator.merge(
        numerator,
        how="left",
        on=["fiscal_year", "account_type"],
        validate="one_to_one",
    )
    for column in ("joint_program_year_accounts", "joint_original_budget"):
        coverage[column] = coverage[column].fillna(0)
    coverage["missing_performance_original_budget"] = (
        coverage["complete_financial_original_budget"] - coverage["joint_original_budget"]
    )
    coverage["program_year_account_coverage"] = (
        coverage["joint_program_year_accounts"]
        / coverage["complete_financial_program_year_accounts"]
    )
    coverage["original_budget_coverage"] = (
        coverage["joint_original_budget"] / coverage["complete_financial_original_budget"]
    )
    if coverage["missing_performance_original_budget"].lt(0).any():
        raise SameYearBudgetCheckError("공동분석 예산이 회계유형별 전체 예산을 초과합니다.")
    return coverage.convert_dtypes()


def build_signal_summary(analysis: pd.DataFrame) -> pd.DataFrame:
    joint = analysis.loc[analysis["analysis_status"].eq("JOINT_ANALYSIS")]
    return (
        joint.groupby(
            ["account_type", "reported_performance_signal"],
            as_index=False,
        )
        .agg(
            program_year_account_count=("program_code", "size"),
            formula_review_program_year_account_count=(
                "formula_review_count",
                lambda values: int(values.gt(0).sum()),
            ),
            original_budget=("account_original_budget", "sum"),
            execution_rate_median=("account_execution_rate", "median"),
            execution_below_80_count=("execution_below_80", "sum"),
            execution_below_90_count=("execution_below_90", "sum"),
        )
        .convert_dtypes()
    )


def run_same_year_budget_check(
    *,
    indicator_path: Path = Path(
        "data/processed/performance/analysis_ready/program_kpi_year_analysis_ready.parquet"
    ),
    overall_financial_path: Path = Path("data/processed/masters/program_year_financial.parquet"),
    project_financial_path: Path = Path("data/processed/masters/project_year_financial_v2.parquet"),
    output_dir: Path = Path("data/analytics/mss_same_year_budget_check"),
    ministry_code: str = "102",
    start_year: int = 2022,
    end_year: int = 2024,
    overwrite: bool = False,
) -> SameYearBudgetCheckResult:
    output_paths = (
        output_dir / "performance_program_year.parquet",
        output_dir / "account_type_program_year_financial.parquet",
        output_dir / "program_year_account_type_check.csv",
        output_dir / "coverage_by_year_account_type.csv",
        output_dir / "signal_summary_by_account_type.csv",
        output_dir / "analysis_summary.json",
    )
    existing = [path for path in output_paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "기존 산출물이 있습니다. --overwrite를 지정하세요: "
            + ", ".join(str(path) for path in existing)
        )
    input_paths = (indicator_path, overall_financial_path, project_financial_path)
    for path in input_paths:
        if not path.is_file():
            raise SameYearBudgetCheckError(f"입력 파일을 찾을 수 없습니다: {path}")
    hashes_before = {str(path): _sha256(path) for path in input_paths}

    indicators = pd.read_parquet(indicator_path)
    overall_financial = pd.read_parquet(overall_financial_path)
    project_financial = pd.read_parquet(project_financial_path)
    ministry_code = ministry_code.zfill(3)
    indicators = indicators.loc[
        indicators["ministry_code"].astype("string").str.zfill(3).eq(ministry_code)
        & indicators["fiscal_year"].between(start_year, end_year)
    ].copy()
    overall_financial = overall_financial.loc[
        overall_financial["ministry_code"].astype("string").str.zfill(3).eq(ministry_code)
        & overall_financial["fiscal_year"].between(start_year, end_year)
    ].copy()
    project_financial = project_financial.loc[
        project_financial["ministry_code"].astype("string").str.zfill(3).eq(ministry_code)
        & project_financial["fiscal_year"].between(start_year, end_year)
    ].copy()

    performance = aggregate_program_year_performance(indicators)
    account_financial = build_account_type_financial(project_financial)
    analysis = join_performance_and_financial(
        performance,
        overall_financial,
        account_financial,
        ministry_code=ministry_code,
    )
    coverage = build_coverage(account_financial, analysis)
    signal_summary = build_signal_summary(analysis)
    hashes_after = {str(path): _sha256(path) for path in input_paths}
    joint = analysis.loc[analysis["analysis_status"].eq("JOINT_ANALYSIS")]
    unsupported_noncore = project_financial.loc[
        ~project_financial["account_type_classified"].isin(ACCOUNT_TYPES)
    ]
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {
            "ministry_code": ministry_code,
            "start_year": start_year,
            "end_year": end_year,
            "performance_grain": "ministry x program x performance_indicator x fiscal_year",
            "analysis_grain": "ministry x program x fiscal_year x account_type",
        },
        "counts": {
            "indicator_rows": len(indicators),
            "performance_program_years": len(performance),
            "program_match_eligible": int(
                analysis.loc[
                    :, ["fiscal_year", "performance_program_name", "program_match_eligible"]
                ]
                .drop_duplicates()["program_match_eligible"]
                .sum()
            ),
            "program_match_review": int(
                analysis.loc[
                    :, ["fiscal_year", "performance_program_name", "program_match_eligible"]
                ]
                .drop_duplicates()["program_match_eligible"]
                .eq(False)
                .sum()
            ),
            "account_type_financial_rows": len(account_financial),
            "analysis_rows": len(analysis),
            "joint_analysis_program_year_accounts": len(joint),
        },
        "analysis_status_counts": {
            str(key): int(value)
            for key, value in analysis["analysis_status"].value_counts().items()
        },
        "performance_signal_counts": {
            str(key): int(value)
            for key, value in performance["reported_performance_signal"].value_counts().items()
        },
        "low_execution_joint_rows": {
            "below_80": int(joint["execution_below_80"].sum()),
            "below_90": int(joint["execution_below_90"].sum()),
        },
        "account_type_scope": {
            "supported_types": list(ACCOUNT_TYPES),
            "unsupported_noncore_rows": len(unsupported_noncore),
            "unsupported_noncore_projects": int(unsupported_noncore["project_id"].nunique()),
            "unsupported_noncore_amounts": {
                column: int(pd.to_numeric(unsupported_noncore[column], errors="coerce").sum())
                for column in (
                    "analysis_original_budget",
                    "analysis_current_budget",
                    "analysis_settlement_expenditure",
                )
            },
        },
        "coverage": {
            account_type: {
                "program_year_account_coverage": float(
                    part["joint_program_year_accounts"].sum()
                    / part["complete_financial_program_year_accounts"].sum()
                ),
                "original_budget_coverage": float(
                    part["joint_original_budget"].sum()
                    / part["complete_financial_original_budget"].sum()
                ),
            }
            for account_type, part in coverage.groupby("account_type")
        },
        "validation": {
            "indicator_id_unique": not indicators["source_indicator_id"].duplicated().any(),
            "performance_program_year_key_unique": not performance.duplicated(
                PERFORMANCE_KEY
            ).any(),
            "account_type_financial_key_unique": not account_financial.duplicated(
                ACCOUNT_PROGRAM_KEY
            ).any(),
            "analysis_key_unique": not analysis.duplicated(
                [
                    "ministry_code",
                    "fiscal_year",
                    "program_goal_number",
                    "performance_program_name",
                    "account_type",
                ]
            ).any(),
            "report_target_missing_count": int(
                indicators["analysis_report_target_numeric"].isna().sum()
            ),
            "actual_value_missing_count": int(
                indicators["analysis_actual_value_numeric"].isna().sum()
            ),
            "official_rate_missing_count": int(
                indicators["analysis_official_achievement_rate_numeric"].isna().sum()
            ),
            "input_files_unchanged": hashes_before == hashes_after,
        },
        "method": {
            "performance": (
                "공식 달성률 평균·합산 없이 산식 비교 적격 지표의 100% 미만·이상 건수만 집계"
            ),
            "financial": (
                "일반회계·특별회계·기금을 분리하고 확인된 분모가 있는 유형만 집행률 계산; "
                "기금은 VWFOEM2 예산현액을 지출계획현액 대응 분모로 사용"
            ),
            "interpretation": (
                "점검 우선순위 후보를 위한 탐색 신호이며 실패·낭비·감액 대상으로 판정하지 않음"
            ),
        },
        "source_sha256": hashes_before,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    performance.to_parquet(output_paths[0], index=False)
    account_financial.to_parquet(output_paths[1], index=False)
    analysis.to_csv(output_paths[2], index=False, encoding="utf-8-sig")
    coverage.to_csv(output_paths[3], index=False, encoding="utf-8-sig")
    signal_summary.to_csv(output_paths[4], index=False, encoding="utf-8-sig")
    output_paths[5].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return SameYearBudgetCheckResult(
        performance_program_year=performance,
        account_type_financial=account_financial,
        analysis=analysis,
        coverage=coverage,
        signal_summary=signal_summary,
        summary=summary,
        output_paths=output_paths,
    )


__all__ = [
    "ACCOUNT_TYPES",
    "SameYearBudgetCheckError",
    "SameYearBudgetCheckResult",
    "aggregate_program_year_performance",
    "build_account_type_financial",
    "build_coverage",
    "build_signal_summary",
    "join_performance_and_financial",
    "run_same_year_budget_check",
]
