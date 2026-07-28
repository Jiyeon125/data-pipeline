"""재정 분석 명령행 인터페이스."""

import json
from pathlib import Path

import typer

from analytics.analysis_definition_validation import (
    DefinitionValidationPaths,
    build_analysis_definition_validation,
)
from analytics.analysis_policy_decision_support import (
    DecisionSupportPaths,
    build_analysis_policy_decision_support,
)
from analytics.financial_eda import EDAPaths, build_financial_eda
from analytics.m3_financial_signals import M3Paths, build_m3_analysis
from analytics.m3_methodology_audit import AuditPaths, build_m3_methodology_audit
from analytics.mss_priority_scenario_analysis import (
    PriorityScenarioError,
    PriorityScenarioPaths,
    run_priority_scenario_analysis,
)
from analytics.mss_same_year_budget_check import (
    SameYearBudgetCheckError,
    run_same_year_budget_check,
)
from analytics.unknown_top16_review import (
    UnknownReviewPaths,
    build_unknown_review_workbook,
    validate_unknown_review_workbook,
)

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
        f"M3 방법론 감사 완료: 산출물 {len(result.output_paths)}개, 보고서 {result.report_path}"
    )


@app.command("build-analysis-policy-decision-support")
def build_analysis_policy_decision_support_command(
    root: Path = typer.Option(Path("."), help="프로젝트 루트"),
) -> None:
    """집행률·연말집중·반복 기준의 분포·민감도 의사결정 자료를 생성합니다."""
    result = build_analysis_policy_decision_support(DecisionSupportPaths.from_root(root))
    typer.echo(
        f"분석 기준 의사결정 자료 완료: 표 {len(result.output_paths)}개, "
        f"그래프 {len(result.figure_paths)}개, 보고서 {result.report_path}"
    )


@app.command("prepare-unknown-priority-review")
def prepare_unknown_priority_review(
    root: Path = typer.Option(Path("."), help="프로젝트 루트"),
    overwrite: bool = typer.Option(
        False,
        help="기존 검수 파일을 덮어씁니다. 사람 입력 유실 위험이 있어 기본값은 false입니다.",
    ),
) -> None:
    """UNKNOWN 예산 80% 커버리지 우선사업의 사람 검수용 Excel 워크북을 생성합니다."""
    output = build_unknown_review_workbook(
        UnknownReviewPaths.from_root(root),
        overwrite=overwrite,
    )
    typer.echo(f"UNKNOWN 80% 커버리지 검수 워크북 생성: {output}")


@app.command("validate-unknown-priority-review")
def validate_unknown_priority_review(
    root: Path = typer.Option(Path("."), help="프로젝트 루트"),
    require_complete: bool = typer.Option(
        False,
        help="현재 80% 커버리지 대상 모두 CONFIRMED인지 완료 기준으로 검사합니다.",
    ),
) -> None:
    """UNKNOWN 80% 커버리지 검수 워크북의 구조·허용값·근거 완전성을 검사합니다."""
    result = validate_unknown_review_workbook(
        UnknownReviewPaths.from_root(root),
        require_complete=require_complete,
    )
    typer.echo(
        f"검수 워크북 검증 {result.status}: 사업 {result.project_count}개, "
        f"연도 {result.year_row_count}행, 확정 {result.confirmed_project_count}개, "
        f"오류 {result.error_count}개, 경고 {result.warning_count}개"
    )
    if result.status == "FAIL":
        raise typer.Exit(code=1)


@app.command("analyze-mss-same-year-budget")
def analyze_mss_same_year_budget(
    root: Path = typer.Option(Path("."), help="프로젝트 루트"),
    ministry_code: str = typer.Option("102"),
    start_year: int = typer.Option(2022),
    end_year: int = typer.Option(2024),
    overwrite: bool = typer.Option(False, help="기존 산출물 덮어쓰기"),
) -> None:
    """중기부 성과와 재정을 프로그램-연도-회계유형 단위로 결합합니다."""
    try:
        result = run_same_year_budget_check(
            indicator_path=root
            / "data/processed/performance/analysis_ready/program_kpi_year_analysis_ready.parquet",
            overall_financial_path=root / "data/processed/masters/program_year_financial.parquet",
            project_financial_path=root
            / "data/processed/masters/project_year_financial_v2.parquet",
            output_dir=root / "data/analytics/mss_same_year_budget_check",
            ministry_code=ministry_code,
            start_year=start_year,
            end_year=end_year,
            overwrite=overwrite,
        )
    except (
        SameYearBudgetCheckError,
        FileExistsError,
        OSError,
        ValueError,
    ) as exc:
        typer.echo(f"중기부 동년도 점검 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result.summary, ensure_ascii=False, indent=2))
    for path in result.output_paths:
        typer.echo(f"- {path}")


@app.command("analyze-manual-same-year-budget")
def analyze_manual_same_year_budget(
    indicator_path: Path = typer.Option(..., help="부처별 분석용 성과지표 파케이"),
    output_dir: Path = typer.Option(..., help="부처별 동년도 분석 산출물 디렉터리"),
    root: Path = typer.Option(Path("."), help="프로젝트 루트"),
    ministry_code: str = typer.Option(..., help="앞자리 0을 포함한 3자리 부처코드"),
    start_year: int = typer.Option(2022),
    end_year: int = typer.Option(2024),
    overwrite: bool = typer.Option(False, help="기존 산출물 덮어쓰기"),
) -> None:
    """수기 골드셋 성과와 재정을 프로그램-연도-회계유형 단위로 결합합니다."""
    try:
        result = run_same_year_budget_check(
            indicator_path=indicator_path,
            overall_financial_path=root / "data/processed/masters/program_year_financial.parquet",
            project_financial_path=root
            / "data/processed/masters/project_year_financial_v2.parquet",
            output_dir=output_dir,
            ministry_code=ministry_code,
            start_year=start_year,
            end_year=end_year,
            overwrite=overwrite,
        )
    except (
        SameYearBudgetCheckError,
        FileExistsError,
        OSError,
        ValueError,
    ) as exc:
        typer.echo(f"수기 골드셋 동년도 점검 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result.summary, ensure_ascii=False, indent=2))
    for path in result.output_paths:
        typer.echo(f"- {path}")


@app.command("analyze-mss-priority-scenarios")
def analyze_mss_priority_scenarios(
    root: Path = typer.Option(Path("."), help="프로젝트 루트"),
    overwrite: bool = typer.Option(False, help="기존 산출물 덮어쓰기"),
) -> None:
    """중기부 점검 후보군과 복수 시나리오 순위 안정성을 산출합니다."""
    try:
        result = run_priority_scenario_analysis(
            PriorityScenarioPaths.from_root(root),
            overwrite=overwrite,
        )
    except (
        PriorityScenarioError,
        FileExistsError,
        FileNotFoundError,
        OSError,
        ValueError,
    ) as exc:
        typer.echo(f"중기부 후보·시나리오 분석 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result.summary, ensure_ascii=False, indent=2))
    for path in (*result.output_paths, *result.figure_paths):
        typer.echo(f"- {path}")


if __name__ == "__main__":
    app()
