from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl import Workbook

from performance_pipeline.manual_performance import build_manual_performance_pilot

HEADERS = [
    "행ID",
    "부처",
    "회계연도",
    "전략목표번호",
    "프로그램목표번호",
    "예산프로그램코드",
    "프로그램명",
    "계획서 성과지표명",
    "보고서 성과지표명",
    "단위",
    "지표방향",
    "목표치",
    "실적치",
    "달성률",
    "계획서 페이지",
    "보고서 페이지",
    "계획서 근거",
    "보고서 근거",
    "매칭상태",
    "변경내용",
    "검수자",
    "비고",
]


def _workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "02_골드셋"
    sheet.append(["설명"])
    sheet.append(["설명"])
    sheet.append([])
    sheet.append(HEADERS)
    sheet.append(
        [
            "id-1",
            "중소벤처기업부",
            2022,
            "Ⅰ",
            "Ⅰ-1",
            None,
            "프로그램A",
            "지표1",
            "지표1",
            "%",
            "상향",
            10,
            11,
            110,
            "p.1",
            "p.2",
            "목표 10",
            "실적 11",
            "완전일치",
            None,
            None,
            None,
        ]
    )
    sheet.append(
        [
            "id-2",
            "중소벤처기업부",
            2022,
            "Ⅰ",
            "Ⅰ-1",
            None,
            "프로그램A",
            "지표2",
            "지표2",
            "점",
            "상향",
            20,
            None,
            None,
            "p.1",
            "p.2",
            "목표 20",
            None,
            "불일치",
            "보고서 실적 없음",
            None,
            None,
        ]
    )
    sheet.append(
        [
            "id-3",
            "중소벤처기업부",
            2023,
            "Ⅱ",
            "Ⅱ-1",
            None,
            "프로 그램B",
            "지표3",
            "지표3",
            "%",
            "상향",
            30,
            31,
            103.3,
            "p.3",
            "p.4",
            "목표 30",
            "실적 31",
            "완전일치",
            None,
            None,
            None,
        ]
    )
    sheet.append(
        [
            "id-4",
            "중소벤처기업부",
            2024,
            "Ⅲ",
            "Ⅲ-1",
            None,
            "미매칭프로그램",
            "지표4",
            "지표4",
            "%",
            "상향",
            40,
            41,
            102.5,
            "p.5",
            "p.6",
            "목표 40",
            "실적 41",
            "완전일치",
            None,
            None,
            None,
        ]
    )
    sheet.append(
        [
            "id-1",
            "중소벤처기업부",
            2024,
            "Ⅲ",
            "Ⅲ-1",
            None,
            "예시프로그램",
            "예시지표",
            "예시지표",
            "%",
            "상향",
            1,
            1,
            100,
            "p.1",
            "p.1",
            "예시",
            "예시",
            "완전일치",
            None,
            "예시",
            "예시 행",
        ]
    )
    workbook.save(path)


def _financial(path: Path) -> None:
    pd.DataFrame(
        [
            {
                "fiscal_year": 2022,
                "ministry_code": "102",
                "ministry_name": "중소벤처기업부",
                "program_code": "0100",
                "program_name": "프로그램A",
                "original_budget": 100,
                "current_budget": 110,
                "settlement_expenditure": 90,
                "execution_rate": 0.818,
                "financial_linkage_status": "COMPLETE",
                "financial_quality_level": "HIGH",
            },
            {
                "fiscal_year": 2023,
                "ministry_code": "102",
                "ministry_name": "중소벤처기업부",
                "program_code": "0200",
                "program_name": "프로그램B",
                "original_budget": 200,
                "current_budget": 220,
                "settlement_expenditure": 180,
                "execution_rate": 0.818,
                "financial_linkage_status": "COMPLETE",
                "financial_quality_level": "HIGH",
            },
            {
                "fiscal_year": 2022,
                "ministry_code": "102",
                "ministry_name": "중소벤처기업부",
                "program_code": "UNKNOWN",
                "program_name": "프로그램A",
                "original_budget": 0,
                "current_budget": 0,
                "settlement_expenditure": 0,
                "execution_rate": None,
                "financial_linkage_status": "UNMATCHED",
                "financial_quality_level": "LOW",
            },
            {
                "fiscal_year": 2022,
                "ministry_code": "019",
                "ministry_name": "고용노동부",
                "program_code": "0100",
                "program_name": "다른부처프로그램",
                "original_budget": 999,
                "current_budget": 999,
                "settlement_expenditure": 999,
                "execution_rate": 1.0,
                "financial_linkage_status": "COMPLETE",
                "financial_quality_level": "HIGH",
            },
        ]
    ).to_parquet(path, index=False)


def test_manual_pilot_preserves_rows_and_matches_unique_program_years(
    tmp_path: Path,
) -> None:
    workbook_path = tmp_path / "manual.xlsx"
    financial_path = tmp_path / "financial.parquet"
    output_dir = tmp_path / "output"
    _workbook(workbook_path)
    _financial(financial_path)

    result = build_manual_performance_pilot(
        input_path=workbook_path,
        financial_path=financial_path,
        output_dir=output_dir,
    )

    assert len(result.manual_rows) == 5
    assert result.manual_rows["is_example"].sum() == 1
    assert len(result.indicators) == 4
    assert not result.indicators["source_indicator_id"].duplicated().any()
    assert len(result.program_year) == 3
    assert result.program_year["program_match_status"].value_counts().to_dict() == {
        "EXACT_NAME_UNIQUE_FINANCIAL": 1,
        "NORMALIZED_NAME": 1,
        "MANUAL_REVIEW_NO_MATCH": 1,
    }
    matched = result.program_year["program_match_eligible"].astype(bool)
    assert result.program_year.loc[matched, "original_budget"].sum() == 300
    assert result.summary["amount_reconciliation"]["original_budget"]["difference"] == 0
    assert result.summary["validation"]["source_file_unchanged"] is True
    assert result.summary["validation"]["amounts_preserved"] is True
    assert result.summary["actual_value_missing_count"] == 1
    assert all(path.exists() for path in result.output_paths)
