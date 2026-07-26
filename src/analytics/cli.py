"""재정 분석 명령행 인터페이스."""

from pathlib import Path

import typer

from analytics.analysis_definition_validation import (
    DefinitionValidationPaths,
    build_analysis_definition_validation,
)
from analytics.financial_eda import EDAPaths, build_financial_eda
from analytics.m3_financial_signals import M3Paths, build_m3_analysis
from analytics.m3_methodology_audit import AuditPaths, build_m3_methodology_audit

app = typer.Typer(help="재정 마스터 기반 비LLM 분석")


@app.command("build-m2-data-review")
def build_m2_data_review(
    root: Path = typer.Option(Path("."), help="프로젝트 루트"),
) -> None:
    """1차 재정 EDA 표·그림·중간점검 보고서를 생성합니다."""
    result = build_financial_eda(EDAPaths.from_root(root))
    typer.echo(
        f"EDA 완료: 표 {len(result.table_paths)}개, "
        f"그래프 {len(result.figure_paths)}개, 보고서 {result.report_path}"
    )


@app.command("validate-m2-definitions")
def validate_m2_definitions(
    root: Path = typer.Option(Path("."), help="프로젝트 루트"),
) -> None:
    """M2 분석 정의·표본 대표성 검증 보고서를 생성합니다."""
    result = build_analysis_definition_validation(DefinitionValidationPaths.from_root(root))
    typer.echo(f"분석 정의 검증 완료: 표 {len(result.table_paths)}개, 보고서 {result.report_path}")


@app.command("build-m3-financial-signals")
def build_m3_financial_signals(
    root: Path = typer.Option(Path("."), help="프로젝트 루트"),
) -> None:
    """M3 독립 재정 신호·환류·강건성 분석을 생성합니다."""
    result = build_m3_analysis(M3Paths.from_root(root))
    typer.echo(
        f"M3 분석 완료: 산출물 {len(result.output_paths)}개, "
        f"그래프 {len(result.figure_paths)}개, 보고서 {result.report_path}"
    )


@app.command("audit-m3-methodology")
def audit_m3_methodology(
    root: Path = typer.Option(Path("."), help="프로젝트 루트"),
) -> None:
    """M3 상대기준·분석단위·반복관측 방법론을 감사합니다."""
    result = build_m3_methodology_audit(AuditPaths.from_root(root))
    typer.echo(
        f"M3 방법론 감사 완료: 산출물 {len(result.output_paths)}개, "
        f"보고서 {result.report_path}"
    )


if __name__ == "__main__":
    app()
