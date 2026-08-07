"""설명요구 점수 — 로그 Lift 가중 파일럿.

가중치 산식
    lift_i = P(미래확인 | 신호_i=1) / P(미래확인 | 신호_i=0)
    w_i    = max(0, ln(lift_i))
    score  = 100 × Σ (w_i · x_i) / Σ w_i

미래확인(strict)
    다음 해 성과미달 OR 집행률<0.80 OR 레인이 REPEATED/STRONG

예산 규모는 점수에 넣지 않습니다. 부처×연도 백분위는 타이브레이크만.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

LANE_ORDER = {
    "DATA_QUEUE": 0,
    "URGENT": 1,
    "PRIORITY": 2,
    "REVIEW": 3,
    "MONITOR": 4,
}
EVIDENCE_ORDER = {"CONFIRMED": 0, "LIMITED": 1, "DATA_BLOCKED": 2}
OUTCOME_COL = "future_confirmed_strict"
MIN_FLAG_N = 8
MIN_NONFLAG_N = 8


@dataclass(frozen=True)
class ExplanationNeedPaths:
    work_queue: Path
    output_dir: Path

    @classmethod
    def from_root(cls, root: Path) -> ExplanationNeedPaths:
        return cls(
            work_queue=root
            / "data/analytics/multi_ministry_priority_scenarios"
            / "full_population_review_work_queue.csv",
            output_dir=root / "data/analytics/explanation_need_score",
        )


class ExplanationNeedScoreError(ValueError):
    """설명요구 점수 입력·검증 조건이 깨졌을 때 발생합니다."""


def _as_bool(series: pd.Series) -> pd.Series:
    return series.astype("boolean").fillna(False).astype(bool)


def _signal_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    """점수 성분 x_i (0/1)."""
    result = frame.copy()
    rate = pd.to_numeric(result["account_execution_rate"], errors="coerce")
    gap = pd.to_numeric(result["performance_gap"], errors="coerce")
    feedback = _as_bool(result["low_performance_budget_increase_t1"]) | _as_bool(
        result["low_performance_budget_increase_t2"]
    )
    if "independent_signal_family_count" in result.columns:
        indep = pd.to_numeric(result["independent_signal_family_count"], errors="coerce")
    else:
        indep = (
            gap.fillna(0).gt(0).astype(int)
            + rate.lt(0.90).fillna(False).astype(int)
            + feedback.astype(int)
        )

    result["x_repeated_execution"] = _as_bool(result["repeated_execution_signal"]).astype(int)
    # 강/중 구간을 나누면 소표본에서 가중치가 뒤집힐 수 있어 집행은 하나로 추정한다.
    result["x_execution_low"] = rate.lt(0.90).fillna(False).astype(int)
    result["x_performance_gap"] = gap.fillna(0).gt(0).astype(int)
    result["x_feedback_increase"] = feedback.astype(int)
    result["x_multiple_independent"] = indep.fillna(0).ge(2).astype(int)
    return result


SIGNAL_COLUMNS = (
    "x_repeated_execution",
    "x_execution_low",
    "x_performance_gap",
    "x_feedback_increase",
    "x_multiple_independent",
)

SIGNAL_LABELS = {
    "x_repeated_execution": "repeated_execution",
    "x_execution_low": "execution_low",
    "x_performance_gap": "performance_gap",
    "x_feedback_increase": "feedback_increase",
    "x_multiple_independent": "multiple_independent",
}


def build_weight_panel(work_queue: pd.DataFrame) -> pd.DataFrame:
    """연도 t 신호 → t+1 미래확인 패널."""
    frame = _signal_matrix(work_queue)
    frame["fiscal_year"] = pd.to_numeric(frame["fiscal_year"], errors="coerce").astype(int)
    frame["panel_key"] = (
        frame["ministry_code"].astype(str)
        + "|"
        + frame["program_code"].fillna(frame["program_name_normalized"]).astype(str)
        + "|"
        + frame["account_type"].astype(str)
    )
    cols = [
        "panel_key",
        "fiscal_year",
        "candidate_id",
        *SIGNAL_COLUMNS,
        "performance_gap",
        "account_execution_rate",
        "review_intensity",
        "independent_signal_family_count",
    ]
    base = frame[cols].copy()
    nxt = frame[
        [
            "panel_key",
            "fiscal_year",
            "performance_gap",
            "account_execution_rate",
            "review_intensity",
            "candidate_id",
        ]
    ].copy()
    nxt["fiscal_year"] = nxt["fiscal_year"] - 1
    nxt = nxt.rename(
        columns={
            "performance_gap": "next_gap",
            "account_execution_rate": "next_exec",
            "review_intensity": "next_lane",
            "candidate_id": "next_candidate_id",
        }
    )
    panel = base.merge(
        nxt[
            [
                "panel_key",
                "fiscal_year",
                "next_gap",
                "next_exec",
                "next_lane",
                "next_candidate_id",
            ]
        ],
        on=["panel_key", "fiscal_year"],
        how="inner",
    )
    panel = panel[panel["fiscal_year"].isin([2022, 2023])].copy()
    panel[OUTCOME_COL] = (
        panel["next_gap"].fillna(0).gt(0)
        | panel["next_exec"].lt(0.80)
        | panel["next_lane"].isin(["REPEATED_OR_MULTIPLE", "STRONG_SINGLE"])
    )
    return panel


def estimate_log_lift_weights(panel: pd.DataFrame) -> tuple[dict[str, float], pd.DataFrame]:
    """w_i = max(0, ln(P1/P0)). lift<=1 이면 가중치 0."""
    rows: list[dict[str, Any]] = []
    weights: dict[str, float] = {}
    outcome = panel[OUTCOME_COL].astype(bool)
    for col in SIGNAL_COLUMNS:
        flag = panel[col].astype(bool)
        n1 = int(flag.sum())
        n0 = int((~flag).sum())
        p1 = float(outcome[flag].mean()) if n1 else float("nan")
        p0 = float(outcome[~flag].mean()) if n0 else float("nan")
        if n1 < MIN_FLAG_N or n0 < MIN_NONFLAG_N or not (p0 > 0) or not (p1 >= 0):
            lift = float("nan")
            w_raw = 0.0
            status = "excluded_small_sample_or_undefined"
        else:
            lift = p1 / p0
            w_raw = max(0.0, math.log(lift))
            status = "active" if w_raw > 0 else "excluded_lift_le_1"
        weights[col] = w_raw
        rows.append(
            {
                "signal": SIGNAL_LABELS[col],
                "column": col,
                "n_flagged": n1,
                "n_not_flagged": n0,
                "confirm_rate_flagged": p1,
                "confirm_rate_not_flagged": p0,
                "lift": None if math.isnan(lift) else lift,
                "log_lift_weight_raw": w_raw,
                "status": status,
                "note": (
                    "feedback는 t→t+1 예산정보를 쓰므로 누수 가능성이 있음. "
                    "계수 해석 시 주의."
                    if col == "x_feedback_increase"
                    else ""
                ),
            }
        )

    active_sum = sum(weights.values())
    for row in rows:
        col = row["column"]
        raw = weights[col]
        row["weight_share"] = (raw / active_sum) if active_sum > 0 else 0.0
        # 표용 정수 포인트: 모든 활성 성분 합이 100
        row["display_points"] = round(100 * row["weight_share"]) if raw > 0 else 0

    # 반올림 오차 보정: display_points 합을 100에 맞춤
    table = pd.DataFrame(rows)
    active = table["display_points"] > 0
    if active.any():
        drift = 100 - int(table.loc[active, "display_points"].sum())
        if drift != 0:
            idx = table.loc[active, "log_lift_weight_raw"].idxmax()
            table.loc[idx, "display_points"] += drift

    # 실제 점수 계산은 raw log-lift 사용 (수학식과 동일)
    return weights, table


def assign_scores(frame: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    result = _signal_matrix(frame)
    weight_sum = sum(max(0.0, w) for w in weights.values())
    if weight_sum <= 0:
        raise ExplanationNeedScoreError("활성 로그 Lift 가중치가 없습니다.")

    weighted = np.zeros(len(result), dtype=float)
    for col, weight in weights.items():
        if weight <= 0:
            result[f"comp_{SIGNAL_LABELS[col]}"] = 0.0
            continue
        contrib = result[col].astype(float) * weight
        # 0~100 스케일의 성분 기여
        result[f"comp_{SIGNAL_LABELS[col]}"] = 100.0 * contrib / weight_sum
        weighted += contrib

    result["explanation_need_score"] = (100.0 * weighted / weight_sum).clip(0, 100)
    result["explanation_need_score_rounded"] = result["explanation_need_score"].round(1)

    def component_list(row: pd.Series) -> str:
        names = []
        for col in SIGNAL_COLUMNS:
            if row[col] and weights.get(col, 0) > 0:
                names.append(SIGNAL_LABELS[col].upper())
        return ";".join(names) or "NONE"

    result["score_components"] = result.apply(component_list, axis=1)
    result["score_formula"] = "100 * sum(w_i * x_i) / sum(w_i), w_i=max(0,ln(lift_i))"
    return result


def assign_score_lane(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    score = result["explanation_need_score"]
    lane = pd.Series("MONITOR", index=result.index, dtype="object")
    lane.loc[score.ge(1) & score.lt(40)] = "REVIEW"
    lane.loc[score.ge(40) & score.lt(70)] = "PRIORITY"
    lane.loc[score.ge(70)] = "URGENT"
    data_flag = _as_bool(result["data_validation_signal"])
    lane.loc[data_flag] = "DATA_QUEUE"
    result["score_lane"] = lane
    result["score_lane_order"] = result["score_lane"].map(LANE_ORDER)
    result["budget_review_eligible"] = ~data_flag
    return result


def rank_explanation_need(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    budget = pd.to_numeric(result["account_original_budget"], errors="coerce")
    result["budget_pct_within_ministry_year"] = budget.groupby(
        [result["ministry_code"], result["fiscal_year"]],
        dropna=False,
    ).rank(pct=True, method="average")
    result["_evidence_order"] = result["evidence_status"].map(EVIDENCE_ORDER).fillna(3)
    result["_budget_tie"] = -result["budget_pct_within_ministry_year"].fillna(0.0)
    result = result.sort_values(
        [
            "score_lane_order",
            "explanation_need_score",
            "_evidence_order",
            "_budget_tie",
            "candidate_id",
        ],
        ascending=[True, False, True, True, True],
        ignore_index=True,
    )
    result["score_queue_order"] = range(1, len(result) + 1)
    result["score_lane_rank"] = result.groupby("score_lane").cumcount() + 1
    ministry_sorted = result.sort_values(
        [
            "ministry_code",
            "score_lane_order",
            "explanation_need_score",
            "_evidence_order",
            "_budget_tie",
            "candidate_id",
        ],
        ascending=[True, True, False, True, True, True],
    )
    result["score_queue_order_within_ministry"] = (
        ministry_sorted.groupby("ministry_code").cumcount().add(1).reindex(result.index)
    )
    return result.drop(columns=["_evidence_order", "_budget_tie"])


def compare_with_legacy(frame: pd.DataFrame) -> dict[str, Any]:
    legacy_rank = pd.to_numeric(frame["work_queue_order"], errors="coerce")
    new_rank = pd.to_numeric(frame["score_queue_order"], errors="coerce")
    spearman = legacy_rank.rank().corr(new_rank.rank())

    def top_ids(order_col: str, k: int) -> set[str]:
        return set(frame.nsmallest(k, order_col)["candidate_id"].astype(str))

    overlaps = {}
    for k in (10, 20, 50):
        old = top_ids("work_queue_order", k)
        new = top_ids("score_queue_order", k)
        overlaps[str(k)] = {
            "intersection": len(old & new),
            "jaccard": len(old & new) / len(old | new) if old or new else None,
        }
    return {
        "spearman_legacy_vs_score_queue": None if pd.isna(spearman) else float(spearman),
        "top_k_overlap": overlaps,
        "legacy_intensity_counts": frame["review_intensity"].value_counts().to_dict(),
        "score_lane_counts": frame["score_lane"].value_counts().to_dict(),
        "score_describe": {
            "mean": float(frame["explanation_need_score"].mean()),
            "median": float(frame["explanation_need_score"].median()),
            "p90": float(frame["explanation_need_score"].quantile(0.9)),
            "max": float(frame["explanation_need_score"].max()),
            "nonzero_share": float(frame["explanation_need_score"].gt(0).mean()),
        },
    }


def highlight_pilot_cases(frame: pd.DataFrame) -> pd.DataFrame:
    focus = {
        "075:2023:보건:보건의료:4000:RESPONSIBLE_OPERATION_ACCOUNT": "국립춘천병원",
        "075:2023:보건:보건의료:4100:RESPONSIBLE_OPERATION_ACCOUNT": "국립공주병원",
        "019:2022:사회복지:노동:4000:FUND": "산재보험",
        "102:2022:산업·중소기업및에너지:중소기업및소상공인육성:4100:FUND": "소상공인·전통시장지원",
        "075:2024:사회복지:노인:2200:GENERAL_ACCOUNT": "노인의료보장(반례)",
    }
    hit = frame[frame["candidate_id"].isin(focus)].copy()
    hit["pilot_label"] = hit["candidate_id"].map(focus)
    cols = [
        "pilot_label",
        "candidate_id",
        "ministry_name",
        "fiscal_year",
        "performance_program_name",
        "account_type",
        "explanation_need_score_rounded",
        "score_components",
        "score_lane",
        "score_queue_order",
        "review_intensity",
        "work_queue_order",
        "evidence_status",
    ]
    return hit[cols].sort_values("score_queue_order")


def run_explanation_need_score(paths: ExplanationNeedPaths) -> dict[str, Any]:
    if not paths.work_queue.exists():
        raise ExplanationNeedScoreError(f"입력 대기열이 없습니다: {paths.work_queue}")

    raw = pd.read_csv(paths.work_queue)
    required = {
        "candidate_id",
        "ministry_code",
        "fiscal_year",
        "account_execution_rate",
        "performance_gap",
        "repeated_execution_signal",
        "low_performance_budget_increase_t1",
        "low_performance_budget_increase_t2",
        "data_validation_signal",
        "evidence_status",
        "account_original_budget",
        "review_intensity",
        "work_queue_order",
        "program_code",
        "program_name_normalized",
        "account_type",
    }
    missing = sorted(required - set(raw.columns))
    if missing:
        raise ExplanationNeedScoreError(f"필수 컬럼 없음: {missing}")

    panel = build_weight_panel(raw)
    weights, weight_table = estimate_log_lift_weights(panel)
    scored = assign_scores(raw, weights)
    scored = assign_score_lane(scored)
    scored = rank_explanation_need(scored)
    comparison = compare_with_legacy(scored)
    pilots = highlight_pilot_cases(scored)

    paths.output_dir.mkdir(parents=True, exist_ok=True)
    queue_path = paths.output_dir / "explanation_need_work_queue.csv"
    budget_queue_path = paths.output_dir / "budget_review_work_queue.csv"
    pilots_path = paths.output_dir / "pilot_cases_under_new_score.csv"
    weights_path = paths.output_dir / "log_lift_weights.csv"
    panel_path = paths.output_dir / "weight_estimation_panel.csv"
    summary_path = paths.output_dir / "summary.json"

    scored.to_csv(queue_path, index=False)
    scored.loc[scored["budget_review_eligible"]].to_csv(budget_queue_path, index=False)
    pilots.to_csv(pilots_path, index=False)
    weight_table.to_csv(weights_path, index=False)
    panel.to_csv(panel_path, index=False)

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "pilot_log_lift_weights",
        "formula": {
            "lift_i": "P(future_confirmed_strict | x_i=1) / P(future_confirmed_strict | x_i=0)",
            "w_i": "max(0, ln(lift_i))",
            "score": "100 * sum(w_i * x_i) / sum(w_i)",
            "future_confirmed_strict": (
                "next_year performance_gap>0 OR execution_rate<0.80 "
                "OR lane in {REPEATED_OR_MULTIPLE, STRONG_SINGLE}"
            ),
            "panel_n": len(panel),
            "base_years": [2022, 2023],
        },
        "weights_raw_log_lift": {SIGNAL_LABELS[k]: v for k, v in weights.items()},
        "weights_table": weight_table.to_dict(orient="records"),
        "lane_thresholds": {
            "URGENT": ">=70",
            "PRIORITY": "40-69",
            "REVIEW": "1-39",
            "MONITOR": "0",
        },
        "design": {
            "budget_in_score": False,
            "budget_tiebreak": "within_ministry_year_percentile_only",
            "data_queue_separated": True,
            "legacy_intensity_kept_for_comparison": True,
            "hand_tuned_points": False,
        },
        "counts": {
            "rows": len(scored),
            "budget_review_rows": int(scored["budget_review_eligible"].sum()),
            "score_lane": scored["score_lane"].value_counts().to_dict(),
        },
        "comparison_with_legacy": comparison,
        "pilot_cases": pilots.to_dict(orient="records"),
        "output_paths": [
            str(queue_path),
            str(budget_queue_path),
            str(pilots_path),
            str(weights_path),
            str(panel_path),
            str(summary_path),
        ],
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
