from __future__ import annotations

import json
from pathlib import Path

import httpx

from open_fiscal_pipeline.client import OpenFiscalClient
from open_fiscal_pipeline.config import DatasetConfig, Settings


def _load_fixture(name: str):
    return json.loads(Path(f"tests/fixtures/{name}").read_text(encoding="utf-8"))


def _dataset() -> DatasetConfig:
    return DatasetConfig(
        dataset_id="expenditure_budget_init",
        name="세부사업 총액",
        source_type="api",
        url="https://example.test/ExpenditureBudgetInit5",
        service_name="ExpenditureBudgetInit5",
    )


def test_request_uses_exact_open_fiscal_base_params() -> None:
    payload = _load_fixture("openfiscal_success.json")
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(200, json=payload)

    settings = Settings(api_key="secret", page_size=1000)

    with OpenFiscalClient(settings, transport=httpx.MockTransport(handler)) as client:
        page = client.request_page(
            _dataset(),
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
    assert page.parsed.top_level_type == "object"


def test_request_accepts_list_root_json() -> None:
    payload = _load_fixture("openfiscal_list_root.json")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    settings = Settings(api_key="secret", page_size=10)
    with OpenFiscalClient(settings, transport=httpx.MockTransport(handler)) as client:
        page = client.request_page(
            _dataset(),
            page_index=1,
            page_size=10,
            params={"FSCL_YY": "2024"},
        )

    assert len(page.parsed.records) == 2
    assert page.parsed.top_level_type == "array"
    assert page.parsed.result_code == "INFO-000"
