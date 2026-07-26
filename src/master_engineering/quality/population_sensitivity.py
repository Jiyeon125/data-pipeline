"""분석 모집단 제외 민감도와 집단별 편향을 진단합니다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

SOURCE_KEY = ["source_project_year_id", "fiscal_year", "ministry_code"]
SOURCE_AMOUNT_COLUMNS = (
    "budget_amount",
    "current_budget_amount",
    "cumulative_expenditure_amount",
    "cumulative_net_expenditure_amount",
    "settlement_budget_amount",
    "settlement_current_budget_amount",
    "settlement_expenditure_amount",
    "settlement_net_expenditure_amount",
    "settlement_carryover_amount",
    "settlement_unused_amount",
    "execution_numerator_amount",
    "execution_denominator_amount",
)
POPULATION_FLAGS = {
    "broad_population": "broad_population_flag",
    "core_financial_population": "core_financial_population_flag",
    "strict_ranking_population": "strict_ranking_population_flag",
}
SIZE_LABELS = [
    "Q1_SMALL",
    "Q2_MEDIUM",
    "Q3_LARGE",
    "Q4_VERY_LARGE",
]


@dataclass
class PopulationSensitivityResult:
    full_frame: pd.DataFrame
    broad_population: pd.DataFrame
    core_financial_population: pd.DataFrame
    strict_ranking_population: pd.DataFrame
    waterfall: pd.DataFrame
    amount_coverage: pd.DataFrame
    bias_diagnostics: pd.DataFrame
    summary: dict[str, Any]
    output_paths: list[Path]


def _bool_series(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame[column].astype("boolean").fillna(False).astype(bool)


def classify_exclusion_review_type(row: pd.Series) -> str:
    """기존 제외행을 범위·분석별 제한·데이터 차단으로 재분류합니다."""
    if bool(row.get("analysis_included_classified", False)) is False:
        return "SCOPE_EXCLUDED"
    if row.get("financial_quality_level") == "BLOCKING":
        return "DATA_QUALITY_BLOCKING"
    if str(row.get("population_exclusion_reason", "")) == "MASKED_BASE_AMOUNT":
        return "DATA_QUALITY_BLOCKING"
    return "ANALYSIS_SPECIFIC_LIMITATION"


def _project_size_bucket(frame: pd.DataFrame) -> pd.Series:
    result = pd.Series("MISSING", index=frame.index, dtype="string")
    amount = frame["project_size_amount"]
    result.loc[amount.notna() & amount.le(0)] = "NON_POSITIVE"
    for indexes in frame.loc[amount.gt(0)].groupby("fiscal_year").groups.values():
        ranked = amount.loc[indexes].rank(method="first", pct=True)
        result.loc[indexes] = pd.cut(
            ranked,
            bins=[0, 0.25, 0.5, 0.75, 1.0],
            labels=SIZE_LABELS,
            include_lowest=True,
        ).astype("string")
    return result


def add_analysis_eligibility_flags(frame: pd.DataFrame) -> pd.DataFrame:
    """분석영역별 적격 플래그와 세 모집단 플래그를 추가합니다."""
    result = frame.copy()
    scope = _bool_series(result, "analysis_included_classified")
    masked = _bool_series(result, "is_masked") | result[
        "masked_source_row_count"
    ].fillna(0).gt(0)
    parse_failure = result["amount_parse_failure_row_count"].fillna(0).gt(0)
    settlement_duplicate = _bool_series(result, "settlement_duplicate_key_flag")
    monthly_duplicate = _bool_series(result, "monthly_duplicate_review_required")
    blocking = result["financial_quality_level"].eq("BLOCKING")

    result["original_budget_analysis_amount"] = result[
        "settlement_budget_amount"
    ].combine_first(result["budget_amount"])
    result["current_budget_analysis_amount"] = result[
        "settlement_current_budget_amount"
    ].combine_first(result["current_budget_amount"])
    result["settlement_analysis_amount"] = result["settlement_expenditure_amount"]
    result["project_size_amount"] = result["current_budget_analysis_amount"].abs()
    result["project_size_bucket"] = _project_size_bucket(result)
    result["analysis_ministry_name"] = result["ministry_name"]
    for column in [
        "ministry_name_settlement",
        "ministry_name_budget_api",
        "ministry_name_monthly",
    ]:
        if column in result:
            result["analysis_ministry_name"] = result[
                "analysis_ministry_name"
            ].combine_first(result[column])

    result["budget_analysis_eligible"] = (
        scope
        & result["original_budget_analysis_amount"].notna()
        & ~masked
        & ~parse_failure
    )
    result["settlement_analysis_eligible"] = (
        scope
        & result["settlement_analysis_amount"].notna()
        & ~settlement_duplicate
        & ~result["settlement_matching_status"].eq("MULTIPLE_MATCHES")
    )
    result["execution_analysis_eligible"] = (
        scope
        & result["execution_rate"].notna()
        & result["execution_denominator_status"].eq("APPLIED")
        & ~_bool_series(result, "execution_rate_over_100_flag")
        & ~monthly_duplicate
        & ~settlement_duplicate
    )
    result["monthly_pattern_analysis_eligible"] = (
        scope
        & result["cumulative_expenditure_amount"].notna()
        & result["observed_month_count"].fillna(0).ge(12)
        & ~masked
        & ~monthly_duplicate
    )

    stable_year_eligible = (
        scope
        & _bool_series(result, "required_project_hierarchy_available")
        & result["original_budget_analysis_amount"].notna()
    )
    eligible_year_counts = (
        result.loc[stable_year_eligible]
        .groupby("classification_project_id")["fiscal_year"]
        .nunique()
    )
    result["trend_analysis_eligible"] = (
        stable_year_eligible
        & result["classification_project_id"].map(eligible_year_counts).fillna(0).ge(2)
    )

    preliminary_core = (
        result["budget_analysis_eligible"]
        & result["settlement_analysis_eligible"]
        & ~blocking
    )
    rankable_classification = (
        result["classification_status"].eq("RULE_CANDIDATE")
        & result["fiscal_instrument"].ne("UNKNOWN")
        & result["project_category"].ne("UNKNOWN")
    )
    result["ranking_small_group_limited_flag"] = (
        result["comparison_group_size"].fillna(0).gt(0)
        & result["comparison_group_size"].fillna(0).lt(5)
    )
    result["ranking_analysis_eligible"] = (
        preliminary_core
        & result["execution_analysis_eligible"]
        & rankable_classification
        & _bool_series(result, "reconciliation_analysis_eligible")
        & ~result["ranking_small_group_limited_flag"]
        & result["comparison_group_size"].fillna(0).ge(5)
    )
    result["broad_population_flag"] = scope & (
        result["budget_analysis_eligible"]
        | result["settlement_analysis_eligible"]
        | result["monthly_pattern_analysis_eligible"]
    )
    result["core_financial_population_flag"] = preliminary_core
    result["strict_ranking_population_flag"] = result["ranking_analysis_eligible"]

    result = result.sort_values(
        ["classification_project_id", "fiscal_year", "source_project_year_id"]
    )
    previous_budget = result.groupby("classification_project_id")[
        "original_budget_analysis_amount"
    ].shift(1)
    previous_year = result.groupby("classification_project_id")["fiscal_year"].shift(1)
    consecutive = result["fiscal_year"].sub(previous_year).eq(1)
    result["budget_change_rate"] = pd.NA
    valid_change = (
        consecutive
        & previous_budget.notna()
        & previous_budget.ne(0)
        & result["original_budget_analysis_amount"].notna()
    )
    result.loc[valid_change, "budget_change_rate"] = (
        result.loc[valid_change, "original_budget_analysis_amount"]
        - previous_budget.loc[valid_change]
    ) / previous_budget.loc[valid_change].abs()
    result["budget_change_rate"] = pd.to_numeric(
        result["budget_change_rate"], errors="coerce"
    ).astype("Float64")
    return result.sort_index()


def _snapshot_row(
    frame: pd.DataFrame,
    *,
    stage_order: int,
    stage: str,
    stage_kind: str,
    mask: pd.Series,
) -> dict[str, Any]:
    selected = frame.loc[mask]
    return {
        "stage_order": stage_order,
        "stage": stage,
        "stage_kind": stage_kind,
        "row_count": len(selected),
        "row_share": len(selected) / len(frame) if len(frame) else 0.0,
        "project_count": int(selected["classification_project_id"].nunique()),
        "original_budget_amount": int(
            selected["original_budget_analysis_amount"].sum(skipna=True)
        ),
        "current_budget_amount": int(
            selected["current_budget_analysis_amount"].sum(skipna=True)
        ),
        "settlement_expenditure_amount": int(
            selected["settlement_analysis_amount"].sum(skipna=True)
        ),
    }


def _build_waterfall(frame: pd.DataFrame) -> pd.DataFrame:
    all_rows = pd.Series(True, index=frame.index)
    current_excluded = frame["previous_population"].eq("EXCLUDED")
    rows = [
        _snapshot_row(
            frame,
            stage_order=1,
            stage="SOURCE_ALL",
            stage_kind="BASELINE",
            mask=all_rows,
        ),
        _snapshot_row(
            frame,
            stage_order=2,
            stage="CURRENT_ANALYSIS_POPULATION",
            stage_kind="SNAPSHOT",
            mask=frame["previous_population"].eq("INCLUDED"),
        ),
    ]
    for order, exclusion_type in enumerate(
        [
            "SCOPE_EXCLUDED",
            "ANALYSIS_SPECIFIC_LIMITATION",
            "DATA_QUALITY_BLOCKING",
        ],
        start=3,
    ):
        rows.append(
            _snapshot_row(
                frame,
                stage_order=order,
                stage=exclusion_type,
                stage_kind="CURRENT_EXCLUSION_COMPONENT",
                mask=current_excluded & frame["exclusion_review_type"].eq(exclusion_type),
            )
        )
    for order, (population, flag) in enumerate(POPULATION_FLAGS.items(), start=6):
        rows.append(
            _snapshot_row(
                frame,
                stage_order=order,
                stage=population.upper(),
                stage_kind="SENSITIVITY_POPULATION",
                mask=frame[flag],
            )
        )
    return pd.DataFrame(rows)


def _coverage_row(
    frame: pd.DataFrame,
    subset: pd.DataFrame,
    *,
    group_level: str,
    reason: str,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "group_level": group_level,
        "reason": reason,
        "row_count": len(subset),
        "row_share": len(subset) / len(frame) if len(frame) else 0.0,
        "project_count": int(subset["classification_project_id"].nunique()),
    }
    for label, column in [
        ("original_budget", "original_budget_analysis_amount"),
        ("current_budget", "current_budget_analysis_amount"),
        ("settlement_expenditure", "settlement_analysis_amount"),
    ]:
        total = frame[column].sum(skipna=True)
        value = subset[column].sum(skipna=True)
        row[f"{label}_amount"] = int(value)
        row[f"{label}_amount_share"] = float(value / total) if total else None
        row[f"{label}_nonnull_count"] = int(subset[column].notna().sum())
    return row


def _build_amount_coverage(frame: pd.DataFrame) -> pd.DataFrame:
    excluded = frame.loc[frame["previous_population"].eq("EXCLUDED")]
    rows: list[dict[str, Any]] = []
    for exclusion_type, group in excluded.groupby("exclusion_review_type", dropna=False):
        rows.append(
            _coverage_row(
                frame,
                group,
                group_level="EXCLUSION_TYPE",
                reason=str(exclusion_type),
            )
        )
    for reason, group in excluded.groupby("population_exclusion_reason", dropna=False):
        rows.append(
            _coverage_row(
                frame,
                group,
                group_level="EXCLUSION_REASON",
                reason=str(reason),
            )
        )
    return pd.DataFrame(rows).sort_values(
        ["group_level", "row_count"], ascending=[True, False]
    )


def _build_bias_diagnostics(frame: pd.DataFrame) -> pd.DataFrame:
    group_columns = [
        "ministry_code",
        "analysis_ministry_name",
        "fiscal_year",
        "account_type_classified",
        "project_size_bucket",
    ]
    rows: list[pd.DataFrame] = []
    for population_name, flag in POPULATION_FLAGS.items():
        overall_exclusion_rate = 1.0 - float(frame[flag].mean())
        grouped = (
            frame.groupby(group_columns, dropna=False)
            .agg(
                total_row_count=(flag, "size"),
                included_row_count=(flag, "sum"),
                project_count=("classification_project_id", "nunique"),
                original_budget_amount=("original_budget_analysis_amount", "sum"),
                current_budget_amount=("current_budget_analysis_amount", "sum"),
                settlement_expenditure_amount=("settlement_analysis_amount", "sum"),
            )
            .reset_index()
            .rename(columns={"analysis_ministry_name": "ministry_name"})
        )
        grouped["excluded_row_count"] = (
            grouped["total_row_count"] - grouped["included_row_count"]
        )
        grouped["inclusion_rate"] = (
            grouped["included_row_count"] / grouped["total_row_count"]
        )
        grouped["exclusion_rate"] = 1.0 - grouped["inclusion_rate"]
        grouped["overall_exclusion_rate"] = overall_exclusion_rate
        grouped["exclusion_rate_gap"] = (
            grouped["exclusion_rate"] - overall_exclusion_rate
        )
        grouped["over_exclusion_flag"] = (
            grouped["total_row_count"].ge(10)
            & grouped["exclusion_rate_gap"].ge(0.15)
        )
        grouped["large_project_over_exclusion_flag"] = (
            grouped["project_size_bucket"].eq("Q4_VERY_LARGE")
            & grouped["over_exclusion_flag"]
        )
        grouped["bias_severity"] = "NONE"
        grouped.loc[
            grouped["over_exclusion_flag"] & grouped["exclusion_rate_gap"].lt(0.25),
            "bias_severity",
        ] = "MEDIUM"
        grouped.loc[
            grouped["over_exclusion_flag"] & grouped["exclusion_rate_gap"].ge(0.25),
            "bias_severity",
        ] = "HIGH"
        grouped.insert(0, "population_name", population_name)
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True).sort_values(
        ["population_name", "large_project_over_exclusion_flag", "exclusion_rate_gap"],
        ascending=[True, False, False],
    )


def _numeric_distribution(series: pd.Series) -> dict[str, Any]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return {"count": 0, "missing_count": int(series.isna().sum())}
    quantiles = values.quantile([0.1, 0.25, 0.5, 0.75, 0.9])
    return {
        "count": len(values),
        "missing_count": int(series.isna().sum()),
        "mean": float(values.mean()),
        "std": float(values.std()) if len(values) > 1 else None,
        "min": float(values.min()),
        "p10": float(quantiles.loc[0.1]),
        "p25": float(quantiles.loc[0.25]),
        "median": float(quantiles.loc[0.5]),
        "p75": float(quantiles.loc[0.75]),
        "p90": float(quantiles.loc[0.9]),
        "max": float(values.max()),
    }


def _category_distribution(series: pd.Series) -> dict[str, int]:
    return {
        str(key): int(value)
        for key, value in series.astype("string")
        .fillna("MISSING")
        .value_counts(dropna=False)
        .sort_index()
        .items()
    }


def _population_statistics(frame: pd.DataFrame, flag: str) -> dict[str, Any]:
    subset = frame.loc[frame[flag]]
    ministry = (
        subset.groupby(["ministry_code", "analysis_ministry_name"], dropna=False)
        .agg(
            project_year_count=("source_project_year_id", "size"),
            project_count=("classification_project_id", "nunique"),
            original_budget_amount=("original_budget_analysis_amount", "sum"),
            current_budget_amount=("current_budget_analysis_amount", "sum"),
            settlement_expenditure_amount=("settlement_analysis_amount", "sum"),
        )
        .reset_index()
        .rename(columns={"analysis_ministry_name": "ministry_name"})
    )
    return {
        "row_count": len(subset),
        "project_count": int(subset["classification_project_id"].nunique()),
        "ministry": ministry.to_dict(orient="records"),
        "execution_rate_distribution": _numeric_distribution(subset["execution_rate"]),
        "project_size_amount_distribution": _numeric_distribution(
            subset["project_size_amount"]
        ),
        "project_size_bucket_distribution": _category_distribution(
            subset["project_size_bucket"]
        ),
        "account_type_distribution": _category_distribution(
            subset["account_type_classified"]
        ),
        "fiscal_instrument_distribution": _category_distribution(
            subset["fiscal_instrument"]
        ),
        "budget_change_rate_distribution": _numeric_distribution(
            subset["budget_change_rate"]
        ),
    }


def analyze_population_sensitivity(
    *,
    population_path: Path,
    excluded_path: Path,
    output_dir: Path,
    overwrite: bool = False,
) -> PopulationSensitivityResult:
    """현재 모집단 제외를 분석영역별로 재평가하고 민감도 산출물을 만듭니다."""
    included = pd.read_parquet(population_path).assign(previous_population="INCLUDED")
    excluded = pd.read_parquet(excluded_path).assign(previous_population="EXCLUDED")
    for frame in (included, excluded):
        frame["ministry_code"] = frame["ministry_code"].astype("string")
    source = pd.concat([included, excluded], ignore_index=True)
    source_key_duplicate = source.duplicated(SOURCE_KEY, keep=False)
    if source_key_duplicate.any():
        raise ValueError("입력 모집단 결합 후 사업-연도 기본키 중복이 있습니다.")

    source["exclusion_review_type"] = "CURRENTLY_INCLUDED"
    excluded_mask = source["previous_population"].eq("EXCLUDED")
    source.loc[excluded_mask, "exclusion_review_type"] = source.loc[
        excluded_mask
    ].apply(classify_exclusion_review_type, axis=1)
    result = add_analysis_eligibility_flags(source)

    waterfall = _build_waterfall(result)
    amount_coverage = _build_amount_coverage(result)
    bias_diagnostics = _build_bias_diagnostics(result)
    broad = result.loc[result["broad_population_flag"]].copy()
    core = result.loc[result["core_financial_population_flag"]].copy()
    strict = result.loc[result["strict_ranking_population_flag"]].copy()

    original = source.set_index(SOURCE_KEY).sort_index()
    augmented = result.set_index(SOURCE_KEY).sort_index()
    amount_change_count = 0
    for column in SOURCE_AMOUNT_COLUMNS:
        left = pd.to_numeric(original[column], errors="coerce").astype("Float64")
        right = pd.to_numeric(augmented[column], errors="coerce").astype("Float64")
        changed = ~(left.eq(right) | (left.isna() & right.isna()))
        amount_change_count += int(changed.sum())

    exclusion_type_counts = (
        result.loc[excluded_mask, "exclusion_review_type"]
        .value_counts()
        .sort_index()
        .to_dict()
    )
    analysis_flag_counts = {
        column: int(result[column].sum())
        for column in [
            "budget_analysis_eligible",
            "execution_analysis_eligible",
            "settlement_analysis_eligible",
            "monthly_pattern_analysis_eligible",
            "trend_analysis_eligible",
            "ranking_analysis_eligible",
        ]
    }
    small_groups = sorted(
        result.loc[
            result["ranking_small_group_limited_flag"], "comparison_group"
        ].dropna().unique()
    )
    large_bias = bias_diagnostics.loc[
        bias_diagnostics["large_project_over_exclusion_flag"]
    ].copy()
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "input_row_counts": {
            "current_population": len(included),
            "current_excluded": len(excluded),
            "combined": len(source),
        },
        "current_exclusion_reclassification_counts": exclusion_type_counts,
        "analysis_eligibility_counts": analysis_flag_counts,
        "population_counts": {
            "broad_population": len(broad),
            "core_financial_population": len(core),
            "strict_ranking_population": len(strict),
        },
        "population_statistics": {
            population: _population_statistics(result, flag)
            for population, flag in POPULATION_FLAGS.items()
        },
        "ranking_small_group_count": len(small_groups),
        "ranking_small_groups": small_groups,
        "bias_diagnostics": {
            "over_exclusion_group_count": int(
                bias_diagnostics["over_exclusion_flag"].sum()
            ),
            "large_project_over_exclusion_group_count": len(large_bias),
            "large_project_over_exclusion_groups": large_bias[
                [
                    "population_name",
                    "ministry_code",
                    "ministry_name",
                    "fiscal_year",
                    "account_type_classified",
                    "project_size_bucket",
                    "total_row_count",
                    "exclusion_rate",
                    "overall_exclusion_rate",
                    "exclusion_rate_gap",
                    "bias_severity",
                ]
            ].to_dict(orient="records"),
            "rule": (
                "group rows >= 10 and exclusion rate >= population overall + 0.15; "
                "large flag additionally requires Q4_VERY_LARGE"
            ),
        },
        "amount_definitions": {
            "original_budget": "settlement_budget_amount, 없으면 budget_amount",
            "current_budget": (
                "settlement_current_budget_amount, 없으면 current_budget_amount"
            ),
            "settlement_expenditure": "settlement_expenditure_amount",
            "project_size": "abs(current_budget_analysis_amount), fiscal_year quartile",
            "budget_change": (
                "동일 classification_project_id의 연속연도 original budget 증감률; "
                "전년 0 또는 비연속연도는 null"
            ),
        },
        "population_definitions": {
            "broad_population": (
                "범위 포함이며 예산·결산·월별패턴 중 하나 이상 분석 가능"
            ),
            "core_financial_population": (
                "범위 포함, 본예산·결산 분석 가능, BLOCKING 아님"
            ),
            "strict_ranking_population": (
                "core + 집행률 + 대조 + 재정수단 후보 + 비교집단 5개 이상"
            ),
        },
        "validation": {
            "source_row_count_preserved": len(result) == len(source),
            "source_key_duplicate_count": int(source_key_duplicate.sum()),
            "source_amount_changed_cell_count": amount_change_count,
            "population_nested": bool(
                set(strict[SOURCE_KEY].itertuples(index=False, name=None))
                <= set(core[SOURCE_KEY].itertuples(index=False, name=None))
                <= set(broad[SOURCE_KEY].itertuples(index=False, name=None))
            ),
            "leading_zero_ministry_codes_preserved": all(
                code in set(result["ministry_code"]) for code in ("019", "075")
            ),
            "source_trace_missing_count": int(result["source_trace"].isna().sum()),
            "excluded_reclassification_missing_count": int(
                result.loc[excluded_mask, "exclusion_review_type"].isna().sum()
            ),
        },
    }

    output_paths = [
        output_dir / "population_exclusion_waterfall.csv",
        output_dir / "population_amount_coverage.csv",
        output_dir / "population_bias_diagnostics.csv",
        output_dir / "population_sensitivity_summary.json",
        output_dir / "broad_population.parquet",
        output_dir / "core_financial_population.parquet",
        output_dir / "strict_ranking_population.parquet",
    ]
    existing = [path for path in output_paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"출력 파일이 이미 있습니다: {existing[0]}")
    output_dir.mkdir(parents=True, exist_ok=True)
    waterfall.to_csv(output_paths[0], index=False, encoding="utf-8-sig")
    amount_coverage.to_csv(output_paths[1], index=False, encoding="utf-8-sig")
    bias_diagnostics.to_csv(output_paths[2], index=False, encoding="utf-8-sig")
    output_paths[3].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    broad.to_parquet(output_paths[4], index=False)
    core.to_parquet(output_paths[5], index=False)
    strict.to_parquet(output_paths[6], index=False)
    return PopulationSensitivityResult(
        full_frame=result,
        broad_population=broad,
        core_financial_population=core,
        strict_ranking_population=strict,
        waterfall=waterfall,
        amount_coverage=amount_coverage,
        bias_diagnostics=bias_diagnostics,
        summary=summary,
        output_paths=output_paths,
    )
