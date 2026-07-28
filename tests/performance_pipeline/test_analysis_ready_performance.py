from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from performance_pipeline.analysis_ready_performance import (
    AnalysisReadyPerformanceError,
    build_analysis_ready_master,
    build_verified_manual_analysis_ready_master,
    run_analysis_ready_master,
    run_verified_manual_analysis_ready_master,
)


def _manual(rows: list[dict] | None = None) -> pd.DataFrame:
    base = {
        "source_indicator_id": "id-1",
        "ministry_name": "중소벤처기업부",
        "fiscal_year": 2023,
        "performance_program_name": "프로그램A",
        "planned_target_raw": "10",
        "actual_value_raw": None,
        "official_achievement_rate_raw": None,
        "planned_target_numeric": 10.0,
        "actual_value_numeric": None,
        "official_achievement_rate_numeric": None,
        "source_trace": "manual.xlsx#row=1",
    }
    return pd.DataFrame(rows or [base])


def _reconciliation(rows: list[dict] | None = None) -> pd.DataFrame:
    base = {
        "source_indicator_id": "id-1",
        "ministry_code": "102",
        "ministry_name": "중소벤처기업부",
        "fiscal_year": 2023,
        "performance_program_name": "프로그램A",
        "report_target_numeric_pdf": 12.0,
        "actual_value_numeric_pdf": 15.0,
        "official_achievement_rate_numeric_pdf": 125.0,
        "pdf_report_target_raw": "12",
        "pdf_report_actual_raw": "15",
        "pdf_report_official_achievement_rate_raw": "125.0",
        "report_target_match_status": "MATCH_AFTER_CHANGE",
        "report_actual_match_status": "MANUAL_MISSING_PDF_PRESENT",
        "report_achievement_rate_match_status": "MANUAL_MISSING_PDF_PRESENT",
        "overall_reconciliation_status": "MANUAL_MISSING_PDF_PRESENT",
        "reviewer": "검수자",
        "review_status": "CONFIRMED",
        "review_note": "원문 확인",
        "review_confirmed_at": "2026-07-28",
        "report_source_file": "report.pdf",
        "report_split_pdf_page": 5,
        "report_source_pdf_page": 105,
        "documented_change_target_before_raw": "10",
        "documented_change_target_after_raw": "12",
        "documented_change_reason_raw": "실적치 확정 반영",
    }
    return pd.DataFrame(rows or [base])


def test_confirmed_pdf_values_fill_only_manual_missing_values() -> None:
    manual = _manual()
    result = build_analysis_ready_master(manual, _reconciliation())

    assert result.loc[0, "actual_value_numeric"] is None
    assert pd.isna(result.loc[0, "official_achievement_rate_numeric"])
    assert result.loc[0, "analysis_actual_value_numeric"] == 15.0
    assert result.loc[0, "analysis_official_achievement_rate_numeric"] == 125.0
    assert result.loc[0, "analysis_actual_value_source"] == "PDF_CONFIRMED"
    assert result.loc[0, "analysis_official_achievement_rate_source"] == "PDF_CONFIRMED"
    assert result.loc[0, "analysis_plan_target_numeric"] == 10.0
    assert result.loc[0, "analysis_report_target_numeric"] == 12.0
    assert result.loc[0, "ministry_code"] == "102"
    assert result.loc[0, "analysis_ready_for_same_year_rate"]


def test_existing_manual_values_win_over_conflicting_pdf_values() -> None:
    manual = _manual(
        [
            {
                **_manual().iloc[0].to_dict(),
                "actual_value_raw": "17.7",
                "official_achievement_rate_raw": "106.6",
                "actual_value_numeric": 17.7,
                "official_achievement_rate_numeric": 106.6,
            }
        ]
    )
    reconciliation = _reconciliation(
        [
            {
                **_reconciliation().iloc[0].to_dict(),
                "report_target_match_status": "VALUE_MISMATCH",
                "report_actual_match_status": "VALUE_MISMATCH",
                "report_achievement_rate_match_status": "VALUE_MISMATCH",
                "overall_reconciliation_status": "AMBIGUOUS",
            }
        ]
    )

    result = build_analysis_ready_master(manual, reconciliation)

    assert result.loc[0, "analysis_actual_value_numeric"] == 17.7
    assert result.loc[0, "analysis_official_achievement_rate_numeric"] == 106.6
    assert result.loc[0, "analysis_actual_value_source"] == "MANUAL"
    assert pd.isna(result.loc[0, "analysis_report_target_numeric"])


def test_unconfirmed_pdf_values_do_not_fill_manual_missing_values() -> None:
    reconciliation = _reconciliation()
    reconciliation.loc[0, "review_status"] = None

    result = build_analysis_ready_master(_manual(), reconciliation)

    assert pd.isna(result.loc[0, "analysis_actual_value_numeric"])
    assert pd.isna(result.loc[0, "analysis_official_achievement_rate_numeric"])
    assert result.loc[0, "analysis_actual_value_source"] == "MISSING"
    assert not result.loc[0, "analysis_ready_for_same_year_rate"]


def test_verified_manual_master_preserves_values_without_inventing_report_target(
    tmp_path: Path,
) -> None:
    manual = _manual(
        [
            {
                **_manual().iloc[0].to_dict(),
                "actual_value_raw": "15",
                "official_achievement_rate_raw": "125",
                "actual_value_numeric": 15.0,
                "official_achievement_rate_numeric": 125.0,
            }
        ]
    )
    master = build_verified_manual_analysis_ready_master(manual, ministry_code="019")

    assert master.loc[0, "ministry_code"] == "019"
    assert master.loc[0, "analysis_actual_value_numeric"] == 15.0
    assert master.loc[0, "analysis_official_achievement_rate_numeric"] == 125.0
    assert pd.isna(master.loc[0, "analysis_report_target_numeric"])
    assert master.loc[0, "analysis_achievement_rate_formula_eligible"]
    assert manual.equals(master.loc[:, manual.columns])

    manual_path = tmp_path / "program_kpi_year.parquet"
    output_dir = tmp_path / "analysis_ready"
    manual.to_parquet(manual_path, index=False)
    before = manual_path.read_bytes()
    result = run_verified_manual_analysis_ready_master(
        manual_path=manual_path,
        output_dir=output_dir,
        ministry_code="019",
    )
    assert result.summary["validation"]["row_count_preserved"]
    assert result.summary["validation"]["original_columns_preserved"]
    assert result.summary["validation"]["input_file_unchanged"]
    assert before == manual_path.read_bytes()


def test_visual_confirmation_fills_only_missing_report_target() -> None:
    reconciliation = _reconciliation()
    reconciliation.loc[0, "report_target_numeric_pdf"] = None
    reconciliation.loc[0, "pdf_report_target_raw"] = None
    reconciliation.loc[0, "report_target_match_status"] = "OCR_REQUIRED"
    confirmation = pd.DataFrame(
        [
            {
                "source_indicator_id": "id-1",
                "confirmed_report_target_raw": "10",
                "confirmed_report_target_numeric": 10.0,
                "source_file": "report.pdf",
                "split_pdf_page": 7,
                "source_pdf_page": 176,
                "reviewer": "Codex PDF 육안검수",
                "confirmed_at": "2026-07-28",
                "note": "목표칸 확인",
            }
        ]
    )

    result = build_analysis_ready_master(_manual(), reconciliation, confirmation)

    assert result.loc[0, "analysis_report_target_numeric"] == 10.0
    assert result.loc[0, "analysis_report_target_source"] == "PDF_VISUAL_CONFIRMED"
    assert result.loc[0, "analysis_report_target_confirmed_source_page"] == 176


def test_row_id_mismatch_fails_instead_of_dropping_rows() -> None:
    reconciliation = _reconciliation()
    reconciliation.loc[0, "source_indicator_id"] = "other-id"

    with pytest.raises(AnalysisReadyPerformanceError, match="행ID 집합"):
        build_analysis_ready_master(_manual(), reconciliation)


def test_nonstandard_formula_is_preserved_but_not_formula_eligible() -> None:
    manual = _manual()
    manual.loc[0, "source_indicator_id"] = "중기부-2023-II1-03"
    reconciliation = _reconciliation()
    reconciliation.loc[0, "source_indicator_id"] = "중기부-2023-II1-03"

    result = build_analysis_ready_master(manual, reconciliation)

    assert result.loc[0, "analysis_official_achievement_rate_numeric"] == 125.0
    assert result.loc[0, "analysis_achievement_rate_formula_review_required"]
    assert not result.loc[0, "analysis_achievement_rate_formula_eligible"]


def test_run_writes_reproducible_outputs_without_changing_inputs(tmp_path: Path) -> None:
    manual_path = tmp_path / "manual.parquet"
    reconciliation_path = tmp_path / "reconciliation.parquet"
    confirmations_path = tmp_path / "confirmations.csv"
    output_dir = tmp_path / "output"
    _manual().to_parquet(manual_path, index=False)
    reconciliation = _reconciliation()
    reconciliation.loc[0, "report_target_numeric_pdf"] = None
    reconciliation.loc[0, "pdf_report_target_raw"] = None
    reconciliation.loc[0, "report_target_match_status"] = "OCR_REQUIRED"
    reconciliation.to_parquet(reconciliation_path, index=False)
    pd.DataFrame(
        [
            {
                "source_indicator_id": "id-1",
                "confirmed_report_target_raw": "10",
                "confirmed_report_target_numeric": 10.0,
                "source_file": "report.pdf",
                "split_pdf_page": 7,
                "source_pdf_page": 176,
                "reviewer": "검수자",
                "confirmed_at": "2026-07-28",
                "note": "목표칸 확인",
            }
        ]
    ).to_csv(confirmations_path, index=False)
    before = (
        manual_path.read_bytes(),
        reconciliation_path.read_bytes(),
        confirmations_path.read_bytes(),
    )

    result = run_analysis_ready_master(
        manual_path=manual_path,
        reconciliation_path=reconciliation_path,
        report_target_confirmations_path=confirmations_path,
        output_dir=output_dir,
    )

    assert [path.exists() for path in result.output_paths] == [True, True]
    assert result.summary["validation"]["original_columns_preserved"]
    assert result.summary["validation"]["input_files_unchanged"]
    assert result.summary["validation"]["visual_target_adoption_requires_confirmation"]
    assert result.master.loc[0, "analysis_report_target_numeric"] == 10.0
    assert before == (
        manual_path.read_bytes(),
        reconciliation_path.read_bytes(),
        confirmations_path.read_bytes(),
    )
