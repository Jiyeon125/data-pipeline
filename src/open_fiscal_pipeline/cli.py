from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from .client import OpenFiscalClient, collect_api
from .config import Settings, load_yaml

app = typer.Typer(no_args_is_help=True, help="열린재정 데이터 수집 파이프라인")

DEFAULT_DATASETS_PATH = Path("configs/datasets.yaml")


def _iter_api_datasets(
    datasets: dict[str, Any],
    dataset_id: str | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    items = datasets.get("datasets")
    if not isinstance(items, dict):
        raise ValueError("configs/datasets.yaml의 datasets는 객체(map)여야 합니다.")

    selected: list[tuple[str, dict[str, Any]]] = []
    for current_id, config in items.items():
        if dataset_id is not None and current_id != dataset_id:
            continue
        if not isinstance(config, dict):
            raise ValueError(f"데이터셋 설정이 객체가 아닙니다: {current_id}")
        if not config.get("enabled", True):
            continue
        if config.get("source_type") != "api":
            continue
        if not config.get("url"):
            raise ValueError(f"API 데이터셋 url이 비어 있습니다: {current_id}")
        selected.append((current_id, config))

    if dataset_id is not None and not selected:
        raise ValueError(f"활성화된 API 데이터셋을 찾을 수 없습니다: {dataset_id}")
    return selected


@app.command("smoke-test")
def smoke_test(
    dataset_id: str | None = typer.Option(
        None,
        help="테스트할 데이터셋 ID. 생략 시 configs/datasets.yaml의 첫 API 데이터셋 사용",
    ),
    config_path: Path = typer.Option(DEFAULT_DATASETS_PATH, help="데이터셋 설정 파일"),
) -> None:
    """인증키와 데이터셋 요청주소로 첫 페이지를 호출하고 응답 구조를 확인합니다."""
    try:
        settings = Settings.from_env()
        datasets = load_yaml(config_path)
        api_datasets = _iter_api_datasets(datasets, dataset_id=dataset_id)
        if not api_datasets:
            raise ValueError("활성화된 API 데이터셋이 없습니다.")
        selected_id, config = api_datasets[0]
        with OpenFiscalClient(settings) as client:
            result = client.smoke_test(config["url"])
    except (ValueError, OSError, RuntimeError, FileNotFoundError) as exc:
        typer.echo(f"연결 테스트 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    safe_result = {
        "dataset_id": selected_id,
        "requested_at": result["requested_at"],
        "api_url": result["api_url"],
        "top_level_keys": result["top_level_keys"],
    }
    typer.echo(json.dumps(safe_result, ensure_ascii=False, indent=2))


@app.command("collect")
def collect(
    max_pages: int = typer.Option(1, min=1, help="데이터셋별 시험 수집 최대 페이지 수"),
    year: int | None = typer.Option(None, help="회계연도. 실제 파라미터명은 API 명세 확인 후 매핑"),
    ministry: str | None = typer.Option(None, help="소관명. 실제 파라미터명은 API 명세 확인 후 매핑"),
    dataset_id: str | None = typer.Option(None, help="특정 데이터셋 ID만 수집"),
    config_path: Path = typer.Option(DEFAULT_DATASETS_PATH, help="데이터셋 설정 파일"),
    output_dir: Path = typer.Option(Path("data/raw")),
) -> None:
    """configs/datasets.yaml의 API 데이터셋을 순회하며 원본 JSON을 보존합니다."""
    params: dict[str, object] = {}
    if year is not None:
        params["year"] = year
    if ministry:
        params["ministry"] = ministry

    try:
        settings = Settings.from_env()
        datasets = load_yaml(config_path)
        api_datasets = _iter_api_datasets(datasets, dataset_id=dataset_id)
        if not api_datasets:
            raise ValueError("활성화된 API 데이터셋이 없습니다.")

        saved_all: list[Path] = []
        for current_id, config in api_datasets:
            paths = collect_api(
                url=config["url"],
                api_key=settings.api_key,
                output_dir=output_dir / current_id,
                max_pages=max_pages,
                dataset_id=current_id,
                settings=settings,
                **params,
            )
            typer.echo(f"[{current_id}] 원본 응답 {len(paths)}개 저장")
            for path in paths:
                typer.echo(f"- {path}")
            saved_all.extend(paths)
    except (ValueError, OSError, RuntimeError, FileNotFoundError) as exc:
        typer.echo(f"수집 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"총 {len(saved_all)}개 파일 저장")


if __name__ == "__main__":
    app()
