from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from fiscal_dashboard.app import (
    MAIN_TABS,
    _component_summary,
    _data_review_table,
    _program_count,
    _queue_simple_table,
    _review_worklist,
    filter_candidates,
    load_dashboard_data,
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
    assert len(filtered) == 208
    assert _program_count(candidates) == 79
    assert filtered["scenario_ranking_eligible"].all()
    assert data["scores"].shape[0] == 832
    assert data["drilldown"].shape[0] == 74
    assert not data["drilldown"]["project_performance_attributed"].any()
    assert data["work_queue"].shape[0] == 412
    assert data["work_queue"]["work_lane"].value_counts().to_dict() == {
        "MONITOR": 130,
        "SINGLE_REVIEW": 102,
        "CONTEXT_REVIEW": 87,
        "REPEATED_OR_MULTIPLE": 76,
        "DATA_FIRST": 15,
        "STRONG_SINGLE": 2,
    }
    assert data["work_queue"]["review_grade"].value_counts().to_dict() == {
        "C": 211,
        "D": 130,
        "B": 34,
        "A": 22,
        "H": 15,
    }
    program_queue = data["program_year_queue"]
    assert program_queue.shape[0] == 236
    assert program_queue["program_year_id"].is_unique
    assert program_queue["fiscal_year"].value_counts().sort_index().to_dict() == {
        2022: 79,
        2023: 80,
        2024: 77,
    }
    assert program_queue["review_grade"].value_counts().to_dict() == {
        "C": 90,
        "D": 89,
        "H": 27,
        "A": 16,
        "B": 14,
    }
    assert int(program_queue["base_key_reused"].sum()) == 51
    assert int(program_queue["identity_resolved_by_extended_key"].sum()) == 37
    assert int(program_queue["identity_unresolved"].sum()) == 16
    assert (
        not program_queue.loc[program_queue["identity_resolved_by_extended_key"], "review_grade"]
        .eq("H")
        .any()
    )
    assert program_queue.loc[program_queue["context_only"], "review_grade"].eq("D").all()
    assert int(program_queue["context_only"].sum()) == 56
    assert not program_queue.duplicated(["fiscal_year", "program_year_id"]).any()
    assert (
        program_queue.loc[program_queue["fiscal_year"].eq(2024)]
        .nsmallest(5, "review_queue_order_within_year")["program_year_id"]
        .nunique()
        == 5
    )
    program_summary = data["summary"]["program_year_review_queue"]
    assert program_summary["program_year_amount_diff_counts"] == {
        "program_original_budget": 0,
        "program_current_budget": 0,
        "program_expenditure": 0,
    }
    assert program_summary["low_execution_target_met"] == {
        "raw_account_row_count": 40,
        "unique_program_year_count": 38,
        "unique_program_count": 29,
        "program_year_c_grade_count": 14,
    }
    low_execution_target_met_ids = set(
        program_queue.loc[
            program_queue["diagnostic_type"].eq("LOW_EXECUTION_TARGET_MET")
            & program_queue["review_grade"].eq("C"),
            "program_year_id",
        ]
    )
    assert {
        "019:1000:2022",
        "019:3000:2022",
        "075:3900:2022",
        "075:3900:2023",
        "075:4500:2023",
        "019:1000:2024",
        "075:1800:2024",
        "075:1900:2024",
        "075:3700:2024",
        "075:3800:2024",
        "075:3900:2024",
        "075:4000:2024",
    }.issubset(low_execution_target_met_ids)
    assert program_summary["preferred_key_conflict_group_count"] == 24
    assert program_summary["unique_program_count"] == 80
    assert program_summary["program_identity_count_including_unknown_continuity"] == 84
    assert program_summary["unknown_continuity_program_year_count"] == 4
    assert data["work_queue"]["program_total_feedback_complete_t1"].sum() == 72
    assert data["work_queue"]["program_total_feedback_complete_t2"].sum() == 34
    assert data["work_queue"]["continuous_project_feedback_complete_t1"].sum() == 108
    assert data["work_queue"]["continuous_project_feedback_complete_t2"].sum() == 42
    assert data["work_queue"]["program_total_account_type_mismatch_t1"].sum() == 3
    assert data["work_queue"]["account_type"].eq("FUND").sum() == 131
    assert data["summary"]["review_workbench_method"]["weighted_sum_used"] is False
    assert data["summary"]["review_workbench_method"]["t1_t2_kept_separate"] is True
    assert (
        data["summary"]["review_workbench_method"]["t1_t2_excluded_from_current_review_intensity"]
        is True
    )
    assert (
        data["summary"]["review_workbench_method"]["partial_signal_score_used_in_work_queue"]
        is False
    )
    assert data["summary"]["review_workbench_method"]["signal_score_used_in_work_queue"] is True
    assert (
        data["summary"]["review_workbench_method"]["signal_score_used_in_default_grade_queue"]
        is False
    )
    assert data["summary"]["analysis_time_basis"] == (
        "ANNUAL_RETROSPECTIVE_AFTER_REQUIRED_SOURCE_RELEASES"
    )
    assert data["summary"]["output_schema_version"] == (
        "priority_review_outputs_v5_identity_context_resolution"
    )
    assert data["summary"]["real_time_or_historical_information_set_reconstructed"] is False
    assert data["summary"]["feedback_linkage"] == {
        "eligible_rows": 2896,
        "matched_rows": 2893,
        "unmatched_base_project_rows": 3,
    }
    assert data["work_queue"]["safety_conclusion"].eq("NOT_ASSESSED").all()
    grade_summary = data["summary"]["question_review_grade"]
    assert sum(grade_summary["grade_counts_all_412"].values()) == 412
    assert "H" not in grade_summary["grade_counts_reviewable_a_to_d"]
    assert grade_summary["t1_t2_used_in_review_grade"] is False
    threshold_qa = pd.read_csv(
        Path("data/analytics/multi_ministry_priority_scenarios/question_review_threshold_qa.csv")
    )
    production = threshold_qa.loc[threshold_qa["qa_variant"].eq("production_threshold")]
    assert production["baseline_review_grade"].eq(production["qa_review_grade"]).all()
    blind = pd.read_csv(
        Path("data/analytics/multi_ministry_priority_scenarios/question_review_blind_pairs.csv")
    )
    assert blind["pair_id"].nunique() == 10
    assert "review_grade" not in blind
    simple = _queue_simple_table(data["work_queue"])
    assert simple.columns.tolist()[3:9] == [
        "점검등급",
        "주 진단",
        "핵심 근거",
        "다음 확인질문",
        "사업특성 상태",
        "근거강도",
    ]
    assert simple["점검등급"].str.contains("검토순서|판단 보류").all()
    program_simple = _queue_simple_table(program_queue.loc[program_queue["fiscal_year"].eq(2024)])
    assert "회계" not in program_simple
    assert "관측기간" in program_simple
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
    assert len(no_trigger) == 130
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
    # 기본값은 최신 공통연도 2024, 같은 프로그램은 한 행만 표시.
    assert [(metric.label, metric.value) for metric in app.metric[:4]] == [
        ("선택연도 고유 프로그램", "77"),
        ("검토순서 A", "4"),
        ("H 판단 보류", "8"),
        ("현재 표 프로그램", "49"),
    ]
    assert app.multiselect[0].options == [
        "고용노동부",
        "보건복지부",
        "중소벤처기업부",
        "과학기술정보통신부",
    ]
    assert next(box for box in app.selectbox if box.label == "기준연도").value == 2024


def test_dashboard_open_card_and_pdf_review_navigation() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    open_card = next(button for button in app.button if button.label == "선택한 프로그램 상세 열기")
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
    assert review_metric.value == "5"


def test_dashboard_mss_project_queue_without_false_pdf_link() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    app.multiselect[0].set_value(["102"]).run()
    app.segmented_control[0].set_value("사업 카드").run()
    project_candidate = (
        load_dashboard_data(Path("."))["program_year_queue"]
        .loc[
            lambda frame: frame["ministry_code"].eq("102") & frame["fiscal_year"].eq(2024),
            "program_year_id",
        ]
        .iloc[0]
    )
    app.selectbox[0].set_value(project_candidate).run()

    assert not app.exception
    review_button = next(
        button for button in app.button if button.label == "이 프로그램 원문(PDF) 검수로 이동"
    )
    assert review_button.disabled
