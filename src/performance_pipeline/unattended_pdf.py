from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import fitz
import pandas as pd
import yaml

from .pdf_reconciliation import (
    normalize_indicator_name,
    normalize_program_goal,
    parse_numeric,
    sha256_file,
)

ROMAN_PATTERN = r"[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+|[IVX]+|\d+"
PROGRAM_PATTERN = re.compile(
    rf"프로그램\s*목표\s*(?P<strategy>{ROMAN_PATTERN})\s*[-‐‑‒–—−]\s*(?P<program>\d+)",
    re.IGNORECASE,
)
NUMBER_TOKEN = re.compile(r"\(?[+-]?\d[\d,]*(?:\.\d+)?\)?")
PUA_CHAR_RE = re.compile(r"[\ue000-\uf8ff]")


class UnattendedPdfError(RuntimeError):
    pass


@dataclass(frozen=True)
class UnattendedPdfResult:
    summary: dict[str, Any]
    output_paths: tuple[Path, ...]


def _clean_cell(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value))).strip()


def _metric_raw(value: Any) -> str | None:
    text = _clean_cell(value)
    if not text:
        return None
    if text in {"-", "–", "—"} or "신규" in text:
        return text
    matches = NUMBER_TOKEN.findall(text)
    return matches[-1] if matches else text


def _clean_indicator(value: Any) -> tuple[str, str | None, str | None]:
    raw = re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]\s*", "", str(value or ""))
    text = _clean_cell(raw)
    text = re.sub(r"^[1-9](?!\d)\s*(?=[가-힣A-Za-z])", "", text)
    direction = "하향" if "하향지표" in text else None
    text = re.sub(r"[ㅇ○ᄋ]\s*$", "", text).strip()
    units = [item.strip() for item in re.findall(r"\(([^()]*)\)", text) if item.strip()]
    unit = next((item for item in reversed(units) if "지표" not in item), None)
    name = re.sub(r"\([^()]*하향지표[^()]*\)", "", text)
    if unit:
        name = re.sub(rf"(?:\({re.escape(unit)}\)\s*)+$", "", name)
    return re.sub(r"\s+", " ", name).strip(" /·"), unit, direction


def _display_page(text: str) -> str | None:
    for line in text.splitlines()[:8]:
        if match := re.search(r"-\s*(\d+)\s*-", unicodedata.normalize("NFKC", line)):
            return match.group(1)
    return None


def _year_column(rows: list[list[Any]], fiscal_year: int) -> int | None:
    suffix = str(fiscal_year)[-2:]
    for row in rows[:3]:
        for index, cell in enumerate(row):
            compact = re.sub(r"\s+", "", _clean_cell(cell)).replace("’", "'")
            if re.search(rf"(?:'{suffix}|{fiscal_year})(?:년)?$", compact):
                return index
    return None


def _roman_number(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).upper()
    return {
        "I": "Ⅰ",
        "II": "Ⅱ",
        "III": "Ⅲ",
        "IV": "Ⅳ",
        "V": "Ⅴ",
        "VI": "Ⅵ",
        "VII": "Ⅶ",
        "VIII": "Ⅷ",
        "IX": "Ⅸ",
        "X": "Ⅹ",
        "XI": "Ⅺ",
        "XII": "Ⅻ",
    }.get(normalized, normalized)


def _hierarchy_from_words(words: list[tuple[Any, ...]], page_number: int) -> dict[str, Any] | None:
    ordered = sorted(words, key=lambda word: (round(float(word[1]), 1), float(word[0])))
    compact = unicodedata.normalize("NFKC", "".join(_clean_cell(word[4]) for word in ordered))
    match = re.search(
        rf"프로그램목표(?:(?P<s1>{ROMAN_PATTERN})[-‐‑‒–—−](?P<p1>\d+)|[-‐‑‒–—−](?P<p2>\d+)(?P<s2>{ROMAN_PATTERN}))",
        compact,
        re.IGNORECASE,
    )
    if not match:
        return None
    strategy = _roman_number(match.group("s1") or match.group("s2"))
    program = match.group("p1") or match.group("p2")
    header_words = [
        word for word in ordered if _clean_cell(word[4]) in {"프로그램", "프로그램목표"}
    ]
    header_y = min((float(word[1]) for word in header_words), default=0.0)
    candidates: list[tuple[float, str]] = []
    for word in ordered:
        token = re.fullmatch(r"\(([^()]{2,50})\)", _clean_cell(word[4]))
        if (
            token
            and re.search(r"[가-힣A-Za-z]", token.group(1))
            and float(word[1]) <= header_y + 60
        ):
            candidates.append((abs(float(word[1]) - header_y), token.group(1)))
    program_name = min(candidates, default=(0.0, None), key=lambda item: item[0])[1]
    evidence = " ".join(_clean_cell(word[4]) for word in ordered if float(word[1]) <= header_y + 60)
    statement = evidence.split("프로그램 목표", 1)[0].strip(" .:-") or None
    return {
        "strategic_goal_number": strategy,
        "program_goal_number": f"{strategy}-{program}",
        "program_name": program_name,
        "program_goal_statement": statement,
        "hierarchy_source_page": page_number,
        "hierarchy_source_text": evidence[:400],
    }


def _page_hierarchy(
    page_texts: list[str],
    page_words: list[list[tuple[Any, ...]]],
    target_page: int,
    lookback_pages: int = 20,
) -> dict[str, Any]:
    for page_number in range(target_page, max(0, target_page - lookback_pages), -1):
        if found := _hierarchy_from_words(page_words[page_number - 1], page_number):
            return found
        for line in page_texts[page_number - 1].splitlines():
            if match := PROGRAM_PATTERN.search(unicodedata.normalize("NFKC", line)):
                strategy = _roman_number(match.group("strategy"))
                return {
                    "strategic_goal_number": strategy,
                    "program_goal_number": f"{strategy}-{match.group('program')}",
                    "program_name": None,
                    "program_goal_statement": None,
                    "hierarchy_source_page": page_number,
                    "hierarchy_source_text": _clean_cell(line)[:400],
                }
    return {
        "strategic_goal_number": None,
        "program_goal_number": None,
        "program_name": None,
        "program_goal_statement": None,
        "hierarchy_source_page": None,
        "hierarchy_source_text": None,
    }


def _common_record(
    *,
    ministry_code: str,
    ministry_name: str,
    fiscal_year: int,
    document_type: str,
    source_file: str,
    source_page: int,
    printed_page: str | None,
    hierarchy: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ministry_code": ministry_code,
        "ministry_name": ministry_name,
        "fiscal_year": fiscal_year,
        "document_type": document_type,
        **hierarchy,
        "source_file": source_file,
        "source_pdf_page": source_page,
        "printed_page": printed_page,
    }


def parse_plan_table(
    rows: list[list[Any]],
    *,
    common: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not rows or max((len(row) for row in rows), default=0) < 11:
        return [], []
    fiscal_year = int(common["fiscal_year"])
    year_column = _year_column(rows, fiscal_year)
    if year_column is None and max((len(row) for row in rows), default=0) > 8:
        year_column = 8
    records: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for row_number, row in enumerate(rows[1:], start=2):
        padded = list(row) + [None] * (13 - len(row))
        if "목표" not in _clean_cell(padded[3]):
            continue
        name, unit, direction = _clean_indicator(padded[0])
        target = _metric_raw(padded[year_column]) if year_column is not None else None
        if not name or normalize_indicator_name(name) in {"성과지표", "구분"}:
            unresolved.append(
                {
                    **common,
                    "table_row_number": row_number,
                    "routing_status": "OCR_REQUIRED",
                    "routing_reason": "INDICATOR_NAME_NOT_RECOVERED",
                    "planned_target_raw": target,
                }
            )
            continue
        records.append(
            {
                **common,
                "indicator_name": name,
                "indicator_unit": unit,
                "indicator_direction": direction,
                "planned_target_raw": target,
                "report_target_raw": None,
                "actual_value_raw": None,
                "official_achievement_rate_raw": None,
                "measurement_formula": _clean_cell(padded[11]) or None,
                "source_text": f"성과지표={name}; {fiscal_year}년 계획목표={target}",
                "extraction_method": "PYMUPDF_TABLE",
            }
        )
    return records, unresolved


def parse_report_table(rows: list[list[Any]], *, common: dict[str, Any]) -> list[dict[str, Any]]:
    if not rows:
        return []
    header_index = next(
        (
            index
            for index, row in enumerate(rows[:4])
            if any("성과지표" in _clean_cell(cell) for cell in row)
        ),
        None,
    )
    if header_index is None:
        return []
    fiscal_year = int(common["fiscal_year"])
    year_column = _year_column(rows[header_index : header_index + 3], fiscal_year)
    if year_column is None:
        return []
    header = rows[header_index]
    status_column = next(
        (
            index
            for index, cell in enumerate(header)
            if "목표대비" in _clean_cell(cell) or "달성률" in _clean_cell(cell)
        ),
        2,
    )
    records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def finish() -> None:
        nonlocal current
        if not current or not current.get("indicator_name"):
            current = None
            return
        current["source_text"] = (
            f"성과지표={current['indicator_name']}; {fiscal_year}년 보고목표="
            f"{current.get('report_target_raw')}; 실적={current.get('actual_value_raw')}; "
            f"달성률={current.get('official_achievement_rate_raw')}"
        )
        records.append(current)
        current = None

    for row in rows[header_index + 1 :]:
        padded = list(row) + [None] * (max(year_column, status_column, 2) + 1 - len(row))
        indicator_cell = _clean_cell(padded[0])
        status = _clean_cell(padded[status_column])
        if indicator_cell:
            finish()
            name, unit, direction = _clean_indicator(indicator_cell)
            current = {
                **common,
                "indicator_name": name,
                "indicator_unit": unit,
                "indicator_direction": direction,
                "planned_target_raw": None,
                "report_target_raw": None,
                "actual_value_raw": None,
                "official_achievement_rate_raw": None,
                "measurement_formula": _clean_cell(padded[1]) or None,
                "extraction_method": "PYMUPDF_TABLE",
            }
        if current is None:
            continue
        value = _metric_raw(padded[year_column])
        if status.startswith("목표"):
            current["report_target_raw"] = value
        elif status.startswith("실적"):
            current["actual_value_raw"] = value
        elif "달성률" in status:
            current["official_achievement_rate_raw"] = value
            finish()
    finish()
    return records


def _route(record: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    name = str(record.get("indicator_name") or "")
    if not name or PUA_CHAR_RE.search(name):
        reasons.append("INDICATOR_NAME_UNRELIABLE")
    if not normalize_program_goal(record.get("program_goal_number")):
        reasons.append("PROGRAM_CONTEXT_MISSING")
    if record["document_type"] == "PLAN" and record.get("planned_target_raw") is None:
        reasons.append("PLAN_TARGET_MISSING")
    if record["document_type"] == "REPORT" and not any(
        record.get(field)
        for field in ("report_target_raw", "actual_value_raw", "official_achievement_rate_raw")
    ):
        reasons.append("REPORT_VALUES_MISSING")
    record["routing_status"] = "LOCAL_CONFIRMED" if not reasons else "LLM_REVIEW_REQUIRED"
    record["routing_reason"] = ";".join(reasons) or None
    return record


def _deduplicate(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for record in records:
        name = normalize_indicator_name(record.get("indicator_name"))
        if not name:
            continue
        goal = normalize_program_goal(record.get("program_goal_number"))
        key = (
            record["ministry_code"],
            int(record["fiscal_year"]),
            record["document_type"],
            goal or f"PAGE:{record['source_pdf_page']}",
            name,
        )
        groups.setdefault(key, []).append(record)
    selected: list[dict[str, Any]] = []
    value_fields = (
        "planned_target_raw",
        "report_target_raw",
        "actual_value_raw",
        "official_achievement_rate_raw",
    )
    for candidates in groups.values():
        candidates.sort(
            key=lambda row: (
                -sum(row.get(field) is not None for field in value_fields),
                row["source_pdf_page"],
            )
        )
        chosen = dict(candidates[0])
        fingerprints = {tuple(row.get(field) for field in value_fields) for row in candidates}
        chosen["duplicate_candidate_count"] = len(candidates)
        if len(fingerprints) > 1:
            chosen["routing_status"] = "HUMAN_REVIEW_REQUIRED"
            chosen["routing_reason"] = "CONFLICTING_DUPLICATE_VALUES"
        selected.append(_route(chosen) if len(fingerprints) == 1 else chosen)
    return sorted(
        selected,
        key=lambda row: (
            row["ministry_code"],
            int(row["fiscal_year"]),
            row["document_type"],
            int(row["source_pdf_page"]),
            row["indicator_name"],
        ),
    )


def discover_documents(
    raw_dir: Path,
    ministry_name: str,
    years: tuple[int, ...] = (2022, 2023, 2024),
) -> dict[int, dict[str, Path]]:
    documents: dict[int, dict[str, Path]] = {}
    missing: list[str] = []
    for year in years:
        paths = {
            "PLAN": raw_dir / f"{year}년도 성과계획서_{ministry_name}.pdf",
            "REPORT": raw_dir / f"{year}년도 성과보고서_{ministry_name}.pdf",
        }
        for path in paths.values():
            if not path.is_file():
                missing.append(str(path))
        documents[year] = paths
    if missing:
        raise UnattendedPdfError(f"필수 PDF가 없습니다: {missing}")
    return documents


def extract_ministry_documents(
    *,
    raw_dir: Path,
    ministry_code: str,
    ministry_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    records: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    page_audit: list[dict[str, Any]] = []
    source_hashes: dict[str, str] = {}
    for fiscal_year, paths in discover_documents(raw_dir, ministry_name).items():
        for document_type, pdf_path in paths.items():
            source_hashes[str(pdf_path)] = sha256_file(pdf_path)
            with fitz.open(pdf_path) as document:
                page_texts = [page.get_text("text") for page in document]
                page_words = [page.get_text("words") for page in document]
                for page_index, page in enumerate(document):
                    source_page = page_index + 1
                    text = page_texts[page_index]
                    compact = re.sub(r"\s+", "", text)
                    if document_type == "REPORT" and "성과지표" not in compact:
                        continue
                    try:
                        tables = page.find_tables().tables
                    except Exception as exc:  # noqa: BLE001 - 페이지별 실패를 감사표에 보존합니다.
                        page_audit.append(
                            {
                                "ministry_code": ministry_code,
                                "fiscal_year": fiscal_year,
                                "document_type": document_type,
                                "source_file": pdf_path.name,
                                "source_pdf_page": source_page,
                                "table_count": None,
                                "record_count": 0,
                                "unresolved_count": 0,
                                "page_status": "TABLE_DETECTION_FAILED",
                                "error": str(exc),
                            }
                        )
                        continue
                    hierarchy = _page_hierarchy(page_texts, page_words, source_page)
                    common = _common_record(
                        ministry_code=ministry_code,
                        ministry_name=ministry_name,
                        fiscal_year=fiscal_year,
                        document_type=document_type,
                        source_file=pdf_path.name,
                        source_page=source_page,
                        printed_page=_display_page(text),
                        hierarchy=hierarchy,
                    )
                    before = len(records)
                    before_unresolved = len(unresolved)
                    for table in tables:
                        rows = table.extract()
                        if document_type == "PLAN":
                            parsed, pending = parse_plan_table(rows, common=common)
                            records.extend(parsed)
                            unresolved.extend(pending)
                        else:
                            records.extend(parse_report_table(rows, common=common))
                    added = len(records) - before
                    pending_added = len(unresolved) - before_unresolved
                    if added or pending_added:
                        page_audit.append(
                            {
                                "ministry_code": ministry_code,
                                "fiscal_year": fiscal_year,
                                "document_type": document_type,
                                "source_file": pdf_path.name,
                                "source_pdf_page": source_page,
                                "table_count": len(tables),
                                "record_count": added,
                                "unresolved_count": pending_added,
                                "page_status": "PARSED",
                                "error": None,
                            }
                        )
    return _deduplicate(records), unresolved, page_audit, source_hashes


def _same_number(left: Any, right: Any) -> bool:
    left_number, right_number = parse_numeric(left), parse_numeric(right)
    if left_number is None or right_number is None:
        return _clean_cell(left) == _clean_cell(right)
    return abs(left_number - right_number) <= 1e-9


def evaluate_discovery(discovered: pd.DataFrame, gold: pd.DataFrame) -> pd.DataFrame:
    lookup: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in discovered.to_dict("records"):
        key = (
            str(row["ministry_code"]).zfill(3),
            int(row["fiscal_year"]),
            row["document_type"],
            normalize_program_goal(row.get("program_goal_number")),
            normalize_indicator_name(row.get("indicator_name")),
        )
        lookup.setdefault(key, []).append(row)
    evaluations: list[dict[str, Any]] = []
    for row in gold.to_dict("records"):
        common = {
            "source_indicator_id": row["source_indicator_id"],
            "ministry_code": str(row["ministry_code"]).zfill(3),
            "fiscal_year": int(row["fiscal_year"]),
            "program_goal_number": row.get("program_goal_number"),
        }
        for document_type, name_field in (
            ("PLAN", "indicator_name_plan"),
            ("REPORT", "indicator_name_report"),
        ):
            expected_name = row.get(name_field)
            key = (
                common["ministry_code"],
                common["fiscal_year"],
                document_type,
                normalize_program_goal(common["program_goal_number"]),
                normalize_indicator_name(expected_name),
            )
            candidates = lookup.get(key, []) if normalize_indicator_name(expected_name) else []
            found = len(candidates) == 1
            candidate = candidates[0] if found else {}
            evaluation = {
                **common,
                "document_type": document_type,
                "expected_indicator_name": expected_name,
                "discovered": found,
                "candidate_count": len(candidates),
                "discovered_indicator_name": candidate.get("indicator_name"),
                "routing_status": candidate.get("routing_status"),
                "source_file": candidate.get("source_file"),
                "source_pdf_page": candidate.get("source_pdf_page"),
            }
            if document_type == "PLAN":
                expected, actual = (
                    row.get("planned_target_raw"),
                    candidate.get("planned_target_raw"),
                )
                evaluation["target_match"] = found and _same_number(expected, actual)
                evaluation["actual_match"] = None
                evaluation["rate_match"] = None
            else:
                evaluation["target_match"] = None
                expected_actual, actual = (
                    row.get("actual_value_raw"),
                    candidate.get("actual_value_raw"),
                )
                expected_rate, rate = (
                    row.get("official_achievement_rate_raw"),
                    candidate.get("official_achievement_rate_raw"),
                )
                evaluation["actual_match"] = (
                    found and _same_number(expected_actual, actual)
                    if pd.notna(expected_actual)
                    else None
                )
                evaluation["rate_match"] = (
                    found and _same_number(expected_rate, rate) if pd.notna(expected_rate) else None
                )
            evaluations.append(evaluation)
    return pd.DataFrame(evaluations)


def _load_ministries(root: Path, ministry_codes: tuple[str, ...]) -> list[tuple[str, str]]:
    config = yaml.safe_load((root / "configs/ministries.yaml").read_text(encoding="utf-8"))
    names = {str(item["code"]).zfill(3): str(item["name"]) for item in config["ministries"]}
    missing = [code for code in ministry_codes if code not in names]
    if missing:
        raise UnattendedPdfError(f"configs/ministries.yaml에 없는 부처코드입니다: {missing}")
    return [(code, names[code]) for code in ministry_codes]


def _gold_path(root: Path, ministry_code: str) -> Path:
    if ministry_code == "102":
        return root / "data/processed/performance/program_kpi_year.parquet"
    return (
        root
        / "data/processed/performance/by_ministry"
        / f"ministry_code={ministry_code}"
        / "program_kpi_year.parquet"
    )


def run_unattended_pdf_pilot(
    root: Path,
    *,
    ministry_codes: tuple[str, ...] = ("019", "075", "102", "162"),
    output_dir: Path | None = None,
    overwrite: bool = False,
) -> UnattendedPdfResult:
    root = root.resolve()
    ministry_codes = tuple(str(code).zfill(3) for code in ministry_codes)
    output_dir = output_dir or root / "data/processed/performance/unattended_pdf"
    targets = (
        output_dir / "discovered_records.parquet",
        output_dir / "page_audit.csv",
        output_dir / "unresolved_queue.csv",
        output_dir / "gold_evaluation.csv",
        output_dir / "summary.json",
    )
    existing = [path for path in targets if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(", ".join(str(path) for path in existing))

    all_records: list[dict[str, Any]] = []
    all_unresolved: list[dict[str, Any]] = []
    all_page_audit: list[dict[str, Any]] = []
    source_hashes_before: dict[str, str] = {}
    raw_dir = root / "data/raw/performance_docs"
    ministries = _load_ministries(root, ministry_codes)
    for code, name in ministries:
        records, unresolved, page_audit, source_hashes = extract_ministry_documents(
            raw_dir=raw_dir,
            ministry_code=code,
            ministry_name=name,
        )
        all_records.extend(records)
        all_unresolved.extend(unresolved)
        all_page_audit.extend(page_audit)
        source_hashes_before.update(source_hashes)

    for code, name in ministries:
        for year, paths in discover_documents(raw_dir, name).items():
            for document_type, source_path in paths.items():
                usable = any(
                    row["ministry_code"] == code
                    and int(row["fiscal_year"]) == year
                    and row["document_type"] == document_type
                    and row["routing_status"] == "LOCAL_CONFIRMED"
                    for row in all_records
                )
                if not usable:
                    all_unresolved.append(
                        {
                            "ministry_code": code,
                            "ministry_name": name,
                            "fiscal_year": year,
                            "document_type": document_type,
                            "source_file": source_path.name,
                            "routing_status": (
                                "OCR_REQUIRED" if document_type == "PLAN" else "LLM_REVIEW_REQUIRED"
                            ),
                            "routing_reason": "NO_LOCAL_CONFIRMED_DOCUMENT_RECORDS",
                        }
                    )

    # 골드셋은 전체 PDF 추출이 끝난 뒤 사후 채점에만 읽습니다.
    gold_frames: list[pd.DataFrame] = []
    for code in ministry_codes:
        path = _gold_path(root, code)
        frame = pd.read_parquet(path)
        frame["ministry_code"] = code
        gold_frames.append(frame)
    discovered = pd.DataFrame(all_records)
    gold = pd.concat(
        [frame.dropna(axis=1, how="all") for frame in gold_frames], ignore_index=True, sort=False
    )
    evaluation = evaluate_discovery(discovered, gold)
    page_audit = pd.DataFrame(all_page_audit)
    unresolved = pd.DataFrame(all_unresolved)
    source_hashes_after = {path: sha256_file(Path(path)) for path in source_hashes_before}
    hash_mismatches = {
        path: {"before": source_hashes_before[path], "after": source_hashes_after[path]}
        for path in source_hashes_before
        if source_hashes_before[path] != source_hashes_after[path]
    }

    def ratio(column: str) -> float | None:
        values = evaluation[column].dropna()
        return float(values.mean()) if len(values) else None

    def conditional_ratio(column: str) -> float | None:
        values = evaluation.loc[evaluation["discovered"], column].dropna()
        return float(values.mean()) if len(values) else None

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "ministry_codes": list(ministry_codes),
        "source_pdf_count": len(source_hashes_before),
        "source_hash_unchanged": not hash_mismatches,
        "source_hash_mismatches": hash_mismatches,
        "api_call_count": 0,
        "gold_loaded_after_extraction": True,
        "discovered_record_count": len(discovered),
        "discovered_by_document_type": dict(Counter(discovered["document_type"])),
        "routing_status_counts": dict(Counter(discovered["routing_status"])),
        "unresolved_row_count": len(unresolved),
        "gold_indicator_row_count": len(gold),
        "gold_document_row_count": len(evaluation),
        "strict_discovery_rate": ratio("discovered"),
        "strict_discovery_rate_by_document_type": {
            document_type: float(sub["discovered"].mean())
            for document_type, sub in evaluation.groupby("document_type")
        },
        "end_to_end_plan_target_accuracy": ratio("target_match"),
        "end_to_end_report_actual_accuracy": ratio("actual_match"),
        "end_to_end_report_rate_accuracy": ratio("rate_match"),
        "conditional_plan_target_accuracy": conditional_ratio("target_match"),
        "conditional_report_actual_accuracy": conditional_ratio("actual_match"),
        "conditional_report_rate_accuracy": conditional_ratio("rate_match"),
        "by_ministry": {},
        "interpretation_limit": (
            "골드셋은 사후 발견률·필드 일치율 평가에만 사용했습니다. 골드에 없는 추가 발견행은 "
            "오탐으로 판정하지 않았으며, 완전 무인 승격은 LOCAL_CONFIRMED 행도 문서 홀드아웃 검증 후에만 허용합니다."
        ),
    }
    for code in ministry_codes:
        sub = evaluation[evaluation["ministry_code"] == code]
        summary["by_ministry"][code] = {
            "gold_indicator_rows": int((gold["ministry_code"] == code).sum()),
            "document_rows": len(sub),
            "strict_discovery_rate": float(sub["discovered"].mean()) if len(sub) else None,
            "strict_discovery_rate_by_document_type": {
                document_type: float(document_sub["discovered"].mean())
                for document_type, document_sub in sub.groupby("document_type")
            },
            "conditional_plan_target_accuracy": float(
                sub.loc[sub["discovered"], "target_match"].dropna().mean()
            )
            if sub.loc[sub["discovered"], "target_match"].notna().any()
            else None,
            "conditional_report_actual_accuracy": float(
                sub.loc[sub["discovered"], "actual_match"].dropna().mean()
            )
            if sub.loc[sub["discovered"], "actual_match"].notna().any()
            else None,
            "conditional_report_rate_accuracy": float(
                sub.loc[sub["discovered"], "rate_match"].dropna().mean()
            )
            if sub.loc[sub["discovered"], "rate_match"].notna().any()
            else None,
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    discovered.to_parquet(targets[0], index=False)
    page_audit.to_csv(targets[1], index=False, encoding="utf-8-sig")
    unresolved.to_csv(targets[2], index=False, encoding="utf-8-sig")
    evaluation.to_csv(targets[3], index=False, encoding="utf-8-sig")
    targets[4].write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return UnattendedPdfResult(summary=summary, output_paths=targets)
