from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from .client import OpenFiscalClient, OpenFiscalError
from .config import ConfigError, DatasetConfig, Settings, load_datasets

app = typer.Typer(no_args_is_help=True, help="열린재정 데이터 수집 파이프라인")
DEFAULT_DATASETS_PATH = Path("configs/datasets.yaml")


def _logical_params(
    *,
    year: int | None,
    ministry: str | None,
    ministry_code: str | None,
    execution_month: str | None,
    supplementary_round: str | None,
    account_code: str | None,
    extra_params: list[str] | None,
) -> tuple[dict[str, Any], dict[str, str]]:
    logical: dict[str, Any] = {
        "year": year,
        "ministry": ministry,
        "ministry_code": ministry_code,
        "execution_month": execution_month,
        "supplementary_round": supplementary_round,
        "account_code": account_code,
    }
    direct: dict[str, str] = {}
    for item in extra_params or []:
        if "=" not in item:
            raise ConfigError(f"--param은 KEY=VALUE 형식이어야 합니다: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ConfigError(f"빈 파라미터 이름입니다: {item}")
        direct[key] = value.strip()
    return logical, direct


def _get_dataset(config_path: Path, dataset_id: str) -> DatasetConfig:
    datasets = load_datasets(config_path)
    dataset = datasets.get(dataset_id)
    if dataset is None:
        raise ConfigError(f"데이터셋을 찾을 수 없습니다: {dataset_id}")
    if not dataset.enabled:
        raise ConfigError(f"비활성화된 데이터셋입니다: {dataset_id}")
    return dataset


def _safe_output(dataset: DatasetConfig, page: Any) -> dict[str, Any]:
    record_keys = sorted(
        {str(key) for record in page.parsed.records[:5] for key in record.keys()}
    )
    expected = set(dataset.expected_fields)
    actual = set(record_keys)
    return {
        "dataset_id": dataset.dataset_id,
        "dataset_name": dataset.name,
        "requested_at": page.requested_at,
        "api_url": dataset.url,
        "result_code": page.parsed.result_code,
        "result_message": page.parsed.result_message,
        "total_count": page.parsed.total_count,
        "record_count": len(page.parsed.records),
        "top_level_keys": list(page.parsed.top_level_keys),
        "record_keys": record_keys,
        "missing_expected_fields": sorted(expected - actual) if actual else sorted(expected),
        "unexpected_fields": sorted(actual - expected) if expected else [],
    }


@app.command("doctor")
def doctor(
    config_path: Path = typer.Option(DEFAULT_DATASETS_PATH, help="데이터셋 설정 파일"),
) -> None:
    """환경변수와 데이터셋 명세를 검사합니다. 네트워크 호출은 하지 않습니다."""
    try:
        settings = Settings.from_env(require_api_key=False)
        datasets = load_datasets(config_path)
    except (ConfigError, OSError, FileNotFoundError, ValueError) as exc:
        typer.echo(f"설정 검사 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    rows = []
    for dataset in datasets.values():
        rows.append(
            {
                "dataset_id": dataset.dataset_id,
                "source_type": dataset.source_type,
                "enabled": dataset.enabled,
                "required": list(dataset.required),
                "url_configured": bool(dataset.url) if dataset.source_type == "api" else None,
            }
        )

    result = {
        "api_key_configured": bool(settings.api_key),
        "page_size": settings.page_size,
        "settlement_dir": str(settings.settlement_dir) if settings.settlement_dir else None,
        "settlement_dir_exists": (
            settings.settlement_dir.exists() if settings.settlement_dir else None
        ),
        "ministry_code_configured": bool(settings.ministry_code),
        "datasets": rows,
    }
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("probe")
def probe(
    dataset_id: str = typer.Argument(..., help="시험 호출할 데이터셋 ID"),
    year: int | None = typer.Option(None, help="회계연도"),
    ministry: str | None = typer.Option(None, help="소관명"),
    ministry_code: str | None = typer.Option(None, help="소관코드"),
    execution_month: str | None = typer.Option(None, help="집행월. 예: 12 또는 202412"),
    supplementary_round: str | None = typer.Option(None, help="추경차수"),
    account_code: str | None = typer.Option(None, help="회계코드"),
    page_size: int = typer.Option(5, min=1, max=1000),
    param: list[str] | None = typer.Option(None, "--param", help="추가 API 인자 KEY=VALUE"),
    config_path: Path = typer.Option(DEFAULT_DATASETS_PATH, help="데이터셋 설정 파일"),
) -> None:
    """한 데이터셋의 첫 페이지를 호출하고 응답 필드·건수를 검사합니다."""
    try:
        settings = Settings.from_env()
        dataset = _get_dataset(config_path, dataset_id)
        if dataset.source_type != "api":
            raise ConfigError(f"API 데이터셋이 아닙니다: {dataset_id}")
        logical, direct = _logical_params(
            year=year,
            ministry=ministry,
            ministry_code=ministry_code or settings.ministry_code,
            execution_month=execution_month,
            supplementary_round=supplementary_round,
            account_code=account_code,
            extra_params=param,
        )
        params = dataset.build_params(logical)
        params.update(direct)
        with OpenFiscalClient(settings) as client:
            page = client.request_page(
                dataset,
                page_index=1,
                page_size=page_size,
                params=params,
            )
    except (ConfigError, OpenFiscalError, OSError, FileNotFoundError, ValueError) as exc:
        typer.echo(f"시험 호출 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(json.dumps(_safe_output(dataset, page), ensure_ascii=False, indent=2))


@app.command("smoke-test")
def smoke_test(
    dataset_id: str = typer.Option("expenditure_budget_init", help="시험할 데이터셋 ID"),
    year: int = typer.Option(2024, help="회계연도"),
    ministry: str = typer.Option("중소벤처기업부", help="소관명"),
    config_path: Path = typer.Option(DEFAULT_DATASETS_PATH, help="데이터셋 설정 파일"),
) -> None:
    """기존 명령 호환용: 총액 API를 5건 시험 호출합니다."""
    probe(
        dataset_id=dataset_id,
        year=year,
        ministry=ministry,
        ministry_code=None,
        execution_month=None,
        supplementary_round=None,
        account_code=None,
        page_size=5,
        param=None,
        config_path=config_path,
    )


@app.command("probe-all")
def probe_all(
    year: int = typer.Option(2024, help="회계연도"),
    ministry: str = typer.Option("중소벤처기업부", help="소관명"),
    ministry_code: str | None = typer.Option(None, help="월별 집행용 소관코드"),
    execution_month: str | None = typer.Option("12", help="월별 집행용 집행월"),
    supplementary_round: str | None = typer.Option("1", help="추경차수"),
    page_size: int = typer.Option(5, min=1, max=1000),
    config_path: Path = typer.Option(DEFAULT_DATASETS_PATH, help="데이터셋 설정 파일"),
) -> None:
    """호출에 필요한 값이 갖춰진 API를 모두 한 페이지씩 시험합니다."""
    try:
        settings = Settings.from_env()
        datasets = load_datasets(config_path)
    except (ConfigError, OSError, FileNotFoundError, ValueError) as exc:
        typer.echo(f"설정 로드 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    logical = {
        "year": year,
        "ministry": ministry,
        "ministry_code": ministry_code or settings.ministry_code,
        "execution_month": execution_month,
        "supplementary_round": supplementary_round,
        "account_code": None,
    }
    results: list[dict[str, Any]] = []

    with OpenFiscalClient(settings) as client:
        for dataset in datasets.values():
            if not dataset.enabled or dataset.source_type != "api":
                continue
            try:
                params = dataset.build_params(logical)
                page = client.request_page(
                    dataset,
                    page_index=1,
                    page_size=page_size,
                    params=params,
                )
                results.append({"status": "ok", **_safe_output(dataset, page)})
            except ConfigError as exc:
                results.append(
                    {
                        "status": "skipped",
                        "dataset_id": dataset.dataset_id,
                        "reason": str(exc),
                    }
                )
            except OpenFiscalError as exc:
                results.append(
                    {
                        "status": "error",
                        "dataset_id": dataset.dataset_id,
                        "reason": str(exc),
                    }
                )

    typer.echo(json.dumps(results, ensure_ascii=False, indent=2))
    if any(row["status"] == "error" for row in results):
        raise typer.Exit(code=1)


@app.command("collect")
def collect(
    dataset_id: str = typer.Argument(..., help="수집할 데이터셋 ID"),
    year: int | None = typer.Option(None, help="회계연도"),
    ministry: str | None = typer.Option(None, help="소관명"),
    ministry_code: str | None = typer.Option(None, help="소관코드"),
    execution_month: str | None = typer.Option(None, help="집행월"),
    supplementary_round: str | None = typer.Option(None, help="추경차수"),
    account_code: str | None = typer.Option(None, help="회계코드"),
    max_pages: int | None = typer.Option(None, min=1, help="최대 페이지. 생략 시 끝까지"),
    page_size: int | None = typer.Option(None, min=1, max=1000),
    param: list[str] | None = typer.Option(None, "--param", help="추가 API 인자 KEY=VALUE"),
    config_path: Path = typer.Option(DEFAULT_DATASETS_PATH, help="데이터셋 설정 파일"),
    output_dir: Path = typer.Option(Path("data/raw"), help="원본 저장 디렉터리"),
) -> None:
    """데이터셋을 페이지 끝까지 수집하고 원본 JSON을 보존합니다."""
    try:
        settings = Settings.from_env()
        dataset = _get_dataset(config_path, dataset_id)
        if dataset.source_type != "api":
            raise ConfigError(f"API 데이터셋이 아닙니다: {dataset_id}")
        logical, direct = _logical_params(
            year=year,
            ministry=ministry,
            ministry_code=ministry_code or settings.ministry_code,
            execution_month=execution_month,
            supplementary_round=supplementary_round,
            account_code=account_code,
            extra_params=param,
        )
        params = dataset.build_params(logical)
        params.update(direct)
        partition = output_dir / dataset_id
        if year is not None:
            partition /= f"year={year}"
        with OpenFiscalClient(settings) as client:
            paths = client.collect_pages(
                dataset,
                output_dir=partition,
                params=params,
                max_pages=max_pages,
                page_size=page_size,
            )
    except (ConfigError, OpenFiscalError, OSError, FileNotFoundError, ValueError) as exc:
        typer.echo(f"수집 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"[{dataset_id}] 원본 응답 {len(paths)}개 저장")
    for path in paths:
        typer.echo(f"- {path}")


if __name__ == "__main__":
    app()
