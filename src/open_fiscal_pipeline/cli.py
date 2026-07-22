from __future__ import annotations

import json
from pathlib import Path

import typer

from .client import OpenFiscalClient
from .config import Settings

app = typer.Typer(no_args_is_help=True, help="열린재정 데이터 수집 파이프라인")


@app.command("smoke-test")
def smoke_test() -> None:
    """인증키와 요청주소로 첫 페이지를 호출하고 응답 구조를 확인합니다."""
    try:
        settings = Settings.from_env()
        with OpenFiscalClient(settings) as client:
            result = client.smoke_test()
    except (ValueError, OSError, RuntimeError) as exc:
        typer.echo(f"연결 테스트 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    safe_result = {
        "requested_at": result["requested_at"],
        "api_url": result["api_url"],
        "top_level_keys": result["top_level_keys"],
    }
    typer.echo(json.dumps(safe_result, ensure_ascii=False, indent=2))


@app.command("collect")
def collect(
    max_pages: int = typer.Option(1, min=1, help="시험 수집할 최대 페이지 수"),
    year: int | None = typer.Option(None, help="회계연도. 실제 파라미터명은 API 명세 확인 후 매핑"),
    ministry: str | None = typer.Option(None, help="소관명. 실제 파라미터명은 API 명세 확인 후 매핑"),
    output_dir: Path = typer.Option(Path("data/raw/open_fiscal")),
) -> None:
    """원본 JSON을 변경하지 않고 페이지별로 보존합니다."""
    params: dict[str, object] = {}
    if year is not None:
        params["year"] = year
    if ministry:
        params["ministry"] = ministry

    try:
        settings = Settings.from_env()
        with OpenFiscalClient(settings) as client:
            paths = client.collect_pages(output_dir, max_pages=max_pages, **params)
    except (ValueError, OSError, RuntimeError) as exc:
        typer.echo(f"수집 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"원본 응답 {len(paths)}개 저장")
    for path in paths:
        typer.echo(f"- {path}")


if __name__ == "__main__":
    app()
