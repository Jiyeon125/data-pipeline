"""GDP 디플레이터를 적용한 T+1·T+2 실질 예산환류 민감도 분석."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

GDP_DEFLATOR_2020_BASE = {2022: 105.0, 2023: 107.0, 2024: 111.4}
GDP_DEFLATOR_SOURCE = (
    "KOSIS GDP 디플레이터(2020=100), 원출처 한국은행 국민계정, 2022~2024 완결 분석 구간"
)
GDP_DEFLATOR_SOURCE_URL = (
    "https://kosis.kr/visual/economyBoard/economyJipyo.do?listId=125&unitySrvcId=653"
)
GDP_DEFLATOR_ACCESSED_AT = "2026-08-03"


@dataclass(frozen=True)
class RealBudgetFeedbackPaths:
    candidates: Path
    output_dir: Path
    report: Path

    @classmethod
    def from_root(cls, root: Path) -> RealBudgetFeedbackPaths:
        return cls(
            candidates=root
            / "data"
            / "analytics"
            / "multi_ministry_priority_scenarios"
            / "candidate_population.csv",
            output_dir=root / "data" / "analytics" / "real_budget_feedback",
            report=root / "docs" / "REAL_BUDGET_FEEDBACK_SENSITIVITY.md",
        )


@dataclass(frozen=True)
class RealBudgetFeedbackResult:
    output_paths: list[Path]
    report_path: Path
    summary: dict[str, object]


def _require_columns(frame: pd.DataFrame, columns: set[str]) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"실질 예산환류 입력 컬럼 누락: {missing}")


def _direction(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return pd.Series(
        np.select(
            [numeric.lt(-1e-9), numeric.gt(1e-9), numeric.notna()],
            ["DECREASE", "INCREASE", "MAINTAIN"],
            default="MISSING",
        ),
        index=values.index,
    )


def _real_review_intensity(frame: pd.DataFrame) -> pd.Series:
    independent_count = pd.DataFrame(
        {
            "performance": frame["performance_signal"].fillna(False),
            "execution": frame["execution_review_signal"].fillna(False),
            "feedback_t1": frame["low_performance_budget_increase_t1_real"],
            "feedback_t2": frame["low_performance_budget_increase_t2_real"],
        }
    ).sum(axis=1)
    strong = (
        pd.to_numeric(frame["performance_gap"], errors="coerce").fillna(0).ge(1)
        | pd.to_numeric(frame["current_execution_severity"], errors="coerce").fillna(0).ge(1)
        | frame["low_performance_budget_increase_t1_real"]
        | frame["low_performance_budget_increase_t2_real"]
    )
    context = (
        frame["accounting_context_signal"].fillna(False)
        | frame["structure_context_signal"].fillna(False)
        | frame["budget_increase_context_signal"].fillna(False)
        | frame["budget_decrease_context_signal"].fillna(False)
        | frame["good_performance_budget_decrease_t1_real"]
        | frame["good_performance_budget_decrease_t2_real"]
    )
    result = pd.Series("MONITOR", index=frame.index)
    result.loc[context] = "CONTEXT_REVIEW"
    result.loc[independent_count.eq(1)] = "SINGLE_REVIEW"
    result.loc[independent_count.eq(1) & strong] = "STRONG_SINGLE"
    result.loc[independent_count.ge(2) | frame["repeated_execution_signal"].fillna(False)] = (
        "REPEATED_OR_MULTIPLE"
    )
    result.loc[frame["data_validation_signal"].fillna(False)] = "DATA_FIRST"
    return result


def attach_real_budget_feedback(
    candidates: pd.DataFrame,
    deflators: dict[int, float] | None = None,
) -> pd.DataFrame:
    """명목 후보를 바꾸지 않고 동일 행에 실질 환류 민감도 필드를 추가합니다."""
    deflators = deflators or GDP_DEFLATOR_2020_BASE
    required = {
        "candidate_id",
        "fiscal_year",
        "ministry_code",
        "account_type",
        "account_original_budget",
        "analysis_status",
        "comparable_rate_count",
        "performance_gap",
        "performance_signal",
        "execution_review_signal",
        "current_execution_severity",
        "repeated_execution_signal",
        "accounting_context_signal",
        "structure_context_signal",
        "budget_increase_context_signal",
        "budget_decrease_context_signal",
        "data_validation_signal",
        "review_intensity",
    }
    for horizon in ("t1", "t2"):
        required.update(
            {
                f"program_total_feedback_complete_{horizon}",
                f"program_total_budget_change_rate_{horizon}",
                f"program_total_base_budget_{horizon}",
                f"program_total_outcome_budget_{horizon}",
                f"low_performance_budget_increase_{horizon}",
                f"good_performance_budget_decrease_{horizon}",
            }
        )
    _require_columns(candidates, required)
    if candidates["candidate_id"].duplicated().any():
        raise ValueError("candidate_id 중복으로 실질 민감도 분석 grain을 보장할 수 없습니다.")

    result = candidates.copy()
    base_year = pd.to_numeric(result["fiscal_year"], errors="coerce")
    joint = result["analysis_status"].eq("JOINT_ANALYSIS")
    comparable_performance = pd.to_numeric(result["comparable_rate_count"], errors="coerce").gt(0)
    performance_gap = pd.to_numeric(result["performance_gap"], errors="coerce")

    for horizon, lag in (("t1", 1), ("t2", 2)):
        nominal = pd.to_numeric(
            result[f"program_total_budget_change_rate_{horizon}"], errors="coerce"
        )
        base_deflator = base_year.map(deflators)
        outcome_deflator = base_year.add(lag).map(deflators)
        complete = result[f"program_total_feedback_complete_{horizon}"].fillna(False)
        eligible = complete & nominal.notna() & base_deflator.notna() & outcome_deflator.notna()
        real = pd.Series(np.nan, index=result.index, dtype=float)
        real.loc[eligible] = (1 + nominal.loc[eligible]) * base_deflator.loc[
            eligible
        ] / outcome_deflator.loc[eligible] - 1

        result[f"feedback_base_deflator_{horizon}"] = base_deflator
        result[f"feedback_outcome_deflator_{horizon}"] = outcome_deflator
        result[f"real_feedback_eligible_{horizon}"] = eligible
        result[f"real_feedback_exclusion_reason_{horizon}"] = np.select(
            [
                ~complete | nominal.isna(),
                base_deflator.isna(),
                outcome_deflator.isna(),
            ],
            [
                "NOMINAL_FEEDBACK_INCOMPLETE",
                "BASE_DEFLATOR_UNAVAILABLE",
                "OUTCOME_DEFLATOR_UNAVAILABLE",
            ],
            default="NONE",
        )
        result[f"program_total_budget_change_rate_{horizon}_real"] = real
        nominal_direction = _direction(nominal)
        real_direction = _direction(real)
        result[f"nominal_budget_direction_{horizon}"] = nominal_direction
        result[f"real_budget_direction_{horizon}"] = real_direction
        result[f"nominal_real_direction_changed_{horizon}"] = eligible & nominal_direction.ne(
            real_direction
        )
        result[f"nominal_increase_real_nonincrease_{horizon}"] = (
            eligible & nominal.gt(0) & real.le(0)
        )
        result[f"low_performance_budget_increase_{horizon}_real"] = (
            joint & comparable_performance & performance_gap.gt(0) & eligible & real.gt(0)
        )
        result[f"good_performance_budget_decrease_{horizon}_real"] = (
            joint & comparable_performance & performance_gap.eq(0) & eligible & real.lt(0)
        )

    result["review_intensity_real_sensitivity"] = _real_review_intensity(result)
    result["review_intensity_real_changed"] = result["review_intensity_real_sensitivity"].ne(
        result["review_intensity"]
    )
    return result


def _impact_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dimensions = {
        "OVERALL": [],
        "MINISTRY": ["ministry_code"],
        "ACCOUNT_TYPE": ["account_type"],
        "MINISTRY_ACCOUNT_TYPE": ["ministry_code", "account_type"],
    }
    for horizon in ("t1", "t2"):
        for dimension, columns in dimensions.items():
            groups = [("ALL", frame)] if not columns else frame.groupby(columns, dropna=False)
            for group, part in groups:
                group_values = group if isinstance(group, tuple) else (group,)
                eligible = part[f"real_feedback_eligible_{horizon}"].fillna(False)
                flip = part[f"nominal_increase_real_nonincrease_{horizon}"].fillna(False)
                base_budget = pd.to_numeric(
                    part[f"program_total_base_budget_{horizon}"], errors="coerce"
                )
                nominal = pd.to_numeric(
                    part[f"program_total_budget_change_rate_{horizon}"], errors="coerce"
                )
                real = pd.to_numeric(
                    part[f"program_total_budget_change_rate_{horizon}_real"], errors="coerce"
                )
                row = {
                    "feedback_horizon": horizon.upper(),
                    "dimension": dimension,
                    "group": " | ".join(str(value) for value in group_values),
                    "row_count": len(part),
                    "real_feedback_eligible_count": int(eligible.sum()),
                    "eligible_base_budget": float(base_budget[eligible].sum()),
                    "nominal_increase_count": int((eligible & nominal.gt(0)).sum()),
                    "real_increase_count": int((eligible & real.gt(0)).sum()),
                    "nominal_increase_real_nonincrease_count": int(flip.sum()),
                    "direction_changed_base_budget": float(base_budget[flip].sum()),
                    "median_nominal_change_rate": float(nominal[eligible].median()),
                    "median_real_change_rate": float(real[eligible].median()),
                    "low_performance_increase_nominal_count": int(
                        part[f"low_performance_budget_increase_{horizon}"].fillna(False).sum()
                    ),
                    "low_performance_increase_real_count": int(
                        part[f"low_performance_budget_increase_{horizon}_real"].sum()
                    ),
                    "good_performance_decrease_nominal_count": int(
                        part[f"good_performance_budget_decrease_{horizon}"].fillna(False).sum()
                    ),
                    "good_performance_decrease_real_count": int(
                        part[f"good_performance_budget_decrease_{horizon}_real"].sum()
                    ),
                }
                rows.append(row)
    return pd.DataFrame(rows)


def _render_report(summary: dict[str, object]) -> str:
    horizon = summary["horizon_summary"]
    return f"""# GDP 디플레이터 실질 예산환류 민감도

## 결론

명목 예산변화는 유지하고 실질 변화는 별도 민감도 신호로 사용합니다. 물가보정은
삭감·증액 판단이 아니라, 명목 증가가 실제 구매력 증가인지 추가 설명이 필요한지를
구분합니다.

## 분석 범위와 산식

- 한 행: 부처 × 성과 프로그램 × 회계유형 × 기준연도 (`candidate_id` 유일)
- 입력: 4개 부처 점검후보 모집단 {summary["input_row_count"]:,}행
- 지수: {GDP_DEFLATOR_SOURCE}
- 지수값: 2022=105.0, 2023=107.0, 2024=111.4
- 실질 증감률: `(1 + 명목증감률) × 기준연도 디플레이터 ÷ 후속연도 디플레이터 - 1`
- 2025 성과실적이 없는 점과 지수 개정 가능성을 고려해 2022~2024 완결 구간만 계산

## 핵심 결과

| 구분 | T+1 | T+2 |
|---|---:|---:|
| 실질 비교 가능 행 | {horizon["t1"]["eligible_count"]:,} | {horizon["t2"]["eligible_count"]:,} |
| 전체 412행 대비 비교 가능률 | {horizon["t1"]["eligible_share"]:.1%} | {horizon["t2"]["eligible_share"]:.1%} |
| 명목 증가 → 실질 비증가 | {horizon["t1"]["direction_flip_count"]:,} | {horizon["t2"]["direction_flip_count"]:,} |
| 명목 중위 증감률 | {horizon["t1"]["median_nominal_rate"]:.1%} | {horizon["t2"]["median_nominal_rate"]:.1%} |
| 실질 중위 증감률 | {horizon["t1"]["median_real_rate"]:.1%} | {horizon["t2"]["median_real_rate"]:.1%} |
| 성과미달·예산증가 신호(명목→실질) | {horizon["t1"]["low_performance_nominal"]:,}→{horizon["t1"]["low_performance_real"]:,} | {horizon["t2"]["low_performance_nominal"]:,}→{horizon["t2"]["low_performance_real"]:,} |

실질 민감도를 적용하면 점검강도가 바뀌는 행은 {summary["review_intensity_changed_count"]:,}개입니다.
기존 결과를 대체하지 않고 이 행들에 `물가보정 민감` 배지를 붙이는 것이 권장됩니다.

T+1은 전체 행의 {horizon["t1"]["eligible_share"]:.1%}, T+2는 {horizon["t2"]["eligible_share"]:.1%}만
완전 비교가 가능하므로 이 결과를 전체 모집단 비율로 일반화하지 않습니다. 금액 합계도
성과 프로그램·회계유형 후보 행의 노출규모이며 국가 전체 예산의 순합계로 해석하지 않습니다.

## 해석 제한

- GDP 디플레이터는 모든 재화·서비스를 포괄하므로 특정 사업의 장비비·공사비·인건비
  가격 변화를 정확히 대변하지 않습니다.
- 따라서 실질 감소는 사업 축소의 증거가 아니라 추가 설명을 요청할 근거입니다.
- 2025 지수는 현재 산출물에서 제외했습니다. 최신 확정·잠정 계열을 채택할지 결정한 뒤
  2024→2025와 2023→2025를 다시 계산해야 합니다.
"""


def build_real_budget_feedback_sensitivity(
    paths: RealBudgetFeedbackPaths,
) -> RealBudgetFeedbackResult:
    if not paths.candidates.exists():
        raise FileNotFoundError(paths.candidates)
    candidates = pd.read_csv(
        paths.candidates,
        low_memory=False,
        dtype={"ministry_code": "string", "program_code": "string"},
    )
    nominal_columns = [
        "program_total_budget_change_rate_t1",
        "program_total_budget_change_rate_t2",
    ]
    amount_columns = [
        "account_original_budget",
        "program_total_base_budget_t1",
        "program_total_outcome_budget_t1",
        "program_total_base_budget_t2",
        "program_total_outcome_budget_t2",
    ]
    nominal_before = candidates[nominal_columns].copy()
    amount_sums_before = {
        column: float(pd.to_numeric(candidates[column], errors="coerce").sum())
        for column in amount_columns
    }
    result = attach_real_budget_feedback(candidates)
    impact = _impact_summary(result)
    changed = result[result["review_intensity_real_changed"]].copy()
    overall = impact[impact["dimension"].eq("OVERALL")].set_index("feedback_horizon")
    horizon_summary = {}
    for horizon in ("t1", "t2"):
        row = overall.loc[horizon.upper()]
        horizon_summary[horizon] = {
            "eligible_count": int(row["real_feedback_eligible_count"]),
            "eligible_share": float(row["real_feedback_eligible_count"] / len(candidates)),
            "direction_flip_count": int(row["nominal_increase_real_nonincrease_count"]),
            "direction_flip_base_budget": float(row["direction_changed_base_budget"]),
            "median_nominal_rate": float(row["median_nominal_change_rate"]),
            "median_real_rate": float(row["median_real_change_rate"]),
            "low_performance_nominal": int(row["low_performance_increase_nominal_count"]),
            "low_performance_real": int(row["low_performance_increase_real_count"]),
            "good_performance_nominal": int(row["good_performance_decrease_nominal_count"]),
            "good_performance_real": int(row["good_performance_decrease_real_count"]),
        }
    summary: dict[str, object] = {
        "purpose": "명목 T+1·T+2 예산환류 신호의 GDP 디플레이터 민감도 검증",
        "input_row_count": len(candidates),
        "output_row_count": len(result),
        "candidate_id_unique": bool(result["candidate_id"].is_unique),
        "ministries": sorted(result["ministry_code"].dropna().astype(str).unique().tolist()),
        "deflator": {
            "base": "2020=100",
            "values": {str(year): value for year, value in GDP_DEFLATOR_2020_BASE.items()},
            "source": GDP_DEFLATOR_SOURCE,
            "source_url": GDP_DEFLATOR_SOURCE_URL,
            "accessed_at": GDP_DEFLATOR_ACCESSED_AT,
        },
        "horizon_summary": horizon_summary,
        "review_intensity_changed_count": len(changed),
        "validation": {
            "row_count_preserved": len(candidates) == len(result),
            "candidate_id_unique": bool(result["candidate_id"].is_unique),
            "nominal_rates_unchanged": bool(
                nominal_before.reset_index(drop=True).equals(
                    result[nominal_columns].reset_index(drop=True)
                )
            ),
            "amount_sums_unchanged": all(
                np.isclose(
                    amount_sums_before[column],
                    float(pd.to_numeric(result[column], errors="coerce").sum()),
                )
                for column in amount_columns
            ),
            "real_values_only_when_eligible": all(
                result.loc[
                    ~result[f"real_feedback_eligible_{horizon}"],
                    f"program_total_budget_change_rate_{horizon}_real",
                ]
                .isna()
                .all()
                for horizon in ("t1", "t2")
            ),
        },
        "input_sha256": hashlib.sha256(paths.candidates.read_bytes()).hexdigest(),
    }
    if not all(summary["validation"].values()):
        raise ValueError(f"실질 예산환류 검증 실패: {summary['validation']}")

    paths.output_dir.mkdir(parents=True, exist_ok=True)
    paths.report.parent.mkdir(parents=True, exist_ok=True)
    result_path = paths.output_dir / "program_year_real_feedback_sensitivity.csv"
    impact_path = paths.output_dir / "real_feedback_impact_summary.csv"
    changed_path = paths.output_dir / "review_intensity_changed_rows.csv"
    summary_path = paths.output_dir / "real_budget_feedback_summary.json"
    result.to_csv(result_path, index=False, encoding="utf-8-sig")
    impact.to_csv(impact_path, index=False, encoding="utf-8-sig")
    changed.to_csv(changed_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    paths.report.write_text(_render_report(summary), encoding="utf-8")
    return RealBudgetFeedbackResult(
        output_paths=[result_path, impact_path, changed_path, summary_path],
        report_path=paths.report,
        summary=summary,
    )
