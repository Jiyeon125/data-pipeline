from __future__ import annotations

import hashlib

import pytest

from validation.analyze_grade_robustness import (
    ABLATIONS,
    EXPECTED_SHA256,
    QUEUE_PATH,
    SENSITIVITY_SCENARIOS,
    ablation_analysis,
    load_baseline,
    reproduce_baseline,
    sensitivity_analysis,
    threshold_inventory,
)


def test_shadow_baseline_reproduces_all_236_production_grades() -> None:
    baseline = load_baseline()
    shadow, reproduction = reproduce_baseline(baseline)

    assert len(reproduction) == 236
    assert reproduction["program_year_id"].is_unique
    assert reproduction["match"].all()
    assert shadow["review_grade"].value_counts().to_dict() == {
        "C": 90,
        "D": 89,
        "H": 27,
        "A": 16,
        "B": 14,
    }
    assert shadow.loc[shadow["fiscal_year"].eq(2024), "review_grade"].value_counts().to_dict() == {
        "C": 35,
        "D": 28,
        "H": 8,
        "A": 4,
        "B": 2,
    }


def test_threshold_inventory_limits_analysis_to_four_grade_thresholds() -> None:
    inventory = threshold_inventory(load_baseline())
    analyzed = inventory.loc[inventory["excluded_reason"].eq(""), "threshold_name"]

    assert set(analyzed) == {
        "execution_strong",
        "execution_moderate",
        "budget_increase_cutoff",
        "budget_decrease_cutoff",
    }
    assert (
        inventory.loc[inventory["threshold_name"].eq("execution_strong"), "current_value"].item()
        == 0.8
    )
    assert (
        inventory.loc[inventory["threshold_name"].eq("execution_moderate"), "current_value"].item()
        == 0.9
    )


def test_oat_sensitivity_keeps_h_fixed_and_has_no_a_d_extreme_move() -> None:
    sensitivity, stability, transitions, boundaries, _ = sensitivity_analysis(load_baseline())
    variants = sensitivity.loc[sensitivity["scenario_id"].ne("baseline")]

    assert len(sensitivity) == len(SENSITIVITY_SCENARIOS)
    assert len(stability) == 236
    assert len(transitions) == len(SENSITIVITY_SCENARIOS) * 25
    assert not boundaries[["scenario_id", "program_year_id"]].duplicated().any()
    assert variants["h_transition_count"].eq(0).all()
    assert variants["a_to_d_or_d_to_a_count"].eq(0).all()
    assert variants["grade_retention_rate"].min() == pytest.approx(0.9377990431)
    assert variants["grade_retention_rate"].max() == 1.0
    assert variants["ab_jaccard"].min() == pytest.approx(0.8823529412)
    assert variants["ab_jaccard"].max() == 1.0


def test_signal_ablation_counts_and_h_contract_are_reproducible() -> None:
    baseline = load_baseline()
    summary, cases, _ = ablation_analysis(baseline)
    changed = summary.set_index("signal_family_removed")["grade_changed_count"].to_dict()

    assert len(summary) == len(ABLATIONS)
    assert len(cases) == len(baseline) * len(ABLATIONS)
    assert changed == {
        "execution": 20,
        "reported_performance": 56,
        "budget_performance_mismatch": 50,
        "repetition": 24,
    }
    h_ids = set(baseline.loc[baseline["review_grade"].eq("H"), "program_year_id"])
    assert cases.loc[cases["program_year_id"].isin(h_ids), "shadow_review_grade"].eq("H").all()
    assert cases.loc[cases["single_family_dependent_ab"], "program_year_id"].nunique() == 6


def test_production_csv_hash_is_unchanged() -> None:
    assert hashlib.sha256(QUEUE_PATH.read_bytes()).hexdigest() == EXPECTED_SHA256
