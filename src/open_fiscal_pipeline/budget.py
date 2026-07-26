"""예산 API 데이터셋의 부처·연도별 일괄 원본 수집."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from .config import DatasetConfig, Ministry

DEFAULT_BUDGET_DATASET_IDS = (
    "expenditure_budget_init",
    "total_expenditure_project",
    "expenditure_budget_add",
    "total_expenditure_item",
    "expenditure_budget_init_item",
)


class PageCollector(Protocol):
    def collect_pages(
        self,
        dataset: DatasetConfig,
        *,
        output_dir: Path,
        params: dict[str, Any],
        max_pages: int | None = None,
        page_size: int | None = None,
    ) -> list[Path]: ...


@dataclass(frozen=True)
class BudgetCollectionResult:
    dataset_id: str
    ministry_code: str
    ministry_name: str
    fiscal_year: int
    status: str
    file_count: int = 0
    record_count: int = 0
    total_count: int | None = None
    error: str | None = None


def budget_partition(
    output_dir: Path,
    dataset_id: str,
    fiscal_year: int,
    ministry_code: str,
) -> Path:
    return output_dir / dataset_id / f"year={fiscal_year}" / f"ministry_code={ministry_code}"


def _page_metadata(paths: list[Path]) -> tuple[int, int | None, bool]:
    record_count = 0
    total_count: int | None = None
    last_page_count: int | None = None
    page_indexes: list[int] = []
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        metadata = document.get("metadata") or {}
        page_count = int(metadata.get("record_count") or 0)
        record_count += page_count
        last_page_count = page_count
        page_indexes.append(int(metadata.get("page_index") or 0))
        if metadata.get("total_count") is not None:
            total_count = int(metadata["total_count"])
    complete = bool(paths) and (
        (total_count is not None and record_count >= total_count)
        or (last_page_count == 0 and max(page_indexes, default=0) > 0)
    )
    return record_count, total_count, complete


def collect_budget_slice(
    client: PageCollector,
    dataset: DatasetConfig,
    ministry: Ministry,
    fiscal_year: int,
    *,
    output_dir: Path,
    page_size: int,
    supplementary_round: str = "1",
    overwrite: bool = False,
) -> BudgetCollectionResult:
    partition = budget_partition(output_dir, dataset.dataset_id, fiscal_year, ministry.code)
    existing = sorted(partition.glob("page_*.json"))
    if existing and not overwrite:
        record_count, total_count, complete = _page_metadata(existing)
        if not complete:
            raise ValueError(
                f"미완료 원본 파티션입니다. 확인 후 --overwrite가 필요합니다: {partition}"
            )
        return BudgetCollectionResult(
            dataset.dataset_id,
            ministry.code,
            ministry.name,
            fiscal_year,
            "skipped",
            len(existing),
            record_count,
            total_count,
        )

    if overwrite:
        for path in existing:
            path.unlink()

    logical = {
        "year": fiscal_year,
        "ministry": ministry.name,
        "ministry_code": ministry.code,
        "execution_month": None,
        "supplementary_round": supplementary_round,
        "account_code": None,
    }
    params = dataset.build_params(logical)
    paths = client.collect_pages(
        dataset,
        output_dir=partition,
        params=params,
        page_size=page_size,
    )
    record_count, total_count, complete = _page_metadata(paths)
    status = "no_data" if record_count == 0 else "success"
    if not complete and status != "no_data":
        raise ValueError(f"수집 완료 여부를 확인할 수 없습니다: {partition}")
    return BudgetCollectionResult(
        dataset.dataset_id,
        ministry.code,
        ministry.name,
        fiscal_year,
        status,
        len(paths),
        record_count,
        total_count,
    )


def build_budget_summary(results: list[BudgetCollectionResult]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    dataset_record_counts: dict[str, int] = {}
    for result in results:
        status_counts[result.status] = status_counts.get(result.status, 0) + 1
        dataset_record_counts[result.dataset_id] = (
            dataset_record_counts.get(result.dataset_id, 0) + result.record_count
        )
    return {
        "combination_count": len(results),
        "status_counts": status_counts,
        "record_count": sum(result.record_count for result in results),
        "file_count": sum(result.file_count for result in results),
        "dataset_record_counts": dataset_record_counts,
        "failures": [asdict(result) for result in results if result.status == "failure"],
    }
