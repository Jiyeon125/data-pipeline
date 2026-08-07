import inspect
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from fiscal_dashboard.app import (
    MAIN_TABS,
    _component_summary,
    _data_review_table,
    _multiple_reason_facts,
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
    assert simple.columns.tolist() == [
        "등급",
        "부처",
        "프로그램",
        "왜 확인하나",
        "핵심 근거",
        "안정성",
        "다음 확인",
        "본예산(억원·참고)",
    ]
    priority_2024 = data["priority_stability"]
    assert len(priority_2024) == 6
    assert int(priority_2024["threshold_stable_ab"].sum()) == 5
    assert int(priority_2024["exact_grade_stable"].sum()) == 2
    assert priority_2024.loc[
        priority_2024["threshold_boundary"], "performance_program_name"
    ].tolist() == ["소록도병원"]
    affected = program_queue.loc[
        program_queue["program_year_id"].isin(
            ["075:3800:2023", "075:4100:2023", "075:4000:2023"]
        )
    ]
    assert len(affected) == 3
    assert all(len(_multiple_reason_facts(row)) == 2 for _, row in affected.iterrows())
    assert simple["등급"].str.contains("우선 확인|원인 확인|맥락 확인|모니터링|데이터 보완").all()
    program_simple = _queue_simple_table(program_queue.loc[program_queue["fiscal_year"].eq(2024)])
    assert "회계" not in program_simple
    assert len(program_simple.columns) == 8
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
    assert app.segmented_control[0].value == "개요"
    # 기본값은 최신 공통연도 2024, 같은 프로그램은 한 행만 표시.
    assert [(metric.label, metric.value) for metric in app.metric[:5]] == [
        ("분석 프로그램", "77"),
        ("우선 확인 A+B", "6"),
        ("맥락 확인 C", "35"),
        ("데이터 보완 H", "8"),
        ("모니터링 D", "28"),
    ]
    rendered = " ".join(element.value for element in [*app.markdown, *app.info])
    assert "프로그램 **7.79%**" in rendered
    assert "본예산 **3.91%**" in rendered
    assert "본예산의 **81.84%**" in rendered
    assert app.multiselect[0].options == [
        "고용노동부",
        "보건복지부",
        "중소벤처기업부",
        "과학기술정보통신부",
    ]
    assert next(box for box in app.selectbox if box.label == "기준연도").value == 2024
    assert next(box for box in app.selectbox if box.label == "대기열 구분").value == "우선 확인 A+B"
    assert next(toggle for toggle in app.toggle if toggle.label == "검수자 모드").value is False
    assert "성과지표 원문 검수" not in " ".join(item.value for item in app.markdown)

    app.segmented_control[0].set_value("분석·검증").run()
    assert not app.exception
    metrics = {(metric.label, metric.value) for metric in app.metric}
    assert {("부합", "8건"), ("반박", "2건"), ("근거 부족", "2건")} <= metrics


def test_dashboard_queue_and_detail_information_architecture() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    app.segmented_control[0].set_value("점검 대기열").run()
    assert not app.exception
    table = app.dataframe[0].value
    assert table.columns.tolist() == [
        "등급",
        "부처",
        "프로그램",
        "왜 확인하나",
        "핵심 근거",
        "안정성",
        "다음 확인",
        "본예산(억원·참고)",
    ]
    assert table["안정성"].value_counts().to_dict() == {"임계값 안정": 5, "경계 사례": 1}
    assert len(table.columns) == 8
    rendered = table.to_string() + " " + " ".join(item.value for item in app.markdown)
    assert not any(
        code in rendered
        for code in ["UNKNOWN_TYPE", "PATTERN_CANDIDATE", "DISPLAY_ONLY", "context_flags"]
    )
    assert not any("원문(PDF) 검수" in button.label for button in app.button)

    app.segmented_control[0].set_value("프로그램 상세").run()
    assert not app.exception
    assert any("다음 확인" in (item.value or "") for item in app.info)
    assert any("**진단:**" in item.value for item in app.markdown)
    assert app.dataframe[0].value.columns.tolist() == [
        "회계유형",
        "본예산",
        "예산현액",
        "지출액",
        "집행률",
        "원시행 등급",
        "원시행 진단",
    ]
    detail_source = inspect.getsource(__import__("fiscal_dashboard.app", fromlist=["_render_program_year_detail"])._render_program_year_detail)
    assert detail_source.index('with st.expander("회계유형별 감사 데이터 보기"') < detail_source.index("st.dataframe(\n            account_view")


def test_dashboard_pdf_review_mode() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    next(toggle for toggle in app.toggle if toggle.label == "검수자 모드").set_value(True).run()

    assert not app.exception
    assert [title.value for title in app.title] == ["검수자 도구"]
    assert not app.segmented_control
    review_metric = next(metric for metric in app.metric if metric.label == "남은 검수")
    assert review_metric.value == "5"


def test_dashboard_mss_project_queue_without_false_pdf_link() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    app.multiselect[0].set_value(["102"]).run()
    app.segmented_control[0].set_value("점검 대기열").run()
    project_candidate = (
        load_dashboard_data(Path("."))["program_year_queue"]
        .loc[
            lambda frame: frame["ministry_code"].eq("102") & frame["fiscal_year"].eq(2024),
            "program_year_id",
        ]
        .iloc[0]
    )
    next(box for box in app.selectbox if box.label == "프로그램 선택").set_value(
        project_candidate
    ).run()
    app.segmented_control[0].set_value("프로그램 상세").run()

    assert not app.exception
    assert not any("원문(PDF) 검수" in button.label for button in app.button)

    app.segmented_control[0].set_value("점검 대기열").run()
    app.multiselect[0].set_value(["019", "075", "102", "162"]).run()
    next(box for box in app.selectbox if box.label == "대기열 구분").set_value(
        "데이터 보완 H"
    ).run()
    assert not app.exception
    hold_table = app.dataframe[0].value
    assert hold_table["등급"].eq("H 데이터 보완").all()
    assert not hold_table["등급"].str.contains("A |B |C |D ", regex=True).any()

    next(box for box in app.selectbox if box.label == "대기열 구분").set_value("전체").run()
    assert not app.exception
    assert len(app.dataframe) == 2
    assert not app.dataframe[0].value["등급"].eq("H 데이터 보완").any()
    assert app.dataframe[1].value["등급"].eq("H 데이터 보완").all()


def test_dashboard_analysis_validation_numbers_and_labels() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()
    app.segmented_control[0].set_value("분석·검증").run()

    assert not app.exception
    rendered = " ".join(
        str(element.value)
        for element in [*app.markdown, *app.info, *app.warning, *app.caption]
    )
    assert "성과 앵커형 질문형 점검등급" in rendered
    assert "93.78%~100.00%" in rendered
    assert "0.8824~1.0000" in rendered
    assert "소록도병원" in rendered
    assert "77 → 6, 7.79%" in rendered
    assert "1,080 → 74, 6.85%" in rendered
    assert "예측 성능이 아니라" in rendered
    assert "472개 지표행" in rendered
    assert "독립 검토자를 추가 확보하지 못해" in rendered
    assert [(metric.label, metric.value) for metric in app.metric[:4]] == [
        ("기준 재현", "236/236"),
        ("계약검사 실패", "0"),
        ("대기순서 지배관계 위반", "0"),
        ("A↔D 극단 이동", "0"),
    ]
    assert all(
        code not in rendered
        for code in [
            "PRIORITY_REVIEW",
            "reported_performance",
            "budget_performance_mismatch",
            "NEXT_YEAR_AB",
        ]
    )


@pytest.mark.parametrize(
    ("grade", "diagnostic_type", "queue_filter"),
    [
        ("A", None, "우선 확인 A+B"),
        ("B", None, "우선 확인 A+B"),
        ("C", "LOW_EXECUTION_TARGET_MET", "맥락 확인 C"),
        ("D", None, "모니터링 D"),
        ("H", None, "데이터 보완 H"),
    ],
)
def test_dashboard_2024_representative_grade_detail(
    grade: str,
    diagnostic_type: str | None,
    queue_filter: str,
) -> None:
    queue = load_dashboard_data(Path("."))["program_year_queue"]
    cases = queue.loc[queue["fiscal_year"].eq(2024) & queue["review_grade"].eq(grade)]
    if diagnostic_type:
        cases = cases.loc[cases["diagnostic_type"].eq(diagnostic_type)]
    assert not cases.empty
    row = cases.sort_values("program_year_id").iloc[0]

    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()
    assert not app.exception
    next(box for box in app.selectbox if box.key == "queue_filter").set_value(queue_filter).run()
    next(control for control in app.segmented_control if control.key == "main_tab").set_value(
        "점검 대기열"
    ).run()
    assert not app.exception
    table = app.dataframe[0].value
    assert row["performance_program_name"] in table["프로그램"].tolist()
    assert "핵심 근거" in table.columns
    if grade == "H":
        assert table["등급"].eq("H 데이터 보완").all()

    next(box for box in app.selectbox if box.key == "selected_program_year").set_value(
        row["program_year_id"]
    ).run()
    next(control for control in app.segmented_control if control.key == "main_tab").set_value(
        "프로그램 상세"
    ).run()
    assert not app.exception

    rendered = " ".join(
        str(element.value)
        for element in [*app.markdown, *app.info, *app.caption, *app.warning, *app.get("badge")]
    )
    assert grade in rendered
    assert "**진단:**" in rendered
    assert "다음 확인" in rendered
    assert "연도별 관측" in rendered
    assert str(row["diagnostic_type"]) not in rendered
    assert str(row["context_type"]) not in rendered
    assert not any(
        code in rendered
        for code in ["UNKNOWN_TYPE", "PATTERN_CANDIDATE", "DISPLAY_ONLY", "context_flags"]
    )
    assert app.dataframe[0].value.columns.tolist() == [
        "회계유형",
        "본예산",
        "예산현액",
        "지출액",
        "집행률",
        "원시행 등급",
        "원시행 진단",
    ]
    detail_source = inspect.getsource(
        __import__(
            "fiscal_dashboard.app", fromlist=["_render_program_year_detail"]
        )._render_program_year_detail
    )
    assert detail_source.index(
        'with st.expander("회계유형별 감사 데이터 보기"'
    ) < detail_source.index("st.dataframe(\n            account_view")
