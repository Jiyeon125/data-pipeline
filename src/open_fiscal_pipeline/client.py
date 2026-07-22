from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .config import Settings


class OpenFiscalClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.Client(timeout=settings.timeout_seconds)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "OpenFiscalClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def request_page(self, page_index: int = 1, **params: Any) -> dict[str, Any]:
        query = {
            self.settings.api_key_param: self.settings.api_key,
            self.settings.page_index_param: page_index,
            self.settings.page_size_param: self.settings.page_size,
            **params,
        }
        response = self.client.get(self.settings.api_url, params=query)
        response.raise_for_status()

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            preview = response.text[:500]
            raise ValueError(f"JSON 응답이 아닙니다: {preview}") from exc

        if not isinstance(payload, dict):
            raise ValueError("최상위 API 응답이 JSON 객체가 아닙니다.")
        return payload

    def smoke_test(self) -> dict[str, Any]:
        started = datetime.now(UTC)
        payload = self.request_page(page_index=1)
        return {
            "requested_at": started.isoformat(),
            "api_url": self.settings.api_url,
            "top_level_keys": list(payload.keys()),
            "payload": payload,
        }

    def collect_pages(
        self,
        output_dir: Path,
        max_pages: int = 1,
        **params: Any,
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []

        for page_index in range(1, max_pages + 1):
            payload = self.request_page(page_index=page_index, **params)
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            path = output_dir / f"page_{page_index:04d}_{timestamp}.json"
            path.write_text(
                json.dumps(
                    {
                        "metadata": {
                            "requested_at": datetime.now(UTC).isoformat(),
                            "api_url": self.settings.api_url,
                            "page_index": page_index,
                            "page_size": self.settings.page_size,
                            "params": params,
                        },
                        "response": payload,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            saved.append(path)
            time.sleep(self.settings.request_interval_seconds)

        return saved
