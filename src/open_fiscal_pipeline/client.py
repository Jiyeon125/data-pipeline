from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .config import DatasetConfig, Settings
from .response import ParsedResponse, parse_api_payload


class OpenFiscalError(RuntimeError):
    """열린재정 호출 또는 응답 검증 오류입니다."""


@dataclass(frozen=True)
class APIPage:
    page_index: int
    requested_at: str
    payload: Any
    parsed: ParsedResponse


class OpenFiscalClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.client = httpx.Client(
            timeout=settings.timeout_seconds,
            transport=transport,
            follow_redirects=True,
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "OpenFiscalClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def request_page(
        self,
        dataset: DatasetConfig,
        *,
        page_index: int = 1,
        page_size: int | None = None,
        params: dict[str, Any] | None = None,
    ) -> APIPage:
        if dataset.source_type != "api" or not dataset.url:
            raise OpenFiscalError(f"API 데이터셋이 아닙니다: {dataset.dataset_id}")

        actual_page_size = page_size or self.settings.page_size
        if not 1 <= actual_page_size <= 1000:
            raise OpenFiscalError("페이지 크기는 1~1000이어야 합니다.")

        query: dict[str, Any] = {
            "Key": self.settings.api_key,
            "Type": "json",
            "pIndex": page_index,
            "pSize": actual_page_size,
        }
        query.update(
            {
                key: value
                for key, value in (params or {}).items()
                if value not in (None, "")
            }
        )
        requested_at = datetime.now(UTC).isoformat()

        try:
            response = self.client.get(dataset.url, params=query)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            preview = exc.response.text[:300].replace(self.settings.api_key, "***")
            raise OpenFiscalError(
                f"HTTP {exc.response.status_code} 응답: {preview}"
            ) from exc
        except httpx.HTTPError as exc:
            raise OpenFiscalError(f"API 연결 실패: {type(exc).__name__}") from exc

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            preview = response.text[:300].replace(self.settings.api_key, "***")
            raise OpenFiscalError(f"JSON 응답이 아닙니다: {preview}") from exc

        if not isinstance(payload, (dict, list)):
            raise OpenFiscalError("최상위 API 응답이 JSON 객체 또는 배열이 아닙니다.")

        try:
            parsed = parse_api_payload(payload, dataset.service_name)
        except ValueError as exc:
            raise OpenFiscalError(str(exc)) from exc

        if not parsed.is_success and not parsed.is_no_data:
            raise OpenFiscalError(
                f"API 오류 {parsed.result_code or 'UNKNOWN'}: "
                f"{parsed.result_message or '메시지 없음'}"
            )

        return APIPage(
            page_index=page_index,
            requested_at=requested_at,
            payload=payload,
            parsed=parsed,
        )

    def collect_pages(
        self,
        dataset: DatasetConfig,
        *,
        output_dir: Path,
        params: dict[str, Any],
        max_pages: int | None = None,
        page_size: int | None = None,
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        actual_page_size = page_size or self.settings.page_size
        saved: list[Path] = []
        page_index = 1

        while max_pages is None or page_index <= max_pages:
            page = self.request_page(
                dataset,
                page_index=page_index,
                page_size=actual_page_size,
                params=params,
            )
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            path = output_dir / f"page_{page_index:04d}_{timestamp}.json"
            path.write_text(
                json.dumps(
                    {
                        "metadata": {
                            "requested_at": page.requested_at,
                            "dataset_id": dataset.dataset_id,
                            "dataset_name": dataset.name,
                            "api_url": dataset.url,
                            "page_index": page_index,
                            "page_size": actual_page_size,
                            "params": params,
                            "record_count": len(page.parsed.records),
                            "total_count": page.parsed.total_count,
                            "result_code": page.parsed.result_code,
                            "top_level_type": page.parsed.top_level_type,
                        },
                        "response": page.payload,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            saved.append(path)

            if page.parsed.is_no_data or not page.parsed.records:
                break
            if (
                page.parsed.total_count is not None
                and page_index * actual_page_size >= page.parsed.total_count
            ):
                break

            page_index += 1
            time.sleep(self.settings.request_interval_seconds)

        return saved
