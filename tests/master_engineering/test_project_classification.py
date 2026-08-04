from __future__ import annotations

from pathlib import Path

import pandas as pd

from master_engineering.build_masters.project_classification import (
    build_project_classification,
    classify_account_type,
    classify_exclusion,
    classify_fiscal_instrument,
)


def test_account_type_classification() -> None:
    assert classify_account_type("일반회계", "110")[0] == "GENERAL_ACCOUNT"
    assert classify_account_type("지역균형발전특별회계", "236")[0] == "SPECIAL_ACCOUNT"
    assert classify_account_type("고용보험기금", "541")[0] == "FUND"


def test_responsible_operation_account_uses_4xx_rule() -> None:
    account_type, basis = classify_account_type("국립과학관", "433")
    assert account_type == "RESPONSIBLE_OPERATION_ACCOUNT"
    assert basis == "ACCOUNT_CODE_4XX"


def test_single_instrument_keyword_is_candidate() -> None:
    instrument, method, evidence, review = classify_fiscal_instrument(
        "중소기업지원",
        "정책자금",
        "소상공인 융자",
    )
    assert instrument == "LOAN"
    assert method == "RULE_KEYWORD_CANDIDATE"
    assert evidence
    assert review is False


def test_overlapping_instrument_keywords_require_manual_review() -> None:
    instrument, method, evidence, review = classify_fiscal_instrument(
        "산업지원",
        "시설 운영",
        "정보화 시스템 구축",
    )
    assert instrument == "UNKNOWN"
    assert method == "RULE_KEYWORD_OVERLAP"
    assert "FACILITY" in evidence and "INFORMATIZATION" in evidence
    assert review is True


def test_structured_exclusion_rule_does_not_delete_row() -> None:
    included, category, reason, review = classify_exclusion(
        "인건비(기금인건비)",
        "일반지출",
        "프로그램",
        "단위사업",
        "세부사업",
    )
    assert included is False
    assert category == "PERSONNEL"
    assert "business_class_name" in str(reason)
    assert review is False


def test_multiple_scope_rules_and_financial_assets_are_excluded() -> None:
    included, category, reason, review = classify_exclusion(
        "주요사업비(기금사업비)",
        "보전지출",
        "여유자금운용",
        "여유자금운용",
        "국채외채권매입",
    )
    assert included is False
    assert category == "MULTIPLE_SCOPE_EXCLUSIONS"
    assert "FINANCIAL_ASSET_OPERATION" in str(reason)
    assert "PRESERVATION_EXPENDITURE" in str(reason)
    assert "SURPLUS_OPERATION" in str(reason)
    assert review is False


def test_missing_business_class_uses_narrow_administration_name_fallback() -> None:
    personnel = classify_exclusion(
        None,
        None,
        "행정안전행정지원",
        "소속기관인건비",
        "인건비(위원회)",
    )
    basic = classify_exclusion(
        None,
        None,
        "일반행정지원",
        "본부 기본경비",
        "중앙사고수습본부 기본경비(총액)",
    )
    policy_support = classify_exclusion(
        None,
        "일반지출",
        "보육지원강화",
        "어린이집 지원",
        "보육교직원 인건비 및 운영지원",
    )

    assert personnel[:2] == (False, "PERSONNEL")
    assert basic[:2] == (False, "BASIC_OPERATION")
    assert policy_support == (True, None, None, False)


def _source_frame() -> pd.DataFrame:
    rows = [
        {
            "project_id": "code:2024:101:110:1000:1001:1002",
            "fiscal_year": 2024,
            "ministry_code": "101",
            "ministry_name": "행정안전부",
            "account_code": "110",
            "account_name": "일반회계",
            "program_code": "1000",
            "program_name": "지역지원",
            "activity_code": "1001",
            "activity_name": "사업지원",
            "subactivity_code": "1002",
            "subactivity_name": "민간보조",
            "business_class_name": "주요사업비(기금사업비)",
            "finance_detail_name": "일반지출",
            "matching_status": "EXACT_HIERARCHY_UNIQUE",
            "settlement_matching_status": "EXACT_HIERARCHY_UNIQUE",
            "settlement_reconciliation_status": "EXACT",
            "settlement_vs_december_relative_difference": 0.0,
            "execution_denominator_status": "APPLIED",
            "quality_issue_reasons": "",
            "is_masked": False,
            "masked_source_row_count": 0,
            "source_path": "settlement_2024.csv",
            "source_datasets": '["budget"]',
            "settlement_expenditure_amount": 80,
            "settlement_current_budget_amount": 100,
            "current_budget_amount": 100,
            "execution_numerator_amount": 80,
            "execution_denominator_amount": 100,
        },
        {
            "project_id": "code:2024:075:433:2000:2001:2002",
            "fiscal_year": 2024,
            "ministry_code": "075",
            "ministry_name": "보건복지부",
            "account_code": "433",
            "account_name": "국립재활원",
            "program_code": "2000",
            "program_name": "기관운영",
            "activity_code": "2001",
            "activity_name": "기본경비",
            "subactivity_code": "2002",
            "subactivity_name": "기관운영",
            "business_class_name": "기본경비(경상운영비)",
            "finance_detail_name": "일반지출",
            "matching_status": "EXACT_HIERARCHY_UNIQUE",
            "settlement_matching_status": "EXACT_HIERARCHY_UNIQUE",
            "settlement_reconciliation_status": "EXACT",
            "settlement_vs_december_relative_difference": 0.0,
            "execution_denominator_status": "MISSING_DENOMINATOR",
            "quality_issue_reasons": "MISSING_DENOMINATOR",
            "is_masked": False,
            "masked_source_row_count": 0,
            "source_path": "settlement_2024.csv",
            "source_datasets": '["budget"]',
            "settlement_expenditure_amount": 20,
            "settlement_current_budget_amount": pd.NA,
            "current_budget_amount": 25,
            "execution_numerator_amount": 20,
            "execution_denominator_amount": pd.NA,
        },
        {
            "project_id": "code:2024:019:541:3000:3001:3002",
            "fiscal_year": 2024,
            "ministry_code": "019",
            "ministry_name": "고용노동부",
            "account_code": "541",
            "account_name": "고용보험기금",
            "program_code": "3000",
            "program_name": "고용지원",
            "activity_code": "3001",
            "activity_name": "직접사업",
            "subactivity_code": "3002",
            "subactivity_name": "취업지원",
            "business_class_name": "주요사업비(기금사업비)",
            "finance_detail_name": "일반지출",
            "matching_status": "EXACT_HIERARCHY_UNIQUE",
            "settlement_matching_status": "EXACT_HIERARCHY_UNIQUE",
            "settlement_reconciliation_status": "EXACT",
            "settlement_vs_december_relative_difference": 0.0,
            "execution_denominator_status": "APPLIED",
            "quality_issue_reasons": "EXECUTION_RATE_OVER_1",
            "is_masked": False,
            "masked_source_row_count": 0,
            "source_path": "settlement_2024.csv",
            "source_datasets": '["budget"]',
            "settlement_expenditure_amount": 120,
            "settlement_current_budget_amount": 100,
            "current_budget_amount": 100,
            "execution_numerator_amount": 120,
            "execution_denominator_amount": 100,
        },
    ]
    return pd.DataFrame(rows)


def _build(tmp_path: Path):
    source = _source_frame()
    source_path = tmp_path / "financial.parquet"
    source.to_parquet(source_path, index=False)
    manual = pd.DataFrame(
        [
            {
                "project_id": source.loc[1, "project_id"],
                "fiscal_year": 2024,
                "ministry_code": "075",
                "review_priority": "NON_BLOCKING",
                "blocks_annual_financial_analysis": False,
                "automatic_resolution_rule": "EXCLUDE_EXECUTION_RATE_MISSING_DENOMINATOR",
                "priority_reason": "MISSING_DENOMINATOR",
            },
            {
                "project_id": source.loc[2, "project_id"],
                "fiscal_year": 2024,
                "ministry_code": "019",
                "review_priority": "INFORMATIONAL",
                "blocks_annual_financial_analysis": False,
                "automatic_resolution_rule": "KEEP_RATE_AND_FLAG_NO_AUTOMATIC_CLIPPING",
                "priority_reason": "EXECUTION_RATE_OVER_1",
            },
        ]
    )
    manual_path = tmp_path / "manual.csv"
    manual.to_csv(manual_path, index=False)
    over = pd.DataFrame(
        [
            {
                "project_id": source.loc[2, "project_id"],
                "fiscal_year": 2024,
                "ministry_code": "019",
            }
        ]
    )
    over_path = tmp_path / "over.csv"
    over.to_csv(over_path, index=False)
    datasets = tmp_path / "datasets.yaml"
    datasets.write_text("datasets: {}\n", encoding="utf-8")
    ministries = tmp_path / "ministries.yaml"
    ministries.write_text(
        'ministries:\n  - code: "101"\n  - code: "075"\n  - code: "019"\n',
        encoding="utf-8",
    )
    guide = tmp_path / "guide.md"
    guide.write_text("# guide\n", encoding="utf-8")
    return (
        source,
        build_project_classification(
            financial_v1_path=source_path,
            manual_review_path=manual_path,
            execution_over_100_path=over_path,
            datasets_path=datasets,
            ministries_path=ministries,
            mentoring_guide_path=guide,
            project_plan_path=tmp_path / "missing-plan.md",
            output_dir=tmp_path / "out",
            overwrite=True,
        ),
    )


def test_missing_denominator_restricts_rate_not_row_and_over_100_is_rate_limited(
    tmp_path: Path,
) -> None:
    source, result = _build(tmp_path)
    combined = pd.concat(
        [result.analysis_population, result.analysis_excluded], ignore_index=True
    ).set_index("source_project_year_id")
    missing_den = combined.loc[source.loc[1, "project_id"]]
    assert missing_den["financial_quality_level"] == "RESTRICTED"
    assert bool(missing_den["financial_analysis_eligible"])
    assert not bool(missing_den["execution_rate_analysis_eligible"])
    assert "SETTLEMENT_UNLINKED" not in str(
        missing_den.get("financial_analysis_limitation_flags") or ""
    )
    assert "EXECUTION_DENOMINATOR_UNCONFIRMED" in str(
        missing_den.get("financial_analysis_limitation_flags") or ""
    )
    over_row = combined.loc[source.loc[2, "project_id"]]
    assert bool(over_row["financial_analysis_eligible"])
    assert not bool(over_row["execution_rate_analysis_eligible"])


def test_population_partition_preserves_row_count(tmp_path: Path) -> None:
    source, result = _build(tmp_path)
    assert len(result.analysis_population) + len(result.analysis_excluded) == len(source)
    assert result.summary["validation"]["population_partition_matches_source"] is True


def test_comparison_group_size_counts_unique_projects(tmp_path: Path) -> None:
    _, result = _build(tmp_path)
    assert len(result.analysis_population) == 2
    assert result.analysis_population["comparison_group_size"].eq(1).all()
    assert result.analysis_population["small_group_flag"].all()


def test_unknown_instrument_is_not_confirmed(tmp_path: Path) -> None:
    _, result = _build(tmp_path)
    unknown = result.classification[result.classification["fiscal_instrument"] == "UNKNOWN"]
    assert not unknown["classification_status"].eq("RULE_CONFIRMED").any()


def test_source_amounts_are_unchanged(tmp_path: Path) -> None:
    source, result = _build(tmp_path)
    combined = pd.concat(
        [result.analysis_population, result.analysis_excluded], ignore_index=True
    ).set_index("source_project_year_id")
    expected = source.set_index("project_id")
    for column in [
        "settlement_expenditure_amount",
        "settlement_current_budget_amount",
        "current_budget_amount",
        "execution_numerator_amount",
        "execution_denominator_amount",
    ]:
        pd.testing.assert_series_equal(
            combined[column].sort_index().astype("Float64"),
            expected[column].sort_index().astype("Float64"),
            check_names=False,
        )
