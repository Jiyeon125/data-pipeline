from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import yaml

KEY = ["ministry_code", "program_code", "fiscal_year", "account_type"]
COMPONENTS = (
    "performance_gap",
    "execution_management",
    "budget_performance_mismatch",
    "fiscal_impact",
)
SIGNAL_FLAGS = (
    "type_repeated_strong_low_execution",
    "type_repeated_moderate_low_execution",
    "type_repeated_year_end_concentration",
    "type_accounting_adjustment_pattern",
    "type_budget_rapid_increase",
    "type_budget_rapid_decrease",
    "type_program_budget_concentration",
    "type_multiple_financial_signals",
    "type_data_validation_priority",
)
TIER_ORDER = {
    "DATA_REVIEW": 0,
    "MULTIPLE_SIGNAL_REVIEW": 1,
    "STRONG_SINGLE_SIGNAL_REVIEW": 2,
    "MODERATE_OR_CONTEXT_REVIEW": 3,
    "CONTEXT_REVIEW": 4,
    "INFORMATION": 5,
}


class PriorityScenarioError(ValueError):
    """점검 후보·시나리오 순위의 입력 또는 검증 조건이 깨졌을 때 발생합니다."""


@dataclass(frozen=True)
class PriorityScenarioPaths:
    same_year_analysis: Path
    financial_features: Path
    config: Path
    output_dir: Path
    figure_dir: Path
    figure_prefix: str = "mss_priority_scenario"

    @classmethod
    def from_root(cls, root: Path) -> PriorityScenarioPaths:
        return cls(
            same_year_analysis=root
            / "data/analytics/mss_same_year_budget_check/program_year_account_type_check.csv",
            financial_features=root / "data/analytics/m3/financial_signal_features.parquet",
            config=root / "configs/mss_priority_scenarios.yaml",
            output_dir=root / "data/analytics/mss_priority_scenarios",
            figure_dir=root / "artifacts/figures/presentation",
        )

    @classmethod
    def three_ministry_from_root(cls, root: Path) -> PriorityScenarioPaths:
        return cls(
            same_year_analysis=root / "data/analytics/three_ministry_same_year_budget_check/"
            "program_year_account_type_check.csv",
            financial_features=root / "data/analytics/m3/financial_signal_features.parquet",
            config=root / "configs/three_ministry_priority_scenarios.yaml",
            output_dir=root / "data/analytics/three_ministry_priority_scenarios",
            figure_dir=root / "artifacts/figures/presentation",
            figure_prefix="three_ministry_priority_scenario",
        )


@dataclass(frozen=True)
class PriorityScenarioResult:
    candidates: pd.DataFrame
    scenario_scores: pd.DataFrame
    stability: pd.DataFrame
    drilldown: pd.DataFrame
    spearman: pd.DataFrame
    top_k_overlap: pd.DataFrame
    summary: dict[str, Any]
    output_paths: tuple[Path, ...]
    figure_paths: tuple[Path, ...]


def _require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise PriorityScenarioError(f"{label}에 필수 컬럼이 없습니다: {missing}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_scenario_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise PriorityScenarioError("시나리오 설정은 객체여야 합니다.")
    if tuple(config.get("components", ())) != COMPONENTS:
        raise PriorityScenarioError(f"구성요소는 다음 순서여야 합니다: {COMPONENTS}")
    scenarios = config.get("scenarios")
    if not isinstance(scenarios, dict) or len(scenarios) < 2:
        raise PriorityScenarioError("비교할 시나리오가 2개 이상 필요합니다.")
    for name, weights in scenarios.items():
        if set(weights) != set(COMPONENTS):
            raise PriorityScenarioError(f"{name} 시나리오의 구성요소가 불완전합니다.")
        if any(float(value) < 0 for value in weights.values()):
            raise PriorityScenarioError(f"{name} 시나리오에 음수 가중치가 있습니다.")
        if abs(sum(float(value) for value in weights.values()) - 1) > 1e-9:
            raise PriorityScenarioError(f"{name} 시나리오 가중치 합계가 1이 아닙니다.")
    top_k = config.get("top_k")
    if not isinstance(top_k, list) or not top_k or any(int(value) < 1 for value in top_k):
        raise PriorityScenarioError("top_k에는 1 이상의 정수가 필요합니다.")
    thresholds = config.get("thresholds", {})
    strong = float(thresholds.get("execution_strong", -1))
    moderate = float(thresholds.get("execution_moderate", -1))
    if not 0 <= strong < moderate <= 1:
        raise PriorityScenarioError("집행률 강한·주의 기준의 순서 또는 범위가 잘못되었습니다.")
    return config


def _weighted_share(part: pd.DataFrame, flag: str, weights: pd.Series) -> float:
    mask = part[flag].fillna(False).astype(bool)
    denominator = float(weights.sum())
    if denominator > 0:
        return float(weights.loc[mask].sum() / denominator)
    return float(mask.mean())


def aggregate_program_account_signals(
    features: pd.DataFrame,
    *,
    ministry_code: str | None = None,
    ministry_codes: tuple[str, ...] | None = None,
    start_year: int,
    end_year: int,
) -> pd.DataFrame:
    _require_columns(
        features,
        {
            *KEY,
            "project_id",
            "original_budget_analysis_amount",
            "rank_confidence",
            "independent_signal_count",
            "active_signal_types",
            *SIGNAL_FLAGS,
        },
        "M3 재정 신호 feature",
    )
    if (ministry_code is None) == (ministry_codes is None):
        raise PriorityScenarioError("ministry_code 또는 ministry_codes 중 하나만 지정해야 합니다.")
    codes = (
        (str(ministry_code).zfill(3),)
        if ministry_code is not None
        else tuple(str(code).zfill(3) for code in ministry_codes or ())
    )
    source = features.loc[
        features["ministry_code"].astype("string").str.zfill(3).isin(codes)
        & features["fiscal_year"].between(start_year, end_year)
        & features["program_code"].notna()
        & features["account_type"].notna()
    ].copy()
    source["ministry_code"] = source["ministry_code"].astype("string")
    source["program_code"] = source["program_code"].astype("string")
    if source["project_id"].duplicated().any():
        raise PriorityScenarioError("M3 재정 신호의 project_id가 중복되었습니다.")

    confidence_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    rows: list[dict[str, Any]] = []
    for key_values, part in source.groupby(KEY, sort=True, dropna=False):
        weights = (
            pd.to_numeric(part["original_budget_analysis_amount"], errors="coerce")
            .fillna(0)
            .clip(lower=0)
        )
        denominator = float(weights.sum())
        row: dict[str, Any] = dict(zip(KEY, key_values, strict=True))
        row.update(
            {
                "project_signal_row_count": len(part),
                "project_signal_budget": denominator,
                "weighted_independent_signal_count": (
                    float(
                        (
                            pd.to_numeric(part["independent_signal_count"], errors="coerce").fillna(
                                0
                            )
                            * weights
                        ).sum()
                        / denominator
                    )
                    if denominator > 0
                    else float(
                        pd.to_numeric(part["independent_signal_count"], errors="coerce")
                        .fillna(0)
                        .mean()
                    )
                ),
            }
        )
        for flag in SIGNAL_FLAGS:
            row[f"{flag}_project_count"] = int(part[flag].fillna(False).sum())
            row[f"{flag}_budget_share"] = _weighted_share(part, flag, weights)
        confidence = part["rank_confidence"].dropna().astype(str).map(confidence_order).dropna()
        row["rank_confidence_worst"] = (
            min(confidence_order, key=confidence_order.get)
            if confidence.empty
            else {value: label for label, value in confidence_order.items()}[int(confidence.min())]
        )
        active_types = sorted(
            {
                item
                for value in part["active_signal_types"].dropna().astype(str)
                for item in value.split(";")
                if item and item != "NONE"
            }
        )
        row["active_financial_signal_types"] = ";".join(active_types) or "NONE"
        rows.append(row)

    result = pd.DataFrame(rows).convert_dtypes()
    if result.duplicated(KEY).any():
        raise PriorityScenarioError("프로그램-연도-회계유형 재정 신호 키가 중복되었습니다.")
    return result


def build_stable_top5_project_drilldown(
    candidates: pd.DataFrame,
    stability: pd.DataFrame,
    features: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """안정 상위 후보의 세부사업 재정 원인을 성과 귀속 없이 연결합니다."""
    _require_columns(
        candidates,
        {
            "candidate_id",
            *KEY,
            "performance_program_name",
            "priority_reason",
            "account_original_budget",
            "account_current_budget",
            "account_settlement_expenditure",
        },
        "후보표",
    )
    _require_columns(
        stability,
        {"candidate_id", "all_scenario_top_5"},
        "순위 안정성표",
    )
    _require_columns(
        features,
        {
            *KEY,
            "project_id",
            "account_code",
            "account_name_budget_api",
            "activity_code",
            "activity_name_budget_api",
            "subactivity_code",
            "subactivity_name_budget_api",
            "original_budget_analysis_amount",
            "current_budget_analysis_amount",
            "settlement_analysis_amount",
            "settlement_carryover_amount",
            "settlement_unused_amount",
            "execution_rate",
            "active_signal_types",
            "project_status",
            "structural_change_type",
            "financial_quality_level",
            "rank_confidence",
            "budget_ranking_eligible",
            "execution_ranking_eligible",
            "source_trace_v2",
        },
        "M3 세부사업 재정 신호",
    )
    stable_ids = stability.loc[
        stability["all_scenario_top_5"].fillna(False),
        "candidate_id",
    ]
    stable = candidates.loc[
        candidates["candidate_id"].isin(stable_ids),
        [
            "candidate_id",
            *KEY,
            "performance_program_name",
            "priority_reason",
            "account_original_budget",
            "account_current_budget",
            "account_settlement_expenditure",
        ],
    ].copy()
    stable["ministry_code"] = stable["ministry_code"].astype("string").str.zfill(3)
    stable["program_code"] = stable["program_code"].astype("string")
    if stable["candidate_id"].duplicated().any():
        raise PriorityScenarioError("안정 상위 후보 ID가 중복되었습니다.")

    feature_columns = [
        *KEY,
        "project_id",
        "account_code",
        "account_name_budget_api",
        "activity_code",
        "activity_name_budget_api",
        "subactivity_code",
        "subactivity_name_budget_api",
        "original_budget_analysis_amount",
        "current_budget_analysis_amount",
        "settlement_analysis_amount",
        "settlement_carryover_amount",
        "settlement_unused_amount",
        "execution_rate",
        "active_signal_types",
        "project_status",
        "structural_change_type",
        "financial_quality_level",
        "rank_confidence",
        "budget_ranking_eligible",
        "execution_ranking_eligible",
        "source_trace_v2",
    ]
    source = features[feature_columns].copy()
    source["ministry_code"] = source["ministry_code"].astype("string").str.zfill(3)
    source["program_code"] = source["program_code"].astype("string")
    drilldown = source.merge(
        stable,
        on=KEY,
        how="inner",
        validate="many_to_one",
    )
    matched_ids = set(drilldown["candidate_id"])
    missing_ids = sorted(set(stable["candidate_id"]) - matched_ids)
    if missing_ids:
        raise PriorityScenarioError(f"안정 상위 후보의 세부사업이 누락되었습니다: {missing_ids}")
    if drilldown.duplicated(["candidate_id", "project_id"]).any():
        raise PriorityScenarioError("후보-세부사업 키가 중복되었습니다.")
    if set(drilldown["ministry_code"]) != set(stable["ministry_code"]):
        raise PriorityScenarioError("세부사업 드릴다운에 다른 부처 행이 섞였습니다.")

    amount_map = {
        "original_budget_analysis_amount": "project_original_budget",
        "current_budget_analysis_amount": "project_current_budget",
        "settlement_analysis_amount": "project_expenditure",
        "settlement_carryover_amount": "project_carryover",
        "settlement_unused_amount": "project_unused",
    }
    drilldown = drilldown.rename(columns=amount_map)
    for column in amount_map.values():
        drilldown[column] = pd.to_numeric(drilldown[column], errors="coerce")
    drilldown["project_remaining_amount"] = (
        drilldown["project_current_budget"] - drilldown["project_expenditure"]
    )
    drilldown["budget_share_within_candidate"] = drilldown["project_original_budget"].div(
        drilldown["account_original_budget"].where(drilldown["account_original_budget"].gt(0))
    )
    total_remaining = drilldown.groupby("candidate_id")["project_remaining_amount"].transform("sum")
    drilldown["remaining_share_within_candidate"] = drilldown["project_remaining_amount"].div(
        total_remaining.where(total_remaining.ne(0))
    )
    drilldown["budget_rank_within_candidate"] = drilldown.groupby("candidate_id")[
        "project_original_budget"
    ].rank(method="min", ascending=False)
    drilldown["program_performance_signal"] = drilldown["priority_reason"].str.contains(
        "PERFORMANCE_BELOW_TARGET",
        na=False,
    )
    drilldown["project_performance_attributed"] = False
    drilldown["drilldown_role"] = "PROJECT_FINANCIAL_CONTEXT_ONLY"
    drilldown = drilldown.rename(
        columns={
            "subactivity_name_budget_api": "project_name",
            "active_signal_types": "project_financial_signal_types",
        }
    )

    checks = drilldown.groupby("candidate_id", as_index=False).agg(
        project_original_budget=("project_original_budget", "sum"),
        project_current_budget=("project_current_budget", "sum"),
        project_expenditure=("project_expenditure", "sum"),
    )
    checks = checks.merge(
        stable[
            [
                "candidate_id",
                "account_original_budget",
                "account_current_budget",
                "account_settlement_expenditure",
            ]
        ],
        on="candidate_id",
        validate="one_to_one",
    )
    comparisons = (
        ("project_original_budget", "account_original_budget"),
        ("project_current_budget", "account_current_budget"),
        ("project_expenditure", "account_settlement_expenditure"),
    )
    for project_column, account_column in comparisons:
        if checks[project_column].sub(checks[account_column]).abs().gt(0.5).any():
            raise PriorityScenarioError(f"세부사업 합계와 후보표 금액이 다릅니다: {project_column}")

    output_columns = [
        "candidate_id",
        *KEY,
        "performance_program_name",
        "priority_reason",
        "program_performance_signal",
        "project_performance_attributed",
        "drilldown_role",
        "project_id",
        "account_code",
        "account_name_budget_api",
        "activity_code",
        "activity_name_budget_api",
        "subactivity_code",
        "project_name",
        "project_original_budget",
        "project_current_budget",
        "project_expenditure",
        "project_remaining_amount",
        "project_carryover",
        "project_unused",
        "execution_rate",
        "budget_share_within_candidate",
        "remaining_share_within_candidate",
        "budget_rank_within_candidate",
        "project_financial_signal_types",
        "project_status",
        "structural_change_type",
        "financial_quality_level",
        "rank_confidence",
        "budget_ranking_eligible",
        "execution_ranking_eligible",
        "source_trace_v2",
    ]
    result = drilldown[output_columns].sort_values(
        ["candidate_id", "budget_rank_within_candidate", "project_id"],
        ignore_index=True,
    )
    summary = {
        "candidate_count": int(result["candidate_id"].nunique()),
        "unique_program_count": int(result["program_code"].nunique()),
        "project_row_count": len(result),
        "other_ministry_row_count": int(
            (~result["ministry_code"].isin(stable["ministry_code"])).sum()
        ),
        "candidate_project_key_unique": not result.duplicated(["candidate_id", "project_id"]).any(),
        "original_budget_reconciled": True,
        "current_budget_reconciled": True,
        "expenditure_reconciled": True,
        "project_performance_attribution_count": int(
            result["project_performance_attributed"].sum()
        ),
    }
    return result.convert_dtypes(), summary


def _current_execution_severity(
    execution_rate: pd.Series,
    *,
    strong: float,
    moderate: float,
) -> pd.Series:
    numeric = pd.to_numeric(execution_rate, errors="coerce")
    result = pd.Series(pd.NA, index=numeric.index, dtype="Float64")
    result.loc[numeric.notna()] = 0.0
    result.loc[numeric.lt(moderate)] = 0.5
    result.loc[numeric.lt(strong)] = 1.0
    return result


def _build_priority_reason(row: pd.Series) -> str:
    reasons: list[str] = []
    if row["analysis_status"] != "JOINT_ANALYSIS":
        reasons.append(str(row["analysis_status"]))
    if bool(row["data_validation_signal"]):
        reasons.append("DATA_VALIDATION")
    if bool(row["performance_signal"]):
        reasons.append("PERFORMANCE_BELOW_TARGET")
    if bool(row["execution_signal"]):
        reasons.append("EXECUTION_MANAGEMENT")
    if bool(row["budget_mismatch_signal"]):
        reasons.append("BUDGET_PERFORMANCE_MISMATCH")
    if bool(row["accounting_context_signal"]):
        reasons.append("ACCOUNTING_ADJUSTMENT_CONTEXT")
    if bool(row["structure_context_signal"]):
        reasons.append("PROGRAM_STRUCTURE_CONTEXT")
    return ";".join(reasons) or "NO_REVIEW_SIGNAL"


def build_candidate_population(
    analysis: pd.DataFrame,
    program_signals: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    _require_columns(
        analysis,
        {
            *KEY,
            "performance_program_name",
            "analysis_status",
            "comparable_rate_count",
            "below_target_count",
            "formula_review_count",
            "reported_performance_signal",
            "account_original_budget",
            "account_execution_rate",
            "account_financial_linkage_status",
            "account_financial_quality_level",
        },
        "중기부 성과·재정 결합표",
    )
    analysis = analysis.copy()
    analysis["ministry_code"] = analysis["ministry_code"].astype("string")
    analysis["program_code"] = analysis["program_code"].astype("string")
    complete_key = analysis[KEY].notna().all(axis=1)
    if analysis.loc[complete_key].duplicated(KEY).any():
        raise PriorityScenarioError("성과·재정 결합표의 유효 분석 키가 중복되었습니다.")

    merged = analysis.loc[complete_key].merge(
        program_signals,
        on=KEY,
        how="left",
        validate="one_to_one",
        indicator="financial_signal_join_status",
    )
    incomplete = analysis.loc[~complete_key].copy()
    for column in program_signals.columns:
        if column not in KEY:
            incomplete[column] = pd.NA
    incomplete["financial_signal_join_status"] = "left_only"
    if not incomplete.empty:
        merged = pd.concat(
            [merged, incomplete.dropna(axis=1, how="all")],
            ignore_index=True,
        )
    joint = merged["analysis_status"].eq("JOINT_ANALYSIS")
    signal_joined = merged["financial_signal_join_status"].eq("both")
    merged["financial_signal_budget_difference"] = pd.to_numeric(
        merged["project_signal_budget"], errors="coerce"
    ) - pd.to_numeric(merged["account_original_budget"], errors="coerce")
    merged["financial_signal_budget_reconciled"] = signal_joined & merged[
        "financial_signal_budget_difference"
    ].fillna(0).eq(0)

    comparable = pd.to_numeric(merged["comparable_rate_count"], errors="coerce")
    merged["performance_gap"] = (
        pd.to_numeric(merged["below_target_count"], errors="coerce")
        .div(comparable.where(comparable.gt(0)))
        .astype("Float64")
    )

    thresholds = config["thresholds"]
    merged["current_execution_severity"] = _current_execution_severity(
        merged["account_execution_rate"],
        strong=float(thresholds["execution_strong"]),
        moderate=float(thresholds["execution_moderate"]),
    )
    repeated_moderate = merged["type_repeated_moderate_low_execution_budget_share"] * float(
        thresholds["repeated_moderate_weight"]
    )
    repeated_year_end = merged["type_repeated_year_end_concentration_budget_share"] * float(
        thresholds["repeated_year_end_weight"]
    )
    merged["execution_management"] = pd.concat(
        [
            merged["current_execution_severity"],
            merged["type_repeated_strong_low_execution_budget_share"],
            repeated_moderate,
            repeated_year_end,
        ],
        axis=1,
    ).max(axis=1, skipna=False)

    low_performance_increase = (
        merged["performance_gap"] * merged["type_budget_rapid_increase_budget_share"]
    )
    high_performance_decrease = (1 - merged["performance_gap"]) * merged[
        "type_budget_rapid_decrease_budget_share"
    ]
    merged["budget_performance_mismatch"] = pd.concat(
        [low_performance_increase, high_performance_decrease],
        axis=1,
    ).max(axis=1, skipna=False)

    merged["fiscal_impact"] = pd.Series(pd.NA, index=merged.index, dtype="Float64")
    merged.loc[joint, "fiscal_impact"] = (
        pd.to_numeric(
            merged.loc[joint, "account_original_budget"],
            errors="coerce",
        )
        .groupby(merged.loc[joint, "fiscal_year"])
        .rank(method="average", pct=True)
        .astype("Float64")
    )
    merged["fiscal_impact_within_ministry"] = pd.Series(pd.NA, index=merged.index, dtype="Float64")
    merged.loc[joint, "fiscal_impact_within_ministry"] = (
        pd.to_numeric(
            merged.loc[joint, "account_original_budget"],
            errors="coerce",
        )
        .groupby(
            [
                merged.loc[joint, "ministry_code"],
                merged.loc[joint, "fiscal_year"],
            ]
        )
        .rank(method="average", pct=True)
        .astype("Float64")
    )

    merged["data_validation_signal"] = (
        merged["analysis_status"].ne("JOINT_ANALYSIS")
        | ~signal_joined
        | ~merged["financial_signal_budget_reconciled"]
        | merged["type_data_validation_priority_budget_share"].fillna(0).gt(0)
    )
    merged["performance_signal"] = merged["performance_gap"].fillna(0).gt(0)
    merged["execution_signal"] = merged["execution_management"].fillna(0).gt(0)
    merged["budget_mismatch_signal"] = merged["budget_performance_mismatch"].fillna(0).gt(0)
    merged["accounting_context_signal"] = (
        merged["type_accounting_adjustment_pattern_budget_share"].fillna(0).gt(0)
    )
    merged["structure_context_signal"] = (
        merged["type_program_budget_concentration_budget_share"].fillna(0).gt(0)
    )
    modeled_columns = [
        "performance_signal",
        "execution_signal",
        "budget_mismatch_signal",
    ]
    context_columns = ["accounting_context_signal", "structure_context_signal"]
    merged["modeled_signal_family_count"] = merged[modeled_columns].sum(axis=1)
    merged["context_signal_family_count"] = merged[context_columns].sum(axis=1)
    merged["review_candidate"] = joint & (
        merged["modeled_signal_family_count"].gt(0) | merged["context_signal_family_count"].gt(0)
    )
    component_complete = merged[list(COMPONENTS)].notna().all(axis=1)
    merged["scenario_ranking_eligible"] = (
        joint
        & ~merged["data_validation_signal"]
        & merged["modeled_signal_family_count"].gt(0)
        & component_complete
    )
    merged["context_only_candidate"] = (
        merged["review_candidate"] & ~merged["scenario_ranking_eligible"]
    )

    strong_single = (
        merged["performance_gap"].fillna(0).ge(1)
        | merged["current_execution_severity"].fillna(0).ge(1)
        | merged["type_repeated_strong_low_execution_budget_share"].fillna(0).ge(0.5)
    )
    merged["priority_tier"] = "INFORMATION"
    merged.loc[merged["context_only_candidate"], "priority_tier"] = "CONTEXT_REVIEW"
    merged.loc[merged["scenario_ranking_eligible"], "priority_tier"] = "MODERATE_OR_CONTEXT_REVIEW"
    merged.loc[
        merged["scenario_ranking_eligible"] & strong_single,
        "priority_tier",
    ] = "STRONG_SINGLE_SIGNAL_REVIEW"
    merged.loc[
        merged["scenario_ranking_eligible"] & merged["modeled_signal_family_count"].ge(2),
        "priority_tier",
    ] = "MULTIPLE_SIGNAL_REVIEW"
    merged.loc[merged["data_validation_signal"], "priority_tier"] = "DATA_REVIEW"
    merged["priority_reason"] = merged.apply(_build_priority_reason, axis=1)
    program_identity = merged["program_code"].fillna(
        merged["performance_program_name"].astype("string")
    )
    merged["candidate_id"] = (
        merged["ministry_code"].fillna("NA").astype(str)
        + ":"
        + merged["fiscal_year"].astype(str)
        + ":"
        + program_identity.fillna("NA").astype(str)
        + ":"
        + merged["account_type"].fillna("NA").astype(str)
    )
    merged["priority_tier_order"] = merged["priority_tier"].map(TIER_ORDER)
    result = merged.sort_values(
        [
            "priority_tier_order",
            "fiscal_year",
            "performance_program_name",
            "account_type",
        ],
        na_position="last",
    ).reset_index(drop=True)
    if result["candidate_id"].duplicated().any():
        raise PriorityScenarioError("후보 ID가 중복되었습니다.")
    return result.convert_dtypes()


def score_scenarios(
    candidates: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    eligible = candidates.loc[candidates["scenario_ranking_eligible"]].copy()
    if eligible.empty:
        raise PriorityScenarioError("시나리오 순위를 계산할 적격 후보가 없습니다.")
    if eligible[list(COMPONENTS)].isna().any().any():
        raise PriorityScenarioError("시나리오 구성요소 결측을 0점 처리할 수 없습니다.")

    rows: list[pd.DataFrame] = []
    for scenario, raw_weights in config["scenarios"].items():
        weights = {key: float(value) for key, value in raw_weights.items()}
        part = eligible[
            [
                "candidate_id",
                *KEY,
                "performance_program_name",
                "priority_tier",
                "priority_reason",
                "account_original_budget",
                "fiscal_impact_within_ministry",
                *COMPONENTS,
            ]
        ].copy()
        part["scenario"] = scenario
        part["scenario_score"] = sum(
            part[component].astype(float) * weight for component, weight in weights.items()
        )
        part["scenario_score_within_ministry"] = (
            part["scenario_score"]
            - part["fiscal_impact"].astype(float) * weights["fiscal_impact"]
            + part["fiscal_impact_within_ministry"].astype(float) * weights["fiscal_impact"]
        )
        part["scenario_rank_min"] = part["scenario_score"].rank(method="min", ascending=False)
        part["scenario_rank_average"] = part["scenario_score"].rank(
            method="average", ascending=False
        )
        part["scenario_rank_max"] = part["scenario_score"].rank(method="max", ascending=False)
        denominator = max(len(part) - 1, 1)
        part["scenario_rank_percentile"] = 1 - (part["scenario_rank_average"] - 1) / denominator
        grouped = part.groupby("ministry_code")["scenario_score_within_ministry"]
        part["scenario_rank_min_within_ministry"] = grouped.rank(method="min", ascending=False)
        part["scenario_rank_average_within_ministry"] = grouped.rank(
            method="average", ascending=False
        )
        part["scenario_rank_max_within_ministry"] = grouped.rank(method="max", ascending=False)
        ministry_counts = part.groupby("ministry_code")["candidate_id"].transform("size")
        part["scenario_rank_percentile_within_ministry"] = 1 - (
            part["scenario_rank_average_within_ministry"] - 1
        ) / (ministry_counts - 1).clip(lower=1)
        part["scenario_weights"] = json.dumps(weights, ensure_ascii=False, sort_keys=True)
        rows.append(part)
    result = pd.concat(rows, ignore_index=True).convert_dtypes()
    if not result["scenario_score"].between(0, 1, inclusive="both").all():
        raise PriorityScenarioError("시나리오 점수가 0~1 범위를 벗어났습니다.")
    return result


def build_rank_stability(
    candidates: pd.DataFrame,
    scenario_scores: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    scenario_names = list(config["scenarios"])
    rank_pivot = scenario_scores.pivot(
        index="candidate_id",
        columns="scenario",
        values="scenario_rank_average",
    )
    if rank_pivot[scenario_names].isna().any().any():
        raise PriorityScenarioError("일부 후보의 시나리오 순위가 누락되었습니다.")
    stability = candidates.loc[
        candidates["scenario_ranking_eligible"],
        [
            "candidate_id",
            *KEY,
            "performance_program_name",
            "priority_tier",
            "priority_reason",
            "account_original_budget",
            *COMPONENTS,
        ],
    ].copy()
    stability = stability.merge(
        rank_pivot[scenario_names].add_prefix("rank_").reset_index(),
        on="candidate_id",
        validate="one_to_one",
    )
    rank_columns = [f"rank_{name}" for name in scenario_names]
    stability["mean_scenario_rank"] = stability[rank_columns].mean(axis=1)
    stability["scenario_rank_std"] = stability[rank_columns].std(axis=1, ddof=0)
    stability["best_scenario_rank"] = stability[rank_columns].min(axis=1)
    stability["worst_scenario_rank"] = stability[rank_columns].max(axis=1)
    stability["scenario_rank_range"] = (
        stability["worst_scenario_rank"] - stability["best_scenario_rank"]
    )
    within_rank_pivot = scenario_scores.pivot(
        index="candidate_id",
        columns="scenario",
        values="scenario_rank_average_within_ministry",
    )
    stability = stability.merge(
        within_rank_pivot[scenario_names].add_prefix("rank_within_ministry_").reset_index(),
        on="candidate_id",
        validate="one_to_one",
    )
    within_rank_columns = [f"rank_within_ministry_{name}" for name in scenario_names]
    stability["mean_scenario_rank_within_ministry"] = stability[within_rank_columns].mean(axis=1)
    stability["scenario_rank_std_within_ministry"] = stability[within_rank_columns].std(
        axis=1, ddof=0
    )
    stability["best_scenario_rank_within_ministry"] = stability[within_rank_columns].min(axis=1)
    stability["worst_scenario_rank_within_ministry"] = stability[within_rank_columns].max(axis=1)
    stability["scenario_rank_range_within_ministry"] = (
        stability["worst_scenario_rank_within_ministry"]
        - stability["best_scenario_rank_within_ministry"]
    )
    for top_k in config["top_k"]:
        k = int(top_k)
        top_membership = (
            scenario_scores.assign(in_top_k=scenario_scores["scenario_rank_min"].le(k))
            .pivot(index="candidate_id", columns="scenario", values="in_top_k")[scenario_names]
            .sum(axis=1)
        )
        stability[f"top_{k}_scenario_count"] = (
            stability["candidate_id"].map(top_membership).astype("Int64")
        )
        stability[f"all_scenario_top_{k}"] = stability[f"top_{k}_scenario_count"].eq(
            len(scenario_names)
        )
        within_top_membership = (
            scenario_scores.assign(
                in_top_k=scenario_scores["scenario_rank_min_within_ministry"].le(k)
            )
            .pivot(index="candidate_id", columns="scenario", values="in_top_k")[scenario_names]
            .sum(axis=1)
        )
        stability[f"top_{k}_scenario_count_within_ministry"] = (
            stability["candidate_id"].map(within_top_membership).astype("Int64")
        )
        stability[f"all_scenario_top_{k}_within_ministry"] = stability[
            f"top_{k}_scenario_count_within_ministry"
        ].eq(len(scenario_names))
    stability = stability.sort_values(
        ["mean_scenario_rank", "scenario_rank_std", "account_original_budget"],
        ascending=[True, True, False],
    ).reset_index(drop=True)
    stability["exploratory_consensus_order"] = range(1, len(stability) + 1)
    return stability.convert_dtypes()


def build_spearman_table(
    scenario_scores: pd.DataFrame,
    scenario_names: list[str],
) -> pd.DataFrame:
    pivot = scenario_scores.pivot(
        index="candidate_id",
        columns="scenario",
        values="scenario_rank_average",
    )
    rows: list[dict[str, Any]] = []
    for left in scenario_names:
        for right in scenario_names:
            pair = pivot[[left, right]].dropna()
            rows.append(
                {
                    "scenario_left": left,
                    "scenario_right": right,
                    "candidate_count": len(pair),
                    "spearman_rank_correlation": (
                        1.0
                        if left == right
                        else float(pair[left].corr(pair[right], method="pearson"))
                    ),
                }
            )
    return pd.DataFrame(rows).convert_dtypes()


def build_top_k_overlap(
    scenario_scores: pd.DataFrame,
    scenario_names: list[str],
    top_k_values: list[int],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for top_k in top_k_values:
        sets = {
            scenario: set(
                scenario_scores.loc[
                    scenario_scores["scenario"].eq(scenario)
                    & scenario_scores["scenario_rank_min"].le(top_k),
                    "candidate_id",
                ]
            )
            for scenario in scenario_names
        }
        for left, right in combinations(scenario_names, 2):
            intersection = sets[left] & sets[right]
            union = sets[left] | sets[right]
            rows.append(
                {
                    "comparison_type": "PAIR",
                    "top_k": int(top_k),
                    "scenario_left": left,
                    "scenario_right": right,
                    "left_set_size_with_ties": len(sets[left]),
                    "right_set_size_with_ties": len(sets[right]),
                    "intersection_count": len(intersection),
                    "union_count": len(union),
                    "jaccard_overlap": len(intersection) / len(union) if union else 1.0,
                    "overlap_coefficient": (
                        len(intersection) / min(len(sets[left]), len(sets[right]))
                        if sets[left] and sets[right]
                        else 1.0
                    ),
                }
            )
        all_intersection = set.intersection(*(sets[name] for name in scenario_names))
        all_union = set.union(*(sets[name] for name in scenario_names))
        rows.append(
            {
                "comparison_type": "ALL_SCENARIOS",
                "top_k": int(top_k),
                "scenario_left": "ALL",
                "scenario_right": "ALL",
                "left_set_size_with_ties": min(len(value) for value in sets.values()),
                "right_set_size_with_ties": max(len(value) for value in sets.values()),
                "intersection_count": len(all_intersection),
                "union_count": len(all_union),
                "jaccard_overlap": (len(all_intersection) / len(all_union) if all_union else 1.0),
                "overlap_coefficient": (
                    len(all_intersection) / min(len(value) for value in sets.values())
                    if all(sets.values())
                    else 1.0
                ),
            }
        )
    return pd.DataFrame(rows).convert_dtypes()


def _set_korean_font() -> None:
    candidates = ["Malgun Gothic", "NanumGothic", "AppleGothic", "DejaVu Sans"]
    available = {font.name for font in plt.matplotlib.font_manager.fontManager.ttflist}
    for font in candidates:
        if font in available:
            plt.rcParams["font.family"] = font
            break
    plt.rcParams["axes.unicode_minus"] = False


def _plot_rank_range(stability: pd.DataFrame, output: Path) -> None:
    _set_korean_font()
    plot = stability.head(15).sort_values("mean_scenario_rank", ascending=False).copy()
    labels = (
        plot["ministry_code"].astype(str)
        + " · "
        + plot["fiscal_year"].astype(str)
        + " "
        + plot["performance_program_name"].astype(str)
        + " / "
        + plot["account_type"]
        .replace(
            {
                "GENERAL_ACCOUNT": "일반회계",
                "SPECIAL_ACCOUNT": "특별회계",
                "FUND": "기금",
            }
        )
        .astype(str)
    )
    fig, ax = plt.subplots(figsize=(12, 8))
    ax.hlines(
        y=range(len(plot)),
        xmin=plot["best_scenario_rank"],
        xmax=plot["worst_scenario_rank"],
        color="#9CA3AF",
        linewidth=2.5,
    )
    ax.scatter(
        plot["mean_scenario_rank"],
        range(len(plot)),
        s=58,
        color="#1F5A94",
        edgecolor="#17324D",
        linewidth=0.7,
        zorder=3,
        label="평균 시나리오 순위",
    )
    ax.set_yticks(range(len(plot)), labels)
    ax.set_xlabel("시나리오 순위 (낮을수록 상위)")
    ax.set_title(
        "점검 후보의 시나리오별 순위 범위",
        loc="left",
        pad=30,
        fontweight="bold",
    )
    ax.text(
        0,
        1.01,
        "2022~2024년 프로그램-연도-회계유형, 평균순위 상위 15개",
        transform=ax.transAxes,
        color="#4B5563",
    )
    ax.grid(axis="x", color="#E5E7EB", linewidth=0.8)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.legend(frameon=False, loc="lower right")
    fig.tight_layout()
    fig.savefig(output, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _plot_spearman_heatmap(
    spearman: pd.DataFrame,
    scenario_names: list[str],
    output: Path,
) -> None:
    _set_korean_font()
    matrix = spearman.pivot(
        index="scenario_left",
        columns="scenario_right",
        values="spearman_rank_correlation",
    ).loc[scenario_names, scenario_names]
    display_names = {
        "equal": "균등가중",
        "performance_focus": "성과중심",
        "execution_focus": "집행중심",
        "fiscal_impact_adjusted": "재정영향 보정",
    }
    labels = [display_names.get(name, name) for name in scenario_names]
    fig, ax = plt.subplots(figsize=(8.5, 7))
    image = ax.imshow(matrix.astype(float), cmap="Blues", vmin=0, vmax=1)
    for row in range(len(scenario_names)):
        for column in range(len(scenario_names)):
            value = float(matrix.iloc[row, column])
            ax.text(
                column,
                row,
                f"{value:.2f}",
                ha="center",
                va="center",
                color="white" if value >= 0.7 else "#17324D",
                fontweight="bold",
            )
    ax.set_xticks(range(len(scenario_names)), labels, rotation=25, ha="right")
    ax.set_yticks(range(len(scenario_names)), labels)
    ax.set_title(
        "점검 후보 시나리오 간 Spearman 순위상관",
        loc="left",
        pad=30,
        fontweight="bold",
    )
    ax.text(
        0,
        1.01,
        "시나리오 순위 적격 후보만 비교, 1에 가까울수록 순위가 유사",
        transform=ax.transAxes,
        color="#4B5563",
    )
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04, label="Spearman 상관계수")
    fig.tight_layout()
    fig.savefig(output, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _build_summary(
    candidates: pd.DataFrame,
    scenario_scores: pd.DataFrame,
    stability: pd.DataFrame,
    spearman: pd.DataFrame,
    top_k_overlap: pd.DataFrame,
    config: dict[str, Any],
    *,
    input_hashes: dict[str, str],
) -> dict[str, Any]:
    off_diagonal = spearman.loc[
        spearman["scenario_left"].ne(spearman["scenario_right"]),
        "spearman_rank_correlation",
    ]
    all_overlap = top_k_overlap.loc[top_k_overlap["comparison_type"].eq("ALL_SCENARIOS")]
    scenario_names = list(config["scenarios"])
    within_ministry: dict[str, Any] = {}
    for code, score_part in scenario_scores.groupby("ministry_code", sort=True):
        stability_part = stability.loc[stability["ministry_code"].eq(code)]
        pivot = score_part.pivot(
            index="candidate_id",
            columns="scenario",
            values="scenario_rank_average_within_ministry",
        )[scenario_names]
        correlations = [
            float(pivot[left].corr(pivot[right], method="pearson"))
            for left, right in combinations(scenario_names, 2)
        ]
        top_k_summary = {}
        for raw_top_k in config["top_k"]:
            top_k = int(raw_top_k)
            sets = {
                scenario: set(
                    score_part.loc[
                        score_part["scenario"].eq(scenario)
                        & score_part["scenario_rank_min_within_ministry"].le(top_k),
                        "candidate_id",
                    ]
                )
                for scenario in scenario_names
            }
            intersection = set.intersection(*(sets[name] for name in scenario_names))
            union = set.union(*(sets[name] for name in scenario_names))
            top_k_summary[str(top_k)] = {
                "intersection_count": len(intersection),
                "union_count": len(union),
                "jaccard_overlap": len(intersection) / len(union) if union else 1.0,
            }
        within_ministry[str(code)] = {
            "eligible_rows": len(stability_part),
            "minimum_off_diagonal_spearman": min(correlations),
            "maximum_off_diagonal_spearman": max(correlations),
            "rank_range_median": float(
                stability_part["scenario_rank_range_within_ministry"].median()
            ),
            "rank_range_max": float(stability_part["scenario_rank_range_within_ministry"].max()),
            "all_scenario_top_k": top_k_summary,
        }
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": config["scope"],
        "grain": "ministry x program x fiscal_year x account_type",
        "status": "exploratory_scenario_ranking_not_final_policy_priority",
        "counts": {
            "analysis_rows": len(candidates),
            "joint_analysis_rows": int(candidates["analysis_status"].eq("JOINT_ANALYSIS").sum()),
            "data_review_rows": int(candidates["priority_tier"].eq("DATA_REVIEW").sum()),
            "review_candidate_rows": int(candidates["review_candidate"].sum()),
            "scenario_ranking_eligible_rows": int(candidates["scenario_ranking_eligible"].sum()),
            "context_only_candidate_rows": int(candidates["context_only_candidate"].sum()),
            "information_rows": int(candidates["priority_tier"].eq("INFORMATION").sum()),
            "scenario_count": int(scenario_scores["scenario"].nunique()),
        },
        "stability": {
            "minimum_off_diagonal_spearman": float(off_diagonal.min()),
            "maximum_off_diagonal_spearman": float(off_diagonal.max()),
            "all_scenario_top_k": {
                str(int(row.top_k)): {
                    "intersection_count": int(row.intersection_count),
                    "intersection_unique_program_count": int(
                        stability.loc[
                            stability[f"all_scenario_top_{int(row.top_k)}"],
                            "program_code",
                        ].nunique()
                    ),
                    "union_count": int(row.union_count),
                    "jaccard_overlap": float(row.jaccard_overlap),
                }
                for row in all_overlap.itertuples()
            },
            "rank_range_median": float(stability["scenario_rank_range"].median()),
            "rank_range_max": float(stability["scenario_rank_range"].max()),
            "within_ministry": within_ministry,
        },
        "components": {
            "performance_gap": "below_target_count / comparable_rate_count",
            "execution_management": (
                "max(current execution severity, repeated low-execution budget share, "
                "0.5 x repeated year-end-concentration budget share)"
            ),
            "budget_performance_mismatch": (
                "max(performance gap x rapid-increase budget share, "
                "(1-performance gap) x rapid-decrease budget share)"
            ),
            "fiscal_impact": (
                "overall: within-year percentile; ministry view: within-ministry-year percentile"
            ),
        },
        "scenario_weights": config["scenarios"],
        "unavailable_components": ["performance_indicator_type"],
        "validation": {
            "analysis_key_unique": not candidates.loc[candidates[KEY].notna().all(axis=1)]
            .duplicated(KEY)
            .any(),
            "candidate_id_unique": not candidates["candidate_id"].duplicated().any(),
            "m3_signal_missing_rows": int(
                candidates["financial_signal_join_status"].ne("both").sum()
            ),
            "m3_account_budget_mismatch_rows": int(
                (
                    candidates["financial_signal_join_status"].eq("both")
                    & ~candidates["financial_signal_budget_reconciled"]
                ).sum()
            ),
            "joint_financial_signal_join_complete": bool(
                candidates.loc[
                    candidates["analysis_status"].eq("JOINT_ANALYSIS"),
                    "financial_signal_join_status",
                ]
                .eq("both")
                .all()
            ),
            "scenario_components_complete": not scenario_scores[list(COMPONENTS)]
            .isna()
            .any()
            .any(),
            "scenario_scores_between_zero_and_one": bool(
                scenario_scores["scenario_score"].between(0, 1).all()
            ),
            "missing_indicator_type_not_zero_scored": True,
            "fiscal_impact_alone_not_ranked": bool(
                candidates.loc[
                    candidates["scenario_ranking_eligible"],
                    [
                        "performance_signal",
                        "execution_signal",
                        "budget_mismatch_signal",
                    ],
                ]
                .any(axis=1)
                .all()
            ),
            "final_composite_score_generated": False,
            "final_overall_rank_generated": False,
            "policy_failure_label_generated": False,
        },
        "input_sha256": input_hashes,
        "interpretation_limits": [
            "성과지표 유형과 자율평가 의견은 현재 시나리오에 포함되지 않음",
            "시나리오 순위는 수기 성과 표본의 탐색 결과이며 최종 정책 우선순위가 아님",
            "프로그램 성과를 세부사업 성과로 귀속하지 않음",
            "사업규모는 위험 자체가 아니라 영향도 보정에만 사용",
            "동률을 보존하므로 상위 K 집합 크기는 K보다 클 수 있음",
        ],
    }


def run_priority_scenario_analysis(
    paths: PriorityScenarioPaths,
    *,
    overwrite: bool = False,
) -> PriorityScenarioResult:
    for source in (paths.same_year_analysis, paths.financial_features, paths.config):
        if not source.exists():
            raise FileNotFoundError(source)
    input_hashes = {
        str(source): _sha256(source)
        for source in (paths.same_year_analysis, paths.financial_features, paths.config)
    }
    config = load_scenario_config(paths.config)
    scope = config["scope"]
    analysis = pd.read_csv(
        paths.same_year_analysis,
        dtype={"ministry_code": "string", "program_code": "string"},
    )
    features = pd.read_parquet(paths.financial_features)
    ministry_codes = scope.get("ministry_codes")
    program_signals = aggregate_program_account_signals(
        features,
        ministry_code=(str(scope["ministry_code"]) if ministry_codes is None else None),
        ministry_codes=(
            tuple(str(code) for code in ministry_codes) if ministry_codes is not None else None
        ),
        start_year=int(scope["start_year"]),
        end_year=int(scope["end_year"]),
    )
    candidates = build_candidate_population(analysis, program_signals, config)
    scenario_scores = score_scenarios(candidates, config)
    scenario_names = list(config["scenarios"])
    stability = build_rank_stability(candidates, scenario_scores, config)
    drilldown, drilldown_summary = build_stable_top5_project_drilldown(
        candidates,
        stability,
        features,
    )
    spearman = build_spearman_table(scenario_scores, scenario_names)
    top_k_overlap = build_top_k_overlap(
        scenario_scores,
        scenario_names,
        [int(value) for value in config["top_k"]],
    )
    summary = _build_summary(
        candidates,
        scenario_scores,
        stability,
        spearman,
        top_k_overlap,
        config,
        input_hashes=input_hashes,
    )
    summary["drilldown"] = drilldown_summary
    if {
        str(source): _sha256(source)
        for source in (paths.same_year_analysis, paths.financial_features, paths.config)
    } != input_hashes:
        raise PriorityScenarioError("입력 파일이 실행 중 변경되었습니다.")

    paths.output_dir.mkdir(parents=True, exist_ok=True)
    paths.figure_dir.mkdir(parents=True, exist_ok=True)
    output_map = {
        "candidate_population.csv": candidates,
        "scenario_scores.csv": scenario_scores,
        "rank_stability.csv": stability,
        "stable_top5_project_drilldown.csv": drilldown,
        "scenario_spearman.csv": spearman,
        "top_k_overlap.csv": top_k_overlap,
    }
    output_paths = tuple(paths.output_dir / name for name in output_map)
    summary_path = paths.output_dir / "analysis_summary.json"
    rank_figure = paths.figure_dir / f"{paths.figure_prefix}_rank_range.png"
    spearman_figure = paths.figure_dir / f"{paths.figure_prefix}_spearman.png"
    targets = (*output_paths, summary_path, rank_figure, spearman_figure)
    existing = [path for path in targets if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "기존 산출물이 있습니다. --overwrite를 사용하세요: "
            + ", ".join(str(path) for path in existing)
        )
    for name, frame in output_map.items():
        frame.to_csv(paths.output_dir / name, index=False, encoding="utf-8-sig")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _plot_rank_range(stability, rank_figure)
    _plot_spearman_heatmap(spearman, scenario_names, spearman_figure)
    return PriorityScenarioResult(
        candidates=candidates,
        scenario_scores=scenario_scores,
        stability=stability,
        drilldown=drilldown,
        spearman=spearman,
        top_k_overlap=top_k_overlap,
        summary=summary,
        output_paths=(*output_paths, summary_path),
        figure_paths=(rank_figure, spearman_figure),
    )
