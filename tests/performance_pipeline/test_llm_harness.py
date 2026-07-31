from __future__ import annotations

import json

import httpx
import pandas as pd
import pytest

from performance_pipeline import llm_harness as lh


def _candidate_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_indicator_id": "019-2023-1",
                "ministry_code": "019",
                "fiscal_year": 2023,
                "review_status": pd.NA,
                "overall_reconciliation_status": "OCR_REQUIRED",
                "page_evidence_status": "EXACT_MATCH",
                "report_source_file": "report.pdf",
                "report_split_pdf_page": 7,
                "documented_change_source_file": pd.NA,
                "documented_change_split_pdf_page": pd.NA,
                "report_source_text": "성과지표 A 목표 10 실적 9 달성률 90%",
            },
            {
                "source_indicator_id": "019-2023-2",
                "ministry_code": "019",
                "fiscal_year": 2023,
                "review_status": pd.NA,
                "overall_reconciliation_status": "PDF_MISSING_MANUAL_PRESENT",
                "page_evidence_status": "PDF_NOT_FOUND",
                "report_source_file": pd.NA,
                "report_split_pdf_page": pd.NA,
                "documented_change_source_file": pd.NA,
                "documented_change_split_pdf_page": pd.NA,
            },
            {
                "source_indicator_id": "019-2023-3",
                "ministry_code": "019",
                "fiscal_year": 2023,
                "review_status": "CONFIRMED",
                "overall_reconciliation_status": "VALUE_MISMATCH",
                "page_evidence_status": "EXACT_MATCH",
                "report_source_file": "report.pdf",
                "report_split_pdf_page": 8,
                "report_source_text": "성과지표 B 목표 10 실적 8",
            },
        ]
    )


def test_classification_and_request_grouping_are_local_first() -> None:
    rows = lh.classify_rows(_candidate_rows())
    assert rows["automation_route"].tolist() == [
        "LOCAL_CONFIRMED",
        "HUMAN_ONLY",
        "LOCAL_CONFIRMED",
    ]
    assert rows["evidence_acceptance_status"].tolist() == [
        "EVIDENCE_CONFIRMED",
        "HUMAN_REVIEW_REQUIRED",
        "HUMAN_CONFIRMED",
    ]

    requests, index = lh.build_request_entries(
        rows,
        model="gpt-test",
        prompt_version="p1",
        schema_version="s1",
        max_evidence_chars=1200,
        max_output_tokens=500,
    )
    assert requests == []
    assert index.empty


def test_request_builder_keeps_strict_schema_for_future_llm_rows() -> None:
    rows = lh.classify_rows(_candidate_rows().iloc[[0]])
    rows["automation_route"] = "LLM_CANDIDATE"
    requests, index = lh.build_request_entries(
        rows,
        model="gpt-test",
        prompt_version="p1",
        schema_version="s1",
        max_evidence_chars=1200,
        max_output_tokens=500,
    )
    assert index["source_indicator_id"].tolist() == ["019-2023-1"]
    assert requests[0]["body"]["store"] is False
    assert requests[0]["body"]["reasoning"] == {"effort": "low"}
    assert requests[0]["body"]["text"]["format"]["strict"] is True
    user_payload = json.loads(requests[0]["body"]["input"][1]["content"])
    assert user_payload["request_id"] == requests[0]["custom_id"]


def test_cost_gate_uses_maximum_output_budget() -> None:
    config = {
        "harness": {
            "estimated_output_tokens_per_request": 450,
            "max_output_tokens": 1800,
            "batch_discount": 0.5,
            "pricing_usd_per_million": {"gpt-5.6-luna": {"input": 0.20, "output": 1.20}},
        }
    }
    result = lh._cost_scenarios([{"body": {"input": "test"}}], config)
    luna = result["models"]["gpt-5.6-luna"]

    assert luna["output_tokens_estimate"] == 450
    assert luna["maximum_output_tokens"] == 1800
    assert luna["batch_usd_estimate"] > luna["expected_batch_usd_estimate"]
    assert result["cost_gate_basis"] == "maximum_output_tokens"


def test_pilot_selection_round_robins_ministries() -> None:
    index = pd.DataFrame(
        [
            {
                "request_id": f"{ministry}-{year}-{number}",
                "ministry_code": ministry,
                "fiscal_year": year,
                "local_status": "OCR_REQUIRED",
            }
            for ministry in ("019", "075", "162")
            for year in (2022, 2023)
            for number in range(2)
        ]
    )
    selected = lh._pilot_request_ids(index, 6)
    assert len(selected) == 6
    assert {request_id.split("-")[0] for request_id in selected} == {
        "019",
        "075",
        "162",
    }
    assert {int(request_id.split("-")[1]) for request_id in selected} == {2022, 2023}


def test_response_contract_requires_grounded_quotes_and_string_values() -> None:
    request_id = "perf-test"
    valid = {
        "request_id": request_id,
        "records": [
            {
                "source_indicator_id": "019-2023-1",
                "indicator_name": "성과지표 A",
                "unit": None,
                "plan_target_raw": None,
                "report_target_raw": "10",
                "actual_value_raw": "9",
                "official_achievement_rate_raw": "90%",
                "extraction_status": "EXTRACTED",
                "review_reasons": [],
                "evidence": [
                    {
                        "document_type": "REPORT",
                        "source_file": "report.pdf",
                        "source_page": 7,
                        "quote": "목표 10 실적 9",
                    }
                ],
            }
        ],
    }
    result = lh.validate_extraction_payload(
        valid,
        request_id=request_id,
        expected_ids={"019-2023-1"},
        allowed_sources={"report.pdf": {7}},
        grounding_text="성과지표 A 목표 10 실적 9 달성률 90%",
    )
    assert result[0]["actual_value_raw"] == "9"

    hallucinated = json.loads(json.dumps(valid))
    hallucinated["records"][0]["evidence"][0]["quote"] = "원문에 없는 문장"
    with pytest.raises(lh.LlmHarnessError, match="입력 원문"):
        lh.validate_extraction_payload(
            hallucinated,
            request_id=request_id,
            expected_ids={"019-2023-1"},
            allowed_sources={"report.pdf": {7}},
            grounding_text="성과지표 A 목표 10 실적 9 달성률 90%",
        )

    wrong_type = json.loads(json.dumps(valid))
    wrong_type["records"][0]["actual_value_raw"] = 9
    with pytest.raises(lh.LlmHarnessError, match="문자열 또는 null"):
        lh.validate_extraction_payload(
            wrong_type,
            request_id=request_id,
            expected_ids={"019-2023-1"},
            allowed_sources={"report.pdf": {7}},
            grounding_text="성과지표 A 목표 10 실적 9 달성률 90%",
        )


def test_batch_submission_is_disabled_by_default(tmp_path) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "llm.yaml").write_text(
        "llm:\n  api_execution_allowed: false\nharness: {}\n",
        encoding="utf-8",
    )
    with pytest.raises(lh.LlmHarnessError, match="false"):
        lh.submit_batch(tmp_path, max_approved_cost_usd=1)


def test_fetch_batch_downloads_completed_output_once(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "configs"
    harness_dir = tmp_path / "data/interim/llm_harness"
    config_dir.mkdir()
    harness_dir.mkdir(parents=True)
    (config_dir / "llm.yaml").write_text(
        """llm:
  api_key_env: OPENAI_API_KEY
  request_timeout_seconds: 30
harness: {}
""",
        encoding="utf-8",
    )
    (harness_dir / "batch_state_pilot.json").write_text(
        json.dumps({"batch": {"id": "batch_test"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/batches/batch_test":
            return httpx.Response(
                200,
                json={
                    "id": "batch_test",
                    "status": "completed",
                    "output_file_id": "file_output",
                    "request_counts": {"total": 1, "completed": 1, "failed": 0},
                },
            )
        if request.url.path == "/v1/files/file_output/content":
            return httpx.Response(200, content=b'{"custom_id":"perf-test"}\n')
        return httpx.Response(404)

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://api.openai.com",
    ) as client:
        result = lh.fetch_batch_results(tmp_path, client=client)

    assert result["status"] == "completed"
    assert (harness_dir / "pilot_batch_responses.jsonl").read_bytes().startswith(b"{")
