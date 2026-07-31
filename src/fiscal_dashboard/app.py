"""다부처 점검 후보·순위 안정성·성과 원문 검수 Streamlit 대시보드."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from matplotlib import font_manager

from performance_pipeline.pdf_reconciliation import (
    DEFAULT_MANUAL_REVIEW_CONFIRMATIONS_PATH,
    REVIEW_STATUS_VALUES,
    apply_manual_review_confirmations,
    load_manual_review_confirmations,
    upsert_manual_review_confirmation,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path("data/analytics/multi_ministry_priority_scenarios")
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
SCENARIO_LABELS = {
    "equal": "균등가중",
    "performance_focus": "성과중심",
    "execution_focus": "집행중심",
    "fiscal_impact_adjusted": "재정영향 보정",
}
REASON_LABELS = {
    "PERFORMANCE_BELOW_TARGET": "성과 목표 미달",
    "EXECUTION_MANAGEMENT": "집행 설명 필요",
    "BUDGET_PERFORMANCE_MISMATCH": "성과·예산변화 불일치",
    "ACCOUNTING_ADJUSTMENT_CONTEXT": "회계조정 맥락",
    "PROGRAM_STRUCTURE_CONTEXT": "프로그램 구조 맥락",
    "LOW_PERFORMANCE_BUDGET_INCREASE_T1": "성과 미달 뒤 T+1 예산 증가",
    "LOW_PERFORMANCE_BUDGET_INCREASE_T2": "성과 미달 뒤 T+2 예산 증가",
    "GOOD_PERFORMANCE_BUDGET_DECREASE_T1_CONTEXT": "성과 양호 뒤 T+1 예산 감소 맥락",
    "GOOD_PERFORMANCE_BUDGET_DECREASE_T2_CONTEXT": "성과 양호 뒤 T+2 예산 감소 맥락",
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
MANUAL_REVIEW_REQUIRED_STATUSES = {
    "VALUE_MISMATCH",
    "AMBIGUOUS",
    "PDF_MISSING_MANUAL_PRESENT",
    "OCR_REQUIRED",
}
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
            "review_candidate",
            "scenario_ranking_eligible",
            "data_validation_signal",
            "account_original_budget",
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
            "review_candidate",
            "scenario_ranking_eligible",
            "data_validation_signal",
            "account_original_budget",
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
            "전체 업무대기열이 후보 모집단 412행을 빠짐없이 보존하지 못했습니다."
        )
    if data["stability"]["candidate_id"].duplicated().any():
        raise DashboardDataError("안정성표 candidate_id가 중복되었습니다.")
    if data["scores"].duplicated(["candidate_id", "scenario"]).any():
        raise DashboardDataError("시나리오 점수의 후보-시나리오 키가 중복되었습니다.")
    return data


def _program_count(frame: pd.DataFrame) -> int:
    return len(
        frame.dropna(subset=["program_code"]).drop_duplicates(
            ["ministry_code", "field_name", "sector_name", "program_code"]
        )
    )


@st.cache_data
def load_pdf_review_queue(root: Path = PROJECT_ROOT) -> pd.DataFrame:
    """3개 부처 PDF 대조 결과와 현재 사람 검수 상태를 읽습니다."""
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
    queue["manual_review_required"] = queue["overall_reconciliation_status"].isin(
        MANUAL_REVIEW_REQUIRED_STATUSES
    )
    queue["review_priority_order"] = (
        queue["overall_reconciliation_status"].map(REVIEW_PRIORITY_ORDER).fillna(99)
    )
    return queue


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


def _go_to_step(step: str) -> None:
    st.session_state["workflow_step"] = step


def _go_to_review(program_name: str, ministry_code: str) -> None:
    st.session_state["review_program_filter"] = program_name
    st.session_state["review_ministry_filter"] = ministry_code
    st.session_state["comparison_mode"] = "원문 검수"
    _go_to_step(WORKFLOW_STEPS[3])


def _go_to_advanced() -> None:
    st.session_state["comparison_mode"] = "고급 민감도"
    _go_to_step(WORKFLOW_STEPS[3])


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


def main() -> None:
    st.set_page_config(
        page_title="재정사업 점검 작업대",
        page_icon=":material/fact_check:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.title("재정사업 점검 작업대")
    st.caption(
        "고용노동부·보건복지부·중소벤처기업부·과학기술정보통신부 2022–2024 파일럿 · "
        "업무 현황 → 점검대기열 → 사업 상세 → 비교·원문 검수 순서로 진행합니다."
    )

    try:
        data = load_dashboard_data()
    except (FileNotFoundError, DashboardDataError, OSError, ValueError) as exc:
        st.error(str(exc))
        st.stop()

    candidates = data["work_queue"]
    stability = data["stability"]
    scores = data["scores"]
    project_queue = data["project_queue"]
    summary = data["summary"]
    counts = summary["counts"]

    st.sidebar.header("필터")
    ministry_codes = sorted(candidates["ministry_code"].dropna().astype(str).unique())
    selected_ministries = st.sidebar.multiselect(
        "부처",
        ministry_codes,
        default=ministry_codes,
        format_func=lambda value: MINISTRY_LABELS.get(value, value),
        key="global_ministries",
    )
    scope = st.sidebar.radio(
        "점검 업무 범위",
        ["전체 업무대기열", *WORK_SCOPE_TO_LANE],
    )
    years = sorted(candidates["fiscal_year"].dropna().astype(int).unique().tolist())
    selected_years = st.sidebar.multiselect(
        "회계연도",
        years,
        default=years,
        key="global_years",
    )
    account_types = sorted(candidates["account_type"].dropna().astype(str).unique())
    selected_accounts = st.sidebar.multiselect(
        "회계유형",
        account_types,
        default=account_types,
        format_func=_format_account,
        key="global_accounts",
    )
    tiers = sorted(
        candidates["review_intensity"].dropna().astype(str).unique(),
        key=lambda value: list(REVIEW_INTENSITY_LABELS).index(value),
    )
    selected_tiers = st.sidebar.multiselect(
        "점검강도",
        tiers,
        default=tiers,
        format_func=lambda value: REVIEW_INTENSITY_LABELS.get(value, value),
        key="global_tiers",
    )
    filtered_all = filter_candidates(
        candidates,
        scope="전체 업무대기열",
        years=selected_years,
        account_types=selected_accounts,
        tiers=selected_tiers,
        ministry_codes=selected_ministries,
    )
    filtered = filter_candidates(
        candidates,
        scope=scope,
        years=selected_years,
        account_types=selected_accounts,
        tiers=selected_tiers,
        ministry_codes=selected_ministries,
    )
    workbench = data["review_queue"]
    filtered_workbench = workbench.loc[
        workbench["ministry_code"].isin(selected_ministries)
        & workbench["fiscal_year"].isin(selected_years)
        & workbench["account_type"].isin(selected_accounts)
        & workbench["review_intensity"].isin(selected_tiers)
    ].copy()
    if scope in WORK_SCOPE_TO_LANE:
        filtered_workbench = filtered_workbench.loc[
            filtered_workbench["review_intensity"].eq(WORK_SCOPE_TO_LANE[scope])
        ]
    workflow_step = st.segmented_control(
        "작업 단계",
        WORKFLOW_STEPS,
        default=WORKFLOW_STEPS[0],
        key="workflow_step",
        width="stretch",
    )
    comparison_mode = None
    if workflow_step == WORKFLOW_STEPS[3]:
        comparison_mode = st.segmented_control(
            "검수 방식",
            ["원문 검수", "고급 민감도"],
            default="원문 검수",
            key="comparison_mode",
        )
    if st.session_state.pop("review_saved", False):
        st.toast("검수 결과를 저장했습니다.", icon=":material/check_circle:")

    st.caption(f"현재 필터: {len(filtered_all):,}행 · {_program_count(filtered_all):,}개 프로그램")
    with st.container(horizontal=True):
        st.metric("전체 업무행", f"{len(filtered_all):,}", border=True)
        st.metric(
            "반복·복수 신호",
            f"{filtered_all['review_intensity'].eq('REPEATED_OR_MULTIPLE').sum():,}",
            border=True,
        )
        st.metric(
            "강한 단일 신호",
            f"{filtered_all['review_intensity'].eq('STRONG_SINGLE').sum():,}",
            border=True,
        )
        st.metric(
            "데이터 먼저",
            f"{filtered_all['review_intensity'].eq('DATA_FIRST').sum():,}",
            border=True,
        )
        st.metric(
            "신호 미검출",
            f"{filtered_all['review_intensity'].eq('MONITOR').sum():,}",
            border=True,
        )

    if workflow_step == WORKFLOW_STEPS[0]:
        st.subheader("가중점수 대신 확인할 근거와 다음 행동을 보여드립니다")
        st.info(
            "성과·집행·T+1·T+2·예산구조 신호를 합산하지 않았습니다. "
            "반복성, 독립 신호 수, 근거상태, 본예산 순으로 점검업무를 정렬하며 "
            "‘신호 미검출’은 안전 판정이 아닙니다.",
            icon=":material/route:",
        )
        try:
            queue = load_pdf_review_queue()
        except (FileNotFoundError, OSError, ValueError) as exc:
            queue = None
            st.warning(f"PDF 검수 현황을 불러오지 못했습니다: {exc}")
        done_reviews = (
            0
            if queue is None
            else int(queue["review_status"].isin(["CONFIRMED", "CORRECTED"]).sum())
        )
        total_reviews = 0 if queue is None else len(queue)
        status_columns = st.columns(4, border=True)
        review = filtered_all.loc[filtered_all["data_validation_signal"].fillna(False)].copy()
        worklist = _review_worklist(review)
        unresolved_work = worklist.loc[worklist["상태"].eq("확인 필요")]
        resolved_rows = int(
            review["analysis_status"]
            .isin(
                [
                    "STRUCTURAL_PROGRAM_DELETED_TRANSFERRED",
                    "EXTERNAL_MINISTRY_FINANCIAL_PROGRAM",
                ]
            )
            .sum()
        )
        status_columns[0].metric(
            "1. 재정 연결 완료",
            f"{counts['joint_analysis_rows']:,}/{counts['analysis_rows']:,}행",
        )
        status_columns[0].caption("성과와 재정을 프로그램·연도·회계별로 연결한 결과입니다.")
        status_columns[1].metric("2. 먼저 해결", f"{len(unresolved_work):,}개 작업")
        status_columns[1].caption(
            f"원본 {len(review):,}행을 프로그램별로 묶었습니다. "
            f"구조변경·타부처 소관 확인 완료 {resolved_rows:,}행은 제외했습니다."
        )
        status_columns[2].metric(
            "3. 세부사업 검토",
            f"{len(project_queue):,}행",
        )
        status_columns[2].caption("프로그램 성과는 상위 맥락으로만 표시합니다.")
        status_columns[3].metric("4. 원문 검수", f"{done_reviews:,}/{total_reviews:,}행")
        status_columns[3].caption("발표 사례로 쓸 성과지표를 사람이 확인합니다.")
        st.markdown("#### 전체 점검 업무대기열")
        st.dataframe(
            _table_view(filtered_all.sort_values("work_queue_order").head(10)),
            hide_index=True,
            width="stretch",
            column_config={
                "본예산(억원)": st.column_config.NumberColumn(format="%.1f"),
            },
        )
        st.caption(
            f"업무순서 상위 10행입니다. 현재 필터의 전체 {len(filtered_all):,}행은 "
            "‘2. 점검대기열’에서 확인하고 내려받을 수 있습니다."
        )
        st.warning(
            "기금은 제외하지 않되 일반·특별회계와 분모·운용구조가 달라 같은 "
            "집행수치로 직접 비교하지 않습니다. 내부거래·전출·원금상환·여유자금 운용은 "
            "기존 분석 모집단에서 제외한 상태를 유지합니다.",
            icon=":material/warning:",
        )
        if unresolved_work.empty:
            st.success("현재 필터에는 먼저 해결할 데이터 작업이 없습니다.")
        else:
            st.markdown("#### 바로 이어서 할 작업")
            st.dataframe(
                unresolved_work.head(5),
                hide_index=True,
                width="stretch",
                column_order=[
                    "부처",
                    "프로그램",
                    "대상연도",
                    "확인할 문제",
                    "다음 행동",
                    "순위 영향",
                ],
            )
            st.caption(
                f"상위 5개만 미리 보여드립니다. 전체 {len(unresolved_work):,}개 작업은 "
                "‘2. 먼저 해결’에서 확인할 수 있습니다."
            )
        action_columns = st.columns(3)
        for column, label, icon, step in (
            (
                action_columns[0],
                "점검대기열 보기",
                ":material/format_list_numbered:",
                WORKFLOW_STEPS[1],
            ),
            (action_columns[1], "사업 상세 보기", ":material/search:", WORKFLOW_STEPS[2]),
            (
                action_columns[2],
                "비교·원문 검수",
                ":material/description:",
                WORKFLOW_STEPS[3],
            ),
        ):
            column.button(
                label,
                icon=icon,
                on_click=_go_to_step,
                args=(step,),
                width="stretch",
            )

    elif workflow_step == WORKFLOW_STEPS[1]:
        review = filtered_all.loc[filtered_all["data_validation_signal"].fillna(False)].copy()
        st.subheader("다음에 확인할 세부사업과 데이터 작업을 한 줄로 정리했습니다")
        st.caption(
            "가중점수 순위가 아닙니다. 데이터 차단 → 반복·복수 → 강한 단일 → 단일 → "
            "맥락 → 모니터링 순서이며, 같은 단계에서는 반복성·독립 신호 수·근거상태·"
            "본예산만 업무 정렬에 사용합니다."
        )
        st.dataframe(
            _workbench_table(filtered_workbench.sort_values("workbench_order")),
            hide_index=True,
            width="stretch",
            height=520,
            column_config={
                "본예산(억원)": st.column_config.NumberColumn(format="%.1f"),
            },
        )
        st.download_button(
            "현재 점검대기열 CSV 내려받기",
            _workbench_table(filtered_workbench.sort_values("workbench_order"))
            .to_csv(index=False)
            .encode("utf-8-sig"),
            file_name="review_workbench_queue_filtered.csv",
            mime="text/csv",
            icon=":material/download:",
        )
        st.markdown("#### 데이터 확인이 먼저 필요한 프로그램")
        if review.empty:
            st.success("현재 필터에는 먼저 확인할 데이터가 없습니다.")
        else:
            worklist = _review_worklist(review)
            unresolved_work = worklist.loc[worklist["상태"].eq("확인 필요")]
            resolved_work = worklist.loc[worklist["상태"].eq("확인 완료")]
            with st.container(horizontal=True):
                st.metric("원본 확인행", f"{len(review):,}", border=True)
                st.metric("실제 확인 작업", f"{len(unresolved_work):,}", border=True)
                st.metric(
                    "프로그램코드 확인",
                    f"{review['analysis_status'].eq('PROGRAM_MATCH_REVIEW').sum():,}행",
                    border=True,
                )
                st.metric(
                    "확인 완료",
                    f"{len(resolved_work):,}개",
                    border=True,
                )
            chart_data = (
                unresolved_work.groupby("부처", as_index=True)["영향행"]
                .sum()
                .sort_values(ascending=False)
            )
            if not chart_data.empty:
                st.bar_chart(chart_data, horizontal=True, x_label="영향행", y_label="부처")
            st.dataframe(
                worklist,
                hide_index=True,
                width="stretch",
                column_config={
                    "영향행": st.column_config.NumberColumn(format="%d"),
                },
            )
            with st.expander(
                f"원본 {len(review):,}행과 금액 차이 보기",
                icon=":material/table_chart:",
            ):
                st.dataframe(
                    _data_review_table(
                        review.sort_values(
                            ["ministry_code", "fiscal_year", "performance_program_name"]
                        )
                    ),
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "본예산 차이(억원)": st.column_config.NumberColumn(format="%.1f"),
                    },
                )
        st.button(
            "사업 상세로 이동",
            icon=":material/arrow_forward:",
            on_click=_go_to_step,
            args=(WORKFLOW_STEPS[2],),
        )

    elif workflow_step == WORKFLOW_STEPS[2]:
        st.subheader("프로그램 신호와 세부사업 원인을 분리해서 확인합니다")
        if filtered.empty:
            st.warning("현재 필터에 해당하는 후보가 없습니다.")
        else:
            st.caption(f"현재 필터: {len(filtered)}행 · {_program_count(filtered)}개 프로그램")
            joined = filtered.sort_values("work_queue_order")
            option_frame = joined
            option_labels = {
                row.candidate_id: (
                    f"{MINISTRY_LABELS.get(str(row.ministry_code), row.ministry_code)} · "
                    f"{int(row.fiscal_year)} {row.performance_program_name} / "
                    f"{_format_account(row.account_type)}"
                )
                for row in option_frame.itertuples()
            }
            selected_id = st.selectbox(
                "확인할 후보",
                option_frame["candidate_id"].tolist(),
                format_func=lambda value: option_labels[value],
                key="selected_candidate",
            )
            row = candidates.loc[candidates["candidate_id"].eq(selected_id)].iloc[0]
            tier_label = REVIEW_INTENSITY_LABELS.get(
                row["review_intensity"], row["review_intensity"]
            )
            lane_label = WORK_LANE_LABELS.get(row["work_lane"], row["work_lane"])
            st.info(
                f"**업무순서 {int(row['work_queue_order']):,} · {lane_label}**  \n"
                f"{tier_label} · {row['next_action']}",
                icon=":material/flag:",
            )
            comparable_value = pd.to_numeric(
                pd.Series([row.get("comparable_rate_count")]), errors="coerce"
            ).iloc[0]
            below_value = pd.to_numeric(
                pd.Series([row.get("below_target_count")]), errors="coerce"
            ).iloc[0]
            comparable_count = 0 if pd.isna(comparable_value) else int(comparable_value)
            below_count = 0 if pd.isna(below_value) else int(below_value)
            execution_rate = pd.to_numeric(row.get("account_execution_rate"), errors="coerce")

            def feedback_value(horizon: str) -> tuple[str, str]:
                complete = bool(row.get(f"feedback_budget_complete_{horizon}", False))
                rate = pd.to_numeric(
                    row.get(f"feedback_budget_change_rate_{horizon}"),
                    errors="coerce",
                )
                if pd.isna(rate):
                    return "자료 없음", "연속 사업 예산 코호트가 없습니다."
                status = "완전 연결" if complete else "부분 연결"
                return f"{float(rate):+.1%}", status

            t1_value, t1_help = feedback_value("t1")
            t2_value, t2_help = feedback_value("t2")
            with st.container(horizontal=True):
                st.metric(
                    "성과 미달",
                    f"{below_count}/{comparable_count}개",
                    help="프로그램 성과지표 맥락이며 세부사업 성과로 귀속하지 않습니다.",
                    border=True,
                )
                st.metric(
                    "집행률",
                    "자료 없음" if pd.isna(execution_rate) else f"{float(execution_rate):.1%}",
                    help="회계유형별 확인된 분모를 사용합니다.",
                    border=True,
                )
                st.metric("T+1 예산변화", t1_value, help=t1_help, border=True)
                st.metric("T+2 예산변화", t2_value, help=t2_help, border=True)
                st.metric(
                    "반복 신호",
                    f"{int(row['repeated_signal_family_count'])}종",
                    border=True,
                )
            st.caption(
                "T+1과 T+2는 합치지 않습니다. 성과미달 뒤 예산증가는 점검 신호로, "
                "성과양호 뒤 예산감소는 사업종료·단계전환 가능성을 확인하는 맥락으로 표시합니다."
            )
            if row["account_type"] == "FUND":
                st.warning(
                    "기금은 일반회계와 분모·잔액 운용구조가 다릅니다. 이 화면의 집행률은 "
                    "기금 내부 설명에만 사용하고 일반회계와 직접 서열 비교하지 않습니다."
                )
            st.caption(
                f"본예산 {float(row['account_original_budget']) / 100_000_000:,.1f}억원 · "
                f"집행률 "
                + (
                    "자료 없음"
                    if pd.isna(row["account_execution_rate"])
                    else f"{float(row['account_execution_rate']):.1%}"
                )
            )
            projects = project_queue.loc[project_queue["candidate_id"].eq(selected_id)].copy()
            if not projects.empty:
                st.subheader("세부사업 검토 순서")
                st.warning(
                    "프로그램 순위를 먼저 보고, 그 안에서는 데이터 검증 → 세부사업 재정신호 "
                    "→ 프로그램 구조 → 예산규모 순으로 확인합니다. 프로그램 성과를 "
                    "세부사업 성과로 귀속하지 않습니다."
                )
                total_remaining = float(projects["project_remaining_amount"].sum())
                top_remaining = float(projects["project_remaining_amount"].max())
                project_metrics = st.columns(4)
                project_metrics[0].metric("세부사업", f"{len(projects):,}개")
                project_metrics[1].metric(
                    "상위 1개 예산비중",
                    f"{projects['budget_share_within_candidate'].max():.1%}",
                )
                project_metrics[2].metric(
                    "예산현액-지출액",
                    f"{total_remaining / 100_000_000:,.1f}억원",
                )
                project_metrics[3].metric(
                    "최대 잔액 기여",
                    (
                        "해당 없음"
                        if total_remaining <= 0
                        else f"{top_remaining / total_remaining:.1%}"
                    ),
                )
                figure = _project_budget_figure(projects)
                st.pyplot(figure, width="stretch")
                plt.close(figure)
                st.dataframe(
                    _project_table_view(
                        projects.sort_values(
                            "project_review_order_within_candidate",
                        )
                    ),
                    hide_index=True,
                    width="stretch",
                    height=430,
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
            elif row["work_lane"] == "DATA_FIRST":
                st.info(
                    "이 행은 데이터 검증을 마친 뒤 세부사업 검토 순서를 연결합니다. "
                    "대기열에서 삭제된 것이 아닙니다."
                )
            action_columns = st.columns(2)
            action_columns[0].button(
                "고급 민감도 확인",
                icon=":material/compare_arrows:",
                on_click=_go_to_advanced,
                width="stretch",
                disabled=not bool(row["scenario_ranking_eligible"]),
                help=(
                    None
                    if bool(row["scenario_ranking_eligible"])
                    else "기존 가중치 민감도 산출물이 있는 행만 비교합니다."
                ),
            )
            pdf_review_available = str(row["ministry_code"]) in PDF_REVIEW_MINISTRY_CODES
            action_columns[1].button(
                "이 프로그램 PDF 원문 확인",
                icon=":material/description:",
                on_click=_go_to_review,
                args=(str(row["performance_program_name"]), str(row["ministry_code"])),
                width="stretch",
                disabled=not pdf_review_available,
                help=(
                    None
                    if pdf_review_available
                    else "중기부는 아직 공통 PDF 원문 검수 큐에 연결되지 않았습니다."
                ),
            )
            with st.expander(
                "현재 필터의 전체 업무대기열과 CSV",
                icon=":material/table_chart:",
            ):
                display_table = _table_view(joined)
                st.dataframe(
                    display_table,
                    hide_index=True,
                    width="stretch",
                    height=430,
                    column_config={
                        "본예산(억원)": st.column_config.NumberColumn(format="%.1f"),
                    },
                )
                st.download_button(
                    "현재 업무대기열 CSV 내려받기",
                    display_table.to_csv(index=False).encode("utf-8-sig"),
                    file_name="multi_ministry_review_work_queue_filtered.csv",
                    mime="text/csv",
                    icon=":material/download:",
                )

    elif workflow_step == WORKFLOW_STEPS[3] and comparison_mode == "고급 민감도":
        eligible = filtered_all.loc[filtered_all["scenario_ranking_eligible"].fillna(False)].copy()
        eligible_stability = stability.loc[
            stability["candidate_id"].isin(eligible["candidate_id"])
        ].copy()
        eligible_scores = scores.loc[scores["candidate_id"].isin(eligible["candidate_id"])].copy()
        st.subheader("기존 가중치 결과는 고급 민감도에서만 확인합니다")
        st.warning(
            "이 화면은 기본 업무순서를 만들지 않습니다. 기존 네 가중치 결과가 얼마나 "
            "달라지는지 확인하는 재현·민감도 자료입니다."
        )
        if eligible_scores.empty:
            st.warning("현재 필터에는 순위를 비교할 수 있는 후보가 없습니다.")
        else:
            rank_options = ["전체 부처"]
            if len(selected_ministries) == 1:
                rank_options.append("선택 부처 내부")
            rank_basis = st.segmented_control(
                "순위 기준",
                rank_options,
                default=rank_options[0],
            )
            within_ministry = rank_basis == "선택 부처 내부"
            top_5_column = (
                "all_scenario_top_5_within_ministry" if within_ministry else "all_scenario_top_5"
            )
            rank_scope_label = (
                f"{MINISTRY_LABELS.get(selected_ministries[0], selected_ministries[0])} 내부"
                if within_ministry
                else "전체 부처"
            )
            scenario = st.selectbox(
                "강조할 기준",
                list(SCENARIO_LABELS),
                format_func=lambda value: SCENARIO_LABELS[value],
            )
            left, right = st.columns(2)
            with left:
                figure = _rank_range_figure(
                    eligible_stability,
                    within_ministry=within_ministry,
                )
                st.pyplot(figure, width="stretch")
                plt.close(figure)
                st.caption("선이 짧을수록 네 기준을 바꿔도 순위가 안정적입니다.")
            with right:
                figure = _scenario_top_figure(
                    eligible_scores,
                    scenario,
                    within_ministry=within_ministry,
                )
                st.pyplot(figure, width="stretch")
                plt.close(figure)
                st.caption("점수는 선택한 기준 안에서 후보를 정렬하기 위한 값입니다.")
            st.warning(
                f"{rank_scope_label} 기준 현재 필터 {len(eligible_stability):,}행 중 "
                f"공통 Top 5는 "
                f"{int(eligible_stability[top_5_column].fillna(False).sum()):,}행입니다. "
                "특정 기준의 1~5위를 최종 순위로 확정하지 마세요.",
                icon=":material/warning:",
            )
            with st.expander(
                f"전체 {counts['scenario_ranking_eligible_rows']:,}행의 순위 안정성 근거",
                icon=":material/analytics:",
            ):
                figure = _spearman_figure(data["spearman"])
                st.pyplot(figure, width="stretch")
                plt.close(figure)
                all_overlap = data["overlap"].loc[
                    data["overlap"]["comparison_type"].eq("ALL_SCENARIOS")
                ]
                overlap_columns = st.columns(len(all_overlap))
                for column, overlap_row in zip(
                    overlap_columns,
                    all_overlap.itertuples(),
                    strict=True,
                ):
                    column.metric(
                        f"Top {int(overlap_row.top_k)} 공통/합집합",
                        f"{int(overlap_row.intersection_count)} / {int(overlap_row.union_count)}",
                        delta=f"Jaccard {float(overlap_row.jaccard_overlap):.2f}",
                        delta_color="off",
                    )

    elif workflow_step == WORKFLOW_STEPS[3]:
        st.subheader("사람 확인이 필요한 성과지표부터 PDF 원문으로 검수합니다")
        st.caption(
            "기본 화면은 자동 강근거 160행을 제외한 필수 검수 201행입니다. "
            "수기값과 PDF값을 나란히 보고 결과를 별도 감사 CSV에 저장합니다. "
            "현재 공통 검수 큐는 고용노동부·보건복지부·과학기술정보통신부를 지원합니다."
        )
        with st.expander("검수 전에 30초만 읽어주세요", icon=":material/help:"):
            st.markdown(
                """
                1. **불일치·모호·PDF 근거 누락 27행**을 먼저 확인합니다.
                2. **OCR 필요 174행**은 추출 텍스트가 아니라 페이지 이미지를 직접 읽습니다.
                3. `CORRECTED`를 고르면 메모에 **파일명·쪽·정확한 값**을 반드시 적습니다.
                4. `CORRECTED`는 원본값을 자동 수정하지 않습니다. 수정 오버레이 반영 전에는 순위 근거로 확정하지 않습니다.
                5. 전체 안내: `docs/THREE_MINISTRY_PERFORMANCE_REVIEW_GUIDE.md`
                """
            )
        try:
            queue = load_pdf_review_queue()
        except (FileNotFoundError, OSError, ValueError) as exc:
            st.error(str(exc))
        else:
            review_base = queue.loc[
                queue["ministry_code"].isin(selected_ministries)
                & queue["fiscal_year"].isin(selected_years)
            ].copy()
            focus_program = st.session_state.get("review_program_filter")
            focus_ministry = st.session_state.get("review_ministry_filter")
            if focus_program:
                review_base = review_base.loc[
                    review_base["performance_program_name"].eq(focus_program)
                    & review_base["ministry_code"].eq(focus_ministry)
                ]
                st.info(
                    f"후보 분석에서 선택한 **{focus_program}** 프로그램의 지표만 보고 있습니다.",
                    icon=":material/filter_alt:",
                )
                st.button(
                    "프로그램 필터 해제",
                    icon=":material/filter_alt_off:",
                    on_click=_clear_review_focus,
                )
            else:
                show_auto_strong = st.toggle(
                    "자동 강근거 160행도 표본 검수 대상으로 보기",
                    value=False,
                    help="EXACT_MATCH와 MATCH_AFTER_CHANGE까지 포함합니다.",
                )
                if not show_auto_strong:
                    review_base = review_base.loc[review_base["manual_review_required"]].copy()

            completed = int(review_base["review_status"].isin(["CONFIRMED", "CORRECTED"]).sum())
            with st.container(horizontal=True):
                st.metric("현재 검수 대상", f"{len(review_base):,}", border=True)
                st.metric("사람 검수 완료", f"{completed:,}", border=True)
                st.metric(
                    "OCR 확인 필요",
                    f"{review_base['overall_reconciliation_status'].eq('OCR_REQUIRED').sum():,}",
                    border=True,
                )
                st.metric(
                    "불일치·모호",
                    (
                        review_base["overall_reconciliation_status"]
                        .isin(["VALUE_MISMATCH", "AMBIGUOUS"])
                        .sum()
                    ),
                    border=True,
                )
            progress = 0.0 if review_base.empty else completed / len(review_base)
            st.progress(progress, text=f"사람 검수 진행률 {progress:.1%}")
            unresolved_only = st.toggle("검수하지 않은 지표만 보기", value=True)
            review_queue = review_base.copy()
            if unresolved_only:
                review_queue = review_queue.loc[
                    ~review_queue["review_status"].isin(
                        ["CONFIRMED", "CORRECTED", "NOT_RESOLVABLE"]
                    )
                ]
            review_queue = review_queue.sort_values(
                ["review_priority_order", "ministry_code", "fiscal_year"]
            )
            if review_queue.empty:
                st.success("현재 필터에서 남은 검수행이 없습니다.")
            else:
                labels = {
                    row.source_indicator_id: (
                        f"{MINISTRY_LABELS.get(str(row.ministry_code), row.ministry_code)} · "
                        f"{int(row.fiscal_year)} · {row.performance_program_name} · "
                        f"{row.manual_indicator_name_report} "
                        f"[{row.overall_reconciliation_status}]"
                    )
                    for row in review_queue.itertuples()
                }
                selected_review_id = st.selectbox(
                    "검수할 성과지표",
                    review_queue["source_indicator_id"].tolist(),
                    format_func=lambda value: labels[value],
                )
                review_row = review_queue.loc[
                    review_queue["source_indicator_id"].eq(selected_review_id)
                ].iloc[0]
                st.info(
                    str(review_row.get("review_instruction") or "근거 페이지 안내 없음"),
                    icon=":material/find_in_page:",
                )
                guidance = REVIEW_STATUS_GUIDANCE.get(
                    str(review_row["overall_reconciliation_status"]),
                    "자동 판정과 원문 근거를 함께 확인하세요.",
                )
                if bool(review_row["manual_review_required"]):
                    st.warning(guidance, icon=":material/priority_high:")
                else:
                    st.info(guidance, icon=":material/info:")
                comparison = pd.DataFrame(
                    {
                        "확인할 값": ["지표명", "계획 목표", "보고 목표", "실적", "공식 달성률"],
                        "수기 입력": [
                            review_row.get("manual_indicator_name_report"),
                            review_row.get("manual_planned_target_raw"),
                            None,
                            review_row.get("manual_actual_value_raw"),
                            review_row.get("manual_official_achievement_rate_raw"),
                        ],
                        "PDF 자동 추출": [
                            review_row.get("pdf_report_indicator_name"),
                            review_row.get("pdf_plan_target_raw"),
                            review_row.get("pdf_report_target_raw"),
                            review_row.get("pdf_report_actual_raw"),
                            review_row.get("pdf_report_official_achievement_rate_raw"),
                        ],
                    }
                )
                st.dataframe(comparison, hide_index=True, width="stretch")
                pages = review_page_specs(review_row)
                if not pages:
                    st.warning("자동으로 특정된 원문 페이지가 없습니다. 검수 사유를 확인해 주세요.")
                else:
                    page_columns = st.columns(min(len(pages), 3))
                    for column, (label, source_file, page) in zip(
                        page_columns, pages[:3], strict=True
                    ):
                        with column:
                            try:
                                image = render_pdf_page(PROJECT_ROOT, source_file, page)
                            except (FileNotFoundError, OSError, ValueError) as exc:
                                st.error(str(exc))
                            else:
                                st.image(
                                    image,
                                    caption=f"{label} · {page}쪽",
                                    width="stretch",
                                )
                with st.expander("자동 판정과 추출 근거", icon=":material/code:"):
                    st.write(f"자동 판정: {review_row['overall_reconciliation_status']}")
                    st.write(f"검수 사유: {review_row.get('review_reason')}")
                    st.code(str(review_row.get("report_source_text") or "보고서 추출 텍스트 없음"))

                with st.form("pdf_review_form"):
                    reviewer = st.text_input("검수자")
                    review_status = st.selectbox(
                        "검수 결과",
                        [value for value in REVIEW_STATUS_VALUES if value],
                        index=1,
                        format_func=lambda value: REVIEW_STATUS_LABELS[value],
                    )
                    review_note = st.text_area(
                        "검수 메모",
                        placeholder=(
                            "[파일·쪽] ... / [확인값] 계획목표=, 보고목표=, 실적=, "
                            "달성률= / [판정근거] ..."
                        ),
                    )
                    submitted = st.form_submit_button(
                        "저장하고 다음 지표 보기",
                        type="primary",
                        icon=":material/save:",
                    )
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
                        st.session_state["review_saved"] = True
                        st.rerun()

    with st.expander("분석 정의와 출처"):
        st.markdown(
            """
             - **분석 단위:** 부처 × 프로그램 × 회계연도 × 회계유형
             - **기본 업무순서:** 데이터 차단 → 반복·복수 → 강한 단일 → 단일 → 맥락 → 모니터링
             - **독립 신호:** 성과, 집행, T+1, T+2, 예산구조를 합산하지 않고 병렬 표시
             - **회계 원칙:** 일반·특별·기금을 분리하며 기금을 일반회계와 직접 서열 비교하지 않음
             - **고급 민감도:** 기존 균등·성과·집행·재정영향 가중치는 재현용으로만 보존
             - **금지 해석:** 실패·낭비·삭감 대상 자동 판정
             - **원천:** 4개 부처 수기 성과표, 3개 부처 PDF 대조 결과, 검증된 M3 재정 신호
             - **제한:** 사업별 기대 성과시차·의무지출·목비목·융자 순재정부담 미반영
             - **현재 상태:** 4개 부처 파일럿이며 검토업무 순서이지 정책효과성 순위가 아님
             """
        )
        st.code(
            "fiscal-analytics analyze-priority-scenarios --root . --overwrite",
            language="powershell",
        )
        st.caption(f"분석 생성 시각(UTC): {summary.get('generated_at', '확인 불가')}")


if __name__ == "__main__":
    main()
