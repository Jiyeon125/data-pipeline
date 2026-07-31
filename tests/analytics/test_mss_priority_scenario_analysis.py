from pathlib import Path

import pandas as pd

from analytics.mss_priority_scenario_analysis import (
    SIGNAL_FLAGS,
    PriorityScenarioPaths,
    aggregate_program_account_signals,
    build_candidate_population,
    build_full_population_review_work_queue,
    build_project_review_work_queue,
    build_rank_stability,
    build_review_workbench_queue,
    build_spearman_table,
    build_stable_top5_project_drilldown,
    build_top_k_overlap,
    load_scenario_config,
    score_scenarios,
)


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
        "STRONG_SINGLE": 1,
        "DATA_FIRST": 1,
        "CONTEXT_REVIEW": 1,
        "MONITOR": 1,
    }
    assert work_queue["safety_conclusion"].eq("NOT_ASSESSED").all()
    assert work_queue.sort_values("work_queue_order")["review_intensity"].tolist() == [
        "DATA_FIRST",
        "REPEATED_OR_MULTIPLE",
        "STRONG_SINGLE",
        "CONTEXT_REVIEW",
        "MONITOR",
    ]


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
    workbench = build_review_workbench_queue(work_queue, queue)
    assert len(workbench) == 2
    assert workbench["review_item_type"].eq("DETAILED_PROJECT_REVIEW").all()
    assert workbench["work_item_id"].is_unique
