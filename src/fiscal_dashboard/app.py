"""다부처 점검 후보·순위 안정성·성과 원문 검수 Streamlit 대시보드."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = PROJECT_ROOT / "src"
# Streamlit Cloud는 requirements.txt만 설치하고 editable 패키지를 안 넣을 수 있음
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from matplotlib import font_manager

from performance_pipeline.llm_harness import classify_rows
from performance_pipeline.pdf_reconciliation import (
    DEFAULT_MANUAL_REVIEW_CONFIRMATIONS_PATH,
    REVIEW_STATUS_VALUES,
    apply_manual_review_confirmations,
    load_manual_review_confirmations,
    upsert_manual_review_confirmation,
)

DATA_DIR = Path("data/analytics/multi_ministry_priority_scenarios")
EXPECTED_PRIORITY_OUTPUT_SCHEMA_VERSION = "priority_review_outputs_v5_identity_context_resolution"
CASE_REVIEW_DIR = Path("data/analytics/priority_case_evidence_review")
MINISTRY_LABELS = {
    "019": "고용노동부",
    "075": "보건복지부",
    "102": "중소벤처기업부",
    "162": "과학기술정보통신부",
}
PDF_REVIEW_MINISTRY_CODES = ("019", "075", "162")

ACCOUNT_LABELS = {
    "GENERAL_ACCOUNT": "일반회계",
    "SPECIAL_ACCOUNT": "특별회계",
    "RESPONSIBLE_OPERATION_ACCOUNT": "책임운영기관특별회계",
    "FUND": "기금",
    "NOT_AVAILABLE": "회계유형 미확인",
}
TIER_LABELS = {
    "DATA_REVIEW": "데이터 검증 우선",
    "MULTIPLE_SIGNAL_REVIEW": "복수 신호",
    "STRONG_SINGLE_SIGNAL_REVIEW": "강한 단일 신호",
    "MODERATE_OR_CONTEXT_REVIEW": "주의·맥락 신호",
    "CONTEXT_REVIEW": "맥락 검토",
    "INFORMATION": "정보",
}
REVIEW_INTENSITY_LABELS = {
    "DATA_FIRST": "데이터 먼저",
    "REPEATED_OR_MULTIPLE": "반복·복수 신호",
    "STRONG_SINGLE": "강한 단일 신호",
    "SINGLE_REVIEW": "단일 신호",
    "CONTEXT_REVIEW": "맥락 검토",
    "MONITOR": "신호 미검출·모니터링",
}
REVIEW_GRADE_LABELS = {
    "A": "A 우선 확인",
    "B": "B 원인 확인",
    "C": "C 맥락 확인",
    "D": "D 모니터링",
    "H": "H 데이터 보완",
}
DIAGNOSTIC_LABELS = {
    "DATA_OR_COMPARABILITY_HOLD": "데이터·비교가능성 확인 필요",
    "REPEATED_LOW_EXECUTION_WITH_REPORTED_TARGET_MISS": "반복 저집행과 보고목표 미달 동시 관측",
    "REPEATED_REPORTED_TARGET_MISS_WITH_BUDGET_INCREASE": "연속연도 보고목표 미달 관측과 당해 예산 증가",
    "STRONG_OR_REPEATED_SINGLE_SIGNAL": "강한 또는 반복 단일 신호",
    "LOW_EXECUTION_TARGET_MET": "저집행과 보고목표 달성 동시 관측",
    "LOW_EXECUTION_PERFORMANCE_INFORMATION_MISSING": "저집행과 성과정보 결측 동시 관측",
    "MULTIYEAR_CONTEXT_WITH_SINGLE_YEAR_LOW_EXECUTION": "다년도 맥락에서 단년도 저집행 관측",
    "TARGET_ADEQUACY_REVIEW": "목표 적정성 원문 확인",
    "CONTEXT_OR_SINGLE_SIGNAL_REVIEW": "단일·맥락 신호 확인",
    "SINGLE_SIGNAL_REVIEW": "단일 점검신호 확인",
    "NO_STRUCTURED_SIGNAL_DETECTED": "현재 정의에서 구조화 신호 미검출",
}
SCENARIO_LABELS = {
    "equal": "동일조건 기준",
    "performance_focus": "성과중심",
    "execution_focus": "집행중심",
    "fiscal_impact_adjusted": "재정영향 보정",
}
REASON_LABELS = {
    "PERFORMANCE_BELOW_TARGET": "보고된 목표 미달 (사업효과 판정 아님)",
    "EXECUTION_MANAGEMENT": "집행 설명 필요",
    "BUDGET_PERFORMANCE_MISMATCH": "성과·예산변화 불일치",
    "ACCOUNTING_ADJUSTMENT_CONTEXT": "회계조정 맥락",
    "PROGRAM_STRUCTURE_CONTEXT": "프로그램 구조 맥락",
    "LOW_PERFORMANCE_BUDGET_INCREASE_T1": "보고 목표 미달 뒤 프로그램 전체 T+1 예산 증가",
    "LOW_PERFORMANCE_BUDGET_INCREASE_T2": "보고 목표 미달 뒤 프로그램 전체 T+2 예산 증가",
    "GOOD_PERFORMANCE_BUDGET_DECREASE_T1_CONTEXT": "보고 목표 달성 뒤 프로그램 전체 T+1 예산 감소 맥락",
    "GOOD_PERFORMANCE_BUDGET_DECREASE_T2_CONTEXT": "보고 목표 달성 뒤 프로그램 전체 T+2 예산 감소 맥락",
    "PROGRAM_ACCOUNT_TYPE_MISMATCH_T1": "T+1 프로그램 회계유형 구성 불일치",
    "PROGRAM_ACCOUNT_TYPE_MISMATCH_T2": "T+2 프로그램 회계유형 구성 불일치",
    "DATA_VALIDATION": "데이터 검증",
    "FINANCIAL_LINKAGE_LIMITED": "재정 연결 제한",
    "PROGRAM_MATCH_REVIEW": "프로그램 매칭 검토",
    "STRUCTURAL_PROGRAM_DELETED_TRANSFERRED": "프로그램 이관·삭제 확인",
    "EXTERNAL_MINISTRY_FINANCIAL_PROGRAM": "타부처 소관 재정 확인",
    "NO_REVIEW_SIGNAL": "점검 신호 없음",
}
FINANCIAL_SIGNAL_LABELS = {
    "REPEATED_STRONG_LOW_EXECUTION": "반복 저집행",
    "REPEATED_MODERATE_LOW_EXECUTION": "반복 집행주의",
    "REPEATED_YEAR_END_CONCENTRATION": "반복 연말집중",
    "ACCOUNTING_ADJUSTMENT_PATTERN": "회계조정 맥락",
    "DENOMINATOR_OR_MATCHING_REVIEW": "분모·매칭 검토",
    "BUDGET_RAPID_INCREASE": "예산 급증",
    "BUDGET_RAPID_DECREASE": "예산 급감",
    "PROGRAM_BUDGET_CONCENTRATION": "프로그램 예산집중",
    "MULTIPLE_FINANCIAL_SIGNALS": "복수 재정신호",
    "DATA_VALIDATION_PRIORITY": "데이터 검증 우선",
    "NONE": "추가 재정신호 없음",
}
PROJECT_REVIEW_GROUP_LABELS = {
    "DATA_VALIDATION_FIRST": "데이터 먼저 확인",
    "PROJECT_FINANCIAL_SIGNAL": "세부사업 재정신호",
    "PROGRAM_STRUCTURE_CONTEXT": "프로그램 구조 맥락",
    "LARGE_BUDGET_CONTEXT": "예산규모 맥락",
}
WORK_LANE_LABELS = {
    **REVIEW_INTENSITY_LABELS,
}
WORK_SCOPE_TO_LANE = {label: value for value, label in REVIEW_INTENSITY_LABELS.items()}
WORKFLOW_STEPS = [
    "1. 업무 현황",
    "2. 점검대기열",
    "3. 사업 상세",
    "4. 비교·원문 검수",
]
REVIEW_STATUS_LABELS = {
    "PENDING": "보류",
    "CONFIRMED": "원문과 일치",
    "CORRECTED": "수정 필요",
    "NOT_RESOLVABLE": "현재 문서로 확인 불가",
}
# 사람 판정이 끝나면 열린 검수 큐에서 제외 (보류 PENDING은 남김)
DONE_REVIEW_STATUSES = frozenset({"CONFIRMED", "CORRECTED", "NOT_RESOLVABLE"})
REVIEW_PRIORITY_ORDER = {
    "VALUE_MISMATCH": 1,
    "AMBIGUOUS": 2,
    "PDF_MISSING_MANUAL_PRESENT": 3,
    "OCR_REQUIRED": 4,
    "MATCH_AFTER_CHANGE": 5,
    "EXACT_MATCH": 6,
}
REVIEW_STATUS_GUIDANCE = {
    "VALUE_MISMATCH": "수기값과 PDF값이 다릅니다. 계획·보고·변경표를 모두 보고 맞는 값을 메모에 적으세요.",
    "AMBIGUOUS": "같은 지표명이 여러 프로그램에 있습니다. 프로그램명과 표 위치가 같은 행인지 확인하세요.",
    "PDF_MISSING_MANUAL_PRESENT": "수기값은 있지만 자동 추출 근거가 없습니다. 원문에서 직접 찾고, 없으면 확인 불가로 남기세요.",
    "OCR_REQUIRED": "텍스트 추출을 믿지 말고 렌더링된 페이지의 인쇄값을 직접 읽으세요.",
    "MATCH_AFTER_CHANGE": "별첨6의 변경 전·후 값과 사유가 보고서 값에 이어지는지 표본 확인하세요.",
    "EXACT_MATCH": "자동 대조는 일치했습니다. 필수 검수 대상은 아니며 발표 사례일 때만 표본 확인하세요.",
}


class DashboardDataError(ValueError):
    """대시보드 입력 계약이 깨졌을 때 발생합니다."""


def load_dashboard_data(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """검증된 분석 산출물을 읽고 대시보드 입력 계약을 확인합니다."""
    base = root / DATA_DIR
    filenames = {
        "candidates": "candidate_population.csv",
        "work_queue": "full_population_review_work_queue.csv",
        "program_year_queue": "program_year_review_queue.csv",
        "scores": "scenario_scores.csv",
        "stability": "rank_stability.csv",
        "drilldown": "stable_top5_project_drilldown.csv",
        "project_queue": "full_population_project_review_queue.csv",
        "review_queue": "review_workbench_queue.csv",
        "spearman": "scenario_spearman.csv",
        "overlap": "top_k_overlap.csv",
    }
    required_paths = [base / name for name in (*filenames.values(), "analysis_summary.json")]
    missing = [path for path in required_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "대시보드 입력이 없습니다. 먼저 "
            "`fiscal-analytics analyze-priority-scenarios "
            "--root . --overwrite`를 "
            f"실행하세요: {', '.join(str(path) for path in missing)}"
        )

    data: dict[str, Any] = {
        key: pd.read_csv(base / filename) for key, filename in filenames.items()
    }
    for frame in data.values():
        if "ministry_code" in frame:
            frame["ministry_code"] = frame["ministry_code"].astype("string").str.zfill(3)
        if "program_code" in frame:
            frame["program_code"] = frame["program_code"].astype("string").str.zfill(4)
    for name in ("candidates", "work_queue", "review_queue"):
        data[name]["account_type"] = data[name]["account_type"].fillna("NOT_AVAILABLE")
    data["summary"] = json.loads((base / "analysis_summary.json").read_text(encoding="utf-8"))
    schema_version = data["summary"].get("output_schema_version")
    if schema_version != EXPECTED_PRIORITY_OUTPUT_SCHEMA_VERSION:
        raise DashboardDataError(
            "점검대기열 산출물 스키마가 현재 화면과 다릅니다. "
            f"expected={EXPECTED_PRIORITY_OUTPUT_SCHEMA_VERSION}, actual={schema_version or 'LEGACY'}; "
            "분석 산출물을 최신 코드로 다시 생성하세요."
        )
    case_base = root / CASE_REVIEW_DIR
    case_filenames = {
        "case_review": "selected_cases.csv",
        "case_indicators": "indicator_evidence.csv",
        "case_projects": "project_drilldown.csv",
        "case_t1_direction": "t1_direction_summary.csv",
    }
    case_paths = {key: case_base / filename for key, filename in case_filenames.items()}
    case_summary_path = case_base / "case_validation_summary.json"
    missing_case_paths = [
        path for path in (*case_paths.values(), case_summary_path) if not path.exists()
    ]
    if missing_case_paths:
        raise FileNotFoundError(
            "대표 사례·반례 검수 입력이 없습니다. 먼저 "
            "`fiscal-analytics review-priority-cases --root .`를 실행하세요: "
            f"{', '.join(str(path) for path in missing_case_paths)}"
        )
    for key, path in case_paths.items():
        data[key] = pd.read_csv(path)
        if "ministry_code" in data[key]:
            data[key]["ministry_code"] = data[key]["ministry_code"].astype("string").str.zfill(3)
    data["case_summary"] = json.loads(case_summary_path.read_text(encoding="utf-8"))
    validation_filenames = {
        "robustness_profile": "program_review_robustness_profile.csv",
        "priority_stability": "priority_review_2024_stability.csv",
        "workload_compression": "workload_compression_summary.csv",
        "workload_by_grade": "workload_by_grade_and_budget.csv",
        "temporal_followup": "temporal_followup_summary.csv",
        "ablation_summary": "signal_ablation_summary.csv",
        "sensitivity_scenarios": "grade_sensitivity_scenarios.csv",
        "contract_audit": "review_grade_contract_audit.csv",
        "dominance_audit": "queue_dominance_audit.csv",
        "shadow_reproduction": "shadow_baseline_reproduction.csv",
        "external_validation": "external_validation_cases.csv",
    }
    validation_base = root / "validation"
    missing_validation = [
        validation_base / filename
        for filename in validation_filenames.values()
        if not (validation_base / filename).exists()
    ]
    if missing_validation:
        raise FileNotFoundError(
            "대시보드 검증 입력이 없습니다: "
            + ", ".join(str(path) for path in missing_validation)
        )
    for key, filename in validation_filenames.items():
        data[key] = pd.read_csv(validation_base / filename)

    profile_columns = [
        "program_year_id",
        "production_review_grade",
        "threshold_stable_ab",
        "exact_grade_stable",
        "threshold_boundary",
        "changed_when_execution_removed",
        "changed_when_reported_performance_removed",
        "changed_when_budget_mismatch_removed",
        "changed_when_repetition_removed",
        "signal_dependency_count",
        "signal_dependency_signature",
    ]
    profile = data["robustness_profile"][profile_columns]
    if profile["program_year_id"].duplicated().any():
        raise DashboardDataError("강건성 프로필 program_year_id가 중복되었습니다.")
    queue = data["program_year_queue"].merge(
        profile,
        on="program_year_id",
        how="left",
        validate="one_to_one",
    )
    if queue["production_review_grade"].isna().any():
        raise DashboardDataError("생산 대기열과 강건성 프로필의 키가 일치하지 않습니다.")
    if not queue["review_grade"].eq(queue["production_review_grade"]).all():
        raise DashboardDataError("강건성 프로필의 생산 등급이 기준 대기열과 다릅니다.")
    data["program_year_queue"] = queue.drop(columns="production_review_grade")
    required_columns = {
        "candidates": {
            "candidate_id",
            "field_name",
            "sector_name",
            "program_code",
            "fiscal_year",
            "account_type",
            "performance_program_name",
            "priority_tier",
            "priority_reason",
            "retrospective_feedback_reason",
            "review_candidate",
            "scenario_ranking_eligible",
            "data_validation_signal",
            "account_original_budget",
            "program_total_feedback_complete_t1",
            "program_total_feedback_complete_t2",
            "program_total_budget_change_rate_t1",
            "program_total_budget_change_rate_t2",
            "continuous_project_feedback_complete_t1",
            "continuous_project_feedback_complete_t2",
            "continuous_project_budget_change_rate_t1",
            "continuous_project_budget_change_rate_t2",
        },
        "work_queue": {
            "candidate_id",
            "field_name",
            "sector_name",
            "program_code",
            "fiscal_year",
            "account_type",
            "performance_program_name",
            "priority_tier",
            "priority_reason",
            "retrospective_feedback_reason",
            "review_candidate",
            "scenario_ranking_eligible",
            "data_validation_signal",
            "account_original_budget",
            "signal_score",
            "signal_score_status",
            "size_role_in_work_queue",
            "work_lane",
            "work_item_status",
            "work_queue_order",
            "work_queue_order_within_ministry",
            "work_lane_rank_overall",
            "work_lane_rank_within_ministry",
            "safety_conclusion",
            "review_intensity",
            "next_action",
            "evidence_status",
            "independent_signal_family_count",
            "repeated_signal_family_count",
            "review_grade",
            "reviewability_status",
            "diagnostic_type",
            "signal_families",
            "signal_strength",
            "context_type",
            "context_status",
            "context_source",
            "context_evidence",
            "context_effect",
            "grade_cap_reason",
            "grade_reason_codes",
            "next_review_question",
            "evidence_strength",
            "grade_queue_order",
        },
        "program_year_queue": {
            "program_year_id",
            "program_identity_id",
            "ministry_code",
            "field_name",
            "sector_name",
            "program_code",
            "fiscal_year",
            "performance_program_name",
            "program_original_budget",
            "program_current_budget",
            "program_expenditure",
            "program_execution_rate",
            "program_budget_change_rate",
            "reported_target_status",
            "below_target_count",
            "comparable_rate_count",
            "review_grade",
            "reviewability_status",
            "diagnostic_type",
            "signal_families",
            "grade_trigger_signal_families",
            "signal_strength",
            "context_type",
            "context_status",
            "context_flags",
            "context_only",
            "context_effect",
            "next_review_question",
            "evidence_strength",
            "observed_start_year",
            "observed_end_year",
            "observed_year_count",
            "continuity_status",
            "raw_candidate_ids",
            "review_queue_order_within_year",
        },
        "review_queue": {
            "work_item_id",
            "review_item_type",
            "candidate_id",
            "review_intensity",
            "next_action",
            "workbench_order",
        },
        "scores": {
            "candidate_id",
            "scenario",
            "scenario_score",
            "scenario_rank_average",
        },
        "stability": {
            "candidate_id",
            "mean_scenario_rank",
            "best_scenario_rank",
            "worst_scenario_rank",
            "scenario_rank_range",
            "all_scenario_top_5",
            "all_scenario_top_10",
        },
        "drilldown": {
            "candidate_id",
            "project_id",
            "project_name",
            "activity_name_budget_api",
            "project_original_budget",
            "project_current_budget",
            "project_expenditure",
            "project_remaining_amount",
            "project_carryover",
            "project_unused",
            "execution_rate",
            "budget_share_within_candidate",
            "remaining_share_within_candidate",
            "project_financial_signal_types",
            "project_performance_attributed",
            "program_level_reported_target_context_signal",
            "program_context_grain",
            "program_context_disclaimer",
        },
        "project_queue": {
            "candidate_id",
            "project_id",
            "project_name",
            "activity_name_budget_api",
            "project_review_group",
            "project_review_order_within_candidate",
            "review_sequence_overall",
            "review_sequence_within_ministry",
            "project_original_budget",
            "project_current_budget",
            "project_expenditure",
            "project_remaining_amount",
            "project_carryover",
            "project_unused",
            "execution_rate",
            "budget_share_within_candidate",
            "remaining_share_within_candidate",
            "project_financial_signal_types",
            "project_performance_attributed",
            "program_level_reported_target_context_signal",
            "program_context_grain",
            "program_context_disclaimer",
            "work_lane",
            "work_queue_order",
            "work_queue_order_within_ministry",
        },
    }
    for name, columns in required_columns.items():
        missing_columns = sorted(columns - set(data[name].columns))
        if missing_columns:
            raise DashboardDataError(f"{name} 입력 컬럼 누락: {missing_columns}")
    if data["candidates"]["candidate_id"].duplicated().any():
        raise DashboardDataError("후보표 candidate_id가 중복되었습니다.")
    if data["work_queue"]["candidate_id"].duplicated().any():
        raise DashboardDataError("전체 업무대기열 candidate_id가 중복되었습니다.")
    if set(data["work_queue"]["candidate_id"]) != set(data["candidates"]["candidate_id"]):
        raise DashboardDataError(
            "감사용 업무대기열이 프로그램-연도-회계유형 원시 분석행을 빠짐없이 보존하지 못했습니다."
        )
    if not data["work_queue"]["review_grade"].isin(REVIEW_GRADE_LABELS).all():
        raise DashboardDataError("질문형 점검등급에 정의되지 않은 값이 있습니다.")
    if data["work_queue"]["grade_queue_order"].nunique() != len(data["work_queue"]):
        raise DashboardDataError("질문형 점검등급 대기순서가 중복되었습니다.")
    if data["program_year_queue"]["program_year_id"].duplicated().any():
        raise DashboardDataError("프로그램-연도 대기열 기본키가 중복되었습니다.")
    if data["program_year_queue"].duplicated(["fiscal_year", "program_year_id"]).any():
        raise DashboardDataError("선택연도 대기열에 같은 프로그램이 중복되었습니다.")
    if not data["program_year_queue"]["review_grade"].isin(REVIEW_GRADE_LABELS).all():
        raise DashboardDataError("프로그램-연도 대기열에 정의되지 않은 점검등급이 있습니다.")
    score = pd.to_numeric(data["work_queue"]["signal_score"], errors="coerce")
    incomplete = data["work_queue"]["signal_score_status"].eq("INCOMPLETE_COMPONENTS")
    if score.loc[incomplete].notna().any():
        raise DashboardDataError("구성요소 불완전 행의 신호점수가 null이 아닙니다.")
    if score.loc[data["work_queue"]["signal_score_status"].eq("COMPLETE")].isna().any():
        raise DashboardDataError("COMPLETE 행의 신호점수가 누락되었습니다.")
    if data["stability"]["candidate_id"].duplicated().any():
        raise DashboardDataError("안정성표 candidate_id가 중복되었습니다.")
    if data["scores"].duplicated(["candidate_id", "scenario"]).any():
        raise DashboardDataError("시나리오 점수의 후보-시나리오 키가 중복되었습니다.")
    if data["case_review"]["candidate_id"].duplicated().any():
        raise DashboardDataError("대표 사례표 candidate_id가 중복되었습니다.")
    if set(data["case_review"]["candidate_id"]) - set(data["candidates"]["candidate_id"]):
        raise DashboardDataError("대표 사례표에 후보 모집단 밖의 candidate_id가 있습니다.")
    return data


def _program_count(frame: pd.DataFrame) -> int:
    return len(
        frame.dropna(subset=["program_code"]).drop_duplicates(
            ["ministry_code", "field_name", "sector_name", "program_code"]
        )
    )


def _confirmations_mtime(root: Path = PROJECT_ROOT) -> float:
    path = root / DEFAULT_MANUAL_REVIEW_CONFIRMATIONS_PATH
    return path.stat().st_mtime if path.is_file() else 0.0


@st.cache_data
def load_pdf_review_queue(
    root: Path = PROJECT_ROOT,
    _confirmations_mtime: float = 0.0,
) -> pd.DataFrame:
    """3개 부처 PDF 대조 결과와 현재 사람 검수 상태를 읽습니다.

    `_confirmations_mtime`은 검수 CSV가 바뀌면 캐시를 무효화하기 위한 키입니다.
    """
    del _confirmations_mtime  # cache key only
    frames = []
    for code in PDF_REVIEW_MINISTRY_CODES:
        path = (
            root
            / "data/processed/performance/pdf_reconciliation"
            / f"ministry_code={code}"
            / f"{code}_performance_pdf_reconciliation.parquet"
        )
        if path.exists():
            frames.append(pd.read_parquet(path).astype(object))
    if not frames:
        raise FileNotFoundError("3개 부처 PDF 대조 결과가 없습니다.")
    queue = pd.concat(frames, ignore_index=True).convert_dtypes()
    confirmations_path = root / DEFAULT_MANUAL_REVIEW_CONFIRMATIONS_PATH
    confirmations = load_manual_review_confirmations(confirmations_path)
    relevant = confirmations.loc[
        confirmations["source_indicator_id"].isin(queue["source_indicator_id"])
    ]
    queue = apply_manual_review_confirmations(queue, relevant)
    queue = classify_rows(queue)
    status = queue["review_status"].astype("string").fillna("")
    queue["manual_review_required"] = queue["evidence_acceptance_status"].eq(
        "HUMAN_REVIEW_REQUIRED"
    ) & ~status.isin(DONE_REVIEW_STATUSES)
    queue["review_done"] = status.isin(DONE_REVIEW_STATUSES)
    queue["review_priority_order"] = (
        queue["overall_reconciliation_status"].map(REVIEW_PRIORITY_ORDER).fillna(99)
    )
    return queue


def get_pdf_review_queue(root: Path = PROJECT_ROOT) -> pd.DataFrame:
    """검수 CSV mtime을 넣어 캐시된 PDF 검수 큐를 읽습니다."""
    return load_pdf_review_queue(root, _confirmations_mtime=_confirmations_mtime(root))


@st.cache_data
def render_pdf_page(root: Path, source_file: str, page_number: int) -> bytes:
    """원본 PDF의 1개 페이지를 검수용 PNG로 렌더링합니다."""
    import fitz

    matches = list((root / "data/raw/performance_docs").rglob(source_file))
    if len(matches) != 1:
        raise FileNotFoundError(f"PDF 파일을 하나로 특정할 수 없습니다: {source_file}")
    with fitz.open(matches[0]) as document:
        if not 1 <= page_number <= document.page_count:
            raise ValueError(f"{source_file} 페이지 범위 오류: {page_number}/{document.page_count}")
        pixmap = document[page_number - 1].get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        return pixmap.tobytes("png")


def filter_candidates(
    candidates: pd.DataFrame,
    *,
    scope: str,
    years: list[int],
    account_types: list[str],
    tiers: list[str],
    ministry_codes: list[str] | None = None,
) -> pd.DataFrame:
    """화면 필터만 적용하고 후보·점수 정의는 변경하지 않습니다."""
    if scope in WORK_SCOPE_TO_LANE:
        mask = candidates["work_lane"].eq(WORK_SCOPE_TO_LANE[scope])
    elif scope == "순위 적격 후보":
        mask = candidates["scenario_ranking_eligible"].fillna(False)
    elif scope == "전체 점검 후보":
        mask = candidates["review_candidate"].fillna(False)
    else:
        mask = pd.Series(True, index=candidates.index)
    ministry_mask = (
        candidates["ministry_code"].isin(ministry_codes)
        if ministry_codes is not None
        else pd.Series(True, index=candidates.index)
    )
    return candidates.loc[
        mask
        & ministry_mask
        & candidates["fiscal_year"].isin(years)
        & candidates["account_type"].isin(account_types)
        & candidates["review_intensity"].isin(tiers)
    ].copy()


def _reason_text(value: object) -> str:
    return " · ".join(
        REASON_LABELS.get(item, item) for item in str(value).split(";") if item and item != "nan"
    )


def _format_account(value: object) -> str:
    return ACCOUNT_LABELS.get(str(value), str(value))


def _financial_signal_text(value: object) -> str:
    return " · ".join(
        FINANCIAL_SIGNAL_LABELS.get(item, item)
        for item in str(value).split(";")
        if item and item != "nan"
    )


def _set_korean_font() -> None:
    available = {font.name for font in font_manager.fontManager.ttflist}
    for name in ("Malgun Gothic", "NanumGothic", "AppleGothic", "DejaVu Sans"):
        if name in available:
            plt.rcParams["font.family"] = name
            break
    plt.rcParams["axes.unicode_minus"] = False


def _rank_range_figure(
    stability: pd.DataFrame,
    *,
    within_ministry: bool = False,
) -> plt.Figure:
    _set_korean_font()
    mean_column = "mean_scenario_rank_within_ministry" if within_ministry else "mean_scenario_rank"
    best_column = "best_scenario_rank_within_ministry" if within_ministry else "best_scenario_rank"
    worst_column = (
        "worst_scenario_rank_within_ministry" if within_ministry else "worst_scenario_rank"
    )
    plot = stability.sort_values(mean_column).head(15).sort_values(mean_column, ascending=False)
    labels = (
        plot["ministry_code"].astype(str).map(MINISTRY_LABELS).fillna(plot["ministry_code"])
        + " · "
        + plot["fiscal_year"].astype(str)
        + " "
        + plot["performance_program_name"].astype(str)
        + " / "
        + plot["account_type"].map(ACCOUNT_LABELS).fillna(plot["account_type"])
    )
    fig, ax = plt.subplots(figsize=(11, max(4.5, len(plot) * 0.48)))
    ax.hlines(
        range(len(plot)),
        plot[best_column],
        plot[worst_column],
        color="#9CA3AF",
        linewidth=3,
    )
    ax.scatter(
        plot[mean_column],
        range(len(plot)),
        color="#245A8D",
        edgecolor="#17324D",
        s=58,
        zorder=3,
    )
    ax.set_yticks(range(len(plot)), labels)
    ax.set_xlabel("시나리오 순위 (낮을수록 상위)")
    scope_label = "부처 내부" if within_ministry else "전체 부처"
    ax.set_title(
        f"{scope_label} 후보별 순위 범위",
        loc="left",
        fontweight="bold",
        pad=22,
    )
    ax.text(
        0,
        1.01,
        "점은 평균순위, 선은 네 시나리오의 최상·최하 순위",
        transform=ax.transAxes,
        color="#596579",
    )
    ax.grid(axis="x", color="#E5E7EB")
    ax.spines[["top", "right", "left"]].set_visible(False)
    fig.tight_layout()
    return fig


def _spearman_figure(spearman: pd.DataFrame) -> plt.Figure:
    _set_korean_font()
    scenarios = list(SCENARIO_LABELS)
    matrix = (
        spearman.pivot(
            index="scenario_left",
            columns="scenario_right",
            values="spearman_rank_correlation",
        )
        .loc[scenarios, scenarios]
        .astype(float)
    )
    labels = [SCENARIO_LABELS[name] for name in scenarios]
    fig, ax = plt.subplots(figsize=(7.3, 5.8))
    image = ax.imshow(matrix, cmap="Blues", vmin=0, vmax=1)
    for row in range(len(scenarios)):
        for column in range(len(scenarios)):
            value = matrix.iloc[row, column]
            ax.text(
                column,
                row,
                f"{value:.2f}",
                ha="center",
                va="center",
                color="white" if value >= 0.7 else "#17324D",
                fontweight="bold",
            )
    ax.set_xticks(range(len(labels)), labels, rotation=25, ha="right")
    ax.set_yticks(range(len(labels)), labels)
    ax.set_title("시나리오 간 순위상관", loc="left", fontweight="bold", pad=22)
    ax.text(
        0,
        1.01,
        "전체 순위 적격 후보 기준, 1에 가까울수록 순위가 유사",
        transform=ax.transAxes,
        color="#596579",
    )
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    return fig


def _scenario_top_figure(
    scores: pd.DataFrame,
    scenario: str,
    *,
    within_ministry: bool = False,
) -> plt.Figure:
    _set_korean_font()
    rank_column = (
        "scenario_rank_average_within_ministry" if within_ministry else "scenario_rank_average"
    )
    score_column = "scenario_score_within_ministry" if within_ministry else "scenario_score"
    plot = (
        scores.loc[scores["scenario"].eq(scenario)]
        .sort_values([rank_column, "performance_program_name"])
        .head(10)
        .sort_values(score_column)
    )
    labels = (
        plot["ministry_code"].astype(str).map(MINISTRY_LABELS).fillna(plot["ministry_code"])
        + " · "
        + plot["fiscal_year"].astype(str)
        + " "
        + plot["performance_program_name"].astype(str)
        + " / "
        + plot["account_type"].map(ACCOUNT_LABELS).fillna(plot["account_type"])
    )
    fig, ax = plt.subplots(figsize=(9, max(4.2, len(plot) * 0.48)))
    bars = ax.barh(range(len(plot)), plot[score_column], color="#D3A62C")
    ax.bar_label(bars, fmt="%.3f", padding=4, color="#263445")
    ax.set_yticks(range(len(plot)), labels)
    ax.set_xlabel("탐색 점수 (0~1)")
    ax.set_xlim(0, max(1, float(plot[score_column].max()) * 1.15))
    scope_label = "부처 내부" if within_ministry else "전체 부처"
    ax.set_title(
        f"{scope_label} · {SCENARIO_LABELS.get(scenario, scenario)} 상위 후보",
        loc="left",
        fontweight="bold",
        pad=22,
    )
    ax.text(
        0,
        1.01,
        "점수는 해당 시나리오 안의 정렬용이며 최종 정책점수가 아님",
        transform=ax.transAxes,
        color="#596579",
    )
    ax.grid(axis="x", color="#E5E7EB")
    ax.spines[["top", "right", "left"]].set_visible(False)
    fig.tight_layout()
    return fig


def _project_budget_figure(projects: pd.DataFrame) -> plt.Figure:
    _set_korean_font()
    plot = projects.nlargest(8, "project_original_budget").sort_values("project_original_budget")
    values = plot["project_original_budget"].div(100_000_000)
    fig, ax = plt.subplots(figsize=(8.5, max(4.2, len(plot) * 0.5)))
    bars = ax.barh(range(len(plot)), values, color="#245A8D")
    ax.bar_label(bars, fmt="%.1f", padding=4, color="#263445")
    ax.set_yticks(range(len(plot)), plot["project_name"])
    ax.set_xlabel("본예산(억원)")
    ax.set_title("세부사업 본예산 상위", loc="left", fontweight="bold", pad=22)
    ax.text(
        0,
        1.01,
        f"선택 후보의 세부사업 {len(projects)}개 중 상위 8개",
        transform=ax.transAxes,
        color="#596579",
    )
    ax.set_xlim(0, max(1, float(values.max()) * 1.18))
    ax.grid(axis="x", color="#E5E7EB")
    ax.spines[["top", "right", "left"]].set_visible(False)
    fig.tight_layout()
    return fig


def _project_table_view(projects: pd.DataFrame) -> pd.DataFrame:
    table = projects.copy()
    table["검토유형"] = table["project_review_group"].map(PROJECT_REVIEW_GROUP_LABELS)
    table["본예산(억원)"] = table["project_original_budget"].div(100_000_000)
    table["예산비중"] = table["budget_share_within_candidate"]
    table["집행률"] = table["execution_rate"]
    table["잔액(억원)"] = table["project_remaining_amount"].div(100_000_000)
    table["잔액기여"] = table["remaining_share_within_candidate"]
    table["이월(억원)"] = table["project_carryover"].div(100_000_000)
    table["불용(억원)"] = table["project_unused"].div(100_000_000)
    table["재정신호"] = table["project_financial_signal_types"].map(_financial_signal_text)
    return table[
        [
            "project_review_order_within_candidate",
            "검토유형",
            "project_name",
            "activity_name_budget_api",
            "본예산(억원)",
            "예산비중",
            "집행률",
            "잔액(억원)",
            "잔액기여",
            "이월(억원)",
            "불용(억원)",
            "재정신호",
        ]
    ].rename(
        columns={
            "project_review_order_within_candidate": "검토순서",
            "project_name": "세부사업",
            "activity_name_budget_api": "단위사업",
        }
    )


def _table_view(frame: pd.DataFrame) -> pd.DataFrame:
    table = frame.copy()
    table["부처"] = (
        table["ministry_code"].astype(str).map(MINISTRY_LABELS).fillna(table["ministry_code"])
    )
    table["회계유형"] = table["account_type"].map(ACCOUNT_LABELS).fillna(table["account_type"])
    table["점검강도"] = (
        table["review_intensity"].map(REVIEW_INTENSITY_LABELS).fillna(table["review_intensity"])
    )
    table["점검근거"] = table["priority_reason"].map(_reason_text)
    if "work_lane" in table:
        table["업무레인"] = table["work_lane"].map(WORK_LANE_LABELS).fillna(table["work_lane"])
    table["본예산(억원)"] = pd.to_numeric(table["account_original_budget"], errors="coerce").div(
        100_000_000
    )
    rename = {
        "fiscal_year": "연도",
        "performance_program_name": "프로그램",
        "work_queue_order": "업무순서",
        "work_lane_rank_overall": "레인내순서",
        "next_action": "다음 행동",
        "independent_signal_family_count": "독립신호수",
        "repeated_signal_family_count": "반복신호수",
        "evidence_status": "근거상태",
    }
    table = table.rename(columns=rename)
    columns = [
        "부처",
        "연도",
        "프로그램",
        "회계유형",
        "점검강도",
        "점검근거",
        "다음 행동",
        "독립신호수",
        "반복신호수",
        "근거상태",
        "본예산(억원)",
    ]
    if "업무순서" in table:
        columns.insert(0, "업무순서")
    if "업무레인" in table:
        columns.insert(2, "업무레인")
    for optional in ("레인내순서",):
        if optional in table:
            columns.append(optional)
    return table[columns]


def _workbench_table(frame: pd.DataFrame) -> pd.DataFrame:
    table = frame.copy()
    table["업무순서"] = table["workbench_order"]
    table["업무유형"] = table["review_item_type"].map(
        {
            "PROGRAM_DATA_TASK": "프로그램 데이터 확인",
            "DETAILED_PROJECT_REVIEW": "세부사업 점검",
        }
    )
    table["부처"] = table["ministry_code"].map(MINISTRY_LABELS).fillna(table["ministry_code"])
    table["회계유형"] = table["account_type"].map(ACCOUNT_LABELS).fillna(table["account_type"])
    table["점검강도"] = (
        table["review_intensity"].map(REVIEW_INTENSITY_LABELS).fillna(table["review_intensity"])
    )
    table["프로그램"] = table["performance_program_name"]
    table["세부사업"] = table["project_name"].fillna("데이터 확인 후 연결")
    table["다음 행동"] = table["next_action"]
    table["본예산(억원)"] = pd.to_numeric(table["work_item_budget"], errors="coerce").div(
        100_000_000
    )
    return table[
        [
            "업무순서",
            "업무유형",
            "부처",
            "fiscal_year",
            "프로그램",
            "세부사업",
            "회계유형",
            "점검강도",
            "다음 행동",
            "본예산(억원)",
        ]
    ].rename(columns={"fiscal_year": "연도"})


def _data_review_table(frame: pd.DataFrame) -> pd.DataFrame:
    table = _table_view(frame)
    issues = pd.DataFrame(index=frame.index)
    issues["재정신호 미연결"] = frame["financial_signal_join_status"].ne("both")
    issues["회계별 본예산 불일치"] = frame["financial_signal_join_status"].eq("both") & ~frame[
        "financial_signal_budget_reconciled"
    ].fillna(False)
    issues["성과·재정 공동분석 제한"] = frame["analysis_status"].ne("JOINT_ANALYSIS")
    issue_text = issues.apply(
        lambda row: " · ".join(row.index[row].tolist()) or "세부사업 데이터 품질 신호",
        axis=1,
    )
    table["확인할 내용"] = issue_text.to_numpy()
    table["본예산 차이(억원)"] = (
        pd.to_numeric(
            frame["financial_signal_budget_difference"],
            errors="coerce",
        )
        .div(100_000_000)
        .to_numpy()
    )
    columns = [
        "부처",
        "연도",
        "프로그램",
        "회계유형",
        "확인할 내용",
        "본예산 차이(억원)",
        "점검근거",
    ]
    return table[columns]


def _review_worklist(frame: pd.DataFrame) -> pd.DataFrame:
    """데이터 검증행을 실제 확인할 프로그램 단위 작업으로 묶습니다."""
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "상태",
                "부처",
                "프로그램",
                "대상연도",
                "영향행",
                "확인할 문제",
                "다음 행동",
                "순위 영향",
            ]
        )

    review = frame.copy()
    review["_program_key"] = review["program_name_normalized"].fillna(
        review["performance_program_name"]
    )

    def classify(row: pd.Series) -> tuple[str, str, str]:
        if row["analysis_status"] == "STRUCTURAL_PROGRAM_DELETED_TRANSFERRED":
            return (
                "확인 완료",
                "프로그램 이관·삭제",
                "순위 제외를 유지하고 구조변경 근거만 보존",
            )
        if row["analysis_status"] == "EXTERNAL_MINISTRY_FINANCIAL_PROGRAM":
            return (
                "확인 완료",
                "타부처 소관 재정 프로그램",
                "과기정통부 순위 제외를 유지하고 타부처 소관 근거 보존",
            )
        if row["analysis_status"] == "PROGRAM_MATCH_REVIEW":
            issue = (
                "프로그램 코드 후보가 여러 개"
                if row["program_match_status"] == "MANUAL_REVIEW_MULTIPLE_MATCHES"
                else "프로그램 코드 후보가 없음"
            )
            return (
                "확인 필요",
                issue,
                "해당 연도 성과계획서 대상사업 표에서 공식 프로그램코드 확인",
            )
        if row["analysis_status"] == "FINANCIAL_LINKAGE_LIMITED":
            return (
                "확인 필요",
                "성과 프로그램 일부 재정행만 분석 가능",
                "제외 세부사업의 마스킹·중복·분모 누락 근거 확인",
            )
        return (
            "확인 필요",
            "세부사업 재정 데이터 검증 신호",
            "분모·매칭·집행 신호의 원인을 세부사업 자료에서 확인",
        )

    review[["상태", "확인할 문제", "다음 행동"]] = review.apply(
        classify,
        axis=1,
        result_type="expand",
    )
    rows = []
    for (_, program_key, status, issue, action), group in review.groupby(
        ["ministry_code", "_program_key", "상태", "확인할 문제", "다음 행동"],
        sort=False,
        dropna=False,
    ):
        latest = group.sort_values("fiscal_year").iloc[-1]
        rows.append(
            {
                "상태": status,
                "부처": MINISTRY_LABELS.get(str(latest["ministry_code"]), latest["ministry_code"]),
                "프로그램": latest["performance_program_name"],
                "대상연도": ", ".join(
                    str(year) for year in sorted(group["fiscal_year"].dropna().astype(int).unique())
                ),
                "영향행": len(group),
                "확인할 문제": issue,
                "다음 행동": action,
                "순위 영향": "현재 순위 제외",
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["상태", "부처", "프로그램"],
        ascending=[False, True, True],
        ignore_index=True,
    )


def _component_summary(label: str, value: object) -> tuple[str, str]:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "자료 없음", "이 값이 없어 현재 순위 비교에서 제한될 수 있습니다."
    numeric = float(numeric)
    if label == "성과":
        return f"{numeric:.0%}", "비교 가능한 성과지표 중 목표 미달 비중"
    if label == "집행":
        level = "강한 확인 필요" if numeric >= 0.75 else "확인 필요" if numeric > 0 else "신호 없음"
        return level, f"현재·반복 집행 신호 강도 {numeric:.2f}"
    if label == "예산 흐름":
        level = "확인 필요" if numeric > 0 else "신호 없음"
        return level, f"성과와 예산 증감의 불일치 정도 {numeric:.2f}"
    upper_share = max(1, round((1 - numeric) * 100))
    return f"상위 약 {upper_share}%", "같은 비교집단에서의 본예산 규모"


MAIN_TABS = ("개요", "점검 대기열", "프로그램 상세", "분석·검증")
PENDING_MAIN_TAB_KEY = "pending_main_tab"
QUEUE_FILTER_GRADES = {
    "우선 확인 A+B": ("A", "B"),
    "맥락 확인 C": ("C",),
    "데이터 보완 H": ("H",),
    "모니터링 D": ("D",),
    "전체": ("A", "B", "C", "D", "H"),
}
EVIDENCE_STRENGTH_LABELS = {
    "STRONG": "근거 충분",
    "LIMITED": "일부 확인 필요",
    "BLOCKED": "판단 자료 부족",
}
CONTEXT_TYPE_LABELS = {
    "DEMAND_DRIVEN": "수요연동 가능성",
    "CONTINGENCY": "수요발생형 가능성",
    "MULTIYEAR_CAPITAL": "다년도 사업",
    "DELAYED_OUTCOME": "성과시차 가능성",
    "YEAR_END_CONCENTRATED": "연말집중 패턴",
    "ROUTINE_RECURRENT": "반복·경상 사업",
    "UNKNOWN_TYPE": "사업특성 미확인",
}
EXTERNAL_VALIDATION_COUNTS = {"부합": 8, "반박": 2, "근거 부족": 2}


def _request_main_tab(tab: str) -> None:
    """segmented_control(key=main_tab) 생성 전에만 탭을 바꿀 수 있어, 다음 렌더용으로 예약합니다."""
    if tab not in MAIN_TABS:
        raise ValueError(f"알 수 없는 화면 탭: {tab}")
    st.session_state[PENDING_MAIN_TAB_KEY] = tab


def _apply_pending_main_tab() -> None:
    pending = st.session_state.pop(PENDING_MAIN_TAB_KEY, None)
    if pending in MAIN_TABS:
        st.session_state["main_tab"] = pending
    elif st.session_state.get("main_tab") not in MAIN_TABS:
        st.session_state["main_tab"] = "개요"


def _clear_review_focus() -> None:
    st.session_state.pop("review_program_filter", None)
    st.session_state.pop("review_ministry_filter", None)


def stable_program_summary(
    candidates: pd.DataFrame,
    stability: pd.DataFrame,
) -> pd.DataFrame:
    """전 시나리오 Top 5 행을 프로그램 단위의 읽기 쉬운 요약으로 묶습니다."""
    stable = candidates.merge(
        stability.loc[
            stability["all_scenario_top_5"].fillna(False),
            ["candidate_id", "mean_scenario_rank"],
        ],
        on="candidate_id",
        how="inner",
        validate="one_to_one",
    )
    rows: list[dict[str, Any]] = []
    for (ministry_code, program_code, program_name), group in stable.groupby(
        ["ministry_code", "program_code", "performance_program_name"],
        sort=False,
        dropna=False,
    ):
        observations = ", ".join(
            f"{int(row.fiscal_year)} {_format_account(row.account_type)}"
            for row in group.sort_values(["fiscal_year", "account_type"]).itertuples()
        )
        reason_codes = {
            code
            for value in group["priority_reason"]
            for code in str(value).split(";")
            if code and code != "nan"
        }
        rows.append(
            {
                "ministry_code": ministry_code,
                "program_code": program_code,
                "program_name": program_name,
                "stable_row_count": len(group),
                "observations": observations,
                "reasons": " · ".join(
                    REASON_LABELS.get(code, code) for code in sorted(reason_codes)
                ),
                "best_mean_rank": group["mean_scenario_rank"].min(),
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "ministry_code",
                "program_code",
                "program_name",
                "stable_row_count",
                "observations",
                "reasons",
                "best_mean_rank",
            ]
        )
    return pd.DataFrame(rows).sort_values(
        ["best_mean_rank", "program_name"],
        ignore_index=True,
    )


def review_page_specs(row: pd.Series) -> list[tuple[str, str, int]]:
    """검수행에서 실제로 열 수 있는 PDF 파일·쪽 목록만 만듭니다."""
    candidates = (
        ("계획서", "plan_source_file", "plan_split_pdf_page"),
        ("보고서", "report_source_file", "report_split_pdf_page"),
        (
            "성과계획 변경표",
            "documented_change_source_file",
            "documented_change_split_pdf_page",
        ),
    )
    result: list[tuple[str, str, int]] = []
    seen: set[tuple[str, int]] = set()
    for label, file_column, page_column in candidates:
        source_file = row.get(file_column)
        page = pd.to_numeric(pd.Series([row.get(page_column)]), errors="coerce").iloc[0]
        if pd.isna(source_file) or not str(source_file).strip() or pd.isna(page):
            continue
        key = (str(source_file), int(page))
        if key not in seen:
            result.append((label, *key))
            seen.add(key)
    return result


def _plain_lane_help(lane: object) -> str:
    return {
        "DATA_FIRST": "숫자 해석 전에 연결·분모·매칭을 먼저 확인해야 하는 행",
        "REPEATED_OR_MULTIPLE": "문제가 여러 해 또는 여러 종류로 겹침 → 우선 볼 후보",
        "STRONG_SINGLE": "강한 단일 집행 신호",
        "SINGLE_REVIEW": "독립 신호가 하나 있어 근거를 확인할 후보",
        "CONTEXT_REVIEW": "회계조정·구조·예산방향 등 맥락 확인",
        "MONITOR": "지금 트리거가 거의 없음 (안전·정상 판정 아님)",
    }.get(str(lane), str(lane))


def _as_int(value: object) -> int | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return None
    return int(numeric)


def _signal_composition_label(row: pd.Series | object) -> str:
    """대기열용: 점수% 대신 개수·유무로 구성을 보여 줍니다."""
    getter = (
        row.get
        if isinstance(row, pd.Series)
        else lambda key, default=None: getattr(row, key, default)
    )
    below = _as_int(getter("below_target_count"))
    comparable = _as_int(getter("comparable_rate_count"))
    if below is None or comparable is None:
        perf = "성과 —"
    else:
        perf = f"보고 목표 미달 {below}/{comparable}개"

    rate = pd.to_numeric(
        pd.Series([getter("program_execution_rate", getter("account_execution_rate"))]),
        errors="coerce",
    ).iloc[0]
    if pd.isna(rate):
        exec_label = "집행률 —"
    else:
        exec_label = f"집행률 {float(rate):.0%}"
    if bool(getter("repeated_execution_signal", getter("repeated_low_execution_signal"))):
        exec_label += "·반복"

    if bool(getter("budget_mismatch_signal")):
        mismatch = "불일치 있음"
    elif pd.isna(
        pd.to_numeric(pd.Series([getter("budget_performance_mismatch")]), errors="coerce").iloc[0]
    ):
        mismatch = "불일치 —"
    else:
        mismatch = "불일치 없음"
    return f"{perf} · {exec_label} · {mismatch}"


def _plain_signal_cards(row: pd.Series) -> list[tuple[str, str, str]]:
    """프로그램 상세용: 보고목표·집행·예산변화의 원시값과 짧은 해석."""
    below = _as_int(row.get("below_target_count"))
    comparable = _as_int(row.get("comparable_rate_count"))
    if below is None or comparable is None:
        perf_value, perf_help = "자료 없음", "비교 가능한 보고지표 수를 확인하지 못했습니다."
    else:
        perf_value = f"{below} / {comparable}개"
        perf_help = f"비교 가능 지표 {comparable}개 중 {below}개가 보고목표 미달입니다."

    rate = pd.to_numeric(
        row.get("program_execution_rate", row.get("account_execution_rate")), errors="coerce"
    )
    exec_bits: list[str] = []
    if bool(row.get("repeated_low_execution_signal", row.get("repeated_execution_signal"))):
        exec_bits.append("이전 관측연도에도 저집행 신호가 있습니다.")
    if pd.isna(rate):
        exec_value = "자료 없음"
    else:
        exec_value = f"{float(rate):.0%}"
    exec_help = " ".join(exec_bits) if exec_bits else "선택연도의 프로그램 총집행률입니다."

    budget_change = pd.to_numeric(row.get("program_budget_change_rate"), errors="coerce")
    if pd.isna(budget_change):
        budget_value = "비교 불가"
        budget_help = "직전 연도와 비교할 수 있는 본예산이 없습니다."
    else:
        budget_value = f"{float(budget_change):+.1%}"
        budget_help = "직전 관측연도 대비 프로그램 본예산 변화입니다."
    return [
        ("보고목표", perf_value, perf_help),
        ("집행", exec_value, exec_help),
        ("예산 변화", budget_value, budget_help),
    ]


def _context_badge_text(row: pd.Series) -> str:
    return CONTEXT_TYPE_LABELS.get(str(row.get("context_type")), "사업특성 미확인")


def _evidence_strength_text(value: object) -> str:
    return EVIDENCE_STRENGTH_LABELS.get(str(value), "일부 확인 필요")


def _queue_simple_table(frame: pd.DataFrame) -> pd.DataFrame:
    if "program_year_id" in frame:
        table = frame.sort_values("review_queue_order_within_year").copy()
        budget_column = "program_original_budget"
    else:
        table = frame.sort_values("grade_queue_order").copy()
        budget_column = "account_original_budget"
    table["부처"] = table["ministry_code"].map(MINISTRY_LABELS).fillna(table["ministry_code"])
    table["프로그램"] = table["performance_program_name"]
    table["등급"] = table["review_grade"].map(REVIEW_GRADE_LABELS)
    table["왜 확인하나"] = (
        table["diagnostic_type"].map(DIAGNOSTIC_LABELS).fillna(table["diagnostic_type"])
    )
    table["핵심 근거"] = [_signal_composition_label(row) for _, row in table.iterrows()]
    table["다음 확인"] = table["next_review_question"]
    if "threshold_stable_ab" in table:
        table["안정성"] = "—"
        ab = table["review_grade"].isin(["A", "B"])
        table.loc[ab & table["threshold_stable_ab"].fillna(False), "안정성"] = "임계값 안정"
        table.loc[ab & table["threshold_boundary"].fillna(False), "안정성"] = "경계 사례"
    else:
        table["안정성"] = "—"
    table["본예산(억원·참고)"] = pd.to_numeric(table[budget_column], errors="coerce").div(
        100_000_000
    )
    return table[
        [
            "등급",
            "부처",
            "프로그램",
            "왜 확인하나",
            "핵심 근거",
            "안정성",
            "다음 확인",
            "본예산(억원·참고)",
        ]
    ]


def _signal_dependency_notes(row: pd.Series) -> list[str]:
    notes: list[str] = []
    if bool(row.get("changed_when_reported_performance_removed")) and str(
        row.get("review_grade")
    ) in {"A", "B"}:
        notes.append("성과신호가 없으면 우선 확인군 이탈")
    if bool(row.get("changed_when_execution_removed")):
        notes.append("집행신호에 민감")
    if bool(row.get("changed_when_repetition_removed")):
        notes.append("반복성 제거 시 등급 완화")
    if bool(row.get("changed_when_budget_mismatch_removed")):
        notes.append("예산괴리는 세부등급·진단 조정에 기여")
    return notes or ["검토한 네 신호 제거에서 등급 변화 없음"]


def _multiple_reason_facts(row: pd.Series) -> list[str]:
    facts: list[str] = []
    if bool(row.get("repeated_low_execution_signal")) and bool(row.get("performance_signal")):
        facts.append("반복 저집행과 보고목표 미달이 함께 관측됨")
    if bool(row.get("reported_target_miss_consecutive")) and bool(
        row.get("budget_increase_context_signal")
    ):
        facts.append("연속연도 보고목표 미달과 예산 증가가 함께 관측됨")
    return facts


def _render_program_year_detail(
    row: pd.Series,
    program_queue: pd.DataFrame,
    account_queue: pd.DataFrame,
) -> None:
    grade = str(row["review_grade"])
    ministry = MINISTRY_LABELS.get(str(row["ministry_code"]), row["ministry_code"])
    st.markdown(f"### {row['performance_program_name']}")
    st.caption(
        f"{ministry} · {int(row['fiscal_year'])}년 · "
        f"관측기간 {int(row['observed_start_year'])}–{int(row['observed_end_year'])}년"
    )
    st.badge(REVIEW_GRADE_LABELS.get(grade, grade), color="orange" if grade == "H" else "blue")
    if grade in {"A", "B"}:
        stability_label = "임계값 안정" if bool(row.get("threshold_stable_ab")) else "경계 사례"
        st.badge(stability_label, color="green" if stability_label == "임계값 안정" else "orange")
        st.caption("안정성 배지는 강건성 설명용이며 생산등급이나 대기열 순서를 바꾸지 않습니다.")
    diagnosis = DIAGNOSTIC_LABELS.get(str(row.get("diagnostic_type")), row.get("diagnostic_type"))
    st.markdown(f"**진단:** {diagnosis}")
    st.info(
        f"**다음 확인:** {row.get('next_review_question')}", icon=":material/help:"
    )
    cards = _plain_signal_cards(row)
    for column, (title, value, help_text) in zip(
        st.columns(3, border=True), cards, strict=True
    ):
        column.metric(title, value)
        column.caption(help_text)
    with st.container(horizontal=True):
        st.badge(_context_badge_text(row), color="gray")
        st.badge(_evidence_strength_text(row.get("evidence_strength")), color="blue")
    st.markdown("#### 신호 의존성 요약")
    st.markdown("\n".join(f"- {note}" for note in _signal_dependency_notes(row)))
    facts = _multiple_reason_facts(row)
    if facts:
        st.markdown("#### 동시 관측 사실")
        st.markdown("\n".join(f"- {fact}" for fact in facts))
    budget = pd.to_numeric(row.get("program_original_budget"), errors="coerce")
    st.metric(
        "재정영향 참고값",
        "—" if pd.isna(budget) else f"본예산 {float(budget) / 100_000_000:,.1f}억원",
        help="점검등급과 별도로 보는 규모 참고값이며 등급 판정값이 아닙니다.",
    )
    if grade == "H":
        hold_labels = {
            "MISSING_PROGRAM_CODE_UNKNOWN_CONTINUITY": "프로그램코드가 없어 연도 간 동일성을 확정할 수 없음",
            "SAME_CODE_NAME_MULTIPLE_FIELD_SECTOR": "같은 코드·이름이 복수 분야·부문에 있어 집계 범위를 확정할 수 없음",
        }
        hold_reason = hold_labels.get(
            str(row.get("identity_resolution_reason")), "비교가능성 또는 상위 데이터 품질 확인 필요"
        )
        st.warning(f"**판단 보류 사유:** {hold_reason}", icon=":material/pending:")

    history = program_queue.loc[
        program_queue["program_identity_id"].eq(row["program_identity_id"])
    ].sort_values("fiscal_year")
    st.markdown("#### 연도별 관측")
    target_labels = {
        "ALL_COMPARABLE_BELOW_TARGET": "보고목표 미달",
        "ALL_COMPARABLE_AT_OR_ABOVE_TARGET": "보고목표 달성",
        "MIXED_COMPARABLE": "보고목표 혼합",
        "NO_COMPARABLE_RATE": "비교 자료 없음",
    }
    with st.container(horizontal=True):
        for observation in history.itertuples():
            target = target_labels.get(str(observation.reported_target_status), "보고목표 확인 필요")
            st.badge(
                f"{int(observation.fiscal_year)} · "
                f"{REVIEW_GRADE_LABELS.get(str(observation.review_grade), observation.review_grade)} · "
                f"{target}",
                color="gray" if str(observation.review_grade) == "D" else "blue",
            )
    chart_left, chart_right = st.columns(2)
    execution_history = history[["fiscal_year", "program_execution_rate"]].rename(
        columns={"fiscal_year": "연도", "program_execution_rate": "집행률"}
    )
    budget_history = history[["fiscal_year", "program_original_budget"]].rename(
        columns={"fiscal_year": "연도", "program_original_budget": "본예산(억원)"}
    )
    budget_history["본예산(억원)"] = pd.to_numeric(
        budget_history["본예산(억원)"], errors="coerce"
    ).div(100_000_000)
    with chart_left:
        st.caption("연도별 집행률")
        st.line_chart(execution_history, x="연도", y="집행률")
    with chart_right:
        st.caption("연도별 본예산")
        st.bar_chart(budget_history, x="연도", y="본예산(억원)")

    raw_ids = set(json.loads(str(row["raw_candidate_ids"])))
    accounts = account_queue.loc[account_queue["candidate_id"].isin(raw_ids)].copy()
    account_view = accounts[
        [
            "account_type",
            "account_original_budget",
            "account_current_budget",
            "account_settlement_expenditure",
            "account_execution_rate",
            "review_grade",
            "diagnostic_type",
        ]
    ].rename(
        columns={
            "account_type": "회계유형",
            "account_original_budget": "본예산",
            "account_current_budget": "예산현액",
            "account_settlement_expenditure": "지출액",
            "account_execution_rate": "집행률",
            "review_grade": "원시행 등급",
            "diagnostic_type": "원시행 진단",
        }
    )
    account_view["회계유형"] = (
        account_view["회계유형"].map(ACCOUNT_LABELS).fillna(account_view["회계유형"])
    )
    account_view["원시행 등급"] = account_view["원시행 등급"].map(REVIEW_GRADE_LABELS)
    account_view["원시행 진단"] = account_view["원시행 진단"].map(DIAGNOSTIC_LABELS)
    with st.expander("회계유형별 감사 데이터 보기", icon=":material/table_view:"):
        st.caption("감사·드릴다운용 원시 분석행이며 최종 점검대상 수로 세지 않습니다.")
        st.dataframe(
            account_view,
            hide_index=True,
            column_config={
                "본예산": st.column_config.NumberColumn(format="%,.0f"),
                "예산현액": st.column_config.NumberColumn(format="%,.0f"),
                "지출액": st.column_config.NumberColumn(format="%,.0f"),
                "집행률": st.column_config.NumberColumn(format="percent"),
            },
        )
        st.caption(
            f"내부 프로그램-연도 ID: {row['program_year_id']} · "
            f"원시행 ID: {', '.join(sorted(raw_ids))}"
        )


def _signal_checklist(row: pd.Series) -> list[str]:
    checks: list[str] = []
    if bool(row.get("data_validation_signal")):
        checks.append("데이터·연결 확인이 먼저 필요")
    if bool(row.get("performance_signal")):
        checks.append("보고된 목표 미달 신호 (사업효과 판정 아님)")
    if bool(row.get("execution_signal")) or bool(row.get("execution_review_signal")):
        checks.append("집행 설명 필요 신호")
    if bool(row.get("budget_mismatch_signal")):
        checks.append("성과와 예산변화 불일치")
    if bool(row.get("accounting_context_signal")):
        checks.append("회계조정 맥락")
    if bool(row.get("structure_context_signal")):
        checks.append("프로그램 구조·집중도 맥락")
    if not checks:
        checks.append("현재 표시할 독립 트리거가 거의 없음 (정상 판정 아님)")
    return checks


def _retrospective_feedback_checklist(row: pd.Series) -> list[str]:
    checks: list[str] = []
    if bool(row.get("low_performance_budget_increase_t1")) or bool(
        row.get("low_performance_budget_increase_t2")
    ):
        checks.append("보고 목표 미달 뒤 후속 예산 증가")
    if bool(row.get("good_performance_budget_decrease_t1")) or bool(
        row.get("good_performance_budget_decrease_t2")
    ):
        checks.append("보고 목표 달성 뒤 후속 예산 감소")
    if bool(row.get("retrospective_feedback_data_quality_signal")):
        checks.append("후속연도 프로그램 회계유형 구성 확인 필요")
    return checks


def _render_candidate_detail(row: pd.Series, project_queue: pd.DataFrame) -> None:
    lane = str(row["review_intensity"])
    grade = str(row["review_grade"])
    st.markdown(
        f"### {MINISTRY_LABELS.get(str(row['ministry_code']), row['ministry_code'])} · "
        f"{int(row['fiscal_year'])} · {row['performance_program_name']}"
    )
    st.caption(
        f"{_format_account(row['account_type'])} · "
        f"검토 순서 {int(row['grade_queue_order'])} · "
        f"{REVIEW_GRADE_LABELS.get(grade, grade)}"
    )
    st.info(
        f"{DIAGNOSTIC_LABELS.get(str(row.get('diagnostic_type')), row.get('diagnostic_type'))}  \n"
        f"다음 확인질문: {row.get('next_review_question')}",
        icon=":material/flag:",
    )
    st.caption(
        "이 등급은 사업 성과평가·감액등급이 아니라 프로그램 원문 검토 순서입니다. "
        f"사업특성: {row.get('context_flags', 'NONE')} / {row.get('context_type')} / "
        f"{row.get('context_status')} / {row.get('context_effect')}"
    )
    if row.get("signal_score_status") == "INCOMPLETE_COMPONENTS":
        st.warning(
            "신호 구성요소가 불완전하여 점수 계산을 보류했습니다. null을 0점이나 정상으로 대체하지 않습니다."
        )

    st.markdown("**왜 이 대기열에 있나**")
    for item in _signal_checklist(row):
        st.markdown(f"- {item}")
    st.caption(f"점검 근거 코드: {_reason_text(row.get('priority_reason'))}")
    retrospective = _retrospective_feedback_checklist(row)
    if retrospective:
        st.markdown("**사후 환류 맥락** (현재 대기레인·순서에는 사용하지 않음)")
        for item in retrospective:
            st.markdown(f"- {item}")
        st.caption(f"사후 환류 코드: {_reason_text(row.get('retrospective_feedback_reason'))}")

    budget = pd.to_numeric(row.get("account_original_budget"), errors="coerce")

    def feedback_label(horizon: str) -> str:
        rate = pd.to_numeric(
            row.get(f"program_total_budget_change_rate_{horizon}"),
            errors="coerce",
        )
        if pd.isna(rate):
            return "비교 제한"
        return f"{float(rate):+.1%}"

    st.markdown("**숫자로 보는 신호** (대기 순서가 아닙니다)")
    cards = _plain_signal_cards(row)
    columns = st.columns(4)
    for column, (title, value, help_text) in zip(columns, cards, strict=True):
        column.metric(title, value, help=help_text)
        column.caption(help_text)

    m1, m2, m3 = st.columns(3)
    m1.metric("사후 환류 T+2", feedback_label("t2"))
    m2.metric("사후 환류 T+1", feedback_label("t1"))
    m3.metric(
        "본예산 (참고)",
        "—" if pd.isna(budget) else f"{float(budget) / 100_000_000:,.1f}억",
    )
    st.caption("환류는 회고 참고값이며 현재 대기레인·순서와 위험 점수에 사용하지 않습니다.")
    if str(row.get("account_type")) == "FUND":
        st.warning(
            "기금·융자는 일반회계와 같은 예산 크기로 서열 비교하지 않습니다.",
            icon=":material/warning:",
        )

    with st.expander("후보로 올리기 전 최소 확인 5가지", icon=":material/checklist:"):
        st.markdown(
            """
1. 같은 사업·같은 시계열인가  
2. 성과자료가 믿을 만한가  
3. 예산·집행을 같은 단위로 비교할 수 있는가  
4. 회계·사업구조가 바뀌지 않았는가  
5. 신호를 설명하거나 반박할 공식 근거가 있는가  

미확인이 크면 **추가 확인 후보**로 낮춥니다. 실패·삭감 자동 판정이 아닙니다.
"""
        )

    projects = project_queue.loc[project_queue["candidate_id"].eq(row["candidate_id"])].copy()
    st.markdown("**세부사업에서 원인 보기** (프로그램 성과를 세부사업에 그대로 씌우지 않음)")
    if projects.empty:
        if lane == "DATA_FIRST":
            st.info("데이터 확인을 마친 뒤 세부사업 목록이 연결됩니다.")
        else:
            st.caption("연결된 세부사업 검토행이 없습니다.")
    else:
        st.dataframe(
            _project_table_view(projects.sort_values("project_review_order_within_candidate")),
            hide_index=True,
            width="stretch",
            height=360,
            column_config={
                "본예산(억원)": st.column_config.NumberColumn(format="%.1f"),
                "예산비중": st.column_config.NumberColumn(format="percent"),
                "집행률": st.column_config.NumberColumn(format="percent"),
                "잔액(억원)": st.column_config.NumberColumn(format="%.1f"),
                "잔액기여": st.column_config.NumberColumn(format="percent"),
                "이월(억원)": st.column_config.NumberColumn(format="%.1f"),
                "불용(억원)": st.column_config.NumberColumn(format="%.1f"),
            },
        )

    pdf_ok = str(row["ministry_code"]) in PDF_REVIEW_MINISTRY_CODES
    if st.button(
        "이 프로그램 원문(PDF) 검수로 이동",
        icon=":material/description:",
        disabled=not pdf_ok,
        width="stretch",
        key=f"goto_pdf_{row['candidate_id']}",
    ):
        st.session_state["review_program_filter"] = str(row["performance_program_name"])
        st.session_state["review_ministry_filter"] = str(row["ministry_code"])
        _request_main_tab("원문 검수")
        st.rerun()

    if not pdf_ok:
        st.caption("중기부는 공통 PDF 검수 큐에 아직 연결되어 있지 않습니다.")


def _render_pdf_tab(selected_ministries: list[str], selected_years: list[int]) -> None:
    st.markdown("### 성과지표 원문 검수")
    st.info(
        "**이 화면에서 하는 일:** PDF 페이지를 보고 수기값이 원문과 같은지 "
        "**판정(일치/수정필요/확인불가/보류)** 을 남기는 것입니다.  \n"
        "**하지 않는 일:** 수기 마스터·분석 숫자를 이 폼에서 직접 고쳐 쓰지 않습니다.  \n"
        "값이 틀렸으면 결과=`수정 필요` + 메모에 `[파일·쪽] / [올바른 값]` 을 적습니다.  \n"
        "**띄어쓰기만** 다르고 의미·목표·실적·달성률이 같으면 → `원문과 일치` "
        "+ 메모에「띄어쓰기만 상이, 의미 동일」."
    )
    st.caption(
        "기본 목록 = 자동 근거를 못 붙인 잔여 지표(고용·복지·과기). "
        "잔여 29행 엑셀(`data/manual/performance/잔여29행_원문검수_작성용.xlsx`)도 "
        "같은 판정입니다. 엑셀에는 수정값을 칸에 적을 수 있고, "
        "이 화면은 판정·메모를 `pdf_reconciliation_manual_confirmations.csv`에 저장합니다."
    )
    if st.session_state.pop("review_saved", False):
        st.toast(
            "저장했습니다. 완료된 행은 열린 검수 큐에서 빠집니다.",
            icon=":material/check_circle:",
        )
    try:
        queue = get_pdf_review_queue()
    except (FileNotFoundError, OSError, ValueError) as exc:
        st.error(str(exc))
        return

    review_base = queue.loc[
        queue["ministry_code"].isin(selected_ministries) & queue["fiscal_year"].isin(selected_years)
    ].copy()
    focus_program = st.session_state.get("review_program_filter")
    focus_ministry = st.session_state.get("review_ministry_filter")
    if focus_program:
        review_base = review_base.loc[
            review_base["performance_program_name"].eq(focus_program)
            & review_base["ministry_code"].eq(focus_ministry)
        ]
        st.info(f"**{focus_program}** 만 보는 중입니다.", icon=":material/filter_alt:")
        if st.button("프로그램 필터 해제", icon=":material/filter_alt_off:"):
            _clear_review_focus()
            st.rerun()
    else:
        show_auto_strong = st.toggle("근거 승인된 행도 보기", value=False)
        if not show_auto_strong:
            # 미완료 사람검수 대상만 (완료분은 manual_review_required=False로 이미 제외)
            review_base = review_base.loc[
                review_base["manual_review_required"] | review_base["review_done"]
            ].copy()

    open_base = review_base.loc[~review_base["review_done"]].copy()
    done_base = review_base.loc[review_base["review_done"]].copy()
    c1, c2, c3 = st.columns(3)
    c1.metric("남은 검수", f"{len(open_base):,}")
    c2.metric("이 필터에서 완료", f"{len(done_base):,}")
    c3.metric(
        "불일치·모호(미완료)",
        int(open_base["overall_reconciliation_status"].isin(["VALUE_MISMATCH", "AMBIGUOUS"]).sum()),
    )
    show_done = st.toggle("완료한 행도 다시 보기(수정용)", value=False)
    review_queue = review_base if show_done else open_base
    review_queue = review_queue.sort_values(
        ["review_priority_order", "ministry_code", "fiscal_year"]
    )
    if review_queue.empty:
        st.success("남은 검수행이 없습니다. 완료분은 위 토글로만 다시 볼 수 있습니다.")
        return

    labels = {
        row.source_indicator_id: (
            f"{MINISTRY_LABELS.get(str(row.ministry_code), row.ministry_code)} · "
            f"{int(row.fiscal_year)} · {row.performance_program_name} · "
            f"{row.manual_indicator_name_report}"
            + (" · ✅완료" if bool(getattr(row, "review_done", False)) else "")
        )
        for row in review_queue.itertuples()
    }
    options = review_queue["source_indicator_id"].tolist()
    # 저장 직후 이전 선택이 목록에 없으면 다음 미완료 항목으로
    if st.session_state.get("pdf_review_pick") not in options:
        st.session_state["pdf_review_pick"] = options[0]
    selected_review_id = st.selectbox(
        "검수할 지표",
        options,
        format_func=lambda value: labels[value],
        key="pdf_review_pick",
    )
    review_row = review_queue.loc[review_queue["source_indicator_id"].eq(selected_review_id)].iloc[
        0
    ]
    st.write(str(review_row.get("review_instruction") or "근거 페이지 안내 없음"))
    comparison = pd.DataFrame(
        {
            "항목": ["지표명", "계획 목표", "실적", "공식 달성률"],
            "수기": [
                review_row.get("manual_indicator_name_report"),
                review_row.get("manual_planned_target_raw"),
                review_row.get("manual_actual_value_raw"),
                review_row.get("manual_official_achievement_rate_raw"),
            ],
            "PDF": [
                review_row.get("pdf_report_indicator_name"),
                review_row.get("pdf_plan_target_raw"),
                review_row.get("pdf_report_actual_raw"),
                review_row.get("pdf_report_official_achievement_rate_raw"),
            ],
        }
    )
    st.dataframe(comparison, hide_index=True, width="stretch")
    pages = review_page_specs(review_row)
    if pages:
        page_columns = st.columns(min(len(pages), 3))
        for column, (label, source_file, page) in zip(page_columns, pages[:3], strict=True):
            with column:
                try:
                    image = render_pdf_page(PROJECT_ROOT, source_file, page)
                except (FileNotFoundError, OSError, ValueError) as exc:
                    st.error(str(exc))
                else:
                    st.image(image, caption=f"{label} · {page}쪽", width="stretch")
    status_help = {
        "CONFIRMED": "PDF 인쇄값과 수기가 같음(띄어쓰기만 달라도 여기).",
        "CORRECTED": "수기가 틀림 → 메모에 올바른 지표명/목표/실적/달성률을 적음. 마스터는 별도 반영.",
        "NOT_RESOLVABLE": "현재 PDF만으로는 확정 불가.",
        "PENDING": "나중에 다시 볼 때.",
    }
    with st.form("pdf_review_form"):
        reviewer = st.text_input("검수자", placeholder="이름 또는 이니셜")
        review_status = st.selectbox(
            "결과",
            [value for value in REVIEW_STATUS_VALUES if value],
            index=1,
            format_func=lambda value: (
                f"{REVIEW_STATUS_LABELS[value]} — {status_help.get(value, '')}"
            ),
        )
        review_note = st.text_area(
            "메모 (필수)",
            placeholder=(
                "예1) [보고서 250쪽] 지표명·목표·실적 일치. 띄어쓰기만 '시 행결과'로 동일 전사.\n"
                "예2) [보고서 250쪽] 실적 수기 12 → 원문 13. 올바른 실적=13."
            ),
        )
        submitted = st.form_submit_button("판정 저장", type="primary", icon=":material/save:")
    if submitted:
        try:
            upsert_manual_review_confirmation(
                PROJECT_ROOT / DEFAULT_MANUAL_REVIEW_CONFIRMATIONS_PATH,
                source_indicator_id=selected_review_id,
                reviewer=reviewer,
                review_status=review_status,
                review_note=review_note,
            )
        except (OSError, ValueError) as exc:
            st.error(str(exc))
        else:
            load_pdf_review_queue.clear()
            st.session_state.pop("pdf_review_pick", None)
            st.session_state["review_saved"] = True
            st.rerun()


def _render_overview(
    base_for_counts: pd.DataFrame,
    summary: dict[str, Any],
    workload: pd.DataFrame,
    workload_by_grade: pd.DataFrame,
) -> None:
    st.markdown("## 개요 · 2024년")
    with st.container(horizontal=True):
        st.metric("분석 프로그램", f"{len(base_for_counts):,}", border=True)
        st.metric(
            "우선 확인 A+B",
            f"{base_for_counts['review_grade'].isin(['A', 'B']).sum():,}",
            border=True,
        )
        st.metric(
            "맥락 확인 C", f"{base_for_counts['review_grade'].eq('C').sum():,}", border=True
        )
        st.metric(
            "데이터 보완 H", f"{base_for_counts['review_grade'].eq('H').sum():,}", border=True
        )
        st.metric(
            "모니터링 D", f"{base_for_counts['review_grade'].eq('D').sum():,}", border=True
        )

    st.info(
        "점검등급은 구조화 신호의 확인 우선도이며, 재정규모는 별도 영향 참고값입니다."
    )
    priority = workload.loc[workload["analysis_group"].eq("PRIORITY_REVIEW")].iloc[0]
    monitor = workload.loc[workload["analysis_group"].eq("MONITOR")].iloc[0]
    st.markdown(
        f"우선 확인 A+B는 프로그램 **{float(priority['program_share']):.2%}**, "
        f"본예산 **{float(priority['original_budget_share']):.2%}**입니다. "
        f"모니터링 D는 본예산의 **{float(monitor['original_budget_share']):.2%}**를 차지하지만, "
        "D는 안전·정상 판정이 아니라 현재 정의에서 구조화 신호가 검출되지 않은 상태입니다."
    )

    left, right = st.columns(2)
    grade_order = ["A", "B", "C", "D", "H"]
    grade_counts = (
        base_for_counts["review_grade"].value_counts().reindex(grade_order, fill_value=0).rename_axis("등급").reset_index(name="프로그램 수")
    )
    budget_share = workload_by_grade.assign(
        **{"본예산 비중": pd.to_numeric(workload_by_grade["original_budget_share"], errors="coerce")}
    )[["review_grade", "본예산 비중"]].rename(columns={"review_grade": "등급"})
    with left:
        st.markdown("#### 등급별로 몇 개 프로그램이 있나")
        st.bar_chart(grade_counts, x="등급", y="프로그램 수")
    with right:
        st.markdown("#### 등급별 본예산 비중")
        st.bar_chart(budget_share, x="등급", y="본예산 비중")

    group_labels = {
        "PRIORITY_REVIEW": "우선 확인 A+B",
        "CONTEXT_REVIEW": "맥락 확인 C",
        "DATA_HOLD": "데이터 보완 H",
        "MONITOR": "모니터링 D",
    }
    group_view = workload.loc[workload["analysis_group"].isin(group_labels)].copy()
    group_view["업무그룹"] = group_view["analysis_group"].map(group_labels)
    group_view["프로그램 수"] = pd.to_numeric(group_view["program_count"], errors="coerce")
    group_view["본예산 비중"] = pd.to_numeric(
        group_view["original_budget_share"], errors="coerce"
    ).map(lambda value: f"{value:.2%}")
    st.markdown("#### 업무그룹별 프로그램·예산 비교")
    st.dataframe(
        group_view[["업무그룹", "프로그램 수", "본예산 비중"]],
        hide_index=True,
        width="stretch",
    )

    grain_summary = summary.get("program_year_review_queue", {})
    with st.expander("데이터 범위와 분석 단위", icon=":material/database:"):
        st.markdown(
            f"- 기준연도: **2024년** · 고유 프로그램 **{len(base_for_counts):,}개**\n"
            f"- 프로그램-연도 분석행: **{grain_summary.get('program_year_count', '—')}행**\n"
            f"- 프로그램-연도-회계유형 원시 감사행: "
            f"**{grain_summary.get('program_year_account_analysis_row_count', '—')}행**\n"
            f"- 식별 가능한 고유 프로그램: **{grain_summary.get('unique_program_count', '—')}개**"
        )


def _render_methodology(data: dict[str, Any]) -> None:
    st.markdown("## 분석·검증")
    st.info(
        "보고된 성과 미달을 기준축으로 두고, 집행·반복·예산변화 신호의 동시 관측 여부를 이용해 "
        "원문 확인의 우선도와 확인질문을 구분하는 성과 앵커형 질문형 점검등급입니다."
    )
    roles = pd.DataFrame(
        {
            "신호": ["보고된 성과", "집행", "반복", "예산괴리", "데이터 품질"],
            "역할": ["A/B의 기준축", "우선 확인 필요성 강화", "지속성 강화", "세부 등급·진단 조정", "H 판단 보류"],
        }
    )
    st.dataframe(roles, hide_index=True, width="stretch")

    st.markdown("### 규칙 검증")
    shadow = data["shadow_reproduction"]
    contract = data["contract_audit"]
    dominance = data["dominance_audit"]
    sensitivity = data["sensitivity_scenarios"].loc[
        data["sensitivity_scenarios"]["scenario_id"].ne("baseline")
    ]
    with st.container(horizontal=True):
        st.metric("기준 재현", f"{shadow['match'].astype(str).str.lower().eq('true').sum()}/236", border=True)
        st.metric("계약검사 실패", f"{pd.to_numeric(contract['failure_count']).sum():.0f}", border=True)
        st.metric(
            "대기순서 지배관계 위반",
            "0" if dominance["status"].eq("PASS").all() else "확인 필요",
            border=True,
        )
        st.metric(
            "A↔D 극단 이동",
            f"{pd.to_numeric(sensitivity['a_to_d_or_d_to_a_count']).sum():.0f}",
            border=True,
        )

    stability = data["priority_stability"]
    st.markdown("### 임계값 민감도")
    st.markdown(
        f"- A~D 등급 유지율: **{pd.to_numeric(sensitivity['grade_retention_rate']).min():.2%}~"
        f"{pd.to_numeric(sensitivity['grade_retention_rate']).max():.2%}**\n"
        f"- A+B 집합 유사도: **{pd.to_numeric(sensitivity['ab_jaccard']).min():.4f}~"
        f"{pd.to_numeric(sensitivity['ab_jaccard']).max():.4f}**\n"
        f"- 2024년 A+B 6개 중 업무그룹 유지: **{stability['threshold_stable_ab'].fillna(False).sum():.0f}개**\n"
        f"- 정확한 등급까지 동일: **{stability['exact_grade_stable'].fillna(False).sum():.0f}개**\n"
        f"- 경계 사례: **{', '.join(stability.loc[stability['threshold_boundary'].fillna(False), 'performance_program_name'])}**"
    )

    st.markdown("### 신호 제거")
    labels = {
        "execution": "집행",
        "reported_performance": "보고된 성과",
        "budget_performance_mismatch": "예산괴리",
        "repetition": "반복",
    }
    ablation = data["ablation_summary"].copy()
    ablation["신호"] = ablation["signal_family_removed"].map(labels)
    ablation["등급 변경"] = pd.to_numeric(ablation["grade_changed_count"])
    ablation["A/B 이탈"] = pd.to_numeric(ablation["ab_exit_count"])
    st.dataframe(ablation[["신호", "등급 변경", "A/B 이탈"]], hide_index=True, width="stretch")
    st.caption("독립 변수 중요도가 아니라 등급규칙의 신호 의존성입니다.")

    workload = data["workload_compression"]
    priority = workload.loc[workload["analysis_group"].eq("PRIORITY_REVIEW")].iloc[0]
    core = workload.loc[workload["analysis_group"].eq("THRESHOLD_STABLE_AB_CORE")].iloc[0]
    boundary = workload.loc[workload["analysis_group"].eq("THRESHOLD_BOUNDARY_AB")].iloc[0]
    st.markdown("### 검토범위 압축")
    st.markdown(
        f"- 프로그램: **77 → {int(priority['program_count'])}, {float(priority['program_share']):.2%}**\n"
        f"- 원문 드릴다운 단위: **1,080 → {int(priority['linked_source_review_unit_count'])}, "
        f"{float(priority['source_review_unit_share']):.2%}**\n"
        f"- 안정 핵심군: **{int(core['program_count'])}개 프로그램·{int(core['linked_source_review_unit_count'])}개 원문 단위**\n"
        f"- 경계군: **{int(boundary['program_count'])}개 프로그램·{int(boundary['linked_source_review_unit_count'])}개 원문 단위**"
    )

    temporal = data["temporal_followup"]
    def temporal_value(cohort: str, metric: str, scope: str = "H_EXCLUDED") -> pd.Series:
        return temporal.loc[
            temporal["analysis_scope"].eq(scope)
            & temporal["cohort"].eq(cohort)
            & temporal["metric"].eq(metric)
        ].iloc[0]

    st.markdown("### 다음 연도 관측")
    followup_ab = temporal.loc[
        temporal["analysis_scope"].eq("H_INCLUDED")
        & temporal["cohort"].isin(["A", "B"])
        & temporal["metric"].eq("FOLLOWUP_AVAILABLE")
    ][["numerator", "denominator"]].apply(pd.to_numeric).sum()
    temporal_rows = [
        (
            "A+B 후속연도 연결",
            {**followup_ab.to_dict(), "rate": followup_ab["numerator"] / followup_ab["denominator"]},
        ),
        ("동일 신호 재관측", temporal_value("A+B", "NEXT_YEAR_SAME_SIGNAL_FAMILY")),
        ("다음 연도 A+B 유지", temporal_value("A+B", "NEXT_YEAR_AB")),
        ("C→A/B", temporal_value("C", "NEXT_YEAR_AB")),
        ("D→A/B", temporal_value("D", "NEXT_YEAR_AB")),
    ]
    st.dataframe(
        pd.DataFrame(
            {
                "관측": [label for label, _ in temporal_rows],
                "결과": [
                    f"{int(row['numerator'])}/{int(row['denominator'])}, {float(row['rate']):.2%}"
                    for _, row in temporal_rows
                ],
            }
        ),
        hide_index=True,
        width="stretch",
    )
    st.warning("이는 예측 성능이 아니라 다음 연도 관측과의 방향적 연관성입니다.")

    st.markdown("### 외부검증")
    with st.container(horizontal=True):
        for label, count in EXTERNAL_VALIDATION_COUNTS.items():
            st.metric(label, f"{count}건", border=True)
    st.markdown("대표 누락 사례: **건강보험제도 운영**")
    st.markdown("### 동료집단 참고값")
    st.info("472개 지표행 중 동질 비교집단 조건을 충족한 경우는 10개에 그쳐 동료집단 백분위를 본편 기준으로 채택하지 않았습니다.")
    st.markdown("### 사람 검토")
    st.markdown(
        "블라인드 쌍대비교 검토표를 설계하고 연구자 1인의 예비 사용성 점검을 수행하였으나, "
        "제출 일정 내 독립 검토자를 추가 확보하지 못해 검토자 간 일치도와 모델-사람 판단 부합도는 "
        "산출하지 않았다. 해당 검증은 후속 과제로 남겼다."
    )


def main() -> None:
    st.set_page_config(
        page_title="재정사업 점검 대기열",
        page_icon=":material/fact_check:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    try:
        data = load_dashboard_data()
    except (FileNotFoundError, DashboardDataError, OSError, ValueError) as exc:
        st.error(str(exc))
        st.stop()

    queue = data["program_year_queue"]
    account_queue = data["work_queue"]
    summary = data["summary"]

    st.sidebar.header("필터")
    years = sorted(queue["fiscal_year"].dropna().astype(int).unique().tolist())
    latest_common_year = int(
        summary.get("program_year_review_queue", {}).get("latest_common_analysis_year")
        or max(years)
    )
    selected_year = st.sidebar.selectbox(
        "기준연도",
        years,
        index=years.index(latest_common_year),
        key="global_year",
    )
    ministry_codes = sorted(queue["ministry_code"].dropna().astype(str).unique())
    selected_ministries = st.sidebar.multiselect(
        "부처",
        ministry_codes,
        default=ministry_codes,
        format_func=lambda value: MINISTRY_LABELS.get(value, value),
        key="global_ministries",
    )
    queue_filter = st.sidebar.selectbox(
        "대기열 구분", list(QUEUE_FILTER_GRADES), index=0, key="queue_filter"
    )
    reviewer_mode = st.sidebar.toggle(
        "검수자 모드",
        value=False,
        help="내부 검수자가 PDF 원문 판정과 메모 저장 도구를 사용할 때만 켭니다.",
    )

    if reviewer_mode:
        st.title("검수자 도구")
        st.caption("내부 원문 검수 전용 화면입니다. 판정·메모 저장 기능은 기존과 같습니다.")
        _render_pdf_tab(selected_ministries, [selected_year])
        return

    st.title("재정사업 점검 대기열")
    st.markdown(
        "이 대시보드는 사업의 성공·실패나 예산 삭감을 판정하지 않습니다. "
        "구조화된 성과·집행·예산 신호를 바탕으로 원문을 먼저 확인할 프로그램과 확인질문을 제시합니다."
    )

    filtered = queue.loc[
        queue["ministry_code"].isin(selected_ministries) & queue["fiscal_year"].eq(selected_year)
    ].copy()
    filtered = filtered.loc[filtered["review_grade"].isin(QUEUE_FILTER_GRADES[queue_filter])]

    tabs = list(MAIN_TABS)
    _apply_pending_main_tab()
    tab = st.segmented_control(
        "화면",
        tabs,
        key="main_tab",
        width="stretch",
    )

    base_for_counts = queue.loc[queue["fiscal_year"].eq(2024)]

    if tab == "개요":
        _render_overview(
            base_for_counts,
            summary,
            data["workload_compression"],
            data["workload_by_grade"],
        )
    elif tab == "점검 대기열":
        section_titles = {
            "우선 확인 A+B": "우선 확인",
            "맥락 확인 C": "맥락 확인",
            "데이터 보완 H": "데이터 보완",
            "모니터링 D": "모니터링",
            "전체": "전체 대기열",
        }
        st.markdown(f"## {section_titles[queue_filter]}")
        if queue_filter == "데이터 보완 H":
            st.caption("등급 순위가 아니라 판단에 필요한 데이터와 비교가능성을 먼저 확인하는 목록입니다.")
        if filtered.empty:
            st.warning("필터에 맞는 행이 없습니다. 사이드바 필터를 넓혀 보세요.")
        else:
            options = filtered.sort_values("review_queue_order_within_year")
            ids = options["program_year_id"].tolist()
            if st.session_state.get("selected_program_year") not in ids:
                st.session_state["selected_program_year"] = ids[0]
            labels = {
                row.program_year_id: (
                    f"{REVIEW_GRADE_LABELS.get(str(row.review_grade), row.review_grade)} · "
                    f"{MINISTRY_LABELS.get(str(row.ministry_code), row.ministry_code)} · "
                    f"{row.performance_program_name}"
                )
                for row in options.itertuples()
            }
            selected_id = st.selectbox(
                "프로그램 선택",
                ids,
                format_func=lambda value: labels[value],
                key="selected_program_year",
            )
            simple = _queue_simple_table(filtered)
            queue_table_config = {
                "본예산(억원·참고)": st.column_config.NumberColumn(format="%.1f"),
                "핵심 근거": st.column_config.TextColumn(
                    help="성과·집행·예산 방향의 구조화 관측 사실입니다. 정책효과 판정이 아닙니다."
                ),
            }
            if queue_filter == "전체":
                st.markdown("### A–D 점검 대기열")
                st.dataframe(
                    _queue_simple_table(filtered.loc[filtered["review_grade"].ne("H")]),
                    hide_index=True,
                    height=420,
                    column_config=queue_table_config,
                )
                st.markdown("### H 데이터 보완")
                st.caption("데이터·비교가능성을 먼저 확인하며 A–D와 같은 서열로 표시하지 않습니다.")
                st.dataframe(
                    _queue_simple_table(filtered.loc[filtered["review_grade"].eq("H")]),
                    hide_index=True,
                    height=260,
                    column_config=queue_table_config,
                )
            else:
                st.dataframe(
                    simple,
                    hide_index=True,
                    height=480,
                    column_config=queue_table_config,
                )
            st.download_button(
                "현재 표 CSV",
                simple.to_csv(index=False).encode("utf-8-sig"),
                file_name="review_queue_simple.csv",
                mime="text/csv",
                icon=":material/download:",
            )
            selected_row = options.loc[options["program_year_id"].eq(selected_id)].iloc[0]
            with st.container(border=True):
                st.markdown(
                    f"**선택 프로그램:** {selected_row['performance_program_name']} · "
                    f"{DIAGNOSTIC_LABELS.get(str(selected_row['diagnostic_type']), selected_row['diagnostic_type'])}"
                )
                st.write(f"다음 확인: {selected_row['next_review_question']}")
                st.caption(
                    f"사업특성: {_context_badge_text(selected_row)} · "
                    f"근거강도: {_evidence_strength_text(selected_row['evidence_strength'])}"
                )

    elif tab == "프로그램 상세":
        pool = filtered if not filtered.empty else queue
        if pool.empty:
            st.warning("볼 행이 없습니다. 사이드바 필터를 넓혀 보세요.")
        else:
            options = pool.sort_values("review_queue_order_within_year")
            ids = options["program_year_id"].tolist()
            if st.session_state.get("selected_program_year") not in ids:
                st.session_state["selected_program_year"] = ids[0]
            selected_id = st.session_state["selected_program_year"]
            row = queue.loc[queue["program_year_id"].eq(selected_id)].iloc[0]
            _render_program_year_detail(row, queue, account_queue)
    else:
        _render_methodology(data)


if __name__ == "__main__":
    main()
