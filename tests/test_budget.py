from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from open_fiscal_pipeline.budget import (
    build_budget_summary,
    collect_budget_slice,
)
from open_fiscal_pipeline.config import DatasetConfig, Ministry


class FakeCollector:
    def __init__(self, records: int = 2) -> None:
        self.records = records
        self.calls = 0

    def collect_pages(
        self,
        dataset: DatasetConfig,
        *,
        output_dir: Path,
        params: dict[str, Any],
        max_pages: int | None = None,
        page_size: int | None = None,
    ) -> list[Path]:
        self.calls += 1
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "page_0001_test.json"
        path.write_text(
            json.dumps(
                {
                    "metadata": {
                        "dataset_id": dataset.dataset_id,
                        "page_index": 1,
                        "record_count": self.records,
                        "total_count": self.records,
                        "params": params,
                    },
                    "response": {},
                }
            ),
            encoding="utf-8",
        )
        return [path]


def _dataset() -> DatasetConfig:
    return DatasetConfig(
        dataset_id="budget",
        name="예산",
        source_type="api",
        url="https://example.invalid",
        parameter_map={"year": "FSCL_YY", "ministry": "OFFC_NM"},
        required=("year",),
    )


def test_collect_budget_slice_saves_partition_and_params(tmp_path: Path) -> None:
    client = FakeCollector()
    result = collect_budget_slice(
        client,
        _dataset(),
        Ministry("019", "고용노동부"),
        2024,
        output_dir=tmp_path,
        page_size=1000,
    )

    assert result.status == "success"
    assert result.record_count == 2
    assert (tmp_path / "budget/year=2024/ministry_code=019/page_0001_test.json").exists()


def test_complete_partition_is_skipped(tmp_path: Path) -> None:
    client = FakeCollector()
    kwargs = {
        "output_dir": tmp_path,
        "page_size": 1000,
    }
    collect_budget_slice(
        client,
        _dataset(),
        Ministry("019", "고용노동부"),
        2024,
        **kwargs,
    )
    result = collect_budget_slice(
        client,
        _dataset(),
        Ministry("019", "고용노동부"),
        2024,
        **kwargs,
    )

    assert result.status == "skipped"
    assert client.calls == 1


def test_incomplete_partition_requires_explicit_overwrite(tmp_path: Path) -> None:
    partition = tmp_path / "budget/year=2024/ministry_code=019"
    partition.mkdir(parents=True)
    (partition / "page_0001_test.json").write_text(
        json.dumps(
            {
                "metadata": {
                    "page_index": 1,
                    "record_count": 1,
                    "total_count": 2,
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="미완료 원본 파티션"):
        collect_budget_slice(
            FakeCollector(),
            _dataset(),
            Ministry("019", "고용노동부"),
            2024,
            output_dir=tmp_path,
            page_size=1000,
        )


def test_budget_summary_reports_failures_and_counts() -> None:
    from open_fiscal_pipeline.budget import BudgetCollectionResult

    summary = build_budget_summary(
        [
            BudgetCollectionResult("a", "019", "고용노동부", 2024, "success", 1, 10, 10),
            BudgetCollectionResult(
                "b",
                "019",
                "고용노동부",
                2024,
                "failure",
                error="boom",
            ),
        ]
    )

    assert summary["record_count"] == 10
    assert summary["status_counts"] == {"success": 1, "failure": 1}
    assert len(summary["failures"]) == 1
