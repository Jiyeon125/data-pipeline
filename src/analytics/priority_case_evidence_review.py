"""4개 부처 점검 후보의 대표 사례·반례 근거 검수."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from analytics.mss_priority_scenario_analysis import (
    add_program_total_feedback as _add_program_total_feedback,
)
from analytics.mss_priority_scenario_analysis import apply_feedback_cutoff

T1_DIRECTION_SQL = """
SELECT
    ministry_code,
    ministry_name,
    CASE
        WHEN program_total_budget_change_rate_t1 > 0 THEN 'INCREASE'
        WHEN program_total_budget_change_rate_t1 < 0 THEN 'DECREASE'
        ELSE 'NO_CHANGE'
    END AS t1_budget_direction,
    COUNT(*) AS program_account_rows,
    SUM(account_original_budget) AS original_budget,
    SUM(CASE WHEN evidence_status = 'CONFIRMED' THEN 1 ELSE 0 END) AS confirmed_rows
FROM candidate_population
WHERE performance_miss = 1
  AND program_total_feedback_complete_t1 = 1
GROUP BY
    ministry_code,
    ministry_name,
    t1_budget_direction
ORDER BY
    ministry_code,
    t1_budget_direction
""".strip()

CASE_TABLE_SQL = """
SELECT
    case_order,
    CASE case_role
        WHEN 'DATA_BLOCKER' THEN '데이터 먼저'
        WHEN 'MISS_THEN_T1_INCREASE' THEN '보고 목표 미달 뒤 증액'
        WHEN 'MISS_THEN_T1_DECREASE_COUNTEREXAMPLE' THEN '보고 목표 미달 뒤 감액 반례'
        WHEN 'ALL_MET_THEN_T1_INCREASE_CONTEXT' THEN '보고 목표 달성 뒤 증액 맥락'
    END AS case_role,
    ministry_name,
    fiscal_year,
    performance_program_name,
    account_type,
    below_target_count,
    account_execution_rate,
    program_total_budget_change_rate_t1,
    feedback_budget_change_rate_t1,
    budget_direction_reconciled,
    evidence_status
FROM selected_cases
ORDER BY case_order
""".strip()


class CaseEvidenceReviewError(ValueError):
    """사례 검수 입력이나 검증 조건이 깨졌을 때 발생합니다."""


@dataclass(frozen=True)
class CaseEvidencePaths:
    root: Path
    candidates: Path
    project_queue: Path
    program_financial: Path
    performance_root: Path
    output_dir: Path
    report: Path
    report_artifact: Path

    @classmethod
    def from_root(cls, root: Path) -> CaseEvidencePaths:
        root = root.resolve()
        return cls(
            root=root,
            candidates=root
            / "data/analytics/multi_ministry_priority_scenarios/candidate_population.csv",
            project_queue=root / "data/analytics/multi_ministry_priority_scenarios/"
            "full_population_project_review_queue.csv",
            program_financial=root / "data/processed/masters/program_year_financial.parquet",
            performance_root=root / "data/processed/performance/by_ministry",
            output_dir=root / "data/analytics/priority_case_evidence_review",
            report=root / "docs/PRIORITY_CASE_EVIDENCE_REVIEW.md",
            report_artifact=root / "artifacts/reports/priority_case_evidence_review/artifact.json",
        )


@dataclass(frozen=True)
class CaseEvidenceResult:
    cases: pd.DataFrame
    indicator_evidence: pd.DataFrame
    project_drilldown: pd.DataFrame
    summary: dict[str, Any]
    output_paths: tuple[Path, ...]
    report_path: Path


def _bool(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame[column].astype("boolean").fillna(False).astype(bool)


def _normalize_name(values: pd.Series) -> pd.Series:
    return (
        values.astype("string")
        .str.replace(r"\s+", "", regex=True)
        .str.replace("·", "", regex=False)
        .str.strip()
    )


def _prepare_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    required = {
        "candidate_id",
        "ministry_code",
        "ministry_name",
        "fiscal_year",
        "program_goal_number",
        "field_name",
        "sector_name",
        "program_code",
        "financial_program_name",
        "performance_program_name",
        "account_type",
        "evidence_status",
        "below_target_count",
        "reported_rate_count",
        "feedback_budget_complete_t1",
        "feedback_budget_change_rate_t1",
        "low_performance_budget_increase_t1",
        "review_intensity",
        "review_intensity_order",
        "repeated_signal_family_count",
        "independent_signal_family_count",
        "account_original_budget",
    }
    missing = sorted(required.difference(candidates.columns))
    if missing:
        raise CaseEvidenceReviewError(f"후보 입력 필수 열 누락: {missing}")
    if candidates["candidate_id"].duplicated().any():
        raise CaseEvidenceReviewError("후보 입력 candidate_id가 중복됩니다.")

    result = candidates.copy()
    result["ministry_code"] = result["ministry_code"].astype("string").str.zfill(3)
    result["program_code"] = result["program_code"].astype("string")
    result["fiscal_year"] = pd.to_numeric(result["fiscal_year"], errors="raise").astype(int)
    for column in (
        "below_target_count",
        "reported_rate_count",
        "feedback_budget_change_rate_t1",
        "repeated_signal_family_count",
        "independent_signal_family_count",
        "account_original_budget",
    ):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result["performance_miss"] = result["below_target_count"].fillna(0).gt(0)
    result["all_reported_met"] = (
        result["reported_rate_count"].fillna(0).gt(0) & ~result["performance_miss"]
    )
    result["program_name_normalized_case"] = _normalize_name(result["performance_program_name"])
    result["evidence_order"] = result["evidence_status"].map(
        {"CONFIRMED": 0, "LIMITED": 1, "DATA_BLOCKED": 2}
    )
    return result


def add_program_total_feedback(
    candidates: pd.DataFrame,
    program_financial: pd.DataFrame,
    *,
    cutoff_year: int | None = None,
) -> pd.DataFrame:
    """공통 후보 산출기와 동일한 프로그램 전체금액 정의를 사용합니다."""
    result = _add_program_total_feedback(_prepare_candidates(candidates), program_financial)
    if cutoff_year is not None:
        result = apply_feedback_cutoff(result, cutoff_year)
    result["low_performance_program_total_budget_increase_t1"] = (
        result["performance_miss"]
        & result["program_total_feedback_complete_t1"]
        & result["program_total_budget_change_rate_t1"].gt(0)
    )
    return result


def _append_case(
    selected: list[pd.DataFrame],
    candidates: pd.DataFrame,
    *,
    role: str,
    reason: str,
    limit: int,
    exclude_ids: set[str],
) -> None:
    available = candidates.loc[~candidates["candidate_id"].isin(exclude_ids)].copy()
    if available.empty:
        return
    picked = available.head(limit).copy()
    picked["case_role"] = role
    picked["case_selection_reason"] = reason
    selected.append(picked)
    exclude_ids.update(picked["candidate_id"].tolist())


def select_review_cases(candidates: pd.DataFrame) -> pd.DataFrame:
    """데이터 차단·4개 부처 증가사례·확정 반례를 설명 가능하게 선택합니다."""
    frame = _prepare_candidates(candidates)
    selected: list[pd.DataFrame] = []
    used: set[str] = set()

    blockers = frame[_bool(frame, "data_validation_signal")].sort_values(
        ["account_original_budget", "candidate_id"],
        ascending=[False, True],
        na_position="last",
    )
    _append_case(
        selected,
        blockers,
        role="DATA_BLOCKER",
        reason="판단 전에 프로그램 코드·분모·금액 연결 근거를 확인해야 하는 최대 예산 사례",
        limit=1,
        exclude_ids=used,
    )

    increases = frame[_bool(frame, "low_performance_program_total_budget_increase_t1")].sort_values(
        [
            "evidence_order",
            "repeated_signal_family_count",
            "independent_signal_family_count",
            "account_original_budget",
            "candidate_id",
        ],
        ascending=[True, False, False, False, True],
        na_position="last",
    )
    ministry_picks = increases.groupby("ministry_code", sort=True, as_index=False).head(1)
    _append_case(
        selected,
        ministry_picks,
        role="MISS_THEN_T1_INCREASE",
        reason="보고 목표 미달 뒤 T+1 예산 증가가 확인된 부처별 대표 사례",
        limit=len(ministry_picks),
        exclude_ids=used,
    )

    decrease_counterexamples = frame[
        frame["performance_miss"]
        & _bool(frame, "program_total_feedback_complete_t1")
        & frame["program_total_budget_change_rate_t1"].lt(0)
        & frame["evidence_status"].eq("CONFIRMED")
    ].sort_values(
        [
            "repeated_signal_family_count",
            "independent_signal_family_count",
            "account_original_budget",
            "candidate_id",
        ],
        ascending=[False, False, False, True],
        na_position="last",
    )
    _append_case(
        selected,
        decrease_counterexamples,
        role="MISS_THEN_T1_DECREASE_COUNTEREXAMPLE",
        reason="보고 목표 미달 뒤에도 T+1 예산이 감소한 확정근거 반례",
        limit=4,
        exclude_ids=used,
    )

    met_increase_counterexamples = frame[
        frame["all_reported_met"]
        & _bool(frame, "program_total_feedback_complete_t1")
        & frame["program_total_budget_change_rate_t1"].gt(0)
        & frame["evidence_status"].eq("CONFIRMED")
    ].sort_values(
        ["account_original_budget", "candidate_id"],
        ascending=[False, True],
        na_position="last",
    )
    _append_case(
        selected,
        met_increase_counterexamples,
        role="ALL_MET_THEN_T1_INCREASE_CONTEXT",
        reason="보고된 지표가 모두 목표 이상이면서 T+1 예산이 증가한 해석 맥락 사례",
        limit=2,
        exclude_ids=used,
    )

    if not selected:
        raise CaseEvidenceReviewError("선정 가능한 대표 사례가 없습니다.")

    result = pd.concat(selected, ignore_index=True)
    role_order = {
        "DATA_BLOCKER": 1,
        "MISS_THEN_T1_INCREASE": 2,
        "MISS_THEN_T1_DECREASE_COUNTEREXAMPLE": 3,
        "ALL_MET_THEN_T1_INCREASE_CONTEXT": 4,
    }
    result["case_role_order"] = result["case_role"].map(role_order)
    result = result.sort_values(
        ["case_role_order", "ministry_code", "account_original_budget", "candidate_id"],
        ascending=[True, True, False, True],
        na_position="last",
    ).reset_index(drop=True)
    result.insert(0, "case_order", np.arange(1, len(result) + 1))
    return result


def t1_direction_summary(candidates: pd.DataFrame) -> pd.DataFrame:
    frame = _prepare_candidates(candidates)
    query_input = frame[
        [
            "ministry_code",
            "ministry_name",
            "program_total_budget_change_rate_t1",
            "account_original_budget",
            "evidence_status",
        ]
    ].copy()
    query_input["performance_miss"] = frame["performance_miss"].astype(int)
    query_input["program_total_feedback_complete_t1"] = _bool(
        frame, "program_total_feedback_complete_t1"
    ).astype(int)
    with sqlite3.connect(":memory:") as connection:
        query_input.to_sql("candidate_population", connection, index=False)
        result = pd.read_sql_query(T1_DIRECTION_SQL, connection)
    total = result.groupby(["ministry_code", "ministry_name"])["program_account_rows"].transform(
        "sum"
    )
    result["within_ministry_row_share"] = result["program_account_rows"] / total
    return result.sort_values(["ministry_code", "t1_budget_direction"]).reset_index(drop=True)


def review_intensity_summary(candidates: pd.DataFrame) -> pd.DataFrame:
    frame = _prepare_candidates(candidates)
    result = (
        frame.groupby(["review_intensity_order", "review_intensity"], dropna=False)
        .agg(
            program_account_rows=("candidate_id", "size"),
            original_budget=("account_original_budget", "sum"),
        )
        .reset_index()
    )
    result["row_share"] = result["program_account_rows"] / len(frame)
    total_budget = frame["account_original_budget"].sum(min_count=1)
    result["budget_share"] = result["original_budget"] / total_budget
    return result.sort_values("review_intensity_order").reset_index(drop=True)


def _load_indicator_evidence(paths: CaseEvidencePaths, cases: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    evidence_columns = [
        "source_indicator_id",
        "ministry_code",
        "ministry_name",
        "fiscal_year",
        "program_goal_number",
        "performance_program_name",
        "indicator_name_plan",
        "indicator_name_report",
        "indicator_unit",
        "analysis_plan_target_raw",
        "analysis_report_target_raw",
        "analysis_actual_value_raw",
        "analysis_official_achievement_rate_numeric",
        "plan_source_page",
        "report_source_page",
        "analysis_value_adoption_status",
        "analysis_source_trace",
    ]
    for ministry_code in sorted(cases["ministry_code"].dropna().unique()):
        path = (
            paths.performance_root
            / f"ministry_code={ministry_code}"
            / "analysis_ready/program_kpi_year_analysis_ready.parquet"
        )
        if not path.exists():
            raise FileNotFoundError(path)
        frame = pd.read_parquet(path)
        frame["ministry_code"] = frame["ministry_code"].astype("string").str.zfill(3)
        frame["fiscal_year"] = pd.to_numeric(frame["fiscal_year"], errors="raise").astype(int)
        frame["program_goal_number"] = frame["program_goal_number"].astype("string")
        frame["program_name_normalized_case"] = _normalize_name(frame["performance_program_name"])
        frames.append(frame[[*evidence_columns, "program_name_normalized_case"]])
    indicators = pd.concat(frames, ignore_index=True)
    keys = [
        "candidate_id",
        "ministry_code",
        "fiscal_year",
        "program_goal_number",
        "program_name_normalized_case",
    ]
    cases = cases.copy()
    cases["program_goal_number"] = cases["program_goal_number"].astype("string")
    evidence = cases[keys].merge(
        indicators,
        on=[
            "ministry_code",
            "fiscal_year",
            "program_goal_number",
            "program_name_normalized_case",
        ],
        how="left",
        validate="one_to_many",
    )
    evidence["analysis_official_achievement_rate_numeric"] = pd.to_numeric(
        evidence["analysis_official_achievement_rate_numeric"], errors="coerce"
    )
    evidence["indicator_below_target"] = evidence["analysis_official_achievement_rate_numeric"].lt(
        100
    )
    evidence["indicator_source_trace_available"] = evidence["analysis_source_trace"].notna()
    keep = [
        "candidate_id",
        "source_indicator_id",
        "ministry_code",
        "ministry_name",
        "fiscal_year",
        "performance_program_name",
        "indicator_name_plan",
        "indicator_name_report",
        "indicator_unit",
        "analysis_plan_target_raw",
        "analysis_report_target_raw",
        "analysis_actual_value_raw",
        "analysis_official_achievement_rate_numeric",
        "indicator_below_target",
        "plan_source_page",
        "report_source_page",
        "analysis_value_adoption_status",
        "analysis_source_trace",
        "indicator_source_trace_available",
    ]
    return evidence[keep]


def _load_project_drilldown(
    paths: CaseEvidencePaths, cases: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    projects = pd.read_csv(
        paths.project_queue,
        dtype={
            "ministry_code": "string",
            "program_code": "string",
            "subactivity_code": "string",
        },
    )
    required = {
        "candidate_id",
        "project_id",
        "project_original_budget",
        "project_performance_attributed",
        "program_context_grain",
        "program_context_disclaimer",
    }
    missing = sorted(required - set(projects.columns))
    if missing:
        raise CaseEvidenceReviewError(
            f"세부사업 대기열이 구버전이거나 필수 열이 누락되었습니다: {missing}"
        )
    deprecated = sorted(
        {
            "program_performance_signal",
            "performance_signal",
            "low_performance_budget_increase_t1",
            "low_performance_budget_increase_t2",
            "good_performance_budget_decrease_t1",
            "good_performance_budget_decrease_t2",
        }
        & set(projects.columns)
    )
    if deprecated:
        raise CaseEvidenceReviewError(
            f"세부사업 대기열에 프로그램 수준 구버전 필드가 남아 있습니다: {deprecated}"
        )
    selected = projects[projects["candidate_id"].isin(cases["candidate_id"])].copy()
    selected = selected.sort_values(
        ["candidate_id", "project_review_order_within_candidate", "project_id"]
    )
    selected["project_evidence_rank"] = selected.groupby("candidate_id").cumcount() + 1
    top_projects = selected[selected["project_evidence_rank"].le(3)].copy()
    reconciliation = (
        selected.groupby("candidate_id", dropna=False)
        .agg(
            linked_project_rows=("project_id", "size"),
            linked_project_original_budget=("project_original_budget", "sum"),
            performance_attributed_rows=(
                "project_performance_attributed",
                lambda s: int(s.astype("boolean").fillna(False).sum()),
            ),
        )
        .reset_index()
    )
    return top_projects, reconciliation


def _augment_cases(
    cases: pd.DataFrame,
    indicators: pd.DataFrame,
    project_reconciliation: pd.DataFrame,
) -> pd.DataFrame:
    evidence_summary = (
        indicators.groupby("candidate_id", dropna=False)
        .agg(
            indicator_evidence_rows=("source_indicator_id", "count"),
            indicator_source_trace_rows=("indicator_source_trace_available", "sum"),
            evidence_below_target_count=("indicator_below_target", "sum"),
            plan_source_pages=(
                "plan_source_page",
                lambda s: " | ".join(sorted({str(v) for v in s.dropna()})),
            ),
            report_source_pages=(
                "report_source_page",
                lambda s: " | ".join(sorted({str(v) for v in s.dropna()})),
            ),
        )
        .reset_index()
    )
    result = cases.merge(evidence_summary, on="candidate_id", how="left", validate="one_to_one")
    result = result.merge(
        project_reconciliation, on="candidate_id", how="left", validate="one_to_one"
    )
    result["project_budget_difference"] = (
        result["linked_project_original_budget"] - result["account_original_budget"]
    )
    result["indicator_count_reconciled"] = result["indicator_evidence_rows"].eq(
        result["indicator_count"]
    )
    result["below_target_count_reconciled"] = result["evidence_below_target_count"].eq(
        result["below_target_count"]
    )
    result["source_trace_complete"] = result["indicator_source_trace_rows"].eq(
        result["indicator_evidence_rows"]
    )
    result["project_budget_reconciled"] = (
        result["project_budget_difference"].abs().le(1e-6).astype("boolean")
    )
    result.loc[
        result["review_item_type"].eq("PROGRAM_DATA_TASK"),
        "project_budget_reconciled",
    ] = pd.NA
    return result


def _format_percent(value: Any) -> str:
    if pd.isna(value):
        return "—"
    return f"{float(value) * 100:.1f}%"


def _format_won(value: Any) -> str:
    if pd.isna(value):
        return "—"
    return f"{float(value) / 1_000_000_000_000:.2f}조원"


def _report_markdown(
    cases: pd.DataFrame,
    direction: pd.DataFrame,
    intensity: pd.DataFrame,
    summary: dict[str, Any],
) -> str:
    role_labels = {
        "DATA_BLOCKER": "데이터 우선",
        "MISS_THEN_T1_INCREASE": "보고 목표 미달 뒤 증액",
        "MISS_THEN_T1_DECREASE_COUNTEREXAMPLE": "보고 목표 미달 뒤 감액 반례",
        "ALL_MET_THEN_T1_INCREASE_CONTEXT": "보고 목표 달성 뒤 증액 맥락",
    }
    lines = [
        "# 4개 부처 점검 후보 대표 사례·반례 검수",
        "",
        "## Executive Summary",
        "",
        (
            f"- **보고 목표 미달은 다음 예산의 단일 방향을 설명하지 못했습니다.** "
            f"T+1 완전 연결 {summary['low_performance_t1_complete_rows']}행 중 "
            f"{summary['low_performance_t1_increase_rows']}행은 증가, "
            f"{summary['low_performance_t1_decrease_rows']}행은 감소했습니다."
        ),
        (
            f"- **확정근거 표본에서도 방향이 갈렸습니다.** "
            f"{summary['confirmed_low_performance_t1_rows']}행 중 증가 "
            f"{summary['confirmed_low_performance_t1_increase_rows']}행, 감소 "
            f"{summary['confirmed_low_performance_t1_decrease_rows']}행이어서 "
            "자동 증액·감액 판단보다 설명 필요 사례를 우선 제시하는 방식이 타당합니다."
        ),
        (
            f"- **집행 신호와 성과 신호도 분리해야 합니다.** 반복 집행 신호 "
            f"{summary['repeated_execution_rows']}행 중 보고 목표 미달은 "
            f"{summary['repeated_execution_with_performance_miss_rows']}행이었고, "
            f"{summary['repeated_execution_without_performance_miss_rows']}행은 "
            "보고된 지표가 모두 목표 이상이었습니다."
        ),
        "",
        "## 선정된 사례",
        "",
        "|구분|부처|연도|프로그램|회계|보고 목표 미달|집행률|프로그램 전체 T+1|연속 분석사업 T+1|방향 일치|근거상태|",
        "|---|---|---:|---|---|---:|---:|---:|---:|---|---|",
    ]
    for row in cases.itertuples(index=False):
        lines.append(
            f"|{role_labels[row.case_role]}|{row.ministry_name}|{row.fiscal_year}|"
            f"{row.performance_program_name}|{row.account_type}|"
            f"{int(row.below_target_count or 0)}|{_format_percent(row.account_execution_rate)}|"
            f"{_format_percent(row.program_total_budget_change_rate_t1)}|"
            f"{_format_percent(row.feedback_budget_change_rate_t1)}|"
            f"{'예' if row.budget_direction_reconciled else '아니요'}|{row.evidence_status}|"
        )
    lines.extend(
        [
            "",
            "## 발견 1. 보고 목표 미달 뒤 예산 반응은 증가와 감소가 함께 존재합니다",
            "",
            (
                f"보고 목표 미달과 프로그램 전체 T+1 예산이 연결된 "
                f"{summary['low_performance_t1_complete_rows']}행에서 증가 "
                f"{summary['low_performance_t1_increase_rows']}행, 감소 "
                f"{summary['low_performance_t1_decrease_rows']}행이 "
                "확인됐습니다. 이는 보고 목표 미달이 예산 증감의 원인이라는 뜻이 아니라, "
                "예산 변화 사유를 추가로 확인해야 하는 후보를 좁혀 준다는 뜻입니다."
            ),
            "",
            (
                f"프로그램 전체와 연속 분석사업 소계의 증감 방향이 다른 행은 "
                f"{summary['t1_budget_direction_mismatch_rows']}행입니다. "
                "국립나주병원처럼 일부 분석사업 소계가 줄어도 인건비·기본경비를 포함한 "
                "프로그램 전체는 늘 수 있으므로 두 금액을 바꾸어 읽으면 안 됩니다."
            ),
            "",
            "## 발견 2. 집행 신호와 성과 신호는 서로 대체할 수 없습니다",
            "",
            (
                f"반복 집행 신호 {summary['repeated_execution_rows']}행 가운데 보고 목표 미달이 "
                f"함께 관측된 행은 {summary['repeated_execution_with_performance_miss_rows']}행이고, "
                f"나머지 {summary['repeated_execution_without_performance_miss_rows']}행은 보고된 "
                "성과지표가 모두 목표 이상이었습니다. "
                "따라서 낮은 집행·연말집중을 성과 부진으로 번역하지 않고 각각의 "
                "원인과 설명을 따로 확인하는 현재 대시보드 구조가 타당합니다."
            ),
            "",
            "## 발견 3. 기금과 데이터 차단 사례는 별도 경로가 필요합니다",
            "",
            (
                "기금 사례는 일반회계와 같은 기준으로 직접 서열화하지 않았습니다. "
                "또한 데이터 우선 15행은 전체 후보의 3.6%지만 본예산의 8.3%를 "
                "차지하므로, 신호 점검 전에 프로그램 코드·분모·금액 연결을 먼저 "
                "복구하는 것이 업무 영향 측면에서 합리적입니다."
            ),
            "",
            "## 권장 다음 단계",
            "",
            "1. 보고 목표 미달 뒤 T+1 증액 사례에는 증액 사유·사업 단계·의무지출 여부를 확인합니다.",
            "2. 동일 신호인데 감액된 반례를 함께 제시해 자동 삭감·증액 도구가 아님을 명시합니다.",
            "3. 기금은 공급·회수·순재정부담 자료가 확보될 때까지 별도 회계 맥락으로 유지합니다.",
            "4. `LIMITED` 사례는 발표 핵심 근거가 아니라 4개 부처 확장 가능성 사례로만 사용합니다.",
            "5. 공식 사유 확인은 `docs/OFFICIAL_BUDGET_CHANGE_EVIDENCE_PLAYBOOK.md` 순서로 기록합니다.",
            "",
            "## 추가 확인 질문",
            "",
            "- 국립춘천병원의 T+1 증액은 시설·인력·의무지출 중 어떤 사유에서 발생했는가?",
            "- 과학기술기반조성의 T+1 감액은 단계전환 또는 대형 시설사업 공정과 관련되는가?",
            "- 중소기업수출촉진지원의 일반회계와 기금은 같은 성과 맥락 안에서 어떤 역할을 나누는가?",
            "",
            "## 한계와 가정",
            "",
            (
                "- 분석 단위는 부처×프로그램×연도×회계유형이며 프로그램 성과를 "
                "세부사업 성과로 귀속하지 않았습니다."
            ),
            "- T+1·T+2는 별도 코호트이며 이 보고서의 방향 비교는 단일 회계 프로그램의 T+1 전체금액 연결행만 사용했습니다.",
            (
                f"- 프로그램 전체와 연속 분석사업 소계의 방향 불일치 "
                f"{summary['t1_budget_direction_mismatch_rows']}행은 전체금액을 우선하고 "
                "소계는 변화 원인 드릴다운에만 사용했습니다."
            ),
            (
                "- 예산 변화 사유, 의무지출, 사업 단계, 성과발현 시차가 없어 인과관계나 "
                "증액·감액의 적정성을 판단할 수 없습니다."
            ),
            "",
            "## 검증 요약",
            "",
            f"- 후보 {summary['candidate_rows']}행, 선정 사례 {summary['selected_case_rows']}행",
            (
                f"- 사례 지표 근거 {summary['indicator_evidence_rows']}행, 출처 추적 누락 "
                f"{summary['indicator_source_trace_missing_rows']}행"
            ),
            f"- 세부사업 성과 귀속 {summary['project_performance_attributed_rows']}행",
            (
                f"- 선정된 정상 검토 사례의 세부사업 예산 합계 불일치 "
                f"{summary['project_budget_mismatch_rows']}행"
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def _json_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(frame.to_json(orient="records", force_ascii=False))


def _report_artifact(
    cases: pd.DataFrame,
    direction: pd.DataFrame,
    intensity: pd.DataFrame,
    summary: dict[str, Any],
) -> dict[str, Any]:
    title = "4개 부처 점검 후보 대표 사례·반례 검수"
    sources = [
        {
            "id": "priority_candidates",
            "label": "4개 부처 비가중 점검 후보",
            "path": "data/analytics/multi_ministry_priority_scenarios/candidate_population.csv",
            "query": {
                "description": "보고 목표 미달과 프로그램 전체 T+1 예산 연결이 모두 있는 행을 부처·예산방향별로 집계합니다.",
                "sql": T1_DIRECTION_SQL,
            },
        },
        {
            "id": "case_review",
            "label": "대표 사례·반례 검수 산출물",
            "path": "data/analytics/priority_case_evidence_review/selected_cases.csv",
            "query": {
                "description": "검수 사례를 선정 순서대로 읽기 쉬운 역할명과 함께 조회합니다.",
                "sql": CASE_TABLE_SQL,
            },
        },
    ]
    chart_rows = direction.copy()
    chart_rows["예산방향"] = chart_rows["t1_budget_direction"].map(
        {"INCREASE": "증가", "DECREASE": "감소", "NO_CHANGE": "변화 없음"}
    )
    with sqlite3.connect(":memory:") as connection:
        cases.to_sql("selected_cases", connection, index=False)
        case_rows = pd.read_sql_query(CASE_TABLE_SQL, connection)
    return {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": title,
            "description": "성과·집행·예산 신호를 자동 처방으로 오해하지 않도록 증액 사례와 반례를 함께 검수합니다.",
            "sources": sources,
            "blocks": [
                {
                    "id": "title",
                    "type": "markdown",
                    "body": f"# {title}",
                },
                {
                    "id": "executive-summary",
                    "type": "markdown",
                    "sourceId": "priority_candidates",
                    "body": (
                        "## Executive Summary\n\n"
                        f"- **보고 목표 미달은 예산의 단일 방향을 설명하지 못했습니다.** "
                        f"T+1 완전 연결 {summary['low_performance_t1_complete_rows']}행 중 "
                        f"증가 {summary['low_performance_t1_increase_rows']}행, 감소 "
                        f"{summary['low_performance_t1_decrease_rows']}행입니다.\n"
                        f"- **확정근거에서도 방향이 갈렸습니다.** "
                        f"{summary['confirmed_low_performance_t1_rows']}행 중 증가 "
                        f"{summary['confirmed_low_performance_t1_increase_rows']}행, 감소 "
                        f"{summary['confirmed_low_performance_t1_decrease_rows']}행입니다.\n"
                        "- **따라서 결과는 증액·감액 처방이 아니라 설명 필요 사례의 "
                        "검토 순서로 사용해야 합니다.**"
                    ),
                },
                {
                    "id": "direction-finding",
                    "type": "markdown",
                    "sourceId": "priority_candidates",
                    "body": (
                        "## 같은 보고 목표 미달 뒤에도 예산은 증가하거나 감소했습니다\n\n"
                        "부처별로 증가와 감소가 모두 관측됩니다. 이 분포는 보고 목표 미달이 "
                        "예산 증감의 원인임을 뜻하지 않으며, 예산 변화 사유를 추가로 "
                        "확인할 후보를 좁혀 줍니다."
                    ),
                },
                {
                    "id": "t1-direction-chart-block",
                    "type": "chart",
                    "chartId": "t1-direction-chart",
                },
                {
                    "id": "case-finding",
                    "type": "markdown",
                    "sourceId": "case_review",
                    "body": (
                        "## 프로그램 전체와 분석사업 소계를 분리해 읽습니다\n\n"
                        f"두 범위의 증감 방향이 다른 행은 "
                        f"{summary['t1_budget_direction_mismatch_rows']}행입니다. "
                        "전체금액은 프로그램 예산 반응에, 연속 분석사업 소계는 "
                        "세부 변화 원인 확인에만 사용합니다."
                    ),
                },
                {
                    "id": "selected-cases-table-block",
                    "type": "table",
                    "tableId": "selected-cases-table",
                },
                {
                    "id": "execution-finding",
                    "type": "markdown",
                    "sourceId": "priority_candidates",
                    "body": (
                        "## 집행 신호와 성과 신호는 서로 대체할 수 없습니다\n\n"
                        f"반복 집행 신호 {summary['repeated_execution_rows']}행 중 보고 목표 "
                        f"미달은 {summary['repeated_execution_with_performance_miss_rows']}행, "
                        "보고된 지표가 모두 목표 이상인 행은 "
                        f"{summary['repeated_execution_without_performance_miss_rows']}행입니다. "
                        "따라서 두 신호는 독립적으로 확인해야 합니다."
                    ),
                },
                {
                    "id": "next-steps",
                    "type": "markdown",
                    "body": (
                        "## 권장 다음 단계\n\n"
                        "1. 보고 목표 미달 뒤 증액 사례의 증액 사유·사업 단계·의무지출 여부를 확인합니다.\n"
                        "2. 감액 반례를 함께 제시해 자동 삭감·증액 도구가 아님을 명시합니다.\n"
                        "3. 기금은 공급·회수·순재정부담 자료 확보 전까지 별도로 해석합니다."
                    ),
                },
                {
                    "id": "further-questions",
                    "type": "markdown",
                    "body": (
                        "## 추가 확인 질문\n\n"
                        "- 국립춘천병원의 T+1 증액은 시설·인력·의무지출 중 어떤 사유인가?\n"
                        "- 과학기술기반조성의 감액은 대형 시설사업 공정이나 단계전환과 관련되는가?\n"
                        "- 중소기업수출촉진지원의 일반회계와 기금은 어떤 역할을 나누는가?"
                    ),
                },
                {
                    "id": "caveats",
                    "type": "markdown",
                    "body": (
                        "## 한계와 가정\n\n"
                        "- 분석 단위는 부처×프로그램×연도×회계유형입니다.\n"
                        "- 프로그램 성과를 세부사업 성과로 귀속하지 않았습니다.\n"
                        "- T+1과 T+2는 별도 코호트이며 방향 비교는 T+1 완전 연결행만 사용했습니다.\n"
                        "- 확정근거는 9행이므로 전체 52행의 비율은 탐색 결과입니다.\n"
                        "- 예산 변화 사유가 없어 인과관계나 증액·감액의 적정성을 판단할 수 없습니다."
                    ),
                },
            ],
            "charts": [
                {
                    "id": "t1-direction-chart",
                    "title": "보고 목표 미달 뒤 프로그램 전체 T+1 예산변화 방향",
                    "dataset": "t1_direction",
                    "type": "bar",
                    "encodings": {
                        "x": {"field": "ministry_name", "type": "nominal"},
                        "y": {"field": "program_account_rows", "type": "quantitative"},
                        "color": {"field": "예산방향", "type": "nominal"},
                    },
                    "options": {"orientation": "vertical", "grouping": "grouped"},
                    "sourceId": "priority_candidates",
                }
            ],
            "tables": [
                {
                    "id": "selected-cases-table",
                    "title": "대표 사례와 반례",
                    "dataset": "selected_cases",
                    "columns": [
                        {"field": "case_order", "label": "순서", "type": "number"},
                        {"field": "case_role", "label": "구분", "type": "text"},
                        {"field": "ministry_name", "label": "부처", "type": "text"},
                        {"field": "fiscal_year", "label": "연도", "type": "number"},
                        {
                            "field": "performance_program_name",
                            "label": "프로그램",
                            "type": "text",
                        },
                        {"field": "account_type", "label": "회계유형", "type": "text"},
                        {
                            "field": "below_target_count",
                            "label": "성과미달 지표",
                            "type": "number",
                        },
                        {
                            "field": "account_execution_rate",
                            "label": "집행률",
                            "type": "percent",
                        },
                        {
                            "field": "program_total_budget_change_rate_t1",
                            "label": "프로그램 전체 T+1",
                            "type": "percent",
                            "semantic": "movement",
                        },
                        {
                            "field": "feedback_budget_change_rate_t1",
                            "label": "연속 분석사업 T+1",
                            "type": "percent",
                            "semantic": "movement",
                        },
                        {
                            "field": "evidence_status",
                            "label": "근거상태",
                            "type": "text",
                        },
                    ],
                    "defaultSort": {"field": "case_order", "direction": "asc"},
                    "sourceId": "case_review",
                }
            ],
        },
        "snapshot": {
            "version": 1,
            "status": "ready",
            "datasets": {
                "t1_direction": _json_records(chart_rows),
                "selected_cases": _json_records(case_rows),
                "review_intensity": _json_records(intensity),
            },
        },
        "sources": sources,
    }


def build_case_evidence_review(paths: CaseEvidencePaths) -> CaseEvidenceResult:
    for source in (paths.candidates, paths.project_queue, paths.program_financial):
        if not source.exists():
            raise FileNotFoundError(source)

    candidates = pd.read_csv(
        paths.candidates,
        dtype={"ministry_code": "string", "program_code": "string"},
    )
    data_cutoff_fiscal_year = int(pd.to_numeric(candidates["fiscal_year"], errors="raise").max())
    prepared = add_program_total_feedback(
        candidates,
        pd.read_parquet(paths.program_financial),
        cutoff_year=data_cutoff_fiscal_year,
    )
    cases = select_review_cases(prepared)
    indicators = _load_indicator_evidence(paths, cases)
    project_drilldown, project_reconciliation = _load_project_drilldown(paths, cases)
    cases = _augment_cases(cases, indicators, project_reconciliation)
    direction = t1_direction_summary(prepared)
    intensity = review_intensity_summary(prepared)

    t1_scope = prepared[
        prepared["performance_miss"] & _bool(prepared, "program_total_feedback_complete_t1")
    ]
    confirmed_t1_scope = t1_scope[t1_scope["evidence_status"].eq("CONFIRMED")]
    repeated = prepared[_bool(prepared, "repeated_execution_signal")]
    normal_cases = cases[~cases["review_item_type"].eq("PROGRAM_DATA_TASK")]

    if not cases["indicator_count_reconciled"].all():
        raise CaseEvidenceReviewError("선정 사례의 성과지표 행 수가 후보 집계와 다릅니다.")
    if not cases["below_target_count_reconciled"].all():
        raise CaseEvidenceReviewError("선정 사례의 성과 미달 수가 원문 근거와 다릅니다.")
    if not cases["source_trace_complete"].all():
        raise CaseEvidenceReviewError("선정 사례 성과지표에 출처 추적 누락이 있습니다.")
    if normal_cases["project_budget_reconciled"].fillna(False).eq(False).any():
        raise CaseEvidenceReviewError("선정 사례의 세부사업 본예산 합계가 프로그램과 다릅니다.")
    if int(project_drilldown["project_performance_attributed"].fillna(False).sum()) != 0:
        raise CaseEvidenceReviewError("프로그램 성과가 세부사업 성과로 귀속됐습니다.")

    summary: dict[str, Any] = {
        "status": "share_with_caveats",
        "data_cutoff_fiscal_year": data_cutoff_fiscal_year,
        "candidate_rows": len(prepared),
        "selected_case_rows": len(cases),
        "selected_case_role_counts": {
            str(key): int(value) for key, value in cases["case_role"].value_counts().items()
        },
        "indicator_evidence_rows": len(indicators),
        "indicator_source_trace_missing_rows": int(
            (~indicators["indicator_source_trace_available"]).sum()
        ),
        "project_drilldown_rows": len(project_drilldown),
        "project_performance_attributed_rows": int(
            project_drilldown["project_performance_attributed"].fillna(False).sum()
        ),
        "project_budget_mismatch_rows": int(
            (~normal_cases["project_budget_reconciled"].fillna(False)).sum()
        ),
        "low_performance_t1_complete_rows": len(t1_scope),
        "low_performance_t1_increase_rows": int(
            t1_scope["program_total_budget_change_rate_t1"].gt(0).sum()
        ),
        "low_performance_t1_decrease_rows": int(
            t1_scope["program_total_budget_change_rate_t1"].lt(0).sum()
        ),
        "confirmed_low_performance_t1_rows": len(confirmed_t1_scope),
        "confirmed_low_performance_t1_increase_rows": int(
            confirmed_t1_scope["program_total_budget_change_rate_t1"].gt(0).sum()
        ),
        "confirmed_low_performance_t1_decrease_rows": int(
            confirmed_t1_scope["program_total_budget_change_rate_t1"].lt(0).sum()
        ),
        "t1_budget_direction_mismatch_rows": int(
            (
                _bool(prepared, "program_total_feedback_complete_t1")
                & _bool(prepared, "feedback_budget_complete_t1")
                & ~_bool(prepared, "budget_direction_reconciled")
            ).sum()
        ),
        "repeated_execution_rows": len(repeated),
        "repeated_execution_with_performance_miss_rows": int(repeated["performance_miss"].sum()),
        "repeated_execution_without_performance_miss_rows": int(repeated["all_reported_met"].sum()),
        "data_first_rows": int(prepared["review_intensity"].eq("DATA_FIRST").sum()),
        "data_first_budget_share": float(
            prepared.loc[
                prepared["review_intensity"].eq("DATA_FIRST"), "account_original_budget"
            ].sum()
            / prepared["account_original_budget"].sum()
        ),
        "interpretation": (
            "점검 후보와 반례를 설명하는 탐색 결과이며 실패·낭비·삭감·증액 판정이 아님"
        ),
    }

    paths.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "selected_cases.csv": cases,
        "indicator_evidence.csv": indicators,
        "project_drilldown.csv": project_drilldown,
        "t1_direction_summary.csv": direction,
        "review_intensity_summary.csv": intensity,
    }
    output_paths: list[Path] = []
    for name, frame in outputs.items():
        path = paths.output_dir / name
        frame.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")
        output_paths.append(path)
    summary_path = paths.output_dir / "case_validation_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    output_paths.append(summary_path)

    paths.report.write_text(
        _report_markdown(cases, direction, intensity, summary),
        encoding="utf-8",
        newline="\n",
    )
    paths.report_artifact.parent.mkdir(parents=True, exist_ok=True)
    paths.report_artifact.write_text(
        json.dumps(
            _report_artifact(cases, direction, intensity, summary),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
        newline="\n",
    )
    output_paths.append(paths.report_artifact)
    return CaseEvidenceResult(
        cases=cases,
        indicator_evidence=indicators,
        project_drilldown=project_drilldown,
        summary=summary,
        output_paths=tuple(output_paths),
        report_path=paths.report,
    )
