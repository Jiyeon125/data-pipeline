from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from open_fiscal_pipeline.normalize_monthly import (
    apply_validation_flags,
    build_normalization_summary,
    extract_rows_from_document,
    normalize_monthly,
    normalize_record,
    parse_amount,
)


def _page_document(
    rows: list[dict],
    *,
    page_index: int = 1,
    requested_at: str = "2026-07-24T00:00:00+00:00",
) -> dict:
    return {
        "metadata": {
            "page_index": page_index,
            "requested_at": requested_at,
            "record_count": len(rows),
        },
        "response": {
            "VWFOEM2": [
                {
                    "head": [
                        {"list_total_count": len(rows)},
                        {"RESULT": {"CODE": "INFO-000", "MESSAGE": "ok"}},
                    ]
                },
                {"row": rows},
            ]
        },
    }


def _base_row(**overrides: object) -> dict:
    row = {
        "FSCL_YY": "2024",
        "EXE_M": "202401",
        "OFFC_CD": "019",
        "OFFC_NM": "고용노동부",
        "FSCL_CD": "110",
        "FSCL_NM": "일반회계",
        "FLD_CD": "010",
        "FLD_NM": "일반·지방행정",
        "SECT_CD": "011",
        "SECT_NM": "일반행정",
        "PGM_CD": "1000",
        "PGM_NM": "프로그램",
        "ACTV_CD": "2000",
        "ACTV_NM": "단위사업",
        "SACTV_CD": "300",
        "SACTV_NM": "세부사업",
        "ANEXP_BDG_AMT": 1000,
        "ANEXP_BDG_CAMT": 900,
        "EP_AMT": 100,
        "THISM_AGGR_EP_AMT": 100,
        "THISM_AGGR_EP_NAMT": 80,
    }
    row.update(overrides)
    return row


def _write_partition(
    root: Path,
    *,
    year: int,
    ministry_code: str,
    execution_month: str,
    rows: list[dict],
    name: str = "page_0001_test.json",
) -> Path:
    partition = (
        root
        / f"year={year}"
        / f"ministry_code={ministry_code}"
        / f"execution_month={execution_month}"
    )
    partition.mkdir(parents=True, exist_ok=True)
    path = partition / name
    path.write_text(
        json.dumps(_page_document(rows), ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_extract_rows_from_raw_json() -> None:
    document = _page_document([_base_row(), _base_row(SACTV_CD="301")])

    rows = extract_rows_from_document(document)

    assert len(rows) == 2
    assert rows[0]["OFFC_CD"] == "019"


def test_code_preserves_leading_zero() -> None:
    row = normalize_record(
        _base_row(OFFC_CD="019", FSCL_CD="075"),
        source_file="a.json",
        source_page=1,
        source_requested_at="t",
    )

    assert row["ministry_code"] == "019"
    assert row["account_code"] == "075"


def test_normal_amount_becomes_int() -> None:
    assert parse_amount(12345) == (12345, None, False)
    assert parse_amount("1,234") == (1234, None, False)


def test_masked_amount_is_null_and_raw_preserved() -> None:
    amount, raw, masked = parse_amount("180310*******")
    assert amount is None
    assert raw == "180310*******"
    assert masked is True

    row = normalize_record(
        _base_row(THISM_AGGR_EP_AMT="180310*******"),
        source_file="masked.json",
        source_page=1,
        source_requested_at="t",
    )
    assert row["cumulative_expenditure_amount"] is None
    assert row["is_masked"] is True
    assert row["masked_fields"] == '["THISM_AGGR_EP_AMT"]'
    assert json.loads(row["masked_raw_values"])["THISM_AGGR_EP_AMT"] == "180310*******"
    assert json.loads(row["amount_missing_reasons"])["THISM_AGGR_EP_AMT"] == "MASKED_SOURCE_VALUE"
    assert row["masked_amount_flag"] is True
    assert row["manual_review_required"] is True
    assert row["review_status"] == "needs_review"
    assert row["table_id"] == "project_month"



def test_source_file_tracking(tmp_path: Path) -> None:
    _write_partition(
        tmp_path,
        year=2024,
        ministry_code="019",
        execution_month="202401",
        rows=[_base_row()],
    )

    result = normalize_monthly(
        input_dir=tmp_path,
        output_dir=tmp_path / "out",
        overwrite=True,
    )

    assert result.frame.iloc[0]["source_file"].endswith(
        "year=2024/ministry_code=019/execution_month=202401/page_0001_test.json"
    )
    assert int(result.frame.iloc[0]["source_page"]) == 1


def test_execution_month_yyyymm_and_year_mismatch_flag() -> None:
    ok = normalize_record(
        _base_row(EXE_M="202401"),
        source_file="a.json",
        source_page=1,
        source_requested_at="t",
    )
    bad = normalize_record(
        _base_row(FSCL_YY="2024", EXE_M="202501"),
        source_file="b.json",
        source_page=1,
        source_requested_at="t",
    )
    frame, issues = apply_validation_flags(pd.DataFrame([ok, bad]))

    assert ok["execution_month"] == "202401"
    assert bool(frame.loc[frame["source_file"] == "b.json", "execution_month_year_mismatch"].iloc[0])
    assert (issues["issue_type"] == "execution_month_year_mismatch").any()


def test_cumulative_decrease_flag() -> None:
    jan = normalize_record(
        _base_row(EXE_M="202401", EP_AMT=100, THISM_AGGR_EP_AMT=100),
        source_file="jan.json",
        source_page=1,
        source_requested_at="t",
    )
    feb = normalize_record(
        _base_row(EXE_M="202402", EP_AMT=10, THISM_AGGR_EP_AMT=50),
        source_file="feb.json",
        source_page=1,
        source_requested_at="t",
    )
    frame, issues = apply_validation_flags(pd.DataFrame([jan, feb]))

    assert bool(frame.loc[frame["execution_month"] == "202402", "cumulative_decrease_flag"].iloc[0])
    assert (issues["issue_type"] == "cumulative_decrease").any()


def test_duplicate_key_flag_keeps_rows() -> None:
    first = normalize_record(
        _base_row(EP_AMT=100, THISM_AGGR_EP_AMT=100),
        source_file="a.json",
        source_page=1,
        source_requested_at="t",
    )
    second = normalize_record(
        _base_row(EP_AMT=200, THISM_AGGR_EP_AMT=200),
        source_file="b.json",
        source_page=1,
        source_requested_at="t",
    )
    frame, issues = apply_validation_flags(pd.DataFrame([first, second]))

    assert len(frame) == 2
    assert bool(frame["duplicate_key_flag"].all())
    assert (issues["issue_detail"].astype(str).str.contains("same_key_different_values")).any()


def test_writes_year_and_combined_parquet(tmp_path: Path) -> None:
    _write_partition(
        tmp_path,
        year=2022,
        ministry_code="101",
        execution_month="202201",
        rows=[_base_row(FSCL_YY="2022", EXE_M="202201", OFFC_CD="101")],
    )
    _write_partition(
        tmp_path,
        year=2023,
        ministry_code="101",
        execution_month="202301",
        rows=[_base_row(FSCL_YY="2023", EXE_M="202301", OFFC_CD="101")],
    )

    result = normalize_monthly(
        input_dir=tmp_path,
        output_dir=tmp_path / "out",
        output_format="parquet",
        overwrite=True,
    )

    combined = tmp_path / "out" / "monthly_expenditure_2022_2023.parquet"
    year_2022 = tmp_path / "out" / "year=2022" / "monthly_expenditure.parquet"
    year_2023 = tmp_path / "out" / "year=2023" / "monthly_expenditure.parquet"
    assert combined.exists()
    assert year_2022.exists()
    assert year_2023.exists()
    assert len(result.frame) == 2
    assert (tmp_path / "out" / "data_dictionary.csv").exists()
    assert (tmp_path / "out" / "normalization_summary.json").exists()
    assert (tmp_path / "out" / "validation_issues.csv").exists()


def test_summary_counts(tmp_path: Path) -> None:
    _write_partition(
        tmp_path,
        year=2024,
        ministry_code="075",
        execution_month="202401",
        rows=[
            _base_row(OFFC_CD="075", THISM_AGGR_EP_AMT="12*****"),
            _base_row(OFFC_CD="075", SACTV_CD="301"),
        ],
    )
    result = normalize_monthly(
        input_dir=tmp_path,
        output_dir=tmp_path / "out",
        overwrite=True,
    )
    summary = result.summary

    assert summary["files_read"] == 1
    assert summary["raw_record_count"] == 2
    assert summary["normalized_row_count"] == 2
    assert summary["masked_row_count"] == 1
    assert summary["masked_field_counts"]["THISM_AGGR_EP_AMT"] == 1
    assert summary["raw_vs_normalized_difference"] == 0
    assert summary["ministry_row_counts"]["075"] == 2


def test_bad_file_recorded_and_others_processed(tmp_path: Path) -> None:
    _write_partition(
        tmp_path,
        year=2024,
        ministry_code="102",
        execution_month="202401",
        rows=[_base_row(OFFC_CD="102")],
    )
    bad_dir = (
        tmp_path
        / "year=2024"
        / "ministry_code=102"
        / "execution_month=202402"
    )
    bad_dir.mkdir(parents=True)
    (bad_dir / "page_0001_bad.json").write_text("{not-json", encoding="utf-8")

    result = normalize_monthly(
        input_dir=tmp_path,
        output_dir=tmp_path / "out",
        overwrite=True,
    )

    assert len(result.frame) == 1
    assert len(result.failed_files) == 1
    assert "JSON" in result.failed_files[0].error or "Expecting" in result.failed_files[0].error
    assert result.summary["failed_files"]


def test_summary_helper_difference() -> None:
    frame = pd.DataFrame(
        [
            normalize_record(
                _base_row(),
                source_file="a.json",
                source_page=1,
                source_requested_at="t",
            )
        ]
    )
    frame, issues = apply_validation_flags(frame)
    summary = build_normalization_summary(
        files_read=1,
        raw_record_count=1,
        frame=frame,
        issues=issues,
        failed_files=[],
    )
    assert summary["raw_vs_normalized_difference"] == 0
    assert summary["normalized_row_count"] == 1
