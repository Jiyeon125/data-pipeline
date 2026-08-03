from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import math
import os
import re
import statistics
import time
from collections import Counter
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import fitz
import httpx
import pandas as pd
import permissive_local_parser_pilot as local_parser
import yaml
from PIL import Image

from performance_pipeline.llm_harness import _load_project_environment, _numeric_comparison_equal
from performance_pipeline.pdf_reconciliation import (
    _configure_pytesseract,
    ocr_page_text,
    printed_page_number,
)

YEARS = (2022, 2023, 2024)
DEFAULT_MINISTRIES = ("019", "075", "102", "162")
KEY_COLUMNS = (
    "ministry_code",
    "fiscal_year",
    "document_type",
    "source_file",
    "source_pdf_page",
)


def _compact(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", value)


def _page_number(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    match = re.search(r"(?:PDF\s*p\.?\s*)?(\d+)", str(value), re.IGNORECASE)
    return int(match.group(1)) if match else None


def _manual_page_numbers(value: Any) -> tuple[int | None, int | None]:
    if value is None or pd.isna(value):
        return None, None
    text = str(value)
    pdf = re.search(r"PDF\s*p\.?\s*(\d+)", text, re.IGNORECASE)
    printed = re.search(r"(?:문서|책자)\s*p\.?\s*(\d+)", text, re.IGNORECASE)
    return (
        int(pdf.group(1)) if pdf else _page_number(text),
        int(printed.group(1)) if printed else None,
    )


def _optional_int(value: Any) -> int | None:
    return None if value is None or pd.isna(value) or value == "" else int(value)


def _expected_value_visible(expected: str | None, source: str) -> bool:
    return bool(expected) and _compact(expected) in _compact(source)


def _markers(document_type: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if document_type == "PLAN":
        return ("프로그램성과지표현황",), ("성과목표체계별예산현황",)
    return ("성과달성도현황",), (
        "성과목표관리체계별예결산현황",
        "성과목표관리체계별예산결산현황",
    )


def _text_bounds(page_texts: list[str], document_type: str) -> tuple[int, int] | None:
    start_markers, end_markers = _markers(document_type)
    compact = [_compact(text) for text in page_texts]
    minimum_page = max(1, len(compact) // 2)
    starts = [
        index + 1
        for index, text in enumerate(compact)
        if index + 1 >= minimum_page and any(marker in text for marker in start_markers)
    ]
    if not starts:
        return None
    start = starts[0]
    ends = [
        index + 1
        for index, text in enumerate(compact)
        if index + 1 > start and any(marker in text for marker in end_markers)
    ]
    return (start, ends[0]) if ends else None


def _ocr_page_token(text: str, marker: str) -> int | None:
    for line in text.splitlines():
        if marker not in _compact(line):
            continue
        tokens = re.findall(r"[0-9OISLGQ]{2,4}", line.upper())
        if not tokens:
            continue
        translated = tokens[-1].translate(str.maketrans("OISLGQ", "015169"))
        if translated.isdigit():
            return int(translated)
    return None


def _ocr_printed_page_offset(pdf_path: Path) -> int:
    offsets: list[int] = []
    with fitz.open(pdf_path) as document:
        page_count = len(document)
    for pdf_page in (15, 20, 25, 30, 35):
        if pdf_page > page_count:
            break
        text = ocr_page_text(pdf_path, pdf_page - 1, dpi=100)
        if match := re.search(r"-\s*(\d+)\s*-", text[:800]):
            offsets.append(pdf_page - int(match.group(1)))
        if len(offsets) >= 2:
            break
    if not offsets:
        raise RuntimeError(f"OCR 문서의 PDF-인쇄 페이지 오프셋을 찾지 못했습니다: {pdf_path}")
    return int(statistics.median(offsets))


def _ocr_bounds(pdf_path: Path, document_type: str) -> tuple[int, int]:
    if document_type != "PLAN":
        raise RuntimeError(f"보고서 별첨 시작 표제를 찾지 못했습니다: {pdf_path}")
    with fitz.open(pdf_path) as document:
        page_count = len(document)
    toc_text = "\n".join(
        ocr_page_text(pdf_path, index, dpi=150) for index in range(min(15, page_count))
    )
    printed_start = _ocr_page_token(toc_text, "프로그램성과지표현황")
    if printed_start is None:
        raise RuntimeError(f"목차 OCR에서 별첨1 인쇄 페이지를 찾지 못했습니다: {pdf_path}")
    expected = printed_start + _ocr_printed_page_offset(pdf_path)
    start = None
    for page_number in range(max(1, expected - 3), min(page_count, expected + 3) + 1):
        text = ocr_page_text(pdf_path, page_number - 1, dpi=120)
        if "프로그램성과지표현황" in _compact(text):
            start = page_number
            break
    if start is None:
        raise RuntimeError(f"목차 기반 위치에서 별첨1을 찾지 못했습니다: {pdf_path}")
    for page_number in range(start + 1, min(page_count, start + 20) + 1):
        text = ocr_page_text(pdf_path, page_number - 1, dpi=120)
        if "성과목표체계별예산현황" in _compact(text):
            return start, page_number
    raise RuntimeError(f"별첨2 시작 페이지를 찾지 못했습니다: {pdf_path}")


def locate_annex(pdf_path: Path, document_type: str) -> tuple[int, int, str]:
    with fitz.open(pdf_path) as document:
        texts = [page.get_text("text") for page in document]
    if bounds := _text_bounds(texts, document_type):
        return *bounds, "TEXT_HEADING"
    start, end = _ocr_bounds(pdf_path, document_type)
    return start, end, "TOC_AND_WINDOW_OCR"


def _text_signal_pages(pdf_path: Path, document_type: str) -> list[int]:
    with fitz.open(pdf_path) as document:
        compact = [_compact(page.get_text("text")) for page in document]
    if document_type == "PLAN":
        return [
            index
            for index, text in enumerate(compact, start=1)
            if "성과지표및목표치" in text and "프로그램목표별성과지표" in text
        ]
    return [
        index
        for index, text in enumerate(compact, start=1)
        if all(label in text for label in ("성과지표", "목표", "실적"))
        and any(label in text for label in ("달성률", "달성도"))
    ]


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_ministries(root: Path) -> dict[str, str]:
    config = yaml.safe_load((root / "configs/ministries.yaml").read_text(encoding="utf-8"))
    return {str(row["code"]).zfill(3): str(row["name"]) for row in config["ministries"]}


def _candidate_key(row: dict[str, Any]) -> tuple[str, int, str, str, int]:
    return (
        str(row["ministry_code"]).zfill(3),
        int(row["fiscal_year"]),
        str(row["document_type"]),
        str(row["source_file"]),
        int(float(row["source_pdf_page"])),
    )


def _add_candidate(
    candidates: dict[tuple[str, int, str, str, int], dict[str, Any]],
    row: dict[str, Any],
    reason: str,
) -> None:
    key = _candidate_key(row)
    if key not in candidates:
        candidates[key] = {
            "ministry_code": key[0],
            "fiscal_year": key[1],
            "document_type": key[2],
            "source_file": key[3],
            "source_pdf_page": key[4],
            "selection_reasons": set(),
        }
    candidates[key]["selection_reasons"].add(reason)


def build_candidate_manifest(
    root: Path,
    output_dir: Path,
    ministry_codes: tuple[str, ...] = DEFAULT_MINISTRIES,
) -> list[dict[str, Any]]:
    names = _load_ministries(root)
    raw_dir = root / "data/raw/performance_docs"
    candidates: dict[tuple[str, int, str, str, int], dict[str, Any]] = {}
    boundaries: list[dict[str, Any]] = []
    for code in ministry_codes:
        for year in YEARS:
            for document_type, label in (("PLAN", "계획서"), ("REPORT", "보고서")):
                source = raw_dir / f"{year}년도 성과{label}_{names[code]}.pdf"
                start, end, method = locate_annex(source, document_type)
                boundaries.append(
                    {
                        "ministry_code": code,
                        "fiscal_year": year,
                        "document_type": document_type,
                        "source_file": source.name,
                        "source_pdf_sha256": local_parser._sha256(source),
                        "annex_start_page": start,
                        "next_annex_start_page": end,
                        "candidate_page_count": end - start,
                        "selection_method": method,
                    }
                )
                for page_number in range(start, end):
                    _add_candidate(
                        candidates,
                        {
                            "ministry_code": code,
                            "fiscal_year": year,
                            "document_type": document_type,
                            "source_file": source.name,
                            "source_pdf_page": page_number,
                        },
                        "PERFORMANCE_ANNEX",
                    )
                for page_number in _text_signal_pages(source, document_type):
                    _add_candidate(
                        candidates,
                        {
                            "ministry_code": code,
                            "fiscal_year": year,
                            "document_type": document_type,
                            "source_file": source.name,
                            "source_pdf_page": page_number,
                        },
                        "PERFORMANCE_TEXT_SIGNAL",
                    )

    discovered = pd.read_parquet(
        root / "data/processed/performance/unattended_pdf/discovered_records.parquet"
    )
    for row in discovered.loc[:, list(KEY_COLUMNS) + ["routing_status"]].to_dict("records"):
        reason = (
            "PREVIOUS_LOCAL_DISCOVERY"
            if row["routing_status"] == "LOCAL_CONFIRMED"
            else "LOCAL_REVIEW_REQUIRED"
        )
        _add_candidate(candidates, row, reason)
    for row in _read_csv(root / "data/processed/performance/unattended_pdf/unresolved_queue.csv"):
        if row.get("source_pdf_page"):
            _add_candidate(candidates, row, "UNRESOLVED_QUEUE")

    pages_dir = output_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    with ExitStack() as stack:
        documents: dict[str, fitz.Document] = {}
        for index, row in enumerate(sorted(candidates.values(), key=_candidate_key), start=1):
            source = raw_dir / row["source_file"]
            if row["source_file"] not in documents:
                documents[row["source_file"]] = stack.enter_context(fitz.open(source))
            document = documents[row["source_file"]]
            page_number = int(row["source_pdf_page"])
            page_id = (
                f"v{index:03d}_{row['ministry_code']}_{row['fiscal_year']}_"
                f"{row['document_type']}_{page_number}"
            )
            page_path = pages_dir / f"{page_id}.pdf"
            with fitz.open() as page_document:
                page_document.insert_pdf(
                    document, from_page=page_number - 1, to_page=page_number - 1
                )
                page_document.save(page_path)
            text_chars = len(document[page_number - 1].get_text("text").strip())
            manifest.append(
                {
                    "page_id": page_id,
                    "stratum": "SELECTIVE_VISION_CANDIDATE",
                    **{key: row[key] for key in KEY_COLUMNS},
                    "source_pdf_sha256": local_parser._sha256(source),
                    "input_pdf": str(page_path.relative_to(root)),
                    "input_pdf_sha256": local_parser._sha256(page_path),
                    "pdf_text_chars": text_chars,
                    "selection_reasons": ";".join(sorted(row["selection_reasons"])),
                }
            )
    local_parser._write_csv(output_dir / "manifest.csv", manifest)
    local_parser._write_csv(output_dir / "annex_boundaries.csv", boundaries)
    return manifest


def _tables(payload: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            if value.get("type") == "table":
                found.append(value)
            for item in value.values():
                if isinstance(item, (dict, list)):
                    walk(item)

    walk(payload)
    return found


def structure_reasons(
    rows: list[str], document_type: str, fiscal_year: int, table_count: int
) -> list[str]:
    reasons: list[str] = []
    compact_rows = [_compact(row) for row in rows]
    if table_count == 0:
        reasons.append("NO_TABLE")
    headers = [index for index, row in enumerate(compact_rows) if "성과지표" in row]
    if not headers:
        reasons.append("INDICATOR_HEADER_MISSING")
    elif min(headers) > 3:
        reasons.append("HEADER_AFTER_DATA")
    joined = "".join(compact_rows)
    if str(fiscal_year) not in joined and str(fiscal_year)[-2:] not in joined:
        reasons.append("CURRENT_YEAR_MISSING")
    if "목표" not in joined:
        reasons.append("TARGET_LABEL_MISSING")
    if document_type == "REPORT":
        if "실적" not in joined:
            reasons.append("ACTUAL_LABEL_MISSING")
        if "달성률" not in joined:
            reasons.append("ACHIEVEMENT_RATE_LABEL_MISSING")
    if not any(re.search(r"\d", row) for row in compact_rows):
        reasons.append("NUMERIC_VALUE_MISSING")
    return reasons


def _structure_route(selection_reasons: str, reasons: list[str]) -> tuple[str, list[str]]:
    selected_by = set(selection_reasons.split(";"))
    if "PREVIOUS_LOCAL_DISCOVERY" in selected_by and "LOCAL_REVIEW_REQUIRED" not in selected_by:
        return "EXISTING_LOCAL_CONFIRMED", []
    return ("VISION_REQUIRED" if reasons else "ODL_STRUCTURE_OK"), reasons


def _needs_previous_page_context(reasons: list[str], page_text: str) -> bool:
    return "CURRENT_YEAR_MISSING" in reasons or (
        "INDICATOR_HEADER_MISSING" in reasons and "성과지표" not in _compact(page_text)
    )


def _needs_next_page_context(reasons: list[str], document_type: str) -> bool:
    return document_type == "REPORT" and bool(
        {"ACTUAL_LABEL_MISSING", "ACHIEVEMENT_RATE_LABEL_MISSING"} & set(reasons)
    )


def _render_for_vision(pdf_path: Path, output_path: Path) -> tuple[int, int, int, float | None]:
    with fitz.open(pdf_path) as document:
        page = document[0]
        source_rotation = page.rotation
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    rotation = 0
    confidence: float | None = None
    if source_rotation in {90, 270}:
        try:
            pytesseract = _configure_pytesseract()
            osd = pytesseract.image_to_osd(image, output_type=pytesseract.Output.DICT)
            confidence = float(osd.get("orientation_conf", 0.0))
            if confidence >= 2.0:
                rotation = int(osd.get("rotate", 0))
                if rotation:
                    image = image.rotate(-rotation, expand=True)
        except Exception:  # noqa: BLE001 - 방향 검출 실패는 요청 사유로 남기고 원본 방향을 보존합니다.
            confidence = None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True)
    width, height = image.size
    return width, height, rotation, confidence


def _vision_schema(fiscal_year: int) -> dict[str, Any]:
    nullable_string = {"type": ["string", "null"]}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["records"],
        "properties": {
            "records": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "program_goal_number",
                        "indicator_name",
                        "unit",
                        "fiscal_year",
                        "planned_target",
                        "actual_value",
                        "achievement_rate",
                        "source_evidence",
                    ],
                    "properties": {
                        "program_goal_number": nullable_string,
                        "indicator_name": nullable_string,
                        "unit": nullable_string,
                        "fiscal_year": {"type": "integer", "enum": [fiscal_year]},
                        "planned_target": nullable_string,
                        "actual_value": nullable_string,
                        "achievement_rate": nullable_string,
                        "source_evidence": nullable_string,
                    },
                },
            }
        },
    }


def _merge_compatible_records(
    records: list[dict[str, Any]], fiscal_year: int
) -> tuple[list[dict[str, Any]], int, int]:
    fields = (
        "program_goal_number",
        "indicator_name",
        "unit",
        "planned_target",
        "actual_value",
        "achievement_rate",
    )
    merged: list[dict[str, Any]] = []
    positions: dict[tuple[str, str, int], int] = {}
    merged_count = 0
    conflict_count = 0
    for record in records:
        indicator = _compact(str(record.get("indicator_name") or ""))
        goal = _compact(str(record.get("program_goal_number") or ""))
        year = _optional_int(record.get("fiscal_year"))
        if not indicator or year != fiscal_year:
            merged.append(record)
            continue
        key = (goal, indicator, year)
        if key not in positions:
            positions[key] = len(merged)
            merged.append(record)
            continue
        current = merged[positions[key]]
        conflicts = any(
            current.get(field) not in (None, "")
            and record.get(field) not in (None, "")
            and _compact(str(current[field])) != _compact(str(record[field]))
            for field in fields
        )
        if conflicts:
            conflict_count += 1
            merged.append(record)
            continue
        for field in fields:
            if current.get(field) in (None, "") and record.get(field) not in (None, ""):
                current[field] = record[field]
        evidence = [
            value
            for value in (current.get("source_evidence"), record.get("source_evidence"))
            if value not in (None, "")
        ]
        current["source_evidence"] = " / ".join(dict.fromkeys(map(str, evidence))) or None
        merged_count += 1
    return merged, merged_count, conflict_count


def _request_entry(
    row: dict[str, Any], image_path: Path, model: str, max_output_tokens: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    prompt = (
        "성과계획서·성과보고서의 표 이미지에서 보이는 값만 추출하세요. 추정하거나 "
        "누락값을 만들지 말고 불명확하면 null을 반환하세요. 모든 지표를 표의 연도 열과 "
        "목표·실적·달성률 행에 맞춰 분리하고, source_evidence에는 해당 지표와 값이 함께 "
        "보이는 짧은 원문을 적으세요. 요청 회계연도 열로 명확히 귀속되는 레코드만 "
        "반환하고, 연도를 확인할 수 없으면 해당 레코드를 반환하지 마세요. "
        f"문서유형={row['document_type']}, 회계연도={row['fiscal_year']}, "
        f"원본페이지={row['source_pdf_page']}, 로컬실패={row['structure_reasons']}"
    )
    image_paths = [
        *(
            [Path(str(row["previous_context_image_path"]))]
            if row.get("previous_context_image_path")
            else []
        ),
        image_path,
        *(
            [Path(str(row["next_context_image_path"]))]
            if row.get("next_context_image_path")
            else []
        ),
    ]
    if row.get("previous_context_image_path"):
        prompt += (
            " 첫 이미지는 직전 페이지의 머리글·연도 문맥이며 그 다음 이미지가 추출 대상입니다."
        )
    if row.get("next_context_image_path"):
        prompt += (
            " 마지막 이미지는 다음 페이지에 이어지는 표 문맥이며 추출 대상 페이지에서 시작된 "
            "같은 행만 연결하세요."
        )
    if row.get("previous_context_image_path") or row.get("next_context_image_path"):
        prompt += (
            " 문맥 이미지에서 새로 시작된 다른 지표는 반환하지 마세요. 지표명이 페이지 경계에서 "
            "끊기면 같은 행의 글자를 이어 붙여 전체 명칭을 반환하세요."
        )
    image_content = [
        {
            "type": "input_image",
            "image_url": "data:image/png;base64,"
            + base64.b64encode(path.read_bytes()).decode("ascii"),
            "detail": "original",
        }
        for path in image_paths
    ]
    request = {
        "custom_id": f"vision-{row['page_id']}",
        "method": "POST",
        "url": "/v1/responses",
        "body": {
            "model": model,
            "store": False,
            "reasoning": {"effort": "low"},
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        *image_content,
                    ],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "performance_page_extraction",
                    "strict": True,
                    "schema": _vision_schema(int(row["fiscal_year"])),
                }
            },
            "max_output_tokens": max_output_tokens,
        },
    }
    index = {
        **row,
        "image_path": str(image_path),
        "request_id": request["custom_id"],
        "prompt_char_count": len(prompt),
    }
    return request, index


def _pilot_sample(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    def add(row: dict[str, Any]) -> None:
        page_id = str(row["page_id"])
        if page_id not in selected_ids and len(selected) < limit:
            selected.append(row)
            selected_ids.add(page_id)

    for row in sorted(rows, key=lambda item: str(item["page_id"])):
        if "UNRESOLVED_QUEUE" in str(row["selection_reasons"]):
            add(row)
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        if str(row["page_id"]) in selected_ids:
            continue
        first_reason = str(row["structure_reasons"]).split(";", 1)[0]
        key = (
            str(row["ministry_code"]),
            str(row["document_type"]),
            first_reason,
        )
        groups.setdefault(key, []).append(row)
    while len(selected) < min(limit, len(rows)):
        added = False
        for key in sorted(groups):
            if groups[key]:
                add(groups[key].pop(0))
                added = True
        if not added:
            break
    return selected


def _response_output_text(payload: dict[str, Any]) -> str:
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                return str(content["text"])
    raise RuntimeError("Responses API 응답에 output_text가 없습니다.")


def _prepare_sync_requests(request_path: Path, max_output_tokens: int) -> list[dict[str, Any]]:
    requests = [
        json.loads(line)
        for line in request_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for request in requests:
        request["body"]["max_output_tokens"] = min(
            int(request["body"].get("max_output_tokens", max_output_tokens)), max_output_tokens
        )
    return requests


def _sync_cost_usd(usage: dict[str, Any], input_price: float, output_price: float) -> float:
    return (
        int(usage.get("input_tokens", 0)) * input_price
        + int(usage.get("output_tokens", 0)) * output_price
    ) / 1_000_000


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _attempt_max_cost_usd(
    index: dict[str, str], output_tokens: int, input_price: float, output_price: float
) -> float:
    image_tokens = int(index["image_patch_tokens"]) + int(
        index.get("previous_context_image_patch_tokens") or 0
    )
    text_tokens = math.ceil(int(index["prompt_char_count"]) / 2)
    # ponytail: 1,500-token protocol overhead; replace with measured p99 after a larger pilot.
    return (
        1.1
        * ((image_tokens + text_tokens + 1500) * input_price + output_tokens * output_price)
        / 1_000_000
    )


def _billed_cost_usd(
    attempt_records: list[dict[str, Any]], saved_records: list[dict[str, Any]]
) -> float:
    attempted_ids = {str(row["custom_id"]) for row in attempt_records}
    return sum(
        float(row.get("cost_usd", row.get("cost_reserve_usd", 0))) for row in attempt_records
    ) + sum(
        float(row["cost_usd"])
        for row in saved_records
        if row.get("ok") and str(row["custom_id"]) not in attempted_ids
    )


def run_sync_pilot(
    root: Path,
    output_dir: Path,
    *,
    max_approved_cost_usd: float,
    execute: bool,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    if not execute:
        raise RuntimeError("동기 API 실행에는 --sync-pilot-execute가 필요합니다.")
    root = root.resolve()
    output_dir = output_dir.resolve()
    _load_project_environment(root)
    config = yaml.safe_load((root / "configs/llm.yaml").read_text(encoding="utf-8"))
    if not config["llm"].get("api_execution_allowed", False):
        raise RuntimeError("configs/llm.yaml의 api_execution_allowed가 false입니다.")
    api_key = os.getenv(str(config["llm"]["api_key_env"]))
    if not api_key:
        raise RuntimeError("OpenAI API 키 환경변수가 없습니다.")
    model = str(config["llm"]["default_model"])
    price = config["harness"]["pricing_usd_per_million"][model]
    summary_path = output_dir / "selective_vision_summary.json"
    dry_run = json.loads(summary_path.read_text(encoding="utf-8"))
    max_output_tokens = int(config["harness"]["max_output_tokens"])
    requests = _prepare_sync_requests(output_dir / "vision_pilot_requests.jsonl", max_output_tokens)
    request_index = {
        row["request_id"]: row
        for row in csv.DictReader(
            (output_dir / "vision_pilot_index.csv").open(encoding="utf-8-sig", newline="")
        )
    }
    maximum_input_tokens = int(dry_run["pilot_image_tokens_estimate"]) + int(
        dry_run["pilot_text_tokens_estimate"]
    )
    maximum_output_tokens = sum(int(row["body"]["max_output_tokens"]) for row in requests)
    maximum_cost = (
        1.1
        * (
            maximum_input_tokens * float(price["input"])
            + maximum_output_tokens * float(price["output"])
        )
        / 1_000_000
    )
    if maximum_cost > max_approved_cost_usd:
        raise RuntimeError(
            f"안전여유 포함 최대 예상비용 ${maximum_cost:.4f}가 승인 상한을 넘습니다."
        )
    sync_request_path = output_dir / "sync_requests.jsonl"
    sync_request_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in requests),
        encoding="utf-8",
    )
    response_dir = output_dir / "sync_responses"
    response_dir.mkdir(parents=True, exist_ok=True)
    attempt_dir = output_dir / "sync_attempts"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    owns_client = client is None
    client = client or httpx.Client(
        base_url="https://api.openai.com",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=float(config["llm"]["request_timeout_seconds"]),
    )
    completed: list[dict[str, Any]] = []
    attempt_records = [
        json.loads(path.read_text(encoding="utf-8")) for path in attempt_dir.glob("*.json")
    ]
    saved_records = [
        json.loads(path.read_text(encoding="utf-8")) for path in response_dir.glob("*.json")
    ]
    cumulative_cost = _billed_cost_usd(attempt_records, saved_records)
    started = time.perf_counter()
    try:
        for position, request in enumerate(requests, start=1):
            custom_id = str(request["custom_id"])
            response_path = response_dir / f"{custom_id}.json"
            if response_path.is_file():
                saved = json.loads(response_path.read_text(encoding="utf-8"))
                if saved.get("ok"):
                    completed.append(saved)
                    continue
            previous_attempts = sorted(attempt_dir.glob(f"{custom_id}__*.json"))
            next_output_tokens = int(request["body"]["max_output_tokens"])
            if previous_attempts:
                previous = json.loads(previous_attempts[-1].read_text(encoding="utf-8"))
                next_output_tokens = int(
                    previous.get("next_max_output_tokens", request["body"]["max_output_tokens"])
                )
            parsed: dict[str, Any] | None = None
            record: dict[str, Any] | None = None
            duplicate_merged_count = 0
            duplicate_conflict_count = 0
            for output_limit in dict.fromkeys((next_output_tokens, max(next_output_tokens, 3600))):
                attempt_ceiling = _attempt_max_cost_usd(
                    request_index[custom_id],
                    output_limit,
                    float(price["input"]),
                    float(price["output"]),
                )
                if cumulative_cost + attempt_ceiling > max_approved_cost_usd:
                    raise RuntimeError(
                        f"{custom_id} 호출 전 비용 상한 점검 실패: "
                        f"${cumulative_cost + attempt_ceiling:.4f} > ${max_approved_cost_usd:.4f}"
                    )
                body = {**request["body"], "max_output_tokens": output_limit}
                response: httpx.Response | None = None
                for retry in range(int(config["llm"].get("max_retries", 2)) + 1):
                    response = client.post("/v1/responses", json=body)
                    if response.status_code not in {429, 500, 502, 503, 504} or retry >= int(
                        config["llm"].get("max_retries", 2)
                    ):
                        break
                    time.sleep(2**retry)
                assert response is not None
                received_at = datetime.now(UTC).isoformat()
                payload = response.json() if response.is_success else None
                usage = (payload or {}).get("usage") or {}
                cost = _sync_cost_usd(usage, float(price["input"]), float(price["output"]))
                cumulative_cost += cost
                parse_error = None
                if response.is_success:
                    try:
                        parsed = json.loads(_response_output_text(payload))
                        if not isinstance(parsed.get("records"), list):
                            raise TypeError("records가 배열이 아닙니다.")
                        (
                            parsed["records"],
                            duplicate_merged_count,
                            duplicate_conflict_count,
                        ) = _merge_compatible_records(
                            parsed["records"], int(request_index[custom_id]["fiscal_year"])
                        )
                    except (json.JSONDecodeError, RuntimeError, TypeError) as error:
                        parsed = None
                        parse_error = f"{type(error).__name__}: {error}"
                else:
                    parse_error = response.text[:2000]
                attempt_number = len(list(attempt_dir.glob(f"{custom_id}__*.json"))) + 1
                attempt_record = {
                    "custom_id": custom_id,
                    "attempt": attempt_number,
                    "ok": response.is_success and parsed is not None,
                    "status_code": response.status_code,
                    "received_at": received_at,
                    "max_output_tokens": output_limit,
                    "usage": usage,
                    "cost_usd": cost,
                    "parse_error": parse_error,
                    "compatible_duplicate_merged_count": duplicate_merged_count,
                    "conflicting_duplicate_group_count": duplicate_conflict_count,
                    "next_max_output_tokens": 3600
                    if parsed is None and output_limit < 3600
                    else None,
                    "response": payload,
                }
                _write_json_atomic(
                    attempt_dir / f"{custom_id}__{attempt_number:03d}.json", attempt_record
                )
                if not response.is_success:
                    _write_json_atomic(response_path, attempt_record)
                    raise RuntimeError(f"{custom_id} 호출 실패: HTTP {response.status_code}")
                if parsed is None:
                    if output_limit < 3600:
                        continue
                    raise RuntimeError(f"{custom_id} 응답 파싱 실패: {parse_error}")
                record = {
                    "custom_id": custom_id,
                    "ok": True,
                    "status_code": response.status_code,
                    "received_at": received_at,
                    "position": position,
                    "usage": usage,
                    "cost_usd": cost,
                    "compatible_duplicate_merged_count": duplicate_merged_count,
                    "conflicting_duplicate_group_count": duplicate_conflict_count,
                    "parsed": parsed,
                    "response": payload,
                }
                _write_json_atomic(response_path, record)
                completed.append(record)
                break
            assert parsed is not None and record is not None
            print(
                f"sync-pilot {position}/{len(requests)} {custom_id} "
                f"records={len(parsed['records'])} billed=${cumulative_cost:.6f}",
                flush=True,
            )
    finally:
        if owns_client:
            client.close()
    ordered = {row["custom_id"]: row for row in completed}
    completed = [
        ordered[str(row["custom_id"])] for row in requests if str(row["custom_id"]) in ordered
    ]
    (output_dir / "sync_responses.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in completed),
        encoding="utf-8",
    )
    usage = {
        "input_tokens": sum(int(row["usage"].get("input_tokens", 0)) for row in completed),
        "output_tokens": sum(int(row["usage"].get("output_tokens", 0)) for row in completed),
    }
    run_summary = {
        "request_count": len(requests),
        "completed_count": len(completed),
        "record_count": sum(len(row["parsed"]["records"]) for row in completed),
        "compatible_duplicate_merged_count": sum(
            int(row.get("compatible_duplicate_merged_count", 0)) for row in completed
        ),
        "conflicting_duplicate_group_count": sum(
            int(row.get("conflicting_duplicate_group_count", 0)) for row in completed
        ),
        "elapsed_seconds": time.perf_counter() - started,
        "usage": usage,
        "successful_response_cost_usd": sum(float(row["cost_usd"]) for row in completed),
        "actual_or_reserved_billed_cost_usd": cumulative_cost,
        "maximum_approved_cost_usd": max_approved_cost_usd,
        "maximum_cost_with_safety_usd": maximum_cost,
        "max_output_tokens_per_request": max_output_tokens,
        "model": model,
        "store": False,
    }
    local_parser._write_json(output_dir / "sync_run_summary.json", run_summary)
    return run_summary


def evaluate_sync_pilot(
    root: Path, output_dir: Path, ministry_codes: tuple[str, ...]
) -> dict[str, Any]:
    root, output_dir = root.resolve(), output_dir.resolve()
    gate = yaml.safe_load((root / "configs/llm.yaml").read_text(encoding="utf-8"))["harness"][
        "expansion_gate"
    ]
    index = {
        row["request_id"]: row
        for row in csv.DictReader(
            (output_dir / "vision_pilot_index.csv").open(encoding="utf-8-sig", newline="")
        )
    }
    manifest = _read_csv(output_dir / "manifest.csv")
    manifest_by_page = {
        (
            str(row["ministry_code"]).zfill(3),
            int(row["fiscal_year"]),
            row["document_type"],
            row["source_file"],
            int(row["source_pdf_page"]),
        ): row
        for row in manifest
    }
    request_page_evidence: dict[str, dict[str, set[int]]] = {}
    for request_id, row in index.items():
        physical = {int(row["source_pdf_page"])}
        printed: set[int] = set()
        with fitz.open(root / row["input_pdf"]) as document:
            if page := printed_page_number(document[0].get_text("text")):
                printed.add(page)
        request_page_evidence[request_id] = {"physical": physical, "printed": printed}
    responses = [
        json.loads(line)
        for line in (output_dir / "sync_responses.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    required = {
        "program_goal_number",
        "indicator_name",
        "unit",
        "fiscal_year",
        "planned_target",
        "actual_value",
        "achievement_rate",
        "source_evidence",
    }
    candidates: dict[tuple[str, int, str], list[dict[str, Any]]] = {}
    source_by_request: dict[str, str] = {}
    grounding: list[dict[str, Any]] = []
    for response in responses:
        request_id = str(response["custom_id"])
        page = index[request_id]
        with fitz.open(root / page["input_pdf"]) as document:
            source = document[0].get_text("text")
        source += "\n" + "\n".join(
            local_parser._opendataloader_table_rows(
                output_dir / "opendataloader/raw" / f"{page['page_id']}.json"
            )
        )
        for context_column in ("previous_context_page", "next_context_page"):
            context_page = _optional_int(page.get(context_column))
            if context_page is None:
                continue
            context = manifest_by_page.get(
                (
                    str(page["ministry_code"]).zfill(3),
                    int(page["fiscal_year"]),
                    page["document_type"],
                    page["source_file"],
                    context_page,
                )
            )
            if not context:
                continue
            with fitz.open(root / context["input_pdf"]) as document:
                source += "\n" + document[0].get_text("text")
            source += "\n" + "\n".join(
                local_parser._opendataloader_table_rows(
                    output_dir / "opendataloader/raw" / f"{context['page_id']}.json"
                )
            )
        source_by_request[request_id] = source
        key = (str(page["ministry_code"]).zfill(3), int(page["fiscal_year"]), page["document_type"])
        for record_index, record in enumerate(response["parsed"]["records"], start=1):
            enriched = {
                **record,
                "request_id": request_id,
                "source_pdf_page": int(page["source_pdf_page"]),
            }
            candidates.setdefault(key, []).append(enriched)
            checks: list[bool] = []
            for field in (
                "program_goal_number",
                "indicator_name",
                "unit",
                "planned_target",
                "actual_value",
                "achievement_rate",
            ):
                value = record.get(field)
                if value in (None, ""):
                    continue
                if field in {"program_goal_number", "indicator_name"}:
                    checks.append(local_parser._partial_similarity(str(value), source) >= 0.8)
                else:
                    checks.append(_compact(str(value)) in _compact(source))
            grounding.append(
                {
                    "request_id": request_id,
                    "source_pdf_page": page["source_pdf_page"],
                    "record_index": record_index,
                    "schema_valid": required <= set(record),
                    "non_null_checked_field_count": len(checks),
                    "locally_corroborated_field_count": sum(checks),
                    "all_non_null_fields_locally_corroborated": bool(checks) and all(checks),
                }
            )

    evaluations: list[dict[str, Any]] = []
    reconciliation_paths = [
        root
        / "data/processed/performance/pdf_reconciliation/mss_performance_pdf_reconciliation.parquet",
        *sorted(
            (root / "data/processed/performance/pdf_reconciliation").glob(
                "ministry_code=*/*_performance_pdf_reconciliation.parquet"
            )
        ),
    ]
    reconciliation = pd.concat(
        [pd.read_parquet(path) for path in reconciliation_paths], ignore_index=True, sort=False
    )
    page_columns = [
        "source_indicator_id",
        "plan_source_pdf_page",
        "plan_printed_page",
        "report_source_pdf_page",
        "report_printed_page",
    ]
    gold_frame = _gold_frames(root, ministry_codes).merge(
        reconciliation[page_columns], on="source_indicator_id", how="left", validate="one_to_one"
    )
    gold_records = gold_frame.to_dict("records")
    for gold in gold_records:
        for document_type, page_column, name_column, value_columns in (
            (
                "PLAN",
                "plan_source_page",
                "indicator_name_plan",
                {"planned_target": "planned_target_raw"},
            ),
            (
                "REPORT",
                "report_source_page",
                "indicator_name_report",
                {
                    "actual_value": "actual_value_raw",
                    "achievement_rate": "official_achievement_rate_raw",
                },
            ),
        ):
            expected_name = local_parser._clean_expected(gold.get(name_column))
            manual_pdf_page, manual_printed_page = _manual_page_numbers(gold.get(page_column))
            prefix = document_type.lower()
            physical_pages = {
                page
                for page in (
                    manual_pdf_page,
                    _optional_int(gold.get(f"{prefix}_source_pdf_page")),
                )
                if page is not None
            }
            printed_pages = {
                page
                for page in (
                    manual_printed_page,
                    _optional_int(gold.get(f"{prefix}_printed_page")),
                )
                if page is not None
            }
            key = (
                str(gold["ministry_code"]).zfill(3),
                int(gold["fiscal_year"]),
                document_type,
            )
            exact_requests = [
                row
                for row in index.values()
                if str(row["ministry_code"]).zfill(3) == key[0]
                and int(row["fiscal_year"]) == key[1]
                and row["document_type"] == document_type
                and (
                    physical_pages & request_page_evidence[row["request_id"]]["physical"]
                    or printed_pages & request_page_evidence[row["request_id"]]["printed"]
                )
            ]
            if not expected_name or not exact_requests:
                continue
            request_ids = {request["request_id"] for request in exact_requests}
            nearby = [row for row in candidates.get(key, []) if row["request_id"] in request_ids]
            name_matches = [
                candidate
                for candidate in nearby
                if local_parser._partial_similarity(
                    expected_name, str(candidate.get("indicator_name") or "")
                )
                >= 0.8
            ]
            target_year_matches = [
                candidate
                for candidate in name_matches
                if _optional_int(candidate.get("fiscal_year")) == int(gold["fiscal_year"])
            ]
            best = max(
                target_year_matches or name_matches,
                key=lambda candidate: local_parser._partial_similarity(
                    expected_name, str(candidate.get("indicator_name") or "")
                ),
                default={},
            )
            similarity = max(
                (
                    local_parser._partial_similarity(
                        expected_name, str(candidate.get("indicator_name") or "")
                    )
                    for candidate in nearby
                ),
                default=0.0,
            )
            row = {
                "ministry_code": key[0],
                "fiscal_year": key[1],
                "document_type": document_type,
                "source_indicator_id": gold.get("source_indicator_id"),
                "manual_pdf_page": manual_pdf_page,
                "manual_printed_page": manual_printed_page,
                "reconciliation_source_pdf_page": _optional_int(
                    gold.get(f"{prefix}_source_pdf_page")
                ),
                "reconciliation_printed_page": _optional_int(gold.get(f"{prefix}_printed_page")),
                "matched_request_pages": ";".join(
                    str(request["source_pdf_page"]) for request in exact_requests
                ),
                "expected_indicator_name": expected_name,
                "extracted_indicator_name": best.get("indicator_name"),
                "indicator_similarity": similarity,
                "indicator_recovered": bool(name_matches),
                "target_year_record_match": bool(target_year_matches),
            }
            for field, gold_column in value_columns.items():
                expected = local_parser._clean_expected(gold.get(gold_column))
                visible_request_ids = {
                    request["request_id"]
                    for request in exact_requests
                    if _expected_value_visible(expected, source_by_request[request["request_id"]])
                }
                visible_name_matches = [
                    candidate
                    for candidate in name_matches
                    if candidate["request_id"] in visible_request_ids
                ]
                visible_target_year_matches = [
                    candidate
                    for candidate in target_year_matches
                    if candidate["request_id"] in visible_request_ids
                ]
                row[f"{field}_expected"] = expected
                row[f"{field}_extracted"] = best.get(field)
                row[f"{field}_source_visible"] = bool(visible_request_ids)
                row[f"{field}_value_recovered"] = (
                    any(
                        _numeric_comparison_equal(candidate.get(field), expected)
                        for candidate in visible_name_matches
                    )
                    if visible_request_ids
                    else None
                )
                row[f"{field}_target_year_match"] = (
                    any(
                        _numeric_comparison_equal(candidate.get(field), expected)
                        for candidate in visible_target_year_matches
                    )
                    if visible_request_ids
                    else None
                )
            evaluations.append(row)

    local_parser._write_csv(output_dir / "sync_record_grounding.csv", grounding)
    local_parser._write_csv(output_dir / "sync_gold_evaluation.csv", evaluations)
    grounding_frame, evaluation_frame = pd.DataFrame(grounding), pd.DataFrame(evaluations)

    def evaluation_values(frame: pd.DataFrame, suffix: str) -> pd.Series:
        columns = [column for column in frame if column.endswith(suffix)]
        return (
            pd.concat(
                [frame[column].dropna().astype(bool) for column in columns], ignore_index=True
            )
            if columns
            else pd.Series(dtype=bool)
        )

    recovered_values = evaluation_values(evaluation_frame, "_value_recovered")
    target_year_values = evaluation_values(evaluation_frame, "_target_year_match")
    target_outputs: list[dict[str, Any]] = []
    gold_by_key: dict[tuple[str, int, str], list[dict[str, Any]]] = {}
    for gold in gold_records:
        for document_type, name_column in (
            ("PLAN", "indicator_name_plan"),
            ("REPORT", "indicator_name_report"),
        ):
            name = local_parser._clean_expected(gold.get(name_column))
            if name:
                gold_by_key.setdefault(
                    (
                        str(gold["ministry_code"]).zfill(3),
                        int(gold["fiscal_year"]),
                        document_type,
                    ),
                    [],
                ).append({**gold, "comparison_indicator_name": name})
    for key, rows in candidates.items():
        for row in rows:
            if row.get("fiscal_year") != key[1] or not row.get("indicator_name"):
                continue
            best_gold = max(
                gold_by_key.get(key, []),
                key=lambda gold: local_parser._partial_similarity(
                    str(row["indicator_name"]), gold["comparison_indicator_name"]
                ),
                default={},
            )
            similarity = (
                local_parser._partial_similarity(
                    str(row["indicator_name"]), best_gold["comparison_indicator_name"]
                )
                if best_gold
                else 0.0
            )
            output_evaluation = {
                "request_id": row["request_id"],
                "document_type": key[2],
                "indicator_name": row["indicator_name"],
                "manual_indicator_name": best_gold.get("comparison_indicator_name"),
                "manual_indicator_similarity": similarity,
                "manual_indicator_match": similarity >= 0.8,
            }
            value_columns = (
                {"planned_target": "planned_target_raw"}
                if key[2] == "PLAN"
                else {
                    "actual_value": "actual_value_raw",
                    "achievement_rate": "official_achievement_rate_raw",
                }
            )
            for field, gold_column in value_columns.items():
                expected = local_parser._clean_expected(best_gold.get(gold_column))
                output_evaluation[f"{field}_expected"] = expected
                output_evaluation[f"{field}_extracted"] = row.get(field)
                output_evaluation[f"{field}_match"] = (
                    _numeric_comparison_equal(row.get(field), expected)
                    if expected and similarity >= 0.8
                    else None
                )
            target_outputs.append(output_evaluation)
    local_parser._write_csv(output_dir / "sync_target_year_output_evaluation.csv", target_outputs)
    target_frame = pd.DataFrame(target_outputs)
    target_field_values = pd.concat(
        [
            target_frame[column].dropna().astype(bool)
            for column in target_frame
            if column.endswith("_match") and column != "manual_indicator_match"
        ],
        ignore_index=True,
    )
    summary = {
        "request_count": len(responses),
        "record_count": len(grounding_frame),
        "schema_valid_rate": float(grounding_frame["schema_valid"].mean()),
        "locally_corroborated_record_rate": float(
            grounding_frame["all_non_null_fields_locally_corroborated"].mean()
        ),
        "locally_corroborated_field_rate": float(
            grounding_frame["locally_corroborated_field_count"].sum()
            / grounding_frame["non_null_checked_field_count"].sum()
        ),
        "page_linked_manual_gold_count": len(evaluation_frame),
        "indicator_recovery_rate": float(evaluation_frame["indicator_recovered"].mean()),
        "target_year_record_link_rate": float(evaluation_frame["target_year_record_match"].mean()),
        "visible_expected_field_count": len(recovered_values),
        "value_recovery_rate": (float(recovered_values.mean()) if len(recovered_values) else None),
        "target_year_structured_field_accuracy": (
            float(target_year_values.mean()) if len(target_year_values) else None
        ),
        "expected_fields_not_visible_on_sampled_input_page": int(
            sum(
                (~evaluation_frame[column].astype(bool)).sum()
                for column in evaluation_frame
                if column.endswith("_source_visible")
            )
        ),
        "target_year_output_count": len(target_frame),
        "target_year_output_manual_gold_name_match_rate": float(
            target_frame["manual_indicator_match"].mean()
        ),
        "target_year_output_manual_gold_name_match_count": int(
            target_frame["manual_indicator_match"].sum()
        ),
        "target_year_output_conditional_manual_field_count": len(target_field_values),
        "target_year_output_conditional_manual_field_agreement_rate": (
            float(target_field_values.mean()) if len(target_field_values) else None
        ),
        "by_document_type": {},
        "local_corroboration_review_record_count": int(
            (~grounding_frame["all_non_null_fields_locally_corroborated"]).sum()
        ),
        "expansion_gate_thresholds": gate,
        "interpretation": (
            "사람이 만든 성과지표 세트를 정답지로 사용하고 PDF 물리 페이지와 인쇄 페이지를 같은 "
            "좌표끼리만 연결합니다. sampled input page에 실제 보이는 기대값만 필드 정확도 분모로 "
            "사용합니다. 값 존재 회수와 목표연도에 귀속된 구조화 정확도를 분리하며 로컬 대조율은 "
            "보조 진단일 뿐 품질 게이트가 아닙니다. 전체 목표연도 출력의 수기 지표명 일치율은 수기 "
            "세트가 해당 34쪽의 모든 지표를 포함하지 않으므로 정확도나 precision으로 해석하지 않습니다."
        ),
    }
    for name, part in evaluation_frame.groupby("document_type"):
        part_recovered = evaluation_values(part, "_value_recovered")
        part_target_year = evaluation_values(part, "_target_year_match")
        summary["by_document_type"][name] = {
            "gold_count": len(part),
            "indicator_recovery_rate": float(part["indicator_recovered"].mean()),
            "target_year_record_link_rate": float(part["target_year_record_match"].mean()),
            "visible_expected_field_count": len(part_recovered),
            "value_recovery_rate": (float(part_recovered.mean()) if len(part_recovered) else None),
            "target_year_structured_field_accuracy": (
                float(part_target_year.mean()) if len(part_target_year) else None
            ),
        }
    summary["expansion_gate_passed"] = bool(
        summary["schema_valid_rate"] == 1
        and summary["indicator_recovery_rate"] >= float(gate["indicator_recovery_rate"])
        and summary["target_year_record_link_rate"] >= float(gate["target_year_record_link_rate"])
        and (summary["target_year_structured_field_accuracy"] or 0)
        >= float(gate["target_year_structured_field_accuracy"])
    )
    local_parser._write_json(output_dir / "sync_evaluation_summary.json", summary)
    return summary


def _gold_frames(root: Path, ministry_codes: tuple[str, ...]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for code in ministry_codes:
        path = (
            root / "data/processed/performance/program_kpi_year.parquet"
            if code == "102"
            else root
            / "data/processed/performance/by_ministry"
            / f"ministry_code={code}"
            / "program_kpi_year.parquet"
        )
        frames.append(pd.read_parquet(path).assign(ministry_code=code))
    return pd.concat(frames, ignore_index=True, sort=False)


def _candidate_recall(
    root: Path, manifest: list[dict[str, Any]], ministry_codes: tuple[str, ...]
) -> dict[str, Any]:
    page_sets: dict[tuple[str, int, str], set[int]] = {}
    for row in manifest:
        key = (
            str(row["ministry_code"]).zfill(3),
            int(row["fiscal_year"]),
            str(row["document_type"]),
        )
        page_sets.setdefault(key, set()).add(int(row["source_pdf_page"]))
    gold = _gold_frames(root, ministry_codes)
    previous = pd.read_csv(
        root / "data/processed/performance/unattended_pdf/gold_evaluation.csv",
        dtype={"ministry_code": str},
    )
    missing = {
        (str(row["source_indicator_id"]), str(row["document_type"]))
        for row in previous.loc[~previous["discovered"].fillna(False)].to_dict("records")
    }
    evaluated: list[dict[str, Any]] = []
    for row in gold.to_dict("records"):
        for document_type, page_column in (
            ("PLAN", "plan_source_page"),
            ("REPORT", "report_source_page"),
        ):
            page = _page_number(row.get(page_column))
            if page is None:
                continue
            document_key = (
                str(row["ministry_code"]).zfill(3),
                int(row["fiscal_year"]),
                document_type,
            )
            pages = page_sets.get(document_key, set())
            evaluated.append(
                {
                    "document_type": document_type,
                    "selected_exact": page in pages,
                    "selected_within_2_pages": any(
                        abs(page - candidate_page) <= 2 for candidate_page in pages
                    ),
                    "previously_missed": (str(row["source_indicator_id"]), document_type)
                    in missing,
                }
            )
    frame = pd.DataFrame(evaluated)
    missed = frame.loc[frame["previously_missed"]]
    return {
        "gold_page_linked_rows": len(frame),
        "exact_page_candidate_recall": float(frame["selected_exact"].mean()),
        "within_2_pages_candidate_recall": float(frame["selected_within_2_pages"].mean()),
        "previously_missed_rows": len(missed),
        "previously_missed_exact_page_recall": (
            float(missed["selected_exact"].mean()) if len(missed) else None
        ),
        "previously_missed_within_2_pages_recall": (
            float(missed["selected_within_2_pages"].mean()) if len(missed) else None
        ),
        "by_document_type": {
            name: {
                "exact": float(part["selected_exact"].mean()),
                "within_2_pages": float(part["selected_within_2_pages"].mean()),
            }
            for name, part in frame.groupby("document_type")
        },
        "page_tolerance_reason": (
            "수기 plan_source_page 일부가 다음 별첨 페이지를 가리키는 오프바이원·투 "
            "불일치를 확인해 정확 일치와 ±2쪽 진단을 함께 제시합니다."
        ),
    }


def _local_accuracy(
    root: Path,
    output_dir: Path,
    manifest: list[dict[str, Any]],
    quality_rows: list[dict[str, Any]],
    ministry_codes: tuple[str, ...],
) -> dict[str, Any]:
    pages: dict[tuple[str, int, str], list[dict[str, Any]]] = {}
    for row in manifest:
        key = (
            str(row["ministry_code"]).zfill(3),
            int(row["fiscal_year"]),
            str(row["document_type"]),
        )
        pages.setdefault(key, []).append(row)
    statuses = {row["page_id"]: row["structure_status"] for row in quality_rows}
    raw_dir = output_dir / "opendataloader/raw"
    row_cache: dict[str, list[str]] = {}
    evaluations: list[dict[str, Any]] = []
    gold = _gold_frames(root, ministry_codes)
    for record in gold.to_dict("records"):
        for document_type, page_column, name_column, value_columns in (
            (
                "PLAN",
                "plan_source_page",
                "indicator_name_plan",
                {"planned_target": "planned_target_raw"},
            ),
            (
                "REPORT",
                "report_source_page",
                "indicator_name_report",
                {
                    "actual_value": "actual_value_raw",
                    "achievement_rate": "official_achievement_rate_raw",
                },
            ),
        ):
            expected_name = local_parser._clean_expected(record.get(name_column))
            source_page = _page_number(record.get(page_column))
            if not expected_name or source_page is None:
                continue
            key = (
                str(record["ministry_code"]).zfill(3),
                int(record["fiscal_year"]),
                document_type,
            )
            nearby = sorted(
                (
                    row
                    for row in pages.get(key, [])
                    if abs(int(row["source_pdf_page"]) - source_page) <= 2
                ),
                key=lambda row: abs(int(row["source_pdf_page"]) - source_page),
            )
            best: tuple[float, dict[str, Any] | None, list[str]] = (0.0, None, [])
            for page in nearby:
                page_id = str(page["page_id"])
                table_rows = row_cache.setdefault(
                    page_id,
                    local_parser._opendataloader_table_rows(raw_dir / f"{page_id}.json"),
                )
                similarity = max(
                    (
                        local_parser._partial_similarity(expected_name, table_row)
                        for table_row in table_rows
                    ),
                    default=0.0,
                )
                if similarity > best[0]:
                    best = similarity, page, table_rows
            similarity, matched_page, table_rows = best
            fuzzy_match = similarity >= 0.8
            expected_values = {
                name: local_parser._clean_expected(record.get(column))
                for name, column in value_columns.items()
            }
            value_matches = (
                local_parser._same_row_matches(expected_name, expected_values, table_rows)
                if fuzzy_match
                else {name: False for name in expected_values}
            )
            evaluations.append(
                {
                    "ministry_code": key[0],
                    "fiscal_year": key[1],
                    "document_type": document_type,
                    "source_indicator_id": record.get("source_indicator_id"),
                    "manual_source_page": source_page,
                    "matched_candidate_page": (
                        int(matched_page["source_pdf_page"]) if matched_page else None
                    ),
                    "page_offset": (
                        int(matched_page["source_pdf_page"]) - source_page if matched_page else None
                    ),
                    "structure_status": (
                        statuses.get(str(matched_page["page_id"])) if matched_page else None
                    ),
                    "expected_indicator_name": expected_name,
                    "indicator_similarity": similarity,
                    "indicator_fuzzy_match": fuzzy_match,
                    **{f"{name}_expected": value for name, value in expected_values.items()},
                    **{
                        f"{name}_same_row_match": value_matches[name]
                        if expected_values[name]
                        else None
                        for name in expected_values
                    },
                }
            )
    local_parser._write_csv(output_dir / "local_gold_evaluation.csv", evaluations)
    frame = pd.DataFrame(evaluations)
    field_columns = [column for column in frame if column.endswith("_same_row_match")]
    field_values = pd.concat(
        [frame[column].dropna().astype(bool) for column in field_columns],
        ignore_index=True,
    )
    by_ministry = {
        code: {
            "records": len(part),
            "indicator_fuzzy_match_rate": float(part["indicator_fuzzy_match"].mean()),
        }
        for code, part in frame.groupby("ministry_code")
    }
    return {
        "evaluated_record_count": len(frame),
        "indicator_fuzzy_match_count": int(frame["indicator_fuzzy_match"].sum()),
        "indicator_fuzzy_match_rate": float(frame["indicator_fuzzy_match"].mean()),
        "same_row_field_count": len(field_values),
        "same_row_field_match_count": int(field_values.sum()),
        "conditional_same_row_field_accuracy": (
            float(field_values.mean()) if len(field_values) else None
        ),
        "by_ministry": by_ministry,
        "interpretation": (
            "수기 출처 PDF 쪽 ±2 범위에서 지표명이 복구된 행만 필드 정확도를 평가합니다. "
            "중기부처럼 수기 출처 쪽이 실제 지표표와 다른 행은 지표명 재현율에는 포함하되 "
            "필드 정확도 분모에는 포함하지 않습니다."
        ),
    }


def package_vision_requests(
    root: Path,
    output_dir: Path,
    ministry_codes: tuple[str, ...],
) -> dict[str, Any]:
    manifest = _read_csv(output_dir / "manifest.csv")
    page_lookup = {_candidate_key(row): row for row in manifest}
    raw_dir = output_dir / "opendataloader/raw"
    quality_rows: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    request_index: list[dict[str, Any]] = []
    config = yaml.safe_load((root / "configs/llm.yaml").read_text(encoding="utf-8"))
    model = str(config["llm"]["default_model"])
    max_output_tokens = 6000
    for row in manifest:
        payload = json.loads((raw_dir / f"{row['page_id']}.json").read_text(encoding="utf-8"))
        tables = _tables(payload)
        table_rows = local_parser._opendataloader_table_rows(raw_dir / f"{row['page_id']}.json")
        structure_failures = structure_reasons(
            table_rows,
            row["document_type"],
            int(row["fiscal_year"]),
            len(tables),
        )
        structure_status, reasons = _structure_route(row["selection_reasons"], structure_failures)
        quality = {
            **row,
            "table_count": len(tables),
            "expanded_table_row_count": len(table_rows),
            "structure_status": structure_status,
            "structure_reasons": ";".join(reasons),
        }
        if reasons:
            image_path = output_dir / "vision_images" / f"{row['page_id']}.png"
            width, height, rotation, confidence = _render_for_vision(
                root / row["input_pdf"], image_path
            )
            quality.update(
                {
                    "image_width": width,
                    "image_height": height,
                    "osd_rotation_applied": rotation,
                    "osd_orientation_confidence": confidence,
                    "image_patch_tokens": math.ceil(width / 32) * math.ceil(height / 32),
                }
            )
            with fitz.open(root / row["input_pdf"]) as page_document:
                page_text = page_document[0].get_text("text")
            if _needs_previous_page_context(reasons, page_text):
                previous_key = (
                    str(row["ministry_code"]).zfill(3),
                    int(row["fiscal_year"]),
                    str(row["document_type"]),
                    str(row["source_file"]),
                    int(row["source_pdf_page"]) - 1,
                )
                if previous := page_lookup.get(previous_key):
                    context_path = output_dir / "vision_images" / f"{row['page_id']}_previous.png"
                    context_width, context_height, _, _ = _render_for_vision(
                        root / previous["input_pdf"], context_path
                    )
                    context_tokens = math.ceil(context_width / 32) * math.ceil(context_height / 32)
                    quality.update(
                        {
                            "previous_context_page": previous["source_pdf_page"],
                            "previous_context_image_path": str(context_path),
                            "previous_context_image_patch_tokens": context_tokens,
                            "image_patch_tokens": quality["image_patch_tokens"] + context_tokens,
                        }
                    )
            if _needs_next_page_context(reasons, row["document_type"]):
                next_key = (
                    str(row["ministry_code"]).zfill(3),
                    int(row["fiscal_year"]),
                    str(row["document_type"]),
                    str(row["source_file"]),
                    int(row["source_pdf_page"]) + 1,
                )
                if following := page_lookup.get(next_key):
                    context_path = output_dir / "vision_images" / f"{row['page_id']}_next.png"
                    context_width, context_height, _, _ = _render_for_vision(
                        root / following["input_pdf"], context_path
                    )
                    context_tokens = math.ceil(context_width / 32) * math.ceil(context_height / 32)
                    quality.update(
                        {
                            "next_context_page": following["source_pdf_page"],
                            "next_context_image_path": str(context_path),
                            "next_context_image_patch_tokens": context_tokens,
                            "image_patch_tokens": quality["image_patch_tokens"] + context_tokens,
                        }
                    )
            request, index = _request_entry(quality, image_path, model, max_output_tokens)
            requests.append(request)
            request_index.append(index)
        quality_rows.append(quality)

    request_path = output_dir / "vision_requests.jsonl"
    request_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in requests),
        encoding="utf-8",
    )
    local_parser._write_csv(output_dir / "page_quality.csv", quality_rows)
    local_parser._write_csv(output_dir / "vision_request_index.csv", request_index)
    pilot_limit = int(config["harness"]["pilot_request_limit"])
    pilot_index = _pilot_sample(request_index, pilot_limit)
    pilot_ids = {row["request_id"] for row in pilot_index}
    pilot_requests = [row for row in requests if row["custom_id"] in pilot_ids]
    (output_dir / "vision_pilot_requests.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in pilot_requests),
        encoding="utf-8",
    )
    local_parser._write_csv(output_dir / "vision_pilot_index.csv", pilot_index)
    pricing = config["harness"]["pricing_usd_per_million"][model]
    image_tokens = sum(int(row["image_patch_tokens"]) for row in request_index)
    text_tokens = sum(math.ceil(int(row["prompt_char_count"]) / 2) for row in request_index)
    expected_output_tokens = 1200 * len(requests)
    synchronous_cost = (
        (image_tokens + text_tokens) * float(pricing["input"])
        + expected_output_tokens * float(pricing["output"])
    ) / 1_000_000
    pilot_image_tokens = sum(int(row["image_patch_tokens"]) for row in pilot_index)
    pilot_text_tokens = sum(math.ceil(int(row["prompt_char_count"]) / 2) for row in pilot_index)
    pilot_output_tokens = 1200 * len(pilot_index)
    pilot_synchronous_cost = (
        (pilot_image_tokens + pilot_text_tokens) * float(pricing["input"])
        + pilot_output_tokens * float(pricing["output"])
    ) / 1_000_000
    quality_counts = Counter(row["structure_status"] for row in quality_rows)
    local_page_count = (
        quality_counts["EXISTING_LOCAL_CONFIRMED"] + quality_counts["ODL_STRUCTURE_OK"]
    )
    summary = {
        "candidate_page_count": len(manifest),
        "existing_local_confirmed_page_count": quality_counts["EXISTING_LOCAL_CONFIRMED"],
        "odl_structure_ok_page_count": quality_counts["ODL_STRUCTURE_OK"],
        "vision_required_page_count": quality_counts["VISION_REQUIRED"],
        "local_auto_route_rate": (local_page_count / len(manifest) if manifest else None),
        "vision_request_count": len(requests),
        "previous_context_image_count": sum(
            bool(row.get("previous_context_image_path")) for row in request_index
        ),
        "next_context_image_count": sum(
            bool(row.get("next_context_image_path")) for row in request_index
        ),
        "human_review_before_vision_count": 0,
        "model": model,
        "detail": "original",
        "image_token_method": "ceil(width/32)*ceil(height/32)",
        "image_tokens_estimate": image_tokens,
        "text_tokens_estimate": text_tokens,
        "expected_output_tokens": expected_output_tokens,
        "synchronous_cost_usd_estimate": synchronous_cost,
        "batch_cost_usd_estimate": synchronous_cost
        * float(config["harness"].get("batch_discount", 0.5)),
        "pilot_request_count": len(pilot_index),
        "pilot_image_tokens_estimate": pilot_image_tokens,
        "pilot_text_tokens_estimate": pilot_text_tokens,
        "pilot_expected_output_tokens": pilot_output_tokens,
        "pilot_synchronous_cost_usd_estimate": pilot_synchronous_cost,
        "pilot_batch_cost_usd_estimate": pilot_synchronous_cost
        * float(config["harness"].get("batch_discount", 0.5)),
        "api_call_count": 0,
        "api_execution_allowed": bool(config["llm"].get("api_execution_allowed", False)),
        "gold_loaded_after_local_extraction": True,
        "candidate_recall": _candidate_recall(root, manifest, ministry_codes),
        "local_gold_accuracy": _local_accuracy(
            root, output_dir, manifest, quality_rows, ministry_codes
        ),
        "vision_field_accuracy": None,
        "vision_non_grounded_nonnull_rate": None,
        "vision_auto_promotion_rate": None,
        "interpretation_limit": (
            "외부 API를 호출하지 않은 dry-run입니다. 비전 필드 정확도·비근거값·자동승격률은 "
            "응답 검증 전까지 산정하지 않습니다."
        ),
    }
    local_parser._write_json(output_dir / "selective_vision_summary.json", summary)
    return summary


def run_local_pilot(
    root: Path,
    output_dir: Path,
    ministry_codes: tuple[str, ...] = DEFAULT_MINISTRIES,
    overwrite: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    output_dir = output_dir.resolve()
    summary_path = output_dir / "selective_vision_summary.json"
    if summary_path.exists() and not overwrite:
        raise FileExistsError(summary_path)
    manifest = build_candidate_manifest(root, output_dir, ministry_codes)
    source_hashes = {row["source_file"]: row["source_pdf_sha256"] for row in manifest}
    local_parser.run_opendataloader(root, output_dir)
    changed = [
        source_file
        for source_file, before in source_hashes.items()
        if local_parser._sha256(root / "data/raw/performance_docs" / source_file) != before
    ]
    if changed:
        raise RuntimeError(f"원본 PDF가 변경됐습니다: {changed}")
    summary = package_vision_requests(root, output_dir, ministry_codes)
    summary["source_pdf_hashes_unchanged"] = True
    local_parser._write_json(output_dir / "selective_vision_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-dir", type=Path, default=Path("data/interim/selective_vision_pilot")
    )
    parser.add_argument("--ministry-codes", default=",".join(DEFAULT_MINISTRIES))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--sync-pilot-execute", action="store_true")
    parser.add_argument("--evaluate-sync-pilot", action="store_true")
    parser.add_argument("--max-approved-cost-usd", type=float)
    args = parser.parse_args()
    if args.evaluate_sync_pilot:
        codes = tuple(
            code.strip().zfill(3) for code in args.ministry_codes.split(",") if code.strip()
        )
        print(
            json.dumps(
                evaluate_sync_pilot(args.root, args.output_dir, codes), ensure_ascii=False, indent=2
            )
        )
        return
    if args.sync_pilot_execute:
        if args.max_approved_cost_usd is None:
            parser.error("--sync-pilot-execute에는 --max-approved-cost-usd가 필요합니다.")
        summary = run_sync_pilot(
            args.root,
            args.output_dir,
            max_approved_cost_usd=args.max_approved_cost_usd,
            execute=True,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    codes = tuple(code.strip().zfill(3) for code in args.ministry_codes.split(",") if code.strip())
    summary = run_local_pilot(args.root, args.output_dir, codes, args.overwrite)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
