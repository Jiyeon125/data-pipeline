from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from analytics.mss_priority_scenario_analysis import (
    PriorityScenarioError,
    apply_question_review_grades,
    build_program_year_review_queue,
    load_scenario_config,
)

ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "data/analytics/multi_ministry_priority_scenarios/program_year_review_queue.csv"
ACCOUNT_QUEUE_PATH = (
    ROOT / "data/analytics/multi_ministry_priority_scenarios/full_population_review_work_queue.csv"
)
CONFIG_PATH = ROOT / "configs/priority_scenarios.yaml"
SOURCE_PATH = ROOT / "src/analytics/mss_priority_scenario_analysis.py"
EXPECTED_SHA256 = "d7c59cc14da21f0e669f2e09867766100957ddad68f8600b43d64392c6236a96"
GRADE_PRIORITY = {"A": 0, "B": 1, "C": 2, "D": 3}
STRENGTH_ORDER = {"STRONG": 0, "MODERATE": 1, "AMBIGUOUS": 2, "NONE": 3, "NOT_ASSESSED": 4}
OUTPUT_COLUMNS = [
    "review_grade",
    "reviewability_status",
    "diagnostic_type",
    "grade_reason_codes",
    "next_review_question",
    "grade_trigger_signal_families",
    "context_flags",
]


def _grade_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ministry_code": "102",
        "field_name": "분야",
        "sector_name": "부문",
        "program_code": "P",
        "fiscal_year": 2024,
        "data_validation_signal": False,
        "comparable_rate_count": 1,
        "below_target_count": 0,
        "reported_target_status": "ALL_COMPARABLE_AT_OR_ABOVE_TARGET",
        "performance_signal": False,
        "current_execution_severity": 0.0,
        "type_repeated_strong_low_execution_budget_share": 0.0,
        "type_repeated_moderate_low_execution_budget_share": 0.0,
        "type_repeated_year_end_concentration_budget_share": 0.0,
        "reported_target_miss_consecutive": False,
        "repeated_low_execution_signal": False,
        "budget_increase_context_signal": False,
        "budget_decrease_context_signal": False,
        "budget_mismatch_signal": False,
        "accounting_context_signal": False,
        "structure_context_signal": False,
        "evidence_status": "CONFIRMED",
        "indicator_coverage_status": "COMPLETE_REPORTED_RATE_COVERAGE",
    }
    row.update(changes)
    return row


def _grade(**changes: object) -> pd.Series:
    return apply_question_review_grades(pd.DataFrame([_grade_row(**changes)])).iloc[0]


def decision_table() -> pd.DataFrame:
    common_sort = "fiscal_year; review_grade_order; signal_strength; independent_signal_family_count desc; program_original_budget desc"
    tie = "program_year_id asc"
    rows = [
        (
            "H1",
            "H",
            1,
            "data_validation_signal",
            "NONE",
            "data_quality",
            "NONE",
            "blocked upstream data",
            "display only",
            "data/linkage invalid",
            "DATA_OR_COMPARABILITY_HOLD",
        ),
        (
            "H2",
            "H",
            1,
            "performance missing AND no execution signal",
            "NONE",
            "data_quality",
            "NONE",
            "missing performance blocks judgment only when execution signal is absent",
            "display only",
            "performance not comparable",
            "DATA_OR_COMPARABILITY_HOLD",
        ),
        (
            "H3",
            "H",
            1,
            "program identity key incomplete",
            "NONE",
            "data_quality",
            "NONE",
            "missing key is not imputed",
            "display only",
            "identity unresolved",
            "DATA_OR_COMPARABILITY_HOLD",
        ),
        (
            "C1",
            "C",
            2,
            "execution signal AND reported target met AND no performance miss",
            "hold",
            "execution",
            "NONE",
            "missing performance uses C2",
            "budget/account/structure context cannot raise grade",
            "reviewable with limitation",
            "LOW_EXECUTION_TARGET_MET",
        ),
        (
            "C2",
            "C",
            2,
            "execution signal AND performance missing AND not data blocked",
            "hold",
            "execution;data_quality",
            "NONE",
            "missing performance is retained as limitation",
            "display only",
            "performance comparison unavailable",
            "LOW_EXECUTION_PERFORMANCE_INFORMATION_MISSING",
        ),
        (
            "C3",
            "C",
            2,
            "confirmed multiyear context AND current low execution only",
            "hold; repeated low execution; performance miss; budget increase",
            "execution",
            "NONE",
            "context must be confirmed",
            "relaxes single-year low execution to C",
            "comparable after context confirmation",
            "MULTIYEAR_CONTEXT_WITH_SINGLE_YEAR_LOW_EXECUTION",
        ),
        (
            "A1",
            "A",
            3,
            "repeated low execution AND reported performance miss",
            "hold; special C",
            "execution;reported_performance",
            "repeated low execution",
            "missing values do not create signals",
            "context display only",
            "reviewable",
            "REPEATED_LOW_EXECUTION_WITH_REPORTED_TARGET_MISS",
        ),
        (
            "A2",
            "A",
            3,
            "consecutive reported target miss AND budget increase",
            "hold; special C",
            "reported_performance;budget_performance_mismatch",
            "consecutive-year target miss",
            "nonconsecutive years do not count",
            "budget increase participates only in this explicit compound rule",
            "reviewable",
            "REPEATED_REPORTED_TARGET_MISS_WITH_BUDGET_INCREASE",
        ),
        (
            "B1",
            "B",
            4,
            "performance miss AND execution signal",
            "hold; special C; A",
            "execution;reported_performance",
            "not required",
            "missing signals are false",
            "display only",
            "reviewable",
            "STRONG_OR_REPEATED_SINGLE_SIGNAL",
        ),
        (
            "B2",
            "B",
            4,
            "strong current low execution OR repeated low execution OR consecutive performance miss",
            "hold; special C; A",
            "applicable single family",
            "strong or repeated",
            "missing signals are false",
            "display only",
            "reviewable",
            "STRONG_OR_REPEATED_SINGLE_SIGNAL",
        ),
        (
            "C4",
            "C",
            5,
            "one of performance miss, execution, budget mismatch, target adequacy",
            "hold; special C; A; B",
            "applicable single family",
            "target adequacy requires repeated overachievement and unchanged target",
            "missing signals are false",
            "context alone excluded",
            "limited",
            "SINGLE_SIGNAL_REVIEW or TARGET_ADEQUACY_REVIEW",
        ),
        (
            "D1",
            "D",
            6,
            "no grade-trigger signal",
            "hold; special C; A; B; C",
            "NONE",
            "NONE",
            "absence is not proof of safety",
            "context-only remains D and does not add trigger families",
            "reviewable",
            "NO_STRUCTURED_SIGNAL_DETECTED",
        ),
    ]
    columns = [
        "rule_id",
        "review_grade",
        "precedence",
        "entry_required",
        "excluded_by",
        "signal_families",
        "repeat_condition",
        "missing_handling",
        "context_effect",
        "identity_comparability",
        "diagnostic_type",
    ]
    result = pd.DataFrame(rows, columns=columns)
    result["grade_reason_codes"] = result["diagnostic_type"]
    result["next_review_question_rule"] = result["diagnostic_type"].map(
        {
            "DATA_OR_COMPARABILITY_HOLD": "confirm program key, amount unit, and performance comparability first",
            "LOW_EXECUTION_TARGET_MET": "verify denominator/comparability, then target adequacy, demand, savings, and lag",
            "LOW_EXECUTION_PERFORMANCE_INFORMATION_MISSING": "confirm why performance is missing and verify execution denominator",
            "MULTIYEAR_CONTEXT_WITH_SINGLE_YEAR_LOW_EXECUTION": "compare the year with the planned multiyear stage",
            "REPEATED_LOW_EXECUTION_WITH_REPORTED_TARGET_MISS": "verify overlap in the same program scope and years",
            "REPEATED_REPORTED_TARGET_MISS_WITH_BUDGET_INCREASE": "verify overlap in the same program scope and years",
            "STRONG_OR_REPEATED_SINGLE_SIGNAL": "check official explanation and indicator changes",
            "SINGLE_SIGNAL_REVIEW or TARGET_ADEQUACY_REVIEW": "check exceptions/comparability; target adequacy has a dedicated question",
            "NO_STRUCTURED_SIGNAL_DETECTED": "check whether structured inputs are sufficiently complete",
        }
    )
    result["within_grade_sort_keys"] = common_sort
    result["final_tie_break"] = tie
    return result


def _audit_row(
    check_id: str,
    mask: pd.Series,
    queue: pd.DataFrame,
    evidence: str,
) -> dict[str, object]:
    failed = queue.loc[mask, "program_year_id"].astype(str).tolist()
    return {
        "check_id": check_id,
        "status": "PASS" if not failed else "FAIL",
        "checked_rows": len(queue),
        "failure_count": len(failed),
        "evidence": evidence,
        "failed_program_year_ids": ";".join(failed[:20]),
    }


def contract_audit(queue: pd.DataFrame) -> pd.DataFrame:
    allowed = {"A", "B", "C", "D", "H"}
    expected_reviewability = {
        "A": "REVIEWABLE",
        "B": "REVIEWABLE",
        "C": "LIMITED",
        "D": "REVIEWABLE",
        "H": "HOLD",
    }
    source = inspect.getsource(apply_question_review_grades)
    audit = [
        _audit_row(
            "program_year_id_unique",
            queue["program_year_id"].duplicated(keep=False),
            queue,
            "236-row final key",
        ),
        _audit_row(
            "exactly_one_review_grade",
            queue["review_grade"].isna() | ~queue["review_grade"].isin(allowed),
            queue,
            "allowed mutually exclusive values A/B/C/D/H",
        ),
        _audit_row(
            "one_primary_diagnostic_type",
            queue["diagnostic_type"].fillna("").str.strip().eq("")
            | queue["diagnostic_type"].astype(str).str.contains(";"),
            queue,
            "one nonempty diagnostic cell",
        ),
        _audit_row(
            "one_primary_grade_reason_code",
            queue["grade_reason_codes"].fillna("").str.strip().eq("")
            | queue["grade_reason_codes"].astype(str).str.contains(";"),
            queue,
            "one nonempty reason-code cell",
        ),
        _audit_row(
            "reason_matches_primary_diagnostic",
            queue["grade_reason_codes"].ne(queue["diagnostic_type"]),
            queue,
            "current code aliases reason code to primary diagnostic",
        ),
        _audit_row(
            "grade_reviewability_consistent",
            queue["reviewability_status"].ne(queue["review_grade"].map(expected_reviewability)),
            queue,
            "A/B/D reviewable, C limited, H hold",
        ),
        _audit_row(
            "H_separate_hold_axis",
            queue["review_grade"].eq("H")
            & (
                queue["reviewability_status"].ne("HOLD")
                | queue["signal_strength"].ne("NOT_ASSESSED")
            ),
            queue,
            "H is hold/not-assessed, not A-D signal strength",
        ),
        _audit_row(
            "context_only_is_D",
            queue["context_only"].fillna(False).astype(bool) & queue["review_grade"].ne("D"),
            queue,
            "context flags do not trigger grade",
        ),
        _audit_row(
            "low_execution_target_met_is_C",
            queue["diagnostic_type"].eq("LOW_EXECUTION_TARGET_MET") & queue["review_grade"].ne("C"),
            queue,
            "explicit special-C rule",
        ),
        _audit_row(
            "identity_unresolved_is_H",
            queue["identity_unresolved"].fillna(False).astype(bool) & queue["review_grade"].ne("H"),
            queue,
            "aggregator converts unresolved identity to data-validation hold",
        ),
        _audit_row(
            "data_or_comparability_hold_is_H",
            queue["diagnostic_type"].eq("DATA_OR_COMPARABILITY_HOLD")
            & queue["review_grade"].ne("H"),
            queue,
            "hold diagnostic must be H",
        ),
        _audit_row(
            "t1_t2_not_grade_inputs",
            pd.Series("_t1" in source or "_t2" in source, index=queue.index),
            queue,
            "static inspection of grade function",
        ),
        _audit_row(
            "signal_score_not_imputed_in_grade",
            pd.Series("signal_score" in source, index=queue.index),
            queue,
            "signal_score absent from grade function and final 236-row schema",
        ),
    ]
    return pd.DataFrame(audit)


def _property(
    group: str,
    check_id: str,
    passed: bool,
    expected: str,
    observed: str,
    evidence: str,
) -> dict[str, object]:
    return {
        "property_group": group,
        "check_id": check_id,
        "status": "PASS" if passed else "FAIL",
        "expected": expected,
        "observed": observed,
        "evidence": evidence,
    }


def property_audit() -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    monotonic_cases = [
        (
            "D_to_C_performance",
            {},
            {
                "performance_signal": True,
                "below_target_count": 1,
                "reported_target_status": "ALL_COMPARABLE_BELOW_TARGET",
            },
        ),
        ("D_to_C_execution", {}, {"current_execution_severity": 0.5}),
        (
            "C_to_B_two_domains",
            {
                "performance_signal": True,
                "below_target_count": 1,
                "reported_target_status": "ALL_COMPARABLE_BELOW_TARGET",
            },
            {"current_execution_severity": 0.5},
        ),
        (
            "B_to_A_repeated_execution",
            {
                "performance_signal": True,
                "below_target_count": 1,
                "reported_target_status": "ALL_COMPARABLE_BELOW_TARGET",
                "current_execution_severity": 0.5,
            },
            {"repeated_low_execution_signal": True},
        ),
        (
            "B_to_A_repeated_miss_budget",
            {
                "performance_signal": True,
                "below_target_count": 1,
                "reported_target_status": "ALL_COMPARABLE_BELOW_TARGET",
                "reported_target_miss_consecutive": True,
            },
            {"budget_increase_context_signal": True},
        ),
    ]
    for name, before_changes, added in monotonic_cases:
        before = _grade(**before_changes)["review_grade"]
        after = _grade(**before_changes, **added)["review_grade"]
        passed = (
            before in GRADE_PRIORITY
            and after in GRADE_PRIORITY
            and GRADE_PRIORITY[after] <= GRADE_PRIORITY[before]
        )
        rows.append(
            _property(
                "monotonicity",
                name,
                passed,
                "same or higher A-D review priority",
                f"{before}->{after}",
                "one independent adverse signal added",
            )
        )

    exception = _grade(current_execution_severity=0.5, repeated_low_execution_signal=True)
    rows.append(
        _property(
            "monotonicity",
            "documented_target_met_exception",
            exception["review_grade"] == "C",
            "C",
            str(exception["review_grade"]),
            "LOW_EXECUTION_TARGET_MET caps execution-only target-met cases at C",
        )
    )

    information_cases = [
        (
            "missing_performance_without_execution",
            {
                "comparable_rate_count": pd.NA,
                "below_target_count": pd.NA,
                "reported_target_status": "NO_COMPARABLE_RATE",
            },
            "H",
        ),
        ("data_uncertainty_flag", {"data_validation_signal": True}, "H"),
        ("missing_execution_severity", {"current_execution_severity": pd.NA}, "H"),
        ("identity_unresolved_direct_input", {"identity_unresolved": True}, "H"),
        ("comparability_conflict_direct_input", {"program_performance_status_conflict": True}, "H"),
    ]
    for name, changes, expected in information_cases:
        observed = str(_grade(**changes)["review_grade"])
        rows.append(
            _property(
                "information_degradation",
                name,
                observed == expected,
                expected,
                observed,
                "isolated call to current grade function",
            )
        )

    for name, changes in [
        ("budget_increase_only", {"budget_increase_context_signal": True}),
        ("budget_decrease_only", {"budget_decrease_context_signal": True}),
        ("accounting_only", {"accounting_context_signal": True}),
        ("structure_only", {"structure_context_signal": True}),
        ("year_end_only", {"type_repeated_year_end_concentration_budget_share": 0.2}),
    ]:
        observed = _grade(**changes)
        passed = (
            observed["review_grade"] == "D" and observed["grade_trigger_signal_families"] == "NONE"
        )
        rows.append(
            _property(
                "context_separation",
                name,
                passed,
                "D and zero trigger families",
                f"{observed['review_grade']};{observed['grade_trigger_signal_families']}",
                "context remains display-only",
            )
        )

    counterexamples = [
        ("low_execution_target_met", {"current_execution_severity": 0.5}, "C"),
        ("low_execution_only_not_A", {"current_execution_severity": 1.0}, "C"),
        (
            "missing_performance_low_execution_not_A",
            {
                "current_execution_severity": 0.5,
                "comparable_rate_count": pd.NA,
                "below_target_count": pd.NA,
                "reported_target_status": "NO_COMPARABLE_RATE",
            },
            "C",
        ),
        ("no_structured_signal", {}, "D"),
    ]
    for name, changes, expected in counterexamples:
        observed = str(_grade(**changes)["review_grade"])
        rows.append(
            _property(
                "required_counterexample",
                name,
                observed == expected,
                expected,
                observed,
                "explicit production counterexample",
            )
        )

    base = _grade(current_execution_severity=0.5)
    changed = _grade(
        current_execution_severity=0.5,
        low_performance_budget_increase_t1=True,
        low_performance_budget_increase_t2=True,
        program_total_budget_change_rate_t1=99.0,
        program_total_budget_change_rate_t2=-99.0,
    )
    same = all(base[column] == changed[column] for column in OUTPUT_COLUMNS)
    rows.append(
        _property(
            "time_consistency",
            "t1_t2_values_do_not_change_grade",
            same,
            "identical grade outputs",
            f"{base['review_grade']}->{changed['review_grade']}",
            "all grade output fields compared",
        )
    )

    shuffled_input = pd.DataFrame(
        [
            _grade_row(
                program_code="P2",
                fiscal_year=2024,
                performance_signal=True,
                below_target_count=1,
                reported_target_status="ALL_COMPARABLE_BELOW_TARGET",
            ),
            _grade_row(program_code="P1", fiscal_year=2023, current_execution_severity=0.5),
            _grade_row(program_code="P3", fiscal_year=2022),
        ]
    )
    first = (
        apply_question_review_grades(shuffled_input)
        .sort_values(["program_code", "fiscal_year"])[OUTPUT_COLUMNS]
        .reset_index(drop=True)
    )
    second = (
        apply_question_review_grades(shuffled_input.sample(frac=1, random_state=17))
        .sort_values(["program_code", "fiscal_year"])[OUTPUT_COLUMNS]
        .reset_index(drop=True)
    )
    deterministic = first.equals(second)
    rows.append(
        _property(
            "determinism",
            "input_order_invariant",
            deterministic,
            "identical output",
            str(deterministic),
            "same isolated rows shuffled",
        )
    )
    digest1 = hashlib.sha256(first.to_csv(index=False).encode()).hexdigest()
    digest2 = hashlib.sha256(
        apply_question_review_grades(shuffled_input)
        .sort_values(["program_code", "fiscal_year"])[OUTPUT_COLUMNS]
        .reset_index(drop=True)
        .to_csv(index=False)
        .encode()
    ).hexdigest()
    rows.append(
        _property(
            "determinism",
            "repeat_run_hash",
            digest1 == digest2,
            digest1,
            digest2,
            "canonical CSV serialization",
        )
    )

    account_queue = pd.read_csv(
        ACCOUNT_QUEUE_PATH,
        dtype={"ministry_code": "string", "program_code": "string"},
    )
    config = load_scenario_config(CONFIG_PATH)
    built_first, _ = build_program_year_review_queue(account_queue, config)
    built_shuffled, _ = build_program_year_review_queue(
        account_queue.sample(frac=1, random_state=31), config
    )
    queue_contract_columns = [
        "program_year_id",
        "review_grade",
        "diagnostic_type",
        "program_year_queue_order",
        "review_queue_order_within_year",
    ]
    canonical_first = (
        built_first[queue_contract_columns].sort_values("program_year_id").reset_index(drop=True)
    )
    canonical_shuffled = (
        built_shuffled[queue_contract_columns].sort_values("program_year_id").reset_index(drop=True)
    )
    queue_order_invariant = canonical_first.equals(canonical_shuffled)
    rows.append(
        _property(
            "determinism",
            "full_412_row_input_order_invariant",
            queue_order_invariant,
            "identical grades and queue order",
            str(queue_order_invariant),
            "production 412-row audit input shuffled",
        )
    )
    queue_hash_1 = hashlib.sha256(canonical_first.to_csv(index=False).encode()).hexdigest()
    rebuilt, _ = build_program_year_review_queue(account_queue, config)
    queue_hash_2 = hashlib.sha256(
        rebuilt[queue_contract_columns]
        .sort_values("program_year_id")
        .reset_index(drop=True)
        .to_csv(index=False)
        .encode()
    ).hexdigest()
    rows.append(
        _property(
            "determinism",
            "full_queue_repeat_run_hash",
            queue_hash_1 == queue_hash_2,
            queue_hash_1,
            queue_hash_2,
            "production 412-row input rebuilt twice",
        )
    )
    duplicate_blocked = False
    try:
        build_program_year_review_queue(
            pd.concat([account_queue, account_queue.iloc[[0]]], ignore_index=True), config
        )
    except PriorityScenarioError as exc:
        duplicate_blocked = "candidate_id가 중복" in str(exc)
    rows.append(
        _property(
            "determinism",
            "duplicate_raw_id_explicit_error",
            duplicate_blocked,
            "PriorityScenarioError",
            str(duplicate_blocked),
            "duplicated production audit row",
        )
    )

    source = SOURCE_PATH.read_text(encoding="utf-8")
    duplicate_guard = (
        'if result["program_year_id"].duplicated().any():' in source
        and "프로그램-연도 대기열 기본키가 중복되었습니다." in source
    )
    rows.append(
        _property(
            "determinism",
            "duplicate_program_year_id_guard",
            duplicate_guard,
            "explicit error guard",
            str(duplicate_guard),
            "build_program_year_review_queue output postcondition",
        )
    )
    consecutive_guard = "sub(previous_year).eq(1)" in source
    rows.append(
        _property(
            "time_consistency",
            "nonconsecutive_years_not_repeated",
            consecutive_guard,
            "adjacent fiscal years only",
            str(consecutive_guard),
            "current history implementation",
        )
    )
    future_test = "test_program_year_asof_is_unchanged_when_future_year_is_added" in (
        ROOT / "tests/analytics/test_mss_priority_scenario_analysis.py"
    ).read_text(encoding="utf-8")
    rows.append(
        _property(
            "time_consistency",
            "future_year_does_not_change_past",
            future_test,
            "executable regression test exists",
            str(future_test),
            "related production unit test",
        )
    )
    return pd.DataFrame(rows)


def dominance_audit(queue: pd.DataFrame) -> pd.DataFrame:
    checked = 0
    violations: list[dict[str, object]] = []
    work = queue.copy()
    work["_strength"] = work["signal_strength"].map(STRENGTH_ORDER).fillna(5)
    work["_families"] = -pd.to_numeric(
        work["independent_signal_family_count"], errors="coerce"
    ).fillna(0)
    work["_budget"] = -pd.to_numeric(work["program_original_budget"], errors="coerce").fillna(0)
    for (year, grade), part in work.groupby(["fiscal_year", "review_grade"], dropna=False):
        records = list(part.to_dict("records"))
        for left in records:
            for right in records:
                if left["program_year_id"] == right["program_year_id"]:
                    continue
                left_keys = (left["_strength"], left["_families"], left["_budget"])
                right_keys = (right["_strength"], right["_families"], right["_budget"])
                if all(a <= b for a, b in zip(left_keys, right_keys, strict=True)) and any(
                    a < b for a, b in zip(left_keys, right_keys, strict=True)
                ):
                    checked += 1
                    if (
                        left["review_queue_order_within_year"]
                        > right["review_queue_order_within_year"]
                    ):
                        violations.append(
                            {
                                "status": "FAIL",
                                "fiscal_year": year,
                                "review_grade": grade,
                                "dominant_program_year_id": left["program_year_id"],
                                "dominated_program_year_id": right["program_year_id"],
                                "dominant_queue_order": left["review_queue_order_within_year"],
                                "dominated_queue_order": right["review_queue_order_within_year"],
                                "priority_keys": "signal_strength;independent_signal_family_count_desc;program_original_budget_desc",
                                "checked_dominance_pairs": checked,
                            }
                        )
    if not violations:
        violations.append(
            {
                "status": "PASS",
                "fiscal_year": pd.NA,
                "review_grade": pd.NA,
                "dominant_program_year_id": pd.NA,
                "dominated_program_year_id": pd.NA,
                "dominant_queue_order": pd.NA,
                "dominated_queue_order": pd.NA,
                "priority_keys": "signal_strength;independent_signal_family_count_desc;program_original_budget_desc",
                "checked_dominance_pairs": checked,
            }
        )
    return pd.DataFrame(violations)


def _plot_flow(path: Path) -> None:
    plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False})
    fig, ax = plt.subplots(figsize=(16, 9))
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 9)
    ax.axis("off")
    ax.text(0.8, 8.45, "프로그램×연도 점검등급 결정 흐름", fontsize=24, weight="bold")
    ax.text(
        0.8,
        8.05,
        "A–D는 원문 검토 우선순위 축 · H는 데이터/비교가능성 보류 축",
        fontsize=13,
        color="#374151",
    )
    boxes = [
        (1.0, 6.4, 3.0, 1.0, "입력\n프로그램×연도 신호", "#E5E7EB"),
        (5.0, 6.4, 3.0, 1.0, "판단 가능?\nidentity·comparability", "#DBEAFE"),
        (11.5, 6.4, 3.2, 1.0, "H · 판단 보류\nA–D 위험서열 아님", "#EDE9FE"),
        (5.0, 4.65, 3.0, 1.0, "명시적 특례 C?\n목표달성·성과결측·다년도", "#FEF3C7"),
        (1.0, 2.55, 2.6, 1.0, "A\n명시적 복합 신호", "#FCA5A5"),
        (4.3, 2.55, 2.6, 1.0, "B\n강한/반복 단일", "#FDBA74"),
        (7.6, 2.55, 2.6, 1.0, "C\n단일·맥락 확인", "#FDE68A"),
        (10.9, 2.55, 2.6, 1.0, "D\n현재 신호 미검출", "#BBF7D0"),
    ]
    for x, y, w, h, label, color in boxes:
        ax.add_patch(
            plt.Rectangle((x, y), w, h, facecolor=color, edgecolor="#334155", linewidth=1.5)
        )
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=13, weight="bold")
    arrows = [
        ((4.0, 6.9), (5.0, 6.9), ""),
        ((8.0, 6.9), (11.5, 6.9), "아니오"),
        ((6.5, 6.4), (6.5, 5.65), "예"),
        ((6.5, 4.65), (8.9, 3.55), "예 → C"),
        ((6.5, 4.65), (6.5, 3.85), "아니오: precedence 적용"),
    ]
    for start, end, label in arrows:
        ax.annotate(
            "", xy=end, xytext=start, arrowprops={"arrowstyle": "->", "lw": 1.8, "color": "#475569"}
        )
        if label:
            ax.text(
                (start[0] + end[0]) / 2,
                (start[1] + end[1]) / 2 + 0.18,
                label,
                ha="center",
                fontsize=10,
            )
    ax.text(1.0, 1.25, "A–D precedence: 명시적 A → B → 일반 C → D", fontsize=13, weight="bold")
    ax.text(
        1.0,
        0.82,
        "동일 연도·동일 등급 정렬: 신호강도 → 독립 신호계열 수 → 본예산(동률 정리) → program_year_id",
        fontsize=11,
    )
    ax.text(
        1.0,
        0.42,
        "미사용: signal_score · T+1/T+2 · 가중치 시나리오 · legacy lane",
        fontsize=11,
        color="#4B5563",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _write_rulebook(
    path: Path,
    contract: pd.DataFrame,
    properties: pd.DataFrame,
    dominance: pd.DataFrame,
) -> None:
    prop_counts = properties["status"].value_counts().to_dict()
    contract_counts = contract["status"].value_counts().to_dict()
    dominance_failures = int(dominance["status"].eq("FAIL").sum())
    text = f"""# 생산 점검등급 및 대기열 규칙서

## 기준과 범위

- 기준 HEAD: `6dc0bd96e1beac66b6cdbd4900286b671f54e1ec`
- 생산 CSV SHA-256: `{EXPECTED_SHA256}`
- 분석 버전: `review_workbench_v5_identity_context_resolution`
- 출력 스키마: `priority_review_outputs_v5_identity_context_resolution`
- 최종 단위: 프로그램×연도 236행, 원시 감사 단위: 프로그램×연도×회계유형 412행
- 이 문서는 현재 생산 코드의 계약을 설명하며 생산 등급·CSV를 변경하지 않습니다.

등급은 사업평가나 위험확률이 아니라 원문 검토 순서입니다. A–D만 검토 우선순위 축이고 H는 데이터·식별자·비교가능성 문제로 판단을 보류하는 별도 축입니다.

## 결정 precedence

1. **H**: `data_validation_signal`, 성과정보 결측이면서 집행 신호도 없음, 또는 프로그램 식별키 불완전
2. **특례 C**: 저집행+보고목표 달성, 저집행+성과정보 없음, 확인된 다년도 맥락의 단년도 저집행
3. **A**: 반복 저집행+보고목표 미달, 또는 연속 목표미달+예산 증가
4. **B**: 성과미달+집행 신호의 두 영역 결합, 강한 현재 저집행, 반복 저집행, 연속 목표미달
5. **일반 C**: 단일 성과·집행·예산불일치·목표적정성 신호
6. **D**: 위 조건이 없으며 context만 있거나 현재 구조화 신호가 없음

세부 조합과 진단·질문·결측·제외조건은 [`validation/review_grade_decision_table.csv`](../validation/review_grade_decision_table.csv)에 있습니다. 같은 행에서 A 진단 두 개가 동시에 성립하면 코드의 후행 할당 때문에 `REPEATED_REPORTED_TARGET_MISS_WITH_BUDGET_INCREASE`가 primary diagnostic이 됩니다. 특례 C에서는 다년도 진단이 후행하여 다른 특례 C 진단을 덮어쓸 수 있습니다.

## 신호와 context

- 등급 신호계열: `data_quality`, `execution`, `reported_performance`, `budget_performance_mismatch`, `target_or_trend`.
- context: 예산 증가·감소, 회계조정, 프로그램 구조, 반복 연말집중. context만 있으면 D이며 `grade_trigger_signal_families`를 늘리지 않습니다.
- `LOW_EXECUTION_TARGET_MET`는 명시적 충돌 특례로 C입니다. 저집행만으로 A가 되지 않습니다.
- 반복은 전년과 회계연도가 정확히 1 차이일 때만 성립합니다. 2022와 2024만 있으면 반복이 아닙니다.
- `grade_reason_codes`는 현재 별도 다중코드가 아니라 primary `diagnostic_type`의 복사값입니다.

## identity·comparability와 결측

프로그램-연도 집계기는 식별자 미해소, 프로그램명·성과상태 충돌, 금액 결측, 비공동분석 행을 `data_validation_signal`로 승격한 뒤 등급 함수에 전달합니다. 따라서 현재 236행에서는 해당 사례가 H입니다. 다만 격리된 등급 함수는 `identity_unresolved`와 `program_performance_status_conflict`를 직접 읽지 않고 upstream 플래그에 의존합니다.

성과 비교가능 건수가 없고 집행 신호도 없으면 H, 저집행 신호가 있으면 특례 C입니다. 숫자 신호 결측은 다수 조건에서 0/False처럼 처리되므로 격리 호출에서 집행 심각도 결측이 D로 완화되는 속성 위반이 있습니다. 생산 집계기의 upstream 검증이 일부를 막지만 함수 자체의 완전한 정보악화 계약은 아닙니다.

## 대기열 정렬 계약

최종 `program_year_queue_order`는 다음의 안정 정렬입니다.

1. `fiscal_year` 오름차순
2. `review_grade_order`: H, A, B, C, D — H 선두는 데이터 확인 업무를 먼저 처리하기 위한 queue precedence이며 위험서열이 아닙니다.
3. `signal_strength`: STRONG, MODERATE, AMBIGUOUS, NONE, NOT_ASSESSED
4. `independent_signal_family_count` 내림차순
5. `program_original_budget` 내림차순 — 등급 변경 없이 동률 정리·업무영향 참고만
6. `program_year_id` 오름차순 최종 tie-break

`review_queue_order_within_year`는 위 정렬 후 연도별로 다시 1부터 부여합니다. `repeated_signal_family_count`, `evidence_strength`, `signal_score`, T+1·T+2는 최종 236행 정렬키가 아닙니다.

## 자동검증 결과

- 236행 계약: PASS {contract_counts.get("PASS", 0)}, FAIL {contract_counts.get("FAIL", 0)}
- 규칙 속성: PASS {prop_counts.get("PASS", 0)}, FAIL {prop_counts.get("FAIL", 0)}
- dominance 위반: {dominance_failures}

속성 실패는 생산 CSV를 바꾸지 않았습니다. 상세 반례는 [`validation/review_grade_property_audit.csv`](../validation/review_grade_property_audit.csv)에 기록했습니다.

## legacy lane과 signal_score 부록

- legacy 여섯 lane은 412행 감사·하위호환용이며 최종 UI 등급체계가 아닙니다.
- legacy 업무큐는 lane, 반복 신호 수, 독립 신호 수, evidence, complete-case `signal_score`, 본예산, candidate_id를 사용합니다.
- `signal_score`는 성과·집행·예산불일치 세 구성요소가 모두 있을 때만 산술평균하며 부분 결측을 0점으로 보충하지 않습니다. legacy 정렬 구현은 결측 여부를 먼저 분리한 뒤 내부 정렬용 값에만 0을 사용합니다.
- 최종 236행 등급 함수와 CSV 스키마에는 `signal_score`가 없으며 등급·정렬에 사용되지 않습니다.
- 가중치 시나리오는 고급 민감도 산출물에만 남고 생산 판정에 사용되지 않습니다.
"""
    path.write_text(text, encoding="utf-8")


def main() -> None:
    actual_hash = hashlib.sha256(QUEUE_PATH.read_bytes()).hexdigest()
    if actual_hash != EXPECTED_SHA256:
        raise SystemExit(f"baseline SHA mismatch: {actual_hash}")
    queue = pd.read_csv(QUEUE_PATH, dtype={"ministry_code": "string", "program_code": "string"})
    if queue.shape != (236, 91):
        raise SystemExit(f"baseline shape mismatch: {queue.shape}")

    decisions = decision_table()
    contract = contract_audit(queue)
    properties = property_audit()
    dominance = dominance_audit(queue)

    output_dir = ROOT / "validation"
    decisions.to_csv(
        output_dir / "review_grade_decision_table.csv", index=False, encoding="utf-8-sig"
    )
    contract.to_csv(
        output_dir / "review_grade_contract_audit.csv", index=False, encoding="utf-8-sig"
    )
    properties.to_csv(
        output_dir / "review_grade_property_audit.csv", index=False, encoding="utf-8-sig"
    )
    dominance.to_csv(output_dir / "queue_dominance_audit.csv", index=False, encoding="utf-8-sig")
    _plot_flow(output_dir / "figures/review_grade_decision_flow.png")
    _write_rulebook(ROOT / "docs/REVIEW_GRADE_RULEBOOK.md", contract, properties, dominance)


if __name__ == "__main__":
    main()
