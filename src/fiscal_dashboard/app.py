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
    "A": "검토순서 A · 우선 원문 확인",
    "B": "검토순서 B · 원인 확인 권고",
    "C": "검토순서 C · 맥락 확인",
    "D": "검토순서 D · 현재 정의상 신호 미검출",
    "H": "H 판단 보류 · 데이터·비교가능성 확인",
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
    "equal": "균등가중",
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


MAIN_TABS = ("대기열", "사업 카드", "원문 검수")
PENDING_MAIN_TAB_KEY = "pending_main_tab"


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
        st.session_state["main_tab"] = "대기열"


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
    """사업 카드용: (제목, 값, 설명) — 퍼센트 강도 대신 개수·유무."""
    below = _as_int(row.get("below_target_count"))
    comparable = _as_int(row.get("comparable_rate_count"))
    if below is None or comparable is None:
        perf_value, perf_help = "자료 없음", "비교 가능한 성과지표 수를 확인하지 못함"
    else:
        perf_value = f"{below} / {comparable}개"
        perf_help = "공식 보고 달성률이 비교 가능한 지표 중 목표 미달 개수 (사업효과 판정 아님)"

    rate = pd.to_numeric(row.get("account_execution_rate"), errors="coerce")
    review_projects = _as_int(row.get("account_execution_review_project_count"))
    total_projects = _as_int(row.get("account_project_count"))
    exec_bits: list[str] = []
    if bool(row.get("execution_below_80")):
        exec_bits.append("80% 미만")
    elif bool(row.get("execution_below_90")):
        exec_bits.append("90% 미만")
    if bool(row.get("repeated_execution_signal")):
        exec_bits.append("반복 집행신호")
    if pd.isna(rate):
        exec_value = "자료 없음"
    else:
        exec_value = f"{float(rate):.0%}"
        if review_projects is not None and total_projects is not None and total_projects > 0:
            exec_value = f"{float(rate):.0%} · 점검세부 {review_projects}/{total_projects}"
    exec_help = " · ".join(exec_bits) if exec_bits else "올해 집행률 (필요 시 반복·세부사업 수)"

    if bool(row.get("budget_mismatch_signal")):
        mismatch_value = "있음"
        mismatch_help = "보고 목표 상태와 당해 예산변화 패턴 확인"
    else:
        mismatch_value = "없음"
        mismatch_help = "보고 목표 상태·당해 예산변화 불일치 신호 없음"

    independent = _as_int(row.get("independent_signal_family_count")) or 0
    repeated = _as_int(row.get("repeated_signal_family_count")) or 0
    return [
        ("보고 목표 미달 지표", perf_value, perf_help),
        ("집행", exec_value, exec_help),
        ("보고 목표·당해 예산변화", mismatch_value, mismatch_help),
        ("독립 / 반복 신호", f"{independent} / {repeated}개", "켜진 신호 종류 수 · 반복 계열 수"),
    ]


def _queue_simple_table(frame: pd.DataFrame) -> pd.DataFrame:
    if "program_year_id" in frame:
        table = frame.sort_values("review_queue_order_within_year").copy()
        table["순서"] = table["review_queue_order_within_year"]
        table["관측기간"] = (
            table["observed_start_year"].astype("Int64").astype("string")
            + "–"
            + table["observed_end_year"].astype("Int64").astype("string")
            + " ("
            + table["observed_year_count"].astype("Int64").astype("string")
            + "개 연도)"
        )
        budget_column = "program_original_budget"
    else:
        table = frame.sort_values("grade_queue_order").copy()
        table["순서"] = table["grade_queue_order"]
        table["관측기간"] = table["fiscal_year"].astype("Int64").astype("string")
        budget_column = "account_original_budget"
    table["부처"] = table["ministry_code"].map(MINISTRY_LABELS).fillna(table["ministry_code"])
    table["프로그램"] = table["performance_program_name"]
    table["점검등급"] = table["review_grade"].map(REVIEW_GRADE_LABELS)
    table["주 진단"] = (
        table["diagnostic_type"].map(DIAGNOSTIC_LABELS).fillna(table["diagnostic_type"])
    )
    table["핵심 근거"] = [_signal_composition_label(row) for _, row in table.iterrows()]
    table["다음 확인질문"] = table["next_review_question"]
    context_flags = table.get("context_flags", pd.Series("NONE", index=table.index)).astype(str)
    table["사업특성 상태"] = (
        context_flags
        + " / "
        + table["context_type"].astype(str)
        + " / "
        + table["context_status"].astype(str)
        + " / "
        + table["context_effect"].astype(str)
    )
    table["근거강도"] = table["evidence_strength"]
    table["예산(억원·참고)"] = pd.to_numeric(table[budget_column], errors="coerce").div(100_000_000)
    return table[
        [
            "순서",
            "부처",
            "프로그램",
            "점검등급",
            "주 진단",
            "핵심 근거",
            "다음 확인질문",
            "사업특성 상태",
            "근거강도",
            "관측기간",
            "예산(억원·참고)",
        ]
    ]


def _render_program_year_detail(
    row: pd.Series,
    program_queue: pd.DataFrame,
    account_queue: pd.DataFrame,
) -> None:
    grade = str(row["review_grade"])
    st.markdown(
        f"### {MINISTRY_LABELS.get(str(row['ministry_code']), row['ministry_code'])} · "
        f"{int(row['fiscal_year'])} · {row['performance_program_name']}"
    )
    st.caption(
        f"프로그램×연도 검토행 · 순서 {int(row['review_queue_order_within_year'])} · "
        f"{REVIEW_GRADE_LABELS.get(grade, grade)} · {row['continuity_status']}"
    )
    st.info(
        f"{DIAGNOSTIC_LABELS.get(str(row.get('diagnostic_type')), row.get('diagnostic_type'))}  \n"
        f"다음 확인질문: {row.get('next_review_question')}",
        icon=":material/flag:",
    )
    st.caption(
        "등급은 사업 성과평가·감액등급이 아니라 프로그램 원문 검토 순서입니다. "
        "보고 목표 상태는 프로그램 수준 참고 맥락이며 세부사업 성과로 귀속하지 않습니다. "
        f"맥락 배지: {row.get('context_flags', 'NONE')} / {row.get('context_effect')}"
    )

    def amount_label(value: object) -> str:
        numeric = pd.to_numeric(value, errors="coerce")
        return "—" if pd.isna(numeric) else f"{float(numeric) / 100_000_000:,.1f}억"

    metrics = st.columns(4)
    metrics[0].metric("본예산", amount_label(row["program_original_budget"]))
    metrics[1].metric("예산현액", amount_label(row["program_current_budget"]))
    metrics[2].metric("지출액", amount_label(row["program_expenditure"]))
    execution = pd.to_numeric(row.get("program_execution_rate"), errors="coerce")
    metrics[3].metric("총집행률", "—" if pd.isna(execution) else f"{float(execution):.1%}")

    history = program_queue.loc[
        program_queue["program_identity_id"].eq(row["program_identity_id"])
    ].sort_values("fiscal_year")
    timeline = history[
        [
            "fiscal_year",
            "review_grade",
            "diagnostic_type",
            "program_original_budget",
            "program_current_budget",
            "program_expenditure",
            "program_execution_rate",
            "reported_target_status",
        ]
    ].rename(
        columns={
            "fiscal_year": "연도",
            "review_grade": "점검등급",
            "diagnostic_type": "진단유형",
            "program_original_budget": "본예산",
            "program_current_budget": "예산현액",
            "program_expenditure": "지출액",
            "program_execution_rate": "집행률",
            "reported_target_status": "보고목표 상태",
        }
    )
    st.markdown("**연도별 프로그램 관측 타임라인**")
    st.dataframe(
        timeline,
        hide_index=True,
        width="stretch",
        column_config={
            "본예산": st.column_config.NumberColumn(format="%,.0f"),
            "예산현액": st.column_config.NumberColumn(format="%,.0f"),
            "지출액": st.column_config.NumberColumn(format="%,.0f"),
            "집행률": st.column_config.NumberColumn(format="percent"),
        },
    )

    raw_ids = set(json.loads(str(row["raw_candidate_ids"])))
    accounts = account_queue.loc[account_queue["candidate_id"].isin(raw_ids)].copy()
    account_view = accounts[
        [
            "candidate_id",
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
            "candidate_id": "원시행 ID",
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
    st.markdown("**선택 연도의 회계유형별 원시 분석행**")
    st.caption("아래 행은 감사·드릴다운용이며 최종 점검대상 수로 세지 않습니다.")
    st.dataframe(
        account_view,
        hide_index=True,
        width="stretch",
        column_config={
            "본예산": st.column_config.NumberColumn(format="%,.0f"),
            "예산현액": st.column_config.NumberColumn(format="%,.0f"),
            "지출액": st.column_config.NumberColumn(format="%,.0f"),
            "집행률": st.column_config.NumberColumn(format="percent"),
        },
    )
    pdf_ok = str(row["ministry_code"]) in PDF_REVIEW_MINISTRY_CODES
    if st.button(
        "이 프로그램 원문(PDF) 검수로 이동",
        icon=":material/description:",
        disabled=not pdf_ok,
        width="stretch",
        key="goto_pdf_program_year",
    ):
        st.session_state["review_program_filter"] = str(row["performance_program_name"])
        st.session_state["review_ministry_filter"] = str(row["ministry_code"])
        _request_main_tab("원문 검수")
        st.rerun()


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


def main() -> None:
    st.set_page_config(
        page_title="재정사업 점검 대기열",
        page_icon=":material/fact_check:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.title("재정사업 점검 대기열")
    st.markdown(
        "이 화면은 **어디부터 원문을 보면 좋은지** 순서를 보여 줍니다.  "
        "실패·낭비·삭감 점수표가 아니며, 예산 크기로 순위를 매기지 않습니다."
    )
    st.caption(
        "분석시점: 필요한 자료가 공개·구조화된 뒤 수행한 회계연도별 연례 사후검토입니다. "
        "회계연도 말 당시의 정보집합이나 실시간 판단을 재현하지 않습니다."
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
    ministry_codes = sorted(queue["ministry_code"].dropna().astype(str).unique())
    selected_ministries = st.sidebar.multiselect(
        "부처",
        ministry_codes,
        default=ministry_codes,
        format_func=lambda value: MINISTRY_LABELS.get(value, value),
        key="global_ministries",
    )
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
    hide_monitor = st.sidebar.toggle(
        "D ‘현재 정의상 신호 미검출’ 숨기기",
        value=True,
        help="D는 정상 판정이 아니라 현재 정의에서 검토신호가 잡히지 않은 행입니다.",
    )
    grade_options = ["전체"] + [
        REVIEW_GRADE_LABELS[key]
        for key in ("H", "A", "B", "C", "D")
        if key != "D" or not hide_monitor
    ]
    selected_grade_label = st.sidebar.radio("검토등급", grade_options, index=0)
    grade_code = None
    if selected_grade_label != "전체":
        grade_code = next(
            key for key, label in REVIEW_GRADE_LABELS.items() if label == selected_grade_label
        )

    filtered = queue.loc[
        queue["ministry_code"].isin(selected_ministries) & queue["fiscal_year"].eq(selected_year)
    ].copy()
    if hide_monitor:
        filtered = filtered.loc[filtered["review_grade"].ne("D")]
    if grade_code is not None:
        filtered = filtered.loc[filtered["review_grade"].eq(grade_code)]

    tabs = list(MAIN_TABS)
    _apply_pending_main_tab()
    tab = st.segmented_control(
        "화면",
        tabs,
        key="main_tab",
        width="stretch",
    )

    # summary strip
    base_for_counts = queue.loc[
        queue["ministry_code"].isin(selected_ministries) & queue["fiscal_year"].eq(selected_year)
    ]
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("선택연도 고유 프로그램", f"{len(base_for_counts):,}")
    s2.metric(
        "검토순서 A",
        f"{base_for_counts['review_grade'].eq('A').sum():,}",
    )
    s3.metric(
        "H 판단 보류",
        f"{base_for_counts['review_grade'].eq('H').sum():,}",
    )
    s4.metric("현재 표 프로그램", f"{len(filtered):,}")
    grain_summary = summary.get("program_year_review_queue", {})
    st.caption(
        f"식별 가능한 고유 프로그램 {grain_summary.get('unique_program_count', '—')}개 · "
        f"연속성 보류 프로그램-연도 "
        f"{grain_summary.get('unknown_continuity_program_year_count', '—')}행 · "
        f"프로그램-연도 {grain_summary.get('program_year_count', '—')}행 · "
        f"프로그램-연도-회계유형 원시 분석행 "
        f"{grain_summary.get('program_year_account_analysis_row_count', '—')}행"
    )

    if tab == "대기열":
        st.markdown("### 위에서부터 보면 됩니다")
        st.caption(
            "정렬: **H 판단 보류 → 검토순서 A → B → C → D**. "
            "H는 고위험 등급이 아니라 데이터·비교가능성을 먼저 확인할 업무입니다. "
            "같은 등급 안에서만 신호 강도·근거 → 본예산(동률)을 사용합니다. "
            "가중치 시나리오 순위표는 없습니다."
        )
        if filtered.empty:
            st.warning("필터에 맞는 행이 없습니다. 사이드바 필터를 넓혀 보세요.")
        else:
            simple = _queue_simple_table(filtered)
            st.dataframe(
                simple,
                hide_index=True,
                width="stretch",
                height=480,
                column_config={
                    "예산(억원·참고)": st.column_config.NumberColumn(format="%.1f"),
                    "핵심 근거": st.column_config.TextColumn(
                        help="성과·집행·예산 방향의 구조화 관측 사실입니다. 정책효과 판정이 아닙니다."
                    ),
                },
            )
            st.download_button(
                "현재 표 CSV",
                simple.to_csv(index=False).encode("utf-8-sig"),
                file_name="review_queue_simple.csv",
                mime="text/csv",
                icon=":material/download:",
            )
            # pick for card
            options = filtered.sort_values("review_queue_order_within_year")
            labels = {
                row.program_year_id: (
                    f"{int(row.review_queue_order_within_year)}. "
                    f"{MINISTRY_LABELS.get(str(row.ministry_code), row.ministry_code)} "
                    f"{int(row.fiscal_year)} {row.performance_program_name}"
                )
                for row in options.itertuples()
            }
            picked = st.selectbox(
                "프로그램 상세로 열어볼 행",
                options["program_year_id"].tolist(),
                format_func=lambda value: labels[value],
                key="queue_pick",
            )
            if st.button(
                "선택한 프로그램 상세 열기", type="primary", icon=":material/arrow_forward:"
            ):
                st.session_state["selected_program_year"] = picked
                _request_main_tab("사업 카드")
                st.rerun()

        with st.expander("등급이 무슨 뜻인가요?"):
            st.markdown("- **H 판단 보류**: 데이터·비교가능성 확인 후 A–D를 판단합니다.")
            st.markdown("- **검토순서 A**: 두 명시적 복합 관측 규칙에 해당합니다.")
            st.markdown("- **검토순서 B**: 강한·반복 단일 또는 서로 다른 두 관측 영역입니다.")
            st.markdown("- **검토순서 C**: 단일·모호·충돌·사업맥락 확인 질문입니다.")
            st.markdown("- **검토순서 D**: 현재 정의에서 구조화 검토신호가 미검출됐습니다.")
            st.caption("A–D는 사업 성과·효율·감액 등급이 아닙니다.")

    elif tab == "사업 카드":
        pool = filtered if not filtered.empty else queue
        if pool.empty:
            st.warning("볼 행이 없습니다. 사이드바 필터를 넓혀 보세요.")
        else:
            options = pool.sort_values("review_queue_order_within_year")
            ids = options["program_year_id"].tolist()
            if st.session_state.get("selected_program_year") not in ids:
                st.session_state["selected_program_year"] = ids[0]
            labels = {
                row.program_year_id: (
                    f"{MINISTRY_LABELS.get(str(row.ministry_code), row.ministry_code)} · "
                    f"{int(row.fiscal_year)} {row.performance_program_name}"
                )
                for row in options.itertuples()
            }
            selected_id = st.selectbox(
                "프로그램",
                ids,
                format_func=lambda value: labels[value],
                key="selected_program_year",
            )
            row = queue.loc[queue["program_year_id"].eq(selected_id)].iloc[0]
            _render_program_year_detail(row, queue, account_queue)

    else:
        _render_pdf_tab(selected_ministries, [selected_year])

    with st.expander("분석 정의 (짧게)"):
        st.markdown(
            """
- **기본 점검대기열 한 행:** 부처 × 프로그램 × 연도  
- **원시 감사행:** 부처 × 프로그램 × 연도 × 회계유형  
- **본편:** 유형별 대기열 (가중 시나리오 없음)  
- **신호 구성:** 보고 목표 상태·집행·당해 예산변화 패턴. 대기 순서는 단계(레인)가 먼저
- **signal_score:** 세 요소가 모두 있을 때만 계산. 같은 단계 안 탐색용이며 1등 점수가 아님
- **환류:** T+1·T+2는 사후 맥락이며 현재 대기레인·순서에 사용하지 않음
- **금지:** 실패·낭비·삭감 자동 판정  
- 자세한 멘토링 반영: `docs/MENTORING_SESSION_3_2026-08-04.md`
"""
        )
        st.caption(f"분석 생성(UTC): {summary.get('generated_at', '확인 불가')}")


if __name__ == "__main__":
    main()
