"""성과계획서·성과보고서 원본 파일 인벤토리."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

DOCUMENT_TYPES = (
    "성과계획서",
    "성과보고서",
    "성과보고서-계획서변경사항",
)
DOCUMENT_NAME_PATTERN = re.compile(
    r"^(?P<year>20\d{2})년도 "
    r"(?P<document_type>성과계획서|성과보고서|성과보고서-계획서변경사항)_"
    r"(?P<ministry>.+)\.pdf$",
    re.IGNORECASE,
)


class DocumentInventoryError(ValueError):
    """원본 문서 인벤토리가 명명·내용 보존 규칙을 위반할 때 발생합니다."""


@dataclass(frozen=True)
class PerformanceDocument:
    path: Path
    fiscal_year: int
    document_type: str
    ministry: str

    @property
    def logical_key(self) -> tuple[int, str, str]:
        return self.fiscal_year, self.document_type, self.ministry


def _has_pdf_signature(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(5) == b"%PDF-"


def parse_document_name(path: Path) -> PerformanceDocument:
    match = DOCUMENT_NAME_PATTERN.fullmatch(path.name)
    if match is None:
        raise DocumentInventoryError(
            "파일명은 '<연도>년도 <문서유형>_<부처명>.pdf' 형식이어야 합니다: "
            f"{path.name}"
        )
    document_type = match.group("document_type")
    if document_type not in DOCUMENT_TYPES:
        raise DocumentInventoryError(f"지원하지 않는 문서유형입니다: {document_type}")
    if not _has_pdf_signature(path):
        raise DocumentInventoryError(f"PDF 확장자이지만 PDF 시그니처가 없습니다: {path}")
    return PerformanceDocument(
        path=path,
        fiscal_year=int(match.group("year")),
        document_type=document_type,
        ministry=match.group("ministry"),
    )


def discover_performance_documents(
    input_dir: Path,
    *,
    allowed_ministries: Iterable[str] | None = None,
) -> list[PerformanceDocument]:
    if not input_dir.is_dir():
        raise DocumentInventoryError(f"문서 디렉터리가 없습니다: {input_dir}")

    allowed = set(allowed_ministries) if allowed_ministries is not None else None
    documents: list[PerformanceDocument] = []
    invalid_files: list[str] = []
    for path in sorted(input_dir.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        try:
            document = parse_document_name(path)
        except DocumentInventoryError as exc:
            invalid_files.append(str(exc))
            continue
        if allowed is not None and document.ministry not in allowed:
            invalid_files.append(f"설정에 없는 부처명입니다: {document.path.name}")
            continue
        documents.append(document)

    if invalid_files:
        raise DocumentInventoryError("\n".join(invalid_files))

    seen: dict[tuple[int, str, str], Path] = {}
    for document in documents:
        previous = seen.get(document.logical_key)
        if previous is not None:
            raise DocumentInventoryError(
                f"논리적으로 중복된 문서입니다: {previous.name}, {document.path.name}"
            )
        seen[document.logical_key] = document.path
    return documents
