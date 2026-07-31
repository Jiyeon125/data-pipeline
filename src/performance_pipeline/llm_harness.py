"""로컬 PDF 대조 결과에서 필요한 부분만 OpenAI Batch 요청으로 준비·검증합니다."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import yaml
from dotenv import load_dotenv

LOCAL_CONFIRMED_STATUSES = {"EXACT_MATCH", "MATCH_AFTER_CHANGE"}
LLM_CANDIDATE_STATUSES = {
    "OCR_REQUIRED",
    "VALUE_MISMATCH",
    "AMBIGUOUS",
    "MANUAL_MISSING_PDF_PRESENT",
}
HUMAN_ONLY_STATUSES = {"PDF_MISSING_MANUAL_PRESENT"}
HUMAN_REVIEW_REQUIRED_STATUSES = {
    "AMBIGUOUS",
    "MANUAL_REVIEW",
    "PDF_MISSING_MANUAL_PRESENT",
    "PDF_NOT_FOUND",
}
MODEL_PLACEHOLDER = "MODEL_SELECTION_REQUIRED"

SYSTEM_PROMPT = """정부 성과계획서·성과보고서의 성과지표 값을 검수합니다.
SOURCE_EVIDENCE에 직접 존재하는 값만 추출하세요.
확인되지 않는 값은 null로 반환하고 추정·계산·보간하지 마세요.
원문 인용은 입력에 실제로 있는 짧은 구절만 그대로 사용하세요.
source_indicator_id를 바꾸거나 새 지표를 만들지 마세요.
계획 목표, 보고 목표, 실적, 공식 달성률은 서로 다른 필드입니다.
공식 달성률을 직접 계산한 값으로 대체하지 마세요."""

OUTPUT_FIELDS = (
    "indicator_name",
    "unit",
    "plan_target_raw",
    "report_target_raw",
    "actual_value_raw",
    "official_achievement_rate_raw",
)

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["request_id", "records"],
    "properties": {
        "request_id": {"type": "string"},
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "source_indicator_id",
                    *OUTPUT_FIELDS,
                    "extraction_status",
                    "review_reasons",
                    "evidence",
                ],
                "properties": {
                    "source_indicator_id": {"type": "string"},
                    **{field: {"type": ["string", "null"]} for field in OUTPUT_FIELDS},
                    "extraction_status": {
                        "type": "string",
                        "enum": ["EXTRACTED", "NOT_FOUND", "AMBIGUOUS"],
                    },
                    "review_reasons": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "document_type",
                                "source_file",
                                "source_page",
                                "quote",
                            ],
                            "properties": {
                                "document_type": {
                                    "type": "string",
                                    "enum": ["PLAN", "REPORT", "CHANGE_TABLE"],
                                },
                                "source_file": {"type": ["string", "null"]},
                                "source_page": {"type": ["integer", "null"]},
                                "quote": {"type": ["string", "null"]},
                            },
                        },
                    },
                },
            },
        },
    },
}


class LlmHarnessError(ValueError):
    """LLM 준비·응답 검증 계약이 깨졌을 때 발생합니다."""


@dataclass(frozen=True)
class LlmHarnessResult:
    summary: dict[str, Any]
    output_paths: tuple[Path, ...]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _clean(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, (list, dict, tuple, set)) and pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


def _page(value: Any) -> int | None:
    value = _clean(value)
    return None if value is None else int(value)


def _normalize_grounding_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def estimate_tokens(value: str) -> int:
    """키 없이 쓰는 보수적 근사치입니다. 실제 사용량은 API 응답 usage로 교체합니다."""
    return max(1, math.ceil(len(value) / 2))


def load_llm_config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload.get("llm"), dict) or not isinstance(payload.get("harness"), dict):
        raise LlmHarnessError("configs/llm.yaml에 llm과 harness 설정이 필요합니다.")
    return payload


def _load_project_environment(root: Path) -> None:
    """저장소 `.env`를 읽되 이미 설정된 셸 환경변수는 덮어쓰지 않습니다."""
    load_dotenv(root / ".env", override=False)


def reconciliation_paths(root: Path) -> tuple[Path, ...]:
    base = root / "data/processed/performance/pdf_reconciliation"
    return (
        base / "mss_performance_pdf_reconciliation.parquet",
        base / "ministry_code=019/019_performance_pdf_reconciliation.parquet",
        base / "ministry_code=075/075_performance_pdf_reconciliation.parquet",
        base / "ministry_code=162/162_performance_pdf_reconciliation.parquet",
    )


def load_reconciliation_rows(root: Path) -> pd.DataFrame:
    paths = reconciliation_paths(root)
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(", ".join(str(path) for path in missing))
    frame = pd.concat((pd.read_parquet(path) for path in paths), ignore_index=True)
    frame["ministry_code"] = frame["ministry_code"].astype("string").str.zfill(3)
    if frame["source_indicator_id"].duplicated().any():
        raise LlmHarnessError("4개 부처 PDF 대조표의 source_indicator_id가 중복됩니다.")
    return frame


def classify_rows(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    reviewed = result["review_status"].notna()
    clear_evidence = (
        result["page_evidence_status"].eq("EXACT_MATCH")
        & result["report_source_file"].notna()
        & result["report_split_pdf_page"].notna()
        & result["report_source_text"].notna()
        & ~result["overall_reconciliation_status"].isin(HUMAN_REVIEW_REQUIRED_STATUSES)
    )
    result["evidence_acceptance_status"] = "HUMAN_REVIEW_REQUIRED"
    result["evidence_acceptance_reason"] = (
        "출처·페이지·값 또는 지표 대응을 사람이 원문에서 확인해야 함"
    )
    result.loc[reviewed, "evidence_acceptance_status"] = "HUMAN_CONFIRMED"
    result.loc[reviewed, "evidence_acceptance_reason"] = "기존 원문 육안검수 확정값 보존"
    result.loc[~reviewed & clear_evidence, "evidence_acceptance_status"] = "EVIDENCE_CONFIRMED"
    result.loc[~reviewed & clear_evidence, "evidence_acceptance_reason"] = (
        "파일·페이지·보고서 원문이 연결되고 지표 대응이 비모호함; 수기 기준값은 변경하지 않음"
    )
    result["automation_route"] = "HUMAN_ONLY"
    result.loc[
        result["evidence_acceptance_status"].isin(["HUMAN_CONFIRMED", "EVIDENCE_CONFIRMED"]),
        "automation_route",
    ] = "LOCAL_CONFIRMED"
    return result


def _bundle_key(row: pd.Series) -> tuple[Any, ...]:
    return (
        _clean(row.get("ministry_code")),
        _clean(row.get("fiscal_year")),
        _clean(row.get("plan_source_file")),
        _page(row.get("plan_split_pdf_page")),
        _clean(row.get("report_source_file")),
        _page(row.get("report_split_pdf_page")),
        _clean(row.get("documented_change_source_file")),
        _page(row.get("documented_change_split_pdf_page")),
    )


def _record_input(
    row: pd.Series,
    max_evidence_chars: int,
    *,
    expose_local_candidates: bool = True,
) -> dict[str, Any]:
    plan_text = _normalize_grounding_text(row.get("plan_source_text"))[:max_evidence_chars]
    report_text = _normalize_grounding_text(row.get("report_source_text"))[:max_evidence_chars]
    record = {
        "source_indicator_id": str(row["source_indicator_id"]),
        "ministry_code": str(row["ministry_code"]).zfill(3),
        "fiscal_year": int(row["fiscal_year"]),
        "program_hint": (
            _clean(row.get("performance_program_name"))
            if expose_local_candidates
            else _clean(row.get("pdf_report_program_name"))
            or _clean(row.get("pdf_plan_program_name"))
        ),
        "indicator_hint": (
            _clean(row.get("manual_indicator_name_report"))
            or _clean(row.get("manual_indicator_name_plan"))
            if expose_local_candidates
            else _clean(row.get("pdf_report_indicator_name"))
            or _clean(row.get("pdf_plan_indicator_name"))
        ),
        "source_evidence": [
            {
                "document_type": "PLAN",
                "source_file": _clean(row.get("plan_source_file")),
                "source_page": _page(row.get("plan_split_pdf_page")),
                "text": plan_text or None,
            },
            {
                "document_type": "REPORT",
                "source_file": _clean(row.get("report_source_file")),
                "source_page": _page(row.get("report_split_pdf_page")),
                "text": report_text or None,
            },
            {
                "document_type": "CHANGE_TABLE",
                "source_file": _clean(row.get("documented_change_source_file")),
                "source_page": _page(row.get("documented_change_split_pdf_page")),
                "text": _normalize_grounding_text(
                    " | ".join(
                        str(value)
                        for value in (
                            _clean(row.get("documented_change_target_before_raw")),
                            _clean(row.get("documented_change_target_after_raw")),
                            _clean(row.get("documented_change_reason_raw")),
                        )
                        if value is not None
                    )
                )
                or None,
            },
        ],
    }
    if expose_local_candidates:
        record["local_pdf_candidates"] = {
            "indicator_name": _clean(row.get("pdf_report_indicator_name"))
            or _clean(row.get("pdf_plan_indicator_name")),
            "unit": _clean(row.get("pdf_report_unit")) or _clean(row.get("pdf_plan_unit")),
            "plan_target_raw": _clean(row.get("pdf_plan_target_raw")),
            "change_target_before_raw": _clean(row.get("documented_change_target_before_raw")),
            "change_target_after_raw": _clean(row.get("documented_change_target_after_raw")),
            "report_target_raw": _clean(row.get("pdf_report_target_raw")),
            "actual_value_raw": _clean(row.get("pdf_report_actual_raw")),
            "official_achievement_rate_raw": _clean(
                row.get("pdf_report_official_achievement_rate_raw")
            ),
        }
        record["local_status"] = str(row["overall_reconciliation_status"])
        record["local_review_reason"] = _clean(row.get("review_reason"))
    return record


def build_request_entries(
    candidates: pd.DataFrame,
    *,
    model: str,
    prompt_version: str,
    schema_version: str,
    max_evidence_chars: int,
    max_output_tokens: int,
    reasoning_effort: str = "low",
    expose_local_candidates: bool = True,
) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    rows = candidates.loc[candidates["automation_route"].eq("LLM_CANDIDATE")].copy()
    rows["bundle_key"] = rows.apply(_bundle_key, axis=1)
    requests: list[dict[str, Any]] = []
    index_rows: list[dict[str, Any]] = []
    for _, group in rows.groupby("bundle_key", sort=True, dropna=False):
        local_status_by_id = {
            str(row["source_indicator_id"]): str(row["overall_reconciliation_status"])
            for _, row in group.iterrows()
        }
        records = [
            _record_input(
                row,
                max_evidence_chars,
                expose_local_candidates=expose_local_candidates,
            )
            for _, row in group.sort_values("source_indicator_id").iterrows()
        ]
        content = {
            "task": "validate_performance_indicator_extraction",
            "records": records,
        }
        request_seed = (
            prompt_version + schema_version + model + reasoning_effort + _json_text(content)
        ).encode("utf-8")
        request_id = "perf-" + _sha256_bytes(request_seed)[:24]
        content["request_id"] = request_id
        content_text = _json_text(content)
        body = {
            "model": model,
            "store": False,
            "reasoning": {"effort": reasoning_effort},
            "input": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content_text},
            ],
            "max_output_tokens": max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "performance_indicator_extraction",
                    "strict": True,
                    "schema": OUTPUT_SCHEMA,
                }
            },
        }
        entry = {
            "custom_id": request_id,
            "method": "POST",
            "url": "/v1/responses",
            "body": body,
        }
        requests.append(entry)
        serialized = _json_text(entry)
        for record in records:
            index_rows.append(
                {
                    "request_id": request_id,
                    "source_indicator_id": record["source_indicator_id"],
                    "ministry_code": record["ministry_code"],
                    "fiscal_year": record["fiscal_year"],
                    "local_status": local_status_by_id[record["source_indicator_id"]],
                    "input_token_estimate": estimate_tokens(serialized),
                    "cache_key": _sha256_bytes(request_seed),
                    "model": model,
                    "reasoning_effort": reasoning_effort,
                }
            )
    columns = [
        "request_id",
        "source_indicator_id",
        "ministry_code",
        "fiscal_year",
        "local_status",
        "input_token_estimate",
        "cache_key",
        "model",
        "reasoning_effort",
    ]
    return requests, pd.DataFrame(index_rows, columns=columns).convert_dtypes()


def _pilot_request_ids(request_index: pd.DataFrame, limit: int) -> set[str]:
    if request_index.empty:
        return set()
    unique = (
        request_index[["request_id", "ministry_code", "fiscal_year", "local_status"]]
        .drop_duplicates("request_id")
        .sort_values(
            ["ministry_code", "fiscal_year", "local_status", "request_id"],
            kind="stable",
        )
    )
    strata = [
        group["request_id"].astype(str).tolist()
        for _, group in unique.groupby(["ministry_code", "fiscal_year"], sort=True)
    ]
    selected: list[str] = []
    while len(selected) < limit and any(strata):
        for group in strata:
            if group and len(selected) < limit:
                selected.append(group.pop(0))
    return set(selected)


def _cost_scenarios(
    request_entries: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    serialized = [_json_text(entry) for entry in request_entries]
    input_tokens = sum(estimate_tokens(value) for value in serialized)
    expected_output_tokens = len(request_entries) * int(
        config["harness"]["estimated_output_tokens_per_request"]
    )
    maximum_output_tokens = len(request_entries) * int(config["harness"]["max_output_tokens"])
    batch_discount = float(config["harness"].get("batch_discount", 0.5))
    prices = config["harness"].get("pricing_usd_per_million", {})
    scenarios: dict[str, Any] = {}
    for model, price in prices.items():
        expected_synchronous = (
            input_tokens * float(price["input"]) / 1_000_000
            + expected_output_tokens * float(price["output"]) / 1_000_000
        )
        maximum_synchronous = (
            input_tokens * float(price["input"]) / 1_000_000
            + maximum_output_tokens * float(price["output"]) / 1_000_000
        )
        scenarios[str(model)] = {
            "input_tokens_estimate": input_tokens,
            "output_tokens_estimate": expected_output_tokens,
            "maximum_output_tokens": maximum_output_tokens,
            "expected_synchronous_usd_estimate": expected_synchronous,
            "expected_batch_usd_estimate": expected_synchronous * batch_discount,
            "synchronous_usd_estimate": maximum_synchronous,
            "batch_usd_estimate": maximum_synchronous * batch_discount,
        }
    return {
        "token_estimation_method": "ceil(serialized_unicode_chars/2)",
        "actual_usage_required_after_pilot": True,
        "cost_gate_basis": "maximum_output_tokens",
        "batch_discount_assumption": batch_discount,
        "pricing_checked_on": config["harness"].get("pricing_checked_on"),
        "pricing_source": config["harness"].get("pricing_source"),
        "models": scenarios,
    }


def prepare_llm_harness(
    root: Path,
    *,
    model: str | None = None,
    output_dir: Path | None = None,
    overwrite: bool = False,
) -> LlmHarnessResult:
    root = root.resolve()
    _load_project_environment(root)
    config_path = root / "configs/llm.yaml"
    config = load_llm_config(config_path)
    model_env = str(config["llm"]["model_env"])
    selected_model = (
        model
        or os.getenv(model_env)
        or str(config["llm"].get("default_model") or MODEL_PLACEHOLDER)
    )
    output_dir = output_dir or root / "data/interim/llm_harness"
    targets = (
        output_dir / "candidate_rows.csv",
        output_dir / "request_index.csv",
        output_dir / "batch_requests.jsonl",
        output_dir / "pilot_requests.jsonl",
        output_dir / "remaining_requests.jsonl",
        output_dir / "performance_indicator_schema.json",
        output_dir / "human_review_queue.csv",
        output_dir / "human_review_queue.xlsx",
        output_dir / "harness_summary.json",
    )
    existing = [path for path in targets if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(", ".join(str(path) for path in existing))

    source_rows = load_reconciliation_rows(root)
    candidates = classify_rows(source_rows)
    harness = config["harness"]
    requests, request_index = build_request_entries(
        candidates,
        model=selected_model,
        prompt_version=str(config["llm"]["prompt_version"]),
        schema_version=str(config["llm"]["schema_version"]),
        max_evidence_chars=int(harness["max_evidence_chars"]),
        max_output_tokens=int(harness["max_output_tokens"]),
        reasoning_effort=str(config["llm"].get("reasoning_effort", "low")),
    )
    pilot_ids = _pilot_request_ids(
        request_index,
        int(harness["pilot_request_limit"]),
    )
    pilot_requests = [request for request in requests if request["custom_id"] in pilot_ids]
    remaining_requests = [request for request in requests if request["custom_id"] not in pilot_ids]
    human_queue = candidates.loc[
        candidates["automation_route"].isin(["LLM_CANDIDATE", "HUMAN_ONLY"]),
        [
            "source_indicator_id",
            "ministry_code",
            "fiscal_year",
            "performance_program_name",
            "manual_indicator_name_report",
            "overall_reconciliation_status",
            "review_reason",
            "review_instruction",
            "automation_route",
            "evidence_acceptance_status",
            "evidence_acceptance_reason",
            "page_evidence_status",
            "manual_planned_target_raw",
            "manual_actual_value_raw",
            "manual_official_achievement_rate_raw",
            "pdf_plan_target_raw",
            "pdf_report_target_raw",
            "pdf_report_actual_raw",
            "pdf_report_official_achievement_rate_raw",
            "plan_source_file",
            "plan_split_pdf_page",
            "report_source_file",
            "report_split_pdf_page",
        ],
    ].copy()
    human_queue["llm_validation_status"] = "NOT_RUN"
    human_queue["human_review_status"] = "PENDING"

    output_dir.mkdir(parents=True, exist_ok=True)
    candidates.to_csv(targets[0], index=False, encoding="utf-8-sig")
    request_index.to_csv(targets[1], index=False, encoding="utf-8-sig")
    targets[2].write_text(
        "".join(_json_text(request) + "\n" for request in requests),
        encoding="utf-8",
    )
    targets[3].write_text(
        "".join(_json_text(request) + "\n" for request in pilot_requests),
        encoding="utf-8",
    )
    targets[4].write_text(
        "".join(_json_text(request) + "\n" for request in remaining_requests),
        encoding="utf-8",
    )
    targets[5].write_text(
        json.dumps(OUTPUT_SCHEMA, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    human_queue.to_csv(targets[6], index=False, encoding="utf-8-sig")
    human_queue.to_excel(targets[7], index=False)
    source_paths = reconciliation_paths(root)
    status = (
        "NO_LLM_CALL_REQUIRED"
        if not requests
        else (
            "READY_FOR_MODEL_SELECTION"
            if selected_model == MODEL_PLACEHOLDER
            else "READY_FOR_API_APPROVAL"
        )
    )
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "api_called": False,
        "api_ready": bool(requests) and selected_model != MODEL_PLACEHOLDER,
        "model": selected_model,
        "reasoning_effort": str(config["llm"].get("reasoning_effort", "low")),
        "source_rows": len(candidates),
        "route_counts": {
            str(key): int(value)
            for key, value in candidates["automation_route"].value_counts().items()
        },
        "evidence_acceptance_counts": {
            str(key): int(value)
            for key, value in candidates["evidence_acceptance_status"].value_counts().items()
        },
        "llm_candidate_rows": int(candidates["automation_route"].eq("LLM_CANDIDATE").sum()),
        "human_only_rows": int(candidates["automation_route"].eq("HUMAN_ONLY").sum()),
        "request_count": len(requests),
        "request_row_count": len(request_index),
        "pilot_request_count": len(pilot_requests),
        "pilot_row_count": int(request_index["request_id"].isin(pilot_ids).sum()),
        "remaining_request_count": len(remaining_requests),
        "request_grouping": (
            "ministry, year, plan file/page, report file/page, change-table file/page; "
            "multiple indicators on the same evidence bundle share one request"
        ),
        "cost": _cost_scenarios(requests, config),
        "pilot_cost": _cost_scenarios(pilot_requests, config),
        "validation_contract": {
            "strict_json_schema": True,
            "source_indicator_id_exact": True,
            "evidence_file_page_allowlist": True,
            "evidence_quote_grounding": True,
            "unverified_values_null": True,
            "human_review_required": True,
        },
        "source_sha256": {str(path.relative_to(root)): _sha256_file(path) for path in source_paths},
    }
    targets[8].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return LlmHarnessResult(summary=summary, output_paths=targets)


def prepare_mss_masked_goldset_pilot(
    root: Path,
    *,
    model: str | None = None,
    output_dir: Path | None = None,
    overwrite: bool = False,
) -> LlmHarnessResult:
    """중기부 수기 정답값을 요청에서 가린 1차 필드 추출 파일럿을 준비합니다."""
    root = root.resolve()
    _load_project_environment(root)
    config = load_llm_config(root / "configs/llm.yaml")
    selected_model = (
        model
        or os.getenv(str(config["llm"]["model_env"]))
        or str(config["llm"].get("default_model") or MODEL_PLACEHOLDER)
    )
    output_dir = output_dir or root / "data/interim/llm_harness/mss_masked_pilot"
    targets = (
        output_dir / "candidate_rows.csv",
        output_dir / "request_index.csv",
        output_dir / "batch_requests.jsonl",
        output_dir / "pilot_requests.jsonl",
        output_dir / "remaining_requests.jsonl",
        output_dir / "performance_indicator_schema.json",
        output_dir / "harness_summary.json",
    )
    existing = [path for path in targets if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(", ".join(str(path) for path in existing))

    source_path = (
        root
        / "data/processed/performance/pdf_reconciliation/mss_performance_pdf_reconciliation.parquet"
    )
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    source_rows = pd.read_parquet(source_path)
    source_rows["ministry_code"] = source_rows["ministry_code"].astype("string").str.zfill(3)
    if source_rows["source_indicator_id"].duplicated().any():
        raise LlmHarnessError("중기부 PDF 대조표의 source_indicator_id가 중복됩니다.")

    local_hint = source_rows["pdf_report_indicator_name"].fillna(
        source_rows["pdf_plan_indicator_name"]
    )
    evidence_ready = source_rows["plan_source_text"].astype("string").str.strip().ne("").fillna(
        False
    ) & source_rows["report_source_text"].astype("string").str.strip().ne("").fillna(False)
    label_ready = (
        source_rows[
            [
                "manual_planned_target_raw",
                "manual_actual_value_raw",
                "manual_official_achievement_rate_raw",
            ]
        ]
        .notna()
        .any(axis=1)
    )
    eligible = source_rows.loc[
        local_hint.astype("string").str.strip().ne("").fillna(False) & evidence_ready & label_ready
    ].copy()
    eligible["automation_route"] = "LLM_CANDIDATE"

    harness = config["harness"]
    requests, request_index = build_request_entries(
        eligible,
        model=selected_model,
        prompt_version=str(config["llm"]["prompt_version"]),
        schema_version=str(config["llm"]["schema_version"]),
        max_evidence_chars=int(harness["max_evidence_chars"]),
        max_output_tokens=int(harness["max_output_tokens"]),
        reasoning_effort=str(config["llm"].get("reasoning_effort", "low")),
        expose_local_candidates=False,
    )
    pilot_ids = _pilot_request_ids(request_index, int(harness["pilot_request_limit"]))
    pilot_requests = [request for request in requests if request["custom_id"] in pilot_ids]
    pilot_index = request_index.loc[request_index["request_id"].isin(pilot_ids)].copy()
    pilot_source_ids = set(pilot_index["source_indicator_id"].astype(str))
    pilot_candidates = eligible.loc[
        eligible["source_indicator_id"].astype(str).isin(pilot_source_ids)
    ].copy()
    forbidden_request_keys = {
        "local_pdf_candidates",
        "local_status",
        "local_review_reason",
    }
    for request in pilot_requests:
        content = json.loads(request["body"]["input"][1]["content"])
        if any(forbidden_request_keys & set(record) for record in content["records"]):
            raise LlmHarnessError("가린 골드셋 요청에 로컬 정답 후보가 포함됐습니다.")

    output_dir.mkdir(parents=True, exist_ok=True)
    pilot_candidates.to_csv(targets[0], index=False, encoding="utf-8-sig")
    pilot_index.to_csv(targets[1], index=False, encoding="utf-8-sig")
    request_text = "".join(_json_text(request) + "\n" for request in pilot_requests)
    targets[2].write_text(request_text, encoding="utf-8")
    targets[3].write_text(request_text, encoding="utf-8")
    targets[4].write_text("", encoding="utf-8")
    targets[5].write_text(
        json.dumps(OUTPUT_SCHEMA, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    cost = _cost_scenarios(pilot_requests, config)
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "READY_FOR_API_APPROVAL",
        "pilot_type": "KNOWN_INDICATOR_MASKED_VALUE_EXTRACTION",
        "api_called": False,
        "api_ready": bool(pilot_requests) and selected_model != MODEL_PLACEHOLDER,
        "api_execution_allowed": bool(config["llm"].get("api_execution_allowed", False)),
        "model": selected_model,
        "reasoning_effort": str(config["llm"].get("reasoning_effort", "low")),
        "source_rows": len(source_rows),
        "eligible_rows": len(eligible),
        "eligible_request_count": len(requests),
        "request_count": len(pilot_requests),
        "request_row_count": len(pilot_index),
        "year_counts": {
            str(key): int(value)
            for key, value in pilot_candidates["fiscal_year"].value_counts().sort_index().items()
        },
        "local_status_counts": {
            str(key): int(value)
            for key, value in pilot_candidates["overall_reconciliation_status"]
            .value_counts()
            .items()
        },
        "masked_input_contract": {
            "manual_label_keys_in_request": False,
            "local_value_candidates_in_request": False,
            "local_pdf_indicator_locator_exposed": True,
            "source_evidence_exposed": True,
            "full_row_discovery_tested": False,
        },
        "cost": cost,
        "pilot_cost": cost,
        "validation_contract": {
            "strict_json_schema": True,
            "source_indicator_id_exact": True,
            "evidence_file_page_allowlist": True,
            "evidence_quote_grounding": True,
            "field_accuracy_against_local_goldset": True,
            "promotion_allowed_before_human_review": False,
        },
        "source_sha256": {str(source_path.relative_to(root)): _sha256_file(source_path)},
    }
    targets[6].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return LlmHarnessResult(summary=summary, output_paths=targets)


def _response_text(line: dict[str, Any]) -> str:
    if isinstance(line.get("output"), dict):
        return _json_text(line["output"])
    response = line.get("response") or {}
    if int(response.get("status_code", 0)) != 200:
        raise LlmHarnessError(f"응답 상태코드 오류: {response.get('status_code')}")
    body = response.get("body") or {}
    for item in body.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "refusal":
                raise LlmHarnessError(f"모델 거절: {content.get('refusal')}")
            if content.get("type") == "output_text":
                return str(content["text"])
    raise LlmHarnessError("Responses API 응답에 output_text가 없습니다.")


def _usage_summary(
    response_lines: list[dict[str, Any]],
    *,
    model: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    input_tokens = 0
    cached_tokens = 0
    output_tokens = 0
    for line in response_lines:
        usage = ((line.get("response") or {}).get("body") or {}).get("usage") or {}
        input_tokens += int(usage.get("input_tokens", 0))
        output_tokens += int(usage.get("output_tokens", 0))
        cached_tokens += int((usage.get("input_tokens_details") or {}).get("cached_tokens", 0))
    price = config["harness"].get("pricing_usd_per_million", {}).get(model)
    conservative_batch_cost = None
    if price:
        conservative_batch_cost = float(config["harness"].get("batch_discount", 0.5)) * (
            input_tokens * float(price["input"]) / 1_000_000
            + output_tokens * float(price["output"]) / 1_000_000
        )
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "conservative_batch_cost_usd": conservative_batch_cost,
        "cost_note": "캐시 중복할인을 가정하지 않은 Batch 상한 추정; 실제 청구액과 대조 필요",
    }


def _request_context(entry: dict[str, Any]) -> tuple[set[str], dict[str, set[Any]], str]:
    body = entry["body"]
    user_content = json.loads(body["input"][1]["content"])
    indicator_ids = {str(record["source_indicator_id"]) for record in user_content["records"]}
    allowed: dict[str, set[Any]] = {}
    grounding: list[str] = []
    for record in user_content["records"]:
        for evidence in record["source_evidence"]:
            source_file = evidence.get("source_file")
            if source_file:
                allowed.setdefault(str(source_file), set()).add(evidence.get("source_page"))
            grounding.append(str(evidence.get("text") or ""))
    return indicator_ids, allowed, _normalize_grounding_text(" ".join(grounding))


def validate_extraction_payload(
    payload: dict[str, Any],
    *,
    request_id: str,
    expected_ids: set[str],
    allowed_sources: dict[str, set[Any]],
    grounding_text: str,
) -> list[dict[str, Any]]:
    if set(payload) != {"request_id", "records"} or payload["request_id"] != request_id:
        raise LlmHarnessError("응답 request_id 또는 최상위 필드가 요청과 다릅니다.")
    if not isinstance(payload["records"], list):
        raise LlmHarnessError("응답 records는 배열이어야 합니다.")
    records = payload["records"]
    ids = [str(record.get("source_indicator_id")) for record in records]
    if len(ids) != len(set(ids)) or set(ids) != expected_ids:
        raise LlmHarnessError("응답 source_indicator_id 집합이 요청과 다릅니다.")
    required = {
        "source_indicator_id",
        *OUTPUT_FIELDS,
        "extraction_status",
        "review_reasons",
        "evidence",
    }
    for record in records:
        if set(record) != required:
            raise LlmHarnessError("응답 레코드의 필드 집합이 스키마와 다릅니다.")
        if not isinstance(record["source_indicator_id"], str):
            raise LlmHarnessError("source_indicator_id는 문자열이어야 합니다.")
        if any(
            record[field] is not None and not isinstance(record[field], str)
            for field in OUTPUT_FIELDS
        ):
            raise LlmHarnessError("추출값은 문자열 또는 null이어야 합니다.")
        if record["extraction_status"] not in {"EXTRACTED", "NOT_FOUND", "AMBIGUOUS"}:
            raise LlmHarnessError("허용되지 않은 extraction_status입니다.")
        if not isinstance(record["review_reasons"], list) or not isinstance(
            record["evidence"], list
        ):
            raise LlmHarnessError("review_reasons와 evidence는 배열이어야 합니다.")
        if any(not isinstance(reason, str) for reason in record["review_reasons"]):
            raise LlmHarnessError("review_reasons의 원소는 문자열이어야 합니다.")
        if record["extraction_status"] == "EXTRACTED" and all(
            record[field] is None for field in OUTPUT_FIELDS
        ):
            raise LlmHarnessError("EXTRACTED 레코드의 추출값이 모두 null입니다.")
        for evidence in record["evidence"]:
            if set(evidence) != {
                "document_type",
                "source_file",
                "source_page",
                "quote",
            }:
                raise LlmHarnessError("근거 필드 집합이 스키마와 다릅니다.")
            if evidence["document_type"] not in {"PLAN", "REPORT", "CHANGE_TABLE"}:
                raise LlmHarnessError("허용되지 않은 document_type입니다.")
            source_file = evidence["source_file"]
            source_page = evidence["source_page"]
            quote_raw = evidence["quote"]
            if source_file is not None and not isinstance(source_file, str):
                raise LlmHarnessError("근거 source_file은 문자열 또는 null이어야 합니다.")
            if source_page is not None and (
                not isinstance(source_page, int) or isinstance(source_page, bool)
            ):
                raise LlmHarnessError("근거 source_page는 정수 또는 null이어야 합니다.")
            if quote_raw is not None and not isinstance(quote_raw, str):
                raise LlmHarnessError("근거 quote는 문자열 또는 null이어야 합니다.")
            if source_file is not None and (
                source_file not in allowed_sources
                or source_page not in allowed_sources[source_file]
            ):
                raise LlmHarnessError("응답 근거 파일·페이지가 요청 허용목록 밖입니다.")
            quote = _normalize_grounding_text(quote_raw)
            if quote and quote not in grounding_text:
                raise LlmHarnessError("응답 근거 인용이 입력 원문에 없습니다.")
    return records


def _comparison_equal(actual: Any, expected: Any) -> bool:
    if actual is None or pd.isna(actual):
        return expected is None or pd.isna(expected)
    if expected is None or pd.isna(expected):
        return False
    left = re.sub(r"[,\s%]", "", str(actual))
    right = re.sub(r"[,\s%]", "", str(expected))
    try:
        return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-9)
    except ValueError:
        return left.casefold() == right.casefold()


def validate_llm_responses(
    root: Path,
    responses_path: Path,
    *,
    request_set: str = "pilot",
    harness_dir: Path | None = None,
    output_dir: Path | None = None,
    overwrite: bool = False,
) -> LlmHarnessResult:
    root = root.resolve()
    harness_dir = harness_dir or root / "data/interim/llm_harness"
    if request_set not in {"pilot", "remaining", "all"}:
        raise LlmHarnessError("request_set은 pilot, remaining 또는 all이어야 합니다.")
    request_filename = (
        "batch_requests.jsonl" if request_set == "all" else f"{request_set}_requests.jsonl"
    )
    output_dir = output_dir or harness_dir / f"validated_{request_set}"
    requests_path = harness_dir / request_filename
    candidates_path = harness_dir / "candidate_rows.csv"
    for path in (requests_path, candidates_path, responses_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    targets = (
        output_dir / "validated_records.csv",
        output_dir / "validation_failures.csv",
        output_dir / "human_review_queue.csv",
        output_dir / "retry_requests.jsonl",
        output_dir / "validation_summary.json",
    )
    existing = [path for path in targets if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(", ".join(str(path) for path in existing))

    requests = {
        entry["custom_id"]: entry
        for entry in (
            json.loads(line)
            for line in requests_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    response_lines = [
        json.loads(line)
        for line in responses_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    response_ids = [str(line.get("custom_id", "")) for line in response_lines]
    duplicate_response_ids = {
        request_id for request_id in response_ids if response_ids.count(request_id) > 1
    }
    validated: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for line in response_lines:
        request_id = str(line.get("custom_id", ""))
        if request_id in duplicate_response_ids:
            failures.append({"request_id": request_id, "error": "DUPLICATE_RESPONSE_ID"})
            continue
        entry = requests.get(request_id)
        if entry is None:
            failures.append({"request_id": request_id, "error": "UNKNOWN_REQUEST_ID"})
            continue
        try:
            expected_ids, allowed_sources, grounding_text = _request_context(entry)
            payload = json.loads(_response_text(line))
            records = validate_extraction_payload(
                payload,
                request_id=request_id,
                expected_ids=expected_ids,
                allowed_sources=allowed_sources,
                grounding_text=grounding_text,
            )
            validated.extend({"request_id": request_id, **record} for record in records)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            failures.append(
                {
                    "request_id": request_id,
                    "error": exc.__class__.__name__,
                    "detail": str(exc),
                }
            )

    records = pd.DataFrame(validated)
    failures_df = pd.DataFrame(failures)
    candidates = pd.read_csv(
        candidates_path,
        dtype={"ministry_code": "string", "source_program_code": "string"},
        low_memory=False,
    )
    expected_source_ids = set()
    for entry in requests.values():
        expected_source_ids.update(_request_context(entry)[0])
    if records.empty:
        review = candidates.loc[
            candidates["automation_route"].isin(["LLM_CANDIDATE", "HUMAN_ONLY"])
        ].copy()
        field_accuracy: dict[str, Any] = {}
    else:
        review = candidates.loc[
            candidates["automation_route"].isin(["LLM_CANDIDATE", "HUMAN_ONLY"])
        ].merge(
            records,
            on="source_indicator_id",
            how="left",
            validate="one_to_one",
            suffixes=("_local", "_llm"),
        )
        expected_columns = {
            "indicator_name": "manual_indicator_name_report",
            "unit": "manual_indicator_unit",
            "plan_target_raw": "manual_planned_target_raw",
            "actual_value_raw": "manual_actual_value_raw",
            "official_achievement_rate_raw": "manual_official_achievement_rate_raw",
        }
        field_accuracy = {}
        for field, expected_column in expected_columns.items():
            comparison = review.apply(
                lambda row, field=field, expected_column=expected_column: _comparison_equal(
                    row.get(field), row.get(expected_column)
                ),
                axis=1,
            )
            returned = review["request_id"].notna()
            available = returned & (review[field].notna() | review[expected_column].notna())
            field_accuracy[field] = {
                "compared": int(available.sum()),
                "correct": int((comparison & available).sum()),
                "accuracy": (
                    float((comparison & available).sum() / available.sum())
                    if available.any()
                    else None
                ),
            }
        review["human_review_status"] = "PENDING"
        review["llm_validation_status"] = "NOT_IN_THIS_REQUEST_SET"
        review.loc[
            review["source_indicator_id"].isin(expected_source_ids),
            "llm_validation_status",
        ] = "NO_VALID_RESPONSE"
        review.loc[
            review["request_id"].notna(),
            "llm_validation_status",
        ] = "SCHEMA_AND_GROUNDING_PASS"

    output_dir.mkdir(parents=True, exist_ok=True)
    records.to_csv(targets[0], index=False, encoding="utf-8-sig")
    failures_df.to_csv(targets[1], index=False, encoding="utf-8-sig")
    review.to_csv(targets[2], index=False, encoding="utf-8-sig")
    expected_request_ids = set(requests)
    returned_request_ids = set(response_ids)
    failed_request_ids = set(failures_df.get("request_id", pd.Series(dtype="string")))
    retry_request_ids = (expected_request_ids - returned_request_ids) | (
        failed_request_ids & expected_request_ids
    )
    targets[3].write_text(
        "".join(
            _json_text(requests[request_id]) + "\n" for request_id in sorted(retry_request_ids)
        ),
        encoding="utf-8",
    )
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "api_called_by_validator": False,
        "request_set": request_set,
        "expected_request_count": len(expected_request_ids),
        "returned_request_count": len(returned_request_ids),
        "missing_request_count": len(expected_request_ids - returned_request_ids),
        "unknown_request_count": len(returned_request_ids - expected_request_ids),
        "valid_record_count": len(records),
        "failure_count": len(failures_df),
        "retry_request_count": len(retry_request_ids),
        "retry_submission_allowed": False,
        "usage": _usage_summary(
            response_lines,
            model=str(
                json.loads((harness_dir / "harness_summary.json").read_text(encoding="utf-8"))[
                    "model"
                ]
            ),
            config=load_llm_config(root / "configs/llm.yaml"),
        ),
        "field_accuracy": field_accuracy,
        "promotion_allowed": False,
        "promotion_rule": "사람 검수 승인 전에는 수기 기준선을 덮어쓰지 않음",
    }
    targets[4].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return LlmHarnessResult(summary=summary, output_paths=targets)


def submit_batch(
    root: Path,
    *,
    max_approved_cost_usd: float,
    request_set: str = "pilot",
    harness_dir: Path | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """명시적 설정·키·비용승인이 모두 있을 때만 Batch를 제출합니다."""
    root = root.resolve()
    _load_project_environment(root)
    config = load_llm_config(root / "configs/llm.yaml")
    if not bool(config["llm"].get("api_execution_allowed", False)):
        raise LlmHarnessError("configs/llm.yaml의 api_execution_allowed가 false입니다.")
    key = os.getenv(str(config["llm"]["api_key_env"]))
    if not key:
        raise LlmHarnessError("OpenAI API 키 환경변수가 없습니다.")
    harness_dir = harness_dir or root / "data/interim/llm_harness"
    if not harness_dir.is_absolute():
        harness_dir = root / harness_dir
    summary = json.loads((harness_dir / "harness_summary.json").read_text(encoding="utf-8"))
    if not summary["api_ready"]:
        raise LlmHarnessError("모델 선택 후 하네스를 다시 생성해야 합니다.")
    model = str(summary["model"])
    if request_set not in {"pilot", "remaining"}:
        raise LlmHarnessError("request_set은 pilot 또는 remaining이어야 합니다.")
    cost_key = "pilot_cost" if request_set == "pilot" else "cost"
    estimate = summary[cost_key]["models"].get(model)
    if estimate is None:
        raise LlmHarnessError("선택 모델의 검증된 가격 설정이 없습니다.")
    estimated_cost = float(estimate["batch_usd_estimate"])
    if request_set == "remaining":
        pilot_estimate = summary["pilot_cost"]["models"][model]
        estimated_cost -= float(pilot_estimate["batch_usd_estimate"])
    project_limit = float(config["harness"]["max_build_qa_cost_usd"])
    if estimated_cost > project_limit or estimated_cost > max_approved_cost_usd:
        raise LlmHarnessError(
            f"예상 Batch 비용 ${estimated_cost:.4f}가 승인·프로젝트 상한을 넘습니다."
        )
    state_path = harness_dir / f"batch_state_{request_set}.json"
    if state_path.exists():
        raise LlmHarnessError(
            f"{state_path.name}이 이미 있습니다. 기존 Batch 상태를 먼저 확인하세요."
        )

    owns_client = client is None
    client = client or httpx.Client(
        base_url="https://api.openai.com",
        headers={"Authorization": f"Bearer {key}"},
        timeout=float(config["llm"]["request_timeout_seconds"]),
    )
    try:
        batch_path = harness_dir / f"{request_set}_requests.jsonl"
        with batch_path.open("rb") as handle:
            upload = client.post(
                "/v1/files",
                data={"purpose": "batch"},
                files={"file": (batch_path.name, handle, "application/jsonl")},
            )
        upload.raise_for_status()
        file_id = upload.json()["id"]
        created = client.post(
            "/v1/batches",
            json={
                "input_file_id": file_id,
                "endpoint": "/v1/responses",
                "completion_window": "24h",
                "metadata": {
                    "baseline_id": "manual-v1-20260731",
                    "request_set": request_set,
                },
            },
        )
        created.raise_for_status()
        state = {
            "submitted_at": datetime.now(UTC).isoformat(),
            "estimated_batch_cost_usd": estimated_cost,
            "request_set": request_set,
            "input_file_id": file_id,
            "batch": created.json(),
        }
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return state
    finally:
        if owns_client:
            client.close()


def fetch_batch_results(
    root: Path,
    *,
    request_set: str = "pilot",
    harness_dir: Path | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """한 번 상태를 확인하고 완료된 결과·오류 파일만 로컬에 저장합니다."""
    root = root.resolve()
    _load_project_environment(root)
    config = load_llm_config(root / "configs/llm.yaml")
    key = os.getenv(str(config["llm"]["api_key_env"]))
    if not key:
        raise LlmHarnessError("OpenAI API 키 환경변수가 없습니다.")
    harness_dir = harness_dir or root / "data/interim/llm_harness"
    if not harness_dir.is_absolute():
        harness_dir = root / harness_dir
    if request_set not in {"pilot", "remaining"}:
        raise LlmHarnessError("request_set은 pilot 또는 remaining이어야 합니다.")
    state_path = harness_dir / f"batch_state_{request_set}.json"
    if not state_path.is_file():
        raise FileNotFoundError(state_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    batch_id = str((state.get("batch") or {}).get("id", ""))
    if not batch_id:
        raise LlmHarnessError("batch_state.json에 Batch ID가 없습니다.")

    owns_client = client is None
    client = client or httpx.Client(
        base_url="https://api.openai.com",
        headers={"Authorization": f"Bearer {key}"},
        timeout=float(config["llm"]["request_timeout_seconds"]),
    )
    try:
        response = client.get(f"/v1/batches/{batch_id}")
        response.raise_for_status()
        batch = response.json()
        downloads: dict[str, str] = {}
        for file_field, filename in (
            ("output_file_id", "batch_responses.jsonl"),
            ("error_file_id", "batch_errors.jsonl"),
        ):
            file_id = batch.get(file_field)
            if not file_id:
                continue
            content = client.get(f"/v1/files/{file_id}/content")
            content.raise_for_status()
            destination = harness_dir / f"{request_set}_{filename}"
            destination.write_bytes(content.content)
            downloads[file_field] = str(destination)
        state["last_checked_at"] = datetime.now(UTC).isoformat()
        state["batch"] = batch
        state["downloads"] = downloads
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "batch_id": batch_id,
            "request_set": request_set,
            "status": batch.get("status"),
            "request_counts": batch.get("request_counts"),
            "downloads": downloads,
        }
    finally:
        if owns_client:
            client.close()
