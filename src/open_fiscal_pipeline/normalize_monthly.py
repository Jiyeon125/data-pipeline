from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from .response import parse_api_payload

AMOUNT_FIELD_MAP: dict[str, str] = {
    "ANEXP_BDG_AMT": "budget_amount",
    "ANEXP_BDG_CAMT": "current_budget_amount",
    "EP_AMT": "expenditure_amount",
    "THISM_AGGR_EP_AMT": "cumulative_expenditure_amount",
    "THISM_AGGR_EP_NAMT": "cumulative_net_expenditure_amount",
}

# VWFOEM2 공식 출력항목 설명이 저장소에 없어, 동일 필드명을 쓰는 관련 Open API
# (예금보험공사 일별 상환기금 운용상황) 및 부처 월별 집행 공개표 표기를 잠정 참고합니다.
# mentoring_amount_type / aggregation_basis는 docs/MENTORING_GUIDE.md §6 금액유형 체계와의
# 잠정 대응이며, 공식 명세 확인 전까지 확정값이 아닙니다.
AMOUNT_FIELD_MEANINGS: dict[str, dict[str, str]] = {
    "ANEXP_BDG_AMT": {
        "provisional_meaning": "세출예산액(원)",
        "confidence": "provisional",
        "basis": "관련 Open API(일별 상환기금) anexpBdgamt 항목명 교차확인",
        "mentoring_amount_type": "national_assembly_final_budget_or_initial_plan",
        "aggregation_basis": "unspecified",
        "notes": "본예산·당초계획 후보. 예산현액과 혼합·대체 금지(§6)",
    },
    "ANEXP_BDG_CAMT": {
        "provisional_meaning": "세출예산현액(원)",
        "confidence": "provisional",
        "basis": "관련 Open API(일별 상환기금) anexpBdgCamt 항목명 교차확인",
        "mentoring_amount_type": "current_budget",
        "aggregation_basis": "unspecified",
        "notes": "집행률 분모 후보(일반·특별회계). 본예산과 별도 보존(§6.2)",
    },
    "EP_AMT": {
        "provisional_meaning": "당월 지출액(원)",
        "confidence": "provisional",
        "basis": (
            "관련 Open API epAmt='당일지출금액'을 월별 API 맥락에 맞게 잠정 해석. "
            "부처 공개표의 '당월 집행액' 표기와 대응"
        ),
        "mentoring_amount_type": "expenditure",
        "aggregation_basis": "monthly",
        "notes": "당월분. 누계·결산과 혼합 금지. 낮은 집행은 실패가 아니라 집행설명필요 신호(§10)",
    },
    "THISM_AGGR_EP_AMT": {
        "provisional_meaning": "당년도 누계 지출금액(총계, 원)",
        "confidence": "provisional",
        "basis": "관련 Open API thismAggrEpAmt='당년도누계지출금액(총계)' 교차확인",
        "mentoring_amount_type": "expenditure",
        "aggregation_basis": "gross_ytd",
        "notes": "총계. 순계·총지출과 혼용 금지(§6.4)",
    },
    "THISM_AGGR_EP_NAMT": {
        "provisional_meaning": "당년도 누계 지출금액(순계, 원)",
        "confidence": "provisional",
        "basis": "관련 Open API thismAggrEpNamt='당년도누계지출금액(순계)' 교차확인",
        "mentoring_amount_type": "net_expenditure",
        "aggregation_basis": "net_ytd",
        "notes": "순계. 총계와 별도 컬럼으로만 보존하며 서로 대체하지 않음(§6.4)",
    },
}

TABLE_ID = "project_month"
EXTRACTION_METHOD = "api_json_normalize"

# docs/MENTORING_GUIDE.md §15.2 확장: 마스킹은 원본에 숫자가 있으나 공개 제한된 경우
MISSING_REASON_MASKED = "MASKED_SOURCE_VALUE"
MISSING_REASON_PARSE_FAILED = "PARSE_FAILED"
MISSING_REASON_SOURCE_MISSING = "SOURCE_VALUE_MISSING"

CODE_FIELD_MAP: dict[str, str] = {
    "OFFC_CD": "ministry_code",
    "FSCL_CD": "account_code",
    "FLD_CD": "field_code",
    "SECT_CD": "sector_code",
    "PGM_CD": "program_code",
    "ACTV_CD": "activity_code",
    "SACTV_CD": "subactivity_code",
}

NAME_FIELD_MAP: dict[str, str] = {
    "OFFC_NM": "ministry_name",
    "FSCL_NM": "account_name",
    "FLD_NM": "field_name",
    "SECT_NM": "sector_name",
    "PGM_NM": "program_name",
    "ACTV_NM": "activity_name",
    "SACTV_NM": "subactivity_name",
}

COMPOSITE_KEY_FIELDS: tuple[str, ...] = (
    "fiscal_year",
    "execution_month",
    "ministry_code",
    "account_code",
    "program_code",
    "activity_code",
    "subactivity_code",
)

BUSINESS_KEY_FIELDS: tuple[str, ...] = (
    "fiscal_year",
    "ministry_code",
    "account_code",
    "program_code",
    "activity_code",
    "subactivity_code",
)

YYYYMM_RE = re.compile(r"^\d{6}$")
MASK_RE = re.compile(r"\*")

OutputFormat = Literal["parquet", "csv", "both"]


@dataclass
class FailedFile:
    path: str
    error: str


@dataclass
class NormalizationResult:
    frame: pd.DataFrame
    issues: pd.DataFrame
    summary: dict[str, Any]
    failed_files: list[FailedFile] = field(default_factory=list)
    output_paths: list[Path] = field(default_factory=list)


def is_masked_value(value: Any) -> bool:
    if value is None:
        return False
    return bool(MASK_RE.search(str(value)))


def as_code(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def as_fiscal_year(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text.isdigit():
        return None
    return int(text)


def as_execution_month(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not YYYYMM_RE.fullmatch(text):
        return text
    return text


def parse_amount(value: Any) -> tuple[int | None, str | None, bool]:
    """정상 금액은 nullable int, 마스킹은 null + 원문 보존."""
    if value is None or value == "":
        return None, None, False
    if is_masked_value(value):
        return None, str(value), True
    if isinstance(value, bool):
        return None, str(value), False
    if isinstance(value, int):
        return value, None, False
    if isinstance(value, float) and value.is_integer():
        return int(value), None, False
    text = str(value).strip().replace(",", "")
    if not text:
        return None, None, False
    try:
        return int(text), None, False
    except ValueError:
        return None, text, False


def extract_rows_from_document(document: dict[str, Any], *, service_name: str = "VWFOEM2") -> list[dict[str, Any]]:
    response = document.get("response", document)
    parsed = parse_api_payload(response, service_name=service_name)
    return list(parsed.records)


def normalize_record(
    record: dict[str, Any],
    *,
    source_file: str,
    source_page: int | None,
    source_requested_at: str | None,
    source_url: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "table_id": TABLE_ID,
        "fiscal_year": as_fiscal_year(record.get("FSCL_YY")),
        "execution_month": as_execution_month(record.get("EXE_M")),
        "source_file": source_file,
        "source_page": source_page,
        "source_url": source_url,
        "source_requested_at": source_requested_at,
        "extraction_method": EXTRACTION_METHOD,
    }
    for source, target in CODE_FIELD_MAP.items():
        row[target] = as_code(record.get(source))
    for source, target in NAME_FIELD_MAP.items():
        value = record.get(source)
        row[target] = None if value in (None, "") else str(value)

    masked_fields: list[str] = []
    masked_raw_values: dict[str, str] = {}
    amount_missing_reasons: dict[str, str] = {}
    for source, target in AMOUNT_FIELD_MAP.items():
        raw_value = record.get(source)
        amount, raw, masked = parse_amount(raw_value)
        row[target] = amount
        if masked and raw is not None:
            masked_fields.append(source)
            masked_raw_values[source] = raw
            amount_missing_reasons[source] = MISSING_REASON_MASKED
        elif amount is None and raw is not None:
            # 비마스킹이지만 정수 변환 실패 — 보간하지 않고 결측사유만 기록(§15)
            masked_raw_values[source] = raw
            amount_missing_reasons[source] = MISSING_REASON_PARSE_FAILED
        elif amount is None and raw_value in (None, ""):
            amount_missing_reasons[source] = MISSING_REASON_SOURCE_MISSING

    is_masked = bool(masked_fields)
    row["is_masked"] = is_masked
    row["masked_fields"] = json.dumps(masked_fields, ensure_ascii=False)
    row["masked_raw_values"] = json.dumps(masked_raw_values, ensure_ascii=False)
    row["amount_missing_reasons"] = json.dumps(amount_missing_reasons, ensure_ascii=False)
    row["masked_amount_flag"] = is_masked
    # 데이터 신뢰도 제한조건(§23). 정책판정이 아니라 원문 검증 우선 표시.
    needs_data_review = is_masked or any(
        reason in {MISSING_REASON_MASKED, MISSING_REASON_PARSE_FAILED}
        for reason in amount_missing_reasons.values()
    )
    row["manual_review_required"] = needs_data_review
    row["review_status"] = "needs_review" if needs_data_review else "normalized"
    row["execution_month_year_mismatch"] = False
    row["cumulative_decrease_flag"] = False
    row["monthly_cumulative_mismatch_flag"] = False
    row["duplicate_key_flag"] = False
    return row


def discover_raw_files(
    input_dir: Path,
    *,
    start_year: int | None = None,
    end_year: int | None = None,
    ministry_code: str | None = None,
) -> list[Path]:
    if not input_dir.exists():
        return []

    paths: list[Path] = []
    for path in sorted(input_dir.rglob("page_*.json")):
        parts = {part.split("=", 1)[0]: part.split("=", 1)[1] for part in path.parts if "=" in part}
        year_text = parts.get("year")
        code_text = parts.get("ministry_code")
        if year_text is not None and year_text.isdigit():
            year = int(year_text)
            if start_year is not None and year < start_year:
                continue
            if end_year is not None and year > end_year:
                continue
        if ministry_code is not None and code_text != ministry_code:
            continue
        paths.append(path)
    return paths


def _relative_source(path: Path, input_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(input_dir.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def load_and_normalize_files(
    paths: Sequence[Path],
    *,
    input_dir: Path,
) -> tuple[list[dict[str, Any]], list[FailedFile], int]:
    rows: list[dict[str, Any]] = []
    failed: list[FailedFile] = []
    raw_record_count = 0

    for path in paths:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                raise TypeError("원본 JSON 최상위는 객체여야 합니다.")
            metadata = document.get("metadata") or {}
            records = extract_rows_from_document(document)
            raw_record_count += len(records)
            source_file = _relative_source(path, input_dir)
            source_page = metadata.get("page_index")
            source_requested_at = metadata.get("requested_at")
            source_url = metadata.get("api_url")
            page_index = int(source_page) if source_page not in (None, "") else None
            for record in records:
                if not isinstance(record, dict):
                    raise TypeError(f"레코드가 객체가 아닙니다: {type(record)}")
                rows.append(
                    normalize_record(
                        record,
                        source_file=source_file,
                        source_page=page_index,
                        source_requested_at=(
                            None if source_requested_at in (None, "") else str(source_requested_at)
                        ),
                        source_url=None if source_url in (None, "") else str(source_url),
                    )
                )
        except (OSError, TypeError, ValueError, json.JSONDecodeError, KeyError) as exc:
            failed.append(FailedFile(path=str(path), error=str(exc)))
    return rows, failed, raw_record_count


def apply_validation_flags(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if frame.empty:
        empty_issues = pd.DataFrame(
            columns=[
                "issue_type",
                "issue_detail",
                "source_file",
                "fiscal_year",
                "execution_month",
                "ministry_code",
                "account_code",
                "program_code",
                "activity_code",
                "subactivity_code",
            ]
        )
        return frame, empty_issues

    result = frame.copy()
    issues: list[dict[str, Any]] = []

    # 1) 집행연월·회계연도 불일치
    month = result["execution_month"].astype("string")
    year_from_month = month.str.slice(0, 4)
    fiscal_text = result["fiscal_year"].astype("string")
    mismatch = (
        result["execution_month"].notna()
        & result["fiscal_year"].notna()
        & month.str.fullmatch(r"\d{6}").fillna(False)
        & (year_from_month != fiscal_text)
    )
    result["execution_month_year_mismatch"] = mismatch
    for idx in result.index[mismatch]:
        row = result.loc[idx]
        issues.append(
            _issue_row(
                row,
                "execution_month_year_mismatch",
                (
                    "원문 검증 필요: execution_month와 fiscal_year 연도 불일치 "
                    f"(execution_month={row['execution_month']} fiscal_year={row['fiscal_year']})"
                ),
            )
        )

    # 5) 중복 복합키 — 완전 동일 / 금액 상이 구분
    key_cols = list(COMPOSITE_KEY_FIELDS)
    amount_cols = list(AMOUNT_FIELD_MAP.values())
    compare_cols = key_cols + amount_cols + [
        "ministry_name",
        "account_name",
        "field_code",
        "sector_code",
        "program_name",
        "activity_name",
        "subactivity_name",
        "masked_raw_values",
    ]
    result["_dup_count"] = result.groupby(key_cols, dropna=False)["source_file"].transform("count")
    result["duplicate_key_flag"] = result["_dup_count"] > 1
    for key, group in result[result["duplicate_key_flag"]].groupby(key_cols, dropna=False):
        unique_payloads = group.drop_duplicates(subset=compare_cols)
        if len(unique_payloads) == 1:
            detail = "identical_duplicate"
        else:
            detail = "same_key_different_values"
        for idx in group.index:
            row = result.loc[idx]
            issues.append(
                _issue_row(
                    row,
                    "duplicate_key",
                    (
                        f"데이터 불확실성: {detail}; "
                        f"occurrences={int(row['_dup_count'])}; key={key}"
                    ),
                )
            )

    # 2) 누계 감소, 3) 당월·누계 관계 (금액 의미 잠정이므로 플래그만)
    result = result.sort_values(
        list(BUSINESS_KEY_FIELDS) + ["execution_month", "source_file", "source_page"],
        kind="mergesort",
    ).reset_index(drop=True)
    result["cumulative_decrease_flag"] = False
    result["monthly_cumulative_mismatch_flag"] = False

    for _, group in result.groupby(list(BUSINESS_KEY_FIELDS), dropna=False, sort=False):
        prev_cum: int | None = None
        prev_month: str | None = None
        for idx, row in group.iterrows():
            cum = row["cumulative_expenditure_amount"]
            ep = row["expenditure_amount"]
            month_value = row["execution_month"]
            if (
                prev_cum is not None
                and cum is not None
                and pd.notna(cum)
                and pd.notna(prev_cum)
                and int(cum) < int(prev_cum)
            ):
                result.at[idx, "cumulative_decrease_flag"] = True
                issues.append(
                    _issue_row(
                        row,
                        "cumulative_decrease",
                        (
                            "집행설명필요: 동일 사업 누계(총계)가 전월보다 감소 "
                            f"(prev_month={prev_month} prev_cum={prev_cum} curr_cum={int(cum)}). "
                            "실패·낭비로 해석하지 않음"
                        ),
                    )
                )

            if (
                isinstance(month_value, str)
                and YYYYMM_RE.fullmatch(month_value)
                and ep is not None
                and cum is not None
                and pd.notna(ep)
                and pd.notna(cum)
            ):
                month_num = int(month_value[4:6])
                if month_num == 1 and int(ep) != int(cum):
                    result.at[idx, "monthly_cumulative_mismatch_flag"] = True
                    issues.append(
                        _issue_row(
                            row,
                            "january_ep_vs_cumulative",
                            (
                                "원문 검증 필요: 1월 당월지출과 누계(총계) 불일치 "
                                f"(expenditure_amount={int(ep)} cumulative_gross={int(cum)}). "
                                "금액유형 잠정 전제 하의 검산이며 값을 수정하지 않음"
                            ),
                        )
                    )
                elif (
                    month_num > 1
                    and prev_cum is not None
                    and prev_month is not None
                    and YYYYMM_RE.fullmatch(str(prev_month))
                    and str(prev_month)[:4] == month_value[:4]
                    and int(str(prev_month)[4:6]) == month_num - 1
                    and int(prev_cum) + int(ep) != int(cum)
                ):
                    result.at[idx, "monthly_cumulative_mismatch_flag"] = True
                    issues.append(
                        _issue_row(
                            row,
                            "monthly_vs_cumulative",
                            (
                                "원문 검증 필요: 전월누계(총계)+당월지출 ≠ 당월누계(총계) "
                                f"(prev_cum={int(prev_cum)} + ep={int(ep)} "
                                f"!= cum={int(cum)}). 총계·순계 혼용 검산 아님"
                            ),
                        )
                    )

            if cum is not None and pd.notna(cum):
                prev_cum = int(cum)
                prev_month = str(month_value) if month_value is not None else None

    for idx in result.index[result["is_masked"]]:
        row = result.loc[idx]
        issues.append(
            _issue_row(
                row,
                "masked_amount",
                (
                    "원문 검증 필요: 마스킹 금액은 추정·0 변환하지 않음 "
                    f"(masked_fields={row['masked_fields']}; raw={row['masked_raw_values']})"
                ),
            )
        )

    # 데이터 품질 검수 대상(§23). 누계감소 등 집행설명필요는 별도 신호로 유지.
    if "manual_review_required" not in result.columns:
        result["manual_review_required"] = False
    result["manual_review_required"] = (
        result["manual_review_required"].fillna(False).astype(bool)
        | result["is_masked"].astype(bool)
        | result["execution_month_year_mismatch"].astype(bool)
        | result["duplicate_key_flag"].astype(bool)
    )
    result["review_status"] = result["manual_review_required"].map(
        lambda flag: "needs_review" if bool(flag) else "normalized"
    )

    result = result.drop(columns=["_dup_count"], errors="ignore")
    issues_frame = pd.DataFrame(issues)
    if issues_frame.empty:
        issues_frame = pd.DataFrame(
            columns=[
                "issue_type",
                "issue_detail",
                "source_file",
                "fiscal_year",
                "execution_month",
                "ministry_code",
                "account_code",
                "program_code",
                "activity_code",
                "subactivity_code",
            ]
        )
    return result, issues_frame


def _issue_row(row: pd.Series, issue_type: str, detail: str) -> dict[str, Any]:
    return {
        "issue_type": issue_type,
        "issue_detail": detail,
        "source_file": row.get("source_file"),
        "fiscal_year": row.get("fiscal_year"),
        "execution_month": row.get("execution_month"),
        "ministry_code": row.get("ministry_code"),
        "account_code": row.get("account_code"),
        "program_code": row.get("program_code"),
        "activity_code": row.get("activity_code"),
        "subactivity_code": row.get("subactivity_code"),
    }


def build_normalization_summary(
    *,
    files_read: int,
    raw_record_count: int,
    frame: pd.DataFrame,
    issues: pd.DataFrame,
    failed_files: Iterable[FailedFile],
) -> dict[str, Any]:
    failed = [ {"path": item.path, "error": item.error} for item in failed_files ]
    if frame.empty:
        return {
            "created_at": datetime.now(UTC).isoformat(),
            "files_read": files_read,
            "raw_record_count": raw_record_count,
            "normalized_row_count": 0,
            "ministry_row_counts": {},
            "year_row_counts": {},
            "ministry_year_row_counts": {},
            "masked_row_count": 0,
            "masked_field_counts": {},
            "duplicate_key_row_count": 0,
            "cumulative_decrease_count": 0,
            "execution_month_year_mismatch_count": 0,
            "monthly_cumulative_mismatch_count": 0,
            "gross_net_difference_row_count": 0,
            "manual_review_required_count": 0,
            "raw_vs_normalized_difference": raw_record_count,
            "failed_files": failed,
            "amount_field_meanings": AMOUNT_FIELD_MEANINGS,
            "table_id": TABLE_ID,
            "mentoring_notes": {
                "amount_types": "별도 컬럼 보존, 혼합·대체 금지",
                "aggregation_basis": "총계·순계 혼용 금지",
                "masked_amounts": "추정·0 변환 금지",
                "cumulative_signals": "집행설명필요 신호이며 실패·낭비 판정 아님",
            },
        }

    masked_field_counts: Counter[str] = Counter()
    for values in frame.loc[frame["is_masked"], "masked_fields"]:
        try:
            parsed = json.loads(values) if isinstance(values, str) else values
        except json.JSONDecodeError:
            parsed = []
        for item in parsed or []:
            masked_field_counts[str(item)] += 1

    ministry_counts = (
        frame.groupby("ministry_code", dropna=False).size().astype(int).to_dict()
    )
    year_counts = (
        frame.groupby(frame["fiscal_year"].astype("string"), dropna=False)
        .size()
        .astype(int)
        .to_dict()
    )
    ministry_year = (
        frame.assign(_my=frame["ministry_code"].astype("string") + ":" + frame["fiscal_year"].astype("string"))
        .groupby("_my")
        .size()
        .astype(int)
        .to_dict()
    )

    both_present = (
        frame["cumulative_expenditure_amount"].notna()
        & frame["cumulative_net_expenditure_amount"].notna()
    )
    gross_net_diff = both_present & (
        frame["cumulative_expenditure_amount"] != frame["cumulative_net_expenditure_amount"]
    )

    return {
        "created_at": datetime.now(UTC).isoformat(),
        "files_read": files_read,
        "raw_record_count": raw_record_count,
        "normalized_row_count": len(frame),
        "ministry_row_counts": {str(k): int(v) for k, v in ministry_counts.items()},
        "year_row_counts": {str(k): int(v) for k, v in year_counts.items()},
        "ministry_year_row_counts": {str(k): int(v) for k, v in ministry_year.items()},
        "masked_row_count": int(frame["is_masked"].sum()),
        "masked_field_counts": dict(masked_field_counts),
        "duplicate_key_row_count": int(frame["duplicate_key_flag"].sum()),
        "cumulative_decrease_count": int(frame["cumulative_decrease_flag"].sum()),
        "execution_month_year_mismatch_count": int(
            frame["execution_month_year_mismatch"].sum()
        ),
        "monthly_cumulative_mismatch_count": int(
            frame["monthly_cumulative_mismatch_flag"].sum()
        ),
        "gross_net_difference_row_count": int(gross_net_diff.sum()),
        "manual_review_required_count": int(frame["manual_review_required"].sum()),
        "raw_vs_normalized_difference": int(raw_record_count - len(frame)),
        "failed_files": failed,
        "issue_type_counts": (
            issues.groupby("issue_type").size().astype(int).to_dict() if not issues.empty else {}
        ),
        "amount_field_meanings": AMOUNT_FIELD_MEANINGS,
        "ministry_month_combinations": int(
            frame.groupby(["ministry_code", "execution_month"], dropna=False).ngroups
        ),
        "table_id": TABLE_ID,
        "mentoring_notes": {
            "amount_types": "별도 컬럼 보존, 혼합·대체 금지",
            "aggregation_basis": "총계·순계 혼용 금지(§6.4). gross_net_difference는 참고 집계만",
            "masked_amounts": "추정·0 변환 금지(§25.18)",
            "cumulative_signals": "집행설명필요 신호이며 실패·낭비 판정 아님(§10)",
        },
    }


def data_dictionary_rows() -> list[dict[str, str]]:
    rows = [
        {
            "column_name": "table_id",
            "dtype": "string",
            "description": "논리 테이블 ID (MENTORING_GUIDE §22.4 project_month)",
            "source_field": "",
            "notes": "파일명은 monthly_expenditure, 분석 단위 식별자는 project_month",
        },
        {
            "column_name": "fiscal_year",
            "dtype": "int64(nullable)",
            "description": "회계연도",
            "source_field": "FSCL_YY",
            "notes": "",
        },
        {
            "column_name": "execution_month",
            "dtype": "string",
            "description": "집행연월 YYYYMM",
            "source_field": "EXE_M",
            "notes": "",
        },
    ]
    for source, target in CODE_FIELD_MAP.items():
        rows.append(
            {
                "column_name": target,
                "dtype": "string",
                "description": f"코드 필드 ({source})",
                "source_field": source,
                "notes": "앞자리 0 보존을 위해 문자열(§2.1)",
            }
        )
    for source, target in NAME_FIELD_MAP.items():
        rows.append(
            {
                "column_name": target,
                "dtype": "string",
                "description": f"명칭 필드 ({source})",
                "source_field": source,
                "notes": "",
            }
        )
    for source, target in AMOUNT_FIELD_MAP.items():
        meaning = AMOUNT_FIELD_MEANINGS[source]
        rows.append(
            {
                "column_name": target,
                "dtype": "int64(nullable)",
                "description": meaning["provisional_meaning"],
                "source_field": source,
                "notes": (
                    f"잠정 매핑({meaning['confidence']}); "
                    f"mentoring_amount_type={meaning['mentoring_amount_type']}; "
                    f"aggregation_basis={meaning['aggregation_basis']}; "
                    f"{meaning['basis']}; {meaning['notes']}; "
                    "마스킹 시 null+결측사유(보간 금지)"
                ),
            }
        )
    rows.extend(
        [
            {
                "column_name": "is_masked",
                "dtype": "bool",
                "description": "금액 마스킹 포함 여부",
                "source_field": "",
                "notes": "데이터 신뢰도 구성요소(§23)",
            },
            {
                "column_name": "masked_fields",
                "dtype": "string(json array)",
                "description": "마스킹된 원본 금액 필드명 목록",
                "source_field": "",
                "notes": '예: ["THISM_AGGR_EP_AMT"]',
            },
            {
                "column_name": "masked_raw_values",
                "dtype": "string(json object)",
                "description": "마스킹(또는 비정수) 금액 원문",
                "source_field": "",
                "notes": "원본값 보존. 추정 숫자로 덮어쓰지 않음(§25.18-19)",
            },
            {
                "column_name": "amount_missing_reasons",
                "dtype": "string(json object)",
                "description": "금액 결측사유 코드",
                "source_field": "",
                "notes": (
                    "MASKED_SOURCE_VALUE|PARSE_FAILED|SOURCE_VALUE_MISSING "
                    "(§15.2 확장). 0으로 보간하지 않음"
                ),
            },
            {
                "column_name": "source_file",
                "dtype": "string",
                "description": "원본 JSON 상대 경로",
                "source_field": "",
                "notes": "§22.10 원문 출처",
            },
            {
                "column_name": "source_page",
                "dtype": "int64(nullable)",
                "description": "원본 페이지 번호",
                "source_field": "metadata.page_index",
                "notes": "",
            },
            {
                "column_name": "source_url",
                "dtype": "string",
                "description": "원본 API URL",
                "source_field": "metadata.api_url",
                "notes": "§22.10",
            },
            {
                "column_name": "source_requested_at",
                "dtype": "string",
                "description": "원본 요청 시각",
                "source_field": "metadata.requested_at",
                "notes": "§22.10 requested_at",
            },
            {
                "column_name": "extraction_method",
                "dtype": "string",
                "description": "추출·정규화 방법",
                "source_field": "",
                "notes": "api_json_normalize",
            },
            {
                "column_name": "manual_review_required",
                "dtype": "bool",
                "description": "수기·원문 검증 필요 여부",
                "source_field": "",
                "notes": "마스킹·연도불일치·복합키중복 등 데이터 신뢰도 제한(§23)",
            },
            {
                "column_name": "review_status",
                "dtype": "string",
                "description": "검수상태",
                "source_field": "",
                "notes": "normalized|needs_review",
            },
            {
                "column_name": "execution_month_year_mismatch",
                "dtype": "bool",
                "description": "집행연월 연도와 회계연도 불일치",
                "source_field": "",
                "notes": "원문 검증 필요 플래그(값 수정 없음)",
            },
            {
                "column_name": "cumulative_decrease_flag",
                "dtype": "bool",
                "description": "동일 사업 누계(총계)가 전월보다 감소",
                "source_field": "",
                "notes": "집행설명필요 신호(§10). 실패·낭비 판정 아님",
            },
            {
                "column_name": "monthly_cumulative_mismatch_flag",
                "dtype": "bool",
                "description": "당월 지출과 누계(총계) 관계 검산 불일치",
                "source_field": "",
                "notes": "금액 의미 잠정 전제. 총계·순계 혼용 검산 아님",
            },
            {
                "column_name": "masked_amount_flag",
                "dtype": "bool",
                "description": "마스킹 금액 포함",
                "source_field": "",
                "notes": "is_masked와 동일",
            },
            {
                "column_name": "duplicate_key_flag",
                "dtype": "bool",
                "description": "복합키 중복 행",
                "source_field": "",
                "notes": "행 삭제 없이 표시(§25.9). identical vs different 구분",
            },
        ]
    )
    return rows


def _write_table(frame: pd.DataFrame, path: Path, fmt: Literal["parquet", "csv"]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "parquet":
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False, encoding="utf-8-sig")


def write_outputs(
    frame: pd.DataFrame,
    issues: pd.DataFrame,
    summary: dict[str, Any],
    *,
    output_dir: Path,
    output_format: OutputFormat = "parquet",
    overwrite: bool = False,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    formats: list[Literal["parquet", "csv"]]
    if output_format == "both":
        formats = ["parquet", "csv"]
    elif output_format == "csv":
        formats = ["csv"]
    else:
        formats = ["parquet"]

    if frame.empty or frame["fiscal_year"].isna().all():
        start_year, end_year = "unknown", "unknown"
        years: list[int] = []
    else:
        years = sorted(int(y) for y in frame["fiscal_year"].dropna().unique())
        start_year, end_year = str(years[0]), str(years[-1])

    written: list[Path] = []
    stem = f"monthly_expenditure_{start_year}_{end_year}"

    def _ensure_writable(path: Path) -> None:
        if path.exists() and not overwrite:
            raise FileExistsError(
                f"출력 파일이 이미 있습니다. --overwrite를 사용하세요: {path}"
            )

    for fmt in formats:
        combined = output_dir / f"{stem}.{fmt if fmt == 'csv' else 'parquet'}"
        _ensure_writable(combined)
        _write_table(frame, combined, fmt)
        written.append(combined)
        for year in years:
            year_path = (
                output_dir
                / f"year={year}"
                / f"monthly_expenditure.{'csv' if fmt == 'csv' else 'parquet'}"
            )
            _ensure_writable(year_path)
            year_frame = frame[frame["fiscal_year"] == year]
            _write_table(year_frame, year_path, fmt)
            written.append(year_path)

    dictionary_path = output_dir / "data_dictionary.csv"
    _ensure_writable(dictionary_path)
    pd.DataFrame(data_dictionary_rows()).to_csv(
        dictionary_path, index=False, encoding="utf-8-sig"
    )
    written.append(dictionary_path)

    summary_path = output_dir / "normalization_summary.json"
    _ensure_writable(summary_path)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    written.append(summary_path)

    issues_path = output_dir / "validation_issues.csv"
    _ensure_writable(issues_path)
    issues.to_csv(issues_path, index=False, encoding="utf-8-sig")
    written.append(issues_path)

    return written


def normalize_monthly(
    *,
    input_dir: Path,
    output_dir: Path,
    output_format: OutputFormat = "parquet",
    start_year: int | None = None,
    end_year: int | None = None,
    ministry_code: str | None = None,
    overwrite: bool = False,
) -> NormalizationResult:
    paths = discover_raw_files(
        input_dir,
        start_year=start_year,
        end_year=end_year,
        ministry_code=ministry_code,
    )
    rows, failed, raw_record_count = load_and_normalize_files(paths, input_dir=input_dir)
    frame = pd.DataFrame(rows)
    if not frame.empty:
        # 코드 컬럼을 명시적 문자열로 유지
        for column in CODE_FIELD_MAP.values():
            frame[column] = frame[column].astype("string")
        frame["execution_month"] = frame["execution_month"].astype("string")
        for column in AMOUNT_FIELD_MAP.values():
            frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")
        frame["fiscal_year"] = pd.to_numeric(frame["fiscal_year"], errors="coerce").astype(
            "Int64"
        )
        frame["source_page"] = pd.to_numeric(frame["source_page"], errors="coerce").astype(
            "Int64"
        )

    frame, issues = apply_validation_flags(frame)
    summary = build_normalization_summary(
        files_read=len(paths),
        raw_record_count=raw_record_count,
        frame=frame,
        issues=issues,
        failed_files=failed,
    )
    output_paths = write_outputs(
        frame,
        issues,
        summary,
        output_dir=output_dir,
        output_format=output_format,
        overwrite=overwrite,
    )
    return NormalizationResult(
        frame=frame,
        issues=issues,
        summary=summary,
        failed_files=failed,
        output_paths=output_paths,
    )
