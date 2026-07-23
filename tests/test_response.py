from __future__ import annotations

import json
from pathlib import Path

from open_fiscal_pipeline.response import parse_api_payload


def test_parse_standard_open_fiscal_response() -> None:
    payload = json.loads(
        Path("tests/fixtures/openfiscal_success.json").read_text(encoding="utf-8")
    )
    parsed = parse_api_payload(payload, "ExpenditureBudgetInit5")

    assert parsed.is_success
    assert not parsed.is_no_data
    assert parsed.total_count == 2
    assert len(parsed.records) == 2
    assert parsed.records[0]["OFFC_NM"] == "중소벤처기업부"
    assert parsed.result_code == "INFO-000"
