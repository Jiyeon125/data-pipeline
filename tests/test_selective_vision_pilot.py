import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from permissive_local_parser_pilot import _opendataloader_table_rows
from selective_vision_pilot import (
    _attempt_max_cost_usd,
    _billed_cost_usd,
    _expected_value_visible,
    _manual_page_numbers,
    _needs_previous_page_context,
    _pilot_sample,
    _prepare_sync_requests,
    _response_output_text,
    _structure_route,
    _sync_cost_usd,
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
    start = source.index("def _request_entry")
    request_function = source[start : source.index("\ndef ", start)]
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


def test_sync_request_clamps_output_and_parses_response(tmp_path) -> None:
    request_path = tmp_path / "requests.jsonl"
    request_path.write_text(
        '{"custom_id":"p1","body":{"max_output_tokens":6000}}\n',
        encoding="utf-8",
    )
    requests = _prepare_sync_requests(request_path, 1800)
    payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": '{"records":[]}'},
                ],
            }
        ]
    }

    assert requests[0]["body"]["max_output_tokens"] == 1800
    assert _response_output_text(payload) == '{"records":[]}'
    assert _sync_cost_usd({"input_tokens": 1000, "output_tokens": 500}, 0.2, 1.2) == 0.0008
    index = {
        "image_patch_tokens": "1600",
        "previous_context_image_patch_tokens": "800",
        "prompt_char_count": "200",
    }
    assert round(_attempt_max_cost_usd(index, 1800, 0.2, 1.2), 6) == 0.003256


def test_billed_cost_does_not_double_count_resumed_success() -> None:
    attempts = [
        {"custom_id": "new", "cost_usd": 0.002},
        {"custom_id": "lost", "cost_reserve_usd": 0.003},
    ]
    saved = [
        {"custom_id": "new", "ok": True, "cost_usd": 0.002},
        {"custom_id": "old", "ok": True, "cost_usd": 0.001},
    ]

    assert _billed_cost_usd(attempts, saved) == 0.006


def test_numeric_gold_comparison_accepts_units_around_one_number() -> None:
    from performance_pipeline.llm_harness import _numeric_comparison_equal

    assert _numeric_comparison_equal("77.05(점)", "77.05")


def test_manual_page_numbers_separate_pdf_and_printed_pages() -> None:
    assert _manual_page_numbers("PDF p.494 / 문서 p.486") == (494, 486)


def test_expected_value_visibility_uses_only_the_sampled_page_source() -> None:
    assert _expected_value_visible("113.9", "실적 1.89 / 달성률 113.9")
    assert not _expected_value_visible("100.7", "목표 66.4 68.0 69.0")
    assert _expected_value_visible(
        "전체 빈곤층 대비 복 지수혜 비율", "전체 빈곤층 대비 복지수혜 비율"
    )
