"""예산 API 원본을 추적 가능한 예산 레코드와 금액 이벤트로 정규화합니다."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .budget import DEFAULT_BUDGET_DATASET_IDS
from .config import DatasetConfig
from .normalize_monthly import parse_amount
from .response import parse_api_payload

DIMENSION_FIELD_MAP = {
    "OFFC_NM": "ministry_name",
    "FSCL_NM": "account_name",
    "ACCT_NM": "account_category_name",
    "FLD_NM": "field_name",
    "SECT_NM": "sector_name",
    "PGM_NM": "program_name",
    "ACTV_NM": "activity_name",
    "SACTV_NM": "subactivity_name",
    "CITM_NM": "item_name",
    "EITM_NM": "subitem_name",
    "BZ_CLS_NM": "business_class_name",
    "FIN_DE_EP_NM": "finance_detail_name",
}

MATCH_KEY = (
    "fiscal_year",
    "ministry_code",
    "account_name",
    "program_name",
    "activity_name",
    "subactivity_name",
)
PROJECT_NAME_KEY = ("fiscal_year", "ministry_code", "subactivity_name")
CODE_COLUMNS = ("account_code", "program_code", "activity_code", "subactivity_code")


@dataclass
class FailedFile:
    path: str
    error: str


@dataclass
class BudgetNormalizationResult:
    records: pd.DataFrame
    amount_events: pd.DataFrame
    issues: pd.DataFrame
    summary: dict[str, Any]
    failed_files: list[FailedFile] = field(default_factory=list)
    output_paths: list[Path] = field(default_factory=list)


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _year(value: Any) -> int | None:
    text = _text(value)
    return int(text) if text and text.isdigit() else None


def _partition_values(path: Path) -> dict[str, str]:
    return {part.split("=", 1)[0]: part.split("=", 1)[1] for part in path.parts if "=" in part}


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _digest(*values: Any) -> str:
    raw = "\x1f".join("" if value is None else str(value) for value in values)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def discover_budget_files(
    input_dir: Path,
    *,
    start_year: int | None = None,
    end_year: int | None = None,
    ministry_code: str | None = None,
    dataset_ids: set[str] | None = None,
) -> list[Path]:
    if not input_dir.exists():
        return []
    selected = dataset_ids or set(DEFAULT_BUDGET_DATASET_IDS)
    paths: list[Path] = []
    for path in sorted(input_dir.rglob("page_*.json")):
        parts = _partition_values(path)
        dataset_id = next(
            (value for value in DEFAULT_BUDGET_DATASET_IDS if value in path.parts),
            None,
        )
        if dataset_id not in selected:
            continue
        year_text = parts.get("year")
        if year_text and year_text.isdigit():
            year = int(year_text)
            if start_year is not None and year < start_year:
                continue
            if end_year is not None and year > end_year:
                continue
        if ministry_code is not None and parts.get("ministry_code") != ministry_code:
            continue
        paths.append(path)
    return paths


def _normalize_source_record(
    record: dict[str, Any],
    *,
    dataset: DatasetConfig,
    ministry_code: str | None,
    source_file: str,
    source_page: int | None,
    source_row: int,
    requested_at: str | None,
    source_url: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    fiscal_year = _year(record.get("FSCL_YY"))
    row: dict[str, Any] = {
        "table_id": "budget_record",
        "dataset_id": dataset.dataset_id,
        "fiscal_year": fiscal_year,
        "ministry_code": ministry_code,
        "supplementary_round": _text(record.get("SBUDG_DGR")),
        "budget_inquiry_basis_code": _text(record.get("ANEXP_INQ_STND_CD")),
        "source_file": source_file,
        "source_page": source_page,
        "source_row": source_row,
        "source_requested_at": requested_at,
        "source_url": source_url,
        "extraction_method": "api_json_normalize",
    }
    for source, target in DIMENSION_FIELD_MAP.items():
        row[target] = _text(record.get(source))

    entity_values = [row.get(column) for column in MATCH_KEY]
    row["entity_id"] = f"name:{_digest(*entity_values)}"
    row["entity_id_basis"] = "fiscal_year+ministry_code+account/program/activity/subactivity_name"
    row["source_record_id"] = (
        f"{dataset.dataset_id}:{_digest(source_file, source_page, source_row)}"
    )

    raw_amounts: dict[str, Any] = {}
    masked_fields: list[str] = []
    parse_failed_fields: list[str] = []
    amount_events: list[dict[str, Any]] = []
    for source_field in dataset.amount_fields:
        raw_value = record.get(source_field)
        raw_amounts[source_field] = raw_value
        amount, unparsed_raw, masked = parse_amount(raw_value)
        if masked:
            masked_fields.append(source_field)
        elif unparsed_raw is not None and amount is None:
            parse_failed_fields.append(source_field)
        source_unit_code = (
            "KCUR" if "KCUR" in source_field else "FRC" if "FRC" in source_field else None
        )
        amount_events.append(
            {
                "table_id": "amount_event",
                "entity_id": row["entity_id"],
                "source_record_id": row["source_record_id"],
                "dataset_id": dataset.dataset_id,
                "fiscal_year": fiscal_year,
                "ministry_code": ministry_code,
                "amount_type": source_field,
                "amount": amount,
                "raw_value": _text(raw_value),
                "is_masked": masked,
                "parse_failed": unparsed_raw is not None and amount is None and not masked,
                "source_unit_code": source_unit_code,
                "unit_confirmed": False,
                "source_field": source_field,
                "source_file": source_file,
                "source_page": source_page,
                "source_row": source_row,
                "confirmed_flag": False,
            }
        )
    row["amount_raw_values"] = json.dumps(raw_amounts, ensure_ascii=False)
    row["is_masked"] = bool(masked_fields)
    row["masked_fields"] = json.dumps(masked_fields, ensure_ascii=False)
    row["amount_parse_failed"] = bool(parse_failed_fields)
    row["parse_failed_fields"] = json.dumps(parse_failed_fields, ensure_ascii=False)
    row["schema_missing_fields"] = json.dumps(
        sorted(set(dataset.expected_fields) - set(record)),
        ensure_ascii=False,
    )
    return row, amount_events


def _load_monthly_lookup(path: Path | None) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame(columns=[*MATCH_KEY, *CODE_COLUMNS])
    columns = [*MATCH_KEY, *CODE_COLUMNS]
    frame = pd.read_parquet(path, columns=columns)
    for column in ("ministry_code", *CODE_COLUMNS):
        frame[column] = frame[column].astype("string")
    return frame.drop_duplicates()


def _unique_lookup(
    monthly: pd.DataFrame,
    keys: tuple[str, ...],
) -> tuple[pd.DataFrame, set[tuple[Any, ...]]]:
    if monthly.empty:
        return monthly, set()
    grouped = monthly.groupby(list(keys), dropna=False, sort=False)
    counts = grouped.size().rename("_candidate_count").reset_index()
    unique_keys = counts[counts["_candidate_count"] == 1].drop(columns="_candidate_count")
    unique = unique_keys.merge(monthly, how="left", on=list(keys)).drop_duplicates(list(keys))
    ambiguous = {
        tuple(row)
        for row in counts.loc[counts["_candidate_count"] > 1, list(keys)].itertuples(
            index=False, name=None
        )
    }
    return unique, ambiguous


def apply_code_matching(records: pd.DataFrame, monthly: pd.DataFrame) -> pd.DataFrame:
    frame = records.copy()
    for column in CODE_COLUMNS:
        frame[column] = pd.Series(pd.NA, index=frame.index, dtype="string")
    frame["matching_status"] = "NO_MATCH"

    if frame.empty or monthly.empty:
        frame["manual_review_required"] = True
        frame["review_status"] = "UNREVIEWED"
        return frame

    full_lookup, full_ambiguous = _unique_lookup(monthly, MATCH_KEY)
    project_lookup, project_ambiguous = _unique_lookup(monthly, PROJECT_NAME_KEY)

    full = frame[list(MATCH_KEY)].merge(
        full_lookup,
        how="left",
        on=list(MATCH_KEY),
        sort=False,
    )
    full.index = frame.index
    full_matched = full["subactivity_code"].notna()
    for column in CODE_COLUMNS:
        frame.loc[full_matched, column] = full.loc[full_matched, column]
    frame.loc[full_matched, "matching_status"] = "EXACT_HIERARCHY_UNIQUE"

    remaining = ~full_matched
    project = frame.loc[remaining, list(PROJECT_NAME_KEY)].merge(
        project_lookup,
        how="left",
        on=list(PROJECT_NAME_KEY),
        sort=False,
    )
    project.index = frame.index[remaining]
    project_matched = project["subactivity_code"].notna()
    for column in CODE_COLUMNS:
        frame.loc[project.index[project_matched], column] = project.loc[project_matched, column]
    frame.loc[project.index[project_matched], "matching_status"] = "EXACT_PROJECT_NAME_UNIQUE"

    def key_in_ambiguous(
        row: pd.Series, keys: tuple[str, ...], values: set[tuple[Any, ...]]
    ) -> bool:
        return tuple(row.get(key) for key in keys) in values

    still_unmatched = frame["matching_status"] == "NO_MATCH"
    ambiguous_mask = frame.loc[still_unmatched].apply(
        lambda row: (
            key_in_ambiguous(row, MATCH_KEY, full_ambiguous)
            or key_in_ambiguous(row, PROJECT_NAME_KEY, project_ambiguous)
        ),
        axis=1,
    )
    frame.loc[ambiguous_mask.index[ambiguous_mask], "matching_status"] = "MULTIPLE_MATCHES"
    frame["manual_review_required"] = (
        ~frame["matching_status"].isin({"EXACT_HIERARCHY_UNIQUE", "EXACT_PROJECT_NAME_UNIQUE"})
        | frame["is_masked"]
        | frame["amount_parse_failed"]
    )
    frame["review_status"] = "UNREVIEWED"
    return frame


def _add_duplicate_flags(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        frame["duplicate_key_flag"] = pd.Series(dtype=bool)
        return frame
    keys = [
        "dataset_id",
        "fiscal_year",
        "ministry_code",
        "account_name",
        "program_name",
        "activity_name",
        "subactivity_name",
        "item_name",
        "subitem_name",
        "supplementary_round",
    ]
    frame["duplicate_key_flag"] = frame.duplicated(keys, keep=False)
    frame["manual_review_required"] = frame["manual_review_required"] | frame["duplicate_key_flag"]
    return frame


def _issues(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "issue_type",
        "dataset_id",
        "fiscal_year",
        "ministry_code",
        "source_record_id",
        "matching_status",
        "source_file",
    ]
    issue_frames: list[pd.DataFrame] = []
    masks = {
        "CODE_MATCH_REVIEW": ~frame["matching_status"].isin(
            {"EXACT_HIERARCHY_UNIQUE", "EXACT_PROJECT_NAME_UNIQUE"}
        ),
        "MASKED_AMOUNT": frame["is_masked"],
        "AMOUNT_PARSE_FAILED": frame["amount_parse_failed"],
        "DUPLICATE_BUSINESS_KEY": frame["duplicate_key_flag"],
    }
    base_columns = [column for column in columns if column != "issue_type"]
    for issue_type, mask in masks.items():
        selected = frame.loc[mask, base_columns].copy()
        selected.insert(0, "issue_type", issue_type)
        issue_frames.append(selected)
    return (
        pd.concat(issue_frames, ignore_index=True)
        if issue_frames
        else pd.DataFrame(columns=columns)
    )


def normalize_budget(
    *,
    input_dir: Path,
    output_dir: Path,
    amount_event_output_dir: Path,
    datasets: dict[str, DatasetConfig],
    monthly_path: Path | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    ministry_code: str | None = None,
    dataset_ids: set[str] | None = None,
    overwrite: bool = False,
) -> BudgetNormalizationResult:
    paths = discover_budget_files(
        input_dir,
        start_year=start_year,
        end_year=end_year,
        ministry_code=ministry_code,
        dataset_ids=dataset_ids,
    )
    rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    failed: list[FailedFile] = []
    raw_record_count = 0
    for path in paths:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            metadata = document.get("metadata") or {}
            dataset_id = str(metadata.get("dataset_id") or "")
            dataset = datasets[dataset_id]
            parsed = parse_api_payload(
                document.get("response", document),
                service_name=dataset.service_name or dataset.dataset_id,
            )
            raw_record_count += len(parsed.records)
            parts = _partition_values(path)
            source_file = _relative(path, input_dir)
            source_page_raw = metadata.get("page_index")
            source_page = int(source_page_raw) if source_page_raw not in (None, "") else None
            for source_row, record in enumerate(parsed.records, start=1):
                if not isinstance(record, dict):
                    raise TypeError("API 레코드가 객체가 아닙니다.")
                row, events = _normalize_source_record(
                    record,
                    dataset=dataset,
                    ministry_code=parts.get("ministry_code"),
                    source_file=source_file,
                    source_page=source_page,
                    source_row=source_row,
                    requested_at=_text(metadata.get("requested_at")),
                    source_url=_text(metadata.get("api_url")),
                )
                rows.append(row)
                event_rows.extend(events)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            failed.append(FailedFile(str(path), str(exc)))

    records = pd.DataFrame(rows)
    amount_events = pd.DataFrame(event_rows)
    if not records.empty:
        records["fiscal_year"] = pd.to_numeric(records["fiscal_year"], errors="coerce").astype(
            "Int64"
        )
        records["source_page"] = pd.to_numeric(records["source_page"], errors="coerce").astype(
            "Int64"
        )
        records["source_row"] = pd.to_numeric(records["source_row"], errors="coerce").astype(
            "Int64"
        )
        records["ministry_code"] = records["ministry_code"].astype("string")
    if not amount_events.empty:
        amount_events["fiscal_year"] = pd.to_numeric(
            amount_events["fiscal_year"], errors="coerce"
        ).astype("Int64")
        amount_events["amount"] = pd.to_numeric(amount_events["amount"], errors="coerce").astype(
            "Int64"
        )
        amount_events["ministry_code"] = amount_events["ministry_code"].astype("string")

    records = apply_code_matching(records, _load_monthly_lookup(monthly_path))
    records = _add_duplicate_flags(records)
    issues = _issues(records)
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "files_read": len(paths),
        "raw_record_count": raw_record_count,
        "normalized_row_count": len(records),
        "raw_vs_normalized_difference": raw_record_count - len(records),
        "amount_event_count": len(amount_events),
        "masked_amount_event_count": (
            int(amount_events["is_masked"].sum()) if not amount_events.empty else 0
        ),
        "amount_parse_failure_count": (
            int(amount_events["parse_failed"].sum()) if not amount_events.empty else 0
        ),
        "duplicate_key_row_count": (
            int(records["duplicate_key_flag"].sum()) if not records.empty else 0
        ),
        "manual_review_row_count": (
            int(records["manual_review_required"].sum()) if not records.empty else 0
        ),
        "dataset_row_counts": (
            records["dataset_id"].value_counts(dropna=False).sort_index().to_dict()
            if not records.empty
            else {}
        ),
        "matching_status_counts": (
            records["matching_status"].value_counts(dropna=False).sort_index().to_dict()
            if not records.empty
            else {}
        ),
        "failed_files": [failed_file.__dict__ for failed_file in failed],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    amount_event_output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = [
        output_dir / "budget_records.parquet",
        output_dir / "normalization_summary.json",
        output_dir / "validation_issues.csv",
        output_dir / "manual_review.csv",
        amount_event_output_dir / "budget_amount_events.parquet",
    ]
    existing = [path for path in output_paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"출력 파일이 이미 있습니다: {existing[0]}")
    records.to_parquet(output_paths[0], index=False)
    output_paths[1].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    issues.to_csv(output_paths[2], index=False, encoding="utf-8-sig")
    records.loc[records["manual_review_required"]].to_csv(
        output_paths[3], index=False, encoding="utf-8-sig"
    )
    amount_events.to_parquet(output_paths[4], index=False)
    return BudgetNormalizationResult(
        records=records,
        amount_events=amount_events,
        issues=issues,
        summary=summary,
        failed_files=failed,
        output_paths=output_paths,
    )
