from __future__ import annotations

import importlib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_pipeline_packages_are_importable() -> None:
    packages = (
        "open_fiscal_pipeline",
        "performance_pipeline",
        "master_engineering",
        "fiscal_analytics",
        "fiscal_dashboard",
    )
    for package in packages:
        assert importlib.import_module(package)


def test_new_configuration_files_have_expected_roots() -> None:
    llm = yaml.safe_load((ROOT / "configs/llm.yaml").read_text(encoding="utf-8"))
    joins = yaml.safe_load((ROOT / "configs/join_keys.yaml").read_text(encoding="utf-8"))

    assert set(llm) == {"llm", "extraction", "review"}
    assert {"normalization", "tables", "performance_to_fiscal"} <= set(joins)
    assert joins["normalization"]["code_type"] == "string"
    assert joins["performance_to_fiscal"]["retain_unmatched_rows"] is True


def test_data_zone_directories_exist() -> None:
    expected = (
        "data/raw/performance_docs",
        "data/raw/monthly_expenditure",
        "data/raw/budget",
        "data/raw/settlement",
        "data/interim/llm_extractions",
        "data/interim/ocr_text",
        "data/processed/project_month",
        "data/processed/program_year",
        "data/processed/kpi_year",
        "data/processed/project_year",
        "data/processed/amount_event",
        "data/processed/masters",
        "data/analytics",
        "data/exports",
        "artifacts/llm_runs",
        "artifacts/eval",
        "artifacts/figures",
    )
    for relative_path in expected:
        assert (ROOT / relative_path).is_dir(), relative_path
