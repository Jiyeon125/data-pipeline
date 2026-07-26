"""재정 분석 명령행 인터페이스."""

from pathlib import Path

import typer

from analytics.analysis_definition_validation import (
    DefinitionValidationPaths,
    build_analysis_definition_validation,
)
from analytics.financial_eda import EDAPaths, build_financial_eda

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


if __name__ == "__main__":
    app()
