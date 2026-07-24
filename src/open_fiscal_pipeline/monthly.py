from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .client import OpenFiscalClient
from .config import DatasetConfig, Ministry


@dataclass(frozen=True)
class MonthlyResult:
    ministry_code: str
    ministry_name: str
    year: int
    execution_month: str
    status: str
    record_count: int = 0
    page_count: int = 0
    error: str | None = None


def monthly_partition(output_dir: Path, year: int, code: str, execution_month: str) -> Path:
    return (
        output_dir
        / f"year={year}"
        / f"ministry_code={code}"
        / f"execution_month={execution_month}"
    )


def _load_existing(paths: Iterable[Path]) -> tuple[int, int, int | None, bool]:
    record_count = 0
    max_page = 0
    total_count: int | None = None
    terminal = False
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        metadata = document.get("metadata", {})
        page_index = int(metadata.get("page_index", 0))
        count = int(metadata.get("record_count", 0))
        max_page = max(max_page, page_index)
        record_count += count
        if metadata.get("total_count") is not None:
            total_count = int(metadata["total_count"])
        terminal = terminal or bool(metadata.get("is_no_data"))
    return record_count, max_page, total_count, terminal


def _save_page(
    *,
    page: Any,
    dataset: DatasetConfig,
    output_dir: Path,
    page_size: int,
    year: int,
    execution_month: str,
    ministry: Ministry,
) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = output_dir / f"page_{page.page_index:04d}_{timestamp}.json"
    metadata = {
        "requested_at": page.requested_at,
        "dataset_id": dataset.dataset_id,
        "dataset_name": dataset.name,
        "api_url": dataset.url,
        "fiscal_year": str(year),
        "execution_month": execution_month,
        "ministry_code": ministry.code,
        "ministry_name": ministry.name,
        "page_index": page.page_index,
        "page_size": page_size,
        "params": {
            "FSCL_YY": str(year),
            "EXE_M": execution_month,
            "OFFC_CD": ministry.code,
        },
        "record_count": len(page.parsed.records),
        "total_count": page.parsed.total_count,
        "result_code": page.parsed.result_code,
        "result_message": page.parsed.result_message,
        "is_no_data": page.parsed.is_no_data,
        "top_level_type": page.parsed.top_level_type,
    }
    path.write_text(
        json.dumps({"metadata": metadata, "response": page.payload}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def collect_ministry_month(
    client: OpenFiscalClient,
    dataset: DatasetConfig,
    ministry: Ministry,
    year: int,
    month: int,
    *,
    output_dir: Path,
    page_size: int,
    resume: bool = False,
    overwrite: bool = False,
) -> MonthlyResult:
    execution_month = f"{year}{month:02d}"
    partition = monthly_partition(output_dir, year, ministry.code, execution_month)
    existing = sorted(partition.glob("page_*.json")) if partition.exists() else []

    if overwrite:
        for path in existing:
            path.unlink()
        existing = []
    elif existing and not resume:
        count, _, _, _ = _load_existing(existing)
        return MonthlyResult(
            ministry.code,
            ministry.name,
            year,
            execution_month,
            "skipped",
            count,
            len(existing),
        )

    partition.mkdir(parents=True, exist_ok=True)
    record_count, max_page, total_count, terminal = _load_existing(existing)
    if existing and resume and (
        terminal or (total_count is not None and record_count >= total_count)
    ):
        status = "no_data" if record_count == 0 else "skipped"
        return MonthlyResult(
            ministry.code,
            ministry.name,
            year,
            execution_month,
            status,
            record_count,
            len(existing),
        )

    page_index = max_page + 1
    new_pages = 0
    while True:
        page = client.request_page(
            dataset,
            page_index=page_index,
            page_size=page_size,
            params={
                "FSCL_YY": str(year),
                "EXE_M": execution_month,
                "OFFC_CD": ministry.code,
            },
        )
        _save_page(
            page=page,
            dataset=dataset,
            output_dir=partition,
            page_size=page_size,
            year=year,
            execution_month=execution_month,
            ministry=ministry,
        )
        new_pages += 1
        record_count += len(page.parsed.records)
        total_count = page.parsed.total_count
        if (
            page.parsed.is_no_data
            or not page.parsed.records
            or (total_count is not None and record_count >= total_count)
        ):
            break
        page_index += 1
        time.sleep(client.settings.request_interval_seconds)

    return MonthlyResult(
        ministry.code,
        ministry.name,
        year,
        execution_month,
        "no_data" if record_count == 0 else "success",
        record_count,
        len(existing) + new_pages,
    )


def build_summary(results: list[MonthlyResult]) -> dict[str, Any]:
    status_counts = {
        status: sum(result.status == status for result in results)
        for status in ("success", "no_data", "skipped", "failure")
    }
    ministry_totals: dict[str, int] = {}
    year_totals: dict[str, int] = {}
    ministry_year_totals: dict[str, int] = {}
    for result in results:
        ministry_totals[result.ministry_code] = (
            ministry_totals.get(result.ministry_code, 0) + result.record_count
        )
        year_key = str(result.year)
        year_totals[year_key] = year_totals.get(year_key, 0) + result.record_count
        ministry_year_key = f"{result.ministry_code}:{result.year}"
        ministry_year_totals[ministry_year_key] = (
            ministry_year_totals.get(ministry_year_key, 0) + result.record_count
        )
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "total_ministry_months": len(results),
        "status_counts": status_counts,
        "ministry_record_counts": ministry_totals,
        "year_record_counts": year_totals,
        "ministry_year_record_counts": ministry_year_totals,
        "results": [asdict(result) for result in results],
        "failures": [asdict(result) for result in results if result.status == "failure"],
    }
