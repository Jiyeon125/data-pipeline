"""로컬 사업별 결산 CSV를 비파괴 정규화합니다."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .config import Ministry
from .normalize_budget import CODE_COLUMNS, MATCH_KEY, apply_code_matching
from .normalize_monthly import parse_amount

REQUIRED_COLUMNS = (
    "No.",
    "회계연도",
    "소관명",
    "회계코드명",
    "계정명",
    "분야명",
    "부문명",
    "프로그램명",
    "단위사업명",
    "세부사업명",
    "세출예산금액",
    "증감액",
    "세출예산현액",
    "지출금액",
    "지출순액",
    "차년도이월금액",
    "불용금액",
)
AMOUNT_COLUMNS = {
    "세출예산금액": "settlement_budget_amount",
    "증감액": "settlement_adjustment_amount",
    "세출예산현액": "settlement_current_budget_amount",
    "지출금액": "settlement_expenditure_amount",
    "지출순액": "settlement_net_expenditure_amount",
    "차년도이월금액": "settlement_carryover_amount",
    "불용금액": "settlement_unused_amount",
}
NAME_COLUMNS = {
    "소관명": "ministry_name",
    "회계코드명": "account_name",
    "계정명": "account_category_name",
    "분야명": "field_name",
    "부문명": "sector_name",
    "프로그램명": "program_name",
    "단위사업명": "activity_name",
    "세부사업명": "subactivity_name",
}


@dataclass
class SettlementNormalizationResult:
    records: pd.DataFrame
    issues: pd.DataFrame
    summary: dict[str, Any]
    output_paths: list[Path]


def _digest(*values: Any) -> str:
    raw = "\x1f".join("" if value is None else str(value) for value in values)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _read_csv(path: Path) -> tuple[pd.DataFrame, str]:
    errors: list[str] = []
    for encoding in ("utf-8-sig", "cp949", "utf-16"):
        try:
            return pd.read_csv(path, encoding=encoding, dtype=str), encoding
        except (UnicodeDecodeError, pd.errors.ParserError) as exc:
            errors.append(f"{encoding}:{type(exc).__name__}")
    raise ValueError(f"CSV 인코딩을 확인할 수 없습니다: {path}; {errors}")


def _monthly_lookup(path: Path) -> pd.DataFrame:
    columns = [*MATCH_KEY, *CODE_COLUMNS]
    frame = pd.read_parquet(path, columns=columns)
    frame["fiscal_year"] = pd.to_numeric(frame["fiscal_year"], errors="coerce").astype("Int64")
    for column in ("ministry_code", *CODE_COLUMNS):
        frame[column] = frame[column].astype("string")
    return frame.drop_duplicates()


def _project_id(row: pd.Series) -> str:
    code_values = [
        row.get("fiscal_year"),
        row.get("ministry_code"),
        row.get("account_code"),
        row.get("program_code"),
        row.get("activity_code"),
        row.get("subactivity_code"),
    ]
    if all(pd.notna(value) and str(value) for value in code_values):
        return "code:" + ":".join(str(value) for value in code_values)
    name_values = [row.get(column) for column in MATCH_KEY]
    return f"name:{_digest(*name_values)}"


def _json_counts(series: pd.Series) -> dict[str, int]:
    return {
        str(key): int(value)
        for key, value in series.value_counts(dropna=False).sort_index().items()
    }


def normalize_settlement(
    *,
    input_dir: Path,
    output_dir: Path,
    ministries: dict[str, Ministry],
    monthly_path: Path,
    overwrite: bool = False,
) -> SettlementNormalizationResult:
    paths = sorted(input_dir.glob("사업별결산세출지출현황_*.csv"))
    if not paths:
        raise FileNotFoundError(f"결산 CSV를 찾을 수 없습니다: {input_dir}")

    ministry_name_to_code = {item.name: item.code for item in ministries.values()}
    normalized_parts: list[pd.DataFrame] = []
    inventory: list[dict[str, Any]] = []
    full_input_count = 0
    for path in paths:
        raw, encoding = _read_csv(path)
        missing = sorted(set(REQUIRED_COLUMNS) - set(raw.columns))
        if missing:
            raise ValueError(f"{path.name} 필수 컬럼 누락: {missing}")
        full_input_count += len(raw)
        year_values = sorted(raw["회계연도"].dropna().unique().tolist())
        inventory.append(
            {
                "source_file": path.name,
                "size_bytes": path.stat().st_size,
                "encoding": encoding,
                "row_count": len(raw),
                "column_count": len(raw.columns),
                "fiscal_year_values": year_values,
            }
        )
        selected = raw[raw["소관명"].isin(ministry_name_to_code)].copy()
        frame = pd.DataFrame(
            {
                "table_id": "project_settlement",
                "source_row_number": pd.to_numeric(selected["No."], errors="coerce").astype(
                    "Int64"
                ),
                "fiscal_year": pd.to_numeric(selected["회계연도"], errors="coerce").astype("Int64"),
                "ministry_code": selected["소관명"].map(ministry_name_to_code).astype("string"),
                "source_file": path.name,
                "source_path": str(path.resolve()),
                "source_encoding": encoding,
                "source_unit": "KRW",
            }
        )
        for source, target in NAME_COLUMNS.items():
            frame[target] = selected[source].replace("", pd.NA)

        masked_fields: list[str]
        parse_failed_fields: list[str]
        parsed_columns: dict[str, list[int | None]] = {
            target: [] for target in AMOUNT_COLUMNS.values()
        }
        masked_by_row: list[list[str]] = [[] for _ in range(len(selected))]
        failed_by_row: list[list[str]] = [[] for _ in range(len(selected))]
        for source, target in AMOUNT_COLUMNS.items():
            for index, value in enumerate(selected[source].tolist()):
                amount, raw_unparsed, masked = parse_amount(value)
                parsed_columns[target].append(amount)
                if masked:
                    masked_by_row[index].append(source)
                elif amount is None and raw_unparsed is not None:
                    failed_by_row[index].append(source)
        for target, values in parsed_columns.items():
            frame[target] = pd.array(values, dtype="Int64")
        masked_fields = [json.dumps(values, ensure_ascii=False) for values in masked_by_row]
        parse_failed_fields = [json.dumps(values, ensure_ascii=False) for values in failed_by_row]
        frame["is_masked"] = [bool(values) for values in masked_by_row]
        frame["masked_fields"] = masked_fields
        frame["amount_parse_failed"] = [bool(values) for values in failed_by_row]
        frame["parse_failed_fields"] = parse_failed_fields
        normalized_parts.append(frame)

    records = pd.concat(normalized_parts, ignore_index=True)
    records = apply_code_matching(records, _monthly_lookup(monthly_path))
    records["project_id"] = records.apply(_project_id, axis=1)
    duplicate_key = [
        "fiscal_year",
        "ministry_code",
        "project_id",
    ]
    records["duplicate_key_flag"] = records.duplicated(duplicate_key, keep=False)
    records["year_file_mismatch_flag"] = records.apply(
        lambda row: str(row["fiscal_year"]) not in row["source_file"], axis=1
    )
    records["manual_review_required"] = (
        records["manual_review_required"]
        | records["duplicate_key_flag"]
        | records["year_file_mismatch_flag"]
    )

    reason_masks = {
        "SETTLEMENT_CODE_NO_MATCH": records["matching_status"] == "NO_MATCH",
        "SETTLEMENT_CODE_MULTIPLE_MATCHES": records["matching_status"] == "MULTIPLE_MATCHES",
        "SETTLEMENT_DUPLICATE_KEY": records["duplicate_key_flag"],
        "SETTLEMENT_AMOUNT_MASKED": records["is_masked"],
        "SETTLEMENT_AMOUNT_PARSE_FAILED": records["amount_parse_failed"],
        "SETTLEMENT_YEAR_FILE_MISMATCH": records["year_file_mismatch_flag"],
    }
    issue_parts: list[pd.DataFrame] = []
    issue_columns = [
        "project_id",
        "fiscal_year",
        "ministry_code",
        "matching_status",
        "source_file",
        "source_row_number",
    ]
    for reason, mask in reason_masks.items():
        part = records.loc[mask, issue_columns].copy()
        part.insert(0, "issue_reason", reason)
        issue_parts.append(part)
    issues = pd.concat(issue_parts, ignore_index=True)

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "input_directory": str(input_dir.resolve()),
        "file_count": len(paths),
        "inventory": inventory,
        "full_source_row_count": full_input_count,
        "target_ministry_row_count": len(records),
        "normalized_row_count": len(records),
        "raw_vs_normalized_difference": len(records) - len(records),
        "duplicate_key_row_count": int(records["duplicate_key_flag"].sum()),
        "masked_row_count": int(records["is_masked"].sum()),
        "amount_parse_failure_row_count": int(records["amount_parse_failed"].sum()),
        "manual_review_row_count": int(records["manual_review_required"].sum()),
        "ministry_row_counts": _json_counts(records["ministry_code"]),
        "year_row_counts": _json_counts(records["fiscal_year"]),
        "matching_status_counts": _json_counts(records["matching_status"]),
    }

    dictionary = pd.DataFrame(
        [
            {
                "column_name": target,
                "source_field": source,
                "dtype": "Int64",
                "unit": "KRW",
                "description": f"결산 원본 {source}",
            }
            for source, target in AMOUNT_COLUMNS.items()
        ]
        + [
            {
                "column_name": "project_id",
                "source_field": "",
                "dtype": "string",
                "unit": "",
                "description": "월별 집행 코드 유일매칭 기반 사업 식별자",
            },
            {
                "column_name": "matching_status",
                "source_field": "",
                "dtype": "string",
                "unit": "",
                "description": "코드 매칭 상태",
            },
        ]
    )
    documented = set(dictionary["column_name"])
    dictionary = pd.concat(
        [
            dictionary,
            pd.DataFrame(
                [
                    {
                        "column_name": column,
                        "source_field": next(
                            (source for source, target in NAME_COLUMNS.items() if target == column),
                            "",
                        ),
                        "dtype": str(records[column].dtype),
                        "unit": "KRW" if column.endswith("_amount") else "",
                        "description": "결산 정규화·추적·품질 컬럼",
                    }
                    for column in records.columns
                    if column not in documented
                ]
            ),
        ],
        ignore_index=True,
    )
    summary["table_column_count"] = len(records.columns)
    summary["data_dictionary_column_count"] = len(dictionary)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = [
        output_dir / "project_settlement.parquet",
        output_dir / "settlement_inventory_summary.json",
        output_dir / "settlement_validation_issues.csv",
        output_dir / "settlement_manual_review.csv",
        output_dir / "settlement_data_dictionary.csv",
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
    dictionary.to_csv(output_paths[4], index=False, encoding="utf-8-sig")
    return SettlementNormalizationResult(records, issues, summary, output_paths)
