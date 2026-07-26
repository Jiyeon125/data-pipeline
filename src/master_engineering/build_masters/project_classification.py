"""규칙 기반 사업분류 마스터와 재정분석 모집단을 생성합니다."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

CLASSIFICATION_CODE_KEY = (
    "ministry_code",
    "account_code",
    "program_code",
    "activity_code",
    "subactivity_code",
)
CLASSIFICATION_NAME_KEY = (
    "ministry_name",
    "account_name",
    "program_name",
    "activity_name",
    "subactivity_name",
)
SOURCE_AMOUNT_COLUMNS = (
    "budget_amount",
    "current_budget_amount",
    "cumulative_expenditure_amount",
    "cumulative_net_expenditure_amount",
    "settlement_budget_amount",
    "settlement_adjustment_amount",
    "settlement_current_budget_amount",
    "settlement_expenditure_amount",
    "settlement_net_expenditure_amount",
    "settlement_carryover_amount",
    "settlement_unused_amount",
    "execution_numerator_amount",
    "execution_denominator_amount",
)
ACCOUNT_TYPES = {
    "GENERAL_ACCOUNT",
    "SPECIAL_ACCOUNT",
    "FUND",
    "RESPONSIBLE_OPERATION_ACCOUNT",
    "OTHER",
    "UNKNOWN",
}
INSTRUMENT_RULES = {
    "INTEREST_SUBSIDY": (r"이차\s*보전",),
    "LOAN": (r"융자", r"대출"),
    "GUARANTEE": (r"보증",),
    "EQUITY": (r"출자", r"모태\s*펀드"),
    "CONTRIBUTION": (r"출연",),
    "SUBSIDY": (r"보조",),
    "RND": (r"연구\s*개발", r"R\s*[&＆]\s*D", r"\bRND\b"),
    "INFORMATIZATION": (r"정보화", r"시스템\s*구축"),
    "FACILITY": (r"시설", r"건립", r"청사"),
    "OPERATION": (r"운영",),
    "DIRECT": (r"직접\s*사업", r"직접\s*수행"),
}
EXCLUSION_RULES = {
    "TRANSFER": (r"전출금", r"회계\s*[·ㆍ\-]?\s*기금\s*간\s*전출"),
    "BORROWING": (r"차입금",),
    "PRINCIPAL_REPAYMENT": (r"원금\s*상환", r"차입금\s*상환"),
    "SURPLUS_OPERATION": (r"여유\s*자금\s*운용",),
    "PRESERVATION_EXPENDITURE": (r"보전\s*지출", r"보존성\s*지출"),
}
HARD_FINANCIAL_REASONS = {
    "FINANCIAL_BASE_MISSING",
    "MISSING_DENOMINATOR",
    "SETTLEMENT_CODE_MULTIPLE_MATCHES",
    "SETTLEMENT_CODE_NO_MATCH",
    "SETTLEMENT_DUPLICATE_KEY",
    "SETTLEMENT_MISSING",
    "UNSUPPORTED_ACCOUNT_TYPE",
    "V1_PRIMARY_KEY_DUPLICATE",
}


@dataclass
class ProjectClassificationResult:
    classification: pd.DataFrame
    analysis_population: pd.DataFrame
    analysis_excluded: pd.DataFrame
    manual_review: pd.DataFrame
    exclusion_summary: pd.DataFrame
    summary: dict[str, Any]
    output_paths: list[Path]


def _text(*values: Any) -> str:
    return " | ".join(
        str(value).strip()
        for value in values
        if pd.notna(value) and str(value).strip()
    )


def _digest(*values: Any) -> str:
    raw = "\x1f".join("" if pd.isna(value) else str(value).strip() for value in values)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _first_not_null(series: pd.Series) -> Any:
    values = series.dropna()
    return values.iloc[0] if not values.empty else pd.NA


def _last_not_null(series: pd.Series) -> Any:
    values = series.dropna()
    return values.iloc[-1] if not values.empty else pd.NA


def _bool(value: Any) -> bool:
    return False if pd.isna(value) else bool(value)


def classify_account_type(account_name: Any, account_code: Any) -> tuple[str, str]:
    """공식 회계 명칭과 책임운영기관 4xx 코드로 회계유형을 분류합니다."""
    name = "" if pd.isna(account_name) else str(account_name).strip()
    code = "" if pd.isna(account_code) else str(account_code).strip()
    if re.fullmatch(r"4\d{2}", code):
        return "RESPONSIBLE_OPERATION_ACCOUNT", "ACCOUNT_CODE_4XX"
    if "일반회계" in name:
        return "GENERAL_ACCOUNT", "ACCOUNT_NAME_GENERAL"
    if "특별회계" in name:
        return "SPECIAL_ACCOUNT", "ACCOUNT_NAME_SPECIAL"
    if "기금" in name:
        return "FUND", "ACCOUNT_NAME_FUND"
    if name and ("기타" in name or "그 밖" in name):
        return "OTHER", "ACCOUNT_NAME_OTHER"
    return "UNKNOWN", "ACCOUNT_RULE_UNRESOLVED"


def classify_fiscal_instrument(
    program_name: Any,
    activity_name: Any,
    subactivity_name: Any,
) -> tuple[str, str, str, bool]:
    """사업 계층 명칭에서 재정수단 후보를 보수적으로 분류합니다."""
    text = _text(program_name, activity_name, subactivity_name)
    matches: dict[str, list[str]] = {}
    for instrument, patterns in INSTRUMENT_RULES.items():
        evidence = [pattern for pattern in patterns if re.search(pattern, text, re.IGNORECASE)]
        if evidence:
            matches[instrument] = evidence
    if len(matches) == 1:
        instrument = next(iter(matches))
        evidence = ",".join(matches[instrument])
        return instrument, "RULE_KEYWORD_CANDIDATE", evidence, False
    if len(matches) > 1:
        evidence = ";".join(
            f"{instrument}:{','.join(patterns)}" for instrument, patterns in sorted(matches.items())
        )
        return "UNKNOWN", "RULE_KEYWORD_OVERLAP", evidence, True
    return "UNKNOWN", "NO_INSTRUMENT_RULE_MATCH", "", True


def classify_exclusion(
    business_class_name: Any,
    finance_detail_name: Any,
    program_name: Any,
    activity_name: Any,
    subactivity_name: Any,
) -> tuple[bool, str | None, str | None, bool]:
    """구조화 필드와 사업 명칭으로 분석 제외 후보를 분류합니다."""
    business = _text(business_class_name)
    finance = _text(finance_detail_name)
    names = _text(program_name, activity_name, subactivity_name)
    hits: dict[str, list[str]] = {}
    if "인건비" in business:
        hits.setdefault("PERSONNEL", []).append(f"business_class_name={business}")
    if "기본경비" in business:
        hits.setdefault("BASIC_OPERATION", []).append(f"business_class_name={business}")
    if "내부거래" in finance:
        hits.setdefault("INTERNAL_TRANSACTION", []).append(
            f"finance_detail_name={finance}"
        )
    for category, patterns in EXCLUSION_RULES.items():
        evidence = [pattern for pattern in patterns if re.search(pattern, _text(finance, names))]
        if evidence:
            hits.setdefault(category, []).append(
                f"keyword={','.join(evidence)};text={_text(finance, names)}"
            )
    if len(hits) == 1:
        category = next(iter(hits))
        return False, category, " | ".join(hits[category]), False
    if len(hits) > 1:
        evidence = "; ".join(
            f"{category}[{' | '.join(values)}]" for category, values in sorted(hits.items())
        )
        return True, None, f"복수 제외 규칙 충돌: {evidence}", True
    return True, None, None, False


def _project_category(
    *,
    business_class_name: Any,
    finance_detail_name: Any,
    exclusion_category: Any,
) -> str:
    if pd.notna(exclusion_category):
        return str(exclusion_category)
    business = _text(business_class_name)
    finance = _text(finance_detail_name)
    if "주요사업비" in business:
        return "PROGRAM_EXPENDITURE"
    if "일반지출" in finance:
        return "PROGRAM_EXPENDITURE"
    return "UNKNOWN"


def _classification_project_id(row: pd.Series) -> str:
    codes = [row.get(column) for column in CLASSIFICATION_CODE_KEY]
    if all(pd.notna(value) and str(value).strip() for value in codes):
        return "classification-code:" + ":".join(str(value).strip() for value in codes)
    names = [row.get(column) for column in CLASSIFICATION_NAME_KEY]
    return f"classification-name:{_digest(*names)}"


def _reason_set(value: Any) -> set[str]:
    if pd.isna(value):
        return set()
    return {reason for reason in str(value).split(";") if reason}


def _financial_restrictions(row: pd.Series) -> list[str]:
    restrictions: list[str] = []
    priority = row.get("review_priority")
    reasons = _reason_set(row.get("quality_issue_reasons"))
    if priority == "BLOCKING" or reasons & HARD_FINANCIAL_REASONS:
        restrictions.append("BLOCKING_FINANCIAL_QUALITY")
    if _bool(row.get("execution_rate_over_100_flag")):
        restrictions.append("EXECUTION_RATE_OVER_1")
    if row.get("execution_denominator_status") != "APPLIED":
        restrictions.append("EXECUTION_DENOMINATOR_UNCONFIRMED")
    if (
        row.get("matching_status") == "MULTIPLE_MATCHES"
        or row.get("settlement_matching_status") == "MULTIPLE_MATCHES"
    ):
        restrictions.append("MULTIPLE_MATCHING_CANDIDATES")
    relative = row.get("settlement_vs_december_relative_difference")
    if (
        row.get("settlement_reconciliation_status") == "MISMATCH"
        and row.get("account_type_classified") != "FUND"
        and pd.notna(relative)
        and float(relative) > 0.01
    ):
        restrictions.append("MATERIAL_SCOPE_OR_CLOSING_DIFFERENCE")
    if _bool(row.get("is_masked")) or (
        pd.notna(row.get("masked_source_row_count"))
        and float(row.get("masked_source_row_count")) > 0
    ):
        restrictions.append("MASKED_BASE_AMOUNT")
    required_codes = [row.get(column) for column in CLASSIFICATION_CODE_KEY]
    if not all(pd.notna(value) and str(value).strip() for value in required_codes):
        restrictions.append("PROJECT_KEY_CONTINUITY_UNCONFIRMED")
    return list(dict.fromkeys(restrictions))


def _financial_quality_level(row: pd.Series, restrictions: list[str]) -> str:
    if "BLOCKING_FINANCIAL_QUALITY" in restrictions:
        return "BLOCKING"
    if restrictions:
        return "RESTRICTED"
    priority = row.get("review_priority")
    if priority in {"NON_BLOCKING", "INFORMATIONAL"}:
        return str(priority)
    return "CLEAR"


def _classification_status(row: pd.Series) -> str:
    if _bool(row["classification_manual_review_required"]):
        return "MANUAL_REVIEW"
    if row["fiscal_instrument"] != "UNKNOWN":
        return "RULE_CANDIDATE"
    return "UNKNOWN"


def _input_availability(paths: Iterable[Path]) -> dict[str, bool]:
    return {str(path): path.exists() for path in paths}


def _validate_ministries(frame: pd.DataFrame, ministries_path: Path) -> dict[str, Any]:
    configured: set[str] = set()
    if ministries_path.exists():
        payload = yaml.safe_load(ministries_path.read_text(encoding="utf-8")) or {}
        configured = {str(item["code"]) for item in payload.get("ministries", [])}
    observed = set(frame["ministry_code"].astype("string").dropna())
    return {
        "configured_codes": sorted(configured),
        "observed_codes": sorted(observed),
        "unexpected_codes": sorted(observed - configured),
        "leading_zero_codes_preserved": all(
            code in observed for code in configured if code.startswith("0")
        ),
    }


def _collapse_classification(yearly: pd.DataFrame) -> pd.DataFrame:
    signature_columns = [
        "account_type_classified",
        "fiscal_instrument",
        "project_category",
        "analysis_included_classified",
        "exclusion_category_classified",
        "classification_status",
    ]
    rows: list[dict[str, Any]] = []
    for project_id, group in yearly.groupby("classification_project_id", sort=True):
        ordered = group.sort_values("fiscal_year")
        distinct_signatures = ordered[signature_columns].astype("string").drop_duplicates()
        pieces = [ordered] if len(distinct_signatures) == 1 else [
            year_group for _, year_group in ordered.groupby("fiscal_year", sort=True)
        ]
        for piece in pieces:
            latest = piece.iloc[-1]
            classification_year = (
                int(latest["fiscal_year"]) if len(distinct_signatures) > 1 else pd.NA
            )
            rows.append(
                {
                    "project_id": project_id,
                    "classification_year": classification_year,
                    "ministry_code": latest["ministry_code"],
                    "ministry_name": latest["ministry_name"],
                    "account_code": latest["account_code"],
                    "account_name": latest["account_name"],
                    "account_type": latest["account_type_classified"],
                    "program_code": latest["program_code"],
                    "program_name": latest["program_name"],
                    "activity_code": latest["activity_code"],
                    "activity_name": latest["activity_name"],
                    "subactivity_code": latest["subactivity_code"],
                    "subactivity_name": latest["subactivity_name"],
                    "fiscal_instrument": latest["fiscal_instrument"],
                    "project_category": latest["project_category"],
                    "comparison_group": latest["comparison_group"],
                    "analysis_included": bool(latest["analysis_included_classified"]),
                    "exclusion_category": latest["exclusion_category_classified"],
                    "exclusion_reason": latest["exclusion_reason_classified"],
                    "classification_method": latest["classification_method"],
                    "classification_evidence": latest["classification_evidence"],
                    "classification_status": latest["classification_status"],
                    "manual_review_required": bool(
                        piece["classification_manual_review_required"].any()
                    ),
                    "source_project_year_ids": json.dumps(
                        sorted(set(piece["source_project_year_id"].astype(str))),
                        ensure_ascii=False,
                    ),
                    "observed_years": json.dumps(
                        sorted(int(value) for value in piece["fiscal_year"].dropna().unique())
                    ),
                }
            )
    result = pd.DataFrame(rows)
    result["classification_year"] = pd.to_numeric(
        result["classification_year"], errors="coerce"
    ).astype("Int64")
    return result


def _primary_population_reason(row: pd.Series) -> str | None:
    if not row["analysis_included_classified"]:
        category = row.get("exclusion_category_classified")
        category_value = "UNRESOLVED" if pd.isna(category) else str(category)
        return f"CLASSIFICATION_EXCLUSION:{category_value}"
    raw_restrictions = row.get("financial_analysis_exclusion_reason")
    restrictions = (
        [] if pd.isna(raw_restrictions) else str(raw_restrictions).split(";")
    )
    restrictions = [reason for reason in restrictions if reason]
    if restrictions:
        return restrictions[0]
    if not row["required_project_hierarchy_available"]:
        return "REQUIRED_PROJECT_HIERARCHY_MISSING"
    if not row["base_amount_basis_confirmed"]:
        return "BASE_AMOUNT_BASIS_UNCONFIRMED"
    return None


def build_project_classification(
    *,
    financial_v1_path: Path,
    manual_review_path: Path,
    execution_over_100_path: Path,
    datasets_path: Path,
    ministries_path: Path,
    mentoring_guide_path: Path,
    project_plan_path: Path,
    output_dir: Path,
    overwrite: bool = False,
) -> ProjectClassificationResult:
    """사업분류, 품질 결합, 분석 모집단과 제외 모집단을 구축합니다."""
    required_paths = [
        financial_v1_path,
        manual_review_path,
        execution_over_100_path,
        datasets_path,
        ministries_path,
        mentoring_guide_path,
    ]
    missing_required = [path for path in required_paths if not path.exists()]
    if missing_required:
        raise FileNotFoundError(f"필수 입력 파일이 없습니다: {missing_required[0]}")

    source = pd.read_parquet(financial_v1_path)
    manual = pd.read_csv(manual_review_path, dtype={"ministry_code": "string"})
    over_100 = pd.read_csv(execution_over_100_path, dtype={"ministry_code": "string"})
    source["ministry_code"] = source["ministry_code"].astype("string")
    source["source_project_year_id"] = source["project_id"].astype("string")

    manual_keys = ["project_id", "fiscal_year", "ministry_code"]
    manual_subset = manual[
        manual_keys
        + [
            "review_priority",
            "blocks_annual_financial_analysis",
            "automatic_resolution_rule",
            "priority_reason",
        ]
    ].drop_duplicates(manual_keys)
    source = source.merge(
        manual_subset,
        how="left",
        left_on=["source_project_year_id", "fiscal_year", "ministry_code"],
        right_on=manual_keys,
        validate="one_to_one",
        suffixes=("", "_manual"),
    )
    if "project_id_manual" in source:
        source = source.drop(columns=["project_id_manual"])
    over_keys = set(
        zip(
            over_100["project_id"].astype("string"),
            pd.to_numeric(over_100["fiscal_year"], errors="coerce").astype("Int64"),
            over_100["ministry_code"].astype("string"),
            strict=True,
        )
    )
    source["execution_rate_over_100_flag"] = [
        (str(project_id), fiscal_year, str(ministry_code)) in over_keys
        for project_id, fiscal_year, ministry_code in zip(
            source["source_project_year_id"],
            source["fiscal_year"],
            source["ministry_code"],
            strict=True,
        )
    ]

    source["account_type_classified"], source["account_type_classification_basis"] = zip(
        *[
            classify_account_type(name, code)
            for name, code in zip(source["account_name"], source["account_code"], strict=True)
        ],
        strict=True,
    )
    instrument_results = [
        classify_fiscal_instrument(program, activity, subactivity)
        for program, activity, subactivity in zip(
            source["program_name"],
            source["activity_name"],
            source["subactivity_name"],
            strict=True,
        )
    ]
    source["fiscal_instrument"] = [value[0] for value in instrument_results]
    source["instrument_classification_method"] = [value[1] for value in instrument_results]
    source["instrument_classification_evidence"] = [value[2] for value in instrument_results]
    source["instrument_manual_review_required"] = [value[3] for value in instrument_results]

    exclusion_results = [
        classify_exclusion(business, finance, program, activity, subactivity)
        for business, finance, program, activity, subactivity in zip(
            source["business_class_name"],
            source["finance_detail_name"],
            source["program_name"],
            source["activity_name"],
            source["subactivity_name"],
            strict=True,
        )
    ]
    source["analysis_included_classified"] = [value[0] for value in exclusion_results]
    source["exclusion_category_classified"] = [value[1] for value in exclusion_results]
    source["exclusion_reason_classified"] = [value[2] for value in exclusion_results]
    source["exclusion_rule_manual_review_required"] = [value[3] for value in exclusion_results]
    source["project_category"] = [
        _project_category(
            business_class_name=business,
            finance_detail_name=finance,
            exclusion_category=category,
        )
        for business, finance, category in zip(
            source["business_class_name"],
            source["finance_detail_name"],
            source["exclusion_category_classified"],
            strict=True,
        )
    ]
    source["classification_manual_review_required"] = (
        source["instrument_manual_review_required"]
        | source["exclusion_rule_manual_review_required"]
        | source["account_type_classified"].eq("UNKNOWN")
        | source["project_category"].eq("UNKNOWN")
    )
    source["classification_status"] = source.apply(_classification_status, axis=1)
    source["classification_method"] = (
        source["account_type_classification_basis"].astype(str)
        + ";"
        + source["instrument_classification_method"].astype(str)
        + ";STRUCTURED_EXCLUSION_RULE"
    )
    source["classification_evidence"] = (
        source["instrument_classification_evidence"].fillna("").astype(str)
        + ";"
        + source["exclusion_reason_classified"].fillna("").astype(str)
    ).str.strip(";")
    source["comparison_group"] = (
        source["account_type_classified"].astype(str)
        + "|"
        + source["fiscal_instrument"].astype(str)
        + "|"
        + source["project_category"].astype(str)
    )
    source["classification_project_id"] = source.apply(_classification_project_id, axis=1)

    restrictions = [list(_financial_restrictions(row)) for _, row in source.iterrows()]
    financial_exclusion_reasons = [
        [
            reason
            for reason in values
            if reason in {"BLOCKING_FINANCIAL_QUALITY", "MASKED_BASE_AMOUNT"}
        ]
        for values in restrictions
    ]
    financial_limitation_reasons = [
        [
            reason
            for reason in values
            if reason not in {"BLOCKING_FINANCIAL_QUALITY", "MASKED_BASE_AMOUNT"}
        ]
        for values in restrictions
    ]
    source["financial_analysis_exclusion_reason"] = [
        ";".join(values) if values else pd.NA for values in financial_exclusion_reasons
    ]
    source["financial_analysis_limitation_flags"] = [
        ";".join(values) if values else pd.NA for values in financial_limitation_reasons
    ]
    source["financial_analysis_eligible"] = [
        not values for values in financial_exclusion_reasons
    ]
    source["financial_quality_level"] = [
        _financial_quality_level(row, values)
        for (_, row), values in zip(source.iterrows(), restrictions, strict=True)
    ]
    source["execution_rate_analysis_eligible"] = (
        source["financial_analysis_eligible"]
        & source["execution_denominator_status"].eq("APPLIED")
        & ~source["execution_rate_over_100_flag"]
    )
    source["reconciliation_analysis_eligible"] = (
        source["financial_analysis_eligible"]
        & ~source["financial_analysis_limitation_flags"]
        .fillna("")
        .str.contains("MATERIAL_SCOPE_OR_CLOSING_DIFFERENCE|MULTIPLE_MATCHING_CANDIDATES")
    )
    source["required_project_hierarchy_available"] = source[
        list(CLASSIFICATION_CODE_KEY)
    ].notna().all(axis=1) & source[list(CLASSIFICATION_CODE_KEY)].astype(
        "string"
    ).apply(
        lambda column: column.str.strip().ne("")
    ).all(
        axis=1
    )
    source["base_amount_basis_confirmed"] = source[
        "settlement_expenditure_amount"
    ].notna()
    source["population_exclusion_reason"] = source.apply(_primary_population_reason, axis=1)
    source["analysis_population_included"] = (
        source["analysis_included_classified"]
        & source["financial_analysis_eligible"]
        & source["required_project_hierarchy_available"]
        & source["base_amount_basis_confirmed"]
    )

    source["source_trace"] = source["source_path"].astype("string")
    source["source_trace_level"] = "RAW_FILE"
    dataset_fallback = source["source_trace"].isna() & source["source_datasets"].notna()
    source.loc[dataset_fallback, "source_trace"] = source.loc[
        dataset_fallback, "source_datasets"
    ].astype("string")
    source.loc[dataset_fallback, "source_trace_level"] = "RAW_DATASET_SET"
    v1_fallback = source["source_trace"].isna()
    source.loc[v1_fallback, "source_trace"] = (
        "project_year_financial_v1:"
        + source.loc[v1_fallback, "source_project_year_id"].astype("string")
    )
    source.loc[v1_fallback, "source_trace_level"] = "DERIVED_V1_ROW"

    eligible = source["analysis_population_included"]
    group_sizes = (
        source.loc[eligible]
        .groupby("comparison_group")["classification_project_id"]
        .nunique()
        .rename("comparison_group_size")
    )
    source["comparison_group_size"] = (
        source["comparison_group"].map(group_sizes).fillna(0).astype("Int64")
    )
    source["small_group_flag"] = source["comparison_group_size"].lt(5)

    classification = _collapse_classification(source)
    classification_key_duplicate = classification.duplicated(
        ["project_id", "classification_year"], keep=False
    )
    classification_sizes = (
        source.loc[eligible]
        .groupby("comparison_group")["classification_project_id"]
        .nunique()
    )
    classification["comparison_group_size"] = (
        classification["comparison_group"].map(classification_sizes).fillna(0).astype("Int64")
    )
    classification["small_group_flag"] = classification["comparison_group_size"].lt(5)

    analysis_population = source.loc[eligible].copy()
    analysis_excluded = source.loc[~eligible].copy()
    if len(analysis_population) + len(analysis_excluded) != len(source):
        raise ValueError("분석 모집단과 제외 모집단의 합이 원본 행 수와 다릅니다.")

    manual_review = classification.loc[classification["manual_review_required"]].copy()
    amount_columns = [
        column
        for column in (
            "settlement_expenditure_amount",
            "settlement_current_budget_amount",
            "current_budget_amount",
        )
        if column in analysis_excluded
    ]
    aggregations: dict[str, tuple[str, str]] = {
        "excluded_row_count": ("source_project_year_id", "size"),
        "excluded_project_count": ("classification_project_id", "nunique"),
    }
    for column in amount_columns:
        aggregations[f"{column}_sum"] = (column, "sum")
    exclusion_summary = (
        analysis_excluded.groupby("population_exclusion_reason", dropna=False)
        .agg(**aggregations)
        .reset_index()
        .sort_values("excluded_row_count", ascending=False)
    )

    key_duplicates = source.duplicated(
        ["source_project_year_id", "fiscal_year", "ministry_code"], keep=False
    )
    amount_unchanged = True
    combined = pd.concat([analysis_population, analysis_excluded], ignore_index=True)
    combined = combined.set_index(
        ["source_project_year_id", "fiscal_year", "ministry_code"]
    ).sort_index()
    original = source.set_index(
        ["source_project_year_id", "fiscal_year", "ministry_code"]
    ).sort_index()
    for column in SOURCE_AMOUNT_COLUMNS:
        if column in source:
            amount_unchanged &= original[column].equals(combined[column])

    ministry_validation = _validate_ministries(source, ministries_path)
    input_paths = [
        financial_v1_path,
        manual_review_path,
        execution_over_100_path,
        datasets_path,
        ministries_path,
        mentoring_guide_path,
        project_plan_path,
    ]
    account_counts = (
        classification.groupby("account_type", dropna=False)["project_id"]
        .nunique()
        .sort_index()
        .to_dict()
    )
    instrument_counts = (
        classification.groupby("fiscal_instrument", dropna=False)["project_id"]
        .nunique()
        .sort_index()
        .to_dict()
    )
    exclusion_counts = (
        analysis_excluded["population_exclusion_reason"]
        .value_counts(dropna=False)
        .sort_index()
        .to_dict()
    )
    comparison_sizes = (
        analysis_population.groupby("comparison_group")["classification_project_id"].nunique()
    )
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "input_availability": _input_availability(input_paths),
        "source_project_year_row_count": len(source),
        "classification_project_count": int(
            classification["project_id"].nunique(dropna=True)
        ),
        "classification_row_count": len(classification),
        "classification_year_exception_row_count": int(
            classification["classification_year"].notna().sum()
        ),
        "financial_instrument_project_counts": instrument_counts,
        "account_type_project_counts": account_counts,
        "analysis_population_row_count": len(analysis_population),
        "analysis_excluded_row_count": len(analysis_excluded),
        "analysis_population_rate": len(analysis_population) / len(source) if len(source) else 0.0,
        "exclusion_reason_row_counts": exclusion_counts,
        "blocking_excluded_row_count": int(
            analysis_excluded["financial_quality_level"].eq("BLOCKING").sum()
        ),
        "execution_rate_over_100_excluded_row_count": int(
            (~source.loc[source["execution_rate_over_100_flag"], "execution_rate_analysis_eligible"])
            .sum()
        ),
        "unknown_instrument_classification_count": int(
            classification.loc[
                classification["fiscal_instrument"].eq("UNKNOWN"), "project_id"
            ].nunique()
        ),
        "unknown_instrument_classification_row_count": int(
            classification["fiscal_instrument"].eq("UNKNOWN").sum()
        ),
        "unknown_account_type_count": int(
            classification.loc[
                classification["account_type"].eq("UNKNOWN"), "project_id"
            ].nunique()
        ),
        "rule_candidate_count": int(
            classification.loc[
                classification["classification_status"].eq("RULE_CANDIDATE"), "project_id"
            ].nunique()
        ),
        "rule_candidate_classification_row_count": int(
            classification["classification_status"].eq("RULE_CANDIDATE").sum()
        ),
        "manual_review_classification_count": int(
            manual_review["project_id"].nunique()
        ),
        "manual_review_classification_row_count": len(manual_review),
        "comparison_group_count": int(comparison_sizes.size),
        "small_comparison_group_count": int((comparison_sizes < 5).sum()),
        "validation": {
            "source_row_count_preserved": len(combined) == len(source),
            "joined_primary_key_duplicate_count": int(key_duplicates.sum()),
            "classification_primary_key_duplicate_count": int(
                classification_key_duplicate.sum()
            ),
            "classification_analysis_included_null_count": int(
                source["analysis_included_classified"].isna().sum()
            ),
            "excluded_reason_missing_count": int(
                analysis_excluded["population_exclusion_reason"].isna().sum()
            ),
            "population_partition_matches_source": (
                len(analysis_population) + len(analysis_excluded) == len(source)
            ),
            "source_amounts_unchanged": bool(amount_unchanged),
            "unknown_not_rule_confirmed_count": int(
                (
                    classification["fiscal_instrument"].eq("UNKNOWN")
                    & classification["classification_status"].eq("RULE_CONFIRMED")
                ).sum()
            ),
            "ministry_codes": ministry_validation,
            "source_tracking_missing_count": int(
                source["source_trace"].isna().sum()
            ),
            "raw_source_reference_missing_count": int(
                (source["source_path"].isna() & source["source_datasets"].isna()).sum()
            ),
        },
        "rules": {
            "responsible_operation_account": "account_code 4xx",
            "instrument": "사업 계층 명칭의 단일 키워드 적중은 RULE_CANDIDATE",
            "instrument_overlap": "복수 재정수단 적중은 UNKNOWN 및 MANUAL_REVIEW",
            "exclusion": "구조화 필드 또는 단일 제외 규칙 적중만 자동 제외",
            "comparison_group": "account_type|fiscal_instrument|project_category",
            "comparison_group_size": "분석 모집단 내 고유 classification_project_id 수",
            "small_group": "comparison_group_size < 5; 자동 병합하지 않음",
            "annual_amount": "제외 금액 요약은 공식 결산 지출액을 우선 표시",
        },
        "limitations": [
            "재정수단은 공식 사업유형 코드가 없어 명칭 키워드 후보이며 최종 확정이 아님",
            "사업 계보 원천이 없어 코드 계층이 불완전한 행은 연속성 미확정으로 제한",
            (
                "docs/PROJECT_PLAN.md가 없어 사용자 지정 기준과 "
                "docs/MENTORING_GUIDE.md를 적용"
                if not project_plan_path.exists()
                else ""
            ),
        ],
    }
    summary["limitations"] = [item for item in summary["limitations"] if item]

    classification_dir = output_dir / "classification"
    output_paths = [
        output_dir / "project_classification.parquet",
        output_dir / "project_year_analysis_population.parquet",
        output_dir / "project_year_analysis_excluded.parquet",
        classification_dir / "classification_summary.json",
        classification_dir / "classification_manual_review.csv",
        classification_dir / "analysis_population_summary.json",
        classification_dir / "exclusion_summary.csv",
    ]
    existing = [path for path in output_paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"출력 파일이 이미 있습니다: {existing[0]}")
    classification_dir.mkdir(parents=True, exist_ok=True)
    classification.to_parquet(output_paths[0], index=False)
    analysis_population.to_parquet(output_paths[1], index=False)
    analysis_excluded.to_parquet(output_paths[2], index=False)
    output_paths[3].write_text(
        json.dumps(
            {
                key: value
                for key, value in summary.items()
                if key
                not in {
                    "analysis_population_row_count",
                    "analysis_excluded_row_count",
                    "analysis_population_rate",
                    "exclusion_reason_row_counts",
                    "blocking_excluded_row_count",
                    "execution_rate_over_100_excluded_row_count",
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    manual_review.to_csv(output_paths[4], index=False, encoding="utf-8-sig")
    output_paths[5].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    exclusion_summary.to_csv(output_paths[6], index=False, encoding="utf-8-sig")
    return ProjectClassificationResult(
        classification=classification,
        analysis_population=analysis_population,
        analysis_excluded=analysis_excluded,
        manual_review=manual_review,
        exclusion_summary=exclusion_summary,
        summary=summary,
        output_paths=output_paths,
    )
