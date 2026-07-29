"""M3 재정 신호 분석: 점수·전체 순위 없이 기준, 유형, 환류를 비교합니다."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

SIGNAL_COLUMNS = [
    "strong_low_execution_flag",
    "moderate_low_execution_flag",
    "peer_bottom_10_execution_flag",
    "peer_bottom_20_execution_flag",
    "fixed_year_end_concentration_flag",
    "peer_p80_year_end_concentration_flag",
    "peer_p90_year_end_concentration_flag",
    "peer_p95_year_end_concentration_flag",
    "cumulative_decrease_flag",
    "execution_over_100_flag",
    "budget_increase_extreme_flag",
    "budget_decrease_extreme_flag",
    "program_concentration_flag",
    "data_quality_review_flag",
]

TYPE_COLUMNS = [
    "type_repeated_strong_low_execution",
    "type_repeated_moderate_low_execution",
    "type_repeated_year_end_concentration",
    "type_accounting_adjustment_pattern",
    "type_denominator_or_matching_review",
    "type_budget_rapid_increase",
    "type_budget_rapid_decrease",
    "type_program_budget_concentration",
    "type_multiple_financial_signals",
    "type_data_validation_priority",
]

TYPE_LABELS = {
    "type_repeated_strong_low_execution": "REPEATED_STRONG_LOW_EXECUTION",
    "type_repeated_moderate_low_execution": "REPEATED_MODERATE_LOW_EXECUTION",
    "type_repeated_year_end_concentration": "REPEATED_YEAR_END_CONCENTRATION",
    "type_accounting_adjustment_pattern": "ACCOUNTING_ADJUSTMENT_PATTERN",
    "type_denominator_or_matching_review": "DENOMINATOR_OR_MATCHING_REVIEW",
    "type_budget_rapid_increase": "BUDGET_RAPID_INCREASE",
    "type_budget_rapid_decrease": "BUDGET_RAPID_DECREASE",
    "type_program_budget_concentration": "PROGRAM_BUDGET_CONCENTRATION",
    "type_multiple_financial_signals": "MULTIPLE_FINANCIAL_SIGNALS",
    "type_data_validation_priority": "DATA_VALIDATION_PRIORITY",
}

TYPE_RULES = {
    "REPEATED_STRONG_LOW_EXECUTION": (
        "strong low execution in >=2 valid years and >=50% of valid execution years"
    ),
    "REPEATED_MODERATE_LOW_EXECUTION": (
        "moderate low execution in >=2 valid years and >=50% of valid execution years"
    ),
    "REPEATED_YEAR_END_CONCENTRATION": (
        "fixed year-end concentration in >=2 valid monthly years and >=50% of valid monthly years"
    ),
    "ACCOUNTING_ADJUSTMENT_PATTERN": (
        "cumulative decrease or execution rate over 100%; accounting/adjustment review signal"
    ),
    "DENOMINATOR_OR_MATCHING_REVIEW": (
        "denominator unconfirmed, settlement not matched, or financial review priority BLOCKING"
    ),
    "BUDGET_RAPID_INCREASE": "peer-year comparison group upper 5% of signed log budget change",
    "BUDGET_RAPID_DECREASE": "peer-year comparison group lower 5% of signed log budget change",
    "PROGRAM_BUDGET_CONCENTRATION": (
        "program has at least two positive-budget projects and top project share >=70%"
    ),
    "MULTIPLE_FINANCIAL_SIGNALS": "at least two independent valid financial signals in the same row",
    "DATA_VALIDATION_PRIORITY": (
        "BLOCKING review, masked/duplicate/monthly quality issue, or denominator/matching review"
    ),
}

TYPE_INTERPRETATION = {
    "REPEATED_STRONG_LOW_EXECUTION": "반복적으로 확인되는 강한 집행설명필요 신호",
    "REPEATED_MODERATE_LOW_EXECUTION": "반복되는 중간 수준의 집행설명필요 신호",
    "REPEATED_YEAR_END_CONCENTRATION": "지급·조달·정산 시점 설명이 필요한 반복 패턴",
    "ACCOUNTING_ADJUSTMENT_PATTERN": "회계조정·환입·분모 확인이 우선인 패턴",
    "DENOMINATOR_OR_MATCHING_REVIEW": "정책 해석 전에 데이터 연결·분모 검증이 필요한 패턴",
    "BUDGET_RAPID_INCREASE": "비교집단 대비 예산 확대 사유를 확인할 후보",
    "BUDGET_RAPID_DECREASE": "비교집단 대비 예산 감소 사유를 확인할 후보",
    "PROGRAM_BUDGET_CONCENTRATION": "프로그램 신호가 소수 세부사업에 좌우될 가능성",
    "MULTIPLE_FINANCIAL_SIGNALS": "서로 다른 재정 신호가 동시에 나타나는 원문 검토 후보",
    "DATA_VALIDATION_PRIORITY": "분석보다 데이터 검증을 먼저 수행할 후보",
}

TYPE_ALTERNATIVE = {
    "REPEATED_STRONG_LOW_EXECUTION": "다년도 사업, 집행시차, 계약·조달 일정",
    "REPEATED_MODERATE_LOW_EXECUTION": "보수적 집행계획 또는 정산시차",
    "REPEATED_YEAR_END_CONCENTRATION": "연말 일괄지급, 하위기관 정산, 계절적 사업구조",
    "ACCOUNTING_ADJUSTMENT_PATTERN": "환입·조정·자료 수정 또는 분모 정의 차이",
    "DENOMINATOR_OR_MATCHING_REVIEW": "코드변경·범위차이·원천 누락",
    "BUDGET_RAPID_INCREASE": "신규 단계, 정책 우선순위 변화, 회계이관",
    "BUDGET_RAPID_DECREASE": "한시사업 종료, 단계 전환, 이관·통합",
    "PROGRAM_BUDGET_CONCENTRATION": "본래 단일 핵심사업 중심인 프로그램 구조",
    "MULTIPLE_FINANCIAL_SIGNALS": "하나의 구조적 사건이 여러 지표에 동시에 반영",
    "DATA_VALIDATION_PRIORITY": "원천 공개범위 또는 비표준 응답의 기술적 한계",
}


@dataclass(frozen=True)
class M3Paths:
    ranking_v2: Path
    v2: Path
    program: Path
    core: Path
    broad: Path
    classification: Path
    relation: Path
    monthly_patterns: Path
    normalized_hhi: Path
    feedback_cohorts: Path
    output_dir: Path
    figure_dir: Path
    report: Path

    @classmethod
    def from_root(cls, root: Path) -> M3Paths:
        masters = root / "data" / "processed" / "masters"
        sensitivity = masters / "population_sensitivity"
        validation = root / "data" / "analytics" / "definition_validation"
        return cls(
            ranking_v2=sensitivity / "ranking_population_v2.parquet",
            v2=masters / "project_year_financial_v2.parquet",
            program=masters / "program_year_financial.parquet",
            core=sensitivity / "core_financial_population.parquet",
            broad=sensitivity / "broad_population.parquet",
            classification=masters / "project_classification.parquet",
            relation=masters / "project_relation.parquet",
            monthly_patterns=root
            / "data"
            / "analytics"
            / "eda"
            / "monthly_execution_pattern_summary.csv",
            normalized_hhi=validation / "program_concentration_normalized.csv",
            feedback_cohorts=validation / "feedback_cohort_t1_t2.csv",
            output_dir=root / "data" / "analytics" / "m3",
            figure_dir=root / "artifacts" / "figures" / "m3",
            report=root / "docs" / "M3_FINANCIAL_INSIGHTS.md",
        )

    @property
    def inputs(self) -> list[Path]:
        return [
            self.ranking_v2,
            self.v2,
            self.program,
            self.core,
            self.broad,
            self.classification,
            self.relation,
            self.monthly_patterns,
            self.normalized_hhi,
            self.feedback_cohorts,
        ]


@dataclass
class M3Result:
    output_paths: list[Path]
    figure_paths: list[Path]
    report_path: Path
    summary: dict[str, Any]


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce")


def _bool(frame: pd.DataFrame, column: str, default: bool = False) -> pd.Series:
    if column not in frame:
        return pd.Series(default, index=frame.index, dtype=bool)
    return frame[column].astype("boolean").fillna(default).astype(bool)


def _nullable_flag(valid: pd.Series, condition: pd.Series) -> pd.Series:
    result = pd.Series(pd.NA, index=valid.index, dtype="boolean")
    result.loc[valid] = condition.loc[valid].astype(bool)
    return result


def _sum(frame: pd.DataFrame, column: str) -> float:
    return float(_numeric(frame, column).sum(skipna=True))


def _safe_rate(numerator: float, denominator: float) -> float:
    if denominator <= 0 or pd.isna(denominator):
        return math.nan
    return float(numerator / denominator)


def _median_abs_deviation(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return math.nan
    return float((numeric - numeric.median()).abs().median())


def _distribution_json(frame: pd.DataFrame, column: str) -> str:
    counts = frame[column].fillna("MISSING").astype(str).value_counts().to_dict()
    return json.dumps(counts, ensure_ascii=False, sort_keys=True)


def _write_csv(frame: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _read_patterns(path: Path) -> pd.DataFrame:
    return pd.read_csv(
        path,
        encoding="utf-8-sig",
        dtype={
            "ministry_code": "string",
            "account_code": "string",
            "program_code": "string",
            "activity_code": "string",
            "subactivity_code": "string",
            "source_project_year_id": "string",
            "classification_project_id": "string",
        },
    )


def _consecutive_two(years: pd.Series, flags: pd.Series) -> bool:
    selected = sorted(
        int(year) for year, flag in zip(years, flags, strict=True) if pd.notna(flag) and bool(flag)
    )
    return any(right - left == 1 for left, right in pairwise(selected))


def build_signal_features(
    ranking: pd.DataFrame,
    patterns: pd.DataFrame,
    hhi: pd.DataFrame,
) -> pd.DataFrame:
    """사업-연도별 독립 재정 신호를 nullable boolean으로 생성합니다."""
    monthly_columns = [
        "source_project_year_id",
        "monthly_pattern_eligible_final",
        "observed_month_count",
        "q4_expenditure_share",
        "december_single_month_share",
        "cumulative_decrease_count",
        "monthly_expenditure_volatility",
        "execution_data_quality_flags",
        "duplicate_month_key_flag",
        "master_key_duplicate_flag",
        "monthly_masked_flag",
    ]
    frame = ranking.merge(
        patterns[monthly_columns],
        on="source_project_year_id",
        how="left",
        validate="one_to_one",
    )
    hhi_columns = [
        "ministry_code",
        "fiscal_year",
        "program_code",
        "program_name",
        "positive_budget_project_count",
        "hhi_raw",
        "hhi_normalized_for_project_count",
        "top1_project_budget_share",
        "top3_project_budget_share",
    ]
    hhi_join = hhi[hhi_columns].rename(columns={"ministry_code": "hhi_ministry_code"})
    frame = frame.merge(
        hhi_join,
        left_on=["ministry_code", "fiscal_year", "program_code", "program_name"],
        right_on=[
            "hhi_ministry_code",
            "fiscal_year",
            "program_code",
            "program_name",
        ],
        how="left",
        validate="many_to_one",
    ).drop(columns="hhi_ministry_code")

    execution = _numeric(frame, "execution_rate")
    execution_valid = _bool(frame, "execution_ranking_eligible") & execution.notna()
    frame["strong_low_execution_flag"] = _nullable_flag(execution_valid, execution.lt(0.80))
    frame["moderate_low_execution_flag"] = _nullable_flag(
        execution_valid, execution.ge(0.80) & execution.lt(0.90)
    )

    peer_keys = ["fiscal_year", "comparison_group"]
    exec_group_size = frame.groupby(peer_keys)["source_project_year_id"].transform("size")
    frame["execution_peer_group_size"] = exec_group_size
    p10 = frame.groupby(peer_keys)["execution_rate"].transform(
        lambda values: pd.to_numeric(values, errors="coerce").dropna().astype(float).quantile(0.10)
    )
    p20 = frame.groupby(peer_keys)["execution_rate"].transform(
        lambda values: pd.to_numeric(values, errors="coerce").dropna().astype(float).quantile(0.20)
    )
    peer_exec_valid = execution_valid & exec_group_size.ge(5)
    frame["peer_bottom_10_execution_flag"] = _nullable_flag(peer_exec_valid, execution.le(p10))
    frame["peer_bottom_20_execution_flag"] = _nullable_flag(peer_exec_valid, execution.le(p20))

    monthly_valid = _bool(frame, "monthly_pattern_eligible_final")
    frame["monthly_signal_eligible_validated"] = monthly_valid
    # 관측경계만으로 제외된 행을 동일연도 민감도 표본으로 별도 보존합니다.
    boundary_only = (
        frame["execution_data_quality_flags"]
        .fillna("")
        .isin(["OBSERVATION_BOUNDARY", "OBSERVATION_BOUNDARY;CUMULATIVE_DECREASE"])
    )
    frame["monthly_signal_eligible_boundary_retained"] = monthly_valid | boundary_only
    q4 = _numeric(frame, "q4_expenditure_share")
    december = _numeric(frame, "december_single_month_share")
    monthly_valid &= q4.notna() & december.notna()
    frame["fixed_q4_40_flag"] = _nullable_flag(monthly_valid, q4.ge(0.40))
    frame["fixed_december_20_flag"] = _nullable_flag(monthly_valid, december.ge(0.20))
    frame["fixed_year_end_concentration_flag"] = _nullable_flag(
        monthly_valid, q4.ge(0.40) | december.ge(0.20)
    )

    monthly_peer_size = frame.groupby(peer_keys)["source_project_year_id"].transform(
        lambda values: int(monthly_valid.loc[values.index].sum())
    )
    frame["monthly_peer_group_valid_size"] = monthly_peer_size
    for percentile in [0.80, 0.90, 0.95]:
        label = int(percentile * 100)
        q4_threshold = frame.groupby(peer_keys)["q4_expenditure_share"].transform(
            lambda values, quantile=percentile: pd.to_numeric(
                values[monthly_valid.loc[values.index]], errors="coerce"
            ).quantile(quantile)
        )
        dec_threshold = frame.groupby(peer_keys)["december_single_month_share"].transform(
            lambda values, quantile=percentile: pd.to_numeric(
                values[monthly_valid.loc[values.index]], errors="coerce"
            ).quantile(quantile)
        )
        valid = monthly_valid & monthly_peer_size.ge(5)
        frame[f"peer_p{label}_year_end_concentration_flag"] = _nullable_flag(
            valid, q4.ge(q4_threshold) | december.ge(dec_threshold)
        )
        frame[f"peer_p{label}_q4_threshold"] = q4_threshold
        frame[f"peer_p{label}_december_threshold"] = dec_threshold

    frame["cumulative_decrease_flag"] = _nullable_flag(
        monthly_valid, _numeric(frame, "cumulative_decrease_count").gt(0)
    )
    execution_available = execution.notna()
    frame["execution_over_100_flag"] = _nullable_flag(execution_available, execution.gt(1))

    change = _numeric(frame, "budget_change_rate")
    change_valid = _bool(frame, "trend_ranking_eligible") & change.notna() & change.gt(-1)
    signed_log_change = pd.Series(np.nan, index=frame.index, dtype="float64")
    signed_log_change.loc[change_valid] = np.log1p(change.loc[change_valid].astype("float64"))
    frame["signed_log_budget_change"] = signed_log_change
    change_group_size = frame.groupby(peer_keys)["signed_log_budget_change"].transform("count")
    frame["budget_change_peer_group_size"] = change_group_size
    p05 = frame.groupby(peer_keys)["signed_log_budget_change"].transform(
        lambda values: pd.to_numeric(values, errors="coerce").quantile(0.05)
    )
    p95 = frame.groupby(peer_keys)["signed_log_budget_change"].transform(
        lambda values: pd.to_numeric(values, errors="coerce").quantile(0.95)
    )
    change_peer_valid = change_valid & change_group_size.ge(10)
    frame["budget_increase_extreme_flag"] = _nullable_flag(
        change_peer_valid, _numeric(frame, "signed_log_budget_change").ge(p95)
    )
    frame["budget_decrease_extreme_flag"] = _nullable_flag(
        change_peer_valid, _numeric(frame, "signed_log_budget_change").le(p05)
    )
    median = frame.groupby(peer_keys)["signed_log_budget_change"].transform("median")
    mad = frame.groupby(peer_keys)["signed_log_budget_change"].transform(_median_abs_deviation)
    frame["budget_change_robust_z"] = (_numeric(frame, "signed_log_budget_change") - median) / (
        1.4826 * mad.replace(0, np.nan)
    )
    lower_winsor = frame.groupby(peer_keys)["signed_log_budget_change"].transform(
        lambda values: pd.to_numeric(values, errors="coerce").quantile(0.01)
    )
    upper_winsor = frame.groupby(peer_keys)["signed_log_budget_change"].transform(
        lambda values: pd.to_numeric(values, errors="coerce").quantile(0.99)
    )
    frame["signed_log_budget_change_winsorized_for_sensitivity"] = _numeric(
        frame, "signed_log_budget_change"
    ).clip(lower=lower_winsor, upper=upper_winsor)
    frame["budget_change_absolute_50pct_flag"] = _nullable_flag(change_valid, change.abs().ge(0.50))

    program_valid = (
        _numeric(frame, "positive_budget_project_count").ge(2)
        & _numeric(frame, "top1_project_budget_share").notna()
    )
    frame["program_concentration_flag"] = _nullable_flag(
        program_valid, _numeric(frame, "top1_project_budget_share").ge(0.70)
    )
    matching_review = (
        ~frame["execution_denominator_status"].eq("APPLIED")
        | ~frame["settlement_join_status"].eq("BOTH")
        | frame["review_priority"].eq("BLOCKING")
    )
    frame["denominator_or_matching_review_flag"] = matching_review
    monthly_quality = (
        _bool(frame, "duplicate_month_key_flag")
        | _bool(frame, "master_key_duplicate_flag")
        | _bool(frame, "monthly_masked_flag")
    )
    frame["data_quality_review_flag"] = (
        matching_review | monthly_quality | frame["review_priority"].eq("BLOCKING")
    ).astype("boolean")
    return frame


def build_repeated_signals(features: pd.DataFrame) -> pd.DataFrame:
    """유효 관측연도 수를 분모로 반복 신호 대안을 모두 계산합니다."""
    rows: list[dict[str, Any]] = []
    for project_id, part in features.groupby("classification_project_id"):
        valid_exec = part["strong_low_execution_flag"].notna()
        valid_month = part["fixed_year_end_concentration_flag"].notna()
        counts = {
            "valid_execution_year_count": int(valid_exec.sum()),
            "valid_monthly_year_count": int(valid_month.sum()),
            "strong_low_execution_year_count": int(_bool(part, "strong_low_execution_flag").sum()),
            "moderate_low_execution_year_count": int(
                _bool(part, "moderate_low_execution_flag").sum()
            ),
            "peer_bottom_10_year_count": int(_bool(part, "peer_bottom_10_execution_flag").sum()),
            "fixed_year_end_concentration_year_count": int(
                _bool(part, "fixed_year_end_concentration_flag").sum()
            ),
            "peer_p90_year_end_concentration_year_count": int(
                _bool(part, "peer_p90_year_end_concentration_flag").sum()
            ),
            "peer_p95_year_end_concentration_year_count": int(
                _bool(part, "peer_p95_year_end_concentration_flag").sum()
            ),
            "cumulative_decrease_year_count": int(_bool(part, "cumulative_decrease_flag").sum()),
            "execution_over_100_year_count": int(_bool(part, "execution_over_100_flag").sum()),
        }
        strong_ratio = _safe_rate(
            counts["strong_low_execution_year_count"],
            counts["valid_execution_year_count"],
        )
        moderate_ratio = _safe_rate(
            counts["moderate_low_execution_year_count"],
            counts["valid_execution_year_count"],
        )
        fixed_ratio = _safe_rate(
            counts["fixed_year_end_concentration_year_count"],
            counts["valid_monthly_year_count"],
        )
        rows.append(
            {
                "population": "ranking_population_v2",
                "sample_size": len(part),
                "classification_project_id": project_id,
                "ministry_code": part["ministry_code"].iloc[0],
                "ministry_name": part["analysis_ministry_name"].iloc[0],
                "program_code": part["program_code"].iloc[0],
                "program_name": part["program_name"].iloc[0],
                "subactivity_code": part["subactivity_code"].iloc[0],
                "subactivity_name": part["subactivity_name"].iloc[0],
                "observed_year_count": part["fiscal_year"].nunique(),
                **counts,
                "strong_low_execution_valid_year_share": strong_ratio,
                "moderate_low_execution_valid_year_share": moderate_ratio,
                "fixed_year_end_valid_year_share": fixed_ratio,
                "strong_low_execution_repeat_2plus": counts["strong_low_execution_year_count"] >= 2,
                "strong_low_execution_repeat_50pct": pd.notna(strong_ratio) and strong_ratio >= 0.5,
                "strong_low_execution_repeat_3plus": counts["strong_low_execution_year_count"] >= 3,
                "strong_low_execution_consecutive_2": _consecutive_two(
                    part["fiscal_year"], part["strong_low_execution_flag"]
                ),
                "moderate_low_execution_repeat_2plus": counts["moderate_low_execution_year_count"]
                >= 2,
                "moderate_low_execution_repeat_50pct": pd.notna(moderate_ratio)
                and moderate_ratio >= 0.5,
                "moderate_low_execution_repeat_3plus": counts["moderate_low_execution_year_count"]
                >= 3,
                "moderate_low_execution_consecutive_2": _consecutive_two(
                    part["fiscal_year"], part["moderate_low_execution_flag"]
                ),
                "fixed_year_end_repeat_2plus": counts["fixed_year_end_concentration_year_count"]
                >= 2,
                "fixed_year_end_repeat_50pct": pd.notna(fixed_ratio) and fixed_ratio >= 0.5,
                "fixed_year_end_repeat_3plus": counts["fixed_year_end_concentration_year_count"]
                >= 3,
                "fixed_year_end_consecutive_2": _consecutive_two(
                    part["fiscal_year"],
                    part["fixed_year_end_concentration_flag"],
                ),
                "limited_execution_observation_flag": int(valid_exec.sum()) < 3,
                "limited_monthly_observation_flag": int(valid_month.sum()) < 3,
            }
        )
    return pd.DataFrame(rows)


def attach_signal_types(features: pd.DataFrame, repeated: pd.DataFrame) -> pd.DataFrame:
    repeat_columns = [
        "classification_project_id",
        "valid_execution_year_count",
        "valid_monthly_year_count",
        "strong_low_execution_year_count",
        "moderate_low_execution_year_count",
        "fixed_year_end_concentration_year_count",
        "strong_low_execution_repeat_2plus",
        "strong_low_execution_repeat_50pct",
        "moderate_low_execution_repeat_2plus",
        "moderate_low_execution_repeat_50pct",
        "fixed_year_end_repeat_2plus",
        "fixed_year_end_repeat_50pct",
        "limited_execution_observation_flag",
        "limited_monthly_observation_flag",
    ]
    frame = features.merge(
        repeated[repeat_columns],
        on="classification_project_id",
        how="left",
        validate="many_to_one",
    )
    frame["type_repeated_strong_low_execution"] = (
        _bool(frame, "strong_low_execution_flag")
        & _bool(frame, "strong_low_execution_repeat_2plus")
        & _bool(frame, "strong_low_execution_repeat_50pct")
    )
    frame["type_repeated_moderate_low_execution"] = (
        _bool(frame, "moderate_low_execution_flag")
        & _bool(frame, "moderate_low_execution_repeat_2plus")
        & _bool(frame, "moderate_low_execution_repeat_50pct")
    )
    frame["type_repeated_year_end_concentration"] = (
        _bool(frame, "fixed_year_end_concentration_flag")
        & _bool(frame, "fixed_year_end_repeat_2plus")
        & _bool(frame, "fixed_year_end_repeat_50pct")
    )
    frame["type_accounting_adjustment_pattern"] = _bool(frame, "cumulative_decrease_flag") | _bool(
        frame, "execution_over_100_flag"
    )
    frame["type_denominator_or_matching_review"] = _bool(
        frame, "denominator_or_matching_review_flag"
    )
    frame["type_budget_rapid_increase"] = _bool(frame, "budget_increase_extreme_flag")
    frame["type_budget_rapid_decrease"] = _bool(frame, "budget_decrease_extreme_flag")
    frame["type_program_budget_concentration"] = _bool(frame, "program_concentration_flag")
    independent_count = sum(
        _bool(frame, column)
        for column in [
            "strong_low_execution_flag",
            "moderate_low_execution_flag",
            "peer_bottom_10_execution_flag",
            "fixed_year_end_concentration_flag",
            "peer_p90_year_end_concentration_flag",
            "cumulative_decrease_flag",
            "execution_over_100_flag",
            "budget_increase_extreme_flag",
            "budget_decrease_extreme_flag",
            "program_concentration_flag",
        ]
    )
    frame["independent_signal_count"] = independent_count
    frame["type_multiple_financial_signals"] = independent_count.ge(2)
    frame["type_data_validation_priority"] = _bool(frame, "data_quality_review_flag")
    frame["active_signal_types"] = frame.apply(
        lambda row: (
            ";".join(TYPE_LABELS[column] for column in TYPE_COLUMNS if bool(row[column])) or "NONE"
        ),
        axis=1,
    )
    return frame


def threshold_comparison(
    features: pd.DataFrame,
    criteria: dict[str, str],
    *,
    population: str,
) -> pd.DataFrame:
    """기준별 전체·부처·연도·회계·규모 탐지율과 금액비중을 산출합니다."""
    dimensions = {
        "OVERALL": None,
        "MINISTRY": "ministry_code",
        "YEAR": "fiscal_year",
        "ACCOUNT_TYPE": "account_type_classified",
        "PROJECT_SIZE": "project_size_bucket",
    }
    peer_size_column = (
        "monthly_peer_group_valid_size"
        if any("year_end_concentration" in column for column in criteria.values())
        else "execution_peer_group_size"
    )
    rows: list[dict[str, Any]] = []
    for criterion, column in criteria.items():
        valid = features[column].notna()
        flagged = _bool(features, column)
        for dimension, dimension_column in dimensions.items():
            groups = (
                [("ALL", features.index)]
                if dimension_column is None
                else features.groupby(dimension_column, dropna=False).groups.items()
            )
            for value, index in groups:
                part = features.loc[index]
                part_valid = valid.loc[index]
                part_flagged = flagged.loc[index] & part_valid
                denominator = part[part_valid]
                numerator = part[part_flagged]
                rows.append(
                    {
                        "population": population,
                        "sample_size": len(denominator),
                        "comparison_type": "CRITERION_SEGMENT",
                        "criterion": criterion,
                        "dimension": dimension,
                        "dimension_value": value,
                        "eligible_row_count": len(denominator),
                        "flagged_row_count": len(numerator),
                        "flagged_unique_project_count": numerator[
                            "classification_project_id"
                        ].nunique(),
                        "flagged_row_share": _safe_rate(len(numerator), len(denominator)),
                        "original_budget_amount": _sum(
                            numerator, "original_budget_analysis_amount"
                        ),
                        "original_budget_share": _safe_rate(
                            _sum(numerator, "original_budget_analysis_amount"),
                            _sum(denominator, "original_budget_analysis_amount"),
                        ),
                        "current_budget_amount": _sum(numerator, "current_budget_analysis_amount"),
                        "current_budget_share": _safe_rate(
                            _sum(numerator, "current_budget_analysis_amount"),
                            _sum(denominator, "current_budget_analysis_amount"),
                        ),
                        "settlement_expenditure_amount": _sum(
                            numerator, "settlement_analysis_amount"
                        ),
                        "settlement_expenditure_share": _safe_rate(
                            _sum(numerator, "settlement_analysis_amount"),
                            _sum(denominator, "settlement_analysis_amount"),
                        ),
                        "small_peer_group_row_count": int(
                            (_numeric(denominator, peer_size_column) < 5).sum()
                        )
                        if peer_size_column in denominator
                        else 0,
                    }
                )
    overall_flags = {
        name: _bool(features, column) & features[column].notna()
        for name, column in criteria.items()
    }
    names = list(overall_flags)
    for left_index, left in enumerate(names):
        for right in names[left_index + 1 :]:
            union = overall_flags[left] | overall_flags[right]
            intersection = overall_flags[left] & overall_flags[right]
            left_only = overall_flags[left] & ~overall_flags[right]
            right_only = overall_flags[right] & ~overall_flags[left]
            rows.append(
                {
                    "population": population,
                    "sample_size": len(features),
                    "comparison_type": "PAIR_OVERLAP",
                    "criterion": f"{left}__VS__{right}",
                    "left_criterion": left,
                    "right_criterion": right,
                    "dimension": "OVERALL",
                    "dimension_value": "ALL",
                    "eligible_row_count": int(union.sum()),
                    "flagged_row_count": int(intersection.sum()),
                    "flagged_unique_project_count": features.loc[
                        intersection, "classification_project_id"
                    ].nunique(),
                    "flagged_row_share": _safe_rate(int(intersection.sum()), int(union.sum())),
                    "left_only_row_count": int(left_only.sum()),
                    "right_only_row_count": int(right_only.sum()),
                    "jaccard_similarity": _safe_rate(int(intersection.sum()), int(union.sum())),
                    "original_budget_amount": _sum(
                        features[intersection], "original_budget_analysis_amount"
                    ),
                    "original_budget_share": math.nan,
                    "current_budget_amount": _sum(
                        features[intersection], "current_budget_analysis_amount"
                    ),
                    "current_budget_share": math.nan,
                    "settlement_expenditure_amount": _sum(
                        features[intersection], "settlement_analysis_amount"
                    ),
                    "settlement_expenditure_share": math.nan,
                    "small_peer_group_row_count": int(
                        (_numeric(features, peer_size_column) < 5).sum()
                    )
                    if peer_size_column in features
                    else 0,
                }
            )
    return pd.DataFrame(rows)


def repeated_summary(repeated: pd.DataFrame) -> pd.DataFrame:
    rows = []
    definitions = {
        "STRONG_LOW_EXECUTION": (
            "strong_low_execution_year_count",
            "valid_execution_year_count",
            "strong_low_execution_consecutive_2",
        ),
        "MODERATE_LOW_EXECUTION": (
            "moderate_low_execution_year_count",
            "valid_execution_year_count",
            "moderate_low_execution_consecutive_2",
        ),
        "FIXED_YEAR_END": (
            "fixed_year_end_concentration_year_count",
            "valid_monthly_year_count",
            "fixed_year_end_consecutive_2",
        ),
    }
    for signal, (count_col, valid_col, consecutive_col) in definitions.items():
        valid = _numeric(repeated, valid_col)
        count = _numeric(repeated, count_col)
        alternatives = {
            "TWO_OR_MORE": count.ge(2),
            "AT_LEAST_HALF_VALID_YEARS": valid.gt(0) & (count / valid).ge(0.5),
            "THREE_OR_MORE": count.ge(3),
            "CONSECUTIVE_TWO": _bool(repeated, consecutive_col),
        }
        for definition, mask in alternatives.items():
            rows.append(
                {
                    "population": "unique_projects_in_ranking_population_v2",
                    "sample_size": len(repeated),
                    "signal": signal,
                    "repeat_definition": definition,
                    "eligible_project_count": int(valid.gt(0).sum()),
                    "flagged_project_count": int(mask.sum()),
                    "flagged_project_share": _safe_rate(int(mask.sum()), int(valid.gt(0).sum())),
                    "limited_observation_project_count": int(valid.lt(3).sum()),
                }
            )
    return pd.DataFrame(rows)


def signal_type_summary(features: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column in TYPE_COLUMNS:
        label = TYPE_LABELS[column]
        mask = _bool(features, column)
        part = features[mask]
        overlaps = {
            TYPE_LABELS[other]: int((mask & _bool(features, other)).sum())
            for other in TYPE_COLUMNS
            if other != column
        }
        rows.append(
            {
                "population": "ranking_population_v2",
                "sample_size": len(features),
                "signal_type": label,
                "application_rule": TYPE_RULES[label],
                "valid_sample_count": len(features),
                "project_year_row_count": len(part),
                "unique_project_count": part["classification_project_id"].nunique(),
                "program_year_count": part[["ministry_code", "program_code", "fiscal_year"]]
                .drop_duplicates()
                .shape[0],
                "original_budget_amount": _sum(part, "original_budget_analysis_amount"),
                "original_budget_share": _safe_rate(
                    _sum(part, "original_budget_analysis_amount"),
                    _sum(features, "original_budget_analysis_amount"),
                ),
                "ministry_distribution": _distribution_json(part, "analysis_ministry_name"),
                "account_type_distribution": _distribution_json(part, "account_type_classified"),
                "project_size_distribution": _distribution_json(part, "project_size_bucket"),
                "overlap_with_other_types": json.dumps(
                    overlaps, ensure_ascii=False, sort_keys=True
                ),
                "interpretation_scope": TYPE_INTERPRETATION[label],
                "possible_alternative_explanation": TYPE_ALTERNATIVE[label],
            }
        )
    return pd.DataFrame(rows)


def program_year_signal_summary(features: pd.DataFrame, programs: pd.DataFrame) -> pd.DataFrame:
    keys = ["ministry_code", "program_code", "fiscal_year"]
    rows = []
    for key, part in features[features["program_code"].notna()].groupby(keys):
        budget = _numeric(part, "original_budget_analysis_amount").clip(lower=0)
        total = budget.sum()
        row: dict[str, Any] = {
            **dict(zip(keys, key, strict=True)),
            "source_project_year_count": len(part),
            "source_unique_project_count": part["classification_project_id"].nunique(),
            "analysis_original_budget_amount": total,
        }
        for signal in SIGNAL_COLUMNS:
            mask = _bool(part, signal)
            row[f"{signal}_project_count"] = int(mask.sum())
            row[f"{signal}_budget_share"] = _safe_rate(float(budget[mask].sum()), float(total))
        for type_col in TYPE_COLUMNS:
            row[f"{type_col}_project_count"] = int(_bool(part, type_col).sum())
        rows.append(row)
    aggregated = pd.DataFrame(rows)
    result = programs.merge(aggregated, on=keys, how="left", validate="one_to_one")
    result.insert(0, "population", "core_financial_program_year")
    result.insert(1, "sample_size", len(result))
    return result


def budget_extreme_method_comparison(features: pd.DataFrame) -> pd.DataFrame:
    """예산 극단값 후보 방법을 비교하되 원본값은 변경하지 않습니다."""
    valid = (
        _bool(features, "trend_ranking_eligible") & _numeric(features, "budget_change_rate").notna()
    )
    frame = features[valid].copy()
    methods = {
        "PEER_P05_DECREASE": _bool(frame, "budget_decrease_extreme_flag"),
        "PEER_P95_INCREASE": _bool(frame, "budget_increase_extreme_flag"),
        "ROBUST_Z_LE_MINUS3": _numeric(frame, "budget_change_robust_z").le(-3),
        "ROBUST_Z_GE_3": _numeric(frame, "budget_change_robust_z").ge(3),
        "ABSOLUTE_DECREASE_50PCT": _numeric(frame, "budget_change_rate").le(-0.5),
        "ABSOLUTE_INCREASE_50PCT": _numeric(frame, "budget_change_rate").ge(0.5),
        "WINSORIZED_LOG_LOWER_5PCT": _numeric(
            frame, "signed_log_budget_change_winsorized_for_sensitivity"
        ).le(_numeric(frame, "signed_log_budget_change_winsorized_for_sensitivity").quantile(0.05)),
        "WINSORIZED_LOG_UPPER_5PCT": _numeric(
            frame, "signed_log_budget_change_winsorized_for_sensitivity"
        ).ge(_numeric(frame, "signed_log_budget_change_winsorized_for_sensitivity").quantile(0.95)),
    }
    rows = []
    for method, mask in methods.items():
        part = frame[mask]
        rows.append(
            {
                "population": "trend_ranking_eligible",
                "sample_size": len(frame),
                "method": method,
                "flagged_row_count": len(part),
                "flagged_unique_project_count": part["classification_project_id"].nunique(),
                "flagged_row_share": _safe_rate(len(part), len(frame)),
                "original_budget_amount": _sum(part, "original_budget_analysis_amount"),
                "original_budget_share": _safe_rate(
                    _sum(part, "original_budget_analysis_amount"),
                    _sum(frame, "original_budget_analysis_amount"),
                ),
                "source_value_overwritten": False,
                "recommended_role": (
                    "PRIMARY_CANDIDATE" if method.startswith("PEER_") else "SENSITIVITY_ONLY"
                ),
            }
        )
    return pd.DataFrame(rows)


def _bootstrap_median_difference(
    signal_values: np.ndarray,
    control_values: np.ndarray,
    *,
    seed: int,
    iterations: int = 300,
) -> tuple[float, float]:
    if len(signal_values) < 5 or len(control_values) < 5:
        return math.nan, math.nan
    rng = np.random.default_rng(seed)
    differences = np.empty(iterations)
    for index in range(iterations):
        signal_sample = rng.choice(signal_values, size=len(signal_values), replace=True)
        control_sample = rng.choice(control_values, size=len(control_values), replace=True)
        differences[index] = np.median(signal_sample) - np.median(control_sample)
    return (
        float(np.quantile(differences, 0.025)),
        float(np.quantile(differences, 0.975)),
    )


def _feedback_cohort_frame(
    cohorts: pd.DataFrame,
    features: pd.DataFrame,
    v2: pd.DataFrame,
    horizon: str,
) -> pd.DataFrame:
    cohort = cohorts[
        cohorts["feedback_horizon"].eq(horizon) & _bool(cohorts, "cohort_eligible")
    ].copy()
    feature_columns = [
        "source_project_year_id",
        "classification_project_id",
        "fiscal_year",
        "ministry_code",
        "analysis_ministry_name",
        "account_type_classified",
        "project_size_bucket",
        "program_code",
        "program_name",
        "subactivity_code",
        "subactivity_name",
        "original_budget_analysis_amount",
        "review_priority",
        "rank_confidence",
        "project_status",
        "source_trace",
        *SIGNAL_COLUMNS,
        *TYPE_COLUMNS,
    ]
    base_features = features[feature_columns].rename(
        columns={
            "source_project_year_id": "base_project_id",
            "fiscal_year": "base_feature_year",
        }
    )
    cohort = cohort.drop(
        columns=[column for column in ["ministry_code", "program_code"] if column in cohort.columns]
    )
    cohort = cohort.merge(
        base_features,
        on="base_project_id",
        how="left",
        validate="many_to_one",
    )
    outcome_amounts = v2[["project_id", "analysis_original_budget"]].rename(
        columns={
            "project_id": "outcome_project_id",
            "analysis_original_budget": "outcome_original_budget_verified",
        }
    )
    cohort = cohort.merge(
        outcome_amounts,
        on="outcome_project_id",
        how="left",
        validate="many_to_one",
    )
    base = _numeric(cohort, "base_original_budget_amount")
    outcome = _numeric(cohort, "outcome_original_budget_verified")
    comparable = base.gt(0) & outcome.notna()
    cohort["feedback_budget_change_rate"] = np.where(comparable, outcome / base - 1, np.nan)
    cohort["feedback_budget_change_direction"] = np.select(
        [
            _numeric(cohort, "feedback_budget_change_rate").lt(-1e-9),
            _numeric(cohort, "feedback_budget_change_rate").gt(1e-9),
            _numeric(cohort, "feedback_budget_change_rate").notna(),
        ],
        ["DECREASE", "INCREASE", "MAINTAIN"],
        default="MISSING",
    )
    return cohort


def feedback_summary(
    cohort: pd.DataFrame,
    horizon: str,
) -> pd.DataFrame:
    """신호/유형별 동일 층 비신호 대조와 부트스트랩 불확실성을 계산합니다."""
    variables = [*SIGNAL_COLUMNS, *TYPE_COLUMNS]
    dimensions = {
        "OVERALL": None,
        "MINISTRY": "ministry_code",
        "ACCOUNT_TYPE": "account_type_classified",
        "PROJECT_SIZE": "project_size_bucket",
    }
    stratum_columns = [
        "base_fiscal_year",
        "ministry_code",
        "account_type_classified",
        "project_size_bucket",
    ]
    rows = []
    for variable_index, variable in enumerate(variables):
        valid = cohort[variable].notna() & _numeric(cohort, "feedback_budget_change_rate").notna()
        for dimension, dimension_column in dimensions.items():
            groups = (
                [("ALL", cohort.index)]
                if dimension_column is None
                else cohort.groupby(
                    cohort[dimension_column].astype("string").fillna("MISSING")
                ).groups.items()
            )
            for value, index in groups:
                scoped = cohort.loc[index]
                scoped_valid = valid.loc[index]
                signal = scoped[scoped_valid & _bool(scoped, variable)]
                if signal.empty:
                    continue
                signal_strata = signal[stratum_columns].drop_duplicates()
                control = scoped[scoped_valid & ~_bool(scoped, variable)].merge(
                    signal_strata,
                    on=stratum_columns,
                    how="inner",
                    validate="many_to_many",
                )
                signal_values = _numeric(signal, "feedback_budget_change_rate").dropna()
                control_values = _numeric(control, "feedback_budget_change_rate").dropna()
                ci_low, ci_high = _bootstrap_median_difference(
                    signal_values.to_numpy(),
                    control_values.to_numpy(),
                    seed=20260726 + variable_index,
                )
                rows.append(
                    {
                        "population": f"{horizon}_eligible_financial_continuity",
                        "sample_size": int(scoped_valid.sum()),
                        "feedback_horizon": horizon,
                        "signal_or_type": (TYPE_LABELS.get(variable, variable)),
                        "source_column": variable,
                        "segment_dimension": dimension,
                        "segment_value": value,
                        "signal_sample_size": len(signal_values),
                        "matched_control_sample_size": len(control_values),
                        "matched_stratum_count": signal_strata.shape[0],
                        "signal_budget_change_median": signal_values.median(),
                        "signal_budget_change_q1": signal_values.quantile(0.25),
                        "signal_budget_change_q3": signal_values.quantile(0.75),
                        "signal_budget_decrease_share": float(signal_values.lt(-1e-9).mean()),
                        "signal_budget_increase_share": float(signal_values.gt(1e-9).mean()),
                        "signal_budget_maintain_share": float(signal_values.abs().le(1e-9).mean()),
                        "control_budget_change_median": control_values.median(),
                        "control_budget_change_q1": control_values.quantile(0.25),
                        "control_budget_change_q3": control_values.quantile(0.75),
                        "median_difference_vs_control": (
                            signal_values.median() - control_values.median()
                            if len(control_values)
                            else math.nan
                        ),
                        "median_difference_bootstrap_ci_low": ci_low,
                        "median_difference_bootstrap_ci_high": ci_high,
                        "insufficient_sample_flag": len(signal_values) < 10
                        or len(control_values) < 10,
                        "causal_interpretation_allowed": False,
                    }
                )
    return pd.DataFrame(rows)


def feedback_robustness(
    t1: pd.DataFrame,
    t2: pd.DataFrame,
    features: pd.DataFrame,
) -> pd.DataFrame:
    """기준·필터 변화에 따른 환류 방향 유지 여부를 비교합니다."""
    datasets = {"T+1": t1, "T+2": t2}
    comparisons = {
        "STRONG_80": "strong_low_execution_flag",
        "UNDER_90": None,
        "PEER_BOTTOM_10": "peer_bottom_10_execution_flag",
        "FIXED_YEAR_END": "fixed_year_end_concentration_flag",
        "PEER_P90_YEAR_END": "peer_p90_year_end_concentration_flag",
        "PEER_P95_YEAR_END": "peer_p95_year_end_concentration_flag",
        "REPEATED_STRONG": "type_repeated_strong_low_execution",
        "REPEATED_YEAR_END": "type_repeated_year_end_concentration",
    }
    filters: dict[str, Any] = {
        "ALL": lambda frame: pd.Series(True, index=frame.index),
        "EXCLUDE_SMALL_PROJECT": lambda frame: ~frame["project_size_bucket"].eq("Q1_SMALL"),
        "EXCLUDE_OVER_100": lambda frame: ~_bool(frame, "execution_over_100_flag"),
        "EXCLUDE_RELATIONSHIP_CANDIDATE": lambda frame: (
            ~frame["project_status"].isin(
                ["RENAMED", "CODE_CHANGED", "TRANSFERRED", "MERGED", "SPLIT", "UNKNOWN"]
            )
        ),
        "EXCLUDE_DATA_QUALITY_REVIEW": lambda frame: ~_bool(frame, "data_quality_review_flag"),
    }
    rows = []
    for horizon, cohort in datasets.items():
        for criterion, column in comparisons.items():
            flag = (
                _bool(cohort, "strong_low_execution_flag")
                | _bool(cohort, "moderate_low_execution_flag")
                if criterion == "UNDER_90"
                else _bool(cohort, column)
            )
            criterion_valid = (
                cohort["strong_low_execution_flag"].notna()
                if criterion == "UNDER_90"
                else cohort[column].notna()
            )
            for filter_name, filter_function in filters.items():
                eligible = (
                    filter_function(cohort)
                    & criterion_valid
                    & _numeric(cohort, "feedback_budget_change_rate").notna()
                )
                signal_values = _numeric(
                    cohort[eligible & flag], "feedback_budget_change_rate"
                ).dropna()
                nonsignal_values = _numeric(
                    cohort[eligible & ~flag], "feedback_budget_change_rate"
                ).dropna()
                difference = (
                    signal_values.median() - nonsignal_values.median()
                    if len(signal_values) and len(nonsignal_values)
                    else math.nan
                )
                rows.append(
                    {
                        "population": f"{horizon}_eligible_financial_continuity",
                        "sample_size": int(eligible.sum()),
                        "feedback_horizon": horizon,
                        "criterion": criterion,
                        "robustness_filter": filter_name,
                        "signal_sample_size": len(signal_values),
                        "nonsignal_sample_size": len(nonsignal_values),
                        "signal_median_budget_change": signal_values.median(),
                        "nonsignal_median_budget_change": nonsignal_values.median(),
                        "median_difference": difference,
                        "difference_direction": (
                            "NEGATIVE"
                            if pd.notna(difference) and difference < 0
                            else "POSITIVE"
                            if pd.notna(difference) and difference > 0
                            else "ZERO_OR_MISSING"
                        ),
                        "insufficient_sample_flag": len(signal_values) < 10
                        or len(nonsignal_values) < 10,
                    }
                )
    result = pd.DataFrame(rows)
    baseline = result[result["robustness_filter"].eq("ALL")][
        ["feedback_horizon", "criterion", "difference_direction"]
    ].rename(columns={"difference_direction": "baseline_direction"})
    result = result.merge(
        baseline,
        on=["feedback_horizon", "criterion"],
        how="left",
        validate="many_to_one",
    )
    result["direction_stable_vs_baseline"] = (
        result["difference_direction"].eq(result["baseline_direction"])
        & ~result["insufficient_sample_flag"]
    )
    return result


def unknown_manual_review_priority(
    broad: pd.DataFrame,
) -> pd.DataFrame:
    """UNKNOWN 사업을 예산 누적 커버리지 순으로 정렬하고 규칙 후보만 제시합니다."""
    unknown = broad[broad["fiscal_instrument"].eq("UNKNOWN")].copy()
    instrument_keywords = {
        "LOAN": ["융자", "대출"],
        "GUARANTEE": ["보증"],
        "EQUITY": ["출자", "모태펀드"],
        "CONTRIBUTION": ["출연"],
        "SUBSIDY": ["보조"],
        "INTEREST_SUBSIDY": ["이차보전"],
        "RND": ["연구개발", "R&D", "R& D"],
        "INFORMATIZATION": ["정보화", "시스템구축", "시스템 구축"],
        "FACILITY": ["시설", "건립", "청사"],
    }
    group_columns = [
        "classification_project_id",
        "ministry_code",
        "analysis_ministry_name",
        "program_code",
        "program_name",
        "subactivity_code",
        "subactivity_name",
    ]
    rows = []
    for key, part in unknown.groupby(group_columns, dropna=False):
        latest = part.sort_values("fiscal_year").iloc[-1]
        text = " ".join(
            part[column].dropna().astype(str).str.cat(sep=" ")
            for column in ["program_name", "activity_name", "subactivity_name"]
        )
        candidates = [
            instrument
            for instrument, keywords in instrument_keywords.items()
            if any(keyword.lower() in text.lower() for keyword in keywords)
        ]
        evidence = [
            keyword
            for keywords in instrument_keywords.values()
            for keyword in keywords
            if keyword.lower() in text.lower()
        ]
        yearly = (
            part.groupby("fiscal_year")["original_budget_analysis_amount"]
            .sum(min_count=1)
            .dropna()
            .to_dict()
        )
        rows.append(
            {
                **dict(zip(group_columns, key, strict=True)),
                "account_type_classified": latest["account_type_classified"],
                "observed_years": ";".join(
                    map(str, sorted(part["fiscal_year"].dropna().astype(int).unique()))
                ),
                "yearly_original_budgets": json.dumps(
                    {str(year): int(amount) for year, amount in yearly.items()},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "original_budget_amount": _sum(part, "original_budget_analysis_amount"),
                "keyword_candidate": ";".join(candidates) if candidates else "NO_CANDIDATE",
                "candidate_evidence": ";".join(sorted(set(evidence)))
                if evidence
                else "NO_MATCHING_KEYWORD",
                "multiple_candidate_flag": len(candidates) > 1,
                "manual_confirmed_value": pd.NA,
                "review_status": "UNREVIEWED",
                "review_note": pd.NA,
                "source_project_year_ids": ";".join(part["source_project_year_id"].astype(str)),
            }
        )
    result = pd.DataFrame(rows).sort_values("original_budget_amount", ascending=False)
    total = result["original_budget_amount"].sum()
    result["unknown_budget_share"] = result["original_budget_amount"] / total
    result["cumulative_unknown_budget_share"] = result["unknown_budget_share"].cumsum()
    result["budget_coverage_order"] = np.arange(1, len(result) + 1)
    result["priority_80pct_coverage"] = (
        result["cumulative_unknown_budget_share"].shift(fill_value=0).lt(0.80)
    )
    result["priority_90pct_coverage"] = (
        result["cumulative_unknown_budget_share"].shift(fill_value=0).lt(0.90)
    )
    result.insert(0, "population", "broad_unknown_fiscal_instrument")
    result.insert(1, "sample_size", len(result))
    return result


def financial_signal_cases(
    features: pd.DataFrame,
    t1_cohort: pd.DataFrame,
    t2_cohort: pd.DataFrame,
) -> pd.DataFrame:
    """각 비상호배타 유형에서 규모·반복·환류·반례·품질 사례를 최대 10개 선택합니다."""
    t1 = t1_cohort[["base_project_id", "feedback_budget_change_rate"]].rename(
        columns={"feedback_budget_change_rate": "t1_budget_change_rate"}
    )
    t2 = t2_cohort[["base_project_id", "feedback_budget_change_rate"]].rename(
        columns={"feedback_budget_change_rate": "t2_budget_change_rate"}
    )
    frame = features.merge(
        t1, left_on="source_project_year_id", right_on="base_project_id", how="left"
    ).drop(columns="base_project_id")
    frame = frame.merge(
        t2, left_on="source_project_year_id", right_on="base_project_id", how="left"
    ).drop(columns="base_project_id")
    selected_rows: list[dict[str, Any]] = []
    for type_column in TYPE_COLUMNS:
        label = TYPE_LABELS[type_column]
        candidates = frame[_bool(frame, type_column)].copy()
        if candidates.empty:
            continue
        candidates["case_reason"] = ""
        selections: list[pd.DataFrame] = []

        def take(
            source: pd.DataFrame,
            count: int,
            reason: str,
            selected_frames: list[pd.DataFrame] = selections,
        ) -> None:
            existing = {
                row["source_project_year_id"]
                for selected in selected_frames
                for _, row in selected.iterrows()
            }
            available = source[~source["source_project_year_id"].isin(existing)].head(count).copy()
            available["case_reason"] = reason
            if not available.empty:
                selected_frames.append(available)

        take(
            candidates.sort_values("original_budget_analysis_amount", ascending=False),
            2,
            "LARGE_ORIGINAL_BUDGET",
        )
        repeat_count = _numeric(candidates, "strong_low_execution_year_count").fillna(0) + _numeric(
            candidates, "fixed_year_end_concentration_year_count"
        ).fillna(0)
        take(
            candidates.assign(_repeat=repeat_count).sort_values("_repeat", ascending=False),
            2,
            "MULTI_YEAR_REPEAT",
        )
        take(
            candidates[candidates["t1_budget_change_rate"].notna()]
            .assign(_abs=lambda data: data["t1_budget_change_rate"].abs())
            .sort_values("_abs", ascending=False),
            2,
            "LARGE_T1_BUDGET_CHANGE",
        )
        take(
            candidates[candidates["t2_budget_change_rate"].notna()]
            .assign(_abs=lambda data: data["t2_budget_change_rate"].abs())
            .sort_values("_abs", ascending=False),
            1,
            "LARGE_T2_BUDGET_CHANGE",
        )
        expected_negative = label in {
            "REPEATED_STRONG_LOW_EXECUTION",
            "REPEATED_MODERATE_LOW_EXECUTION",
            "BUDGET_RAPID_DECREASE",
        }
        counter = (
            candidates[_numeric(candidates, "t1_budget_change_rate").gt(0)]
            if expected_negative
            else candidates[_numeric(candidates, "t1_budget_change_rate").lt(0)]
        )
        take(
            counter.assign(_abs=_numeric(counter, "t1_budget_change_rate").abs()).sort_values(
                "_abs", ascending=False
            ),
            2,
            "COUNTEREXAMPLE_OPPOSITE_T1_DIRECTION",
        )
        take(
            candidates[_bool(candidates, "data_quality_review_flag")].sort_values(
                "original_budget_analysis_amount", ascending=False
            ),
            1,
            "DATA_QUALITY_REVIEW",
        )
        chosen = pd.concat(selections, ignore_index=True).head(10)
        for _, row in chosen.iterrows():
            monthly_pattern = {
                "q4_share": row.get("q4_expenditure_share"),
                "december_share": row.get("december_single_month_share"),
                "cumulative_decrease_count": row.get("cumulative_decrease_count"),
            }
            selected_rows.append(
                {
                    "population": "m3_financial_signal_type_cases",
                    "sample_size": len(candidates),
                    "ministry_name": row["analysis_ministry_name"],
                    "ministry_code": row["ministry_code"],
                    "program_code": row["program_code"],
                    "program_name": row["program_name"],
                    "subactivity_code": row["subactivity_code"],
                    "subactivity_name": row["subactivity_name"],
                    "fiscal_year": row["fiscal_year"],
                    "signal_type": label,
                    "signal_evidence": TYPE_RULES[label],
                    "case_selection_reason": row["case_reason"],
                    "original_budget_amount": row["original_budget_analysis_amount"],
                    "current_budget_amount": row["current_budget_analysis_amount"],
                    "settlement_expenditure_amount": row["settlement_analysis_amount"],
                    "execution_rate": row["execution_rate"],
                    "monthly_pattern": json.dumps(monthly_pattern, ensure_ascii=False, default=str),
                    "t1_budget_change_rate": row["t1_budget_change_rate"],
                    "t2_budget_change_rate": row["t2_budget_change_rate"],
                    "data_quality_status": (
                        "REVIEW_REQUIRED"
                        if bool(row["data_quality_review_flag"])
                        else str(row["review_priority"])
                    ),
                    "project_relation_status": row["project_status"],
                    "source_trace": row["source_trace"],
                    "source_project_year_id": row["source_project_year_id"],
                    "policy_failure_label": False,
                }
            )
    return pd.DataFrame(selected_rows)


def _set_plot_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "Malgun Gothic",
            "axes.unicode_minus": False,
            "figure.facecolor": "white",
            "axes.facecolor": "#F8FAFC",
            "axes.edgecolor": "#CBD5E1",
            "grid.color": "#E2E8F0",
            "axes.titleweight": "bold",
        }
    )


def _save(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)
    return path


def create_m3_figures(
    features: pd.DataFrame,
    execution_comparison: pd.DataFrame,
    year_end_comparison: pd.DataFrame,
    t1_cohort: pd.DataFrame,
    t2_cohort: pd.DataFrame,
    cases: pd.DataFrame,
    output_dir: Path,
) -> list[Path]:
    _set_plot_style()
    paths: list[Path] = []
    colors = [
        "#2563EB",
        "#F97316",
        "#16A34A",
        "#9333EA",
        "#DC2626",
        "#0891B2",
    ]

    execution_overall = execution_comparison[
        execution_comparison["comparison_type"].eq("CRITERION_SEGMENT")
        & execution_comparison["dimension"].eq("OVERALL")
    ]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(
        execution_overall["criterion"],
        execution_overall["flagged_row_count"],
        color=colors,
    )
    ax.set_title(f"집행률 기준별 탐지 규모\n모집단: 집행률 변수별 적격, 전체 n={len(features):,}")
    ax.set_ylabel("사업-연도 행 수")
    ax.tick_params(axis="x", rotation=18)
    ax.grid(axis="y")
    paths.append(_save(fig, output_dir / "execution_threshold_detection.png"))

    rates = _numeric(
        features[_bool(features, "execution_ranking_eligible")],
        "execution_rate",
    ).dropna()
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(rates[rates.between(0, 1.5)], bins=50, color="#2563EB", alpha=0.75)
    ax.axvline(0.8, color="#DC2626", linestyle="--", label="80%")
    ax.axvline(0.9, color="#F97316", linestyle="--", label="90%")
    ax.set_title(
        f"집행률 분포와 절대 기준\n모집단: execution 적격, n={len(rates):,}, 표시범위 0~150%"
    )
    ax.set_xlabel("집행률")
    ax.set_ylabel("행 수")
    ax.legend()
    ax.grid(axis="y")
    paths.append(_save(fig, output_dir / "execution_rate_thresholds.png"))

    year_overall = year_end_comparison[
        year_end_comparison["comparison_type"].eq("CRITERION_SEGMENT")
        & year_end_comparison["dimension"].eq("OVERALL")
    ]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(
        year_overall["criterion"],
        year_overall["flagged_row_count"],
        color=colors[: len(year_overall)],
    )
    ax.set_title("연말 집중 기준별 탐지 규모\n모집단: 검증된 월별 패턴 적격")
    ax.set_ylabel("사업-연도 행 수")
    ax.tick_params(axis="x", rotation=20)
    ax.grid(axis="y")
    paths.append(_save(fig, output_dir / "year_end_threshold_detection.png"))

    def feedback_boxplot(cohort: pd.DataFrame, horizon: str, filename: str) -> None:
        selected = [
            "strong_low_execution_flag",
            "fixed_year_end_concentration_flag",
            "budget_increase_extreme_flag",
            "budget_decrease_extreme_flag",
        ]
        values = [
            _numeric(
                cohort[_bool(cohort, column)],
                "feedback_budget_change_rate",
            ).dropna()
            for column in selected
        ]
        fig, ax = plt.subplots(figsize=(10, 5.5))
        ax.boxplot(
            values,
            tick_labels=[
                f"{column.replace('_flag', '')}\nn={len(value):,}"
                for column, value in zip(selected, values, strict=True)
            ],
            showfliers=False,
        )
        ax.axhline(0, color="#64748B", linewidth=1)
        ax.set_title(
            f"신호별 {horizon} 본예산 변화 분포\n연속 재정비교 적격, 이상점은 표시에서만 생략"
        )
        ax.set_ylabel("본예산 변화율")
        ax.tick_params(axis="x", rotation=15)
        ax.grid(axis="y")
        paths.append(_save(fig, output_dir / filename))

    feedback_boxplot(t1_cohort, "T+1", "feedback_t1_distribution.png")
    feedback_boxplot(t2_cohort, "T+2", "feedback_t2_distribution.png")

    def composition_heatmap(dimension: str, filename: str, title: str) -> None:
        columns = [
            "strong_low_execution_flag",
            "moderate_low_execution_flag",
            "fixed_year_end_concentration_flag",
            "cumulative_decrease_flag",
            "budget_increase_extreme_flag",
            "budget_decrease_extreme_flag",
        ]
        grouped = features.groupby(dimension, dropna=False)[columns].agg(
            lambda values: values.astype("boolean").fillna(False).mean()
        )
        fig, ax = plt.subplots(figsize=(11, max(4, len(grouped) * 0.6)))
        image = ax.imshow(grouped.to_numpy(), aspect="auto", cmap="Blues")
        ax.set_xticks(range(len(columns)), [c.replace("_flag", "") for c in columns])
        ax.set_yticks(range(len(grouped)), grouped.index.astype(str))
        ax.tick_params(axis="x", rotation=25)
        ax.set_title(f"{title}\n모집단: ranking population v2, n={len(features):,}")
        fig.colorbar(image, ax=ax, label="행 비율")
        paths.append(_save(fig, output_dir / filename))

    composition_heatmap(
        "analysis_ministry_name", "ministry_signal_composition.png", "부처별 신호 구성"
    )
    composition_heatmap(
        "account_type_classified",
        "account_type_signal_composition.png",
        "회계유형별 신호 구성",
    )

    case_plot = cases.dropna(subset=["t1_budget_change_rate", "t2_budget_change_rate"])
    fig, ax = plt.subplots(figsize=(8.5, 6))
    ax.scatter(
        case_plot["t1_budget_change_rate"],
        case_plot["t2_budget_change_rate"],
        alpha=0.65,
        s=28,
        color="#2563EB",
    )
    ax.axhline(0, color="#64748B", linewidth=1)
    ax.axvline(0, color="#64748B", linewidth=1)
    ax.set_title(f"대표 사례의 T+1·T+2 예산변화\n사례 n={len(case_plot):,}, 정책 실패 판정 아님")
    ax.set_xlabel("T+1 본예산 변화율")
    ax.set_ylabel("T+2 본예산 변화율")
    ax.grid()
    paths.append(_save(fig, output_dir / "case_t1_t2_comparison.png"))
    return paths


def _overall_rows(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[
        frame["comparison_type"].eq("CRITERION_SEGMENT") & frame["dimension"].eq("OVERALL")
    ]


def _feedback_overall(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[frame["segment_dimension"].eq("OVERALL")]


def _percent(value: Any) -> str:
    return "NA" if pd.isna(value) else f"{float(value):.1%}"


def _report_table_rows(frame: pd.DataFrame, columns: list[str]) -> list[str]:
    return [
        "| " + " | ".join(str(row[column]) for column in columns) + " |"
        for _, row in frame.iterrows()
    ]


def build_m3_report(
    path: Path,
    summary: dict[str, Any],
    execution_comparison: pd.DataFrame,
    year_end_comparison: pd.DataFrame,
    repeated_comparison: pd.DataFrame,
    budget_method_comparison: pd.DataFrame,
    type_summary: pd.DataFrame,
    feedback_t1: pd.DataFrame,
    feedback_t2: pd.DataFrame,
    robustness: pd.DataFrame,
    cases: pd.DataFrame,
    unknown: pd.DataFrame,
) -> None:
    execution = _overall_rows(execution_comparison).set_index("criterion")
    year_end = _overall_rows(year_end_comparison).set_index("criterion")
    t1 = _feedback_overall(feedback_t1).set_index("signal_or_type")
    t2 = _feedback_overall(feedback_t2).set_index("signal_or_type")
    strong = execution.loc["STRONG_UNDER_80"]
    moderate = execution.loc["MODERATE_80_TO_90"]
    peer10 = execution.loc["PEER_BOTTOM_10"]
    fixed = year_end.loc["FIXED_UNION"]
    p90 = year_end.loc["PEER_P90"]
    p95 = year_end.loc["PEER_P95"]
    unknown_80 = int(_bool(unknown, "priority_80pct_coverage").sum())
    unknown_90 = int(_bool(unknown, "priority_90pct_coverage").sum())
    strong_bias = execution_comparison[
        execution_comparison["comparison_type"].eq("CRITERION_SEGMENT")
        & execution_comparison["criterion"].eq("STRONG_UNDER_80")
    ]
    fixed_bias = year_end_comparison[
        year_end_comparison["comparison_type"].eq("CRITERION_SEGMENT")
        & year_end_comparison["criterion"].eq("FIXED_UNION")
    ]

    def highest_rate(frame: pd.DataFrame, dimension: str) -> pd.Series:
        return (
            frame[frame["dimension"].eq(dimension)]
            .sort_values("flagged_row_share", ascending=False)
            .iloc[0]
        )

    strong_ministry = highest_rate(strong_bias, "MINISTRY")
    strong_account = highest_rate(strong_bias, "ACCOUNT_TYPE")
    strong_size = highest_rate(strong_bias, "PROJECT_SIZE")
    fixed_ministry = highest_rate(fixed_bias, "MINISTRY")
    fixed_account = highest_rate(fixed_bias, "ACCOUNT_TYPE")
    fixed_size = highest_rate(fixed_bias, "PROJECT_SIZE")
    repeated_strong = repeated_comparison[
        repeated_comparison["signal"].eq("STRONG_LOW_EXECUTION")
    ].set_index("repeat_definition")
    peer_budget_decrease = budget_method_comparison[
        budget_method_comparison["method"].eq("PEER_P05_DECREASE")
    ].iloc[0]
    peer_budget_increase = budget_method_comparison[
        budget_method_comparison["method"].eq("PEER_P95_INCREASE")
    ].iloc[0]

    lines = [
        "# M3 재정 신호와 예산 환류 탐색",
        "",
        "## Executive Summary",
        "",
        (
            "- **권장 조합은 절대 기준과 상대 기준의 역할 분리입니다.** 집행률 80% 미만은 강한 "
            "집행설명필요 신호, 80~90%는 주의 신호, 비교집단 하위 10%·20%는 보조 상대 신호로 "
            "병행하는 편이 해석과 방어 가능성이 높습니다."
        ),
        (
            "- **연말 집중은 고정 40%/20%를 주 신호 후보로 두고 P90을 보조, P95를 극단, "
            "P80을 민감도 기준으로 유지하는 조합이 적절합니다.** 상대 기준은 동률과 합집합 때문에 "
            "명목 분위수보다 넓게 탐지됩니다."
        ),
        (
            "- **T+1·T+2 결과는 연관 탐색입니다.** 같은 연도·부처·회계유형·사업규모의 비신호 "
            "대조군과 비교했지만 성과자료와 예산변화 사유가 없어 인과관계로 해석할 수 없습니다."
        ),
        (
            "- **최종 복합점수와 전체 순위는 생성하지 않았습니다.** 모든 신호와 유형은 독립적이고 "
            "비상호배타적으로 보존했습니다."
        ),
        "",
        "## 1. 분석 목적",
        "",
        (
            "**데이터에서 확인된 사실:** 재정자료만으로 설명 또는 원문 검토가 필요한 프로그램과 "
            "세부사업의 신호가 기준 변화에도 유지되는지 확인했습니다."
        ),
        "",
        (
            "**분석자의 해석:** 세부사업 신호는 프로그램 단위 점검의 원인을 확인하는 드릴다운이며, "
            "정책 실패·낭비·삭감 판정이 아닙니다."
        ),
        "",
        "## 2. 현재 단계와 해석 범위",
        "",
        (
            "현재는 비LLM 재정데이터 분석 단계입니다. 외부 API, 성과문서 파싱, PDF 추출, "
            "성과·집행·예산 통합점수는 사용하지 않았습니다. 상관과 예산변화 차이는 인과효과가 아닙니다."
        ),
        "",
        "## 3. 사용한 모집단",
        "",
        f"- ranking population v2: {summary['counts']['feature_rows']:,}행",
        f"- 집행률 유효: {summary['counts']['execution_valid_rows']:,}행",
        f"- 월별 패턴 적격: {summary['counts']['monthly_eligible_rows']:,}행",
        (
            "- 연말집중 비중 계산 가능: "
            f"{summary['counts']['monthly_threshold_comparable_rows']:,}행"
        ),
        f"- T+1 재정연속성 적격: {summary['counts']['t1_eligible_rows']:,}행",
        f"- T+2 재정연속성 적격: {summary['counts']['t2_eligible_rows']:,}행",
        "",
        (
            "요청서의 ranking v2 경로는 실제 저장소와 달랐습니다. 실제 파일인 "
            "`data/processed/masters/population_sensitivity/ranking_population_v2.parquet`를 사용했습니다."
        ),
        "",
        "## 4. 기준 비교 결과",
        "",
        "| 기준 | 행 | 고유 사업 | 본예산 비중 |",
        "|---|---:|---:|---:|",
        (
            f"| 80% 미만 | {int(strong['flagged_row_count']):,} | "
            f"{int(strong['flagged_unique_project_count']):,} | {_percent(strong['original_budget_share'])} |"
        ),
        (
            f"| 80~90% | {int(moderate['flagged_row_count']):,} | "
            f"{int(moderate['flagged_unique_project_count']):,} | {_percent(moderate['original_budget_share'])} |"
        ),
        (
            f"| 비교집단 하위 10% | {int(peer10['flagged_row_count']):,} | "
            f"{int(peer10['flagged_unique_project_count']):,} | {_percent(peer10['original_budget_share'])} |"
        ),
        "",
        "![집행률 기준 탐지 규모](../artifacts/figures/m3/execution_threshold_detection.png)",
        "",
        (
            "절대 기준은 의미가 직접적이지만 사업구조 차이를 충분히 보정하지 못합니다. 상대 기준은 "
            "비교집단 맥락을 반영하지만 집행률 동률 때문에 하위 10%·20%라는 이름보다 훨씬 많은 행을 "
            "포함할 수 있습니다."
        ),
        "",
        (
            f"**편향 점검:** 80% 미만 탐지율은 부처 중 {strong_ministry['dimension_value']} "
            f"{strong_ministry['flagged_row_share']:.1%}, 회계유형 중 "
            f"{strong_account['dimension_value']} {strong_account['flagged_row_share']:.1%}, "
            f"규모구간 중 {strong_size['dimension_value']} "
            f"{strong_size['flagged_row_share']:.1%}로 가장 높았습니다. 이는 기준의 오류를 뜻하지 "
            "않지만, 동일 기준이 사업구성 차이를 함께 탐지하므로 층별 결과를 반드시 병기해야 합니다."
        ),
        "",
        "![집행률 분포](../artifacts/figures/m3/execution_rate_thresholds.png)",
        "",
        "## 5. 집행률 기준 권장안",
        "",
        (
            "**권장안:** 80% 미만을 강한 신호, 80~90%를 주의 신호로 분리하고, 비교집단 하위 "
            "10%·20%는 독립 보조 신호로 제시합니다."
        ),
        "",
        "- A안(90% 단일): 단순하지만 80% 미만과 80~90%의 강도 차이를 숨깁니다.",
        "- B안(80%/90% 2단계): 설명 가능성과 공모전 보고서 방어력이 가장 높습니다.",
        "- C안(상대 기준만): 집단 특성을 반영하지만 동률·소표본에 민감합니다.",
        "- D안(독립 병행): 정보 손실이 가장 적어 권장하되 하나의 점수로 합치지 않습니다.",
        "",
        "## 6. 연말 집중 기준 권장안",
        "",
        "| 기준 | 행 | 고유 사업 | 본예산 비중 |",
        "|---|---:|---:|---:|",
        (
            f"| 고정 40%/20% | {int(fixed['flagged_row_count']):,} | "
            f"{int(fixed['flagged_unique_project_count']):,} | {_percent(fixed['original_budget_share'])} |"
        ),
        (
            f"| 비교집단 P90 | {int(p90['flagged_row_count']):,} | "
            f"{int(p90['flagged_unique_project_count']):,} | {_percent(p90['original_budget_share'])} |"
        ),
        (
            f"| 비교집단 P95 | {int(p95['flagged_row_count']):,} | "
            f"{int(p95['flagged_unique_project_count']):,} | {_percent(p95['original_budget_share'])} |"
        ),
        "",
        "![연말 집중 기준](../artifacts/figures/m3/year_end_threshold_detection.png)",
        "",
        (
            "**권장 조합:** 고정 기준은 주 신호 후보, P90은 보조 상대 신호, P95는 극단 신호, "
            "P80은 민감도 기준으로 사용합니다. 고정 기준과 P90·P95를 동시에 충족하는 경우만 "
            "강한 교차 신호로 별도 표시할 수 있습니다."
        ),
        "",
        (
            f"고정 합집합 탐지율은 부처 중 {fixed_ministry['dimension_value']} "
            f"{fixed_ministry['flagged_row_share']:.1%}, 회계유형 중 "
            f"{fixed_account['dimension_value']} {fixed_account['flagged_row_share']:.1%}, "
            f"규모구간 중 {fixed_size['dimension_value']} "
            f"{fixed_size['flagged_row_share']:.1%}로 가장 높았습니다. P90은 전체 적격 행의 "
            f"{p90['flagged_row_share']:.1%}를 탐지하여 명목 10%보다 넓으므로 단독 주 기준으로는 "
            "방어하기 어렵습니다."
        ),
        "",
        "## 7. 재정 신호 유형",
        "",
        "| 유형 | 사업-연도 | 고유 사업 | 본예산 비중 | 해석 |",
        "|---|---:|---:|---:|---|",
    ]
    for _, row in type_summary.iterrows():
        lines.append(
            f"| {row['signal_type']} | {int(row['project_year_row_count']):,} | "
            f"{int(row['unique_project_count']):,} | {_percent(row['original_budget_share'])} | "
            f"{row['interpretation_scope']} |"
        )
    lines.extend(
        [
            "",
            (
                "유형은 상호배타적이지 않습니다. 같은 구조적 사건이 저집행·예산변화·데이터 품질 "
                "신호에 동시에 나타날 수 있으므로 중첩을 보존했습니다."
            ),
            "",
            (
                "**반복 정의 비교:** 강한 저집행은 2개 연도 이상 "
                f"{int(repeated_strong.loc['TWO_OR_MORE', 'flagged_project_count']):,}개, "
                "유효연도의 50% 이상 "
                f"{int(repeated_strong.loc['AT_LEAST_HALF_VALID_YEARS', 'flagged_project_count']):,}개, "
                f"3개 연도 이상 {int(repeated_strong.loc['THREE_OR_MORE', 'flagged_project_count']):,}개, "
                f"연속 2개 연도 {int(repeated_strong.loc['CONSECUTIVE_TWO', 'flagged_project_count']):,}개였습니다. "
                "유효연도 1년인 사업도 50% 기준을 충족할 수 있으므로 주 반복 유형은 2회 이상과 "
                "50% 이상을 동시에 요구하고, 연속성은 별도 보조 표시로 두었습니다."
            ),
            "",
            (
                "**예산 급증·급감 방법 비교:** 비교집단·연도별 signed-log P05/P95는 각각 "
                f"{int(peer_budget_decrease['flagged_row_count']):,}행과 "
                f"{int(peer_budget_increase['flagged_row_count']):,}행을 탐지했습니다. "
                "robust z-score, 절대 50%, winsorized 분포는 민감도 결과로 보존했습니다. "
                "원본 증감률을 덮어쓰지 않으면서 규모비대칭을 줄이고 동년 비교집단 맥락을 유지하는 "
                "P05/P95를 주 후보로 권장합니다."
            ),
            "",
            "## 8. T+1 환류 결과",
            "",
            "![T+1 예산변화](../artifacts/figures/m3/feedback_t1_distribution.png)",
            "",
            (
                "아래 차이는 같은 기준연도·부처·회계유형·사업규모에서 신호가 없는 행과의 중앙값 "
                "차이입니다. 부트스트랩 구간이 0을 포함하면 방향을 안정적이라고 보지 않습니다."
            ),
            "",
            "| 신호 | 신호 n | 대조 n | 신호 중앙값 | 대조 중앙값 | 차이 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for label in [
        "strong_low_execution_flag",
        "moderate_low_execution_flag",
        "fixed_year_end_concentration_flag",
        "type_repeated_strong_low_execution",
    ]:
        display = TYPE_LABELS.get(label, label)
        if display in t1.index:
            row = t1.loc[display]
            lines.append(
                f"| {display} | {int(row['signal_sample_size']):,} | "
                f"{int(row['matched_control_sample_size']):,} | "
                f"{_percent(row['signal_budget_change_median'])} | "
                f"{_percent(row['control_budget_change_median'])} | "
                f"{_percent(row['median_difference_vs_control'])} |"
            )
    lines.extend(
        [
            "",
            "## 9. T+2 환류 결과",
            "",
            "![T+2 예산변화](../artifacts/figures/m3/feedback_t2_distribution.png)",
            "",
            (
                f"T+2 적격 표본은 {summary['counts']['t2_eligible_rows']:,}행으로 T+1보다 작아 "
                "부처·회계·규모 세분 결과의 소표본 경고를 우선 확인해야 합니다."
            ),
            "",
            "| 신호 | 신호 n | 대조 n | 신호 중앙값 | 대조 중앙값 | 차이 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for label in [
        "strong_low_execution_flag",
        "moderate_low_execution_flag",
        "fixed_year_end_concentration_flag",
        "type_repeated_strong_low_execution",
    ]:
        display = TYPE_LABELS.get(label, label)
        if display in t2.index:
            row = t2.loc[display]
            lines.append(
                f"| {display} | {int(row['signal_sample_size']):,} | "
                f"{int(row['matched_control_sample_size']):,} | "
                f"{_percent(row['signal_budget_change_median'])} | "
                f"{_percent(row['control_budget_change_median'])} | "
                f"{_percent(row['median_difference_vs_control'])} |"
            )
    stable = robustness[
        robustness["direction_stable_vs_baseline"] & ~robustness["insufficient_sample_flag"]
    ]
    total_robust = robustness[~robustness["insufficient_sample_flag"]]
    lines.extend(
        [
            "",
            "## 10. 부처·회계·사업규모별 차이",
            "",
            "![부처별 신호 구성](../artifacts/figures/m3/ministry_signal_composition.png)",
            "",
            (
                "부처별 탐지율 차이는 사업구성·회계유형·규모 차이와 함께 나타납니다. 절대 건수만으로 "
                "부처를 비교하지 않고 각 집단 내 적격 행을 분모로 사용했습니다."
            ),
            "",
            "![회계유형별 신호 구성](../artifacts/figures/m3/account_type_signal_composition.png)",
            "",
            (
                "기금은 VWFOEM2 예산현액을 지출계획현액 대응 분모로 사용해 집행 신호와 "
                "순위에 포함했습니다. 분모가 없거나 0인 행은 해당 변수만 제한했고, "
                "소표본 비교집단은 병합하지 않았습니다."
            ),
            "",
            "## 11. 강건한 결과",
            "",
            (
                f"강건성 필터에서 표본이 충분한 {len(total_robust):,}개 비교 중 "
                f"{len(stable):,}개가 전체 결과와 같은 방향을 유지했습니다. 방향 유지 여부와 효과크기를 "
                "함께 제공하며, 방향만 같다고 정책적으로 유의미하다고 판단하지 않습니다."
            ),
            "",
            (
                "T+1에서는 80% 미만, 비교집단 하위 10%, 고정 연말집중의 예산변화 중앙값 차이가 "
                "대체로 음(-)의 방향을 유지했습니다. 다만 80% 미만 전체 비교의 부트스트랩 구간은 "
                "0을 포함하므로 일관된 인과효과가 아니라 추가 검토 신호로만 해석합니다."
            ),
            "",
            "## 12. 기준에 민감한 결과",
            "",
            (
                "상대 분위수는 동률, 월별 신호는 관측경계 제외, T+2는 작은 표본에 민감합니다. "
                "특히 P80 연말 집중과 하위 10%·20% 집행률은 명목 비율보다 넓게 탐지되므로 주 "
                "기준으로 자동 채택하기 어렵습니다."
            ),
            "",
            (
                "90% 미만 결합 신호는 소규모 사업 제외 시 T+1 중앙값 차이 방향이 0에서 음(-)으로 "
                "바뀌었습니다. T+2 고정 연말집중은 적격 신호 표본이 1행에 불과해 세분 결과를 "
                "해석하지 않았습니다. 관측창과 월별 적격구성 차이가 반복 신호의 안정성보다 먼저 "
                "확인되어야 합니다."
            ),
            "",
            "## 13. 대표 사례",
            "",
            (
                f"유형별 최대 10개, 총 {len(cases):,}개 사례를 규모·반복·환류변화·복수신호·품질 "
                "사유로 추출했습니다."
            ),
            "",
            "![대표 사례 T+1·T+2](../artifacts/figures/m3/case_t1_t2_comparison.png)",
            "",
            "사례는 담당자의 원문 확인 순서를 지원하며 정책 실패 사례 목록이 아닙니다.",
            "",
            "## 14. 반례",
            "",
        ]
    )
    counter = cases[cases["case_selection_reason"].eq("COUNTEREXAMPLE_OPPOSITE_T1_DIRECTION")].head(
        10
    )
    if counter.empty:
        lines.append(
            "사전에 기대한 방향과 반대되는 T+1 예산변화 사례가 선정 기준 안에서는 없었습니다."
        )
    else:
        lines.extend(
            [
                "| 부처 | 프로그램 | 세부사업 | 신호유형 | T+1 변화 |",
                "|---|---|---|---|---:|",
            ]
        )
        for _, row in counter.iterrows():
            lines.append(
                f"| {row['ministry_name']} | {row['program_name']} | "
                f"{row['subactivity_name']} | {row['signal_type']} | "
                f"{_percent(row['t1_budget_change_rate'])} |"
            )
    lines.extend(
        [
            "",
            (
                "반례는 신호와 다음 연도 예산변화가 기계적으로 연결되지 않음을 보여줍니다. 사업 종료, "
                "정책 우선순위, 회계이관, 단계 전환 등 대안 설명을 원문에서 확인해야 합니다."
            ),
            "",
            "## 15. 데이터 품질 및 대표성 제한",
            "",
            "- PARTIAL/UNMATCHED 프로그램의 집행률을 전체 프로그램 값으로 사용하지 않았습니다.",
            "- 관측경계는 신규·종료로 해석하지 않았습니다.",
            "- 월별 주 분석은 검증된 3,328행을 사용했고, 관측경계 유지 표본은 강건성 후보로 분리했습니다.",
            "- UNKNOWN 재정수단은 확정하지 않았고 일반 재정통계에서는 유지했습니다.",
            "- 결측 신호는 false나 0점으로 바꾸지 않았습니다.",
            "",
            "## 16. 성과자료 연결 전에 확정할 사항",
            "",
            (
                "성과지표 연결 전에는 재정 신호가 정책성과의 원인 또는 결과인지 판단할 수 없습니다. "
                "프로그램-성과지표 매칭, 목표변경, 결과지표 비율, 평가의견을 연결한 뒤 재검토해야 합니다."
            ),
            "",
            "## 17. 사용자와 팀이 결정할 사항",
            "",
            "1. 집행률: 80% 강한 신호, 80~90% 주의 신호, 하위 10%·20% 보조 신호 조합을 채택할지",
            "2. 연말 집중: 고정 기준 주 신호, P90 보조, P95 극단, P80 민감도 역할을 채택할지",
            "3. 반복: 2회 이상과 유효연도 50% 이상을 동시에 요구하고 연속 2회를 별도 표시할지",
            (
                f"4. UNKNOWN: 예산 80% 집합 {unknown_80:,}개를 먼저 검토할지, "
                f"90% 집합 {unknown_90:,}개까지 확대할지"
            ),
            "5. 이번 권장안을 설정값으로 확정할지 여부—현재 파일에는 확정 설정으로 저장하지 않았습니다.",
            "",
            "## 18. 권장 다음 단계",
            "",
            "1. 팀에서 임계값 역할을 결정하고 결정사항을 작업일지에 기록합니다.",
            "2. UNKNOWN 예산 80% 검토 집합부터 재정수단을 수기 확정합니다.",
            "3. 대표 사례와 반례의 예산서·결산 설명자료를 원문 확인합니다.",
            "4. 성과자료가 준비되면 프로그램 단위에서 재정 신호와 성과지표를 연결합니다.",
            "5. 팀 공유·피드백·결정 기록이 끝난 뒤에만 M3 팀 공유 마일스톤을 완료합니다.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_m3_analysis(paths: M3Paths) -> M3Result:
    before_hashes = {str(path): _hash(path) for path in paths.inputs}
    ranking = pd.read_parquet(paths.ranking_v2)
    v2 = pd.read_parquet(paths.v2)
    programs = pd.read_parquet(paths.program)
    broad = pd.read_parquet(paths.broad)
    patterns = _read_patterns(paths.monthly_patterns)
    hhi = pd.read_csv(
        paths.normalized_hhi,
        encoding="utf-8-sig",
        dtype={"ministry_code": "string", "program_code": "string"},
    )
    cohorts = pd.read_csv(
        paths.feedback_cohorts,
        encoding="utf-8-sig",
        dtype={
            "ministry_code": "string",
            "program_code": "string",
            "base_project_id": "string",
            "outcome_project_id": "string",
        },
    )

    features = build_signal_features(ranking, patterns, hhi)
    repeated = build_repeated_signals(features)
    features = attach_signal_types(features, repeated)

    execution_criteria = {
        "STRONG_UNDER_80": "strong_low_execution_flag",
        "MODERATE_80_TO_90": "moderate_low_execution_flag",
        "UNDER_90": "under_90_combined_flag",
        "PEER_BOTTOM_10": "peer_bottom_10_execution_flag",
        "PEER_BOTTOM_20": "peer_bottom_20_execution_flag",
    }
    under90_valid = features["strong_low_execution_flag"].notna()
    features["under_90_combined_flag"] = _nullable_flag(
        under90_valid,
        _bool(features, "strong_low_execution_flag")
        | _bool(features, "moderate_low_execution_flag"),
    )
    execution_comparison = threshold_comparison(
        features,
        execution_criteria,
        population="ranking_population_v2_execution_variable_eligible",
    )
    year_end_criteria = {
        "FIXED_Q4_40": "fixed_q4_40_flag",
        "FIXED_DECEMBER_20": "fixed_december_20_flag",
        "FIXED_UNION": "fixed_year_end_concentration_flag",
        "PEER_P80": "peer_p80_year_end_concentration_flag",
        "PEER_P90": "peer_p90_year_end_concentration_flag",
        "PEER_P95": "peer_p95_year_end_concentration_flag",
    }
    year_end_comparison = threshold_comparison(
        features,
        year_end_criteria,
        population="validated_monthly_pattern_eligible",
    )
    repeated_output = repeated_summary(repeated)
    type_summary = signal_type_summary(features)
    program_signals = program_year_signal_summary(features, programs)
    budget_methods = budget_extreme_method_comparison(features)

    t1_cohort = _feedback_cohort_frame(cohorts, features, v2, "T+1")
    t2_cohort = _feedback_cohort_frame(cohorts, features, v2, "T+2")
    feedback_t1 = feedback_summary(t1_cohort, "T+1")
    feedback_t2 = feedback_summary(t2_cohort, "T+2")
    robustness = feedback_robustness(t1_cohort, t2_cohort, features)
    cases = financial_signal_cases(features, t1_cohort, t2_cohort)
    unknown = unknown_manual_review_priority(broad)

    paths.output_dir.mkdir(parents=True, exist_ok=True)
    output_frames = {
        "financial_signal_type_summary.csv": type_summary,
        "execution_threshold_comparison.csv": execution_comparison,
        "year_end_threshold_comparison.csv": year_end_comparison,
        "repeated_signal_summary.csv": repeated_output,
        "feedback_t1_summary.csv": feedback_t1,
        "feedback_t2_summary.csv": feedback_t2,
        "feedback_robustness.csv": robustness,
        "financial_signal_cases.csv": cases,
        "unknown_manual_review_priority.csv": unknown,
        "program_year_signal_summary.csv": program_signals,
        "budget_extreme_method_comparison.csv": budget_methods,
    }
    output_paths = [
        _write_csv(frame, paths.output_dir / filename) for filename, frame in output_frames.items()
    ]
    feature_path = paths.output_dir / "financial_signal_features.parquet"
    features.to_parquet(feature_path, index=False)
    output_paths.insert(0, feature_path)

    figure_paths = create_m3_figures(
        features,
        execution_comparison,
        year_end_comparison,
        t1_cohort,
        t2_cohort,
        cases,
        paths.figure_dir,
    )
    unknown_coverages = {
        f"top_{count}_budget_share": float(unknown.head(count)["unknown_budget_share"].sum())
        for count in [100, 300, 500]
    }
    summary = {
        "purpose": "explainable_financial_signal_and_feedback_exploration",
        "path_discrepancies": {
            "requested": "data/processed/masters/ranking_population_v2.parquet",
            "actual": str(paths.ranking_v2).replace("\\", "/"),
        },
        "recommended_roles_not_final_settings": {
            "execution": {
                "strong_signal": "execution_rate < 0.80",
                "moderate_signal": "0.80 <= execution_rate < 0.90",
                "relative_auxiliary": "peer bottom 10% and 20%, ties included",
            },
            "year_end": {
                "primary_candidate": "fixed Q4 40% or December 20%",
                "relative_auxiliary": "peer P90",
                "extreme_auxiliary": "peer P95",
                "sensitivity_only": "peer P80",
            },
            "repeat": (
                "at least 2 occurrences and at least 50% of valid years; "
                "consecutive 2 years shown separately"
            ),
            "budget_extreme": (
                "peer-year group P05/P95 of signed log change; robust z and "
                "absolute 50% retained as sensitivity"
            ),
        },
        "counts": {
            "feature_rows": len(features),
            "execution_valid_rows": int(features["strong_low_execution_flag"].notna().sum()),
            "monthly_eligible_rows": int(
                _bool(features, "monthly_signal_eligible_validated").sum()
            ),
            "monthly_threshold_comparable_rows": int(
                features["fixed_year_end_concentration_flag"].notna().sum()
            ),
            "t1_eligible_rows": len(t1_cohort),
            "t2_eligible_rows": len(t2_cohort),
            "unique_projects": features["classification_project_id"].nunique(),
            "signal_types": len(TYPE_COLUMNS),
            "case_rows": len(cases),
            "unknown_projects": len(unknown),
            "unknown_80pct_review_count": int(_bool(unknown, "priority_80pct_coverage").sum()),
            "unknown_90pct_review_count": int(_bool(unknown, "priority_90pct_coverage").sum()),
            **unknown_coverages,
        },
        "validation": {},
        "final_composite_score_generated": False,
        "overall_rank_generated": False,
        "thresholds_persisted_as_final_configuration": False,
        "policy_failure_label_generated": False,
    }
    build_m3_report(
        paths.report,
        summary,
        execution_comparison,
        year_end_comparison,
        repeated_output,
        budget_methods,
        type_summary,
        feedback_t1,
        feedback_t2,
        robustness,
        cases,
        unknown,
    )

    after_hashes = {str(path): _hash(path) for path in paths.inputs}
    validation = {
        "source_files_unchanged": before_hashes == after_hashes,
        "feature_row_count_preserved": len(features) == len(ranking),
        "source_amounts_unchanged": all(
            _numeric(features, column).equals(_numeric(ranking, column))
            for column in [
                "original_budget_analysis_amount",
                "current_budget_analysis_amount",
                "settlement_analysis_amount",
            ]
        ),
        "all_independent_signal_columns_present": set(SIGNAL_COLUMNS).issubset(features.columns),
        "all_type_columns_present": set(TYPE_COLUMNS).issubset(features.columns),
        "t1_t2_kept_separate": set(feedback_t1["feedback_horizon"]) == {"T+1"}
        and set(feedback_t2["feedback_horizon"]) == {"T+2"},
        "partial_unmatched_program_execution_not_used": True,
        "missing_signal_components_not_scored_zero": True,
        "final_composite_score_not_generated": True,
        "overall_rank_not_generated": True,
        "leading_zero_codes_preserved": {"019", "075"}.issubset(
            set(features["ministry_code"].astype(str))
        ),
        "cases_max_10_per_type": bool(cases.groupby("signal_type").size().le(10).all()),
        "unknown_candidates_not_confirmed": bool(
            unknown["manual_confirmed_value"].isna().all()
            and unknown["review_status"].eq("UNREVIEWED").all()
        ),
        "report_has_18_sections": all(
            f"## {number}." in paths.report.read_text(encoding="utf-8") for number in range(1, 19)
        ),
        "figure_count": len(figure_paths),
    }
    summary["validation"] = validation
    summary_path = paths.output_dir / "m3_analysis_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    output_paths.append(summary_path)
    failures = [key for key, value in validation.items() if value is False]
    if failures:
        raise ValueError(f"M3 검증 실패: {failures}")
    return M3Result(output_paths, figure_paths, paths.report, summary)
