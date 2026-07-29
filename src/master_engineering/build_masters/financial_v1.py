"""예산·월별 집행·결산을 연결한 사업-연도 재정 v1 테이블을 생성합니다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

SETTLEMENT_AMOUNT_COLUMNS = (
    "settlement_budget_amount",
    "settlement_adjustment_amount",
    "settlement_current_budget_amount",
    "settlement_expenditure_amount",
    "settlement_net_expenditure_amount",
    "settlement_carryover_amount",
    "settlement_unused_amount",
)
JOIN_KEY = ["project_id", "fiscal_year", "ministry_code"]


@dataclass
class FinancialV1Result:
    frame: pd.DataFrame
    issues: pd.DataFrame
    summary: dict[str, Any]
    output_paths: list[Path]


def _first_not_null(series: pd.Series) -> Any:
    values = series.dropna()
    return values.iloc[0] if not values.empty else pd.NA


def _collapse_settlement(settlement: pd.DataFrame) -> pd.DataFrame:
    counts = (
        settlement.groupby(JOIN_KEY, dropna=False)
        .size()
        .rename("settlement_record_count")
        .reset_index()
    )
    dimension_columns = [
        "ministry_name",
        "account_name",
        "account_category_name",
        "field_name",
        "sector_name",
        "program_name",
        "activity_name",
        "subactivity_name",
        "matching_status",
        "source_file",
        "source_path",
    ]
    aggregations = {column: (column, _first_not_null) for column in dimension_columns}
    aggregations.update({column: (column, _first_not_null) for column in SETTLEMENT_AMOUNT_COLUMNS})
    collapsed = (
        settlement.groupby(JOIN_KEY, dropna=False)
        .agg(**aggregations)
        .reset_index()
        .merge(counts, how="left", on=JOIN_KEY, validate="one_to_one")
    )
    duplicate = collapsed["settlement_record_count"] > 1
    collapsed.loc[duplicate, list(SETTLEMENT_AMOUNT_COLUMNS)] = pd.NA
    collapsed["settlement_duplicate_key_flag"] = duplicate
    return collapsed


def _account_type(value: Any, account_code: Any) -> str:
    text = "" if pd.isna(value) else str(value)
    code = "" if pd.isna(account_code) else str(account_code)
    if "기금" in text:
        return "FUND"
    if "일반회계" in text:
        return "GENERAL_ACCOUNT"
    if "특별회계" in text or (len(code) == 3 and code.startswith("4")):
        return "SPECIAL_ACCOUNT"
    return "OTHER"


def _reconciliation_status(row: pd.Series) -> str:
    if row["settlement_join_status"] != "BOTH":
        return "NOT_COMPARABLE_SOURCE_MISSING"
    month = row.get("latest_execution_month")
    if pd.isna(month) or not str(month).endswith("12"):
        return "NOT_COMPARABLE_DECEMBER_MISSING"
    if pd.isna(row.get("cumulative_expenditure_amount")) or pd.isna(
        row.get("settlement_expenditure_amount")
    ):
        return "NOT_COMPARABLE_AMOUNT_MISSING"
    difference = int(row["settlement_vs_december_difference"])
    if difference == 0:
        return "EXACT"
    relative = float(row["settlement_vs_december_relative_difference"])
    if abs(difference) <= 1_000 or relative <= 0.000001:
        return "WITHIN_TOLERANCE"
    return "MISMATCH"


def _issue_reasons(row: pd.Series) -> str:
    reasons: list[str] = []
    if row["settlement_join_status"] == "FINANCIAL_ONLY":
        reasons.append("SETTLEMENT_MISSING")
    elif row["settlement_join_status"] == "SETTLEMENT_ONLY":
        reasons.append("FINANCIAL_BASE_MISSING")
    duplicate_settlement = row.get("settlement_duplicate_key_flag", False)
    if pd.notna(duplicate_settlement) and bool(duplicate_settlement):
        reasons.append("SETTLEMENT_DUPLICATE_KEY")
    matching = row.get("settlement_matching_status")
    if matching == "NO_MATCH":
        reasons.append("SETTLEMENT_CODE_NO_MATCH")
    elif matching == "MULTIPLE_MATCHES":
        reasons.append("SETTLEMENT_CODE_MULTIPLE_MATCHES")
    duplicate_monthly = row.get("monthly_duplicate_review_required", False)
    if pd.notna(duplicate_monthly) and bool(duplicate_monthly):
        reasons.append("MONTHLY_LATEST_DUPLICATE")
    reconciliation = row.get("settlement_reconciliation_status")
    if reconciliation == "MISMATCH":
        gross_difference = row.get("settlement_vs_december_difference")
        net_amount = row.get("settlement_net_expenditure_amount")
        cumulative = row.get("cumulative_expenditure_amount")
        net_closer = (
            pd.notna(net_amount)
            and pd.notna(cumulative)
            and pd.notna(gross_difference)
            and abs(int(net_amount) - int(cumulative)) < abs(int(gross_difference))
        )
        if net_closer:
            reasons.append("GROSS_NET_BASIS_DIFFERENCE_CANDIDATE")
        elif row.get("account_type") == "FUND":
            reasons.append("FUND_MONTHLY_SETTLEMENT_BASIS_MISMATCH")
        else:
            reasons.append("DECEMBER_SETTLEMENT_MISMATCH")
    elif reconciliation == "NOT_COMPARABLE_DECEMBER_MISSING":
        reasons.append("DECEMBER_CUMULATIVE_MISSING")
    denominator = row.get("execution_denominator_status")
    if denominator in {
        "MISSING_DENOMINATOR",
        "ZERO_DENOMINATOR",
        "UNSUPPORTED_ACCOUNT_TYPE",
        "UNCONFIRMED_FUND_PLAN_DENOMINATOR",
    }:
        reasons.append(denominator)
    execution_rate = row.get("execution_rate")
    if pd.notna(execution_rate) and float(execution_rate) > 2:
        reasons.append("EXECUTION_RATE_EXTREME")
    elif pd.notna(execution_rate) and float(execution_rate) > 1:
        reasons.append("EXECUTION_RATE_OVER_1")
    return ";".join(dict.fromkeys(reasons))


ISSUE_METADATA = {
    "SETTLEMENT_MISSING": (
        "SOURCE_COVERAGE",
        "HIGH",
        "예산·월별 사업에 대응하는 결산 행이 없음",
        "명칭·코드 변경, 종료·신규, 원본 누락 여부 확인",
    ),
    "FINANCIAL_BASE_MISSING": (
        "SOURCE_COVERAGE",
        "HIGH",
        "결산 사업에 대응하는 예산·월별 기준 행이 없음",
        "코드 매칭 후보와 사업 계보 확인",
    ),
    "UNCONFIRMED_FUND_PLAN_DENOMINATOR": (
        "DEFINITION",
        "HIGH",
        "기금 지출계획현액과 월별 예산현액 필드의 공식 대응 관계가 미확인",
        "공식 필드 명세 확인 전 기금 집행률·집행 신호·순위에서 제외",
    ),
    "SETTLEMENT_DUPLICATE_KEY": (
        "GRAIN_UNIQUENESS",
        "HIGH",
        "동일 사업-연도에 복수 결산 행 존재",
        "계정·회계 세부 차원을 확인한 뒤 집계 또는 분리",
    ),
    "SETTLEMENT_CODE_NO_MATCH": (
        "ENTITY_MATCHING",
        "HIGH",
        "동일 명칭 코드 후보가 없음",
        "명칭·코드 변경 또는 신규 사업 여부 확인",
    ),
    "SETTLEMENT_CODE_MULTIPLE_MATCHES": (
        "ENTITY_MATCHING",
        "HIGH",
        "동일 명칭에 복수 코드 후보 존재",
        "회계·프로그램·단위사업 계층으로 후보 확정",
    ),
    "MONTHLY_LATEST_DUPLICATE": (
        "GRAIN_UNIQUENESS",
        "HIGH",
        "최신 월 동일 사업키 복수 행 존재",
        "원본 행 차이와 추가 차원 확인",
    ),
    "DECEMBER_SETTLEMENT_MISMATCH": (
        "AMOUNT_CONSISTENCY",
        "HIGH",
        "12월 누계와 결산 지출총액 불일치",
        "정산·환수·마감조정·집계기준 확인",
    ),
    "GROSS_NET_BASIS_DIFFERENCE_CANDIDATE": (
        "AMOUNT_CONSISTENCY",
        "MEDIUM",
        "결산 지출순액이 12월 누계에 더 가까움",
        "총액·순액 및 환수·반납 기준 확인",
    ),
    "FUND_MONTHLY_SETTLEMENT_BASIS_MISMATCH": (
        "AMOUNT_CONSISTENCY",
        "HIGH",
        "기금 월별 누계와 결산 지출 기준 불일치",
        "기금 운용·결산 기준 및 연말 조정 확인",
    ),
    "DECEMBER_CUMULATIVE_MISSING": (
        "PERIOD_COVERAGE",
        "HIGH",
        "12월 누계 관측값 없음",
        "12월 원본 누락·중복·사업 종료 여부 확인",
    ),
    "MISSING_DENOMINATOR": (
        "METRIC_DEFINITION",
        "HIGH",
        "집행률 분모 누락",
        "예산현액 또는 기금 지출계획현액 확인",
    ),
    "ZERO_DENOMINATOR": (
        "METRIC_DEFINITION",
        "MEDIUM",
        "집행률 분모가 0",
        "신규·종료·조정 사업 여부 확인 후 제외",
    ),
    "UNSUPPORTED_ACCOUNT_TYPE": (
        "METRIC_DEFINITION",
        "MEDIUM",
        "회계유형 미확정",
        "회계코드 매핑표 보완",
    ),
    "EXECUTION_RATE_OVER_1": (
        "METRIC_VALIDITY",
        "MEDIUM",
        "집행률이 1을 초과",
        "예산현액 조정·초과지출·분모 기준 확인",
    ),
    "EXECUTION_RATE_EXTREME": (
        "METRIC_VALIDITY",
        "HIGH",
        "집행률이 2를 초과",
        "소액 분모·단위·회계유형·조인 정확성 우선 확인",
    ),
}


def build_financial_v1(
    *,
    financial_base_path: Path,
    settlement_path: Path,
    output_dir: Path,
    overwrite: bool = False,
) -> FinancialV1Result:
    financial = pd.read_parquet(financial_base_path)
    settlement = _collapse_settlement(pd.read_parquet(settlement_path))
    for frame in (financial, settlement):
        frame["fiscal_year"] = pd.to_numeric(frame["fiscal_year"], errors="coerce").astype("Int64")
        frame["ministry_code"] = frame["ministry_code"].astype("string")

    merged = financial.merge(
        settlement,
        how="outer",
        on=JOIN_KEY,
        suffixes=("", "_settlement"),
        indicator="settlement_join_status",
        validate="one_to_one",
    )
    merged["settlement_join_status"] = merged["settlement_join_status"].map(
        {
            "both": "BOTH",
            "left_only": "FINANCIAL_ONLY",
            "right_only": "SETTLEMENT_ONLY",
        }
    )
    merged["settlement_matching_status"] = merged.get("matching_status_settlement")
    merged.insert(0, "table_id_v1", "project_year_financial_v1")

    merged["settlement_vs_december_difference"] = (
        merged["settlement_expenditure_amount"] - merged["cumulative_expenditure_amount"]
    ).astype("Int64")
    divisor = merged["settlement_expenditure_amount"].abs().clip(lower=1)
    merged["settlement_vs_december_relative_difference"] = (
        merged["settlement_vs_december_difference"].abs() / divisor
    )
    merged["settlement_reconciliation_status"] = merged.apply(_reconciliation_status, axis=1)

    account_name = merged.get("account_name_settlement").combine_first(merged.get("account_name"))
    account_code = merged.get("account_code", pd.Series(pd.NA, index=merged.index))
    merged["account_type"] = [
        _account_type(name, code) for name, code in zip(account_name, account_code, strict=True)
    ]
    merged["account_type_basis"] = "ACCOUNT_NAME"
    responsible_operation = merged["account_type"].eq("SPECIAL_ACCOUNT") & ~account_name.fillna(
        ""
    ).str.contains("특별회계")
    merged.loc[responsible_operation, "account_type_basis"] = (
        "ACCOUNT_CODE_4XX_RESPONSIBLE_OPERATION_SPECIAL"
    )
    merged.loc[merged["account_type"].eq("OTHER"), "account_type_basis"] = "UNRESOLVED"
    merged["execution_numerator_amount"] = merged["settlement_expenditure_amount"]
    merged["execution_denominator_amount"] = pd.Series(pd.NA, index=merged.index, dtype="Int64")
    merged["execution_denominator_source"] = pd.NA
    general_mask = merged["account_type"].isin({"GENERAL_ACCOUNT", "SPECIAL_ACCOUNT"})
    fund_mask = merged["account_type"] == "FUND"
    merged.loc[general_mask, "execution_denominator_amount"] = merged.loc[
        general_mask, "settlement_current_budget_amount"
    ]
    merged.loc[general_mask, "execution_denominator_source"] = (
        "project_settlement.settlement_current_budget_amount"
    )
    merged.loc[fund_mask, "execution_denominator_source"] = (
        "UNCONFIRMED:project_month.current_budget_amount"
    )
    denominator = merged["execution_denominator_amount"]
    numerator = merged["execution_numerator_amount"]
    merged["execution_denominator_status"] = "APPLIED"
    merged.loc[fund_mask, "execution_denominator_status"] = "UNCONFIRMED_FUND_PLAN_DENOMINATOR"
    merged.loc[merged["account_type"] == "OTHER", "execution_denominator_status"] = (
        "UNSUPPORTED_ACCOUNT_TYPE"
    )
    merged.loc[
        denominator.isna() & general_mask,
        "execution_denominator_status",
    ] = "MISSING_DENOMINATOR"
    merged.loc[denominator == 0, "execution_denominator_status"] = "ZERO_DENOMINATOR"
    merged["execution_rate"] = pd.NA
    valid_rate = (
        merged["execution_denominator_status"].eq("APPLIED")
        & denominator.notna()
        & numerator.notna()
        & (denominator != 0)
    )
    merged.loc[valid_rate, "execution_rate"] = (
        numerator.loc[valid_rate] / denominator.loc[valid_rate]
    )
    merged["execution_rate"] = pd.to_numeric(merged["execution_rate"], errors="coerce").astype(
        "Float64"
    )
    merged["execution_rate_unit"] = "ratio"

    merged["quality_issue_reasons"] = merged.apply(_issue_reasons, axis=1)
    merged["manual_review_required_v1"] = merged["quality_issue_reasons"].ne("")
    primary_duplicate = merged.duplicated(JOIN_KEY, keep=False)
    merged.loc[primary_duplicate, "quality_issue_reasons"] = merged.loc[
        primary_duplicate, "quality_issue_reasons"
    ].map(lambda value: f"{value};V1_PRIMARY_KEY_DUPLICATE".strip(";"))
    merged.loc[primary_duplicate, "manual_review_required_v1"] = True

    issue_rows: list[dict[str, Any]] = []
    for row in merged.loc[merged["manual_review_required_v1"]].itertuples(index=False):
        row_dict = row._asdict()
        for reason in str(row_dict["quality_issue_reasons"]).split(";"):
            if reason:
                metadata = ISSUE_METADATA.get(reason, ("OTHER", "MEDIUM", "", ""))
                issue_rows.append(
                    {
                        "issue_reason": reason,
                        "issue_category": metadata[0],
                        "severity": metadata[1],
                        "likely_cause": metadata[2],
                        "recommended_action": metadata[3],
                        "project_id": row_dict["project_id"],
                        "fiscal_year": row_dict["fiscal_year"],
                        "ministry_code": row_dict["ministry_code"],
                        "settlement_join_status": row_dict["settlement_join_status"],
                        "settlement_reconciliation_status": row_dict[
                            "settlement_reconciliation_status"
                        ],
                    }
                )
    issues = pd.DataFrame(issue_rows)
    issue_counts = (
        issues["issue_reason"].value_counts().sort_index().to_dict() if not issues.empty else {}
    )
    issue_category_counts = (
        issues["issue_category"].value_counts().sort_index().to_dict() if not issues.empty else {}
    )
    comparable = merged["settlement_reconciliation_status"].isin(
        {"EXACT", "WITHIN_TOLERANCE", "MISMATCH"}
    )
    matched = merged["settlement_join_status"] == "BOTH"
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "financial_base_row_count": len(financial),
        "settlement_project_year_count": len(settlement),
        "financial_v1_row_count": len(merged),
        "primary_key_duplicate_count": int(primary_duplicate.sum()),
        "settlement_join_status_counts": (
            merged["settlement_join_status"].value_counts().sort_index().to_dict()
        ),
        "settlement_match_rate": float(matched.mean()) if len(merged) else 0.0,
        "reconciliation_status_counts": (
            merged["settlement_reconciliation_status"].value_counts().sort_index().to_dict()
        ),
        "comparable_reconciliation_count": int(comparable.sum()),
        "reconciliation_exact_or_tolerance_rate": (
            float(
                merged.loc[comparable, "settlement_reconciliation_status"]
                .isin({"EXACT", "WITHIN_TOLERANCE"})
                .mean()
            )
            if comparable.any()
            else 0.0
        ),
        "account_type_counts": merged["account_type"].value_counts().sort_index().to_dict(),
        "execution_denominator_status_counts": (
            merged["execution_denominator_status"].value_counts().sort_index().to_dict()
        ),
        "manual_review_row_count": int(merged["manual_review_required_v1"].sum()),
        "manual_review_rate": float(merged["manual_review_required_v1"].mean()),
        "quality_issue_reason_counts": issue_counts,
        "quality_issue_category_counts": issue_category_counts,
    }

    dictionary = pd.DataFrame(
        [
            ["project_id", "string", "", "사업-연도 조인 식별자"],
            ["settlement_join_status", "string", "", "재정기준-결산 조인 상태"],
            [
                "settlement_expenditure_amount",
                "Int64",
                "KRW",
                "결산 지출금액",
            ],
            [
                "cumulative_expenditure_amount",
                "Int64",
                "KRW",
                "월별 집행 최신월 누계 지출금액",
            ],
            [
                "settlement_vs_december_difference",
                "Int64",
                "KRW",
                "결산 지출금액 - 12월 누계 지출금액",
            ],
            [
                "settlement_reconciliation_status",
                "string",
                "",
                "12월 누계와 결산 대조 상태",
            ],
            ["account_type", "string", "", "집행률 분모 규칙용 회계유형"],
            ["account_type_basis", "string", "", "회계유형 분류 근거"],
            ["execution_numerator_amount", "Int64", "KRW", "결산 지출금액"],
            [
                "execution_denominator_amount",
                "Int64",
                "KRW",
                "회계유형별 집행률 분모",
            ],
            ["execution_rate", "Float64", "ratio", "집행액 / 적용 분모"],
            [
                "quality_issue_reasons",
                "string",
                "",
                "세미콜론으로 분리한 수기검토 원인",
            ],
        ],
        columns=["column_name", "dtype", "unit", "description"],
    )
    documented = set(dictionary["column_name"])
    dictionary = pd.concat(
        [
            dictionary,
            pd.DataFrame(
                [
                    {
                        "column_name": column,
                        "dtype": str(merged[column].dtype),
                        "unit": (
                            "KRW"
                            if column.endswith(("_amount", "_difference"))
                            else "ratio"
                            if column.endswith("_rate")
                            else ""
                        ),
                        "description": (
                            "project_year_financial_base 원천 컬럼"
                            if column in financial.columns
                            else "project_settlement 원천 컬럼"
                            if column in settlement.columns
                            else "financial v1 파생·품질 컬럼"
                        ),
                    }
                    for column in merged.columns
                    if column not in documented
                ]
            ),
        ],
        ignore_index=True,
    )
    valid_execution_rate = merged["execution_rate"].dropna()
    summary.update(
        {
            "execution_rate_nonnull_count": len(valid_execution_rate),
            "execution_rate_negative_count": int((valid_execution_rate < 0).sum()),
            "execution_rate_over_1_count": int((valid_execution_rate > 1).sum()),
            "execution_rate_min": (
                float(valid_execution_rate.min()) if len(valid_execution_rate) else None
            ),
            "execution_rate_max": (
                float(valid_execution_rate.max()) if len(valid_execution_rate) else None
            ),
            "table_column_count": len(merged.columns),
            "data_dictionary_column_count": len(dictionary),
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = [
        output_dir / "project_year_financial_v1.parquet",
        output_dir / "project_year_financial_v1_quality_summary.json",
        output_dir / "project_year_financial_v1_quality_issues.csv",
        output_dir / "project_year_financial_v1_manual_review.csv",
        output_dir / "project_year_financial_v1_data_dictionary.csv",
    ]
    existing = [path for path in output_paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"출력 파일이 이미 있습니다: {existing[0]}")
    merged.to_parquet(output_paths[0], index=False)
    output_paths[1].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    issues.to_csv(output_paths[2], index=False, encoding="utf-8-sig")
    merged.loc[merged["manual_review_required_v1"]].to_csv(
        output_paths[3], index=False, encoding="utf-8-sig"
    )
    dictionary.to_csv(output_paths[4], index=False, encoding="utf-8-sig")
    return FinancialV1Result(merged, issues, summary, output_paths)
