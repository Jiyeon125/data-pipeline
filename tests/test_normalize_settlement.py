from __future__ import annotations

from pathlib import Path

import pandas as pd

from open_fiscal_pipeline.config import Ministry
from open_fiscal_pipeline.normalize_settlement import normalize_settlement


def test_normalize_settlement_matches_code_and_preserves_amounts(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    pd.DataFrame(
        [
            {
                "No.": "1",
                "회계연도": "2024",
                "소관명": "고용노동부",
                "회계코드명": "일반회계",
                "계정명": "",
                "분야명": "사회복지",
                "부문명": "고용",
                "프로그램명": "프로그램",
                "단위사업명": "단위사업",
                "세부사업명": "세부사업",
                "세출예산금액": "1,000",
                "증감액": "100",
                "세출예산현액": "1,100",
                "지출금액": "900",
                "지출순액": "890",
                "차년도이월금액": "50",
                "불용금액": "150",
            }
        ]
    ).to_csv(
        raw / "사업별결산세출지출현황_2024.csv",
        index=False,
        encoding="utf-8-sig",
    )
    monthly = tmp_path / "monthly.parquet"
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
    ).to_parquet(monthly, index=False)

    result = normalize_settlement(
        input_dir=raw,
        output_dir=tmp_path / "processed",
        ministries={"019": Ministry("019", "고용노동부")},
        monthly_path=monthly,
    )

    assert result.summary["normalized_row_count"] == 1
    assert result.records.loc[0, "matching_status"] == "EXACT_HIERARCHY_UNIQUE"
    assert result.records.loc[0, "settlement_expenditure_amount"] == 900
    assert result.records.loc[0, "source_unit"] == "KRW"
    assert result.summary["data_dictionary_column_count"] == result.summary["table_column_count"]
