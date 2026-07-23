from __future__ import annotations

import pytest

from open_fiscal_pipeline.config import ConfigError, load_datasets


def test_dataset_parameter_mapping_uses_official_names() -> None:
    datasets = load_datasets("configs/datasets.yaml")
    dataset = datasets["total_expenditure_project"]
    params = dataset.build_params({"year": 2024, "ministry": "중소벤처기업부"})

    assert params["FSCL_YY"] == "2024"
    assert params["OFFC_NM"] == "중소벤처기업부"
    assert params["BDG_FND_DIV_CD"] == "0"
    assert params["ANEXP_INQ_STND_CD"] == "1"
    assert "year" not in params
    assert "ministry" not in params


def test_monthly_expenditure_requires_code_and_month() -> None:
    dataset = load_datasets("configs/datasets.yaml")["monthly_expenditure"]

    with pytest.raises(ConfigError):
        dataset.build_params({"year": 2024, "execution_month": "12"})

    params = dataset.build_params(
        {"year": 2024, "execution_month": "12", "ministry_code": "TEST"}
    )
    assert params == {"FSCL_YY": "2024", "EXE_M": "12", "OFFC_CD": "TEST"}
