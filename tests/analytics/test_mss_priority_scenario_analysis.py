from io import StringIO
from pathlib import Path

import pandas as pd
import pytest

from analytics.mss_priority_scenario_analysis import (
    SIGNAL_FLAGS,
    SIGNAL_SCORE_COMPONENTS,
    PriorityScenarioPaths,
    _build_priority_reason,
    _build_retrospective_feedback_reason,
    aggregate_program_account_signals,
    apply_feedback_cutoff,
    apply_question_review_grades,
    attach_reported_target_history,
    attach_signal_size_separation,
    build_candidate_population,
    build_full_population_review_work_queue,
    build_program_year_review_queue,
    build_project_review_work_queue,
    build_rank_stability,
    build_review_workbench_queue,
    build_spearman_table,
    build_stable_top5_project_drilldown,
    build_top_k_overlap,
    load_scenario_config,
    score_scenarios,
    validate_candidate_work_queue_integrity,
)


def _question_grade_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ministry_code": "102",
        "field_name": "f",
        "sector_name": "s",
        "program_code": "p",
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


@pytest.mark.parametrize(
    ("changes", "grade", "diagnostic"),
    [
        (
            {"current_execution_severity": 1.0, "budget_increase_context_signal": True},
            "C",
            "LOW_EXECUTION_TARGET_MET",
        ),
        (
            {
                "reported_target_status": "ALL_COMPARABLE_BELOW_TARGET",
                "below_target_count": 1,
                "performance_signal": True,
                "reported_target_miss_consecutive": True,
            },
            "B",
            "STRONG_OR_REPEATED_SINGLE_SIGNAL",
        ),
        (
            {
                "current_execution_severity": 0.5,
                "comparable_rate_count": 0,
                "reported_target_status": "NO_COMPARABLE_RATE",
            },
            "C",
            "LOW_EXECUTION_PERFORMANCE_INFORMATION_MISSING",
        ),
        (
            {"repeated_target_overachievement": True, "target_unchanged": True},
            "C",
            "TARGET_ADEQUACY_REVIEW",
        ),
        (
            {"budget_increase_context_signal": True},
            "D",
            "NO_STRUCTURED_SIGNAL_DETECTED",
        ),
        (
            {"accounting_context_signal": True, "structure_context_signal": True},
            "D",
            "NO_STRUCTURED_SIGNAL_DETECTED",
        ),
        (
            {"budget_increase_context_signal": True, "budget_mismatch_signal": True},
            "C",
            "SINGLE_SIGNAL_REVIEW",
        ),
        (
            {
                "reported_target_status": "ALL_COMPARABLE_BELOW_TARGET",
                "below_target_count": 1,
                "performance_signal": True,
                "reported_target_miss_consecutive": True,
                "budget_increase_context_signal": True,
                "budget_mismatch_signal": True,
            },
            "A",
            "REPEATED_REPORTED_TARGET_MISS_WITH_BUDGET_INCREASE",
        ),
        (
            {
                "current_execution_severity": 1.0,
                "context_type": "MULTIYEAR_CAPITAL",
                "context_status": "CONFIRMED_STRUCTURED",
                "context_source": "STRUCTURED_FIELD",
                "context_evidence": "CONFIRMED_MULTIYEAR",
            },
            "C",
            "MULTIYEAR_CONTEXT_WITH_SINGLE_YEAR_LOW_EXECUTION",
        ),
        (
            {"data_validation_signal": True},
            "H",
            "DATA_OR_COMPARABILITY_HOLD",
        ),
        ({}, "D", "NO_STRUCTURED_SIGNAL_DETECTED"),
    ],
)
def test_question_review_grade_counterexamples(
    changes: dict[str, object], grade: str, diagnostic: str
) -> None:
    result = apply_question_review_grades(pd.DataFrame([_question_grade_row(**changes)]))

    assert result.loc[0, "review_grade"] == grade
    assert result.loc[0, "diagnostic_type"] == diagnostic
    assert result.loc[0, "signal_families"] == result.loc[0, "grade_trigger_signal_families"]
    if changes.get("current_execution_severity") and not changes.get("performance_signal"):
        assert result.loc[0, "review_grade"] != "A"
    if diagnostic == "NO_STRUCTURED_SIGNAL_DETECTED" and any(
        changes.get(name)
        for name in (
            "budget_increase_context_signal",
            "budget_decrease_context_signal",
            "accounting_context_signal",
            "structure_context_signal",
        )
    ):
        assert bool(result.loc[0, "context_only"])
        assert result.loc[0, "context_effect"] == "DISPLAY_ONLY_NO_GRADE_CHANGE"


def test_reported_target_history_is_consecutive_asof_and_deduplicated() -> None:
    rows = []
    for year, account in (("2022", "GENERAL"), ("2022", "FUND"), ("2024", "GENERAL")):
        rows.append(
            _question_grade_row(
                fiscal_year=year,
                account_type=account,
                below_target_count=1,
                reported_target_status="ALL_COMPARABLE_BELOW_TARGET",
                performance_signal=True,
            )
        )
    gap = attach_reported_target_history(pd.DataFrame(rows))
    assert not gap["reported_target_miss_consecutive"].any()
    assert (
        gap.loc[gap["fiscal_year"].eq("2024"), "reported_target_history_status"]
        .eq("NON_CONSECUTIVE_GAP")
        .all()
    )

    with_middle = pd.concat(
        [
            pd.DataFrame(rows),
            pd.DataFrame(
                [
                    _question_grade_row(
                        fiscal_year="2023",
                        account_type="GENERAL",
                        below_target_count=1,
                        reported_target_status="ALL_COMPARABLE_BELOW_TARGET",
                        performance_signal=True,
                    )
                ]
            ),
        ],
        ignore_index=True,
    )
    history = attach_reported_target_history(with_middle.sample(frac=1, random_state=5))
    assert (
        history.loc[history["fiscal_year"].eq("2022"), "reported_target_miss_consecutive"]
        .eq(False)
        .all()
    )
    assert history.loc[
        history["fiscal_year"].isin(["2023", "2024"]), "reported_target_miss_consecutive"
    ].all()


def test_t1_t2_values_do_not_change_question_review_grade() -> None:
    row = _question_grade_row(current_execution_severity=1.0)
    before = apply_question_review_grades(
        pd.DataFrame([{**row, "low_performance_budget_increase_t1": False}])
    )
    after = apply_question_review_grades(
        pd.DataFrame([{**row, "low_performance_budget_increase_t1": True}])
    )

    assert before.loc[0, "review_grade"] == after.loc[0, "review_grade"]


def _program_account_row(
    program_code: str | None,
    year: int,
    *,
    account_type: str = "GENERAL_ACCOUNT",
    original: float = 100.0,
    current: float = 100.0,
    expenditure: float = 100.0,
    below: int | None = 0,
    comparable: int | None = 1,
    field_name: str = "분야",
    sector_name: str = "부문",
    program_name: str | None = None,
    data_validation: bool = False,
    **extra: object,
) -> dict[str, object]:
    status = (
        "NO_COMPARABLE_RATE"
        if not comparable
        else ("ALL_COMPARABLE_BELOW_TARGET" if below else "ALL_COMPARABLE_AT_OR_ABOVE_TARGET")
    )
    row: dict[str, object] = {
        "candidate_id": f"102:{year}:{field_name}:{sector_name}:{program_code}:{account_type}",
        "ministry_code": "102",
        "field_name": field_name,
        "sector_name": sector_name,
        "program_code": program_code,
        "fiscal_year": year,
        "account_type": account_type,
        "performance_program_name": program_name or f"프로그램 {program_code}",
        "account_original_budget": original,
        "account_current_budget": current,
        "account_settlement_expenditure": expenditure,
        "account_execution_rate": expenditure / current if current else pd.NA,
        "below_target_count": below,
        "at_or_above_target_count": (comparable - below)
        if comparable is not None and below is not None
        else pd.NA,
        "comparable_rate_count": comparable,
        "reported_target_status": status,
        "indicator_coverage_status": "COMPLETE_REPORTED_RATE_COVERAGE",
        "data_validation_signal": data_validation,
        "analysis_status": "DATA_REVIEW" if data_validation else "JOINT_ANALYSIS",
        "evidence_status": "DATA_BLOCKED" if data_validation else "CONFIRMED",
        "review_grade": "D",
        "diagnostic_type": "NO_STRUCTURED_SIGNAL_DETECTED",
        "type_repeated_year_end_concentration_budget_share": 0.0,
        "type_accounting_adjustment_pattern_budget_share": 0.0,
        "type_program_budget_concentration_budget_share": 0.0,
        "current_execution_severity": 0.0,
        "type_repeated_strong_low_execution_budget_share": 0.0,
        "type_repeated_moderate_low_execution_budget_share": 0.0,
        "performance_signal": bool(below),
    }
    row.update(extra)
    return row


def test_program_year_queue_reaggregates_money_performance_and_grades() -> None:
    rows = [
        # 저집행 + 목표달성: 두 회계 합산 후에도 C, 성과 개수는 합산하지 않음.
        _program_account_row("P1", 2024, current=100, expenditure=60),
        _program_account_row(
            "P1", 2024, account_type="FUND", original=50, current=50, expenditure=30
        ),
        # 연속 목표미달 + 프로그램 총예산 증가: 2024 A.
        _program_account_row("P2", 2023, original=100, below=1),
        _program_account_row("P2", 2024, original=120, below=1),
        # 중간연도 누락은 반복으로 세지 않음.
        _program_account_row("P3", 2022, current=100, expenditure=70),
        _program_account_row("P3", 2024, current=100, expenditure=70),
        # 성과정보 없음 + 저집행은 C, 데이터 불확실은 H, 신호 없음은 D.
        _program_account_row("P4", 2024, current=100, expenditure=70, below=None, comparable=None),
        _program_account_row("P5", 2024, data_validation=True),
        _program_account_row("P6", 2024),
        # 반복 초과달성 + 목표 불변, 확인된 다년도 맥락.
        _program_account_row(
            "P7", 2024, repeated_target_overachievement=True, target_unchanged=True
        ),
        _program_account_row(
            "P8",
            2024,
            current=100,
            expenditure=70,
            context_type="MULTIYEAR_CAPITAL",
            context_status="CONFIRMED_STRUCTURED",
            context_source="STRUCTURED_FIELD",
            context_evidence="CONFIRMED_MULTIYEAR",
            context_effect="NO_GRADE_CHANGE",
        ),
        # 코드 namespace 충돌이 확장키로 해소되면 각각 D.
        _program_account_row("COLLIDE", 2024, field_name="분야A", program_name="프로그램A"),
        _program_account_row("COLLIDE", 2024, field_name="분야B", program_name="프로그램B"),
        # 같은 코드·이름이 복수 분야에 있으면 집계 identity가 불명확하여 H.
        _program_account_row("UNRESOLVED", 2024, field_name="분야A", program_name="같은프로그램"),
        _program_account_row("UNRESOLVED", 2024, field_name="분야B", program_name="같은프로그램"),
        # 확장키 안에서도 프로그램명이 둘이면 identity를 확정하지 않고 H.
        _program_account_row("EXTENDED_CONFLICT", 2024, program_name="프로그램A"),
        _program_account_row(
            "EXTENDED_CONFLICT", 2024, account_type="FUND", program_name="프로그램B"
        ),
        # 프로그램코드 결측은 연도 간 연속성을 확정할 수 없어 H.
        _program_account_row(None, 2024, program_name="코드결측프로그램"),
        _program_account_row("P9", 2024),
        _program_account_row("P9", 2024, account_type="FUND", below=1),
        # 고집행 + 반복 목표미달(예산 증가 없음)은 B.
        _program_account_row("P10", 2023, below=1),
        _program_account_row("P10", 2024, below=1),
    ]
    queue, summary = build_program_year_review_queue(
        pd.DataFrame(rows),
        {"thresholds": {"execution_strong": 0.8, "execution_moderate": 0.9}},
    )

    def pick(code: str, year: int) -> pd.Series:
        return queue.loc[queue["program_code"].eq(code) & queue["fiscal_year"].eq(year)].iloc[0]

    assert queue["program_year_id"].is_unique
    assert summary["amount_reconciliation_absolute_differences"] == {
        "program_original_budget": 0.0,
        "program_current_budget": 0.0,
        "program_expenditure": 0.0,
    }
    assert summary["program_year_amount_diff_counts"] == {
        "program_original_budget": 0,
        "program_current_budget": 0,
        "program_expenditure": 0,
    }
    assert pick("P1", 2024)["program_original_budget"] == 150
    assert pick("P1", 2024)["program_execution_rate"] == pytest.approx(0.6)
    assert pick("P1", 2024)["comparable_rate_count"] == 1
    assert pick("P1", 2024)["review_grade"] == "C"
    assert pick("P1", 2024)["diagnostic_type"] == "LOW_EXECUTION_TARGET_MET"
    assert pick("P2", 2024)["review_grade"] == "A"
    assert not bool(pick("P3", 2024)["repeated_low_execution_signal"])
    assert pick("P4", 2024)["review_grade"] == "C"
    assert pick("P5", 2024)["review_grade"] == "H"
    assert pick("P6", 2024)["review_grade"] == "D"
    assert pick("P7", 2024)["diagnostic_type"] == "TARGET_ADEQUACY_REVIEW"
    assert pick("P8", 2024)["diagnostic_type"] == (
        "MULTIYEAR_CONTEXT_WITH_SINGLE_YEAR_LOW_EXECUTION"
    )
    collision = queue.loc[queue["program_code"].eq("COLLIDE")]
    assert len(collision) == 2
    assert collision["review_grade"].eq("D").all()
    assert collision["base_key_reused"].all()
    assert collision["identity_resolved_by_extended_key"].all()
    assert not collision["identity_unresolved"].any()
    unresolved = queue.loc[queue["program_code"].eq("UNRESOLVED")]
    assert len(unresolved) == 2
    assert unresolved["review_grade"].eq("H").all()
    assert unresolved["identity_unresolved"].all()
    assert unresolved["identity_resolution_reason"].eq("SAME_CODE_NAME_MULTIPLE_FIELD_SECTOR").all()
    extended_conflict = queue.loc[queue["program_code"].eq("EXTENDED_CONFLICT")]
    assert len(extended_conflict) == 2
    assert extended_conflict["review_grade"].eq("H").all()
    assert (
        extended_conflict["identity_resolution_reason"]
        .eq("EXTENDED_KEY_PROGRAM_NAME_CONFLICT")
        .all()
    )
    missing_code = queue.loc[queue["program_code"].isna()].iloc[0]
    assert missing_code["review_grade"] == "H"
    assert bool(missing_code["identity_unresolved"])
    assert missing_code["continuity_status"] == "UNKNOWN_CONTINUITY"
    assert pick("P9", 2024)["review_grade"] == "H"
    assert bool(pick("P9", 2024)["program_performance_status_conflict"])
    assert pick("P10", 2024)["review_grade"] == "B"


def test_program_year_asof_is_unchanged_when_future_year_is_added() -> None:
    base = pd.DataFrame(
        [
            _program_account_row("P", 2022, below=1),
            _program_account_row("P", 2023, below=1),
            _program_account_row("P", 2024, below=1),
        ]
    )
    config = {"thresholds": {"execution_strong": 0.8, "execution_moderate": 0.9}}
    before, _ = build_program_year_review_queue(base, config)
    after, _ = build_program_year_review_queue(
        pd.concat([base, pd.DataFrame([_program_account_row("P", 2025)])], ignore_index=True),
        config,
    )

    columns = [
        "program_year_id",
        "review_grade",
        "diagnostic_type",
        "reported_target_miss_consecutive",
        "program_budget_change_rate",
    ]
    pd.testing.assert_frame_equal(
        before[columns].sort_values("program_year_id").reset_index(drop=True),
        after.loc[after["fiscal_year"].le(2024), columns]
        .sort_values("program_year_id")
        .reset_index(drop=True),
        check_dtype=False,
    )


def test_feedback_cutoff_blocks_outcomes_after_analysis_end_year() -> None:
    frame = pd.DataFrame(
        {
            "fiscal_year": [2023, 2024],
            "low_performance_budget_increase_t1": [True, True],
            "low_performance_budget_increase_t2": [True, True],
            "program_total_feedback_complete_t1": [True, True],
            "program_total_feedback_complete_t2": [True, True],
            "program_total_outcome_budget_t1": [110, 120],
            "program_total_outcome_budget_t2": [120, 130],
        }
    )

    result = apply_feedback_cutoff(frame, 2024)

    assert result["low_performance_budget_increase_t1"].tolist() == [True, False]
    assert result["low_performance_budget_increase_t2"].tolist() == [False, False]
    assert result["program_total_outcome_budget_t1"].notna().tolist() == [True, False]
    assert result["program_total_outcome_budget_t2"].isna().all()


def test_multi_ministry_paths_and_scope_are_configuration_driven() -> None:
    paths = PriorityScenarioPaths.multi_ministry_from_root(Path("."))
    config = load_scenario_config(paths.config)

    assert paths.output_dir.name == "multi_ministry_priority_scenarios"
    assert config["scope"]["ministry_codes"] == ["019", "075", "102", "162"]


def _manual_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    definitions = [
        ("A", 100.0, 1, 1, 0.95, set()),
        ("B", 80.0, 1, 0, 0.75, {"type_repeated_strong_low_execution"}),
        ("C", 60.0, 1, 0, 0.95, {"type_program_budget_concentration"}),
        ("D", 40.0, 1, 0, 0.95, set()),
        ("E", 20.0, 0, 0, float("nan"), set()),
    ]
    analysis_rows = []
    feature_rows = []
    for program, budget, comparable, below, execution, active_flags in definitions:
        analysis_rows.append(
            {
                "ministry_code": "102",
                "field_name": "산업·중소기업및에너지",
                "sector_name": "산업혁신지원",
                "program_code": program,
                "fiscal_year": 2024,
                "account_type": "일반회계",
                "performance_program_name": f"프로그램 {program}",
                "analysis_status": (
                    "JOINT_ANALYSIS" if program != "E" else "FINANCIAL_LINKAGE_LIMITED"
                ),
                "comparable_rate_count": comparable,
                "below_target_count": below,
                "formula_review_count": 0,
                "reported_performance_signal": below > 0,
                "account_original_budget": budget,
                "account_current_budget": budget,
                "account_settlement_expenditure": (
                    budget * execution if pd.notna(execution) else pd.NA
                ),
                "account_execution_rate": execution,
                "account_financial_linkage_status": "COMPLETE",
                "account_financial_quality_level": "HIGH",
            }
        )
        feature = {
            "ministry_code": "102",
            "field_name": "산업·중소기업및에너지",
            "sector_name": "산업혁신지원",
            "program_code": program,
            "fiscal_year": 2024,
            "account_type": "일반회계",
            "account_type_classified": "일반회계",
            "project_id": f"project-{program}",
            "original_budget_analysis_amount": budget,
            "rank_confidence": "HIGH",
            "independent_signal_count": len(active_flags),
            "active_signal_types": ";".join(sorted(active_flags)) or "NONE",
        }
        feature.update({flag: flag in active_flags for flag in SIGNAL_FLAGS})
        feature_rows.append(feature)
    return pd.DataFrame(analysis_rows), pd.DataFrame(feature_rows)


def test_manual_candidate_rules_and_budget_weighting() -> None:
    analysis, features = _manual_inputs()
    config = load_scenario_config(Path("configs/mss_priority_scenarios.yaml"))
    signals = aggregate_program_account_signals(
        features,
        ministry_code="102",
        start_year=2024,
        end_year=2024,
    )
    candidates = build_candidate_population(analysis, signals, config).set_index("program_code")

    assert candidates.loc["A", "performance_gap"] == 1
    assert candidates.loc["B", "execution_management"] == 1
    assert candidates.loc["C", "context_only_candidate"]
    assert not candidates.loc["D", "review_candidate"]  # 규모만으로 후보를 만들지 않음
    assert candidates.loc["E", "priority_tier"] == "DATA_REVIEW"
    assert signals["project_signal_budget"].sum() == analysis["account_original_budget"].sum()
    assert "signal_score" in candidates.columns
    assert not bool(candidates["fiscal_impact_in_signal_score"].iloc[0])
    assert (
        candidates.loc["A", "signal_score"]
        == candidates.loc["A", list(SIGNAL_SCORE_COMPONENTS)].astype(float).mean()
    )
    assert candidates.loc["E", "signal_score_status"] == "INCOMPLETE_COMPONENTS"
    assert pd.isna(candidates.loc["E", "signal_score"])


def test_retrospective_feedback_is_not_a_current_priority_reason() -> None:
    row = pd.Series(
        {
            "analysis_status": "JOINT_ANALYSIS",
            "data_validation_signal": False,
            "performance_signal": False,
            "execution_signal": False,
            "budget_mismatch_signal": False,
            "accounting_context_signal": False,
            "structure_context_signal": False,
            "low_performance_budget_increase_t1": True,
            "low_performance_budget_increase_t2": False,
            "good_performance_budget_decrease_t1": False,
            "good_performance_budget_decrease_t2": False,
            "program_total_account_type_mismatch_t1": True,
            "program_total_account_type_mismatch_t2": False,
        }
    )

    assert _build_priority_reason(row) == "NO_REVIEW_SIGNAL"
    assert _build_retrospective_feedback_reason(row) == (
        "LOW_PERFORMANCE_BUDGET_INCREASE_T1;PROGRAM_ACCOUNT_TYPE_MISMATCH_T1"
    )


def test_work_queue_orders_by_signal_score_before_budget() -> None:
    """같은 레인·신호 수면 예산이 커도 signal_score가 높은 쪽이 앞선다."""
    rows = []
    for program, budget, gap in (
        ("BIG", 1_000_000.0, 0.2),
        ("STRONG", 10_000.0, 0.9),
    ):
        rows.append(
            {
                "candidate_id": f"102:2024:f:s:{program}:GENERAL_ACCOUNT",
                "ministry_code": "102",
                "field_name": "f",
                "sector_name": "s",
                "program_code": program,
                "fiscal_year": 2024,
                "account_type": "GENERAL_ACCOUNT",
                "performance_program_name": program,
                "analysis_status": "JOINT_ANALYSIS",
                "scenario_ranking_eligible": True,
                "data_validation_signal": False,
                "context_only_candidate": False,
                "context_signal_family_count": 0,
                "account_original_budget": budget,
                "account_current_budget": budget,
                "account_settlement_expenditure": budget * 0.9,
                "priority_reason": "PERFORMANCE_BELOW_TARGET",
                "performance_gap": gap,
                "execution_management": gap,
                "budget_performance_mismatch": gap,
                "review_intensity": "SINGLE_REVIEW",
                "review_item_type": "DETAILED_PROJECT_REVIEW",
                "repeated_signal_family_count": 0,
                "independent_signal_family_count": 1,
                "evidence_status": "CONFIRMED",
                "next_action": "표시된 독립 신호의 근거를 확인",
            }
        )
    candidates = attach_signal_size_separation(pd.DataFrame(rows))
    stability = pd.DataFrame(
        {
            "candidate_id": candidates["candidate_id"],
            "mean_scenario_rank": [1.0, 2.0],
            "scenario_rank_range": [0.0, 0.0],
            "mean_scenario_rank_within_ministry": [1.0, 2.0],
            "scenario_rank_range_within_ministry": [0.0, 0.0],
            "exploratory_consensus_order": [1, 2],
            "all_scenario_top_5": [False, False],
            "all_scenario_top_5_within_ministry": [False, False],
        }
    )
    work_queue, summary = build_full_population_review_work_queue(candidates, stability)
    ordered = work_queue.sort_values("work_queue_order")["program_code"].tolist()
    assert ordered == ["STRONG", "BIG"]
    assert summary["signal_size_separation"]["size_role"] == "tiebreak_only"
    assert summary["signal_size_separation"]["fiscal_impact_in_signal_score"] is False


def test_program_signals_use_classified_account_type() -> None:
    _, features = _manual_inputs()
    features.loc[0, "account_type"] = "SPECIAL_ACCOUNT"
    features.loc[0, "account_type_classified"] = "RESPONSIBLE_OPERATION_ACCOUNT"

    signals = aggregate_program_account_signals(
        features.iloc[[0]],
        ministry_code="102",
        start_year=2024,
        end_year=2024,
    )

    assert signals.loc[0, "account_type"] == "RESPONSIBLE_OPERATION_ACCOUNT"


def test_manual_scenario_rank_stability() -> None:
    analysis, features = _manual_inputs()
    config = load_scenario_config(Path("configs/mss_priority_scenarios.yaml"))
    signals = aggregate_program_account_signals(
        features,
        ministry_code="102",
        start_year=2024,
        end_year=2024,
    )
    candidates = build_candidate_population(analysis, signals, config)
    scores = score_scenarios(candidates, config)
    stability = build_rank_stability(candidates, scores, config)
    scenarios = list(config["scenarios"])
    spearman = build_spearman_table(scores, scenarios)
    overlap = build_top_k_overlap(scores, scenarios, [1])
    work_queue, work_summary = build_full_population_review_work_queue(
        candidates,
        stability,
    )

    assert len(stability) == 2
    assert scores.groupby("candidate_id")["scenario"].nunique().eq(len(scenarios)).all()
    assert scores["scenario_score"].between(0, 1).all()
    assert scores["scenario_rank_average"].equals(scores["scenario_rank_average_within_ministry"])
    assert stability["scenario_rank_range"].equals(stability["scenario_rank_range_within_ministry"])
    assert len(spearman) == len(scenarios) ** 2
    assert overlap["comparison_type"].eq("ALL_SCENARIOS").sum() == 1
    assert work_summary["candidate_coverage_rate"] == 1
    assert work_queue["work_lane"].value_counts().to_dict() == {
        "REPEATED_OR_MULTIPLE": 1,
        "SINGLE_REVIEW": 1,
        "DATA_FIRST": 1,
        "CONTEXT_REVIEW": 1,
        "MONITOR": 1,
    }
    assert work_queue["safety_conclusion"].eq("NOT_ASSESSED").all()
    # 성과미달만인 A는 STRONG_SINGLE이 아니라 SINGLE_REVIEW (3차 멘토링)
    assert work_queue.sort_values("work_queue_order")["review_intensity"].tolist() == [
        "DATA_FIRST",
        "REPEATED_OR_MULTIPLE",
        "SINGLE_REVIEW",
        "CONTEXT_REVIEW",
        "MONITOR",
    ]
    assert work_queue.set_index("program_code").loc["A", "review_intensity"] == "SINGLE_REVIEW"

    rerun_queue, _ = build_full_population_review_work_queue(
        candidates.sample(frac=1, random_state=7),
        stability.sample(frac=1, random_state=11),
    )
    pd.testing.assert_frame_equal(work_queue, rerun_queue)

    tampered = work_queue.copy()
    left, right = tampered.index[:2]
    tampered.loc[[left, right], "account_original_budget"] = tampered.loc[
        [right, left], "account_original_budget"
    ].to_numpy()
    with pytest.raises(ValueError, match="불변 필드가 변경"):
        validate_candidate_work_queue_integrity(candidates, tampered)

    with pytest.raises(ValueError, match="anti-join"):
        validate_candidate_work_queue_integrity(candidates, work_queue.iloc[:-1])

    reloaded = pd.read_csv(StringIO(work_queue.to_csv(index=False)))
    incomplete = reloaded["signal_score_status"].eq("INCOMPLETE_COMPONENTS")
    assert incomplete.sum() == 1
    assert reloaded.loc[incomplete, "signal_score"].isna().all()


def test_stable_drilldown_uses_ministry_program_year_account_key() -> None:
    candidate = pd.DataFrame(
        [
            {
                "candidate_id": "102:2024:2100:GENERAL_ACCOUNT",
                "ministry_code": "102",
                "field_name": "산업·중소기업및에너지",
                "sector_name": "산업혁신지원",
                "program_code": "2100",
                "fiscal_year": 2024,
                "account_type": "GENERAL_ACCOUNT",
                "performance_program_name": "중소기업기술개발지원",
                "priority_reason": "PERFORMANCE_BELOW_TARGET",
                "account_original_budget": 100,
                "account_current_budget": 110,
                "account_settlement_expenditure": 90,
                "analysis_status": "JOINT_ANALYSIS",
                "scenario_ranking_eligible": True,
                "data_validation_signal": False,
                "context_only_candidate": False,
                "context_signal_family_count": 0,
                "performance_gap": 1.0,
                "execution_management": 0.0,
                "budget_performance_mismatch": 0.0,
                "review_intensity": "SINGLE_REVIEW",
                "review_intensity_order": 3,
                "review_item_type": "DETAILED_PROJECT_REVIEW",
                "next_action": "표시된 독립 신호의 근거를 확인",
                "evidence_status": "CONFIRMED",
                "independent_signal_family_count": 1,
                "repeated_signal_family_count": 0,
                "performance_signal": True,
                "execution_review_signal": False,
                "low_performance_budget_increase_t1": False,
                "low_performance_budget_increase_t2": False,
                "good_performance_budget_decrease_t1": False,
                "good_performance_budget_decrease_t2": False,
            }
        ]
    )
    candidate = attach_signal_size_separation(candidate)
    stability = pd.DataFrame(
        [
            {
                "candidate_id": "102:2024:2100:GENERAL_ACCOUNT",
                "all_scenario_top_5": True,
                "all_scenario_top_5_within_ministry": True,
                "mean_scenario_rank": 1.0,
                "scenario_rank_range": 0.0,
                "mean_scenario_rank_within_ministry": 1.0,
                "scenario_rank_range_within_ministry": 0.0,
                "exploratory_consensus_order": 1,
            }
        ]
    )

    def feature(ministry: str, project: str, budget: int) -> dict[str, object]:
        return {
            "ministry_code": ministry,
            "field_name": "산업·중소기업및에너지",
            "sector_name": "산업혁신지원",
            "program_code": "2100",
            "fiscal_year": 2024,
            "account_type": "GENERAL_ACCOUNT",
            "account_type_classified": "GENERAL_ACCOUNT",
            "project_id": project,
            "account_code": "110",
            "account_name_budget_api": "일반회계",
            "activity_code": "2101",
            "activity_name_budget_api": "단위사업",
            "subactivity_code": project,
            "subactivity_name_budget_api": f"세부사업 {project}",
            "original_budget_analysis_amount": budget,
            "current_budget_analysis_amount": budget + 5,
            "settlement_analysis_amount": budget - 5,
            "settlement_carryover_amount": 2,
            "settlement_unused_amount": 8,
            "execution_rate": (budget - 5) / (budget + 5),
            "active_signal_types": "NONE",
            "project_status": "CONTINUING",
            "structural_change_type": pd.NA,
            "financial_quality_level": "HIGH",
            "rank_confidence": "HIGH",
            "budget_ranking_eligible": True,
            "execution_ranking_eligible": True,
            "source_trace_v2": "source.csv",
            "priority_reason": "M3_SOURCE_VALUE_MUST_NOT_COLLIDE",
        }

    features = pd.DataFrame(
        [
            feature("102", "A", 60),
            feature("102", "B", 40),
            feature("075", "C", 999),
        ]
    )
    drilldown, summary = build_stable_top5_project_drilldown(
        candidate,
        stability,
        features,
    )

    assert drilldown["project_id"].tolist() == ["A", "B"]
    assert drilldown["project_original_budget"].sum() == 100
    assert drilldown["project_current_budget"].sum() == 110
    assert drilldown["project_expenditure"].sum() == 90
    assert drilldown["budget_share_within_candidate"].sum() == 1
    assert drilldown["drilldown_selection_scope"].eq("OVERALL_AND_WITHIN_MINISTRY").all()
    assert not drilldown["project_performance_attributed"].any()
    assert drilldown["program_context_grain"].eq("PROGRAM_YEAR_ACCOUNT").all()
    assert (
        drilldown["program_context_disclaimer"]
        .eq("PROGRAM_LEVEL_REFERENCE_NOT_PROJECT_PERFORMANCE")
        .all()
    )
    assert "priority_reason" not in drilldown
    assert "program_performance_signal" not in drilldown
    assert summary["other_ministry_row_count"] == 0

    work_queue, _ = build_full_population_review_work_queue(
        candidate,
        stability,
    )
    queue, queue_summary = build_project_review_work_queue(
        candidate,
        work_queue,
        features,
    )
    assert queue["project_id"].tolist() == ["A", "B"]
    assert queue["project_review_group"].eq("LARGE_BUDGET_CONTEXT").all()
    assert queue["project_review_order_within_candidate"].tolist() == [1, 2]
    assert queue["review_sequence_overall"].tolist() == [1, 2]
    assert queue_summary["reviewable_candidate_coverage_rate"] == 1
    assert queue_summary["project_performance_attribution_count"] == 0
    assert "review_grade" not in queue
    assert queue["program_level_review_grade_context"].eq("C").all()
    for column in (
        "performance_signal",
        "low_performance_budget_increase_t1",
        "low_performance_budget_increase_t2",
        "good_performance_budget_decrease_t1",
        "good_performance_budget_decrease_t2",
    ):
        assert column not in queue
    workbench = build_review_workbench_queue(work_queue, queue)
    assert len(workbench) == 2
    assert workbench["review_item_type"].eq("DETAILED_PROJECT_REVIEW").all()
    assert workbench["work_item_id"].is_unique
    project_rows = workbench["review_item_type"].eq("DETAILED_PROJECT_REVIEW")
    assert workbench.loc[project_rows, "performance_signal"].isna().all()
    assert not workbench.loc[project_rows, "project_performance_attributed"].any()
    assert workbench.loc[project_rows, "program_context_grain"].eq("PROGRAM_YEAR_ACCOUNT").all()
