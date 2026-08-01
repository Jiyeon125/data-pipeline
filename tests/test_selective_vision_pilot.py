import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from permissive_local_parser_pilot import _opendataloader_table_rows
from selective_vision_pilot import (
    _needs_previous_page_context,
    _pilot_sample,
    _structure_route,
    _text_bounds,
    structure_reasons,
)


def test_text_bounds_ignore_toc_and_stop_before_next_annex() -> None:
    texts = [""] * 20
    texts[2] = "목차 프로그램 성과지표 현황 100"
    texts[14] = "별첨1 프로그램 성과지표 현황"
    texts[16] = "별첨2 성과목표체계별 예산현황"
    assert _text_bounds(texts, "PLAN") == (15, 17)


def test_structure_gate_accepts_complex_table_and_rejects_known_failures() -> None:
    raw = Path("data/interim/parser_pilot/opendataloader/raw")
    good = _opendataloader_table_rows(raw / "p14_075_2023_REPORT_187.json")
    rotated = _opendataloader_table_rows(raw / "p09_019_2024_PLAN_253.json")
    missing_header = _opendataloader_table_rows(raw / "p12_162_2023_PLAN_126.json")

    assert structure_reasons(good, "REPORT", 2023, 3) == []
    assert "HEADER_AFTER_DATA" in structure_reasons(rotated, "PLAN", 2024, 1)
    assert "INDICATOR_HEADER_MISSING" in structure_reasons(missing_header, "PLAN", 2023, 1)


def test_opendataloader_request_inputs_do_not_use_gold_values() -> None:
    source = Path("scripts/selective_vision_pilot.py").read_text(encoding="utf-8")
    request_function = source[source.index("def _request_entry") : source.index("def _gold_frames")]
    forbidden = {"expected_indicator_name", "target_match", "actual_match", "rate_match"}
    assert not any(name in request_function for name in forbidden)
    config = yaml.safe_load(Path("configs/llm.yaml").read_text(encoding="utf-8"))
    assert config["llm"]["api_execution_allowed"] is False


def test_existing_local_confirmation_is_not_sent_to_vision_again() -> None:
    status, reasons = _structure_route(
        "PERFORMANCE_TEXT_SIGNAL;PREVIOUS_LOCAL_DISCOVERY", ["NO_TABLE"]
    )

    assert status == "EXISTING_LOCAL_CONFIRMED"
    assert reasons == []


def test_continued_table_without_visible_header_gets_previous_page_context() -> None:
    assert _needs_previous_page_context(
        ["INDICATOR_HEADER_MISSING"], "과학기술인재 육성지원 정책만족도"
    )
    assert not _needs_previous_page_context(["INDICATOR_HEADER_MISSING"], "프로그램 성과지표 현황")


def test_pilot_sample_keeps_unresolved_and_spreads_strata() -> None:
    rows = [
        {
            "page_id": f"p{index}",
            "request_id": f"vision-p{index}",
            "ministry_code": "019" if index < 3 else "075",
            "document_type": "PLAN" if index % 2 else "REPORT",
            "selection_reasons": "UNRESOLVED_QUEUE" if index == 4 else "ANNEX",
            "structure_reasons": "NO_TABLE" if index % 2 else "HEADER_AFTER_DATA",
        }
        for index in range(6)
    ]

    sample = _pilot_sample(rows, 4)

    assert "p4" in {row["page_id"] for row in sample}
    assert len({(row["ministry_code"], row["document_type"]) for row in sample}) >= 3
