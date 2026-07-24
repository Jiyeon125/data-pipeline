"""마스터 테이블 엔지니어링 CLI 진입점."""

from __future__ import annotations

import typer

app = typer.Typer(no_args_is_help=True, help="성과·재정 마스터 테이블 엔지니어링")


@app.callback()
def main() -> None:
    """마스터 엔지니어링 명령을 실행합니다."""


@app.command("status")
def status() -> None:
    """현재 스캐폴딩 상태를 출력합니다."""
    typer.echo("master_engineering: scaffolded")


if __name__ == "__main__":
    app()
