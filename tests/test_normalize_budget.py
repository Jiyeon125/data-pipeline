from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from open_fiscal_pipeline.config import DatasetConfig
from open_fiscal_pipeline.normalize_budget import normalize_budget


def _dataset() -> DatasetConfig:
    return DatasetConfig(
        dataset_id="expenditure_budget_init",
        name="세부사업 예산",
        source_type="api",
        url="https://example.invalid",
        service_name="ExpenditureBudgetInit5",
        expected_fields=(
            "FSCL_YY",
            "OFFC_NM",
            "FSCL_NM",
            "PGM_NM",
            "ACTV_NM",
            "SACTV_NM",
            "Y_YY_MEDI_KCUR_AMT",
        ),
        amount_fields=("Y_YY_MEDI_KCUR_AMT",),
    )


def test_normalize_budget_preserves_amount_type_and_matches_codes(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    partition = raw_dir / "expenditure_budget_init" / "year=2024" / "ministry_code=019"
    partition.mkdir(parents=True)
    document = {
        "metadata": {
            "dataset_id": "expenditure_budget_init",
            "page_index": 1,
            "requested_at": "2026-07-24T00:00:00Z",
            "api_url": "https://example.invalid",
        },
        "response": {
            "ExpenditureBudgetInit5": [
                {"head": [{"list_total_count": 1}, {"RESULT": {"CODE": "INFO-000"}}]},
                {
                    "row": [
                        {
                            "FSCL_YY": "2024",
                            "OFFC_NM": "고용노동부",
                            "FSCL_NM": "일반회계",
                            "PGM_NM": "프로그램",
                            "ACTV_NM": "단위사업",
                            "SACTV_NM": "세부사업",
                            "Y_YY_MEDI_KCUR_AMT": "1,200",
                        }
                    ]
                },
            ]
        },
    }
    (partition / "page_0001_test.json").write_text(
        json.dumps(document, ensure_ascii=False),
        encoding="utf-8",
    )
    monthly_path = tmp_path / "monthly.parquet"
    pd.DataFrame(
        [
            {
                "fiscal_year": 2024,
                "ministry_code": "019",
                "account_name": "일반회계",
                "program_name": "프로그램",
                "activity_name": "단위사업",
                "subactivity_name": "세부사업",
                "account_code": "01",
                "program_code": "1000",
                "activity_code": "1100",
                "subactivity_code": "1110",
            }
        ]
    ).to_parquet(monthly_path, index=False)

    result = normalize_budget(
        input_dir=raw_dir,
        output_dir=tmp_path / "processed" / "budget",
        amount_event_output_dir=tmp_path / "processed" / "amount_event",
        datasets={"expenditure_budget_init": _dataset()},
        monthly_path=monthly_path,
    )

    assert result.summary["raw_record_count"] == 1
    assert result.summary["raw_vs_normalized_difference"] == 0
    assert result.records.loc[0, "matching_status"] == "EXACT_HIERARCHY_UNIQUE"
    assert result.records.loc[0, "subactivity_code"] == "1110"
    assert result.amount_events.loc[0, "amount"] == 1200
    assert result.amount_events.loc[0, "amount_type"] == "Y_YY_MEDI_KCUR_AMT"
    assert result.amount_events.loc[0, "unit_confirmed"] == False


def test_masked_amount_is_null_and_requires_review(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    partition = raw_dir / "expenditure_budget_init" / "year=2024" / "ministry_code=019"
    partition.mkdir(parents=True)
    (partition / "page_0001_test.json").write_text(
        json.dumps(
            {
                "metadata": {
                    "dataset_id": "expenditure_budget_init",
                    "page_index": 1,
                },
                "response": {
                    "ExpenditureBudgetInit5": [
                        {"head": [{"list_total_count": 1}]},
                        {
                            "row": [
                                {
                                    "FSCL_YY": "2024",
                                    "Y_YY_MEDI_KCUR_AMT": "***",
                                }
                            ]
                        },
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    result = normalize_budget(
        input_dir=raw_dir,
        output_dir=tmp_path / "budget",
        amount_event_output_dir=tmp_path / "amount_event",
        datasets={"expenditure_budget_init": _dataset()},
    )

    assert pd.isna(result.amount_events.loc[0, "amount"])
    assert bool(result.amount_events.loc[0, "is_masked"])
    assert bool(result.records.loc[0, "manual_review_required"])
