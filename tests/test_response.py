from __future__ import annotations

import json
from pathlib import Path

from open_fiscal_pipeline.response import parse_api_payload


def _load_fixture(name: str):
    return json.loads(Path(f"tests/fixtures/{name}").read_text(encoding="utf-8"))


def test_parse_standard_open_fiscal_response() -> None:
    payload = _load_fixture("openfiscal_success.json")
    parsed = parse_api_payload(payload, "ExpenditureBudgetInit5")

    assert parsed.is_success
    assert not parsed.is_no_data
    assert parsed.total_count == 2
    assert len(parsed.records) == 2
    assert parsed.records[0]["OFFC_NM"] == "중소벤처기업부"
    assert parsed.result_code == "INFO-000"
    assert parsed.top_level_type == "object"


def test_parse_list_root_open_fiscal_response() -> None:
    payload = _load_fixture("openfiscal_list_root.json")
    parsed = parse_api_payload(payload, "ExpenditureBudgetInit5")

    assert parsed.is_success
    assert parsed.total_count == 2
    assert len(parsed.records) == 2
    assert parsed.records[1]["FSCL_BSNS_NM"] == "시험사업2"
    assert parsed.result_code == "INFO-000"
    assert parsed.top_level_type == "array"
    assert parsed.top_level_keys == ("ExpenditureBudgetInit5",)


def test_parse_direct_record_list() -> None:
    payload = [
        {"FSCL_YY": "2024", "OFFC_NM": "중소벤처기업부"},
        {"FSCL_YY": "2025", "OFFC_NM": "중소벤처기업부"},
    ]
    parsed = parse_api_payload(payload)

    assert parsed.is_success
    assert parsed.total_count is None
    assert len(parsed.records) == 2
    assert parsed.top_level_type == "array"
