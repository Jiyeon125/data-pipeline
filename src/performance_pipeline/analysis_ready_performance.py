from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd


class AnalysisReadyPerformanceError(ValueError):
    """분석용 성과지표 마스터를 안전하게 만들 수 없을 때 발생합니다."""


@dataclass(frozen=True)
class AnalysisReadyPerformanceResult:
    master: pd.DataFrame
    summary: dict[str, Any]
    output_paths: tuple[Path, ...]


REQUIRED_MANUAL_COLUMNS: tuple[str, ...] = (
    "source_indicator_id",
    "ministry_name",
    "fiscal_year",
    "performance_program_name",
    "planned_target_raw",
    "actual_value_raw",
    "official_achievement_rate_raw",
    "planned_target_numeric",
    "actual_value_numeric",
    "official_achievement_rate_numeric",
    "source_trace",
)

REQUIRED_RECONCILIATION_COLUMNS: tuple[str, ...] = (
    "source_indicator_id",
    "ministry_code",
    "ministry_name",
    "fiscal_year",
    "performance_program_name",
    "report_target_numeric_pdf",
    "actual_value_numeric_pdf",
    "official_achievement_rate_numeric_pdf",
    "pdf_report_target_raw",
    "pdf_report_actual_raw",
    "pdf_report_official_achievement_rate_raw",
    "report_target_match_status",
    "report_actual_match_status",
    "report_achievement_rate_match_status",
    "overall_reconciliation_status",
    "reviewer",
    "review_status",
    "review_note",
    "review_confirmed_at",
    "report_source_file",
    "report_split_pdf_page",
    "report_source_pdf_page",
    "documented_change_target_before_raw",
    "documented_change_target_after_raw",
    "documented_change_reason_raw",
)

REPORT_TARGET_USABLE_STATUSES = {"EXACT_MATCH", "MATCH_AFTER_CHANGE", "ROUNDING_ONLY"}
NONSTANDARD_FORMULA_INDICATOR_IDS = {
    "중기부-2022-II1-03",
    "중기부-2023-II1-03",
}
DEFAULT_REPORT_TARGET_CONFIRMATIONS_PATH = Path(
    "data/manual/performance/pdf_report_target_confirmations.csv"
)
REQUIRED_REPORT_TARGET_CONFIRMATION_COLUMNS: tuple[str, ...] = (
    "source_indicator_id",
    "confirmed_report_target_raw",
    "confirmed_report_target_numeric",
    "source_file",
    "split_pdf_page",
    "source_pdf_page",
    "reviewer",
    "confirmed_at",
    "note",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_columns(df: pd.DataFrame, required: tuple[str, ...], label: str) -> None:
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise AnalysisReadyPerformanceError(f"{label}에 필수 컬럼이 없습니다: {missing}")


def _require_unique_ids(df: pd.DataFrame, label: str) -> None:
    if df["source_indicator_id"].isna().any():
        raise AnalysisReadyPerformanceError(f"{label}의 source_indicator_id에 결측이 있습니다.")
    duplicates = df.loc[
        df["source_indicator_id"].duplicated(keep=False), "source_indicator_id"
    ].astype(str)
    if not duplicates.empty:
        raise AnalysisReadyPerformanceError(
            f"{label}의 source_indicator_id가 중복되었습니다: {sorted(duplicates.unique())}"
        )


def load_report_target_confirmations(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame(columns=REQUIRED_REPORT_TARGET_CONFIRMATION_COLUMNS)
    confirmations = pd.read_csv(path, dtype="string")
    _require_columns(
        confirmations,
        REQUIRED_REPORT_TARGET_CONFIRMATION_COLUMNS,
        "보고서 목표 육안확정 파일",
    )
    _require_unique_ids(confirmations, "보고서 목표 육안확정 파일")
    confirmations["confirmed_report_target_numeric"] = pd.to_numeric(
        confirmations["confirmed_report_target_numeric"], errors="coerce"
    )
    if confirmations["confirmed_report_target_numeric"].isna().any():
        raise AnalysisReadyPerformanceError(
            "보고서 목표 육안확정 파일에 숫자로 해석할 수 없는 확정값이 있습니다."
        )
    return confirmations


def _align_reconciliation(manual_df: pd.DataFrame, reconciliation_df: pd.DataFrame) -> pd.DataFrame:
    manual_ids = set(manual_df["source_indicator_id"].astype(str))
    reconciliation_ids = set(reconciliation_df["source_indicator_id"].astype(str))
    if manual_ids != reconciliation_ids:
        raise AnalysisReadyPerformanceError(
            "수기 마스터와 PDF 대조 결과의 행ID 집합이 다릅니다: "
            f"수기만 {len(manual_ids - reconciliation_ids)}건, "
            f"PDF만 {len(reconciliation_ids - manual_ids)}건"
        )
    indexed = reconciliation_df.assign(
        source_indicator_id=reconciliation_df["source_indicator_id"].astype(str)
    ).set_index("source_indicator_id")
    return indexed.loc[manual_df["source_indicator_id"].astype(str)].reset_index()


def _require_context_match(manual_df: pd.DataFrame, aligned: pd.DataFrame) -> None:
    context_columns = ("ministry_name", "fiscal_year", "performance_program_name")
    mismatched_ids: set[str] = set()
    for column in context_columns:
        manual_values = manual_df[column].astype("string").fillna("<NA>").reset_index(drop=True)
        pdf_values = aligned[column].astype("string").fillna("<NA>").reset_index(drop=True)
        mismatched_ids.update(
            manual_df.loc[manual_values.ne(pdf_values), "source_indicator_id"].astype(str)
        )
    if mismatched_ids:
        raise AnalysisReadyPerformanceError(
            "같은 source_indicator_id의 부처·연도·프로그램이 서로 다릅니다: "
            f"{sorted(mismatched_ids)}"
        )


def build_analysis_ready_master(
    manual_df: pd.DataFrame,
    reconciliation_df: pd.DataFrame,
    report_target_confirmations_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """원본 수기값을 보존하고 검수 확정된 PDF 결측 보완값만 별도 분석값으로 채택합니다."""
    _require_columns(manual_df, REQUIRED_MANUAL_COLUMNS, "수기 성과지표 마스터")
    _require_columns(
        reconciliation_df,
        REQUIRED_RECONCILIATION_COLUMNS,
        "PDF 대조 결과",
    )
    _require_unique_ids(manual_df, "수기 성과지표 마스터")
    _require_unique_ids(reconciliation_df, "PDF 대조 결과")

    analysis_columns = {
        "analysis_plan_target_raw",
        "analysis_plan_target_numeric",
        "analysis_report_target_raw",
        "analysis_report_target_numeric",
        "analysis_report_target_source",
        "analysis_report_target_confirmed_source_file",
        "analysis_report_target_confirmed_split_page",
        "analysis_report_target_confirmed_source_page",
        "analysis_report_target_confirmed_at",
        "analysis_report_target_confirmation_note",
        "analysis_actual_value_raw",
        "analysis_actual_value_numeric",
        "analysis_actual_value_source",
        "analysis_official_achievement_rate_raw",
        "analysis_official_achievement_rate_numeric",
        "analysis_official_achievement_rate_source",
        "analysis_actual_value_missing_flag",
        "analysis_achievement_rate_missing_flag",
        "analysis_ready_for_same_year_rate",
        "analysis_achievement_rate_formula_review_required",
        "analysis_achievement_rate_formula_review_reason",
        "analysis_achievement_rate_formula_eligible",
        "analysis_value_adoption_status",
    }
    collisions = sorted(analysis_columns.intersection(manual_df.columns))
    if collisions:
        raise AnalysisReadyPerformanceError(
            f"수기 마스터에 분석용 파생 컬럼이 이미 존재합니다: {collisions}"
        )

    manual = manual_df.reset_index(drop=True).copy()
    aligned = _align_reconciliation(manual, reconciliation_df)
    _require_context_match(manual, aligned)

    confirmed = aligned["review_status"].eq("CONFIRMED")
    trusted_row = aligned["overall_reconciliation_status"].eq("EXACT_MATCH") | confirmed

    actual_fill = (
        manual["actual_value_numeric"].isna()
        & aligned["actual_value_numeric_pdf"].notna()
        & aligned["report_actual_match_status"].eq("MANUAL_MISSING_PDF_PRESENT")
        & confirmed
    )
    rate_fill = (
        manual["official_achievement_rate_numeric"].isna()
        & aligned["official_achievement_rate_numeric_pdf"].notna()
        & aligned["report_achievement_rate_match_status"].eq("MANUAL_MISSING_PDF_PRESENT")
        & confirmed
    )
    report_target_usable = (
        aligned["report_target_numeric_pdf"].notna()
        & aligned["report_target_match_status"].isin(REPORT_TARGET_USABLE_STATUSES)
        & trusted_row
    )

    result = manual.copy()
    if "ministry_code" not in result.columns:
        result.insert(
            1,
            "ministry_code",
            aligned["ministry_code"].astype("string").str.zfill(3),
        )
    result["analysis_plan_target_raw"] = manual["planned_target_raw"]
    result["analysis_plan_target_numeric"] = manual["planned_target_numeric"]
    result["analysis_report_target_raw"] = aligned["pdf_report_target_raw"].where(
        report_target_usable
    )
    result["analysis_report_target_numeric"] = aligned["report_target_numeric_pdf"].where(
        report_target_usable
    )
    result["analysis_report_target_source"] = "MISSING"
    result.loc[
        report_target_usable & aligned["report_target_match_status"].eq("EXACT_MATCH"),
        "analysis_report_target_source",
    ] = "PDF_EXACT"
    result.loc[
        report_target_usable & ~aligned["report_target_match_status"].eq("EXACT_MATCH"),
        "analysis_report_target_source",
    ] = "PDF_CONFIRMED"
    result["analysis_report_target_confirmed_source_file"] = pd.NA
    result["analysis_report_target_confirmed_split_page"] = pd.NA
    result["analysis_report_target_confirmed_source_page"] = pd.NA
    result["analysis_report_target_confirmed_at"] = pd.NA
    result["analysis_report_target_confirmation_note"] = pd.NA

    confirmations = (
        report_target_confirmations_df
        if report_target_confirmations_df is not None
        else pd.DataFrame(columns=REQUIRED_REPORT_TARGET_CONFIRMATION_COLUMNS)
    )
    if not confirmations.empty:
        _require_columns(
            confirmations,
            REQUIRED_REPORT_TARGET_CONFIRMATION_COLUMNS,
            "보고서 목표 육안확정 파일",
        )
        _require_unique_ids(confirmations, "보고서 목표 육안확정 파일")
        unknown_ids = set(confirmations["source_indicator_id"].astype(str)) - set(
            result["source_indicator_id"].astype(str)
        )
        if unknown_ids:
            raise AnalysisReadyPerformanceError(
                f"보고서 목표 육안확정 파일에 알 수 없는 행ID가 있습니다: {sorted(unknown_ids)}"
            )
        indexed_confirmations = confirmations.assign(
            source_indicator_id=confirmations["source_indicator_id"].astype(str)
        ).set_index("source_indicator_id")
        confirmed_targets = (
            result["source_indicator_id"]
            .astype(str)
            .map(indexed_confirmations["confirmed_report_target_numeric"])
        )
        visually_confirmed = confirmed_targets.notna()
        invalid = visually_confirmed & (
            ~aligned["review_status"].eq("CONFIRMED")
            | result["analysis_report_target_numeric"].notna()
            | ~confirmed_targets.eq(result["analysis_plan_target_numeric"])
        )
        if invalid.any():
            invalid_ids = result.loc[invalid, "source_indicator_id"].astype(str).tolist()
            raise AnalysisReadyPerformanceError(
                "육안확정 목표는 PDF 검수확정·기존 목표 결측·계획 목표 일치 조건을 "
                f"모두 충족해야 합니다: {invalid_ids}"
            )
        for output_column, confirmation_column in (
            ("analysis_report_target_raw", "confirmed_report_target_raw"),
            ("analysis_report_target_numeric", "confirmed_report_target_numeric"),
            ("analysis_report_target_confirmed_source_file", "source_file"),
            ("analysis_report_target_confirmed_split_page", "split_pdf_page"),
            ("analysis_report_target_confirmed_source_page", "source_pdf_page"),
            ("analysis_report_target_confirmed_at", "confirmed_at"),
            ("analysis_report_target_confirmation_note", "note"),
        ):
            result.loc[visually_confirmed, output_column] = (
                result.loc[visually_confirmed, "source_indicator_id"]
                .astype(str)
                .map(indexed_confirmations[confirmation_column])
            )
        result.loc[visually_confirmed, "analysis_report_target_source"] = "PDF_VISUAL_CONFIRMED"

    result["analysis_actual_value_raw"] = manual["actual_value_raw"]
    result.loc[actual_fill, "analysis_actual_value_raw"] = aligned.loc[
        actual_fill, "pdf_report_actual_raw"
    ]
    result["analysis_actual_value_numeric"] = manual["actual_value_numeric"]
    result.loc[actual_fill, "analysis_actual_value_numeric"] = aligned.loc[
        actual_fill, "actual_value_numeric_pdf"
    ]
    result["analysis_actual_value_source"] = "MISSING"
    result.loc[manual["actual_value_numeric"].notna(), "analysis_actual_value_source"] = "MANUAL"
    result.loc[actual_fill, "analysis_actual_value_source"] = "PDF_CONFIRMED"

    result["analysis_official_achievement_rate_raw"] = manual["official_achievement_rate_raw"]
    result.loc[rate_fill, "analysis_official_achievement_rate_raw"] = aligned.loc[
        rate_fill, "pdf_report_official_achievement_rate_raw"
    ]
    result["analysis_official_achievement_rate_numeric"] = manual[
        "official_achievement_rate_numeric"
    ]
    result.loc[rate_fill, "analysis_official_achievement_rate_numeric"] = aligned.loc[
        rate_fill, "official_achievement_rate_numeric_pdf"
    ]
    result["analysis_official_achievement_rate_source"] = "MISSING"
    result.loc[
        manual["official_achievement_rate_numeric"].notna(),
        "analysis_official_achievement_rate_source",
    ] = "MANUAL"
    result.loc[rate_fill, "analysis_official_achievement_rate_source"] = "PDF_CONFIRMED"

    result["analysis_actual_value_missing_flag"] = result["analysis_actual_value_numeric"].isna()
    result["analysis_achievement_rate_missing_flag"] = result[
        "analysis_official_achievement_rate_numeric"
    ].isna()
    result["analysis_ready_for_same_year_rate"] = ~result["analysis_achievement_rate_missing_flag"]
    result["analysis_achievement_rate_formula_review_required"] = result[
        "source_indicator_id"
    ].isin(NONSTANDARD_FORMULA_INDICATOR_IDS)
    result["analysis_achievement_rate_formula_review_reason"] = pd.NA
    result.loc[
        result["analysis_achievement_rate_formula_review_required"],
        "analysis_achievement_rate_formula_review_reason",
    ] = "공식 달성률이 일반 상향·하향 산식으로 재현되지 않아 사업별 산식 원문 확인 필요"
    result["analysis_achievement_rate_formula_eligible"] = (
        result["analysis_ready_for_same_year_rate"]
        & ~result["analysis_achievement_rate_formula_review_required"]
    )
    result["analysis_value_adoption_status"] = "MANUAL_VALUES_PRESERVED"
    result.loc[actual_fill | rate_fill, "analysis_value_adoption_status"] = (
        "PDF_CONFIRMED_MISSING_VALUES_FILLED"
    )

    result["pdf_reconciliation_status"] = aligned["overall_reconciliation_status"]
    result["pdf_review_status"] = aligned["review_status"]
    result["pdf_reviewer"] = aligned["reviewer"]
    result["pdf_review_note"] = aligned["review_note"]
    result["pdf_review_confirmed_at"] = aligned["review_confirmed_at"]
    result["pdf_report_target_match_status"] = aligned["report_target_match_status"]
    result["pdf_report_actual_match_status"] = aligned["report_actual_match_status"]
    result["pdf_report_achievement_rate_match_status"] = aligned[
        "report_achievement_rate_match_status"
    ]
    result["pdf_report_source_file"] = aligned["report_source_file"]
    result["pdf_report_split_page"] = aligned["report_split_pdf_page"]
    result["pdf_report_source_page"] = aligned["report_source_pdf_page"]
    result["documented_change_target_before_raw"] = aligned["documented_change_target_before_raw"]
    result["documented_change_target_after_raw"] = aligned["documented_change_target_after_raw"]
    result["documented_change_reason_raw"] = aligned["documented_change_reason_raw"]

    result["analysis_source_trace"] = manual["source_trace"]
    adopted = actual_fill | rate_fill
    result.loc[adopted, "analysis_source_trace"] = (
        manual.loc[adopted, "source_trace"].astype(str)
        + " -> "
        + aligned.loc[adopted, "report_source_file"].astype(str)
        + " split_page="
        + aligned.loc[adopted, "report_split_pdf_page"].astype("Int64").astype(str)
        + " review=CONFIRMED"
    )
    if not confirmations.empty:
        result.loc[visually_confirmed, "analysis_source_trace"] = (
            result.loc[visually_confirmed, "analysis_source_trace"].astype(str)
            + " -> "
            + result.loc[visually_confirmed, "analysis_report_target_confirmed_source_file"].astype(
                str
            )
            + " split_page="
            + result.loc[visually_confirmed, "analysis_report_target_confirmed_split_page"].astype(
                str
            )
            + " target_review=VISUAL_CONFIRMED"
        )

    if not manual.equals(result.loc[:, manual.columns]):
        raise AnalysisReadyPerformanceError("원본 수기 컬럼이 변경되었습니다.")
    return result


def build_verified_manual_analysis_ready_master(
    manual_df: pd.DataFrame,
    *,
    ministry_code: str,
) -> pd.DataFrame:
    """사람 검수 골드셋의 공식 보고값을 재계산 없이 분석용 컬럼으로 복사합니다."""
    _require_columns(manual_df, REQUIRED_MANUAL_COLUMNS, "수기 성과지표 마스터")
    _require_unique_ids(manual_df, "수기 성과지표 마스터")
    if not ministry_code.strip():
        raise AnalysisReadyPerformanceError("부처코드는 비어 있을 수 없습니다.")

    result = manual_df.reset_index(drop=True).copy()
    code = ministry_code.zfill(3)
    if "ministry_code" in result:
        existing = result["ministry_code"].astype("string").str.zfill(3)
        if existing.notna().any() and not existing.dropna().eq(code).all():
            raise AnalysisReadyPerformanceError("수기 마스터의 부처코드가 요청 범위와 다릅니다.")
        result["ministry_code"] = code
    else:
        result.insert(1, "ministry_code", code)

    result["analysis_plan_target_raw"] = result["planned_target_raw"]
    result["analysis_plan_target_numeric"] = result["planned_target_numeric"]
    result["analysis_report_target_raw"] = pd.NA
    result["analysis_report_target_numeric"] = pd.NA
    result["analysis_report_target_source"] = "NOT_AVAILABLE_IN_GOLDSET"
    result["analysis_actual_value_raw"] = result["actual_value_raw"]
    result["analysis_actual_value_numeric"] = result["actual_value_numeric"]
    result["analysis_actual_value_source"] = "VERIFIED_MANUAL_GOLDSET"
    result.loc[result["actual_value_numeric"].isna(), "analysis_actual_value_source"] = "MISSING"
    result["analysis_official_achievement_rate_raw"] = result["official_achievement_rate_raw"]
    result["analysis_official_achievement_rate_numeric"] = result[
        "official_achievement_rate_numeric"
    ]
    result["analysis_official_achievement_rate_source"] = "VERIFIED_MANUAL_GOLDSET"
    rate_missing = result["official_achievement_rate_numeric"].isna()
    result.loc[rate_missing, "analysis_official_achievement_rate_source"] = "MISSING"
    result["analysis_actual_value_missing_flag"] = result["actual_value_numeric"].isna()
    result["analysis_achievement_rate_missing_flag"] = rate_missing
    result["analysis_ready_for_same_year_rate"] = ~rate_missing
    result["analysis_achievement_rate_formula_review_required"] = (
        result["official_achievement_rate_raw"].notna() & rate_missing
    )
    result["analysis_achievement_rate_formula_review_reason"] = pd.NA
    result.loc[
        result["analysis_achievement_rate_formula_review_required"],
        "analysis_achievement_rate_formula_review_reason",
    ] = "수기 검수본에 공식 달성률 원문은 있으나 숫자로 정규화되지 않음"
    result["analysis_achievement_rate_formula_eligible"] = ~rate_missing
    result["analysis_value_adoption_status"] = "VERIFIED_MANUAL_VALUES_PRESERVED"
    result["analysis_source_trace"] = result["source_trace"]
    result["analysis_rate_use_basis"] = "공식 보고 달성률 사용; 목표·실적 기반 산식 재계산 아님"

    if not manual_df.reset_index(drop=True).equals(
        result.loc[:, manual_df.columns].reset_index(drop=True)
    ):
        raise AnalysisReadyPerformanceError("원본 수기 컬럼이 변경되었습니다.")
    return result


def build_analysis_ready_summary(
    manual_df: pd.DataFrame,
    master: pd.DataFrame,
    *,
    source_hashes: dict[str, str] | None = None,
    input_files_unchanged: bool | None = None,
) -> dict[str, Any]:
    filled = master["analysis_value_adoption_status"].eq("PDF_CONFIRMED_MISSING_VALUES_FILLED")
    pdf_actual = master["analysis_actual_value_source"].eq("PDF_CONFIRMED")
    pdf_rate = master["analysis_official_achievement_rate_source"].eq("PDF_CONFIRMED")
    visual_target = master["analysis_report_target_source"].eq("PDF_VISUAL_CONFIRMED")
    program_year = (
        master.groupby(
            ["ministry_code", "fiscal_year", "performance_program_name"],
            dropna=False,
        )
        .agg(
            indicator_count=("source_indicator_id", "size"),
            available_rate_count=(
                "analysis_official_achievement_rate_numeric",
                "count",
            ),
            formula_review_count=(
                "analysis_achievement_rate_formula_review_required",
                "sum",
            ),
        )
        .reset_index()
    )
    program_year["all_rates_available"] = program_year["available_rate_count"].eq(
        program_year["indicator_count"]
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "grain": "ministry x program x performance_indicator x fiscal_year",
        "input_row_count": len(manual_df),
        "output_row_count": len(master),
        "rows_by_fiscal_year": {
            str(key): int(value)
            for key, value in master["fiscal_year"].value_counts().sort_index().items()
        },
        "manual_missing_before": {
            "actual_value": int(manual_df["actual_value_numeric"].isna().sum()),
            "official_achievement_rate": int(
                manual_df["official_achievement_rate_numeric"].isna().sum()
            ),
        },
        "pdf_confirmed_fill_count": {
            "rows": int(filled.sum()),
            "actual_value": int(pdf_actual.sum()),
            "official_achievement_rate": int(pdf_rate.sum()),
            "rows_by_fiscal_year": {
                str(key): int(value)
                for key, value in master.loc[filled, "fiscal_year"]
                .value_counts()
                .sort_index()
                .items()
            },
        },
        "analysis_missing_after": {
            "actual_value": int(master["analysis_actual_value_missing_flag"].sum()),
            "official_achievement_rate": int(
                master["analysis_achievement_rate_missing_flag"].sum()
            ),
            "report_target": int(master["analysis_report_target_numeric"].isna().sum()),
        },
        "visually_confirmed_report_target_count": int(
            master["analysis_report_target_source"].eq("PDF_VISUAL_CONFIRMED").sum()
        ),
        "formula_review": {
            "nonstandard_formula_row_count": int(
                master["analysis_achievement_rate_formula_review_required"].sum()
            ),
            "formula_eligible_rate_row_count": int(
                master["analysis_achievement_rate_formula_eligible"].sum()
            ),
        },
        "program_year_completeness": {
            "program_year_count": len(program_year),
            "all_rates_available_count": int(program_year["all_rates_available"].sum()),
            "formula_review_program_year_count": int(
                program_year["formula_review_count"].gt(0).sum()
            ),
        },
        "analysis_source_counts": {
            "actual_value": {
                str(key): int(value)
                for key, value in master["analysis_actual_value_source"].value_counts().items()
            },
            "official_achievement_rate": {
                str(key): int(value)
                for key, value in master["analysis_official_achievement_rate_source"]
                .value_counts()
                .items()
            },
            "report_target": {
                str(key): int(value)
                for key, value in master["analysis_report_target_source"].value_counts().items()
            },
        },
        "source_sha256": source_hashes or {},
        "validation": {
            "row_count_preserved": len(master) == len(manual_df),
            "indicator_id_unique": bool(~master["source_indicator_id"].duplicated().any()),
            "original_columns_preserved": manual_df.reset_index(drop=True).equals(
                master.loc[:, manual_df.columns].reset_index(drop=True)
            ),
            "pdf_adoption_requires_confirmation": bool(
                master.loc[pdf_actual | pdf_rate, "pdf_review_status"].eq("CONFIRMED").all()
            ),
            "visual_target_adoption_requires_confirmation": bool(
                master.loc[visual_target, "pdf_review_status"].eq("CONFIRMED").all()
            ),
            "manual_nonnull_actual_preserved": bool(
                master.loc[
                    manual_df["actual_value_numeric"].notna(),
                    "analysis_actual_value_numeric",
                ]
                .reset_index(drop=True)
                .equals(
                    manual_df.loc[
                        manual_df["actual_value_numeric"].notna(), "actual_value_numeric"
                    ].reset_index(drop=True)
                )
            ),
            "manual_nonnull_rate_preserved": bool(
                master.loc[
                    manual_df["official_achievement_rate_numeric"].notna(),
                    "analysis_official_achievement_rate_numeric",
                ]
                .reset_index(drop=True)
                .equals(
                    manual_df.loc[
                        manual_df["official_achievement_rate_numeric"].notna(),
                        "official_achievement_rate_numeric",
                    ].reset_index(drop=True)
                )
            ),
            "input_files_unchanged": input_files_unchanged,
        },
        "interpretation_limit": (
            "PDF 검수 확정값은 수기 결측 보완에만 사용합니다. 계획 목표와 보고서 개정 "
            "목표를 분리하고, 공식 달성률을 재계산값으로 덮어쓰지 않으며, 프로그램 성과를 "
            "세부사업에 귀속하지 않습니다."
        ),
    }


def run_analysis_ready_master(
    *,
    manual_path: Path = Path("data/processed/performance/program_kpi_year.parquet"),
    reconciliation_path: Path = Path(
        "data/processed/performance/pdf_reconciliation/mss_performance_pdf_reconciliation.parquet"
    ),
    report_target_confirmations_path: Path = DEFAULT_REPORT_TARGET_CONFIRMATIONS_PATH,
    output_dir: Path = Path("data/processed/performance/analysis_ready"),
    overwrite: bool = False,
) -> AnalysisReadyPerformanceResult:
    output_paths = (
        output_dir / "program_kpi_year_analysis_ready.parquet",
        output_dir / "analysis_ready_summary.json",
    )
    existing = [path for path in output_paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "기존 산출물이 있습니다. --overwrite를 지정하세요: "
            + ", ".join(str(path) for path in existing)
        )
    for path in (manual_path, reconciliation_path):
        if not path.is_file():
            raise AnalysisReadyPerformanceError(f"입력 파일을 찾을 수 없습니다: {path}")

    input_paths = [manual_path, reconciliation_path]
    if report_target_confirmations_path.is_file():
        input_paths.append(report_target_confirmations_path)
    source_hashes_before = {str(path): _sha256(path) for path in input_paths}
    manual_df = pd.read_parquet(manual_path)
    reconciliation_df = pd.read_parquet(reconciliation_path)
    confirmations_df = load_report_target_confirmations(report_target_confirmations_path)
    master = build_analysis_ready_master(
        manual_df,
        reconciliation_df,
        confirmations_df,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    master.to_parquet(output_paths[0], index=False)
    source_hashes_after = {str(path): _sha256(path) for path in input_paths}
    summary = build_analysis_ready_summary(
        manual_df,
        master,
        source_hashes=source_hashes_before,
        input_files_unchanged=source_hashes_before == source_hashes_after,
    )
    output_paths[1].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return AnalysisReadyPerformanceResult(
        master=master,
        summary=summary,
        output_paths=output_paths,
    )


def run_verified_manual_analysis_ready_master(
    *,
    manual_path: Path,
    output_dir: Path,
    ministry_code: str,
    overwrite: bool = False,
) -> AnalysisReadyPerformanceResult:
    """수기 골드셋을 원본 보존 상태로 동년도 분석 입력 형식에 맞춥니다."""
    output_paths = (
        output_dir / "program_kpi_year_analysis_ready.parquet",
        output_dir / "analysis_ready_summary.json",
    )
    existing = [path for path in output_paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "기존 산출물이 있습니다. --overwrite를 지정하세요: "
            + ", ".join(str(path) for path in existing)
        )
    if not manual_path.is_file():
        raise AnalysisReadyPerformanceError(f"입력 파일을 찾을 수 없습니다: {manual_path}")

    source_hash = _sha256(manual_path)
    manual_df = pd.read_parquet(manual_path)
    master = build_verified_manual_analysis_ready_master(
        manual_df,
        ministry_code=ministry_code,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    master.to_parquet(output_paths[0], index=False)
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "grain": "ministry x program x performance_indicator x fiscal_year",
        "ministry_code": ministry_code.zfill(3),
        "input_row_count": len(manual_df),
        "output_row_count": len(master),
        "rows_by_fiscal_year": {
            str(key): int(value)
            for key, value in master["fiscal_year"].value_counts().sort_index().items()
        },
        "analysis_missing": {
            "actual_value": int(master["analysis_actual_value_missing_flag"].sum()),
            "official_achievement_rate": int(
                master["analysis_achievement_rate_missing_flag"].sum()
            ),
            "report_target": int(master["analysis_report_target_numeric"].isna().sum()),
        },
        "formula_eligible_rate_row_count": int(
            master["analysis_achievement_rate_formula_eligible"].sum()
        ),
        "source_sha256": {str(manual_path): source_hash},
        "validation": {
            "row_count_preserved": len(master) == len(manual_df),
            "indicator_id_unique": not master["source_indicator_id"].duplicated().any(),
            "original_columns_preserved": manual_df.reset_index(drop=True).equals(
                master.loc[:, manual_df.columns].reset_index(drop=True)
            ),
            "input_file_unchanged": source_hash == _sha256(manual_path),
            "ministry_code_preserved": bool(
                master["ministry_code"].eq(ministry_code.zfill(3)).all()
            ),
        },
        "interpretation_limit": (
            "수기 검수본의 공식 달성률을 사용하며 산식을 재계산하지 않습니다. "
            "보고서 최종 목표는 골드셋에 없어 결측으로 유지하고 계획 목표로 대체하지 않습니다."
        ),
    }
    output_paths[1].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return AnalysisReadyPerformanceResult(
        master=master,
        summary=summary,
        output_paths=output_paths,
    )


__all__ = [
    "DEFAULT_REPORT_TARGET_CONFIRMATIONS_PATH",
    "AnalysisReadyPerformanceError",
    "AnalysisReadyPerformanceResult",
    "build_analysis_ready_master",
    "build_analysis_ready_summary",
    "build_verified_manual_analysis_ready_master",
    "load_report_target_confirmations",
    "run_analysis_ready_master",
    "run_verified_manual_analysis_ready_master",
]
