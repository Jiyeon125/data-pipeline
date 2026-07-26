"""마스터 테이블 엔지니어링 CLI 진입점."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from .build_masters.financial_v1 import build_financial_v1
from .build_masters.project_classification import build_project_classification
from .build_masters.project_continuity import build_project_continuity
from .build_masters.project_year import (
    build_project_year_budget_base,
    build_project_year_financial_base,
)
from .quality.financial_followup import analyze_financial_quality_followup
from .quality.population_sensitivity import analyze_population_sensitivity
from .quality.ranking_population_v2 import build_ranking_population_v2

app = typer.Typer(no_args_is_help=True, help="성과·재정 마스터 테이블 엔지니어링")


@app.callback()
def main() -> None:
    """마스터 엔지니어링 명령을 실행합니다."""


@app.command("status")
def status() -> None:
    """현재 스캐폴딩 상태를 출력합니다."""
    typer.echo("master_engineering: scaffolded")


@app.command("build-project-continuity")
def build_project_continuity_command(
    financial_v1_path: Path = typer.Option(
        Path("data/processed/masters/project_year_financial_v1.parquet")
    ),
    broad_population_path: Path = typer.Option(
        Path("data/processed/masters/population_sensitivity/broad_population.parquet")
    ),
    core_population_path: Path = typer.Option(
        Path(
            "data/processed/masters/population_sensitivity/"
            "core_financial_population.parquet"
        )
    ),
    strict_population_path: Path = typer.Option(
        Path(
            "data/processed/masters/population_sensitivity/"
            "strict_ranking_population.parquet"
        )
    ),
    classification_path: Path = typer.Option(
        Path("data/processed/masters/project_classification.parquet")
    ),
    mentoring_guide_path: Path = typer.Option(Path("docs/MENTORING_GUIDE.md")),
    project_plan_path: Path = typer.Option(Path("docs/PROJECT_PLAN.md")),
    output_dir: Path = typer.Option(Path("data/processed/masters")),
    overwrite: bool = typer.Option(False),
) -> None:
    """사업 연속성, 재정 파생변수, 프로그램-연도 재정 테이블을 생성합니다."""
    try:
        result = build_project_continuity(
            financial_v1_path=financial_v1_path,
            broad_path=broad_population_path,
            core_path=core_population_path,
            strict_path=strict_population_path,
            classification_path=classification_path,
            mentoring_guide_path=mentoring_guide_path,
            project_plan_path=project_plan_path,
            output_dir=output_dir,
            overwrite=overwrite,
        )
    except (OSError, FileExistsError, ValueError) as exc:
        typer.echo(f"사업 연속성 산출물 생성 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result.summaries, ensure_ascii=False, indent=2))
    for path in result.output_paths:
        typer.echo(f"- {path}")


@app.command("build-ranking-population-v2")
def build_ranking_population_v2_command(
    core_path: Path = typer.Option(
        Path(
            "data/processed/masters/population_sensitivity/"
            "core_financial_population.parquet"
        )
    ),
    strict_path: Path = typer.Option(
        Path(
            "data/processed/masters/population_sensitivity/"
            "strict_ranking_population.parquet"
        )
    ),
    financial_v2_path: Path = typer.Option(
        Path("data/processed/masters/project_year_financial_v2.parquet")
    ),
    output_dir: Path = typer.Option(
        Path("data/processed/masters/population_sensitivity")
    ),
    overwrite: bool = typer.Option(False),
) -> None:
    """core 기반 변수별 적격 순위 모집단 v2를 생성합니다."""
    try:
        result = build_ranking_population_v2(
            core_path=core_path,
            strict_path=strict_path,
            financial_v2_path=financial_v2_path,
            output_dir=output_dir,
            overwrite=overwrite,
        )
    except (OSError, FileExistsError, ValueError) as exc:
        typer.echo(f"순위 모집단 v2 생성 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result.summary, ensure_ascii=False, indent=2))
    for path in result.output_paths:
        typer.echo(f"- {path}")


@app.command("build-project-year-budget")
def build_project_year_budget(
    budget_records_path: Path = typer.Option(
        Path("data/processed/budget/budget_records.parquet"),
        help="정규화된 예산 레코드",
    ),
    amount_events_path: Path = typer.Option(
        Path("data/processed/amount_event/budget_amount_events.parquet"),
        help="정규화된 예산 금액 이벤트",
    ),
    output_dir: Path = typer.Option(
        Path("data/processed/masters"),
        help="중간 기준 테이블 저장 디렉터리",
    ),
    overwrite: bool = typer.Option(False, help="기존 출력 덮어쓰기"),
) -> None:
    """예산 API 기준의 사업-연도 중간 테이블을 구축합니다."""
    try:
        result = build_project_year_budget_base(
            budget_records_path=budget_records_path,
            amount_events_path=amount_events_path,
            output_dir=output_dir,
            overwrite=overwrite,
        )
    except (OSError, FileExistsError, ValueError) as exc:
        typer.echo(f"사업-연도 테이블 구축 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result.summary, ensure_ascii=False, indent=2))
    for path in result.output_paths:
        typer.echo(f"- {path}")


@app.command("analyze-population-sensitivity")
def analyze_project_population_sensitivity(
    population_path: Path = typer.Option(
        Path("data/processed/masters/project_year_analysis_population.parquet"),
        help="현재 일반 분석 모집단",
    ),
    excluded_path: Path = typer.Option(
        Path("data/processed/masters/project_year_analysis_excluded.parquet"),
        help="현재 제외 모집단",
    ),
    output_dir: Path = typer.Option(
        Path("data/processed/masters/population_sensitivity"),
        help="모집단 민감도 산출물 저장 디렉터리",
    ),
    overwrite: bool = typer.Option(False, help="기존 출력 덮어쓰기"),
) -> None:
    """모집단 제외 과도성과 분석별 적격·편향을 진단합니다."""
    try:
        result = analyze_population_sensitivity(
            population_path=population_path,
            excluded_path=excluded_path,
            output_dir=output_dir,
            overwrite=overwrite,
        )
    except (OSError, FileExistsError, ValueError) as exc:
        typer.echo(f"모집단 민감도 분석 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result.summary, ensure_ascii=False, indent=2))
    for path in result.output_paths:
        typer.echo(f"- {path}")


@app.command("build-project-analysis-population")
def build_project_analysis_population(
    financial_v1_path: Path = typer.Option(
        Path("data/processed/masters/project_year_financial_v1.parquet"),
        help="분류 대상 financial v1",
    ),
    manual_review_path: Path = typer.Option(
        Path("data/processed/masters/quality/manual_review_prioritized.csv"),
        help="우선순위가 적용된 수기검토 목록",
    ),
    execution_over_100_path: Path = typer.Option(
        Path("data/processed/masters/quality/execution_rate_over_100.csv"),
        help="집행률 1 초과 목록",
    ),
    datasets_path: Path = typer.Option(
        Path("configs/datasets.yaml"),
        help="데이터셋 설정",
    ),
    ministries_path: Path = typer.Option(
        Path("configs/ministries.yaml"),
        help="부처 설정",
    ),
    mentoring_guide_path: Path = typer.Option(
        Path("docs/MENTORING_GUIDE.md"),
        help="분류·제외 분석 원칙",
    ),
    project_plan_path: Path = typer.Option(
        Path("docs/PROJECT_PLAN.md"),
        help="프로젝트 기획 문서(없으면 한계로 기록)",
    ),
    output_dir: Path = typer.Option(
        Path("data/processed/masters"),
        help="분류 마스터와 분석 모집단 저장 디렉터리",
    ),
    overwrite: bool = typer.Option(False, help="기존 출력 덮어쓰기"),
) -> None:
    """규칙 기반 사업분류 마스터와 재정분석 모집단을 생성합니다."""
    try:
        result = build_project_classification(
            financial_v1_path=financial_v1_path,
            manual_review_path=manual_review_path,
            execution_over_100_path=execution_over_100_path,
            datasets_path=datasets_path,
            ministries_path=ministries_path,
            mentoring_guide_path=mentoring_guide_path,
            project_plan_path=project_plan_path,
            output_dir=output_dir,
            overwrite=overwrite,
        )
    except (OSError, FileExistsError, ValueError) as exc:
        typer.echo(f"사업분류·분석 모집단 구축 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result.summary, ensure_ascii=False, indent=2))
    for path in result.output_paths:
        typer.echo(f"- {path}")


@app.command("build-project-year-financial")
def build_project_year_financial(
    budget_base_path: Path = typer.Option(
        Path("data/processed/masters/project_year_budget_base.parquet"),
        help="예산 API 기준 사업-연도 테이블",
    ),
    monthly_path: Path = typer.Option(
        Path("data/processed/monthly_expenditure/monthly_expenditure_2022_2025.parquet"),
        help="월별 집행 정규화 테이블",
    ),
    output_dir: Path = typer.Option(
        Path("data/processed/masters"),
        help="재정 사업-연도 중간 테이블 저장 디렉터리",
    ),
    overwrite: bool = typer.Option(False, help="기존 출력 덮어쓰기"),
) -> None:
    """예산 기준 테이블과 월별 집행을 연결합니다."""
    try:
        result = build_project_year_financial_base(
            budget_base_path=budget_base_path,
            monthly_path=monthly_path,
            output_dir=output_dir,
            overwrite=overwrite,
        )
    except (OSError, FileExistsError, ValueError) as exc:
        typer.echo(f"재정 사업-연도 테이블 구축 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result.summary, ensure_ascii=False, indent=2))
    for path in result.output_paths:
        typer.echo(f"- {path}")


@app.command("build-project-year-financial-v1")
def build_project_year_financial_v1(
    financial_base_path: Path = typer.Option(
        Path("data/processed/masters/project_year_financial_base.parquet"),
        help="예산·월별 집행 재정 기준 테이블",
    ),
    settlement_path: Path = typer.Option(
        Path("data/processed/settlement/project_settlement.parquet"),
        help="정규화된 결산 테이블",
    ),
    output_dir: Path = typer.Option(
        Path("data/processed/masters"),
        help="financial v1 및 품질 산출물 저장 디렉터리",
    ),
    overwrite: bool = typer.Option(False, help="기존 출력 덮어쓰기"),
) -> None:
    """결산 연결·12월 대조·집행률 규칙을 적용한 financial v1을 생성합니다."""
    try:
        result = build_financial_v1(
            financial_base_path=financial_base_path,
            settlement_path=settlement_path,
            output_dir=output_dir,
            overwrite=overwrite,
        )
    except (OSError, FileExistsError, ValueError) as exc:
        typer.echo(f"financial v1 구축 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result.summary, ensure_ascii=False, indent=2))
    for path in result.output_paths:
        typer.echo(f"- {path}")


@app.command("analyze-financial-v1-quality")
def analyze_financial_v1_quality(
    input_path: Path = typer.Option(
        Path("data/processed/masters/project_year_financial_v1.parquet"),
        help="품질 후속 분석 대상 financial v1",
    ),
    output_dir: Path = typer.Option(
        Path("data/processed/masters/quality"),
        help="후속 품질 산출물 저장 디렉터리",
    ),
    overwrite: bool = typer.Option(False, help="기존 출력 덮어쓰기"),
) -> None:
    """불일치·초과 집행·수기검토 우선순위 후속 분석을 생성합니다."""
    try:
        result = analyze_financial_quality_followup(
            input_path=input_path,
            output_dir=output_dir,
            overwrite=overwrite,
        )
    except (OSError, FileExistsError, ValueError) as exc:
        typer.echo(f"financial v1 후속 품질분석 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result.summary, ensure_ascii=False, indent=2))
    for path in result.output_paths:
        typer.echo(f"- {path}")


if __name__ == "__main__":
    app()
