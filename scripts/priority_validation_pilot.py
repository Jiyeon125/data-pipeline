"""파일럿: 사례 수치 대조 + 시간순 확인율·Lift (데분 프로세스 업그레이드용)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = (
    ROOT
    / "data/analytics/multi_ministry_priority_scenarios/full_population_review_work_queue.csv"
)
OUT = ROOT / "data/analytics/priority_validation_pilot"

CASE_DEFS = [
    {
        "label": "국립춘천병원 2023",
        "candidate_id": "075:2023:보건:보건의료:4000:RESPONSIBLE_OPERATION_ACCOUNT",
        "card": {
            "gap": 1.0,
            "exec": 0.5637,
            "t1_change": 0.0857,
            "lane": "REPEATED_OR_MULTIPLE",
            "order": 13,
            "evidence": "CONFIRMED",
            "fb_t1": True,
        },
    },
    {
        "label": "국립공주병원 2023",
        "candidate_id": "075:2023:보건:보건의료:4100:RESPONSIBLE_OPERATION_ACCOUNT",
        "card": {
            "gap": 1.0,
            "exec": 0.8547,
            "t1_change": 0.0301,
            "lane": "REPEATED_OR_MULTIPLE",
            "order": 12,
            "evidence": "CONFIRMED",
            "fb_t1": True,
        },
    },
    {
        "label": "산재보험 2022",
        "candidate_id": "019:2022:사회복지:노동:4000:FUND",
        "card": {
            "gap": 0.5,
            "exec": 0.9376,
            "t1_change": 0.0870,
            "lane": "REPEATED_OR_MULTIPLE",
            "order": 133,
            "evidence": "LIMITED",
            "fb_t1": True,
        },
    },
    {
        "label": "소상공인·전통시장지원 2022",
        "candidate_id": "102:2022:산업·중소기업및에너지:중소기업및소상공인육성:4100:FUND",
        "card": {
            "gap": 1.0,
            "exec": 0.9998,
            "t1_change": -0.9173,
            "lane": "STRONG_SINGLE",
            "order": 144,
            "evidence": "LIMITED",
            "fb_t1": False,
        },
    },
    {
        "label": "노인의료보장 2024 (반례)",
        "candidate_id": "075:2024:사회복지:노인:2200:GENERAL_ACCOUNT",
        "card": {
            "gap": 0.0,
            "exec": 0.9984,
            "t1_change": None,
            "lane": "CONTEXT_REVIEW",
            "order": 220,
            "evidence": "CONFIRMED",
            "fb_t1": False,
        },
    },
]


def approx_eq(a, b, tol=0.02) -> bool:
    if a is None or (isinstance(a, float) and np.isnan(a)):
        return b is None or (isinstance(b, float) and np.isnan(b))
    if b is None or (isinstance(b, float) and np.isnan(b)):
        return False
    return abs(float(a) - float(b)) <= tol


def verify_cases(wq: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for case in CASE_DEFS:
        hit = wq.loc[wq["candidate_id"].eq(case["candidate_id"])]
        if hit.empty:
            rows.append({"label": case["label"], "status": "MISSING", "failed_checks": "id"})
            continue
        r = hit.iloc[0]
        card = case["card"]
        checks = {
            "lane": r["review_intensity"] == card["lane"],
            "order": int(r["work_queue_order"]) == card["order"],
            "evidence": r["evidence_status"] == card["evidence"],
            "gap": approx_eq(r["performance_gap"], card["gap"]),
            "exec": approx_eq(r["account_execution_rate"], card["exec"]),
            "fb_t1": bool(r["low_performance_budget_increase_t1"]) == bool(card["fb_t1"]),
            "t1_change": True
            if card["t1_change"] is None
            else approx_eq(r["program_total_budget_change_rate_t1"], card["t1_change"]),
        }
        rows.append(
            {
                "label": case["label"],
                "status": "OK" if all(checks.values()) else "CHECK",
                "candidate_id": case["candidate_id"],
                "lane": r["review_intensity"],
                "work_queue_order": int(r["work_queue_order"]),
                "evidence_status": r["evidence_status"],
                "performance_gap": float(r["performance_gap"])
                if pd.notna(r["performance_gap"])
                else None,
                "execution_rate": float(r["account_execution_rate"])
                if pd.notna(r["account_execution_rate"])
                else None,
                "t1_budget_change": float(r["program_total_budget_change_rate_t1"])
                if pd.notna(r["program_total_budget_change_rate_t1"])
                else None,
                "fb_t1": bool(r["low_performance_budget_increase_t1"]),
                "failed_checks": ",".join(k for k, v in checks.items() if not v),
            }
        )
    return pd.DataFrame(rows)


def build_panel(wq: pd.DataFrame) -> pd.DataFrame:
    frame = wq.copy()
    frame["panel_key"] = (
        frame["ministry_code"].astype(str)
        + "|"
        + frame["program_code"].fillna(frame["program_name_normalized"]).astype(str)
        + "|"
        + frame["account_type"].astype(str)
    )
    # 올해 알 수 있는 신호만 (미래 예산 환류 제외)
    frame["sig_performance"] = frame["performance_gap"].fillna(0).gt(0)
    frame["sig_execution"] = frame["account_execution_rate"].lt(0.90)
    frame["sig_repeated"] = frame["repeated_execution_signal"].astype(bool)
    frame["sig_any_core"] = (
        frame["sig_performance"] | frame["sig_execution"] | frame["sig_repeated"]
    )
    frame["flagged_queue"] = frame["review_intensity"].isin(
        ["REPEATED_OR_MULTIPLE", "STRONG_SINGLE", "SINGLE_REVIEW"]
    )

    cols = [
        "panel_key",
        "fiscal_year",
        "candidate_id",
        "ministry_name",
        "performance_program_name",
        "performance_gap",
        "account_execution_rate",
        "independent_signal_family_count",
        "review_intensity",
        "account_original_budget",
        "work_queue_order",
        "sig_performance",
        "sig_execution",
        "sig_repeated",
        "sig_any_core",
        "flagged_queue",
    ]
    base = frame[cols].copy()
    nxt = frame[cols].copy()
    nxt["fiscal_year"] = nxt["fiscal_year"] - 1
    nxt = nxt.rename(
        columns={
            "performance_gap": "next_gap",
            "account_execution_rate": "next_exec",
            "independent_signal_family_count": "next_indep",
            "review_intensity": "next_lane",
            "candidate_id": "next_candidate_id",
            "work_queue_order": "next_order",
        }
    )
    panel = base.merge(
        nxt[
            [
                "panel_key",
                "fiscal_year",
                "next_gap",
                "next_exec",
                "next_indep",
                "next_lane",
                "next_candidate_id",
                "next_order",
            ]
        ],
        on=["panel_key", "fiscal_year"],
        how="inner",
    )
    panel = panel[panel["fiscal_year"].isin([2022, 2023])].copy()
    # 넓은 확인: 내년에 뭔가 볼 거리가 남음
    panel["future_confirmed"] = (
        panel["next_gap"].fillna(0).gt(0)
        | panel["next_exec"].lt(0.90)
        | panel["next_indep"].fillna(0).ge(1)
        | panel["next_lane"].isin(
            [
                "REPEATED_OR_MULTIPLE",
                "STRONG_SINGLE",
                "SINGLE_REVIEW",
                "CONTEXT_REVIEW",
                "DATA_FIRST",
            ]
        )
    )
    # 빡센 확인: 내년에도 성과미달/강한 저집행/반복·강단일 레인
    panel["future_confirmed_strict"] = (
        panel["next_gap"].fillna(0).gt(0)
        | panel["next_exec"].lt(0.80)
        | panel["next_lane"].isin(["REPEATED_OR_MULTIPLE", "STRONG_SINGLE"])
    )
    return panel


def top_precision(panel: pd.DataFrame, flag: str, outcome: str, k: int = 20) -> dict:
    base_rate = panel[outcome].mean()
    if flag == "flagged_queue":
        top = panel.sort_values("work_queue_order").head(k)
    else:
        top = (
            panel[panel[flag]]
            .sort_values("account_original_budget", ascending=False)
            .head(k)
        )
    size_top = panel.sort_values("account_original_budget", ascending=False).head(k)
    prec = top[outcome].mean() if len(top) else np.nan
    size_prec = size_top[outcome].mean()
    return {
        "flag": flag,
        "outcome": outcome,
        "k": k,
        "panel_n": len(panel),
        "flagged_n": int(panel[flag].sum()),
        "base_rate": float(base_rate),
        "precision_at_k": float(prec) if pd.notna(prec) else None,
        "size_precision_at_k": float(size_prec),
        "lift_vs_all": float(prec / base_rate) if base_rate and pd.notna(prec) else None,
        "lift_vs_size": float(prec / size_prec) if size_prec and pd.notna(prec) else None,
        "flagged_confirm_rate": float(panel.loc[panel[flag], outcome].mean())
        if panel[flag].any()
        else None,
        "not_flagged_confirm_rate": float(panel.loc[~panel[flag], outcome].mean())
        if (~panel[flag]).any()
        else None,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    wq = pd.read_csv(SRC)
    for c in [
        "low_performance_budget_increase_t1",
        "repeated_execution_signal",
        "performance_signal",
    ]:
        if c in wq.columns:
            wq[c] = wq[c].astype("boolean").fillna(False).astype(bool)
    for c in [
        "fiscal_year",
        "performance_gap",
        "account_execution_rate",
        "account_original_budget",
        "independent_signal_family_count",
        "work_queue_order",
    ]:
        wq[c] = pd.to_numeric(wq[c], errors="coerce")
    wq["fiscal_year"] = wq["fiscal_year"].astype(int)

    verify = verify_cases(wq)
    verify.to_csv(OUT / "pilot_case_verification.csv", index=False)

    panel = build_panel(wq)
    panel.to_csv(OUT / "panel_base_to_next_year.csv", index=False)

    metric_rows = []
    for outcome in ["future_confirmed", "future_confirmed_strict"]:
        for flag in [
            "sig_performance",
            "sig_execution",
            "sig_repeated",
            "sig_any_core",
            "flagged_queue",
        ]:
            for k in [20, 50]:
                if len(panel) >= k:
                    metric_rows.append(top_precision(panel, flag, outcome, k))
    metrics = pd.DataFrame(metric_rows)
    metrics.to_csv(OUT / "lift_precision_by_signal.csv", index=False)

    strict = metrics[metrics["outcome"].eq("future_confirmed_strict") & metrics["k"].eq(20)]
    easy = {
        "case_verification": verify[["label", "status", "failed_checks"]].to_dict(
            orient="records"
        ),
        "panel_n": len(panel),
        "strict_base_rate": float(panel["future_confirmed_strict"].mean()),
        "wide_base_rate": float(panel["future_confirmed"].mean()),
        "strict_lift_at_20": strict[
            [
                "flag",
                "precision_at_k",
                "size_precision_at_k",
                "lift_vs_all",
                "lift_vs_size",
                "flagged_confirm_rate",
                "not_flagged_confirm_rate",
                "flagged_n",
            ]
        ].to_dict(orient="records"),
        "notes": {
            "signals_exclude_future_budget": True,
            "strict_event": "next year gap>0 OR exec<0.80 OR lane in REPEATED/STRONG",
        },
    }
    (OUT / "easy_summary.json").write_text(
        json.dumps(easy, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(easy, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
