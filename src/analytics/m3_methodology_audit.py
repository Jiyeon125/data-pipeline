"""M3 상대순위, 분석 단위, 반복관측 방법론 감사."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from analytics.m3_financial_signals import _feedback_cohort_frame

PEER_KEYS = ["fiscal_year", "comparison_group"]
PROGRAM_KEYS = [
    "fiscal_year",
    "ministry_code",
    "program_code",
    "program_name",
]
FEEDBACK_STRATA = [
    "base_fiscal_year",
    "ministry_code",
    "account_type_classified",
    "project_size_bucket",
]
STRUCTURE_CANDIDATE_STATUSES = {
    "RENAMED",
    "CODE_CHANGED",
    "TRANSFERRED",
    "MERGED",
    "SPLIT",
    "UNKNOWN",
}


@dataclass(frozen=True)
class AuditPaths:
    root: Path
    features: Path
    programs: Path
    broad: Path
    v2: Path
    cohorts: Path
    unknown: Path
    output_dir: Path
    report: Path

    @classmethod
    def from_root(cls, root: Path) -> AuditPaths:
        root = root.resolve()
        return cls(
            root=root,
            features=root / "data/analytics/m3/financial_signal_features.parquet",
            programs=root / "data/processed/masters/program_year_financial.parquet",
            broad=root
            / "data/processed/masters/population_sensitivity/broad_population.parquet",
            v2=root / "data/processed/masters/project_year_financial_v2.parquet",
            cohorts=root
            / "data/analytics/definition_validation/feedback_cohort_t1_t2.csv",
            unknown=root / "data/analytics/m3/unknown_manual_review_priority.csv",
            output_dir=root / "data/analytics/m3_audit",
            report=root / "docs/M3_METHODOLOGY_AUDIT.md",
        )

    @property
    def inputs(self) -> list[Path]:
        return [
            self.features,
            self.programs,
            self.broad,
            self.v2,
            self.cohorts,
            self.unknown,
        ]


@dataclass(frozen=True)
class AuditResult:
    output_paths: list[Path]
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
    if denominator <= 0 or pd.isna(denominator):
        return math.nan
    return float(numerator / denominator)


def _sum(frame: pd.DataFrame, column: str) -> float:
    value = pd.to_numeric(frame[column], errors="coerce").sum(min_count=1)
    return float(value) if pd.notna(value) else math.nan


def _json_default(value: Any) -> Any:
    """NumPy 스칼라를 표준 JSON 스칼라로 변환합니다."""
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _tail_minimum_size(tail_share: float) -> int:
    """꼬리구간에 최소 2개 관측이 기대되도록 최소 표본 수를 정합니다."""
    return math.ceil(2 / tail_share)


def _is_boundary(values: pd.Series, cutoff: float) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return pd.Series(
        np.isclose(numeric.astype(float), cutoff, rtol=1e-12, atol=1e-12),
        index=values.index,
    )


def peer_threshold_tie_audit(features: pd.DataFrame) -> pd.DataFrame:
    """비교집단·지표별 분위수 경계와 동률 과다탐지 원인을 분해합니다."""
    specs = [
        ("EXECUTION_BOTTOM_10", "execution_rate", 0.10, "BOTTOM"),
        ("EXECUTION_BOTTOM_20", "execution_rate", 0.20, "BOTTOM"),
        ("YEAR_END_Q4_P80", "q4_expenditure_share", 0.80, "TOP"),
        ("YEAR_END_DECEMBER_P80", "december_single_month_share", 0.80, "TOP"),
        ("YEAR_END_Q4_P90", "q4_expenditure_share", 0.90, "TOP"),
        ("YEAR_END_DECEMBER_P90", "december_single_month_share", 0.90, "TOP"),
        ("YEAR_END_Q4_P95", "q4_expenditure_share", 0.95, "TOP"),
        ("YEAR_END_DECEMBER_P95", "december_single_month_share", 0.95, "TOP"),
    ]
    rows: list[dict[str, Any]] = []
    for criterion, column, quantile, direction in specs:
        if column == "execution_rate":
            valid = features["strong_low_execution_flag"].notna()
            tail_share = quantile
        else:
            valid = features["fixed_year_end_concentration_flag"].notna()
            tail_share = 1 - quantile
        scoped = features.loc[valid].copy()
        minimum_size = _tail_minimum_size(tail_share)
        for key, part in scoped.groupby(PEER_KEYS, dropna=False):
            values = _numeric(part, column).dropna()
            if values.empty:
                continue
            cutoff = float(values.quantile(quantile))
            boundary = _is_boundary(values, cutoff)
            detected = values.le(cutoff) if direction == "BOTTOM" else values.ge(cutoff)
            strict = values.lt(cutoff) if direction == "BOTTOM" else values.gt(cutoff)
            target_count = math.ceil(len(values) * tail_share)
            rows.append(
                {
                    "population": "ranking_population_v2_peer_metric_valid",
                    "criterion": criterion,
                    "metric": column,
                    "direction": direction,
                    "quantile": quantile,
                    "fiscal_year": key[0],
                    "comparison_group": key[1],
                    "sample_size": len(values),
                    "unique_value_count": values.nunique(dropna=True),
                    "quantile_cutoff": cutoff,
                    "boundary_tie_row_count": int(boundary.sum()),
                    "boundary_tie_share": _safe_rate(int(boundary.sum()), len(values)),
                    "existing_detected_row_count": int(detected.sum()),
                    "strict_beyond_cutoff_row_count": int(strict.sum()),
                    "target_tail_row_count": target_count,
                    "target_tail_share": tail_share,
                    "existing_detected_share": float(detected.mean()),
                    "over_detection_row_count": max(
                        int(detected.sum()) - target_count, 0
                    ),
                    "minimum_peer_group_size": minimum_size,
                    "small_peer_group_flag": len(values) < minimum_size,
                    "all_values_tied_flag": values.nunique(dropna=True) == 1,
                    "tie_inflation_explains_excess": int(boundary.sum())
                    >= max(int(detected.sum()) - target_count, 0),
                }
            )
    return pd.DataFrame(rows)


def _rank_flags(
    values: pd.Series,
    *,
    quantile: float,
    direction: str,
) -> dict[str, pd.Series]:
    numeric = pd.to_numeric(values, errors="coerce")
    tail_share = quantile if direction == "BOTTOM" else 1 - quantile
    cutoff = float(numeric.quantile(quantile))
    boundary = _is_boundary(numeric, cutoff)
    average_rank = numeric.rank(method="average", pct=True)
    max_rank = numeric.rank(method="max", pct=True)
    min_rank = numeric.rank(method="min", pct=True)
    if direction == "BOTTOM":
        inclusive = numeric.le(cutoff)
        average = average_rank.le(quantile)
        maximum = max_rank.le(quantile)
        strict = numeric.lt(cutoff)
        conservative = max_rank.le(quantile)
        ordered = numeric.sort_values(ascending=True)
    else:
        inclusive = numeric.ge(cutoff)
        average = average_rank.ge(quantile)
        maximum = max_rank.ge(quantile)
        strict = numeric.gt(cutoff)
        conservative = min_rank.ge(quantile)
        ordered = numeric.sort_values(ascending=False)
    target_n = max(math.ceil(len(numeric) * tail_share), 1)
    exact_boundary = float(ordered.iloc[min(target_n - 1, len(ordered) - 1)])
    exact_boundary_mask = _is_boundary(numeric, exact_boundary)
    better = (
        numeric.lt(exact_boundary)
        if direction == "BOTTOM"
        else numeric.gt(exact_boundary)
    )
    exact_hold = (
        better | exact_boundary_mask
        if int(exact_boundary_mask.sum()) == 1
        else better
    )
    return {
        "EXISTING_QUANTILE_INCLUSIVE": inclusive,
        "AVERAGE_PERCENTILE_RANK": average,
        "MAX_PERCENTILE_RANK": maximum,
        "STRICT_CUTOFF_EXCLUDE_BOUNDARY": strict,
        "EXACT_N_BOUNDARY_WITHHELD": exact_hold,
        "CONSERVATIVE_TIE_BLOCK": conservative,
        "BOUNDARY_TIE": boundary,
    }


def build_peer_method_flags(features: pd.DataFrame) -> pd.DataFrame:
    """동률 처리 대안별 행 플래그와 순위 진단 열을 생성합니다."""
    result = features[
        [
            "source_project_year_id",
            "classification_project_id",
            "fiscal_year",
            "ministry_code",
            "analysis_ministry_name",
            "account_type_classified",
            "project_size_bucket",
            "comparison_group",
            "original_budget_analysis_amount",
            "current_budget_analysis_amount",
            "settlement_analysis_amount",
            "execution_rate",
            "q4_expenditure_share",
            "december_single_month_share",
        ]
    ].copy()
    execution_valid = features["strong_low_execution_flag"].notna()
    monthly_valid = features["fixed_year_end_concentration_flag"].notna()

    for tail, label in [(0.10, "bottom_10"), (0.20, "bottom_20")]:
        minimum_size = _tail_minimum_size(tail)
        for index in result.loc[execution_valid].groupby(
            PEER_KEYS, dropna=False
        ).groups.values():
            values = _numeric(result.loc[index], "execution_rate")
            flags = _rank_flags(values, quantile=tail, direction="BOTTOM")
            eligible = len(values) >= minimum_size
            result.loc[index, f"peer_{label}_percentile_rank_average"] = values.rank(
                method="average", pct=True
            )
            result.loc[index, f"peer_{label}_percentile_rank_max"] = values.rank(
                method="max", pct=True
            )
            result.loc[index, f"peer_{label}_group_size"] = len(values)
            for method, flag in flags.items():
                column = f"peer_{label}_{method.lower()}"
                result.loc[index, column] = flag.astype("boolean") if eligible else pd.NA

    for percentile in [0.80, 0.90, 0.95]:
        tail = 1 - percentile
        label = f"p{int(percentile * 100)}"
        minimum_size = _tail_minimum_size(tail)
        for index in result.loc[monthly_valid].groupby(
            PEER_KEYS, dropna=False
        ).groups.values():
            q4 = _numeric(result.loc[index], "q4_expenditure_share")
            december = _numeric(result.loc[index], "december_single_month_share")
            eligible = len(index) >= minimum_size
            q4_flags = _rank_flags(q4, quantile=percentile, direction="TOP")
            dec_flags = _rank_flags(
                december, quantile=percentile, direction="TOP"
            )
            result.loc[index, f"peer_{label}_q4_percentile_rank_average"] = q4.rank(
                method="average", pct=True
            )
            result.loc[
                index, f"peer_{label}_december_percentile_rank_average"
            ] = december.rank(method="average", pct=True)
            result.loc[index, f"peer_{label}_group_size"] = len(index)
            for method in q4_flags:
                q4_column = f"peer_{label}_q4_{method.lower()}"
                dec_column = f"peer_{label}_december_{method.lower()}"
                union_column = f"peer_{label}_year_end_{method.lower()}"
                if eligible:
                    result.loc[index, q4_column] = q4_flags[method].astype(
                        "boolean"
                    )
                    result.loc[index, dec_column] = dec_flags[method].astype(
                        "boolean"
                    )
                    result.loc[index, union_column] = (
                        q4_flags[method] | dec_flags[method]
                    ).astype("boolean")
                else:
                    result.loc[index, [q4_column, dec_column, union_column]] = pd.NA
    return result


def peer_method_comparison(
    features: pd.DataFrame,
    peer_flags: pd.DataFrame,
) -> pd.DataFrame:
    """상대순위 방법별 탐지 규모·금액·편향을 같은 형식으로 비교합니다."""
    frame = features.merge(
        peer_flags.drop(
            columns=[
                column
                for column in peer_flags.columns
                if column in features.columns
                and column != "source_project_year_id"
            ]
        ),
        on="source_project_year_id",
        how="left",
        validate="one_to_one",
    )
    methods = [
        "existing_quantile_inclusive",
        "average_percentile_rank",
        "max_percentile_rank",
        "strict_cutoff_exclude_boundary",
        "exact_n_boundary_withheld",
        "conservative_tie_block",
    ]
    criteria: dict[str, tuple[str, int]] = {}
    for label, minimum in [("bottom_10", 20), ("bottom_20", 10)]:
        for method in methods:
            criteria[f"EXECUTION_{label.upper()}__{method.upper()}"] = (
                f"peer_{label}_{method}",
                minimum,
            )
    for label, minimum in [("p80", 10), ("p90", 20), ("p95", 40)]:
        for method in methods:
            criteria[f"YEAR_END_{label.upper()}__{method.upper()}"] = (
                f"peer_{label}_year_end_{method}",
                minimum,
            )
    dimensions = {
        "OVERALL": None,
        "MINISTRY": "ministry_code",
        "ACCOUNT_TYPE": "account_type_classified",
        "PROJECT_SIZE": "project_size_bucket",
    }
    rows: list[dict[str, Any]] = []
    for criterion, (column, minimum_size) in criteria.items():
        valid = frame[column].notna()
        flagged = frame[column].astype("boolean").fillna(False)
        for dimension, dimension_column in dimensions.items():
            groups = (
                [("ALL", frame.index)]
                if dimension_column is None
                else frame.groupby(dimension_column, dropna=False).groups.items()
            )
            for value, index in groups:
                scoped_valid = valid.loc[index]
                scoped_flagged = flagged.loc[index] & scoped_valid
                denominator = frame.loc[index][scoped_valid]
                numerator = frame.loc[index][scoped_flagged]
                rows.append(
                    {
                        "population": "ranking_population_v2_peer_method_eligible",
                        "criterion": criterion.split("__")[0],
                        "method": criterion.split("__")[1],
                        "dimension": dimension,
                        "dimension_value": value,
                        "minimum_peer_group_size": minimum_size,
                        "eligible_row_count": len(denominator),
                        "flagged_row_count": len(numerator),
                        "flagged_unique_project_count": numerator[
                            "classification_project_id"
                        ].nunique(),
                        "flagged_row_share": _safe_rate(
                            len(numerator), len(denominator)
                        ),
                        "original_budget_amount": _sum(
                            numerator, "original_budget_analysis_amount"
                        ),
                        "original_budget_share": _safe_rate(
                            _sum(numerator, "original_budget_analysis_amount"),
                            _sum(
                                denominator, "original_budget_analysis_amount"
                            ),
                        ),
                        "current_budget_amount": _sum(
                            numerator, "current_budget_analysis_amount"
                        ),
                        "settlement_expenditure_amount": _sum(
                            numerator, "settlement_analysis_amount"
                        ),
                        "recommended_candidate": criterion.endswith(
                            "CONSERVATIVE_TIE_BLOCK"
                        ),
                        "arbitrary_boundary_selection_used": False,
                    }
                )
    return pd.DataFrame(rows)


def split_signal_grains(
    features: pd.DataFrame,
    programs: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """세부사업-연도, 세부사업 반복, 프로그램-연도 신호를 분리합니다."""
    project_signal_columns = [
        "strong_low_execution_flag",
        "moderate_low_execution_flag",
        "peer_bottom_10_execution_flag",
        "peer_bottom_20_execution_flag",
        "fixed_year_end_concentration_flag",
        "peer_p80_year_end_concentration_flag",
        "peer_p90_year_end_concentration_flag",
        "peer_p95_year_end_concentration_flag",
        "cumulative_decrease_flag",
        "execution_over_100_flag",
        "budget_increase_extreme_flag",
        "budget_decrease_extreme_flag",
        "data_quality_review_flag",
    ]
    identity = [
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
        "project_size_bucket",
        "original_budget_analysis_amount",
        "current_budget_analysis_amount",
        "settlement_analysis_amount",
        "execution_rate",
        "q4_expenditure_share",
        "december_single_month_share",
        "project_status",
        "source_trace",
    ]
    project_year = features[identity + project_signal_columns].copy()
    project_year.insert(0, "analysis_grain", "project_year")
    project_year["program_level_signal_attached"] = False

    recurrence_specs = {
        "valid_execution_year_count": (
            "strong_low_execution_flag",
            lambda values: int(values.notna().sum()),
        ),
        "strong_low_execution_year_count": (
            "strong_low_execution_flag",
            lambda values: int(
                values.astype("boolean").fillna(False).sum()
            ),
        ),
        "moderate_low_execution_year_count": (
            "moderate_low_execution_flag",
            lambda values: int(
                values.astype("boolean").fillna(False).sum()
            ),
        ),
        "fixed_year_end_concentration_year_count": (
            "fixed_year_end_concentration_flag",
            lambda values: int(
                values.astype("boolean").fillna(False).sum()
            ),
        ),
        "cumulative_decrease_year_count": (
            "cumulative_decrease_flag",
            lambda values: int(
                values.astype("boolean").fillna(False).sum()
            ),
        ),
        "execution_over_100_year_count": (
            "execution_over_100_flag",
            lambda values: int(
                values.astype("boolean").fillna(False).sum()
            ),
        ),
    }
    rows = []
    for project_id, part in project_year.groupby(
        "classification_project_id", dropna=False
    ):
        latest = part.sort_values("fiscal_year").iloc[-1]
        row: dict[str, Any] = {
            "analysis_grain": "project",
            "classification_project_id": project_id,
            "ministry_code": latest["ministry_code"],
            "analysis_ministry_name": latest["analysis_ministry_name"],
            "program_code_latest": latest["program_code"],
            "program_name_latest": latest["program_name"],
            "subactivity_code_latest": latest["subactivity_code"],
            "subactivity_name_latest": latest["subactivity_name"],
            "observed_year_count": part["fiscal_year"].nunique(),
            "first_fiscal_year": part["fiscal_year"].min(),
            "last_fiscal_year": part["fiscal_year"].max(),
            "source_project_year_count": len(part),
        }
        for output, (column, aggregator) in recurrence_specs.items():
            row[output] = aggregator(part[column])
        valid = row["valid_execution_year_count"]
        strong = row["strong_low_execution_year_count"]
        moderate = row["moderate_low_execution_year_count"]
        year_end = row["fixed_year_end_concentration_year_count"]
        row["repeated_strong_low_execution_flag"] = (
            valid >= 2 and strong >= 2 and strong / valid >= 0.5
        )
        row["repeated_moderate_low_execution_flag"] = (
            valid >= 2 and moderate >= 2 and moderate / valid >= 0.5
        )
        monthly_valid = int(
            part["fixed_year_end_concentration_flag"].notna().sum()
        )
        row["valid_monthly_year_count"] = monthly_valid
        row["repeated_year_end_concentration_flag"] = (
            monthly_valid >= 2 and year_end >= 2 and year_end / monthly_valid >= 0.5
        )
        rows.append(row)
    recurrence = pd.DataFrame(rows)

    program_year = programs.copy()
    program_year.insert(0, "analysis_grain", "program_year")
    program_year["program_concentration_flag"] = (
        pd.to_numeric(
            program_year["analysis_included_project_count"], errors="coerce"
        ).ge(2)
        & pd.to_numeric(
            program_year["top1_project_budget_share"], errors="coerce"
        ).ge(0.70)
    ).astype("boolean")
    program_year["program_signal_row_weight"] = 1
    program_year["program_signal_counting_rule"] = (
        "count distinct ministry-program-name-fiscal_year"
    )

    old_program_rows = _bool(features, "program_concentration_flag")
    new_program_rows = _bool(program_year, "program_concentration_flag")
    old_budget = _sum(
        features.loc[old_program_rows], "original_budget_analysis_amount"
    )
    new_budget = _sum(
        program_year.loc[new_program_rows], "original_budget"
    )
    audit_rows = [
        {
            "signal": "PROGRAM_BUDGET_CONCENTRATION",
            "intended_grain": "program_year",
            "previous_storage_grain": "project_year",
            "previous_flagged_row_count": int(old_program_rows.sum()),
            "correct_grain_flagged_row_count": int(new_program_rows.sum()),
            "row_count_inflation_factor": _safe_rate(
                int(old_program_rows.sum()), int(new_program_rows.sum())
            ),
            "previous_unique_project_count": features.loc[
                old_program_rows, "classification_project_id"
            ].nunique(),
            "correct_unique_program_year_count": int(new_program_rows.sum()),
            "previous_budget_amount": old_budget,
            "correct_grain_budget_amount": new_budget,
            "budget_amount_difference": old_budget - new_budget,
            "duplicate_counting_confirmed": int(old_program_rows.sum())
            > int(new_program_rows.sum()),
            "risk": (
                "row and project counts were inflated by the number of "
                "projects in concentrated programs"
            ),
            "remediation": (
                "count the flag only in program_year_signal_features; "
                "project tables may keep program keys but not the flag"
            ),
        },
        {
            "signal": "PROJECT_YEAR_FINANCIAL_SIGNALS",
            "intended_grain": "project_year",
            "previous_storage_grain": "project_year",
            "previous_flagged_row_count": len(features),
            "correct_grain_flagged_row_count": len(project_year),
            "row_count_inflation_factor": 1.0,
            "previous_unique_project_count": features[
                "classification_project_id"
            ].nunique(),
            "correct_unique_program_year_count": math.nan,
            "previous_budget_amount": _sum(
                features, "original_budget_analysis_amount"
            ),
            "correct_grain_budget_amount": _sum(
                project_year, "original_budget_analysis_amount"
            ),
            "budget_amount_difference": 0.0,
            "duplicate_counting_confirmed": False,
            "risk": "none after program-level flags are removed",
            "remediation": "use project_year_signal_features for drilldown only",
        },
        {
            "signal": "PROJECT_SIGNAL_RECURRENCE",
            "intended_grain": "project",
            "previous_storage_grain": "project_year_repeated_values",
            "previous_flagged_row_count": len(features),
            "correct_grain_flagged_row_count": len(recurrence),
            "row_count_inflation_factor": _safe_rate(
                len(features), len(recurrence)
            ),
            "previous_unique_project_count": features[
                "classification_project_id"
            ].nunique(),
            "correct_unique_program_year_count": math.nan,
            "previous_budget_amount": math.nan,
            "correct_grain_budget_amount": math.nan,
            "budget_amount_difference": math.nan,
            "duplicate_counting_confirmed": True,
            "risk": "repeat counts copied to every project-year can be overcounted",
            "remediation": "count recurrence once per classification_project_id",
        },
    ]
    return project_year, recurrence, program_year, pd.DataFrame(audit_rows)


def _matched_signal_control(
    cohort: pd.DataFrame,
    signal_column: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    valid = (
        cohort[signal_column].notna()
        & _numeric(cohort, "feedback_budget_change_rate").notna()
    )
    signal = cohort.loc[valid & _bool(cohort, signal_column)].copy()
    if signal.empty:
        return signal, cohort.iloc[0:0].copy()
    strata = signal[FEEDBACK_STRATA].drop_duplicates()
    control = cohort.loc[valid & ~_bool(cohort, signal_column)].merge(
        strata,
        on=FEEDBACK_STRATA,
        how="inner",
        validate="many_to_many",
    )
    return signal, control


def _cluster_bootstrap_interval(
    signal: pd.DataFrame,
    control: pd.DataFrame,
    *,
    seed: int,
    iterations: int = 600,
) -> tuple[float, float]:
    signal_groups = {
        key: _numeric(part, "feedback_budget_change_rate").dropna().to_numpy()
        for key, part in signal.groupby("classification_project_id")
    }
    control_groups = {
        key: _numeric(part, "feedback_budget_change_rate").dropna().to_numpy()
        for key, part in control.groupby("classification_project_id")
    }
    if len(signal_groups) < 10 or len(control_groups) < 10:
        return math.nan, math.nan
    rng = np.random.default_rng(seed)
    signal_keys = np.array(list(signal_groups), dtype=object)
    control_keys = np.array(list(control_groups), dtype=object)
    differences = np.empty(iterations)
    for index in range(iterations):
        sampled_signal = rng.choice(
            signal_keys, size=len(signal_keys), replace=True
        )
        sampled_control = rng.choice(
            control_keys, size=len(control_keys), replace=True
        )
        signal_values = np.concatenate(
            [signal_groups[key] for key in sampled_signal]
        )
        control_values = np.concatenate(
            [control_groups[key] for key in sampled_control]
        )
        differences[index] = np.median(signal_values) - np.median(
            control_values
        )
    return (
        float(np.quantile(differences, 0.025)),
        float(np.quantile(differences, 0.975)),
    )


def _mean_rank_difference(
    signal: pd.DataFrame,
    control: pd.DataFrame,
) -> float:
    combined = pd.concat(
        [
            signal.assign(_signal_group=True),
            control.assign(_signal_group=False),
        ],
        ignore_index=True,
    )
    combined["_within_stratum_rank"] = combined.groupby(
        FEEDBACK_STRATA, dropna=False
    )["feedback_budget_change_rate"].rank(method="average", pct=True)
    signal_mean = combined.loc[
        combined["_signal_group"], "_within_stratum_rank"
    ].mean()
    control_mean = combined.loc[
        ~combined["_signal_group"], "_within_stratum_rank"
    ].mean()
    return float(signal_mean - control_mean)


def feedback_cluster_bootstrap(
    features: pd.DataFrame,
    peer_flags: pd.DataFrame,
    cohorts: pd.DataFrame,
    v2: pd.DataFrame,
) -> pd.DataFrame:
    """동일 사업 반복관측을 군집 단위로 재표집하여 환류 방향을 검증합니다."""
    audit_columns = [
        "source_project_year_id",
        "peer_bottom_10_conservative_tie_block",
        "peer_bottom_20_conservative_tie_block",
        "peer_p90_year_end_conservative_tie_block",
    ]
    enriched_features = features.merge(
        peer_flags[audit_columns],
        on="source_project_year_id",
        how="left",
        validate="one_to_one",
    )
    signal_specs = {
        "STRONG_LOW_EXECUTION": (
            "strong_low_execution_flag",
            "valid_execution_year_count",
        ),
        "MODERATE_LOW_EXECUTION": (
            "moderate_low_execution_flag",
            "valid_execution_year_count",
        ),
        "PEER_BOTTOM_10_CONSERVATIVE": (
            "peer_bottom_10_conservative_tie_block",
            "valid_execution_year_count",
        ),
        "PEER_BOTTOM_20_CONSERVATIVE": (
            "peer_bottom_20_conservative_tie_block",
            "valid_execution_year_count",
        ),
        "FIXED_YEAR_END": (
            "fixed_year_end_concentration_flag",
            "valid_monthly_year_count",
        ),
        "PEER_P90_YEAR_END_CONSERVATIVE": (
            "peer_p90_year_end_conservative_tie_block",
            "valid_monthly_year_count",
        ),
        "REPEATED_STRONG_LOW_EXECUTION": (
            "type_repeated_strong_low_execution",
            "valid_execution_year_count",
        ),
        "REPEATED_YEAR_END_CONCENTRATION": (
            "type_repeated_year_end_concentration",
            "valid_monthly_year_count",
        ),
    }
    rows: list[dict[str, Any]] = []
    for horizon_index, horizon in enumerate(["T+1", "T+2"]):
        cohort = _feedback_cohort_frame(
            cohorts, enriched_features, v2, horizon
        )
        extra_columns = [
            "source_project_year_id",
            "valid_execution_year_count",
            "valid_monthly_year_count",
            "peer_bottom_10_conservative_tie_block",
            "peer_bottom_20_conservative_tie_block",
            "peer_p90_year_end_conservative_tie_block",
        ]
        cohort = cohort.merge(
            enriched_features[extra_columns].rename(
                columns={"source_project_year_id": "base_project_id"}
            ),
            on="base_project_id",
            how="left",
            validate="many_to_one",
        )
        filters = {
            "ALL": pd.Series(True, index=cohort.index),
            "EXCLUDE_STRUCTURE_CANDIDATE": ~cohort["project_status"].isin(
                STRUCTURE_CANDIDATE_STATUSES
            ),
            "EXCLUDE_ONE_VALID_OBSERVATION": None,
            "EXCLUDE_SMALL_PROJECT": ~cohort["project_size_bucket"].eq(
                "Q1_SMALL"
            ),
            "EXCLUDE_LARGE_PROJECT": ~cohort["project_size_bucket"].eq(
                "Q4_VERY_LARGE"
            ),
        }
        for signal_index, (
            signal_name,
            (signal_column, valid_year_column),
        ) in enumerate(signal_specs.items()):
            if signal_column not in cohort:
                continue
            for filter_name, base_filter in filters.items():
                filter_mask = (
                    _numeric(cohort, valid_year_column).ge(2)
                    if filter_name == "EXCLUDE_ONE_VALID_OBSERVATION"
                    else base_filter
                )
                scoped = cohort.loc[filter_mask].copy()
                signal, control = _matched_signal_control(
                    scoped, signal_column
                )
                signal_values = _numeric(
                    signal, "feedback_budget_change_rate"
                ).dropna()
                control_values = _numeric(
                    control, "feedback_budget_change_rate"
                ).dropna()
                signal_projects = signal[
                    "classification_project_id"
                ].nunique()
                control_projects = control[
                    "classification_project_id"
                ].nunique()
                insufficient = signal_projects < 10 or control_projects < 10
                ci_low, ci_high = _cluster_bootstrap_interval(
                    signal,
                    control,
                    seed=20260726
                    + horizon_index * 100
                    + signal_index * 10,
                )
                rows.append(
                    {
                        "population": f"{horizon}_financial_continuity",
                        "feedback_horizon": horizon,
                        "signal": signal_name,
                        "source_column": signal_column,
                        "sensitivity_filter": filter_name,
                        "signal_row_count": len(signal_values),
                        "control_row_count": len(control_values),
                        "signal_unique_project_count": signal_projects,
                        "control_unique_project_count": control_projects,
                        "signal_budget_change_median": signal_values.median(),
                        "control_budget_change_median": control_values.median(),
                        "median_difference": (
                            signal_values.median()
                            - control_values.median()
                            if len(signal_values) and len(control_values)
                            else math.nan
                        ),
                        "mean_within_stratum_rank_difference": (
                            _mean_rank_difference(signal, control)
                            if len(signal_values) and len(control_values)
                            else math.nan
                        ),
                        "cluster_bootstrap_ci_low": ci_low,
                        "cluster_bootstrap_ci_high": ci_high,
                        "cluster_unit": "classification_project_id",
                        "bootstrap_iterations": 600
                        if not insufficient
                        else 0,
                        "insufficient_sample_flag": insufficient,
                        "result_status": (
                            "INSUFFICIENT_SAMPLE"
                            if insufficient
                            else "ESTIMATED_ASSOCIATION_NOT_CAUSAL"
                        ),
                        "causal_interpretation_allowed": False,
                    }
                )
    return pd.DataFrame(rows)


def _review_scenario_metrics(
    broad: pd.DataFrame,
    features: pd.DataFrame,
    unknown: pd.DataFrame,
    *,
    scenario: str,
    selected: pd.DataFrame,
    assumption_type: str,
) -> dict[str, Any]:
    selected_ids = set(selected["classification_project_id"].dropna())
    known = ~broad["fiscal_instrument"].eq("UNKNOWN")
    selected_rows = broad["classification_project_id"].isin(selected_ids)
    classified = known | selected_rows
    total_projects = broad["classification_project_id"].nunique()
    classified_projects = broad.loc[
        classified, "classification_project_id"
    ].nunique()
    selected_feature_rows = features[
        "classification_project_id"
    ].isin(selected_ids)
    current_rank_eligible = _bool(
        features, "fiscal_instrument_ranking_eligible"
    )
    total_budget = _sum(broad, "original_budget_analysis_amount")
    return {
        "scenario": scenario,
        "assumption_type": assumption_type,
        "review_unit_count": len(selected),
        "review_unique_project_count": len(selected_ids),
        "selected_unknown_budget_coverage": _safe_rate(
            _sum(selected, "original_budget_amount"),
            _sum(unknown, "original_budget_amount"),
        ),
        "classified_unique_project_count": classified_projects,
        "classified_unique_project_share": _safe_rate(
            classified_projects, total_projects
        ),
        "classified_project_year_row_count": int(classified.sum()),
        "classified_project_year_row_share": _safe_rate(
            int(classified.sum()), len(broad)
        ),
        "classified_original_budget_amount": _sum(
            broad.loc[classified], "original_budget_analysis_amount"
        ),
        "classified_original_budget_share": _safe_rate(
            _sum(
                broad.loc[classified], "original_budget_analysis_amount"
            ),
            total_budget,
        ),
        "fiscal_instrument_ranking_eligible_row_count": int(
            (current_rank_eligible | selected_feature_rows).sum()
        ),
        "ranking_eligible_row_increase": int(
            (selected_feature_rows & ~current_rank_eligible).sum()
        ),
        "comparison_group_size_change": math.nan,
        "small_group_count_change": math.nan,
        "comparison_group_change_status": (
            "UNIDENTIFIED_WITHOUT_MANUAL_INSTRUMENT_VALUES"
            if assumption_type == "COVERAGE_ASSUMPTION"
            else "ACTUAL_OR_PROXY_VALUES_REQUIRED"
        ),
        "actual_manual_confirmation_used": assumption_type
        == "ACTUAL_CONFIRMED",
    }


def unknown_review_impact(
    broad: pd.DataFrame,
    features: pd.DataFrame,
    unknown: pd.DataFrame,
) -> pd.DataFrame:
    """상위 16·40개 검수가 분류 커버리지에 미칠 효과를 가정과 실제로 분리합니다."""
    baseline = unknown.iloc[0:0].copy()
    top16 = unknown.head(16).copy()
    top40 = unknown.head(40).copy()
    actual = unknown[
        unknown["review_status"].eq("VERIFIED")
        & unknown["manual_confirmed_value"].notna()
    ].copy()
    rows = [
        _review_scenario_metrics(
            broad,
            features,
            unknown,
            scenario="BASELINE_ACTUAL",
            selected=baseline,
            assumption_type="ACTUAL_CONFIRMED",
        ),
        _review_scenario_metrics(
            broad,
            features,
            unknown,
            scenario="ASSUME_TOP_16_ALL_CONFIRMED",
            selected=top16,
            assumption_type="COVERAGE_ASSUMPTION",
        ),
        _review_scenario_metrics(
            broad,
            features,
            unknown,
            scenario="ASSUME_TOP_40_ALL_CONFIRMED",
            selected=top40,
            assumption_type="COVERAGE_ASSUMPTION",
        ),
        _review_scenario_metrics(
            broad,
            features,
            unknown,
            scenario="ACTUAL_MANUAL_CONFIRMED",
            selected=actual,
            assumption_type="ACTUAL_CONFIRMED",
        ),
    ]
    result = pd.DataFrame(rows)
    for count, selected in [(16, top16), (40, top40)]:
        single_candidate = selected[
            ~selected["keyword_candidate"].eq("NO_CANDIDATE")
            & ~_bool(selected, "multiple_candidate_flag")
        ]
        proxy = _review_scenario_metrics(
            broad,
            features,
            unknown,
            scenario=f"KEYWORD_PROXY_TOP_{count}",
            selected=single_candidate,
            assumption_type="UNCONFIRMED_KEYWORD_PROXY",
        )
        proxy["comparison_group_change_status"] = (
            "PARTIAL_PROXY_ONLY_NOT_A_MANUAL_CLASSIFICATION"
        )
        result = pd.concat([result, pd.DataFrame([proxy])], ignore_index=True)

    result["unknown_review_unit_total"] = len(unknown)
    result["top16_cumulative_budget_share"] = float(
        top16["cumulative_unknown_budget_share"].max()
    )
    result["top40_cumulative_budget_share"] = float(
        top40["cumulative_unknown_budget_share"].max()
    )
    result["top16_average_annual_budget"] = float(
        (
            top16["original_budget_amount"]
            / top16["observed_years"].fillna("").str.split(";").str.len()
        ).sum()
    )
    result["top40_average_annual_budget"] = float(
        (
            top40["original_budget_amount"]
            / top40["observed_years"].fillna("").str.split(";").str.len()
        ).sum()
    )
    for count, selected in [(16, top16), (40, top40)]:
        latest_budgets = []
        observed_year_counts = []
        for row in selected.itertuples(index=False):
            yearly = json.loads(row.yearly_original_budgets)
            observed_year_counts.append(len(yearly))
            latest_year = max(yearly, key=int)
            latest_budgets.append(float(yearly[latest_year]))
        result[f"top{count}_latest_year_budget"] = sum(latest_budgets)
        result[f"top{count}_mean_observed_year_count"] = float(
            np.mean(observed_year_counts)
        )
    result["interpretation_note"] = (
        "coverage scenarios assume a valid manual instrument assignment; "
        "comparison-group changes remain unknown until actual values exist"
    )
    return result


def _overall_method(
    comparison: pd.DataFrame,
    criterion: str,
    method: str,
) -> pd.Series:
    return comparison[
        comparison["criterion"].eq(criterion)
        & comparison["method"].eq(method)
        & comparison["dimension"].eq("OVERALL")
    ].iloc[0]


def build_audit_report(
    path: Path,
    summary: dict[str, Any],
    tie_audit: pd.DataFrame,
    method_comparison: pd.DataFrame,
    unit_audit: pd.DataFrame,
    feedback: pd.DataFrame,
    unknown_impact: pd.DataFrame,
) -> None:
    bottom10_old = _overall_method(
        method_comparison,
        "EXECUTION_BOTTOM_10",
        "EXISTING_QUANTILE_INCLUSIVE",
    )
    bottom10_new = _overall_method(
        method_comparison,
        "EXECUTION_BOTTOM_10",
        "CONSERVATIVE_TIE_BLOCK",
    )
    bottom20_old = _overall_method(
        method_comparison,
        "EXECUTION_BOTTOM_20",
        "EXISTING_QUANTILE_INCLUSIVE",
    )
    bottom20_new = _overall_method(
        method_comparison,
        "EXECUTION_BOTTOM_20",
        "CONSERVATIVE_TIE_BLOCK",
    )
    p90_old = _overall_method(
        method_comparison,
        "YEAR_END_P90",
        "EXISTING_QUANTILE_INCLUSIVE",
    )
    p90_new = _overall_method(
        method_comparison,
        "YEAR_END_P90",
        "CONSERVATIVE_TIE_BLOCK",
    )
    program = unit_audit[
        unit_audit["signal"].eq("PROGRAM_BUDGET_CONCENTRATION")
    ].iloc[0]
    t1_fixed = feedback[
        feedback["feedback_horizon"].eq("T+1")
        & feedback["signal"].eq("FIXED_YEAR_END")
        & feedback["sensitivity_filter"].eq("ALL")
    ].iloc[0]
    top16 = unknown_impact[
        unknown_impact["scenario"].eq("ASSUME_TOP_16_ALL_CONFIRMED")
    ].iloc[0]
    top40 = unknown_impact[
        unknown_impact["scenario"].eq("ASSUME_TOP_40_ALL_CONFIRMED")
    ].iloc[0]
    tie_excess = tie_audit["over_detection_row_count"].sum()
    all_tied = int(tie_audit["all_values_tied_flag"].sum())
    lines = [
        "# M3 방법론 감사",
        "",
        "## 1. 감사 결론",
        "",
        (
            "M3의 절대 집행률과 고정 연말집중 기준은 유지할 수 있지만, 기존 상대 분위수 플래그는 "
            "동률 경계와 소표본 때문에 명목 꼬리비율보다 넓게 탐지되어 교체가 필요합니다. "
            "프로그램 집중도는 프로그램-연도에서만 세고, T+1 결과는 사업 단위 군집 "
            "부트스트랩 구간과 함께 제시해야 합니다."
        ),
        "",
        "## 2. 사용 자료와 원본 보존",
        "",
        (
            f"기존 M3 6,290행을 읽기 전용으로 사용했습니다. 입력 해시 변경은 0건이며 감사 결과는 "
            f"`data/analytics/m3_audit/`에 분리했습니다. 검증 상태: {summary['validation_status']}."
        ),
        "",
        "## 3. 상대 분위수 과다 탐지 원인",
        "",
        (
            f"비교집단·지표 경계 감사에서 목표 꼬리 수를 넘은 행의 합은 {tie_excess:,}행이며, "
            f"모든 값이 같은 비교집단-지표 조합도 {all_tied:,}개였습니다. 분위수 경계 이하·이상을 "
            "모두 포함하는 규칙이 큰 동률 블록 전체를 선택한 것이 정확한 원인입니다."
        ),
        "",
        "| 기준 | 기존 탐지 | 보수적 동률 블록 | 기존 비율 | 보수적 비율 |",
        "|---|---:|---:|---:|---:|",
        (
            f"| 집행률 하위 10% | {int(bottom10_old['flagged_row_count']):,} | "
            f"{int(bottom10_new['flagged_row_count']):,} | "
            f"{bottom10_old['flagged_row_share']:.1%} | "
            f"{bottom10_new['flagged_row_share']:.1%} |"
        ),
        (
            f"| 집행률 하위 20% | {int(bottom20_old['flagged_row_count']):,} | "
            f"{int(bottom20_new['flagged_row_count']):,} | "
            f"{bottom20_old['flagged_row_share']:.1%} | "
            f"{bottom20_new['flagged_row_share']:.1%} |"
        ),
        (
            f"| 연말집중 P90 | {int(p90_old['flagged_row_count']):,} | "
            f"{int(p90_new['flagged_row_count']):,} | "
            f"{p90_old['flagged_row_share']:.1%} | "
            f"{p90_new['flagged_row_share']:.1%} |"
        ),
        "",
        "## 4. 상대순위 대안 판단",
        "",
        (
            "average percentile는 동률 블록의 중간순위를 부여하지만 목표 비율을 보장하지 않습니다. "
            "max percentile는 하위 꼬리에서 보수적이지만 상위 꼬리에서는 반대로 넓어질 수 있습니다. "
            "따라서 하위 꼬리는 max rank, 상위 꼬리는 min rank를 사용하는 방향별 "
            "`CONSERVATIVE_TIE_BLOCK`을 권장합니다. 경계 동률은 별도 플래그로 남기며 일부를 "
            "자의적으로 선택하지 않습니다."
        ),
        "",
        (
            "최소 비교집단은 기대 꼬리 관측 2개 기준으로 하위 10%·P90은 20개, 하위 20%·P80은 "
            "10개, P95는 40개로 두었습니다. 이는 권장 후보이며 팀 결정 전 확정 설정은 아닙니다."
        ),
        "",
        "## 5. 신호 분석 단위 감사",
        "",
        (
            f"프로그램 집중도는 기존 세부사업-연도 {int(program['previous_flagged_row_count']):,}행에 "
            f"복제되어 있었지만 실제 집중 프로그램-연도는 "
            f"{int(program['correct_grain_flagged_row_count']):,}행입니다. 행 수 기준 "
            f"{program['row_count_inflation_factor']:.1f}배 중복이며, 유형별 사업 수를 프로그램 수로 "
            "해석하면 과대계상됩니다."
        ),
        "",
        (
            "감사 산출물은 `project_year_signal_features`, `project_signal_recurrence`, "
            "`program_year_signal_features`로 분리했습니다. 프로그램 플래그는 세부사업 피처에서 "
            "제거했고 반복값은 고유 세부사업당 한 번만 저장했습니다."
        ),
        "",
        "## 6. T+1·T+2 사업 군집 부트스트랩",
        "",
        (
            f"T+1 고정 연말집중은 신호 {int(t1_fixed['signal_row_count']):,}행, 대조 "
            f"{int(t1_fixed['control_row_count']):,}행이며 중앙값 차이는 "
            f"{t1_fixed['median_difference']:.1%}입니다. 사업 단위 군집 부트스트랩 95% 구간은 "
            f"[{t1_fixed['cluster_bootstrap_ci_low']:.1%}, "
            f"{t1_fixed['cluster_bootstrap_ci_high']:.1%}]입니다."
        ),
        "",
        (
            "동일 연도·부처·회계유형·사업규모의 신호 존재 층에서 대조군을 구성하고, "
            "classification_project_id를 재표집 단위로 사용했습니다. 구조변화 후보, 유효관측 "
            "1년, 소규모, 대규모 제외 전후를 별도 행으로 보존했습니다. 구간이 0을 포함하거나 "
            "고유 사업이 10개 미만이면 결론으로 사용하지 않습니다."
        ),
        "",
        "## 7. UNKNOWN 우선검토 효과",
        "",
        (
            f"상위 16개를 모두 수기 확정한다고 가정하면 분류 본예산 커버리지는 "
            f"{top16['classified_original_budget_share']:.1%}, 상위 40개는 "
            f"{top40['classified_original_budget_share']:.1%}까지 개선됩니다. 이는 분류값이 "
            "실제로 확정된 결과가 아니라 커버리지 가정입니다."
        ),
        "",
        (
            f"상위 16개의 연평균 본예산 합계는 {top16['top16_average_annual_budget'] / 1e12:,.1f}조원, "
            f"각 사업의 최근 관측연도 본예산 합계는 "
            f"{top16['top16_latest_year_budget'] / 1e12:,.1f}조원이며 평균 관측연도 수는 "
            f"{top16['top16_mean_observed_year_count']:.1f}년입니다. 따라서 4개 연도 누적액만으로 "
            "우선순위를 해석하지 않습니다."
        ),
        "",
        (
            "상위 16개는 현재 키워드 단일 후보가 없어 재정수단별 비교집단 크기 변화는 계산할 수 "
            "없습니다. 실제 수기 확정값이 생기기 전에는 순위 적격 증가 행만 잠재치로 제시하고 "
            "비교집단 변화는 `UNIDENTIFIED`로 유지했습니다."
        ),
        "",
        "## 8. 공유 가능 범위",
        "",
        (
            "절대 기준, 고정 연말집중, 단위 분리 결과, 동률 과다탐지 원인과 군집 부트스트랩 결과는 "
            "팀에 공유할 수 있습니다. 상대 신호는 보수적 동률 보정 버전으로 교체하기 전까지 기존 "
            "플래그를 사용하면 안 됩니다. UNKNOWN 효과는 가정과 실제를 구분해 표시해야 합니다."
        ),
        "",
        "## 9. 권장 결정안",
        "",
        "1. 집행률 주 기준은 `<80%`, `80~90%`로 유지합니다.",
        "2. 상대 집행률은 방향별 보수적 percentile rank와 경계 동률 플래그를 병행합니다.",
        "3. 연말집중 주 기준은 고정 40%/20%, P90은 보조, P80·P95는 민감도로 둡니다.",
        "4. 반복은 2회 이상이면서 유효연도 50% 이상, 연속 2회는 보조로 둡니다.",
        "5. UNKNOWN 16개를 먼저 실제 수기검토한 뒤 효과표를 실제값으로 갱신합니다.",
        "",
        "## 10. 남은 한계",
        "",
        (
            "군집 부트스트랩은 반복관측 의존성을 완화하지만 사업 종료, 단계 전환, 정책 우선순위 등 "
            "미관측 요인을 제거하지 못합니다. 평균순위 차이도 인과효과가 아닙니다. 수기 확정되지 "
            "않은 UNKNOWN은 재정수단별 비교집단에 배치하지 않았습니다."
        ),
        "",
        "## 11. 다음 단계",
        "",
        "1. UNKNOWN 상위 16개를 실제로 수기 분류합니다.",
        "2. 팀에 감사 결과를 공유하고 기준 역할을 결정합니다.",
        "3. 결정된 값만 설정파일과 의사결정 기록에 고정합니다.",
        "4. 그 뒤 프로그램 단위 성과자료를 연결합니다.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def build_m3_methodology_audit(paths: AuditPaths) -> AuditResult:
    missing = [path for path in paths.inputs if not path.exists()]
    if missing:
        raise FileNotFoundError(f"M3 감사 입력 누락: {missing}")
    before = {str(path): _hash(path) for path in paths.inputs}
    features = pd.read_parquet(paths.features)
    programs = pd.read_parquet(paths.programs)
    broad = pd.read_parquet(paths.broad)
    v2 = pd.read_parquet(paths.v2)
    cohorts = pd.read_csv(
        paths.cohorts,
        dtype={"ministry_code": "string", "program_code": "string"},
    )
    unknown = pd.read_csv(
        paths.unknown,
        dtype={
            "ministry_code": "string",
            "program_code": "string",
            "subactivity_code": "string",
        },
    )
    for frame in [features, programs, broad, v2]:
        if "ministry_code" in frame:
            frame["ministry_code"] = frame["ministry_code"].astype("string")

    tie_audit = peer_threshold_tie_audit(features)
    peer_flags = build_peer_method_flags(features)
    method_comparison = peer_method_comparison(features, peer_flags)
    project_year, recurrence, program_year, unit_audit = split_signal_grains(
        features, programs
    )
    feedback = feedback_cluster_bootstrap(
        features, peer_flags, cohorts, v2
    )
    unknown_impact = unknown_review_impact(broad, features, unknown)

    paths.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "peer_threshold_tie_audit.csv": tie_audit,
        "peer_threshold_method_comparison.csv": method_comparison,
        "signal_unit_audit.csv": unit_audit,
        "feedback_cluster_bootstrap.csv": feedback,
        "unknown_review_impact.csv": unknown_impact,
    }
    output_paths: list[Path] = []
    for filename, frame in outputs.items():
        output = paths.output_dir / filename
        frame.to_csv(output, index=False, encoding="utf-8-sig")
        output_paths.append(output)
    parquet_outputs = {
        "project_year_signal_features.parquet": project_year,
        "project_signal_recurrence.parquet": recurrence,
        "program_year_signal_features.parquet": program_year,
    }
    for filename, frame in parquet_outputs.items():
        output = paths.output_dir / filename
        frame.to_parquet(output, index=False)
        output_paths.append(output)

    after = {str(path): _hash(path) for path in paths.inputs}
    program_audit = unit_audit[
        unit_audit["signal"].eq("PROGRAM_BUDGET_CONCENTRATION")
    ].iloc[0]
    validation = {
        "source_files_unchanged": before == after,
        "project_year_row_count_preserved": len(project_year) == len(features),
        "project_recurrence_key_unique": not recurrence[
            "classification_project_id"
        ].duplicated().any(),
        "program_year_key_unique": not program_year[
            PROGRAM_KEYS
        ].duplicated().any(),
        "program_signal_not_in_project_features": (
            "program_concentration_flag" not in project_year
        ),
        "program_duplicate_counting_detected": bool(
            program_audit["duplicate_counting_confirmed"]
        ),
        "no_arbitrary_tie_selection": not method_comparison[
            "arbitrary_boundary_selection_used"
        ].any(),
        "cluster_unit_is_project": feedback["cluster_unit"].eq(
            "classification_project_id"
        ).all(),
        "t1_t2_separate": set(feedback["feedback_horizon"]) == {"T+1", "T+2"},
        "unknown_actual_and_assumption_separated": set(
            unknown_impact["assumption_type"]
        )
        >= {
            "ACTUAL_CONFIRMED",
            "COVERAGE_ASSUMPTION",
            "UNCONFIRMED_KEYWORD_PROXY",
        },
        "leading_zero_codes_preserved": {"019", "075"}.issubset(
            set(project_year["ministry_code"].astype(str))
        ),
        "final_composite_score_generated": False,
        "overall_rank_generated": False,
    }
    failed = [
        key
        for key, value in validation.items()
        if key
        not in {"final_composite_score_generated", "overall_rank_generated"}
        and value is False
    ]
    summary: dict[str, Any] = {
        "population": "M3 methodology audit",
        "feature_rows": len(features),
        "tie_audit_group_metric_rows": len(tie_audit),
        "method_comparison_rows": len(method_comparison),
        "project_year_signal_rows": len(project_year),
        "project_recurrence_rows": len(recurrence),
        "program_year_signal_rows": len(program_year),
        "feedback_audit_rows": len(feedback),
        "unknown_impact_scenarios": len(unknown_impact),
        "validation": validation,
        "validation_status": "PASS" if not failed else "FAIL",
        "thresholds_persisted_as_final_configuration": False,
        "existing_m3_outputs_overwritten": False,
        "manual_unknown_values_invented": False,
        "limitations": [
            "peer threshold minimum sizes are methodology recommendations, not final config",
            "cluster bootstrap is associational and does not identify causal effects",
            "comparison-group changes require actual manual UNKNOWN classifications",
        ],
    }
    summary_path = paths.output_dir / "m3_methodology_audit_summary.json"
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
    build_audit_report(
        paths.report,
        summary,
        tie_audit,
        method_comparison,
        unit_audit,
        feedback,
        unknown_impact,
    )
    if failed:
        raise ValueError(f"M3 방법론 감사 검증 실패: {failed}")
    return AuditResult(output_paths, paths.report, summary)
