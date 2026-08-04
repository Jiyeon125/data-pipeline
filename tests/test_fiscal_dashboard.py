from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from fiscal_dashboard.app import (
    MAIN_TABS,
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
        tiers=candidates["review_intensity"].dropna().unique().tolist(),
    )

    assert len(candidates) == 412
    assert candidates["candidate_id"].is_unique
    assert set(candidates["candidate_id"]) == set(data["candidates"]["candidate_id"])
    assert len(filtered) == 231
    assert _program_count(candidates) == 79
    assert filtered["scenario_ranking_eligible"].all()
    assert data["scores"].shape[0] == 924
    assert data["drilldown"].shape[0] == 74
    assert not data["drilldown"]["project_performance_attributed"].any()
    assert data["work_queue"].shape[0] == 412
    assert data["work_queue"]["work_lane"].value_counts().to_dict() == {
        "REPEATED_OR_MULTIPLE": 132,
        "MONITOR": 105,
        "CONTEXT_REVIEW": 84,
        "SINGLE_REVIEW": 76,
        "DATA_FIRST": 15,
    }
    assert "STRONG_SINGLE" not in data["work_queue"]["work_lane"].to_numpy()
    assert data["work_queue"]["program_total_feedback_complete_t1"].sum() == 72
    assert data["work_queue"]["program_total_feedback_complete_t2"].sum() == 34
    assert data["work_queue"]["continuous_project_feedback_complete_t1"].sum() == 108
    assert data["work_queue"]["continuous_project_feedback_complete_t2"].sum() == 42
    assert data["work_queue"]["program_total_account_type_mismatch_t1"].sum() == 3
    assert data["work_queue"]["account_type"].eq("FUND").sum() == 131
    assert data["summary"]["review_workbench_method"]["weighted_sum_used"] is False
    assert data["summary"]["review_workbench_method"]["t1_t2_kept_separate"] is True
    assert data["summary"]["review_workbench_method"]["signal_score_used_in_work_queue"] is True
    assert data["summary"]["feedback_linkage"] == {
        "eligible_rows": 2896,
        "matched_rows": 2893,
        "unmatched_base_project_rows": 3,
    }
    assert data["work_queue"]["safety_conclusion"].eq("NOT_ASSESSED").all()
    assert data["project_queue"].shape[0] == 3286
    assert data["project_queue"]["candidate_id"].nunique() == 397
    assert not data["project_queue"]["project_performance_attributed"].any()
    assert not data["stability"]["candidate_id"].duplicated().any()
    assert data["review_queue"].shape[0] == 3301
    assert data["review_queue"]["work_item_id"].is_unique
    assert data["review_queue"]["review_item_type"].value_counts().to_dict() == {
        "DETAILED_PROJECT_REVIEW": 3286,
        "PROGRAM_DATA_TASK": 15,
    }
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
        tiers=candidates["review_intensity"].dropna().unique().tolist(),
    )
    assert len(full) == 412
    assert full["data_validation_signal"].sum() == 15
    assert len(_data_review_table(full.loc[full["data_validation_signal"]])) == 15
    worklist = _review_worklist(full.loc[full["data_validation_signal"]])
    assert len(worklist) == 10
    assert worklist["영향행"].sum() == 15
    assert _component_summary("성과", 0.5)[0] == "50%"
    assert stable_program_summary(candidates, data["stability"]).empty
    no_trigger = filter_candidates(
        candidates,
        scope="신호 미검출·모니터링",
        years=[2022, 2023, 2024],
        account_types=candidates["account_type"].dropna().unique().tolist(),
        tiers=candidates["review_intensity"].dropna().unique().tolist(),
    )
    assert len(no_trigger) == 105
    assert no_trigger["safety_conclusion"].eq("NOT_ASSESSED").all()

    from fiscal_dashboard.app import get_pdf_review_queue

    queue = get_pdf_review_queue(Path("."))
    assert len(queue) == 361
    # 사람 판정 완료분은 열린 검수 대상에서 제외
    assert int(queue["review_done"].sum()) >= 1
    assert queue["manual_review_required"].sum() == 28
    assert any(review_page_specs(row) for _, row in queue.iterrows())
    mohw = queue.loc[queue["source_indicator_id"].eq("MOHW-2023-II2-01")].iloc[0]
    assert mohw["review_status"] == "CONFIRMED"
    assert bool(mohw["review_done"]) is True
    assert bool(mohw["manual_review_required"]) is False


def test_dashboard_default_render() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    assert not app.exception
    assert [title.value for title in app.title] == ["재정사업 점검 대기열"]
    assert app.segmented_control[0].options == list(MAIN_TABS)
    assert app.segmented_control[0].value == "대기열"
    # 기본 필터: ‘신호 없음’(MONITOR) 숨김 → 412-105=307
    assert [(metric.label, metric.value) for metric in app.metric[:4]] == [
        ("지금 표에 보이는 행", "307"),
        ("우선(반복·복수)", "132"),
        ("데이터 먼저", "15"),
        ("프로그램 수", "78"),
    ]
    assert app.multiselect[0].options == [
        "고용노동부",
        "보건복지부",
        "중소벤처기업부",
        "과학기술정보통신부",
    ]


def test_dashboard_open_card_and_pdf_review_navigation() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    open_card = next(
        button for button in app.button if button.label == "선택한 행 사업 카드 열기"
    )
    open_card.click().run()
    assert not app.exception
    assert app.segmented_control[0].value == "사업 카드"

    review_button = next(
        button
        for button in app.button
        if button.label == "이 프로그램 원문(PDF) 검수로 이동" and not button.disabled
    )
    review_button.click().run()
    assert not app.exception
    assert app.segmented_control[0].value == "원문 검수"
    assert any("판정" in (item.value or "") for item in app.info)


def test_dashboard_pdf_review_mode() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    app.segmented_control[0].set_value("원문 검수").run()

    assert not app.exception
    review_metric = next(metric for metric in app.metric if metric.label == "남은 검수")
    assert review_metric.value == "28"


def test_dashboard_mss_project_queue_without_false_pdf_link() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    app.multiselect[0].set_value(["102"]).run()
    app.segmented_control[0].set_value("사업 카드").run()
    project_candidate = (
        load_dashboard_data(Path("."))["project_queue"]
        .loc[lambda frame: frame["ministry_code"].eq("102"), "candidate_id"]
        .iloc[0]
    )
    app.selectbox[0].set_value(project_candidate).run()

    assert not app.exception
    review_button = next(
        button for button in app.button if button.label == "이 프로그램 원문(PDF) 검수로 이동"
    )
    assert review_button.disabled
