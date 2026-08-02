"""전면 구조개선 전 Gate A 기준선과 P0 위험을 재현합니다."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

MINISTRIES = ("019", "075", "102", "162")
YEARS = (2022, 2023, 2024)
FINANCING = {"SUBSIDY", "CONTRIBUTION", "LOAN", "GUARANTEE", "EQUITY", "INTEREST_SUBSIDY"}
CHARACTERISTICS = {"RND", "FACILITY", "INFORMATIZATION", "OPERATION", "DIRECT"}

TABLES = {
    "project_year_v2": (
        "data/processed/masters/project_year_financial_v2.parquet",
        ("project_id",),
        "analysis_original_budget",
        "source-derived project-year observation",
    ),
    "broad": (
        "data/processed/masters/population_sensitivity/broad_population.parquet",
        ("source_project_year_id",),
        "original_budget_analysis_amount",
        "project-year",
    ),
    "core": (
        "data/processed/masters/population_sensitivity/core_financial_population.parquet",
        ("source_project_year_id",),
        "original_budget_analysis_amount",
        "project-year",
    ),
    "ranking_v2": (
        "data/processed/masters/population_sensitivity/ranking_population_v2.parquet",
        ("source_project_year_id",),
        "original_budget_analysis_amount",
        "project-year",
    ),
    "m3_features": (
        "data/analytics/m3/financial_signal_features.parquet",
        ("source_project_year_id",),
        "original_budget_analysis_amount",
        "project-year",
    ),
    "program_year": (
        "data/processed/masters/program_year_financial.parquet",
        (
            "ministry_code",
            "fiscal_year",
            "field_name",
            "sector_name",
            "program_code",
            "program_name",
        ),
        "program_total_original_budget",
        "ministry-program-year",
    ),
    "budget_records": (
        "data/processed/budget/budget_records.parquet",
        ("source_record_id",),
        None,
        "normalized source record",
    ),
    "amount_events": (
        "data/processed/amount_event/budget_amount_events.parquet",
        ("source_record_id", "amount_type"),
        None,
        "source record-amount type",
    ),
    "monthly": (
        "data/processed/monthly_expenditure/monthly_expenditure_2022_2025.parquet",
        (
            "ministry_code",
            "fiscal_year",
            "execution_month",
            "account_code",
            "program_code",
            "activity_code",
            "subactivity_code",
        ),
        None,
        "ministry-year-month-account-program-activity-subactivity",
    ),
    "settlement": (
        "data/processed/settlement/project_settlement.parquet",
        ("source_path", "source_row_number"),
        "settlement_budget_amount",
        "project-year settlement source record",
    ),
    "candidates": (
        "data/analytics/multi_ministry_priority_scenarios/candidate_population.csv",
        ("candidate_id",),
        "account_original_budget",
        "ministry-program-year-account type",
    ),
}

ZONES = (
    ("data/raw", "AUTHORITATIVE_INPUT", "수집 원본", "수집 명령 또는 수기 반입"),
    ("data/manual", "AUTHORITATIVE_DECISION", "사람 검수·확정값", "사람 검수"),
    ("configs", "RULE_SOURCE", "범위·조인·임계값", "Git 변경"),
    ("data/interim", "REGENERABLE_INTERMEDIATE", "OCR·LLM·임시 변환", "성과 파이프라인"),
    (
        "data/processed/budget",
        "REGENERABLE_NORMALIZED",
        "예산 정규화",
        "openfiscal normalize-budget",
    ),
    (
        "data/processed/monthly_expenditure",
        "REGENERABLE_NORMALIZED",
        "월별 집행 정규화",
        "openfiscal normalize-monthly",
    ),
    (
        "data/processed/settlement",
        "REGENERABLE_NORMALIZED",
        "결산 정규화",
        "openfiscal normalize-settlement",
    ),
    ("data/processed/performance", "REGENERABLE_REVIEWED", "성과·PDF 대조", "fiscal-performance"),
    ("data/processed/masters", "REGENERABLE_CORE", "재정 마스터", "fiscal-master"),
    ("data/analytics", "REGENERABLE_ANALYSIS", "피처·후보·검증", "fiscal-analytics"),
    ("data/exports", "PRESENTATION_CONTRACT", "승인된 소비자 계약", "패키지 빌드"),
    ("artifacts", "GENERATED_ARTIFACT", "보고서·그림·실행기록", "각 분석 명령"),
)


def _read(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, dtype={"ministry_code": "string"}, low_memory=False)


def _scope(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame
    if "ministry_code" in result:
        result = result[result["ministry_code"].astype("string").str.zfill(3).isin(MINISTRIES)]
    if "fiscal_year" in result:
        years = pd.to_numeric(result["fiscal_year"], errors="coerce")
        result = result[years.isin(YEARS)]
    return result.copy()


def _concat(frames: list[pd.DataFrame]) -> pd.DataFrame:
    return pd.concat(
        [frame.dropna(axis=1, how="all") for frame in frames],
        ignore_index=True,
        sort=False,
    )


def _amount(frame: pd.DataFrame, column: str) -> float:
    return float(pd.to_numeric(frame[column], errors="coerce").sum())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_tables(root: Path) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    profiles = []
    for name, (relative_path, key, amount_column, grain) in TABLES.items():
        path = root / relative_path
        if not path.is_file():
            raise FileNotFoundError(f"Gate A 필수 입력이 없습니다: {path}")
        frame = _scope(_read(path))
        missing = sorted(set(key) - set(frame.columns))
        if missing:
            raise ValueError(f"{name}의 선언 키 열이 없습니다: {missing}")
        years = (
            pd.to_numeric(frame["fiscal_year"], errors="coerce").dropna()
            if "fiscal_year" in frame
            else []
        )
        profiles.append(
            {
                "table": name,
                "path": relative_path,
                "grain": grain,
                "declared_key": "|".join(key),
                "rows": len(frame),
                "columns": len(frame.columns),
                "key_duplicate_rows": int(frame.duplicated(list(key), keep=False).sum()),
                "year_min": int(min(years)) if len(years) else None,
                "year_max": int(max(years)) if len(years) else None,
                "amount_column": amount_column,
                "amount_sum": _amount(frame, amount_column) if amount_column else None,
                "file_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
        frames[name] = frame
    return frames, pd.DataFrame(profiles)


def _performance(root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    kpis = []
    reconciliations = []
    financial = []
    for code in MINISTRIES:
        base = root / "data/processed/performance/by_ministry" / f"ministry_code={code}"
        kpi_path = base / "analysis_ready/program_kpi_year_analysis_ready.parquet"
        financial_path = (
            root / "data/processed/performance/program_year_performance_financial.parquet"
            if code == "102"
            else base / "program_year_performance_financial.parquet"
        )
        for path in (kpi_path, financial_path):
            if not path.is_file():
                raise FileNotFoundError(f"Gate A 성과 입력이 없습니다: {path}")
        kpis.append(pd.read_parquet(kpi_path))
        financial.append(pd.read_parquet(financial_path))
        if code != "102":
            pdf_path = (
                root
                / "data/processed/performance/pdf_reconciliation"
                / f"ministry_code={code}"
                / f"{code}_performance_pdf_reconciliation.parquet"
            )
            if not pdf_path.is_file():
                raise FileNotFoundError(f"Gate A PDF 대조 입력이 없습니다: {pdf_path}")
            reconciliations.append(pd.read_parquet(pdf_path))
    return (
        _scope(_concat(kpis)),
        _concat(reconciliations),
        _scope(_concat(financial)),
    )


def _zone_inventory(root: Path) -> pd.DataFrame:
    rows = []
    for relative_path, contract, role, producer in ZONES:
        path = root / relative_path
        files = list(path.rglob("*")) if path.exists() else []
        files = [item for item in files if item.is_file()]
        rows.append(
            {
                "path": relative_path,
                "contract": contract,
                "role": role,
                "producer": producer,
                "file_count": len(files),
                "bytes": sum(item.stat().st_size for item in files),
            }
        )
    return pd.DataFrame(rows)


def _git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() or None


def build_refactor_gate_a_audit(
    root: Path,
    *,
    output_dir: Path | None = None,
    overwrite: bool = False,
) -> tuple[dict[str, Any], tuple[Path, ...]]:
    """4개 부처의 현재 기준선과 구조개선 전 P0 위험을 파일로 고정합니다."""
    root = root.resolve()
    output_dir = output_dir or root / "artifacts/refactor/gate_a"
    outputs = (
        output_dir / "baseline_snapshot.json",
        output_dir / "dataset_inventory.csv",
        output_dir / "source_generation_map.csv",
        output_dir / "risk_register.csv",
    )
    existing = [path for path in outputs if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"Gate A 산출물이 이미 있습니다: {existing[0]}")

    frames, inventory = _load_tables(root)
    v2, m3, candidate = frames["project_year_v2"], frames["m3_features"], frames["candidates"]
    kpi, pdf, performance_financial = _performance(root)

    identity_columns = [
        "program_code",
        "activity_code",
        "subactivity_code",
        "program_name",
        "activity_name",
        "subactivity_name",
    ]
    collision = v2[v2[identity_columns].isna().all(axis=1)]
    hierarchy_missing = m3[["program_code", "activity_code", "subactivity_code"]].isna().all(axis=1)
    policy_m3 = m3.loc[~hierarchy_missing]
    unknown = policy_m3[policy_m3["fiscal_instrument"].eq("UNKNOWN")]

    t2_signal = candidate["fiscal_year"].eq(2023) & (
        candidate["low_performance_budget_increase_t2"].fillna(False)
        | candidate["good_performance_budget_decrease_t2"].fillna(False)
    )
    t1_signal = candidate["fiscal_year"].eq(2024) & (
        candidate["low_performance_budget_increase_t1"].fillna(False)
        | candidate["good_performance_budget_decrease_t1"].fillna(False)
    )
    t2_exposure = (
        candidate["fiscal_year"].eq(2023) & candidate["program_total_budget_change_rate_t2"].notna()
    )
    t1_exposure = (
        candidate["fiscal_year"].eq(2024) & candidate["program_total_budget_change_rate_t1"].notna()
    )

    normalized = "_gate_a_program_name"
    kpi = kpi.copy()
    kpi[normalized] = kpi["performance_program_name"].fillna("").str.replace(r"\s+", "", regex=True)
    bridge = kpi.groupby(
        ["ministry_code", "fiscal_year", normalized], as_index=False, dropna=False
    ).agg(
        performance_goal_count=("program_goal_number", "nunique"),
        source_program_code_present=("source_program_code", lambda values: values.notna().any()),
    )
    bridge = bridge[bridge["performance_goal_count"].gt(1) & ~bridge["source_program_code_present"]]
    performance_financial = performance_financial.copy()
    performance_financial[normalized] = (
        performance_financial["performance_program_name"]
        .fillna("")
        .str.replace(r"\s+", "", regex=True)
    )
    bridge = bridge.merge(
        performance_financial[
            ["ministry_code", "fiscal_year", normalized, "original_budget"]
        ].drop_duplicates(["ministry_code", "fiscal_year", normalized]),
        on=["ministry_code", "fiscal_year", normalized],
        how="left",
        validate="one_to_one",
    )

    feedback_path = root / "data/analytics/definition_validation/feedback_cohort_t1_t2.csv"
    feedback = pd.read_csv(feedback_path, dtype={"ministry_code": "string"}, low_memory=False)
    feedback = feedback[
        feedback["ministry_code"].str.zfill(3).isin(MINISTRIES)
        & feedback["base_fiscal_year"].isin(YEARS)
        & feedback["outcome_fiscal_year"].isin(YEARS)
    ]
    feedback_blocked = feedback[
        feedback["cohort_exclusion_reason"].eq("BUDGET_CHANGE_NOT_ELIGIBLE_IN_CHAIN")
    ]
    special_unmatched = candidate[
        candidate["account_type"].eq("SPECIAL_ACCOUNT")
        & ~candidate["account_financial_linkage_status"].eq("COMPLETE")
    ]
    fund_zero = v2[
        v2["account_type"].eq("FUND")
        & pd.to_numeric(v2["execution_denominator_amount"], errors="coerce").eq(0)
    ]
    kpi_ids = set(kpi["source_indicator_id"].astype(str))
    pdf_ids = set(pdf["source_indicator_id"].astype(str))

    checks = {
        "candidate_id_unique": not candidate["candidate_id"].duplicated().any(),
        "candidate_scope_only": set(candidate["ministry_code"].astype(str).str.zfill(3)).issubset(
            MINISTRIES
        )
        and set(candidate["fiscal_year"].astype(int)).issubset(YEARS),
        "kpi_id_unique": not kpi["source_indicator_id"].duplicated().any(),
        "pdf_reconciliation_recoverable": len(pdf) == len(pdf_ids) and pdf_ids.issubset(kpi_ids),
    }
    if not all(checks.values()):
        raise ValueError(
            f"Gate A 필수 계약 실패: {[key for key, value in checks.items() if not value]}"
        )

    physical_ids = int(v2["classification_project_id"].nunique())
    metrics = {
        "project_year_v2": {
            "rows": len(v2),
            "physical_stable_ids": physical_ids,
            "safe_or_provisional_ids": physical_ids + max(len(collision) - 1, 0),
            "original_budget": _amount(v2, "analysis_original_budget"),
        },
        "broad": {
            "rows": len(frames["broad"]),
            "stable_ids": int(frames["broad"]["classification_project_id"].nunique()),
            "original_budget": _amount(frames["broad"], "original_budget_analysis_amount"),
        },
        "core": {
            "rows": len(frames["core"]),
            "stable_ids": int(frames["core"]["classification_project_id"].nunique()),
            "original_budget": _amount(frames["core"], "original_budget_analysis_amount"),
        },
        "m3_physical": {
            "rows": len(m3),
            "stable_ids": int(m3["classification_project_id"].nunique()),
        },
        "m3_policy_interpretable": {
            "rows": len(policy_m3),
            "stable_ids": int(policy_m3["classification_project_id"].nunique()),
            "missing_hierarchy_rows_excluded": int(hierarchy_missing.sum()),
            "original_budget": _amount(policy_m3, "original_budget_analysis_amount"),
        },
        "unknown_peer_group": {
            "rows": len(unknown),
            "stable_ids": int(unknown["classification_project_id"].nunique()),
            "original_budget": _amount(unknown, "original_budget_analysis_amount"),
            "peer_bottom_10": int(unknown["peer_bottom_10_execution_flag"].fillna(False).sum()),
            "peer_bottom_20": int(unknown["peer_bottom_20_execution_flag"].fillna(False).sum()),
            "budget_increase": int(unknown["budget_increase_extreme_flag"].fillna(False).sum()),
            "budget_decrease": int(unknown["budget_decrease_extreme_flag"].fillna(False).sum()),
        },
        "candidate_population": {
            "rows": len(candidate),
            "ids": int(candidate["candidate_id"].nunique()),
        },
        "performance": {
            "kpi_rows": len(kpi),
            "kpi_ids": len(kpi_ids),
            "pdf_rows_019_075_162": len(pdf),
            "pdf_ids_linked": len(pdf_ids & kpi_ids),
        },
    }

    risk_rows = [
        (
            "P0-01",
            "2025 outcome leakage",
            f"T+2 신호 {int(t2_signal.sum())}, T+1 신호 {int(t1_signal.sum())}; 총 노출 {int(t2_exposure.sum() + t1_exposure.sum())}",
            "analytics/mss_priority_scenario_analysis.py",
            "base year와 support outcome year 분리",
        ),
        (
            "P0-02",
            "UNKNOWN peer group",
            f"{len(unknown)}행/{unknown['classification_project_id'].nunique()}사업; 상대신호 184/340/50/49",
            "analytics/m3_financial_signals.py",
            "미확정 시 회계유형 동료집단으로 후퇴",
        ),
        (
            "P0-03",
            "performance bridge amount duplication",
            f"{len(bridge)}프로그램, {_amount(bridge, 'original_budget'):.0f}원",
            "performance_pipeline/manual_performance.py",
            "bridge에서 재정금액 제거",
        ),
        (
            "P0-04",
            "feedback eligibility contamination",
            f"{len(feedback_blocked)}행, {_amount(feedback_blocked, 'base_original_budget_amount'):.0f}원",
            "analytics/analysis_definition_validation.py",
            "예산 환류 적격성 독립",
        ),
        (
            "P0-05",
            "blank identity hash collision",
            f"{len(collision)}행이 {collision['classification_project_id'].nunique(dropna=False)}개 ID",
            "master_engineering/build_masters/project_classification.py:234",
            "source-bound provisional ID 사용",
        ),
        (
            "P0-06",
            "special-account grain mismatch",
            f"UNMATCHED {len(special_unmatched)}행",
            "analytics/mss_same_year_budget_check.py",
            "회계 세부구분 후 공식 단위 집계",
        ),
        (
            "P0-07",
            "recoverable PDF evidence detached",
            f"{len(pdf_ids & kpi_ids)}/{len(pdf_ids)} ID 연결",
            "performance_pipeline/analysis_ready_performance.py",
            "evidence FK로 연결",
        ),
        (
            "P0-08",
            "classification axes mixed",
            f"지원방식 {int(v2['fiscal_instrument'].isin(FINANCING).sum())}, 특성 {int(v2['fiscal_instrument'].isin(CHARACTERISTICS).sum())}, UNKNOWN {int(v2['fiscal_instrument'].eq('UNKNOWN').sum())}",
            "master_engineering/build_masters/project_classification.py",
            "지원방식·사업특성 assertion 분리",
        ),
        (
            "P0-09",
            "fund denominator unavailable",
            f"0 분모 {len(fund_zero)}행",
            "master_engineering/build_masters/financial_v1.py",
            "집행률만 제한",
        ),
    ]
    risks = pd.DataFrame(
        risk_rows,
        columns=["risk_id", "risk", "current_evidence", "code_location", "required_action"],
    )
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "git_head": _git_head(root),
        "scope": {"ministry_codes": list(MINISTRIES), "fiscal_years": list(YEARS)},
        "checks": checks,
        "metrics": metrics,
        "baseline_drift_note": "M3 물리 3,936행과 계층결측 9행 제외 정책범위 3,927행을 구분합니다.",
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs[0].write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    inventory.to_csv(outputs[1], index=False, encoding="utf-8-sig")
    _zone_inventory(root).to_csv(outputs[2], index=False, encoding="utf-8-sig")
    risks.to_csv(outputs[3], index=False, encoding="utf-8-sig")
    return summary, outputs
