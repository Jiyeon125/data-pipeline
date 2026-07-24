from __future__ import annotations

from pathlib import Path

import pytest

from performance_pipeline.ingest.inventory import (
    DocumentInventoryError,
    discover_performance_documents,
    parse_document_name,
)


def _fake_pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-1.7\n%%EOF\n")
    return path


def test_parse_document_name_preserves_exact_tokens(tmp_path: Path) -> None:
    path = _fake_pdf(tmp_path / "2024년도 성과보고서-계획서변경사항_행정안전부.pdf")

    document = parse_document_name(path)

    assert document.fiscal_year == 2024
    assert document.document_type == "성과보고서-계획서변경사항"
    assert document.ministry == "행정안전부"


def test_discovery_rejects_unknown_ministry(tmp_path: Path) -> None:
    _fake_pdf(tmp_path / "2024년도 성과계획서_가상부처.pdf")

    with pytest.raises(DocumentInventoryError, match="설정에 없는 부처명"):
        discover_performance_documents(tmp_path, allowed_ministries={"행정안전부"})


def test_discovery_rejects_non_pdf_signature(tmp_path: Path) -> None:
    path = tmp_path / "2024년도 성과계획서_행정안전부.pdf"
    path.write_text("not a pdf", encoding="utf-8")

    with pytest.raises(DocumentInventoryError, match="PDF 시그니처"):
        discover_performance_documents(tmp_path, allowed_ministries={"행정안전부"})


def test_discovery_ignores_hidden_placeholders(tmp_path: Path) -> None:
    (tmp_path / ".gitkeep").write_text("", encoding="utf-8")
    _fake_pdf(tmp_path / "2024년도 성과계획서_행정안전부.pdf")

    documents = discover_performance_documents(
        tmp_path,
        allowed_ministries={"행정안전부"},
    )

    assert len(documents) == 1
