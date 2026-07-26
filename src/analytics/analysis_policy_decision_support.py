"""잠정 분석 기준을 분포·민감도·편향으로 검토하는 의사결정 지원 분석."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd

from analytics.m3_methodology_audit import build_peer_method_flags

matplotlib.use("Agg")
import matplotlib.pyplot as plt

THRESHOLDS = [round(value / 100, 2) for value in range(70, 96)]
EXECUTION_DIMENSIONS = {
    "OVERALL": None,
    "ACCOUNT_TYPE": "account_type_classified",
    "MINISTRY": "analysis_ministry_name",
    "FISCAL_YEAR": "fiscal_year",
    "PROJECT_SIZE": "project_size_bucket",
}
BIAS_DIMENSIONS = {
    "MINISTRY": "analysis_ministry_name",
    "ACCOUNT_TYPE": "account_type_classified",
    "FISCAL_YEAR": "fiscal_year",
    "PROJECT_SIZE": "project_size_bucket",
    "FISCAL_INSTRUMENT": "fiscal_instrument",
    "DATA_QUALITY": "financial_quality_level",
}
SIGNAL_SPECS = {
    "UNDER_90_EXECUTION": "under_90_combined_flag",
    "FIXED_YEAR_END": "fixed_year_end_concentration_flag",
}
PALETTE = {
    "blue": "#2563EB",
    "blue_dark": "#1E3A8A",
    "orange": "#F97316",
    "gold": "#D97706",
    "pink": "#DB2777",
    "olive": "#4D7C0F",
    "ink": "#0F172A",
    "muted": "#64748B",
    "grid": "#E2E8F0",
    "open": "#DBEAFE",
}


@dataclass(frozen=True)
class DecisionSupportPaths:
    root: Path
    features: Path
    output_dir: Path
    figure_dir: Path
    report: Path

    @classmethod
    def from_root(cls, root: Path) -> DecisionSupportPaths:
        root = root.resolve()
        return cls(
            root=root,
            features=root / "data/analytics/m3/financial_signal_features.parquet",
            output_dir=root / "data/analytics/decision_support",
            figure_dir=root / "artifacts/figures/decision_support",
            report=root / "docs/ANALYSIS_POLICY_DECISION_SUPPORT.md",
        )


@dataclass(frozen=True)
class DecisionSupportResult:
    output_paths: list[Path]
    figure_paths: list[Path]
    report_path: Path
    summary: dict[str, Any]


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce")


def _bool(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame[column].astype("boolean").fillna(False).astype(bool)


def _safe_rate(numerator: float, denominator: float) -> float:
    if pd.isna(denominator) or denominator <= 0:
        return math.nan
    return float(numerator / denominator)


def _sum(frame: pd.DataFrame, column: str) -> float:
    value = _numeric(frame, column).sum(min_count=1)
    return float(value) if pd.notna(value) else math.nan


def _json_default(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def execution_eligible_frame(features: pd.DataFrame) -> pd.DataFrame:
    """집행률 ECDF의 주 모집단을 생성합니다."""
    eligible = (
        _bool(features, "execution_ranking_eligible")
        & _numeric(features, "execution_rate").notna()
        & _numeric(features, "execution_rate").le(1)
    )
    return features.loc[eligible].copy()


def large_project_scope_sensitivity(
    features: pd.DataFrame,
    *,
    threshold: float = 0.9,
) -> pd.DataFrame:
    """대규모 보통교부세 포함 여부가 금액가중 집행률 신호에 미치는 영향을 계산합니다."""
    eligible = execution_eligible_frame(features)
    ordinary_grant = eligible["subactivity_name"].fillna("").eq("보통교부세")
    bond_purchase = (
        eligible["subactivity_name"]
        .fillna("")
        .str.contains(
            r"(?:국채|채권).*매입",
            regex=True,
        )
    )
    rows = []
    for scenario, keep in [
        ("CURRENT_SCOPE", pd.Series(True, index=eligible.index)),
        ("EXCLUDE_ORDINARY_GRANT", ~ordinary_grant),
    ]:
        frame = eligible.loc[keep]
        detected = frame[_numeric(frame, "execution_rate").lt(threshold)]
        rows.append(
            {
                "scenario": scenario,
                "threshold": threshold,
                "eligible_row_count": len(frame),
                "detected_row_count": len(detected),
                "detected_current_budget_amount": _sum(detected, "current_budget_analysis_amount"),
                "eligible_current_budget_amount": _sum(frame, "current_budget_analysis_amount"),
                "detected_current_budget_share": _safe_rate(
                    _sum(detected, "current_budget_analysis_amount"),
                    _sum(frame, "current_budget_analysis_amount"),
                ),
                "ordinary_grant_removed_row_count": int((ordinary_grant & ~keep).sum()),
                "bond_purchase_row_count_in_current_scope": int(bond_purchase.sum()),
            }
        )
    return pd.DataFrame(rows)


def _ecdf_rows(
    frame: pd.DataFrame,
    *,
    dimension: str,
    dimension_value: Any,
    weighting: str,
) -> list[dict[str, Any]]:
    values = _numeric(frame, "execution_rate")
    if weighting == "UNWEIGHTED":
        weights = pd.Series(1.0, index=frame.index)
        weight_column = "row_count"
    else:
        weights = _numeric(frame, "current_budget_analysis_amount")
        weight_column = "current_budget_analysis_amount"
    valid = values.notna() & weights.notna() & weights.gt(0)
    working = pd.DataFrame({"execution_rate": values.loc[valid], "weight": weights.loc[valid]})
    if working.empty:
        return []
    grouped = (
        working.groupby("execution_rate", as_index=False)
        .agg(point_row_count=("weight", "size"), point_weight=("weight", "sum"))
        .sort_values("execution_rate")
    )
    grouped["cumulative_weight"] = grouped["point_weight"].cumsum()
    grouped["cumulative_share"] = grouped["cumulative_weight"] / grouped["point_weight"].sum()
    grouped["cumulative_row_count"] = grouped["point_row_count"].cumsum()
    grouped["cumulative_row_share"] = (
        grouped["cumulative_row_count"] / grouped["point_row_count"].sum()
    )
    rows: list[dict[str, Any]] = []
    for row in grouped.itertuples(index=False):
        rows.append(
            {
                "population": "execution_ranking_eligible_excluding_over_100",
                "weighting": weighting,
                "weight_column": weight_column,
                "dimension": dimension,
                "dimension_value": dimension_value,
                "execution_rate": row.execution_rate,
                "point_row_count": row.point_row_count,
                "point_weight": row.point_weight,
                "cumulative_row_count": row.cumulative_row_count,
                "cumulative_row_share": row.cumulative_row_share,
                "cumulative_weight": row.cumulative_weight,
                "cumulative_share": row.cumulative_share,
                "sample_size": len(working),
                "total_weight": grouped["point_weight"].sum(),
                "execution_over_100_excluded": True,
                "reference_line_80": 0.8,
                "reference_line_90": 0.9,
            }
        )
    return rows


def execution_ecdf_summary(features: pd.DataFrame) -> pd.DataFrame:
    """전체·집단별 비가중 및 예산현액 가중 ECDF를 생성합니다."""
    eligible = execution_eligible_frame(features)
    rows: list[dict[str, Any]] = []
    for dimension, column in EXECUTION_DIMENSIONS.items():
        groups = (
            [("ALL", eligible.index)]
            if column is None
            else eligible.groupby(column, dropna=False).groups.items()
        )
        for value, index in groups:
            part = eligible.loc[index]
            for weighting in ["UNWEIGHTED", "CURRENT_BUDGET_WEIGHTED"]:
                rows.extend(
                    _ecdf_rows(
                        part,
                        dimension=dimension,
                        dimension_value=value,
                        weighting=weighting,
                    )
                )
    return pd.DataFrame(rows)


def _threshold_summary_row(
    denominator: pd.DataFrame,
    detected: pd.DataFrame,
    *,
    threshold: float,
    dimension: str,
    dimension_value: Any,
) -> dict[str, Any]:
    return {
        "population": "execution_ranking_eligible_excluding_over_100",
        "threshold": threshold,
        "threshold_percent": round(threshold * 100),
        "dimension": dimension,
        "dimension_value": dimension_value,
        "eligible_row_count": len(denominator),
        "detected_row_count": len(detected),
        "detected_row_share": _safe_rate(len(detected), len(denominator)),
        "eligible_unique_project_count": denominator["classification_project_id"].nunique(),
        "detected_unique_project_count": detected["classification_project_id"].nunique(),
        "detected_unique_project_share": _safe_rate(
            detected["classification_project_id"].nunique(),
            denominator["classification_project_id"].nunique(),
        ),
        "detected_original_budget_amount": _sum(detected, "original_budget_analysis_amount"),
        "original_budget_share": _safe_rate(
            _sum(detected, "original_budget_analysis_amount"),
            _sum(denominator, "original_budget_analysis_amount"),
        ),
        "detected_current_budget_amount": _sum(detected, "current_budget_analysis_amount"),
        "current_budget_share": _safe_rate(
            _sum(detected, "current_budget_analysis_amount"),
            _sum(denominator, "current_budget_analysis_amount"),
        ),
        "detected_settlement_amount": _sum(detected, "settlement_analysis_amount"),
        "settlement_share": _safe_rate(
            _sum(detected, "settlement_analysis_amount"),
            _sum(denominator, "settlement_analysis_amount"),
        ),
        "original_budget_available_count": int(
            _numeric(denominator, "original_budget_analysis_amount").notna().sum()
        ),
        "current_budget_available_count": int(
            _numeric(denominator, "current_budget_analysis_amount").notna().sum()
        ),
        "settlement_available_count": int(
            _numeric(denominator, "settlement_analysis_amount").notna().sum()
        ),
    }


def execution_threshold_sensitivity(features: pd.DataFrame) -> pd.DataFrame:
    """70~95% 집행률 임계값별 탐지 규모와 금액 비중을 계산합니다."""
    eligible = execution_eligible_frame(features)
    rows: list[dict[str, Any]] = []
    for threshold in THRESHOLDS:
        for dimension, column in EXECUTION_DIMENSIONS.items():
            groups = (
                [("ALL", eligible.index)]
                if column is None
                else eligible.groupby(column, dropna=False).groups.items()
            )
            for value, index in groups:
                denominator = eligible.loc[index]
                detected = denominator[_numeric(denominator, "execution_rate").lt(threshold)]
                rows.append(
                    _threshold_summary_row(
                        denominator,
                        detected,
                        threshold=threshold,
                        dimension=dimension,
                        dimension_value=value,
                    )
                )
    result = pd.DataFrame(rows)
    overall = result["dimension"].eq("OVERALL")
    ordered = result.loc[overall].sort_values("threshold")
    incremental_rows = ordered["detected_row_count"].diff()
    incremental_row_share = ordered["detected_row_share"].diff()
    incremental_budget_share = ordered["current_budget_share"].diff()
    result.loc[ordered.index, "incremental_detected_rows"] = incremental_rows
    result.loc[ordered.index, "incremental_detected_row_share"] = incremental_row_share
    result.loc[ordered.index, "incremental_current_budget_share"] = incremental_budget_share
    result.loc[ordered.index, "incremental_change_rank"] = incremental_rows.rank(
        method="min", ascending=False
    ).astype("Int64")
    result["rapid_change_candidate"] = (
        result["dimension"].eq("OVERALL") & result["incremental_change_rank"].le(3)
    ).fillna(False)
    result["rapid_change_interpretation"] = np.where(
        result["rapid_change_candidate"],
        "TOP_3_ONE_PERCENTAGE_POINT_INCREMENT_NOT_AUTOMATIC_THRESHOLD",
        "NOT_TOP_3_INCREMENT",
    )
    return result


def execution_threshold_increment_cases(features: pd.DataFrame) -> pd.DataFrame:
    """1%p 임계값 증가 때 처음 포함되는 사업-연도 원자료를 보존합니다."""
    eligible = execution_eligible_frame(features).copy()
    rates = _numeric(eligible, "execution_rate")
    eligible["entry_threshold_percent"] = np.floor(rates * 100).astype("Int64") + 1
    eligible = eligible[
        eligible["entry_threshold_percent"].between(70, 95, inclusive="both")
    ].copy()
    eligible["entry_threshold"] = eligible["entry_threshold_percent"] / 100
    current_budget = _numeric(eligible, "current_budget_analysis_amount")
    eligible["entry_threshold_current_budget_rank"] = (
        current_budget.groupby(eligible["entry_threshold_percent"])
        .rank(method="min", ascending=False)
        .astype("Int64")
    )
    for column in [
        "analysis_included_classified",
        "exclusion_category_classified",
        "classification_status",
        "overall_ranking_eligible",
        "ranking_component_limitation_reasons",
    ]:
        if column not in eligible.columns:
            eligible[column] = pd.NA
    columns = [
        "entry_threshold",
        "entry_threshold_percent",
        "entry_threshold_current_budget_rank",
        "source_project_year_id",
        "classification_project_id",
        "fiscal_year",
        "ministry_code",
        "analysis_ministry_name",
        "account_type_classified",
        "fiscal_instrument",
        "project_size_bucket",
        "program_code",
        "program_name",
        "subactivity_code",
        "subactivity_name",
        "execution_rate",
        "original_budget_analysis_amount",
        "current_budget_analysis_amount",
        "settlement_analysis_amount",
        "financial_quality_level",
        "analysis_included_classified",
        "exclusion_category_classified",
        "classification_status",
        "overall_ranking_eligible",
        "ranking_component_limitation_reasons",
        "source_trace",
    ]
    return eligible[columns].sort_values(
        ["entry_threshold_percent", "entry_threshold_current_budget_rank"]
    )


def threshold_group_bias(
    sensitivity: pd.DataFrame,
) -> pd.DataFrame:
    """집단 탐지율을 전체 탐지율과 비교합니다."""
    overall = sensitivity[sensitivity["dimension"].eq("OVERALL")][
        ["threshold", "detected_row_share"]
    ].rename(columns={"detected_row_share": "overall_detected_row_share"})
    grouped = sensitivity[
        sensitivity["dimension"].isin(["MINISTRY", "ACCOUNT_TYPE", "FISCAL_YEAR", "PROJECT_SIZE"])
    ].copy()
    grouped = grouped.merge(overall, on="threshold", how="left", validate="many_to_one")

    # 재정수단·품질 상태는 동일한 적격 모집단에서 별도로 계산합니다.
    return grouped


def build_threshold_group_bias(
    features: pd.DataFrame,
    sensitivity: pd.DataFrame,
) -> pd.DataFrame:
    """요청된 여섯 집단의 임계값별 편향 진단을 완성합니다."""
    eligible = execution_eligible_frame(features)
    overall_rates = sensitivity[sensitivity["dimension"].eq("OVERALL")].set_index("threshold")[
        "detected_row_share"
    ]
    rows: list[dict[str, Any]] = []
    for threshold in THRESHOLDS:
        overall_rate = float(overall_rates.loc[threshold])
        for dimension, column in BIAS_DIMENSIONS.items():
            for value, index in eligible.groupby(column, dropna=False).groups.items():
                part = eligible.loc[index]
                detected = _numeric(part, "execution_rate").lt(threshold)
                group_rate = float(detected.mean()) if len(part) else math.nan
                ratio = _safe_rate(group_rate, overall_rate)
                if pd.notna(ratio) and ratio >= 2:
                    bias_flag = "HIGH_OVER_REPRESENTATION"
                elif pd.notna(ratio) and ratio <= 0.5:
                    bias_flag = "LOW_UNDER_REPRESENTATION"
                else:
                    bias_flag = "WITHIN_DIAGNOSTIC_BAND"
                rows.append(
                    {
                        "population": "execution_ranking_eligible_excluding_over_100",
                        "threshold": threshold,
                        "threshold_percent": round(threshold * 100),
                        "dimension": dimension,
                        "dimension_value": value,
                        "eligible_row_count": len(part),
                        "detected_row_count": int(detected.sum()),
                        "group_detected_rate": group_rate,
                        "overall_detected_rate": overall_rate,
                        "group_to_overall_detection_ratio": ratio,
                        "diagnostic_bias_flag": bias_flag,
                        "small_denominator_flag": len(part) < 20,
                        "diagnostic_rule": "ratio>=2 or ratio<=0.5; not a policy threshold",
                    }
                )
    return pd.DataFrame(rows)


def _largest_tie_share(values: pd.Series) -> float:
    counts = values.value_counts(dropna=True)
    return _safe_rate(float(counts.max()), float(counts.sum())) if len(counts) else math.nan


def _boundary_count(values: pd.Series, quantile: float) -> tuple[float, int]:
    cutoff = float(values.quantile(quantile))
    tied = np.isclose(values.astype(float), cutoff, rtol=1e-12, atol=1e-12)
    return cutoff, int(tied.sum())


def peer_confidence(expected_tail_count: float) -> tuple[bool, str]:
    """기대 꼬리 관측 수 기반 잠정 적용 가능성과 신뢰도를 반환합니다."""
    if expected_tail_count < 2:
        return False, "NOT_AVAILABLE"
    if expected_tail_count < 5:
        return True, "LOW"
    if expected_tail_count < 10:
        return True, "MEDIUM"
    return True, "HIGH"


def peer_distribution_diagnostics(features: pd.DataFrame) -> pd.DataFrame:
    """비교집단별 동률 구조와 하위 꼬리 표본 안정성을 계산합니다."""
    eligible = execution_eligible_frame(features)
    rows: list[dict[str, Any]] = []
    for (year, group), part in eligible.groupby(["fiscal_year", "comparison_group"], dropna=False):
        values = _numeric(part, "execution_rate").dropna()
        p10, p10_ties = _boundary_count(values, 0.10)
        p20, p20_ties = _boundary_count(values, 0.20)
        common = {
            "population": "execution_ranking_eligible_excluding_over_100",
            "fiscal_year": year,
            "comparison_group": group,
            "peer_group_size": len(values),
            "execution_unique_value_count": values.nunique(),
            "execution_unique_value_share": _safe_rate(values.nunique(), len(values)),
            "execution_exact_100_count": int(np.isclose(values, 1.0).sum()),
            "execution_exact_100_share": float(np.isclose(values, 1.0).mean()),
            "largest_tie_block_share": _largest_tie_share(values),
            "bottom_10_cutoff": p10,
            "bottom_10_boundary_tie_count": p10_ties,
            "bottom_20_cutoff": p20,
            "bottom_20_boundary_tie_count": p20_ties,
        }
        for criterion, share in [
            ("EXECUTION_BOTTOM_10", 0.10),
            ("EXECUTION_BOTTOM_20", 0.20),
        ]:
            expected = len(values) * share
            available, confidence = peer_confidence(expected)
            rows.append(
                {
                    **common,
                    "criterion": criterion,
                    "tail_share": share,
                    "peer_expected_tail_count": expected,
                    "peer_signal_available": available,
                    "peer_signal_confidence": confidence,
                    "confidence_rule_status": "CANDIDATE_NOT_FINAL_CONFIG",
                }
            )
    return pd.DataFrame(rows)


def _amount_share(
    numerator: pd.DataFrame,
    denominator: pd.DataFrame,
    column: str,
) -> float:
    return _safe_rate(_sum(numerator, column), _sum(denominator, column))


def year_end_pattern_types(
    features: pd.DataFrame,
    peer_flags: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """연말집중 고정 유형과 보수적 P90 중첩을 집계합니다."""
    p90 = peer_flags[
        [
            "source_project_year_id",
            "peer_p90_year_end_conservative_tie_block",
            "peer_p90_group_size",
        ]
    ]
    frame = features.merge(
        p90,
        on="source_project_year_id",
        how="left",
        validate="one_to_one",
    )
    eligible = (
        _bool(frame, "monthly_signal_eligible_validated")
        & _numeric(frame, "q4_expenditure_share").notna()
        & _numeric(frame, "december_single_month_share").notna()
    )
    frame = frame.loc[eligible].copy()
    q4 = _bool(frame, "fixed_q4_40_flag")
    december = _bool(frame, "fixed_december_20_flag")
    fixed = q4 | december
    p90_flag = _bool(frame, "peer_p90_year_end_conservative_tie_block")
    frame["year_end_fixed_pattern"] = np.select(
        [q4 & ~december, ~q4 & december, q4 & december],
        ["Q4_ONLY", "DECEMBER_ONLY", "BOTH_FIXED"],
        default="NO_FIXED",
    )
    frame["conservative_p90_flag"] = p90_flag
    frame["fixed_and_p90_flag"] = fixed & p90_flag
    frame["peer_p90_only_flag"] = ~fixed & p90_flag
    frame["current_budget_plot_size"] = _numeric(frame, "current_budget_analysis_amount")
    frame["current_budget_plot_size"] = frame["current_budget_plot_size"].where(
        frame["current_budget_plot_size"].gt(0)
    )
    frame["current_budget_plot_size_log"] = np.log1p(frame["current_budget_plot_size"])

    specs: dict[str, pd.Series] = {
        "Q4_ONLY": q4 & ~december,
        "DECEMBER_ONLY": ~q4 & december,
        "BOTH_FIXED": q4 & december,
        "PEER_P90_ONLY": ~fixed & p90_flag,
        "FIXED_AND_P90": fixed & p90_flag,
    }
    dimensions = {
        "OVERALL": None,
        "ACCOUNT_TYPE": "account_type_classified",
        "MINISTRY": "analysis_ministry_name",
    }
    rows: list[dict[str, Any]] = []
    for pattern, flag in specs.items():
        for dimension, column in dimensions.items():
            groups = (
                [("ALL", frame.index)]
                if column is None
                else frame.groupby(column, dropna=False).groups.items()
            )
            for value, index in groups:
                denominator = frame.loc[index]
                detected = frame.loc[index][flag.loc[index]]
                rows.append(
                    {
                        "population": "validated_monthly_pattern_with_nonnull_shares",
                        "pattern_type": pattern,
                        "dimension": dimension,
                        "dimension_value": value,
                        "eligible_row_count": len(denominator),
                        "detected_row_count": len(detected),
                        "detected_row_share": _safe_rate(len(detected), len(denominator)),
                        "detected_unique_project_count": detected[
                            "classification_project_id"
                        ].nunique(),
                        "original_budget_share": _amount_share(
                            detected,
                            denominator,
                            "original_budget_analysis_amount",
                        ),
                        "current_budget_share": _amount_share(
                            detected,
                            denominator,
                            "current_budget_analysis_amount",
                        ),
                        "settlement_share": _amount_share(
                            detected,
                            denominator,
                            "settlement_analysis_amount",
                        ),
                        "peer_p90_missing_count": int(
                            denominator["peer_p90_year_end_conservative_tie_block"].isna().sum()
                        ),
                    }
                )
    point_columns = [
        "source_project_year_id",
        "classification_project_id",
        "fiscal_year",
        "ministry_code",
        "analysis_ministry_name",
        "account_type_classified",
        "program_code",
        "program_name",
        "subactivity_code",
        "subactivity_name",
        "q4_expenditure_share",
        "december_single_month_share",
        "current_budget_analysis_amount",
        "current_budget_plot_size_log",
        "year_end_fixed_pattern",
        "conservative_p90_flag",
        "fixed_and_p90_flag",
        "peer_p90_only_flag",
        "peer_p90_group_size",
        "source_trace",
    ]
    return pd.DataFrame(rows), frame[point_columns].copy()


def _has_consecutive_true(years: list[int]) -> bool:
    ordered = sorted(years)
    return any(right - left == 1 for left, right in pairwise(ordered))


def repeated_signal_distribution(features: pd.DataFrame) -> pd.DataFrame:
    """고유 사업·신호별 반복 횟수와 유효연도 비율을 생성합니다."""
    rows: list[dict[str, Any]] = []
    for project_id, part in features.groupby("classification_project_id", dropna=False):
        latest = part.sort_values("fiscal_year").iloc[-1]
        annual_budget = _numeric(part, "original_budget_analysis_amount")
        average_budget = float(annual_budget.mean()) if annual_budget.notna().any() else math.nan
        for signal_name, column in SIGNAL_SPECS.items():
            valid = part[column].notna()
            valid_part = part.loc[valid].copy()
            occurred = valid_part[_bool(valid_part, column)]
            valid_count = valid_part["fiscal_year"].nunique()
            occurrence_count = occurred["fiscal_year"].nunique()
            ratio = _safe_rate(occurrence_count, valid_count)
            consecutive = _has_consecutive_true(
                occurred["fiscal_year"].astype(int).unique().tolist()
            )
            if valid_count == 2 and occurrence_count == 2:
                pattern = "TWO_OF_TWO"
            elif valid_count == 3 and occurrence_count == 2:
                pattern = "TWO_OF_THREE"
            elif valid_count == 4 and occurrence_count == 2:
                pattern = "TWO_OF_FOUR"
            elif valid_count == 4 and occurrence_count >= 3:
                pattern = "THREE_PLUS_OF_FOUR"
            else:
                pattern = "OTHER"
            rows.append(
                {
                    "population": "unique_project_signal_recurrence",
                    "classification_project_id": project_id,
                    "signal_name": signal_name,
                    "ministry_code": latest["ministry_code"],
                    "analysis_ministry_name": latest["analysis_ministry_name"],
                    "account_type_classified": latest["account_type_classified"],
                    "program_code_latest": latest["program_code"],
                    "program_name_latest": latest["program_name"],
                    "subactivity_code_latest": latest["subactivity_code"],
                    "subactivity_name_latest": latest["subactivity_name"],
                    "valid_observation_year_count": valid_count,
                    "signal_occurrence_year_count": occurrence_count,
                    "signal_occurrence_year_share": ratio,
                    "consecutive_two_year_flag": consecutive,
                    "nonconsecutive_two_plus_flag": occurrence_count >= 2 and not consecutive,
                    "repetition_pattern": pattern,
                    "repeat_2plus_flag": occurrence_count >= 2,
                    "repeat_2plus_and_50pct_flag": occurrence_count >= 2
                    and pd.notna(ratio)
                    and ratio >= 0.5,
                    "repeat_3plus_flag": occurrence_count >= 3,
                    "average_annual_original_budget": average_budget,
                    "average_annual_budget_plot_size": (
                        math.log1p(average_budget)
                        if pd.notna(average_budget) and average_budget > 0
                        else math.nan
                    ),
                    "source_project_year_count": len(part),
                }
            )
    return pd.DataFrame(rows)


def _segment_bias_summary(
    frame: pd.DataFrame,
    flag: pd.Series,
    *,
    dimensions: dict[str, str] | None = None,
) -> tuple[float, float, str]:
    dimensions = dimensions or {
        "MINISTRY": "analysis_ministry_name",
        "ACCOUNT_TYPE": "account_type_classified",
        "PROJECT_SIZE": "project_size_bucket",
    }
    overall = float(flag.mean()) if len(frame) else math.nan
    ratios: list[tuple[str, Any, float, int]] = []
    for dimension, column in dimensions.items():
        for value, index in frame.groupby(column, dropna=False).groups.items():
            rate = float(flag.loc[index].mean())
            ratios.append(
                (
                    dimension,
                    value,
                    _safe_rate(rate, overall),
                    len(index),
                )
            )
    valid = [item for item in ratios if pd.notna(item[2])]
    if not valid:
        return math.nan, math.nan, "NO_VALID_GROUP_RATE"
    highest = max(valid, key=lambda item: item[2])
    lowest = min(valid, key=lambda item: item[2])
    summary = (
        f"max={highest[0]}:{highest[1]} {highest[2]:.2f}x(n={highest[3]}); "
        f"min={lowest[0]}:{lowest[1]} {lowest[2]:.2f}x(n={lowest[3]})"
    )
    return float(highest[2]), float(lowest[2]), summary


def _row_option(
    features: pd.DataFrame,
    flag: pd.Series,
    *,
    option_id: str,
    option_name: str,
    definition: str,
    stability: str,
    explainability: str,
    advantages: str,
    disadvantages: str,
    recommended_role: str,
    limitations: str,
) -> dict[str, Any]:
    detected = features.loc[flag]
    max_bias, min_bias, bias_summary = _segment_bias_summary(features, flag)
    return {
        "option_id": option_id,
        "option_name": option_name,
        "analysis_grain": "project_year",
        "definition": definition,
        "eligible_row_count": len(features),
        "detected_row_count": len(detected),
        "detected_row_share": _safe_rate(len(detected), len(features)),
        "detected_unique_project_count": detected["classification_project_id"].nunique(),
        "detected_unique_project_share": _safe_rate(
            detected["classification_project_id"].nunique(),
            features["classification_project_id"].nunique(),
        ),
        "detected_original_budget_share": _amount_share(
            detected,
            features,
            "original_budget_analysis_amount",
        ),
        "detected_current_budget_share": _amount_share(
            detected,
            features,
            "current_budget_analysis_amount",
        ),
        "max_group_bias_ratio": max_bias,
        "min_group_bias_ratio": min_bias,
        "group_bias_summary": bias_summary,
        "sample_stability": stability,
        "explainability": explainability,
        "advantages": advantages,
        "disadvantages": disadvantages,
        "recommended_role": recommended_role,
        "application_limitations": limitations,
        "final_policy_status": "CANDIDATE_NOT_FINAL_CONFIG",
    }


def _project_option(
    recurrence: pd.DataFrame,
    features: pd.DataFrame,
    flag_column: str,
    *,
    option_id: str,
    option_name: str,
    definition: str,
    stability: str,
    explainability: str,
    advantages: str,
    disadvantages: str,
    recommended_role: str,
    limitations: str,
) -> dict[str, Any]:
    project_flags = recurrence.groupby("classification_project_id")[flag_column].any()
    selected_ids = set(project_flags[project_flags].index)
    selected_projects = recurrence[
        recurrence["classification_project_id"].isin(selected_ids)
    ].drop_duplicates("classification_project_id")
    signal_years = features[
        features["classification_project_id"].isin(selected_ids)
        & (
            _bool(features, "under_90_combined_flag")
            | _bool(features, "fixed_year_end_concentration_flag")
        )
    ]
    project_budget = (
        features.groupby("classification_project_id")["original_budget_analysis_amount"]
        .mean()
        .dropna()
    )
    selected_budget = project_budget[project_budget.index.isin(selected_ids)]
    return {
        "option_id": option_id,
        "option_name": option_name,
        "analysis_grain": "project",
        "definition": definition,
        "eligible_row_count": recurrence["classification_project_id"].nunique(),
        "detected_row_count": len(signal_years),
        "detected_row_share": math.nan,
        "detected_unique_project_count": len(selected_projects),
        "detected_unique_project_share": _safe_rate(
            len(selected_projects),
            recurrence["classification_project_id"].nunique(),
        ),
        "detected_original_budget_share": _safe_rate(
            float(selected_budget.sum()), float(project_budget.sum())
        ),
        "detected_current_budget_share": math.nan,
        "max_group_bias_ratio": math.nan,
        "min_group_bias_ratio": math.nan,
        "group_bias_summary": "project-grain recurrence; inspect recurrence CSV by segment",
        "sample_stability": stability,
        "explainability": explainability,
        "advantages": advantages,
        "disadvantages": disadvantages,
        "recommended_role": recommended_role,
        "application_limitations": limitations,
        "final_policy_status": "CANDIDATE_NOT_FINAL_CONFIG",
    }


def analysis_policy_options(
    features: pd.DataFrame,
    peer_flags: pd.DataFrame,
    recurrence: pd.DataFrame,
) -> pd.DataFrame:
    """운영 기준 후보별 규모·편향·설명 가능성을 비교합니다."""
    execution = execution_eligible_frame(features)
    peer = peer_flags[
        [
            "source_project_year_id",
            "peer_bottom_10_conservative_tie_block",
            "peer_p90_year_end_conservative_tie_block",
        ]
    ]
    frame = features.merge(peer, on="source_project_year_id", how="left", validate="one_to_one")
    execution_ids = set(execution["source_project_year_id"])
    execution_frame = frame[frame["source_project_year_id"].isin(execution_ids)].copy()
    under80 = _numeric(execution_frame, "execution_rate").lt(0.8)
    under90 = _numeric(execution_frame, "execution_rate").lt(0.9)
    peer10 = _bool(execution_frame, "peer_bottom_10_conservative_tie_block")
    monthly = frame[_bool(frame, "monthly_signal_eligible_validated")].copy()
    fixed = _bool(monthly, "fixed_year_end_concentration_flag")
    p90 = _bool(monthly, "peer_p90_year_end_conservative_tie_block")

    rows = [
        _row_option(
            execution_frame,
            under80,
            option_id="EXECUTION_UNDER_80",
            option_name="집행률 80% 미만 단일 기준",
            definition="execution_rate < 0.80",
            stability="HIGH_FOR_ABSOLUTE_RULE",
            explainability="HIGH",
            advantages="강한 편차를 간단히 설명하고 표본 범위가 관리 가능",
            disadvantages="80~90%의 주의 사례를 놓침",
            recommended_role="STRONG_SIGNAL",
            limitations="회계별 분모 확인 불가 또는 100% 초과 행",
        ),
        _row_option(
            execution_frame,
            under90,
            option_id="EXECUTION_UNDER_90",
            option_name="집행률 90% 미만 단일 기준",
            definition="execution_rate < 0.90",
            stability="HIGH_FOR_ABSOLUTE_RULE",
            explainability="MEDIUM",
            advantages="주의 범위까지 한 번에 포착",
            disadvantages="강한 편차와 경미한 편차가 섞임",
            recommended_role="SENSITIVITY_OR_SUMMARY",
            limitations="심각도를 별도 등급으로 표시해야 함",
        ),
        _row_option(
            execution_frame,
            under90,
            option_id="EXECUTION_TWO_STAGE_80_90",
            option_name="80%·90% 2단계 기준",
            definition="<80 strong; 80<=rate<90 caution",
            stability="HIGH_FOR_ABSOLUTE_RULE",
            explainability="HIGH",
            advantages="강한 신호와 주의 신호를 분리",
            disadvantages="두 기준 모두 운영 문서에 정의해야 함",
            recommended_role="PRIMARY_POLICY",
            limitations="정책 실패 판정이 아닌 설명 필요 강도",
        ),
        _row_option(
            execution_frame,
            under90 | peer10,
            option_id="ABSOLUTE_AND_RELATIVE_PARALLEL",
            option_name="절대 기준과 상대 기준 병행",
            definition="<90 absolute OR conservative peer bottom 10",
            stability="CONDITIONAL_ON_PEER_CONFIDENCE",
            explainability="MEDIUM",
            advantages="절대 수준과 동료집단 내 상대 위치를 함께 제공",
            disadvantages="상대 신호 동률·소표본 규칙이 필요",
            recommended_role="PRIMARY_PLUS_AUXILIARY",
            limitations="peer confidence NOT_AVAILABLE 또는 LOW 집단",
        ),
        _row_option(
            monthly,
            fixed,
            option_id="YEAR_END_FIXED_40_20",
            option_name="연말집중 고정 기준",
            definition="q4_share>=0.40 OR december_share>=0.20",
            stability="MEDIUM",
            explainability="HIGH",
            advantages="공통 규칙으로 설명이 쉽고 4분기형·12월형 분리 가능",
            disadvantages="사업 특성별 정상 지급주기를 반영하지 못함",
            recommended_role="PRIMARY_EXPLORATION",
            limitations="월별 패턴 미확인·0원 집행·정상 연말 지급 사업",
        ),
        _row_option(
            monthly,
            fixed | p90,
            option_id="YEAR_END_FIXED_AND_P90",
            option_name="고정 기준과 보수적 P90 병행",
            definition="fixed rule OR conservative peer P90",
            stability="CONDITIONAL_ON_PEER_CONFIDENCE",
            explainability="MEDIUM",
            advantages="절대 집중과 동료집단 내 상대 집중을 함께 확인",
            disadvantages="두 월별 비중의 합집합이라 명목 10%보다 넓음",
            recommended_role="PRIMARY_PLUS_AUXILIARY",
            limitations="P90 비교집단 기대 꼬리 관측 2개 미만",
        ),
    ]
    recurrence = recurrence.copy()
    recurrence["repeat_2_any_same_signal"] = recurrence.groupby("classification_project_id")[
        "repeat_2plus_flag"
    ].transform("any")
    recurrence["repeat_primary_any_same_signal"] = recurrence.groupby("classification_project_id")[
        "repeat_2plus_and_50pct_flag"
    ].transform("any")
    recurrence["consecutive_any_same_signal"] = recurrence.groupby("classification_project_id")[
        "consecutive_two_year_flag"
    ].transform("any")
    rows.extend(
        [
            _project_option(
                recurrence,
                features,
                "repeat_2_any_same_signal",
                option_id="REPEAT_TWO_PLUS",
                option_name="반복 2회 이상",
                definition="same signal occurs in at least two valid years",
                stability="LOW_WHEN_VALID_YEAR_COUNT_IS_SMALL",
                explainability="HIGH",
                advantages="단년도 우연 변동을 줄임",
                disadvantages="2년 중 2회와 4년 중 2회를 동일하게 취급",
                recommended_role="SENSITIVITY",
                limitations="유효 관측연도 수가 적은 사업",
            ),
            _project_option(
                recurrence,
                features,
                "repeat_primary_any_same_signal",
                option_id="REPEAT_TWO_PLUS_AND_50PCT",
                option_name="반복 2회 이상 및 유효연도 50% 이상",
                definition="same signal count>=2 AND count/valid_years>=0.5",
                stability="MEDIUM_TO_HIGH_BY_VALID_YEAR_COUNT",
                explainability="HIGH",
                advantages="횟수와 관측 기회를 동시에 반영",
                disadvantages="유효연도 2년 사업은 여전히 제한적",
                recommended_role="PRIMARY_RECURRENCE",
                limitations="유효 관측연도 수를 항상 함께 표시",
            ),
            _project_option(
                recurrence,
                features,
                "consecutive_any_same_signal",
                option_id="REPEAT_CONSECUTIVE_TWO",
                option_name="연속 2회 강화 신호",
                definition="same signal occurs in two consecutive fiscal years",
                stability="MEDIUM",
                explainability="HIGH",
                advantages="지속되는 운영 패턴을 직접 표현",
                disadvantages="비연속 반복을 놓침",
                recommended_role="REINFORCED_SIGNAL",
                limitations="관측창 경계와 중간연도 결측",
            ),
        ]
    )
    return pd.DataFrame(rows)


def _set_plot_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "Malgun Gothic",
            "axes.unicode_minus": False,
            "figure.facecolor": "white",
            "axes.facecolor": "#F8FAFC",
            "axes.edgecolor": "#CBD5E1",
            "grid.color": PALETTE["grid"],
            "axes.titleweight": "bold",
            "axes.titlesize": 12,
            "axes.labelcolor": PALETTE["ink"],
            "text.color": PALETTE["ink"],
        }
    )


def _save(fig: plt.Figure, path: Path, *, top: float = 0.92) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=(0, 0, 1, top))
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


def _plot_ecdf_panel(
    ecdf: pd.DataFrame,
    *,
    dimension: str,
    title: str,
    path: Path,
) -> Path:
    subset = ecdf[ecdf["dimension"].eq(dimension)]
    values = list(subset["dimension_value"].drop_duplicates())
    columns = 1 if len(values) == 1 else 2
    rows = math.ceil(len(values) / columns)
    fig, axes = plt.subplots(rows, columns, figsize=(13, 4.4 * rows), squeeze=False)
    for ax, value in zip(axes.flat, values, strict=False):
        part = subset[subset["dimension_value"].eq(value)]
        for weighting, color, line_style in [
            ("UNWEIGHTED", PALETTE["blue"], "-"),
            ("CURRENT_BUDGET_WEIGHTED", PALETTE["orange"], "--"),
        ]:
            line = part[part["weighting"].eq(weighting)].sort_values("execution_rate")
            ax.step(
                line["execution_rate"],
                line["cumulative_share"],
                where="post",
                color=color,
                linestyle=line_style,
                linewidth=2,
                label=weighting,
            )
        ax.axvline(0.8, color=PALETTE["pink"], linestyle=":", label="80%")
        ax.axvline(0.9, color=PALETTE["gold"], linestyle=":", label="90%")
        sample = int(part["sample_size"].max()) if len(part) else 0
        ax.set_title(f"{value} · n={sample:,}")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1.01)
        ax.set_xlabel("집행률")
        ax.set_ylabel("누적 비율")
        ax.grid(alpha=0.7)
    for ax in axes.flat[len(values) :]:
        ax.axis("off")
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.88),
        ncol=4,
        frameon=False,
    )
    fig.suptitle(
        f"{title}\n모집단: execution 적격·100% 초과 제외, 비가중과 예산현액 가중",
        y=0.98,
    )
    return _save(fig, path, top=0.78)


def create_decision_support_figures(
    ecdf: pd.DataFrame,
    sensitivity: pd.DataFrame,
    bias: pd.DataFrame,
    peer: pd.DataFrame,
    year_points: pd.DataFrame,
    recurrence: pd.DataFrame,
    options: pd.DataFrame,
    figure_dir: Path,
) -> tuple[list[Path], pd.DataFrame]:
    """의사결정에 필요한 정적 시각화와 차트 맵을 생성합니다."""
    _set_plot_style()
    figure_paths: list[Path] = []
    chart_rows: list[dict[str, Any]] = []

    for dimension, filename, title in [
        ("OVERALL", "execution_ecdf_overall.png", "전체 집행률 ECDF"),
        ("ACCOUNT_TYPE", "execution_ecdf_by_account_type.png", "회계유형별 집행률 ECDF"),
        ("MINISTRY", "execution_ecdf_by_ministry.png", "부처별 집행률 ECDF"),
        ("FISCAL_YEAR", "execution_ecdf_by_year.png", "연도별 집행률 ECDF"),
        ("PROJECT_SIZE", "execution_ecdf_by_project_size.png", "사업규모별 집행률 ECDF"),
    ]:
        path = _plot_ecdf_panel(
            ecdf,
            dimension=dimension,
            title=title,
            path=figure_dir / filename,
        )
        figure_paths.append(path)
        chart_rows.append(
            {
                "figure": filename,
                "section": "집행률 분포",
                "question": f"{dimension}에서 사업 수와 예산가중 분포가 다른가",
                "chart_family": "distribution",
                "chart_type": "ECDF step line",
                "source_file": "execution_ecdf_summary.csv",
                "reading_note": "같은 x에서 주황선이 파란선보다 높으면 저집행 구간의 예산 비중이 사업 수 비중보다 큼",
            }
        )

    overall = sensitivity[sensitivity["dimension"].eq("OVERALL")].sort_values("threshold")
    fig, axes = plt.subplots(2, 1, figsize=(10, 9), sharex=True)
    axes[0].plot(
        overall["threshold_percent"],
        overall["detected_row_share"],
        marker="o",
        color=PALETTE["blue"],
        label="사업-연도 비율",
    )
    axes[0].plot(
        overall["threshold_percent"],
        overall["detected_unique_project_share"],
        marker="s",
        color=PALETTE["olive"],
        label="고유 사업 비율",
    )
    axes[1].plot(
        overall["threshold_percent"],
        overall["original_budget_share"],
        color=PALETTE["blue_dark"],
        label="본예산",
    )
    axes[1].plot(
        overall["threshold_percent"],
        overall["current_budget_share"],
        color=PALETTE["orange"],
        label="예산현액",
    )
    axes[1].plot(
        overall["threshold_percent"],
        overall["settlement_share"],
        color=PALETTE["pink"],
        label="결산 지출",
    )
    for ax in axes:
        ax.axvline(80, color=PALETTE["pink"], linestyle=":")
        ax.axvline(90, color=PALETTE["gold"], linestyle=":")
        ax.grid()
        ax.legend()
        ax.set_ylabel("탐지 비율")
    axes[1].set_xlabel("집행률 임계값(%)")
    fig.suptitle(
        f"집행률 임계값 민감도\n70~95%, 1%p 간격, 적격 n={int(overall['eligible_row_count'].max()):,}"
    )
    figure_paths.append(_save(fig, figure_dir / "execution_threshold_sensitivity.png"))
    chart_rows.append(
        {
            "figure": "execution_threshold_sensitivity.png",
            "section": "임계값 민감도",
            "question": "70~95%에서 탐지 행·사업·금액이 얼마나 달라지는가",
            "chart_family": "trend",
            "chart_type": "multi-line sensitivity curve",
            "source_file": "execution_threshold_sensitivity.csv",
            "reading_note": "기울기가 큰 구간은 1%p 변경에 민감한 구간이며 자동 절단점이 아님",
        }
    )

    selected_bias = bias[bias["threshold"].isin([0.8, 0.9])].copy()
    pivot = selected_bias.pivot_table(
        index=["dimension", "dimension_value"],
        columns="threshold_percent",
        values="group_to_overall_detection_ratio",
    )
    fig, ax = plt.subplots(figsize=(10, max(6, len(pivot) * 0.28)))
    image = ax.imshow(
        pivot.fillna(0).to_numpy(),
        aspect="auto",
        cmap="coolwarm",
        vmin=0,
        vmax=max(2, float(np.nanmax(pivot.to_numpy()))),
    )
    ax.set_yticks(
        range(len(pivot)),
        [f"{dimension} | {value}" for dimension, value in pivot.index],
        fontsize=7,
    )
    ax.set_xticks(range(len(pivot.columns)), [f"{value}%" for value in pivot.columns])
    ax.set_title("80%·90% 기준의 집단 탐지율 / 전체 탐지율")
    fig.colorbar(image, ax=ax, label="배수(2배·0.5배는 진단선)")
    figure_paths.append(_save(fig, figure_dir / "threshold_group_bias_heatmap.png"))
    chart_rows.append(
        {
            "figure": "threshold_group_bias_heatmap.png",
            "section": "집단 편향",
            "question": "80%·90% 기준이 특정 집단을 과대표집하는가",
            "chart_family": "matrix",
            "chart_type": "heatmap",
            "source_file": "threshold_group_bias.csv",
            "reading_note": "2배 이상 또는 0.5배 이하는 원인 확인 대상이며 정책상 제외 기준이 아님",
        }
    )

    peer10 = peer[peer["criterion"].eq("EXECUTION_BOTTOM_10")]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    axes[0].scatter(
        peer10["peer_group_size"],
        peer10["largest_tie_block_share"],
        s=30,
        alpha=0.65,
        color=PALETTE["blue"],
    )
    axes[0].set_xlabel("비교집단 크기")
    axes[0].set_ylabel("최대 동률 블록 비율")
    axes[0].set_title("비교집단 크기와 동률 집중")
    confidence_counts = (
        peer10["peer_signal_confidence"]
        .value_counts()
        .reindex(["NOT_AVAILABLE", "LOW", "MEDIUM", "HIGH"], fill_value=0)
    )
    axes[1].bar(
        confidence_counts.index,
        confidence_counts.values,
        color=[
            PALETTE["muted"],
            PALETTE["orange"],
            PALETTE["gold"],
            PALETTE["blue"],
        ],
    )
    axes[1].set_title("하위 10% 상대 신호 신뢰도 후보")
    axes[1].set_ylabel("비교집단-연도 수")
    for ax in axes:
        ax.grid(axis="y")
    fig.suptitle("상대 기준 적용 가능성 · 기대 꼬리 관측 수 기반 잠정 등급")
    figure_paths.append(_save(fig, figure_dir / "peer_distribution_diagnostics.png"))
    chart_rows.append(
        {
            "figure": "peer_distribution_diagnostics.png",
            "section": "상대 기준 안정성",
            "question": "비교집단 표본과 동률이 상대 신호를 지지하는가",
            "chart_family": "relationship and comparison",
            "chart_type": "scatter plus bar",
            "source_file": "peer_distribution_diagnostics.csv",
            "reading_note": "동률 블록이 크거나 기대 꼬리 관측이 2개 미만이면 상대 신호를 사용하지 않음",
        }
    )

    fig, ax = plt.subplots(figsize=(10, 7))
    account_values = year_points["account_type_classified"].astype(str).unique()
    colors = [
        PALETTE["blue"],
        PALETTE["orange"],
        PALETTE["olive"],
        PALETTE["pink"],
        PALETTE["gold"],
        PALETTE["muted"],
    ]
    for color, account in zip(colors, account_values, strict=False):
        part = year_points[year_points["account_type_classified"].astype(str).eq(account)]
        sizes = np.clip(part["current_budget_plot_size_log"].fillna(1) * 3, 8, 90)
        ax.scatter(
            part["q4_expenditure_share"],
            part["december_single_month_share"],
            s=sizes,
            alpha=0.35,
            color=color,
            label=account,
        )
    ax.axvline(0.4, color=PALETTE["pink"], linestyle=":")
    ax.axhline(0.2, color=PALETTE["gold"], linestyle=":")
    ax.set_xlabel("4분기 집행 비중")
    ax.set_ylabel("12월 단월 집행 비중")
    ax.set_title(
        f"연말집중 2차원 분포\n검증된 월별 패턴 n={len(year_points):,}, 점 크기=예산현액 로그"
    )
    ax.legend(fontsize=7)
    ax.grid()
    figure_paths.append(_save(fig, figure_dir / "year_end_pattern_scatter.png"))
    chart_rows.append(
        {
            "figure": "year_end_pattern_scatter.png",
            "section": "연말집중 유형",
            "question": "4분기형과 12월형 집중은 분리되는가",
            "chart_family": "relationship",
            "chart_type": "bubble scatter",
            "source_file": "year_end_pattern_points.csv",
            "reading_note": "세로선 오른쪽은 4분기형, 가로선 위는 12월형, 우상단은 두 기준 동시 충족",
        }
    )

    ministries = list(year_points["analysis_ministry_name"].dropna().unique())
    fig, axes = plt.subplots(
        math.ceil(len(ministries) / 2),
        2,
        figsize=(12, 4 * math.ceil(len(ministries) / 2)),
        squeeze=False,
    )
    for ax, ministry in zip(axes.flat, ministries, strict=False):
        part = year_points[year_points["analysis_ministry_name"].eq(ministry)]
        ax.scatter(
            part["q4_expenditure_share"],
            part["december_single_month_share"],
            s=12,
            alpha=0.4,
            color=PALETTE["blue"],
        )
        ax.axvline(0.4, color=PALETTE["pink"], linestyle=":")
        ax.axhline(0.2, color=PALETTE["gold"], linestyle=":")
        ax.set_title(f"{ministry} · n={len(part):,}")
        ax.set_xlabel("4분기 비중")
        ax.set_ylabel("12월 비중")
        ax.grid()
    for ax in axes.flat[len(ministries) :]:
        ax.axis("off")
    fig.suptitle("부처별 연말집중 2차원 분포")
    figure_paths.append(_save(fig, figure_dir / "year_end_pattern_by_ministry.png"))
    chart_rows.append(
        {
            "figure": "year_end_pattern_by_ministry.png",
            "section": "연말집중 유형",
            "question": "부처별 지급 구조 차이가 고정 기준에 영향을 주는가",
            "chart_family": "relationship",
            "chart_type": "faceted scatter",
            "source_file": "year_end_pattern_points.csv",
            "reading_note": "부처별 점 구름의 위치와 기준선 주변 밀도를 비교",
        }
    )

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), sharey=True)
    for ax, signal in zip(
        axes,
        ["UNDER_90_EXECUTION", "FIXED_YEAR_END"],
        strict=True,
    ):
        part = recurrence[recurrence["signal_name"].eq(signal)]
        colors_series = np.where(
            part["consecutive_two_year_flag"],
            PALETTE["orange"],
            PALETTE["blue"],
        )
        sizes = np.clip(part["average_annual_budget_plot_size"].fillna(1) * 2, 8, 80)
        ax.scatter(
            part["valid_observation_year_count"],
            part["signal_occurrence_year_share"],
            s=sizes,
            c=colors_series,
            alpha=0.4,
        )
        ax.axhline(0.5, color=PALETTE["pink"], linestyle=":")
        ax.set_title(signal)
        ax.set_xlabel("유효 관측연도 수")
        ax.grid()
    axes[0].set_ylabel("신호 발생연도 비율")
    fig.suptitle("사업별 반복 신호 분포\n주황=연속 2회, 점 크기=연평균 본예산 로그")
    figure_paths.append(_save(fig, figure_dir / "repeated_signal_distribution.png"))
    chart_rows.append(
        {
            "figure": "repeated_signal_distribution.png",
            "section": "반복 안정성",
            "question": "같은 반복 횟수가 유효 관측연도 수에 따라 어떻게 다른가",
            "chart_family": "relationship",
            "chart_type": "bubble scatter",
            "source_file": "repeated_signal_distribution.csv",
            "reading_note": "50%선 위이면서 2회 이상인 사업이 주 반복 후보, 연속 여부는 색으로 구분",
        }
    )

    fig, ax = plt.subplots(figsize=(11, 6))
    plot_options = options.sort_values("detected_unique_project_share")
    ax.barh(
        plot_options["option_name"],
        plot_options["detected_unique_project_share"],
        color=np.where(
            plot_options["recommended_role"].isin(
                ["PRIMARY_POLICY", "PRIMARY_RECURRENCE", "PRIMARY_EXPLORATION"]
            ),
            PALETTE["blue"],
            PALETTE["open"],
        ),
        edgecolor=PALETTE["blue_dark"],
    )
    ax.set_xlabel("탐지 고유 사업 비율")
    ax.set_title("분석정책 후보별 탐지 범위 · 분석 단위 차이 주의")
    ax.grid(axis="x")
    figure_paths.append(_save(fig, figure_dir / "analysis_policy_options.png"))
    chart_rows.append(
        {
            "figure": "analysis_policy_options.png",
            "section": "의사결정 대안",
            "question": "후보 기준별 탐지 범위와 권장 역할은 무엇인가",
            "chart_family": "comparison",
            "chart_type": "horizontal bar",
            "source_file": "analysis_policy_options.csv",
            "reading_note": "반복 기준은 project grain이라 행 기준 옵션과 직접 순위 비교하지 않음",
        }
    )
    return figure_paths, pd.DataFrame(chart_rows)


def _percent(value: Any) -> str:
    return "NA" if pd.isna(value) else f"{float(value):.1%}"


def _overall_threshold(
    sensitivity: pd.DataFrame,
    threshold: float,
) -> pd.Series:
    return sensitivity[
        sensitivity["dimension"].eq("OVERALL") & sensitivity["threshold"].eq(threshold)
    ].iloc[0]


def _overall_pattern(
    patterns: pd.DataFrame,
    pattern_type: str,
) -> pd.Series:
    return patterns[
        patterns["dimension"].eq("OVERALL") & patterns["pattern_type"].eq(pattern_type)
    ].iloc[0]


def _top_bias_rows(
    bias: pd.DataFrame,
    threshold: float,
    *,
    limit: int = 6,
) -> pd.DataFrame:
    return (
        bias[
            bias["threshold"].eq(threshold)
            & ~bias["small_denominator_flag"]
            & bias["diagnostic_bias_flag"].ne("WITHIN_DIAGNOSTIC_BAND")
        ]
        .sort_values(
            "group_to_overall_detection_ratio",
            ascending=False,
        )
        .head(limit)
    )


def build_decision_support_report(
    path: Path,
    summary: dict[str, Any],
    sensitivity: pd.DataFrame,
    increment_cases: pd.DataFrame,
    bias: pd.DataFrame,
    peer: pd.DataFrame,
    patterns: pd.DataFrame,
    recurrence: pd.DataFrame,
    options: pd.DataFrame,
    scope_sensitivity: pd.DataFrame,
    chart_map: pd.DataFrame,
) -> None:
    """발표·질의응답에 사용할 분석 기준 의사결정 문서를 작성합니다."""
    under80 = _overall_threshold(sensitivity, 0.8)
    under90 = _overall_threshold(sensitivity, 0.9)
    scope = scope_sensitivity.set_index("scenario")
    top_increments = (
        sensitivity[sensitivity["dimension"].eq("OVERALL") & sensitivity["rapid_change_candidate"]]
        .sort_values("incremental_change_rank")
        .copy()
    )
    q4_only = _overall_pattern(patterns, "Q4_ONLY")
    december_only = _overall_pattern(patterns, "DECEMBER_ONLY")
    both_fixed = _overall_pattern(patterns, "BOTH_FIXED")
    peer_only = _overall_pattern(patterns, "PEER_P90_ONLY")
    fixed_peer = _overall_pattern(patterns, "FIXED_AND_P90")
    peer10 = peer[peer["criterion"].eq("EXECUTION_BOTTOM_10")]
    confidence = (
        peer10["peer_signal_confidence"]
        .value_counts()
        .reindex(["NOT_AVAILABLE", "LOW", "MEDIUM", "HIGH"], fill_value=0)
    )
    repeated = recurrence[recurrence["repeat_2plus_and_50pct_flag"]]
    low_repeat = repeated[repeated["signal_name"].eq("UNDER_90_EXECUTION")]
    year_repeat = repeated[repeated["signal_name"].eq("FIXED_YEAR_END")]
    bias80 = _top_bias_rows(bias, 0.8)
    bias90 = _top_bias_rows(bias, 0.9)
    policy = options.set_index("option_id")
    threshold90_cases = increment_cases[increment_cases["entry_threshold_percent"].eq(90)].head(5)
    threshold90_top2 = threshold90_cases.head(2)
    threshold90_top2_unknown = int(threshold90_top2["fiscal_instrument"].eq("UNKNOWN").sum())
    threshold90_top2_included = int(
        threshold90_top2["analysis_included_classified"].fillna(False).sum()
    )

    lines = [
        "# 분석 기준 의사결정 지원 보고서",
        "",
        "## 기술 요약",
        "",
        (
            f"집행률 분석 적격·100% 초과 제외 모집단은 {summary['execution_primary_rows']:,}행입니다. "
            f"80% 미만은 {int(under80['detected_row_count']):,}행"
            f"({_percent(under80['detected_row_share'])}), 90% 미만은 "
            f"{int(under90['detected_row_count']):,}행"
            f"({_percent(under90['detected_row_share'])})입니다. 80%와 90%는 분포가 자동으로 "
            "발견한 절단점이 아니라, 탐지 강도를 두 단계로 설명하기 위한 잠정 운영 기준입니다."
        ),
        "",
        (
            "권장안은 `<80%`를 강한 집행설명필요, `80~90%`를 주의 신호로 구분하고, "
            "보수적 하위 10%는 신뢰도 등급이 있는 보조 신호로 사용하는 것입니다. "
            "연말집중은 4분기 40% 또는 12월 20%를 주 탐색 기준 후보로 두되 두 유형을 분리하며, "
            "보수적 P90은 비교집단 맥락만 제공합니다. 반복은 같은 신호가 2회 이상이면서 "
            "유효 관측연도의 50% 이상일 때 주 반복 후보로 봅니다."
        ),
        "",
        (
            "이 문서는 최종 임계값이나 전체 순위를 저장하지 않습니다. 모든 표·그림은 "
            "`data/analytics/decision_support/`의 CSV를 직접 수정·재분석할 수 있게 구성했고, "
            "기존 M3와 원본 데이터는 덮어쓰지 않았습니다."
        ),
        "",
        "## 1. 집행률 분포를 읽는 법",
        "",
        (
            "ECDF의 파란 실선은 사업-연도 수 기준, 주황 점선은 예산현액 가중 기준입니다. "
            "같은 집행률에서 주황선이 더 높으면 저집행 구간이 차지하는 예산 비중이 사업 수 "
            "비중보다 크다는 뜻입니다. 80%·90% 수직선은 후보 기준이며, 그래프는 전체·회계유형·"
            "부처·연도·사업규모별로 분리했습니다."
        ),
        "",
    ]
    for figure in [
        "execution_ecdf_overall.png",
        "execution_ecdf_by_account_type.png",
        "execution_ecdf_by_ministry.png",
        "execution_ecdf_by_year.png",
        "execution_ecdf_by_project_size.png",
    ]:
        lines.extend([f"![{figure}](../artifacts/figures/decision_support/{figure})", ""])
    lines.extend(
        [
            (
                "발표 시에는 전체 ECDF로 기준 위치를 설명하고, 질의응답에서는 회계·부처별 패널로 "
                "특정 집단 편향 여부를 답하는 방식이 적절합니다."
            ),
            "",
            "## 2. 70~95% 민감도는 기준 변경의 영향을 보여줍니다",
            "",
            (
                f"80% 기준은 고유 사업 {int(under80['detected_unique_project_count']):,}개와 "
                f"예산현액 {_percent(under80['current_budget_share'])}를 탐지합니다. 90% 기준은 "
                f"고유 사업 {int(under90['detected_unique_project_count']):,}개와 예산현액 "
                f"{_percent(under90['current_budget_share'])}를 탐지합니다. 두 값을 합쳐 하나의 "
                "정책 판정으로 쓰지 않고 강한 신호와 주의 신호로 나누는 이유입니다."
            ),
            "",
            "![execution_threshold_sensitivity.png](../artifacts/figures/decision_support/execution_threshold_sensitivity.png)",
            "",
            (
                "그래프의 기울기는 임계값을 1%p 높였을 때 새로 포함되는 사업·금액의 크기입니다. "
                "가장 큰 1%p 증가 구간 세 개는 자동 임계값이 아니라 추가 확인 후보로만 표시했습니다."
            ),
            "",
            "| 증가순위 | 임계값 | 추가 행 | 추가 행 비율 | 추가 예산현액 비율 |",
            "|---:|---:|---:|---:|---:|",
        ]
    )
    for row in top_increments.itertuples(index=False):
        lines.append(
            f"| {int(row.incremental_change_rank)} | {int(row.threshold_percent)}% | "
            f"{int(row.incremental_detected_rows):,} | "
            f"{_percent(row.incremental_detected_row_share)} | "
            f"{_percent(row.incremental_current_budget_share)} |"
        )
    lines.extend(
        [
            "",
            (
                f"89%에서 90%로 이동할 때 새로 포함되는 행은 "
                f"{int(under90['incremental_detected_rows']):,}개지만 예산현액 비중은 "
                f"{_percent(under90['incremental_current_budget_share'])}p 증가합니다. "
                "90% 기준의 금액 영향은 소수 대규모 사업에 민감하므로 해당 구간 원자료를 별도 보존했습니다."
            ),
            "",
            "| 부처 | 프로그램 | 세부사업 | 연도 | 집행률 | 예산현액 |",
            "|---|---|---|---:|---:|---:|",
        ]
    )
    for row in threshold90_cases.itertuples(index=False):
        lines.append(
            f"| {row.analysis_ministry_name} | {row.program_name} | "
            f"{row.subactivity_name} | {int(row.fiscal_year)} | "
            f"{row.execution_rate:.1%} | "
            f"{row.current_budget_analysis_amount / 1e12:,.2f}조원 |"
        )
    lines.extend(
        [
            "",
            (
                f"예산현액 상위 두 행 가운데 재정수단 `UNKNOWN`은 "
                f"{threshold90_top2_unknown}행, 현재 분석 포함 분류는 "
                f"{threshold90_top2_included}행입니다. 따라서 90% 기준의 금액 비중을 "
                "발표하기 전에는 이 대규모 사업들의 정책사업 범위와 재정수단을 먼저 확인해야 "
                "합니다. 이 표는 기준을 폐기하는 근거가 아니라 금액가중 결과가 분류 검토에 "
                "민감하다는 근거입니다."
            ),
            "",
            (
                f"현재 범위에서 90% 미만 탐지 예산현액 비중은 "
                f"{scope.loc['CURRENT_SCOPE', 'detected_current_budget_share']:.1%}이며, "
                f"보통교부세를 민감도에서 제외하면 "
                f"{scope.loc['EXCLUDE_ORDINARY_GRANT', 'detected_current_budget_share']:.1%}입니다. "
                f"국채·채권매입은 범위 규칙 적용 후 현재 M3에 "
                f"{int(scope.loc['CURRENT_SCOPE', 'bond_purchase_row_count_in_current_scope']):,}행입니다."
            ),
        ]
    )
    lines.extend(
        [
            "",
            "## 3. 같은 기준이라도 집단별 탐지율이 다릅니다",
            "",
            (
                "편향 배수는 `집단 탐지율 / 전체 탐지율`입니다. 2배 이상 또는 0.5배 이하는 원인을 "
                "확인하기 위한 진단 표시이며 해당 집단을 제외하거나 기준을 바꾸는 정책 규칙이 아닙니다. "
                "표본 20행 미만은 별도 소표본으로 표시했습니다."
            ),
            "",
            "![threshold_group_bias_heatmap.png](../artifacts/figures/decision_support/threshold_group_bias_heatmap.png)",
            "",
            "### 80% 기준에서 우선 확인할 집단",
            "",
            "| 차원 | 집단 | 적격 행 | 탐지율 | 전체 대비 배수 |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for row in bias80.itertuples(index=False):
        lines.append(
            f"| {row.dimension} | {row.dimension_value} | {int(row.eligible_row_count):,} | "
            f"{_percent(row.group_detected_rate)} | "
            f"{row.group_to_overall_detection_ratio:.2f}x |"
        )
    lines.extend(
        [
            "",
            "### 90% 기준에서 우선 확인할 집단",
            "",
            "| 차원 | 집단 | 적격 행 | 탐지율 | 전체 대비 배수 |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for row in bias90.itertuples(index=False):
        lines.append(
            f"| {row.dimension} | {row.dimension_value} | {int(row.eligible_row_count):,} | "
            f"{_percent(row.group_detected_rate)} | "
            f"{row.group_to_overall_detection_ratio:.2f}x |"
        )
    lines.extend(
        [
            "",
            "## 4. 상대 기준은 적용 가능성과 신뢰도를 분리합니다",
            "",
            (
                f"하위 10% 기준의 비교집단-연도 {len(peer10):,}개 중 NOT_AVAILABLE "
                f"{int(confidence['NOT_AVAILABLE']):,}개, LOW {int(confidence['LOW']):,}개, "
                f"MEDIUM {int(confidence['MEDIUM']):,}개, HIGH {int(confidence['HIGH']):,}개입니다."
            ),
            "",
            "![peer_distribution_diagnostics.png](../artifacts/figures/decision_support/peer_distribution_diagnostics.png)",
            "",
            "| 기대 꼬리 관측 수 | 적용 가능 | 잠정 신뢰도 | 사용 원칙 |",
            "|---:|---|---|---|",
            "| 2개 미만 | 아니오 | NOT_AVAILABLE | 상대 신호를 산출하지 않음 |",
            "| 2~4개 | 예 | LOW | 단독 근거로 사용하지 않음 |",
            "| 5~9개 | 예 | MEDIUM | 절대 기준의 보조 근거 |",
            "| 10개 이상 | 예 | HIGH | 비교집단 보조 신호로 표시 |",
            "",
            (
                "이 등급은 잠정 후보입니다. 비교집단이 크더라도 고유 집행률 값이 적거나 최대 동률 "
                "블록이 크면 상대순위 해석을 낮춰야 합니다. `peer_distribution_diagnostics.csv`에서 "
                "집단별 경계값·동률 수를 직접 확인할 수 있습니다."
            ),
            "",
            "## 5. 연말집중은 4분기형과 12월형을 분리해야 합니다",
            "",
            (
                f"검증된 월별 패턴에서 4분기 기준만 충족한 행은 "
                f"{int(q4_only['detected_row_count']):,}행, 12월 기준만 충족한 행은 "
                f"{int(december_only['detected_row_count']):,}행, 두 기준을 모두 충족한 행은 "
                f"{int(both_fixed['detected_row_count']):,}행입니다. 고정 기준은 충족하지 않지만 "
                f"보수적 P90인 행은 {int(peer_only['detected_row_count']):,}행이고, 고정 기준과 "
                f"P90을 모두 충족한 행은 {int(fixed_peer['detected_row_count']):,}행입니다."
            ),
            "",
            "![year_end_pattern_scatter.png](../artifacts/figures/decision_support/year_end_pattern_scatter.png)",
            "",
            (
                "세로선 오른쪽은 4분기 집중, 가로선 위는 12월 집중입니다. 우상단은 두 기준을 모두 "
                "충족합니다. 점 크기는 예산현액의 로그이므로 큰 점은 금액 영향도 확인 대상이지만 "
                "정책 실패를 의미하지 않습니다."
            ),
            "",
            (
                "일부 점의 4분기·12월 비중이 0보다 작은 것은 순지출 환수·정산 등 회계 조정 "
                "패턴일 수 있습니다. 이 행은 연말집중으로 해석하지 않고 누계 감소·회계 조정 "
                "신호와 원자료를 별도로 확인해야 합니다."
            ),
            "",
            "![year_end_pattern_by_ministry.png](../artifacts/figures/decision_support/year_end_pattern_by_ministry.png)",
            "",
            (
                "부처별 점 구름이 다르면 지급 일정이나 사업구성 차이일 수 있으므로, 고정 기준 탐지율의 "
                "차이를 곧바로 성과 차이로 해석하지 않습니다."
            ),
            "",
            "## 6. 반복 신호는 유효 관측연도 수와 함께 봅니다",
            "",
            (
                f"동일 신호가 2회 이상이면서 유효연도의 50% 이상인 사업은 집행률 90% 미만 기준 "
                f"{low_repeat['classification_project_id'].nunique():,}개, 고정 연말집중 기준 "
                f"{year_repeat['classification_project_id'].nunique():,}개입니다."
            ),
            "",
            "![repeated_signal_distribution.png](../artifacts/figures/decision_support/repeated_signal_distribution.png)",
            "",
            (
                "x축이 2이고 y축이 100%인 사업은 2년 중 2회이며, x축이 4이고 y축이 50%인 사업은 "
                "4년 중 2회입니다. 두 사업은 주 반복 조건을 모두 충족하지만 증거의 두께가 다르므로 "
                "유효 관측연도 수를 함께 표시합니다. 주황색 연속 2회는 강화 정보입니다."
            ),
            "",
            (
                f"고정 연말집중 반복 후보 {year_repeat['classification_project_id'].nunique():,}개는 "
                "현재 모두 유효 월별 관측 2년에서 연속 2회 발생한 사업입니다. 월별 관측 가능한 "
                "연도가 제한되어 있으므로 집행률 반복보다 증거가 약하며, 발표에서는 "
                "'2년 연속 관찰'로 표현해야 합니다."
            ),
            "",
            "## 7. 후보 기준별 의사결정표",
            "",
            "![analysis_policy_options.png](../artifacts/figures/decision_support/analysis_policy_options.png)",
            "",
            "| 후보 | 분석 단위 | 탐지 행 | 탐지 사업 | 본예산 비중 | 권장 역할 | 안정성 |",
            "|---|---|---:|---:|---:|---|---|",
        ]
    )
    for row in options.itertuples(index=False):
        lines.append(
            f"| {row.option_name} | {row.analysis_grain} | "
            f"{int(row.detected_row_count):,} | {int(row.detected_unique_project_count):,} | "
            f"{_percent(row.detected_original_budget_share)} | {row.recommended_role} | "
            f"{row.sample_stability} |"
        )
    lines.extend(
        [
            "",
            "### 분석 담당자의 권장안",
            "",
            "1. **권장 주 기준:** 집행률 80%·90% 2단계 기준.",
            "2. **권장 강한 신호:** 집행률 80% 미만.",
            "3. **권장 보조 기준:** 신뢰도 등급을 통과한 보수적 하위 10%, 고정 연말집중의 보수적 P90.",
            "4. **권장 민감도 기준:** 집행률 90% 단일 기준, 하위 20%, 연말집중 P80·P95.",
            "5. **권장 반복 기준:** 동일 신호 2회 이상이면서 유효연도의 50% 이상.",
            "6. **권장 강화 정보:** 동일 신호 연속 2회.",
            "",
            "### 적용하지 말아야 할 집단",
            "",
            "- 집행률 분모가 미확정이거나 100% 초과로 품질 검토가 필요한 행",
            "- 상대 기준 기대 꼬리 관측 수가 2개 미만인 비교집단",
            "- 경계 동률 블록이 커서 상대순위가 사실상 구분되지 않는 비교집단",
            "- 월별 패턴 적격이 아니거나 4분기·12월 비중을 계산할 수 없는 행",
            "- 유효 관측연도 1년 사업의 반복 판정",
            "- 프로그램 집중도를 세부사업 수로 집계하는 방식",
            "",
            "### 기준 변경 시 예상 영향",
            "",
            (
                f"80%에서 90%로 완화하면 탐지 행은 "
                f"{int(under90['detected_row_count'] - under80['detected_row_count']):,}행, "
                f"고유 사업은 "
                f"{int(under90['detected_unique_project_count'] - under80['detected_unique_project_count']):,}개 "
                "늘어납니다. 이는 강한 신호의 확대가 아니라 주의 신호를 추가하는 변화로 해석해야 합니다."
            ),
            "",
            (
                f"절대 기준과 보수적 상대 기준을 병행하면 탐지 고유 사업 비율은 "
                f"{_percent(policy.loc['ABSOLUTE_AND_RELATIVE_PARALLEL', 'detected_unique_project_share'])}입니다. "
                "다만 상대 신호 LOW 집단까지 동일하게 강조하면 비교집단 소표본이 다시 결과를 지배할 수 있습니다."
            ),
            "",
            "## 8. 산식과 재현 방법",
            "",
            "```powershell",
            "fiscal-analytics build-analysis-policy-decision-support --root .",
            "```",
            "",
            "주요 산식:",
            "",
            "- 비가중 ECDF: 집행률 이하 사업-연도 누적 수 / 전체 유효 사업-연도 수",
            "- 예산가중 ECDF: 집행률 이하 예산현액 누적 합 / 전체 유효 예산현액 합",
            "- 편향 배수: 집단 탐지율 / 전체 탐지율",
            "- 기대 꼬리 관측 수: 비교집단 크기 × 꼬리비율",
            "- 반복률: 신호 발생연도 수 / 유효 관측연도 수",
            "",
            (
                "CSV는 그래프에 표시된 값보다 더 많은 집단·임계값을 포함합니다. 임계값을 바꿔 검토하려면 "
                "`execution_threshold_sensitivity.csv`에서 원하는 threshold 행을 필터링하면 됩니다. "
                "`execution_threshold_increment_cases.csv`에서 각 1%p 구간에 새로 포함되는 실제 사업을 "
                "확인할 수 있습니다. 그래프 원자료와 읽는 법은 "
                "`decision_support_chart_map.csv`에 연결했습니다."
            ),
            "",
            "## 9. 발표 및 질의응답 대비",
            "",
            "### 왜 80%와 90%입니까?",
            "",
            (
                "분포가 하나의 자연 절단점을 자동으로 제시해서가 아닙니다. 80% 미만과 80~90%가 "
                "탐지 강도와 설명 가능성에서 구분되고, 70~95% 민감도에서 기준 변경 영향을 공개할 수 "
                "있기 때문에 두 단계 운영 기준으로 제안했습니다."
            ),
            "",
            "### 왜 평균과 표준편차를 사용하지 않았습니까?",
            "",
            "집행률은 100% 부근 동률과 경계값이 많고 정규분포가 아니므로 ECDF·분위수·동률 구조를 사용했습니다.",
            "",
            "### 왜 사업 수 분포와 예산가중 분포를 같이 봅니까?",
            "",
            "사업 수는 탐지 범위를, 예산가중 분포는 재정 규모 노출을 답합니다. 어느 하나로 다른 하나를 대체하지 않습니다.",
            "",
            "### 편향 배수 2배와 0.5배는 정책 기준입니까?",
            "",
            "아닙니다. 특정 집단의 사업구성·회계특성·품질문제를 확인하는 진단 표시입니다.",
            "",
            "### 연말집중은 낭비입니까?",
            "",
            "아닙니다. 계약·보조금 지급 일정 등 정상 사유가 있을 수 있어 원문 설명이 필요한 집행 패턴으로만 표시합니다.",
            "",
            "### 최종 순위를 왜 만들지 않았습니까?",
            "",
            "성과자료가 아직 연결되지 않았고 기준별 표본·편향·신뢰도 검증이 우선이기 때문입니다.",
            "",
            "## 10. 한계와 강건성",
            "",
            "- 2022~2025년 관측창 때문에 반복 신호의 유효연도가 최대 4년입니다.",
            "- 예산가중 ECDF는 예산현액이 양수로 확인된 행만 사용합니다.",
            "- 집행률 100% 초과 행은 주 ECDF에서 제외하고 별도 품질 검토 대상으로 유지합니다.",
            "- 부처·회계별 분포 차이는 정책성과가 아니라 사업구성과 회계적 분모 차이일 수 있습니다.",
            "- 상대 신뢰도 구간은 잠정 후보이며 팀 결정 전 최종 설정이 아닙니다.",
            "- 이 분석은 기술통계와 운영 기준 검토이며 인과효과를 추정하지 않습니다.",
            "",
            "## 11. 실험 진행 기록",
            "",
        ]
    )
    for checkpoint in summary["experiment_checkpoints"]:
        lines.append(
            f"- **{checkpoint['stage']}** — {checkpoint['status']}: {checkpoint['evidence']}"
        )
    lines.extend(
        [
            "",
            "## 12. 권장 다음 단계",
            "",
            "1. 이 문서의 잠정 권장안을 발표용 기준으로 검토합니다.",
            "2. UNKNOWN 본예산 80% 커버리지 검토집합을 실제 근거로 수기 분류합니다.",
            "3. 분류 결과를 반영해 비교집단 크기와 상대 신호만 최소 재실행합니다.",
            "4. 실제 공유·피드백 후 확정된 기준만 설정파일과 의사결정 기록에 저장합니다.",
            "",
            "## 13. 추가 확인 질문",
            "",
            "- 80~90%를 대시보드에서 별도 색상으로 표시할지, 필터로만 제공할지?",
            "- 상대 신호 LOW 등급을 화면에 표시할지, 상세표에만 남길지?",
            "- 정상 연말 지급이 예상되는 사업유형을 별도 설명 태그로 관리할지?",
            "- UNKNOWN 80% 커버리지 검수 후 추가 검수 범위를 어디까지 둘지?",
            "",
            "## 부록. 차트 원자료 연결",
            "",
            "| 그림 | 분석 질문 | 원자료 | 읽는 법 |",
            "|---|---|---|---|",
        ]
    )
    for row in chart_map.itertuples(index=False):
        lines.append(
            f"| {row.figure} | {row.question} | `{row.source_file}` | {row.reading_note} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_analysis_policy_decision_support(
    paths: DecisionSupportPaths,
) -> DecisionSupportResult:
    """실제 데이터를 실행해 의사결정 자료·그래프·보고서를 생성합니다."""
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    paths.figure_dir.mkdir(parents=True, exist_ok=True)
    before_hash = _hash(paths.features)
    features = pd.read_parquet(paths.features)
    peer_flags = build_peer_method_flags(features)

    ecdf = execution_ecdf_summary(features)
    sensitivity = execution_threshold_sensitivity(features)
    increment_cases = execution_threshold_increment_cases(features)
    bias = build_threshold_group_bias(features, sensitivity)
    peer = peer_distribution_diagnostics(features)
    patterns, year_points = year_end_pattern_types(features, peer_flags)
    recurrence = repeated_signal_distribution(features)
    options = analysis_policy_options(features, peer_flags, recurrence)
    scope_sensitivity = large_project_scope_sensitivity(features)

    figure_paths, chart_map = create_decision_support_figures(
        ecdf,
        sensitivity,
        bias,
        peer,
        year_points,
        recurrence,
        options,
        paths.figure_dir,
    )
    tables = {
        "execution_ecdf_summary.csv": ecdf,
        "execution_threshold_sensitivity.csv": sensitivity,
        "execution_threshold_increment_cases.csv": increment_cases,
        "threshold_group_bias.csv": bias,
        "peer_distribution_diagnostics.csv": peer,
        "year_end_pattern_types.csv": patterns,
        "year_end_pattern_points.csv": year_points,
        "repeated_signal_distribution.csv": recurrence,
        "analysis_policy_options.csv": options,
        "large_project_scope_sensitivity.csv": scope_sensitivity,
        "decision_support_chart_map.csv": chart_map,
    }
    output_paths: list[Path] = []
    for filename, frame in tables.items():
        output = paths.output_dir / filename
        frame.to_csv(output, index=False, encoding="utf-8-sig")
        output_paths.append(output)

    execution_primary = execution_eligible_frame(features)
    over100_count = int(_bool(features, "execution_over_100_flag").sum())
    validations = {
        "source_file_unchanged": before_hash == _hash(paths.features),
        "feature_row_count_preserved": (
            len(features) == features["source_project_year_id"].nunique()
        ),
        "threshold_range_complete": set(
            sensitivity.loc[
                sensitivity["dimension"].eq("OVERALL"),
                "threshold_percent",
            ]
        )
        == set(range(70, 96)),
        "ecdf_bounds_valid": ecdf["cumulative_share"].between(0, 1).all(),
        "ecdf_monotonic_by_group": bool(
            ecdf.groupby(["weighting", "dimension", "dimension_value"], dropna=False)[
                "cumulative_share"
            ]
            .apply(lambda values: values.is_monotonic_increasing)
            .all()
        ),
        "bias_rule_documented": bias["diagnostic_rule"].notna().all(),
        "peer_candidate_not_final": peer["confidence_rule_status"]
        .eq("CANDIDATE_NOT_FINAL_CONFIG")
        .all(),
        "year_end_point_key_unique": not year_points["source_project_year_id"].duplicated().any(),
        "recurrence_key_unique": not recurrence[["classification_project_id", "signal_name"]]
        .duplicated()
        .any(),
        "policy_not_finalized": options["final_policy_status"]
        .eq("CANDIDATE_NOT_FINAL_CONFIG")
        .all(),
        "large_project_scope_sensitivity_complete": set(scope_sensitivity["scenario"])
        == {"CURRENT_SCOPE", "EXCLUDE_ORDINARY_GRANT"},
        "leading_zero_codes_preserved": {"019", "075"}.issubset(
            set(features["ministry_code"].astype(str))
        ),
        "final_composite_score_generated": False,
        "overall_rank_generated": False,
        "existing_m3_overwritten": False,
    }
    failed = [
        key
        for key, value in validations.items()
        if key
        not in {
            "final_composite_score_generated",
            "overall_rank_generated",
            "existing_m3_overwritten",
        }
        and value is False
    ]
    now = datetime.now(UTC).isoformat()
    summary: dict[str, Any] = {
        "generated_at_utc": now,
        "population": "M3 financial signal decision support",
        "source_feature_rows": len(features),
        "execution_primary_rows": len(execution_primary),
        "execution_over_100_excluded_count": over100_count,
        "threshold_count": len(THRESHOLDS),
        "ecdf_rows": len(ecdf),
        "sensitivity_rows": len(sensitivity),
        "threshold_increment_case_rows": len(increment_cases),
        "bias_rows": len(bias),
        "peer_diagnostic_rows": len(peer),
        "year_end_pattern_rows": len(patterns),
        "year_end_point_rows": len(year_points),
        "recurrence_rows": len(recurrence),
        "policy_option_rows": len(options),
        "large_project_scope_sensitivity_rows": len(scope_sensitivity),
        "figure_count": len(figure_paths),
        "validation": validations,
        "validation_status": "PASS" if not failed else "FAIL",
        "thresholds_persisted_as_final_configuration": False,
        "experiment_checkpoints": [
            {
                "stage": "입력·분석 단위 확인",
                "status": "완료",
                "evidence": f"M3 {len(features):,}행 보존, 주 ECDF {len(execution_primary):,}행",
            },
            {
                "stage": "집행률 분포·민감도",
                "status": "완료",
                "evidence": f"ECDF {len(ecdf):,}행, 70~95% 민감도 {len(sensitivity):,}행",
            },
            {
                "stage": "집단 편향·상대 안정성",
                "status": "완료",
                "evidence": f"편향 {len(bias):,}행, 상대 진단 {len(peer):,}행",
            },
            {
                "stage": "연말집중·반복 신호",
                "status": "완료",
                "evidence": f"월별 점 {len(year_points):,}행, 사업-신호 반복 {len(recurrence):,}행",
            },
            {
                "stage": "정책 후보 비교·시각화",
                "status": "완료",
                "evidence": f"후보 {len(options):,}개, PNG {len(figure_paths):,}개",
            },
        ],
        "limitations": [
            "thresholds are candidate operating rules, not statistically discovered optima",
            "group bias ratios are diagnostics, not exclusion rules",
            "weighted ECDF uses positive non-null current budget amounts",
            "relative confidence bands are provisional and not final config",
        ],
    }
    summary_path = paths.output_dir / "decision_support_summary.json"
    summary_path.write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
            default=_json_default,
        ),
        encoding="utf-8",
    )
    output_paths.append(summary_path)
    build_decision_support_report(
        paths.report,
        summary,
        sensitivity,
        increment_cases,
        bias,
        peer,
        patterns,
        recurrence,
        options,
        scope_sensitivity,
        chart_map,
    )
    if failed:
        raise ValueError(f"분석 기준 의사결정 지원 검증 실패: {failed}")
    return DecisionSupportResult(
        output_paths=output_paths,
        figure_paths=figure_paths,
        report_path=paths.report,
        summary=summary,
    )
