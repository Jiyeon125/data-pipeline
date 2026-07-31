from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from fiscal_dashboard.app import (
    GLASS_THEME_PATH,
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


def test_glass_theme_is_local_and_accessible() -> None:
    css = GLASS_THEME_PATH.read_text(encoding="utf-8")

    assert "backdrop-filter: blur" in css
    assert ".st-key-hero" in css
    assert "prefers-reduced-transparency" in css


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
    assert len(filtered) == 235
    assert _program_count(candidates) == 79
    assert filtered["scenario_ranking_eligible"].all()
    assert data["scores"].shape == (940, 28)
    assert data["drilldown"].shape == (110, 40)
    assert not data["drilldown"]["project_performance_attributed"].any()
    assert data["work_queue"].shape == (412, 172)
    assert data["work_queue"]["work_lane"].value_counts().to_dict() == {
        "REPEATED_OR_MULTIPLE": 132,
        "MONITOR": 96,
        "CONTEXT_REVIEW": 93,
        "SINGLE_REVIEW": 60,
        "STRONG_SINGLE": 16,
        "DATA_FIRST": 15,
    }
    assert data["work_queue"]["program_total_feedback_complete_t1"].sum() == 107
    assert data["work_queue"]["program_total_feedback_complete_t2"].sum() == 69
    assert data["work_queue"]["continuous_project_feedback_complete_t1"].sum() == 108
    assert data["work_queue"]["continuous_project_feedback_complete_t2"].sum() == 42
    assert data["work_queue"]["program_total_account_type_mismatch_t1"].sum() == 3
    assert data["work_queue"]["account_type"].eq("FUND").sum() == 131
    assert data["summary"]["review_workbench_method"]["weighted_sum_used"] is False
    assert data["summary"]["review_workbench_method"]["t1_t2_kept_separate"] is True
    assert data["summary"]["feedback_linkage"] == {
        "eligible_rows": 2896,
        "matched_rows": 2893,
        "unmatched_base_project_rows": 3,
    }
    assert data["work_queue"]["safety_conclusion"].eq("NOT_ASSESSED").all()
    assert data["project_queue"].shape == (3286, 65)
    assert data["project_queue"]["candidate_id"].nunique() == 397
    assert not data["project_queue"]["project_performance_attributed"].any()
    assert not data["stability"]["candidate_id"].duplicated().any()
    assert data["review_queue"].shape == (3301, 26)
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
    assert worklist["상태"].eq("확인 필요").sum() == 8
    assert worklist["상태"].eq("확인 완료").sum() == 2
    assert _component_summary("성과", 0.5)[0] == "50%"
    assert stable_program_summary(candidates, data["stability"]).empty
    no_trigger = filter_candidates(
        candidates,
        scope="신호 미검출·모니터링",
        years=[2022, 2023, 2024],
        account_types=candidates["account_type"].dropna().unique().tolist(),
        tiers=candidates["review_intensity"].dropna().unique().tolist(),
    )
    assert len(no_trigger) == 96
    assert no_trigger["safety_conclusion"].eq("NOT_ASSESSED").all()

    queue = load_pdf_review_queue(Path("."))
    assert len(queue) == 361
    assert queue["review_status"].isna().all()
    assert queue["manual_review_required"].sum() == 29
    assert (~queue["manual_review_required"]).sum() == 332
    assert any(review_page_specs(row) for _, row in queue.iterrows())


def test_dashboard_default_render() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    assert not app.exception
    assert [title.value for title in app.title] == ["재정사업 점검 작업대"]
    assert len(app.tabs) == 0
    assert app.segmented_control[0].options == WORKFLOW_STEPS
    assert app.segmented_control[0].value == "1. 업무 현황"
    assert [(metric.label, metric.value) for metric in app.metric[:5]] == [
        ("전체 업무행", "412"),
        ("반복·복수 신호", "132"),
        ("강한 단일 신호", "16"),
        ("데이터 먼저", "15"),
        ("신호 미검출", "96"),
    ]
    assert app.multiselect[0].options == [
        "고용노동부",
        "보건복지부",
        "중소벤처기업부",
        "과학기술정보통신부",
    ]
    assert "가중점수 대신 확인할 근거와 다음 행동을 보여드립니다" in [
        heading.value for heading in app.subheader
    ]
    assert any(frame.value.shape[0] == 10 for frame in app.dataframe)

    app.segmented_control[0].set_value("4. 비교·원문 검수").run()
    assert not app.exception
    assert app.segmented_control[1].value == "대표 사례"
    assert (
        next(metric for metric in app.metric if metric.label == "성과 미달·전체 T+1 연결").value
        == "29"
    )
    assert any(frame.value.shape[0] == 7 for frame in app.dataframe)


def test_dashboard_guided_steps_and_candidate_to_review() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    app.segmented_control[0].set_value("2. 점검대기열").run()
    assert not app.exception
    assert "다음에 확인할 세부사업과 데이터 작업을 한 줄로 정리했습니다" in [
        item.value for item in app.subheader
    ]
    assert any(frame.value.shape[0] == 3301 for frame in app.dataframe)
    assert any(frame.value.shape[0] == 10 for frame in app.dataframe)
    assert any(frame.value.shape[0] == 15 for frame in app.dataframe)

    app.segmented_control[0].set_value("3. 사업 상세").run()
    assert not app.exception
    assert "프로그램 신호와 세부사업 원인을 분리해서 확인합니다" in [
        item.value for item in app.subheader
    ]
    review_button = next(
        button for button in app.button if button.label == "이 프로그램 PDF 원문 확인"
    )
    review_button.click().run()
    assert not app.exception
    assert app.segmented_control[0].value == "4. 비교·원문 검수"
    assert "사람 확인이 필요한 성과지표부터 PDF 원문으로 검수합니다" in [
        item.value for item in app.subheader
    ]
    assert any("후보 분석에서 선택한" in item.value for item in app.info)


def test_dashboard_ministry_rank_view() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    app.multiselect[0].set_value(["019"]).run()
    app.segmented_control[0].set_value("4. 비교·원문 검수").run()
    app.segmented_control[1].set_value("고급 민감도").run()
    app.segmented_control[2].set_value("선택 부처 내부").run()

    assert not app.exception
    assert app.segmented_control[2].value == "선택 부처 내부"
    assert "기존 가중치 결과는 고급 민감도에서만 확인합니다" in [
        item.value for item in app.subheader
    ]
    assert any(
        "고용노동부 내부 기준 현재 필터 41행 중 공통 Top 5는 2행" in item.value
        for item in app.warning
    )


def test_dashboard_pdf_review_mode() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    app.segmented_control[0].set_value("4. 비교·원문 검수").run()
    app.segmented_control[1].set_value("원문 검수").run()

    assert not app.exception
    review_metric = next(metric for metric in app.metric if metric.label == "현재 검수 대상")
    assert review_metric.value == "29"


def test_dashboard_mss_project_queue_without_false_pdf_link() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    app.multiselect[0].set_value(["102"]).run()
    app.segmented_control[0].set_value("3. 사업 상세").run()
    project_candidate = (
        load_dashboard_data(Path("."))["project_queue"]
        .loc[lambda frame: frame["ministry_code"].eq("102"), "candidate_id"]
        .iloc[0]
    )
    app.selectbox[0].set_value(project_candidate).run()

    assert not app.exception
    assert any(frame.value.shape[1] == 12 for frame in app.dataframe)
    review_button = next(
        button for button in app.button if button.label == "이 프로그램 PDF 원문 확인"
    )
    assert review_button.disabled
