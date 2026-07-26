from __future__ import annotations

import pandas as pd

from master_engineering.quality.ranking_population_v2 import (
    add_ranking_v2_flags,
    build_strict_exclusion_breakdown,
)


def _core_row(source_id: str, **updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "source_project_year_id": source_id,
        "classification_project_id": f"class-{source_id}",
        "fiscal_year": 2024,
        "ministry_code": "019",
        "analysis_ministry_name": "고용노동부",
        "program_code": "P1",
        "subactivity_code": "S1",
        "analysis_included_classified": True,
        "original_budget_analysis_amount": 100,
        "current_budget_analysis_amount": 120,
        "settlement_analysis_amount": 90,
        "execution_rate": 0.75,
        "execution_denominator_status": "APPLIED",
        "execution_rate_over_100_flag": False,
        "settlement_duplicate_key_flag": False,
        "settlement_matching_status": "MATCHED",
        "amount_parse_failure_row_count": 0,
        "quality_issue_reasons": "",
        "trend_analysis_eligible": True,
        "execution_analysis_eligible": True,
        "reconciliation_analysis_eligible": True,
        "fiscal_instrument": "DIRECT",
        "project_category": "PROGRAM_EXPENDITURE",
        "classification_status": "RULE_CANDIDATE",
        "comparison_group": "GENERAL_ACCOUNT|DIRECT|PROGRAM_EXPENDITURE",
        "comparison_group_size": 10,
        "ranking_small_group_limited_flag": False,
        "project_size_bucket": "Q3_LARGE",
        "account_type_classified": "GENERAL_ACCOUNT",
    }
    row.update(updates)
    return row


def _v2(core: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "project_id": core["source_project_year_id"],
            "project_status": "CONTINUING",
            "structural_change_type": pd.NA,
            "budget_change_analysis_eligible": True,
            "blocking_quality_flag": False,
            "quality_issue_reasons": "",
            "source_trace": "synthetic",
        }
    )


def test_unknown_and_execution_outlier_only_limit_their_components() -> None:
    core = pd.DataFrame(
        [
            _core_row("unknown", fiscal_instrument="UNKNOWN"),
            _core_row(
                "over-one",
                execution_rate=1.2,
                execution_rate_over_100_flag=True,
            ),
        ]
    )
    result = add_ranking_v2_flags(core, _v2(core)).set_index(
        "source_project_year_id"
    )
    assert bool(result.loc["unknown", "overall_ranking_eligible"])
    assert not bool(result.loc["unknown", "fiscal_instrument_ranking_eligible"])
    assert bool(result.loc["unknown", "budget_ranking_eligible"])
    assert bool(result.loc["over-one", "overall_ranking_eligible"])
    assert not bool(result.loc["over-one", "execution_ranking_eligible"])
    assert bool(result.loc["over-one", "budget_ranking_eligible"])


def test_small_group_and_observation_boundary_are_retained() -> None:
    core = pd.DataFrame(
        [
            _core_row(
                "small",
                comparison_group_size=3,
                ranking_small_group_limited_flag=True,
            ),
            _core_row("boundary"),
        ]
    )
    v2 = _v2(core)
    v2.loc[v2["project_id"].eq("boundary"), "project_status"] = "OBSERVATION_START"
    v2.loc[
        v2["project_id"].eq("boundary"), "budget_change_analysis_eligible"
    ] = False
    result = add_ranking_v2_flags(core, v2).set_index("source_project_year_id")
    assert bool(result.loc["small", "overall_ranking_eligible"])
    assert result.loc["small", "rank_confidence"] == "LOW"
    assert bool(result.loc["small", "rank_display_limited"])
    assert bool(result.loc["boundary", "overall_ranking_eligible"])
    assert not bool(result.loc["boundary", "trend_ranking_eligible"])
    assert bool(result.loc["boundary", "budget_ranking_eligible"])


def test_settlement_limitation_does_not_remove_budget_ranking() -> None:
    core = pd.DataFrame(
        [
            _core_row(
                "settlement-limited",
                settlement_matching_status="MULTIPLE_MATCHES",
            )
        ]
    )
    result = add_ranking_v2_flags(core, _v2(core)).iloc[0]
    assert not bool(result["execution_ranking_eligible"])
    assert bool(result["budget_ranking_eligible"])
    assert bool(result["overall_ranking_eligible"])


def test_hard_scope_exclusion_is_partitioned_with_reason() -> None:
    core = pd.DataFrame(
        [_core_row("scope", analysis_included_classified=False)]
    )
    result = add_ranking_v2_flags(core, _v2(core)).iloc[0]
    assert not bool(result["overall_ranking_eligible"])
    assert result["ranking_v2_hard_exclusion_reason"] == "SCOPE_EXCLUDED"


def test_strict_primary_breakdown_reconciles_gap() -> None:
    core = pd.DataFrame(
        [
            _core_row("kept"),
            _core_row("unknown", fiscal_instrument="UNKNOWN"),
            _core_row("bad-execution", execution_analysis_eligible=False),
        ]
    )
    breakdown, _ = build_strict_exclusion_breakdown(core, {"kept"})
    primary = breakdown.loc[
        breakdown["decomposition_type"].eq("PRIMARY_MUTUALLY_EXCLUSIVE")
    ]
    assert int(primary["excluded_row_count"].sum()) == 2
    control = breakdown.loc[
        breakdown["exclusion_rule"].eq("TOTAL_CORE_MINUS_STRICT")
    ].iloc[0]
    assert control["excluded_row_count"] == 2
