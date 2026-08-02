"""운영 산출물을 바꾸지 않고 우선순위 P0 오류의 영향을 재현합니다."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from analytics.m3_financial_signals import TYPE_COLUMNS, TYPE_LABELS
from analytics.mss_priority_scenario_analysis import (
    REVIEW_INTENSITY_ORDER,
    PriorityScenarioPaths,
    aggregate_program_account_signals,
    aggregate_program_feedback,
    build_candidate_population,
    build_full_population_review_work_queue,
    build_rank_stability,
    load_scenario_config,
    score_scenarios,
)
from master_engineering.quality.refactor_gate_a import (
    MINISTRIES,
    YEARS,
    _performance,
    _scope,
    _sha256,
)


def _bool(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame[column].astype("boolean").fillna(False)


def _recompute_review_intensity(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    independent = [
        "performance_signal",
        "execution_review_signal",
        "low_performance_budget_increase_t1",
        "low_performance_budget_increase_t2",
    ]
    result["independent_signal_family_count"] = pd.DataFrame(
        {column: _bool(result, column) for column in independent}
    ).sum(axis=1)
    context = pd.DataFrame(
        {
            column: _bool(result, column)
            for column in [
                "accounting_context_signal",
                "structure_context_signal",
                "budget_increase_context_signal",
                "budget_decrease_context_signal",
                "good_performance_budget_decrease_t1",
                "good_performance_budget_decrease_t2",
            ]
        }
    ).any(axis=1)
    strong = (
        pd.to_numeric(result["performance_gap"], errors="coerce").fillna(0).ge(1)
        | pd.to_numeric(result["current_execution_severity"], errors="coerce").fillna(0).ge(1)
        | _bool(result, "low_performance_budget_increase_t1")
        | _bool(result, "low_performance_budget_increase_t2")
    )
    count = result["independent_signal_family_count"]
    result["review_intensity"] = "MONITOR"
    result.loc[context, "review_intensity"] = "CONTEXT_REVIEW"
    result.loc[count.eq(1), "review_intensity"] = "SINGLE_REVIEW"
    result.loc[count.eq(1) & strong, "review_intensity"] = "STRONG_SINGLE"
    result.loc[count.ge(2) | _bool(result, "repeated_execution_signal"), "review_intensity"] = (
        "REPEATED_OR_MULTIPLE"
    )
    result.loc[_bool(result, "data_validation_signal"), "review_intensity"] = "DATA_FIRST"
    result["review_candidate"] = result["review_intensity"].isin(
        ["REPEATED_OR_MULTIPLE", "STRONG_SINGLE", "SINGLE_REVIEW", "CONTEXT_REVIEW"]
    )
    result["review_intensity_order"] = result["review_intensity"].map(REVIEW_INTENSITY_ORDER)
    return result


def _suppress_future_outcomes(candidates: pd.DataFrame) -> pd.DataFrame:
    result = candidates.copy()
    for fiscal_year, horizon in ((2024, "t1"), (2023, "t2")):
        mask = result["fiscal_year"].eq(fiscal_year)
        for column in (
            f"low_performance_budget_increase_{horizon}",
            f"good_performance_budget_decrease_{horizon}",
            f"program_total_feedback_complete_{horizon}",
            f"feedback_budget_complete_{horizon}",
            f"continuous_project_feedback_complete_{horizon}",
        ):
            result.loc[mask, column] = False
        for column in (
            f"program_total_outcome_budget_{horizon}",
            f"program_total_budget_change_rate_{horizon}",
            f"feedback_outcome_budget_{horizon}",
            f"feedback_budget_change_rate_{horizon}",
            f"continuous_project_outcome_budget_{horizon}",
            f"continuous_project_budget_change_rate_{horizon}",
        ):
            if column in result:
                result.loc[mask, column] = pd.NA
    return _recompute_review_intensity(result)


def _suppress_unknown_peer_signals(features: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    result = features.copy()
    mask = (
        result["ministry_code"].astype("string").str.zfill(3).isin(MINISTRIES)
        & result["fiscal_year"].isin(YEARS)
        & result["program_code"].notna()
        & result["account_type"].notna()
        & result["fiscal_instrument"].eq("UNKNOWN")
    )
    for column in (
        "peer_bottom_10_execution_flag",
        "peer_bottom_20_execution_flag",
        "budget_increase_extreme_flag",
        "budget_decrease_extreme_flag",
        "type_budget_rapid_increase",
        "type_budget_rapid_decrease",
    ):
        result.loc[mask, column] = False
    signal_columns = [
        "strong_low_execution_flag",
        "moderate_low_execution_flag",
        "peer_bottom_10_execution_flag",
        "fixed_year_end_concentration_flag",
        "peer_p90_year_end_concentration_flag",
        "cumulative_decrease_flag",
        "execution_over_100_flag",
        "budget_increase_extreme_flag",
        "budget_decrease_extreme_flag",
        "program_concentration_flag",
    ]
    result.loc[mask, "independent_signal_count"] = result.loc[mask, signal_columns].apply(
        lambda row: sum(bool(value) for value in row.fillna(False)), axis=1
    )
    result.loc[mask, "type_multiple_financial_signals"] = result.loc[
        mask, "independent_signal_count"
    ].ge(2)
    result.loc[mask, "active_signal_types"] = result.loc[mask].apply(
        lambda row: (
            ";".join(TYPE_LABELS[column] for column in TYPE_COLUMNS if bool(row[column])) or "NONE"
        ),
        axis=1,
    )
    return result, mask


def _queue(candidates: pd.DataFrame, stability: pd.DataFrame) -> pd.DataFrame:
    queue, _ = build_full_population_review_work_queue(candidates, stability)
    return queue


def _transitions(
    before: pd.DataFrame,
    after: pd.DataFrame,
    before_queue: pd.DataFrame,
    after_queue: pd.DataFrame,
    *,
    simulation: str,
) -> pd.DataFrame:
    identity = [
        "candidate_id",
        "ministry_code",
        "fiscal_year",
        "performance_program_name",
        "account_type",
        "account_original_budget",
    ]
    tracked = ["review_intensity", "review_candidate", "scenario_ranking_eligible"]
    result = before[identity + tracked].merge(
        after[["candidate_id", *tracked]],
        on="candidate_id",
        validate="one_to_one",
        suffixes=("_before", "_after"),
    )
    result = result.merge(
        before_queue[["candidate_id", "work_queue_order"]],
        on="candidate_id",
        validate="one_to_one",
    ).merge(
        after_queue[["candidate_id", "work_queue_order"]],
        on="candidate_id",
        validate="one_to_one",
        suffixes=("_before", "_after"),
    )
    changed = (
        result["review_intensity_before"].ne(result["review_intensity_after"])
        | result["review_candidate_before"].ne(result["review_candidate_after"])
        | result["scenario_ranking_eligible_before"].ne(result["scenario_ranking_eligible_after"])
    )
    result = result.loc[changed].copy()
    result.insert(0, "simulation", simulation)
    return result


def _changed_count(frame: pd.DataFrame, column: str) -> int:
    return int(frame[f"{column}_before"].ne(frame[f"{column}_after"]).sum())


def build_refactor_gate_d_impact(
    root: Path,
    *,
    output_dir: Path | None = None,
    overwrite: bool = False,
) -> tuple[dict[str, Any], tuple[Path, ...]]:
    """두 결과변경 P0를 그림자 재계산하고 나머지 P0의 현재 영향을 계수합니다."""
    root = root.resolve()
    output_dir = output_dir or root / "artifacts/refactor/gate_d"
    outputs = (
        output_dir / "impact_summary.json",
        output_dir / "risk_impact.csv",
        output_dir / "candidate_transitions.csv",
    )
    existing = [path for path in outputs if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"Gate D 산출물이 이미 있습니다: {existing[0]}")

    paths = PriorityScenarioPaths.multi_ministry_from_root(root)
    inputs = (
        paths.same_year_analysis,
        paths.financial_features,
        paths.feedback_cohorts,
        paths.program_financial,
        paths.config,
        paths.output_dir / "candidate_population.csv",
        paths.output_dir / "rank_stability.csv",
        paths.output_dir / "scenario_scores.csv",
        root / "data/processed/masters/project_year_financial_v2.parquet",
    )
    for path in inputs:
        if not path.is_file():
            raise FileNotFoundError(path)
    input_hashes = {str(path.relative_to(root)): _sha256(path) for path in inputs}

    candidates = pd.read_csv(
        paths.output_dir / "candidate_population.csv",
        dtype={"ministry_code": "string", "program_code": "string"},
        low_memory=False,
    )
    stability = pd.read_csv(
        paths.output_dir / "rank_stability.csv",
        dtype={"ministry_code": "string", "program_code": "string"},
        low_memory=False,
    )
    baseline_scores = pd.read_csv(
        paths.output_dir / "scenario_scores.csv",
        dtype={"ministry_code": "string", "program_code": "string"},
        low_memory=False,
    )
    baseline_queue = _queue(candidates, stability)

    future_candidates = _suppress_future_outcomes(candidates)
    future_queue = _queue(future_candidates, stability)
    future_transitions = _transitions(
        candidates,
        future_candidates,
        baseline_queue,
        future_queue,
        simulation="NO_FUTURE_OUTCOME",
    )

    features = pd.read_parquet(paths.financial_features)
    unknown_features, unknown_mask = _suppress_unknown_peer_signals(features)
    config = load_scenario_config(paths.config)
    scope = config["scope"]
    codes = tuple(str(code).zfill(3) for code in scope["ministry_codes"])
    analysis = pd.read_csv(
        paths.same_year_analysis,
        dtype={"ministry_code": "string", "program_code": "string"},
        low_memory=False,
    )
    cohorts = pd.read_csv(
        paths.feedback_cohorts,
        dtype={"ministry_code": "string", "program_code": "string"},
        low_memory=False,
    )
    program_financial = pd.read_parquet(paths.program_financial)
    program_signals = aggregate_program_account_signals(
        unknown_features,
        ministry_codes=codes,
        start_year=int(scope["start_year"]),
        end_year=int(scope["end_year"]),
    )
    feedback = aggregate_program_feedback(
        cohorts,
        unknown_features,
        ministry_codes=codes,
        start_year=int(scope["start_year"]),
        end_year=int(scope["end_year"]),
    )
    unknown_candidates = build_candidate_population(
        analysis, program_signals, config, feedback, program_financial
    )
    unknown_scores = score_scenarios(unknown_candidates, config)
    unknown_stability = build_rank_stability(unknown_candidates, unknown_scores, config)
    unknown_queue = _queue(unknown_candidates, unknown_stability)
    unknown_transitions = _transitions(
        candidates,
        unknown_candidates,
        baseline_queue,
        unknown_queue,
        simulation="NO_UNKNOWN_PEER_RELATIVE_SIGNAL",
    )

    score_comparison = baseline_scores[
        ["candidate_id", "scenario", "scenario_score", "scenario_rank_average"]
    ].merge(
        unknown_scores[["candidate_id", "scenario", "scenario_score", "scenario_rank_average"]],
        on=["candidate_id", "scenario"],
        how="inner",
        suffixes=("_before", "_after"),
    )
    score_changed = (
        score_comparison["scenario_score_before"]
        .sub(score_comparison["scenario_score_after"])
        .abs()
        .gt(1e-12)
    )
    rank_changed = score_comparison["scenario_rank_average_before"].ne(
        score_comparison["scenario_rank_average_after"]
    )

    kpi, pdf, performance_financial = _performance(root)
    normalized = "_gate_d_program_name"
    kpi = kpi.copy()
    kpi[normalized] = kpi["performance_program_name"].fillna("").str.replace(r"\s+", "", regex=True)
    performance_financial = performance_financial.copy()
    performance_financial[normalized] = (
        performance_financial["performance_program_name"]
        .fillna("")
        .str.replace(r"\s+", "", regex=True)
    )
    bridge = (
        kpi.groupby(["ministry_code", "fiscal_year", normalized], dropna=False)
        .agg(
            performance_goal_count=("program_goal_number", "nunique"),
            source_program_code_present=(
                "source_program_code",
                lambda values: values.notna().any(),
            ),
        )
        .reset_index()
    )
    bridge = bridge[bridge["performance_goal_count"].gt(1) & ~bridge["source_program_code_present"]]
    bridge_financial = (
        performance_financial.groupby(["ministry_code", "fiscal_year", normalized], dropna=False)
        .agg(
            bridge_financial_rows=("original_budget", "size"),
            bridge_budget_row_sum=("original_budget", "sum"),
            bridge_budget_once=("original_budget", "first"),
        )
        .reset_index()
    )
    bridge = bridge.merge(
        bridge_financial,
        on=["ministry_code", "fiscal_year", normalized],
        how="left",
        validate="one_to_one",
    )
    bridge["duplicated_amount"] = bridge["bridge_budget_row_sum"] - bridge["bridge_budget_once"]

    scoped_cohorts = cohorts[
        cohorts["ministry_code"].str.zfill(3).isin(MINISTRIES)
        & cohorts["base_fiscal_year"].isin(YEARS)
        & cohorts["outcome_fiscal_year"].isin(YEARS)
    ]
    feedback_blocked = scoped_cohorts[
        scoped_cohorts["cohort_exclusion_reason"].eq("BUDGET_CHANGE_NOT_ELIGIBLE_IN_CHAIN")
    ]
    v2 = _scope(pd.read_parquet(root / "data/processed/masters/project_year_financial_v2.parquet"))
    identity_columns = [
        "program_code",
        "activity_code",
        "subactivity_code",
        "program_name",
        "activity_name",
        "subactivity_name",
    ]
    blank_identity = v2[v2[identity_columns].isna().all(axis=1)]
    special_unmatched = candidates[
        candidates["account_type"].eq("SPECIAL_ACCOUNT")
        & ~candidates["account_financial_linkage_status"].eq("COMPLETE")
    ]
    kpi_ids = set(kpi["source_indicator_id"].astype(str))
    pdf_ids = set(pdf["source_indicator_id"].astype(str))
    fund_zero = v2[
        v2["account_type"].eq("FUND")
        & pd.to_numeric(v2["execution_denominator_amount"], errors="coerce").eq(0)
    ]
    fund_zero_ids = set(fund_zero["project_id"].astype(str))
    fund_candidate_mask = (
        candidates["source_project_ids"]
        .fillna("[]")
        .map(lambda value: bool(set(json.loads(value)) & fund_zero_ids))
    )

    transitions = pd.concat(
        [future_transitions, unknown_transitions], ignore_index=True
    ).convert_dtypes()
    unknown_lane_changed = _changed_count(unknown_transitions, "review_intensity")
    unknown_eligible_changed = _changed_count(unknown_transitions, "scenario_ranking_eligible")
    future_lane_changed = _changed_count(future_transitions, "review_intensity")
    risk_impact = pd.DataFrame(
        [
            {
                "risk_id": "P0-01",
                "risk": "future outcome leakage",
                "current_evidence": "2024 T+1 and 2023 T+2 use 2025 outcome budget",
                "candidate_lane_changed": future_lane_changed,
                "candidate_eligibility_changed": 0,
                "budget_of_lane_changed": pd.to_numeric(
                    future_transitions.loc[
                        future_transitions["review_intensity_before"].ne(
                            future_transitions["review_intensity_after"]
                        ),
                        "account_original_budget",
                    ],
                    errors="coerce",
                ).sum(),
                "recommended_action": "cut off outcome years after 2024",
            },
            {
                "risk_id": "P0-02/P0-08",
                "risk": "UNKNOWN peer group and mixed classification axes",
                "current_evidence": f"{int(unknown_mask.sum())} project-years",
                "candidate_lane_changed": unknown_lane_changed,
                "candidate_eligibility_changed": unknown_eligible_changed,
                "budget_of_lane_changed": pd.to_numeric(
                    unknown_transitions.loc[
                        unknown_transitions["review_intensity_before"].ne(
                            unknown_transitions["review_intensity_after"]
                        ),
                        "account_original_budget",
                    ],
                    errors="coerce",
                ).sum(),
                "recommended_action": "suppress peer-relative signals until instrument confirmed",
            },
            {
                "risk_id": "P0-03",
                "risk": "performance bridge amount duplication",
                "current_evidence": f"{len(bridge)} bridge programs",
                "candidate_lane_changed": 0,
                "candidate_eligibility_changed": 0,
                "budget_of_lane_changed": 0,
                "recommended_action": "remove amounts from the performance bridge",
            },
            {
                "risk_id": "P0-04",
                "risk": "feedback eligibility contamination",
                "current_evidence": f"{len(feedback_blocked)} blocked rows; 0 marked eligible",
                "candidate_lane_changed": 0,
                "candidate_eligibility_changed": 0,
                "budget_of_lane_changed": 0,
                "recommended_action": "retain cohort_eligible filter and regression test",
            },
            {
                "risk_id": "P0-05",
                "risk": "blank identity collision",
                "current_evidence": f"{len(blank_identity)} source rows; 0 candidate rows",
                "candidate_lane_changed": 0,
                "candidate_eligibility_changed": 0,
                "budget_of_lane_changed": 0,
                "recommended_action": "use core_v2 source-bound provisional IDs",
            },
            {
                "risk_id": "P0-06",
                "risk": "special-account grain mismatch",
                "current_evidence": f"{len(special_unmatched)} DATA_FIRST rows",
                "candidate_lane_changed": 0,
                "candidate_eligibility_changed": 0,
                "budget_of_lane_changed": 0,
                "recommended_action": "keep DATA_FIRST until account detail reconciles",
            },
            {
                "risk_id": "P0-07",
                "risk": "recoverable PDF evidence detached",
                "current_evidence": f"{len(pdf_ids - kpi_ids)} detached of {len(pdf_ids)} PDF IDs",
                "candidate_lane_changed": 0,
                "candidate_eligibility_changed": 0,
                "budget_of_lane_changed": 0,
                "recommended_action": "reuse core_v2 evidence links",
            },
            {
                "risk_id": "P0-09",
                "risk": "fund denominator unavailable",
                "current_evidence": f"{len(fund_zero)} project-years; {int(fund_candidate_mask.sum())} candidates",
                "candidate_lane_changed": 0,
                "candidate_eligibility_changed": 0,
                "budget_of_lane_changed": 0,
                "recommended_action": "keep affected candidates in DATA_FIRST",
            },
        ]
    ).convert_dtypes()

    summary: dict[str, Any] = {
        "scope": {"ministry_codes": list(MINISTRIES), "fiscal_years": list(YEARS)},
        "baseline": {
            "candidate_rows": len(candidates),
            "review_candidate_rows": int(_bool(candidates, "review_candidate").sum()),
            "scenario_ranking_eligible_rows": int(
                _bool(candidates, "scenario_ranking_eligible").sum()
            ),
        },
        "future_outcome_shadow": {
            "future_outcome_exposed_candidate_horizons": int(
                (
                    candidates["fiscal_year"].eq(2024)
                    & _bool(candidates, "program_total_feedback_complete_t1")
                ).sum()
                + (
                    candidates["fiscal_year"].eq(2023)
                    & _bool(candidates, "program_total_feedback_complete_t2")
                ).sum()
            ),
            "future_outcome_signal_rows": int(
                (
                    candidates["fiscal_year"].eq(2024)
                    & (
                        _bool(candidates, "low_performance_budget_increase_t1")
                        | _bool(candidates, "good_performance_budget_decrease_t1")
                    )
                ).sum()
                + (
                    candidates["fiscal_year"].eq(2023)
                    & (
                        _bool(candidates, "low_performance_budget_increase_t2")
                        | _bool(candidates, "good_performance_budget_decrease_t2")
                    )
                ).sum()
            ),
            "lane_changed_rows": future_lane_changed,
            "review_candidates_removed": int(
                (
                    _bool(future_transitions, "review_candidate_before")
                    & ~_bool(future_transitions, "review_candidate_after")
                ).sum()
            ),
            "queue_order_changed_rows": int(
                baseline_queue.set_index("candidate_id")["work_queue_order"]
                .ne(future_queue.set_index("candidate_id")["work_queue_order"])
                .sum()
            ),
        },
        "unknown_peer_shadow": {
            "unknown_project_year_rows": int(unknown_mask.sum()),
            "lane_changed_rows": unknown_lane_changed,
            "scenario_eligibility_changed_rows": unknown_eligible_changed,
            "queue_order_changed_rows": int(
                baseline_queue.set_index("candidate_id")["work_queue_order"]
                .ne(unknown_queue.set_index("candidate_id")["work_queue_order"])
                .sum()
            ),
            "scenario_score_changed_candidates": int(
                score_comparison.loc[score_changed, "candidate_id"].nunique()
            ),
            "scenario_rank_changed_candidates": int(
                score_comparison.loc[rank_changed, "candidate_id"].nunique()
            ),
            "maximum_absolute_rank_shift": float(
                score_comparison["scenario_rank_average_before"]
                .sub(score_comparison["scenario_rank_average_after"])
                .abs()
                .max()
            ),
        },
        "other_p0_checks": {
            "bridge_programs": len(bridge),
            "bridge_duplicated_amount": float(bridge["duplicated_amount"].fillna(0).sum()),
            "feedback_blocked_rows": len(feedback_blocked),
            "feedback_blocked_rows_marked_eligible": int(
                _bool(feedback_blocked, "cohort_eligible").sum()
            ),
            "blank_identity_rows": len(blank_identity),
            "special_account_unmatched_candidate_rows": len(special_unmatched),
            "pdf_evidence_ids": len(pdf_ids),
            "pdf_evidence_detached_ids": len(pdf_ids - kpi_ids),
            "fund_zero_denominator_project_year_rows": len(fund_zero),
            "fund_zero_denominator_candidate_rows": int(fund_candidate_mask.sum()),
        },
        "decision_boundary": {
            "production_outputs_changed": False,
            "final_policy_rank_generated": False,
            "requires_user_approval_before_production_change": True,
        },
        "input_sha256": input_hashes,
    }
    if {str(path.relative_to(root)): _sha256(path) for path in inputs} != input_hashes:
        raise ValueError("Gate D 입력 파일이 실행 중 변경되었습니다.")

    output_dir.mkdir(parents=True, exist_ok=True)
    risk_impact.to_csv(outputs[1], index=False, encoding="utf-8-sig")
    transitions.to_csv(outputs[2], index=False, encoding="utf-8-sig")
    outputs[0].write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary, outputs
