from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "data/analytics/multi_ministry_priority_scenarios/program_year_review_queue.csv"
CANDIDATES = ROOT / "data/analytics/multi_ministry_priority_scenarios/candidate_population.csv"
PROJECTS = (
    ROOT
    / "data/analytics/multi_ministry_priority_scenarios/full_population_project_review_queue.csv"
)
EXPECTED_SHA256 = "d7c59cc14da21f0e669f2e09867766100957ddad68f8600b43d64392c6236a96"
VALIDATION = ROOT / "validation"
FIGURES = VALIDATION / "figures"
CHECKPOINT = ROOT / "docs/work_in_progress/OPERATIONAL_ANALYSIS_CHECKPOINT.md"
GRADE_ORDER = {"A": 1, "B": 2, "C": 3, "D": 4, "H": 5}
WORK_GROUP = {
    "A": "PRIORITY_REVIEW",
    "B": "PRIORITY_REVIEW",
    "C": "CONTEXT_REVIEW",
    "D": "MONITOR",
    "H": "DATA_HOLD",
}
ABLATION_COLUMNS = {
    "execution": "changed_when_execution_removed",
    "reported_performance": "changed_when_reported_performance_removed",
    "budget_performance_mismatch": "changed_when_budget_mismatch_removed",
    "repetition": "changed_when_repetition_removed",
}


def _write_csv(frame: pd.DataFrame, name: str) -> None:
    frame.to_csv(VALIDATION / name, index=False, encoding="utf-8-sig")


def _json_list(value: object) -> list[str]:
    if pd.isna(value):
        return []
    parsed = json.loads(str(value))
    if not isinstance(parsed, list):
        raise TypeError(f"JSON 목록이 아닙니다: {value}")
    return [str(item) for item in parsed]


def _bool(value: object) -> bool:
    return False if pd.isna(value) else bool(value)


def _families(value: object) -> set[str]:
    return {item for item in str(value).split(";") if item and item != "NONE"}


def _checkpoint(completed: list[str]) -> None:
    labels = [
        "기준 검증",
        "기존 판정 조건과 강건성 산출물 추적",
        "안정성·의존성 층화표",
        "검토범위 압축 분석",
        "시간외 방향성 분석",
        "peer 가능성 감사 및 조건부 백분위",
        "보고서와 발표 요약",
        "그림",
        "최종 검증",
    ]
    lines = [
        "# Operational Analysis Checkpoint",
        "",
        "- 상태: 진행 중",
        "- 기준 HEAD: `609b9db848d7e476e3fcb7d62050fd21c2672bf4` (확인 완료)",
        f"- 기준 CSV SHA-256: `{EXPECTED_SHA256}` (확인 완료)",
        "- 기준 CSV: 236행 × 91열, `program_year_id` 중복 0건",
        "- 등급 분포: 전체 A16/B14/C90/D89/H27, 2024년 A4/B2/C35/D28/H8",
        "- 생산 코드·설정·CSV·등급·`analysis_summary.json`: 수정하지 않음",
        "",
        "## 진행 상황",
        "",
        *[f"- [{'x' if label in completed else ' '}] {label}" for label in labels],
        "",
    ]
    CHECKPOINT.write_text("\n".join(lines), encoding="utf-8")


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    actual_hash = hashlib.sha256(QUEUE.read_bytes()).hexdigest()
    if actual_hash != EXPECTED_SHA256:
        raise RuntimeError(f"기준 CSV SHA 불일치: {actual_hash}")
    queue = pd.read_csv(
        QUEUE,
        dtype={"ministry_code": "string", "program_code": "string"},
    )
    expected_counts = {"A": 16, "B": 14, "C": 90, "D": 89, "H": 27}
    expected_2024 = {"A": 4, "B": 2, "C": 35, "D": 28, "H": 8}
    if queue.shape != (236, 91) or queue["program_year_id"].duplicated().any():
        raise RuntimeError("기준 CSV 크기 또는 키 계약 불일치")
    if queue["review_grade"].value_counts().to_dict() != expected_counts:
        raise RuntimeError("전체 등급 분포 불일치")
    counts_2024 = queue.loc[queue["fiscal_year"].eq(2024), "review_grade"].value_counts()
    if counts_2024.to_dict() != expected_2024:
        raise RuntimeError("2024년 등급 분포 불일치")
    candidates = pd.read_csv(
        CANDIDATES,
        dtype={"ministry_code": "string", "program_code": "string"},
    )
    projects = pd.read_csv(
        PROJECTS,
        dtype={"ministry_code": "string", "program_code": "string"},
    )
    if candidates["candidate_id"].duplicated().any():
        raise RuntimeError("candidate_id 중복")
    if projects[["candidate_id", "project_id"]].duplicated().any():
        raise RuntimeError("candidate_id×project_id 중복")
    return queue, candidates, projects


def attach_linked_counts(
    queue: pd.DataFrame, candidates: pd.DataFrame, projects: pd.DataFrame
) -> pd.DataFrame:
    links = queue[["program_year_id", "raw_candidate_ids"]].copy()
    links["candidate_id"] = links["raw_candidate_ids"].map(_json_list)
    links = links.explode("candidate_id", ignore_index=True)
    if links["candidate_id"].duplicated().any() or len(links) != 412:
        raise RuntimeError("program_year_id→candidate_id 연결 계약 불일치")
    candidate_ids = set(candidates["candidate_id"])
    if not set(links["candidate_id"]) <= candidate_ids:
        raise RuntimeError("candidate_population에 없는 candidate_id")

    indicator_lists = candidates.set_index("candidate_id")["source_indicator_ids"].map(_json_list)
    indicator_links = links[["program_year_id", "candidate_id"]].copy()
    indicator_links["source_indicator_id"] = indicator_links["candidate_id"].map(indicator_lists)
    indicator_links = indicator_links.explode("source_indicator_id")
    indicator_count = (
        indicator_links.dropna(subset=["source_indicator_id"])
        .groupby("program_year_id")["source_indicator_id"]
        .nunique()
    )

    project_links = links.merge(
        projects[["candidate_id", "project_id"]],
        on="candidate_id",
        how="left",
        validate="one_to_many",
    )
    missing_candidates = (
        project_links.loc[project_links["project_id"].isna()]
        .groupby("program_year_id")["candidate_id"]
        .nunique()
    )
    review_units = (
        project_links.dropna(subset=["project_id"]).groupby("program_year_id")["project_id"].count()
    )

    result = queue.copy()
    result["linked_indicator_count"] = (
        result["program_year_id"].map(indicator_count).fillna(0).astype(int)
    )
    result["comparable_indicator_count"] = pd.to_numeric(
        result["comparable_rate_count"], errors="coerce"
    )
    result["linked_source_review_unit_count"] = (
        result["program_year_id"].map(review_units).fillna(0).astype(int)
    )
    missing = result["program_year_id"].map(missing_candidates).fillna(0).astype(int)
    result["source_review_unit_link_reason"] = "COMPLETE_CANDIDATE_TO_PROJECT_LINK"
    result.loc[missing.gt(0), "source_review_unit_link_reason"] = (
        "PARTIAL_OR_ZERO_LINKED_CANDIDATE_IDS:" + missing.loc[missing.gt(0)].astype(str)
    )
    return result


def build_robustness_profile(queue: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    stability = pd.read_csv(VALIDATION / "program_grade_stability.csv")
    ablation = pd.read_csv(VALIDATION / "signal_ablation_cases.csv")
    if len(stability) != 236 or len(ablation) != 944:
        raise RuntimeError("기존 강건성 산출물 행 수 불일치")
    scenario_columns = [
        column
        for column in stability
        if column.startswith("grade__") and column != "grade__baseline"
    ]
    scenario_groups = stability[scenario_columns].replace(WORK_GROUP)
    baseline_group = stability["production_review_grade"].map(WORK_GROUP)
    scenario_ab = stability[scenario_columns].isin(["A", "B"])
    baseline_ab = stability["production_review_grade"].isin(["A", "B"])

    profile = stability[
        [
            "program_year_id",
            "fiscal_year",
            "ministry_code",
            "performance_program_name",
            "production_review_grade",
        ]
    ].copy()
    profile["production_work_group"] = baseline_group
    profile["threshold_stable_ab"] = baseline_ab & scenario_ab.all(axis=1)
    profile["exact_grade_stable"] = stability["stable_across_all_variants"].astype("boolean")
    profile.loc[stability["production_review_grade"].eq("H"), "exact_grade_stable"] = pd.NA
    profile["threshold_boundary"] = scenario_groups.ne(baseline_group, axis=0).any(axis=1)
    ranks = stability[scenario_columns].apply(lambda column: column.map(GRADE_ORDER))
    inverse = {value: key for key, value in GRADE_ORDER.items()}
    profile["minimum_shadow_grade"] = ranks.min(axis=1).map(inverse)
    profile["maximum_shadow_grade"] = ranks.max(axis=1).map(inverse)
    profile["grade_stability_rate"] = stability["grade_stability"]
    ever_ab = scenario_ab.any(axis=1)
    profile["ab_jaccard_membership_status"] = np.select(
        [
            baseline_ab & scenario_ab.all(axis=1),
            baseline_ab & ~scenario_ab.all(axis=1),
            ~baseline_ab & ever_ab,
            stability["production_review_grade"].eq("H"),
        ],
        ["BASELINE_AB_STABLE", "BASELINE_AB_BOUNDARY", "ENTERS_AB_IN_VARIANT", "H_FIXED"],
        default="NEVER_AB",
    )

    changed = ablation.pivot(
        index="program_year_id", columns="signal_family_removed", values="grade_changed"
    )
    for family, column in ABLATION_COLUMNS.items():
        profile[column] = profile["program_year_id"].map(changed[family]).astype(bool)
    dependency_families = (
        ablation.loc[ablation["grade_changed"]]
        .groupby("program_year_id")["signal_family_removed"]
        .agg(lambda values: ";".join(values))
    )
    profile["signal_dependency_count"] = (
        profile["program_year_id"]
        .map(
            ablation.loc[ablation["grade_changed"]]
            .groupby("program_year_id")["signal_family_removed"]
            .nunique()
        )
        .fillna(0)
        .astype(int)
    )
    profile["signal_dependency_signature"] = (
        profile["program_year_id"].map(dependency_families).fillna("NONE")
    )
    single = ablation.groupby("program_year_id")["single_family_dependent_ab"].any()
    profile["single_signal_dependent_ab"] = profile["program_year_id"].map(single).fillna(False)

    def note(row: pd.Series) -> str:
        if row["production_review_grade"] == "H":
            return "H_FIXED_NOT_DISTANCE_SCORED"
        if row["threshold_boundary"]:
            return "OAT_WORK_GROUP_BOUNDARY"
        if not row["exact_grade_stable"]:
            return "OAT_EXACT_GRADE_CHANGE_WITHIN_WORK_GROUP"
        if row["signal_dependency_count"]:
            return "OAT_STABLE_WITH_ABLATION_DEPENDENCY"
        return "OAT_AND_ABLATION_GRADE_STABLE"

    profile["robustness_note"] = profile.apply(note, axis=1)
    profile = profile.sort_values("program_year_id", ignore_index=True)

    ablation_grades = ablation.pivot(
        index="program_year_id", columns="signal_family_removed", values="shadow_review_grade"
    ).add_prefix("grade_without_")
    stability_2024 = stability.loc[
        stability["fiscal_year"].eq(2024) & baseline_ab,
        ["program_year_id", *scenario_columns],
    ]
    priority_2024 = (
        profile.loc[
            profile["fiscal_year"].eq(2024) & profile["production_review_grade"].isin(["A", "B"])
        ]
        .merge(stability_2024, on="program_year_id", validate="one_to_one")
        .merge(ablation_grades, on="program_year_id", validate="one_to_one")
        .sort_values("program_year_id", ignore_index=True)
    )
    if len(priority_2024) != 6 or int(priority_2024["threshold_stable_ab"].sum()) != 5:
        raise RuntimeError("2024 A+B 안정성 재검증 불일치")
    _write_csv(profile, "program_review_robustness_profile.csv")
    _write_csv(priority_2024, "priority_review_2024_stability.csv")
    return profile, priority_2024


def _complex_signal(row: pd.Series) -> bool:
    repeated = (
        _bool(row["repeated_low_execution_signal"])
        or _bool(row["reported_target_miss_consecutive"])
        or float(row.get("repeated_signal_family_count", 0) or 0) > 0
    )
    return repeated or len(_families(row["grade_trigger_signal_families"]) - {"data_quality"}) >= 2


def _summary_row(frame: pd.DataFrame, label: str, total: pd.DataFrame) -> dict[str, object]:
    incomplete_links = frame["source_review_unit_link_reason"].ne(
        "COMPLETE_CANDIDATE_TO_PROJECT_LINK"
    )
    return {
        "analysis_group": label,
        "program_count": len(frame),
        "program_share": len(frame) / len(total),
        "original_budget_sum": frame["program_original_budget"].sum(min_count=1),
        "original_budget_share": frame["program_original_budget"].sum()
        / total["program_original_budget"].sum(),
        "current_budget_sum": frame["program_current_budget"].sum(min_count=1),
        "current_budget_share": frame["program_current_budget"].sum()
        / total["program_current_budget"].sum(),
        "expenditure_sum": frame["program_expenditure"].sum(min_count=1),
        "linked_indicator_count": int(frame["linked_indicator_count"].sum()),
        "linked_indicator_share": frame["linked_indicator_count"].sum()
        / total["linked_indicator_count"].sum(),
        "comparable_indicator_count": int(frame["comparable_indicator_count"].sum()),
        "comparable_indicator_share": frame["comparable_indicator_count"].sum()
        / total["comparable_indicator_count"].sum(),
        "linked_source_review_unit_count": int(frame["linked_source_review_unit_count"].sum()),
        "source_review_unit_share": frame["linked_source_review_unit_count"].sum()
        / total["linked_source_review_unit_count"].sum(),
        "source_review_unit_hold_reason": (
            ""
            if not incomplete_links.any()
            else f"PARTIAL_OR_ZERO_LINKED_PROGRAMS:{int(incomplete_links.sum())}"
        ),
        "mean_observed_year_count": frame["observed_year_count"].mean(),
        "next_review_question_count": int(frame["next_review_question"].notna().sum()),
        "repeated_or_complex_signal_count": int(frame["repeated_or_complex_signal"].sum()),
    }


def build_workload_outputs(
    queue: pd.DataFrame, profile: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    work = queue.loc[queue["fiscal_year"].eq(2024)].copy()
    work = work.merge(
        profile[["program_year_id", "threshold_stable_ab", "threshold_boundary"]],
        on="program_year_id",
        validate="one_to_one",
    )
    work["production_work_group"] = work["review_grade"].map(WORK_GROUP)
    work["repeated_or_complex_signal"] = work.apply(_complex_signal, axis=1)
    total = work
    groups = [
        ("PRIORITY_REVIEW", work["review_grade"].isin(["A", "B"])),
        ("CONTEXT_REVIEW", work["review_grade"].eq("C")),
        ("MONITOR", work["review_grade"].eq("D")),
        ("DATA_HOLD", work["review_grade"].eq("H")),
        ("THRESHOLD_STABLE_AB_CORE", work["threshold_stable_ab"]),
        (
            "THRESHOLD_BOUNDARY_AB",
            work["review_grade"].isin(["A", "B"]) & work["threshold_boundary"],
        ),
    ]
    summary = pd.DataFrame([_summary_row(work.loc[mask], label, total) for label, mask in groups])

    grade_rows = []
    for grade in ["A", "B", "C", "D", "H"]:
        row = _summary_row(work.loc[work["review_grade"].eq(grade)], grade, total)
        row["review_grade"] = grade
        grade_rows.append(row)
    by_grade = pd.DataFrame(grade_rows)[["review_grade", *summary.columns[1:]]]

    core_boundary = work.loc[work["review_grade"].isin(["A", "B"])].copy()
    core_boundary["robustness_stratum"] = np.where(
        core_boundary["threshold_stable_ab"], "THRESHOLD_STABLE_CORE", "THRESHOLD_BOUNDARY"
    )
    dependency_columns = [column for column in profile if column.startswith("changed_when_")]
    core_boundary = core_boundary.merge(
        profile[
            [
                "program_year_id",
                "exact_grade_stable",
                "grade_stability_rate",
                "signal_dependency_signature",
                "signal_dependency_count",
                *dependency_columns,
            ]
        ],
        on="program_year_id",
        validate="one_to_one",
    )
    core_boundary = core_boundary[
        [
            "program_year_id",
            "performance_program_name",
            "review_grade",
            "robustness_stratum",
            "threshold_stable_ab",
            "threshold_boundary",
            "exact_grade_stable",
            "grade_stability_rate",
            "signal_dependency_count",
            "signal_dependency_signature",
            *dependency_columns,
            "program_original_budget",
            "program_current_budget",
            "linked_indicator_count",
            "comparable_indicator_count",
            "linked_source_review_unit_count",
            "repeated_or_complex_signal",
        ]
    ].sort_values(["robustness_stratum", "program_year_id"], ignore_index=True)

    total_budget = total["program_original_budget"].sum()
    total_comparable = total["comparable_indicator_count"].sum()

    def curve_rows(frame: pd.DataFrame, curve_id: str) -> pd.DataFrame:
        frame = frame.copy().reset_index(drop=True)
        frame["curve_id"] = curve_id
        frame["curve_sequence"] = frame.index + 1
        frame["cumulative_program_count"] = frame.index + 1
        frame["cumulative_program_share"] = (frame.index + 1) / len(total)
        frame["cumulative_original_budget_share"] = (
            frame["program_original_budget"].cumsum() / total_budget
        )
        frame["cumulative_comparable_indicator_share"] = (
            frame["comparable_indicator_count"].cumsum() / total_comparable
        )
        frame["cumulative_repeated_or_complex_signal_count"] = frame[
            "repeated_or_complex_signal"
        ].cumsum()
        frame["cumulative_linked_source_review_unit_count"] = frame[
            "linked_source_review_unit_count"
        ].cumsum()
        frame["cumulative_linked_source_review_unit_share"] = (
            frame["cumulative_linked_source_review_unit_count"]
            / total["linked_source_review_unit_count"].sum()
        )
        return frame

    ordered = work.sort_values("program_year_queue_order")
    ab = ordered.loc[ordered["review_grade"].isin(["A", "B"])]
    c = ordered.loc[ordered["review_grade"].eq("C")]
    curves = pd.concat(
        [
            curve_rows(ab, "AB_INTERNAL_PRODUCTION_ORDER"),
            curve_rows(pd.concat([ab, c]), "AB_THEN_C_EXPANSION"),
            curve_rows(ordered.loc[ordered["review_grade"].eq("D")], "D_MONITOR_SEPARATE"),
            curve_rows(ordered.loc[ordered["review_grade"].eq("H")], "H_DATA_HOLD_SEPARATE"),
        ],
        ignore_index=True,
    )
    curve_columns = [
        "curve_id",
        "curve_sequence",
        "program_year_id",
        "performance_program_name",
        "review_grade",
        "production_work_group",
        "cumulative_program_count",
        "cumulative_program_share",
        "cumulative_original_budget_share",
        "cumulative_comparable_indicator_share",
        "cumulative_repeated_or_complex_signal_count",
        "cumulative_linked_source_review_unit_count",
        "cumulative_linked_source_review_unit_share",
    ]
    curves = curves[curve_columns]

    _write_csv(summary, "workload_compression_summary.csv")
    _write_csv(curves, "workload_cumulative_curve.csv")
    _write_csv(by_grade, "workload_by_grade_and_budget.csv")
    _write_csv(core_boundary, "priority_review_core_and_boundary.csv")
    return summary, curves, by_grade, core_boundary


def _budget_direction(value: object) -> str:
    if pd.isna(value):
        return "MISSING"
    if float(value) > 0:
        return "INCREASE"
    if float(value) < 0:
        return "DECREASE"
    return "FLAT"


def build_temporal_outputs(
    queue: pd.DataFrame, profile: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    work = queue.merge(
        profile[["program_year_id", "threshold_stable_ab", "threshold_boundary"]],
        on="program_year_id",
        validate="one_to_one",
    )
    work["work_group"] = work["review_grade"].map(WORK_GROUP)
    lookup = work.set_index(["program_identity_id", "fiscal_year"], drop=False)
    rows: list[dict[str, object]] = []
    for baseline in work.loc[work["fiscal_year"].isin([2022, 2023])].itertuples(index=False):
        exclusion = ""
        followup = None
        if baseline.identity_unresolved or baseline.continuity_status in {
            "UNKNOWN_CONTINUITY",
            "UNRESOLVED_IDENTITY_HOLD",
        }:
            exclusion = "BASELINE_IDENTITY_UNRESOLVED"
        else:
            key = (baseline.program_identity_id, baseline.fiscal_year + 1)
            if key not in lookup.index:
                exclusion = "NEXT_YEAR_OBSERVATION_MISSING"
            else:
                selected = lookup.loc[key]
                if isinstance(selected, pd.DataFrame):
                    exclusion = "NEXT_YEAR_IDENTITY_NOT_UNIQUE"
                elif selected.identity_unresolved:
                    exclusion = "NEXT_YEAR_IDENTITY_UNRESOLVED"
                else:
                    followup = selected
        available = followup is not None
        baseline_families = _families(baseline.grade_trigger_signal_families)
        next_families = _families(followup.grade_trigger_signal_families) if available else set()
        rows.append(
            {
                "program_year_id": baseline.program_year_id,
                "program_identity_id": baseline.program_identity_id,
                "fiscal_year": baseline.fiscal_year,
                "ministry_code": baseline.ministry_code,
                "performance_program_name": baseline.performance_program_name,
                "baseline_review_grade": baseline.review_grade,
                "baseline_work_group": baseline.work_group,
                "baseline_diagnostic_type": baseline.diagnostic_type,
                "threshold_stable_ab": baseline.threshold_stable_ab,
                "threshold_boundary": baseline.threshold_boundary,
                "next_year_program_year_id": followup.program_year_id if available else pd.NA,
                "next_year_review_grade": followup.review_grade if available else pd.NA,
                "next_year_work_group": followup.work_group if available else pd.NA,
                "next_year_same_signal_family_observed": (
                    bool(baseline_families & next_families) if available else pd.NA
                ),
                "next_year_reported_target_miss": (
                    _bool(followup.performance_signal) if available else pd.NA
                ),
                "next_year_execution_signal": (
                    (
                        float(followup.current_execution_severity or 0) > 0
                        or _bool(followup.repeated_low_execution_signal)
                    )
                    if available
                    else pd.NA
                ),
                "next_year_budget_direction": (
                    _budget_direction(followup.program_budget_change_rate) if available else pd.NA
                ),
                "grade_transition": (
                    f"{baseline.review_grade}->{followup.review_grade}" if available else pd.NA
                ),
                "followup_available": available,
                "exclusion_reason": exclusion,
            }
        )
    cases = pd.DataFrame(rows)
    available = cases.loc[cases["followup_available"]].copy()
    summary_rows: list[dict[str, object]] = []

    def add(scope: str, cohort: str, metric: str, mask: pd.Series, outcome: pd.Series) -> None:
        denominator = int(mask.sum())
        numerator = int((mask & outcome.astype("boolean").fillna(False)).sum())
        summary_rows.append(
            {
                "analysis_scope": scope,
                "cohort": cohort,
                "metric": metric,
                "numerator": numerator,
                "denominator": denominator,
                "rate": numerator / denominator if denominator else pd.NA,
            }
        )

    for grade in ["A", "B", "C", "D", "H"]:
        cohort = cases["baseline_review_grade"].eq(grade)
        add("H_INCLUDED", grade, "FOLLOWUP_AVAILABLE", cohort, cases["followup_available"])
        add("H_INCLUDED", grade, "FOLLOWUP_MISSING", cohort, ~cases["followup_available"])

    ab = available["baseline_review_grade"].isin(["A", "B"])
    add(
        "H_EXCLUDED",
        "A+B",
        "NEXT_YEAR_SAME_SIGNAL_FAMILY",
        ab,
        available["next_year_same_signal_family_observed"],
    )
    add(
        "H_EXCLUDED",
        "A+B",
        "NEXT_YEAR_AB",
        ab,
        available["next_year_review_grade"].isin(["A", "B"]),
    )
    for target in ["C", "D", "H"]:
        add(
            "H_INCLUDED",
            "A+B",
            f"NEXT_YEAR_{target}",
            ab,
            available["next_year_review_grade"].eq(target),
        )
    add(
        "H_EXCLUDED",
        "C",
        "NEXT_YEAR_AB",
        available["baseline_review_grade"].eq("C"),
        available["next_year_review_grade"].isin(["A", "B"]),
    )
    add(
        "H_EXCLUDED",
        "D",
        "NEXT_YEAR_AB",
        available["baseline_review_grade"].eq("D"),
        available["next_year_review_grade"].isin(["A", "B"]),
    )
    low_met = available["baseline_diagnostic_type"].eq("LOW_EXECUTION_TARGET_MET")
    for target in ["A", "B", "C", "D", "H"]:
        add(
            "H_INCLUDED",
            "LOW_EXECUTION_TARGET_MET",
            f"NEXT_YEAR_{target}",
            low_met,
            available["next_year_review_grade"].eq(target),
        )
    for label, mask in [
        ("THRESHOLD_STABLE_AB", ab & available["threshold_stable_ab"]),
        ("THRESHOLD_BOUNDARY_AB", ab & available["threshold_boundary"]),
    ]:
        add(
            "H_EXCLUDED",
            label,
            "NEXT_YEAR_SAME_SIGNAL_FAMILY",
            mask,
            available["next_year_same_signal_family_observed"],
        )
        add(
            "H_EXCLUDED",
            label,
            "NEXT_YEAR_AB",
            mask,
            available["next_year_review_grade"].isin(["A", "B"]),
        )
    for scope, scope_mask in [
        ("H_INCLUDED", pd.Series(True, index=available.index)),
        (
            "H_EXCLUDED",
            ~available["baseline_review_grade"].eq("H")
            & ~available["next_year_review_grade"].eq("H"),
        ),
    ]:
        add(
            scope,
            "ALL",
            "NEXT_YEAR_SAME_SIGNAL_FAMILY",
            scope_mask,
            available["next_year_same_signal_family_observed"],
        )

    summary = pd.DataFrame(summary_rows)
    transition_rows = []
    for scope, part in [
        ("H_INCLUDED", available),
        (
            "H_EXCLUDED",
            available.loc[
                ~available["baseline_review_grade"].eq("H")
                & ~available["next_year_review_grade"].eq("H")
            ],
        ),
    ]:
        counts = part.groupby(["baseline_review_grade", "next_year_review_grade"]).size()
        denominators = part.groupby("baseline_review_grade").size()
        for (source, target), count in counts.items():
            transition_rows.append(
                {
                    "analysis_scope": scope,
                    "baseline_review_grade": source,
                    "next_year_review_grade": target,
                    "program_count": int(count),
                    "baseline_grade_denominator": int(denominators[source]),
                    "transition_share": count / denominators[source],
                }
            )
    transitions = pd.DataFrame(transition_rows)
    _write_csv(cases, "temporal_followup_cases.csv")
    _write_csv(summary, "temporal_followup_summary.csv")
    _write_csv(transitions, "temporal_grade_transitions.csv")
    return cases, summary, transitions


def build_peer_outputs(queue: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = queue.copy()
    work["peer_account_composition"] = (
        work["account_types"]
        .fillna("NOT_AVAILABLE")
        .map(lambda value: ";".join(sorted(str(value).split(";"))))
    )
    work["peer_definition"] = (
        "ministry="
        + work["ministry_code"].astype(str)
        + ";year="
        + work["fiscal_year"].astype(str)
        + ";accounts="
        + work["peer_account_composition"]
    )
    metric_specs = {
        "program_execution_rate": "program_current_budget",
        "program_budget_change_rate": "program_original_budget",
    }
    audit_rows: list[dict[str, object]] = []
    reference_rows: list[dict[str, object]] = []
    group_columns = ["ministry_code", "fiscal_year", "peer_account_composition"]
    for metric, denominator_column in metric_specs.items():
        numeric = pd.to_numeric(work[metric], errors="coerce")
        denominator = pd.to_numeric(work[denominator_column], errors="coerce")
        row_valid = ~work["identity_unresolved"].fillna(True) & numeric.notna() & denominator.gt(0)
        for _, group in work.groupby(group_columns, dropna=False):
            valid_group = group.loc[row_valid.loc[group.index]].copy()
            values = pd.to_numeric(valid_group[metric], errors="coerce")
            valid_n = len(values)
            distinct_n = values.nunique()
            group_eligible = valid_n >= 10 and distinct_n >= 5
            for index, row in group.iterrows():
                reason = ""
                if _bool(row["identity_unresolved"]):
                    reason = "IDENTITY_UNRESOLVED"
                elif pd.isna(numeric.loc[index]):
                    reason = "METRIC_MISSING"
                elif denominator.loc[index] <= 0 or pd.isna(denominator.loc[index]):
                    reason = "DENOMINATOR_NOT_COMPARABLE"
                elif valid_n < 10:
                    reason = f"VALID_PEER_N_LT_10:{valid_n}"
                elif distinct_n < 5:
                    reason = f"DISTINCT_VALUE_N_LT_5:{distinct_n}"
                audit_rows.append(
                    {
                        "program_year_id": row["program_year_id"],
                        "fiscal_year": row["fiscal_year"],
                        "ministry_code": row["ministry_code"],
                        "performance_program_name": row["performance_program_name"],
                        "metric_name": metric,
                        "metric_value": numeric.loc[index],
                        "peer_definition": row["peer_definition"],
                        "valid_peer_n": valid_n,
                        "distinct_value_n": distinct_n,
                        "peer_eligible": group_eligible and not reason,
                        "peer_hold_reason": reason,
                    }
                )
            if group_eligible:
                percentiles = values.rank(method="average", pct=True)
                q1, median, q3 = values.quantile([0.25, 0.5, 0.75])
                for index, value in values.items():
                    row = work.loc[index]
                    reference_rows.append(
                        {
                            "program_year_id": row["program_year_id"],
                            "fiscal_year": row["fiscal_year"],
                            "ministry_code": row["ministry_code"],
                            "performance_program_name": row["performance_program_name"],
                            "metric_name": metric,
                            "metric_value": value,
                            "tie_aware_percentile": percentiles.loc[index],
                            "peer_definition": row["peer_definition"],
                            "valid_peer_n": valid_n,
                            "distinct_value_n": distinct_n,
                            "median": median,
                            "q1": q1,
                            "q3": q3,
                            "iqr": q3 - q1,
                            "peer_hold_reason": "",
                        }
                    )
    audit = pd.DataFrame(audit_rows)
    references = pd.DataFrame(reference_rows)
    _write_csv(audit, "peer_group_eligibility_audit.csv")
    _write_csv(references, "peer_reference_percentiles.csv")
    return audit, references


def _configure_plots() -> None:
    plt.rcParams.update(
        {
            "font.family": "Malgun Gothic",
            "axes.unicode_minus": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#374151",
            "text.color": "#1f2937",
            "axes.labelcolor": "#374151",
            "xtick.color": "#4b5563",
            "ytick.color": "#4b5563",
        }
    )


def build_figures(
    priority_2024: pd.DataFrame,
    transitions: pd.DataFrame,
    peer_references: pd.DataFrame,
) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    _configure_plots()
    labels = ["전체", "A+B", "안정 핵심", "C", "H(보완)", "D(모니터)"]
    values = [77, 6, int(priority_2024["threshold_stable_ab"].sum()), 35, 8, 28]
    colors = ["#d1d5db", "#2563eb", "#93c5fd", "#d4a72c", "#f59e0b", "#9ca3af"]
    fig, ax = plt.subplots(figsize=(9, 5.2))
    bars = ax.bar(labels, values, color=colors, edgecolor="#374151", linewidth=0.8)
    ax.set_title("2024년 프로그램 검토업무 분할", loc="left", weight="bold")
    ax.set_ylabel("프로그램 수")
    ax.set_ylim(0, 85)
    ax.grid(axis="y", color="#e5e7eb", linewidth=0.7)
    ax.set_axisbelow(True)
    for bar, value in zip(bars, values, strict=True):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 1.2, str(value), ha="center")
    ax.axvline(3.5, color="#6b7280", linestyle="--", linewidth=1)
    ax.text(4, 78, "별도 데이터 보완·모니터 영역", ha="center", color="#6b7280")
    fig.tight_layout()
    fig.savefig(FIGURES / "workload_compression.png", dpi=180)
    plt.close(fig)

    plot = priority_2024.sort_values("grade_stability_rate")
    fig, ax = plt.subplots(figsize=(9, 5.4))
    colors = np.where(plot["threshold_stable_ab"], "#2563eb", "#f59e0b")
    bars = ax.barh(plot["performance_program_name"], plot["grade_stability_rate"], color=colors)
    ax.set_xlim(0, 1.08)
    ax.set_xlabel("정확 등급 유지율 (6개 OAT 변형)")
    ax.set_title("2024년 A+B 임계값 안정성", loc="left", weight="bold")
    ax.grid(axis="x", color="#e5e7eb", linewidth=0.7)
    ax.set_axisbelow(True)
    for bar, value in zip(bars, plot["grade_stability_rate"], strict=True):
        ax.text(value + 0.015, bar.get_y() + bar.get_height() / 2, f"{value:.0%}", va="center")
    fig.tight_layout()
    fig.savefig(FIGURES / "priority_review_stability_2024.png", dpi=180)
    plt.close(fig)

    matrix = (
        transitions.loc[transitions["analysis_scope"].eq("H_INCLUDED")]
        .pivot(
            index="baseline_review_grade", columns="next_year_review_grade", values="program_count"
        )
        .reindex(index=list("ABCDH"), columns=list("ABCDH"), fill_value=0)
        .fillna(0)
    )
    fig, ax = plt.subplots(figsize=(7, 6))
    image = ax.imshow(matrix, cmap="Blues")
    ax.set_xticks(range(5), matrix.columns)
    ax.set_yticks(range(5), matrix.index)
    ax.set_xlabel("다음 연도 등급")
    ax.set_ylabel("기준연도 등급")
    ax.set_title("정확 식별자 연결 프로그램의 다음 연도 등급 이동", loc="left", weight="bold")
    for i in range(5):
        for j in range(5):
            value = int(matrix.iloc[i, j])
            ax.text(
                j,
                i,
                value,
                ha="center",
                va="center",
                color="white" if value > matrix.to_numpy().max() / 2 else "#1f2937",
            )
    fig.colorbar(image, ax=ax, label="프로그램-연도 수")
    fig.tight_layout()
    fig.savefig(FIGURES / "temporal_grade_transition.png", dpi=180)
    plt.close(fig)

    if not peer_references.empty:
        peer = peer_references.sort_values("metric_value")
        fig, ax = plt.subplots(figsize=(9, 5.2))
        ax.scatter(peer["metric_value"], peer["tie_aware_percentile"], color="#2563eb")
        ax.set_xlabel("프로그램 집행률")
        ax.set_ylabel("동료집단 tie-aware 백분위")
        ax.set_title("계산 가능한 동료집단 참고값", loc="left", weight="bold")
        ax.grid(color="#e5e7eb", linewidth=0.7)
        fig.tight_layout()
        fig.savefig(FIGURES / "peer_reference_examples.png", dpi=180)
        plt.close(fig)


def reported_dependency_audit(queue: pd.DataFrame) -> dict[str, object]:
    ab = queue["review_grade"].isin(["A", "B"])
    a = queue["review_grade"].eq("A")
    b = queue["review_grade"].eq("B")
    current_miss = queue["performance_signal"].fillna(False).astype(bool)
    repeated_miss = queue["reported_target_miss_consecutive"].fillna(False).astype(bool)
    comparable = pd.to_numeric(queue["comparable_rate_count"], errors="coerce")
    target_met = comparable.gt(0) & ~current_miss
    performance_missing = comparable.isna() | comparable.le(0)
    return {
        "ab_count": int(ab.sum()),
        "a_count": int(a.sum()),
        "b_count": int(b.sum()),
        "a_without_current_or_repeated_miss": int((a & ~current_miss & ~repeated_miss).sum()),
        "b_without_current_or_repeated_miss": int((b & ~current_miss & ~repeated_miss).sum()),
        "coherent_nonmiss_execution_rows_capped_or_held": int(
            (
                (target_met | performance_missing)
                & ~current_miss
                & queue["review_grade"].isin(["C", "H"])
            ).sum()
        ),
        "classification": "RULE_STRUCTURAL_DEPENDENCY",
        "synthetic_b_path_note": (
            "격리 등급함수에는 강한/반복 집행만으로 B 조건이 있으나, 생산 upstream에서 "
            "비교가능 성과는 미달/달성으로 완전 분할되고 달성·성과결측+집행은 특례 C이므로 "
            "일관된 생산 입력에서는 성과 앵커 없는 B가 성립하지 않는다."
        ),
    }


def _metric(summary: pd.DataFrame, cohort: str, metric: str) -> pd.Series:
    selected = summary.loc[summary["cohort"].eq(cohort) & summary["metric"].eq(metric)]
    if len(selected) != 1:
        raise RuntimeError(f"시간외 요약 metric 불일치: {cohort}/{metric}")
    return selected.iloc[0]


def build_reports(
    dependency: dict[str, object],
    sensitivity: pd.DataFrame,
    ablation_summary: pd.DataFrame,
    priority_2024: pd.DataFrame,
    workload: pd.DataFrame,
    by_grade: pd.DataFrame,
    temporal_cases: pd.DataFrame,
    temporal_summary: pd.DataFrame,
    peer_audit: pd.DataFrame,
    peer_references: pd.DataFrame,
) -> None:
    priority = workload.set_index("analysis_group").loc["PRIORITY_REVIEW"]
    core = workload.set_index("analysis_group").loc["THRESHOLD_STABLE_AB_CORE"]
    boundary = workload.set_index("analysis_group").loc["THRESHOLD_BOUNDARY_AB"]
    unit_total = int(
        workload.loc[
            workload["analysis_group"].isin(
                ["PRIORITY_REVIEW", "CONTEXT_REVIEW", "MONITOR", "DATA_HOLD"]
            ),
            "linked_source_review_unit_count",
        ].sum()
    )
    boundary_names = ", ".join(
        priority_2024.loc[priority_2024["threshold_boundary"], "performance_program_name"]
    )
    exact = int(priority_2024["exact_grade_stable"].sum())
    stable = int(priority_2024["threshold_stable_ab"].sum())
    available = int(temporal_cases["followup_available"].sum())
    total_temporal = len(temporal_cases)
    ab_same = _metric(temporal_summary, "A+B", "NEXT_YEAR_SAME_SIGNAL_FAMILY")
    ab_keep = _metric(temporal_summary, "A+B", "NEXT_YEAR_AB")
    eligible_peer = int(peer_audit["peer_eligible"].sum())
    held_peer = len(peer_audit) - eligible_peer
    sensitivity_nonbaseline = sensitivity.loc[sensitivity["scenario_id"].ne("baseline")]
    retention_min = sensitivity_nonbaseline["grade_retention_rate"].min()
    retention_max = sensitivity_nonbaseline["grade_retention_rate"].max()
    jaccard_min = sensitivity_nonbaseline["ab_jaccard"].min()
    jaccard_max = sensitivity_nonbaseline["ab_jaccard"].max()
    extreme = int(sensitivity_nonbaseline["a_to_d_or_d_to_a_count"].sum())

    grade_table = "\n".join(
        f"| {row.review_grade} | {row.program_count} | {row.original_budget_share:.2%} | "
        f"{row.current_budget_share:.2%} |"
        for row in by_grade.itertuples()
    )
    ablation_table = "\n".join(
        f"| {row.signal_family_removed} | {row.grade_changed_count} | {row.ab_exit_count} | "
        f"{row.c_to_d_or_d_to_c_count} |"
        for row in ablation_summary.itertuples()
    )
    operational = f"""# 프로그램-연도 운영 분석 보고서

## 기술 요약

2024년 77개 중 생산 A+B는 6개({priority.program_share:.2%})이며, 5개가 모든 OAT 변형에서 A+B를 유지했습니다. 정확 등급까지 유지한 사례는 {exact}개이고 업무그룹 경계 사례는 `{boundary_names}` 1개입니다. 생산 등급은 변경하지 않았습니다.

reported performance 의존성은 `{dependency["classification"]}`입니다. A의 두 경로는 현재 또는 연속 성과미달을 직접 요구합니다. B에는 집행 단독 조건식이 존재하지만 생산 입력의 성과 상태 완전분할과 특례 C precedence 때문에 일관된 입력에서는 성과 앵커 없는 B가 성립하지 않습니다.

## 임계값 안정성과 신호 의존성은 서로 다른 질문이다

- A~D 정확 등급 유지율: {retention_min:.2%}~{retention_max:.2%}
- A+B Jaccard: {jaccard_min:.4f}~{jaccard_max:.4f}
- A↔D: {extreme}건
- 2024 A+B: 업무그룹 유지 {stable}/6, 정확 등급 유지 {exact}/6, 경계 {int(boundary.program_count)}/6

| 제거 신호 | 등급 변경 | A/B 이탈 | C↔D |
|---|---:|---:|---:|
{ablation_table}

ablation은 신호 제거 시 규칙이 얼마나 반응하는지 보여주며 독립 기여율이나 feature importance가 아닙니다. 설명 precedence 결함 3행은 원시 `repeated_low_execution_signal`, `performance_signal`, `reported_target_miss_consecutive`, `budget_increase_context_signal`과 `grade_trigger_signal_families`로 판독했습니다.

## 범위와 정의

- 단위: 프로그램×연도 236행, 압축 분석은 2024년 77행
- `threshold_stable_ab`: 6개 OAT 변형 모두 A 또는 B
- `threshold_boundary`: 하나 이상의 OAT 변형에서 기준 업무그룹 이탈
- `signal_dependency_signature`: 등급을 바꾼 제거 신호 계열 목록
- 원문 검토단위: `raw_candidate_ids → candidate_id → project_id`의 명시적 연결

## 한계와 다음 단계

등급은 성과판정이나 위험확률이 아니라 원문 검토 순서입니다. 안정 핵심군은 보조 설명일 뿐 새 생산등급이 아닙니다. 대시보드·발표에는 생산 A+B와 안정/경계를 나란히 표시하되 정렬은 바꾸지 않는 것이 적절합니다.
"""
    (ROOT / "docs/OPERATIONAL_ANALYSIS_REPORT.md").write_text(operational, encoding="utf-8")

    workload_report = f"""# 검토범위 압축 보고서

## 기술 요약

2024년 생산 A+B는 6/77개({priority.program_share:.2%})로 프로그램 검토범위를 압축합니다. 이 6개가 차지하는 본예산은 {priority.original_budget_share:.2%}, 예산현액은 {priority.current_budget_share:.2%}, 연결 성과지표는 {priority.linked_indicator_share:.2%}, 비교가능 성과지표는 {priority.comparable_indicator_share:.2%}입니다.

원문 검토단위는 `candidate_id×project_id`로 연결된 2024년 {unit_total:,}개 중 A+B {int(priority.linked_source_review_unit_count):,}개({priority.source_review_unit_share:.2%})입니다. H의 일부 candidate는 상세사업이 연결되지 않아 잠재 원문 전체량이 아니라 실제 연결 가능한 단위만 분모로 사용했습니다.

## 등급별 규모와 예산 비중

| 등급 | 프로그램 수 | 본예산 비중 | 예산현액 비중 |
|---|---:|---:|---:|
{grade_table}

## 안정 핵심군과 경계군

- 임계값 안정 핵심군: {int(core.program_count)}/6
- 임계값 경계군: {int(boundary.program_count)}/6 (`{boundary_names}`)
- A+B 내부 반복·복합 구조화 신호 포함: {int(priority.repeated_or_complex_signal_count)}/{int(priority.program_count)}

![2024년 검토업무 분할](../validation/figures/workload_compression.png)

## 해석 제한

압축률은 검토업무 분할을 뜻합니다. 문제사업 포착률·정확도·재현율이 아닙니다. H는 우선순위 축에 누적하지 않고 데이터 보완 업무로 분리했습니다.
"""
    (ROOT / "docs/WORKLOAD_COMPRESSION_REPORT.md").write_text(workload_report, encoding="utf-8")

    temporal_report = f"""# 다음 연도 방향성 분석 보고서

## 기술 요약

2022·2023년 기준 {total_temporal}개 프로그램-연도 중 정확한 `program_identity_id`로 다음 연도를 연결한 표본은 {available}/{total_temporal}개입니다. 기준 A+B 중 다음 연도 동일 신호계열 관측은 {int(ab_same.numerator)}/{int(ab_same.denominator)}({ab_same.rate:.2%}), 다음 연도 A+B 유지는 {int(ab_keep.numerator)}/{int(ab_keep.denominator)}({ab_keep.rate:.2%})였습니다.

![다음 연도 등급 이동](../validation/figures/temporal_grade_transition.png)

## 방법

2022→2023, 2023→2024만 사용했습니다. 명칭 유사도나 추정 연결은 사용하지 않았고 identity unresolved·UNKNOWN_CONTINUITY·후속연도 결측은 사유와 함께 제외했습니다. 미래자료는 기준연도 등급 판정에 입력하지 않았습니다.

## 한계

이는 다음 연도 관측과의 방향적 연관성입니다. 예측 정확도·적중률·모델 성능·인과효과·정책효과를 뜻하지 않습니다. 모든 비율은 `temporal_followup_summary.csv`에 분자와 분모를 함께 저장했습니다.
"""
    (ROOT / "docs/TEMPORAL_FOLLOWUP_REPORT.md").write_text(temporal_report, encoding="utf-8")

    peer_report = f"""# 조건부 동료집단 상대위치 보고서

## 기술 요약

감사 대상은 236행×2지표={len(peer_audit)}행입니다. 조건을 모두 충족한 계산 가능 행은 {eligible_peer}행, 보류는 {held_peer}행이며 실제 백분위 산출은 {len(peer_references)}행입니다.

유효 집단은 동일 부처·동일 연도·정확히 같은 회계구성으로 정의했습니다. n≥10, 고유값≥5, 프로그램×연도 단위, 양의 비교가능 분모, identity 정상 조건을 모두 적용했습니다. 성과달성률 백분위는 계산하지 않았습니다.

## 발표 사용 권고

계산 가능 범위가 매우 좁아 발표 핵심 분석으로 사용하지 않는 것을 권고합니다. 값은 해당 동료집단 안에서의 설명 참고값이며 생산 등급·정렬·진단을 바꾸지 않습니다.
"""
    (ROOT / "docs/PEER_REFERENCE_REPORT.md").write_text(peer_report, encoding="utf-8")

    presentation = f"""# 데이터분석 발표 요약

## 현재 규칙의 성격

- 결론: A+B의 reported performance 의존성은 현재 표본의 우연이 아니라 생산 파이프라인과 precedence가 만든 구조적 의존성입니다.
- A는 두 복합 규칙 모두 현재 또는 연속 성과미달을 요구합니다.
- B의 코드에는 강한·반복 집행 단독 조건이 있으나, 성과달성+집행과 성과결측+집행은 특례 C로 먼저 분기됩니다. 생산 upstream은 비교가능 성과를 미달/달성으로 완전 분할하므로 일관된 입력에서 성과 앵커 없는 B는 없습니다.
- 따라서 ‘성과 앵커형 점검모델’은 정확한 표현입니다. 집행·반복은 A/B를 강화하고, budget mismatch는 A+B 포함보다 A↔B 및 C↔D 세부등급을 조정합니다.
- 수정할 표현: “성과신호 제거에도 유지되는 사례가 안정 핵심” 대신 “임계값 안정성과 신호 구성 의존성을 분리해 설명”합니다.

## 임계값 안정성

- A~D 유지율: {retention_min:.2%}~{retention_max:.2%}
- A+B Jaccard: {jaccard_min:.4f}~{jaccard_max:.4f}
- 2024 A+B 6개 중 업무그룹 유지 {stable}개, 정확 등급 유지 {exact}개
- 경계 사례: `{boundary_names}`
- A↔D: {extreme}건

## 신호 의존성

- reported performance 제거 시 A+B 30개 전부 이탈: 구조적 앵커를 제거한 결과이며 외부 타당성 증거가 아닙니다.
- execution 제거: 등급 변경 {int(ablation_summary.set_index("signal_family_removed").loc["execution", "grade_changed_count"])}건, A/B 이탈 {int(ablation_summary.set_index("signal_family_removed").loc["execution", "ab_exit_count"])}건.
- repetition 제거: 등급 변경 {int(ablation_summary.set_index("signal_family_removed").loc["repetition", "grade_changed_count"])}건, A/B 이탈 {int(ablation_summary.set_index("signal_family_removed").loc["repetition", "ab_exit_count"])}건.
- budget mismatch 제거: A/B 이탈 0건이지만 세부등급 변경은 {int(ablation_summary.set_index("signal_family_removed").loc["budget_performance_mismatch", "grade_changed_count"])}건.
- 신호 계열이 겹치므로 ablation을 독립 기여율로 해석할 수 없습니다.

## 검토범위 압축

- 77개 중 A+B 6개({priority.program_share:.2%})
- 임계값 안정 핵심군 {stable}개, 경계군 {int(boundary.program_count)}개
- A+B 본예산 비중 {priority.original_budget_share:.2%}, 예산현액 비중 {priority.current_budget_share:.2%}
- A+B 연결 성과지표 {int(priority.linked_indicator_count)}개({priority.linked_indicator_share:.2%})
- A+B 연결 원문 검토단위 {int(priority.linked_source_review_unit_count):,}개({priority.source_review_unit_share:.2%})

## 시간외 방향성

- 후속 관측 가능: {available}/{total_temporal}
- A+B 다음 연도 동일 신호계열: {int(ab_same.numerator)}/{int(ab_same.denominator)}({ab_same.rate:.2%})
- A+B 다음 연도 A+B 유지: {int(ab_keep.numerator)}/{int(ab_keep.denominator)}({ab_keep.rate:.2%})
- 예측력이 아니라 정확 식별자 연결 표본의 방향적 연관성입니다.

## peer 분석

- 감사 {len(peer_audit)}행 중 계산 가능 {eligible_peer}행, 보류 {held_peer}행
- 계산 범위가 좁아 발표 핵심 분석으로 쓰지 않고 설명 참고값으로만 둡니다.

## 발표에서 과장하지 않을 주장

- 등급을 사업 성과·위험·정책효과로 부르지 않습니다.
- 내부 신호 포함범위를 정확도·재현율·문제사업 포착률로 부르지 않습니다.
- 시간외 연관성을 예측력이나 인과효과로 부르지 않습니다.
- peer 백분위를 생산 등급 근거로 사용하지 않습니다.
"""
    (ROOT / "docs/DATA_ANALYSIS_PRESENTATION_SUMMARY.md").write_text(presentation, encoding="utf-8")


def main() -> None:
    completed = ["기준 검증"]
    _checkpoint(completed)
    queue, candidates, projects = load_inputs()
    queue = attach_linked_counts(queue, candidates, projects)
    completed.append("기존 판정 조건과 강건성 산출물 추적")
    _checkpoint(completed)

    profile, priority_2024 = build_robustness_profile(queue)
    completed.append("안정성·의존성 층화표")
    _checkpoint(completed)

    workload, _, by_grade, _ = build_workload_outputs(queue, profile)
    completed.append("검토범위 압축 분석")
    _checkpoint(completed)

    temporal_cases, temporal_summary, transitions = build_temporal_outputs(queue, profile)
    completed.append("시간외 방향성 분석")
    _checkpoint(completed)

    peer_audit, peer_references = build_peer_outputs(queue)
    completed.append("peer 가능성 감사 및 조건부 백분위")
    _checkpoint(completed)

    sensitivity = pd.read_csv(VALIDATION / "grade_sensitivity_scenarios.csv")
    ablation_summary = pd.read_csv(VALIDATION / "signal_ablation_summary.csv")
    dependency = reported_dependency_audit(queue)
    build_figures(priority_2024, transitions, peer_references)
    completed.append("그림")
    _checkpoint(completed)
    build_reports(
        dependency,
        sensitivity,
        ablation_summary,
        priority_2024,
        workload,
        by_grade,
        temporal_cases,
        temporal_summary,
        peer_audit,
        peer_references,
    )
    completed.append("보고서와 발표 요약")
    _checkpoint(completed)


if __name__ == "__main__":
    main()
