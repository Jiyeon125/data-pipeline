"""중기부 점검 후보와 복수 시나리오 안정성 Streamlit 대시보드."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from matplotlib import font_manager

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path("data/analytics/mss_priority_scenarios")

ACCOUNT_LABELS = {
    "GENERAL_ACCOUNT": "일반회계",
    "SPECIAL_ACCOUNT": "특별회계",
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
    "DATA_VALIDATION": "데이터 검증",
    "FINANCIAL_LINKAGE_LIMITED": "재정 연결 제한",
    "PROGRAM_MATCH_REVIEW": "프로그램 매칭 검토",
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


class DashboardDataError(ValueError):
    """대시보드 입력 계약이 깨졌을 때 발생합니다."""


def load_dashboard_data(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """검증된 분석 산출물을 읽고 대시보드 입력 계약을 확인합니다."""
    base = root / DATA_DIR
    filenames = {
        "candidates": "candidate_population.csv",
        "scores": "scenario_scores.csv",
        "stability": "rank_stability.csv",
        "drilldown": "stable_top5_project_drilldown.csv",
        "spearman": "scenario_spearman.csv",
        "overlap": "top_k_overlap.csv",
    }
    required_paths = [base / name for name in (*filenames.values(), "analysis_summary.json")]
    missing = [path for path in required_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "대시보드 입력이 없습니다. 먼저 "
            "`fiscal-analytics analyze-mss-priority-scenarios --root . --overwrite`를 "
            f"실행하세요: {', '.join(str(path) for path in missing)}"
        )

    data: dict[str, Any] = {
        key: pd.read_csv(base / filename) for key, filename in filenames.items()
    }
    data["candidates"]["account_type"] = data["candidates"]["account_type"].fillna("NOT_AVAILABLE")
    data["summary"] = json.loads((base / "analysis_summary.json").read_text(encoding="utf-8"))
    required_columns = {
        "candidates": {
            "candidate_id",
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
    }
    for name, columns in required_columns.items():
        missing_columns = sorted(columns - set(data[name].columns))
        if missing_columns:
            raise DashboardDataError(f"{name} 입력 컬럼 누락: {missing_columns}")
    if data["candidates"]["candidate_id"].duplicated().any():
        raise DashboardDataError("후보표 candidate_id가 중복되었습니다.")
    if data["stability"]["candidate_id"].duplicated().any():
        raise DashboardDataError("안정성표 candidate_id가 중복되었습니다.")
    if data["scores"].duplicated(["candidate_id", "scenario"]).any():
        raise DashboardDataError("시나리오 점수의 후보-시나리오 키가 중복되었습니다.")
    return data


def filter_candidates(
    candidates: pd.DataFrame,
    *,
    scope: str,
    years: list[int],
    account_types: list[str],
    tiers: list[str],
) -> pd.DataFrame:
    """화면 필터만 적용하고 후보·점수 정의는 변경하지 않습니다."""
    if scope == "순위 적격 후보":
        mask = candidates["scenario_ranking_eligible"].fillna(False)
    elif scope == "전체 점검 후보":
        mask = candidates["review_candidate"].fillna(False)
    else:
        mask = pd.Series(True, index=candidates.index)
    return candidates.loc[
        mask
        & candidates["fiscal_year"].isin(years)
        & candidates["account_type"].isin(account_types)
        & candidates["priority_tier"].isin(tiers)
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


def _rank_range_figure(stability: pd.DataFrame) -> plt.Figure:
    _set_korean_font()
    plot = (
        stability.sort_values("mean_scenario_rank")
        .head(15)
        .sort_values("mean_scenario_rank", ascending=False)
    )
    labels = (
        plot["fiscal_year"].astype(str)
        + " "
        + plot["performance_program_name"].astype(str)
        + " / "
        + plot["account_type"].map(ACCOUNT_LABELS).fillna(plot["account_type"])
    )
    fig, ax = plt.subplots(figsize=(11, max(4.5, len(plot) * 0.48)))
    ax.hlines(
        range(len(plot)),
        plot["best_scenario_rank"],
        plot["worst_scenario_rank"],
        color="#9CA3AF",
        linewidth=3,
    )
    ax.scatter(
        plot["mean_scenario_rank"],
        range(len(plot)),
        color="#245A8D",
        edgecolor="#17324D",
        s=58,
        zorder=3,
    )
    ax.set_yticks(range(len(plot)), labels)
    ax.set_xlabel("시나리오 순위 (낮을수록 상위)")
    ax.set_title("후보별 시나리오 순위 범위", loc="left", fontweight="bold", pad=22)
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


def _scenario_top_figure(scores: pd.DataFrame, scenario: str) -> plt.Figure:
    _set_korean_font()
    plot = (
        scores.loc[scores["scenario"].eq(scenario)]
        .sort_values(["scenario_rank_average", "performance_program_name"])
        .head(10)
        .sort_values("scenario_score")
    )
    labels = (
        plot["fiscal_year"].astype(str)
        + " "
        + plot["performance_program_name"].astype(str)
        + " / "
        + plot["account_type"].map(ACCOUNT_LABELS).fillna(plot["account_type"])
    )
    fig, ax = plt.subplots(figsize=(9, max(4.2, len(plot) * 0.48)))
    bars = ax.barh(range(len(plot)), plot["scenario_score"], color="#D3A62C")
    ax.bar_label(bars, fmt="%.3f", padding=4, color="#263445")
    ax.set_yticks(range(len(plot)), labels)
    ax.set_xlabel("탐색 점수 (0~1)")
    ax.set_xlim(0, max(1, float(plot["scenario_score"].max()) * 1.15))
    ax.set_title(
        f"{SCENARIO_LABELS.get(scenario, scenario)} 상위 후보",
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


def _tier_figure(candidates: pd.DataFrame) -> plt.Figure:
    _set_korean_font()
    counts = candidates["priority_tier"].map(TIER_LABELS).value_counts().sort_values()
    fig, ax = plt.subplots(figsize=(6, max(3.5, len(counts) * 0.55)))
    bars = ax.barh(counts.index, counts.values, color="#245A8D")
    ax.bar_label(bars, padding=4, color="#263445")
    ax.set_xlabel("프로그램-연도-회계유형 행")
    ax.set_xlim(0, max(1, float(counts.max()) * 1.18))
    ax.set_title("점검단계 분포", loc="left", fontweight="bold", pad=22)
    ax.text(
        0,
        1.01,
        "현재 필터 기준",
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
            "project_name": "세부사업",
            "activity_name_budget_api": "단위사업",
        }
    )


def _table_view(frame: pd.DataFrame) -> pd.DataFrame:
    table = frame.copy()
    table["회계유형"] = table["account_type"].map(ACCOUNT_LABELS).fillna(table["account_type"])
    table["점검단계"] = table["priority_tier"].map(TIER_LABELS).fillna(table["priority_tier"])
    table["점검근거"] = table["priority_reason"].map(_reason_text)
    table["본예산(억원)"] = pd.to_numeric(table["account_original_budget"], errors="coerce").div(
        100_000_000
    )
    rename = {
        "fiscal_year": "연도",
        "performance_program_name": "프로그램",
        "mean_scenario_rank": "평균순위",
        "scenario_rank_range": "순위범위",
        "all_scenario_top_5": "전시나리오 Top5",
        "all_scenario_top_10": "전시나리오 Top10",
    }
    table = table.rename(columns=rename)
    columns = [
        "연도",
        "프로그램",
        "회계유형",
        "점검단계",
        "점검근거",
        "본예산(억원)",
    ]
    for optional in (
        "평균순위",
        "순위범위",
        "전시나리오 Top5",
        "전시나리오 Top10",
    ):
        if optional in table:
            columns.append(optional)
    return table[columns]


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
    for (program_code, program_name), group in stable.groupby(
        ["program_code", "performance_program_name"],
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
    return pd.DataFrame(rows).sort_values(
        ["best_mean_rank", "program_name"],
        ignore_index=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="중기부 재정사업 점검 후보",
        page_icon="🔎",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.title("중기부 재정사업 점검 후보")
    st.caption("중기부 2022–2024 파일럿 · 발표용 초안 · 최종 5개 부처 통합본 아님")

    try:
        data = load_dashboard_data()
    except (FileNotFoundError, DashboardDataError, OSError, ValueError) as exc:
        st.error(str(exc))
        st.stop()

    candidates = data["candidates"]
    stability = data["stability"]
    scores = data["scores"]
    drilldown = data["drilldown"]
    summary = data["summary"]
    counts = summary["counts"]
    top_k = summary["stability"]["all_scenario_top_k"]
    stable_programs = stable_program_summary(candidates, stability)

    st.subheader("지금 봐야 할 결과")
    st.success(
        "네 시나리오 모두에서 상위 5위에 남은 후보는 **5개 행, 3개 프로그램**입니다. "
        "따라서 아래 3개 프로그램부터 원문과 세부사업 원인을 확인하는 것이 현재의 결론입니다."
    )
    card_columns = st.columns(len(stable_programs))
    for column, row in zip(card_columns, stable_programs.itertuples(), strict=True):
        with column.container(border=True):
            st.markdown(f"**{row.program_name}**")
            st.caption(f"전 시나리오 Top 5 · {row.stable_row_count}개 행")
            st.write(row.observations)
            st.write(f"점검 근거: {row.reasons}")
    st.caption(
        "프로그램 자체의 확정 순위가 아니라, 여러 연도·회계 행 중 가중치를 바꿔도 "
        "상위권에 남은 행을 프로그램명으로 묶은 보기입니다."
    )

    st.sidebar.header("필터")
    scope = st.sidebar.radio(
        "보기 범위",
        ["순위 적격 후보", "전체 점검 후보", "데이터 검증 포함 전체"],
    )
    years = sorted(candidates["fiscal_year"].dropna().astype(int).unique().tolist())
    selected_years = st.sidebar.multiselect("회계연도", years, default=years)
    account_types = sorted(candidates["account_type"].dropna().astype(str).unique())
    selected_accounts = st.sidebar.multiselect(
        "회계유형",
        account_types,
        default=account_types,
        format_func=_format_account,
    )
    tiers = sorted(
        candidates["priority_tier"].dropna().astype(str).unique(),
        key=lambda value: list(TIER_LABELS).index(value),
    )
    selected_tiers = st.sidebar.multiselect(
        "점검단계",
        tiers,
        default=tiers,
        format_func=lambda value: TIER_LABELS.get(value, value),
    )
    filtered = filter_candidates(
        candidates,
        scope=scope,
        years=selected_years,
        account_types=selected_accounts,
        tiers=selected_tiers,
    )
    filtered_stability = stability.loc[
        stability["candidate_id"].isin(filtered["candidate_id"])
    ].copy()
    filtered_scores = scores.loc[scores["candidate_id"].isin(filtered["candidate_id"])].copy()

    metric_columns = st.columns(4)
    metric_columns[0].metric("점검 후보", f"{counts['review_candidate_rows']:,}행")
    metric_columns[1].metric("순위 비교 가능", f"{counts['scenario_ranking_eligible_rows']:,}행")
    metric_columns[2].metric("안정 상위", f"{len(stable_programs):,}개 프로그램")
    metric_columns[3].metric("데이터 검증 우선", f"{counts['data_review_rows']:,}행")

    summary_tab, candidates_tab, scenario_tab, quality_tab = st.tabs(
        ["핵심 요약", "후보 찾아보기", "시나리오 비교", "데이터 검증"]
    )
    with summary_tab:
        left, right = st.columns([2, 1])
        with left:
            figure = _rank_range_figure(stability)
            st.pyplot(figure, width="stretch")
            plt.close(figure)
        with right:
            st.markdown("#### 이렇게 읽으시면 됩니다")
            st.markdown(
                f"""
                1. **상위 5위는 안정적입니다.** 공통 {top_k["5"]["intersection_count"]}행,
                   합집합 {top_k["5"]["union_count"]}행입니다.
                2. **상위 10위 경계는 흔들립니다.** 공통 {top_k["10"]["intersection_count"]}행,
                   합집합 {top_k["10"]["union_count"]}행입니다.
                3. **가중치 영향은 후보마다 다릅니다.** 선이 길수록 시나리오 변경에
                   따라 순위가 크게 달라집니다.
                """
            )
            st.warning(
                "상위 3개 프로그램은 우선 원문 검토 대상으로 쓸 수 있지만, "
                "그 아래 순서를 하나의 최종 순위처럼 사용하면 안 됩니다."
            )
        st.markdown("#### 아직 완성되지 않은 부분")
        st.info(
            "현재는 중기부 파일럿입니다. 안정 상위 후보의 세부사업 재정 드릴다운은 "
            "연결됐지만, 성과지표 유형·자율평가 의견과 나머지 부처 데이터가 "
            "추가되어야 최종 대시보드가 됩니다."
        )

    with candidates_tab:
        if filtered.empty:
            st.warning("현재 필터에 해당하는 후보가 없습니다.")
        else:
            st.caption(
                f"현재 필터: {len(filtered)}행 · "
                f"{filtered['program_code'].dropna().nunique()}개 프로그램"
            )
            left, right = st.columns(2)
            with left:
                if filtered_stability.empty:
                    st.warning("현재 필터에는 시나리오 순위 적격 후보가 없습니다.")
                else:
                    figure = _rank_range_figure(filtered_stability)
                    st.pyplot(figure, width="stretch")
                    plt.close(figure)
            with right:
                figure = _tier_figure(filtered)
                st.pyplot(figure, width="stretch")
                plt.close(figure)

            joined = filtered.merge(
                stability[
                    [
                        "candidate_id",
                        "mean_scenario_rank",
                        "scenario_rank_range",
                        "all_scenario_top_5",
                        "all_scenario_top_10",
                    ]
                ],
                on="candidate_id",
                how="left",
                validate="one_to_one",
            ).sort_values(
                ["mean_scenario_rank", "priority_tier_order", "account_original_budget"],
                ascending=[True, True, False],
                na_position="last",
            )
            st.subheader("후보를 골라 근거 확인")
            stable_ids = set(
                stability.loc[
                    stability["all_scenario_top_5"].fillna(False),
                    "candidate_id",
                ]
            )
            option_frame = filtered.assign(
                stable_top5=filtered["candidate_id"].isin(stable_ids)
            ).sort_values(
                [
                    "stable_top5",
                    "scenario_ranking_eligible",
                    "priority_tier_order",
                    "account_original_budget",
                ],
                ascending=[False, False, True, False],
            )
            option_ids = option_frame["candidate_id"].tolist()
            option_labels = {
                row.candidate_id: (
                    f"{int(row.fiscal_year)} {row.performance_program_name} / "
                    f"{_format_account(row.account_type)}"
                )
                for row in option_frame.itertuples()
            }
            selected_id = st.selectbox(
                "후보 선택",
                option_ids,
                format_func=lambda value: option_labels[value],
            )
            row = candidates.loc[candidates["candidate_id"].eq(selected_id)].iloc[0]
            st.write(
                f"**점검 단계:** {TIER_LABELS.get(row['priority_tier'], row['priority_tier'])}"
            )
            st.write(f"**점검 근거:** {_reason_text(row['priority_reason'])}")
            detail_metrics = st.columns(4)
            component_specs = [
                ("성과미달 비중", "performance_gap"),
                ("집행관리 신호", "execution_management"),
                ("성과·예산 불일치", "budget_performance_mismatch"),
                ("재정영향도", "fiscal_impact"),
            ]
            for column, (label, field) in zip(detail_metrics, component_specs, strict=True):
                value = pd.to_numeric(pd.Series([row.get(field)]), errors="coerce").iloc[0]
                column.metric(label, "자료 없음" if pd.isna(value) else f"{value:.2f}")

            candidate_scores = scores.loc[scores["candidate_id"].eq(selected_id)].copy()
            if candidate_scores.empty:
                st.warning("이 행은 데이터 또는 구성요소 제한으로 시나리오 순위에서 제외됩니다.")
            else:
                candidate_scores["시나리오"] = candidate_scores["scenario"].map(SCENARIO_LABELS)
                candidate_scores = candidate_scores.rename(
                    columns={
                        "scenario_score": "탐색점수",
                        "scenario_rank_average": "순위",
                    }
                )
                st.dataframe(
                    candidate_scores[["시나리오", "탐색점수", "순위"]].sort_values("순위"),
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "탐색점수": st.column_config.NumberColumn(format="%.3f"),
                        "순위": st.column_config.NumberColumn(format="%.1f"),
                    },
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
            projects = drilldown.loc[drilldown["candidate_id"].eq(selected_id)].copy()
            st.subheader("세부사업 재정 원인")
            if projects.empty:
                st.info("세부사업 원인표는 현재 전 시나리오 Top 5 후보에만 준비되어 있습니다.")
            else:
                st.warning(
                    "프로그램 성과미달을 아래 세부사업의 성과로 귀속하지 않습니다. "
                    "아래 표는 예산구성·집행·이월·불용 원인을 확인하는 용도입니다."
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
                            "project_remaining_amount",
                            ascending=False,
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
            with st.expander("현재 필터의 전체 후보표와 CSV"):
                display_table = _table_view(joined)
                st.dataframe(
                    display_table,
                    hide_index=True,
                    width="stretch",
                    height=430,
                    column_config={
                        "본예산(억원)": st.column_config.NumberColumn(format="%.1f"),
                        "평균순위": st.column_config.NumberColumn(format="%.1f"),
                        "순위범위": st.column_config.NumberColumn(format="%.1f"),
                    },
                )
                st.download_button(
                    "현재 후보표 CSV 내려받기",
                    display_table.to_csv(index=False).encode("utf-8-sig"),
                    file_name="mss_priority_candidates_filtered.csv",
                    mime="text/csv",
                )

    with scenario_tab:
        if filtered_scores.empty:
            st.warning("현재 필터에는 시나리오 순위 적격 후보가 없습니다.")
        else:
            left, right = st.columns(2)
            with left:
                scenario = st.selectbox(
                    "상위 후보 시나리오",
                    list(SCENARIO_LABELS),
                    format_func=lambda value: SCENARIO_LABELS[value],
                )
                figure = _scenario_top_figure(filtered_scores, scenario)
                st.pyplot(figure, width="stretch")
                plt.close(figure)
            with right:
                figure = _spearman_figure(data["spearman"])
                st.pyplot(figure, width="stretch")
                plt.close(figure)
            all_overlap = data["overlap"].loc[
                data["overlap"]["comparison_type"].eq("ALL_SCENARIOS")
            ]
            overlap_columns = st.columns(len(all_overlap))
            for column, row in zip(overlap_columns, all_overlap.itertuples(), strict=True):
                column.metric(
                    f"Top {int(row.top_k)} 공통/합집합",
                    f"{int(row.intersection_count)} / {int(row.union_count)}",
                    delta=f"Jaccard {float(row.jaccard_overlap):.2f}",
                    delta_color="off",
                )
            st.caption(
                "순위상관과 Top K 중복은 전체 38개 순위 적격 행 기준입니다. "
                "상위 5행은 3개 고유 프로그램의 여러 연도·회계를 포함합니다."
            )

    with quality_tab:
        review = candidates.loc[candidates["data_validation_signal"].fillna(False)].copy()
        st.subheader(f"정책 신호보다 먼저 확인할 데이터 검증 {len(review)}행")
        st.dataframe(
            _table_view(
                review.sort_values(["fiscal_year", "performance_program_name", "account_type"])
            ),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "재정 연결 제한 또는 프로그램 매칭 검토 행은 순위에서 제외했으며 "
            "결측을 0점으로 대체하지 않았습니다."
        )

    with st.expander("분석 정의와 출처"):
        st.markdown(
            """
            - **분석 단위:** 부처 × 프로그램 × 회계연도 × 회계유형
            - **시나리오:** 균등가중, 성과중심, 집행중심, 재정영향 보정
            - **금지 해석:** 실패·낭비·삭감 대상 자동 판정
             - **원천:** 중기부 수기 검수 성과표와 검증된 M3 재정 신호
             - **드릴다운:** 안정 상위 5행의 세부사업 94행, 금액 합계 보존
             - **제한:** 성과지표 유형·자율평가 의견 미포함, 특별회계 소표본
             - **현재 상태:** 중기부 파일럿 발표용 초안, 최종 통합 대시보드 아님
             """
        )
        st.code(
            "fiscal-analytics analyze-mss-priority-scenarios --root . --overwrite",
            language="powershell",
        )
        st.caption(f"분석 생성 시각(UTC): {summary.get('generated_at', '확인 불가')}")


if __name__ == "__main__":
    main()
