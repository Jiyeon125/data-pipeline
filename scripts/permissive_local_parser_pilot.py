"""Run the local, LLM-free PDF parser pilot."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import time
from collections import defaultdict
from difflib import SequenceMatcher
from importlib import metadata
from pathlib import Path
from typing import Any

RESTRICTED = ("AGPL", "GPL", "NON-COMMERCIAL", "RESEARCH ONLY")
CONDITIONAL = ("LGPL", "MPL")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _classify_license_text(upper: str) -> tuple[list[str], list[str]]:
    restricted = [token for token in RESTRICTED if token != "GPL" and token in upper]
    if re.search(r"(?<![A-Z])GPL", upper):
        restricted.append("GPL")
    conditional = [token for token in CONDITIONAL if token in upper]
    return restricted, conditional


def audit_licenses(output: Path) -> int:
    rows: list[dict[str, Any]] = []
    for dist in sorted(metadata.distributions(), key=lambda item: item.metadata["Name"].lower()):
        expression = dist.metadata.get("License-Expression") or ""
        license_text = dist.metadata.get("License") or ""
        classifiers = " | ".join(
            value
            for value in dist.metadata.get_all("Classifier", [])
            if value.startswith("License ::")
        )
        concise = expression or classifiers or license_text.splitlines()[0][:160]
        upper = f"{expression} {classifiers} {license_text.splitlines()[0] if license_text else ''}".upper()
        restricted, conditional = _classify_license_text(upper)
        rows.append(
            {
                "package": dist.metadata["Name"],
                "version": dist.version,
                "license_expression": expression,
                "license_summary": concise,
                "gate": (
                    "RESTRICTED_REVIEW"
                    if restricted
                    else "CONDITIONAL_DISTRIBUTION_COMPLIANCE"
                    if conditional
                    else "REVIEWED_NO_RESTRICTED_METADATA"
                ),
                "restricted_tokens": ",".join(restricted),
                "conditional_tokens": ",".join(conditional),
            }
        )
    _write_csv(output, rows)
    print(
        json.dumps(
            {
                "packages": len(rows),
                "restricted": [r for r in rows if r["restricted_tokens"]],
                "conditional": [r for r in rows if r["conditional_tokens"]],
            },
            ensure_ascii=False,
        )
    )
    return int(any(row["restricted_tokens"] for row in rows))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _as_int(value: Any) -> int:
    return int(float(value))


def build_manifest(root: Path, output_dir: Path) -> None:
    from pypdf import PdfReader, PdfWriter

    audit = _read_csv(root / "data/processed/performance/unattended_pdf/page_audit.csv")
    unresolved = _read_csv(root / "data/processed/performance/unattended_pdf/unresolved_queue.csv")
    source_root = root / "data/raw/performance_docs"
    selected: list[dict[str, Any]] = []
    keys: set[tuple[str, int]] = set()

    def add(row: dict[str, Any], stratum: str) -> bool:
        page = _as_int(row["source_pdf_page"])
        key = (row["source_file"], page)
        if key in keys:
            return False
        keys.add(key)
        selected.append({**row, "source_pdf_page": page, "stratum": stratum})
        return True

    parsed = [r for r in audit if r["page_status"] == "PARSED" and _as_int(r["record_count"]) > 0]
    ministries = sorted({_as_int(r["ministry_code"]) for r in parsed})
    for ministry in ministries:
        for document_type in ("PLAN", "REPORT"):
            pool = [
                r
                for r in parsed
                if _as_int(r["ministry_code"]) == ministry and r["document_type"] == document_type
            ]
            if pool:
                add(
                    min(
                        pool,
                        key=lambda r: (-_as_int(r["fiscal_year"]), _as_int(r["source_pdf_page"])),
                    ),
                    "NORMAL",
                )

    for row in unresolved:
        if row.get("source_pdf_page"):
            add(row, "OCR_REQUIRED")

    for ministry in ministries:
        pool = [r for r in parsed if _as_int(r["ministry_code"]) == ministry]
        pool.sort(
            key=lambda r: (
                -_as_int(r["table_count"]),
                -_as_int(r["record_count"]),
                _as_int(r["source_pdf_page"]),
            )
        )
        for row in pool:
            if add(row, "COMPLEX_TABLE"):
                break

    readers: dict[str, PdfReader] = {}
    low_text: list[tuple[int, dict[str, Any]]] = []
    for row in parsed:
        key = (row["source_file"], _as_int(row["source_pdf_page"]))
        if key in keys:
            continue
        reader = readers.setdefault(row["source_file"], PdfReader(source_root / row["source_file"]))
        text = reader.pages[key[1] - 1].extract_text() or ""
        low_text.append((len(text.strip()), row))
    for _, row in sorted(low_text, key=lambda item: (item[0], item[1]["source_file"])):
        if len(selected) >= 18:
            break
        add(row, "LOW_TEXT")

    if len(selected) != 18:
        raise RuntimeError(f"동결 표본은 18쪽이어야 합니다: {len(selected)}")

    pages_dir = output_dir / "pages"
    manifest: list[dict[str, Any]] = []
    for index, row in enumerate(selected, start=1):
        source = source_root / row["source_file"]
        page = _as_int(row["source_pdf_page"])
        reader = readers.setdefault(row["source_file"], PdfReader(source))
        writer = PdfWriter()
        writer.add_page(reader.pages[page - 1])
        page_id = f"p{index:02d}_{_as_int(row['ministry_code']):03d}_{_as_int(row['fiscal_year'])}_{row['document_type']}_{page}"
        output_pdf = pages_dir / f"{page_id}.pdf"
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        with output_pdf.open("wb") as handle:
            writer.write(handle)
        text = reader.pages[page - 1].extract_text() or ""
        manifest.append(
            {
                "page_id": page_id,
                "stratum": row["stratum"],
                "ministry_code": f"{_as_int(row['ministry_code']):03d}",
                "fiscal_year": _as_int(row["fiscal_year"]),
                "document_type": row["document_type"],
                "source_file": row["source_file"],
                "source_pdf_page": page,
                "source_pdf_sha256": _sha256(source),
                "input_pdf": str(output_pdf.relative_to(root)),
                "input_pdf_sha256": _sha256(output_pdf),
                "pdf_text_chars": len(text.strip()),
            }
        )
    _write_csv(output_dir / "manifest.csv", manifest)
    print(
        json.dumps(
            {"pages": len(manifest), "strata": dict(_counts(manifest, "stratum"))},
            ensure_ascii=False,
        )
    )


def _counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[str(row[key])] += 1
    return counts


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _validated_manifest(root: Path, output_dir: Path) -> list[dict[str, str]]:
    manifest = _read_csv(output_dir / "manifest.csv")
    for row in manifest:
        if _sha256(root / row["input_pdf"]) != row["input_pdf_sha256"]:
            raise RuntimeError(f"동결 1쪽 PDF 해시가 달라졌습니다: {row['input_pdf']}")
        source = root / "data/raw/performance_docs" / row["source_file"]
        if _sha256(source) != row["source_pdf_sha256"]:
            raise RuntimeError(f"원본 PDF 해시가 달라졌습니다: {source}")
    return manifest


def _count_grounded_nodes(value: Any) -> tuple[int, int]:
    if isinstance(value, list):
        counts = [_count_grounded_nodes(item) for item in value]
    elif isinstance(value, dict):
        own = (1, int(bool(value.get("bounding box")))) if value.get("type") else (0, 0)
        counts = [
            _count_grounded_nodes(item) for item in value.values() if isinstance(item, (dict, list))
        ]
        return own[0] + sum(count[0] for count in counts), own[1] + sum(
            count[1] for count in counts
        )
    else:
        return 0, 0
    return sum(count[0] for count in counts), sum(count[1] for count in counts)


def _chunks(rows: list[dict[str, str]], size: int = 80) -> list[list[dict[str, str]]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def run_opendataloader(root: Path, output_dir: Path) -> None:
    import psutil

    manifest = _validated_manifest(root, output_dir)
    parser_dir = output_dir / "opendataloader"
    raw_dir = parser_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    java_homes = sorted((root / ".pilot_envs/java").glob("*-jre"))
    executable = root / ".pilot_envs/opendataloader/Scripts/opendataloader-pdf.exe"
    if not java_homes or not executable.is_file():
        raise RuntimeError("격리 Java 또는 OpenDataLoader 실행파일이 없습니다.")
    env = {**os.environ, "JAVA_HOME": str(java_homes[-1])}
    env["PATH"] = f"{java_homes[-1] / 'bin'}{os.pathsep}{env['PATH']}"
    started = time.perf_counter()
    peak_ram = 0
    stdout_parts: list[bytes] = []
    stderr_parts: list[bytes] = []
    returncodes: list[int] = []
    batches = _chunks(manifest)
    for batch in batches:
        command = [
            str(executable),
            *(str(root / row["input_pdf"]) for row in batch),
            "-o",
            str(raw_dir),
            "-f",
            "json,markdown",
            "--image-output",
            "off",
            "--table-method",
            "cluster",
            "--threads",
            "1",
            "-q",
        ]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        parent = psutil.Process(process.pid)
        while process.poll() is None:
            try:
                processes = [parent, *parent.children(recursive=True)]
                peak_ram = max(peak_ram, sum(item.memory_info().rss for item in processes))
            except psutil.Error:
                pass
            time.sleep(0.05)
        stdout, stderr = process.communicate()
        stdout_parts.append(stdout)
        stderr_parts.append(stderr)
        returncodes.append(process.returncode)
    elapsed = time.perf_counter() - started
    (parser_dir / "stdout.txt").write_bytes(b"\n".join(stdout_parts))
    (parser_dir / "stderr.txt").write_bytes(b"\n".join(stderr_parts))
    batch_returncode = next((code for code in returncodes if code), 0)
    rows: list[dict[str, Any]] = []
    for page in manifest:
        stem = Path(page["input_pdf"]).stem
        markdown_path = raw_dir / f"{stem}.md"
        json_path = raw_dir / f"{stem}.json"
        status = "SUCCESS" if markdown_path.is_file() and json_path.is_file() else "FAILED"
        text = markdown_path.read_text(encoding="utf-8") if markdown_path.is_file() else ""
        (raw_dir / f"{page['page_id']}.txt").write_text(text, encoding="utf-8")
        payload = json.loads(json_path.read_text(encoding="utf-8")) if json_path.is_file() else {}
        nodes, grounded_nodes = _count_grounded_nodes(payload)
        rows.append(
            {
                **page,
                "parser_name": "OpenDataLoader PDF",
                "parser_version": "2.5.0",
                "model_revision": "fast-java-cluster",
                "status": status,
                "error": "" if status == "SUCCESS" else f"batch_returncode={batch_returncode}",
                "detected_items": nodes,
                "grounded_items": grounded_nodes,
                "text_chars": len(text),
                "elapsed_seconds_amortized": round(elapsed / len(manifest), 3),
                "process_peak_ram_mb": round(peak_ram / 1024 / 1024, 3),
                "external_llm_api_calls": 0,
            }
        )
    _write_csv(parser_dir / "parser_results.csv", rows)
    _write_json(
        parser_dir / "run_summary.json",
        {
            "parser": "OpenDataLoader PDF",
            "version": "2.5.0",
            "pages": len(rows),
            "success": sum(row["status"] == "SUCCESS" for row in rows),
            "elapsed_seconds": round(elapsed, 3),
            "peak_ram_mb": round(peak_ram / 1024 / 1024, 3),
            "batch_count": len(batches),
            "batch_returncode": batch_returncode,
            "external_llm_api_calls": 0,
        },
    )
    print((parser_dir / "run_summary.json").read_text(encoding="utf-8"))


def _norm(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", value).lower()


def _partial_similarity(needle: str, haystack: str) -> float:
    needle, haystack = _norm(needle), _norm(haystack)
    if not needle or not haystack:
        return 0.0
    if needle in haystack:
        return 1.0
    window = len(needle)
    return max(
        SequenceMatcher(None, needle, haystack[index : index + window]).ratio()
        for index in range(max(1, len(haystack) - window + 1))
    )


def _clean_expected(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text in {"", "<NA>", "nan", "None"} else text


def _load_reference_rows(root: Path) -> dict[tuple[str, int], dict[str, Any]]:
    import pandas as pd

    paths = (
        root / "data/processed/performance/by_ministry/ministry_code=019/program_kpi_year.parquet",
        root / "data/processed/performance/by_ministry/ministry_code=075/program_kpi_year.parquet",
        root / "data/processed/performance/program_kpi_year.parquet",
        root / "data/processed/performance/by_ministry/ministry_code=162/program_kpi_year.parquet",
    )
    references: dict[tuple[str, int], dict[str, Any]] = {}
    for path in paths:
        for row in pd.read_parquet(path).to_dict("records"):
            references[(str(row["source_indicator_id"]), int(row["fiscal_year"]))] = row
    return references


def _node_text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(filter(None, (_node_text(item) for item in value)))
    if isinstance(value, dict):
        return str(value.get("content") or _node_text(value.get("kids", []))).strip()
    return ""


def _opendataloader_table_rows(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    tables: list[dict[str, Any]] = []

    def collect(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            if value.get("type") == "table":
                tables.append(value)
            for item in value.values():
                if isinstance(item, (dict, list)):
                    collect(item)

    collect(payload)
    expanded: list[str] = []
    for table in tables:
        row_count = int(table.get("number of rows", 0))
        column_count = int(table.get("number of columns", 0))
        matrix = [["" for _ in range(column_count)] for _ in range(row_count)]
        for row in table.get("rows", []):
            for cell in row.get("cells", []):
                text = _node_text(cell)
                row_start = int(cell.get("row number", 1)) - 1
                column_start = int(cell.get("column number", 1)) - 1
                for row_index in range(row_start, row_start + int(cell.get("row span", 1))):
                    for column_index in range(
                        column_start, column_start + int(cell.get("column span", 1))
                    ):
                        if row_index < row_count and column_index < column_count:
                            matrix[row_index][column_index] = text
        expanded.extend(" | ".join(row) for row in matrix)
    return expanded


def _parser_rows(parser_name: str, parser_dir: Path, page_id: str) -> list[str]:
    text = (parser_dir / "raw" / f"{page_id}.txt").read_text(encoding="utf-8")
    rows = [line.strip() for line in text.splitlines() if line.strip()]
    if parser_name == "opendataloader":
        rows.extend(_opendataloader_table_rows(parser_dir / "raw" / f"{page_id}.json"))
    return rows


def _same_row_matches(
    indicator: str, expected_values: dict[str, str], rows: list[str]
) -> dict[str, bool]:
    indicator_rows = [row for row in rows if _partial_similarity(indicator, row) >= 0.8]
    return {
        name: bool(value) and any(_norm(value) in _norm(row) for row in indicator_rows)
        for name, value in expected_values.items()
    }


def evaluate_parser(root: Path, output_dir: Path, parser_name: str) -> None:
    manifest = _read_csv(output_dir / "manifest.csv")
    parser_dir = output_dir / parser_name
    results = {row["page_id"]: row for row in _read_csv(parser_dir / "parser_results.csv")}
    gold = _read_csv(root / "data/processed/performance/unattended_pdf/gold_evaluation.csv")
    references = _load_reference_rows(root)
    evaluations: list[dict[str, Any]] = []
    for page in manifest:
        result = results.get(page["page_id"])
        if result is None or not result["status"].startswith("SUCCESS"):
            continue
        text = (parser_dir / "raw" / f"{page['page_id']}.txt").read_text(encoding="utf-8")
        expected = {
            (row["source_indicator_id"], row["expected_indicator_name"])
            for row in gold
            if row["source_file"] == page["source_file"]
            and row["source_pdf_page"]
            and _as_int(row["source_pdf_page"]) == _as_int(page["source_pdf_page"])
        }
        parser_rows = _parser_rows(parser_name, parser_dir, page["page_id"])
        for source_indicator_id, indicator in sorted(expected):
            similarity = _partial_similarity(indicator, text)
            best_row = max(
                parser_rows,
                key=lambda value: _partial_similarity(indicator, value),
                default="",
            )
            reference = references.get((source_indicator_id, _as_int(page["fiscal_year"])), {})
            expected_values = (
                {"planned_target": _clean_expected(reference.get("planned_target_raw"))}
                if page["document_type"] == "PLAN"
                else {
                    "actual_value": _clean_expected(reference.get("actual_value_raw")),
                    "achievement_rate": _clean_expected(
                        reference.get("official_achievement_rate_raw")
                    ),
                }
            )
            value_matches = _same_row_matches(indicator, expected_values, parser_rows)
            evaluations.append(
                {
                    "parser_name": parser_name,
                    "page_id": page["page_id"],
                    "stratum": page["stratum"],
                    "source_indicator_id": source_indicator_id,
                    "expected_indicator_name": indicator,
                    "normalized_contains": _norm(indicator) in _norm(text),
                    "best_partial_similarity": round(similarity, 3),
                    "exploratory_similarity_ge_0_8": similarity >= 0.8,
                    "best_row": best_row,
                    "best_row_indicator_similarity": round(
                        _partial_similarity(indicator, best_row), 3
                    ),
                    "expected_planned_target": expected_values.get("planned_target", ""),
                    "expected_actual_value": expected_values.get("actual_value", ""),
                    "expected_achievement_rate": expected_values.get("achievement_rate", ""),
                    "planned_target_same_row": value_matches.get("planned_target", ""),
                    "actual_value_same_row": value_matches.get("actual_value", ""),
                    "achievement_rate_same_row": value_matches.get("achievement_rate", ""),
                }
            )
    _write_csv(parser_dir / "indicator_name_evaluation.csv", evaluations)
    matched = sum(str(row["normalized_contains"]).lower() == "true" for row in evaluations)
    fuzzy = sum(str(row["exploratory_similarity_ge_0_8"]).lower() == "true" for row in evaluations)
    assessed_values = [
        value
        for row in evaluations
        for value in (
            row["planned_target_same_row"],
            row["actual_value_same_row"],
            row["achievement_rate_same_row"],
        )
        if value != ""
    ]
    failed_pages = [
        row["page_id"] for row in results.values() if not row["status"].startswith("SUCCESS")
    ]
    fallback_pages = [
        row["page_id"] for row in results.values() if row["status"] == "SUCCESS_FALLBACK_NO_OCR"
    ]
    summary = {
        "parser": parser_name,
        "pages": len(results),
        "failed_pages": failed_pages,
        "fallback_no_ocr_pages": fallback_pages,
        "expected_indicator_names": len(evaluations),
        "exact_normalized_matches": matched,
        "exact_rate": matched / len(evaluations) if evaluations else None,
        "similarity_ge_0_8": fuzzy,
        "similarity_rate": fuzzy / len(evaluations) if evaluations else None,
        "same_row_value_fields_assessed": len(assessed_values),
        "same_row_value_fields_matched": sum(assessed_values),
        "same_row_value_field_rate": (
            sum(assessed_values) / len(assessed_values) if assessed_values else None
        ),
    }
    _write_json(parser_dir / "evaluation_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=(
            "audit",
            "manifest",
            "run-opendataloader",
            "evaluate-parser",
        ),
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path("data/interim/parser_pilot"))
    parser.add_argument("--parser", choices=("docling", "opendataloader"))
    args = parser.parse_args()
    if args.command == "audit":
        raise SystemExit(audit_licenses(args.output_dir / "minimal_license_inventory.csv"))
    if args.command == "manifest":
        build_manifest(args.root, args.output_dir)
    elif args.command == "run-opendataloader":
        run_opendataloader(args.root, args.output_dir)
    elif args.command == "evaluate-parser":
        if args.parser is None:
            parser.error("evaluate-parser에는 --parser가 필요합니다.")
        evaluate_parser(args.root, args.output_dir, args.parser)


if __name__ == "__main__":
    main()
