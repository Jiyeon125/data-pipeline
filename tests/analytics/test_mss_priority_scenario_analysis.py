from pathlib import Path

import pandas as pd

from analytics.mss_priority_scenario_analysis import (
    SIGNAL_FLAGS,
    aggregate_program_account_signals,
    build_candidate_population,
    build_rank_stability,
    build_spearman_table,
    build_stable_top5_project_drilldown,
    build_top_k_overlap,
    load_scenario_config,
    score_scenarios,
)


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
            "program_code": program,
            "fiscal_year": 2024,
            "account_type": "일반회계",
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

    assert len(stability) == 2
    assert scores.groupby("candidate_id")["scenario"].nunique().eq(len(scenarios)).all()
    assert scores["scenario_score"].between(0, 1).all()
    assert len(spearman) == len(scenarios) ** 2
    assert overlap["comparison_type"].eq("ALL_SCENARIOS").sum() == 1


def test_stable_drilldown_uses_ministry_program_year_account_key() -> None:
    candidate = pd.DataFrame(
        [
            {
                "candidate_id": "102:2024:2100:GENERAL_ACCOUNT",
                "ministry_code": "102",
                "program_code": "2100",
                "fiscal_year": 2024,
                "account_type": "GENERAL_ACCOUNT",
                "performance_program_name": "중소기업기술개발지원",
                "priority_reason": "PERFORMANCE_BELOW_TARGET",
                "account_original_budget": 100,
                "account_current_budget": 110,
                "account_settlement_expenditure": 90,
            }
        ]
    )
    stability = pd.DataFrame(
        [
            {
                "candidate_id": "102:2024:2100:GENERAL_ACCOUNT",
                "all_scenario_top_5": True,
            }
        ]
    )

    def feature(ministry: str, project: str, budget: int) -> dict[str, object]:
        return {
            "ministry_code": ministry,
            "program_code": "2100",
            "fiscal_year": 2024,
            "account_type": "GENERAL_ACCOUNT",
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
    assert not drilldown["project_performance_attributed"].any()
    assert summary["other_ministry_row_count"] == 0
