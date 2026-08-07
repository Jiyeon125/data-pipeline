import hashlib
import inspect
import json
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from fiscal_dashboard.app import (
    MAIN_TABS,
    DashboardDataError,
    _component_summary,
    _data_hold_table,
    _data_review_table,
    _multiple_reason_facts,
    _program_count,
    _program_year_project_rows,
    _project_table_view,
    _queue_simple_table,
    _review_worklist,
    filter_candidates,
    load_dashboard_data,
    review_page_specs,
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
    assert {
        "candidates",
        "scores",
        "stability",
        "drilldown",
        "review_queue",
        "spearman",
        "overlap",
        "case_review",
        "case_indicators",
        "case_projects",
        "case_t1_direction",
    }.isdisjoint(data)
    assert len(filtered) == 208
    assert _program_count(candidates) == 79
    assert filtered["scenario_ranking_eligible"].all()
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
        "프로그램",
        "부처",
        "왜 확인하나요?",
        "핵심 근거",
        "확인할 자료",
        "다음 질문",
        "본예산(참고)",
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
    program_simple = _queue_simple_table(program_queue.loc[program_queue["fiscal_year"].eq(2024)])
    assert "회계" not in program_simple
    assert len(program_simple.columns) == 7
    hold_simple = _data_hold_table(
        program_queue.loc[
            program_queue["fiscal_year"].eq(2024) & program_queue["review_grade"].eq("H")
        ]
    )
    assert hold_simple.columns.tolist() == [
        "프로그램",
        "부처",
        "왜 아직 판단할 수 없나요?",
        "필요한 자료",
        "다음 조치",
        "본예산(참고)",
    ]
    assert data["project_queue"].shape[0] == 3286
    assert data["project_queue"]["candidate_id"].nunique() == 397
    assert not data["project_queue"]["project_performance_attributed"].any()
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


def test_program_year_project_linkage_and_amount_contract() -> None:
    data = load_dashboard_data(Path("."))
    queue = data["program_year_queue"]
    account_queue = data["work_queue"]
    project_queue = data["project_queue"]
    project_candidate_ids = set(project_queue["candidate_id"])
    row = next(
        row
        for _, row in queue.loc[queue["fiscal_year"].eq(2024)].iterrows()
        if len(json.loads(row["raw_candidate_ids"])) > 1
        and set(json.loads(row["raw_candidate_ids"])) <= project_candidate_ids
    )

    projects = _program_year_project_rows(row, account_queue, project_queue)
    expected_ids = set(json.loads(row["raw_candidate_ids"]))
    assert set(projects["candidate_id"]) == expected_ids
    assert not projects.duplicated(["candidate_id", "project_id"]).any()
    assert projects["candidate_id"].isin(expected_ids).all()
    account_types = account_queue.set_index("candidate_id")["account_type"]
    assert projects["account_type"].eq(projects["candidate_id"].map(account_types)).all()

    for project_column, account_column in (
        ("project_original_budget", "account_original_budget"),
        ("project_current_budget", "account_current_budget"),
        ("project_expenditure", "account_settlement_expenditure"),
    ):
        actual = projects.groupby("candidate_id")[project_column].sum()
        expected = pd.to_numeric(account_queue.set_index("candidate_id")[account_column])
        pd.testing.assert_series_equal(
            actual.sort_index(),
            expected.loc[actual.index].sort_index(),
            check_names=False,
            check_dtype=False,
        )

    table = _project_table_view(projects)
    assert set(table["회계유형"]) <= {
        "일반회계",
        "특별회계",
        "책임운영기관특별회계",
        "기금",
    }
    assert not table["세부사업 재정신호"].str.contains("[A-Z]_", regex=True).any()


def test_program_year_project_linkage_rejects_performance_attribution() -> None:
    data = load_dashboard_data(Path("."))
    row = data["program_year_queue"].loc[
        data["program_year_queue"]["program_year_id"].eq("075:3300:2024")
    ].iloc[0]
    project_queue = data["project_queue"].copy()
    candidate_id = json.loads(row["raw_candidate_ids"])[0]
    project_queue.loc[
        project_queue["candidate_id"].eq(candidate_id), "project_performance_attributed"
    ] = True

    with pytest.raises(DashboardDataError, match="세부사업 성과로 귀속"):
        _program_year_project_rows(row, data["work_queue"], project_queue)


def test_production_queue_checksum_is_unchanged() -> None:
    path = Path(
        "data/analytics/multi_ministry_priority_scenarios/program_year_review_queue.csv"
    )
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "d7c59cc14da21f0e669f2e09867766100957ddad68f8600b43d64392c6236a96"
    )


def test_dashboard_default_render() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    assert not app.exception
    assert [title.value for title in app.title] == ["2024년, 어떤 프로그램부터 확인해야 할까요?"]
    assert app.segmented_control[0].options == list(MAIN_TABS)
    assert app.segmented_control[0].value == "개요"
    card_labels = {button.label for button in app.button}
    assert {
        "먼저 확인할 프로그램 — 6개",
        "맥락을 확인할 프로그램 — 35개",
        "데이터 확인이 먼저 필요한 프로그램 — 8개",
        "모니터링할 프로그램 — 28개",
    } <= card_labels
    rendered = " ".join(
        str(element.value) for element in [*app.markdown, *app.info, *app.caption]
    )
    assert "77개 프로그램의 성과·집행·예산 정보를 검토해" in rendered
    assert "먼저 확인할 프로그램 목록을 확인합니다." in rendered
    assert "프로그램을 눌러 선정 이유와 근거를 확인합니다." in rendered
    assert "성과보고서·예산·집행 원문을 확인합니다." in rendered
    assert "보고목표 미달이 반복되거나 집행·예산 신호가 함께 관측됐습니다." in rendered
    assert "프로그램 식별이나 성과 비교에 필요한 자료가 부족합니다." in rendered
    assert "정상·안전 판정은 아닙니다." in rendered
    assert "전체의 7.79%" in rendered
    assert "본예산의 3.91%" in rendered
    assert "본예산의 81.84%" in rendered
    assert app.multiselect[0].options == [
        "고용노동부",
        "보건복지부",
        "중소벤처기업부",
        "과학기술정보통신부",
    ]
    assert next(box for box in app.selectbox if box.label == "기준연도").value == 2024
    work_filter = next(box for box in app.selectbox if box.label == "업무구분")
    assert work_filter.value == "먼저 확인할 프로그램"
    assert work_filter.options == [
        "먼저 확인할 프로그램",
        "맥락을 확인할 프로그램",
        "데이터 확인이 먼저 필요한 프로그램",
        "모니터링할 프로그램",
        "전체",
    ]
    assert next(field for field in app.text_input if field.label == "프로그램명 검색").value == ""
    assert any(button.label == "필터 초기화" for button in app.button)
    internal_view = next(box for box in app.selectbox if box.label == "내부 화면")
    assert internal_view.value == "사용자 화면"
    assert internal_view.options == ["사용자 화면", "분석·검증", "PDF 원문 검수"]
    assert "분석·검증" not in app.segmented_control[0].options
    assert "성과지표 원문 검수" not in " ".join(item.value for item in app.markdown)
    default_screen = rendered + " " + " ".join(card_labels)
    assert "A+B" not in default_screen
    assert not any(label in default_screen for label in ["A 우선 확인", "B 원인 확인", "C 맥락 확인", "D 모니터링", "H 데이터 보완"])

    next(box for box in app.selectbox if box.label == "내부 화면").set_value("분석·검증").run()
    assert not app.exception
    metrics = {(metric.label, metric.value) for metric in app.metric}
    assert {("부합", "8건"), ("반박", "2건"), ("근거 부족", "2건")} <= metrics


@pytest.mark.parametrize(
    ("card_label", "work_group", "expected_count"),
    [
        ("먼저 확인할 프로그램 — 6개", "먼저 확인할 프로그램", 6),
        ("맥락을 확인할 프로그램 — 35개", "맥락을 확인할 프로그램", 35),
        (
            "데이터 확인이 먼저 필요한 프로그램 — 8개",
            "데이터 확인이 먼저 필요한 프로그램",
            8,
        ),
        ("모니터링할 프로그램 — 28개", "모니터링할 프로그램", 28),
    ],
)
def test_dashboard_overview_cards_open_work_groups(
    card_label: str, work_group: str, expected_count: int
) -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()
    next(button for button in app.button if button.label == card_label).click().run()

    assert not app.exception
    assert next(control for control in app.segmented_control if control.key == "main_tab").value == (
        "점검 대기열"
    )
    assert next(box for box in app.selectbox if box.key == "queue_filter").value == work_group
    assert len(app.dataframe[0].value) == expected_count


def test_dashboard_plain_language_usability_tasks() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()
    overview_text = " ".join(str(item.value) for item in [*app.markdown, *app.caption])

    # 1, 5: 개수와 데이터 부족·모니터링의 차이를 등급 지식 없이 확인합니다.
    assert any(button.label == "먼저 확인할 프로그램 — 6개" for button in app.button)
    assert "프로그램 식별이나 성과 비교에 필요한 자료가 부족합니다." in overview_text
    assert "정상·안전 판정은 아닙니다." in overview_text

    # 2~4: 이유, 열어야 할 자료, 원문 질문을 같은 대기열 행에서 확인합니다.
    next(button for button in app.button if button.label == "먼저 확인할 프로그램 — 6개").click().run()
    queue = app.dataframe[0].value
    assert queue["왜 확인하나요?"].str.endswith(".").all()
    assert queue["확인할 자료"].str.len().gt(0).all()
    assert queue["다음 질문"].str.endswith("?").all()

    # 6: 이름 검색은 내부 코드 없이 프로그램을 한 건으로 좁힙니다.
    next(field for field in app.text_input if field.key == "program_search").set_value(
        "직업능력개발"
    ).run()
    assert app.dataframe[0].value["프로그램"].tolist() == ["직업능력개발"]

    # 7: 필터 초기화는 기본 업무구분·전체 부처·빈 검색어로 복원합니다.
    next(button for button in app.button if button.label == "필터 초기화").click().run()
    assert next(box for box in app.selectbox if box.key == "queue_filter").value == (
        "먼저 확인할 프로그램"
    )
    assert next(field for field in app.text_input if field.key == "program_search").value == ""
    assert set(app.multiselect[0].value) == {"019", "075", "102", "162"}


def test_dashboard_queue_and_detail_information_architecture() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    app.segmented_control[0].set_value("점검 대기열").run()
    assert not app.exception
    table = app.dataframe[0].value
    assert table.columns.tolist() == [
        "프로그램",
        "부처",
        "왜 확인하나요?",
        "핵심 근거",
        "확인할 자료",
        "다음 질문",
        "본예산(참고)",
    ]
    assert len(table) == 6
    assert table["확인할 자료"].str.contains("성과보고서").all()
    rendered = table.to_string() + " " + " ".join(item.value for item in app.markdown)
    assert not any(
        code in rendered
        for code in ["UNKNOWN_TYPE", "PATTERN_CANDIDATE", "DISPLAY_ONLY", "context_flags"]
    )
    assert not any("원문(PDF) 검수" in button.label for button in app.button)

    app.segmented_control[0].set_value("프로그램 상세").run()
    assert not app.exception
    assert any("다음 확인질문" in (item.value or "") for item in app.info)
    detail_rendered = " ".join(
        str(element.value)
        for element in [*app.markdown, *app.info, *app.warning, *app.caption, *app.get("badge")]
    )
    assert "왜 확인하나요?" in detail_rendered
    assert "확인할 자료" in detail_rendered
    assert "판단 시 주의" in detail_rendered
    assert "세부사업에서 원인 보기" in detail_rendered
    assert "개별 성과로 귀속하지 않습니다" in detail_rendered
    assert not any(label in detail_rendered for label in ["A 우선 확인", "B 원인 확인", "C 맥락 확인", "D 모니터링", "H 데이터 보완"])
    account_table = next(
        frame.value
        for frame in app.dataframe
        if frame.value.columns.tolist()
        == [
            "회계유형",
            "본예산",
            "예산현액",
            "지출액",
            "집행률",
        ]
    )
    assert account_table.columns.tolist() == [
        "회계유형",
        "본예산",
        "예산현액",
        "지출액",
        "집행률",
    ]
    detail_source = inspect.getsource(__import__("fiscal_dashboard.app", fromlist=["_render_program_year_detail"])._render_program_year_detail)
    assert detail_source.index('st.markdown("#### 연도별 관측")') < detail_source.index(
        'st.markdown("#### 세부사업에서 원인 보기")'
    )
    assert detail_source.index('st.markdown("#### 세부사업에서 원인 보기")') < detail_source.index(
        'with st.expander("회계유형별 감사자료 보기"'
    )
    assert detail_source.index('with st.expander("회계유형별 감사자료 보기"') < detail_source.index("st.dataframe(\n            account_view")


def test_dashboard_pdf_review_mode() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()

    next(box for box in app.selectbox if box.label == "내부 화면").set_value(
        "PDF 원문 검수"
    ).run()

    assert not app.exception
    assert [title.value for title in app.title] == ["검수자 도구"]
    assert not app.segmented_control
    review_metric = next(metric for metric in app.metric if metric.label == "남은 검수")
    assert review_metric.value == "5"


def test_program_detail_opens_pdf_review_with_program_focus() -> None:
    row = (
        load_dashboard_data(Path("."))["program_year_queue"]
        .loc[lambda frame: frame["program_year_id"].eq("075:3300:2024")]
        .iloc[0]
    )
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()
    next(control for control in app.segmented_control if control.key == "main_tab").set_value(
        "점검 대기열"
    ).run()
    next(option for option in app.radio if option.key == "selected_program_year").set_value(
        row["program_year_id"]
    ).run()
    next(control for control in app.segmented_control if control.key == "main_tab").set_value(
        "프로그램 상세"
    ).run()

    next(
        button
        for button in app.button
        if button.label == "이 프로그램 성과계획서·성과보고서 원문 검수로 이동"
    ).click().run()

    assert not app.exception
    assert next(box for box in app.selectbox if box.label == "내부 화면").value == (
        "PDF 원문 검수"
    )
    assert [title.value for title in app.title] == ["검수자 도구"]
    assert any(row["performance_program_name"] in str(item.value) for item in app.info)


def test_program_detail_explains_when_no_project_rows_are_linked() -> None:
    data = load_dashboard_data(Path("."))
    project_candidate_ids = set(data["project_queue"]["candidate_id"])
    row = next(
        row
        for _, row in data["program_year_queue"].iterrows()
        if set(json.loads(row["raw_candidate_ids"])).isdisjoint(project_candidate_ids)
    )
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()
    next(box for box in app.selectbox if box.key == "global_year").set_value(
        int(row["fiscal_year"])
    ).run()
    next(box for box in app.selectbox if box.key == "queue_filter").set_value(
        "데이터 확인이 먼저 필요한 프로그램"
    ).run()
    next(control for control in app.segmented_control if control.key == "main_tab").set_value(
        "점검 대기열"
    ).run()
    next(option for option in app.radio if option.key == "selected_program_year").set_value(
        row["program_year_id"]
    ).run()
    next(control for control in app.segmented_control if control.key == "main_tab").set_value(
        "프로그램 상세"
    ).run()

    assert not app.exception
    assert any(
        "명시적 candidate_id로 연결된 세부사업 집행행이 없습니다" in str(item.value)
        for item in app.caption
    )


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
    next(option for option in app.radio if option.label == "프로그램 선택").set_value(
        project_candidate
    ).run()
    app.segmented_control[0].set_value("프로그램 상세").run()

    assert not app.exception
    pdf_button = next(
        button
        for button in app.button
        if button.label == "이 프로그램 성과계획서·성과보고서 원문 검수로 이동"
    )
    assert pdf_button.disabled
    assert any(
        "현재 PDF 원문 검수 큐에 연결되어 있지 않습니다" in str(item.value)
        for item in app.caption
    )

    app.segmented_control[0].set_value("점검 대기열").run()
    app.multiselect[0].set_value(["019", "075", "102", "162"]).run()
    next(box for box in app.selectbox if box.label == "업무구분").set_value(
        "데이터 확인이 먼저 필요한 프로그램"
    ).run()
    assert not app.exception
    hold_table = app.dataframe[0].value
    assert hold_table.columns.tolist() == [
        "프로그램",
        "부처",
        "왜 아직 판단할 수 없나요?",
        "필요한 자료",
        "다음 조치",
        "본예산(참고)",
    ]
    assert hold_table["필요한 자료"].str.contains("프로그램 식별자료").all()

    next(box for box in app.selectbox if box.label == "업무구분").set_value("전체").run()
    assert not app.exception
    assert len(app.dataframe) == 2
    assert "왜 확인하나요?" in app.dataframe[0].value
    assert "왜 아직 판단할 수 없나요?" in app.dataframe[1].value


def test_dashboard_analysis_validation_numbers_and_labels() -> None:
    app = AppTest.from_file("src/fiscal_dashboard/app.py", default_timeout=30).run()
    next(box for box in app.selectbox if box.label == "내부 화면").set_value("분석·검증").run()

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
    assert app.dataframe[0].value.to_dict("records") == [
        {"사용자 업무구분": "먼저 확인할 프로그램", "내부 판정코드": "A·B"},
        {"사용자 업무구분": "맥락을 확인할 프로그램", "내부 판정코드": "C"},
        {"사용자 업무구분": "데이터 확인이 먼저 필요한 프로그램", "내부 판정코드": "H"},
        {"사용자 업무구분": "모니터링할 프로그램", "내부 판정코드": "D"},
    ]
    assert "사용자에게 요구되는 지식이 아닙니다" in rendered
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
        ("A", None, "먼저 확인할 프로그램"),
        ("B", None, "먼저 확인할 프로그램"),
        ("C", "LOW_EXECUTION_TARGET_MET", "맥락을 확인할 프로그램"),
        ("D", None, "모니터링할 프로그램"),
        ("H", None, "데이터 확인이 먼저 필요한 프로그램"),
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
    assert "다음 질문" in table.columns or "다음 조치" in table.columns
    if grade == "H":
        assert "왜 아직 판단할 수 없나요?" in table.columns

    next(option for option in app.radio if option.key == "selected_program_year").set_value(
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
    assert "왜 확인하나요?" in rendered
    assert "다음 확인질문" in rendered
    assert "확인할 자료" in rendered
    assert "연도별 관측" in rendered
    assert "세부사업에서 원인 보기" in rendered
    assert "개별 성과로 귀속하지 않습니다" in rendered
    assert str(row["diagnostic_type"]) not in rendered
    assert str(row["context_type"]) not in rendered
    assert not any(
        code in rendered
        for code in ["UNKNOWN_TYPE", "PATTERN_CANDIDATE", "DISPLAY_ONLY", "context_flags"]
    )
    project_table = next(
        frame.value for frame in app.dataframe if "세부사업 재정신호" in frame.value.columns
    )
    assert len(project_table) <= 8
    assert project_table.columns.tolist() == [
        "회계유형",
        "검토유형",
        "세부사업",
        "단위사업",
        "본예산(억원)",
        "예산현액(억원)",
        "지출액(억원)",
        "집행률",
        "잔액(억원)",
        "이월(억원)",
        "불용(억원)",
        "프로그램 내 예산비중",
        "프로그램 내 잔액기여",
        "세부사업 재정신호",
    ]
    account_table = next(
        frame.value
        for frame in app.dataframe
        if frame.value.columns.tolist()
        == [
            "회계유형",
            "본예산",
            "예산현액",
            "지출액",
            "집행률",
        ]
    )
    assert account_table.columns.tolist() == [
        "회계유형",
        "본예산",
        "예산현액",
        "지출액",
        "집행률",
    ]
    detail_source = inspect.getsource(
        __import__(
            "fiscal_dashboard.app", fromlist=["_render_program_year_detail"]
        )._render_program_year_detail
    )
    assert detail_source.index(
        'with st.expander("회계유형별 감사자료 보기"'
    ) < detail_source.index("st.dataframe(\n            account_view")
