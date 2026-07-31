from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from fiscal_dashboard.app import (
    WORKFLOW_STEPS,
    _component_summary,
    _data_review_table,
    _program_count,
    _review_worklist,
    filter_candidates,
    load_dashboard_data,
    load_pdf_review_queue,
    review_page_specs,
    stable_program_summary,
)


def test_dashboard_data_contract_and_filter() -> None:
    data = load_dashboard_data(Path("."))
    candidates = data["candidates"]
    filtered = filter_candidates(
        candidates,
        scope="순위 적격 후보",
        years=[2022, 2023, 2024],
        account_types=[
            "GENERAL_ACCOUNT",
            "SPECIAL_ACCOUNT",
            "RESPONSIBLE_OPERATION_ACCOUNT",
            "FUND",
        ],
        tiers=candidates["priority_tier"].dropna().unique().tolist(),
    )

    assert len(candidates) == 347
    assert len(filtered) == 193
    assert _program_count(candidates) == 68
    assert filtered["scenario_ranking_eligible"].all()
    assert data["scores"].shape == (772, 28)
    assert data["drilldown"].empty
    assert not data["drilldown"]["project_performance_attributed"].any()
    assert not data["stability"]["candidate_id"].duplicated().any()
    assert pd.to_numeric(data["scores"]["scenario_score"]).between(0, 1).all()
    full = filter_candidates(
        candidates,
        scope="데이터 검증 포함 전체",
        years=[2022, 2023, 2024],
        account_types=[
            "GENERAL_ACCOUNT",
            "SPECIAL_ACCOUNT",
            "RESPONSIBLE_OPERATION_ACCOUNT",
            "FUND",
            "NOT_AVAILABLE",
        ],
        tiers=candidates["priority_tier"].dropna().unique().tolist(),
    )
    assert len(full) == 347
    assert full["data_validation_signal"].sum() == 14
    assert len(_data_review_table(full.loc[full["data_validation_signal"]])) == 14
    worklist = _review_worklist(full.loc[full["data_validation_signal"]])
    assert len(worklist) == 9
    assert worklist["영향행"].sum() == 14
    assert worklist["상태"].eq("확인 필요").sum() == 7
    assert worklist["상태"].eq("확인 완료").sum() == 2
    assert _component_summary("성과", 0.5)[0] == "50%"
    assert stable_program_summary(candidates, data["stability"]).empty

    queue = load_pdf_review_queue(Path("."))
    assert len(queue) == 361
    assert queue["review_status"].isna().all()
    assert any(review_page_specs(row) for _, row in queue.iterrows())


def test_dashboard_default_render() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    assert not app.exception
    assert [title.value for title in app.title] == ["재정사업 점검 작업대"]
    assert len(app.tabs) == 0
    assert app.segmented_control[0].options == WORKFLOW_STEPS
    assert app.segmented_control[0].value == "1. 전체 현황"
    assert [(metric.label, metric.value) for metric in app.metric[:4]] == [
        ("분석행", "347"),
        ("점검 신호 있음", "228"),
        ("순위 비교 가능", "193"),
        ("데이터 먼저 확인", "14"),
    ]
    assert "지금 해야 할 일부터 보여드립니다" in [heading.value for heading in app.subheader]
    assert any(frame.value.shape[0] == 5 for frame in app.dataframe)


def test_dashboard_guided_steps_and_candidate_to_review() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    app.segmented_control[0].set_value("2. 먼저 해결").run()
    assert not app.exception
    assert "먼저 해결할 일을 프로그램 단위로 정리했습니다" in [item.value for item in app.subheader]
    assert any(frame.value.shape[0] == 9 for frame in app.dataframe)
    assert any(frame.value.shape[0] == 14 for frame in app.dataframe)

    app.segmented_control[0].set_value("3. 후보 살펴보기").run()
    assert not app.exception
    assert "후보 하나를 골라 왜 올라왔는지 확인합니다" in [item.value for item in app.subheader]
    review_button = next(
        button for button in app.button if button.label == "이 프로그램 PDF 원문 확인"
    )
    review_button.click().run()
    assert not app.exception
    assert app.segmented_control[0].value == "5. 원문 검수"
    assert "발표에 쓸 성과지표만 PDF 원문으로 확인합니다" in [item.value for item in app.subheader]
    assert any("후보 분석에서 선택한" in item.value for item in app.info)


def test_dashboard_ministry_rank_view() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    app.multiselect[0].set_value(["019"]).run()
    app.segmented_control[0].set_value("4. 순위 안정성").run()
    app.segmented_control[1].set_value("선택 부처 내부").run()

    assert not app.exception
    assert app.segmented_control[1].value == "선택 부처 내부"
    assert "기준을 바꿔도 계속 상위인지 확인합니다" in [item.value for item in app.subheader]
    assert any(
        "고용노동부 내부 기준 현재 필터 41행 중 공통 Top 5는 2행" in item.value
        for item in app.warning
    )
