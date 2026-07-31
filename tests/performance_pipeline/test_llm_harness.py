from __future__ import annotations

import json
import os
from pathlib import Path

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


def test_masked_request_keeps_evidence_but_hides_local_value_candidates() -> None:
    rows = _candidate_rows().iloc[[0]].copy()
    rows["automation_route"] = "LLM_CANDIDATE"
    rows["pdf_report_indicator_name"] = "성과지표 A"
    rows["pdf_report_program_name"] = "프로그램 A"
    requests, _ = lh.build_request_entries(
        rows,
        model="gpt-test",
        prompt_version="p1",
        schema_version="s1",
        max_evidence_chars=1200,
        max_output_tokens=500,
        expose_local_candidates=False,
    )
    record = json.loads(requests[0]["body"]["input"][1]["content"])["records"][0]

    assert record["indicator_hint"] == "성과지표 A"
    assert record["source_evidence"][1]["text"] == "성과지표 A 목표 10 실적 9 달성률 90%"
    assert not {"local_pdf_candidates", "local_status", "local_review_reason"} & set(record)


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


def test_project_env_loads_openai_key_without_overriding_shell(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=from-dotenv\nOPENAI_MODEL=from-dotenv-model\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_MODEL", "from-shell")

    lh._load_project_environment(tmp_path)

    assert os.environ["OPENAI_API_KEY"] == "from-dotenv"
    assert os.environ["OPENAI_MODEL"] == "from-shell"


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


def test_mss_masked_pilot_is_stratified_and_upload_file_has_no_gold_keys(tmp_path) -> None:
    result = lh.prepare_mss_masked_goldset_pilot(
        Path("."),
        output_dir=tmp_path / "mss_masked_pilot",
        overwrite=True,
    )
    summary = result.summary
    requests = [
        json.loads(line)
        for line in (tmp_path / "mss_masked_pilot/pilot_requests.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    candidates = pd.read_csv(tmp_path / "mss_masked_pilot/candidate_rows.csv")

    assert summary["source_rows"] == 63
    assert summary["eligible_rows"] == 59
    assert summary["request_count"] == len(requests) == 12
    assert summary["request_row_count"] == len(candidates) == 34
    assert set(summary["year_counts"]) == {"2022", "2023", "2024"}
    assert summary["api_called"] is False
    assert summary["api_execution_allowed"] is False
    assert summary["masked_input_contract"]["full_row_discovery_tested"] is False
    assert "manual_actual_value_raw" in candidates
    for request in requests:
        records = json.loads(request["body"]["input"][1]["content"])["records"]
        assert all(
            not {"local_pdf_candidates", "local_status", "local_review_reason"} & set(record)
            for record in records
        )


def test_batch_submission_accepts_explicit_masked_pilot_directory(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "configs"
    harness_dir = tmp_path / "masked"
    config_dir.mkdir()
    harness_dir.mkdir()
    (config_dir / "llm.yaml").write_text(
        """llm:
  api_execution_allowed: true
  api_key_env: OPENAI_API_KEY
  request_timeout_seconds: 30
harness:
  max_build_qa_cost_usd: 80
""",
        encoding="utf-8",
    )
    (harness_dir / "harness_summary.json").write_text(
        json.dumps(
            {
                "api_ready": True,
                "model": "gpt-test",
                "pilot_cost": {"models": {"gpt-test": {"batch_usd_estimate": 0.01}}},
                "cost": {"models": {"gpt-test": {"batch_usd_estimate": 0.01}}},
            }
        ),
        encoding="utf-8",
    )
    (harness_dir / "pilot_requests.jsonl").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/files":
            return httpx.Response(200, json={"id": "file_test"})
        if request.url.path == "/v1/batches":
            return httpx.Response(200, json={"id": "batch_test", "status": "validating"})
        return httpx.Response(404)

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://api.openai.com",
    ) as client:
        result = lh.submit_batch(
            tmp_path,
            max_approved_cost_usd=1,
            harness_dir=harness_dir,
            client=client,
        )

    assert result["input_file_id"] == "file_test"
    assert (harness_dir / "batch_state_pilot.json").is_file()


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
