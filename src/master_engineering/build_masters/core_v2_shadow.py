"""기존 산출물을 바꾸지 않고 정규화된 core_v2 shadow를 생성합니다."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_MINISTRIES = ("019", "075", "102", "162")
DEFAULT_YEARS = (2022, 2023, 2024)
PROJECT_CODES = ("ministry_code", "program_code", "activity_code", "subactivity_code")
PROJECT_NAMES = ("program_name", "activity_name", "subactivity_name")

SCHEMA_CONTRACT = (
    (
        "source_observation",
        "legacy project-year-account row",
        "source_observation_id",
        "",
        "input row count",
    ),
    ("program_entity", "program identity", "program_entity_id", "", "PK unique"),
    (
        "program_version",
        "program identity-fiscal year",
        "program_version_id",
        "program_entity_id",
        "PK/FK unique",
    ),
    (
        "project_entity",
        "persistent or source-bound project identity",
        "project_entity_id",
        "",
        "PK unique",
    ),
    (
        "project_version",
        "project identity-fiscal year",
        "project_version_id",
        "project_entity_id",
        "PK/FK unique",
    ),
    (
        "hierarchy_assignment",
        "project version-program version",
        "hierarchy_assignment_id",
        "project_version_id;program_version_id",
        "PK/FK unique",
    ),
    (
        "account_or_fund",
        "ministry-account code-account type",
        "account_or_fund_id",
        "",
        "PK unique",
    ),
    (
        "budget_fact",
        "source observation-budget amount type",
        "budget_fact_id",
        "source_observation_id;project_version_id;account_or_fund_id",
        "PK/FK and amount sums",
    ),
    (
        "execution_fact",
        "source observation-execution amount type",
        "execution_fact_id",
        "source_observation_id;project_version_id;account_or_fund_id",
        "PK/FK and amount sums",
    ),
    (
        "evidence_link",
        "target-source observation",
        "evidence_id",
        "source_observation_id",
        "PK/FK unique",
    ),
    (
        "legacy_id_crosswalk",
        "legacy ID-new ID mapping",
        "crosswalk_id",
        "",
        "PK unique; cardinality explicit",
    ),
    (
        "identity_resolution_case",
        "source-bound project identity case",
        "resolution_case_id",
        "project_entity_id;source_observation_id",
        "PK/FK unique",
    ),
)


@dataclass
class CoreV2ShadowResult:
    tables: dict[str, pd.DataFrame]
    summary: dict[str, Any]
    output_paths: list[Path]


def _hash_id(prefix: str, *values: Any) -> str:
    payload = "\x1f".join("" if pd.isna(value) else str(value).strip() for value in values)
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _present(value: Any) -> bool:
    return pd.notna(value) and bool(str(value).strip())


def _canonical(values: pd.Series) -> Any:
    unique = values.dropna().astype("string").str.strip()
    unique = unique[unique.ne("")].drop_duplicates()
    return unique.iloc[0] if len(unique) == 1 else pd.NA


def _variant_count(frame: pd.DataFrame, columns: Iterable[str]) -> int:
    signatures = frame[list(columns)].fillna("").astype("string").agg("\x1f".join, axis=1)
    return int(signatures.nunique())


def _scope(
    frame: pd.DataFrame,
    ministry_codes: Iterable[str],
    fiscal_years: Iterable[int],
) -> pd.DataFrame:
    result = frame.copy()
    result["ministry_code"] = result["ministry_code"].astype("string").str.zfill(3)
    years = pd.to_numeric(result["fiscal_year"], errors="coerce")
    return result[
        result["ministry_code"].isin(tuple(ministry_codes)) & years.isin(tuple(fiscal_years))
    ].copy()


def _entity_rows(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    project_rows: list[dict[str, Any]] = []
    for entity_id, group in frame.groupby("project_entity_id", sort=True, dropna=False):
        first = group.iloc[0]
        project_rows.append(
            {
                "project_entity_id": entity_id,
                "identity_status": first["project_identity_status"],
                "is_persistent": first["project_identity_status"] == "OFFICIAL_CODE_IDENTITY",
                "ministry_code": _canonical(group["ministry_code"]),
                "program_code": _canonical(group["program_code"]),
                "activity_code": _canonical(group["activity_code"]),
                "subactivity_code": _canonical(group["subactivity_code"]),
                "source_observation_count": int(group["source_observation_id"].nunique()),
                "resolution_required": first["project_identity_status"] != "OFFICIAL_CODE_IDENTITY",
            }
        )

    program_rows: list[dict[str, Any]] = []
    for entity_id, group in frame.groupby("program_entity_id", sort=True, dropna=False):
        first = group.iloc[0]
        program_rows.append(
            {
                "program_entity_id": entity_id,
                "identity_status": first["program_identity_status"],
                "is_persistent": first["program_identity_status"] == "OFFICIAL_CODE_IDENTITY",
                "ministry_code": _canonical(group["ministry_code"]),
                "program_code": _canonical(group["program_code"]),
                "source_observation_count": int(group["source_observation_id"].nunique()),
                "resolution_required": first["program_identity_status"] != "OFFICIAL_CODE_IDENTITY",
            }
        )
    return pd.DataFrame(project_rows), pd.DataFrame(program_rows)


def _version_rows(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    project_rows: list[dict[str, Any]] = []
    for version_id, group in frame.groupby("project_version_id", sort=True, dropna=False):
        variants = _variant_count(group, PROJECT_NAMES)
        project_rows.append(
            {
                "project_version_id": version_id,
                "project_entity_id": group["project_entity_id"].iloc[0],
                "fiscal_year": int(group["fiscal_year"].iloc[0]),
                "program_name": _canonical(group["program_name"]),
                "activity_name": _canonical(group["activity_name"]),
                "subactivity_name": _canonical(group["subactivity_name"]),
                "name_variant_count": variants,
                "name_resolution_status": (
                    "SINGLE_SOURCE_NAME" if variants == 1 else "CONFLICTING_SOURCE_NAMES"
                ),
                "source_observation_count": int(group["source_observation_id"].nunique()),
            }
        )

    program_rows: list[dict[str, Any]] = []
    for version_id, group in frame.groupby("program_version_id", sort=True, dropna=False):
        names = group["program_name"].dropna().astype("string").str.strip()
        names = names[names.ne("")].drop_duplicates()
        program_rows.append(
            {
                "program_version_id": version_id,
                "program_entity_id": group["program_entity_id"].iloc[0],
                "fiscal_year": int(group["fiscal_year"].iloc[0]),
                "program_name": names.iloc[0] if len(names) == 1 else pd.NA,
                "name_variant_count": len(names),
                "name_resolution_status": (
                    "SINGLE_SOURCE_NAME" if len(names) == 1 else "CONFLICTING_SOURCE_NAMES"
                ),
                "source_observation_count": int(group["source_observation_id"].nunique()),
            }
        )
    return pd.DataFrame(project_rows), pd.DataFrame(program_rows)


def _financial_facts(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    budget_specs = (
        (
            "analysis_original_budget",
            "analysis_original_budget_source",
            "ORIGINAL_BUDGET",
            "ORIGINAL",
        ),
        (
            "analysis_current_budget",
            "analysis_current_budget_source",
            "CURRENT_BUDGET",
            "CURRENT",
        ),
    )
    budget_parts = []
    for source_field, source_type_field, amount_type, stage in budget_specs:
        part = frame[
            [
                "source_observation_id",
                "project_version_id",
                "account_or_fund_id",
                "fiscal_year",
                source_field,
                source_type_field,
                "in_core_financial_population",
                "budget_analysis_eligible",
                "exclusion_reason",
                "quality_issue_reasons",
            ]
        ].rename(
            columns={
                source_field: "amount_normalized",
                source_type_field: "amount_source",
            }
        )
        part = part[part["amount_normalized"].notna()].copy()
        part["analysis_eligible"] = part["in_core_financial_population"].fillna(False) & part[
            "budget_analysis_eligible"
        ].fillna(False)
        part["amount_type"] = amount_type
        part["appropriation_stage"] = stage
        part["source_field"] = source_field
        part["budget_fact_id"] = part.apply(
            lambda row, fact_type=amount_type: _hash_id(
                "bgt", row["source_observation_id"], fact_type
            ),
            axis=1,
        )
        budget_parts.append(part)
    budget = pd.concat(budget_parts, ignore_index=True)
    budget["amount_raw"] = pd.NA
    budget["unit_normalized"] = "KRW"
    budget["unit_confirmed"] = True
    budget["source_grain"] = "LEGACY_AGGREGATED_PROJECT_YEAR_ACCOUNT"

    execution = frame[
        [
            "source_observation_id",
            "project_version_id",
            "account_or_fund_id",
            "fiscal_year",
            "analysis_settlement_expenditure",
            "analysis_settlement_expenditure_source",
            "in_core_financial_population",
            "execution_analysis_eligible",
            "settlement_analysis_eligible",
            "exclusion_reason",
            "quality_issue_reasons",
        ]
    ].rename(
        columns={
            "analysis_settlement_expenditure": "amount_normalized",
            "analysis_settlement_expenditure_source": "amount_source",
        }
    )
    execution = execution[execution["amount_normalized"].notna()].copy()
    execution["analysis_eligible"] = (
        execution["in_core_financial_population"].fillna(False)
        & execution["execution_analysis_eligible"].fillna(False)
        & execution["settlement_analysis_eligible"].fillna(False)
    )
    execution["amount_type"] = "SETTLEMENT_EXPENDITURE"
    execution["execution_period"] = "ANNUAL_SETTLEMENT"
    execution["source_field"] = "analysis_settlement_expenditure"
    execution["execution_fact_id"] = execution.apply(
        lambda row: _hash_id("exe", row["source_observation_id"], "SETTLEMENT_EXPENDITURE"),
        axis=1,
    )
    execution["amount_raw"] = pd.NA
    execution["unit_normalized"] = "KRW"
    execution["unit_confirmed"] = True
    execution["source_grain"] = "LEGACY_AGGREGATED_PROJECT_YEAR_ACCOUNT"
    return budget, execution


def _evidence_links(
    frame: pd.DataFrame,
    budget: pd.DataFrame,
    execution: pd.DataFrame,
) -> pd.DataFrame:
    parts = []
    for target_table, target_column in (
        ("project_version", "project_version_id"),
        ("program_version", "program_version_id"),
        ("hierarchy_assignment", "hierarchy_assignment_id"),
    ):
        part = frame[["source_observation_id", target_column]].rename(
            columns={target_column: "target_id"}
        )
        part["target_table"] = target_table
        part["source_field"] = "LEGACY_PROJECT_YEAR_ROW"
        parts.append(part)
    for target_table, target_column, facts in (
        ("budget_fact", "budget_fact_id", budget),
        ("execution_fact", "execution_fact_id", execution),
    ):
        part = facts[["source_observation_id", target_column, "source_field"]].rename(
            columns={target_column: "target_id"}
        )
        part["target_table"] = target_table
        parts.append(part)
    evidence = pd.concat(parts, ignore_index=True).drop_duplicates()
    evidence["evidence_id"] = evidence.apply(
        lambda row: _hash_id(
            "evd",
            row["target_table"],
            row["target_id"],
            row["source_observation_id"],
            row["source_field"],
        ),
        axis=1,
    )
    evidence["evidence_status"] = "INDIRECT_PROCESSED_SOURCE"
    return evidence


def _legacy_crosswalk(frame: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for legacy_type, legacy_column, new_type, new_column in (
        ("PROJECT_ID", "project_id", "SOURCE_OBSERVATION", "source_observation_id"),
        ("PROJECT_ID", "project_id", "PROJECT_VERSION", "project_version_id"),
        (
            "CLASSIFICATION_PROJECT_ID",
            "classification_project_id",
            "PROJECT_ENTITY",
            "project_entity_id",
        ),
    ):
        part = pd.DataFrame(
            {
                "legacy_id": frame[legacy_column],
                "new_id": frame[new_column],
                "source_observation_id": frame["source_observation_id"],
            }
        )
        part = part[part["legacy_id"].notna()].drop_duplicates()
        part["legacy_id_type"] = legacy_type
        part["new_id_type"] = new_type
        parts.append(part)
    crosswalk = (
        pd.concat(parts, ignore_index=True)
        .groupby(
            ["legacy_id_type", "legacy_id", "new_id_type", "new_id"],
            dropna=False,
            as_index=False,
        )
        .agg(source_observation_count=("source_observation_id", "nunique"))
    )
    cardinality = crosswalk.groupby(["legacy_id_type", "legacy_id", "new_id_type"], dropna=False)[
        "new_id"
    ].transform("nunique")
    crosswalk["mapping_cardinality"] = cardinality.astype("int64")
    crosswalk["mapping_status"] = cardinality.map(
        lambda count: "ONE_TO_ONE" if count == 1 else "ONE_TO_MANY"
    )
    crosswalk["crosswalk_id"] = crosswalk.apply(
        lambda row: _hash_id(
            "xwk",
            row["legacy_id_type"],
            row["legacy_id"],
            row["new_id_type"],
            row["new_id"],
        ),
        axis=1,
    )
    return crosswalk


def _resolution_cases(frame: pd.DataFrame) -> pd.DataFrame:
    provisional = frame[frame["project_identity_status"].eq("PROVISIONAL_SOURCE_BOUND")]
    rows = []
    for _, row in provisional.iterrows():
        missing = [column for column in PROJECT_CODES[1:] if not _present(row[column])]
        rows.append(
            {
                "resolution_case_id": _hash_id("res", row["project_entity_id"]),
                "project_entity_id": row["project_entity_id"],
                "source_observation_id": row["source_observation_id"],
                "legacy_classification_project_id": row["classification_project_id"],
                "reason_code": (
                    "ALL_PROJECT_CODES_MISSING"
                    if len(missing) == len(PROJECT_CODES) - 1
                    else "PARTIAL_PROJECT_CODES_MISSING"
                ),
                "missing_code_fields": ";".join(missing),
                "resolution_status": "UNRESOLVED",
                "blocks_current_year_financial_analysis": False,
                "blocks_cross_year_entity_analysis": True,
                "source_original_budget": row["analysis_original_budget"],
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "resolution_case_id",
            "project_entity_id",
            "source_observation_id",
            "legacy_classification_project_id",
            "reason_code",
            "missing_code_fields",
            "resolution_status",
            "blocks_current_year_financial_analysis",
            "blocks_cross_year_entity_analysis",
            "source_original_budget",
        ],
    )


def _validate(
    tables: dict[str, pd.DataFrame], scoped: pd.DataFrame, cutoff_year: int
) -> dict[str, bool]:
    observations = tables["source_observation"]
    entities = tables["project_entity"]
    versions = tables["project_version"]
    programs = tables["program_entity"]
    program_versions = tables["program_version"]
    assignments = tables["hierarchy_assignment"]
    accounts = tables["account_or_fund"]
    budget = tables["budget_fact"]
    execution = tables["execution_fact"]
    evidence = tables["evidence_link"]
    crosswalk = tables["legacy_id_crosswalk"]
    cases = tables["identity_resolution_case"]

    checks = {
        "source_row_count_preserved": len(observations) == len(scoped),
        "source_observation_pk_unique": observations["source_observation_id"].is_unique,
        "project_entity_pk_unique": entities["project_entity_id"].is_unique,
        "project_version_pk_unique": versions["project_version_id"].is_unique,
        "program_entity_pk_unique": programs["program_entity_id"].is_unique,
        "program_version_pk_unique": program_versions["program_version_id"].is_unique,
        "hierarchy_assignment_pk_unique": assignments["hierarchy_assignment_id"].is_unique,
        "account_or_fund_pk_unique": accounts["account_or_fund_id"].is_unique,
        "budget_fact_pk_unique": budget["budget_fact_id"].is_unique,
        "execution_fact_pk_unique": execution["execution_fact_id"].is_unique,
        "evidence_pk_unique": evidence["evidence_id"].is_unique,
        "crosswalk_pk_unique": crosswalk["crosswalk_id"].is_unique,
        "resolution_case_pk_unique": cases["resolution_case_id"].is_unique,
        "project_version_fk_complete": set(observations["project_version_id"]).issubset(
            set(versions["project_version_id"])
        ),
        "project_entity_fk_complete": set(versions["project_entity_id"]).issubset(
            set(entities["project_entity_id"])
        ),
        "program_version_fk_complete": set(observations["program_version_id"]).issubset(
            set(program_versions["program_version_id"])
        ),
        "program_entity_fk_complete": set(program_versions["program_entity_id"]).issubset(
            set(programs["program_entity_id"])
        ),
        "account_fk_complete": set(observations["account_or_fund_id"]).issubset(
            set(accounts["account_or_fund_id"])
        ),
        "evidence_source_fk_complete": set(evidence["source_observation_id"]).issubset(
            set(observations["source_observation_id"])
        ),
        "cutoff_isolated": observations["fiscal_year"].max() <= cutoff_year,
    }
    source_amounts = {
        "ORIGINAL_BUDGET": int(
            pd.to_numeric(scoped["analysis_original_budget"], errors="coerce").sum()
        ),
        "CURRENT_BUDGET": int(
            pd.to_numeric(scoped["analysis_current_budget"], errors="coerce").sum()
        ),
        "SETTLEMENT_EXPENDITURE": int(
            pd.to_numeric(scoped["analysis_settlement_expenditure"], errors="coerce").sum()
        ),
    }
    fact_amounts = {
        key: int(
            pd.to_numeric(
                (
                    budget.loc[budget["amount_type"].eq(key), "amount_normalized"]
                    if key != "SETTLEMENT_EXPENDITURE"
                    else execution["amount_normalized"]
                ),
                errors="coerce",
            ).sum()
        )
        for key in source_amounts
    }
    checks["amount_sums_preserved_by_type"] = source_amounts == fact_amounts

    blank = (
        observations[list(PROJECT_CODES[1:]) + list(PROJECT_NAMES)]
        .map(lambda value: not _present(value))
        .all(axis=1)
    )
    checks["fully_blank_identity_collision_removed"] = observations.loc[
        blank, "project_entity_id"
    ].nunique() == int(blank.sum())
    checks = {name: bool(passed) for name, passed in checks.items()}
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise ValueError(f"core_v2 shadow 계약 검증 실패: {failed}")
    return checks


def build_core_v2_shadow(
    *,
    input_path: Path,
    output_dir: Path,
    ministry_codes: Iterable[str] = DEFAULT_MINISTRIES,
    fiscal_years: Iterable[int] = DEFAULT_YEARS,
    overwrite: bool = False,
) -> CoreV2ShadowResult:
    """4개 부처 기준선을 정규화한 Parquet shadow 계약으로 분해합니다."""
    ministry_codes = tuple(ministry_codes)
    fiscal_years = tuple(fiscal_years)
    if not ministry_codes or not fiscal_years:
        raise ValueError("core_v2 부처와 회계연도 범위는 비어 있을 수 없습니다.")
    cutoff_year = max(fiscal_years)
    input_frame = pd.read_parquet(input_path)
    required = {
        "project_id",
        "classification_project_id",
        "fiscal_year",
        "ministry_code",
        "account_code",
        "account_type",
        "account_name",
        *PROJECT_CODES[1:],
        *PROJECT_NAMES,
        "analysis_original_budget",
        "analysis_current_budget",
        "analysis_settlement_expenditure",
        "analysis_original_budget_source",
        "analysis_current_budget_source",
        "analysis_settlement_expenditure_source",
        "in_broad_population",
        "in_core_financial_population",
        "budget_analysis_eligible",
        "execution_analysis_eligible",
        "settlement_analysis_eligible",
        "ranking_analysis_eligible",
        "exclusion_reason",
        "project_category",
        "quality_issue_reasons",
        "source_trace",
    }
    missing = sorted(required - set(input_frame.columns))
    if missing:
        raise ValueError(f"core_v2 입력 필수 열이 없습니다: {missing}")
    scoped = _scope(input_frame, ministry_codes, fiscal_years)
    if scoped.empty:
        raise ValueError("core_v2 대상 범위가 비었습니다.")
    if scoped["project_id"].isna().any() or not scoped["project_id"].is_unique:
        raise ValueError("legacy project_id는 범위 안에서 non-null unique여야 합니다.")

    for column in (*PROJECT_CODES, "account_code"):
        scoped[column] = scoped[column].astype("string").str.strip()
    scoped["source_observation_id"] = scoped["project_id"].map(lambda value: _hash_id("obs", value))
    complete_project = scoped[list(PROJECT_CODES)].map(_present).all(axis=1)
    complete_program = scoped[["ministry_code", "program_code"]].map(_present).all(axis=1)
    scoped["project_identity_status"] = complete_project.map(
        {True: "OFFICIAL_CODE_IDENTITY", False: "PROVISIONAL_SOURCE_BOUND"}
    )
    scoped["project_entity_id"] = scoped.apply(
        lambda row: (
            _hash_id("prj", *(row[column] for column in PROJECT_CODES))
            if complete_project.loc[row.name]
            else _hash_id("prv", row["source_observation_id"])
        ),
        axis=1,
    )
    scoped["project_version_id"] = scoped.apply(
        lambda row: _hash_id("pyr", row["project_entity_id"], row["fiscal_year"]), axis=1
    )
    scoped["program_identity_status"] = complete_program.map(
        {True: "OFFICIAL_CODE_IDENTITY", False: "PROVISIONAL_SOURCE_BOUND"}
    )
    scoped["program_entity_id"] = scoped.apply(
        lambda row: (
            _hash_id("pgm", row["ministry_code"], row["program_code"])
            if complete_program.loc[row.name]
            else _hash_id("pgp", row["source_observation_id"])
        ),
        axis=1,
    )
    scoped["program_version_id"] = scoped.apply(
        lambda row: _hash_id("pgy", row["program_entity_id"], row["fiscal_year"]), axis=1
    )
    scoped["account_or_fund_id"] = scoped.apply(
        lambda row: (
            _hash_id("acc", row["ministry_code"], row["account_code"], row["account_type"])
            if _present(row["account_code"])
            else _hash_id("acp", row["source_observation_id"])
        ),
        axis=1,
    )
    scoped["hierarchy_assignment_id"] = scoped.apply(
        lambda row: _hash_id("asg", row["project_version_id"], row["program_version_id"]),
        axis=1,
    )

    project_entity, program_entity = _entity_rows(scoped)
    project_version, program_version = _version_rows(scoped)
    hierarchy = (
        scoped[
            [
                "hierarchy_assignment_id",
                "project_version_id",
                "program_version_id",
                "fiscal_year",
            ]
        ]
        .drop_duplicates()
        .sort_values("hierarchy_assignment_id")
        .reset_index(drop=True)
    )
    hierarchy["assignment_status"] = "OBSERVED"

    account_rows = []
    for account_id, group in scoped.groupby("account_or_fund_id", sort=True, dropna=False):
        names = group["account_name"].dropna().astype("string").str.strip()
        names = names[names.ne("")].drop_duplicates()
        account_rows.append(
            {
                "account_or_fund_id": account_id,
                "ministry_code": _canonical(group["ministry_code"]),
                "account_code": _canonical(group["account_code"]),
                "account_type": _canonical(group["account_type"]),
                "account_name": names.iloc[0] if len(names) == 1 else pd.NA,
                "name_variant_count": len(names),
                "identity_status": (
                    "OFFICIAL_CODE_IDENTITY"
                    if group["account_code"].map(_present).all()
                    else "PROVISIONAL_SOURCE_BOUND"
                ),
            }
        )
    account_or_fund = pd.DataFrame(account_rows)

    observation_columns = [
        "source_observation_id",
        "project_id",
        "classification_project_id",
        "project_entity_id",
        "project_version_id",
        "program_entity_id",
        "program_version_id",
        "hierarchy_assignment_id",
        "account_or_fund_id",
        "project_identity_status",
        "program_identity_status",
        "fiscal_year",
        "ministry_code",
        "account_code",
        "account_type",
        "account_name",
        *PROJECT_CODES[1:],
        *PROJECT_NAMES,
        "analysis_original_budget",
        "analysis_current_budget",
        "analysis_settlement_expenditure",
        "analysis_original_budget_source",
        "analysis_current_budget_source",
        "analysis_settlement_expenditure_source",
        "in_broad_population",
        "in_core_financial_population",
        "budget_analysis_eligible",
        "execution_analysis_eligible",
        "settlement_analysis_eligible",
        "ranking_analysis_eligible",
        "exclusion_reason",
        "project_category",
        "quality_issue_reasons",
        "source_trace",
    ]
    source_observation = (
        scoped[observation_columns].sort_values("source_observation_id").reset_index(drop=True)
    )
    source_observation["source_grain"] = "LEGACY_PROJECT_YEAR_ACCOUNT"
    source_observation["analysis_cutoff_year"] = cutoff_year

    budget_fact, execution_fact = _financial_facts(scoped)
    evidence_link = _evidence_links(scoped, budget_fact, execution_fact)
    legacy_crosswalk = _legacy_crosswalk(scoped)
    identity_resolution_case = _resolution_cases(scoped)
    schema_contract = pd.DataFrame(
        SCHEMA_CONTRACT,
        columns=["table", "grain", "primary_key", "foreign_keys", "quality_gate"],
    )
    tables = {
        "source_observation": source_observation,
        "program_entity": program_entity,
        "program_version": program_version,
        "project_entity": project_entity,
        "project_version": project_version,
        "hierarchy_assignment": hierarchy,
        "account_or_fund": account_or_fund,
        "budget_fact": budget_fact,
        "execution_fact": execution_fact,
        "evidence_link": evidence_link,
        "legacy_id_crosswalk": legacy_crosswalk,
        "identity_resolution_case": identity_resolution_case,
    }
    checks = _validate(tables, scoped, cutoff_year)

    output_paths = [output_dir / f"{name}.parquet" for name in tables]
    contract_path = output_dir / "schema_contract.csv"
    manifest_path = output_dir / "manifest.json"
    all_paths = [*output_paths, contract_path, manifest_path]
    existing = [path for path in all_paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"core_v2 shadow 출력이 이미 있습니다: {existing[0]}")
    output_dir.mkdir(parents=True, exist_ok=True)
    for (name, table), path in zip(tables.items(), output_paths, strict=True):
        table.to_parquet(path, index=False)
    schema_contract.to_csv(contract_path, index=False, encoding="utf-8-sig")

    amount_sums = {
        "original_budget": int(
            pd.to_numeric(scoped["analysis_original_budget"], errors="coerce").sum()
        ),
        "current_budget": int(
            pd.to_numeric(scoped["analysis_current_budget"], errors="coerce").sum()
        ),
        "settlement_expenditure": int(
            pd.to_numeric(scoped["analysis_settlement_expenditure"], errors="coerce").sum()
        ),
    }
    analysis_eligible_amount_sums = {
        "original_budget": int(
            pd.to_numeric(
                budget_fact.loc[
                    budget_fact["amount_type"].eq("ORIGINAL_BUDGET")
                    & budget_fact["analysis_eligible"],
                    "amount_normalized",
                ],
                errors="coerce",
            ).sum()
        ),
        "current_budget": int(
            pd.to_numeric(
                budget_fact.loc[
                    budget_fact["amount_type"].eq("CURRENT_BUDGET")
                    & budget_fact["analysis_eligible"],
                    "amount_normalized",
                ],
                errors="coerce",
            ).sum()
        ),
        "settlement_expenditure": int(
            pd.to_numeric(
                execution_fact.loc[execution_fact["analysis_eligible"], "amount_normalized"],
                errors="coerce",
            ).sum()
        ),
    }
    summary = {
        "schema_version": "core_v2_shadow.1",
        "generated_at": datetime.now(UTC).isoformat(),
        "input": {"path": str(input_path), "sha256": _sha256(input_path)},
        "scope": {
            "ministry_codes": list(ministry_codes),
            "fiscal_years": list(fiscal_years),
            "analysis_cutoff_year": cutoff_year,
        },
        "rows": {name: len(table) for name, table in tables.items()},
        "amount_sums": amount_sums,
        "analysis_eligible_amount_sums": analysis_eligible_amount_sums,
        "identity": {
            "persistent_project_entities": int(project_entity["is_persistent"].sum()),
            "provisional_project_entities": int((~project_entity["is_persistent"]).sum()),
            "project_versions_with_name_conflicts": int(
                project_version["name_resolution_status"].eq("CONFLICTING_SOURCE_NAMES").sum()
            ),
            "legacy_one_to_many_crosswalk_rows": int(
                legacy_crosswalk["mapping_status"].eq("ONE_TO_MANY").sum()
            ),
        },
        "checks": checks,
        "output_sha256": {path.name: _sha256(path) for path in [*output_paths, contract_path]},
        "limitations": [
            "legacy aggregated project-year input에서 만든 shadow이며 raw source fact를 대체하지 않습니다.",
            "성과지표와 월별 집행은 다음 독립 batch에서 각자의 grain으로 연결합니다.",
            "provisional identity는 현재연도 재정분석에는 유지되지만 연도간 entity 추세에는 사용하지 않습니다.",
        ],
    }
    manifest_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return CoreV2ShadowResult(tables=tables, summary=summary, output_paths=all_paths)
