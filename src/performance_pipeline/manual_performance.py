"""사람이 검수한 성과 구조화 엑셀을 프로그램-연도 재정 마스터와 연결합니다."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import load_workbook

GOLD_SHEET = "02_골드셋"
HEADER_ROW = 4
HEADER_MAP = {
    "행ID": "source_indicator_id",
    "부처": "ministry_name",
    "회계연도": "fiscal_year",
    "전략목표번호": "strategic_goal_number",
    "프로그램목표번호": "program_goal_number",
    "예산프로그램코드": "source_program_code",
    "프로그램명": "performance_program_name",
    "계획서 성과지표명": "indicator_name_plan",
    "보고서 성과지표명": "indicator_name_report",
    "단위": "indicator_unit",
    "지표방향": "indicator_direction",
    "목표치": "planned_target_raw",
    "실적치": "actual_value_raw",
    "달성률": "official_achievement_rate_raw",
    "계획서 페이지": "plan_source_page",
    "보고서 페이지": "report_source_page",
    "계획서 근거": "plan_source_text",
    "보고서 근거": "report_source_text",
    "매칭상태": "plan_report_match_status_raw",
    "변경내용": "change_description",
    "검수자": "reviewer",
    "비고": "notes",
}
REQUIRED_HEADERS = tuple(HEADER_MAP)
REQUIRED_FINANCIAL_COLUMNS = {
    "fiscal_year",
    "ministry_code",
    "ministry_name",
    "program_code",
    "program_name",
    "original_budget",
    "current_budget",
    "settlement_expenditure",
    "execution_rate",
    "financial_linkage_status",
    "financial_quality_level",
}
AUTO_MATCH_STATUSES = {
    "EXACT_CODE",
    "EXACT_NAME",
    "NORMALIZED_NAME",
    "EXACT_NAME_UNIQUE_FINANCIAL",
}


class ManualPerformanceError(ValueError):
    """수기 성과자료가 입력·키·보존 계약을 위반할 때 발생합니다."""


@dataclass
class ManualPerformanceResult:
    manual_rows: pd.DataFrame
    indicators: pd.DataFrame
    program_year: pd.DataFrame
    issues: pd.DataFrame
    data_dictionary: pd.DataFrame
    summary: dict[str, Any]
    output_paths: list[Path]


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _year(value: Any) -> int | None:
    text = _text(value)
    if text is None or not text.isdigit():
        return None
    return int(text)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text or text in {"-", "신규", "종료", "집계중", "해당없음"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def normalize_program_name(value: Any) -> str:
    text = unicodedata.normalize("NFKC", _text(value) or "")
    return "".join(character for character in text if not character.isspace())


def _is_example(record: dict[str, Any]) -> bool:
    review_text = " ".join(
        _text(record.get(column)) or "" for column in ("reviewer", "notes", "change_description")
    )
    return "예시" in review_text


def _source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_manual_performance_workbook(
    input_path: Path,
    *,
    ministry_name: str,
    start_year: int,
    end_year: int,
) -> pd.DataFrame:
    """골드셋의 모든 비어 있지 않은 행을 출처 행번호와 함께 읽습니다."""
    if not input_path.is_file():
        raise ManualPerformanceError(f"수기 성과 엑셀을 찾을 수 없습니다: {input_path}")
    if start_year > end_year:
        raise ManualPerformanceError("시작연도는 종료연도보다 클 수 없습니다.")

    workbook = load_workbook(input_path, read_only=True, data_only=False)
    if GOLD_SHEET not in workbook.sheetnames:
        raise ManualPerformanceError(f"필수 시트가 없습니다: {GOLD_SHEET}")
    sheet = workbook[GOLD_SHEET]
    headers = [_text(cell.value) for cell in sheet[HEADER_ROW]]
    missing_headers = [header for header in REQUIRED_HEADERS if header not in headers]
    if missing_headers:
        raise ManualPerformanceError(f"골드셋 필수 열이 없습니다: {', '.join(missing_headers)}")

    positions = {header: headers.index(header) for header in REQUIRED_HEADERS}
    rows: list[dict[str, Any]] = []
    for source_row_number, cells in enumerate(
        sheet.iter_rows(min_row=HEADER_ROW + 1),
        start=HEADER_ROW + 1,
    ):
        values = [cell.value for cell in cells]
        if not any(value not in (None, "") for value in values):
            continue
        record = {target: _text(values[positions[source]]) for source, target in HEADER_MAP.items()}
        record["fiscal_year"] = _year(values[positions["회계연도"]])
        record["source_file"] = input_path.name
        record["source_sheet"] = GOLD_SHEET
        record["source_row_number"] = source_row_number
        record["source_trace"] = f"{input_path.as_posix()}#{GOLD_SHEET}!row={source_row_number}"
        record["is_example"] = _is_example(record)
        record["ministry_scope_match"] = record["ministry_name"] == ministry_name
        record["year_scope_match"] = (
            record["fiscal_year"] is not None and start_year <= record["fiscal_year"] <= end_year
        )
        record["required_fields_available"] = all(
            record.get(column) not in (None, "")
            for column in (
                "source_indicator_id",
                "ministry_name",
                "fiscal_year",
                "performance_program_name",
            )
        ) and bool(record.get("indicator_name_plan") or record.get("indicator_name_report"))
        record["analysis_eligible"] = (
            not record["is_example"]
            and record["ministry_scope_match"]
            and record["year_scope_match"]
            and record["required_fields_available"]
        )
        record["program_name_normalized"] = normalize_program_name(
            record["performance_program_name"]
        )
        record["planned_target_numeric"] = _number(values[positions["목표치"]])
        record["actual_value_numeric"] = _number(values[positions["실적치"]])
        record["official_achievement_rate_numeric"] = _number(values[positions["달성률"]])
        record["actual_value_missing_flag"] = record["actual_value_raw"] is None
        rows.append(record)
    workbook.close()

    if not rows:
        raise ManualPerformanceError("골드셋에 비어 있지 않은 행이 없습니다.")
    return pd.DataFrame(rows).convert_dtypes()


def _validate_financial(financial: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_FINANCIAL_COLUMNS - set(financial.columns)
    if missing:
        raise ManualPerformanceError(
            f"재정 프로그램-연도 필수 열이 없습니다: {', '.join(sorted(missing))}"
        )
    result = financial.copy()
    result["ministry_code"] = result["ministry_code"].astype("string").str.zfill(3)
    result["program_code"] = result["program_code"].astype("string")
    result["fiscal_year"] = pd.to_numeric(result["fiscal_year"], errors="coerce").astype("Int64")
    result["program_name_normalized"] = result["program_name"].map(normalize_program_name)
    duplicate = result.duplicated(["ministry_code", "fiscal_year", "program_code"], keep=False)
    if duplicate.any():
        raise ManualPerformanceError(
            f"재정 프로그램-연도 기본키가 중복되었습니다: {int(duplicate.sum())}행"
        )
    return result


def _indicator_status_counts(series: pd.Series) -> str:
    counts = Counter(str(value) for value in series.dropna().astype(str) if str(value).strip())
    return json.dumps(dict(sorted(counts.items())), ensure_ascii=False)


def _program_year_performance(indicators: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    keys = ["ministry_name", "fiscal_year", "performance_program_name"]
    for key, part in indicators.groupby(keys, dropna=False, sort=True):
        ministry_name, fiscal_year, performance_program_name = key
        rows.append(
            {
                "ministry_name": ministry_name,
                "fiscal_year": fiscal_year,
                "performance_program_name": performance_program_name,
                "source_program_code": part["source_program_code"].dropna().iloc[0]
                if part["source_program_code"].notna().any()
                else pd.NA,
                "program_name_normalized": normalize_program_name(performance_program_name),
                "indicator_count": len(part),
                "reported_indicator_count": int(part["actual_value_raw"].notna().sum()),
                "achievement_rate_numeric_count": int(
                    part["official_achievement_rate_numeric"].notna().sum()
                ),
                "plan_report_mismatch_count": int(
                    part["plan_report_match_status_raw"].eq("불일치").sum()
                ),
                "plan_report_match_status_counts": _indicator_status_counts(
                    part["plan_report_match_status_raw"]
                ),
                "source_indicator_ids": json.dumps(
                    part["source_indicator_id"].astype(str).tolist(),
                    ensure_ascii=False,
                ),
            }
        )
    return pd.DataFrame(rows).convert_dtypes()


def match_program_year(
    program_year: pd.DataFrame,
    financial: pd.DataFrame,
    *,
    ministry_code: str,
) -> pd.DataFrame:
    """코드, 정확 명칭, 공백 정규화 명칭 순으로 유일한 경우만 자동 연결합니다."""
    fiscal = _validate_financial(financial)
    fiscal = fiscal.loc[fiscal["ministry_code"].eq(ministry_code.zfill(3))].copy()
    output_rows: list[dict[str, Any]] = []
    financial_payload_columns = [
        column
        for column in fiscal.columns
        if column
        not in {
            "ministry_code",
            "ministry_name",
            "fiscal_year",
            "program_code",
            "program_name",
            "program_name_normalized",
        }
    ]

    for row in program_year.to_dict(orient="records"):
        year_candidates = fiscal.loc[fiscal["fiscal_year"].eq(row["fiscal_year"])]
        source_code = _text(row.get("source_program_code"))
        if source_code:
            candidates = year_candidates.loc[year_candidates["program_code"].eq(source_code)]
            match_status = "EXACT_CODE"
        else:
            candidates = year_candidates.loc[
                year_candidates["program_name"]
                .astype(str)
                .str.strip()
                .eq(str(row["performance_program_name"]).strip())
            ]
            match_status = "EXACT_NAME"
            if candidates.empty:
                candidates = year_candidates.loc[
                    year_candidates["program_name_normalized"].eq(row["program_name_normalized"])
                ]
                match_status = "NORMALIZED_NAME"

        if len(candidates) > 1:
            usable = candidates.loc[
                candidates["program_code"].ne("UNKNOWN")
                & candidates["financial_linkage_status"].eq("COMPLETE")
            ]
            if len(usable) == 1:
                candidates = usable
                match_status = "EXACT_NAME_UNIQUE_FINANCIAL"

        matched = len(candidates) == 1
        if candidates.empty:
            match_status = "MANUAL_REVIEW_NO_MATCH"
        elif len(candidates) > 1:
            match_status = "MANUAL_REVIEW_MULTIPLE_MATCHES"

        result = dict(row)
        result["ministry_code"] = ministry_code.zfill(3)
        result["program_match_status"] = match_status
        result["program_match_eligible"] = matched
        result["program_code"] = pd.NA
        result["financial_program_name"] = pd.NA
        for column in financial_payload_columns:
            result[column] = pd.NA
        if matched:
            fiscal_row = candidates.iloc[0]
            result["program_code"] = fiscal_row["program_code"]
            result["financial_program_name"] = fiscal_row["program_name"]
            for column in financial_payload_columns:
                result[column] = fiscal_row[column]
        result["performance_outcome_analysis_eligible"] = result["reported_indicator_count"] > 0
        result["same_year_financial_analysis_eligible"] = bool(
            matched and result.get("financial_linkage_status") == "COMPLETE"
        )
        result["same_year_joint_analysis_eligible"] = bool(
            result["performance_outcome_analysis_eligible"]
            and result["same_year_financial_analysis_eligible"]
        )
        output_rows.append(result)
    return pd.DataFrame(output_rows).convert_dtypes()


def _issues(
    manual_rows: pd.DataFrame,
    indicators: pd.DataFrame,
    program_year: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in manual_rows.loc[manual_rows["is_example"]].itertuples():
        rows.append(
            {
                "issue_type": "EXAMPLE_ROW",
                "severity": "INFO",
                "source_row_number": row.source_row_number,
                "source_indicator_id": row.source_indicator_id,
                "fiscal_year": row.fiscal_year,
                "performance_program_name": row.performance_program_name,
                "details": "예시행은 보존하되 분석대상에서 제외",
            }
        )
    for row in manual_rows.loc[
        ~manual_rows["is_example"] & ~manual_rows["analysis_eligible"]
    ].itertuples():
        rows.append(
            {
                "issue_type": "INPUT_ROW_INELIGIBLE",
                "severity": "BLOCKING",
                "source_row_number": row.source_row_number,
                "source_indicator_id": row.source_indicator_id,
                "fiscal_year": row.fiscal_year,
                "performance_program_name": row.performance_program_name,
                "details": "부처·연도 범위 또는 필수키 확인 필요",
            }
        )
    for row in indicators.loc[indicators["actual_value_missing_flag"]].itertuples():
        rows.append(
            {
                "issue_type": "ACTUAL_VALUE_MISSING",
                "severity": "ANALYSIS_LIMITATION",
                "source_row_number": row.source_row_number,
                "source_indicator_id": row.source_indicator_id,
                "fiscal_year": row.fiscal_year,
                "performance_program_name": row.performance_program_name,
                "details": "성과실적 결측; 프로그램 매칭에는 포함하되 성과분석 제한",
            }
        )
    for row in program_year.loc[~program_year["program_match_eligible"]].itertuples():
        rows.append(
            {
                "issue_type": row.program_match_status,
                "severity": "MANUAL_REVIEW",
                "source_row_number": pd.NA,
                "source_indicator_id": pd.NA,
                "fiscal_year": row.fiscal_year,
                "performance_program_name": row.performance_program_name,
                "details": f"영향 성과지표 {row.indicator_count}행; 프로그램코드 수동 확인",
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "issue_type",
            "severity",
            "source_row_number",
            "source_indicator_id",
            "fiscal_year",
            "performance_program_name",
            "details",
        ],
    ).convert_dtypes()


def _data_dictionary() -> pd.DataFrame:
    rows = [
        ("source_indicator_id", "원본 골드셋 행ID", "string"),
        ("fiscal_year", "성과 대상 회계연도", "integer"),
        ("performance_program_name", "성과문서의 프로그램명", "string"),
        ("indicator_name_plan", "성과계획서 지표명", "string"),
        ("indicator_name_report", "성과보고서 지표명", "string"),
        ("planned_target_raw", "계획서 목표치 원문값", "string"),
        ("actual_value_raw", "보고서 실적치 원문값", "string"),
        (
            "official_achievement_rate_raw",
            "성과보고서 공식 달성률 원문값",
            "string",
        ),
        ("program_match_status", "재정 프로그램 매칭상태", "string"),
        ("program_code", "유일 매칭된 열린재정 프로그램코드", "string"),
        ("original_budget", "프로그램 확정 본예산 합계", "integer"),
        ("current_budget", "프로그램 예산현액 합계", "integer"),
        ("settlement_expenditure", "프로그램 결산 지출액 합계", "integer"),
        ("execution_rate", "회계유형별 확인된 분자·분모로 계산한 집행률", "float"),
        (
            "same_year_joint_analysis_eligible",
            "성과실적과 완전 재정연결을 함께 사용할 수 있는지 여부",
            "boolean",
        ),
    ]
    return pd.DataFrame(rows, columns=["column", "definition", "logical_type"])


def build_manual_performance_pilot(
    *,
    input_path: Path,
    financial_path: Path,
    output_dir: Path,
    ministry_name: str = "중소벤처기업부",
    ministry_code: str = "102",
    start_year: int = 2022,
    end_year: int = 2024,
    overwrite: bool = False,
) -> ManualPerformanceResult:
    output_paths = [
        output_dir / "manual_performance_rows.parquet",
        output_dir / "program_kpi_year.parquet",
        output_dir / "program_year_performance_financial.parquet",
        output_dir / "manual_review.csv",
        output_dir / "data_dictionary.csv",
        output_dir / "normalization_summary.json",
    ]
    existing = [path for path in output_paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "기존 산출물이 있습니다. --overwrite를 지정하세요: "
            + ", ".join(str(path) for path in existing)
        )
    if not financial_path.is_file():
        raise ManualPerformanceError(
            f"프로그램-연도 재정 마스터를 찾을 수 없습니다: {financial_path}"
        )

    source_hash_before = _source_sha256(input_path)
    manual_rows = read_manual_performance_workbook(
        input_path,
        ministry_name=ministry_name,
        start_year=start_year,
        end_year=end_year,
    )
    indicators = manual_rows.loc[manual_rows["analysis_eligible"]].copy()
    duplicate_indicator_ids = indicators.duplicated("source_indicator_id", keep=False)
    if duplicate_indicator_ids.any():
        raise ManualPerformanceError(
            f"분석대상 성과지표 행ID가 중복되었습니다: {int(duplicate_indicator_ids.sum())}행"
        )

    financial = pd.read_parquet(financial_path)
    program_performance = _program_year_performance(indicators)
    program_year = match_program_year(
        program_performance,
        financial,
        ministry_code=ministry_code,
    )
    issues = _issues(manual_rows, indicators, program_year)
    data_dictionary = _data_dictionary()

    matched = program_year["program_match_eligible"].astype(bool)
    amount_columns = ["original_budget", "current_budget", "settlement_expenditure"]
    amount_reconciliation: dict[str, dict[str, int]] = {}
    fiscal_checked = _validate_financial(financial)
    fiscal_checked = fiscal_checked.loc[
        fiscal_checked["ministry_code"].eq(ministry_code.zfill(3))
    ].copy()
    for column in amount_columns:
        output_amount = int(
            pd.to_numeric(program_year.loc[matched, column], errors="coerce").sum(skipna=True)
        )
        matched_keys = program_year.loc[matched, ["fiscal_year", "program_code"]].copy()
        source_subset = fiscal_checked.merge(
            matched_keys,
            how="inner",
            on=["fiscal_year", "program_code"],
            validate="one_to_one",
        )
        source_amount = int(pd.to_numeric(source_subset[column], errors="coerce").sum(skipna=True))
        amount_reconciliation[column] = {
            "source_amount": source_amount,
            "output_amount": output_amount,
            "difference": output_amount - source_amount,
        }

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "pilot_scope": {
            "ministry_name": ministry_name,
            "ministry_code": ministry_code.zfill(3),
            "start_year": start_year,
            "end_year": end_year,
        },
        "source_file": str(input_path),
        "source_sha256": source_hash_before,
        "raw_nonempty_row_count": len(manual_rows),
        "example_row_count": int(manual_rows["is_example"].sum()),
        "analysis_indicator_row_count": len(indicators),
        "indicator_year_counts": {
            str(key): int(value)
            for key, value in indicators["fiscal_year"].value_counts().sort_index().items()
        },
        "indicator_id_duplicate_count": int(indicators.duplicated("source_indicator_id").sum()),
        "actual_value_missing_count": int(indicators["actual_value_missing_flag"].sum()),
        "program_year_count": len(program_year),
        "program_match_status_counts": {
            str(key): int(value)
            for key, value in program_year["program_match_status"].value_counts().items()
        },
        "matched_program_year_count": int(matched.sum()),
        "manual_review_program_year_count": int((~matched).sum()),
        "same_year_joint_analysis_eligible_count": int(
            program_year["same_year_joint_analysis_eligible"].sum()
        ),
        "financial_linkage_status_counts": {
            str(key): int(value)
            for key, value in program_year.loc[matched, "financial_linkage_status"]
            .value_counts(dropna=False)
            .items()
        },
        "amount_reconciliation": amount_reconciliation,
        "issue_type_counts": {
            str(key): int(value) for key, value in issues["issue_type"].value_counts().items()
        },
        "validation": {
            "raw_rows_partitioned": len(manual_rows)
            == len(indicators) + int((~manual_rows["analysis_eligible"]).sum()),
            "indicator_id_unique": not indicators["source_indicator_id"].duplicated().any(),
            "program_year_key_unique": not program_year.duplicated(
                ["ministry_code", "fiscal_year", "performance_program_name"]
            ).any(),
            "all_auto_matches_unique": bool(
                program_year.loc[matched, "program_code"].notna().all()
            ),
            "amounts_preserved": all(
                values["difference"] == 0 for values in amount_reconciliation.values()
            ),
            "source_file_unchanged": source_hash_before == _source_sha256(input_path),
        },
        "interpretation_limit": (
            "성과지표를 세부사업에 귀속하지 않으며, 복수 지표의 달성률을 평균하지 "
            "않습니다. 미매칭 프로그램과 재정 PARTIAL/UNMATCHED는 공동분석에서 제한합니다."
        ),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    manual_rows.to_parquet(output_paths[0], index=False)
    indicators.to_parquet(output_paths[1], index=False)
    program_year.to_parquet(output_paths[2], index=False)
    issues.to_csv(output_paths[3], index=False, encoding="utf-8-sig")
    data_dictionary.to_csv(output_paths[4], index=False, encoding="utf-8-sig")
    output_paths[5].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return ManualPerformanceResult(
        manual_rows=manual_rows,
        indicators=indicators,
        program_year=program_year,
        issues=issues,
        data_dictionary=data_dictionary,
        summary=summary,
        output_paths=output_paths,
    )
