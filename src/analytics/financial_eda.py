"""5개 부처 재정 마스터의 1차 EDA와 팀 중간점검 보고서를 생성합니다."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

PROJECT_KEY = [
    "fiscal_year",
    "ministry_code",
    "account_code",
    "program_code",
    "activity_code",
    "subactivity_code",
]
AMOUNT_COLUMNS = [
    "original_budget_analysis_amount",
    "current_budget_analysis_amount",
    "settlement_analysis_amount",
]
ACCOUNT_ORDER = [
    "GENERAL_ACCOUNT",
    "SPECIAL_ACCOUNT",
    "FUND",
    "RESPONSIBLE_OPERATION_ACCOUNT",
    "OTHER",
    "UNKNOWN",
]
MINISTRY_ORDER = ["019", "075", "101", "102", "162"]
YEAR_END_Q4_THRESHOLD = 0.40
YEAR_END_DEC_THRESHOLD = 0.20


@dataclass(frozen=True)
class EDAPaths:
    v2: Path
    program: Path
    broad: Path
    core: Path
    strict: Path
    ranking_v2: Path
    monthly: Path
    classification: Path
    relation: Path
    output_dir: Path
    figure_dir: Path
    report: Path

    @classmethod
    def from_root(cls, root: Path) -> EDAPaths:
        masters = root / "data" / "processed" / "masters"
        sensitivity = masters / "population_sensitivity"
        return cls(
            v2=masters / "project_year_financial_v2.parquet",
            program=masters / "program_year_financial.parquet",
            broad=sensitivity / "broad_population.parquet",
            core=sensitivity / "core_financial_population.parquet",
            strict=sensitivity / "strict_ranking_population.parquet",
            ranking_v2=sensitivity / "ranking_population_v2.parquet",
            monthly=root
            / "data"
            / "processed"
            / "monthly_expenditure"
            / "monthly_expenditure_2022_2025.parquet",
            classification=masters / "project_classification.parquet",
            relation=masters / "project_relation.parquet",
            output_dir=root / "data" / "analytics" / "eda",
            figure_dir=root / "artifacts" / "figures" / "eda",
            report=root / "docs" / "M2_DATA_REVIEW.md",
        )

    @property
    def inputs(self) -> list[Path]:
        return [
            self.v2,
            self.program,
            self.broad,
            self.core,
            self.strict,
            self.ranking_v2,
            self.monthly,
            self.classification,
            self.relation,
        ]


@dataclass
class EDAResult:
    table_paths: list[Path]
    figure_paths: list[Path]
    report_path: Path
    summary_path: Path
    validation: dict[str, Any]


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce")


def _bool(frame: pd.DataFrame, column: str, default: bool = False) -> pd.Series:
    if column not in frame:
        return pd.Series(default, index=frame.index, dtype=bool)
    return frame[column].astype("boolean").fillna(default).astype(bool)


def _safe_rate(numerator: float, denominator: float) -> float:
    if pd.isna(denominator) or denominator <= 0 or pd.isna(numerator):
        return math.nan
    return float(numerator / denominator)


def _amount_sum(frame: pd.DataFrame, column: str) -> float:
    return float(_numeric(frame, column).sum(skipna=True))


def _write_csv(frame: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _json_value(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"지원하지 않는 JSON 값: {type(value)}")


def ministry_year_summary(v2: pd.DataFrame) -> pd.DataFrame:
    """broad/core 용도를 분리한 부처-연도 재정구조 표입니다."""
    broad = v2[_bool(v2, "in_broad_population")].copy()
    core = v2[_bool(v2, "in_core_financial_population")].copy()
    keys = ["ministry_code", "ministry_name", "fiscal_year"]
    rows: list[dict[str, Any]] = []
    for group_key, broad_part in broad.groupby(keys, dropna=False):
        ministry_code, ministry_name, year = group_key
        core_part = core[core["ministry_code"].eq(ministry_code) & core["fiscal_year"].eq(year)]
        broad_original = _amount_sum(broad_part, "analysis_original_budget")
        core_original = _amount_sum(core_part, "analysis_original_budget")
        current = _amount_sum(core_part, "analysis_current_budget")
        settlement = _amount_sum(core_part, "analysis_settlement_expenditure")
        rows.append(
            {
                "population": "broad_structure_with_core_financials",
                "sample_size": len(broad_part),
                "core_sample_size": len(core_part),
                "ministry_code": ministry_code,
                "ministry_name": ministry_name,
                "fiscal_year": int(year),
                "project_count": broad_part["classification_project_id"].nunique(),
                "program_count": broad_part["program_code"].nunique(),
                "original_budget_amount": broad_original,
                "current_budget_amount": current,
                "settlement_expenditure_amount": settlement,
                "carryover_amount": _amount_sum(core_part, "settlement_carryover_amount"),
                "unused_amount": _amount_sum(core_part, "settlement_unused_amount"),
                "execution_rate": _safe_rate(settlement, current),
                "analysis_excluded_original_budget_amount": broad_original - core_original,
                "analysis_target_original_budget_amount": core_original,
                "analysis_target_original_budget_share": _safe_rate(core_original, broad_original),
            }
        )
    return pd.DataFrame(rows).sort_values(["ministry_code", "fiscal_year"])


def account_type_summary(core: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (account_type, year), part in core.groupby(
        ["account_type_classified", "fiscal_year"], dropna=False
    ):
        rate = _numeric(part, "execution_rate")
        valid = rate[rate.notna()]
        current = _amount_sum(part, "current_budget_analysis_amount")
        settlement = _amount_sum(part, "settlement_analysis_amount")
        carryover = _amount_sum(part, "settlement_carryover_amount")
        unused = _amount_sum(part, "settlement_unused_amount")
        rows.append(
            {
                "population": "core_financial_population",
                "sample_size": len(part),
                "execution_rate_sample_size": len(valid),
                "account_type": account_type,
                "fiscal_year": int(year),
                "project_count": part["classification_project_id"].nunique(),
                "original_budget_amount": _amount_sum(part, "original_budget_analysis_amount"),
                "current_budget_amount": current,
                "settlement_expenditure_amount": settlement,
                "execution_rate_median": valid.median(),
                "execution_rate_q1": valid.quantile(0.25),
                "execution_rate_q3": valid.quantile(0.75),
                "carryover_rate": _safe_rate(carryover, current),
                "unused_rate": _safe_rate(unused, current),
                "quality_limited_row_count": int(
                    (~_bool(part, "execution_analysis_eligible")).sum()
                ),
                "quality_limited_row_share": float(
                    (~_bool(part, "execution_analysis_eligible")).mean()
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(["account_type", "fiscal_year"])


def fiscal_instrument_summary(broad: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for instrument, part in broad.groupby("fiscal_instrument", dropna=False):
        rate = _numeric(part, "execution_rate").dropna()
        manual = _bool(part, "classification_manual_review_required")
        rows.append(
            {
                "population": "broad_population",
                "sample_size": len(part),
                "fiscal_instrument": instrument,
                "unique_project_count": part["classification_project_id"].nunique(),
                "original_budget_amount": _amount_sum(part, "original_budget_analysis_amount"),
                "execution_rate_sample_size": len(rate),
                "execution_rate_median": rate.median(),
                "execution_rate_q1": rate.quantile(0.25),
                "execution_rate_q3": rate.quantile(0.75),
                "unknown_row_share": float(part["fiscal_instrument"].eq("UNKNOWN").mean()),
                "manual_review_row_count": int(manual.sum()),
                "manual_review_row_share": float(manual.mean()),
            }
        )
    return pd.DataFrame(rows).sort_values("sample_size", ascending=False)


def build_monthly_patterns(core: pd.DataFrame, monthly: pd.DataFrame) -> pd.DataFrame:
    """중복 사업-월을 합산하지 않고 품질 플래그로 제한합니다."""
    monthly = monthly.copy()
    monthly["month_number"] = monthly["execution_month"].astype(str).str[-2:].astype(int)
    key_month = PROJECT_KEY + ["month_number"]
    counts = monthly.groupby(key_month, dropna=False).size().rename("month_row_count")
    monthly = monthly.merge(counts.reset_index(), on=key_month, how="left")
    grouped_rows: list[dict[str, Any]] = []
    for key, part in monthly.groupby(PROJECT_KEY, dropna=False):
        duplicate = bool(part["month_row_count"].gt(1).any())
        masked = bool(_bool(part, "is_masked").any())
        unique = part.drop_duplicates(key_month, keep=False).sort_values("month_number")
        months = set(unique["month_number"].tolist())

        def value(month: int, column: str, source: pd.DataFrame = unique) -> float:
            found = source.loc[source["month_number"].eq(month), column]
            return float(found.iloc[0]) if len(found) and pd.notna(found.iloc[0]) else math.nan

        dec_cum = value(12, "cumulative_expenditure_amount")
        sep_cum = value(9, "cumulative_expenditure_amount")
        dec_exp = value(12, "expenditure_amount")
        expenditures = _numeric(unique, "expenditure_amount").dropna()
        mean_abs = expenditures.abs().mean()
        cumulative = _numeric(unique, "cumulative_expenditure_amount")
        decrease_count = int(cumulative.diff().lt(0).sum())
        grouped_rows.append(
            {
                **dict(zip(PROJECT_KEY, key, strict=True)),
                "monthly_source_row_count": len(part),
                "observed_month_count": len(months),
                "q1_cumulative_amount": value(3, "cumulative_expenditure_amount"),
                "half_year_cumulative_amount": value(6, "cumulative_expenditure_amount"),
                "q3_cumulative_amount": sep_cum,
                "december_cumulative_amount": dec_cum,
                "q4_expenditure_share": _safe_rate(dec_cum - sep_cum, dec_cum),
                "december_single_month_share": _safe_rate(dec_exp, dec_cum),
                "monthly_expenditure_volatility": (
                    float(expenditures.std(ddof=0) / mean_abs)
                    if len(expenditures) >= 2 and mean_abs > 0
                    else math.nan
                ),
                "cumulative_decrease_count": decrease_count,
                "duplicate_month_key_flag": duplicate,
                "monthly_masked_flag": masked,
                "monthly_source_quality_flag": bool(_bool(part, "manual_review_required").any()),
            }
        )
    patterns = pd.DataFrame(grouped_rows)
    core_columns = [
        *PROJECT_KEY,
        "source_project_year_id",
        "classification_project_id",
        "ministry_name",
        "program_name",
        "subactivity_name",
        "project_status",
        "structural_change_type",
        "execution_denominator_amount",
        "execution_denominator_status",
        "execution_rate",
        "execution_rate_over_100_flag",
        "review_priority",
        "monthly_pattern_analysis_eligible",
    ]
    core_key_counts = core.groupby(PROJECT_KEY, dropna=False).size()
    duplicate_core_keys = set(core_key_counts[core_key_counts.gt(1)].index)
    result = core[core_columns].merge(patterns, on=PROJECT_KEY, how="left", validate="many_to_one")
    result["master_key_duplicate_flag"] = [
        tuple(row) in duplicate_core_keys
        for row in result[PROJECT_KEY].itertuples(index=False, name=None)
    ]
    denominator = _numeric(result, "execution_denominator_amount")
    confirmed = result["execution_denominator_status"].eq("APPLIED") & denominator.gt(0)
    for label, amount in [
        ("q1_cumulative_execution_rate", "q1_cumulative_amount"),
        ("half_year_cumulative_execution_rate", "half_year_cumulative_amount"),
        ("q3_cumulative_execution_rate", "q3_cumulative_amount"),
        ("december_cumulative_execution_rate", "december_cumulative_amount"),
    ]:
        result[label] = np.where(confirmed, _numeric(result, amount) / denominator, np.nan)
    result["year_end_concentration_flag"] = _numeric(result, "q4_expenditure_share").ge(
        YEAR_END_Q4_THRESHOLD
    ) | _numeric(result, "december_single_month_share").ge(YEAR_END_DEC_THRESHOLD)
    boundary = result["structural_change_type"].isin(["LEFT_CENSORED", "RIGHT_CENSORED"])
    blocking = result["review_priority"].eq("BLOCKING")
    result["monthly_pattern_eligible_final"] = (
        _bool(result, "monthly_pattern_analysis_eligible")
        & confirmed
        & ~boundary
        & ~blocking
        & ~_bool(result, "duplicate_month_key_flag")
        & ~_bool(result, "master_key_duplicate_flag")
        & ~_bool(result, "monthly_masked_flag")
        & result["observed_month_count"].eq(12)
    )
    reasons = []
    for _, row in result.iterrows():
        values: list[str] = []
        if pd.isna(row.get("observed_month_count")):
            values.append("NO_MONTHLY_SOURCE")
        elif row["observed_month_count"] < 12:
            values.append("INCOMPLETE_MONTHS")
        if bool(row.get("duplicate_month_key_flag", False)):
            values.append("DUPLICATE_MONTH_KEY")
        if bool(row.get("master_key_duplicate_flag", False)):
            values.append("DUPLICATE_MASTER_HIERARCHY_KEY")
        if bool(row.get("monthly_masked_flag", False)):
            values.append("MASKED_AMOUNT")
        if row["execution_denominator_status"] != "APPLIED":
            values.append("DENOMINATOR_UNCONFIRMED")
        if row["structural_change_type"] in ["LEFT_CENSORED", "RIGHT_CENSORED"]:
            values.append("OBSERVATION_BOUNDARY")
        if row["review_priority"] == "BLOCKING":
            values.append("BLOCKING")
        if (row.get("cumulative_decrease_count") or 0) > 0:
            values.append("CUMULATIVE_DECREASE")
        reasons.append(";".join(values) if values else "NONE")
    result["execution_data_quality_flags"] = reasons
    result.insert(0, "sample_size", len(result))
    result.insert(0, "population", "core_financial_population")
    return result


def repeated_execution_review(patterns: pd.DataFrame, program: pd.DataFrame) -> pd.DataFrame:
    eligible = patterns[_bool(patterns, "monthly_pattern_eligible_final")].copy()
    eligible["under_90"] = _numeric(eligible, "execution_rate").lt(0.9)
    eligible["under_80"] = _numeric(eligible, "execution_rate").lt(0.8)
    eligible["over_100"] = _bool(eligible, "execution_rate_over_100_flag")
    eligible["has_decrease"] = _numeric(eligible, "cumulative_decrease_count").gt(0)

    def aggregate(group: pd.DataFrame, level: str, entity_id: str) -> dict[str, Any]:
        counts = {
            "execution_rate_under_90_year_count": int(group["under_90"].sum()),
            "execution_rate_under_80_year_count": int(group["under_80"].sum()),
            "year_end_concentration_year_count": int(
                _bool(group, "year_end_concentration_flag").sum()
            ),
            "cumulative_decrease_year_count": int(group["has_decrease"].sum()),
            "execution_rate_over_100_year_count": int(group["over_100"].sum()),
        }
        repeated = (
            counts["execution_rate_under_90_year_count"] >= 2
            or counts["year_end_concentration_year_count"] >= 2
            or counts["cumulative_decrease_year_count"] >= 2
            or counts["execution_rate_over_100_year_count"] >= 1
        )
        return {
            "population": "core_financial_population_monthly_eligible",
            "sample_size": len(group),
            "entity_level": level,
            "entity_id": entity_id,
            "ministry_code": group["ministry_code"].iloc[0],
            "ministry_name": group["ministry_name"].iloc[0],
            "program_code": group["program_code"].iloc[0],
            "program_name": group["program_name"].iloc[0],
            "subactivity_name": (group["subactivity_name"].iloc[0] if level == "PROJECT" else None),
            "observed_year_count": group["fiscal_year"].nunique(),
            **counts,
            "repeated_execution_explanation_needed_flag": repeated,
        }

    rows = [
        aggregate(part, "PROJECT", str(project_id))
        for project_id, part in eligible.groupby("classification_project_id")
    ]
    for keys, part in eligible.groupby(["ministry_code", "program_code"]):
        rows.append(aggregate(part, "PROGRAM", "|".join(map(str, keys))))
    return pd.DataFrame(rows).sort_values(
        [
            "repeated_execution_explanation_needed_flag",
            "execution_rate_under_90_year_count",
        ],
        ascending=[False, False],
    )


def program_concentration(core: pd.DataFrame, program: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    keys = ["ministry_code", "program_code", "fiscal_year"]
    for key, part in core.groupby(keys, dropna=False):
        amounts = _numeric(part, "original_budget_analysis_amount").clip(lower=0)
        total = amounts.sum()
        shares = amounts / total if total > 0 else pd.Series(np.nan, index=part.index)
        rows.append(
            {
                **dict(zip(keys, key, strict=True)),
                "budget_concentration_hhi": float((shares**2).sum()) if total > 0 else math.nan,
                "high_single_project_dependency_flag": bool(
                    shares.max() >= 0.5 if total > 0 else False
                ),
            }
        )
    concentration = pd.DataFrame(rows)
    result = program.merge(concentration, on=keys, how="left", validate="one_to_one")
    result.insert(0, "sample_size", len(result))
    result.insert(0, "population", "core_financial_population")
    return result


def unknown_patterns(broad: pd.DataFrame) -> pd.DataFrame:
    unknown = broad[broad["fiscal_instrument"].eq("UNKNOWN")].copy()
    normalized = (
        unknown["subactivity_name"]
        .fillna("")
        .astype(str)
        .str.replace(r"\s+", "", regex=True)
        .str.replace(r"\d+", "#", regex=True)
    )
    unknown["project_name_pattern"] = normalized
    keys = ["ministry_code", "analysis_ministry_name", "program_code", "program_name"]
    rows = []
    for key, part in unknown.groupby(keys, dropna=False):
        top = part["project_name_pattern"].value_counts().head(3)
        rows.append(
            {
                "population": "broad_population_unknown_fiscal_instrument",
                "sample_size": len(part),
                **dict(zip(keys, key, strict=True)),
                "unique_project_count": part["classification_project_id"].nunique(),
                "original_budget_amount": _amount_sum(part, "original_budget_analysis_amount"),
                "top_project_name_patterns": " | ".join(
                    f"{name}({count})" for name, count in top.items()
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["sample_size", "original_budget_amount"], ascending=False
    )


def quality_overview(
    v2: pd.DataFrame,
    broad: pd.DataFrame,
    core: pd.DataFrame,
    strict: pd.DataFrame,
    ranking_v2: pd.DataFrame,
    program: pd.DataFrame,
    monthly: pd.DataFrame,
    relation: pd.DataFrame,
) -> pd.DataFrame:
    metrics = {
        "source_project_year_rows": len(v2),
        "broad_population_rows": len(broad),
        "core_financial_population_rows": len(core),
        "strict_ranking_population_v1_rows": len(strict),
        "ranking_population_v2_rows": len(ranking_v2),
        "budget_basis_available_rows": int(_numeric(v2, "analysis_original_budget").notna().sum()),
        "settlement_joined_rows": int(v2["settlement_join_status"].eq("BOTH").sum()),
        "program_complete_rows": int(program["financial_linkage_status"].eq("COMPLETE").sum()),
        "program_partial_rows": int(program["financial_linkage_status"].eq("PARTIAL").sum()),
        "program_unmatched_rows": int(program["financial_linkage_status"].eq("UNMATCHED").sum()),
        "blocking_rows": int(broad["review_priority"].eq("BLOCKING").sum()),
        "non_blocking_rows": int(broad["review_priority"].eq("NON_BLOCKING").sum()),
        "informational_rows": int(broad["review_priority"].eq("INFORMATIONAL").sum()),
        "unknown_fiscal_instrument_rows": int(broad["fiscal_instrument"].eq("UNKNOWN").sum()),
        "relationship_candidate_rows": int(relation["review_priority"].eq("MANUAL_REVIEW").sum()),
        "left_censored_relation_rows": int(relation["relation_type"].eq("LEFT_CENSORED").sum()),
        "right_censored_relation_rows": int(relation["relation_type"].eq("RIGHT_CENSORED").sum()),
        "execution_rate_available_rows": int(_numeric(v2, "execution_rate").notna().sum()),
        "execution_rate_over_100_rows": int(_numeric(v2, "execution_rate").gt(1).sum()),
        "masked_project_year_rows": int(_bool(v2, "is_masked").sum()),
        "masked_monthly_rows": int(_bool(monthly, "is_masked").sum()),
        "relationship_manual_review_rows": int(
            relation["review_priority"].isin(["MANUAL_REVIEW", "BLOCKING"]).sum()
        ),
    }
    return pd.DataFrame(
        {
            "population": "mixed_as_specified",
            "sample_size": len(v2),
            "metric": list(metrics),
            "value": list(metrics.values()),
        }
    )


def representativeness(
    broad: pd.DataFrame,
    core: pd.DataFrame,
    strict: pd.DataFrame,
    ranking_v2: pd.DataFrame,
) -> pd.DataFrame:
    populations = {
        "broad_population": broad,
        "core_financial_population": core,
        "strict_ranking_population_v1": strict,
        "ranking_population_v2": ranking_v2,
    }
    baseline_ids = set(core["source_project_year_id"])
    core_original = _amount_sum(core, "original_budget_analysis_amount")
    rows: list[dict[str, Any]] = []
    for population_name, frame in populations.items():
        for dimension, column in [
            ("OVERALL", None),
            ("MINISTRY", "ministry_code"),
            ("ACCOUNT_TYPE", "account_type_classified"),
            ("FISCAL_INSTRUMENT", "fiscal_instrument"),
            ("PROJECT_SIZE", "project_size_bucket"),
            ("COMPARISON_GROUP", "comparison_group"),
        ]:
            groups = [("ALL", frame)] if column is None else frame.groupby(column, dropna=False)
            for group_value, part in groups:
                ids = set(part["source_project_year_id"])
                core_group = (
                    core
                    if column is None
                    else core[
                        core[column]
                        .fillna("<NA>")
                        .eq("<NA>" if pd.isna(group_value) else group_value)
                    ]
                )
                denominator = len(core_group)
                rows.append(
                    {
                        "population": population_name,
                        "sample_size": len(part),
                        "dimension": dimension,
                        "group_value": group_value,
                        "row_count": len(part),
                        "unique_project_count": part["classification_project_id"].nunique(),
                        "core_overlap_row_count": len(ids & baseline_ids),
                        "core_row_inclusion_rate": (
                            len(ids & baseline_ids) / denominator if denominator else np.nan
                        ),
                        "original_budget_amount": _amount_sum(
                            part, "original_budget_analysis_amount"
                        ),
                        "original_budget_core_coverage": _safe_rate(
                            _amount_sum(part, "original_budget_analysis_amount"),
                            core_original,
                        )
                        if dimension == "OVERALL"
                        else _safe_rate(
                            _amount_sum(part, "original_budget_analysis_amount"),
                            _amount_sum(core_group, "original_budget_analysis_amount"),
                        ),
                        "large_project_row_count": int(
                            part["project_size_bucket"].eq("LARGE").sum()
                        ),
                        "representativeness_limited_row_count": int(
                            _bool(part, "ranking_representativeness_limited").sum()
                        )
                        if "ranking_representativeness_limited" in part
                        else 0,
                    }
                )
    return pd.DataFrame(rows)


def descriptive_relationships(core: pd.DataFrame, repeated: pd.DataFrame) -> list[dict[str, Any]]:
    def spearman(name: str, left: pd.Series, right: pd.Series) -> dict[str, Any]:
        pair = pd.DataFrame({"left": left, "right": right}).dropna()
        return {
            "metric": name,
            "sample_size": len(pair),
            "missing_count": len(left) - len(pair),
            "spearman_correlation": pair["left"].rank().corr(pair["right"].rank()),
            "interpretation": "기술적 연관이며 인과관계를 의미하지 않음",
        }

    results = [
        spearman(
            "current_budget_vs_settlement",
            _numeric(core, "current_budget_analysis_amount"),
            _numeric(core, "settlement_analysis_amount"),
        ),
        spearman(
            "project_size_vs_execution_rate",
            np.log1p(_numeric(core, "original_budget_analysis_amount").clip(lower=0)),
            _numeric(core, "execution_rate"),
        ),
        spearman(
            "previous_execution_vs_current_budget_change",
            _numeric(core, "execution_rate") - _numeric(core, "execution_rate_change"),
            _numeric(core, "budget_change_rate"),
        ),
    ]
    project_repeat = repeated[repeated["entity_level"].eq("PROJECT")][
        ["entity_id", "execution_rate_under_90_year_count"]
    ].copy()
    project_repeat["classification_project_id"] = project_repeat["entity_id"]
    joined = core.merge(project_repeat, on="classification_project_id", how="left")
    results.append(
        spearman(
            "repeated_under_90_count_vs_budget_change",
            _numeric(joined, "execution_rate_under_90_year_count"),
            _numeric(joined, "budget_change_rate"),
        )
    )
    return results


def _set_plot_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "Malgun Gothic",
            "axes.unicode_minus": False,
            "figure.facecolor": "white",
            "axes.facecolor": "#F8FAFC",
            "axes.edgecolor": "#CBD5E1",
            "grid.color": "#E2E8F0",
            "axes.titleweight": "bold",
            "axes.titlesize": 13,
        }
    )


def _save(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)
    return path


def create_figures(
    ministry: pd.DataFrame,
    account: pd.DataFrame,
    core: pd.DataFrame,
    patterns: pd.DataFrame,
    concentration: pd.DataFrame,
    representative: pd.DataFrame,
) -> list[Path]:
    _set_plot_style()
    output = Path(concentration.attrs["figure_dir"])
    paths: list[Path] = []
    colors = ["#2563EB", "#F97316", "#16A34A", "#9333EA", "#DC2626"]

    def ministry_trend(column: str, title: str, filename: str) -> None:
        pivot = ministry.pivot_table(
            index="fiscal_year",
            columns="ministry_code",
            values=column,
            aggfunc="sum",
        )
        label_map = (
            ministry.dropna(subset=["ministry_name"])
            .drop_duplicates("ministry_code")
            .set_index("ministry_code")["ministry_name"]
            .to_dict()
        )
        pivot = pivot.rename(columns=label_map)
        fig, ax = plt.subplots(figsize=(10, 5.5))
        pivot.div(1e12).plot(ax=ax, marker="o", color=colors)
        ax.set_title(f"{title}\n모집단: broad 구조·core 금액, n={ministry.sample_size.sum():,}")
        ax.set_xlabel("회계연도")
        ax.set_ylabel("조 원")
        ax.grid(axis="y")
        ax.legend(title="부처", fontsize=8)
        paths.append(_save(fig, output / filename))

    ministry_trend(
        "original_budget_amount",
        "부처별·연도별 본예산 추이",
        "ministry_year_original_budget_trend.png",
    )
    ministry_trend(
        "settlement_expenditure_amount",
        "부처별·연도별 결산 지출 추이",
        "ministry_year_settlement_trend.png",
    )

    execution = core[_numeric(core, "execution_rate").between(0, 1.5, inclusive="both")].copy()
    fig, axes = plt.subplots(2, 3, figsize=(13, 8), sharey=True)
    for ax, account_type in zip(axes.flat, ACCOUNT_ORDER, strict=True):
        values = _numeric(
            execution[execution["account_type_classified"].eq(account_type)],
            "execution_rate",
        ).dropna()
        if len(values):
            ax.boxplot(values, vert=True, patch_artist=True)
        ax.set_title(f"{account_type}\nn={len(values):,}", fontsize=10)
        ax.set_xticks([])
        ax.grid(axis="y")
    fig.suptitle(
        "회계유형별 집행률 분포 (유형별 분리)\n모집단: core, 표시범위 0~150%",
        fontweight="bold",
    )
    paths.append(_save(fig, output / "account_type_execution_rate_distribution.png"))

    fig, ax = plt.subplots(figsize=(10, 5.5))
    groups = [
        _numeric(execution[execution["ministry_code"].eq(code)], "execution_rate").dropna()
        for code in MINISTRY_ORDER
    ]
    labels = [
        execution.loc[execution["ministry_code"].eq(code), "analysis_ministry_name"].iloc[0]
        if execution["ministry_code"].eq(code).any()
        else code
        for code in MINISTRY_ORDER
    ]
    ax.boxplot(groups, tick_labels=labels, patch_artist=True)
    ax.set_title(
        f"부처별 집행률 분포\n모집단: core, 유효 n={sum(map(len, groups)):,}, 표시범위 0~150%"
    )
    ax.set_ylabel("집행률")
    ax.tick_params(axis="x", rotation=15)
    ax.grid(axis="y")
    paths.append(_save(fig, output / "ministry_execution_rate_distribution.png"))

    eligible = patterns[_bool(patterns, "monthly_pattern_eligible_final")].copy()
    fig, ax = plt.subplots(figsize=(10, 5.5))
    rate_columns = [
        "q1_cumulative_execution_rate",
        "half_year_cumulative_execution_rate",
        "q3_cumulative_execution_rate",
        "december_cumulative_execution_rate",
    ]
    for color, (name, part) in zip(colors, eligible.groupby("ministry_name"), strict=False):
        medians = [part[column].median() for column in rate_columns]
        ax.plot([3, 6, 9, 12], medians, marker="o", label=name, color=color)
    ax.set_title(f"부처별 월별 누계 집행곡선 요약\n모집단: core 월별 적격, n={len(eligible):,}")
    ax.set_xlabel("기준 월")
    ax.set_ylabel("누계 집행률 중앙값")
    ax.set_xticks([3, 6, 9, 12])
    ax.grid()
    ax.legend(fontsize=8)
    paths.append(_save(fig, output / "monthly_cumulative_execution_curve.png"))

    scatter = core[
        _numeric(core, "original_budget_analysis_amount").gt(0)
        & _numeric(core, "execution_rate").between(0, 2)
    ].copy()
    fig, ax = plt.subplots(figsize=(10, 5.5))
    for color, (account_type, part) in zip(
        colors,
        scatter.groupby("account_type_classified"),
        strict=False,
    ):
        ax.scatter(
            np.log10(_numeric(part, "original_budget_analysis_amount")),
            _numeric(part, "execution_rate"),
            s=9,
            alpha=0.35,
            label=account_type,
            color=color,
        )
    ax.set_title(
        f"사업규모와 집행률\n모집단: core, 유효 n={len(scatter):,}, 집행률 표시범위 0~200%"
    )
    ax.set_xlabel("본예산 log10(원)")
    ax.set_ylabel("집행률")
    ax.grid()
    ax.legend(fontsize=7)
    paths.append(_save(fig, output / "project_size_execution_rate_scatter.png"))

    values = _numeric(concentration, "budget_concentration_hhi").dropna()
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(values, bins=25, color="#2563EB", alpha=0.8)
    ax.set_title(
        f"프로그램 내부 예산집중도(HHI) 분포\n모집단: core 프로그램-연도, n={len(values):,}"
    )
    ax.set_xlabel("예산집중도 HHI")
    ax.set_ylabel("프로그램-연도 수")
    ax.grid(axis="y")
    paths.append(_save(fig, output / "program_budget_concentration_distribution.png"))

    overall = representative[
        representative["dimension"].eq("OVERALL")
        & representative["population"].isin(
            [
                "broad_population",
                "core_financial_population",
                "strict_ranking_population_v1",
                "ranking_population_v2",
            ]
        )
    ].copy()
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    axes[0].bar(overall["population"], overall["row_count"], color=colors[:4])
    axes[0].set_title("행 수")
    axes[0].tick_params(axis="x", rotation=20)
    axes[1].bar(
        overall["population"],
        overall["original_budget_core_coverage"].fillna(0),
        color=colors[:4],
    )
    axes[1].set_title("core 본예산 대비 포함률")
    axes[1].tick_params(axis="x", rotation=20)
    fig.suptitle("모집단 비교\nbroad/core/strict v1/ranking v2", fontweight="bold")
    paths.append(_save(fig, output / "population_comparison.png"))

    labels = ["core", "strict v1", "ranking v2"]
    counts = [
        int(
            overall.loc[overall["population"].eq("core_financial_population"), "row_count"].iloc[0]
        ),
        int(
            overall.loc[overall["population"].eq("strict_ranking_population_v1"), "row_count"].iloc[
                0
            ]
        ),
        int(overall.loc[overall["population"].eq("ranking_population_v2"), "row_count"].iloc[0]),
    ]
    fig, ax = plt.subplots(figsize=(8, 4.8))
    ax.bar(labels, counts, color=["#16A34A", "#DC2626", "#2563EB"])
    for index, count in enumerate(counts):
        ax.text(index, count + 80, f"{count:,}", ha="center")
    ax.set_ylim(0, max(counts) * 1.12)
    ax.set_ylabel("사업-연도 행 수")
    ax.set_title("순위 모집단 제외·복원 워터폴\ncore → strict v1 → ranking v2")
    ax.grid(axis="y")
    paths.append(_save(fig, output / "population_exclusion_waterfall.png"))
    return paths


def _format_trillion(value: float) -> str:
    return f"{value / 1e12:,.1f}조 원"


def build_report(
    path: Path,
    summary: dict[str, Any],
    ministry: pd.DataFrame,
    account: pd.DataFrame,
    patterns: pd.DataFrame,
    repeated: pd.DataFrame,
    concentration: pd.DataFrame,
    representative: pd.DataFrame,
    relationships: list[dict[str, Any]],
) -> None:
    overall = representative[representative["dimension"].eq("OVERALL")].set_index("population")
    year_end_count = int(_bool(patterns, "year_end_concentration_flag").sum())
    repeat_count = int(
        _bool(
            repeated[repeated["entity_level"].eq("PROJECT")],
            "repeated_execution_explanation_needed_flag",
        ).sum()
    )
    partial = summary["quality"]["program_partial_rows"]
    unmatched = summary["quality"]["program_unmatched_rows"]
    high_dependency = int(_bool(concentration, "high_single_project_dependency_flag").sum())
    lines = [
        "# M2 재정 데이터 품질 및 재정구조 중간점검",
        "",
        "## Executive Summary",
        "",
        (
            f"- 원본 사업-연도 {summary['counts']['v2_rows']:,}행 중 broad "
            f"{summary['counts']['broad_rows']:,}행, core {summary['counts']['core_rows']:,}행을 "
            "용도에 맞게 분리했습니다."
        ),
        (
            f"- 기존 strict v1은 core의 {overall.loc['strict_ranking_population_v1', 'core_row_inclusion_rate']:.1%}만 "
            f"남겼지만, ranking v2는 행을 유지하고 변수별 적격성을 제한해 core "
            f"{summary['counts']['core_rows']:,}행을 보존했습니다."
        ),
        (
            f"- 프로그램 연결은 PARTIAL {partial:,}행, UNMATCHED {unmatched:,}행이며 이들의 "
            "집행률은 전체값처럼 해석하지 않습니다."
        ),
        (
            f"- 잠정 기준으로 연말 집중 신호는 {year_end_count:,}개 사업-연도, 반복 집행설명필요 "
            f"사업은 {repeat_count:,}개입니다. 이는 낭비·실패 판정이 아니라 원문 확인 순서입니다."
        ),
        "",
        "## 1. 분석 목적",
        "",
        (
            "5개 부처의 2022~2025년 본예산·예산현액·결산·월별 집행 구조와 "
            "데이터 품질을 진단해 팀 중간점검의 의사결정 근거를 제공합니다."
        ),
        "",
        "## 2. 데이터 범위",
        "",
        f"- 사업-연도 원본: {summary['counts']['v2_rows']:,}행",
        f"- 월별 지출: {summary['counts']['monthly_rows']:,}행",
        f"- 프로그램-연도: {summary['counts']['program_rows']:,}행",
        "- 분석 연도: 2022~2025년, 대상 부처: 019·075·101·102·162",
        "",
        "## 3. 모집단 정의",
        "",
        "- broad: 전체 재정구조·사업 수·예산 규모·회계/재정수단 분포.",
        "- core: 금액·집행률·추세·월별 패턴·프로그램 집계.",
        "- strict v1: 향후 비교집단 순위의 과거 기준이며 전체 규모 설명에는 사용하지 않습니다.",
        "- ranking v2: core 행을 유지하고 budget/execution/trend 등 변수별 적격성만 제한합니다.",
        "",
        "![모집단 비교](../artifacts/figures/eda/population_comparison.png)",
        "",
        (
            "strict v1의 낮은 금액 포함률은 성과가 아니라 필터 설계에서 비롯된 대표성 제약입니다. "
            "ranking v2는 동일 행을 되살리되 유효하지 않은 변수만 순위에서 제한합니다."
        ),
        "",
        "## 4. 데이터 품질",
        "",
        f"- 결산 연결: {summary['quality']['settlement_joined_rows']:,}행",
        (
            f"- BLOCKING/NON_BLOCKING/INFORMATIONAL: "
            f"{summary['quality']['blocking_rows']:,}/"
            f"{summary['quality']['non_blocking_rows']:,}/"
            f"{summary['quality']['informational_rows']:,}행"
        ),
        f"- 재정수단 UNKNOWN: {summary['quality']['unknown_fiscal_instrument_rows']:,}행",
        f"- 관계 수기검토 후보: {summary['quality']['relationship_candidate_rows']:,}행",
        f"- 집행률 100% 초과: {summary['quality']['execution_rate_over_100_rows']:,}행",
        "",
        "![제외 워터폴](../artifacts/figures/eda/population_exclusion_waterfall.png)",
        "",
        "관측경계는 신규·종료로 확정하지 않았고, 중복 월 키는 합산하지 않고 품질 제한으로 남겼습니다.",
        "",
        "## 5. 부처별 재정구조",
        "",
        (
            f"broad 본예산 합계는 {_format_trillion(ministry['original_budget_amount'].sum())}, "
            f"core 결산 지출 합계는 {_format_trillion(ministry['settlement_expenditure_amount'].sum())}입니다."
        ),
        "",
        "![부처별 본예산](../artifacts/figures/eda/ministry_year_original_budget_trend.png)",
        "",
        "부처 간 절대 규모 차이가 크므로 변화율과 포함률을 함께 확인해야 합니다.",
        "",
        "![부처별 결산](../artifacts/figures/eda/ministry_year_settlement_trend.png)",
        "",
        "결산 추이는 연결 가능한 core 금액을 사용했으며, 연결 실패가 많은 집단에서는 실제 규모보다 작게 보일 수 있습니다.",
        "",
        "## 6. 회계유형별 차이",
        "",
        (
            f"회계유형-연도 집계는 {len(account):,}개 셀입니다. 기금은 확인된 지출계획현액, "
            "일반·특별회계는 예산현액을 분모로 사용하므로 서로 같은 분포로 합치지 않았습니다."
        ),
        "",
        "![회계유형별 집행률](../artifacts/figures/eda/account_type_execution_rate_distribution.png)",
        "",
        "상자그림은 유형별 패널로 분리했으며 150% 초과값은 표시에서만 제외하고 원자료에는 유지했습니다.",
        "",
        "![부처별 집행률](../artifacts/figures/eda/ministry_execution_rate_distribution.png)",
        "",
        "부처별 분포 차이는 사업 구성과 회계유형 차이를 함께 반영하므로 직접적인 성과 비교로 해석할 수 없습니다.",
        "",
        "## 7. 월별 집행 패턴",
        "",
        (
            f"월별 패턴 최종 적격 사업-연도는 {int(_bool(patterns, 'monthly_pattern_eligible_final').sum()):,}행입니다. "
            f"잠정 연말 집중 기준은 4분기 비중 {YEAR_END_Q4_THRESHOLD:.0%} 이상 또는 12월 비중 "
            f"{YEAR_END_DEC_THRESHOLD:.0%} 이상입니다."
        ),
        "",
        "![월별 누계 집행](../artifacts/figures/eda/monthly_cumulative_execution_curve.png)",
        "",
        "연말 집중은 지급 일정·조달·하위기관 시차 등으로 발생할 수 있어 집행설명필요 신호로만 사용합니다.",
        "",
        "![사업규모와 집행률](../artifacts/figures/eda/project_size_execution_rate_scatter.png)",
        "",
        "사업규모와 집행률의 관계는 기술적 상관이며 인과관계를 의미하지 않습니다.",
        "",
        "## 8. 프로그램 내부 예산구조",
        "",
        f"단일 세부사업 본예산 비중이 50% 이상인 프로그램-연도는 {high_dependency:,}행입니다.",
        "",
        "![프로그램 집중도](../artifacts/figures/eda/program_budget_concentration_distribution.png)",
        "",
        "집중도가 높다는 사실만으로 위험을 뜻하지 않으며 프로그램 설계상 단일 핵심사업일 가능성을 함께 검토해야 합니다.",
        "",
        "## 9. 모집단 대표성",
        "",
        (
            f"strict v1의 core 본예산 포함률은 "
            f"{overall.loc['strict_ranking_population_v1', 'original_budget_core_coverage']:.1%}, "
            f"ranking v2는 {overall.loc['ranking_population_v2', 'original_budget_core_coverage']:.1%}입니다. "
            "고용노동부 기금 2022~2025년과 과학기술정보통신부 기금 2024년의 대표성 제한 경고를 유지합니다."
        ),
        "",
        "## 10. 주요 발견",
        "",
        f"- 반복 집행설명필요 사업 {repeat_count:,}개는 사례 원문 확인 후보입니다.",
        f"- 프로그램 내부 단일사업 의존 후보 {high_dependency:,}개는 구조 설명이 필요합니다.",
        "- strict v1의 대표성 손실은 ranking v2의 변수별 제한 방식으로 완화할 수 있습니다.",
        "- 재정수단 UNKNOWN은 일반 재정통계에는 유지하고 재정수단별 순위만 제한해야 합니다.",
        "",
        "## 11. 반례와 해석 제한",
        "",
        "- 낮은 집행률이나 연말 집중은 사업 지연·다년도 사업·정산 시차 등 합리적 사유가 있을 수 있습니다.",
        "- 상관계수는 인과효과가 아니며 표본 수와 결측 수를 함께 제시했습니다.",
        "- PARTIAL/UNMATCHED 프로그램은 부분합계를 전체 프로그램 값으로 사용하지 않았습니다.",
        "- 관측창 경계와 관계 후보는 전년 대비 추세만 제한하고 동일 연도 분석에는 유지했습니다.",
        "",
        "기술적 상관 요약:",
        "",
        "| 관계 | n | 결측 | Spearman |",
        "|---|---:|---:|---:|",
    ]
    for item in relationships:
        corr = item["spearman_correlation"]
        lines.append(
            f"| {item['metric']} | {item['sample_size']:,} | "
            f"{item['missing_count']:,} | {corr:.3f} |"
        )
    lines.extend(
        [
            "",
            "## 12. 팀 논의가 필요한 결정사항",
            "",
            "1. 집행률 기준값을 90%로 유지할지",
            "2. 연말 집중 집행 기준을 어떻게 정의할지",
            "3. UNKNOWN 재정수단을 어느 수준까지 수기 분류할지",
            "4. PARTIAL 프로그램을 분석에 포함할지",
            "5. strict 모집단의 대표성 제한을 어떻게 표시할지",
            "6. 관계 후보 2,501건 중 어느 범위를 우선 검토할지",
            "",
            "## 13. 다음 단계",
            "",
            "- 팀 합의 후 집행설명필요 기준을 확정하고 민감도 시나리오를 추가합니다.",
            "- 대규모·반복 신호·UNKNOWN 예산비중을 기준으로 수기검토 우선순위를 정합니다.",
            "- 성과문서 파싱이 가능해지면 재정 신호와 성과지표를 프로그램 단위에서 결합합니다.",
            "",
            "산출표는 `data/analytics/eda/`, 그림은 `artifacts/figures/eda/`에 저장했습니다.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_financial_eda(paths: EDAPaths) -> EDAResult:
    """모든 EDA 산출물을 생성하고 핵심 불변식을 검증합니다."""
    before_hashes = {str(path): _hash(path) for path in paths.inputs}
    frames = {path.stem: pd.read_parquet(path) for path in paths.inputs}
    v2 = frames[paths.v2.stem]
    program = frames[paths.program.stem]
    broad = frames[paths.broad.stem]
    core = frames[paths.core.stem]
    strict = frames[paths.strict.stem]
    ranking_v2 = frames[paths.ranking_v2.stem]
    monthly = frames[paths.monthly.stem]
    relation = frames[paths.relation.stem]
    v2_enrichment = v2[
        [
            "project_id",
            "project_status",
            "structural_change_type",
            "execution_rate_change",
            "ranking_representativeness_limited",
        ]
    ].rename(columns={"project_id": "source_project_year_id"})
    core = core.merge(
        v2_enrichment,
        on="source_project_year_id",
        how="left",
        validate="one_to_one",
    )

    ministry = ministry_year_summary(v2)
    account = account_type_summary(core)
    instrument = fiscal_instrument_summary(broad)
    patterns = build_monthly_patterns(core, monthly)
    repeated = repeated_execution_review(patterns, program)
    concentration = program_concentration(core, program)
    unknown = unknown_patterns(broad)
    quality = quality_overview(v2, broad, core, strict, ranking_v2, program, monthly, relation)
    representative = representativeness(broad, core, strict, ranking_v2)

    paths.output_dir.mkdir(parents=True, exist_ok=True)
    table_frames = {
        "ministry_year_financial_summary.csv": ministry,
        "account_type_financial_summary.csv": account,
        "fiscal_instrument_summary.csv": instrument,
        "monthly_execution_pattern_summary.csv": patterns,
        "repeated_execution_review_projects.csv": repeated,
        "program_budget_concentration.csv": concentration,
        "data_quality_overview.csv": quality,
        "unknown_classification_patterns.csv": unknown,
        "strict_population_representativeness.csv": representative,
    }
    table_paths = [
        _write_csv(frame, paths.output_dir / filename) for filename, frame in table_frames.items()
    ]

    concentration.attrs["figure_dir"] = str(paths.figure_dir)
    figure_paths = create_figures(ministry, account, core, patterns, concentration, representative)
    quality_map = dict(zip(quality["metric"], quality["value"], strict=True))
    relationships = descriptive_relationships(core, repeated)
    summary = {
        "policy": {
            "broad": "전체 재정구조와 일반 기술통계",
            "core": "금액·집행률·추세·월별 패턴·프로그램 집계",
            "strict_v1": "과거 순위 모집단, 전체 규모 설명 금지",
            "ranking_v2": "core 행 유지, 변수별 적격성 제한",
        },
        "thresholds": {
            "execution_review_rate": 0.9,
            "year_end_q4_share": YEAR_END_Q4_THRESHOLD,
            "year_end_december_share": YEAR_END_DEC_THRESHOLD,
            "high_program_dependency_top1_share": 0.5,
        },
        "counts": {
            "v2_rows": len(v2),
            "broad_rows": len(broad),
            "core_rows": len(core),
            "strict_v1_rows": len(strict),
            "ranking_v2_rows": len(ranking_v2),
            "monthly_rows": len(monthly),
            "program_rows": len(program),
            "table_count": len(table_paths),
            "figure_count": len(figure_paths),
        },
        "quality": quality_map,
        "descriptive_relationships": relationships,
    }
    build_report(
        paths.report,
        summary,
        ministry,
        account,
        patterns,
        repeated,
        concentration,
        representative,
        relationships,
    )

    after_hashes = {str(path): _hash(path) for path in paths.inputs}
    amount_checks = {
        column: math.isclose(
            _amount_sum(
                v2[_bool(v2, "in_core_financial_population")],
                {
                    "original_budget_analysis_amount": "analysis_original_budget",
                    "current_budget_analysis_amount": "analysis_current_budget",
                    "settlement_analysis_amount": "analysis_settlement_expenditure",
                }[column],
            ),
            _amount_sum(core, column),
            rel_tol=0,
            abs_tol=0.5,
        )
        for column in AMOUNT_COLUMNS
    }
    validation = {
        "source_files_unchanged": before_hashes == after_hashes,
        "broad_row_count_preserved": len(broad)
        == int(_bool(v2, "in_broad_population").sum()),
        "core_row_count_preserved": len(core)
        == int(_bool(v2, "in_core_financial_population").sum()),
        "strict_row_count_preserved": len(strict)
        == int(_bool(v2, "in_strict_ranking_population").sum()),
        "ranking_v2_row_count_preserved": len(ranking_v2) == len(core),
        "core_amounts_reconciled": amount_checks,
        "partial_or_unmatched_execution_rate_non_null": int(
            program[
                program["financial_linkage_status"].isin(["PARTIAL", "UNMATCHED"])
                & _numeric(program, "execution_rate").notna()
            ].shape[0]
        ),
        "observation_boundary_misclassified_as_new_or_terminated": int(
            v2[
                v2["structural_change_type"].isin(["LEFT_CENSORED", "RIGHT_CENSORED"])
                & v2["project_status"].isin(["NEW", "TERMINATED"])
            ].shape[0]
        ),
        "all_tables_have_population_and_sample_size": all(
            {"population", "sample_size"}.issubset(frame.columns) for frame in table_frames.values()
        ),
        "table_count": len(table_paths),
        "figure_count": len(figure_paths),
    }
    summary["validation"] = validation
    summary_path = paths.output_dir / "eda_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=_json_value),
        encoding="utf-8",
    )
    failed = [
        key
        for key, value in validation.items()
        if (isinstance(value, bool) and not value)
        or (key.endswith("_non_null") and value != 0)
        or (key.endswith("_terminated") and value != 0)
    ]
    if not all(amount_checks.values()):
        failed.append("core_amounts_reconciled")
    if failed:
        raise ValueError(f"EDA 검증 실패: {sorted(set(failed))}")
    return EDAResult(table_paths, figure_paths, paths.report, summary_path, validation)
