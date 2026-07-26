"""core 모집단을 보존하면서 변수별 순위 적격성을 관리합니다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

SOURCE_ID = "source_project_year_id"
AMOUNT_COLUMNS = [
    "original_budget_analysis_amount",
    "current_budget_analysis_amount",
    "settlement_analysis_amount",
]
BLOCKING_KEY_REASONS = {
    "V1_PRIMARY_KEY_DUPLICATE",
    "SETTLEMENT_CODE_MULTIPLE_MATCHES",
    "SETTLEMENT_DUPLICATE_KEY",
}


@dataclass
class RankingPopulationV2Result:
    population: pd.DataFrame
    excluded: pd.DataFrame
    rule_breakdown: pd.DataFrame
    comparison: pd.DataFrame
    summary: dict[str, Any]
    output_paths: list[Path]


def _bool(frame: pd.DataFrame, column: str, default: bool = False) -> pd.Series:
    if column not in frame:
        return pd.Series(default, index=frame.index, dtype=bool)
    return frame[column].astype("boolean").fillna(default).astype(bool)


def _reason_contains(series: pd.Series, reasons: set[str]) -> pd.Series:
    return series.fillna("").astype(str).map(
        lambda value: bool(set(value.split(";")) & reasons)
    )


def _amount_sum(frame: pd.DataFrame, column: str) -> int:
    return int(pd.to_numeric(frame[column], errors="coerce").sum(skipna=True))


def strict_exclusion_masks(core: pd.DataFrame) -> dict[str, pd.Series]:
    """기존 strict 조건을 서로 겹칠 수 있는 규칙별 마스크로 반환합니다."""
    return {
        "FISCAL_INSTRUMENT_UNKNOWN": core["fiscal_instrument"].eq("UNKNOWN"),
        "CLASSIFICATION_STATUS_NOT_RULE_CANDIDATE": ~core[
            "classification_status"
        ].eq("RULE_CANDIDATE"),
        "EXECUTION_RANKING_INELIGIBLE": ~_bool(
            core, "execution_analysis_eligible"
        ),
        "RECONCILIATION_INELIGIBLE": ~_bool(
            core, "reconciliation_analysis_eligible"
        ),
        "PROJECT_CATEGORY_UNKNOWN": core["project_category"].eq("UNKNOWN"),
        "SMALL_COMPARISON_GROUP": _bool(
            core, "ranking_small_group_limited_flag"
        ),
        "COMPARISON_GROUP_SIZE_BELOW_5": core["comparison_group_size"]
        .fillna(0)
        .lt(5),
    }


def _breakdown_row(
    core: pd.DataFrame,
    mask: pd.Series,
    *,
    rule: str,
    decomposition_type: str,
) -> dict[str, Any]:
    affected = core.loc[mask]
    return {
        "population": "CORE_VS_STRICT",
        "decomposition_type": decomposition_type,
        "exclusion_rule": rule,
        "excluded_row_count": len(affected),
        "excluded_unique_project_count": affected[
            "classification_project_id"
        ].nunique(),
        "original_budget_amount": _amount_sum(
            affected, "original_budget_analysis_amount"
        ),
        "current_budget_amount": _amount_sum(
            affected, "current_budget_analysis_amount"
        ),
        "settlement_expenditure_amount": _amount_sum(
            affected, "settlement_analysis_amount"
        ),
        "core_row_count": len(core),
        "core_row_ratio": float(len(affected) / len(core)) if len(core) else None,
        "sample_size": len(affected),
    }


def build_strict_exclusion_breakdown(
    core: pd.DataFrame,
    strict_ids: set[str],
) -> tuple[pd.DataFrame, pd.Series]:
    """strict 제외 3,377행을 비배타·배타 규칙으로 함께 분해합니다."""
    strict_excluded = ~core[SOURCE_ID].astype(str).isin(strict_ids)
    masks = strict_exclusion_masks(core)
    rows: list[dict[str, Any]] = []
    for rule, mask in masks.items():
        rows.append(
            _breakdown_row(
                core,
                strict_excluded & mask,
                rule=rule,
                decomposition_type="NON_EXCLUSIVE_TRIGGER",
            )
        )

    primary = pd.Series(pd.NA, index=core.index, dtype="string")
    precedence = [
        "FISCAL_INSTRUMENT_UNKNOWN",
        "CLASSIFICATION_STATUS_NOT_RULE_CANDIDATE",
        "EXECUTION_RANKING_INELIGIBLE",
        "RECONCILIATION_INELIGIBLE",
        "PROJECT_CATEGORY_UNKNOWN",
        "SMALL_COMPARISON_GROUP",
        "COMPARISON_GROUP_SIZE_BELOW_5",
    ]
    for rule in precedence:
        assign = strict_excluded & primary.isna() & masks[rule]
        primary.loc[assign] = rule
    primary.loc[strict_excluded & primary.isna()] = "OTHER_STRICT_RULE_COMBINATION"
    for rule in primary.loc[strict_excluded].value_counts().sort_index().index:
        rows.append(
            _breakdown_row(
                core,
                strict_excluded & primary.eq(rule),
                rule=str(rule),
                decomposition_type="PRIMARY_MUTUALLY_EXCLUSIVE",
            )
        )
    total = _breakdown_row(
        core,
        strict_excluded,
        rule="TOTAL_CORE_MINUS_STRICT",
        decomposition_type="CONTROL_TOTAL",
    )
    rows.append(total)
    result = pd.DataFrame(rows)
    return result, primary


def add_ranking_v2_flags(
    core: pd.DataFrame,
    financial_v2: pd.DataFrame,
) -> pd.DataFrame:
    """core 행을 유지하고 예산·집행·추세·분류·프로그램별 적격성을 추가합니다."""
    result = core.copy()
    result["ministry_code"] = result["ministry_code"].astype("string")
    v2_columns = [
        "project_id",
        "project_status",
        "structural_change_type",
        "budget_change_analysis_eligible",
        "blocking_quality_flag",
        "quality_issue_reasons",
        "source_trace",
    ]
    available = [column for column in v2_columns if column in financial_v2]
    v2 = financial_v2[available].drop_duplicates("project_id")
    result = result.merge(
        v2,
        how="left",
        left_on=SOURCE_ID,
        right_on="project_id",
        validate="one_to_one",
        suffixes=("", "_v2"),
    )
    result = result.drop(columns=["project_id_v2"], errors="ignore")

    parse_failure = result["amount_parse_failure_row_count"].fillna(0).gt(0)
    base_budget = pd.to_numeric(
        result["original_budget_analysis_amount"], errors="coerce"
    )
    current_budget = pd.to_numeric(
        result["current_budget_analysis_amount"], errors="coerce"
    )
    settlement = pd.to_numeric(result["settlement_analysis_amount"], errors="coerce")
    execution_rate = pd.to_numeric(result["execution_rate"], errors="coerce")
    complete_source_duplicate = result.duplicated(SOURCE_ID, keep=False)
    blocking_key_conflict = _reason_contains(
        result["quality_issue_reasons_v2"].combine_first(
            result["quality_issue_reasons"]
        )
        if "quality_issue_reasons_v2" in result
        else result["quality_issue_reasons"],
        BLOCKING_KEY_REASONS,
    )
    scope_excluded = ~_bool(result, "analysis_included_classified", default=True)
    irrecoverable_parse = (
        parse_failure
        & base_budget.isna()
        & current_budget.isna()
        & settlement.isna()
    )

    result["budget_ranking_eligible"] = (
        base_budget.notna()
        & ~parse_failure
        & ~complete_source_duplicate
        & ~blocking_key_conflict
    )
    result["execution_ranking_eligible"] = (
        execution_rate.notna()
        & result["execution_denominator_status"].eq("APPLIED")
        & ~_bool(result, "execution_rate_over_100_flag")
        & ~_bool(result, "settlement_duplicate_key_flag")
        & ~result["settlement_matching_status"].eq("MULTIPLE_MATCHES")
        & ~blocking_key_conflict
    )
    boundary = result["project_status"].isin(
        {"OBSERVATION_START", "OBSERVATION_END"}
    )
    relationship_candidate = result["budget_change_analysis_eligible"].eq(False)
    result["trend_ranking_eligible"] = (
        _bool(result, "trend_analysis_eligible")
        & ~boundary
        & ~relationship_candidate
        & ~blocking_key_conflict
    )
    result["fiscal_instrument_ranking_eligible"] = result[
        "fiscal_instrument"
    ].ne("UNKNOWN")
    result["program_ranking_eligible"] = (
        result["program_code"].notna()
        & result["project_category"].ne("UNKNOWN")
        & ~blocking_key_conflict
    )

    variable_columns = [
        "budget_ranking_eligible",
        "execution_ranking_eligible",
        "trend_ranking_eligible",
        "fiscal_instrument_ranking_eligible",
        "program_ranking_eligible",
    ]
    all_variables_invalid = ~result[variable_columns].any(axis=1)
    result["ranking_v2_hard_exclusion_reason"] = pd.NA
    hard_rules = [
        ("SCOPE_EXCLUDED", scope_excluded),
        ("BLOCKING_PROJECT_KEY_CONFLICT", blocking_key_conflict),
        ("IRRECOVERABLE_AMOUNT_PARSE_FAILURE", irrecoverable_parse),
        ("COMPLETE_SOURCE_DUPLICATE", complete_source_duplicate),
        ("ALL_CORE_RANKING_VARIABLES_INVALID", all_variables_invalid),
    ]
    for reason, mask in hard_rules:
        assign = result["ranking_v2_hard_exclusion_reason"].isna() & mask
        result.loc[assign, "ranking_v2_hard_exclusion_reason"] = reason
    result["overall_ranking_eligible"] = result[
        "ranking_v2_hard_exclusion_reason"
    ].isna()

    small_group = _bool(result, "ranking_small_group_limited_flag") | result[
        "comparison_group_size"
    ].fillna(0).lt(5)
    result["small_group_flag"] = small_group
    result["rank_confidence"] = "HIGH"
    result.loc[
        result["overall_ranking_eligible"]
        & (~result[variable_columns].all(axis=1)),
        "rank_confidence",
    ] = "MEDIUM"
    result.loc[
        result["overall_ranking_eligible"] & small_group, "rank_confidence"
    ] = "LOW"
    result.loc[
        ~result["overall_ranking_eligible"], "rank_confidence"
    ] = "NOT_APPLICABLE"
    result["rank_display_limited"] = small_group

    limitation_reasons: list[str] = []
    for _, row in result.iterrows():
        reasons: list[str] = []
        if not row["execution_ranking_eligible"]:
            reasons.append("EXECUTION_COMPONENT_UNAVAILABLE")
        if not row["trend_ranking_eligible"]:
            reasons.append("TREND_COMPONENT_UNAVAILABLE")
        if not row["fiscal_instrument_ranking_eligible"]:
            reasons.append("FISCAL_INSTRUMENT_UNKNOWN")
        if not row["program_ranking_eligible"]:
            reasons.append("PROGRAM_COMPONENT_UNAVAILABLE")
        if row["small_group_flag"]:
            reasons.append("SMALL_COMPARISON_GROUP_LOW_CONFIDENCE")
        limitation_reasons.append(";".join(reasons))
    result["ranking_component_limitation_reasons"] = limitation_reasons
    result["ranking_population_policy_version"] = "V2_VARIABLE_SPECIFIC"
    return result


def _comparison_rows(
    core: pd.DataFrame,
    old_strict_ids: set[str],
    v2_ids: set[str],
) -> pd.DataFrame:
    working = core.copy()
    working["old_strict_included"] = working[SOURCE_ID].astype(str).isin(
        old_strict_ids
    )
    working["ranking_v2_included"] = working[SOURCE_ID].astype(str).isin(v2_ids)
    segment_specs = [
        ("OVERALL", []),
        ("MINISTRY", ["ministry_code", "analysis_ministry_name"]),
        ("ACCOUNT_TYPE", ["account_type_classified"]),
        ("FISCAL_INSTRUMENT", ["fiscal_instrument"]),
        ("PROJECT_SIZE", ["project_size_bucket"]),
        ("COMPARISON_GROUP", ["comparison_group"]),
    ]
    rows: list[dict[str, Any]] = []
    for dimension, columns in segment_specs:
        grouped = [((), working)] if not columns else working.groupby(columns, dropna=False)
        for key, group in grouped:
            values = key if isinstance(key, tuple) else (key,)
            segment_value = (
                "ALL"
                if not columns
                else "|".join(
                    f"{column}={value}" for column, value in zip(columns, values, strict=True)
                )
            )
            baseline_amounts = {
                column: _amount_sum(group, column) for column in AMOUNT_COLUMNS
            }
            for population_name, flag in [
                ("STRICT_RANKING_POPULATION_V1", "old_strict_included"),
                ("RANKING_POPULATION_V2", "ranking_v2_included"),
            ]:
                included = group.loc[group[flag]]
                row = {
                    "population": population_name,
                    "segment_dimension": dimension,
                    "segment_value": segment_value,
                    "core_row_count": len(group),
                    "included_row_count": len(included),
                    "row_inclusion_rate": (
                        float(len(included) / len(group)) if len(group) else None
                    ),
                    "core_unique_project_count": group[
                        "classification_project_id"
                    ].nunique(),
                    "included_unique_project_count": included[
                        "classification_project_id"
                    ].nunique(),
                    "sample_size": len(included),
                }
                output_names = {
                    "original_budget_analysis_amount": "original_budget_amount",
                    "current_budget_analysis_amount": "current_budget_amount",
                    "settlement_analysis_amount": "settlement_expenditure_amount",
                }
                for column in AMOUNT_COLUMNS:
                    included_amount = _amount_sum(included, column)
                    baseline = baseline_amounts[column]
                    prefix = output_names[column]
                    row[f"included_{prefix}"] = included_amount
                    row[f"{prefix}_coverage_rate"] = (
                        float(included_amount / baseline) if baseline else None
                    )
                rows.append(row)
    return pd.DataFrame(rows)


def build_ranking_population_v2(
    *,
    core_path: Path,
    strict_path: Path,
    financial_v2_path: Path,
    output_dir: Path,
    overwrite: bool = False,
) -> RankingPopulationV2Result:
    """ranking_population_v2와 strict 비교 산출물을 생성합니다."""
    for path in [core_path, strict_path, financial_v2_path]:
        if not path.exists():
            raise FileNotFoundError(f"필수 입력 파일이 없습니다: {path}")
    core = pd.read_parquet(core_path)
    strict = pd.read_parquet(strict_path)
    financial_v2 = pd.read_parquet(financial_v2_path)
    core["ministry_code"] = core["ministry_code"].astype("string")
    financial_v2["ministry_code"] = financial_v2["ministry_code"].astype("string")
    strict_ids = set(strict[SOURCE_ID].astype(str))

    breakdown, primary_reason = build_strict_exclusion_breakdown(core, strict_ids)
    augmented = add_ranking_v2_flags(core, financial_v2)
    augmented["strict_v1_exclusion_primary_reason"] = primary_reason
    population = augmented.loc[augmented["overall_ranking_eligible"]].copy()
    excluded = augmented.loc[~augmented["overall_ranking_eligible"]].copy()
    v2_ids = set(population[SOURCE_ID].astype(str))
    comparison = _comparison_rows(core, strict_ids, v2_ids)

    original_index = core.set_index(SOURCE_ID).sort_index()
    output_index = augmented.set_index(SOURCE_ID).sort_index()
    amount_changed = 0
    for column in AMOUNT_COLUMNS:
        left = pd.to_numeric(original_index[column], errors="coerce").astype("Float64")
        right = pd.to_numeric(output_index[column], errors="coerce").astype("Float64")
        amount_changed += int((~(left.eq(right) | (left.isna() & right.isna()))).sum())

    primary_total = int(
        breakdown.loc[
            breakdown["decomposition_type"].eq("PRIMARY_MUTUALLY_EXCLUSIVE"),
            "excluded_row_count",
        ].sum()
    )
    strict_gap = len(core) - len(strict)
    variable_counts = {
        column: int(augmented[column].sum())
        for column in [
            "budget_ranking_eligible",
            "execution_ranking_eligible",
            "trend_ranking_eligible",
            "fiscal_instrument_ranking_eligible",
            "program_ranking_eligible",
            "overall_ranking_eligible",
        ]
    }
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "policy_version": "V2_VARIABLE_SPECIFIC",
        "row_counts": {
            "core_financial_population": len(core),
            "strict_ranking_population_v1": len(strict),
            "strict_v1_excluded_from_core": strict_gap,
            "ranking_population_v2": len(population),
            "ranking_population_v2_excluded": len(excluded),
        },
        "strict_exclusion_decomposition": {
            "primary_rule_sum": primary_total,
            "expected_core_minus_strict": strict_gap,
            "fully_reconciled": primary_total == strict_gap,
        },
        "variable_eligibility_counts": variable_counts,
        "rank_confidence_counts": (
            population["rank_confidence"].value_counts().sort_index().to_dict()
        ),
        "hard_exclusion_reason_counts": (
            excluded["ranking_v2_hard_exclusion_reason"]
            .fillna("UNKNOWN")
            .value_counts()
            .sort_index()
            .to_dict()
        ),
        "retained_special_cases": {
            "fiscal_instrument_unknown": int(
                population["fiscal_instrument"].eq("UNKNOWN").sum()
            ),
            "small_comparison_group": int(population["small_group_flag"].sum()),
            "execution_rate_over_1": int(
                _bool(population, "execution_rate_over_100_flag").sum()
            ),
            "observation_boundary": int(
                population["project_status"]
                .isin({"OBSERVATION_START", "OBSERVATION_END"})
                .sum()
            ),
            "relationship_or_trend_limited": int(
                (~population["trend_ranking_eligible"]).sum()
            ),
        },
        "validation": {
            "core_rows_partitioned": len(population) + len(excluded) == len(core),
            "source_key_duplicate_count": int(
                augmented.duplicated(SOURCE_ID, keep=False).sum()
            ),
            "source_amount_changed_cell_count": amount_changed,
            "all_excluded_rows_have_reason": bool(
                excluded["ranking_v2_hard_exclusion_reason"].notna().all()
            ),
            "leading_zero_ministry_codes_preserved": all(
                code in set(augmented["ministry_code"]) for code in ("019", "075")
            ),
            "source_trace_missing_count": int(
                augmented["source_trace"].isna().sum()
            ),
        },
    }

    output_paths = [
        output_dir / "strict_exclusion_rule_breakdown.csv",
        output_dir / "ranking_population_v2.parquet",
        output_dir / "ranking_population_v2_excluded.parquet",
        output_dir / "ranking_population_comparison.csv",
        output_dir / "ranking_population_v2_summary.json",
    ]
    existing = [path for path in output_paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"출력 파일이 이미 있습니다: {existing[0]}")
    output_dir.mkdir(parents=True, exist_ok=True)
    breakdown.to_csv(output_paths[0], index=False, encoding="utf-8-sig")
    population.to_parquet(output_paths[1], index=False)
    excluded.to_parquet(output_paths[2], index=False)
    comparison.to_csv(output_paths[3], index=False, encoding="utf-8-sig")
    output_paths[4].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return RankingPopulationV2Result(
        population=population,
        excluded=excluded,
        rule_breakdown=breakdown,
        comparison=comparison,
        summary=summary,
        output_paths=output_paths,
    )
