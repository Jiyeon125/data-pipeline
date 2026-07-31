from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


def build_llm_cost_benefit(
    root: Path,
    *,
    harness_dir: Path | None = None,
    config_path: Path | None = None,
    output_dir: Path | None = None,
) -> tuple[dict[str, Any], tuple[Path, Path]]:
    """실측 API 비용과 명시적 시간 가정으로 순편익 민감도를 만듭니다."""
    root = root.resolve()
    harness_dir = harness_dir or root / "data/interim/llm_harness/mss_masked_pilot"
    config_path = config_path or root / "configs/llm_cost_benefit.yaml"
    output_dir = output_dir or root / "data/analytics/llm_pilot_cost_benefit"
    if not harness_dir.is_absolute():
        harness_dir = root / harness_dir
    if not config_path.is_absolute():
        config_path = root / config_path
    if not output_dir.is_absolute():
        output_dir = root / output_dir

    validation_path = harness_dir / "validated_pilot/validation_summary.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    pilot_cost_usd = float(validation["usage"]["conservative_batch_cost_usd"])
    pilot_count = float(validation["expected_record_count"])
    valid_record_coverage = float(validation["valid_record_coverage"])
    benefit_eligible_coverage = float(
        validation.get(
            "usable_record_coverage_excluding_evidence_collisions",
            valid_record_coverage,
        )
    )
    valid_request_rate = float(validation["valid_request_rate"])
    if pilot_count <= 0 or benefit_eligible_coverage <= 0 or valid_request_rate <= 0:
        raise ValueError("비용·커버리지 산식의 분모는 0보다 커야 합니다.")

    scope = config["scope"]
    observed_count = float(scope["observed_indicator_count"])
    observed_years = float(scope["observed_years"])
    exchange_rate = float(scope["exchange_rate_krw_per_usd"])
    implementation_hours = float(scope["one_time_implementation_hours"])
    if observed_count <= 0 or observed_years <= 0 or exchange_rate <= 0:
        raise ValueError("범위·연도·환율 가정은 0보다 커야 합니다.")

    retry_multiplier = 1 / valid_request_rate
    cost_per_indicator_usd = pilot_cost_usd / pilot_count
    scopes = {
        "pilot": pilot_count,
        "four_ministry_backfill": observed_count,
        "four_ministry_annual": observed_count / observed_years,
    }
    rows: list[dict[str, Any]] = []
    for scope_name, indicator_count in scopes.items():
        api_cost_usd = cost_per_indicator_usd * indicator_count * retry_multiplier
        api_cost_krw = api_cost_usd * exchange_rate
        for scenario in config["scenarios"]:
            manual_minutes = float(scenario["manual_minutes_per_indicator"])
            assisted_minutes = float(scenario["assisted_minutes_per_indicator"])
            hourly_cost = float(scenario["hourly_labor_cost_krw"])
            maintenance_hours = float(scenario["annual_maintenance_hours"])
            if min(manual_minutes, assisted_minutes, hourly_cost, maintenance_hours) < 0:
                raise ValueError("시간·인건비 가정은 음수일 수 없습니다.")

            baseline_cost = indicator_count * manual_minutes / 60 * hourly_cost
            saved_hours = (
                indicator_count
                * max(manual_minutes - assisted_minutes, 0)
                / 60
                * benefit_eligible_coverage
            )
            gross_labor_benefit = saved_hours * hourly_cost
            maintenance_cost = maintenance_hours * hourly_cost
            recurring_net_benefit = gross_labor_benefit - maintenance_cost - api_cost_krw
            adoption_cost = baseline_cost - gross_labor_benefit + maintenance_cost + api_cost_krw
            implementation_cost = implementation_hours * hourly_cost
            rows.append(
                {
                    "scope": scope_name,
                    "scenario": str(scenario["name"]),
                    "indicator_count": indicator_count,
                    "valid_record_coverage": valid_record_coverage,
                    "benefit_eligible_record_coverage": benefit_eligible_coverage,
                    "manual_minutes_per_indicator": manual_minutes,
                    "assisted_minutes_per_indicator": assisted_minutes,
                    "hourly_labor_cost_krw": hourly_cost,
                    "maintenance_hours": maintenance_hours,
                    "api_cost_usd_with_retry": api_cost_usd,
                    "api_cost_krw_with_retry": api_cost_krw,
                    "baseline_manual_cost_krw": baseline_cost,
                    "gross_labor_benefit_krw": gross_labor_benefit,
                    "maintenance_cost_krw": maintenance_cost,
                    "net_recurring_benefit_krw": recurring_net_benefit,
                    "benefit_cost_ratio": baseline_cost / adoption_cost if adoption_cost else None,
                    "implementation_cost_krw": implementation_cost,
                    "first_cycle_net_benefit_krw": recurring_net_benefit - implementation_cost,
                    "implementation_payback_cycles": (
                        implementation_cost / recurring_net_benefit
                        if recurring_net_benefit > 0
                        else None
                    ),
                    "break_even_manual_minutes": assisted_minutes
                    + (maintenance_cost + api_cost_krw)
                    * 60
                    / (indicator_count * hourly_cost * benefit_eligible_coverage),
                }
            )

    result = pd.DataFrame(rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "llm_cost_benefit_scenarios.csv"
    json_path = output_dir / "llm_cost_benefit_summary.json"
    result.to_csv(csv_path, index=False, encoding="utf-8-sig")
    summary = {
        "measurement": {
            "pilot_requests": int(validation["expected_request_count"]),
            "pilot_indicators": int(pilot_count),
            "valid_request_rate": valid_request_rate,
            "valid_record_coverage": valid_record_coverage,
            "benefit_eligible_record_coverage": benefit_eligible_coverage,
            "input_tokens": int(validation["usage"]["input_tokens"]),
            "output_tokens": int(validation["usage"]["output_tokens"]),
            "pilot_batch_cost_usd": pilot_cost_usd,
            "cost_per_selected_indicator_usd": cost_per_indicator_usd,
            "retry_multiplier_from_observed_valid_request_rate": retry_multiplier,
        },
        "assumptions": config,
        "formulas": {
            "gross_labor_benefit": "rows*(manual_minutes-assisted_minutes)/60*hourly_cost*benefit_eligible_record_coverage",
            "net_recurring_benefit": "gross_labor_benefit-maintenance_cost-api_cost",
            "first_cycle_net_benefit": "net_recurring_benefit-implementation_cost",
        },
        "scenario_rows": len(result),
        "promotion_allowed": False,
        "caveat": "시간·인건비·환율은 민감도 가정이며 실제 검수시간과 기관 원가로 교체해야 함",
    }
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary, (csv_path, json_path)
