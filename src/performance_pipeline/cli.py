from __future__ import annotations

import json
from pathlib import Path

import httpx
import typer

from .analysis_ready_performance import (
    DEFAULT_REPORT_TARGET_CONFIRMATIONS_PATH,
    AnalysisReadyPerformanceError,
    run_analysis_ready_master,
    run_verified_manual_analysis_ready_master,
)
from .llm_harness import (
    LlmHarnessError,
    fetch_batch_results,
    prepare_llm_harness,
    submit_batch,
    validate_llm_responses,
)
from .manual_performance import (
    ManualPerformanceError,
    build_manual_performance_pilot,
    build_program_match_review,
)
from .pdf_reconciliation import (
    DEFAULT_MANUAL_REVIEW_CONFIRMATIONS_PATH,
    PdfReconciliationError,
    run_ministry_pdf_reconciliation,
    run_pdf_reconciliation,
)

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
    program_code_confirmations_path: Path | None = typer.Option(
        None,
        help="원본 PDF로 확인한 프로그램목표별 재정 프로그램코드 표",
    ),
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
            program_code_confirmations_path=program_code_confirmations_path,
            overwrite=overwrite,
        )
    except (ManualPerformanceError, FileExistsError, OSError, ValueError) as exc:
        typer.echo(f"수기 성과자료 처리 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result.summary, ensure_ascii=False, indent=2))
    for path in result.output_paths:
        typer.echo(f"- {path}")


@app.command("build-verified-manual-analysis-ready")
def build_verified_manual_analysis_ready(
    manual_path: Path = typer.Option(..., help="부처별 program_kpi_year.parquet"),
    output_dir: Path = typer.Option(..., help="분석용 성과지표 산출물 디렉터리"),
    ministry_code: str = typer.Option(..., help="앞자리 0을 포함한 3자리 부처코드"),
    overwrite: bool = typer.Option(False, help="기존 산출물 덮어쓰기"),
) -> None:
    """사람 검수 골드셋을 동년도 분석 입력 형식으로 변환합니다."""
    try:
        result = run_verified_manual_analysis_ready_master(
            manual_path=manual_path,
            output_dir=output_dir,
            ministry_code=ministry_code,
            overwrite=overwrite,
        )
    except (AnalysisReadyPerformanceError, FileExistsError, OSError, ValueError) as exc:
        typer.echo(f"수기 골드셋 분석 입력 생성 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result.summary, ensure_ascii=False, indent=2))
    for path in result.output_paths:
        typer.echo(f"- {path}")


@app.command("prepare-program-match-review")
def prepare_program_match_review(
    program_year_path: Path = typer.Option(..., help="정규화된 프로그램-연도 성과재정 파케이"),
    financial_path: Path = typer.Option(
        Path("data/processed/masters/program_year_financial.parquet"),
        help="프로그램-연도 재정 마스터",
    ),
    output_dir: Path = typer.Option(..., help="수기 매칭 검토표 산출물 디렉터리"),
    ministry_code: str = typer.Option(..., help="앞자리 0을 포함한 3자리 부처코드"),
    candidate_count: int = typer.Option(3, min=1, max=10),
    overwrite: bool = typer.Option(False, help="기존 산출물 덮어쓰기"),
) -> None:
    """미매칭 프로그램마다 같은 부처·연도의 재정 프로그램 후보를 만듭니다."""
    try:
        _, summary, output_paths = build_program_match_review(
            program_year_path=program_year_path,
            financial_path=financial_path,
            output_dir=output_dir,
            ministry_code=ministry_code,
            candidate_count=candidate_count,
            overwrite=overwrite,
        )
    except (ManualPerformanceError, FileExistsError, OSError, ValueError) as exc:
        typer.echo(f"프로그램 매칭 검토표 생성 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))
    for path in output_paths:
        typer.echo(f"- {path}")


@app.command("reconcile-ministry-performance-pdfs")
def reconcile_ministry_performance_pdfs(
    ministry_code: str = typer.Argument(help="부처코드 문자열(019, 075, 162)"),
    manual_excel_path: Path = typer.Option(
        Path("data/manual/LLM_문서구조화_3개부처_최종제출본.xlsx"),
        help="3개 부처 수기 원본 엑셀(해시 검증용, 읽기 전용)",
    ),
    output_root: Path = typer.Option(
        Path("data/processed/performance/pdf_reconciliation"),
        help="부처별 Parquet·CSV·JSON 산출물 루트",
    ),
    overwrite: bool = typer.Option(False, help="기존 산출물 덮어쓰기"),
) -> None:
    """한 부처의 2022~2024 수기 성과지표를 PDF 별첨 원문과 대조합니다."""
    try:
        result = run_ministry_pdf_reconciliation(
            ministry_code,
            manual_excel_path=manual_excel_path,
            output_root=output_root,
            overwrite=overwrite,
        )
    except (PdfReconciliationError, FileExistsError, OSError, ValueError) as exc:
        typer.echo(f"PDF 대조 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    for name, path in result["output_paths"].items():
        typer.echo(f"- {name}: {path}")


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
    manual_review_confirmations_path: Path = typer.Option(
        DEFAULT_MANUAL_REVIEW_CONFIRMATIONS_PATH,
        help="사람이 원문을 직접 확인해 채운 검수 확정 CSV(reviewer/review_status/review_note)",
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
            manual_review_confirmations_path=manual_review_confirmations_path,
            overwrite=overwrite,
        )
    except (PdfReconciliationError, FileExistsError, OSError, ValueError) as exc:
        typer.echo(f"PDF 대조 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    for name, path in result["output_paths"].items():
        typer.echo(f"- {name}: {path}")


@app.command("build-mss-analysis-ready")
def build_mss_analysis_ready(
    manual_path: Path = typer.Option(
        Path("data/processed/performance/program_kpi_year.parquet"),
        help="원본 수기 63행 성과지표 마스터(읽기 전용)",
    ),
    reconciliation_path: Path = typer.Option(
        Path(
            "data/processed/performance/pdf_reconciliation/"
            "mss_performance_pdf_reconciliation.parquet"
        ),
        help="PDF 원문 대조·검수 결과",
    ),
    report_target_confirmations_path: Path = typer.Option(
        DEFAULT_REPORT_TARGET_CONFIRMATIONS_PATH,
        help="PDF 원문 육안검수로 확정한 보고서 목표 CSV",
    ),
    output_dir: Path = typer.Option(
        Path("data/processed/performance/analysis_ready"),
        help="분석용 성과지표 마스터 산출물 디렉터리",
    ),
    overwrite: bool = typer.Option(False, help="기존 산출물 덮어쓰기"),
) -> None:
    """검수 확정된 PDF 값으로 수기 결측만 보완한 분석용 중기부 마스터를 만듭니다."""
    try:
        result = run_analysis_ready_master(
            manual_path=manual_path,
            reconciliation_path=reconciliation_path,
            report_target_confirmations_path=report_target_confirmations_path,
            output_dir=output_dir,
            overwrite=overwrite,
        )
    except (
        AnalysisReadyPerformanceError,
        FileExistsError,
        OSError,
        ValueError,
    ) as exc:
        typer.echo(f"분석용 성과지표 마스터 생성 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result.summary, ensure_ascii=False, indent=2))
    for path in result.output_paths:
        typer.echo(f"- {path}")


@app.command("prepare-llm-harness")
def prepare_document_llm_harness(
    root: Path = typer.Option(Path("."), help="프로젝트 루트"),
    model: str | None = typer.Option(
        None,
        help="OpenAI 모델. 생략하면 OPENAI_MODEL, 없으면 configs/llm.yaml 기본 모델",
    ),
    overwrite: bool = typer.Option(False, help="기존 로컬 하네스 산출물 덮어쓰기"),
) -> None:
    """로컬 PDF 대조 결과에서 필요한 행만 묶어 미호출 Batch 요청을 준비합니다."""
    try:
        result = prepare_llm_harness(root, model=model, overwrite=overwrite)
    except (LlmHarnessError, FileExistsError, FileNotFoundError, OSError, ValueError) as exc:
        typer.echo(f"LLM 하네스 준비 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result.summary, ensure_ascii=False, indent=2))
    for path in result.output_paths:
        typer.echo(f"- {path}")


@app.command("validate-llm-responses")
def validate_document_llm_responses(
    responses_path: Path = typer.Argument(help="Batch 응답 JSONL 또는 로컬 fixture"),
    root: Path = typer.Option(Path("."), help="프로젝트 루트"),
    request_set: str = typer.Option("pilot", help="pilot, remaining 또는 all"),
    overwrite: bool = typer.Option(False, help="기존 검증 산출물 덮어쓰기"),
) -> None:
    """API 호출 없이 저장된 LLM 응답의 스키마·근거·골드셋 일치를 검증합니다."""
    try:
        result = validate_llm_responses(
            root,
            responses_path,
            request_set=request_set,
            overwrite=overwrite,
        )
    except (LlmHarnessError, FileExistsError, FileNotFoundError, OSError, ValueError) as exc:
        typer.echo(f"LLM 응답 검증 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result.summary, ensure_ascii=False, indent=2))
    for path in result.output_paths:
        typer.echo(f"- {path}")


@app.command("submit-llm-batch")
def submit_document_llm_batch(
    max_approved_cost_usd: float = typer.Option(
        ...,
        min=0,
        help="사용자가 이번 실행에 명시적으로 승인한 최대 예상비용",
    ),
    request_set: str = typer.Option(
        "pilot",
        help="pilot(기본 12개) 또는 remaining(파일럿 통과 뒤 나머지)",
    ),
    root: Path = typer.Option(Path("."), help="프로젝트 루트"),
) -> None:
    """설정·API 키·모델·비용승인이 모두 있을 때만 OpenAI Batch를 제출합니다."""
    try:
        result = submit_batch(
            root,
            max_approved_cost_usd=max_approved_cost_usd,
            request_set=request_set,
        )
    except (LlmHarnessError, httpx.HTTPError, FileNotFoundError, OSError, ValueError) as exc:
        typer.echo(f"LLM Batch 제출 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("fetch-llm-batch")
def fetch_document_llm_batch(
    root: Path = typer.Option(Path("."), help="프로젝트 루트"),
    request_set: str = typer.Option("pilot", help="pilot 또는 remaining"),
) -> None:
    """Batch 상태를 한 번 확인하고 완료된 응답·오류 파일을 내려받습니다."""
    try:
        result = fetch_batch_results(root, request_set=request_set)
    except (
        LlmHarnessError,
        httpx.HTTPError,
        FileNotFoundError,
        OSError,
        ValueError,
    ) as exc:
        typer.echo(f"LLM Batch 확인 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
