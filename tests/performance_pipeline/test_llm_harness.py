from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pandas as pd
import pytest

from performance_pipeline import llm_harness as lh
from performance_pipeline.llm_economics import build_llm_cost_benefit


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


def test_request_builder_scales_output_limit_with_record_count() -> None:
    rows = pd.concat([_candidate_rows().iloc[[0]]] * 6, ignore_index=True)
    rows["source_indicator_id"] = [f"019-2023-{number}" for number in range(6)]
    rows["automation_route"] = "LLM_CANDIDATE"

    requests, _ = lh.build_request_entries(
        rows,
        model="gpt-test",
        prompt_version="p1",
        schema_version="s1",
        max_evidence_chars=1200,
        max_output_tokens=1800,
        minimum_output_tokens_per_record=400,
    )

    assert requests[0]["body"]["max_output_tokens"] == 2400


def test_request_builder_can_isolate_each_indicator() -> None:
    rows = pd.concat([_candidate_rows().iloc[[0]]] * 2, ignore_index=True)
    rows["source_indicator_id"] = ["019-2023-1", "019-2023-2"]
    rows["automation_route"] = "LLM_CANDIDATE"

    requests, index = lh.build_request_entries(
        rows,
        model="gpt-test",
        prompt_version="p2",
        schema_version="s1",
        max_evidence_chars=1200,
        max_output_tokens=1800,
        max_records_per_request=1,
        reasoning_effort="medium",
    )

    assert len(requests) == len(index) == 2
    assert all(
        len(json.loads(request["body"]["input"][1]["content"])["records"]) == 1
        for request in requests
    )
    assert all(request["body"]["reasoning"] == {"effort": "medium"} for request in requests)


def test_masked_request_keeps_evidence_but_hides_local_value_candidates() -> None:
    rows = _candidate_rows().iloc[[0]].copy()
    rows["automation_route"] = "LLM_CANDIDATE"
    rows["pdf_report_indicator_name"] = "성과지표 A"
    rows["pdf_report_program_name"] = "프로그램 A"
    rows["documented_change_target_before_raw"] = "10"
    rows["documented_change_target_after_raw"] = "12"
    rows["documented_change_reason_raw"] = "목표 상향"
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
    assert record["change_context"]["target_before_raw"] == "10"
    assert record["source_evidence"][2]["text"] == (
        "변경 전 목표: 10 | 변경 후 목표: 12 | 변경 사유: 목표 상향"
    )
    assert record["source_context_status"] == "PASS"
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
                "source_indicator_id": f"source-{ministry}-{year}-{number}",
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


def test_pilot_cohort_does_not_change_when_request_hash_changes() -> None:
    rows = pd.DataFrame(
        [
            {
                "request_id": f"old-{number}",
                "source_indicator_id": f"source-{number:02d}",
                "ministry_code": "102",
                "fiscal_year": 2023 + number % 2,
                "local_status": "EXACT_MATCH",
            }
            for number in range(8)
        ]
    )
    changed = rows.assign(request_id=lambda frame: "new-" + frame["request_id"])

    old_requests = lh._pilot_request_ids(rows, 4)
    new_requests = lh._pilot_request_ids(changed, 4)
    old_sources = set(rows.loc[rows.request_id.isin(old_requests), "source_indicator_id"])
    new_sources = set(changed.loc[changed.request_id.isin(new_requests), "source_indicator_id"])

    assert old_sources == new_sources


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


def test_local_recovery_keeps_complete_records_and_nulls_unsupported_fields() -> None:
    record = {
        "source_indicator_id": "019-2023-1",
        "indicator_name": "추정한 지표명",
        "unit": "%",
        "plan_target_raw": "10",
        "report_target_raw": "10",
        "actual_value_raw": "9",
        "official_achievement_rate_raw": "90%",
        "extraction_status": "EXTRACTED",
        "review_reasons": [],
        "evidence": [
            {
                "document_type": "PLAN",
                "source_file": "plan.pdf",
                "source_page": 1,
                "quote": "지표 ... 목표 10",
            },
            {
                "document_type": "REPORT",
                "source_file": "report.pdf",
                "source_page": 2,
                "quote": "목표 10 실적 9 달성률 90%",
            },
        ],
    }

    recovered = lh._recover_grounded_record(
        record,
        request_id="perf-test",
        allowed_sources={"plan.pdf": {1}, "report.pdf": {2}},
        grounding_text="실제 지표명 % 목표 10 실적 9 달성률 90%",
        recovery_reason="TRUNCATED_RESPONSE_RECORD_RECOVERED",
    )

    assert recovered["indicator_name"] is None
    assert len(recovered["evidence"]) == 1
    assert "UNSUPPORTED_FIELDS_SET_NULL:indicator_name" in recovered["review_reasons"]

    no_exact_quote = json.loads(json.dumps(record))
    no_exact_quote["evidence"][1]["quote"] = None
    with pytest.raises(lh.LlmHarnessError, match="복구 가능한 원문 근거"):
        lh._recover_grounded_record(
            no_exact_quote,
            request_id="perf-test",
            allowed_sources={"plan.pdf": {1}, "report.pdf": {2}},
            grounding_text="실제 지표명 % 목표 10 실적 9 달성률 90%",
            recovery_reason="TRUNCATED_RESPONSE_RECORD_RECOVERED",
        )


def test_completed_record_prefix_ignores_truncated_tail() -> None:
    text = '{"records":[{"source_indicator_id":"one"},{"source_indicator_id":"two"'

    assert lh._completed_record_prefix(text) == [{"source_indicator_id": "one"}]


def test_field_accuracy_separates_gold_accuracy_from_grounded_enrichment() -> None:
    review = pd.DataFrame(
        {
            "request_id": ["r1", "r2", "r3", pd.NA],
            "actual_value_raw": ["9", "11", pd.NA, pd.NA],
            "manual_actual_value_raw": ["9", pd.NA, "10", "12"],
        }
    )

    result = lh._field_accuracy_summary(
        review,
        {"actual_value_raw": "manual_actual_value_raw"},
    )["actual_value_raw"]

    assert result["selected_gold_count"] == 3
    assert result["compared"] == 2
    assert result["correct"] == 1
    assert result["accuracy"] == 0.5
    assert result["end_to_end_correct_rate"] == 1 / 3
    assert result["manual_missing_grounded_extraction_count"] == 1
    assert result["manual_present_llm_null_count"] == 1
    assert result["no_valid_response_with_gold_count"] == 1


def test_gold_evaluation_treats_numeric_units_as_semantically_equal() -> None:
    review = pd.DataFrame(
        {
            "request_id": ["r1", "r2", "r3"],
            "unit": ["(%)", "(점)", "%"],
            "manual_indicator_unit": ["%", "점", "%"],
            "plan_target_raw": ["50.4(%)", "28.7( 조 원 )", "3,342"],
            "manual_planned_target_raw": ["50.4", "28.7", "2900.0"],
        }
    )

    result = lh._field_accuracy_summary(
        review,
        {
            "unit": "manual_indicator_unit",
            "plan_target_raw": "manual_planned_target_raw",
        },
    )

    assert result["unit"]["correct"] == 3
    assert result["plan_target_raw"]["correct"] == 2


def test_duplicate_evidence_is_flagged_without_using_manual_gold() -> None:
    rows = pd.DataFrame(
        {
            "source_indicator_id": ["one", "two", "three"],
            "plan_source_file": ["plan.pdf"] * 3,
            "plan_split_pdf_page": [1, 1, 2],
            "plan_source_text": ["same plan", "same plan", "other plan"],
            "report_source_file": ["report.pdf"] * 3,
            "report_split_pdf_page": [2, 2, 3],
            "report_source_text": ["same report", "same report", "other report"],
        }
    )

    assert lh._evidence_collision_ids(rows) == {"one", "two"}


def test_source_rules_preserve_llm_values_and_apply_only_grounded_corrections() -> None:
    record = {
        "source_indicator_id": "one",
        "indicator_name": "지표",
        "unit": "%",
        "plan_target_raw": "12%",
        "report_target_raw": "12",
        "actual_value_raw": "11",
        "official_achievement_rate_raw": "91.7%",
    }
    input_record = {
        "source_context_status": "PASS",
        "change_context": {"target_before_raw": "10", "target_after_raw": "12"},
    }

    corrected = lh._apply_source_rules(record, input_record)

    assert corrected["plan_target_raw"] == "12%"
    assert corrected["resolved_plan_target_raw"] == "10"
    assert corrected["automatic_correction_status"] == "CORRECTED_FROM_CHANGE_TABLE"
    assert corrected["automatic_correction_rules"] == ["PLAN_TARGET_USE_CHANGE_BEFORE"]

    blocked = lh._apply_source_rules(
        record,
        {"source_context_status": "SOURCE_EVIDENCE_COLLISION"},
    )
    assert blocked["plan_target_raw"] == "12%"
    assert all(blocked[f"resolved_{field}"] is None for field in lh.OUTPUT_FIELDS)
    assert blocked["automatic_correction_status"] == "BLOCKED_SOURCE_EVIDENCE_COLLISION"

    missing_actual = {**corrected, "resolved_actual_value_raw": None}
    filled = lh._apply_local_source_fallbacks(
        missing_actual,
        {"source_evidence": [{"text": "목표 233,033 실적 229,416 221,436 214,917"}]},
        {"pdf_report_actual_raw": "214,917", "manual_actual_value_raw": "정답지 값"},
    )
    assert filled["resolved_actual_value_raw"] == "214,917"
    assert "RESOLVED_ACTUAL_VALUE_RAW_FROM_LOCAL_SOURCE" in filled["automatic_correction_rules"]

    ungrounded = lh._apply_local_source_fallbacks(
        missing_actual,
        {"source_evidence": [{"text": "실적 214,917"}]},
        {"pdf_report_actual_raw": "999", "manual_actual_value_raw": "214,917"},
    )
    assert ungrounded["resolved_actual_value_raw"] is None


def test_manual_gold_changes_only_offline_evaluation(tmp_path) -> None:
    harness = tmp_path / "harness"
    harness.mkdir()
    candidates = _candidate_rows().iloc[[0]].copy()
    candidates["automation_route"] = "LLM_CANDIDATE"
    candidates["pdf_report_indicator_name"] = "성과지표 A"
    candidates["pdf_report_program_name"] = "프로그램 A"
    candidates["pdf_report_actual_raw"] = "9"
    manual_columns = {
        "manual_indicator_name_report": "성과지표 A",
        "manual_indicator_unit": "%",
        "manual_planned_target_raw": "10",
        "manual_actual_value_raw": "9",
        "manual_official_achievement_rate_raw": "90%",
    }
    for column, value in manual_columns.items():
        candidates[column] = value
    requests, _ = lh.build_request_entries(
        candidates,
        model="gpt-5.6-luna",
        prompt_version="p1",
        schema_version="s1",
        max_evidence_chars=1200,
        max_output_tokens=500,
        expose_local_candidates=False,
    )
    request_id = requests[0]["custom_id"]
    payload = {
        "request_id": request_id,
        "records": [
            {
                "source_indicator_id": "019-2023-1",
                "indicator_name": "성과지표 A",
                "unit": "%",
                "plan_target_raw": None,
                "report_target_raw": "10",
                "actual_value_raw": None,
                "official_achievement_rate_raw": "90%",
                "extraction_status": "EXTRACTED",
                "review_reasons": [],
                "evidence": [
                    {
                        "document_type": "REPORT",
                        "source_file": "report.pdf",
                        "source_page": 7,
                        "quote": "성과지표 A 목표 10 실적 9 달성률 90%",
                    }
                ],
            }
        ],
    }
    (harness / "pilot_requests.jsonl").write_text(
        json.dumps(requests[0], ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    candidates.to_csv(harness / "candidate_rows.csv", index=False)
    (harness / "harness_summary.json").write_text(
        json.dumps({"model": "gpt-5.6-luna"}),
        encoding="utf-8",
    )
    responses = harness / "responses.jsonl"
    responses.write_text(
        json.dumps({"custom_id": request_id, "output": payload}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    first = lh.validate_llm_responses(
        Path("."),
        responses,
        harness_dir=harness,
        output_dir=harness / "first",
    )
    first_runtime_files = [first.output_paths[index].read_bytes() for index in (0, 1, 3)]
    first_gold = json.loads(first.output_paths[5].read_text(encoding="utf-8"))
    first_records = pd.read_csv(first.output_paths[0])
    assert pd.isna(first_records.loc[0, "actual_value_raw"])
    assert str(first_records.loc[0, "resolved_actual_value_raw"]) == "9"
    assert first_records.loc[0, "automatic_correction_status"] == "FILLED_FROM_LOCAL_SOURCE"

    for column in manual_columns:
        candidates[column] = "일부러 바꾼 정답"
    candidates.to_csv(harness / "candidate_rows.csv", index=False)
    second = lh.validate_llm_responses(
        Path("."),
        responses,
        harness_dir=harness,
        output_dir=harness / "second",
    )
    second_runtime_files = [second.output_paths[index].read_bytes() for index in (0, 1, 3)]
    second_gold = json.loads(second.output_paths[5].read_text(encoding="utf-8"))

    candidates.drop(columns=list(manual_columns)).to_csv(
        harness / "candidate_rows.csv", index=False
    )
    no_gold = lh.validate_llm_responses(
        Path("."),
        responses,
        harness_dir=harness,
        output_dir=harness / "no_gold",
    )
    no_gold_runtime_files = [no_gold.output_paths[index].read_bytes() for index in (0, 1, 3)]
    no_gold_evaluation = json.loads(no_gold.output_paths[5].read_text(encoding="utf-8"))

    runtime_keys = {
        "valid_request_count",
        "valid_record_count",
        "strict_valid_record_count",
        "recovered_record_count",
        "failure_count",
        "retry_request_count",
        "retry_record_count",
    }
    assert first_runtime_files == second_runtime_files
    assert first_runtime_files == no_gold_runtime_files
    assert {key: first.summary[key] for key in runtime_keys} == {
        key: second.summary[key] for key in runtime_keys
    }
    assert first.summary["runtime_acceptance_uses_manual_gold"] is False
    assert first_gold["field_accuracy"] != second_gold["field_accuracy"]
    assert no_gold.summary["goldset_evaluation_available"] is False
    assert no_gold_evaluation["field_accuracy"] == {}


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
    assert summary["request_count"] == len(requests) == 34
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


def test_cost_benefit_uses_observed_coverage_and_separates_implementation(tmp_path) -> None:
    harness = tmp_path / "harness"
    validated = harness / "validated_pilot"
    validated.mkdir(parents=True)
    (validated / "validation_summary.json").write_text(
        json.dumps(
            {
                "expected_request_count": 2,
                "expected_record_count": 10,
                "valid_request_rate": 0.5,
                "valid_record_coverage": 0.5,
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 200,
                    "conservative_batch_cost_usd": 0.01,
                },
            }
        ),
        encoding="utf-8",
    )
    config = tmp_path / "economics.yaml"
    config.write_text(
        """scope:
  observed_indicator_count: 10
  observed_years: 1
  exchange_rate_krw_per_usd: 1000
  one_time_implementation_hours: 2
scenarios:
  - name: test
    manual_minutes_per_indicator: 10
    assisted_minutes_per_indicator: 2
    hourly_labor_cost_krw: 60000
    annual_maintenance_hours: 1
""",
        encoding="utf-8",
    )

    summary, paths = build_llm_cost_benefit(
        tmp_path,
        harness_dir=harness,
        config_path=config,
    )
    rows = pd.read_csv(paths[0])
    pilot = rows[(rows["scope"] == "pilot") & (rows["scenario"] == "test")].iloc[0]

    assert summary["measurement"]["retry_multiplier_from_observed_valid_request_rate"] == 2
    assert pilot["api_cost_usd_with_retry"] == pytest.approx(0.02)
    assert pilot["gross_labor_benefit_krw"] == pytest.approx(40000)
    assert pilot["net_recurring_benefit_krw"] == pytest.approx(-20020)
    assert pilot["first_cycle_net_benefit_krw"] == pytest.approx(-140020)
