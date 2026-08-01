from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF
import pandas as pd
import pytest

from performance_pipeline import pdf_reconciliation as pr

# ---------------------------------------------------------------------------
# 순수 함수 단위 테스트 (수기 예제 vs 기대값)
# ---------------------------------------------------------------------------


def test_normalize_indicator_name_strips_circled_digit_before_nfkc() -> None:
    """NFKC 정규화가 원문자 숫자(①→1)를 먼저 분해해 제거 정규식을 무력화하는
    회귀 버그를 재발하지 않는지 확인합니다."""
    raw = "중소기업지원사업 \n만\n①\n족도\n"
    assert pr.normalize_indicator_name(raw) == "중소기업지원사업만족도"
    assert pr.normalize_indicator_name(
        "혁신바우처 지원업체 매출액 증가율"
    ) == pr.normalize_indicator_name("②혁신바우처 지원업체 매출액 증가율")


def test_normalize_indicator_name_removes_punctuation_and_whitespace() -> None:
    assert pr.normalize_indicator_name("중소기업 지원사업 만족도(점)") == "중소기업지원사업만족도점"
    assert pr.normalize_indicator_name(None) == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("4.11", 4.11),
        ("(4.11)", 4.11),  # 성과지표 표에서는 괄호가 음수가 아니라 강조/잠정치 표시
        ("-4.11", -4.11),
        ("△4.11", -4.11),
        ("1,234", 1234.0),
        ("72.1%", 72.1),
        ("-", None),
        ("신규", None),
        (None, None),
    ],
)
def test_parse_numeric_examples(raw: str | None, expected: float | None) -> None:
    result = pr.parse_numeric(raw)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_clean_direction_flags_polluted_value() -> None:
    clean, polluted = pr.clean_direction("상향66:57")
    assert clean == "상향66:57"
    assert polluted is True

    clean, polluted = pr.clean_direction("상향")
    assert clean == "상향"
    assert polluted is False

    clean, polluted = pr.clean_direction(None)
    assert clean is None
    assert polluted is False


def test_compute_achievement_rate_up_and_down_indicators() -> None:
    # 상향지표: 실적/목표*100
    assert pr.compute_achievement_rate("상향", 4.0, 4.11) == pytest.approx(102.75)
    # 하향지표: 목표/실적*100
    assert pr.compute_achievement_rate("하향", 2.5, 2.0) == pytest.approx(125.0)
    # 분모 0 또는 방향 불명은 None
    assert pr.compute_achievement_rate("상향", 0.0, 4.11) is None
    assert pr.compute_achievement_rate(None, 4.0, 4.11) is None
    assert pr.compute_achievement_rate("상향", None, 4.11) is None


def test_classify_numeric_match_statuses() -> None:
    assert pr.classify_numeric_match(72.1, 72.1) == "EXACT_MATCH"
    assert pr.classify_numeric_match(72.1, 75.5) == "VALUE_MISMATCH"
    assert pr.classify_numeric_match(None, None) == "NOT_APPLICABLE"
    assert pr.classify_numeric_match(None, 75.5) == "MANUAL_MISSING_PDF_PRESENT"
    assert pr.classify_numeric_match(72.1, None) == "PDF_MISSING_MANUAL_PRESENT"


def test_numeric_change_computes_absolute_and_relative_change() -> None:
    """왜 바뀌었는지는 판단하지 않고, 얼마나 바뀌었는지만 계산합니다."""
    change_abs, change_pct = pr.numeric_change(2.05, 27.7)
    assert change_abs == pytest.approx(25.65)
    assert change_pct == pytest.approx(1251.2195, rel=1e-4)

    # baseline이 0이면 절대 변화량은 계산되지만 상대 변화율은 정의되지 않음.
    change_abs, change_pct = pr.numeric_change(0.0, 5.0)
    assert change_abs == pytest.approx(5.0)
    assert change_pct is None

    # 둘 중 하나라도 없으면 둘 다 None.
    assert pr.numeric_change(None, 5.0) == (None, None)
    assert pr.numeric_change(5.0, None) == (None, None)


def test_classify_rate_match_rounding_vs_mismatch() -> None:
    assert pr.classify_rate_match(104.7, 104.7) == "EXACT_MATCH"
    assert pr.classify_rate_match(104.7, 104.75) == "ROUNDING_ONLY"
    assert pr.classify_rate_match(104.7, 110.0) == "VALUE_MISMATCH"
    assert pr.classify_rate_match(None, None) == "NOT_APPLICABLE"


# ---------------------------------------------------------------------------
# 표 라벨 앵커 추출: 한 줄에 두 연도 값이 붙는 실제 사례 회귀 테스트
# ---------------------------------------------------------------------------


def _make_report_pdf(path, page_text: str) -> None:
    # PyMuPDF 기본 폰트(helv)는 한글 글리프를 지원하지 않아 텍스트 추출 시
    # PUA 문자로 깨집니다. 내장 CJK 폰트(korea-s)를 명시해야 실제 PDF와
    # 동일하게 한글이 정상 추출됩니다.
    doc = fitz.open()
    # 별첨3~별첨4 구간 탐지를 위해 앞뒤 마커 페이지를 둡니다.
    doc.new_page().insert_text((72, 72), "별첨3 성과 달성도 현황", fontname="korea-s", fontsize=10)
    body = doc.new_page()
    body.insert_text((72, 72), page_text, fontname="korea-s", fontsize=10)
    doc.new_page().insert_text((72, 72), "별첨4 예결산 현황", fontname="korea-s", fontsize=10)
    doc.save(path)
    doc.close()


def test_extract_report_achievement_evidence_splits_merged_value_line(tmp_path) -> None:
    """ "100.0% 144.3%"처럼 한 줄에 두 값이 붙어도 다음 지표 이름을 흡수하지 않아야 합니다."""
    page_text = (
        "①규제자유특구 혁신사업육성 사업화 성공률(%)\n"
        "목표\n-\n-\n51.5\n"
        "실적\n-\n신규\n70.7\n"
        "달성률\n-\n100.0% 137.3%\n"
        "②다음지표 이름\n"
    )
    pdf_path = tmp_path / "report.pdf"
    _make_report_pdf(pdf_path, page_text)
    # PdfDocSpec.path는 APPENDIX_ROOT 기준 경로를 조합하므로, 임시 파일 경로를
    # 직접 가리키는 테스트용 스펙으로 우회합니다.
    spec_with_real_path = _SpecWithPath(pdf_path)
    result = pr.extract_report_achievement_evidence(
        spec_with_real_path, ["규제자유특구 혁신사업육성 사업화 성공률"]
    )
    assert "규제자유특구 혁신사업육성 사업화 성공률" in result
    ev = result["규제자유특구 혁신사업육성 사업화 성공률"]
    assert ev.target_values_raw == ["-", "-", "51.5"]
    assert ev.actual_values_raw == ["-", "신규", "70.7"]
    assert ev.rate_values_raw == ["-", "100.0%", "137.3%"]
    assert ev.rate_raw == "137.3%"


def test_full_report_table_skips_formula_label_and_reads_four_years() -> None:
    page_text = (
        "ICT융합 기반산업 시장 매출액\n"
        "'24년 성과 설명\n"
        "사물인터넷\n목표\n매출액(21.7조원)\n+ 블록체인 목표 매출액(0.35조원)\n"
        "'21년\n'22년\n'23년\n'24년\n"
        "목표\n16.07\n15.31\n21.6\n22\n"
        "실적\n16.78\n21.2\n25.5\n28.3\n"
        "달성률(%)\n104.4\n138.5\n118.1\n128.6\n"
    )

    result = pr._extract_text_achievement_evidence(
        [page_text],
        range(1),
        ["ICT융합 기반산업 시장 매출액"],
        source_file="report.pdf",
        source_page=lambda page: page,
        require_complete_values=True,
        extraction_method="FULL_TEXT",
    )

    evidence = result["ICT융합 기반산업 시장 매출액"]
    assert (evidence.target_raw, evidence.actual_raw, evidence.rate_raw) == (
        "22",
        "28.3",
        "128.6",
    )
    assert evidence.value_years == [2021, 2022, 2023, 2024]
    assert evidence.actual_for_year(2023) == "25.5"


def test_report_evidence_uses_pdf_program_goal_to_split_duplicate_names() -> None:
    pages = [
        "프로그램목표 : II-1 성장 지원\n프로그램A①공통지표\n'22년\n'23년\n'24년\n목표\n1\n2\n3\n실적\n4\n5\n6\n달성률\n400%\n250%\n200%",
        "프로그램목표 : III-1 창업 지원\n프로그램B\n①공통지표\n'22년\n'23년\n'24년\n목표\n10\n20\n30\n실적\n40\n50\n60\n달성률\n400%\n250%\n200%",
    ]

    result = pr._extract_text_achievement_evidence(
        pages,
        range(2),
        ["공통지표"],
        source_file="report.pdf",
        source_page=lambda page: page,
        require_complete_values=True,
        extraction_method="TEXT",
        candidate_program_goals={"공통지표": {"II-1", "III-1"}},
    )

    first = result[pr._contextual_evidence_key("공통지표", "II-1")]
    second = result[pr._contextual_evidence_key("공통지표", "III-1")]
    assert (first.program_name, first.actual_for_year(2024)) == ("프로그램A", "6")
    assert (second.program_name, second.actual_for_year(2024)) == ("프로그램B", "60")


def test_report_extraction_keeps_complete_appendix_context(monkeypatch) -> None:
    appendix = pr.AchievementEvidence(
        matched_name="지표",
        split_pdf_page=6,
        source_pdf_page=164,
        printed_page=None,
        source_text="별첨 근거",
        target_values_raw=["1"],
        actual_values_raw=["2"],
        rate_values_raw=["200"],
        source_file="split.pdf",
        program_goal_number="III-1",
        program_name="창업환경조성",
        value_years=[2024],
    )
    full = pr.AchievementEvidence(
        matched_name="지표",
        split_pdf_page=78,
        source_pdf_page=78,
        printed_page=None,
        source_text="전체본 근거",
        target_values_raw=["1"],
        actual_values_raw=["2"],
        rate_values_raw=["200"],
        extraction_method="FULL_TEXT",
        source_file="full.pdf",
        value_years=[2024],
    )
    monkeypatch.setattr(pr, "load_page_texts", lambda _path: ["별첨3"])
    monkeypatch.setattr(pr, "full_document_path", lambda _spec: Path("full.pdf"))
    monkeypatch.setattr(
        pr,
        "_extract_text_achievement_evidence",
        lambda *_args, extraction_method, **_kwargs: {
            "지표": full if extraction_method == "FULL_TEXT" else appendix
        },
    )

    result = pr.extract_report_achievement_evidence(
        pr.PdfDocSpec(2024, "report", "split.pdf", 159, 208), ["지표"]
    )

    assert result["지표"] is appendix


def test_discover_pdf_doc_specs_preserves_leading_zero_code(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(pr, "APPENDIX_ROOT", tmp_path)
    for year in (2022, 2023, 2024):
        root = tmp_path / f"year={year}" / "ministry_code=019"
        root.mkdir(parents=True)
        (root / f"{year}년도 성과계획서_고용노동부-10-19.pdf").touch()
        (root / f"{year}년도 성과보고서_고용노동부-20-29.pdf").touch()

    specs = pr.discover_pdf_doc_specs("19")

    assert len(specs) == 6
    assert {spec.ministry_code for spec in specs} == {"019"}
    assert {(spec.source_page_start, spec.source_page_end) for spec in specs} == {
        (10, 19),
        (20, 29),
    }


class _SpecWithPath:
    """PdfDocSpec과 동일한 인터페이스지만 임시 경로를 직접 가리키는 테스트용 스펙."""

    def __init__(self, path) -> None:
        self._path = path
        self.fiscal_year = 2099
        self.doc_type = "report"

    @property
    def path(self):
        return self._path

    def source_pdf_page(self, split_pdf_page: int) -> int:
        return split_pdf_page


# ---------------------------------------------------------------------------
# reconcile_row: 4개 필수 시나리오
# ---------------------------------------------------------------------------


def _base_row(**overrides) -> dict:
    row = {
        "source_indicator_id": "테스트-2024-I1-01",
        "ministry_name": "중소벤처기업부",
        "fiscal_year": 2024,
        "strategic_goal_number": "Ⅰ",
        "program_goal_number": "Ⅰ-1",
        "source_program_code": None,
        "performance_program_name": "테스트프로그램",
        "indicator_name_plan": "테스트지표",
        "indicator_name_report": "테스트지표",
        "indicator_unit": "%",
        "indicator_direction": "상향",
        "planned_target_raw": "10.0",
        "actual_value_raw": "11.0",
        "official_achievement_rate_raw": "110.0",
        "planned_target_numeric": 10.0,
        "actual_value_numeric": 11.0,
        "official_achievement_rate_numeric": 110.0,
    }
    row.update(overrides)
    return row


def _valid_pages() -> dict[int, tuple[int, int]]:
    plan_spec = pr.doc_spec(2024, "plan")
    report_spec = pr.doc_spec(2024, "report")
    return {
        "plan": {2024: (plan_spec.source_page_start, plan_spec.source_page_end)},
        "report": {2024: (report_spec.source_page_start, report_spec.source_page_end)},
    }


def test_reconcile_row_exact_match(monkeypatch) -> None:
    """시나리오 1: 계획서·보고서 원문이 수기값과 완전히 일치."""
    monkeypatch.setattr(pr, "find_change_evidence", lambda *a, **k: None)
    row = _base_row()
    plan_ev = pr.PlanEvidence(
        matched_name="테스트지표",
        split_pdf_page=1,
        source_pdf_page=188,
        printed_page=180,
        source_text="테스트지표 10.0",
        extraction_method="TEXT",
        numeric_candidates=[10.0],
    )
    report_ev = pr.AchievementEvidence(
        matched_name="테스트지표",
        split_pdf_page=4,
        source_pdf_page=162,
        printed_page=None,
        source_text="목표 10.0 실적 11.0 달성률 110.0%",
        target_values_raw=["10.0"],
        actual_values_raw=["11.0"],
        rate_values_raw=["110.0%"],
        extraction_method="TEXT",
    )
    pages = _valid_pages()
    result = pr.reconcile_row(
        row,
        plan_evidence_by_year={2024: {"테스트지표": plan_ev}},
        report_evidence_by_year={2024: {"테스트지표": report_ev}},
        plan_specs_valid_pages=pages["plan"],
        report_specs_valid_pages=pages["report"],
        report_has_pua_by_year={2024: False},
    )
    assert result["overall_reconciliation_status"] == "EXACT_MATCH"
    assert result["plan_target_match_status"] == "EXACT_MATCH"
    assert result["report_target_match_status"] == "EXACT_MATCH"
    assert result["report_actual_match_status"] == "EXACT_MATCH"
    assert result["report_achievement_rate_match_status"] == "EXACT_MATCH"
    assert result["planned_target_numeric_pdf"] == pytest.approx(10.0)
    # 계획서 목표(10.0)와 보고서 목표(10.0)가 같으므로 변경폭은 0.
    assert result["plan_vs_report_target_change_abs"] == pytest.approx(0.0)
    assert result["plan_vs_report_target_change_pct"] == pytest.approx(0.0)


def test_reconcile_row_marks_different_report_appendix_structure_for_review(
    monkeypatch,
) -> None:
    monkeypatch.setattr(pr, "find_change_evidence", lambda *a, **k: None)
    row = _base_row(ministry_name="과학기술정보통신부")
    specs = (
        pr.PdfDocSpec(2024, "plan", "plan.pdf", 1, 10, ministry_code="162"),
        pr.PdfDocSpec(2024, "report", "report.pdf", 11, 20, ministry_code="162"),
    )
    plan_ev = pr.PlanEvidence(
        matched_name="테스트지표",
        split_pdf_page=1,
        source_pdf_page=1,
        printed_page=None,
        source_text="테스트지표 10.0",
        extraction_method="TEXT",
        numeric_candidates=[10.0],
    )

    result = pr.reconcile_row(
        row,
        plan_evidence_by_year={2024: {"테스트지표": plan_ev}},
        report_evidence_by_year={2024: {}},
        plan_specs_valid_pages={2024: (1, 10)},
        report_specs_valid_pages={2024: (11, 20)},
        report_structure_review_by_year={2024: True},
        plan_image_only_by_year={2024: False},
        doc_specs=specs,
    )

    assert result["ministry_code"] == "162"
    assert result["report_name_match_status"] == "MANUAL_REVIEW"
    assert result["overall_reconciliation_status"] == "MANUAL_REVIEW"
    assert "REPORT_APPENDIX_STRUCTURE_REVIEW" in result["review_reason"]


def _make_change_table_pdf(path, body_text: str) -> None:
    """별첨6 "성과계획서 변경 사항" 표를 흉내 낸 합성 PDF를 만듭니다."""
    doc = fitz.open()
    doc.new_page().insert_text(
        (72, 72), "1. 프로그램 목표 수정 현황 별첨6", fontname="korea-s", fontsize=10
    )
    body = doc.new_page()
    body.insert_text((72, 72), body_text, fontname="korea-s", fontsize=10)
    doc.new_page().insert_text((72, 72), "별첨7 기타 참고자료", fontname="korea-s", fontsize=10)
    doc.save(path)
    doc.close()


def test_find_change_evidence_extracts_free_text_reason_without_brackets(tmp_path) -> None:
    """<괄호> 없는 자유 서술 사유도 다음 지표의 예산 숫자 줄 전까지만 모아야 합니다."""
    body_text = (
        "테스트지표\n"
        "0.4\n"
        "테스트지표\n"
        "0.4\n"
        "10.0\n"
        "20.0\n"
        "일반\n"
        "재정\n"
        "전년도 실적치 고려하여 목표 상향조정\n"
        "123,456\n"
        "다음지표\n"
    )
    pdf_path = tmp_path / "report_change_table.pdf"
    _make_change_table_pdf(pdf_path, body_text)
    spec = _SpecWithPath(pdf_path)

    evidence = pr.find_change_evidence(spec, "테스트지표")

    assert evidence is not None
    assert evidence.target_before_raw == "10.0"
    assert evidence.target_after_raw == "20.0"
    # 괄호 사유가 없으므로 자유 서술을 모으고, 다음 지표의 예산 숫자 줄
    # ("123,456")이 나오면 멈춰야 합니다(다음 행 텍스트를 흡수하지 않음).
    assert evidence.reason == "전년도 실적치 고려하여 목표 상향조정"
    assert "123,456" not in (evidence.reason or "")
    assert "다음지표" not in (evidence.reason or "")


def test_find_change_evidence_prefers_bracketed_reason_over_free_text(tmp_path) -> None:
    """<변경사항 없음>처럼 괄호 사유가 있으면 자유 서술 탐색을 하지 않습니다."""
    body_text = "테스트지표\n0.4\n테스트지표\n0.4\n4.2\n4.2\n일반\n재정\n<변경사항 없음>\n"
    pdf_path = tmp_path / "report_change_table_bracket.pdf"
    _make_change_table_pdf(pdf_path, body_text)
    spec = _SpecWithPath(pdf_path)

    evidence = pr.find_change_evidence(spec, "테스트지표")

    assert evidence is not None
    assert evidence.target_before_raw == "4.2"
    assert evidence.target_after_raw == "4.2"
    assert evidence.reason == "변경사항 없음"


def test_find_change_evidence_stops_at_split_informatization_category(tmp_path) -> None:
    body_text = (
        "테스트지표\n1\n테스트지표\n1\n77.2\n104.8\n"
        "정보\n화\n<'23년 실적치 확정에 따라 목표치 조정>\n"
        "13700\n13800\n다음지표\n"
    )
    pdf_path = tmp_path / "report_change_table_informatization.pdf"
    _make_change_table_pdf(pdf_path, body_text)

    evidence = pr.find_change_evidence(_SpecWithPath(pdf_path), "테스트지표")

    assert evidence is not None
    assert (evidence.target_before_raw, evidence.target_after_raw) == ("77.2", "104.8")


def test_reconcile_row_name_change_documented_in_change_table(monkeypatch) -> None:
    """시나리오 2: 계획서-보고서 지표명이 바뀌었지만 별첨6 변경사항표로 확인됨."""

    def fake_find_change_evidence(report_spec, indicator_name, **kwargs):
        return pr.ChangeEvidence(
            matched_name=indicator_name,
            window_text="변경 전후 근거",
            target_before_raw="9.0",
            target_after_raw="10.0",
            reason="지표명 변경",
            split_pdf_page=35,
            source_pdf_page=193,
            printed_page=None,
            source_text="변경 전후 근거",
        )

    monkeypatch.setattr(pr, "find_change_evidence", fake_find_change_evidence)
    row = _base_row(indicator_name_plan="이전지표명", indicator_name_report="새지표명")
    pages = _valid_pages()
    result = pr.reconcile_row(
        row,
        plan_evidence_by_year={2024: {}},
        report_evidence_by_year={2024: {}},
        plan_specs_valid_pages=pages["plan"],
        report_specs_valid_pages=pages["report"],
        report_has_pua_by_year={2024: False},
    )
    assert result["plan_name_match_status"] == "MATCH_AFTER_CHANGE"
    assert result["planned_target_numeric_pdf"] == pytest.approx(10.0)
    assert result["plan_source_pdf_page"] == 193
    assert "성과보고서" in result["plan_source_file"]
    assert result["documented_change_source_file"] == pr.doc_spec(2024, "report").filename
    assert result["page_evidence_status"] != "MANUAL_REVIEW"
    assert "PAGE_OUT_OF_RANGE" not in (result["review_reason"] or "")
    assert "PLAN_REPORT_NAME_CHANGE_DOCUMENTED_IN_별첨6" in (result["review_reason"] or "")


def test_reconcile_row_manual_missing_pdf_present(monkeypatch) -> None:
    """시나리오 3: 수기 실적치는 결측이나 PDF 원문에는 실적치가 존재."""
    monkeypatch.setattr(pr, "find_change_evidence", lambda *a, **k: None)
    row = _base_row(
        actual_value_raw=None,
        actual_value_numeric=None,
        official_achievement_rate_raw=None,
        official_achievement_rate_numeric=None,
    )
    plan_ev = pr.PlanEvidence(
        matched_name="테스트지표",
        split_pdf_page=1,
        source_pdf_page=188,
        printed_page=180,
        source_text="테스트지표 10.0",
        extraction_method="TEXT",
        numeric_candidates=[10.0],
    )
    report_ev = pr.AchievementEvidence(
        matched_name="테스트지표",
        split_pdf_page=4,
        source_pdf_page=162,
        printed_page=None,
        source_text="목표 10.0 실적 11.0 달성률 110.0%",
        target_values_raw=["10.0"],
        actual_values_raw=["11.0"],
        rate_values_raw=["110.0%"],
        extraction_method="TEXT",
    )
    pages = _valid_pages()
    result = pr.reconcile_row(
        row,
        plan_evidence_by_year={2024: {"테스트지표": plan_ev}},
        report_evidence_by_year={2024: {"테스트지표": report_ev}},
        plan_specs_valid_pages=pages["plan"],
        report_specs_valid_pages=pages["report"],
        report_has_pua_by_year={2024: False},
    )
    assert result["report_actual_match_status"] == "MANUAL_MISSING_PDF_PRESENT"
    assert result["actual_value_numeric_manual"] is None
    assert result["actual_value_numeric_pdf"] == pytest.approx(11.0)
    assert result["overall_reconciliation_status"] == "MANUAL_MISSING_PDF_PRESENT"


def test_reconcile_row_ocr_required_for_image_only_plan_year(monkeypatch) -> None:
    """시나리오 4: 2022년 계획서 별첨1은 이미지 표라 OCR 확인이 필요합니다."""
    monkeypatch.setattr(pr, "find_change_evidence", lambda *a, **k: None)
    row = _base_row(source_indicator_id="테스트-2022-I1-01", fiscal_year=2022)
    plan_spec = pr.doc_spec(2022, "plan")
    report_spec = pr.doc_spec(2022, "report")
    pages = {
        "plan": {2022: (plan_spec.source_page_start, plan_spec.source_page_end)},
        "report": {2022: (report_spec.source_page_start, report_spec.source_page_end)},
    }
    result = pr.reconcile_row(
        row,
        plan_evidence_by_year={2022: {}},
        report_evidence_by_year={2022: {}},
        plan_specs_valid_pages=pages["plan"],
        report_specs_valid_pages=pages["report"],
        report_has_pua_by_year={2022: False},
    )
    assert result["ocr_status"] == "OCR_REQUIRED"
    assert result["overall_reconciliation_status"] == "OCR_REQUIRED"


def test_reconcile_row_target_value_mismatch_reclassified_when_change_table_confirms(
    monkeypatch,
) -> None:
    """시나리오 5: 계획-보고 목표치가 다르지만(수기=계획서 10.0, 보고서 자체 표=12.0)
    별첨6 "성과계획서 변경 사항"표가 정확히 같은 변경전(10.0)→변경후(12.0) 값을
    문서화하고 있으면, 이는 추출 오류가 아니라 목표치 사후 개정입니다.
    VALUE_MISMATCH가 아니라 MATCH_AFTER_CHANGE로 재분류되어야 합니다."""

    def fake_find_change_evidence(report_spec, indicator_name, **kwargs):
        return pr.ChangeEvidence(
            matched_name=indicator_name,
            window_text="변경 전후 근거",
            target_before_raw="10.0",
            target_after_raw="12.0",
            reason="전년도 실적치 고려하여 목표 상향조정",
            split_pdf_page=35,
            source_pdf_page=193,
            printed_page=None,
            source_text="변경 전후 근거",
        )

    monkeypatch.setattr(pr, "find_change_evidence", fake_find_change_evidence)
    # 실적(11.0)·달성률(91.7%)은 변경된 목표(12.0) 기준으로 보고서 표와 그대로
    # 일치시켜, 이 테스트가 목표치 재분류 로직만 단독으로 검증하도록 합니다.
    row = _base_row(official_achievement_rate_raw="91.7", official_achievement_rate_numeric=91.7)
    plan_ev = pr.PlanEvidence(
        matched_name="테스트지표",
        split_pdf_page=1,
        source_pdf_page=188,
        printed_page=180,
        source_text="테스트지표 10.0",
        extraction_method="TEXT",
        numeric_candidates=[10.0],
    )
    report_ev = pr.AchievementEvidence(
        matched_name="테스트지표",
        split_pdf_page=4,
        source_pdf_page=162,
        printed_page=None,
        source_text="목표 12.0 실적 11.0 달성률 91.7%",
        target_values_raw=["12.0"],
        actual_values_raw=["11.0"],
        rate_values_raw=["91.7%"],
        extraction_method="TEXT",
    )
    pages = _valid_pages()
    result = pr.reconcile_row(
        row,
        plan_evidence_by_year={2024: {"테스트지표": plan_ev}},
        report_evidence_by_year={2024: {"테스트지표": report_ev}},
        plan_specs_valid_pages=pages["plan"],
        report_specs_valid_pages=pages["report"],
        report_has_pua_by_year={2024: False},
    )
    # 계획 원문(10.0)은 그대로 EXACT_MATCH — 계획서 자체는 수기값과 다르지 않음.
    assert result["plan_target_match_status"] == "EXACT_MATCH"
    # 보고서 자체 표의 목표치(12.0)는 계획 수기값(10.0)과 다르지만, 별첨6 변경표가
    # 같은 10.0→12.0 변경을 문서화하므로 오류가 아니라 확인된 변경으로 재분류.
    assert result["report_target_match_status"] == "MATCH_AFTER_CHANGE"
    assert result["overall_reconciliation_status"] == "MATCH_AFTER_CHANGE"
    assert "REPORT_TARGET_CHANGE_CONFIRMED_BY_별첨6" in (result["review_reason"] or "")
    # 원본 문서화 사유·변경전후 값은 그대로 보존되어야 함(재분류가 근거를 지우지 않음).
    assert result["documented_change_target_before_raw"] == "10.0"
    assert result["documented_change_target_after_raw"] == "12.0"
    assert result["documented_change_reason_raw"] == "전년도 실적치 고려하여 목표 상향조정"


def test_reconcile_row_target_value_mismatch_kept_when_change_table_does_not_match(
    monkeypatch,
) -> None:
    """시나리오 6: 별첨6에 변경 기록이 있어도 그 변경전·변경후 값이 실제
    계획-보고 목표 불일치(10.0 vs 12.0)와 정확히 일치하지 않으면(여기서는
    변경후 값이 15.0으로 달라 보고서 표 값 12.0과 다름) 재분류하지 않고
    VALUE_MISMATCH를 유지해야 합니다. 명칭·존재 여부만으로 자동 확정하지
    않는다는 원칙을 검증합니다."""

    def fake_find_change_evidence(report_spec, indicator_name, **kwargs):
        return pr.ChangeEvidence(
            matched_name=indicator_name,
            window_text="변경 전후 근거",
            target_before_raw="10.0",
            target_after_raw="15.0",
            reason="다른 사유",
            split_pdf_page=35,
            source_pdf_page=193,
            printed_page=None,
            source_text="변경 전후 근거",
        )

    monkeypatch.setattr(pr, "find_change_evidence", fake_find_change_evidence)
    row = _base_row()
    plan_ev = pr.PlanEvidence(
        matched_name="테스트지표",
        split_pdf_page=1,
        source_pdf_page=188,
        printed_page=180,
        source_text="테스트지표 10.0",
        extraction_method="TEXT",
        numeric_candidates=[10.0],
    )
    report_ev = pr.AchievementEvidence(
        matched_name="테스트지표",
        split_pdf_page=4,
        source_pdf_page=162,
        printed_page=None,
        source_text="목표 12.0 실적 11.0 달성률 91.7%",
        target_values_raw=["12.0"],
        actual_values_raw=["11.0"],
        rate_values_raw=["91.7%"],
        extraction_method="TEXT",
    )
    pages = _valid_pages()
    result = pr.reconcile_row(
        row,
        plan_evidence_by_year={2024: {"테스트지표": plan_ev}},
        report_evidence_by_year={2024: {"테스트지표": report_ev}},
        plan_specs_valid_pages=pages["plan"],
        report_specs_valid_pages=pages["report"],
        report_has_pua_by_year={2024: False},
    )
    assert result["report_target_match_status"] == "VALUE_MISMATCH"
    assert "REPORT_TARGET_CHANGE_CONFIRMED_BY_별첨6" not in (result["review_reason"] or "")


# ---------------------------------------------------------------------------
# build_reconciliation_table / 출력 계약
# ---------------------------------------------------------------------------


def test_flag_indicator_name_collisions_marks_duplicate_names_ambiguous() -> None:
    """같은 연도에 두 프로그램이 완전히 동일한 지표명을 쓰면, 텍스트검색 기반
    매칭이 한쪽 근거를 잘못 나눠 가질 위험이 있으므로 `AMBIGUOUS`로 표시하고
    사람이 확인해야 함을 `review_reason`에 남겨야 합니다. 이름이 겹치지
    않는 행은 건드리면 안 됩니다."""
    manual_df = pd.DataFrame(
        [
            {
                "source_indicator_id": "중기부-2022-II1-01",
                "fiscal_year": 2022,
                "indicator_name_plan": "자금공급 수혜 중소기업 매출액 증가율",
                "indicator_name_report": "자금공급 수혜 중소기업 매출액 증가율",
            },
            {
                "source_indicator_id": "중기부-2022-III1-03",
                "fiscal_year": 2022,
                "indicator_name_plan": "자금공급 수혜 중소기업 매출액 증가율",
                "indicator_name_report": "자금공급 수혜 중소기업 매출액 증가율",
            },
            {
                "source_indicator_id": "중기부-2022-I1-01",
                "fiscal_year": 2022,
                "indicator_name_plan": "중소기업지원사업 만족도",
                "indicator_name_report": "중소기업지원사업 만족도",
            },
        ]
    )
    result_df = pd.DataFrame(
        [
            {
                "source_indicator_id": "중기부-2022-II1-01",
                "fiscal_year": 2022,
                "manual_indicator_name_plan": "자금공급 수혜 중소기업 매출액 증가율",
                "manual_indicator_name_report": "자금공급 수혜 중소기업 매출액 증가율",
                "plan_name_match_status": "EXACT_MATCH",
                "plan_target_match_status": "EXACT_MATCH",
                "report_name_match_status": "EXACT_MATCH",
                "report_target_match_status": "EXACT_MATCH",
                "report_actual_match_status": "EXACT_MATCH",
                "report_achievement_rate_match_status": "EXACT_MATCH",
                "ocr_status": "OCR_REQUIRED",
                "overall_reconciliation_status": "OCR_REQUIRED",
                "review_reason": None,
            },
            {
                "source_indicator_id": "중기부-2022-III1-03",
                "fiscal_year": 2022,
                "manual_indicator_name_plan": "자금공급 수혜 중소기업 매출액 증가율",
                "manual_indicator_name_report": "자금공급 수혜 중소기업 매출액 증가율",
                "plan_name_match_status": "EXACT_MATCH",
                "plan_target_match_status": "VALUE_MISMATCH",
                "report_name_match_status": "EXACT_MATCH",
                "report_target_match_status": "VALUE_MISMATCH",
                "report_actual_match_status": "EXACT_MATCH",
                "report_achievement_rate_match_status": "EXACT_MATCH",
                "ocr_status": "OCR_REQUIRED",
                "overall_reconciliation_status": "OCR_REQUIRED",
                "review_reason": "PLAN_TARGET_FROM_CHANGE_TABLE_ONLY",
            },
            {
                "source_indicator_id": "중기부-2022-I1-01",
                "fiscal_year": 2022,
                "manual_indicator_name_plan": "중소기업지원사업 만족도",
                "manual_indicator_name_report": "중소기업지원사업 만족도",
                "plan_name_match_status": "EXACT_MATCH",
                "plan_target_match_status": "EXACT_MATCH",
                "report_name_match_status": "EXACT_MATCH",
                "report_target_match_status": "EXACT_MATCH",
                "report_actual_match_status": "EXACT_MATCH",
                "report_achievement_rate_match_status": "EXACT_MATCH",
                "ocr_status": "OCR_REQUIRED",
                "overall_reconciliation_status": "OCR_REQUIRED",
                "review_reason": None,
            },
        ]
    )

    flagged = pr._flag_indicator_name_collisions(manual_df, result_df)
    flagged = flagged.set_index("source_indicator_id")

    for sid in ("중기부-2022-II1-01", "중기부-2022-III1-03"):
        assert flagged.loc[sid, "plan_name_match_status"] == "AMBIGUOUS"
        assert flagged.loc[sid, "report_name_match_status"] == "AMBIGUOUS"
        assert flagged.loc[sid, "overall_reconciliation_status"] == "AMBIGUOUS"
        assert (
            "INDICATOR_NAME_AMBIGUOUS_MULTIPLE_PROGRAMS_SAME_YEAR"
            in flagged.loc[sid, "review_reason"]
        )
    # 기존 review_reason(예: 별첨6 대체 근거 사용)은 지우지 않고 이어붙여야 함.
    assert (
        "PLAN_TARGET_FROM_CHANGE_TABLE_ONLY" in flagged.loc["중기부-2022-III1-03", "review_reason"]
    )
    # 이름이 겹치지 않는 행은 그대로 유지.
    assert flagged.loc["중기부-2022-I1-01", "plan_name_match_status"] == "EXACT_MATCH"
    assert flagged.loc["중기부-2022-I1-01", "overall_reconciliation_status"] == "OCR_REQUIRED"
    assert flagged.loc["중기부-2022-I1-01", "review_reason"] is None


def test_distinct_pdf_program_evidence_resolves_duplicate_indicator_names() -> None:
    manual_df = pd.DataFrame(
        [
            {
                "source_indicator_id": "one",
                "fiscal_year": 2022,
                "indicator_name_plan": "공통지표",
                "indicator_name_report": "공통지표",
            },
            {
                "source_indicator_id": "two",
                "fiscal_year": 2022,
                "indicator_name_plan": "공통지표",
                "indicator_name_report": "공통지표",
            },
        ]
    )
    common = {
        "fiscal_year": 2022,
        "manual_indicator_name_plan": "공통지표",
        "manual_indicator_name_report": "공통지표",
        "plan_name_match_status": "EXACT_MATCH",
        "plan_target_match_status": "EXACT_MATCH",
        "report_name_match_status": "EXACT_MATCH",
        "report_target_match_status": "EXACT_MATCH",
        "report_actual_match_status": "EXACT_MATCH",
        "report_achievement_rate_match_status": "EXACT_MATCH",
        "ocr_status": "NOT_APPLICABLE",
        "overall_reconciliation_status": "EXACT_MATCH",
        "review_reason": None,
    }
    result_df = pd.DataFrame(
        [
            {
                **common,
                "source_indicator_id": "one",
                "plan_source_file": "report.pdf",
                "plan_split_pdf_page": 6,
                "plan_source_text": "II-1 공통지표",
                "report_source_file": "report.pdf",
                "report_split_pdf_page": 6,
                "report_source_text": "II-1 공통지표",
                "pdf_report_program_goal_number": "II-1",
            },
            {
                **common,
                "source_indicator_id": "two",
                "plan_source_file": "report.pdf",
                "plan_split_pdf_page": 7,
                "plan_source_text": "III-1 공통지표",
                "report_source_file": "report.pdf",
                "report_split_pdf_page": 7,
                "report_source_text": "III-1 공통지표",
                "pdf_report_program_goal_number": "III-1",
            },
        ]
    )

    resolved = pr._flag_indicator_name_collisions(manual_df, result_df)

    assert resolved["overall_reconciliation_status"].tolist() == ["EXACT_MATCH", "EXACT_MATCH"]
    assert resolved["review_reason"].isna().all()


def test_build_reconciliation_summary_counts_match_row_count() -> None:
    df = pd.DataFrame(
        [
            {
                "source_indicator_id": "a",
                "fiscal_year": 2024,
                "overall_reconciliation_status": "EXACT_MATCH",
                "plan_name_match_status": "EXACT_MATCH",
                "report_name_match_status": "EXACT_MATCH",
                "plan_target_match_status": "EXACT_MATCH",
                "report_target_match_status": "EXACT_MATCH",
                "report_actual_match_status": "EXACT_MATCH",
                "report_achievement_rate_match_status": "EXACT_MATCH",
                "ocr_status": "NOT_APPLICABLE",
                "review_status": None,
                "plan_split_pdf_page": 1,
                "report_split_pdf_page": 2,
                "planned_target_numeric_pdf": 10.0,
                "report_target_numeric_pdf": 10.0,
                "plan_vs_report_target_change_abs": 0.0,
                "plan_vs_report_target_change_pct": 0.0,
            },
            {
                "source_indicator_id": "b",
                "fiscal_year": 2024,
                "overall_reconciliation_status": "VALUE_MISMATCH",
                "plan_name_match_status": "EXACT_MATCH",
                "report_name_match_status": "EXACT_MATCH",
                "plan_target_match_status": "VALUE_MISMATCH",
                "report_target_match_status": "EXACT_MATCH",
                "report_actual_match_status": "EXACT_MATCH",
                "report_achievement_rate_match_status": "EXACT_MATCH",
                "ocr_status": "NOT_APPLICABLE",
                "review_status": "CONFIRMED",
                "plan_split_pdf_page": 1,
                "report_split_pdf_page": 2,
                # 계획 목표(10.0) -> 보고 목표(12.0)로 20% 늘어난 사례.
                "planned_target_numeric_pdf": 10.0,
                "report_target_numeric_pdf": 12.0,
                "plan_vs_report_target_change_abs": 2.0,
                "plan_vs_report_target_change_pct": 20.0,
            },
            {
                "source_indicator_id": "ocr-bogus",
                "fiscal_year": 2022,
                "overall_reconciliation_status": "OCR_REQUIRED",
                "plan_name_match_status": "EXACT_MATCH",
                "report_name_match_status": "EXACT_MATCH",
                "plan_target_match_status": "VALUE_MISMATCH",
                "report_target_match_status": "EXACT_MATCH",
                "report_actual_match_status": "EXACT_MATCH",
                "report_achievement_rate_match_status": "EXACT_MATCH",
                "ocr_status": "OCR_REQUIRED",
                "review_status": None,
                "plan_split_pdf_page": 1,
                "report_split_pdf_page": 2,
                "planned_target_numeric_pdf": 0.5,
                "report_target_numeric_pdf": 13432.0,
                "plan_vs_report_target_change_abs": 13431.5,
                "plan_vs_report_target_change_pct": 2686300.0,
            },
        ]
    )
    summary = pr.build_reconciliation_summary(
        df,
        manual_input_rows=3,
        source_hashes_before={"x": "h1"},
        source_hashes_after={"x": "h1"},
    )
    assert summary["output_row_count"] == 3
    assert summary["manual_review_csv_row_count"] == 2
    assert summary["primary_key_duplicate_count"] == 0
    assert summary["source_file_hash_unchanged"] is True
    assert sum(summary["rows_by_overall_status"].values()) == 3

    change_summary = summary["plan_vs_report_target_change"]
    assert change_summary["rows_with_both_pdf_targets"] == 2
    assert change_summary["rows_excluded_unverified_ocr"] == 1
    assert change_summary["rows_unchanged"] == 1
    assert change_summary["rows_changed"] == 1
    assert change_summary["abs_pct_over_10"] == 1
    assert change_summary["top_changes"][0]["source_indicator_id"] == "b"
    assert change_summary["top_changes"][0]["change_pct"] == pytest.approx(20.0)
    assert change_summary["top_changes"][0]["ocr_status"] == "NOT_APPLICABLE"
    assert summary["review_status_counts"] == {"None": 2, "CONFIRMED": 1}


# ---------------------------------------------------------------------------
# review_instruction / 검수 확정 파일 병합
# ---------------------------------------------------------------------------


def _instruction_row(**overrides: object) -> dict:
    row = {
        "source_indicator_id": "중기부-2024-I1-01",
        "overall_reconciliation_status": "EXACT_MATCH",
        "plan_name_match_status": "EXACT_MATCH",
        "plan_target_match_status": "EXACT_MATCH",
        "report_name_match_status": "EXACT_MATCH",
        "report_target_match_status": "EXACT_MATCH",
        "report_actual_match_status": "EXACT_MATCH",
        "report_achievement_rate_match_status": "EXACT_MATCH",
        "review_reason": None,
        "plan_source_file": "plan.pdf",
        "plan_split_pdf_page": 3,
        "plan_source_pdf_page": 190,
        "report_source_file": "report.pdf",
        "report_split_pdf_page": 5,
        "report_source_pdf_page": 163,
        "documented_change_target_before_raw": None,
        "documented_change_target_after_raw": None,
        "documented_change_split_pdf_page": None,
        "documented_change_source_pdf_page": None,
    }
    row.update(overrides)
    return row


def test_build_review_instruction_returns_none_for_exact_match() -> None:
    assert pr._build_review_instruction(_instruction_row()) is None


def test_build_review_instruction_points_to_plan_page_only_when_plan_mismatched() -> None:
    row = _instruction_row(
        overall_reconciliation_status="VALUE_MISMATCH",
        plan_target_match_status="VALUE_MISMATCH",
    )
    instruction = pr._build_review_instruction(row)
    assert instruction is not None
    assert "[계획서] plan.pdf 3쪽(원본 190쪽)" in instruction
    assert "[보고서]" not in instruction


def test_build_review_instruction_includes_change_table_page_when_documented() -> None:
    row = _instruction_row(
        overall_reconciliation_status="MATCH_AFTER_CHANGE",
        plan_target_match_status="MATCH_AFTER_CHANGE",
        documented_change_target_before_raw="10",
        documented_change_target_after_raw="12",
        documented_change_split_pdf_page=40,
        documented_change_source_pdf_page=209,
    )
    instruction = pr._build_review_instruction(row)
    assert instruction is not None
    assert "[계획서] plan.pdf 3쪽(원본 190쪽)" in instruction
    assert "[별첨6 변경표] 40쪽(원본 209쪽)" in instruction


def test_build_review_instruction_prefixes_collision_note_for_ambiguous() -> None:
    row = _instruction_row(
        overall_reconciliation_status="AMBIGUOUS",
        plan_name_match_status="AMBIGUOUS",
        report_name_match_status="AMBIGUOUS",
        review_reason="INDICATOR_NAME_AMBIGUOUS_MULTIPLE_PROGRAMS_SAME_YEAR",
    )
    instruction = pr._build_review_instruction(row)
    assert instruction is not None
    assert instruction.startswith("동일 연도 내 지표명 중복")
    assert "[계획서] plan.pdf 3쪽(원본 190쪽)" in instruction
    assert "[보고서] report.pdf 5쪽(원본 163쪽)" in instruction


def test_load_manual_review_confirmations_returns_empty_when_file_missing(tmp_path) -> None:
    result = pr.load_manual_review_confirmations(tmp_path / "does_not_exist.csv")
    assert result.empty
    assert list(result.columns) == list(pr.MANUAL_REVIEW_CONFIRMATIONS_COLUMNS)


def test_load_manual_review_confirmations_rejects_bad_status(tmp_path) -> None:
    path = tmp_path / "confirmations.csv"
    path.write_text(
        "source_indicator_id,reviewer,review_status,review_note,review_confirmed_at\n"
        "a,팀,SOMETHING_ELSE,메모,2026-07-28\n",
        encoding="utf-8-sig",
    )
    with pytest.raises(pr.PdfReconciliationError, match="review_status"):
        pr.load_manual_review_confirmations(path)


def test_load_manual_review_confirmations_rejects_duplicate_ids(tmp_path) -> None:
    path = tmp_path / "confirmations.csv"
    path.write_text(
        "source_indicator_id,reviewer,review_status,review_note,review_confirmed_at\n"
        "a,팀,CONFIRMED,메모1,2026-07-28\n"
        "a,팀,CONFIRMED,메모2,2026-07-28\n",
        encoding="utf-8-sig",
    )
    with pytest.raises(pr.PdfReconciliationError, match="중복"):
        pr.load_manual_review_confirmations(path)


def test_upsert_manual_review_confirmation_adds_and_replaces_one_row(tmp_path) -> None:
    path = tmp_path / "confirmations.csv"
    pr.upsert_manual_review_confirmation(
        path,
        source_indicator_id="MOEL-2022-I1-01",
        reviewer="검수자",
        review_status="CONFIRMED",
        review_note="원문과 일치",
        review_confirmed_at="2026-07-29T10:00:00+00:00",
    )
    updated = pr.upsert_manual_review_confirmation(
        path,
        source_indicator_id="MOEL-2022-I1-01",
        reviewer="검수자",
        review_status="CORRECTED",
        review_note="목표치 수정 필요",
        review_confirmed_at="2026-07-29T11:00:00+00:00",
    )
    assert len(updated) == 1
    assert updated.loc[0, "review_status"] == "CORRECTED"
    assert updated.loc[0, "review_note"] == "목표치 수정 필요"
    assert pr.load_manual_review_confirmations(path).equals(updated)


def test_upsert_manual_review_confirmation_requires_reviewer_and_note(tmp_path) -> None:
    with pytest.raises(pr.PdfReconciliationError, match="검수자"):
        pr.upsert_manual_review_confirmation(
            tmp_path / "confirmations.csv",
            source_indicator_id="MOEL-2022-I1-01",
            reviewer="",
            review_status="CONFIRMED",
            review_note="원문과 일치",
        )


def test_apply_manual_review_confirmations_merges_by_id_without_touching_others() -> None:
    result_df = pd.DataFrame(
        [
            {
                "source_indicator_id": "a",
                "reviewer": None,
                "review_status": None,
                "review_note": None,
                "review_confirmed_at": None,
                "overall_reconciliation_status": "OCR_REQUIRED",
                "planned_target_numeric_pdf": 169.0,
            },
            {
                "source_indicator_id": "b",
                "reviewer": None,
                "review_status": None,
                "review_note": None,
                "review_confirmed_at": None,
                "overall_reconciliation_status": "OCR_REQUIRED",
                "planned_target_numeric_pdf": 6.0,
            },
        ]
    )
    confirmations_df = pd.DataFrame(
        [
            {
                "source_indicator_id": "a",
                "reviewer": "팀",
                "review_status": "CONFIRMED",
                "review_note": "원문 확인함",
                "review_confirmed_at": "2026-07-28",
            }
        ]
    )
    merged = pr.apply_manual_review_confirmations(result_df, confirmations_df).set_index(
        "source_indicator_id"
    )
    assert merged.loc["a", "review_status"] == "CONFIRMED"
    assert merged.loc["a", "reviewer"] == "팀"
    assert merged.loc["a", "review_note"] == "원문 확인함"
    # 확정 파일에 없는 행은 손대지 않고, 원본 수치도 절대 바뀌면 안 됨.
    assert merged.loc["b", "review_status"] is None
    assert merged.loc["a", "planned_target_numeric_pdf"] == 169.0
    assert merged.loc["b", "planned_target_numeric_pdf"] == 6.0
    assert merged.loc["a", "overall_reconciliation_status"] == "OCR_REQUIRED"


def test_apply_manual_review_confirmations_rejects_unknown_id() -> None:
    result_df = pd.DataFrame([{"source_indicator_id": "a", "review_status": None}])
    confirmations_df = pd.DataFrame(
        [
            {
                "source_indicator_id": "does-not-exist",
                "reviewer": "팀",
                "review_status": "CONFIRMED",
                "review_note": "메모",
                "review_confirmed_at": "2026-07-28",
            }
        ]
    )
    with pytest.raises(pr.PdfReconciliationError, match="does-not-exist"):
        pr.apply_manual_review_confirmations(result_df, confirmations_df)
