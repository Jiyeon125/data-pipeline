from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParsedResponse:
    service_name: str | None
    records: list[dict[str, Any]]
    total_count: int | None
    result_code: str | None
    result_message: str | None
    top_level_keys: tuple[str, ...]

    @property
    def is_success(self) -> bool:
        if self.result_code is None:
            return True
        return self.result_code.replace("-", "").endswith("000")

    @property
    def is_no_data(self) -> bool:
        if self.result_code is None:
            return False
        return self.result_code.replace("-", "").endswith("200")


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _find_result(node: Any) -> tuple[str | None, str | None]:
    if isinstance(node, dict):
        for key in ("RESULT", "result", "Result"):
            value = node.get(key)
            if isinstance(value, dict):
                code = value.get("CODE") or value.get("code")
                message = value.get("MESSAGE") or value.get("message")
                return (
                    str(code) if code is not None else None,
                    str(message) if message is not None else None,
                )
        for value in node.values():
            code, message = _find_result(value)
            if code is not None or message is not None:
                return code, message
    elif isinstance(node, list):
        for value in node:
            code, message = _find_result(value)
            if code is not None or message is not None:
                return code, message
    return None, None


def _find_total_count(node: Any) -> int | None:
    count_keys = {
        "list_total_count",
        "total_count",
        "totalCount",
        "totalCnt",
        "total",
    }
    if isinstance(node, dict):
        for key, value in node.items():
            if key in count_keys:
                parsed = _to_int(value)
                if parsed is not None:
                    return parsed
        for value in node.values():
            parsed = _find_total_count(value)
            if parsed is not None:
                return parsed
    elif isinstance(node, list):
        for value in node:
            parsed = _find_total_count(value)
            if parsed is not None:
                return parsed
    return None


def _find_records(node: Any) -> list[dict[str, Any]]:
    if isinstance(node, dict):
        for key in ("row", "rows", "item", "items"):
            value = node.get(key)
            if isinstance(value, list) and all(isinstance(row, dict) for row in value):
                return value
            if isinstance(value, dict):
                nested = value.get("item")
                if isinstance(nested, list) and all(isinstance(row, dict) for row in nested):
                    return nested
                if isinstance(nested, dict):
                    return [nested]
        for value in node.values():
            records = _find_records(value)
            if records:
                return records
    elif isinstance(node, list):
        for value in node:
            records = _find_records(value)
            if records:
                return records
    return []


def _select_service_node(
    payload: dict[str, Any], service_name: str | None
) -> tuple[str | None, Any]:
    if service_name and service_name in payload:
        return service_name, payload[service_name]
    if len(payload) == 1:
        only_key = next(iter(payload))
        return str(only_key), payload[only_key]
    return service_name, payload


def parse_api_payload(
    payload: dict[str, Any], service_name: str | None = None
) -> ParsedResponse:
    selected_name, node = _select_service_node(payload, service_name)
    result_code, result_message = _find_result(node)
    return ParsedResponse(
        service_name=selected_name,
        records=_find_records(node),
        total_count=_find_total_count(node),
        result_code=result_code,
        result_message=result_message,
        top_level_keys=tuple(str(key) for key in payload.keys()),
    )
