from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import yaml

from analytics.mss_same_year_budget_check import run_same_year_budget_check

PROGRAM_ID_KEY = ["ministry_code", "field_name", "sector_name", "program_code"]
KEY = [*PROGRAM_ID_KEY, "fiscal_year", "account_type"]
COMPONENTS = (
    "performance_gap",
    "execution_management",
    "budget_performance_mismatch",
    "fiscal_impact",
)
SIGNAL_SCORE_COMPONENTS = (
    "performance_gap",
    "execution_management",
    "budget_performance_mismatch",
)
SIGNAL_SCORE_METHOD = "complete_case_equal_mean_of_three_signal_components"
SIZE_ROLE_IN_WORK_QUEUE = "tiebreak_only"
ANALYSIS_VERSION = "review_workbench_v4_program_year_queue"
OUTPUT_SCHEMA_VERSION = "priority_review_outputs_v4_program_year_queue"
ANALYSIS_TIME_BASIS = "ANNUAL_RETROSPECTIVE_AFTER_REQUIRED_SOURCE_RELEASES"
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
REVIEW_INTENSITY_ORDER = {
    "DATA_FIRST": 0,
    "REPEATED_OR_MULTIPLE": 1,
    "STRONG_SINGLE": 2,
    "SINGLE_REVIEW": 3,
    "CONTEXT_REVIEW": 4,
    "MONITOR": 5,
}
WORK_LANE_ORDER = {name: order + 1 for name, order in REVIEW_INTENSITY_ORDER.items()}
REVIEW_GRADE_ORDER = {"H": 0, "A": 1, "B": 2, "C": 3, "D": 4}
QUESTION_REVIEW_FIELDS = (
    "review_grade",
    "reviewability_status",
    "diagnostic_type",
    "signal_families",
    "signal_strength",
    "context_type",
    "context_status",
    "context_source",
    "context_evidence",
    "context_effect",
    "grade_cap_reason",
    "grade_reason_codes",
    "next_review_question",
    "evidence_strength",
)


class PriorityScenarioError(ValueError):
    """점검 후보·시나리오 순위의 입력 또는 검증 조건이 깨졌을 때 발생합니다."""


@dataclass(frozen=True)
class PriorityScenarioPaths:
    same_year_analysis: Path
    financial_features: Path
    feedback_cohorts: Path
    program_financial: Path
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
            feedback_cohorts=root
            / "data/analytics/definition_validation/feedback_cohort_t1_t2.csv",
            program_financial=root / "data/processed/masters/program_year_financial.parquet",
            config=root / "configs/mss_priority_scenarios.yaml",
            output_dir=root / "data/analytics/mss_priority_scenarios",
            figure_dir=root / "artifacts/figures/presentation",
        )

    @classmethod
    def multi_ministry_from_root(cls, root: Path) -> PriorityScenarioPaths:
        return cls(
            same_year_analysis=root / "data/analytics/multi_ministry_same_year_budget_check/"
            "program_year_account_type_check.csv",
            financial_features=root / "data/analytics/m3/financial_signal_features.parquet",
            feedback_cohorts=root
            / "data/analytics/definition_validation/feedback_cohort_t1_t2.csv",
            program_financial=root / "data/processed/masters/program_year_financial.parquet",
            config=root / "configs/priority_scenarios.yaml",
            output_dir=root / "data/analytics/multi_ministry_priority_scenarios",
            figure_dir=root / "artifacts/figures/presentation",
            figure_prefix="multi_ministry_priority_scenario",
        )


@dataclass(frozen=True)
class PriorityScenarioResult:
    candidates: pd.DataFrame
    work_queue: pd.DataFrame
    program_year_review_queue: pd.DataFrame
    scenario_scores: pd.DataFrame
    stability: pd.DataFrame
    drilldown: pd.DataFrame
    project_review_queue: pd.DataFrame
    review_workbench_queue: pd.DataFrame
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


def _checked_git(root: Path, *args: str) -> str:
    boundary = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.strip()
    if Path(boundary).resolve() != root.resolve():
        raise PriorityScenarioError(f"Git 저장소 경계가 다릅니다: {boundary}")
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.strip()


def _git_provenance(root: Path) -> dict[str, Any]:
    return {
        "commit_sha": _checked_git(root, "rev-parse", "HEAD"),
        "worktree_dirty": bool(_checked_git(root, "status", "--porcelain")),
    }


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
            "account_type_classified",
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
    source["account_type"] = source["account_type_classified"].astype("string")
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


def aggregate_program_feedback(
    cohorts: pd.DataFrame,
    features: pd.DataFrame,
    *,
    ministry_codes: tuple[str, ...],
    start_year: int,
    end_year: int,
) -> pd.DataFrame:
    """T+1·T+2 연속 사업 예산을 프로그램×회계유형별로 따로 집계합니다."""
    _require_columns(
        cohorts,
        {
            "feedback_horizon",
            "base_fiscal_year",
            "base_project_id",
            "ministry_code",
            "cohort_eligible",
            "base_original_budget_amount",
            "outcome_original_budget_amount",
        },
        "T+1·T+2 코호트",
    )
    _require_columns(
        features,
        {
            "project_id",
            "ministry_code",
            "field_name",
            "sector_name",
            "program_code",
            "fiscal_year",
            "account_type_classified",
        },
        "M3 재정 신호 feature",
    )
    project_keys = features[
        [
            "project_id",
            "ministry_code",
            "field_name",
            "sector_name",
            "program_code",
            "fiscal_year",
            "account_type_classified",
        ]
    ].copy()
    project_keys["ministry_code"] = project_keys["ministry_code"].astype("string").str.zfill(3)
    project_keys["program_code"] = project_keys["program_code"].astype("string")
    cohort_ministry = cohorts["ministry_code"].astype("string").str.zfill(3)
    source = cohorts.loc[
        cohorts["cohort_eligible"].fillna(False)
        & cohorts["feedback_horizon"].isin(["T+1", "T+2"])
        & cohorts["base_fiscal_year"].between(start_year, end_year)
        & cohort_ministry.isin(ministry_codes),
        [
            "feedback_horizon",
            "base_fiscal_year",
            "base_project_id",
            "base_original_budget_amount",
            "outcome_original_budget_amount",
        ],
    ].copy()
    source = source.merge(
        project_keys,
        left_on="base_project_id",
        right_on="project_id",
        how="left",
        validate="many_to_one",
        indicator=True,
    )
    eligible_rows = len(source)
    unmatched_rows = int(source["_merge"].ne("both").sum())
    source = source.loc[source["_merge"].eq("both")].drop(columns="_merge").copy()
    source["account_type"] = source["account_type_classified"].astype("string")
    grouped = (
        source.groupby([*KEY, "feedback_horizon"], dropna=False)
        .agg(
            feedback_project_count=("base_project_id", "size"),
            feedback_base_budget=("base_original_budget_amount", "sum"),
            feedback_outcome_budget=("outcome_original_budget_amount", "sum"),
        )
        .reset_index()
    )
    grouped["feedback_budget_change_rate"] = (
        grouped["feedback_outcome_budget"] - grouped["feedback_base_budget"]
    ).div(grouped["feedback_base_budget"].where(grouped["feedback_base_budget"].ne(0)))
    wide = grouped.pivot(index=KEY, columns="feedback_horizon").reset_index()
    wide.columns = [
        "_".join(str(part) for part in column if part).lower().replace("+", "")
        if isinstance(column, tuple)
        else str(column)
        for column in wide.columns
    ]
    result = wide.convert_dtypes()
    if result.duplicated(KEY).any():
        raise PriorityScenarioError("프로그램 T+1·T+2 환류 키가 중복되었습니다.")
    result.attrs["linkage"] = {
        "eligible_rows": eligible_rows,
        "matched_rows": len(source),
        "unmatched_base_project_rows": unmatched_rows,
    }
    return result


def _single_account_type(value: Any) -> str | None:
    if pd.isna(value):
        return None
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return None
    return str(parsed[0]) if isinstance(parsed, list) and len(parsed) == 1 else None


def _direction(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    result = pd.Series(pd.NA, index=numeric.index, dtype="Int64")
    result.loc[numeric.eq(0)] = 0
    result.loc[numeric.gt(0)] = 1
    result.loc[numeric.lt(0)] = -1
    return result


def add_program_total_feedback(
    candidates: pd.DataFrame,
    program_financial: pd.DataFrame,
) -> pd.DataFrame:
    """프로그램 전체 본예산과 연속 관측 세부사업 소계의 T+1·T+2를 분리합니다."""
    candidate_required = {
        "ministry_code",
        "field_name",
        "sector_name",
        "program_code",
        "financial_program_name",
        "fiscal_year",
        "account_type",
    }
    financial_required = {
        "ministry_code",
        "field_name",
        "sector_name",
        "program_code",
        "program_name",
        "fiscal_year",
        "program_total_original_budget",
        "program_analysis_original_budget",
        "account_type_count",
        "account_types",
    }
    _require_columns(candidates, candidate_required, "점검 후보")
    _require_columns(program_financial, financial_required, "프로그램 재정")

    result = candidates.copy()
    generated_prefixes = (
        "program_total_base_budget_",
        "program_total_outcome_budget_",
        "program_analysis_base_budget_",
        "program_analysis_outcome_budget_",
        "program_account_type_count_",
        "program_outcome_account_type_count_",
        "program_account_types_",
        "program_outcome_account_types_",
        "program_total_feedback_complete_",
        "program_total_budget_change_rate_",
        "program_total_account_type_mismatch_",
        "analysis_scope_budget_share_",
        "budget_feedback_basis_",
        "budget_direction_reconciled_",
    )
    generated = [
        column
        for column in result
        if column == "program_name"
        or column == "budget_direction_reconciled"
        or column.startswith(generated_prefixes)
    ]
    result = result.drop(columns=generated)
    result["ministry_code"] = result["ministry_code"].astype("string").str.zfill(3)
    result["program_code"] = result["program_code"].astype("string")
    result["fiscal_year"] = pd.to_numeric(result["fiscal_year"], errors="raise").astype(int)
    result["program_name"] = result["financial_program_name"].astype("string")

    keys = [
        "ministry_code",
        "field_name",
        "sector_name",
        "program_code",
        "program_name",
        "fiscal_year",
    ]
    value_columns = [
        "program_total_original_budget",
        "program_analysis_original_budget",
        "account_type_count",
        "account_types",
    ]
    totals = program_financial[[*keys, *value_columns]].copy()
    totals["ministry_code"] = totals["ministry_code"].astype("string").str.zfill(3)
    totals["program_code"] = totals["program_code"].astype("string")
    totals["fiscal_year"] = pd.to_numeric(totals["fiscal_year"], errors="raise").astype(int)
    if totals.duplicated(keys).any():
        raise PriorityScenarioError("프로그램 전체금액 키가 중복되었습니다.")

    for horizon, offset in (("t1", 1), ("t2", 2)):
        base = totals.rename(
            columns={
                "program_total_original_budget": f"program_total_base_budget_{horizon}",
                "program_analysis_original_budget": f"program_analysis_base_budget_{horizon}",
                "account_type_count": f"program_account_type_count_{horizon}",
                "account_types": f"program_account_types_{horizon}",
            }
        )
        outcome = totals.copy()
        outcome["fiscal_year"] = outcome["fiscal_year"] - offset
        outcome = outcome.rename(
            columns={
                "program_total_original_budget": f"program_total_outcome_budget_{horizon}",
                "program_analysis_original_budget": f"program_analysis_outcome_budget_{horizon}",
                "account_type_count": f"program_outcome_account_type_count_{horizon}",
                "account_types": f"program_outcome_account_types_{horizon}",
            }
        )
        result = result.merge(base, on=keys, how="left", validate="many_to_one")
        result = result.merge(outcome, on=keys, how="left", validate="many_to_one")

        base_budget = pd.to_numeric(result[f"program_total_base_budget_{horizon}"], errors="coerce")
        outcome_budget = pd.to_numeric(
            result[f"program_total_outcome_budget_{horizon}"], errors="coerce"
        )
        base_type = result[f"program_account_types_{horizon}"].map(_single_account_type)
        outcome_type = result[f"program_outcome_account_types_{horizon}"].map(_single_account_type)
        same_account = (
            base_type.eq(result["account_type"].astype("string"))
            & outcome_type.eq(result["account_type"].astype("string"))
            & base_type.eq(outcome_type)
        )
        complete = (
            result[f"program_account_type_count_{horizon}"].eq(1)
            & result[f"program_outcome_account_type_count_{horizon}"].eq(1)
            & same_account
            & base_budget.notna()
            & outcome_budget.notna()
            & base_budget.ne(0)
        )
        single_account_pair = (
            result[f"program_account_type_count_{horizon}"].eq(1)
            & result[f"program_outcome_account_type_count_{horizon}"].eq(1)
            & base_budget.notna()
            & outcome_budget.notna()
        )
        result[f"program_total_account_type_mismatch_{horizon}"] = (
            single_account_pair & ~same_account
        )
        result[f"program_total_feedback_complete_{horizon}"] = complete
        result[f"program_total_budget_change_rate_{horizon}"] = (outcome_budget - base_budget).div(
            base_budget.where(base_budget.ne(0))
        )
        result.loc[
            ~complete,
            f"program_total_budget_change_rate_{horizon}",
        ] = pd.NA
        result[f"analysis_scope_budget_share_{horizon}"] = pd.to_numeric(
            result[f"program_analysis_base_budget_{horizon}"], errors="coerce"
        ).div(base_budget.where(base_budget.ne(0)))
        result[f"budget_feedback_basis_{horizon}"] = "UNAVAILABLE_MIXED_OR_UNLINKED"
        result.loc[
            result[f"program_total_account_type_mismatch_{horizon}"],
            f"budget_feedback_basis_{horizon}",
        ] = "DATA_REVIEW_ACCOUNT_TYPE_MISMATCH"
        result.loc[complete, f"budget_feedback_basis_{horizon}"] = "PROGRAM_TOTAL_SINGLE_ACCOUNT"

        subset_change = result.get(
            f"feedback_budget_change_rate_{horizon}",
            pd.Series(pd.NA, index=result.index),
        )
        subset_complete = result.get(
            f"feedback_budget_complete_{horizon}",
            pd.Series(False, index=result.index),
        )
        result[f"budget_direction_reconciled_{horizon}"] = (
            complete
            & pd.Series(subset_complete, index=result.index).fillna(False).astype(bool)
            & _direction(subset_change).eq(
                _direction(result[f"program_total_budget_change_rate_{horizon}"])
            )
        )

    result["budget_direction_reconciled"] = result["budget_direction_reconciled_t1"]
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
        {
            "candidate_id",
            "all_scenario_top_5",
            "all_scenario_top_5_within_ministry",
        },
        "순위 안정성표",
    )
    _require_columns(
        features,
        {
            *KEY,
            "account_type_classified",
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
    stable_flags = stability.loc[
        stability["all_scenario_top_5"].fillna(False)
        | stability["all_scenario_top_5_within_ministry"].fillna(False),
        [
            "candidate_id",
            "all_scenario_top_5",
            "all_scenario_top_5_within_ministry",
        ],
    ]
    stable = candidates.loc[
        candidates["candidate_id"].isin(stable_flags["candidate_id"]),
        [
            "candidate_id",
            *KEY,
            "performance_program_name",
            "priority_reason",
            "account_original_budget",
            "account_current_budget",
            "account_settlement_expenditure",
        ],
    ].merge(stable_flags, on="candidate_id", validate="one_to_one")
    stable["drilldown_selection_scope"] = "WITHIN_MINISTRY"
    stable.loc[stable["all_scenario_top_5"], "drilldown_selection_scope"] = "OVERALL"
    stable.loc[
        stable["all_scenario_top_5"] & stable["all_scenario_top_5_within_ministry"],
        "drilldown_selection_scope",
    ] = "OVERALL_AND_WITHIN_MINISTRY"
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
    source["account_type"] = features["account_type_classified"].astype("string")
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
    drilldown["program_level_reported_target_context_signal"] = drilldown[
        "priority_reason"
    ].str.contains("PERFORMANCE_BELOW_TARGET", na=False)
    drilldown["program_level_priority_reason_context"] = drilldown["priority_reason"]
    drilldown["program_context_grain"] = "PROGRAM_YEAR_ACCOUNT"
    drilldown["program_context_disclaimer"] = "PROGRAM_LEVEL_REFERENCE_NOT_PROJECT_PERFORMANCE"
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
        "program_level_priority_reason_context",
        "all_scenario_top_5",
        "all_scenario_top_5_within_ministry",
        "drilldown_selection_scope",
        "program_level_reported_target_context_signal",
        "program_context_grain",
        "program_context_disclaimer",
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
        "overall_stable_top5_candidate_count": int(
            result.loc[result["all_scenario_top_5"], "candidate_id"].nunique()
        ),
        "within_ministry_stable_top5_candidate_count": int(
            result.loc[
                result["all_scenario_top_5_within_ministry"],
                "candidate_id",
            ].nunique()
        ),
        "unique_program_count": len(result[PROGRAM_ID_KEY].drop_duplicates()),
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


def validate_candidate_work_queue_integrity(
    candidates: pd.DataFrame,
    work_queue: pd.DataFrame,
) -> dict[str, Any]:
    """후보별 불변키·금액이 업무대기열에서 이동하거나 증식하지 않았는지 검증합니다."""
    amount_columns = [
        "account_original_budget",
        "account_current_budget",
        "account_settlement_expenditure",
    ]
    immutable_columns = [
        *KEY,
        "performance_program_name",
        "analysis_status",
        "priority_reason",
        "signal_score",
        "signal_score_status",
        "review_intensity",
        *QUESTION_REVIEW_FIELDS,
        *amount_columns,
    ]
    required = {"candidate_id", *immutable_columns}
    _require_columns(candidates, required, "후보표")
    _require_columns(work_queue, required, "전체 업무대기열")
    if (
        candidates["candidate_id"].duplicated().any()
        or work_queue["candidate_id"].duplicated().any()
    ):
        raise PriorityScenarioError("후보 또는 업무대기열 candidate_id가 중복되었습니다.")

    audit = candidates[["candidate_id", *immutable_columns]].merge(
        work_queue[["candidate_id", *immutable_columns]],
        on="candidate_id",
        how="outer",
        suffixes=("_before", "_after"),
        indicator=True,
        validate="one_to_one",
    )
    anti_join = audit["_merge"].value_counts().to_dict()
    if anti_join.get("left_only", 0) or anti_join.get("right_only", 0):
        raise PriorityScenarioError(f"후보-업무대기열 anti-join이 발생했습니다: {anti_join}")

    diff_counts: dict[str, int] = {}
    for column in immutable_columns:
        before = audit[f"{column}_before"]
        after = audit[f"{column}_after"]
        both_missing = before.isna() & after.isna()
        if column in amount_columns or column == "signal_score":
            tolerance = 0.5 if column in amount_columns else 1e-12
            equal = (
                pd.to_numeric(before, errors="coerce")
                .sub(pd.to_numeric(after, errors="coerce"))
                .abs()
                .le(tolerance)
            )
        else:
            equal = before.eq(after)
        diff_counts[column] = int((~(both_missing | equal.fillna(False))).sum())
    changed = {column: count for column, count in diff_counts.items() if count}
    if changed:
        raise PriorityScenarioError(f"업무대기열 불변 필드가 변경되었습니다: {changed}")

    group_diffs: dict[str, int] = {}
    for column in amount_columns:
        before = candidates.groupby(KEY, dropna=False)[column].sum(min_count=1).sort_index()
        after = work_queue.groupby(KEY, dropna=False)[column].sum(min_count=1).sort_index()
        group_diffs[column] = int(before.sub(after).abs().gt(0.5).sum())
    if any(group_diffs.values()):
        raise PriorityScenarioError(f"프로그램-연도-회계 금액이 변경되었습니다: {group_diffs}")

    return {
        "candidate_rows_before": len(candidates),
        "candidate_rows_after": len(work_queue),
        "candidate_id_cardinality": "one_to_one",
        "candidate_id_left_only": int(anti_join.get("left_only", 0)),
        "candidate_id_right_only": int(anti_join.get("right_only", 0)),
        "immutable_field_diff_counts": diff_counts,
        "program_year_account_amount_diff_counts": group_diffs,
        "intended_added_fields": sorted(set(work_queue.columns) - set(candidates.columns)),
    }


def build_full_population_review_work_queue(
    candidates: pd.DataFrame,
    stability: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """모든 후보를 점검 업무레인과 레인 내부 순서에 빠짐없이 배정합니다."""
    if set(QUESTION_REVIEW_FIELDS) - set(candidates.columns):
        candidates = apply_question_review_grades(candidates)
    _require_columns(
        candidates,
        {
            "candidate_id",
            "ministry_code",
            "analysis_status",
            "scenario_ranking_eligible",
            "data_validation_signal",
            "context_only_candidate",
            "context_signal_family_count",
            "account_original_budget",
            "signal_score",
        },
        "후보표",
    )
    rank_columns = [
        "candidate_id",
        "mean_scenario_rank",
        "scenario_rank_range",
        "mean_scenario_rank_within_ministry",
        "scenario_rank_range_within_ministry",
        "exploratory_consensus_order",
        "all_scenario_top_5",
        "all_scenario_top_5_within_ministry",
    ]
    _require_columns(stability, set(rank_columns), "순위 안정성표")
    result = candidates.merge(
        stability[rank_columns],
        on="candidate_id",
        how="left",
        validate="one_to_one",
    )
    _require_columns(
        result,
        {
            "review_intensity",
            "repeated_signal_family_count",
            "independent_signal_family_count",
            "evidence_status",
            "next_action",
        },
        "독립 신호 후보표",
    )
    result["work_lane"] = result["review_intensity"]

    resolved = result["analysis_status"].isin(
        {
            "EXTERNAL_MINISTRY_FINANCIAL_PROGRAM",
            "STRUCTURAL_PROGRAM_DELETED_TRANSFERRED",
        }
    )
    result["work_item_status"] = "READY_FOR_REVIEW"
    result.loc[result["work_lane"].eq("DATA_FIRST"), "work_item_status"] = (
        "PENDING_DATA_VERIFICATION"
    )
    result.loc[result["work_lane"].eq("MONITOR"), "work_item_status"] = "MONITOR"
    result.loc[resolved, "work_item_status"] = "RESOLVED_CONTEXT"
    result["work_lane_order"] = result["work_lane"].map(WORK_LANE_ORDER)
    result["work_lane_interpretation"] = result["work_lane"].map(
        {
            "DATA_FIRST": "DATA_OR_LINKAGE_REVIEW_REQUIRED",
            "REPEATED_OR_MULTIPLE": "REPEATED_OR_MULTIPLE_INDEPENDENT_SIGNALS",
            "STRONG_SINGLE": "STRONG_SINGLE_INDEPENDENT_SIGNAL",
            "SINGLE_REVIEW": "SINGLE_INDEPENDENT_SIGNAL",
            "CONTEXT_REVIEW": "CONTEXT_SIGNAL_ONLY",
            "MONITOR": "NO_CURRENT_TRIGGER_DETECTED_NOT_SAFE_CONCLUSION",
        }
    )
    result.loc[resolved, "work_lane_interpretation"] = "RESOLVED_STRUCTURAL_CONTEXT"
    result["safety_conclusion"] = "NOT_ASSESSED"
    result["work_queue_role"] = "REVIEW_WORKFLOW_ORDER_NOT_POLICY_EFFECTIVENESS_RANK"

    budget = pd.to_numeric(result["account_original_budget"], errors="coerce").fillna(0)
    signal_score = pd.to_numeric(result["signal_score"], errors="coerce")
    result["_resolved_order"] = resolved.astype(int)
    result["_repeat_order"] = -pd.to_numeric(
        result["repeated_signal_family_count"], errors="coerce"
    ).fillna(0)
    result["_signal_order"] = -pd.to_numeric(
        result["independent_signal_family_count"], errors="coerce"
    ).fillna(0)
    result["_evidence_order"] = (
        result["evidence_status"].map({"CONFIRMED": 0, "LIMITED": 1, "DATA_BLOCKED": 2}).fillna(3)
    )
    # 규모는 신호 강도 다음의 동률 정리만. 가중합 점수로 쓰지 않음.
    result["_signal_score_missing_order"] = signal_score.isna().astype(int)
    result["_signal_score_order"] = -signal_score.fillna(0)
    result["_budget_order"] = -budget

    lane_sort_keys = [
        "work_lane_order",
        "_repeat_order",
        "_signal_order",
        "_evidence_order",
        "_signal_score_missing_order",
        "_signal_score_order",
        "_budget_order",
        "candidate_id",
    ]
    result = result.sort_values(lane_sort_keys, ignore_index=True)
    result["work_lane_rank_overall"] = result.groupby("work_lane").cumcount() + 1
    ministry_order = result.sort_values(
        [
            "ministry_code",
            *lane_sort_keys,
        ]
    )
    result["work_lane_rank_within_ministry"] = (
        ministry_order.groupby(["ministry_code", "work_lane"])
        .cumcount()
        .add(1)
        .reindex(result.index)
    )
    overall_order = result.sort_values(
        [
            "_resolved_order",
            "work_lane_order",
            "work_lane_rank_overall",
            "candidate_id",
        ]
    )
    result["work_queue_order"] = pd.Series(
        range(1, len(result) + 1),
        index=overall_order.index,
    ).reindex(result.index)
    ministry_queue_order = result.sort_values(
        [
            "ministry_code",
            "_resolved_order",
            "work_lane_order",
            "work_lane_rank_within_ministry",
            "candidate_id",
        ]
    )
    result["work_queue_order_within_ministry"] = (
        ministry_queue_order.groupby("ministry_code").cumcount().add(1).reindex(result.index)
    )
    strength_order = {
        "STRONG": 0,
        "MODERATE": 1,
        "AMBIGUOUS": 2,
        "NONE": 3,
        "NOT_ASSESSED": 4,
    }
    result["_grade_strength_order"] = result["signal_strength"].map(strength_order).fillna(5)
    result["_grade_family_order"] = (
        -result["signal_families"]
        .astype("string")
        .map(lambda value: 0 if value in {"NONE", "<NA>"} else len(str(value).split(";")))
    )
    grade_order = result.sort_values(
        [
            "review_grade_order",
            "_grade_strength_order",
            "_grade_family_order",
            "_evidence_order",
            "_budget_order",
            "candidate_id",
        ]
    )
    result["grade_queue_order"] = pd.Series(
        range(1, len(result) + 1), index=grade_order.index
    ).reindex(result.index)
    result["grade_queue_rank_within_grade"] = (
        grade_order.groupby("review_grade").cumcount().add(1).reindex(result.index)
    )
    ministry_grade_order = result.sort_values(
        [
            "ministry_code",
            "review_grade_order",
            "_grade_strength_order",
            "_grade_family_order",
            "_evidence_order",
            "_budget_order",
            "candidate_id",
        ]
    )
    result["grade_queue_order_within_ministry"] = (
        ministry_grade_order.groupby("ministry_code").cumcount().add(1).reindex(result.index)
    )
    result = result.sort_values("work_queue_order", ignore_index=True)
    result = result.drop(
        columns=[
            "_resolved_order",
            "_repeat_order",
            "_signal_order",
            "_evidence_order",
            "_signal_score_missing_order",
            "_signal_score_order",
            "_budget_order",
            "_grade_strength_order",
            "_grade_family_order",
        ]
    ).convert_dtypes()

    if len(result) != len(candidates) or set(result["candidate_id"]) != set(
        candidates["candidate_id"]
    ):
        raise PriorityScenarioError("전체 업무대기열에서 후보행이 누락되거나 추가되었습니다.")
    if result["work_queue_order"].nunique() != len(result):
        raise PriorityScenarioError("전체 업무대기열 순서가 중복되었습니다.")
    if (
        not result.loc[
            result["scenario_ranking_eligible"],
            "mean_scenario_rank",
        ]
        .notna()
        .all()
    ):
        raise PriorityScenarioError(
            "기존 시나리오 적격 후보의 순위가 업무대기열에서 누락되었습니다."
        )
    lane_counts = result["work_lane"].value_counts()
    if not set(lane_counts.index).issubset(WORK_LANE_ORDER):
        raise PriorityScenarioError("전체 업무대기열에 정의되지 않은 레인이 있습니다.")

    source_budget = pd.to_numeric(candidates["account_original_budget"], errors="coerce").sum()
    result_budget = pd.to_numeric(result["account_original_budget"], errors="coerce").sum()
    if abs(float(source_budget - result_budget)) > 0.5:
        raise PriorityScenarioError("전체 업무대기열에서 본예산 합계가 보존되지 않았습니다.")
    key_integrity = validate_candidate_work_queue_integrity(candidates, result)
    grade_counts = result["review_grade"].value_counts()
    grade_budget = result.groupby("review_grade", dropna=False)["account_original_budget"].sum()
    lane_grade = pd.crosstab(result["work_lane"], result["review_grade"])
    reason_counts = result["grade_reason_codes"].value_counts()
    abnormal = (
        (result["work_lane"].eq("REPEATED_OR_MULTIPLE") & result["review_grade"].eq("D"))
        | (result["work_lane"].eq("MONITOR") & result["review_grade"].eq("A"))
        | (result["work_lane"].eq("DATA_FIRST") & result["review_grade"].isin(["A", "B"]))
    )
    summary = {
        "candidate_count": len(result),
        "candidate_coverage_rate": len(result) / len(candidates),
        "lane_counts": {str(key): int(value) for key, value in lane_counts.items()},
        "lane_original_budget": {
            str(key): float(value)
            for key, value in result.groupby("work_lane")["account_original_budget"].sum().items()
        },
        "signal_score_status_counts": {
            str(key): int(value)
            for key, value in result["signal_score_status"].value_counts().items()
        },
        "resolved_context_count": int(result["work_item_status"].eq("RESOLVED_CONTEXT").sum()),
        "scenario_ranking_rows_preserved": int(
            result["scenario_ranking_eligible"].fillna(False).sum()
        ),
        "work_queue_order_unique": True,
        "original_budget_reconciled": True,
        "key_integrity": key_integrity,
        "question_review_grade": {
            "grade_counts_all_412": {str(key): int(value) for key, value in grade_counts.items()},
            "grade_counts_reviewable_a_to_d": {
                str(key): int(value)
                for key, value in grade_counts.loc[grade_counts.index != "H"].items()
            },
            "grade_original_budget": {
                str(key): float(value) for key, value in grade_budget.items()
            },
            "legacy_lane_to_grade": {
                str(lane): {str(grade): int(count) for grade, count in row.items() if count}
                for lane, row in lane_grade.to_dict(orient="index").items()
            },
            "grade_reason_counts": {str(key): int(value) for key, value in reason_counts.items()},
            "qa_abnormal_transition_count": int(abnormal.sum()),
            "qa_abnormal_candidate_ids": result.loc[abnormal, "candidate_id"].astype(str).tolist(),
            "h_excluded_from_a_to_d_denominator": True,
            "grade_is_program_review_order_not_policy_evaluation": True,
        },
        "safety_conclusion_generated": False,
        "final_policy_rank_generated": False,
        "signal_size_separation": {
            "signal_score_method": SIGNAL_SCORE_METHOD,
            "signal_score_components": list(SIGNAL_SCORE_COMPONENTS),
            "fiscal_impact_in_signal_score": False,
            "size_role": SIZE_ROLE_IN_WORK_QUEUE,
            "within_lane_order": [
                "repeated_signal_family_count_desc",
                "independent_signal_family_count_desc",
                "evidence_status",
                "complete_case_signal_score_desc",
                "account_original_budget_desc_tiebreak_only",
                "candidate_id",
            ],
            "grade_queue_order": [
                "review_grade_H_hold_then_A_B_C_D",
                "signal_strength",
                "signal_family_count",
                "evidence_strength",
                "account_original_budget_desc_tiebreak_only",
                "candidate_id",
            ],
            "legacy_work_queue_order_preserved": True,
        },
    }
    return result, summary


def build_current_execution_threshold_qa(
    candidates: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    """현재연도 집행 임계값만 바꾼 비생산 QA 전환표를 만듭니다."""
    variants = config.get("question_review", {}).get("current_execution_threshold_qa", [])
    rows: list[pd.DataFrame] = []
    for variant in variants:
        strong = float(variant["execution_strong"])
        moderate = float(variant["execution_moderate"])
        if not 0 <= strong < moderate <= 1:
            raise PriorityScenarioError(
                "질문형 등급 QA 집행 임계값의 순서 또는 범위가 잘못되었습니다."
            )
        changed = candidates.copy()
        changed["current_execution_severity"] = _current_execution_severity(
            changed["account_execution_rate"], strong=strong, moderate=moderate
        )
        changed = apply_question_review_grades(changed)
        transition = pd.DataFrame(
            {
                "qa_variant": str(variant["name"]),
                "baseline_review_grade": candidates["review_grade"],
                "qa_review_grade": changed["review_grade"],
                "account_original_budget": pd.to_numeric(
                    candidates["account_original_budget"], errors="coerce"
                ),
            }
        )
        rows.append(
            transition.groupby(
                ["qa_variant", "baseline_review_grade", "qa_review_grade"],
                dropna=False,
            )
            .agg(
                candidate_count=("account_original_budget", "size"),
                account_original_budget=("account_original_budget", "sum"),
            )
            .reset_index()
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "qa_variant",
                "baseline_review_grade",
                "qa_review_grade",
                "candidate_count",
                "account_original_budget",
            ]
        )
    return pd.concat(rows, ignore_index=True).convert_dtypes()


def build_blind_review_pilot(work_queue: pd.DataFrame, pair_count: int = 10) -> pd.DataFrame:
    """등급을 숨긴 결정론적 경계 사례 쌍을 만듭니다. 정확도 검증 표본은 아닙니다."""
    boundaries = [("A", "B"), ("B", "C"), ("C", "D"), ("H", "A"), ("B", "C")]
    pools = {
        grade: part.sort_values("candidate_id").reset_index(drop=True)
        for grade, part in work_queue.groupby("review_grade")
    }
    cursors = {grade: 0 for grade in pools}
    rows: list[dict[str, Any]] = []
    for pair_index in range(pair_count):
        left_grade, right_grade = boundaries[pair_index % len(boundaries)]
        if left_grade not in pools or right_grade not in pools:
            continue
        selected = []
        for grade in (left_grade, right_grade):
            pool = pools[grade]
            row = pool.iloc[cursors[grade] % len(pool)]
            cursors[grade] += 1
            selected.append(row)
        for side, row in zip(("LEFT", "RIGHT"), selected, strict=True):
            candidate_id = str(row["candidate_id"])
            rows.append(
                {
                    "pair_id": f"PAIR_{pair_index + 1:02d}",
                    "case_side": side,
                    "anonymous_case_id": hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[
                        :12
                    ],
                    "ministry_code": row.get("ministry_code"),
                    "fiscal_year": row.get("fiscal_year"),
                    "account_type": row.get("account_type"),
                    "performance_program_name": row.get("performance_program_name"),
                    "account_execution_rate": row.get("account_execution_rate"),
                    "reported_target_status": row.get("reported_target_status"),
                    "reported_target_miss_consecutive": row.get("reported_target_miss_consecutive"),
                    "repeated_low_execution_observed": bool(
                        pd.to_numeric(
                            pd.Series([row.get("type_repeated_strong_low_execution_budget_share")]),
                            errors="coerce",
                        )
                        .fillna(0)
                        .iloc[0]
                        > 0
                        or pd.to_numeric(
                            pd.Series(
                                [row.get("type_repeated_moderate_low_execution_budget_share")]
                            ),
                            errors="coerce",
                        )
                        .fillna(0)
                        .iloc[0]
                        > 0
                    ),
                    "same_year_rapid_budget_increase": row.get("budget_increase_context_signal"),
                    "evidence_strength": row.get("evidence_strength"),
                    "reviewer_first_case": pd.NA,
                    "reviewer_reason": pd.NA,
                }
            )
    result = pd.DataFrame(rows).convert_dtypes()
    if result["pair_id"].nunique() != pair_count or len(result) != pair_count * 2:
        raise PriorityScenarioError("블라인드 쌍대비교 파일럿 10쌍을 구성하지 못했습니다.")
    return result


def summarize_retrospective_feedback_by_grade(work_queue: pd.DataFrame) -> list[dict[str, Any]]:
    """현재 등급에 사용하지 않은 T+1·T+2 결과를 회고용으로만 요약합니다."""
    rows: list[dict[str, Any]] = []
    for grade, part in work_queue.groupby("review_grade"):
        for horizon in ("t1", "t2"):
            rows.append(
                {
                    "review_grade": str(grade),
                    "feedback_horizon": horizon.upper(),
                    "eligible_count": int(
                        part[f"program_total_feedback_complete_{horizon}"].fillna(False).sum()
                    ),
                    "reported_miss_then_budget_increase_count": int(
                        part[f"low_performance_budget_increase_{horizon}"].fillna(False).sum()
                    ),
                    "reported_target_met_then_budget_decrease_count": int(
                        part[f"good_performance_budget_decrease_{horizon}"].fillna(False).sum()
                    ),
                }
            )
    return rows


def build_project_review_work_queue(
    candidates: pd.DataFrame,
    work_queue: pd.DataFrame,
    features: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """데이터 검증 레인을 제외한 모든 후보의 세부사업 검토순서를 연결합니다."""
    _require_columns(candidates, {"candidate_id", "data_validation_signal"}, "후보표")
    work_columns = [
        "candidate_id",
        "work_lane",
        "work_item_status",
        "work_queue_order",
        "work_queue_order_within_ministry",
        "mean_scenario_rank",
        "scenario_rank_range",
        "mean_scenario_rank_within_ministry",
        "scenario_rank_range_within_ministry",
        "exploratory_consensus_order",
        "all_scenario_top_5",
        "all_scenario_top_5_within_ministry",
        "review_intensity",
        "review_intensity_order",
        "next_action",
        "evidence_status",
        "independent_signal_family_count",
        "repeated_signal_family_count",
        "execution_review_signal",
        "review_grade",
        "diagnostic_type",
        "next_review_question",
        "context_type",
        "context_status",
        "context_effect",
        "grade_queue_order",
    ]
    _require_columns(work_queue, set(work_columns), "전체 업무대기열")
    reviewable_ids = candidates.loc[
        ~candidates["data_validation_signal"].fillna(False),
        ["candidate_id"],
    ]
    selection = reviewable_ids.assign(
        all_scenario_top_5=False,
        all_scenario_top_5_within_ministry=True,
    )
    queue, validation = build_stable_top5_project_drilldown(candidates, selection, features)
    queue = queue.drop(columns=["all_scenario_top_5", "all_scenario_top_5_within_ministry"])
    queue = queue.merge(work_queue[work_columns], on="candidate_id", validate="many_to_one")
    queue = queue.rename(
        columns={
            "review_grade": "program_level_review_grade_context",
            "diagnostic_type": "program_level_diagnostic_type_context",
            "next_review_question": "program_level_next_review_question_context",
            "context_type": "program_level_context_type",
            "context_status": "program_level_context_status",
            "context_effect": "program_level_context_effect",
            "grade_queue_order": "program_level_grade_queue_order",
        }
    )
    for column in ("all_scenario_top_5", "all_scenario_top_5_within_ministry"):
        queue[column] = queue[column].fillna(False)
    queue["drilldown_selection_scope"] = "FULL_POPULATION_REVIEWABLE"

    signals = queue["project_financial_signal_types"].astype("string").fillna("NONE")
    data_review = signals.str.contains(
        "DATA_VALIDATION_PRIORITY|DENOMINATOR_OR_MATCHING_REVIEW"
    ) | queue["financial_quality_level"].eq("RESTRICTED")
    project_signal = signals.str.contains("REPEATED_|BUDGET_RAPID_|ACCOUNTING_ADJUSTMENT_PATTERN")
    program_context = signals.str.contains(
        "PROGRAM_BUDGET_CONCENTRATION|MULTIPLE_FINANCIAL_SIGNALS"
    )
    queue["project_review_group"] = "LARGE_BUDGET_CONTEXT"
    queue.loc[program_context, "project_review_group"] = "PROGRAM_STRUCTURE_CONTEXT"
    queue.loc[project_signal, "project_review_group"] = "PROJECT_FINANCIAL_SIGNAL"
    queue.loc[data_review, "project_review_group"] = "DATA_VALIDATION_FIRST"
    group_order = {
        "DATA_VALIDATION_FIRST": 0,
        "PROJECT_FINANCIAL_SIGNAL": 1,
        "PROGRAM_STRUCTURE_CONTEXT": 2,
        "LARGE_BUDGET_CONTEXT": 3,
    }
    queue["_project_review_group_order"] = queue["project_review_group"].map(group_order)
    queue = queue.sort_values(
        [
            "candidate_id",
            "_project_review_group_order",
            "budget_rank_within_candidate",
            "project_id",
        ]
    )
    queue["project_review_order_within_candidate"] = queue.groupby("candidate_id").cumcount() + 1
    queue = queue.sort_values(
        [
            "work_queue_order",
            "project_review_order_within_candidate",
            "project_id",
        ],
        ignore_index=True,
    )
    queue["review_sequence_overall"] = range(1, len(queue) + 1)
    ministry_order = queue.sort_values(
        [
            "ministry_code",
            "work_queue_order_within_ministry",
            "project_review_order_within_candidate",
            "project_id",
        ]
    )
    queue["review_sequence_within_ministry"] = (
        ministry_order.groupby("ministry_code").cumcount().add(1).reindex(queue.index)
    )
    queue = queue.drop(columns="_project_review_group_order").convert_dtypes()

    reviewable = candidates.loc[~candidates["data_validation_signal"].fillna(False)]
    blocked = candidates.loc[candidates["data_validation_signal"].fillna(False)]
    source_budget = pd.to_numeric(candidates["account_original_budget"], errors="coerce")
    reviewable_budget = pd.to_numeric(reviewable["account_original_budget"], errors="coerce")
    blocked_budget = pd.to_numeric(blocked["account_original_budget"], errors="coerce")
    summary = {
        "source_candidate_count": len(candidates),
        "reviewable_candidate_count": len(reviewable),
        "data_verification_blocked_candidate_count": len(blocked),
        "reviewable_candidate_coverage_rate": queue["candidate_id"].nunique() / len(reviewable),
        "unique_program_count": len(queue[PROGRAM_ID_KEY].drop_duplicates()),
        "project_row_count": len(queue),
        "project_review_group_counts": {
            str(key): int(value)
            for key, value in queue["project_review_group"].value_counts().items()
        },
        "ministry_candidate_counts": {
            str(key): int(value)
            for key, value in queue.groupby("ministry_code")["candidate_id"].nunique().items()
        },
        "ministry_project_row_counts": {
            str(key): int(value) for key, value in queue["ministry_code"].value_counts().items()
        },
        "source_original_budget": float(source_budget.sum()),
        "reviewable_original_budget": float(reviewable_budget.sum()),
        "data_verification_blocked_original_budget": float(blocked_budget.sum()),
        "reviewable_original_budget_share": float(reviewable_budget.sum() / source_budget.sum()),
        "project_original_budget": float(queue["project_original_budget"].sum()),
        "project_current_budget": float(queue["project_current_budget"].sum()),
        "project_expenditure": float(queue["project_expenditure"].sum()),
        "other_ministry_row_count": validation["other_ministry_row_count"],
        "candidate_project_key_unique": validation["candidate_project_key_unique"],
        "original_budget_reconciled": validation["original_budget_reconciled"],
        "current_budget_reconciled": validation["current_budget_reconciled"],
        "expenditure_reconciled": validation["expenditure_reconciled"],
        "project_performance_attribution_count": validation[
            "project_performance_attribution_count"
        ],
        "safety_conclusion_generated": False,
        "final_policy_rank_generated": False,
    }
    return queue, summary


def build_review_workbench_queue(
    work_queue: pd.DataFrame,
    project_queue: pd.DataFrame,
) -> pd.DataFrame:
    """프로그램 데이터 작업과 세부사업 검토를 한 업무대기열로 연결합니다."""
    program_tasks = work_queue.loc[work_queue["review_item_type"].eq("PROGRAM_DATA_TASK")].copy()
    program_tasks["work_item_id"] = "DATA:" + program_tasks["candidate_id"].astype(str)
    program_tasks["project_id"] = pd.NA
    program_tasks["project_name"] = pd.NA
    program_tasks["work_item_budget"] = program_tasks["account_original_budget"]
    program_tasks["review_sequence_overall"] = pd.NA
    program_tasks["program_context_grain"] = "PROGRAM_YEAR_ACCOUNT"
    program_tasks["program_context_disclaimer"] = pd.NA
    program_tasks["program_level_priority_reason_context"] = pd.NA
    program_tasks["program_level_reported_target_context_signal"] = pd.NA
    program_tasks["program_level_review_grade_context"] = program_tasks["review_grade"]
    program_tasks["program_level_diagnostic_type_context"] = program_tasks["diagnostic_type"]
    program_tasks["program_level_next_review_question_context"] = program_tasks[
        "next_review_question"
    ]
    program_tasks["program_level_context_type"] = program_tasks["context_type"]
    program_tasks["program_level_context_status"] = program_tasks["context_status"]
    program_tasks["program_level_context_effect"] = program_tasks["context_effect"]
    program_tasks["program_level_grade_queue_order"] = program_tasks["grade_queue_order"]
    program_tasks["project_performance_attributed"] = pd.NA

    project_tasks = project_queue.copy()
    project_tasks["review_item_type"] = "DETAILED_PROJECT_REVIEW"
    project_tasks["work_item_id"] = (
        "PROJECT:"
        + project_tasks["candidate_id"].astype(str)
        + ":"
        + project_tasks["project_id"].astype(str)
    )
    project_tasks["work_item_budget"] = project_tasks["project_original_budget"]

    columns = [
        "work_item_id",
        "review_item_type",
        "candidate_id",
        "ministry_code",
        "fiscal_year",
        "account_type",
        "performance_program_name",
        "project_id",
        "project_name",
        "review_intensity",
        "review_intensity_order",
        "next_action",
        "evidence_status",
        "independent_signal_family_count",
        "repeated_signal_family_count",
        "performance_signal",
        "execution_review_signal",
        "low_performance_budget_increase_t1",
        "low_performance_budget_increase_t2",
        "good_performance_budget_decrease_t1",
        "good_performance_budget_decrease_t2",
        "program_level_priority_reason_context",
        "program_level_reported_target_context_signal",
        "program_level_review_grade_context",
        "program_level_diagnostic_type_context",
        "program_level_next_review_question_context",
        "program_level_context_type",
        "program_level_context_status",
        "program_level_context_effect",
        "program_level_grade_queue_order",
        "program_context_grain",
        "program_context_disclaimer",
        "project_performance_attributed",
        "work_queue_order",
        "work_queue_order_within_ministry",
        "review_sequence_overall",
        "work_item_budget",
    ]
    result = pd.concat(
        [program_tasks.reindex(columns=columns), project_tasks.reindex(columns=columns)],
        ignore_index=True,
    )
    result["_project_order"] = pd.to_numeric(
        result["review_sequence_overall"], errors="coerce"
    ).fillna(0)
    result = result.sort_values(
        ["review_intensity_order", "work_queue_order", "_project_order", "work_item_id"],
        ignore_index=True,
    ).drop(columns="_project_order")
    result["workbench_order"] = range(1, len(result) + 1)
    if result["work_item_id"].duplicated().any():
        raise PriorityScenarioError("통합 점검대기열의 업무 ID가 중복되었습니다.")
    if len(program_tasks) + len(project_tasks) != len(result):
        raise PriorityScenarioError("통합 점검대기열에서 업무행이 누락되었습니다.")
    return result.convert_dtypes()


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


def attach_reported_target_history(candidates: pd.DataFrame) -> pd.DataFrame:
    """프로그램-연도 성과 상태를 중복 제거한 뒤 과거 방향으로만 반복 여부를 붙입니다."""
    _require_columns(
        candidates,
        {*PROGRAM_ID_KEY, "fiscal_year", "below_target_count", "comparable_rate_count"},
        "성과 반복 입력",
    )
    result = candidates.copy()
    valid_key = result[PROGRAM_ID_KEY].notna().all(axis=1)
    result["_history_fiscal_year"] = pd.to_numeric(result["fiscal_year"], errors="coerce")
    source = result.loc[
        valid_key,
        [
            *PROGRAM_ID_KEY,
            "_history_fiscal_year",
            "below_target_count",
            "comparable_rate_count",
        ],
    ].copy()
    source["below_target_count"] = pd.to_numeric(source["below_target_count"], errors="coerce")
    source["comparable_rate_count"] = pd.to_numeric(
        source["comparable_rate_count"], errors="coerce"
    )
    year_key = [*PROGRAM_ID_KEY, "_history_fiscal_year"]
    inconsistent = source.groupby(year_key, dropna=False)[
        ["below_target_count", "comparable_rate_count"]
    ].nunique(dropna=False)
    if inconsistent.gt(1).any(axis=None):
        raise PriorityScenarioError(
            "회계유형별로 복제된 프로그램-연도 성과 상태가 일치하지 않습니다."
        )
    history = source.drop_duplicates(year_key).sort_values(year_key)
    history["_target_miss"] = history["comparable_rate_count"].gt(0) & history[
        "below_target_count"
    ].gt(0)
    history["_target_met"] = history["comparable_rate_count"].gt(0) & history[
        "below_target_count"
    ].eq(0)
    grouped = history.groupby(PROGRAM_ID_KEY, dropna=False, sort=False)
    previous_year = grouped["_history_fiscal_year"].shift()
    consecutive = history["_history_fiscal_year"].sub(previous_year).eq(1)
    history["reported_target_miss_consecutive"] = (
        history["_target_miss"] & grouped["_target_miss"].shift(fill_value=False) & consecutive
    )
    history["reported_target_met_consecutive"] = (
        history["_target_met"] & grouped["_target_met"].shift(fill_value=False) & consecutive
    )
    history["reported_target_history_status"] = "LEFT_CENSORED_OR_FIRST_OBSERVATION"
    history.loc[previous_year.notna() & ~consecutive, "reported_target_history_status"] = (
        "NON_CONSECUTIVE_GAP"
    )
    history.loc[consecutive, "reported_target_history_status"] = "CONSECUTIVE_PRIOR_YEAR"
    attach = history[
        [
            *year_key,
            "reported_target_miss_consecutive",
            "reported_target_met_consecutive",
            "reported_target_history_status",
        ]
    ]
    before = len(result)
    result = result.merge(attach, on=year_key, how="left", validate="many_to_one")
    if len(result) != before:
        raise PriorityScenarioError("성과 반복 이력 결합에서 후보행이 증식했습니다.")
    result.loc[~valid_key, "reported_target_miss_consecutive"] = False
    result.loc[~valid_key, "reported_target_met_consecutive"] = False
    result.loc[~valid_key, "reported_target_history_status"] = "PROGRAM_KEY_INCOMPLETE"
    return result.drop(columns="_history_fiscal_year").convert_dtypes()


def _bool_column(frame: pd.DataFrame, name: str) -> pd.Series:
    if name not in frame:
        return pd.Series(False, index=frame.index, dtype="boolean")
    return frame[name].fillna(False).astype(bool)


def apply_question_review_grades(candidates: pd.DataFrame) -> pd.DataFrame:
    """기존 신호를 정책평가가 아닌 질문형 원문 검토순서로 변환합니다."""
    result = candidates.copy()
    index = result.index

    def numeric(name: str) -> pd.Series:
        if name not in result:
            return pd.Series(pd.NA, index=index, dtype="Float64")
        return pd.to_numeric(result[name], errors="coerce")

    data_blocked = _bool_column(result, "data_validation_signal")
    current_severity = numeric("current_execution_severity")
    current_execution = current_severity.fillna(0).gt(0)
    repeated_low_execution = (
        numeric("type_repeated_strong_low_execution_budget_share").fillna(0).gt(0)
        | numeric("type_repeated_moderate_low_execution_budget_share").fillna(0).gt(0)
        | _bool_column(result, "repeated_low_execution_signal")
    )
    performance_miss = _bool_column(result, "performance_signal")
    repeated_performance_miss = _bool_column(result, "reported_target_miss_consecutive")
    rapid_budget_increase = _bool_column(result, "budget_increase_context_signal")
    budget_mismatch = _bool_column(result, "budget_mismatch_signal")
    accounting_context = _bool_column(result, "accounting_context_signal")
    structure_context = _bool_column(result, "structure_context_signal")
    rapid_budget_decrease = _bool_column(result, "budget_decrease_context_signal")
    repeated_year_end = numeric("type_repeated_year_end_concentration_budget_share").fillna(0).gt(0)
    execution_signal = current_execution | repeated_low_execution
    comparable = numeric("comparable_rate_count")
    performance_missing = (
        comparable.isna() | comparable.le(0)
        if "comparable_rate_count" in result
        else pd.Series(False, index=index, dtype="boolean")
    )
    target_status = result.get(
        "reported_target_status", pd.Series(pd.NA, index=index, dtype="string")
    ).astype("string")
    target_met = target_status.isin({"AT_OR_ABOVE", "ALL_COMPARABLE_AT_OR_ABOVE_TARGET"}) | (
        comparable.gt(0) & numeric("below_target_count").fillna(0).eq(0)
    )
    target_adequacy = _bool_column(result, "repeated_target_overachievement") & _bool_column(
        result, "target_unchanged"
    )

    if "context_type" not in result:
        result["context_type"] = "UNKNOWN_TYPE"
    if "context_status" not in result:
        result["context_status"] = "CONFIRMED_STRUCTURED"
    if "context_source" not in result:
        result["context_source"] = "STRUCTURED_CONTEXT_INVENTORY"
    if "context_evidence" not in result:
        result["context_evidence"] = "NO_CONFIRMED_CONTEXT_TAG"
    if "context_effect" not in result:
        result["context_effect"] = "NO_GRADE_CHANGE"
    result.loc[repeated_year_end, "context_type"] = "YEAR_END_CONCENTRATED"
    result.loc[repeated_year_end, "context_status"] = "PATTERN_CANDIDATE"
    result.loc[repeated_year_end, "context_source"] = "M3_MONTHLY_PATTERN"
    result.loc[repeated_year_end, "context_evidence"] = "REPEATED_YEAR_END_CONCENTRATION_PATTERN"
    result.loc[repeated_year_end, "context_effect"] = "DISPLAY_ONLY"
    confirmed_multiyear = result["context_type"].eq("MULTIYEAR_CAPITAL") & result[
        "context_status"
    ].isin({"CONFIRMED_STRUCTURED", "HUMAN_CONFIRMED"})

    key_incomplete = (
        result[PROGRAM_ID_KEY].isna().any(axis=1) if set(PROGRAM_ID_KEY) <= set(result) else False
    )
    hold = data_blocked | (performance_missing & ~execution_signal) | key_incomplete
    low_execution_target_met = execution_signal & target_met & ~performance_miss
    low_execution_performance_missing = execution_signal & performance_missing & ~data_blocked
    multiyear_relaxation = (
        confirmed_multiyear
        & current_execution
        & ~repeated_low_execution
        & ~performance_miss
        & ~rapid_budget_increase
    )
    special_c = ~hold & (
        low_execution_target_met | low_execution_performance_missing | multiyear_relaxation
    )
    repeated_execution_with_miss = repeated_low_execution & performance_miss
    repeated_miss_with_budget_increase = repeated_performance_miss & rapid_budget_increase
    explicit_a = (
        ~hold & ~special_c & (repeated_execution_with_miss | repeated_miss_with_budget_increase)
    )
    two_domains = performance_miss & execution_signal
    strong_or_repeated_single = (
        current_severity.fillna(0).ge(1) | repeated_low_execution | repeated_performance_miss
    )
    grade_b = ~hold & ~special_c & ~explicit_a & (two_domains | strong_or_repeated_single)
    general_context = (
        performance_miss
        | execution_signal
        | budget_mismatch
        | rapid_budget_increase
        | rapid_budget_decrease
        | accounting_context
        | structure_context
        | repeated_year_end
        | target_adequacy
    )
    grade_c = ~hold & ~special_c & ~explicit_a & ~grade_b & general_context

    result["review_grade"] = "D"
    result.loc[grade_c | special_c, "review_grade"] = "C"
    result.loc[grade_b, "review_grade"] = "B"
    result.loc[explicit_a, "review_grade"] = "A"
    result.loc[hold, "review_grade"] = "H"
    result["reviewability_status"] = "REVIEWABLE"
    result.loc[result["review_grade"].eq("C"), "reviewability_status"] = "LIMITED"
    result.loc[hold, "reviewability_status"] = "HOLD"
    result["signal_strength"] = "NONE"
    result.loc[result["review_grade"].eq("C"), "signal_strength"] = "AMBIGUOUS"
    result.loc[result["review_grade"].eq("B"), "signal_strength"] = "MODERATE"
    result.loc[result["review_grade"].eq("A"), "signal_strength"] = "STRONG"
    result.loc[hold, "signal_strength"] = "NOT_ASSESSED"
    result["diagnostic_type"] = "NO_STRUCTURED_SIGNAL_DETECTED"
    result.loc[grade_c, "diagnostic_type"] = "CONTEXT_OR_SINGLE_SIGNAL_REVIEW"
    result.loc[grade_b, "diagnostic_type"] = "STRONG_OR_REPEATED_SINGLE_SIGNAL"
    result.loc[repeated_execution_with_miss & explicit_a, "diagnostic_type"] = (
        "REPEATED_LOW_EXECUTION_WITH_REPORTED_TARGET_MISS"
    )
    result.loc[repeated_miss_with_budget_increase & explicit_a, "diagnostic_type"] = (
        "REPEATED_REPORTED_TARGET_MISS_WITH_BUDGET_INCREASE"
    )
    result.loc[low_execution_target_met & special_c, "diagnostic_type"] = "LOW_EXECUTION_TARGET_MET"
    result.loc[low_execution_performance_missing & special_c, "diagnostic_type"] = (
        "LOW_EXECUTION_PERFORMANCE_INFORMATION_MISSING"
    )
    result.loc[multiyear_relaxation & special_c, "diagnostic_type"] = (
        "MULTIYEAR_CONTEXT_WITH_SINGLE_YEAR_LOW_EXECUTION"
    )
    result.loc[target_adequacy & grade_c, "diagnostic_type"] = "TARGET_ADEQUACY_REVIEW"
    result.loc[hold, "diagnostic_type"] = "DATA_OR_COMPARABILITY_HOLD"

    families: list[str] = []
    for row_index in index:
        active: list[str] = []
        if bool(data_blocked.loc[row_index]) or bool(hold.loc[row_index]):
            active.append("data_quality")
        if bool(execution_signal.loc[row_index]):
            active.append("execution")
        if bool(performance_miss.loc[row_index]):
            active.append("reported_performance")
        if bool(budget_mismatch.loc[row_index]) or bool(
            repeated_miss_with_budget_increase.loc[row_index]
        ):
            active.append("budget_performance_mismatch")
        if bool(target_adequacy.loc[row_index]):
            active.append("target_or_trend")
        families.append(";".join(active) or "NONE")
    result["signal_families"] = families
    result["grade_cap_reason"] = "NOT_APPLICABLE"
    result.loc[low_execution_target_met & special_c, "grade_cap_reason"] = (
        "LOW_EXECUTION_WITH_REPORTED_TARGET_MET"
    )
    result.loc[low_execution_performance_missing & special_c, "grade_cap_reason"] = (
        "PERFORMANCE_INFORMATION_MISSING"
    )
    result.loc[multiyear_relaxation & special_c, "grade_cap_reason"] = "CONFIRMED_MULTIYEAR_CONTEXT"
    result.loc[multiyear_relaxation & special_c, "context_effect"] = "GRADE_RELAXED_TO_C"
    result["grade_reason_codes"] = result["diagnostic_type"]
    result["next_review_question"] = "현재 구조화 신호가 없다는 판단의 입력 범위가 충분한가?"
    result.loc[grade_c, "next_review_question"] = (
        "원문에 이 신호의 예외 사유나 비교가능성 제한을 설명하는 근거가 있는가?"
    )
    result.loc[grade_b, "next_review_question"] = (
        "반복 또는 강한 단일 신호를 설명하는 공식 근거와 지표 변경이 있는가?"
    )
    result.loc[explicit_a, "next_review_question"] = (
        "겹친 관측 사실이 같은 사업 범위에서 발생했는지 원문과 연도별 근거로 확인할 수 있는가?"
    )
    result.loc[low_execution_target_met & special_c, "next_review_question"] = (
        "집행률 분모와 성과지표 비교가능성을 확인한 뒤, 원문에 목표 적정성·수요 변화·비용 절감·측정 시차를 설명하는 근거가 있는가?"
    )
    result.loc[low_execution_performance_missing & special_c, "next_review_question"] = (
        "성과정보가 없는 이유와 집행률 분모를 원문에서 확인할 수 있는가?"
    )
    result.loc[multiyear_relaxation & special_c, "next_review_question"] = (
        "다년도 일정상 해당 연도 집행 수준이 계획된 단계와 일치하는가?"
    )
    result.loc[target_adequacy & grade_c, "next_review_question"] = (
        "반복 초과달성이 목표 난이도 또는 지표 정의 변경 없이 관측됐는가?"
    )
    result.loc[hold, "next_review_question"] = (
        "프로그램 연결키·금액 단위·성과 비교가능성을 먼저 확정할 수 있는가?"
    )
    result["evidence_strength"] = "STRONG"
    limited = result.get("evidence_status", pd.Series("CONFIRMED", index=index)).astype(
        "string"
    ).eq("LIMITED") | result.get("indicator_coverage_status", pd.Series("", index=index)).astype(
        "string"
    ).str.startswith("PARTIAL")
    result.loc[limited | special_c, "evidence_strength"] = "LIMITED"
    result.loc[hold, "evidence_strength"] = "BLOCKED"
    result["review_grade_order"] = result["review_grade"].map(REVIEW_GRADE_ORDER)
    if result["review_grade"].isna().any() or not set(result["review_grade"]).issubset(
        REVIEW_GRADE_ORDER
    ):
        raise PriorityScenarioError(
            "질문형 점검등급이 모든 후보에 상호배타적으로 배정되지 않았습니다."
        )
    return result.convert_dtypes()


def _program_year_group_map(candidates: pd.DataFrame) -> pd.DataFrame:
    """원시 회계행에 충돌을 숨기지 않는 프로그램-연도 ID를 붙입니다."""
    required = {
        "candidate_id",
        "ministry_code",
        "fiscal_year",
        "program_code",
        "field_name",
        "sector_name",
        "performance_program_name",
    }
    _require_columns(candidates, required, "프로그램-연도 집계 입력")
    result = candidates.copy()
    base_key = ["ministry_code", "fiscal_year", "program_code"]
    metadata = ["field_name", "sector_name", "performance_program_name"]
    conflict = result.groupby(base_key, dropna=False)[metadata].transform(
        lambda values: values.nunique(dropna=False)
    ).gt(1).any(axis=1)
    result["base_program_year_key_conflict"] = conflict

    def token(value: object) -> str:
        return "<NA>" if pd.isna(value) else str(value).strip()

    def stable_suffix(values: list[object]) -> str:
        raw = "|".join(token(value) for value in values)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]

    identities: list[str] = []
    year_ids: list[str] = []
    for row in result.itertuples(index=False):
        ministry = token(row.ministry_code)
        year = token(row.fiscal_year)
        code = token(row.program_code)
        if code != "<NA>":
            identity = f"{ministry}:{code}"
            if bool(row.base_program_year_key_conflict):
                identity += ":" + stable_suffix([row.field_name, row.sector_name])
        else:
            identity = f"{ministry}:UNKNOWN_CONTINUITY:" + stable_suffix(
                [year, row.field_name, row.sector_name, row.performance_program_name]
            )
        identities.append(identity)
        year_ids.append(f"{identity}:{year}")
    result["program_identity_id"] = identities
    result["program_year_id"] = year_ids

    name_conflict = result.groupby("program_year_id", dropna=False)[
        "performance_program_name"
    ].transform(lambda values: values.nunique(dropna=False)).gt(1)
    if name_conflict.any():
        result.loc[name_conflict, "program_identity_id"] += result.loc[name_conflict].apply(
            lambda row: ":" + stable_suffix([row["performance_program_name"]]), axis=1
        )
        result.loc[name_conflict, "program_year_id"] = (
            result.loc[name_conflict, "program_identity_id"]
            + ":"
            + result.loc[name_conflict, "fiscal_year"].astype("string")
        )
    result["program_year_name_conflict"] = name_conflict
    return result


def build_program_year_review_queue(
    account_queue: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """회계유형 원시행을 보존하면서 최종 프로그램-연도 대기열을 만듭니다."""
    required = {
        "candidate_id",
        *KEY,
        "performance_program_name",
        "account_original_budget",
        "account_current_budget",
        "account_settlement_expenditure",
        "below_target_count",
        "comparable_rate_count",
        "reported_target_status",
        "data_validation_signal",
        "analysis_status",
    }
    _require_columns(account_queue, required, "회계유형 감사 대기열")
    source = _program_year_group_map(account_queue)
    source["_fiscal_year_numeric"] = pd.to_numeric(source["fiscal_year"], errors="coerce")
    if source["_fiscal_year_numeric"].isna().any():
        raise PriorityScenarioError("프로그램-연도 집계 입력의 회계연도가 숫자가 아닙니다.")

    amount_columns = {
        "program_original_budget": "account_original_budget",
        "program_current_budget": "account_current_budget",
        "program_expenditure": "account_settlement_expenditure",
    }
    performance_columns = [
        "below_target_count",
        "at_or_above_target_count",
        "comparable_rate_count",
        "reported_target_status",
        "indicator_coverage_status",
        "repeated_target_overachievement",
        "target_unchanged",
    ]
    context_columns = [
        "context_type",
        "context_status",
        "context_source",
        "context_evidence",
        "context_effect",
    ]
    weighted_signal_columns = [
        "type_repeated_year_end_concentration_budget_share",
        "type_accounting_adjustment_pattern_budget_share",
        "type_program_budget_concentration_budget_share",
    ]
    rows: list[dict[str, Any]] = []
    for program_year_id, part in source.groupby("program_year_id", sort=True, dropna=False):
        part = part.sort_values("candidate_id")
        first = part.iloc[0]
        row: dict[str, Any] = {
            "program_year_id": program_year_id,
            "program_identity_id": first["program_identity_id"],
            "ministry_code": first["ministry_code"],
            "fiscal_year": int(first["_fiscal_year_numeric"]),
            "program_code": first["program_code"],
            "field_name": first["field_name"],
            "sector_name": first["sector_name"],
            "performance_program_name": first["performance_program_name"],
            "raw_account_row_count": len(part),
            "account_type_count": int(part["account_type"].nunique(dropna=False)),
            "account_types": ";".join(
                sorted(part["account_type"].fillna("NOT_AVAILABLE").astype(str).unique())
            ),
            "raw_candidate_ids": json.dumps(part["candidate_id"].tolist(), ensure_ascii=False),
            "base_program_year_key_conflict": bool(
                part["base_program_year_key_conflict"].any()
            ),
            "program_year_name_conflict": bool(part["program_year_name_conflict"].any()),
        }
        missing_amount = False
        for output, raw in amount_columns.items():
            values = pd.to_numeric(part[raw], errors="coerce")
            row[output] = values.sum(min_count=1)
            missing_amount |= values.isna().any()

        performance_conflicts: list[str] = []
        for column in performance_columns:
            if column not in part:
                row[column] = pd.NA
                continue
            if part[column].nunique(dropna=False) > 1:
                performance_conflicts.append(column)
                row[column] = pd.NA
            else:
                row[column] = part[column].iloc[0]
        row["performance_status_conflict_fields"] = ";".join(performance_conflicts)
        row["program_performance_status_conflict"] = bool(performance_conflicts)
        for column in context_columns:
            if column in part and part[column].nunique(dropna=False) == 1:
                row[column] = part[column].iloc[0]

        weights = pd.to_numeric(part["account_original_budget"], errors="coerce")
        for column in weighted_signal_columns:
            values = pd.to_numeric(part.get(column), errors="coerce")
            valid = values.notna() & weights.notna()
            denominator = weights.loc[valid].sum()
            row[column] = (
                float((values.loc[valid] * weights.loc[valid]).sum() / denominator)
                if valid.any() and denominator > 0
                else pd.NA
            )
        row["account_type_signal_details"] = json.dumps(
            [
                {
                    "candidate_id": item.candidate_id,
                    "account_type": (
                        "NOT_AVAILABLE" if pd.isna(item.account_type) else str(item.account_type)
                    ),
                    "review_grade": item.review_grade,
                    "diagnostic_type": item.diagnostic_type,
                    "execution_rate": (
                        None
                        if pd.isna(item.account_execution_rate)
                        else float(item.account_execution_rate)
                    ),
                }
                for item in part.itertuples()
            ],
            ensure_ascii=False,
        )
        row["evidence_status"] = (
            "DATA_BLOCKED"
            if part["data_validation_signal"].fillna(False).astype(bool).any()
            else (
                "LIMITED"
                if "evidence_status" in part
                and part["evidence_status"].astype("string").eq("LIMITED").any()
                else "CONFIRMED"
            )
        )
        row["data_validation_signal"] = bool(
            part["data_validation_signal"].fillna(False).astype(bool).any()
            or part["analysis_status"].astype("string").ne("JOINT_ANALYSIS").any()
            or row["base_program_year_key_conflict"]
            or row["program_year_name_conflict"]
            or row["program_performance_status_conflict"]
            or pd.isna(row["program_code"])
            or missing_amount
        )
        row["analysis_status"] = (
            "DATA_QUALITY_HOLD" if row["data_validation_signal"] else "PROGRAM_YEAR_REVIEW"
        )
        rows.append(row)

    result = pd.DataFrame(rows)
    result["program_execution_rate"] = pd.to_numeric(
        result["program_expenditure"], errors="coerce"
    ).div(pd.to_numeric(result["program_current_budget"], errors="coerce").where(lambda s: s.gt(0)))
    thresholds = config["thresholds"]
    result["current_execution_severity"] = _current_execution_severity(
        result["program_execution_rate"],
        strong=float(thresholds["execution_strong"]),
        moderate=float(thresholds["execution_moderate"]),
    )
    comparable = pd.to_numeric(result["comparable_rate_count"], errors="coerce")
    result["performance_gap"] = pd.to_numeric(
        result["below_target_count"], errors="coerce"
    ).div(comparable.where(comparable.gt(0)))
    result["performance_signal"] = result["performance_gap"].fillna(0).gt(0)

    result = result.sort_values(["program_identity_id", "fiscal_year", "program_year_id"])
    history = result.groupby("program_identity_id", sort=False, dropna=False)
    previous_year = history["fiscal_year"].shift()
    consecutive = result["fiscal_year"].sub(previous_year).eq(1)
    previous_low = history["current_execution_severity"].shift().fillna(0).gt(0)
    current_low = result["current_execution_severity"].fillna(0).gt(0)
    result["repeated_low_execution_signal"] = current_low & previous_low & consecutive
    previous_miss = history["performance_signal"].shift(fill_value=False)
    result["reported_target_miss_consecutive"] = (
        result["performance_signal"] & previous_miss & consecutive
    )
    target_met = comparable.gt(0) & ~result["performance_signal"]
    previous_met = target_met.groupby(result["program_identity_id"], sort=False).shift(
        fill_value=False
    )
    result["reported_target_met_consecutive"] = target_met & previous_met & consecutive
    result["reported_target_history_status"] = "LEFT_CENSORED_OR_FIRST_OBSERVATION"
    result.loc[previous_year.notna() & ~consecutive, "reported_target_history_status"] = (
        "NON_CONSECUTIVE_GAP"
    )
    result.loc[consecutive, "reported_target_history_status"] = "CONSECUTIVE_PRIOR_YEAR"
    result.loc[result["program_code"].isna(), "reported_target_history_status"] = (
        "UNKNOWN_CONTINUITY"
    )

    previous_budget = history["program_original_budget"].shift()
    result["program_budget_change_rate"] = pd.to_numeric(
        result["program_original_budget"], errors="coerce"
    ).div(pd.to_numeric(previous_budget, errors="coerce").where(lambda s: s.gt(0))).sub(1)
    result.loc[~consecutive, "program_budget_change_rate"] = pd.NA
    result["budget_increase_context_signal"] = pd.to_numeric(
        result["program_budget_change_rate"], errors="coerce"
    ).gt(0)
    result["budget_decrease_context_signal"] = pd.to_numeric(
        result["program_budget_change_rate"], errors="coerce"
    ).lt(0)
    result["budget_mismatch_signal"] = (
        result["performance_signal"] & result["budget_increase_context_signal"]
    ) | (target_met & result["budget_decrease_context_signal"])
    result["budget_performance_mismatch"] = result["budget_mismatch_signal"].astype(float)
    result["accounting_context_signal"] = pd.to_numeric(
        result["type_accounting_adjustment_pattern_budget_share"], errors="coerce"
    ).fillna(0).gt(0)
    result["structure_context_signal"] = pd.to_numeric(
        result["type_program_budget_concentration_budget_share"], errors="coerce"
    ).fillna(0).gt(0)
    result["type_repeated_strong_low_execution_budget_share"] = 0.0
    result["type_repeated_moderate_low_execution_budget_share"] = 0.0
    result["execution_management"] = pd.concat(
        [
            result["current_execution_severity"],
            result["repeated_low_execution_signal"].astype(float),
        ],
        axis=1,
    ).max(axis=1, skipna=False)
    result["repeated_target_overachievement"] = result[
        "repeated_target_overachievement"
    ].fillna(False).astype(bool)
    result["target_unchanged"] = result["target_unchanged"].fillna(False).astype(bool)
    context_defaults = {
        "context_type": "UNKNOWN_TYPE",
        "context_status": "CONFIRMED_STRUCTURED",
        "context_source": "PROGRAM_YEAR_STRUCTURED_AGGREGATION",
        "context_evidence": "NO_CONFIRMED_CONTEXT_TAG",
        "context_effect": "NO_GRADE_CHANGE",
    }
    for column, default in context_defaults.items():
        if column not in result:
            result[column] = default
        else:
            result[column] = result[column].fillna(default)

    observed = result.groupby("program_identity_id", dropna=False)["fiscal_year"]
    result["observed_start_year"] = observed.transform("min")
    result["observed_end_year"] = observed.transform("max")
    result["observed_year_count"] = observed.transform("nunique")
    result["continuity_status"] = "EXACT_PROGRAM_KEY"
    result.loc[result["base_program_year_key_conflict"], "continuity_status"] = (
        "EXACT_METADATA_DISAMBIGUATION_DATA_HOLD"
    )
    result.loc[result["program_code"].isna(), "continuity_status"] = "UNKNOWN_CONTINUITY"

    result = apply_question_review_grades(result)
    result["independent_signal_family_count"] = result["signal_families"].map(
        lambda value: 0 if value == "NONE" else len(str(value).split(";"))
    )
    result["repeated_signal_family_count"] = (
        result["repeated_low_execution_signal"].astype(int)
        + result["reported_target_miss_consecutive"].astype(int)
    )
    strength_order = {"STRONG": 0, "MODERATE": 1, "AMBIGUOUS": 2, "NONE": 3, "NOT_ASSESSED": 4}
    result["_strength_order"] = result["signal_strength"].map(strength_order).fillna(5)
    result["_family_order"] = -result["independent_signal_family_count"]
    result["_budget_order"] = -pd.to_numeric(result["program_original_budget"], errors="coerce").fillna(0)
    result = result.sort_values(
        [
            "fiscal_year",
            "review_grade_order",
            "_strength_order",
            "_family_order",
            "_budget_order",
            "program_year_id",
        ]
    )
    result["program_year_queue_order"] = range(1, len(result) + 1)
    result["review_queue_order_within_year"] = result.groupby("fiscal_year").cumcount() + 1
    result = result.drop(columns=["_strength_order", "_family_order", "_budget_order"])

    amount_diffs = {}
    for output, raw in amount_columns.items():
        amount_diffs[output] = float(
            abs(
                pd.to_numeric(source[raw], errors="coerce").sum()
                - pd.to_numeric(result[output], errors="coerce").sum()
            )
        )
    if any(value > 0.5 for value in amount_diffs.values()):
        raise PriorityScenarioError(f"프로그램-연도 집계 전후 금액이 다릅니다: {amount_diffs}")
    if result["program_year_id"].duplicated().any():
        raise PriorityScenarioError("프로그램-연도 대기열 기본키가 중복되었습니다.")
    if result.groupby(["fiscal_year", "program_year_id"]).size().gt(1).any():
        raise PriorityScenarioError("선택연도 대기열에 프로그램이 중복되었습니다.")

    raw_execution = (
        pd.to_numeric(source["current_execution_severity"], errors="coerce").fillna(0).gt(0)
        | pd.to_numeric(
            source["type_repeated_strong_low_execution_budget_share"], errors="coerce"
        ).fillna(0).gt(0)
        | pd.to_numeric(
            source["type_repeated_moderate_low_execution_budget_share"], errors="coerce"
        ).fillna(0).gt(0)
    )
    raw_target_met = source["reported_target_status"].isin(
        {"AT_OR_ABOVE", "ALL_COMPARABLE_AT_OR_ABOVE_TARGET"}
    )
    raw_counterexample = source.loc[
        raw_execution & raw_target_met & ~source["performance_signal"].fillna(False).astype(bool)
    ]
    program_counterexample = result.loc[
        result["diagnostic_type"].eq("LOW_EXECUTION_TARGET_MET")
        & result["review_grade"].eq("C")
    ]
    ministry_years = result.groupby("ministry_code")["fiscal_year"].agg(
        lambda values: set(values.astype(int))
    )
    common_years = set.intersection(*ministry_years.tolist()) if len(ministry_years) else set()
    summary = {
        "grain": "ministry x program x fiscal_year",
        "primary_key": "program_year_id",
        "preferred_key_candidate": ["ministry_code", "fiscal_year", "program_code"],
        "preferred_key_conflict_group_count": int(
            source.loc[source["base_program_year_key_conflict"], ["ministry_code", "fiscal_year", "program_code"]]
            .drop_duplicates()
            .shape[0]
        ),
        "program_year_key_unique": True,
        "unique_program_count": int(result["program_identity_id"].nunique()),
        "program_year_count": len(result),
        "program_year_account_analysis_row_count": len(source),
        "unique_program_count_by_year": {
            str(int(key)): int(value)
            for key, value in result.groupby("fiscal_year")["program_year_id"].nunique().items()
        },
        "account_type_count_distribution": {
            str(int(key)): int(value) for key, value in result["account_type_count"].value_counts().sort_index().items()
        },
        "grade_counts": {
            str(key): int(value) for key, value in result["review_grade"].value_counts().items()
        },
        "grade_original_budget": {
            str(key): float(value)
            for key, value in result.groupby("review_grade")["program_original_budget"].sum().items()
        },
        "latest_common_analysis_year": max(common_years) if common_years else None,
        "selected_year_unique_program_count": (
            int(result.loc[result["fiscal_year"].eq(max(common_years)), "program_year_id"].nunique())
            if common_years
            else 0
        ),
        "amount_reconciliation_absolute_differences": amount_diffs,
        "performance_status_conflict_program_year_count": int(
            result["program_performance_status_conflict"].sum()
        ),
        "program_performance_account_duplicate_counted_as_additional_performance": 0,
        "low_execution_target_met": {
            "raw_account_row_count": len(raw_counterexample),
            "unique_program_year_count": int(raw_counterexample["program_year_id"].nunique()),
            "unique_program_count": int(raw_counterexample["program_identity_id"].nunique()),
            "program_year_c_grade_count": len(program_counterexample),
        },
        "top5_unique_programs_by_year": {
            str(int(year)): bool(
                part.nsmallest(5, "review_queue_order_within_year")["program_year_id"].nunique()
                == min(5, len(part))
            )
            for year, part in result.groupby("fiscal_year")
        },
    }
    return result.convert_dtypes(), summary


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


def _build_retrospective_feedback_reason(row: pd.Series) -> str:
    reasons: list[str] = []
    for column, reason in (
        ("low_performance_budget_increase_t1", "LOW_PERFORMANCE_BUDGET_INCREASE_T1"),
        ("low_performance_budget_increase_t2", "LOW_PERFORMANCE_BUDGET_INCREASE_T2"),
        ("good_performance_budget_decrease_t1", "GOOD_PERFORMANCE_BUDGET_DECREASE_T1_CONTEXT"),
        ("good_performance_budget_decrease_t2", "GOOD_PERFORMANCE_BUDGET_DECREASE_T2_CONTEXT"),
        ("program_total_account_type_mismatch_t1", "PROGRAM_ACCOUNT_TYPE_MISMATCH_T1"),
        ("program_total_account_type_mismatch_t2", "PROGRAM_ACCOUNT_TYPE_MISMATCH_T2"),
    ):
        if bool(row.get(column, False)):
            reasons.append(reason)
    return ";".join(reasons) or "NO_RETROSPECTIVE_FEEDBACK"


def apply_feedback_cutoff(frame: pd.DataFrame, cutoff_year: int) -> pd.DataFrame:
    """분석 종료연도 뒤의 예산 결과를 환류 신호에서 차단합니다."""
    result = frame.copy()
    fiscal_year = pd.to_numeric(result["fiscal_year"], errors="coerce")
    for horizon, lag in (("t1", 1), ("t2", 2)):
        outside = fiscal_year.add(lag).gt(cutoff_year)
        for column in (
            f"low_performance_budget_increase_{horizon}",
            f"good_performance_budget_decrease_{horizon}",
            f"program_total_feedback_complete_{horizon}",
            f"feedback_budget_complete_{horizon}",
            f"continuous_project_feedback_complete_{horizon}",
            f"budget_direction_reconciled_{horizon}",
        ):
            if column in result:
                result.loc[outside, column] = False
        for column in (
            f"program_total_outcome_budget_{horizon}",
            f"program_total_budget_change_rate_{horizon}",
            f"feedback_outcome_budget_{horizon}",
            f"feedback_budget_change_rate_{horizon}",
            f"continuous_project_outcome_budget_{horizon}",
            f"continuous_project_budget_change_rate_{horizon}",
        ):
            if column in result:
                result.loc[outside, column] = pd.NA
    return result


def build_candidate_population(
    analysis: pd.DataFrame,
    program_signals: pd.DataFrame,
    config: dict[str, Any],
    feedback: pd.DataFrame | None = None,
    program_financial: pd.DataFrame | None = None,
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
        "성과·재정 결합표",
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
    feedback_columns = [
        f"{metric}_{horizon}"
        for metric in (
            "feedback_project_count",
            "feedback_base_budget",
            "feedback_outcome_budget",
            "feedback_budget_change_rate",
        )
        for horizon in ("t1", "t2")
    ]
    if feedback is None:
        for column in feedback_columns:
            merged[column] = pd.NA
    else:
        merged = merged.merge(feedback, on=KEY, how="left", validate="many_to_one")
        for column in feedback_columns:
            if column not in merged:
                merged[column] = pd.NA
    if program_financial is not None:
        merged = add_program_total_feedback(merged, program_financial)
    else:
        for horizon in ("t1", "t2"):
            merged[f"program_total_feedback_complete_{horizon}"] = False
            merged[f"program_total_budget_change_rate_{horizon}"] = pd.NA
            merged[f"program_total_account_type_mismatch_{horizon}"] = False
            merged[f"budget_feedback_basis_{horizon}"] = "UNAVAILABLE_MIXED_OR_UNLINKED"
            merged[f"budget_direction_reconciled_{horizon}"] = False
        merged["budget_direction_reconciled"] = False
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
    merged["retrospective_feedback_data_quality_signal"] = merged[
        "program_total_account_type_mismatch_t1"
    ].fillna(False) | merged["program_total_account_type_mismatch_t2"].fillna(False)
    merged["performance_signal"] = merged["performance_gap"].fillna(0).gt(0)
    merged["execution_signal"] = merged["execution_management"].fillna(0).gt(0)
    merged["budget_mismatch_signal"] = merged["budget_performance_mismatch"].fillna(0).gt(0)
    merged["accounting_context_signal"] = (
        merged["type_accounting_adjustment_pattern_budget_share"].fillna(0).gt(0)
    )
    merged["structure_context_signal"] = (
        merged["type_program_budget_concentration_budget_share"].fillna(0).gt(0)
    )
    merged["budget_increase_context_signal"] = (
        merged["type_budget_rapid_increase_budget_share"].fillna(0).gt(0)
    )
    merged["budget_decrease_context_signal"] = (
        merged["type_budget_rapid_decrease_budget_share"].fillna(0).gt(0)
    )
    comparable_performance = comparable.gt(0)
    for horizon in ("t1", "t2"):
        base = pd.to_numeric(merged[f"feedback_base_budget_{horizon}"], errors="coerce")
        outcome = pd.to_numeric(merged[f"feedback_outcome_budget_{horizon}"], errors="coerce")
        merged[f"feedback_budget_complete_{horizon}"] = base.notna() & base.sub(
            pd.to_numeric(merged["account_original_budget"], errors="coerce")
        ).abs().le(0.5)
        merged[f"continuous_project_count_{horizon}"] = merged[f"feedback_project_count_{horizon}"]
        merged[f"continuous_project_base_budget_{horizon}"] = base
        merged[f"continuous_project_outcome_budget_{horizon}"] = outcome
        merged[f"continuous_project_budget_change_rate_{horizon}"] = merged[
            f"feedback_budget_change_rate_{horizon}"
        ]
        merged[f"continuous_project_feedback_complete_{horizon}"] = merged[
            f"feedback_budget_complete_{horizon}"
        ]
        if program_financial is not None:
            merged[f"budget_direction_reconciled_{horizon}"] = (
                merged[f"program_total_feedback_complete_{horizon}"]
                & merged[f"continuous_project_feedback_complete_{horizon}"]
                & _direction(merged[f"program_total_budget_change_rate_{horizon}"]).eq(
                    _direction(merged[f"continuous_project_budget_change_rate_{horizon}"])
                )
            )
            if horizon == "t1":
                merged["budget_direction_reconciled"] = merged["budget_direction_reconciled_t1"]
        merged[f"low_performance_budget_increase_{horizon}"] = (
            joint
            & comparable_performance
            & merged["performance_gap"].gt(0)
            & merged[f"program_total_feedback_complete_{horizon}"]
            & pd.to_numeric(
                merged[f"program_total_budget_change_rate_{horizon}"], errors="coerce"
            ).gt(0)
        )
        merged[f"good_performance_budget_decrease_{horizon}"] = (
            joint
            & comparable_performance
            & merged["performance_gap"].eq(0)
            & merged[f"program_total_feedback_complete_{horizon}"]
            & pd.to_numeric(
                merged[f"program_total_budget_change_rate_{horizon}"], errors="coerce"
            ).lt(0)
        )
    merged = apply_feedback_cutoff(merged, int(config["scope"]["end_year"]))
    merged["current_execution_signal"] = merged["current_execution_severity"].fillna(0).gt(0)
    merged["repeated_signal_family_count"] = pd.DataFrame(
        {
            "strong": merged["type_repeated_strong_low_execution_budget_share"].fillna(0).gt(0),
            "moderate": merged["type_repeated_moderate_low_execution_budget_share"].fillna(0).gt(0),
            "year_end": merged["type_repeated_year_end_concentration_budget_share"].fillna(0).gt(0),
        }
    ).sum(axis=1)
    merged["repeated_execution_signal"] = merged["repeated_signal_family_count"].gt(0)
    merged["execution_review_signal"] = (
        merged["current_execution_signal"] | merged["repeated_execution_signal"]
    )
    independent_columns = [
        "performance_signal",
        "execution_review_signal",
    ]
    merged["independent_signal_family_count"] = merged[independent_columns].sum(axis=1)
    merged["evidence_status"] = "CONFIRMED"
    merged.loc[merged["rank_confidence_worst"].isin(["LOW", "MEDIUM"]), "evidence_status"] = (
        "LIMITED"
    )
    merged.loc[merged["data_validation_signal"], "evidence_status"] = "DATA_BLOCKED"
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

    # priority_tier의 강한 단일도 동일 원칙(성과미달 단독 금지).
    strong_single = merged["current_execution_severity"].fillna(0).ge(1) | merged[
        "type_repeated_strong_low_execution_budget_share"
    ].fillna(0).ge(0.5)
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
    # 보고된 목표 미달과 후속예산은 강한 단일 판정 근거로 사용하지 않습니다.
    execution_strong_signal = merged["current_execution_severity"].fillna(0).ge(1)
    strong_independent = execution_strong_signal
    merged["review_intensity"] = "MONITOR"
    merged.loc[
        merged["accounting_context_signal"]
        | merged["structure_context_signal"]
        | merged["budget_increase_context_signal"]
        | merged["budget_decrease_context_signal"],
        "review_intensity",
    ] = "CONTEXT_REVIEW"
    merged.loc[merged["independent_signal_family_count"].eq(1), "review_intensity"] = (
        "SINGLE_REVIEW"
    )
    merged.loc[
        merged["independent_signal_family_count"].eq(1) & strong_independent,
        "review_intensity",
    ] = "STRONG_SINGLE"
    merged.loc[
        merged["independent_signal_family_count"].ge(2) | merged["repeated_execution_signal"],
        "review_intensity",
    ] = "REPEATED_OR_MULTIPLE"
    merged.loc[merged["data_validation_signal"], "review_intensity"] = "DATA_FIRST"
    merged["review_candidate"] = merged["review_intensity"].isin(
        [
            "REPEATED_OR_MULTIPLE",
            "STRONG_SINGLE",
            "SINGLE_REVIEW",
            "CONTEXT_REVIEW",
        ]
    )
    merged["review_intensity_order"] = merged["review_intensity"].map(REVIEW_INTENSITY_ORDER)
    merged["review_item_type"] = "DETAILED_PROJECT_REVIEW"
    merged.loc[merged["data_validation_signal"], "review_item_type"] = "PROGRAM_DATA_TASK"
    merged["next_action"] = merged["review_intensity"].map(
        {
            "DATA_FIRST": "프로그램 코드·분모·금액 연결 근거를 먼저 확인",
            "REPEATED_OR_MULTIPLE": "반복·복수 신호의 원인을 세부사업과 원문에서 확인",
            "STRONG_SINGLE": "강한 단일 신호의 예외 사유와 원문을 확인",
            "SINGLE_REVIEW": "표시된 독립 신호의 근거를 확인",
            "CONTEXT_REVIEW": "회계조정·예산구조·사업변경 맥락을 확인",
            "MONITOR": "현재 신호 미검출, 신규 자료 유입 시 재점검",
        }
    )
    merged["priority_reason"] = merged.apply(_build_priority_reason, axis=1)
    merged["retrospective_feedback_reason"] = merged.apply(
        _build_retrospective_feedback_reason,
        axis=1,
    )
    program_identity = merged["program_code"].fillna(
        merged["performance_program_name"].astype("string")
    )
    merged["candidate_id"] = (
        merged["ministry_code"].fillna("NA").astype(str)
        + ":"
        + merged["fiscal_year"].astype(str)
        + ":"
        + merged["field_name"].fillna("NA").astype(str)
        + ":"
        + merged["sector_name"].fillna("NA").astype(str)
        + ":"
        + program_identity.fillna("NA").astype(str)
        + ":"
        + merged["account_type"].fillna("NA").astype(str)
    )
    merged = attach_reported_target_history(merged)
    merged = apply_question_review_grades(merged)
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
    return attach_signal_size_separation(result.convert_dtypes())


def attach_signal_size_separation(candidates: pd.DataFrame) -> pd.DataFrame:
    """신호 점수와 예산 규모를 분리해 본편 대기열용 필드를 붙입니다.

    - signal_score: 세 구성요소가 모두 있을 때만 산술평균 (fiscal_impact 제외)
    - fiscal_impact: 민감도·파급 시나리오용으로 유지
    - 본편 업무순서는 signal_score 후 예산 동률 정리만 사용
    """
    result = candidates.copy()
    signal_parts = [
        pd.to_numeric(result[column], errors="coerce") for column in SIGNAL_SCORE_COMPONENTS
    ]
    signal_frame = pd.concat(signal_parts, axis=1)
    complete = signal_frame.notna().all(axis=1)
    result["signal_score"] = signal_frame.mean(axis=1).where(complete).astype("Float64")
    result["signal_score_status"] = complete.map({True: "COMPLETE", False: "INCOMPLETE_COMPONENTS"})
    result["signal_score_method"] = SIGNAL_SCORE_METHOD
    result["size_role_in_work_queue"] = SIZE_ROLE_IN_WORK_QUEUE
    result["fiscal_impact_in_signal_score"] = False
    if result["signal_score"].isna().all():
        raise PriorityScenarioError("신호 점수를 계산할 수 없습니다.")
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
                "RESPONSIBLE_OPERATION_ACCOUNT": "책임운영기관특별회계",
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
    provenance: dict[str, Any],
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
        "analysis_version": ANALYSIS_VERSION,
        "output_schema_version": OUTPUT_SCHEMA_VERSION,
        "analysis_time_basis": ANALYSIS_TIME_BASIS,
        "availability_cutoff_enforced": False,
        "real_time_or_historical_information_set_reconstructed": False,
        "data_fiscal_year_min": int(candidates["fiscal_year"].min()),
        "data_fiscal_year_max": int(candidates["fiscal_year"].max()),
        "code_provenance": provenance,
        "stable_tie_break_key": "candidate_id",
        "scope": config["scope"],
        "grain": "ministry x program x fiscal_year x account_type",
        "status": "independent_review_work_queue_primary_weighted_scenarios_advanced_only",
        "counts": {
            "analysis_rows": len(candidates),
            "joint_analysis_rows": int(candidates["analysis_status"].eq("JOINT_ANALYSIS").sum()),
            "data_review_rows": int(candidates["priority_tier"].eq("DATA_REVIEW").sum()),
            "review_candidate_rows": int(candidates["review_candidate"].sum()),
            "scenario_ranking_eligible_rows": int(candidates["scenario_ranking_eligible"].sum()),
            "context_only_candidate_rows": int(candidates["context_only_candidate"].sum()),
            "information_rows": int(candidates["priority_tier"].eq("INFORMATION").sum()),
            "scenario_count": int(scenario_scores["scenario"].nunique()),
            "review_intensity": {
                str(key): int(value)
                for key, value in candidates["review_intensity"].value_counts().items()
            },
            "feedback_t1_complete_rows": int(
                candidates["program_total_feedback_complete_t1"].fillna(False).sum()
            ),
            "feedback_t2_complete_rows": int(
                candidates["program_total_feedback_complete_t2"].fillna(False).sum()
            ),
            "continuous_project_feedback_t1_complete_rows": int(
                candidates["continuous_project_feedback_complete_t1"].fillna(False).sum()
            ),
            "continuous_project_feedback_t2_complete_rows": int(
                candidates["continuous_project_feedback_complete_t2"].fillna(False).sum()
            ),
        },
        "stability": {
            "minimum_off_diagonal_spearman": float(off_diagonal.min()),
            "maximum_off_diagonal_spearman": float(off_diagonal.max()),
            "all_scenario_top_k": {
                str(int(row.top_k)): {
                    "intersection_count": int(row.intersection_count),
                    "intersection_unique_program_count": len(
                        stability.loc[
                            stability[f"all_scenario_top_{int(row.top_k)}"],
                            PROGRAM_ID_KEY,
                        ].drop_duplicates()
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
        "review_workbench_method": {
            "primary_order": [
                "DATA_FIRST",
                "REPEATED_OR_MULTIPLE",
                "STRONG_SINGLE",
                "SINGLE_REVIEW",
                "CONTEXT_REVIEW",
                "MONITOR",
            ],
            "within_intensity_order": [
                "repeated_signal_family_count_desc",
                "independent_signal_family_count_desc",
                "evidence_status",
                "complete_case_signal_score_desc",
                "account_original_budget_desc_tiebreak_only",
                "candidate_id",
            ],
            "weighted_sum_used": False,
            "signal_score_used_in_work_queue": True,
            "signal_score_used_in_default_grade_queue": False,
            "partial_signal_score_used_in_work_queue": False,
            "signal_score_method": SIGNAL_SCORE_METHOD,
            "signal_score_components": list(SIGNAL_SCORE_COMPONENTS),
            "fiscal_impact_in_signal_score": False,
            "size_role_in_work_queue": SIZE_ROLE_IN_WORK_QUEUE,
            "t1_t2_kept_separate": True,
            "t1_t2_excluded_from_current_review_intensity": True,
            "performance_attributed_to_detailed_project": False,
            "account_type_kept_separate": True,
            "question_review_grade_precedence": [
                "H_HOLD",
                "SPECIAL_C_CONFLICT_OR_MISSING_PERFORMANCE",
                "A_EXPLICIT_COMPOUND_RULES",
                "B_STRONG_OR_REPEATED_SINGLE",
                "C_CONTEXT_OR_SINGLE",
                "D_NO_TRIGGER_DETECTED",
            ],
            "legacy_work_queue_order_preserved": True,
            "default_ui_order": "grade_queue_order",
        },
        "legacy_scenario_components": {
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
        "advanced_sensitivity_scenario_weights": config["scenarios"],
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
            "weighted_scenarios_primary_work_order": False,
            "t1_t2_in_single_score": False,
            "t1_t2_in_current_review_intensity": False,
        },
        "input_sha256": input_hashes,
        "config_hash_included_in_input_sha256": True,
        "interpretation_limits": [
            "회계연도 축 사후검토이며 실제 공개시점 당시 정보집합이나 실시간 판단을 재현하지 않음",
            "사업별 기대 성과시차·의무지출·성과지표 유형은 현재 미확정",
            "기존 가중 시나리오는 고급 민감도에만 보존하고 기본 업무순서에 사용하지 않음",
            "프로그램 성과를 세부사업 성과로 귀속하지 않음",
            "기금과 일반·특별회계를 같은 집행률 기준으로 직접 서열 비교하지 않음",
            "융자 공급·회수·순재정부담과 목·비목 예산구조는 현재 원자료 부재",
        ],
    }


def run_priority_scenario_analysis(
    paths: PriorityScenarioPaths,
    *,
    overwrite: bool = False,
) -> PriorityScenarioResult:
    for source in (
        paths.same_year_analysis,
        paths.financial_features,
        paths.feedback_cohorts,
        paths.program_financial,
        paths.config,
    ):
        if not source.exists():
            raise FileNotFoundError(source)
    input_hashes = {
        str(source): _sha256(source)
        for source in (
            paths.same_year_analysis,
            paths.financial_features,
            paths.feedback_cohorts,
            paths.program_financial,
            paths.config,
        )
    }
    project_root = paths.config.resolve().parent.parent
    provenance = _git_provenance(project_root)
    config = load_scenario_config(paths.config)
    scope = config["scope"]
    analysis = pd.read_csv(
        paths.same_year_analysis,
        dtype={"ministry_code": "string", "program_code": "string"},
    )
    features = pd.read_parquet(paths.financial_features)
    feedback_cohorts = pd.read_csv(
        paths.feedback_cohorts,
        dtype={"ministry_code": "string", "program_code": "string"},
    )
    program_financial = pd.read_parquet(paths.program_financial)
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
    feedback = aggregate_program_feedback(
        feedback_cohorts,
        features,
        ministry_codes=tuple(
            str(code).zfill(3) for code in (ministry_codes or [str(scope["ministry_code"])])
        ),
        start_year=int(scope["start_year"]),
        end_year=int(scope["end_year"]),
    )
    candidates = build_candidate_population(
        analysis,
        program_signals,
        config,
        feedback,
        program_financial,
    )
    scenario_scores = score_scenarios(candidates, config)
    scenario_names = list(config["scenarios"])
    stability = build_rank_stability(candidates, scenario_scores, config)
    work_queue, work_queue_summary = build_full_population_review_work_queue(
        candidates,
        stability,
    )
    program_year_review_queue, program_year_review_summary = build_program_year_review_queue(
        work_queue,
        config,
    )
    threshold_qa = build_current_execution_threshold_qa(candidates, config)
    blind_review_pilot = build_blind_review_pilot(work_queue)
    drilldown, drilldown_summary = build_stable_top5_project_drilldown(
        candidates,
        stability,
        features,
    )
    project_review_queue, project_review_summary = build_project_review_work_queue(
        candidates,
        work_queue,
        features,
    )
    review_workbench_queue = build_review_workbench_queue(work_queue, project_review_queue)
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
        provenance=provenance,
    )
    summary["full_population_review_work_queue"] = work_queue_summary
    summary["program_year_review_queue"] = program_year_review_summary
    summary["question_review_grade"] = {
        **work_queue_summary["question_review_grade"],
        "retrospective_feedback_by_grade": summarize_retrospective_feedback_by_grade(work_queue),
        "threshold_qa_scope": "CURRENT_YEAR_EXECUTION_THRESHOLDS_ONLY_NOT_PRODUCTION_RULES",
        "threshold_qa_transition_rows": len(threshold_qa),
        "blind_pair_count": int(blind_review_pilot["pair_id"].nunique()),
        "blind_pair_role": "USABILITY_PILOT_NOT_ACCURACY_VALIDATION",
        "t1_t2_used_in_review_grade": False,
    }
    summary["drilldown"] = drilldown_summary
    summary["project_review_queue"] = project_review_summary
    summary["review_workbench_queue"] = {
        "row_count": len(review_workbench_queue),
        "program_data_task_count": int(
            review_workbench_queue["review_item_type"].eq("PROGRAM_DATA_TASK").sum()
        ),
        "detailed_project_review_count": int(
            review_workbench_queue["review_item_type"].eq("DETAILED_PROJECT_REVIEW").sum()
        ),
        "work_item_id_unique": bool(review_workbench_queue["work_item_id"].is_unique),
        "final_policy_rank_generated": False,
    }
    summary["feedback_linkage"] = feedback.attrs["linkage"]
    if {
        str(source): _sha256(source)
        for source in (
            paths.same_year_analysis,
            paths.financial_features,
            paths.feedback_cohorts,
            paths.program_financial,
            paths.config,
        )
    } != input_hashes:
        raise PriorityScenarioError("입력 파일이 실행 중 변경되었습니다.")

    paths.output_dir.mkdir(parents=True, exist_ok=True)
    paths.figure_dir.mkdir(parents=True, exist_ok=True)
    output_map = {
        "candidate_population.csv": candidates,
        "full_population_review_work_queue.csv": work_queue,
        "program_year_review_queue.csv": program_year_review_queue,
        "scenario_scores.csv": scenario_scores,
        "rank_stability.csv": stability,
        "stable_top5_project_drilldown.csv": drilldown,
        "full_population_project_review_queue.csv": project_review_queue,
        "review_workbench_queue.csv": review_workbench_queue,
        "scenario_spearman.csv": spearman,
        "top_k_overlap.csv": top_k_overlap,
        "question_review_threshold_qa.csv": threshold_qa,
        "question_review_blind_pairs.csv": blind_review_pilot,
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
        work_queue=work_queue,
        program_year_review_queue=program_year_review_queue,
        scenario_scores=scenario_scores,
        stability=stability,
        drilldown=drilldown,
        project_review_queue=project_review_queue,
        review_workbench_queue=review_workbench_queue,
        spearman=spearman,
        top_k_overlap=top_k_overlap,
        summary=summary,
        output_paths=(*output_paths, summary_path),
        figure_paths=(rank_figure, spearman_figure),
    )


def run_configured_multi_ministry_priority_analysis(
    root: Path,
    *,
    overwrite: bool = False,
) -> tuple[Path, PriorityScenarioResult]:
    paths = PriorityScenarioPaths.multi_ministry_from_root(root)
    config = load_scenario_config(paths.config)
    scope = config.get("scope", {})
    ministry_codes = tuple(str(code).zfill(3) for code in scope.get("ministry_codes", ()))
    if not ministry_codes or len(set(ministry_codes)) != len(ministry_codes):
        raise PriorityScenarioError(
            "scope.ministry_codes에는 중복 없는 부처코드가 하나 이상 필요합니다."
        )

    combined_path = paths.same_year_analysis
    if combined_path.exists() and not overwrite:
        raise FileExistsError(f"다부처 성과·재정 결합표가 이미 있습니다: {combined_path}")

    frames: list[pd.DataFrame] = []
    start_year = int(scope["start_year"])
    end_year = int(scope["end_year"])
    for code in ministry_codes:
        result = run_same_year_budget_check(
            indicator_path=root / f"data/processed/performance/by_ministry/ministry_code={code}/"
            "analysis_ready/program_kpi_year_analysis_ready.parquet",
            overall_financial_path=root / "data/processed/masters/program_year_financial.parquet",
            project_financial_path=root
            / "data/processed/masters/project_year_financial_v2.parquet",
            output_dir=root
            / f"data/analytics/by_ministry/ministry_code={code}/same_year_budget_check",
            ministry_code=code,
            start_year=start_year,
            end_year=end_year,
            overwrite=overwrite,
        )
        frames.append(result.analysis)

    combined = pd.concat(frames, ignore_index=True).convert_dtypes()
    key = [
        "ministry_code",
        "fiscal_year",
        "program_goal_number",
        "performance_program_name",
        "account_type",
    ]
    if combined.duplicated(key).any():
        raise PriorityScenarioError("다부처 결합표의 분석 키가 중복되었습니다.")
    actual_codes = set(combined["ministry_code"].astype("string").str.zfill(3))
    if actual_codes != set(ministry_codes):
        raise PriorityScenarioError(
            "다부처 결합표의 부처 범위가 설정과 다릅니다: "
            f"설정={sorted(ministry_codes)}, 결과={sorted(actual_codes)}"
        )

    combined_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(combined_path, index=False, encoding="utf-8-sig")
    priority = run_priority_scenario_analysis(paths, overwrite=overwrite)
    return combined_path, priority
