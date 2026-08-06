from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pandas as pd

from analytics.mss_priority_scenario_analysis import (
    _current_execution_severity,
    apply_question_review_grades,
)

ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "data/analytics/multi_ministry_priority_scenarios/program_year_review_queue.csv"
EXPECTED_SHA256 = "d7c59cc14da21f0e669f2e09867766100957ddad68f8600b43d64392c6236a96"
GRADES = ["A", "B", "C", "D", "H"]
GRADE_DISTANCE = {"A": 0, "B": 1, "C": 2, "D": 3}
BASELINE_THRESHOLDS = {
    "execution_strong": 0.80,
    "execution_moderate": 0.90,
    "budget_increase_cutoff": 0.0,
    "budget_decrease_cutoff": 0.0,
}
SENSITIVITY_SCENARIOS = [
    {"scenario_id": "baseline", **BASELINE_THRESHOLDS},
    {
        "scenario_id": "execution_strong_minus_5pp",
        **BASELINE_THRESHOLDS,
        "execution_strong": 0.75,
    },
    {
        "scenario_id": "execution_strong_plus_5pp",
        **BASELINE_THRESHOLDS,
        "execution_strong": 0.85,
    },
    {
        "scenario_id": "execution_moderate_minus_5pp",
        **BASELINE_THRESHOLDS,
        "execution_moderate": 0.85,
    },
    {
        "scenario_id": "execution_moderate_plus_5pp",
        **BASELINE_THRESHOLDS,
        "execution_moderate": 0.95,
    },
    {
        "scenario_id": "budget_increase_stricter_5pp",
        **BASELINE_THRESHOLDS,
        "budget_increase_cutoff": 0.05,
    },
    {
        "scenario_id": "budget_decrease_stricter_5pp",
        **BASELINE_THRESHOLDS,
        "budget_decrease_cutoff": -0.05,
    },
]
ABLATIONS = (
    "execution",
    "reported_performance",
    "budget_performance_mismatch",
    "repetition",
)


def load_baseline() -> pd.DataFrame:
    actual_hash = hashlib.sha256(QUEUE_PATH.read_bytes()).hexdigest()
    if actual_hash != EXPECTED_SHA256:
        raise RuntimeError(f"기준 CSV SHA가 다릅니다: {actual_hash}")
    frame = pd.read_csv(
        QUEUE_PATH,
        dtype={"ministry_code": "string", "program_code": "string"},
    )
    if frame.shape != (236, 91):
        raise RuntimeError(f"기준 CSV 크기가 다릅니다: {frame.shape}")
    if frame["program_year_id"].duplicated().any():
        raise RuntimeError("기준 CSV의 program_year_id가 중복되었습니다.")
    return frame


def shadow_grade(
    baseline: pd.DataFrame,
    *,
    execution_strong: float = 0.80,
    execution_moderate: float = 0.90,
    budget_increase_cutoff: float = 0.0,
    budget_decrease_cutoff: float = 0.0,
) -> pd.DataFrame:
    if not 0 <= execution_strong < execution_moderate <= 1:
        raise ValueError("집행 임계값은 0 <= strong < moderate <= 1이어야 합니다.")
    result = baseline.copy()
    result["current_execution_severity"] = _current_execution_severity(
        result["program_execution_rate"],
        strong=execution_strong,
        moderate=execution_moderate,
    )

    result = result.sort_values(["program_identity_id", "fiscal_year", "program_year_id"]).copy()
    history = result.groupby("program_identity_id", sort=False, dropna=False)
    previous_year = history["fiscal_year"].shift()
    consecutive = result["fiscal_year"].sub(previous_year).eq(1)
    current_low = result["current_execution_severity"].fillna(0).gt(0)
    previous_low = history["current_execution_severity"].shift().fillna(0).gt(0)
    result["repeated_low_execution_signal"] = current_low & previous_low & consecutive

    budget_change = pd.to_numeric(result["program_budget_change_rate"], errors="coerce")
    result["budget_increase_context_signal"] = budget_change.gt(budget_increase_cutoff)
    result["budget_decrease_context_signal"] = budget_change.lt(budget_decrease_cutoff)
    comparable = pd.to_numeric(result["comparable_rate_count"], errors="coerce")
    performance_miss = result["performance_signal"].fillna(False).astype(bool)
    target_met = comparable.gt(0) & ~performance_miss
    result["budget_mismatch_signal"] = (
        performance_miss & result["budget_increase_context_signal"]
    ) | (target_met & result["budget_decrease_context_signal"])
    result["budget_performance_mismatch"] = result["budget_mismatch_signal"].astype(float)

    graded = apply_question_review_grades(result)
    return graded.sort_values("program_year_id").reset_index(drop=True)


def reproduce_baseline(baseline: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    shadow = shadow_grade(baseline)
    production = baseline.sort_values("program_year_id").reset_index(drop=True)
    reproduction = pd.DataFrame(
        {
            "program_year_id": production["program_year_id"],
            "production_review_grade": production["review_grade"],
            "shadow_review_grade": shadow["review_grade"],
        }
    )
    reproduction["match"] = reproduction["production_review_grade"].eq(
        reproduction["shadow_review_grade"]
    )
    reproduction["mismatch_reason"] = reproduction["match"].map(
        {True: "", False: "SHADOW_GRADE_DIFFERS"}
    )
    if not reproduction["match"].all():
        raise RuntimeError(f"shadow 기준 재현 불일치 {int((~reproduction['match']).sum())}행")
    if (
        production["review_grade"].value_counts().to_dict()
        != shadow["review_grade"].value_counts().to_dict()
    ):
        raise RuntimeError("shadow 전체 등급 분포가 생산 분포와 다릅니다.")
    production_2024 = production.loc[production["fiscal_year"].eq(2024), "review_grade"]
    shadow_2024 = shadow.loc[shadow["fiscal_year"].eq(2024), "review_grade"]
    if production_2024.value_counts().to_dict() != shadow_2024.value_counts().to_dict():
        raise RuntimeError("shadow 2024년 등급 분포가 생산 분포와 다릅니다.")
    return shadow, reproduction


def threshold_inventory(baseline: pd.DataFrame) -> pd.DataFrame:
    non_h = baseline["review_grade"].ne("H")
    execution = pd.to_numeric(baseline["program_execution_rate"], errors="coerce")
    budget_change = pd.to_numeric(baseline["program_budget_change_rate"], errors="coerce")
    comparable = pd.to_numeric(baseline["comparable_rate_count"], errors="coerce")
    rows = [
        {
            "threshold_name": "execution_strong",
            "current_value": 0.80,
            "unit": "execution_rate",
            "source_file": "configs/priority_scenarios.yaml; src/analytics/mss_priority_scenario_analysis.py",
            "source_function": "_current_execution_severity; build_program_year_review_queue",
            "affected_signal_family": "execution",
            "affected_grade_path": "B strong-single condition and severity display",
            "raw_input_columns": "program_execution_rate",
            "fixed_csv_recomputable": True,
            "eligible_program_year_count": int((non_h & execution.notna()).sum()),
            "boundary_case_count": int((non_h & execution.ge(0.75) & execution.lt(0.85)).sum()),
            "excluded_reason": "",
        },
        {
            "threshold_name": "execution_moderate",
            "current_value": 0.90,
            "unit": "execution_rate",
            "source_file": "configs/priority_scenarios.yaml; src/analytics/mss_priority_scenario_analysis.py",
            "source_function": "_current_execution_severity; build_program_year_review_queue",
            "affected_signal_family": "execution;repetition",
            "affected_grade_path": "current execution signal, consecutive low execution, special C/A/B/C",
            "raw_input_columns": "program_execution_rate;program_identity_id;fiscal_year",
            "fixed_csv_recomputable": True,
            "eligible_program_year_count": int((non_h & execution.notna()).sum()),
            "boundary_case_count": int((non_h & execution.ge(0.85) & execution.lt(0.95)).sum()),
            "excluded_reason": "",
        },
        {
            "threshold_name": "budget_increase_cutoff",
            "current_value": 0.0,
            "unit": "budget_change_rate",
            "source_file": "src/analytics/mss_priority_scenario_analysis.py",
            "source_function": "build_program_year_review_queue",
            "affected_signal_family": "budget_performance_mismatch",
            "affected_grade_path": "repeated miss plus budget increase A; mismatch C",
            "raw_input_columns": "program_budget_change_rate;performance_signal;reported_target_miss_consecutive",
            "fixed_csv_recomputable": True,
            "eligible_program_year_count": int((non_h & budget_change.notna()).sum()),
            "boundary_case_count": int(
                (non_h & budget_change.gt(0) & budget_change.le(0.05)).sum()
            ),
            "excluded_reason": "",
        },
        {
            "threshold_name": "budget_decrease_cutoff",
            "current_value": 0.0,
            "unit": "budget_change_rate",
            "source_file": "src/analytics/mss_priority_scenario_analysis.py",
            "source_function": "build_program_year_review_queue",
            "affected_signal_family": "budget_performance_mismatch",
            "affected_grade_path": "target met plus budget decrease mismatch C",
            "raw_input_columns": "program_budget_change_rate;performance_signal;comparable_rate_count",
            "fixed_csv_recomputable": True,
            "eligible_program_year_count": int((non_h & budget_change.notna()).sum()),
            "boundary_case_count": int(
                (non_h & budget_change.ge(-0.05) & budget_change.lt(0)).sum()
            ),
            "excluded_reason": "",
        },
        {
            "threshold_name": "reported_target_achievement_rate",
            "current_value": 100.0,
            "unit": "percent",
            "source_file": "src/analytics/mss_same_year_budget_check.py",
            "source_function": "aggregate_performance_program_year",
            "affected_signal_family": "reported_performance",
            "affected_grade_path": "performance miss and target-met conflict rules",
            "raw_input_columns": "analysis_official_achievement_rate_numeric (not in fixed CSV)",
            "fixed_csv_recomputable": False,
            "eligible_program_year_count": int((non_h & comparable.gt(0)).sum()),
            "boundary_case_count": 0,
            "excluded_reason": "indicator-level raw rates are absent; boolean/count status must not be reverse engineered",
        },
        {
            "threshold_name": "reported_miss_count_minimum",
            "current_value": 1.0,
            "unit": "indicator_count",
            "source_file": "src/analytics/mss_priority_scenario_analysis.py",
            "source_function": "build_program_year_review_queue",
            "affected_signal_family": "reported_performance",
            "affected_grade_path": "performance_signal",
            "raw_input_columns": "below_target_count",
            "fixed_csv_recomputable": True,
            "eligible_program_year_count": int((non_h & comparable.gt(0)).sum()),
            "boundary_case_count": int((non_h & baseline["below_target_count"].isin([0, 1])).sum()),
            "excluded_reason": "integer +/-1 changes the construct: zero would become a miss or two misses would be required",
        },
        {
            "threshold_name": "comparable_rate_minimum",
            "current_value": 1.0,
            "unit": "indicator_count",
            "source_file": "src/analytics/mss_priority_scenario_analysis.py",
            "source_function": "apply_question_review_grades",
            "affected_signal_family": "data_quality_abstention",
            "affected_grade_path": "H versus special C",
            "raw_input_columns": "comparable_rate_count",
            "fixed_csv_recomputable": True,
            "eligible_program_year_count": int(non_h.sum()),
            "boundary_case_count": int(baseline["comparable_rate_count"].isin([0, 1]).sum()),
            "excluded_reason": "H and comparability are fixed by analysis scope",
        },
        {
            "threshold_name": "consecutive_year_gap",
            "current_value": 1.0,
            "unit": "fiscal_year",
            "source_file": "src/analytics/mss_priority_scenario_analysis.py",
            "source_function": "build_program_year_review_queue",
            "affected_signal_family": "repetition",
            "affected_grade_path": "repeated execution and repeated performance",
            "raw_input_columns": "program_identity_id;fiscal_year",
            "fixed_csv_recomputable": True,
            "eligible_program_year_count": int(non_h.sum()),
            "boundary_case_count": 0,
            "excluded_reason": "adjacent-year identity is a time contract, not a tunable numeric threshold",
        },
        {
            "threshold_name": "m3_year_end_q4_december",
            "current_value": "0.40;0.20",
            "unit": "expenditure_share",
            "source_file": "src/analytics/m3_financial_signals.py",
            "source_function": "build_financial_signal_features",
            "affected_signal_family": "context",
            "affected_grade_path": "none; display-only context",
            "raw_input_columns": "q4_expenditure_share;december_single_month_share (not in fixed CSV)",
            "fixed_csv_recomputable": False,
            "eligible_program_year_count": 0,
            "boundary_case_count": 0,
            "excluded_reason": "raw monthly inputs are absent and context-only does not determine grade",
        },
        {
            "threshold_name": "m3_repetition_2plus_50pct",
            "current_value": "2;0.50",
            "unit": "year_count;valid_year_share",
            "source_file": "src/analytics/m3_financial_signals.py",
            "source_function": "build_repeated_signals; attach_signal_types",
            "affected_signal_family": "upstream project-level repetition",
            "affected_grade_path": "none in final program-year recomputation",
            "raw_input_columns": "project-year histories (not in fixed CSV)",
            "fixed_csv_recomputable": False,
            "eligible_program_year_count": 0,
            "boundary_case_count": 0,
            "excluded_reason": "final queue resets account-type repeat shares and recomputes adjacent program-year repetition",
        },
        {
            "threshold_name": "target_adequacy_pair",
            "current_value": "boolean AND boolean",
            "unit": "logical condition",
            "source_file": "src/analytics/mss_priority_scenario_analysis.py",
            "source_function": "apply_question_review_grades",
            "affected_signal_family": "target_or_trend",
            "affected_grade_path": "C target adequacy",
            "raw_input_columns": "repeated_target_overachievement;target_unchanged",
            "fixed_csv_recomputable": False,
            "eligible_program_year_count": 0,
            "boundary_case_count": 0,
            "excluded_reason": "both fixed-CSV fields are false and no raw target history exists for threshold variation",
        },
    ]
    return pd.DataFrame(rows)


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def _transition_rows(
    scenario_id: str,
    production: pd.Series,
    shadow: pd.Series,
) -> list[dict[str, Any]]:
    table = pd.crosstab(production, shadow).reindex(index=GRADES, columns=GRADES, fill_value=0)
    return [
        {
            "scenario_id": scenario_id,
            "production_review_grade": source,
            "shadow_review_grade": target,
            "program_year_count": int(table.loc[source, target]),
        }
        for source in GRADES
        for target in GRADES
    ]


def sensitivity_analysis(
    baseline: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    production = baseline.sort_values("program_year_id").reset_index(drop=True)
    non_h = production["review_grade"].ne("H")
    baseline_ab = set(
        production.loc[production["review_grade"].isin(["A", "B"]), "program_year_id"]
    )
    baseline_2024_ab = set(
        production.loc[
            production["fiscal_year"].eq(2024) & production["review_grade"].isin(["A", "B"]),
            "program_year_id",
        ]
    )
    summaries: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    boundary_rows: list[dict[str, Any]] = []
    scenario_frames: dict[str, pd.DataFrame] = {}

    for scenario in SENSITIVITY_SCENARIOS:
        scenario_id = str(scenario["scenario_id"])
        shadow = shadow_grade(
            production,
            execution_strong=float(scenario["execution_strong"]),
            execution_moderate=float(scenario["execution_moderate"]),
            budget_increase_cutoff=float(scenario["budget_increase_cutoff"]),
            budget_decrease_cutoff=float(scenario["budget_decrease_cutoff"]),
        )
        scenario_frames[scenario_id] = shadow
        production_grade = production["review_grade"]
        shadow_grade_values = shadow["review_grade"]
        if not shadow.loc[production_grade.eq("H"), "review_grade"].eq("H").all():
            raise RuntimeError(f"{scenario_id}에서 H 고정 계약이 깨졌습니다.")
        distances = pd.Series(pd.NA, index=production.index, dtype="Int64")
        distances.loc[non_h] = (
            production_grade.loc[non_h].map(GRADE_DISTANCE)
            - shadow_grade_values.loc[non_h].map(GRADE_DISTANCE)
        ).abs()
        shadow_ab = set(shadow.loc[shadow_grade_values.isin(["A", "B"]), "program_year_id"])
        shadow_2024 = shadow.loc[shadow["fiscal_year"].eq(2024)]
        changed_2024_ab = sum(
            production.set_index("program_year_id").loc[item, "review_grade"]
            != shadow.set_index("program_year_id").loc[item, "review_grade"]
            for item in baseline_2024_ab
        )
        varied = [
            name
            for name, current in BASELINE_THRESHOLDS.items()
            if float(scenario[name]) != current
        ]
        threshold_name = varied[0] if varied else "baseline"
        current_value = BASELINE_THRESHOLDS.get(threshold_name, pd.NA)
        shadow_value = scenario.get(threshold_name, pd.NA)
        summaries.append(
            {
                "scenario_id": scenario_id,
                "threshold_name": threshold_name,
                "current_value": current_value,
                "shadow_value": shadow_value,
                **{f"{grade}_count": int(shadow_grade_values.eq(grade).sum()) for grade in GRADES},
                "ad_eligible_count": int(non_h.sum()),
                "unchanged_ad_count": int(
                    (
                        production_grade.loc[non_h].to_numpy()
                        == shadow_grade_values.loc[non_h].to_numpy()
                    ).sum()
                ),
                "grade_retention_rate": float(
                    (
                        production_grade.loc[non_h].to_numpy()
                        == shadow_grade_values.loc[non_h].to_numpy()
                    ).mean()
                ),
                "one_step_move_count": int(distances.eq(1).sum()),
                "two_or_more_step_move_count": int(distances.ge(2).sum()),
                "a_to_d_or_d_to_a_count": int(distances.eq(3).sum()),
                "baseline_ab_count": len(baseline_ab),
                "shadow_ab_count": len(shadow_ab),
                "ab_jaccard": _jaccard(baseline_ab, shadow_ab),
                "baseline_2024_ab_count": len(baseline_2024_ab),
                "changed_2024_baseline_ab_count": changed_2024_ab,
                "shadow_2024_ab_count": int(shadow_2024["review_grade"].isin(["A", "B"]).sum()),
                "h_transition_count": int(
                    production_grade.eq("H").ne(shadow_grade_values.eq("H")).sum()
                ),
            }
        )
        transitions.extend(_transition_rows(scenario_id, production_grade, shadow_grade_values))

        if scenario_id == "baseline":
            continue
        raw_column = (
            "program_execution_rate"
            if threshold_name.startswith("execution")
            else "program_budget_change_rate"
        )
        signal_columns = {
            "execution_strong": ["current_execution_severity"],
            "execution_moderate": [
                "current_execution_severity",
                "repeated_low_execution_signal",
            ],
            "budget_increase_cutoff": [
                "budget_increase_context_signal",
                "budget_mismatch_signal",
            ],
            "budget_decrease_cutoff": [
                "budget_decrease_context_signal",
                "budget_mismatch_signal",
            ],
        }[threshold_name]
        baseline_shadow = scenario_frames["baseline"]
        signal_changed = pd.Series(False, index=production.index)
        for column in signal_columns:
            signal_changed |= (
                baseline_shadow[column].astype("string").ne(shadow[column].astype("string"))
            )
        for index in production.index[signal_changed & non_h]:
            boundary_rows.append(
                {
                    "scenario_id": scenario_id,
                    "threshold_name": threshold_name,
                    "current_value": current_value,
                    "shadow_value": shadow_value,
                    "program_year_id": production.loc[index, "program_year_id"],
                    "fiscal_year": int(production.loc[index, "fiscal_year"]),
                    "performance_program_name": production.loc[index, "performance_program_name"],
                    "raw_input_column": raw_column,
                    "raw_input_value": production.loc[index, raw_column],
                    "changed_signal_columns": ";".join(
                        column
                        for column in signal_columns
                        if str(baseline_shadow.loc[index, column]) != str(shadow.loc[index, column])
                    ),
                    "production_review_grade": production.loc[index, "review_grade"],
                    "shadow_review_grade": shadow.loc[index, "review_grade"],
                    "grade_changed": bool(
                        production.loc[index, "review_grade"] != shadow.loc[index, "review_grade"]
                    ),
                }
            )

    sensitivity = pd.DataFrame(summaries)
    transition_frame = pd.DataFrame(transitions)
    boundaries = pd.DataFrame(boundary_rows)
    scenario_grades = pd.DataFrame(
        {scenario_id: frame["review_grade"] for scenario_id, frame in scenario_frames.items()}
    )
    stability = production[
        [
            "program_year_id",
            "ministry_code",
            "fiscal_year",
            "performance_program_name",
            "review_grade",
        ]
    ].rename(columns={"review_grade": "production_review_grade"})
    stability = pd.concat([stability, scenario_grades.add_prefix("grade__")], axis=1)
    variant_columns = [
        f"grade__{scenario['scenario_id']}"
        for scenario in SENSITIVITY_SCENARIOS
        if scenario["scenario_id"] != "baseline"
    ]
    stability["unchanged_variant_count"] = (
        stability[variant_columns].eq(stability["production_review_grade"], axis=0).sum(axis=1)
    )
    stability["variant_count"] = len(variant_columns)
    stability["grade_stability"] = stability["unchanged_variant_count"] / stability["variant_count"]
    stability["stable_across_all_variants"] = stability["unchanged_variant_count"].eq(
        stability["variant_count"]
    )
    stability["baseline_ab"] = stability["production_review_grade"].isin(["A", "B"])
    stability["h_fixed_not_distance_scored"] = stability["production_review_grade"].eq("H")
    return sensitivity, stability, transition_frame, boundaries, scenario_frames


def apply_ablation(baseline: pd.DataFrame, family: str) -> pd.DataFrame:
    result = baseline.copy()
    if family == "execution":
        result["current_execution_severity"] = 0.0
        result["repeated_low_execution_signal"] = False
        result["type_repeated_strong_low_execution_budget_share"] = 0.0
        result["type_repeated_moderate_low_execution_budget_share"] = 0.0
        result["execution_management"] = 0.0
    elif family == "reported_performance":
        comparable = pd.to_numeric(result["comparable_rate_count"], errors="coerce")
        comparable_rows = comparable.gt(0)
        result.loc[comparable_rows, "performance_signal"] = False
        result.loc[comparable_rows, "below_target_count"] = 0
        result.loc[comparable_rows, "reported_target_status"] = "ALL_COMPARABLE_AT_OR_ABOVE_TARGET"
        result["reported_target_miss_consecutive"] = False
    elif family == "budget_performance_mismatch":
        result["budget_mismatch_signal"] = False
        result["budget_performance_mismatch"] = 0.0
        result["budget_increase_context_signal"] = False
    elif family == "repetition":
        result["repeated_low_execution_signal"] = False
        result["type_repeated_strong_low_execution_budget_share"] = 0.0
        result["type_repeated_moderate_low_execution_budget_share"] = 0.0
        result["reported_target_miss_consecutive"] = False
    else:
        raise ValueError(f"알 수 없는 신호 제거 계열: {family}")

    graded = apply_question_review_grades(result)
    graded = graded.sort_values("program_year_id").reset_index(drop=True)
    production = baseline.sort_values("program_year_id").reset_index(drop=True)
    if not graded.loc[production["review_grade"].eq("H"), "review_grade"].eq("H").all():
        raise RuntimeError(f"{family} 제거에서 H 고정 계약이 깨졌습니다.")
    return graded


def ablation_analysis(
    baseline: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    production = baseline.sort_values("program_year_id").reset_index(drop=True)
    baseline_ab = production["review_grade"].isin(["A", "B"])
    ablation_frames: dict[str, pd.DataFrame] = {}
    case_rows: list[dict[str, Any]] = []

    for family in ABLATIONS:
        shadow = apply_ablation(production, family)
        ablation_frames[family] = shadow
        for index, row in production.iterrows():
            shadow_grade = shadow.loc[index, "review_grade"]
            case_rows.append(
                {
                    "signal_family_removed": family,
                    "program_year_id": row["program_year_id"],
                    "ministry_code": row["ministry_code"],
                    "fiscal_year": int(row["fiscal_year"]),
                    "performance_program_name": row["performance_program_name"],
                    "production_review_grade": row["review_grade"],
                    "shadow_review_grade": shadow_grade,
                    "grade_changed": bool(row["review_grade"] != shadow_grade),
                    "baseline_ab": bool(row["review_grade"] in {"A", "B"}),
                    "shadow_ab": bool(shadow_grade in {"A", "B"}),
                    "left_ab": bool(
                        row["review_grade"] in {"A", "B"} and shadow_grade not in {"A", "B"}
                    ),
                    "new_a": bool(row["review_grade"] != "A" and shadow_grade == "A"),
                    "new_b": bool(row["review_grade"] != "B" and shadow_grade == "B"),
                    "baseline_grade_trigger_signal_families": row["grade_trigger_signal_families"],
                    "shadow_grade_trigger_signal_families": shadow.loc[
                        index, "grade_trigger_signal_families"
                    ],
                    "baseline_independent_signal_family_count": int(
                        row["independent_signal_family_count"]
                    ),
                    "is_2024_baseline_ab": bool(
                        row["fiscal_year"] == 2024 and row["review_grade"] in {"A", "B"}
                    ),
                }
            )

    cases = pd.DataFrame(case_rows)
    exit_counts = (
        cases.loc[cases["left_ab"]].groupby("program_year_id")["signal_family_removed"].nunique()
    )
    cases["ab_exit_family_count"] = cases["program_year_id"].map(exit_counts).fillna(0).astype(int)
    cases["single_family_dependent_ab"] = cases["left_ab"] & cases["ab_exit_family_count"].eq(1)

    summaries: list[dict[str, Any]] = []
    for family in ABLATIONS:
        part = cases.loc[cases["signal_family_removed"].eq(family)]
        a_baseline = part["production_review_grade"].eq("A")
        repetition_a_moves = (
            part.loc[a_baseline, "shadow_review_grade"].value_counts().to_dict()
            if family == "repetition"
            else {}
        )
        summaries.append(
            {
                "signal_family_removed": family,
                "program_year_count": len(part),
                "grade_changed_count": int(part["grade_changed"].sum()),
                "ab_exit_count": int(part["left_ab"].sum()),
                "new_a_count": int(part["new_a"].sum()),
                "new_b_count": int(part["new_b"].sum()),
                "c_to_d_or_d_to_c_count": int(
                    (
                        part[["production_review_grade", "shadow_review_grade"]]
                        .apply(tuple, axis=1)
                        .isin([("C", "D"), ("D", "C")])
                    ).sum()
                ),
                "single_family_dependent_ab_count": int(part["single_family_dependent_ab"].sum()),
                "baseline_single_trigger_family_ab_count": int(
                    (baseline_ab & production["independent_signal_family_count"].eq(1)).sum()
                ),
                "changed_2024_baseline_ab_count": int(
                    (part["is_2024_baseline_ab"] & part["grade_changed"]).sum()
                ),
                "repetition_removed_a_to_a": int(repetition_a_moves.get("A", 0)),
                "repetition_removed_a_to_b": int(repetition_a_moves.get("B", 0)),
                "repetition_removed_a_to_c": int(repetition_a_moves.get("C", 0)),
                "repetition_removed_a_to_d": int(repetition_a_moves.get("D", 0)),
                "interpretation": "grade signal dependency, not feature importance",
            }
        )
    return pd.DataFrame(summaries), cases, ablation_frames


def explanation_precedence_issue(baseline: pd.DataFrame) -> str:
    affected_ids = ["075:3800:2023", "075:4100:2023", "075:4000:2023"]
    affected = baseline.loc[baseline["program_year_id"].isin(affected_ids)]
    table_rows = "\n".join(
        f"| `{row.program_year_id}` | A | 반복 저집행+목표미달 | 연속 목표미달+예산 증가 | `{row.diagnostic_type}` |"
        for row in affected.itertuples()
    )
    return f"""# 설명 precedence 결함

## 결론

제출 전 수정 우선순위는 **권장**입니다. 생산 등급과 대기열 순서는 정확히 유지되지만,
복수 A 근거 중 하나가 설명 필드에서 소실되어 원문 검토자가 근거를 불완전하게 볼 수 있습니다.

## 영향 3행

| program_year_id | 등급 | 동시에 성립한 A 조건 1 | 동시에 성립한 A 조건 2 | 최종 표시 진단 |
|---|---|---|---|---|
{table_rows}

세 행 모두 `REPEATED_LOW_EXECUTION_WITH_REPORTED_TARGET_MISS`와
`REPEATED_REPORTED_TARGET_MISS_WITH_BUDGET_INCREASE`가 동시에 성립합니다. 코드의 후행
할당 때문에 최종 `diagnostic_type`과 이를 복사한 `grade_reason_codes`에는 두 번째 사유만
남습니다.

## 영향 범위

- `review_grade`: 영향 없음
- 등급 precedence: 영향 없음
- 대기열 순서: 영향 없음
- `diagnostic_type`: 앞선 사유 소실
- `grade_reason_codes`: `diagnostic_type` 복사값이므로 앞선 사유 소실
- `next_review_question`: 현재 세 행은 A 공통 질문을 사용하므로 영향 없음
- 특례 C: 복수 조건이 겹치면 후행 다년도 진단이 질문까지 덮어쓸 잠재 가능성이 있으나 현재 생산 236행 중복 사례는 0건

## 생산 CSV를 바꾸지 않는 보존안

현재 제출 기준 CSV는 유지합니다. 후속 UI에서는 원시 신호 필드로 두 A 조건을 각각 표시하고
기존 `diagnostic_type`을 primary 진단으로 유지할 수 있습니다. 다음 출력 스키마에서는
`grade_reason_codes_all`을 순서가 있는 배열로 추가하거나, `program_year_id × reason_code`
하위 테이블에 `is_primary`와 `precedence_order`를 두는 방식이 더 안전합니다. UI에서 문자열만
재추론하는 방식은 코드와 표시 로직이 다시 어긋날 수 있으므로 임시 방편으로만 사용합니다.
"""


def _grade_count_text(frame: pd.DataFrame) -> str:
    return " ".join(f"{grade} {int(frame[f'{grade}_count'])}" for grade in GRADES)


def robustness_report(
    sensitivity: pd.DataFrame,
    stability: pd.DataFrame,
    boundaries: pd.DataFrame,
    ablation_summary: pd.DataFrame,
    ablation_cases: pd.DataFrame,
) -> str:
    variants = sensitivity.loc[sensitivity["scenario_id"].ne("baseline")]
    retention_min = variants["grade_retention_rate"].min()
    retention_max = variants["grade_retention_rate"].max()
    jaccard_min = variants["ab_jaccard"].min()
    jaccard_max = variants["ab_jaccard"].max()
    extreme = int(variants["a_to_d_or_d_to_a_count"].sum())
    scenario_lines = "\n".join(
        f"| `{row.scenario_id}` | {_grade_count_text(row)} | {row.grade_retention_rate:.3f} | {row.ab_jaccard:.3f} | {int(row.changed_2024_baseline_ab_count)} |"
        for _, row in variants.iterrows()
    )
    ablation_lines = "\n".join(
        f"| `{row.signal_family_removed}` | {int(row.grade_changed_count)} | {int(row.ab_exit_count)} | {int(row.new_a_count)} | {int(row.new_b_count)} | {int(row.c_to_d_or_d_to_c_count)} |"
        for row in ablation_summary.itertuples()
    )
    top_unstable = stability.loc[
        ~stability["stable_across_all_variants"] & stability["production_review_grade"].ne("H")
    ]
    dependent = ablation_cases.loc[ablation_cases["single_family_dependent_ab"]]
    dependent_ids = (
        ", ".join(f"`{item}`" for item in dependent["program_year_id"].drop_duplicates().tolist())
        or "없음"
    )
    baseline_2024_ab = stability.loc[stability["fiscal_year"].eq(2024) & stability["baseline_ab"]]
    stability_2024_lines = "\n".join(
        f"| `{row.program_year_id}` | {row.performance_program_name} | {row.production_review_grade} | "
        f"{row.grade__execution_moderate_minus_5pp} | {row.grade__execution_moderate_plus_5pp} | "
        f"{row.grade__budget_increase_stricter_5pp} | {row.grade__budget_decrease_stricter_5pp} | "
        f"{row.grade_stability:.3f} |"
        for row in baseline_2024_ab.itertuples()
    )
    ablation_2024 = (
        ablation_cases.loc[ablation_cases["is_2024_baseline_ab"]]
        .pivot(
            index=[
                "program_year_id",
                "performance_program_name",
                "production_review_grade",
            ],
            columns="signal_family_removed",
            values="shadow_review_grade",
        )
        .reset_index()
    )
    ablation_2024_lines = "\n".join(
        f"| `{row.program_year_id}` | {row.performance_program_name} | {row.production_review_grade} | "
        f"{row.execution} | {row.reported_performance} | {row.budget_performance_mismatch} | {row.repetition} |"
        for row in ablation_2024.itertuples()
    )
    repetition_summary = ablation_summary.set_index("signal_family_removed").loc["repetition"]
    return f"""# 프로그램-연도 점검등급 강건성 보고서

## 분석 질문과 범위

고정 생산 CSV 236행에서 H 27행과 identity·comparability·결측 상태를 유지한 채,
A~D 등급이 현재 수치 임계값과 신호 계열에 얼마나 의존하는지 shadow 분석했습니다.
이는 정확도·예측력·최적 임계값 또는 feature importance 분석이 아닙니다.

## Shadow 기준 재현

생산 판정식을 재사용하고 집행률·연속연도·예산증감 원시 필드에서 핵심 신호를 다시
계산했습니다. 생산 등급 불일치는 0/236행이며 전체 A16·B14·C90·D89·H27,
2024년 A4·B2·C35·D28·H8을 재현했습니다.

## OAT 임계값 민감도

| 시나리오 | shadow 등급 분포 | A~D 유지율 | A+B Jaccard | 2024 기준 A+B 변경 |
|---|---|---:|---:|---:|
{scenario_lines}

- A~D 등급 유지율 범위: **{retention_min:.3f}~{retention_max:.3f}**
- A+B 집합 Jaccard 범위: **{jaccard_min:.3f}~{jaccard_max:.3f}**
- A↔D 극단 이동: **{extreme}건**
- 모든 임계값 변형에서 불안정한 A~D 프로그램-연도: **{len(top_unstable)}건**
- 신호 경계 사례: **{len(boundaries)}건**. 경계 신호 변경과 실제 등급 변경을 분리해 저장했습니다.

예산 증가·감소는 부호의 의미를 보존하기 위해 반대 방향으로 완화하지 않고 각각 +5%와
-5%의 더 엄격한 인접 경계만 적용했습니다. 집행 강한·주의 기준은 한 번에 하나씩 ±5%p
변경했습니다.

### 2024년 기준 A+B 6건

| program_year_id | 프로그램 | 기준 | 집행주의 85% | 집행주의 95% | 예산증가 5% | 예산감소 -5% | 6변형 안정률 |
|---|---|---:|---:|---:|---:|---:|---:|
{stability_2024_lines}

집행 강한 기준 75%·85%에서는 6건 모두 등급이 같아 표에서 생략했습니다. 6건 중 모든
임계값 변형에서 등급 자체가 유지된 사례는 {int(baseline_2024_ab["stable_across_all_variants"].sum())}건이며,
A+B 집합을 모든 변형에서 유지한 사례는 {int((baseline_2024_ab.filter(like="grade__").isin(["A", "B"]).all(axis=1)).sum())}건입니다.

## 신호 제거 분석

| 제거 신호 | 등급 변경 | A/B 이탈 | A 신규 | B 신규 | C↔D |
|---|---:|---:|---:|---:|---:|
{ablation_lines}

한 계열 제거에만 반응해 A/B에서 이탈한 사례: {dependent_ids}

### 2024년 기준 A+B 신호 의존성

| program_year_id | 프로그램 | 기준 | execution 제거 | reported performance 제거 | budget mismatch 제거 | repetition 제거 |
|---|---|---:|---:|---:|---:|---:|
{ablation_2024_lines}

repetition 제거 시 기준 A 16건은 B {int(repetition_summary["repetition_removed_a_to_b"])}건,
C {int(repetition_summary["repetition_removed_a_to_c"])}건으로 이동했고 A 또는 D에 남은 사례는 없습니다.

신호 제거는 설명 가능한 의존성 점검입니다. execution 제거는 현재·반복 저집행을 함께,
reported_performance 제거는 비교가능 행의 미달 상태와 반복 미달을 함께,
budget_performance_mismatch 제거는 불일치와 A 복합경로의 예산증가 조건을 함께,
repetition 제거는 반복 저집행·연속 목표미달만 제거했습니다.

## 해석 제한과 불리한 결과

- H는 고정했으므로 H 전환 0은 강건성 성과가 아닙니다.
- 성과 100% 기준은 지표별 원시 달성률이 고정 CSV에 없어 재계산하지 않았습니다.
- M3 월별·사업단위 반복 임계값은 원시 입력이 없고 최종 프로그램-연도 등급에 직접
  사용되지 않아 제외했습니다.
- 신호 계열은 서로 겹칩니다. 특히 반복 저집행은 execution과 repetition에 동시에
  관련되므로 제거 결과를 독립적인 기여율로 해석할 수 없습니다.
- reported performance 제거에서는 기준 A+B 30건이 모두 A+B에서 이탈했습니다. 이는
  현재 A/B가 보고성과 신호와 강하게 결합된 규칙 구조라는 뜻이지 성과신호의 외부 타당성이나
  우월성을 입증하지 않습니다.
- budget mismatch 제거는 A/B 이탈 0건이지만 A→B 9건과 C↔D 41건을 만들었습니다.
  따라서 A+B 집합만 보면 안정적으로 보이지만 등급·맥락 설명은 크게 달라집니다.
- 외부검증 12건은 임계값 선택이나 규칙 조정에 사용하지 않았습니다.

## 권고

검토범위 압축은 등급이 모든 OAT 시나리오에서 안정적인 A/B와, 특정 한 계열 제거에도
A/B를 유지하는 사례를 우선 별도 표시하는 방식으로 진행할 수 있습니다. 다만 이를 새
생산등급이나 우월한 임계값으로 해석하지 말고 원문 검토량을 줄이는 보조 필터로만 사용해야 합니다.
"""


def upgrade_summary(
    sensitivity: pd.DataFrame,
    ablation_summary: pd.DataFrame,
) -> str:
    variants = sensitivity.loc[sensitivity["scenario_id"].ne("baseline")]
    return f"""# 데이터분석 업그레이드 요약

## 추가된 검증

- 생산 등급 계약 감사에 이어 동일 236행을 생산 판정식으로 shadow 재현했습니다.
- 고정 CSV에서 안전하게 재계산 가능한 4개 수치 임계값을 OAT 6개 변형으로 점검했습니다.
- execution, reported_performance, budget_performance_mismatch, repetition을 한 계열씩 제거해
  점검등급의 신호 의존성을 분리했습니다.
- H와 identity·comparability·결측 상태는 고정했고 생산 코드·CSV·등급은 변경하지 않았습니다.

## 핵심 결과

- shadow 기준 재현 불일치: 0/236행
- A~D 등급 유지율: {variants["grade_retention_rate"].min():.3f}~{variants["grade_retention_rate"].max():.3f}
- A+B Jaccard: {variants["ab_jaccard"].min():.3f}~{variants["ab_jaccard"].max():.3f}
- 신호 제거별 등급 변경: {", ".join(f"{row.signal_family_removed} {int(row.grade_changed_count)}" for row in ablation_summary.itertuples())}

## 분석적으로 달라진 점

현재 등급을 단일 결과로 제시하는 데서 그치지 않고, 어떤 수치 경계와 신호 계열에서
등급이 유지되거나 이동하는지 프로그램-연도별로 추적할 수 있게 됐습니다. 결과는 임계값
튜닝이나 성과판정이 아니라 검토범위 압축과 경계 사례 확인에만 사용합니다.
"""


def validate_outputs(
    baseline: pd.DataFrame,
    reproduction: pd.DataFrame,
    inventory: pd.DataFrame,
    sensitivity: pd.DataFrame,
    stability: pd.DataFrame,
    transitions: pd.DataFrame,
    boundaries: pd.DataFrame,
    ablation_summary: pd.DataFrame,
    ablation_cases: pd.DataFrame,
) -> None:
    if len(reproduction) != 236 or reproduction["program_year_id"].duplicated().any():
        raise RuntimeError("shadow 재현 CSV 키·행 수가 잘못되었습니다.")
    if not reproduction["match"].all():
        raise RuntimeError("shadow 재현 불일치가 남았습니다.")
    if len(inventory) < 4 or int(inventory["excluded_reason"].eq("").sum()) != 4:
        raise RuntimeError("임계값 목록이 불완전합니다.")
    if (
        len(sensitivity) != len(SENSITIVITY_SCENARIOS)
        or sensitivity["scenario_id"].duplicated().any()
    ):
        raise RuntimeError("민감도 시나리오 수가 잘못되었습니다.")
    if len(stability) != 236 or stability["program_year_id"].duplicated().any():
        raise RuntimeError("프로그램 등급 안정성 키·행 수가 잘못되었습니다.")
    if len(transitions) != len(SENSITIVITY_SCENARIOS) * 25:
        raise RuntimeError("등급 전환행렬 셀 수가 잘못되었습니다.")
    if (
        transitions[["scenario_id", "production_review_grade", "shadow_review_grade"]]
        .duplicated()
        .any()
    ):
        raise RuntimeError("등급 전환행렬 키가 중복되었습니다.")
    if not boundaries.empty and boundaries[["scenario_id", "program_year_id"]].duplicated().any():
        raise RuntimeError("임계값 경계 사례 키가 중복되었습니다.")
    if len(ablation_summary) != len(ABLATIONS):
        raise RuntimeError("신호 제거 요약 행 수가 잘못되었습니다.")
    if len(ablation_cases) != len(baseline) * len(ABLATIONS):
        raise RuntimeError("신호 제거 사례 행 수가 잘못되었습니다.")
    if ablation_cases[["signal_family_removed", "program_year_id"]].duplicated().any():
        raise RuntimeError("신호 제거 사례 키가 중복되었습니다.")
    h_ids = set(baseline.loc[baseline["review_grade"].eq("H"), "program_year_id"])
    h_cases = ablation_cases.loc[ablation_cases["program_year_id"].isin(h_ids)]
    if not h_cases["shadow_review_grade"].eq("H").all():
        raise RuntimeError("신호 제거 결과에서 H가 변했습니다.")


def main() -> None:
    baseline = load_baseline()
    _, reproduction = reproduce_baseline(baseline)
    inventory = threshold_inventory(baseline)
    sensitivity, stability, transitions, boundaries, _ = sensitivity_analysis(baseline)
    ablation_summary, ablation_cases, _ = ablation_analysis(baseline)
    validate_outputs(
        baseline,
        reproduction,
        inventory,
        sensitivity,
        stability,
        transitions,
        boundaries,
        ablation_summary,
        ablation_cases,
    )

    output_dir = ROOT / "validation"
    reproduction.to_csv(
        output_dir / "shadow_baseline_reproduction.csv", index=False, encoding="utf-8-sig"
    )
    inventory.to_csv(
        output_dir / "grade_threshold_inventory.csv", index=False, encoding="utf-8-sig"
    )
    sensitivity.to_csv(
        output_dir / "grade_sensitivity_scenarios.csv", index=False, encoding="utf-8-sig"
    )
    stability.to_csv(output_dir / "program_grade_stability.csv", index=False, encoding="utf-8-sig")
    transitions.to_csv(
        output_dir / "grade_transition_matrices.csv", index=False, encoding="utf-8-sig"
    )
    boundaries.to_csv(output_dir / "grade_boundary_cases.csv", index=False, encoding="utf-8-sig")
    ablation_summary.to_csv(
        output_dir / "signal_ablation_summary.csv", index=False, encoding="utf-8-sig"
    )
    ablation_cases.to_csv(
        output_dir / "signal_ablation_cases.csv", index=False, encoding="utf-8-sig"
    )

    (ROOT / "docs/EXPLANATION_PRECEDENCE_ISSUE.md").write_text(
        explanation_precedence_issue(baseline), encoding="utf-8"
    )
    (ROOT / "docs/GRADE_ROBUSTNESS_REPORT.md").write_text(
        robustness_report(
            sensitivity,
            stability,
            boundaries,
            ablation_summary,
            ablation_cases,
        ),
        encoding="utf-8",
    )
    (ROOT / "docs/DATA_ANALYSIS_UPGRADE_SUMMARY.md").write_text(
        upgrade_summary(sensitivity, ablation_summary), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
