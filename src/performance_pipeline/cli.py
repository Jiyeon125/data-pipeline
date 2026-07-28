from __future__ import annotations

import json
from pathlib import Path

import typer

from .manual_performance import (
    ManualPerformanceError,
    build_manual_performance_pilot,
)
from .pdf_reconciliation import PdfReconciliationError, run_pdf_reconciliation

app = typer.Typer(help="수기 검수 성과자료 정규화와 재정 프로그램 매칭")


@app.callback()
def main() -> None:
    """성과문서 구조화 결과를 재정 프로그램과 연결합니다."""


@app.command("normalize-manual")
def normalize_manual(
    input_path: Path = typer.Option(
        Path("data/manual/LLM_문서구조화_중기부_최종.xlsx"),
        help="수기 검수 성과 엑셀",
    ),
    financial_path: Path = typer.Option(
        Path("data/processed/masters/program_year_financial.parquet"),
        help="프로그램-연도 재정 마스터",
    ),
    output_dir: Path = typer.Option(
        Path("data/processed/performance"),
        help="성과 정규화·매칭 산출물 디렉터리",
    ),
    ministry_name: str = typer.Option("중소벤처기업부"),
    ministry_code: str = typer.Option("102"),
    start_year: int = typer.Option(2022),
    end_year: int = typer.Option(2024),
    overwrite: bool = typer.Option(False, help="기존 산출물 덮어쓰기"),
) -> None:
    """중기부 수기 성과자료 파일럿을 정규화하고 재정 프로그램과 연결합니다."""
    try:
        result = build_manual_performance_pilot(
            input_path=input_path,
            financial_path=financial_path,
            output_dir=output_dir,
            ministry_name=ministry_name,
            ministry_code=ministry_code,
            start_year=start_year,
            end_year=end_year,
            overwrite=overwrite,
        )
    except (ManualPerformanceError, FileExistsError, OSError, ValueError) as exc:
        typer.echo(f"수기 성과자료 처리 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result.summary, ensure_ascii=False, indent=2))
    for path in result.output_paths:
        typer.echo(f"- {path}")


@app.command("reconcile-mss-performance-pdfs")
def reconcile_mss_performance_pdfs(
    manual_parquet_path: Path = typer.Option(
        Path("data/processed/performance/program_kpi_year.parquet"),
        help="대조 기준 63행 파케이",
    ),
    manual_excel_path: Path = typer.Option(
        Path("data/manual/LLM_문서구조화_중기부_최종.xlsx"),
        help="원본 수기 엑셀(해시 검증용, 읽기 전용)",
    ),
    output_dir: Path = typer.Option(
        Path("data/processed/performance/pdf_reconciliation"),
        help="Parquet·CSV·JSON 산출물 디렉터리",
    ),
    export_dir: Path = typer.Option(
        Path("data/exports/performance"),
        help="사람 검토용 엑셀 산출물 디렉터리",
    ),
    overwrite: bool = typer.Option(False, help="기존 산출물 덮어쓰기"),
) -> None:
    """중기부 성과계획서·성과보고서 PDF 별첨과 수기 63행을 원문 대조합니다."""
    try:
        result = run_pdf_reconciliation(
            manual_parquet_path=manual_parquet_path,
            manual_excel_path=manual_excel_path,
            output_dir=output_dir,
            export_dir=export_dir,
            overwrite=overwrite,
        )
    except (PdfReconciliationError, FileExistsError, OSError, ValueError) as exc:
        typer.echo(f"PDF 대조 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    for name, path in result["output_paths"].items():
        typer.echo(f"- {name}: {path}")


if __name__ == "__main__":
    app()
