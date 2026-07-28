from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from fiscal_dashboard.app import (
    filter_candidates,
    load_dashboard_data,
    stable_program_summary,
)


def test_dashboard_data_contract_and_filter() -> None:
    data = load_dashboard_data(Path("."))
    candidates = data["candidates"]
    filtered = filter_candidates(
        candidates,
        scope="순위 적격 후보",
        years=[2022, 2023, 2024],
        account_types=["GENERAL_ACCOUNT", "SPECIAL_ACCOUNT", "FUND"],
        tiers=candidates["priority_tier"].dropna().unique().tolist(),
    )

    assert len(candidates) == 66
    assert len(filtered) == 38
    assert filtered["scenario_ranking_eligible"].all()
    assert data["scores"].shape == (152, 20)
    assert data["drilldown"].shape[0] == 94
    assert data["drilldown"]["candidate_id"].nunique() == 5
    assert not data["drilldown"]["project_performance_attributed"].any()
    assert not data["stability"]["candidate_id"].duplicated().any()
    assert pd.to_numeric(data["scores"]["scenario_score"]).between(0, 1).all()
    full = filter_candidates(
        candidates,
        scope="데이터 검증 포함 전체",
        years=[2022, 2023, 2024],
        account_types=["GENERAL_ACCOUNT", "SPECIAL_ACCOUNT", "FUND", "NOT_AVAILABLE"],
        tiers=candidates["priority_tier"].dropna().unique().tolist(),
    )
    assert len(full) == 66
    assert full["data_validation_signal"].sum() == 8
    stable = stable_program_summary(candidates, data["stability"])
    assert stable["program_name"].tolist() == [
        "소상공인·전통시장지원",
        "창업환경조성",
        "중소기업기술개발지원",
    ]
    assert stable["stable_row_count"].sum() == 5


def test_dashboard_default_render() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    assert not app.exception
    assert [title.value for title in app.title] == ["중기부 재정사업 점검 후보"]
    assert [tab.label for tab in app.tabs] == [
        "핵심 요약",
        "후보 찾아보기",
        "시나리오 비교",
        "데이터 검증",
    ]
    assert [(metric.label, metric.value) for metric in app.metric[:4]] == [
        ("점검 후보", "45행"),
        ("순위 비교 가능", "38행"),
        ("안정 상위", "3개 프로그램"),
        ("데이터 검증 우선", "8행"),
    ]
    assert "세부사업 재정 원인" in [heading.value for heading in app.subheader]
