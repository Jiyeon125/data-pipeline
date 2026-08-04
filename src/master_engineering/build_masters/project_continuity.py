"""사업 연속성, financial v2와 프로그램-연도 재정 테이블을 생성합니다."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from itertools import pairwise
from pathlib import Path
from typing import Any

import pandas as pd

SOURCE_KEY = ["project_id", "fiscal_year", "ministry_code"]
RELATION_COLUMNS = [
    "previous_project_id",
    "next_project_id",
    "previous_fiscal_year",
    "next_fiscal_year",
    "relation_type",
    "continuity_flag",
    "matching_method",
    "matching_score",
    "relation_evidence",
    "review_status",
    "manual_review_required",
]
BLOCKING_REASONS = {
    "V1_PRIMARY_KEY_DUPLICATE",
    "SETTLEMENT_DUPLICATE_KEY",
    "SETTLEMENT_CODE_NO_MATCH",
    "SETTLEMENT_CODE_MULTIPLE_MATCHES",
    "FINANCIAL_BASE_MISSING",
    "UNSUPPORTED_ACCOUNT_TYPE",
}
REPRESENTATIVENESS_LIMITED = {
    ("019", 2022, "FUND"),
    ("019", 2023, "FUND"),
    ("019", 2024, "FUND"),
    ("019", 2025, "FUND"),
    ("162", 2024, "FUND"),
}
SOURCE_AMOUNT_COLUMNS = (
    "budget_amount",
    "current_budget_amount",
    "cumulative_expenditure_amount",
    "cumulative_net_expenditure_amount",
    "settlement_budget_amount",
    "settlement_current_budget_amount",
    "settlement_expenditure_amount",
    "settlement_net_expenditure_amount",
    "settlement_carryover_amount",
    "settlement_unused_amount",
    "execution_numerator_amount",
    "execution_denominator_amount",
)
PREWINDOW_MATCH_METHOD = "PREWINDOW_BUDGET_NAME_KEY_2020_2021"
DEFAULT_PREWINDOW_BUDGET_PATH = Path(
    "data/processed/budget_continuity_2020_2021/budget_records.parquet"
)


@dataclass
class ProjectContinuityResult:
    relations: pd.DataFrame
    financial_v2: pd.DataFrame
    program_year: pd.DataFrame
    relation_manual_review: pd.DataFrame
    program_quality_issues: pd.DataFrame
    summaries: dict[str, dict[str, Any]]
    output_paths: list[Path]


def normalize_project_name(value: Any) -> str:
    """명칭 비교용으로 공백·구두점·괄호를 제거하고 소문자화합니다."""
    if pd.isna(value):
        return ""
    return re.sub(r"[^0-9A-Za-z가-힣]", "", str(value)).lower()


def continuity_name_key(
    ministry_code: Any,
    account_name: Any,
    program_name: Any,
    activity_name: Any,
    subactivity_name: Any,
) -> str:
    """관측창 이전 예산과 연결할 명칭키를 만듭니다."""
    ministry = "" if pd.isna(ministry_code) else str(ministry_code).strip().zfill(3)
    return "|".join(
        [
            ministry,
            normalize_project_name(account_name),
            normalize_project_name(program_name),
            normalize_project_name(activity_name),
            normalize_project_name(subactivity_name),
        ]
    )


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, float) and pd.isna(value):
            continue
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        if str(value).strip() == "":
            continue
        return value
    return pd.NA


def _name_fields_for_continuity(row: Any) -> tuple[Any, Any, Any, Any, Any]:
    def value(name: str) -> Any:
        if isinstance(row, pd.Series):
            return row.get(name)
        return getattr(row, name, None)

    return (
        value("ministry_code"),
        _first_present(value("account_name_budget_api"), value("account_name")),
        _first_present(value("program_name_budget_api"), value("program_name")),
        _first_present(value("activity_name_budget_api"), value("activity_name")),
        _first_present(value("subactivity_name_budget_api"), value("subactivity_name")),
    )


def load_prewindow_budget_name_years(path: Path) -> dict[str, set[int]]:
    """2020~2021 예산 정규화 테이블에서 명칭키→관측연도 집합을 로드합니다."""
    if not path.exists():
        return {}
    frame = pd.read_parquet(path)
    if frame.empty:
        return {}
    result: dict[str, set[int]] = {}
    for row in frame.itertuples(index=False):
        key = continuity_name_key(
            getattr(row, "ministry_code", None),
            getattr(row, "account_name", None),
            getattr(row, "program_name", None),
            getattr(row, "activity_name", None),
            getattr(row, "subactivity_name", None),
        )
        year = pd.to_numeric(getattr(row, "fiscal_year", pd.NA), errors="coerce")
        if pd.isna(year) or not key or key.endswith("||||"):
            continue
        result.setdefault(key, set()).add(int(year))
    return result


def _similarity(left: Any, right: Any) -> float:
    left_norm = normalize_project_name(left)
    right_norm = normalize_project_name(right)
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def _relation_id(*values: Any) -> str:
    raw = "\x1f".join("" if pd.isna(value) else str(value) for value in values)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _classification_map(classification: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    keep_columns = [
        "project_id",
        "account_type",
        "fiscal_instrument",
        "project_category",
        "comparison_group",
        "classification_status",
        "manual_review_required",
    ]
    for record in classification[keep_columns + ["source_project_year_ids"]].to_dict(
        orient="records"
    ):
        for source_id in json.loads(record["source_project_year_ids"]):
            rows.append(
                {
                    "source_project_year_id": source_id,
                    "classification_project_id": record["project_id"],
                    "account_type_classified": record["account_type"],
                    "fiscal_instrument": record["fiscal_instrument"],
                    "project_category": record["project_category"],
                    "comparison_group": record["comparison_group"],
                    "classification_status": record["classification_status"],
                    "classification_manual_review_required": record["manual_review_required"],
                }
            )
    result = pd.DataFrame(rows)
    duplicate = result.duplicated("source_project_year_id", keep=False)
    if duplicate.any():
        raise ValueError("사업분류 원천 사업-연도 매핑이 중복됩니다.")
    return result


def _prepare_projects(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["ministry_code"] = result["ministry_code"].astype("string")
    for column in [
        "account_code",
        "program_code",
        "activity_code",
        "subactivity_code",
    ]:
        result[column] = result[column].astype("string")
    result["normalized_subactivity_name"] = result["subactivity_name"].map(normalize_project_name)
    result["normalized_activity_name"] = result["activity_name"].map(normalize_project_name)
    result["normalized_program_name"] = result["program_name"].map(normalize_project_name)
    return result


def _add_relation(
    relations: list[dict[str, Any]],
    *,
    previous_project_id: Any,
    next_project_id: Any,
    previous_year: int,
    next_year: int,
    relation_type: str,
    continuity_flag: bool | None,
    matching_method: str,
    matching_score: float | None,
    evidence: str,
    review_status: str,
    manual_review_required: bool,
) -> None:
    relations.append(
        {
            "relation_id": "relation:"
            + _relation_id(
                previous_project_id,
                next_project_id,
                previous_year,
                next_year,
                relation_type,
            ),
            "previous_project_id": previous_project_id,
            "next_project_id": next_project_id,
            "previous_fiscal_year": previous_year,
            "next_fiscal_year": next_year,
            "relation_type": relation_type,
            "continuity_flag": continuity_flag,
            "matching_method": matching_method,
            "matching_score": matching_score,
            "relation_evidence": evidence,
            "review_status": review_status,
            "manual_review_required": manual_review_required,
        }
    )


def _unique_pairs_by_key(
    previous: pd.DataFrame,
    following: pd.DataFrame,
    key: list[str],
) -> list[tuple[pd.Series, pd.Series]]:
    left = previous.dropna(subset=key)
    right = following.dropna(subset=key)
    left_groups = left.groupby(key, dropna=False)
    right_groups = right.groupby(key, dropna=False)
    common = left_groups.size().index.intersection(right_groups.size().index)
    pairs: list[tuple[pd.Series, pd.Series]] = []
    for value in common:
        left_group = left_groups.get_group(value)
        right_group = right_groups.get_group(value)
        if len(left_group) == 1 and len(right_group) == 1:
            pairs.append((left_group.iloc[0], right_group.iloc[0]))
    return pairs


def _mutual_best_pairs(
    previous: pd.DataFrame,
    following: pd.DataFrame,
    *,
    threshold: float,
    same_hierarchy: bool,
) -> list[tuple[pd.Series, pd.Series, float]]:
    candidates: list[tuple[str, str, float]] = []
    next_records = list(following.to_dict(orient="records"))
    for left in previous.to_dict(orient="records"):
        for right in next_records:
            if left["ministry_code"] != right["ministry_code"]:
                continue
            if str(left["account_code"]) != str(right["account_code"]):
                continue
            if same_hierarchy and (
                str(left["program_code"]) != str(right["program_code"])
                or str(left["activity_code"]) != str(right["activity_code"])
            ):
                continue
            score = _similarity(left["subactivity_name"], right["subactivity_name"])
            if score >= threshold:
                candidates.append((left["project_id"], right["project_id"], score))
    if not candidates:
        return []
    candidate_frame = pd.DataFrame(candidates, columns=["previous", "next", "score"])
    # 다대일/일대다 후보를 일대일 유사매칭으로 먼저 소비하면 통합·분할을
    # 놓치게 됩니다. 양쪽 모두 후보가 하나뿐인 경우에만 자동 일대일 매칭합니다.
    previous_degree = candidate_frame.groupby("previous")["next"].transform("nunique")
    next_degree = candidate_frame.groupby("next")["previous"].transform("nunique")
    candidate_frame = candidate_frame.loc[previous_degree.eq(1) & next_degree.eq(1)].copy()
    if candidate_frame.empty:
        return []
    best_next = candidate_frame.loc[
        candidate_frame.groupby("previous")["score"].idxmax()
    ].set_index("previous")
    best_previous = candidate_frame.loc[
        candidate_frame.groupby("next")["score"].idxmax()
    ].set_index("next")
    previous_lookup = previous.set_index("project_id", drop=False)
    next_lookup = following.set_index("project_id", drop=False)
    pairs: list[tuple[pd.Series, pd.Series, float]] = []
    for previous_id, row in best_next.iterrows():
        next_id = row["next"]
        if best_previous.loc[next_id, "previous"] == previous_id:
            pairs.append(
                (
                    previous_lookup.loc[previous_id],
                    next_lookup.loc[next_id],
                    float(row["score"]),
                )
            )
    return pairs


def build_project_relations(
    frame: pd.DataFrame,
    *,
    prewindow_name_years: dict[str, set[int]] | None = None,
) -> pd.DataFrame:
    """인접 회계연도 간 사업관계 후보를 규칙 순서에 따라 생성합니다.

    `prewindow_name_years`가 있으면 분석 시작연도 행을 2020~2021 예산 명칭키와
    대조해, 이전이 확인된 사업은 LEFT_CENSORED/OBSERVATION_START 대신 CONTINUED로
    연결합니다. 신규(NEW)로 승격하지는 않습니다.
    """
    projects = _prepare_projects(frame)
    prior = prewindow_name_years or {}
    relations: list[dict[str, Any]] = []
    years = sorted(int(year) for year in projects["fiscal_year"].dropna().unique())
    first_year = years[0]
    last_year = years[-1]
    first_rows = projects.loc[projects["fiscal_year"].eq(first_year)]
    for row in first_rows.itertuples(index=False):
        ministry, account, program, activity, subactivity = _name_fields_for_continuity(row)
        name_key = continuity_name_key(ministry, account, program, activity, subactivity)
        prior_years = sorted(prior.get(name_key, set()))
        if prior_years:
            prior_year = int(prior_years[-1])
            _add_relation(
                relations,
                previous_project_id=f"prewindow:{name_key}",
                next_project_id=row.project_id,
                previous_year=prior_year,
                next_year=first_year,
                relation_type="CONTINUED",
                continuity_flag=True,
                matching_method=PREWINDOW_MATCH_METHOD,
                matching_score=1.0,
                evidence=(
                    "관측창 이전 예산편성 API 명칭키 일치; "
                    f"prior_years={prior_years}; name_key={name_key}; "
                    "코드 매칭이 아닌 정규화 명칭 일치이며 NEW로 확정하지 않음"
                ),
                review_status="RULE_CONFIRMED",
                manual_review_required=False,
            )
            continue
        _add_relation(
            relations,
            previous_project_id=pd.NA,
            next_project_id=row.project_id,
            previous_year=first_year - 1,
            next_year=first_year,
            relation_type="LEFT_CENSORED",
            continuity_flag=None,
            matching_method="OBSERVATION_WINDOW_START",
            matching_score=None,
            evidence=(
                "분석 시작연도 이전 자료 부재로 실제 신규 여부 확인 불가"
                + (
                    f"; prewindow_name_key_checked={name_key}"
                    if name_key and not name_key.endswith("||||")
                    else ""
                )
            ),
            review_status="INFORMATIONAL",
            manual_review_required=False,
        )

    for previous_year, next_year in pairwise(years):
        previous = projects.loc[projects["fiscal_year"].eq(previous_year)].copy()
        following = projects.loc[projects["fiscal_year"].eq(next_year)].copy()
        unmatched_previous = set(previous["project_id"])
        unmatched_next = set(following["project_id"])

        def available(frame_value: pd.DataFrame, ids: set[str]) -> pd.DataFrame:
            return frame_value.loc[frame_value["project_id"].isin(ids)]

        subactivity_key = ["ministry_code", "account_code", "subactivity_code"]
        for left, right in _unique_pairs_by_key(previous, following, subactivity_key):
            if (
                left["project_id"] not in unmatched_previous
                or right["project_id"] not in unmatched_next
            ):
                continue
            same_hierarchy = all(
                str(left[column]) == str(right[column])
                for column in ["program_code", "activity_code"]
            )
            same_name = left["normalized_subactivity_name"] == right["normalized_subactivity_name"]
            relation_type = "CONTINUED" if same_name else "RENAMED"
            confirmed = same_hierarchy
            _add_relation(
                relations,
                previous_project_id=left["project_id"],
                next_project_id=right["project_id"],
                previous_year=previous_year,
                next_year=next_year,
                relation_type=relation_type,
                continuity_flag=confirmed,
                matching_method="SAME_SUBACTIVITY_CODE",
                matching_score=_similarity(left["subactivity_name"], right["subactivity_name"]),
                evidence=(
                    f"subactivity_code={left['subactivity_code']};"
                    f"same_program_activity={same_hierarchy}"
                ),
                review_status="RULE_CONFIRMED" if confirmed else "RULE_CANDIDATE",
                manual_review_required=not confirmed,
            )
            unmatched_previous.remove(left["project_id"])
            unmatched_next.remove(right["project_id"])

        hierarchy_key = [
            "ministry_code",
            "account_code",
            "program_code",
            "activity_code",
            "subactivity_code",
        ]
        for left, right in _unique_pairs_by_key(
            available(previous, unmatched_previous),
            available(following, unmatched_next),
            hierarchy_key,
        ):
            same_name = left["normalized_subactivity_name"] == right["normalized_subactivity_name"]
            _add_relation(
                relations,
                previous_project_id=left["project_id"],
                next_project_id=right["project_id"],
                previous_year=previous_year,
                next_year=next_year,
                relation_type="CONTINUED" if same_name else "RENAMED",
                continuity_flag=True,
                matching_method="SAME_FULL_HIERARCHY",
                matching_score=_similarity(left["subactivity_name"], right["subactivity_name"]),
                evidence="소관·회계·프로그램·단위사업·세부사업 코드 일치",
                review_status="RULE_CONFIRMED",
                manual_review_required=False,
            )
            unmatched_previous.remove(left["project_id"])
            unmatched_next.remove(right["project_id"])

        exact_name_key = [
            "ministry_code",
            "account_code",
            "normalized_subactivity_name",
        ]
        for left, right in _unique_pairs_by_key(
            available(previous, unmatched_previous).loc[
                lambda value: value["normalized_subactivity_name"].ne("")
            ],
            available(following, unmatched_next).loc[
                lambda value: value["normalized_subactivity_name"].ne("")
            ],
            exact_name_key,
        ):
            _add_relation(
                relations,
                previous_project_id=left["project_id"],
                next_project_id=right["project_id"],
                previous_year=previous_year,
                next_year=next_year,
                relation_type="CODE_CHANGED",
                continuity_flag=False,
                matching_method="EXACT_NORMALIZED_NAME_SAME_MINISTRY_ACCOUNT",
                matching_score=1.0,
                evidence="소관·회계·정규화 세부사업명 일치, 코드계층 변경",
                review_status="RULE_CANDIDATE",
                manual_review_required=True,
            )
            unmatched_previous.remove(left["project_id"])
            unmatched_next.remove(right["project_id"])

        for threshold, same_hierarchy, method in [
            (0.92, False, "FUZZY_NAME_SAME_MINISTRY_ACCOUNT"),
            (0.75, True, "FUZZY_NAME_SAME_PROGRAM_ACTIVITY"),
        ]:
            pairs = _mutual_best_pairs(
                available(previous, unmatched_previous),
                available(following, unmatched_next),
                threshold=threshold,
                same_hierarchy=same_hierarchy,
            )
            for left, right, score in pairs:
                if (
                    left["project_id"] not in unmatched_previous
                    or right["project_id"] not in unmatched_next
                ):
                    continue
                _add_relation(
                    relations,
                    previous_project_id=left["project_id"],
                    next_project_id=right["project_id"],
                    previous_year=previous_year,
                    next_year=next_year,
                    relation_type="CODE_CHANGED",
                    continuity_flag=False,
                    matching_method=method,
                    matching_score=score,
                    evidence=(
                        f"name_similarity={score:.4f};"
                        f"previous={left['subactivity_name']};next={right['subactivity_name']}"
                    ),
                    review_status="RULE_CANDIDATE",
                    manual_review_required=True,
                )
                unmatched_previous.remove(left["project_id"])
                unmatched_next.remove(right["project_id"])

        remaining_previous = available(previous, unmatched_previous)
        remaining_next = available(following, unmatched_next)
        candidate_rows: list[dict[str, Any]] = []
        for left in remaining_previous.to_dict(orient="records"):
            for right in remaining_next.to_dict(orient="records"):
                if left["ministry_code"] != right["ministry_code"]:
                    continue
                if str(left["account_code"]) != str(right["account_code"]):
                    continue
                hierarchy_related = (
                    str(left["program_code"]) == str(right["program_code"])
                    or str(left["activity_code"]) == str(right["activity_code"])
                    or left["normalized_program_name"] == right["normalized_program_name"]
                )
                score = _similarity(left["subactivity_name"], right["subactivity_name"])
                if hierarchy_related and score >= 0.70:
                    candidate_rows.append(
                        {
                            "previous": left["project_id"],
                            "next": right["project_id"],
                            "score": score,
                        }
                    )
        candidate_frame = pd.DataFrame(candidate_rows)
        involved_previous: set[str] = set()
        involved_next: set[str] = set()
        if not candidate_frame.empty:
            previous_degree = candidate_frame.groupby("previous")["next"].nunique()
            next_degree = candidate_frame.groupby("next")["previous"].nunique()
            structural = candidate_frame.loc[
                candidate_frame["previous"].map(previous_degree).gt(1)
                | candidate_frame["next"].map(next_degree).gt(1)
            ]
            for candidate in structural.itertuples(index=False):
                previous_count = int(previous_degree.loc[candidate.previous])
                next_count = int(next_degree.loc[candidate.next])
                if previous_count > 1 and next_count == 1:
                    relation_type = "SPLIT"
                elif next_count > 1 and previous_count == 1:
                    relation_type = "MERGED"
                else:
                    relation_type = "UNKNOWN"
                _add_relation(
                    relations,
                    previous_project_id=candidate.previous,
                    next_project_id=candidate.next,
                    previous_year=previous_year,
                    next_year=next_year,
                    relation_type=relation_type,
                    continuity_flag=False,
                    matching_method="STRUCTURAL_CANDIDATE_GRAPH",
                    matching_score=float(candidate.score),
                    evidence=(
                        f"previous_candidate_count={previous_count};"
                        f"next_candidate_count={next_count}"
                    ),
                    review_status="MANUAL_REVIEW",
                    manual_review_required=True,
                )
                involved_previous.add(candidate.previous)
                involved_next.add(candidate.next)
        unmatched_previous -= involved_previous
        unmatched_next -= involved_next

        remaining_previous = available(previous, unmatched_previous)
        remaining_next = available(following, unmatched_next)
        transferred_pairs: list[tuple[str, str, float]] = []
        for left in remaining_previous.to_dict(orient="records"):
            for right in remaining_next.to_dict(orient="records"):
                if left["ministry_code"] == right["ministry_code"]:
                    continue
                if (
                    left["normalized_subactivity_name"]
                    and left["normalized_subactivity_name"] == right["normalized_subactivity_name"]
                ):
                    hierarchy_score = max(
                        _similarity(left["program_name"], right["program_name"]),
                        _similarity(left["activity_name"], right["activity_name"]),
                    )
                    if hierarchy_score >= 0.8:
                        transferred_pairs.append(
                            (left["project_id"], right["project_id"], hierarchy_score)
                        )
        transfer_frame = pd.DataFrame(transferred_pairs, columns=["previous", "next", "score"])
        if not transfer_frame.empty:
            previous_degree = transfer_frame.groupby("previous")["next"].nunique()
            next_degree = transfer_frame.groupby("next")["previous"].nunique()
            unique_transfer = transfer_frame.loc[
                transfer_frame["previous"].map(previous_degree).eq(1)
                & transfer_frame["next"].map(next_degree).eq(1)
            ]
            for candidate in unique_transfer.itertuples(index=False):
                _add_relation(
                    relations,
                    previous_project_id=candidate.previous,
                    next_project_id=candidate.next,
                    previous_year=previous_year,
                    next_year=next_year,
                    relation_type="TRANSFERRED",
                    continuity_flag=False,
                    matching_method="CROSS_MINISTRY_EXACT_NAME_HIERARCHY_SIMILAR",
                    matching_score=float(candidate.score),
                    evidence="부처 변경, 정규화 세부사업명 일치, 상위계층 유사",
                    review_status="MANUAL_REVIEW",
                    manual_review_required=True,
                )
                unmatched_previous.discard(candidate.previous)
                unmatched_next.discard(candidate.next)

        for project_id in sorted(unmatched_previous):
            _add_relation(
                relations,
                previous_project_id=project_id,
                next_project_id=pd.NA,
                previous_year=previous_year,
                next_year=next_year,
                relation_type="TERMINATED",
                continuity_flag=False,
                matching_method="NO_SUCCESSOR_CANDIDATE",
                matching_score=None,
                evidence="다음 연도 연결 후보 없음",
                review_status="RULE_CANDIDATE",
                manual_review_required=True,
            )
        for project_id in sorted(unmatched_next):
            _add_relation(
                relations,
                previous_project_id=pd.NA,
                next_project_id=project_id,
                previous_year=previous_year,
                next_year=next_year,
                relation_type="NEW",
                continuity_flag=False,
                matching_method="NO_PREDECESSOR_CANDIDATE",
                matching_score=None,
                evidence="이전 연도 연결 후보 없음",
                review_status="RULE_CANDIDATE",
                manual_review_required=True,
            )

    last_rows = projects.loc[projects["fiscal_year"].eq(last_year)]
    for row in last_rows.itertuples(index=False):
        _add_relation(
            relations,
            previous_project_id=row.project_id,
            next_project_id=pd.NA,
            previous_year=last_year,
            next_year=last_year + 1,
            relation_type="RIGHT_CENSORED",
            continuity_flag=None,
            matching_method="OBSERVATION_WINDOW_END",
            matching_score=None,
            evidence="분석 종료연도 이후 자료 부재로 실제 종료 여부 확인 불가",
            review_status="INFORMATIONAL",
            manual_review_required=False,
        )

    result = pd.DataFrame(relations)
    result["previous_fiscal_year"] = pd.to_numeric(
        result["previous_fiscal_year"], errors="coerce"
    ).astype("Int64")
    result["next_fiscal_year"] = pd.to_numeric(result["next_fiscal_year"], errors="coerce").astype(
        "Int64"
    )
    result["matching_score"] = pd.to_numeric(result["matching_score"], errors="coerce").astype(
        "Float64"
    )
    result["continuity_flag"] = result["continuity_flag"].astype("boolean")
    conflict = result["relation_type"].eq("UNKNOWN") & result["matching_method"].eq(
        "STRUCTURAL_CANDIDATE_GRAPH"
    )
    candidate = result["manual_review_required"] & ~conflict
    result["review_priority"] = "NONE"
    result.loc[
        result["relation_type"].isin({"LEFT_CENSORED", "RIGHT_CENSORED"}),
        "review_priority",
    ] = "INFORMATIONAL"
    result.loc[candidate, "review_priority"] = "MANUAL_REVIEW"
    result.loc[conflict, "review_priority"] = "BLOCKING"
    return result


def _reason_set(value: Any) -> set[str]:
    if pd.isna(value):
        return set()
    return {reason for reason in str(value).split(";") if reason}


def _status_for_row(
    row: pd.Series,
    incoming: pd.DataFrame,
    outgoing: pd.DataFrame,
) -> tuple[str, str | None, str | None, bool | None]:
    incoming_types = set(incoming["relation_type"]) if not incoming.empty else set()
    outgoing_types = set(outgoing["relation_type"]) if not outgoing.empty else set()
    predecessors = sorted(str(value) for value in incoming["previous_project_id"].dropna().unique())
    successors = sorted(str(value) for value in outgoing["next_project_id"].dropna().unique())
    if "LEFT_CENSORED" in incoming_types:
        status = "OBSERVATION_START"
    elif "TERMINATED" in outgoing_types:
        status = "TERMINATED"
    else:
        priority = [
            "TRANSFERRED",
            "MERGED",
            "SPLIT",
            "CODE_CHANGED",
            "RENAMED",
            "NEW",
        ]
        status = next(
            (
                relation_type
                for relation_type in priority
                if relation_type in incoming_types or relation_type in outgoing_types
            ),
            "CONTINUING"
            if "CONTINUED" in incoming_types or "CONTINUED" in outgoing_types
            else "UNKNOWN",
        )
        if status == "CONTINUING" and "RIGHT_CENSORED" in outgoing_types:
            status = "OBSERVATION_END"
    confirmed_incoming = incoming.loc[
        incoming["continuity_flag"].fillna(False) & incoming["review_status"].eq("RULE_CONFIRMED")
    ]
    continuity: bool | None = len(confirmed_incoming) == 1
    if status in {"OBSERVATION_START", "OBSERVATION_END"}:
        continuity = None
    return (
        status,
        ";".join(predecessors) if predecessors else None,
        ";".join(successors) if successors else None,
        continuity,
    )


def _source_amount(frame: pd.DataFrame, primary: str, fallback: str) -> tuple[pd.Series, pd.Series]:
    amount = frame[primary].combine_first(frame[fallback])
    source = pd.Series(pd.NA, index=frame.index, dtype="string")
    source.loc[frame[primary].notna()] = primary
    source.loc[frame[primary].isna() & frame[fallback].notna()] = fallback
    return amount, source


def build_financial_v2(
    *,
    financial_v1: pd.DataFrame,
    relations: pd.DataFrame,
    classification: pd.DataFrame,
    broad_ids: set[str],
    core_ids: set[str],
    strict_ids: set[str],
    broad_flags: pd.DataFrame,
) -> pd.DataFrame:
    """financial v1에 연속성·증감·규모·대표성 파생변수를 추가합니다."""
    frame = financial_v1.copy()
    frame["ministry_code"] = frame["ministry_code"].astype("string")
    classification_map = _classification_map(classification)
    frame = frame.merge(
        classification_map,
        how="left",
        left_on="project_id",
        right_on="source_project_year_id",
        validate="one_to_one",
    ).drop(columns=["source_project_year_id"])
    frame["in_broad_population"] = frame["project_id"].astype(str).isin(broad_ids)
    frame["in_core_financial_population"] = frame["project_id"].astype(str).isin(core_ids)
    frame["in_strict_ranking_population"] = frame["project_id"].astype(str).isin(strict_ids)
    flag_columns = [
        "source_project_year_id",
        "budget_analysis_eligible",
        "execution_analysis_eligible",
        "settlement_analysis_eligible",
        "monthly_pattern_analysis_eligible",
        "trend_analysis_eligible",
        "ranking_analysis_eligible",
        "source_trace",
    ]
    flags = broad_flags[[column for column in flag_columns if column in broad_flags]].copy()
    frame = frame.merge(
        flags,
        how="left",
        left_on="project_id",
        right_on="source_project_year_id",
        validate="one_to_one",
    ).drop(columns=["source_project_year_id"])
    if "source_trace" not in frame:
        frame["source_trace"] = pd.NA
    fallback_trace = pd.Series(
        "project_year_financial_v1:" + frame["project_id"].astype(str),
        index=frame.index,
        dtype="string",
    )
    for source_column in ["source_path", "source_file", "source_datasets"]:
        if source_column in frame:
            fallback_trace = frame[source_column].astype("string").combine_first(fallback_trace)
    frame["source_trace"] = frame["source_trace"].astype("string").combine_first(fallback_trace)
    for column in [
        "budget_analysis_eligible",
        "execution_analysis_eligible",
        "settlement_analysis_eligible",
        "monthly_pattern_analysis_eligible",
        "trend_analysis_eligible",
        "ranking_analysis_eligible",
    ]:
        frame[column] = frame[column].astype("boolean").fillna(False).astype(bool)

    incoming_groups = {
        key: group
        for key, group in relations.dropna(subset=["next_project_id"]).groupby("next_project_id")
    }
    outgoing_groups = {
        key: group
        for key, group in relations.dropna(subset=["previous_project_id"]).groupby(
            "previous_project_id"
        )
    }
    status_values: list[tuple[str, str | None, str | None, bool]] = []
    empty_relations = pd.DataFrame(columns=relations.columns)
    for _, row in frame.iterrows():
        status_values.append(
            _status_for_row(
                row,
                incoming_groups.get(row["project_id"], empty_relations),
                outgoing_groups.get(row["project_id"], empty_relations),
            )
        )
    frame["project_status"] = [value[0] for value in status_values]
    frame["predecessor_project_id"] = [value[1] for value in status_values]
    frame["successor_project_id"] = [value[2] for value in status_values]
    frame["continuity_flag"] = pd.Series(
        [value[3] for value in status_values],
        index=frame.index,
        dtype="boolean",
    )
    prewindow_incoming = relations.loc[
        relations["matching_method"].eq(PREWINDOW_MATCH_METHOD)
        & relations["next_project_id"].notna()
    ].copy()
    prior_years_map = {
        str(row.next_project_id): str(row.relation_evidence)
        for row in prewindow_incoming.itertuples(index=False)
    }
    frame["prior_window_observed"] = frame["project_id"].astype(str).isin(prior_years_map)
    frame["prior_window_match_method"] = pd.Series(pd.NA, index=frame.index, dtype="string")
    frame.loc[frame["prior_window_observed"], "prior_window_match_method"] = PREWINDOW_MATCH_METHOD
    frame["prior_window_years"] = pd.Series(pd.NA, index=frame.index, dtype="string")
    for project_id, evidence in prior_years_map.items():
        marker = "prior_years="
        if marker not in evidence:
            continue
        years_text = evidence.split(marker, 1)[1].split(";", 1)[0].strip()
        years_text = years_text.strip("[]").replace(" ", "")
        frame.loc[frame["project_id"].astype(str).eq(project_id), "prior_window_years"] = years_text
    frame["continuity_evidence_window_start_year"] = pd.Series(pd.NA, index=frame.index, dtype="Int64")
    if frame["prior_window_observed"].any():
        frame.loc[frame["prior_window_observed"], "continuity_evidence_window_start_year"] = 2020
    boundary_statuses = {"OBSERVATION_START", "OBSERVATION_END"}
    frame["structural_change_flag"] = ~frame["project_status"].isin(
        {"CONTINUING", *boundary_statuses}
    )
    frame["structural_change_type"] = frame["project_status"].where(
        frame["structural_change_flag"], pd.NA
    )
    frame.loc[frame["project_status"].eq("OBSERVATION_START"), "structural_change_type"] = (
        "LEFT_CENSORED"
    )
    frame.loc[frame["project_status"].eq("OBSERVATION_END"), "structural_change_type"] = (
        "RIGHT_CENSORED"
    )
    frame.loc[frame["prior_window_observed"], "structural_change_type"] = pd.NA
    frame.loc[frame["prior_window_observed"], "structural_change_flag"] = False
    frame["trend_analysis_eligible"] = (
        frame["in_core_financial_population"]
        & frame["continuity_flag"].fillna(False)
        & frame["project_status"].isin({"CONTINUING", "RENAMED"})
    )
    relationship_reviews = []
    project_status_confirmed = []
    for _, row in frame.iterrows():
        related = pd.concat(
            [
                incoming_groups.get(row["project_id"], empty_relations),
                outgoing_groups.get(row["project_id"], empty_relations),
            ],
            ignore_index=True,
        )
        non_boundary = related.loc[
            ~related["relation_type"].isin({"LEFT_CENSORED", "RIGHT_CENSORED"})
        ]
        relationship_reviews.append(
            bool(non_boundary["manual_review_required"].any()) if not non_boundary.empty else False
        )
        project_status_confirmed.append(
            bool(
                (
                    non_boundary["relation_type"].eq(row["project_status"])
                    & non_boundary["review_status"].eq("RULE_CONFIRMED")
                ).any()
            )
            if not non_boundary.empty
            else False
        )
    frame["manual_review_required"] = relationship_reviews
    frame["project_status_confirmed"] = project_status_confirmed
    frame.loc[frame["project_status"].isin(boundary_statuses), "manual_review_required"] = False

    frame["analysis_original_budget"], frame["analysis_original_budget_source"] = _source_amount(
        frame, "settlement_budget_amount", "budget_amount"
    )
    frame["analysis_current_budget"], frame["analysis_current_budget_source"] = _source_amount(
        frame, "settlement_current_budget_amount", "current_budget_amount"
    )
    frame["analysis_settlement_expenditure"] = frame["settlement_expenditure_amount"]
    frame["analysis_settlement_expenditure_source"] = "settlement_expenditure_amount"
    frame["blocking_quality_flag"] = frame["quality_issue_reasons"].map(
        lambda value: bool(_reason_set(value) & BLOCKING_REASONS)
    )

    relation_lookup = relations.loc[
        relations["continuity_flag"]
        & relations["review_status"].eq("RULE_CONFIRMED")
        & relations["previous_project_id"].notna()
        & relations["next_project_id"].notna()
    ].drop_duplicates("next_project_id")
    predecessor_map = relation_lookup.set_index("next_project_id")["previous_project_id"].to_dict()
    frame_lookup = frame.set_index("project_id")
    change_columns = [
        "original_budget_change",
        "original_budget_change_rate",
        "current_budget_change",
        "current_budget_change_rate",
        "settlement_expenditure_change",
        "settlement_expenditure_change_rate",
        "execution_rate_change",
    ]
    for column in change_columns:
        frame[column] = pd.NA
    frame["budget_change_status"] = "EXCLUDED"
    frame["budget_change_missing_reason"] = pd.NA
    frame["budget_change_analysis_eligible"] = False

    structural_reason = {
        "NEW": "NEW_PROJECT",
        "TERMINATED": "TERMINATED_PROJECT",
        "TRANSFERRED": "TRANSFERRED_PROJECT",
        "MERGED": "MERGED_PROJECT",
        "SPLIT": "SPLIT_PROJECT",
        "CODE_CHANGED": "CODE_CHANGED_UNCONFIRMED",
        "UNKNOWN": "CONTINUITY_UNCONFIRMED",
        "OBSERVATION_START": "LEFT_CENSORED",
        "OBSERVATION_END": "RIGHT_CENSORED",
    }
    for index, row in frame.iterrows():
        reasons: list[str] = []
        predecessor_id = predecessor_map.get(row["project_id"])
        if row["project_status"] in structural_reason:
            reasons.append(structural_reason[row["project_status"]])
        if predecessor_id is None:
            reasons.append(
                "OBSERVATION_WINDOW_START"
                if int(row["fiscal_year"]) == int(frame["fiscal_year"].min())
                else "CONTINUITY_UNCONFIRMED"
            )
        if row["blocking_quality_flag"]:
            reasons.append("BLOCKING_QUALITY")
        if not row["in_core_financial_population"]:
            reasons.append("NOT_CORE_FINANCIAL_POPULATION")
        previous_row: pd.Series | None = None
        if predecessor_id is not None and predecessor_id in frame_lookup.index:
            previous_row = frame_lookup.loc[predecessor_id]
            if bool(previous_row["blocking_quality_flag"]):
                reasons.append("PREVIOUS_BLOCKING_QUALITY")
            if not bool(previous_row["in_core_financial_population"]):
                reasons.append("PREVIOUS_NOT_CORE_FINANCIAL_POPULATION")
            source_pairs = [
                (
                    row["analysis_original_budget_source"],
                    previous_row["analysis_original_budget_source"],
                ),
                (
                    row["analysis_current_budget_source"],
                    previous_row["analysis_current_budget_source"],
                ),
            ]
            if any(
                pd.isna(current_source)
                or pd.isna(previous_source)
                or str(current_source) != str(previous_source)
                for current_source, previous_source in source_pairs
            ):
                reasons.append("AMOUNT_TYPE_MISMATCH")
            for label, column in [
                ("ORIGINAL_BUDGET", "analysis_original_budget"),
                ("CURRENT_BUDGET", "analysis_current_budget"),
                ("SETTLEMENT_EXPENDITURE", "analysis_settlement_expenditure"),
            ]:
                if pd.isna(previous_row[column]):
                    reasons.append(f"PREVIOUS_{label}_MISSING")
                elif float(previous_row[column]) == 0:
                    reasons.append(f"PREVIOUS_{label}_ZERO")
                if pd.isna(row[column]):
                    reasons.append(f"CURRENT_{label}_MISSING")
            if pd.isna(previous_row["execution_rate"]) or pd.isna(row["execution_rate"]):
                reasons.append("EXECUTION_RATE_MISSING")
        reasons = list(dict.fromkeys(reasons))
        if reasons or previous_row is None:
            frame.at[index, "budget_change_missing_reason"] = ";".join(reasons)
            continue
        calculations = [
            (
                "analysis_original_budget",
                "original_budget_change",
                "original_budget_change_rate",
            ),
            (
                "analysis_current_budget",
                "current_budget_change",
                "current_budget_change_rate",
            ),
            (
                "analysis_settlement_expenditure",
                "settlement_expenditure_change",
                "settlement_expenditure_change_rate",
            ),
        ]
        for amount_column, change_column, rate_column in calculations:
            change = float(row[amount_column]) - float(previous_row[amount_column])
            frame.at[index, change_column] = change
            frame.at[index, rate_column] = change / abs(float(previous_row[amount_column]))
        frame.at[index, "execution_rate_change"] = float(row["execution_rate"]) - float(
            previous_row["execution_rate"]
        )
        frame.at[index, "budget_change_status"] = "CALCULATED"
        frame.at[index, "budget_change_missing_reason"] = pd.NA
        frame.at[index, "budget_change_analysis_eligible"] = True

    for column in change_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Float64")
    core = frame["in_core_financial_population"]
    positive_budget = core & frame["analysis_original_budget"].gt(0)
    frame["log_original_budget"] = pd.NA
    frame.loc[positive_budget, "log_original_budget"] = frame.loc[
        positive_budget, "analysis_original_budget"
    ].map(math.log)
    frame["log_original_budget"] = pd.to_numeric(
        frame["log_original_budget"], errors="coerce"
    ).astype("Float64")
    ministry_total = (
        frame.loc[core]
        .groupby(["ministry_code", "fiscal_year"])["analysis_original_budget"]
        .transform("sum")
    )
    program_total = (
        frame.loc[core]
        .groupby(["ministry_code", "program_code", "fiscal_year"], dropna=False)[
            "analysis_original_budget"
        ]
        .transform("sum")
    )
    frame["ministry_budget_share"] = pd.NA
    frame["program_budget_share"] = pd.NA
    valid_ministry = core & ministry_total.reindex(frame.index).fillna(0).ne(0)
    valid_program = core & program_total.reindex(frame.index).fillna(0).ne(0)
    frame.loc[valid_ministry, "ministry_budget_share"] = (
        frame.loc[valid_ministry, "analysis_original_budget"]
        / ministry_total.reindex(frame.index).loc[valid_ministry]
    )
    frame.loc[valid_program, "program_budget_share"] = (
        frame.loc[valid_program, "analysis_original_budget"]
        / program_total.reindex(frame.index).loc[valid_program]
    )
    frame["ministry_budget_share"] = pd.to_numeric(
        frame["ministry_budget_share"], errors="coerce"
    ).astype("Float64")
    frame["program_budget_share"] = pd.to_numeric(
        frame["program_budget_share"], errors="coerce"
    ).astype("Float64")
    frame["budget_size_quantile"] = pd.NA
    frame.loc[core, "budget_size_quantile"] = (
        frame.loc[core]
        .groupby("fiscal_year")["analysis_original_budget"]
        .rank(method="average", pct=True)
    )
    frame["budget_size_quantile"] = pd.to_numeric(
        frame["budget_size_quantile"], errors="coerce"
    ).astype("Float64")
    frame["large_project_flag"] = core & frame["budget_size_quantile"].ge(0.75)

    representativeness_keys = list(
        zip(
            frame["ministry_code"].astype(str),
            frame["fiscal_year"].astype(int),
            frame["account_type_classified"].astype(str),
            strict=True,
        )
    )
    frame["ranking_representativeness_limited"] = [
        key in REPRESENTATIVENESS_LIMITED for key in representativeness_keys
    ]
    frame["ranking_representativeness_reason"] = pd.NA
    frame.loc[
        frame["ranking_representativeness_limited"],
        "ranking_representativeness_reason",
    ] = (
        "strict 모집단에서 해당 부처·연도·기금 대규모 사업 제외율이 "
        "전체 strict 제외율보다 15%p 이상 높음"
    )
    return frame


def build_program_year_financial(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """프로그램 전체금액과 core 분석금액을 분리해 프로그램-연도로 집계합니다."""
    working = frame.copy()
    working["program_code_group"] = working["program_code"].fillna("UNKNOWN")
    working["program_name_group"] = working["program_name"].fillna("UNKNOWN")
    working["field_name_group"] = working["field_name"].fillna("UNKNOWN")
    working["sector_name_group"] = working["sector_name"].fillna("UNKNOWN")
    group_key = [
        "fiscal_year",
        "ministry_code",
        "field_name_group",
        "sector_name_group",
        "program_code_group",
        "program_name_group",
    ]
    rows: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for key, source_group in working.groupby(group_key, dropna=False, sort=True):
        (
            fiscal_year,
            ministry_code,
            field_name,
            sector_name,
            program_code,
            program_name,
        ) = key
        broad_group = source_group.loc[source_group["in_broad_population"]]
        core_group = source_group.loc[source_group["in_core_financial_population"]]
        source_count = source_group["project_id"].nunique()
        project_count = broad_group["project_id"].nunique()
        core_count = core_group["project_id"].nunique()
        if project_count == 0 or core_count == 0:
            linkage = "UNMATCHED"
        elif core_count < project_count:
            linkage = "PARTIAL"
        else:
            linkage = "COMPLETE"
        account_types = sorted(set(core_group["account_type_classified"].dropna().astype(str)))
        denominator_complete = (
            not core_group.empty
            and core_group["execution_denominator_status"].eq("APPLIED").all()
            and core_group["execution_numerator_amount"].notna().all()
            and core_group["execution_denominator_amount"].notna().all()
        )
        numerator = core_group["execution_numerator_amount"].sum(skipna=True)
        denominator = core_group["execution_denominator_amount"].sum(skipna=True)
        execution_rate = (
            float(numerator / denominator)
            if linkage == "COMPLETE" and denominator_complete and denominator != 0
            else None
        )
        budgets = core_group["analysis_original_budget"].dropna().sort_values(ascending=False)
        budget_total = budgets.sum()
        top1_share = float(budgets.head(1).sum() / budget_total) if budget_total else None
        top3_share = float(budgets.head(3).sum() / budget_total) if budget_total else None
        ministry_names = source_group["ministry_name"].dropna()
        ministry_name = ministry_names.iloc[-1] if not ministry_names.empty else pd.NA
        if linkage == "COMPLETE" and execution_rate is not None:
            quality = "HIGH"
        elif linkage == "UNMATCHED":
            quality = "LOW"
        else:
            quality = "MEDIUM"
        row = {
            "fiscal_year": fiscal_year,
            "ministry_code": ministry_code,
            "ministry_name": ministry_name,
            "field_name": field_name,
            "sector_name": sector_name,
            "program_code": program_code,
            "program_name": program_name,
            "program_total_original_budget": source_group["analysis_original_budget"].sum(
                min_count=1
            ),
            "program_total_current_budget": source_group["analysis_current_budget"].sum(
                min_count=1
            ),
            "program_total_expenditure": source_group["analysis_settlement_expenditure"].sum(
                min_count=1
            ),
            "program_analysis_original_budget": core_group["analysis_original_budget"].sum(
                min_count=1
            ),
            "program_analysis_current_budget": core_group["analysis_current_budget"].sum(
                min_count=1
            ),
            "program_analysis_expenditure": core_group["analysis_settlement_expenditure"].sum(
                min_count=1
            ),
            "carryover_amount": core_group["settlement_carryover_amount"].sum(skipna=True),
            "unused_amount": core_group["settlement_unused_amount"].sum(skipna=True),
            "execution_rate": execution_rate,
            "project_count": project_count,
            "analysis_included_project_count": core_count,
            "confirmed_new_project_count": int(
                (
                    core_group["project_status"].eq("NEW") & core_group["project_status_confirmed"]
                ).sum()
            ),
            "confirmed_terminated_project_count": int(
                (
                    core_group["project_status"].eq("TERMINATED")
                    & core_group["project_status_confirmed"]
                ).sum()
            ),
            "new_project_count": int(core_group["project_status"].eq("NEW").sum()),
            "terminated_project_count": int(core_group["project_status"].eq("TERMINATED").sum()),
            "observation_start_project_count": int(
                core_group["project_status"].eq("OBSERVATION_START").sum()
            ),
            "observation_end_project_count": int(
                core_group["project_status"].eq("OBSERVATION_END").sum()
            ),
            "structural_change_project_count": int(core_group["structural_change_flag"].sum()),
            "execution_review_project_count": int(
                (~core_group["execution_analysis_eligible"]).sum()
            ),
            "large_project_count": int(core_group["large_project_flag"].sum()),
            "top1_project_budget_share": top1_share,
            "top3_project_budget_share": top3_share,
            "financial_linkage_status": linkage,
            "financial_quality_level": quality,
            "source_project_count": source_count,
            "account_type_count": len(account_types),
            "account_types": json.dumps(account_types, ensure_ascii=False),
            "mixed_account_type_flag": len(account_types) > 1,
            "execution_aggregation_method": (
                "회계별 적용 분자·분모 합계 후 비율; PARTIAL/UNMATCHED는 null"
            ),
            "ranking_representativeness_limited": bool(
                core_group["ranking_representativeness_limited"].any()
            ),
            "ranking_representativeness_reason": (
                "strict 모집단 부처·연도·기금 대규모 사업 대표성 제한"
                if core_group["ranking_representativeness_limited"].any()
                else pd.NA
            ),
            "source_project_ids": json.dumps(
                sorted(source_group["project_id"].astype(str).unique()),
                ensure_ascii=False,
            ),
        }
        row["analysis_scope_budget_share"] = (
            row["program_analysis_original_budget"] / row["program_total_original_budget"]
            if pd.notna(row["program_total_original_budget"])
            and row["program_total_original_budget"] != 0
            else None
        )
        # 기존 소비자 호환용 별칭이며, 전체 프로그램 금액으로 해석하면 안 됩니다.
        row["original_budget"] = row["program_analysis_original_budget"]
        row["current_budget"] = row["program_analysis_current_budget"]
        row["settlement_expenditure"] = row["program_analysis_expenditure"]
        rows.append(row)
        issue_types: list[str] = []
        if linkage != "COMPLETE":
            issue_types.append(f"FINANCIAL_LINKAGE_{linkage}")
        if execution_rate is None:
            issue_types.append("PROGRAM_EXECUTION_RATE_NOT_AVAILABLE")
        if len(account_types) > 1:
            issue_types.append("MIXED_ACCOUNT_TYPES")
        if program_code == "UNKNOWN":
            issue_types.append("PROGRAM_CODE_MISSING")
        if row["ranking_representativeness_limited"]:
            issue_types.append("RANKING_REPRESENTATIVENESS_LIMITED")
        for issue_type in issue_types:
            issues.append(
                {
                    "issue_type": issue_type,
                    "fiscal_year": fiscal_year,
                    "ministry_code": ministry_code,
                    "field_name": field_name,
                    "sector_name": sector_name,
                    "program_code": program_code,
                    "program_name": program_name,
                    "financial_linkage_status": linkage,
                    "project_count": project_count,
                    "analysis_included_project_count": core_count,
                }
            )
    result = pd.DataFrame(rows)
    for column in [
        "program_total_original_budget",
        "program_total_current_budget",
        "program_total_expenditure",
        "program_analysis_original_budget",
        "program_analysis_current_budget",
        "program_analysis_expenditure",
        "original_budget",
        "current_budget",
        "settlement_expenditure",
        "carryover_amount",
        "unused_amount",
    ]:
        result[column] = pd.to_numeric(result[column], errors="coerce").astype("Int64")
    result["execution_rate"] = pd.to_numeric(result["execution_rate"], errors="coerce").astype(
        "Float64"
    )
    result["analysis_scope_budget_share"] = pd.to_numeric(
        result["analysis_scope_budget_share"], errors="coerce"
    ).astype("Float64")
    return result, pd.DataFrame(issues)


def build_project_continuity(
    *,
    financial_v1_path: Path,
    broad_path: Path,
    core_path: Path,
    strict_path: Path,
    classification_path: Path,
    mentoring_guide_path: Path,
    project_plan_path: Path,
    output_dir: Path,
    overwrite: bool = False,
    prewindow_budget_path: Path | None = DEFAULT_PREWINDOW_BUDGET_PATH,
) -> ProjectContinuityResult:
    """관계·financial v2·프로그램-연도와 품질 산출물을 생성합니다."""
    required = [
        financial_v1_path,
        broad_path,
        core_path,
        strict_path,
        classification_path,
        mentoring_guide_path,
        project_plan_path,
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"필수 입력 파일이 없습니다: {missing[0]}")
    financial_v1 = pd.read_parquet(financial_v1_path)
    broad = pd.read_parquet(broad_path)
    core = pd.read_parquet(core_path)
    strict = pd.read_parquet(strict_path)
    classification = pd.read_parquet(classification_path)
    for frame in (financial_v1, broad, core, strict, classification):
        frame["ministry_code"] = frame["ministry_code"].astype("string")

    prewindow_path = prewindow_budget_path or DEFAULT_PREWINDOW_BUDGET_PATH
    prewindow_name_years = load_prewindow_budget_name_years(prewindow_path)
    relations = build_project_relations(
        financial_v1,
        prewindow_name_years=prewindow_name_years,
    )
    financial_v2 = build_financial_v2(
        financial_v1=financial_v1,
        relations=relations,
        classification=classification,
        broad_ids=set(broad["source_project_year_id"].astype(str)),
        core_ids=set(core["source_project_year_id"].astype(str)),
        strict_ids=set(strict["source_project_year_id"].astype(str)),
        broad_flags=broad,
    )
    program_year, program_issues = build_program_year_financial(financial_v2)
    manual_review = relations.loc[
        relations["review_priority"].isin({"MANUAL_REVIEW", "BLOCKING"})
    ].copy()

    source_index = financial_v1.set_index(SOURCE_KEY).sort_index()
    v2_index = financial_v2.set_index(SOURCE_KEY).sort_index()
    amount_changed = 0
    for column in SOURCE_AMOUNT_COLUMNS:
        left = pd.to_numeric(source_index[column], errors="coerce").astype("Float64")
        right = pd.to_numeric(v2_index[column], errors="coerce").astype("Float64")
        amount_changed += int((~(left.eq(right) | (left.isna() & right.isna()))).sum())
    program_input = financial_v2.loc[financial_v2["in_core_financial_population"]]
    amount_reconciliation = {}
    for source_column, program_column in [
        ("analysis_original_budget", "original_budget"),
        ("analysis_current_budget", "current_budget"),
        ("analysis_settlement_expenditure", "settlement_expenditure"),
        ("settlement_carryover_amount", "carryover_amount"),
        ("settlement_unused_amount", "unused_amount"),
    ]:
        input_amount = int(program_input[source_column].sum(skipna=True))
        output_amount = int(program_year[program_column].sum(skipna=True))
        amount_reconciliation[program_column] = {
            "input_amount": input_amount,
            "output_amount": output_amount,
            "difference": output_amount - input_amount,
        }
    total_amount_reconciliation = {}
    for source_column, program_column in [
        ("analysis_original_budget", "program_total_original_budget"),
        ("analysis_current_budget", "program_total_current_budget"),
        ("analysis_settlement_expenditure", "program_total_expenditure"),
    ]:
        input_amount = int(financial_v2[source_column].sum(skipna=True))
        output_amount = int(program_year[program_column].sum(skipna=True))
        total_amount_reconciliation[program_column] = {
            "input_amount": input_amount,
            "output_amount": output_amount,
            "difference": output_amount - input_amount,
        }

    relation_counts = relations["relation_type"].value_counts().sort_index().to_dict()
    review_priority_counts = relations["review_priority"].value_counts().sort_index().to_dict()
    missing_reason_counts = (
        financial_v2.loc[
            financial_v2["budget_change_status"].ne("CALCULATED"),
            "budget_change_missing_reason",
        ]
        .fillna("UNKNOWN")
        .str.split(";")
        .explode()
        .value_counts()
        .sort_index()
        .to_dict()
    )
    relation_summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "relation_row_count": len(relations),
        "relation_type_counts": relation_counts,
        "new_relation_count": relation_counts.get("NEW", 0),
        "terminated_relation_count": relation_counts.get("TERMINATED", 0),
        "renamed_relation_count": relation_counts.get("RENAMED", 0),
        "code_changed_relation_count": relation_counts.get("CODE_CHANGED", 0),
        "merge_split_transfer_candidate_count": sum(
            relation_counts.get(value, 0) for value in ["MERGED", "SPLIT", "TRANSFERRED"]
        ),
        "unknown_relation_count": relation_counts.get("UNKNOWN", 0),
        "manual_review_relation_count": len(manual_review),
        "manual_review_total": len(manual_review),
        "blocking_review_count": review_priority_counts.get("BLOCKING", 0),
        "relationship_candidate_count": review_priority_counts.get("MANUAL_REVIEW", 0),
        "observation_boundary_count": sum(
            relation_counts.get(value, 0) for value in ["LEFT_CENSORED", "RIGHT_CENSORED"]
        ),
        "review_status_counts": (relations["review_status"].value_counts().sort_index().to_dict()),
        "review_priority_counts": review_priority_counts,
    }
    first_year = int(financial_v2["fiscal_year"].min())
    last_year = int(financial_v2["fiscal_year"].max())
    prewindow_continued = int(relations["matching_method"].eq(PREWINDOW_MATCH_METHOD).sum())
    observation_summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "observation_window": {"start_year": first_year, "end_year": last_year},
        "continuity_evidence_window": {
            "start_year": 2020 if prewindow_name_years else None,
            "end_year": 2021 if prewindow_name_years else None,
            "source_path": str(prewindow_path),
            "unique_name_key_count": len(prewindow_name_years),
            "match_method": PREWINDOW_MATCH_METHOD,
        },
        "left_censored_relation_count": relation_counts.get("LEFT_CENSORED", 0),
        "right_censored_relation_count": relation_counts.get("RIGHT_CENSORED", 0),
        "prewindow_continued_relation_count": prewindow_continued,
        "observation_start_project_year_count": int(
            financial_v2["project_status"].eq("OBSERVATION_START").sum()
        ),
        "observation_end_project_year_count": int(
            financial_v2["project_status"].eq("OBSERVATION_END").sum()
        ),
        "prior_window_observed_project_year_count": int(
            financial_v2["prior_window_observed"].fillna(False).sum()
        ),
        "start_year_new_due_only_to_boundary_count": int(
            financial_v2.loc[financial_v2["fiscal_year"].eq(first_year), "project_status"]
            .eq("NEW")
            .sum()
        ),
        "end_year_terminated_due_only_to_boundary_count": int(
            financial_v2.loc[financial_v2["fiscal_year"].eq(last_year), "project_status"]
            .eq("TERMINATED")
            .sum()
        ),
        "boundary_manual_review_count": int(
            relations.loc[
                relations["relation_type"].isin({"LEFT_CENSORED", "RIGHT_CENSORED"}),
                "manual_review_required",
            ].sum()
        ),
        "manual_review_total": len(manual_review),
        "blocking_review_count": review_priority_counts.get("BLOCKING", 0),
        "relationship_candidate_count": review_priority_counts.get("MANUAL_REVIEW", 0),
        "observation_boundary_count": sum(
            relation_counts.get(value, 0) for value in ["LEFT_CENSORED", "RIGHT_CENSORED"]
        ),
        "interpretation": (
            "분석 금액 창은 기존 시작연도~종료연도를 유지하고, 2020~2021 예산 명칭키가 "
            "확인된 시작연도 행만 OBSERVATION_START에서 CONTINUING으로 운영 승격한다. "
            "이전 미확인 행은 LEFT_CENSORED를 유지하며 NEW로 바꾸지 않는다."
        ),
    }
    v2_summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source_row_count": len(financial_v1),
        "financial_v2_row_count": len(financial_v2),
        "primary_key_duplicate_count": int(financial_v2.duplicated(SOURCE_KEY, keep=False).sum()),
        "project_status_counts": (
            financial_v2["project_status"].value_counts().sort_index().to_dict()
        ),
        "budget_change_calculated_count": int(
            financial_v2["budget_change_status"].eq("CALCULATED").sum()
        ),
        "budget_change_excluded_count": int(
            financial_v2["budget_change_status"].ne("CALCULATED").sum()
        ),
        "budget_change_missing_reason_counts": missing_reason_counts,
        "representativeness_limited_project_year_count": int(
            financial_v2["ranking_representativeness_limited"].sum()
        ),
        "source_amount_changed_cell_count": amount_changed,
        "leading_zero_ministry_codes_preserved": all(
            code in set(financial_v2["ministry_code"]) for code in ("019", "075")
        ),
        "source_trace_missing_count": int(financial_v2["source_trace"].isna().sum()),
    }
    linkage_counts = program_year["financial_linkage_status"].value_counts().sort_index().to_dict()
    program_summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "program_year_row_count": len(program_year),
        "financial_linkage_status_counts": linkage_counts,
        "project_count_distribution": {
            "min": int(program_year["project_count"].min()) if len(program_year) else None,
            "median": (
                float(program_year["project_count"].median()) if len(program_year) else None
            ),
            "max": int(program_year["project_count"].max()) if len(program_year) else None,
        },
        "representativeness_limited_program_count": int(
            program_year["ranking_representativeness_limited"].sum()
        ),
        "observation_start_project_count": int(
            program_year["observation_start_project_count"].sum()
        ),
        "observation_end_project_count": int(program_year["observation_end_project_count"].sum()),
        "confirmed_new_project_count": int(program_year["confirmed_new_project_count"].sum()),
        "confirmed_terminated_project_count": int(
            program_year["confirmed_terminated_project_count"].sum()
        ),
        "program_execution_rate_nonnull_count": int(program_year["execution_rate"].notna().sum()),
        "partial_or_unmatched_execution_rate_nonnull_count": int(
            program_year.loc[
                program_year["financial_linkage_status"].isin({"PARTIAL", "UNMATCHED"}),
                "execution_rate",
            ]
            .notna()
            .sum()
        ),
        "quality_issue_count": len(program_issues),
        "amount_reconciliation": amount_reconciliation,
        "program_total_amount_reconciliation": total_amount_reconciliation,
    }
    summaries = {
        "project_relation_summary": relation_summary,
        "observation_boundary_summary": observation_summary,
        "project_year_financial_v2_summary": v2_summary,
        "program_year_financial_summary": program_summary,
    }

    output_paths = [
        output_dir / "project_relation.parquet",
        output_dir / "project_year_financial_v2.parquet",
        output_dir / "program_year_financial.parquet",
        output_dir / "project_relation_summary.json",
        output_dir / "project_relation_manual_review.csv",
        output_dir / "project_year_financial_v2_summary.json",
        output_dir / "program_year_financial_summary.json",
        output_dir / "program_year_financial_quality_issues.csv",
        output_dir / "observation_boundary_summary.json",
    ]
    existing = [path for path in output_paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"출력 파일이 이미 있습니다: {existing[0]}")
    output_dir.mkdir(parents=True, exist_ok=True)
    relations.to_parquet(output_paths[0], index=False)
    financial_v2.to_parquet(output_paths[1], index=False)
    program_year.to_parquet(output_paths[2], index=False)
    output_paths[3].write_text(
        json.dumps(relation_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manual_review.to_csv(output_paths[4], index=False, encoding="utf-8-sig")
    output_paths[5].write_text(
        json.dumps(v2_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    output_paths[6].write_text(
        json.dumps(program_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    program_issues.to_csv(output_paths[7], index=False, encoding="utf-8-sig")
    output_paths[8].write_text(
        json.dumps(observation_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return ProjectContinuityResult(
        relations=relations,
        financial_v2=financial_v2,
        program_year=program_year,
        relation_manual_review=manual_review,
        program_quality_issues=program_issues,
        summaries=summaries,
        output_paths=output_paths,
    )
