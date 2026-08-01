from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import math
import re
import statistics
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import fitz
import pandas as pd
import permissive_local_parser_pilot as local_parser
import yaml
from PIL import Image

from performance_pipeline.pdf_reconciliation import _configure_pytesseract, ocr_page_text

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
    return "INDICATOR_HEADER_MISSING" in reasons and "성과지표" not in _compact(page_text)


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


def _vision_schema() -> dict[str, Any]:
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
                        "fiscal_year": {"type": ["integer", "null"]},
                        "planned_target": nullable_string,
                        "actual_value": nullable_string,
                        "achievement_rate": nullable_string,
                        "source_evidence": nullable_string,
                    },
                },
            }
        },
    }


def _request_entry(
    row: dict[str, Any], image_path: Path, model: str, max_output_tokens: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    prompt = (
        "성과계획서·성과보고서의 표 이미지에서 보이는 값만 추출하세요. 추정하거나 "
        "누락값을 만들지 말고 불명확하면 null을 반환하세요. 모든 지표를 표의 연도 열과 "
        "목표·실적·달성률 행에 맞춰 분리하고, source_evidence에는 해당 지표와 값이 함께 "
        "보이는 짧은 원문을 적으세요. "
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
    ]
    if len(image_paths) > 1:
        prompt += " 첫 이미지는 직전 페이지 문맥이고 마지막 이미지는 추출 대상 페이지입니다."
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
                    "schema": _vision_schema(),
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
    args = parser.parse_args()
    codes = tuple(code.strip().zfill(3) for code in args.ministry_codes.split(",") if code.strip())
    summary = run_local_pilot(args.root, args.output_dir, codes, args.overwrite)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
