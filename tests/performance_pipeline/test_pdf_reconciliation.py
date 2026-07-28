from __future__ import annotations

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


def test_reconcile_row_name_change_documented_in_change_table(monkeypatch) -> None:
    """시나리오 2: 계획서-보고서 지표명이 바뀌었지만 별첨6 변경사항표로 확인됨."""

    def fake_find_change_evidence(report_spec, indicator_name):
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
                "plan_split_pdf_page": 1,
                "report_split_pdf_page": 2,
                # 계획 목표(10.0) -> 보고 목표(12.0)로 20% 늘어난 사례.
                "planned_target_numeric_pdf": 10.0,
                "report_target_numeric_pdf": 12.0,
                "plan_vs_report_target_change_abs": 2.0,
                "plan_vs_report_target_change_pct": 20.0,
            },
        ]
    )
    summary = pr.build_reconciliation_summary(
        df,
        manual_input_rows=2,
        source_hashes_before={"x": "h1"},
        source_hashes_after={"x": "h1"},
    )
    assert summary["output_row_count"] == 2
    assert summary["manual_review_csv_row_count"] == 1
    assert summary["primary_key_duplicate_count"] == 0
    assert summary["source_file_hash_unchanged"] is True
    assert sum(summary["rows_by_overall_status"].values()) == 2

    change_summary = summary["plan_vs_report_target_change"]
    assert change_summary["rows_with_both_pdf_targets"] == 2
    assert change_summary["rows_unchanged"] == 1
    assert change_summary["rows_changed"] == 1
    assert change_summary["abs_pct_over_10"] == 1
    assert change_summary["top_changes"][0]["source_indicator_id"] == "b"
    assert change_summary["top_changes"][0]["change_pct"] == pytest.approx(20.0)
    assert change_summary["top_changes"][0]["ocr_status"] == "NOT_APPLICABLE"
