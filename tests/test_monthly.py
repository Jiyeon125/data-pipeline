from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from open_fiscal_pipeline.config import DatasetConfig, Ministry, Settings, load_ministries
from open_fiscal_pipeline.monthly import (
    MonthlyResult,
    build_summary,
    collect_ministry_month,
    monthly_partition,
)
from open_fiscal_pipeline.response import ParsedResponse


@dataclass
class FakePage:
    page_index: int
    requested_at: str
    payload: Any
    parsed: ParsedResponse


class FakeClient:
    def __init__(self, pages: list[FakePage]) -> None:
        self.pages = pages
        self.calls: list[dict[str, Any]] = []
        self.settings = Settings(api_key="test", request_interval_seconds=0)

    def request_page(self, dataset: DatasetConfig, **kwargs: Any) -> FakePage:
        self.calls.append({"dataset": dataset, **kwargs})
        return self.pages.pop(0)


def _dataset() -> DatasetConfig:
    return DatasetConfig(
        dataset_id="monthly_expenditure",
        name="월별 지출운용상황",
        source_type="api",
        url="https://example.test/VWFOEM2",
        service_name="VWFOEM2",
    )


def _page(page_index: int, records: int, total_count: int) -> FakePage:
    rows = [{"index": value} for value in range(records)]
    parsed = ParsedResponse(
        service_name="VWFOEM2",
        records=rows,
        total_count=total_count,
        result_code="INFO-000",
        result_message="정상 처리되었습니다.",
        top_level_keys=("VWFOEM2",),
        top_level_type="object",
    )
    return FakePage(
        page_index=page_index,
        requested_at="2026-07-24T00:00:00+00:00",
        payload={"VWFOEM2": {"row": rows}},
        parsed=parsed,
    )


def test_ministry_codes_preserve_leading_zeroes() -> None:
    ministries = load_ministries("configs/ministries.yaml")

    assert ministries["019"].name == "고용노동부"
    assert ministries["075"].name == "보건복지부"


def test_collect_saves_partitioned_pages_and_metadata(tmp_path: Path) -> None:
    client = FakeClient([_page(1, 2, 3), _page(2, 1, 3)])
    ministry = Ministry(code="019", name="고용노동부")

    result = collect_ministry_month(
        client,
        _dataset(),
        ministry,
        2024,
        1,
        output_dir=tmp_path,
        page_size=2,
    )

    partition = monthly_partition(tmp_path, 2024, "019", "202401")
    paths = sorted(partition.glob("page_*.json"))
    document = json.loads(paths[0].read_text(encoding="utf-8"))
    assert result.status == "success"
    assert result.record_count == 3
    assert len(paths) == 2
    assert document["metadata"]["fiscal_year"] == "2024"
    assert document["metadata"]["execution_month"] == "202401"
    assert document["metadata"]["ministry_code"] == "019"
    assert document["metadata"]["total_count"] == 3
    assert client.calls[0]["params"]["EXE_M"] == "202401"


def test_existing_month_is_skipped_by_default(tmp_path: Path) -> None:
    ministry = Ministry(code="102", name="중소벤처기업부")
    partition = monthly_partition(tmp_path, 2024, "102", "202412")
    partition.mkdir(parents=True)
    (partition / "page_0001_existing.json").write_text(
        json.dumps({"metadata": {"page_index": 1, "record_count": 240, "total_count": 240}}),
        encoding="utf-8",
    )
    client = FakeClient([])

    result = collect_ministry_month(
        client,
        _dataset(),
        ministry,
        2024,
        12,
        output_dir=tmp_path,
        page_size=1000,
    )

    assert result.status == "skipped"
    assert result.record_count == 240
    assert not client.calls


def test_resume_starts_after_last_saved_page(tmp_path: Path) -> None:
    ministry = Ministry(code="075", name="보건복지부")
    partition = monthly_partition(tmp_path, 2024, "075", "202402")
    partition.mkdir(parents=True)
    (partition / "page_0001_existing.json").write_text(
        json.dumps({"metadata": {"page_index": 1, "record_count": 2, "total_count": 3}}),
        encoding="utf-8",
    )
    client = FakeClient([_page(2, 1, 3)])

    result = collect_ministry_month(
        client,
        _dataset(),
        ministry,
        2024,
        2,
        output_dir=tmp_path,
        page_size=2,
        resume=True,
    )

    assert result.status == "success"
    assert result.record_count == 3
    assert client.calls[0]["page_index"] == 2


def test_summary_contains_counts_and_failures() -> None:
    results = [
        MonthlyResult("101", "행정안전부", 2024, "202401", "success", 3, 1),
        MonthlyResult("101", "행정안전부", 2024, "202402", "failure", error="timeout"),
    ]

    summary = build_summary(results)

    assert summary["status_counts"]["success"] == 1
    assert summary["status_counts"]["failure"] == 1
    assert summary["ministry_record_counts"]["101"] == 3
    assert summary["year_record_counts"]["2024"] == 3
    assert summary["ministry_year_record_counts"]["101:2024"] == 3
    assert summary["failures"][0]["error"] == "timeout"
