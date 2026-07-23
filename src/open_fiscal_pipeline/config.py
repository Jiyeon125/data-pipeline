from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    api_key: str
    api_key_param: str
    page_index_param: str
    page_size_param: str
    page_size: int
    request_interval_seconds: float
    timeout_seconds: float

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        api_key = os.environ.get("OPEN_FISCAL_API_KEY", "").strip()
        if not api_key:
            raise ValueError("OPEN_FISCAL_API_KEY가 비어 있습니다. .env 파일을 확인하세요.")

        return cls(
            api_key=api_key,
            api_key_param=os.getenv("OPEN_FISCAL_API_KEY_PARAM", "key").strip(),
            page_index_param=os.getenv("OPEN_FISCAL_PAGE_INDEX_PARAM", "pIndex").strip(),
            page_size_param=os.getenv("OPEN_FISCAL_PAGE_SIZE_PARAM", "pSize").strip(),
            page_size=int(os.getenv("OPEN_FISCAL_PAGE_SIZE", "1000")),
            request_interval_seconds=float(
                os.getenv("OPEN_FISCAL_REQUEST_INTERVAL_SECONDS", "0.4")
            ),
            timeout_seconds=float(
                os.getenv("OPEN_FISCAL_TIMEOUT", os.getenv("OPEN_FISCAL_TIMEOUT_SECONDS", "30"))
            ),
        )


def load_yaml(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {config_path}")

    with config_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"YAML 최상위는 객체여야 합니다: {config_path}")
    return data
