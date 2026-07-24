from __future__ import annotations

import re
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
    top_level_type: str

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


def _looks_like_result_code(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z]+-?\d{3,}", value.strip()))


def _result_from_mapping(node: dict[str, Any]) -> tuple[str | None, str | None]:
    code_keys = (
        "CODE",
        "code",
        "RESULT_CODE",
        "resultCode",
        "result_code",
    )
    message_keys = (
        "MESSAGE",
        "message",
        "RESULT_MESSAGE",
        "resultMessage",
        "result_message",
        "RESULT_MSG",
        "resultMsg",
    )

    code = next((node.get(key) for key in code_keys if node.get(key) not in (None, "")), None)
    message = next(
        (node.get(key) for key in message_keys if node.get(key) not in (None, "")),
        None,
    )
    if code is not None or message is not None:
        return (
            str(code) if code is not None else None,
            str(message) if message is not None else None,
        )
    return None, None


def _find_result(node: Any) -> tuple[str | None, str | None]:
    if isinstance(node, str):
        value = node.strip()
        if _looks_like_result_code(value):
            return value, None
        return None, None

    if isinstance(node, dict):
        direct_code, direct_message = _result_from_mapping(node)
        if direct_code is not None or direct_message is not None:
            return direct_code, direct_message

        for key in ("RESULT", "result", "Result"):
            if key not in node:
                continue
            code, message = _find_result(node[key])
            if code is not None or message is not None:
                return code, message

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


def _is_direct_record_list(node: list[Any]) -> bool:
    if not node or not all(isinstance(item, dict) for item in node):
        return False

    wrapper_keys = {
        "RESULT",
        "result",
        "Result",
        "CODE",
        "code",
        "MESSAGE",
        "message",
        "row",
        "rows",
        "item",
        "items",
        "list_total_count",
        "total_count",
        "totalCount",
        "totalCnt",
    }
    return not any(wrapper_keys.intersection(item.keys()) for item in node)


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
        if _is_direct_record_list(node):
            return [dict(item) for item in node]
        for value in node:
            records = _find_records(value)
            if records:
                return records
    return []


def _select_service_node(payload: Any, service_name: str | None) -> tuple[str | None, Any]:
    if isinstance(payload, dict):
        if service_name and service_name in payload:
            return service_name, payload[service_name]
        if len(payload) == 1:
            only_key = next(iter(payload))
            return str(only_key), payload[only_key]
        return service_name, payload

    if isinstance(payload, list):
        if service_name:
            for item in payload:
                if isinstance(item, dict) and service_name in item:
                    return service_name, item[service_name]
        if len(payload) == 1:
            item = payload[0]
            if isinstance(item, dict) and len(item) == 1:
                only_key = next(iter(item))
                return str(only_key), item[only_key]
            return service_name, item
        return service_name, payload

    return service_name, payload


def _top_level_keys(payload: Any) -> tuple[str, ...]:
    if isinstance(payload, dict):
        return tuple(str(key) for key in payload.keys())
    if isinstance(payload, list):
        keys: list[str] = []
        for index, item in enumerate(payload[:20]):
            if isinstance(item, dict) and len(item) == 1:
                keys.append(str(next(iter(item))))
            else:
                keys.append(f"[{index}]")
        return tuple(keys)
    return ()


def parse_api_payload(payload: Any, service_name: str | None = None) -> ParsedResponse:
    if not isinstance(payload, (dict, list)):
        raise ValueError("API JSON 최상위는 객체 또는 배열이어야 합니다.")

    selected_name, node = _select_service_node(payload, service_name)
    result_code, result_message = _find_result(node)
    return ParsedResponse(
        service_name=selected_name,
        records=_find_records(node),
        total_count=_find_total_count(node),
        result_code=result_code,
        result_message=result_message,
        top_level_keys=_top_level_keys(payload),
        top_level_type="object" if isinstance(payload, dict) else "array",
    )
