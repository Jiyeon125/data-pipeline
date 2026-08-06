from validation.analyze_operational_analysis import (
    build_peer_outputs,
    build_robustness_profile,
    load_inputs,
    reported_dependency_audit,
)


def test_operational_analysis_contracts() -> None:
    queue, _, _ = load_inputs()
    profile, priority_2024 = build_robustness_profile(queue)
    dependency = reported_dependency_audit(queue)

    assert len(profile) == 236
    assert profile["program_year_id"].is_unique
    assert len(priority_2024) == 6
    assert priority_2024["threshold_stable_ab"].sum() == 5
    assert priority_2024["exact_grade_stable"].sum() == 2
    assert dependency["classification"] == "RULE_STRUCTURAL_DEPENDENCY"
    assert dependency["a_without_current_or_repeated_miss"] == 0
    assert dependency["b_without_current_or_repeated_miss"] == 0


def test_peer_reference_is_strictly_eligible() -> None:
    queue, _, _ = load_inputs()
    audit, references = build_peer_outputs(queue)

    assert len(audit) == 472
    assert len(references) == 10
    assert references["valid_peer_n"].ge(10).all()
    assert references["distinct_value_n"].ge(5).all()
    assert references["tie_aware_percentile"].between(0, 1).all()
