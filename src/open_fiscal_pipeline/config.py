from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    api_key: str
    api_url: str
    api_key_param: str
    response_format: str
    page_index_param: str
    page_size_param: str
    page_size: int
    request_interval_seconds: float
    timeout_seconds: float

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        api_key = os.getenv("OPEN_FISCAL_API_KEY", "").strip()
        api_url = os.getenv("OPEN_FISCAL_API_URL", "").strip()
        if not api_key:
            raise ValueError("OPEN_FISCAL_API_KEY가 비어 있습니다. .env 파일을 확인하세요.")
        if not api_url:
            raise ValueError("OPEN_FISCAL_API_URL이 비어 있습니다. 데이터셋 요청주소를 입력하세요.")

        return cls(
            api_key=api_key,
            api_url=api_url,
            api_key_param=os.getenv("OPEN_FISCAL_API_KEY_PARAM", "key").strip(),
            response_format=os.getenv("OPEN_FISCAL_RESPONSE_FORMAT", "json").strip(),
            page_index_param=os.getenv("OPEN_FISCAL_PAGE_INDEX_PARAM", "pIndex").strip(),
            page_size_param=os.getenv("OPEN_FISCAL_PAGE_SIZE_PARAM", "pSize").strip(),
            page_size=int(os.getenv("OPEN_FISCAL_PAGE_SIZE", "1000")),
            request_interval_seconds=float(
                os.getenv("OPEN_FISCAL_REQUEST_INTERVAL_SECONDS", "0.4")
            ),
            timeout_seconds=float(os.getenv("OPEN_FISCAL_TIMEOUT_SECONDS", "30")),
        )
