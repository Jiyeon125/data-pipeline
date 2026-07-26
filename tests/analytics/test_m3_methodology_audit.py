from __future__ import annotations

import pandas as pd

from analytics.m3_methodology_audit import (
    _cluster_bootstrap_interval,
    _rank_flags,
    build_peer_method_flags,
    peer_threshold_tie_audit,
    unknown_review_impact,
)


def _peer_rows(size: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "source_project_year_id": [f"p-{index}" for index in range(size)],
            "classification_project_id": [f"p-{index}" for index in range(size)],
            "fiscal_year": [2024] * size,
            "ministry_code": ["019"] * size,
            "analysis_ministry_name": ["고용노동부"] * size,
            "account_type_classified": ["GENERAL_ACCOUNT"] * size,
            "project_size_bucket": ["Q2_MEDIUM"] * size,
            "comparison_group": ["GENERAL|DIRECT|POLICY"] * size,
            "original_budget_analysis_amount": [100.0] * size,
            "current_budget_analysis_amount": [100.0] * size,
            "settlement_analysis_amount": [100.0] * size,
            "execution_rate": [1.0] * size,
            "q4_expenditure_share": [0.25] * size,
            "december_single_month_share": [0.1] * size,
            "strong_low_execution_flag": [False] * size,
            "fixed_year_end_concentration_flag": [False] * size,
        }
    )


def test_bottom_tail_conservative_rank_withholds_boundary_ties() -> None:
    values = pd.Series([0.5, 0.5] + [1.0] * 18)
    result = _rank_flags(values, quantile=0.10, direction="BOTTOM")
    assert int(result["EXISTING_QUANTILE_INCLUSIVE"].sum()) == 2
    assert int(result["CONSERVATIVE_TIE_BLOCK"].sum()) == 2

    all_tied = _rank_flags(
        pd.Series([1.0] * 20),
        quantile=0.10,
        direction="BOTTOM",
    )
    assert int(all_tied["EXISTING_QUANTILE_INCLUSIVE"].sum()) == 20
    assert int(all_tied["CONSERVATIVE_TIE_BLOCK"].sum()) == 0
    assert int(all_tied["BOUNDARY_TIE"].sum()) == 20


def test_top_tail_conservative_rank_does_not_split_boundary_ties() -> None:
    values = pd.Series([0.1] * 18 + [0.8, 0.8])
    result = _rank_flags(values, quantile=0.90, direction="TOP")
    assert int(result["EXISTING_QUANTILE_INCLUSIVE"].sum()) == 2
    assert int(result["CONSERVATIVE_TIE_BLOCK"].sum()) == 2

    all_tied = _rank_flags(
        pd.Series([0.2] * 20),
        quantile=0.90,
        direction="TOP",
    )
    assert int(all_tied["CONSERVATIVE_TIE_BLOCK"].sum()) == 0


def test_small_peer_group_relative_flags_remain_missing() -> None:
    flags = build_peer_method_flags(_peer_rows(19))
    assert flags["peer_bottom_10_conservative_tie_block"].isna().all()
    assert flags["peer_p90_year_end_conservative_tie_block"].isna().all()


def test_tie_audit_attributes_quantile_excess_to_boundary_block() -> None:
    audit = peer_threshold_tie_audit(_peer_rows(20))
    bottom = audit[audit["criterion"].eq("EXECUTION_BOTTOM_10")].iloc[0]
    assert bottom["existing_detected_row_count"] == 20
    assert bottom["target_tail_row_count"] == 2
    assert bottom["boundary_tie_row_count"] == 20
    assert bool(bottom["tie_inflation_explains_excess"])


def test_cluster_bootstrap_uses_unique_project_clusters() -> None:
    signal = pd.DataFrame(
        {
            "classification_project_id": [project for project in range(10) for _ in range(2)],
            "feedback_budget_change_rate": [-0.1] * 20,
        }
    )
    control = pd.DataFrame(
        {
            "classification_project_id": [project for project in range(20, 30) for _ in range(2)],
            "feedback_budget_change_rate": [0.0] * 20,
        }
    )
    low, high = _cluster_bootstrap_interval(
        signal,
        control,
        seed=20260726,
        iterations=100,
    )
    assert low == -0.1
    assert high == -0.1


def test_unknown_review_impact_uses_current_80pct_coverage_flag() -> None:
    unknown = pd.DataFrame(
        {
            "classification_project_id": ["p1", "p2", "p3"],
            "original_budget_amount": [60.0, 25.0, 15.0],
            "cumulative_unknown_budget_share": [0.60, 0.85, 1.00],
            "priority_80pct_coverage": [True, True, False],
            "observed_years": ["2024", "2024", "2024"],
            "yearly_original_budgets": [
                '{"2024": 60}',
                '{"2024": 25}',
                '{"2024": 15}',
            ],
            "review_status": ["UNREVIEWED"] * 3,
            "manual_confirmed_value": [None] * 3,
            "keyword_candidate": ["NO_CANDIDATE"] * 3,
            "multiple_candidate_flag": [False] * 3,
        }
    )
    broad = pd.DataFrame(
        {
            "classification_project_id": ["p1", "p2", "p3"],
            "fiscal_instrument": ["UNKNOWN"] * 3,
            "original_budget_analysis_amount": [60.0, 25.0, 15.0],
        }
    )
    features = pd.DataFrame(
        {
            "classification_project_id": ["p1", "p2", "p3"],
            "fiscal_instrument_ranking_eligible": [False] * 3,
        }
    )

    result = unknown_review_impact(broad, features, unknown)
    coverage = result[result["scenario"].eq("ASSUME_80PCT_COVERAGE_ALL_CONFIRMED")].iloc[0]

    assert coverage["review_unique_project_count"] == 2
    assert coverage["coverage80_project_count"] == 2
    assert coverage["selected_unknown_budget_coverage"] == 0.85
