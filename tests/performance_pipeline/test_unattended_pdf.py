from __future__ import annotations

import pandas as pd

from performance_pipeline import unattended_pdf as up


def _common(goal: str) -> dict[str, object]:
    return {
        "ministry_code": "102",
        "ministry_name": "중소벤처기업부",
        "fiscal_year": 2024,
        "document_type": "REPORT",
        "strategic_goal_number": "Ⅲ",
        "program_goal_number": goal,
        "program_name": "창업환경조성",
        "hierarchy_source_page": 5,
        "hierarchy_source_text": "프로그램목표 III-1",
        "source_file": "보고서.pdf",
        "source_pdf_page": 6,
        "printed_page": "4",
    }


def test_report_table_discovers_current_year_without_manual_indicator() -> None:
    rows = [
        ["성과지표", "측정산식", "목표대비 달성률", "'22년", "'23년", "'24년"],
        ["① 기술기반업종 창업기업 수(개)", "창업기업 수", "", "", "", ""],
        ["", "", "목표", "200,000", "220,000", "233,033"],
        ["", "", "실적", "190,000", "210,000", "214,917"],
        ["", "", "달성률", "95.0", "95.5", "92.2"],
    ]

    result = up.parse_report_table(rows, common=_common("Ⅲ-1"))

    assert len(result) == 1
    assert result[0]["indicator_name"] == "기술기반업종 창업기업 수"
    assert result[0]["report_target_raw"] == "233,033"
    assert result[0]["actual_value_raw"] == "214,917"
    assert result[0]["official_achievement_rate_raw"] == "92.2"


def test_duplicate_indicator_names_remain_separate_by_program_goal() -> None:
    first = {
        **_common("Ⅱ-1"),
        "indicator_name": "공통지표",
        "planned_target_raw": None,
        "report_target_raw": "8.13",
        "actual_value_raw": "8.28",
        "official_achievement_rate_raw": "101.8",
    }
    second = {
        **_common("Ⅲ-1"),
        "indicator_name": "공통지표",
        "planned_target_raw": None,
        "report_target_raw": "16.6",
        "actual_value_raw": "17.7",
        "official_achievement_rate_raw": "106.6",
    }

    result = up._deduplicate([first, second])

    assert len(result) == 2
    assert {row["program_goal_number"] for row in result} == {"Ⅱ-1", "Ⅲ-1"}
    assert {row["routing_status"] for row in result} == {"LOCAL_CONFIRMED"}


def test_gold_evaluation_uses_program_context_after_extraction() -> None:
    discovered = pd.DataFrame(
        [
            {
                **_common("Ⅲ-1"),
                "indicator_name": "기술기반업종 창업기업 수",
                "routing_status": "LOCAL_CONFIRMED",
                "planned_target_raw": None,
                "report_target_raw": "233,033",
                "actual_value_raw": "214,917",
                "official_achievement_rate_raw": "92.2",
            }
        ]
    )
    gold = pd.DataFrame(
        [
            {
                "source_indicator_id": "중기부-2024-III1-01",
                "ministry_code": "102",
                "fiscal_year": 2024,
                "program_goal_number": "Ⅲ-1",
                "indicator_name_plan": "다른 계획지표명",
                "indicator_name_report": "기술기반업종 창업기업 수",
                "planned_target_raw": "1",
                "actual_value_raw": "214917",
                "official_achievement_rate_raw": "92.2%",
            }
        ]
    )

    result = up.evaluate_discovery(discovered, gold)
    report = result[result["document_type"] == "REPORT"].iloc[0]

    assert bool(report["discovered"]) is True
    assert bool(report["actual_match"]) is True
    assert bool(report["rate_match"]) is True
