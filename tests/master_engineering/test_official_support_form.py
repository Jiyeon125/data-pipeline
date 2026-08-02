import pandas as pd

from master_engineering.build_masters.official_support_form import (
    _download_url,
    _extract_mohw_2022_sections,
    extract_official_fields,
)


def _text(value: str) -> dict:
    return {"Text": {"text": value}}


def _cell(value: str) -> dict:
    return {"content": [_text(value)] if value else []}


def test_extract_official_fields_preserves_multiple_support_forms() -> None:
    document = {
        "sections": [
            {
                "content": [
                    {
                        "Table": {
                            "rows": [
                                {
                                    "cells": [
                                        _cell(value)
                                        for value in (
                                            "직접",
                                            "출자",
                                            "출연",
                                            "보조",
                                            "융자",
                                            "국고보조율(%)",
                                        )
                                    ]
                                },
                                {"cells": [_cell(value) for value in ("○", "", "", "○", "", "50")]},
                            ]
                        }
                    },
                    _text("ㅇ 사업시행방법 : 직접수행+민간보조"),
                    _text("ㅇ 사업시행주체 : 중소벤처기업부, 전담기관"),
                ]
            }
        ]
    }

    result = extract_official_fields(document)

    assert result["support_forms"] == ["DIRECT", "SUBSIDY"]
    assert result["implementation_method_raw"] == "직접수행+민간보조"
    assert result["implementing_entity_raw"] == "중소벤처기업부, 전담기관"


def test_explicit_support_table_is_not_augmented_by_method() -> None:
    document = {
        "sections": [
            {
                "content": [
                    {
                        "Table": {
                            "rows": [
                                {
                                    "cells": [
                                        _cell(value)
                                        for value in ("직접", "출자", "출연", "보조", "융자")
                                    ]
                                },
                                {"cells": [_cell(value) for value in ("", "", "", "○", "")]},
                            ]
                        }
                    },
                    _text("사업시행방법 : 직접수행, 보조"),
                ]
            }
        ]
    }

    result = extract_official_fields(document)

    assert result["support_forms"] == ["SUBSIDY"]


def test_extract_mohw_sections_uses_exact_project_boundary() -> None:
    pages = [
        "사 업 명 (1) 생계급여 (1131-300)\n사업시행방법 : 직접수행, 보조\n",
        "사업시행주체 : 보건복지부, 지방자치단체\n",
        "사 업 명 (2) 의료급여 (1132-302)\n사업시행방법 : 보조\n사업시행주체 : 지자체\n",
    ]

    sections = _extract_mohw_2022_sections(pages)

    assert sections == [
        {
            "activity_code": "1131",
            "subactivity_code": "300",
            "implementation_method_raw": "직접수행, 보조",
            "implementing_entity_raw": "보건복지부, 지방자치단체",
            "source_page_number": "1-2",
        },
        {
            "activity_code": "1132",
            "subactivity_code": "302",
            "implementation_method_raw": "보조",
            "implementing_entity_raw": "지자체",
            "source_page_number": "3-3",
        },
    ]


def test_download_url_sanitizes_slash_in_display_name() -> None:
    url = _download_url(
        pd.Series(
            {
                "fiscal_year": 2022,
                "ministry_name": "과학기술정보통신부",
                "subactivity_name": "VR/AR 기술개발",
                "source_file_name": "2022162110000611131318.hwp",
            }
        )
    )

    assert "%2F" not in url
    assert "VR_AR%20%EA%B8%B0%EC%88%A0%EA%B0%9C%EB%B0%9C" in url
