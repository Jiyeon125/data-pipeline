"""성과 문서 파이프라인 CLI 진입점.

실제 명령은 문서 인벤토리와 추출 스키마가 확정되는 순서대로 추가합니다.
"""

from __future__ import annotations

import typer

app = typer.Typer(no_args_is_help=True, help="성과계획서·성과보고서 파싱 파이프라인")


@app.callback()
def main() -> None:
    """성과 문서 파이프라인 명령을 실행합니다."""


@app.command("status")
def status() -> None:
    """현재 스캐폴딩 상태를 출력합니다."""
    typer.echo("performance_pipeline: scaffolded")


if __name__ == "__main__":
    app()
