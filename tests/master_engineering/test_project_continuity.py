from __future__ import annotations

import pandas as pd

from master_engineering.build_masters.project_continuity import (
    SOURCE_AMOUNT_COLUMNS,
    build_financial_v2,
    build_program_year_financial,
    build_project_relations,
    normalize_project_name,
)


def _project(
    project_id: str,
    year: int,
    subactivity_code: str,
    subactivity_name: str,
    *,
    ministry_code: str = "019",
    program_code: str = "P1",
    activity_code: str = "A1",
) -> dict[str, object]:
    return {
        "project_id": project_id,
        "fiscal_year": year,
        "ministry_code": ministry_code,
        "ministry_name": "테스트부",
        "account_code": "001",
        "program_code": program_code,
        "program_name": "청년지원프로그램",
        "activity_code": activity_code,
        "activity_name": "청년지원단위사업",
        "subactivity_code": subactivity_code,
        "subactivity_name": subactivity_name,
    }


def test_name_normalization_and_same_code_continuity() -> None:
    assert normalize_project_name(" 청년-지원 (R&D) ") == "청년지원rd"
    source = pd.DataFrame(
        [
            _project("p22", 2022, "S1", "청년 지원"),
            _project("p23", 2023, "S1", "청년 지원"),
        ]
    )
    relations = build_project_relations(source)
    continued = relations.loc[relations["relation_type"].eq("CONTINUED")].iloc[0]
    assert continued["previous_project_id"] == "p22"
    assert continued["next_project_id"] == "p23"
    assert bool(continued["continuity_flag"])
    boundaries = relations.loc[relations["relation_type"].isin({"LEFT_CENSORED", "RIGHT_CENSORED"})]
    assert set(boundaries["review_priority"]) == {"INFORMATIONAL"}
    assert not boundaries["manual_review_required"].any()
    assert (
        relations.loc[relations["next_fiscal_year"].eq(2022), "relation_type"].eq("NEW").sum() == 0
    )


def test_renamed_and_code_changed_candidates() -> None:
    renamed = build_project_relations(
        pd.DataFrame(
            [
                _project("r22", 2022, "S1", "기존 청년사업"),
                _project("r23", 2023, "S1", "개편 청년사업"),
            ]
        )
    )
    assert "RENAMED" in set(renamed["relation_type"])

    changed = build_project_relations(
        pd.DataFrame(
            [
                _project("c22", 2022, "S1", "동일 사업"),
                _project("c23", 2023, "S2", "동일 사업"),
            ]
        )
    )
    candidate = changed.loc[changed["relation_type"].eq("CODE_CHANGED")].iloc[0]
    assert candidate["review_status"] == "RULE_CANDIDATE"
    assert not bool(candidate["continuity_flag"])


def test_new_terminated_and_split_candidates_are_not_confirmed() -> None:
    source = pd.DataFrame(
        [
            _project("old", 2022, "S1", "청년지원사업"),
            _project("next-a", 2023, "S2", "청년지원사업 확대"),
            _project("next-b", 2023, "S3", "청년지원사업 지역"),
            _project("new", 2023, "S4", "완전 신규 시설"),
        ]
    )
    relations = build_project_relations(source)
    split = relations.loc[relations["relation_type"].eq("SPLIT")]
    assert len(split) == 2
    assert split["manual_review_required"].all()
    assert not split["continuity_flag"].any()
    assert "NEW" in set(relations["relation_type"])

    terminated = build_project_relations(
        pd.DataFrame(
            [
                _project("ended", 2022, "E1", "종료 사업"),
                _project("other", 2023, "O1", "별개 신규 사업"),
            ]
        )
    )
    assert "TERMINATED" in set(terminated["relation_type"])


def _program_row(
    project_id: str,
    *,
    broad: bool = True,
    core: bool = True,
    budget: int = 100,
) -> dict[str, object]:
    return {
        "project_id": project_id,
        "fiscal_year": 2024,
        "ministry_code": "075",
        "ministry_name": "보건복지부",
        "field_name": "사회복지",
        "sector_name": "기초생활보장",
        "program_code": "P1",
        "program_name": "복지 프로그램",
        "in_broad_population": broad,
        "in_core_financial_population": core,
        "account_type_classified": "GENERAL_ACCOUNT",
        "execution_denominator_status": "APPLIED",
        "execution_numerator_amount": 80 if core else pd.NA,
        "execution_denominator_amount": 100 if core else pd.NA,
        "analysis_original_budget": budget if core else pd.NA,
        "analysis_current_budget": budget if core else pd.NA,
        "analysis_settlement_expenditure": 80 if core else pd.NA,
        "settlement_carryover_amount": 5 if core else pd.NA,
        "settlement_unused_amount": 15 if core else pd.NA,
        "project_status": "CONTINUING",
        "project_status_confirmed": True,
        "structural_change_flag": False,
        "execution_analysis_eligible": core,
        "large_project_flag": budget >= 200,
        "ranking_representativeness_limited": False,
    }


def test_program_amount_aggregation_and_partial_rate_guard() -> None:
    complete, _ = build_program_year_financial(
        pd.DataFrame([_program_row("a", budget=100), _program_row("b", budget=200)])
    )
    assert complete.loc[0, "original_budget"] == 300
    assert complete.loc[0, "execution_rate"] == 0.8

    partial, _ = build_program_year_financial(
        pd.DataFrame([_program_row("a"), _program_row("b", core=False)])
    )
    assert partial.loc[0, "financial_linkage_status"] == "PARTIAL"
    assert pd.isna(partial.loc[0, "execution_rate"])


def test_program_aggregation_does_not_mix_reused_codes_with_different_names() -> None:
    first = _program_row("a")
    second = _program_row("b")
    second["program_name"] = "다른 프로그램"

    programs, _ = build_program_year_financial(pd.DataFrame([first, second]))

    assert len(programs) == 2
    assert set(programs["program_name"]) == {"복지 프로그램", "다른 프로그램"}
    assert programs["original_budget"].eq(100).all()


def test_representativeness_group_is_retained_in_general_population() -> None:
    row = _program_row("fund")
    row["ministry_code"] = "019"
    row["account_type_classified"] = "FUND"
    row["ranking_representativeness_limited"] = True
    program, _ = build_program_year_financial(pd.DataFrame([row]))
    assert bool(program.loc[0, "ranking_representativeness_limited"])
    assert program.loc[0, "financial_linkage_status"] == "COMPLETE"


def test_structural_change_and_zero_base_exclude_changes_without_mutation() -> None:
    rows = [
        _project("z22", 2022, "S1", "계속 사업"),
        _project("z23", 2023, "S1", "계속 사업"),
        _project("n23", 2023, "N1", "신규 시설"),
    ]
    financial = pd.DataFrame(rows)
    for column in SOURCE_AMOUNT_COLUMNS:
        financial[column] = 0 if column in {"budget_amount", "settlement_budget_amount"} else 10
    financial.loc[financial["project_id"].ne("z22"), "budget_amount"] = 20
    financial.loc[financial["project_id"].ne("z22"), "settlement_budget_amount"] = 20
    financial["execution_rate"] = 0.8
    financial["execution_denominator_status"] = "APPLIED"
    financial["quality_issue_reasons"] = ""
    original_amounts = financial[list(SOURCE_AMOUNT_COLUMNS)].copy(deep=True)
    relations = build_project_relations(financial)
    classification = pd.DataFrame(
        [
            {
                "project_id": f"class-{row['project_id']}",
                "account_type": "FUND",
                "fiscal_instrument": "DIRECT",
                "project_category": "OTHER",
                "comparison_group": "FUND|DIRECT|OTHER",
                "classification_status": "RULE_CONFIRMED",
                "manual_review_required": False,
                "source_project_year_ids": f'["{row["project_id"]}"]',
            }
            for row in rows
        ]
    )
    flags = pd.DataFrame(
        {
            "source_project_year_id": financial["project_id"],
            "budget_analysis_eligible": True,
            "execution_analysis_eligible": True,
            "settlement_analysis_eligible": True,
            "monthly_pattern_analysis_eligible": True,
            "trend_analysis_eligible": True,
            "ranking_analysis_eligible": True,
            "source_trace": "synthetic",
        }
    )
    ids = set(financial["project_id"])
    result = build_financial_v2(
        financial_v1=financial,
        relations=relations,
        classification=classification,
        broad_ids=ids,
        core_ids=ids,
        strict_ids=ids,
        broad_flags=flags,
    )
    zero_base = result.loc[result["project_id"].eq("z23")].iloc[0]
    observation_start = result.loc[result["project_id"].eq("z22")].iloc[0]
    new_project = result.loc[result["project_id"].eq("n23")].iloc[0]
    assert "PREVIOUS_ORIGINAL_BUDGET_ZERO" in zero_base["budget_change_missing_reason"]
    assert pd.isna(zero_base["original_budget_change_rate"])
    assert zero_base["project_status"] == "OBSERVATION_END"
    assert zero_base["structural_change_type"] == "RIGHT_CENSORED"
    assert not bool(zero_base["structural_change_flag"])
    assert observation_start["project_status"] == "OBSERVATION_START"
    assert observation_start["structural_change_type"] == "LEFT_CENSORED"
    assert pd.isna(observation_start["continuity_flag"])
    assert not bool(observation_start["manual_review_required"])
    assert new_project["project_status"] == "NEW"
    assert pd.isna(new_project["original_budget_change_rate"])
    pd.testing.assert_frame_equal(
        original_amounts.reset_index(drop=True),
        result[list(SOURCE_AMOUNT_COLUMNS)].reset_index(drop=True),
        check_dtype=False,
    )
    assert result.loc[result["fiscal_year"].eq(2023), "ranking_representativeness_limited"].all()
