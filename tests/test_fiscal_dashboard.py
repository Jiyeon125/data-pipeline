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
    candidates = data["work_queue"]
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

    assert len(candidates) == 412
    assert candidates["candidate_id"].is_unique
    assert set(candidates["candidate_id"]) == set(data["candidates"]["candidate_id"])
    assert len(filtered) == 235
    assert _program_count(candidates) == 79
    assert filtered["scenario_ranking_eligible"].all()
    assert data["scores"].shape == (940, 28)
    assert data["drilldown"].shape == (110, 40)
    assert not data["drilldown"]["project_performance_attributed"].any()
    assert data["work_queue"].shape == (412, 106)
    assert data["work_queue"]["work_lane"].value_counts().to_dict() == {
        "MODELED_SIGNAL_REVIEW": 235,
        "NO_TRIGGER_MONITORING": 125,
        "CONTEXT_REVIEW": 37,
        "DATA_VERIFICATION": 15,
    }
    assert data["work_queue"]["safety_conclusion"].eq("NOT_ASSESSED").all()
    assert data["project_queue"].shape == (3286, 53)
    assert data["project_queue"]["candidate_id"].nunique() == 397
    assert not data["project_queue"]["project_performance_attributed"].any()
    assert not data["stability"]["candidate_id"].duplicated().any()
    assert pd.to_numeric(data["scores"]["scenario_score"]).between(0, 1).all()
    full = filter_candidates(
        candidates,
        scope="전체 업무대기열",
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
    assert len(full) == 412
    assert full["data_validation_signal"].sum() == 15
    assert len(_data_review_table(full.loc[full["data_validation_signal"]])) == 15
    worklist = _review_worklist(full.loc[full["data_validation_signal"]])
    assert len(worklist) == 10
    assert worklist["영향행"].sum() == 15
    assert worklist["상태"].eq("확인 필요").sum() == 8
    assert worklist["상태"].eq("확인 완료").sum() == 2
    assert _component_summary("성과", 0.5)[0] == "50%"
    assert stable_program_summary(candidates, data["stability"]).empty
    no_trigger = filter_candidates(
        candidates,
        scope="현재 신호 미검출·모니터링",
        years=[2022, 2023, 2024],
        account_types=candidates["account_type"].dropna().unique().tolist(),
        tiers=candidates["priority_tier"].dropna().unique().tolist(),
    )
    assert len(no_trigger) == 125
    assert no_trigger["safety_conclusion"].eq("NOT_ASSESSED").all()

    queue = load_pdf_review_queue(Path("."))
    assert len(queue) == 361
    assert queue["review_status"].isna().all()
    assert queue["manual_review_required"].sum() == 201
    assert (~queue["manual_review_required"]).sum() == 160
    assert any(review_page_specs(row) for _, row in queue.iterrows())


def test_dashboard_default_render() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    assert not app.exception
    assert [title.value for title in app.title] == ["재정사업 점검 작업대"]
    assert len(app.tabs) == 0
    assert app.segmented_control[0].options == WORKFLOW_STEPS
    assert app.segmented_control[0].value == "1. 전체 현황"
    assert [(metric.label, metric.value) for metric in app.metric[:5]] == [
        ("전체 업무행", "412"),
        ("성과·집행 신호", "235"),
        ("맥락 검토", "37"),
        ("데이터 먼저", "15"),
        ("신호 미검출", "125"),
    ]
    assert app.multiselect[0].options == [
        "고용노동부",
        "보건복지부",
        "중소벤처기업부",
        "과학기술정보통신부",
    ]
    assert "지금 해야 할 일부터 보여드립니다" in [heading.value for heading in app.subheader]
    assert any(frame.value.shape[0] == 10 for frame in app.dataframe)

    app.segmented_control[0].set_value("5. 원문 검수").run()
    assert not app.exception
    review_metric = next(metric for metric in app.metric if metric.label == "현재 검수 대상")
    assert review_metric.value == "201"


def test_dashboard_guided_steps_and_candidate_to_review() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    app.segmented_control[0].set_value("2. 먼저 해결").run()
    assert not app.exception
    assert "먼저 해결할 일을 프로그램 단위로 정리했습니다" in [item.value for item in app.subheader]
    assert any(frame.value.shape[0] == 10 for frame in app.dataframe)
    assert any(frame.value.shape[0] == 15 for frame in app.dataframe)

    app.radio[0].set_value("성과·집행 신호 검토").run()
    app.segmented_control[0].set_value("3. 후보 살펴보기").run()
    assert not app.exception
    assert "업무 하나를 골라 왜 이 순서인지 확인합니다" in [item.value for item in app.subheader]
    review_button = next(
        button for button in app.button if button.label == "이 프로그램 PDF 원문 확인"
    )
    review_button.click().run()
    assert not app.exception
    assert app.segmented_control[0].value == "5. 원문 검수"
    assert "사람 확인이 필요한 성과지표부터 PDF 원문으로 검수합니다" in [
        item.value for item in app.subheader
    ]
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


def test_dashboard_mss_project_queue_without_false_pdf_link() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    app.multiselect[0].set_value(["102"]).run()
    app.radio[0].set_value("성과·집행 신호 검토").run()
    app.segmented_control[0].set_value("3. 후보 살펴보기").run()

    assert not app.exception
    assert any(frame.value.shape[1] == 12 for frame in app.dataframe)
    review_button = next(
        button for button in app.button if button.label == "이 프로그램 PDF 원문 확인"
    )
    assert review_button.disabled
