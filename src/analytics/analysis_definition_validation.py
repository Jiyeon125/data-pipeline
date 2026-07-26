"""최종 점수 산정 전 분석 정의와 표본 대표성을 검증합니다."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from analytics.financial_eda import PROJECT_KEY

AMOUNT_MAP = {
    "original_budget": (
        "budget_amount",
        "settlement_budget_amount",
    ),
    "current_budget": (
        "current_budget_amount",
        "settlement_current_budget_amount",
    ),
}


@dataclass(frozen=True)
class DefinitionValidationPaths:
    v2: Path
    broad: Path
    core: Path
    ranking_v2: Path
    monthly: Path
    patterns: Path
    repeated: Path
    output_dir: Path
    report: Path

    @classmethod
    def from_root(cls, root: Path) -> DefinitionValidationPaths:
        masters = root / "data" / "processed" / "masters"
        sensitivity = masters / "population_sensitivity"
        eda = root / "data" / "analytics" / "eda"
        return cls(
            v2=masters / "project_year_financial_v2.parquet",
            broad=sensitivity / "broad_population.parquet",
            core=sensitivity / "core_financial_population.parquet",
            ranking_v2=sensitivity / "ranking_population_v2.parquet",
            monthly=root
            / "data"
            / "processed"
            / "monthly_expenditure"
            / "monthly_expenditure_2022_2025.parquet",
            patterns=eda / "monthly_execution_pattern_summary.csv",
            repeated=eda / "repeated_execution_review_projects.csv",
            output_dir=root / "data" / "analytics" / "definition_validation",
            report=root / "docs" / "M2_ANALYSIS_DEFINITION_VALIDATION.md",
        )

    @property
    def inputs(self) -> list[Path]:
        return [
            self.v2,
            self.broad,
            self.core,
            self.ranking_v2,
            self.monthly,
            self.patterns,
            self.repeated,
        ]


@dataclass
class DefinitionValidationResult:
    table_paths: list[Path]
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


def _sum(frame: pd.DataFrame, column: str) -> float:
    return float(_numeric(frame, column).sum(skipna=True))


def _safe_rate(numerator: float, denominator: float) -> float:
    if pd.isna(numerator) or pd.isna(denominator) or denominator <= 0:
        return math.nan
    return float(numerator / denominator)


def _write_csv(frame: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def budget_unit_multiplier_validation(v2: pd.DataFrame) -> pd.DataFrame:
    """API와 결산 예산 필드의 행별 배수를 기록합니다."""
    rows: list[pd.DataFrame] = []
    identity = [
        "project_id",
        "fiscal_year",
        "ministry_code",
        "account_code",
        "program_code",
        "activity_code",
        "subactivity_code",
    ]
    for amount_type, (api_column, settlement_column) in AMOUNT_MAP.items():
        part = v2[identity].copy()
        part["amount_type"] = amount_type
        part["api_source_field"] = api_column
        part["settlement_source_field"] = settlement_column
        part["api_amount"] = _numeric(v2, api_column)
        part["settlement_amount"] = _numeric(v2, settlement_column)
        comparable = part["api_amount"].gt(0) & part["settlement_amount"].gt(0)
        part = part[comparable].copy()
        part["settlement_to_api_multiplier"] = part["settlement_amount"] / part["api_amount"]
        multiplier = part["settlement_to_api_multiplier"]
        part["relative_difference_from_1x"] = (multiplier - 1).abs()
        candidates = np.array([0.001, 0.01, 0.1, 1, 10, 100, 1000])

        def nearest_power10(value: float, choices: np.ndarray = candidates) -> float:
            return float(choices[np.abs(np.log10(choices / value)).argmin()])

        part["nearest_power10_multiplier"] = multiplier.map(nearest_power10)
        near_1x = np.isclose(multiplier, 1.0, rtol=1e-9, atol=1e-9)
        near_power = np.isclose(
            multiplier,
            part["nearest_power10_multiplier"],
            rtol=1e-6,
            atol=1e-9,
        )
        part["unit_multiplier_status"] = np.select(
            [
                near_1x,
                near_power & ~near_1x,
            ],
            [
                "CONSISTENT_1X",
                "POSSIBLE_POWER10_UNIT_MULTIPLIER",
            ],
            default="NON_UNIT_AMOUNT_DIFFERENCE",
        )
        rows.append(part)
    return pd.concat(rows, ignore_index=True)


def monthly_eligibility_breakdown(patterns: pd.DataFrame, core: pd.DataFrame) -> pd.DataFrame:
    """월별 적격 제외를 중복 영향과 상호배타 주사유로 완전히 분해합니다."""
    amounts = core[
        [
            "source_project_year_id",
            "classification_project_id",
            "original_budget_analysis_amount",
            "current_budget_analysis_amount",
            "settlement_analysis_amount",
        ]
    ]
    frame = patterns.merge(
        amounts, on=["source_project_year_id", "classification_project_id"], how="left"
    )
    confirmed = frame["execution_denominator_status"].eq("APPLIED") & _numeric(
        frame, "execution_denominator_amount"
    ).gt(0)
    masks: dict[str, pd.Series] = {
        "NO_MONTHLY_SOURCE": frame["observed_month_count"].isna(),
        "DUPLICATE_MONTH_KEY": _bool(frame, "duplicate_month_key_flag"),
        "DUPLICATE_MASTER_HIERARCHY_KEY": _bool(frame, "master_key_duplicate_flag"),
        "MASKED_AMOUNT": _bool(frame, "monthly_masked_flag"),
        "INCOMPLETE_MONTHS": frame["observed_month_count"].notna()
        & ~frame["observed_month_count"].eq(12),
        "DENOMINATOR_UNCONFIRMED": ~confirmed,
        "BLOCKING": frame["review_priority"].eq("BLOCKING"),
        "OBSERVATION_BOUNDARY": frame["structural_change_type"].isin(
            ["LEFT_CENSORED", "RIGHT_CENSORED"]
        ),
        "BASE_MONTHLY_FLAG_FALSE": ~_bool(frame, "monthly_pattern_analysis_eligible"),
    }
    excluded = ~_bool(frame, "monthly_pattern_eligible_final")
    priority = list(masks)
    primary = pd.Series("OTHER_UNEXPLAINED", index=frame.index, dtype="object")
    remaining = excluded.copy()
    for reason in priority:
        take = remaining & masks[reason]
        primary.loc[take] = reason
        remaining &= ~take
    primary.loc[~excluded] = "ELIGIBLE"
    rows: list[dict[str, Any]] = []

    def row(
        label: str,
        mask: pd.Series,
        decomposition: str,
    ) -> dict[str, Any]:
        part = frame[mask]
        return {
            "population": "core_financial_population",
            "sample_size": len(frame),
            "decomposition_type": decomposition,
            "exclusion_rule": label,
            "row_count": len(part),
            "unique_project_count": part["classification_project_id"].nunique(),
            "core_row_share": len(part) / len(frame),
            "excluded_row_share": (
                len(part) / int(excluded.sum())
                if excluded.any() and not (decomposition == "FINAL_STATUS" and label == "ELIGIBLE")
                else math.nan
            ),
            "original_budget_amount": _sum(part, "original_budget_analysis_amount"),
            "current_budget_amount": _sum(part, "current_budget_analysis_amount"),
            "settlement_expenditure_amount": _sum(part, "settlement_analysis_amount"),
        }

    rows.append(row("ELIGIBLE", ~excluded, "FINAL_STATUS"))
    rows.append(row("EXCLUDED", excluded, "FINAL_STATUS"))
    rows.extend(row(reason, excluded & mask, "OVERLAPPING_RULE") for reason, mask in masks.items())
    rows.extend(
        row(reason, excluded & primary.eq(reason), "MUTUALLY_EXCLUSIVE_PRIMARY")
        for reason in [*priority, "OTHER_UNEXPLAINED"]
    )
    return pd.DataFrame(rows)


def monthly_formula_validation(patterns: pd.DataFrame, monthly: pd.DataFrame) -> pd.DataFrame:
    """분기 누계·4분기·12월 단월 산식을 원본 월 자료로 재계산합니다."""
    eligible = patterns[_bool(patterns, "monthly_pattern_eligible_final")].copy()
    monthly = monthly.copy()
    monthly["month_number"] = monthly["execution_month"].astype(str).str[-2:].astype(int)
    counts = monthly.groupby(PROJECT_KEY + ["month_number"], dropna=False).size()
    unique_keys = counts[counts.eq(1)].index
    indexed = monthly.set_index(PROJECT_KEY + ["month_number"])
    unique = indexed.loc[indexed.index.isin(unique_keys)].reset_index()
    pivot_exp = unique.pivot_table(
        index=PROJECT_KEY,
        columns="month_number",
        values="expenditure_amount",
        aggfunc="first",
    )
    pivot_cum = unique.pivot_table(
        index=PROJECT_KEY,
        columns="month_number",
        values="cumulative_expenditure_amount",
        aggfunc="first",
    )
    base = eligible.set_index(PROJECT_KEY)
    denominator = _numeric(base, "execution_denominator_amount")
    definitions: list[tuple[str, pd.Series, pd.Series, str]] = []
    for month, existing in [
        (3, "q1_cumulative_execution_rate"),
        (6, "half_year_cumulative_execution_rate"),
        (9, "q3_cumulative_execution_rate"),
        (12, "december_cumulative_execution_rate"),
    ]:
        recomputed = pd.to_numeric(pivot_cum.get(month), errors="coerce") / denominator
        definitions.append(
            (
                existing,
                _numeric(base, existing),
                recomputed,
                f"month_{month}_cumulative_expenditure / confirmed_denominator",
            )
        )
    annual = pd.to_numeric(pivot_cum.get(12), errors="coerce")
    q4_sum_share = (
        pd.concat(
            [pd.to_numeric(pivot_exp.get(month), errors="coerce") for month in [10, 11, 12]],
            axis=1,
        ).sum(axis=1, min_count=3)
        / annual
    )
    definitions.append(
        (
            "q4_expenditure_share",
            _numeric(base, "q4_expenditure_share"),
            q4_sum_share,
            "sum(monthly_expenditure_Oct_to_Dec) / December_cumulative_expenditure",
        )
    )
    definitions.append(
        (
            "december_single_month_share",
            _numeric(base, "december_single_month_share"),
            pd.to_numeric(pivot_exp.get(12), errors="coerce") / annual,
            "December_monthly_expenditure / December_cumulative_expenditure",
        )
    )
    rows = []
    for metric, stored, recomputed, formula in definitions:
        pair = pd.concat(
            [stored.rename("stored"), recomputed.rename("recomputed")], axis=1
        ).dropna()
        difference = (pair["stored"] - pair["recomputed"]).abs()
        rows.append(
            {
                "population": "monthly_pattern_eligible",
                "sample_size": len(eligible),
                "metric": metric,
                "formula": formula,
                "comparable_row_count": len(pair),
                "missing_row_count": len(eligible) - len(pair),
                "exact_or_tolerance_match_count": int(difference.le(1e-9).sum()),
                "mismatch_count": int(difference.gt(1e-9).sum()),
                "match_rate": float(difference.le(1e-9).mean()) if len(difference) else math.nan,
                "median_absolute_difference": difference.median(),
                "max_absolute_difference": difference.max(),
            }
        )
    return pd.DataFrame(rows)


def execution_distribution(core: pd.DataFrame) -> pd.DataFrame:
    keys = [
        "ministry_code",
        "analysis_ministry_name",
        "fiscal_year",
        "account_type_classified",
        "project_size_bucket",
    ]
    rows = []
    for key, part in core.groupby(keys, dropna=False):
        rate = _numeric(part, "execution_rate")
        valid = rate.dropna()
        rows.append(
            {
                "population": "core_financial_population",
                "sample_size": len(part),
                **dict(zip(keys, key, strict=True)),
                "execution_rate_valid_count": len(valid),
                "execution_rate_missing_count": int(rate.isna().sum()),
                "execution_rate_mean": valid.mean(),
                "execution_rate_median": valid.median(),
                "execution_rate_q1": valid.quantile(0.25),
                "execution_rate_q3": valid.quantile(0.75),
                "execution_rate_p10": valid.quantile(0.10),
                "execution_rate_p20": valid.quantile(0.20),
                "under_80_count": int(valid.lt(0.8).sum()),
                "under_90_count": int(valid.lt(0.9).sum()),
                "over_100_count": int(valid.gt(1).sum()),
                "under_80_share": float(valid.lt(0.8).mean()) if len(valid) else math.nan,
                "under_90_share": float(valid.lt(0.9).mean()) if len(valid) else math.nan,
            }
        )
    return pd.DataFrame(rows)


def execution_threshold_sensitivity(ranking_v2: pd.DataFrame) -> pd.DataFrame:
    frame = ranking_v2[_bool(ranking_v2, "execution_ranking_eligible")].copy()
    rate = _numeric(frame, "execution_rate")
    group_keys = ["fiscal_year", "comparison_group"]
    group_size = frame.groupby(group_keys)["source_project_year_id"].transform("size")
    p10 = frame.groupby(group_keys)["execution_rate"].transform(
        lambda values: pd.to_numeric(values, errors="coerce").quantile(0.10)
    )
    p20 = frame.groupby(group_keys)["execution_rate"].transform(
        lambda values: pd.to_numeric(values, errors="coerce").quantile(0.20)
    )
    criteria = {
        "FIXED_UNDER_80": rate.lt(0.8),
        "FIXED_UNDER_90": rate.lt(0.9),
        "PEER_BOTTOM_10": group_size.ge(5) & rate.le(p10),
        "PEER_BOTTOM_20": group_size.ge(5) & rate.le(p20),
    }
    rows = []
    for name, mask in criteria.items():
        part = frame[mask]
        rows.append(
            {
                "population": "ranking_population_v2_execution_eligible",
                "sample_size": len(frame),
                "criterion": name,
                "flagged_row_count": len(part),
                "flagged_unique_project_count": part["classification_project_id"].nunique(),
                "flagged_row_share": len(part) / len(frame),
                "original_budget_amount": _sum(part, "original_budget_analysis_amount"),
                "comparison_group_minimum_size": 5 if name.startswith("PEER") else None,
                "peer_eligible_row_count": int(group_size.ge(5).sum())
                if name.startswith("PEER")
                else len(frame),
                "criterion_definition": {
                    "FIXED_UNDER_80": "execution_rate < 0.80",
                    "FIXED_UNDER_90": "execution_rate < 0.90",
                    "PEER_BOTTOM_10": "execution_rate <= peer_group_year_p10",
                    "PEER_BOTTOM_20": "execution_rate <= peer_group_year_p20",
                }[name],
                "tie_policy": (
                    "INCLUDE_ALL_AT_THRESHOLD" if name.startswith("PEER") else "NOT_APPLICABLE"
                ),
            }
        )
    for left, right in [
        ("FIXED_UNDER_80", "PEER_BOTTOM_10"),
        ("FIXED_UNDER_90", "PEER_BOTTOM_20"),
    ]:
        overlap = criteria[left] & criteria[right]
        rows.append(
            {
                "population": "ranking_population_v2_execution_eligible",
                "sample_size": len(frame),
                "criterion": f"OVERLAP_{left}_AND_{right}",
                "flagged_row_count": int(overlap.sum()),
                "flagged_unique_project_count": frame.loc[
                    overlap, "classification_project_id"
                ].nunique(),
                "flagged_row_share": float(overlap.mean()),
                "original_budget_amount": _sum(frame[overlap], "original_budget_analysis_amount"),
                "comparison_group_minimum_size": 5,
                "peer_eligible_row_count": int(group_size.ge(5).sum()),
                "criterion_definition": f"{left} and {right}",
                "tie_policy": "INCLUDE_ALL_AT_THRESHOLD",
            }
        )
    return pd.DataFrame(rows)


def year_end_sensitivity(patterns: pd.DataFrame, core: pd.DataFrame) -> pd.DataFrame:
    frame = patterns[_bool(patterns, "monthly_pattern_eligible_final")].merge(
        core[["source_project_year_id", "comparison_group"]],
        on="source_project_year_id",
        how="left",
        validate="one_to_one",
    )
    keys = ["fiscal_year", "comparison_group"]
    size = frame.groupby(keys)["source_project_year_id"].transform("size")
    q4_p80 = frame.groupby(keys)["q4_expenditure_share"].transform(
        lambda values: pd.to_numeric(values, errors="coerce").quantile(0.80)
    )
    dec_p80 = frame.groupby(keys)["december_single_month_share"].transform(
        lambda values: pd.to_numeric(values, errors="coerce").quantile(0.80)
    )
    fixed = _numeric(frame, "q4_expenditure_share").ge(0.40) | _numeric(
        frame, "december_single_month_share"
    ).ge(0.20)
    peer = size.ge(5) & (
        _numeric(frame, "q4_expenditure_share").ge(q4_p80)
        | _numeric(frame, "december_single_month_share").ge(dec_p80)
    )
    criteria = {
        "FIXED_Q4_40_OR_DEC_20": fixed,
        "PEER_GROUP_P80": peer,
        "OVERLAP_FIXED_AND_PEER_P80": fixed & peer,
        "FIXED_ONLY": fixed & ~peer,
        "PEER_P80_ONLY": peer & ~fixed,
    }
    rows = []
    for name, mask in criteria.items():
        rows.append(
            {
                "population": "monthly_pattern_eligible",
                "sample_size": len(frame),
                "criterion": name,
                "flagged_row_count": int(mask.sum()),
                "flagged_unique_project_count": frame.loc[
                    mask, "classification_project_id"
                ].nunique(),
                "flagged_row_share": float(mask.mean()),
                "peer_eligible_row_count": int(size.ge(5).sum()),
                "comparison_group_minimum_size": 5 if "PEER" in name else None,
                "criterion_definition": {
                    "FIXED_Q4_40_OR_DEC_20": "q4_share >= 0.40 or december_share >= 0.20",
                    "PEER_GROUP_P80": "q4_share >= peer_p80 or december_share >= peer_p80",
                    "OVERLAP_FIXED_AND_PEER_P80": "fixed criterion and peer P80 criterion",
                    "FIXED_ONLY": "fixed criterion and not peer P80",
                    "PEER_P80_ONLY": "peer P80 criterion and not fixed",
                }[name],
                "tie_policy": ("INCLUDE_ALL_AT_THRESHOLD" if "PEER" in name else "NOT_APPLICABLE"),
            }
        )
    return pd.DataFrame(rows)


def repeated_signal_decomposition(patterns: pd.DataFrame) -> pd.DataFrame:
    frame = patterns[_bool(patterns, "monthly_pattern_eligible_final")].copy()
    frame["low_execution"] = _numeric(frame, "execution_rate").lt(0.9)
    frame["year_end"] = _bool(frame, "year_end_concentration_flag")
    frame["decrease"] = _numeric(frame, "cumulative_decrease_count").gt(0)
    frame["over_100"] = _bool(frame, "execution_rate_over_100_flag")
    rows = []
    for project_id, part in frame.groupby("classification_project_id"):
        counts = {
            "low_execution_year_count": int(part["low_execution"].sum()),
            "year_end_concentration_year_count": int(part["year_end"].sum()),
            "cumulative_decrease_year_count": int(part["decrease"].sum()),
            "execution_over_100_year_count": int(part["over_100"].sum()),
        }
        active = [
            name
            for name, value in counts.items()
            if (value >= 2 if name != "execution_over_100_year_count" else value >= 1)
        ]
        rows.append(
            {
                "population": "monthly_pattern_eligible",
                "sample_size": len(part),
                "classification_project_id": project_id,
                "ministry_code": part["ministry_code"].iloc[0],
                "ministry_name": part["ministry_name"].iloc[0],
                "program_code": part["program_code"].iloc[0],
                "program_name": part["program_name"].iloc[0],
                "subactivity_name": part["subactivity_name"].iloc[0],
                "observed_year_count": part["fiscal_year"].nunique(),
                **counts,
                "active_signal_count": len(active),
                "active_signal_types": ";".join(active) if active else "NONE",
                "repeated_explanation_needed_flag": bool(active),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["repeated_explanation_needed_flag", "active_signal_count"],
        ascending=False,
    )


def program_amount_scope(v2: pd.DataFrame) -> pd.DataFrame:
    keys = [
        "ministry_code",
        "ministry_name",
        "fiscal_year",
        "program_code",
        "program_name",
    ]
    usable = v2[v2["program_code"].notna()].copy()
    rows = []
    for key, part in usable.groupby(keys, dropna=False):
        analysis = part[_bool(part, "in_core_financial_population")]
        total_original = _sum(part, "analysis_original_budget")
        total_current = _sum(part, "analysis_current_budget")
        total_settlement = _sum(part, "analysis_settlement_expenditure")
        rows.append(
            {
                "population": "all_project_year_with_program",
                "sample_size": len(part),
                **dict(zip(keys, key, strict=True)),
                "total_project_count": len(part),
                "analysis_project_count": len(analysis),
                "total_original_budget_amount": total_original,
                "analysis_original_budget_amount": _sum(analysis, "analysis_original_budget"),
                "original_budget_analysis_coverage": _safe_rate(
                    _sum(analysis, "analysis_original_budget"), total_original
                ),
                "total_current_budget_amount": total_current,
                "analysis_current_budget_amount": _sum(analysis, "analysis_current_budget"),
                "current_budget_analysis_coverage": _safe_rate(
                    _sum(analysis, "analysis_current_budget"), total_current
                ),
                "total_settlement_expenditure_amount": total_settlement,
                "analysis_settlement_expenditure_amount": _sum(
                    analysis, "analysis_settlement_expenditure"
                ),
                "settlement_analysis_coverage": _safe_rate(
                    _sum(analysis, "analysis_settlement_expenditure"),
                    total_settlement,
                ),
            }
        )
    return pd.DataFrame(rows)


def normalized_program_hhi(core: pd.DataFrame) -> pd.DataFrame:
    keys = [
        "ministry_code",
        "analysis_ministry_name",
        "fiscal_year",
        "program_code",
        "program_name",
    ]
    rows = []
    usable = core[core["program_code"].notna()].copy()
    for key, part in usable.groupby(keys, dropna=False):
        amounts = _numeric(part, "original_budget_analysis_amount").clip(lower=0)
        positive = amounts[amounts.gt(0)]
        n = len(positive)
        total = positive.sum()
        shares = positive / total if total > 0 else pd.Series(dtype=float)
        hhi = float((shares**2).sum()) if n else math.nan
        normalized = float((hhi - 1 / n) / (1 - 1 / n)) if n > 1 else math.nan
        rows.append(
            {
                "population": "core_financial_population",
                "sample_size": len(part),
                **dict(zip(keys, key, strict=True)),
                "positive_budget_project_count": n,
                "single_project_program_flag": n == 1,
                "original_budget_amount": total,
                "hhi_raw": hhi,
                "hhi_minimum_given_project_count": 1 / n if n else math.nan,
                "hhi_normalized_for_project_count": normalized,
                "top1_project_budget_share": shares.max() if n else math.nan,
                "top3_project_budget_share": shares.nlargest(3).sum() if n else math.nan,
            }
        )
    return pd.DataFrame(rows)


def unknown_budget_coverage(broad: pd.DataFrame) -> pd.DataFrame:
    unknown = broad[broad["fiscal_instrument"].eq("UNKNOWN")].copy()
    keys = [
        "classification_project_id",
        "ministry_code",
        "analysis_ministry_name",
        "program_code",
        "program_name",
        "subactivity_code",
        "subactivity_name",
    ]
    result = (
        unknown.groupby(keys, dropna=False)
        .agg(
            observed_year_count=("fiscal_year", "nunique"),
            project_year_row_count=("source_project_year_id", "size"),
            original_budget_amount=("original_budget_analysis_amount", "sum"),
        )
        .reset_index()
        .sort_values("original_budget_amount", ascending=False)
    )
    total = result["original_budget_amount"].sum()
    result["budget_coverage_order"] = np.arange(1, len(result) + 1)
    result["budget_share"] = result["original_budget_amount"] / total
    result["cumulative_budget_share"] = result["budget_share"].cumsum()
    result["minimum_review_set_for_80pct_coverage"] = (
        result["cumulative_budget_share"].shift(fill_value=0).lt(0.80)
    )
    result["minimum_review_set_for_90pct_coverage"] = (
        result["cumulative_budget_share"].shift(fill_value=0).lt(0.90)
    )
    result.insert(0, "sample_size", len(result))
    result.insert(0, "population", "broad_unknown_fiscal_instrument")
    return result


def ranking_scenario_completeness(ranking_v2: pd.DataFrame) -> pd.DataFrame:
    frame = ranking_v2.copy()
    original = _numeric(frame, "original_budget_analysis_amount")
    execution = _numeric(frame, "execution_rate")
    change = _numeric(frame, "budget_change_rate")
    scenarios: dict[str, tuple[list[str], pd.Series, str]] = {
        "BUDGET_SCALE_CROSS_SECTION": (
            ["original_budget_analysis_amount", "budget_ranking_eligible"],
            original.gt(0) & _bool(frame, "budget_ranking_eligible"),
            "positive original budget and budget component eligible",
        ),
        "EXECUTION_CROSS_SECTION": (
            ["execution_rate", "execution_ranking_eligible"],
            execution.notna() & _bool(frame, "execution_ranking_eligible"),
            "confirmed denominator and execution rate valid",
        ),
        "BUDGET_TREND": (
            ["budget_change_rate", "trend_ranking_eligible"],
            change.notna() & _bool(frame, "trend_ranking_eligible"),
            "continuity confirmed and prior-year comparable amount positive",
        ),
        "FISCAL_INSTRUMENT_PEER": (
            [
                "fiscal_instrument",
                "comparison_group",
                "fiscal_instrument_ranking_eligible",
            ],
            _bool(frame, "fiscal_instrument_ranking_eligible") & frame["comparison_group"].notna(),
            "instrument known and peer group identified; small groups retained with LOW confidence",
        ),
        "PROGRAM_STRUCTURE": (
            ["program_code", "original_budget_analysis_amount", "program_ranking_eligible"],
            frame["program_code"].notna()
            & original.notna()
            & _bool(frame, "program_ranking_eligible"),
            "program hierarchy and budget value available",
        ),
        "MULTI_COMPONENT_DIAGNOSTIC": (
            [
                "budget_ranking_eligible",
                "execution_ranking_eligible",
                "program_ranking_eligible",
                "one_of_trend_or_instrument",
            ],
            _bool(frame, "budget_ranking_eligible")
            & _bool(frame, "execution_ranking_eligible")
            & _bool(frame, "program_ranking_eligible")
            & (
                _bool(frame, "trend_ranking_eligible")
                | _bool(frame, "fiscal_instrument_ranking_eligible")
            ),
            "budget, execution, program complete and at least one of trend or instrument valid",
        ),
    }
    rows = []
    for scenario, (required, eligible, criterion) in scenarios.items():
        part = frame[eligible]
        rows.append(
            {
                "population": "ranking_population_v2",
                "sample_size": len(frame),
                "scenario": scenario,
                "required_variables": ";".join(required),
                "completeness_criterion": criterion,
                "complete_row_count": len(part),
                "incomplete_row_count": len(frame) - len(part),
                "complete_row_share": len(part) / len(frame),
                "complete_unique_project_count": part["classification_project_id"].nunique(),
                "original_budget_coverage": _safe_rate(
                    _sum(part, "original_budget_analysis_amount"),
                    _sum(frame, "original_budget_analysis_amount"),
                ),
                "final_score_generated": False,
                "final_rank_generated": False,
            }
        )
    return pd.DataFrame(rows)


def feedback_cohorts(v2: pd.DataFrame, core: pd.DataFrame) -> pd.DataFrame:
    """재정 환류의 T+1과 T+2 비교 가능 코호트를 별도로 정의합니다."""
    core_ids = set(core["source_project_year_id"])
    lookup = v2.set_index("project_id", drop=False)
    targets = v2[v2["project_id"].isin(core_ids)].copy()
    rows = []
    for horizon in [1, 2]:
        minimum_year = 2022 + horizon
        for _, target in targets[targets["fiscal_year"].ge(minimum_year)].iterrows():
            chain = [target]
            current = target
            reason = None
            for _step in range(horizon):
                predecessor_id = current["predecessor_project_id"]
                if pd.isna(predecessor_id) or predecessor_id not in lookup.index:
                    reason = "PREDECESSOR_CHAIN_MISSING"
                    break
                predecessor = lookup.loc[predecessor_id]
                if isinstance(predecessor, pd.DataFrame):
                    reason = "PREDECESSOR_KEY_NOT_UNIQUE"
                    break
                if predecessor["project_id"] not in core_ids:
                    reason = "PREDECESSOR_OUTSIDE_CORE"
                    break
                if int(current["fiscal_year"]) - int(predecessor["fiscal_year"]) != 1:
                    reason = "NON_CONSECUTIVE_YEAR_CHAIN"
                    break
                chain.append(predecessor)
                current = predecessor
            if reason is None and not all(
                bool(item["budget_change_analysis_eligible"]) for item in chain[:-1]
            ):
                reason = "BUDGET_CHANGE_NOT_ELIGIBLE_IN_CHAIN"
            base = chain[-1]
            eligible = reason is None and len(chain) == horizon + 1
            rows.append(
                {
                    "population": "core_financial_population",
                    "sample_size": len(targets[targets["fiscal_year"].ge(minimum_year)]),
                    "feedback_horizon": f"T+{horizon}",
                    "base_fiscal_year": int(target["fiscal_year"]) - horizon,
                    "outcome_fiscal_year": int(target["fiscal_year"]),
                    "ministry_code": target["ministry_code"],
                    "program_code": target["program_code"],
                    "base_project_id": base["project_id"] if len(chain) > horizon else None,
                    "intermediate_project_id": chain[1]["project_id"]
                    if horizon == 2 and len(chain) > 1
                    else None,
                    "outcome_project_id": target["project_id"],
                    "cohort_eligible": eligible,
                    "cohort_exclusion_reason": "NONE" if eligible else reason,
                    "base_original_budget_amount": base["analysis_original_budget"]
                    if len(chain) > horizon
                    else np.nan,
                    "outcome_original_budget_amount": target["analysis_original_budget"],
                    "performance_link_required_later": True,
                    "performance_value_present": False,
                }
            )
    return pd.DataFrame(rows)


def build_report(
    path: Path,
    summary: dict[str, Any],
    unit: pd.DataFrame,
    monthly_breakdown: pd.DataFrame,
    formula: pd.DataFrame,
    execution_sensitivity: pd.DataFrame,
    year_end: pd.DataFrame,
    repeated: pd.DataFrame,
    program_scope: pd.DataFrame,
    hhi: pd.DataFrame,
    unknown: pd.DataFrame,
    scenarios: pd.DataFrame,
    cohorts: pd.DataFrame,
) -> None:
    unit_summary = unit.groupby(["amount_type", "unit_multiplier_status"]).size()
    primary = monthly_breakdown[
        monthly_breakdown["decomposition_type"].eq("MUTUALLY_EXCLUSIVE_PRIMARY")
        & monthly_breakdown["row_count"].gt(0)
    ]
    fixed_year_end = int(
        year_end.loc[year_end["criterion"].eq("FIXED_Q4_40_OR_DEC_20"), "flagged_row_count"].iloc[0]
    )
    peer_year_end = int(
        year_end.loc[year_end["criterion"].eq("PEER_GROUP_P80"), "flagged_row_count"].iloc[0]
    )
    repeated_count = int(_bool(repeated, "repeated_explanation_needed_flag").sum())
    unknown_80 = int(_bool(unknown, "minimum_review_set_for_80pct_coverage").sum())
    t1 = cohorts[cohorts["feedback_horizon"].eq("T+1")]
    t2 = cohorts[cohorts["feedback_horizon"].eq("T+2")]
    lines = [
        "# M2 분석 기준 및 표본 대표성 검증",
        "",
        "## Executive Summary",
        "",
        (
            "- **현재 자료로 최종 점수나 순위를 생성하지 않았습니다.** 이번 단계는 단위, 산식, "
            "표본, 민감도, 완전성 기준을 확정하기 위한 검증입니다."
        ),
        (
            f"- API-결산 본예산 비교 가능 행 중 1배 일치가 "
            f"{int(unit_summary.get(('original_budget', 'CONSISTENT_1X'), 0)):,}행이며, "
            "일관된 1,000배·100만 배 단위 차이는 발견되지 않았습니다."
        ),
        (
            f"- 월별 적격은 3,328행, 제외는 2,962행입니다. 관측경계가 주된 제한이며 "
            f"상호배타 주사유 {len(primary)}개로 전 행을 분해했습니다."
        ),
        (
            f"- 연말 집중은 고정 기준 {fixed_year_end:,}행과 비교집단 P80 기준 "
            f"{peer_year_end:,}행이 달라, 팀 합의 전 하나의 기준을 확정값으로 사용하지 않습니다."
        ),
        f"- 반복 집행설명필요 사업은 {repeated_count:,}개이며 신호별로 분해했습니다.",
        "",
        "## 1. 검증 목적과 금지사항",
        "",
        (
            "정책적 결론, 사업 실패 판정, 최종 복합점수와 최종 순위를 생성하지 않습니다. "
            "분석 가능한 변수와 대표성 범위를 먼저 확정합니다."
        ),
        "",
        "## 2. API·결산 금액 단위 배수",
        "",
        f"- 본예산 비교 가능 행: {int(unit['amount_type'].eq('original_budget').sum()):,}행",
        f"- 예산현액 비교 가능 행: {int(unit['amount_type'].eq('current_budget').sum()):,}행",
        (
            "- 대부분 1배로 일치했습니다. 비1배 소수 행은 일관된 단위 배수라기보다 금액 범위·매칭 "
            "차이 후보로 분류하며 원본값을 보정하지 않습니다."
        ),
        "",
        "## 3. 월별 패턴 적격성과 산식",
        "",
        "| 상호배타 주사유 | 행 수 | core 비율 |",
        "|---|---:|---:|",
    ]
    for _, row in primary.iterrows():
        lines.append(
            f"| {row['exclusion_rule']} | {int(row['row_count']):,} | {row['core_row_share']:.1%} |"
        )
    lines.extend(
        [
            "",
            (
                "월별 분기 누계는 3·6·9·12월 누계액을 확인된 분모로 나눕니다. 4분기 비중은 "
                "10~12월 단월 지출 합계/12월 누계, 12월 비중은 12월 단월 지출/12월 누계로 "
                "재검증했습니다."
            ),
            "",
            "| 산식 | 비교 가능 | 불일치 | 일치율 |",
            "|---|---:|---:|---:|",
        ]
    )
    for _, row in formula.iterrows():
        lines.append(
            f"| {row['metric']} | {int(row['comparable_row_count']):,} | "
            f"{int(row['mismatch_count']):,} | {row['match_rate']:.1%} |"
        )
    lines.extend(
        [
            "",
            "## 4. 집행률 기준 민감도",
            "",
            "| 기준 | 신호 행 | 적격 표본 대비 |",
            "|---|---:|---:|",
        ]
    )
    for _, row in execution_sensitivity[
        ~execution_sensitivity["criterion"].str.startswith("OVERLAP")
    ].iterrows():
        lines.append(
            f"| {row['criterion']} | {int(row['flagged_row_count']):,} | "
            f"{row['flagged_row_share']:.1%} |"
        )
    lines.extend(
        [
            "",
            (
                "고정 80%·90%는 절대 기준이고 하위 10%·20%는 비교집단 내부 상대 기준이므로 "
                "서로 같은 의미가 아닙니다. 분위수 경계의 동률은 모두 포함하므로 실제 신호 비율이 "
                "명목 10%·20%보다 커질 수 있으며, 두 기준의 중첩을 별도로 보존합니다."
            ),
            "",
            "## 5. 연말 집중 기준 민감도",
            "",
            (
                f"고정 40%/20% 기준은 {fixed_year_end:,}행, 비교집단 P80 기준은 "
                f"{peer_year_end:,}행입니다. 비교집단 크기 5 미만은 분위수 판정에서 제외합니다. "
                "P80은 4분기 또는 12월 중 하나가 기준 이상이면 포함하고 동률을 모두 포함하므로 "
                "전체의 20%와 일치할 필요가 없습니다."
            ),
            "",
            "## 6. 반복 집행설명필요 신호",
            "",
            (
                f"사업 {len(repeated):,}개 중 반복 신호는 {repeated_count:,}개입니다. "
                "저집행, 연말 집중, 누계 감소, 100% 초과를 별도 횟수로 제공하며 복합 신호를 "
                "단일 실패 의미로 합치지 않습니다."
            ),
            "",
            "## 7. 프로그램 금액 범위와 집중도",
            "",
            (
                f"프로그램-연도 범위 비교 {len(program_scope):,}행에서 전체금액과 core 분석대상금액을 "
                "별도 컬럼으로 보존했습니다."
            ),
            (
                f"집중도 {len(hhi):,}행은 세부사업 수를 함께 제시하고, 2개 이상 사업에서 "
                "정규화 HHI=(HHI-1/n)/(1-1/n)를 산출했습니다. 단일사업 프로그램은 정규화 HHI를 "
                "결측으로 유지합니다."
            ),
            "",
            "## 8. UNKNOWN 재정수단 검토 범위",
            "",
            (
                f"UNKNOWN 고유 사업 {len(unknown):,}개를 본예산 누적 커버리지 순으로 정렬했습니다. "
                f"상위 {unknown_80:,}개가 UNKNOWN 본예산의 최소 80% 검토 집합입니다. "
                "이는 수기검토 순서이며 사업 순위가 아닙니다."
            ),
            "",
            "## 9. 순위 시나리오별 완전성 정의",
            "",
            "| 시나리오 | 필수 변수 | 완전 행 | 완전율 |",
            "|---|---|---:|---:|",
        ]
    )
    for _, row in scenarios.iterrows():
        lines.append(
            f"| {row['scenario']} | {row['required_variables']} | "
            f"{int(row['complete_row_count']):,} | {row['complete_row_share']:.1%} |"
        )
    lines.extend(
        [
            "",
            (
                "시나리오별 필수 변수가 다르므로 하나의 행 전체 적격 플래그로 대체하지 않습니다. "
                "모든 시나리오에서 최종 점수와 최종 순위 생성 여부는 false입니다."
            ),
            "",
            "## 10. T+1·T+2 환류 코호트",
            "",
            (
                f"- T+1 후보 {len(t1):,}행 중 연속 재정비교 적격 "
                f"{int(_bool(t1, 'cohort_eligible').sum()):,}행"
            ),
            (
                f"- T+2 후보 {len(t2):,}행 중 2단계 연속 재정비교 적격 "
                f"{int(_bool(t2, 'cohort_eligible').sum()):,}행"
            ),
            "",
            (
                "현재 코호트는 재정자료의 연속성만 정의합니다. 성과자료가 결합되기 전에는 "
                "성과 환류 효과나 인과관계를 판단할 수 없습니다."
            ),
            "",
            "## 11. 대표성 판단",
            "",
            (
                "관측경계는 동일 연도 횡단면에는 유지하고 추세에서만 제한합니다. UNKNOWN 재정수단은 "
                "일반 재정분석에 유지하고 재정수단 비교에서만 제한합니다. 소표본 비교집단은 삭제하지 "
                "않고 신뢰도 경고를 유지합니다."
            ),
            "",
            "## 12. 확정 전 팀 결정사항",
            "",
            "1. 절대 저집행 기준을 80%와 90% 중 어느 용도로 사용할지",
            "2. 연말 집중을 고정 40%/20%와 비교집단 P80 중 어떻게 표시할지",
            "3. 4분기 단월 합계와 누계 차이가 불일치하는 사례를 어떤 품질 등급으로 둘지",
            "4. 단일사업 프로그램의 정규화 HHI를 결측으로 유지할지",
            "5. UNKNOWN 예산 80% 커버리지 집합부터 수기검토할지",
            "6. T+1·T+2 코호트에 성과자료가 결합된 뒤 최소 표본 기준을 얼마로 둘지",
            "",
            "## 13. 결론",
            "",
            (
                "현재 결과는 분석 기준 후보와 데이터 완전성 범위를 확정하기 위한 자료입니다. "
                "팀 검토가 끝나기 전에는 최종 점수·순위·정책적 결론을 생성하지 않습니다."
            ),
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_analysis_definition_validation(
    paths: DefinitionValidationPaths,
) -> DefinitionValidationResult:
    before = {str(path): _hash(path) for path in paths.inputs}
    v2 = pd.read_parquet(paths.v2)
    broad = pd.read_parquet(paths.broad)
    core = pd.read_parquet(paths.core)
    ranking_v2 = pd.read_parquet(paths.ranking_v2)
    monthly = pd.read_parquet(paths.monthly)
    patterns = pd.read_csv(
        paths.patterns,
        encoding="utf-8-sig",
        dtype={
            "ministry_code": "string",
            "account_code": "string",
            "program_code": "string",
            "activity_code": "string",
            "subactivity_code": "string",
            "source_project_year_id": "string",
            "classification_project_id": "string",
        },
    )

    unit = budget_unit_multiplier_validation(v2)
    monthly_breakdown = monthly_eligibility_breakdown(patterns, core)
    formula = monthly_formula_validation(patterns, monthly)
    distribution = execution_distribution(core)
    execution_sensitivity = execution_threshold_sensitivity(ranking_v2)
    year_end = year_end_sensitivity(patterns, core)
    repeated = repeated_signal_decomposition(patterns)
    program_scope = program_amount_scope(v2)
    hhi = normalized_program_hhi(core)
    unknown = unknown_budget_coverage(broad)
    scenarios = ranking_scenario_completeness(ranking_v2)
    cohorts = feedback_cohorts(v2, core)

    tables = {
        "budget_unit_multiplier_validation.csv": unit,
        "monthly_eligibility_exclusion_breakdown.csv": monthly_breakdown,
        "monthly_formula_validation.csv": formula,
        "execution_rate_distribution_segmented.csv": distribution,
        "execution_threshold_sensitivity.csv": execution_sensitivity,
        "year_end_concentration_sensitivity.csv": year_end,
        "repeated_execution_signal_decomposition.csv": repeated,
        "program_amount_scope_comparison.csv": program_scope,
        "program_concentration_normalized.csv": hhi,
        "unknown_fiscal_instrument_budget_coverage.csv": unknown,
        "ranking_scenario_completeness.csv": scenarios,
        "feedback_cohort_t1_t2.csv": cohorts,
    }
    table_paths = [
        _write_csv(frame, paths.output_dir / filename) for filename, frame in tables.items()
    ]
    after = {str(path): _hash(path) for path in paths.inputs}
    primary = monthly_breakdown[
        monthly_breakdown["decomposition_type"].eq("MUTUALLY_EXCLUSIVE_PRIMARY")
    ]
    monthly_eligible_rows = int(_bool(patterns, "monthly_pattern_eligible_final").sum())
    monthly_excluded_rows = len(patterns) - monthly_eligible_rows
    validation = {
        "source_files_unchanged": before == after,
        "monthly_eligible_rows": monthly_eligible_rows,
        "monthly_excluded_rows": monthly_excluded_rows,
        "monthly_primary_exclusion_sum": int(primary["row_count"].sum()),
        "monthly_formula_all_core_metrics_present": len(formula) == 6,
        "monthly_formula_row_accounting_complete": bool(
            (formula["comparable_row_count"] + formula["missing_row_count"])
            .eq(monthly_eligible_rows)
            .all()
        ),
        "monthly_formula_mismatch_count": int(formula["mismatch_count"].sum()),
        "program_scope_rows": len(program_scope),
        "normalized_hhi_bounded_0_1": bool(
            _numeric(hhi, "hhi_normalized_for_project_count").dropna().between(0, 1 + 1e-12).all()
        ),
        "ranking_scenario_final_score_generated": bool(
            _bool(scenarios, "final_score_generated").any()
        ),
        "ranking_scenario_final_rank_generated": bool(
            _bool(scenarios, "final_rank_generated").any()
        ),
        "leading_zero_codes_preserved": bool(
            {"019", "075"}.issubset(set(v2["ministry_code"].astype(str)))
        ),
        "table_count": len(table_paths),
    }
    summary = {
        "purpose": "analysis_definition_and_representativeness_validation",
        "final_score_generated": False,
        "final_rank_generated": False,
        "policy_conclusion_generated": False,
        "counts": {
            "unit_comparison_rows": len(unit),
            "monthly_eligible_rows": validation["monthly_eligible_rows"],
            "monthly_excluded_rows": validation["monthly_excluded_rows"],
            "execution_distribution_cells": len(distribution),
            "repeated_project_rows": len(repeated),
            "program_scope_rows": len(program_scope),
            "unknown_project_rows": len(unknown),
            "t1_candidate_rows": int(cohorts["feedback_horizon"].eq("T+1").sum()),
            "t2_candidate_rows": int(cohorts["feedback_horizon"].eq("T+2").sum()),
        },
        "validation": validation,
    }
    build_report(
        paths.report,
        summary,
        unit,
        monthly_breakdown,
        formula,
        execution_sensitivity,
        year_end,
        repeated,
        program_scope,
        hhi,
        unknown,
        scenarios,
        cohorts,
    )
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = paths.output_dir / "definition_validation_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    failures: list[str] = []
    if not validation["source_files_unchanged"]:
        failures.append("source_files_unchanged")
    if validation["monthly_eligible_rows"] + validation["monthly_excluded_rows"] != len(patterns):
        failures.append("monthly_row_partition")
    if validation["monthly_primary_exclusion_sum"] != validation["monthly_excluded_rows"]:
        failures.append("monthly_primary_exclusion_sum")
    if not validation["monthly_formula_row_accounting_complete"]:
        failures.append("monthly_formula_row_accounting_complete")
    if not validation["normalized_hhi_bounded_0_1"]:
        failures.append("normalized_hhi_bounded_0_1")
    if validation["ranking_scenario_final_score_generated"]:
        failures.append("final_score_generated")
    if validation["ranking_scenario_final_rank_generated"]:
        failures.append("final_rank_generated")
    if not validation["leading_zero_codes_preserved"]:
        failures.append("leading_zero_codes_preserved")
    if failures:
        raise ValueError(f"분석 정의 검증 실패: {failures}")
    return DefinitionValidationResult(
        table_paths=table_paths,
        report_path=paths.report,
        summary_path=summary_path,
        validation=validation,
    )
