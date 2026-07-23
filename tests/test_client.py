from __future__ import annotations

import json
from pathlib import Path

import httpx

from open_fiscal_pipeline.client import OpenFiscalClient
from open_fiscal_pipeline.config import DatasetConfig, Settings


def test_request_uses_exact_open_fiscal_base_params() -> None:
    payload = json.loads(
        Path("tests/fixtures/openfiscal_success.json").read_text(encoding="utf-8")
    )
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(200, json=payload)

    dataset = DatasetConfig(
        dataset_id="expenditure_budget_init",
        name="세부사업 총액",
        source_type="api",
        url="https://example.test/ExpenditureBudgetInit5",
        service_name="ExpenditureBudgetInit5",
    )
    settings = Settings(api_key="secret", page_size=1000)

    with OpenFiscalClient(settings, transport=httpx.MockTransport(handler)) as client:
        page = client.request_page(
            dataset,
            page_index=1,
            page_size=5,
            params={"FSCL_YY": "2024", "OFFC_NM": "중소벤처기업부"},
        )

    assert captured["Key"] == "secret"
    assert captured["Type"] == "json"
    assert captured["pIndex"] == "1"
    assert captured["pSize"] == "5"
    assert captured["FSCL_YY"] == "2024"
    assert captured["OFFC_NM"] == "중소벤처기업부"
    assert len(page.parsed.records) == 2
