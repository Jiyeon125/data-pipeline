"""열린재정 공식 세부사업 설명자료에서 지원형태와 시행주체를 회수합니다."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import pandas as pd
import pymupdf

BASE_URL = "https://www.openfiscaldata.go.kr"
LIST_PAGE = f"{BASE_URL}/op/ko/bs/UOPKOBSA02"
LIST_ENDPOINT = f"{BASE_URL}/op/ko/bs/cls/selectSactvSearchList.do"
DOWNLOAD_ENDPOINT = f"{BASE_URL}/op/ko/cm/downloadFileSayBrkd.do"
DEFAULT_MINISTRIES = ("019", "075", "102", "162")
DEFAULT_YEARS = (2022, 2023, 2024)
PROJECT_KEY = (
    "fiscal_year",
    "ministry_code",
    "account_code",
    "program_code",
    "activity_code",
    "subactivity_code",
)
SUPPORT_FORMS = {
    "직접": "DIRECT",
    "출자": "EQUITY",
    "출연": "CONTRIBUTION",
    "보조": "SUBSIDY",
    "융자": "LOAN",
}
MOHW_2022_PDFS = (
    (
        "mohw_2022_general_account.pdf",
        "https://www.mohw.go.kr/boardDownload.es?bid=0037&list_no=369977&seq=1",
    ),
    (
        "mohw_2022_special_accounts_and_funds.pdf",
        "https://www.mohw.go.kr/boardDownload.es?bid=0037&list_no=369977&seq=2",
    ),
)


@dataclass
class OfficialSupportFormResult:
    summary: dict[str, Any]
    output_paths: list[Path]


def _digest(*values: Any) -> str:
    raw = "\x1f".join("" if pd.isna(value) else str(value).strip() for value in values)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_hwp_payload(payload: bytes) -> bool:
    return payload.startswith((b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", b"PK\x03\x04"))


def _normalize_code(value: Any, width: int | None = None) -> Any:
    if pd.isna(value) or not str(value).strip():
        return pd.NA
    text = str(value).strip()
    return text.zfill(width) if width else text


def _node_text(node: Any) -> str:
    if isinstance(node, dict):
        if isinstance(node.get("Text"), dict):
            return str(node["Text"].get("text", ""))
        return "".join(_node_text(value) for value in node.values())
    if isinstance(node, list):
        return "".join(_node_text(value) for value in node)
    return ""


def _text_fragments(node: Any) -> list[str]:
    fragments: list[str] = []
    if isinstance(node, dict):
        if isinstance(node.get("Text"), dict):
            text = str(node["Text"].get("text", "")).strip()
            if text:
                fragments.append(text)
        else:
            for value in node.values():
                fragments.extend(_text_fragments(value))
    elif isinstance(node, list):
        for value in node:
            fragments.extend(_text_fragments(value))
    return fragments


def _table_matrix(table: dict[str, Any]) -> list[list[str]]:
    return [
        [_node_text(cell.get("content", [])).strip() for cell in row.get("cells", [])]
        for row in table.get("rows", [])
    ]


def _support_evidence_from_method(method: str | None) -> dict[str, str]:
    if not method:
        return {}
    return {
        code: f"사업시행방법={method}" for label, code in SUPPORT_FORMS.items() if label in method
    }


def extract_official_fields(document: dict[str, Any]) -> dict[str, Any]:
    """구조가 보존된 HWP JSON에서 공식 필드만 추출합니다."""
    support_evidence: dict[str, str] = {}
    for section in document.get("sections", []):
        for block in section.get("content", []):
            table = block.get("Table") if isinstance(block, dict) else None
            if not isinstance(table, dict):
                continue
            matrix = _table_matrix(table)
            for row_index, header in enumerate(matrix[:-1]):
                normalized = [re.sub(r"\s+", "", cell) for cell in header]
                if not all(label in normalized for label in SUPPORT_FORMS):
                    continue
                values = matrix[row_index + 1]
                for label, code in SUPPORT_FORMS.items():
                    marker = values[normalized.index(label)].strip()
                    if marker and marker not in {"-", "해당없음"}:
                        support_evidence[code] = f"{label}={marker}"

    fragments = _text_fragments(document)
    implementation_method = None
    implementing_entity = None
    for fragment in fragments:
        method_match = re.search(r"사업\s*시행\s*방법\s*[:：]\s*(.+)", fragment)
        entity_match = re.search(r"사업\s*시행\s*주체\s*[:：]\s*(.+)", fragment)
        if method_match and implementation_method is None:
            implementation_method = method_match.group(1).strip()
        if entity_match and implementing_entity is None:
            implementing_entity = entity_match.group(1).strip()

    if not support_evidence:
        support_evidence = _support_evidence_from_method(implementation_method)

    forms = sorted(support_evidence)
    return {
        "support_forms": forms,
        "support_form_evidence": support_evidence,
        "implementation_method_raw": implementation_method,
        "implementing_entity_raw": implementing_entity,
    }


def _extract_mohw_2022_sections(page_texts: list[str]) -> list[dict[str, Any]]:
    starts: list[tuple[int, str, str]] = []
    for page_index, text in enumerate(page_texts):
        if not re.search(r"사\s*업\s*명", text):
            continue
        code = re.search(r"\(\s*(\d{3,5})\s*-\s*(\d{3})\s*\)", text)
        if code:
            starts.append((page_index, code.group(1), code.group(2)))

    sections: list[dict[str, Any]] = []
    for index, (start, activity_code, subactivity_code) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(page_texts)
        text = "\n".join(page_texts[start:end])
        method = re.search(r"사업\s*시행\s*방법\s*[:：]?\s*([^\r\n]+)", text)
        entity = re.search(r"사업\s*시행\s*주체\s*[:：]?\s*([^\r\n]+)", text)
        sections.append(
            {
                "activity_code": activity_code,
                "subactivity_code": subactivity_code,
                "implementation_method_raw": method.group(1).strip() if method else None,
                "implementing_entity_raw": entity.group(1).strip() if entity else None,
                "source_page_number": f"{start + 1}-{end}",
            }
        )
    return sections


def _recover_mohw_2022_pdfs(
    source: pd.DataFrame, documents_dir: Path
) -> tuple[pd.DataFrame, dict[str, int]]:
    scoped = source[
        source["ministry_code"].eq("075")
        & source["fiscal_year"].eq(2022)
        & source["activity_code"].notna()
        & source["subactivity_code"].notna()
    ][list(PROJECT_KEY)].drop_duplicates()
    keys_by_pair = {
        pair: group.to_dict("records")
        for pair, group in scoped.groupby(["activity_code", "subactivity_code"], dropna=False)
    }
    rows: list[dict[str, Any]] = []
    stats = {"sections": 0, "matched": 0, "ambiguous": 0, "unmatched": 0}
    supplemental_dir = documents_dir / "supplemental"
    supplemental_dir.mkdir(parents=True, exist_ok=True)

    for file_name, url in MOHW_2022_PDFS:
        path = supplemental_dir / file_name
        if not path.exists():
            with httpx.Client(timeout=120, follow_redirects=True) as client:
                response = client.get(url)
                response.raise_for_status()
                path.write_bytes(response.content)
        source_sha256 = _sha256(path)
        with pymupdf.open(path) as document:
            sections = _extract_mohw_2022_sections([page.get_text() for page in document])
        stats["sections"] += len(sections)
        for section in sections:
            pair = (section["activity_code"], section["subactivity_code"])
            candidates = keys_by_pair.get(pair, [])
            if len(candidates) != 1:
                stats["ambiguous" if candidates else "unmatched"] += 1
                continue
            stats["matched"] += 1
            method = section["implementation_method_raw"]
            evidence = _support_evidence_from_method(method)
            key = candidates[0]
            rows.append(
                {
                    **key,
                    "source_record_id": f"mohw22_{_digest(url, *pair)}",
                    "source_file_name": file_name,
                    "source_download_url": url,
                    "source_sha256": source_sha256,
                    "source_type": "MOHW_OFFICIAL_2022_PROJECT_DESCRIPTION_PDF",
                    "source_page_number": section["source_page_number"],
                    "support_forms": ";".join(sorted(evidence)),
                    "support_form_evidence": json.dumps(
                        evidence, ensure_ascii=False, sort_keys=True
                    ),
                    "implementation_method_raw": method,
                    "implementing_entity_raw": section["implementing_entity_raw"],
                    "recovery_status": (
                        "OFFICIAL_FIELDS_RECOVERED" if evidence else "NO_EXPLICIT_SUPPORT_FORM"
                    ),
                }
            )
    return pd.DataFrame(rows), stats


def _fetch_inventory(
    client: httpx.Client,
    ministry_codes: tuple[str, ...],
    fiscal_years: tuple[int, ...],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    client.get(LIST_PAGE).raise_for_status()
    for fiscal_year in fiscal_years:
        for ministry_code in ministry_codes:
            search = {
                "pageIndex": 1,
                "pageSize": "5000",
                "totalCnt": "0",
                "acntYr": str(fiscal_year),
                "offcCd": ministry_code,
                "acntCd": "",
                "fldCd": "",
                "sectCd": "",
                "sayNm": "",
                "chkoffcNm": "Y",
                "chkacntNm": "Y",
                "chkfldNm": "Y",
                "chksectNm": "Y",
                "chkpgmNm": "Y",
                "chkactvNm": "Y",
            }
            response = client.post(
                LIST_ENDPOINT,
                json={"opKoBsClsSerDVO": search},
                headers={"AJAX": "true", "Referer": LIST_PAGE},
            )
            response.raise_for_status()
            page = response.json().get("opKoBsClsSerDVOList") or []
            if page and int(page[0]["pageTotCnt"]) != len(page):
                raise RuntimeError(
                    f"공식 목록이 잘렸습니다: {fiscal_year=} {ministry_code=} "
                    f"expected={page[0]['pageTotCnt']} actual={len(page)}"
                )
            rows.extend(page)

    inventory = pd.DataFrame(rows).rename(
        columns={
            "acntYr": "fiscal_year",
            "offcCd": "ministry_code",
            "offcNm": "ministry_name",
            "acntCd": "account_code",
            "acntNm": "account_name",
            "pgmCd": "program_code",
            "pgmNm": "program_name",
            "actvCd": "activity_code",
            "actvNm": "activity_name",
            "sayCd": "subactivity_code",
            "sayNm": "subactivity_name",
            "sayBrkdFileNm": "source_file_name",
            "thyCfmtnMediAmt": "official_budget_million_krw",
        }
    )
    inventory["fiscal_year"] = pd.to_numeric(inventory["fiscal_year"], errors="raise")
    for column, width in (
        ("ministry_code", 3),
        ("account_code", 3),
        ("program_code", None),
        ("activity_code", None),
        ("subactivity_code", 3),
    ):
        inventory[column] = inventory[column].map(lambda value, w=width: _normalize_code(value, w))
    inventory["source_record_id"] = inventory.apply(
        lambda row: (
            f"ofd_{_digest(*(row.get(column) for column in PROJECT_KEY), row.get('source_file_name'))}"
        ),
        axis=1,
    )
    inventory["source_page_url"] = LIST_PAGE
    return inventory


def _download_url(row: pd.Series) -> str:
    display_name = f"{row['ministry_name']}_{row['subactivity_name']}".replace("/", "_")
    source_stem = Path(str(row["source_file_name"])).stem
    return (
        f"{DOWNLOAD_ENDPOINT}/{int(row['fiscal_year'])}/"
        f"{quote(display_name, safe='')}/{quote(source_stem, safe='')}"
    )


def _recover_document(row: pd.Series, documents_dir: Path, parser_exe: Path) -> dict[str, Any]:
    result = {column: row[column] for column in ("source_record_id", *PROJECT_KEY)}
    result["source_file_name"] = row.get("source_file_name")
    result["source_type"] = "OPENFISCAL_OFFICIAL_PROJECT_DESCRIPTION"
    if pd.isna(row.get("source_file_name")):
        return {**result, "recovery_status": "SOURCE_FILE_NOT_PUBLISHED"}

    path = documents_dir / f"{row['source_record_id']}.hwp"
    url = _download_url(row)
    result["source_download_url"] = url
    try:
        header = path.read_bytes()[:8] if path.exists() else b""
        if not _is_hwp_payload(header):
            with httpx.Client(timeout=60, follow_redirects=True) as client:
                response = client.get(url)
                response.raise_for_status()
                if not _is_hwp_payload(response.content[:8]):
                    raise RuntimeError(
                        "공식 다운로드 응답이 HWP/HWPX가 아닙니다: "
                        f"content_type={response.headers.get('content-type')}"
                    )
                path.write_bytes(response.content)
        result["source_sha256"] = _sha256(path)
        completed = subprocess.run(
            [str(parser_exe), "json", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        if completed.returncode:
            detail = (completed.stderr or completed.stdout).strip()[-400:]
            raise RuntimeError(f"unhwp exit={completed.returncode}: {detail}")
        fields = extract_official_fields(json.loads(completed.stdout))
        result.update(fields)
        result["support_forms"] = ";".join(fields["support_forms"])
        result["support_form_evidence"] = json.dumps(
            fields["support_form_evidence"], ensure_ascii=False, sort_keys=True
        )
        result["recovery_status"] = (
            "OFFICIAL_FIELDS_RECOVERED" if fields["support_forms"] else "NO_EXPLICIT_SUPPORT_FORM"
        )
    except (httpx.HTTPError, OSError, subprocess.SubprocessError, RuntimeError, ValueError) as exc:
        result["recovery_status"] = "RECOVERY_FAILED"
        result["recovery_error"] = f"{type(exc).__name__}: {exc}"[:500]
    return result


def _assertions(recovery: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for source in recovery.itertuples(index=False):
        base = {column: getattr(source, column) for column in ("source_record_id", *PROJECT_KEY)}
        evidence_raw = source.support_form_evidence
        evidence = json.loads(str(evidence_raw)) if pd.notna(evidence_raw) else {}
        forms_raw = str(source.support_forms) if pd.notna(source.support_forms) else ""
        for value in filter(None, forms_raw.split(";")):
            rows.append(
                {
                    **base,
                    "assertion_dimension": "SUPPORT_FORM",
                    "assertion_value": value,
                    "assertion_status": "OFFICIAL_EXPLICIT",
                    "evidence_quote": evidence.get(value),
                    "source_type": source.source_type,
                }
            )
        for dimension, value in (
            ("IMPLEMENTATION_METHOD", source.implementation_method_raw),
            ("IMPLEMENTING_ENTITY", source.implementing_entity_raw),
        ):
            if pd.notna(value) and str(value).strip():
                rows.append(
                    {
                        **base,
                        "assertion_dimension": dimension,
                        "assertion_value": str(value).strip(),
                        "assertion_status": "OFFICIAL_EXPLICIT",
                        "evidence_quote": f"{dimension}={str(value).strip()}",
                        "source_type": source.source_type,
                    }
                )
    columns = [
        "assertion_id",
        "source_record_id",
        *PROJECT_KEY,
        "assertion_dimension",
        "assertion_value",
        "assertion_status",
        "evidence_quote",
        "source_type",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    frame = pd.DataFrame(rows)
    frame["assertion_id"] = frame.apply(
        lambda row: (
            f"ast_{_digest(row['source_record_id'], row['assertion_dimension'], row['assertion_value'])}"
        ),
        axis=1,
    )
    return frame[columns]


def _project_year_classification(recovery: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for key, group in recovery.groupby(list(PROJECT_KEY), dropna=False, sort=True):
        forms = sorted(
            {
                value
                for raw in group["support_forms"].dropna().astype(str)
                for value in raw.split(";")
                if value
            }
        )
        methods = sorted(set(group["implementation_method_raw"].dropna().astype(str)))
        entities = sorted(set(group["implementing_entity_raw"].dropna().astype(str)))
        status = (
            "OFFICIAL_EXPLICIT_SINGLE"
            if len(forms) == 1
            else "OFFICIAL_EXPLICIT_MULTIPLE"
            if len(forms) > 1
            else "UNRESOLVED"
        )
        rows.append(
            {
                **dict(zip(PROJECT_KEY, key, strict=True)),
                "support_forms": ";".join(forms),
                "support_form_count": len(forms),
                "support_form_status": status,
                "peer_group_eligible": status == "OFFICIAL_EXPLICIT_SINGLE",
                "implementation_methods": ";".join(methods),
                "implementing_entities": ";".join(entities),
                "official_source_record_count": int(group["source_record_id"].nunique()),
                "recovered_document_count": int(
                    group["recovery_status"].eq("OFFICIAL_FIELDS_RECOVERED").sum()
                ),
            }
        )
    return pd.DataFrame(rows)


def recover_official_support_forms(
    *,
    source_observation_path: Path,
    output_dir: Path,
    documents_dir: Path,
    parser_exe: Path,
    ministry_codes: tuple[str, ...] = DEFAULT_MINISTRIES,
    fiscal_years: tuple[int, ...] = DEFAULT_YEARS,
    workers: int = 4,
    max_documents: int | None = None,
    overwrite: bool = False,
) -> OfficialSupportFormResult:
    """공식 목록과 HWP를 회수해 근거가 남는 분류 assertion을 생성합니다."""
    if not parser_exe.is_file():
        raise FileNotFoundError(f"unhwp 실행 파일이 없습니다: {parser_exe}")
    if not 1 <= workers <= 8:
        raise ValueError("workers는 1~8이어야 합니다.")

    outputs = {
        "inventory": output_dir / "official_project_description_inventory.parquet",
        "recovery": output_dir / "official_support_form_recovery.parquet",
        "assertion": output_dir / "classification_assertion.parquet",
        "project_year": output_dir / "project_year_official_classification.parquet",
        "coverage": output_dir / "coverage_by_ministry_year.csv",
        "summary": output_dir / "summary.json",
    }
    existing = [path for path in outputs.values() if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"공식 지원형태 산출물이 이미 있습니다: {existing[0]}")

    source = pd.read_parquet(source_observation_path)
    source = source[
        source["ministry_code"].astype("string").str.zfill(3).isin(ministry_codes)
        & pd.to_numeric(source["fiscal_year"], errors="coerce").isin(fiscal_years)
    ].copy()
    for column, width in (
        ("ministry_code", 3),
        ("account_code", 3),
        ("program_code", None),
        ("activity_code", None),
        ("subactivity_code", 3),
    ):
        source[column] = source[column].map(lambda value, w=width: _normalize_code(value, w))

    with httpx.Client(timeout=60, follow_redirects=True) as client:
        inventory = _fetch_inventory(client, ministry_codes, fiscal_years)
    source_keys = source[list(PROJECT_KEY)].drop_duplicates()
    inventory = inventory.merge(
        source_keys.assign(in_project_scope=True), on=list(PROJECT_KEY), how="left"
    )
    inventory["in_project_scope"] = inventory["in_project_scope"].eq(True)

    target = inventory[inventory["in_project_scope"]].copy()
    target = target.drop_duplicates("source_record_id")
    if max_documents is not None:
        target = target.head(max_documents)
    documents_dir.mkdir(parents=True, exist_ok=True)
    records = [row for _, row in target.iterrows()]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        recovery_rows = list(
            executor.map(lambda row: _recover_document(row, documents_dir, parser_exe), records)
        )
    recovery = pd.DataFrame(recovery_rows)
    supplemental_stats = {"sections": 0, "matched": 0, "ambiguous": 0, "unmatched": 0}
    if max_documents is None and "075" in ministry_codes and 2022 in fiscal_years:
        supplemental, supplemental_stats = _recover_mohw_2022_pdfs(source, documents_dir)
        recovery = pd.concat([recovery, supplemental], ignore_index=True, sort=False)
    for column in (
        "support_forms",
        "support_form_evidence",
        "implementation_method_raw",
        "implementing_entity_raw",
        "recovery_error",
    ):
        if column not in recovery:
            recovery[column] = pd.NA

    assertion = _assertions(recovery)
    project_year = _project_year_classification(recovery)
    joined = source.merge(project_year, on=list(PROJECT_KEY), how="left")
    joined["analysis_original_budget"] = pd.to_numeric(
        joined["analysis_original_budget"], errors="coerce"
    ).fillna(0)
    joined["official_single"] = joined["support_form_status"].eq("OFFICIAL_EXPLICIT_SINGLE")
    coverage = (
        joined.groupby(["ministry_code", "fiscal_year"], dropna=False)
        .agg(
            source_rows=("source_observation_id", "size"),
            official_single_rows=("official_single", "sum"),
            original_budget=("analysis_original_budget", "sum"),
            official_single_budget=(
                "analysis_original_budget",
                lambda values: values[joined.loc[values.index, "official_single"]].sum(),
            ),
        )
        .reset_index()
    )
    coverage["official_single_row_rate"] = (
        coverage["official_single_rows"] / coverage["source_rows"]
    )
    coverage["official_single_budget_rate"] = coverage["official_single_budget"] / coverage[
        "original_budget"
    ].replace(0, pd.NA)
    official_single_rows = int(joined["official_single"].sum())
    source_budget = float(joined["analysis_original_budget"].sum())
    official_single_budget = float(
        joined.loc[joined["official_single"], "analysis_original_budget"].sum()
    )
    joined["source_support_form_status"] = joined["support_form_status"].fillna(
        "NO_OFFICIAL_KEY_MATCH"
    )
    source_status = {
        str(status): {
            "rows": len(group),
            "row_rate": len(group) / len(joined) if len(joined) else None,
            "original_budget": float(group["analysis_original_budget"].sum()),
            "budget_rate": (
                float(group["analysis_original_budget"].sum()) / source_budget
                if source_budget
                else None
            ),
        }
        for status, group in joined.groupby("source_support_form_status", dropna=False)
    }

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {"ministries": list(ministry_codes), "fiscal_years": list(fiscal_years)},
        "source_observation_rows": len(source),
        "official_inventory_rows": len(inventory),
        "official_inventory_unique_project_year_keys": int(
            inventory[list(PROJECT_KEY)].drop_duplicates().shape[0]
        ),
        "official_list_key_matched_rows": int(inventory["in_project_scope"].sum()),
        "official_source_file_missing": int(inventory["source_file_name"].isna().sum()),
        "in_scope_official_source_file_missing": int(
            (inventory["in_project_scope"] & inventory["source_file_name"].isna()).sum()
        ),
        "mohw_2022_supplemental_pdf": supplemental_stats,
        "documents_attempted": len(recovery),
        "documents_recovered": int(
            recovery["recovery_status"].eq("OFFICIAL_FIELDS_RECOVERED").sum()
        ),
        "documents_failed": int(recovery["recovery_status"].eq("RECOVERY_FAILED").sum()),
        "project_year_official_single": int(
            project_year["support_form_status"].eq("OFFICIAL_EXPLICIT_SINGLE").sum()
        ),
        "project_year_official_multiple": int(
            project_year["support_form_status"].eq("OFFICIAL_EXPLICIT_MULTIPLE").sum()
        ),
        "project_year_unresolved": int(project_year["support_form_status"].eq("UNRESOLVED").sum()),
        "official_single_source_rows": official_single_rows,
        "official_single_row_rate": official_single_rows / len(joined) if len(joined) else None,
        "source_original_budget": source_budget,
        "official_single_original_budget": official_single_budget,
        "official_single_budget_rate": (
            official_single_budget / source_budget if source_budget else None
        ),
        "source_rows_by_support_form_status": source_status,
        "peer_group_rule": "OFFICIAL_EXPLICIT_SINGLE_ONLY",
        "unresolved_rule": "KEEP_UNKNOWN_NOT_DIRECT",
        "parser": {"name": "unhwp", "path": str(parser_exe), "sha256": _sha256(parser_exe)},
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    inventory.to_parquet(outputs["inventory"], index=False)
    recovery.to_parquet(outputs["recovery"], index=False)
    assertion.to_parquet(outputs["assertion"], index=False)
    project_year.to_parquet(outputs["project_year"], index=False)
    coverage.to_csv(outputs["coverage"], index=False, encoding="utf-8-sig")
    outputs["summary"].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return OfficialSupportFormResult(summary=summary, output_paths=list(outputs.values()))
