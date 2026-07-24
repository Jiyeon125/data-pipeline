from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from .client import OpenFiscalClient, OpenFiscalError
from .config import ConfigError, DatasetConfig, Settings, load_datasets, load_ministries
from .monthly import MonthlyResult, build_summary, collect_ministry_month
from .normalize_monthly import normalize_monthly

app = typer.Typer(no_args_is_help=True, help="열린재정 데이터 수집 파이프라인")
DEFAULT_DATASETS_PATH = Path("configs/datasets.yaml")
DEFAULT_MINISTRIES_PATH = Path("configs/ministries.yaml")


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


def _response_status(page: Any) -> str:
    return "no_data" if page.parsed.is_no_data else "ok"


def _safe_output(dataset: DatasetConfig, page: Any) -> dict[str, Any]:
    record_keys = sorted(
        {str(key) for record in page.parsed.records[:5] for key in record}
    )
    expected = set(dataset.expected_fields)
    actual = set(record_keys)
    return {
        "response_status": _response_status(page),
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
    execution_month: str | None = typer.Option(None, help="집행연월. 예: 202412"),
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
    execution_month: str | None = typer.Option("202412", help="월별 집행용 집행연월"),
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
                results.append({"status": _response_status(page), **_safe_output(dataset, page)})
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


@app.command("collect-monthly-all")
def collect_monthly_all(
    start_year: int = typer.Option(2022, min=2000, max=2100, help="시작 회계연도"),
    end_year: int = typer.Option(2025, min=2000, max=2100, help="종료 회계연도"),
    ministry_code: str | None = typer.Option(
        None, help="특정 소관코드만 수집. 생략하면 설정된 전체 부처"
    ),
    page_size: int | None = typer.Option(None, min=1, max=1000, help="페이지당 건수"),
    resume: bool = typer.Option(False, help="미완료 페이지부터 이어서 수집"),
    overwrite: bool = typer.Option(False, help="기존 부처·연월 파일을 삭제 후 다시 수집"),
    config_path: Path = typer.Option(DEFAULT_DATASETS_PATH, help="데이터셋 설정 파일"),
    ministries_path: Path = typer.Option(DEFAULT_MINISTRIES_PATH, help="부처 설정 파일"),
    output_dir: Path = typer.Option(
        Path("data/raw/monthly_expenditure"), help="월별 지출 원본 저장 디렉터리"
    ),
) -> None:
    """설정된 부처의 연도·월별 지출운용상황을 일괄 수집합니다."""
    try:
        if start_year > end_year:
            raise ConfigError("--start-year는 --end-year보다 클 수 없습니다.")
        if resume and overwrite:
            raise ConfigError("--resume과 --overwrite는 동시에 사용할 수 없습니다.")

        settings = Settings.from_env()
        dataset = _get_dataset(config_path, "monthly_expenditure")
        ministries = load_ministries(ministries_path)
        if ministry_code:
            ministry = ministries.get(ministry_code)
            if ministry is None:
                raise ConfigError(f"설정에 없는 소관코드입니다: {ministry_code}")
            selected = [ministry]
        else:
            selected = list(ministries.values())
        actual_page_size = page_size or settings.page_size
    except (ConfigError, OSError, FileNotFoundError, ValueError) as exc:
        typer.echo(f"설정 로드 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    results: list[MonthlyResult] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    run_timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    failure_log_path = output_dir / f"collection_failures_{run_timestamp}.jsonl"
    with OpenFiscalClient(settings) as client:
        for ministry in selected:
            for year in range(start_year, end_year + 1):
                for month in range(1, 13):
                    execution_month = f"{year}{month:02d}"
                    typer.echo(f"수집 중: {ministry.code} {ministry.name} {execution_month}")
                    try:
                        result = collect_ministry_month(
                            client,
                            dataset,
                            ministry,
                            year,
                            month,
                            output_dir=output_dir,
                            page_size=actual_page_size,
                            resume=resume,
                            overwrite=overwrite,
                        )
                    except (OpenFiscalError, OSError, ValueError, json.JSONDecodeError) as exc:
                        result = MonthlyResult(
                            ministry.code,
                            ministry.name,
                            year,
                            execution_month,
                            "failure",
                            error=str(exc),
                        )
                        typer.echo(
                            f"실패(계속 진행): {ministry.code} {execution_month}: {exc}",
                            err=True,
                        )
                        with failure_log_path.open("a", encoding="utf-8") as handle:
                            handle.write(
                                json.dumps(asdict(result), ensure_ascii=False) + "\n"
                            )
                    results.append(result)

    summary = build_summary(results)
    summary_path = output_dir / f"collection_summary_{run_timestamp}.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))
    typer.echo(f"수집 요약 저장: {summary_path}")
    if summary["status_counts"]["failure"]:
        raise typer.Exit(code=1)


@app.command("normalize-monthly")
def normalize_monthly_command(
    input_dir: Path = typer.Option(
        Path("data/raw/monthly_expenditure"),
        help="월별 지출 원본 JSON 디렉터리",
    ),
    output_dir: Path = typer.Option(
        Path("data/processed/monthly_expenditure"),
        help="정규화 결과 저장 디렉터리",
    ),
    format: str = typer.Option(
        "parquet",
        "--format",
        help="출력 형식: parquet, csv, both",
    ),
    start_year: int | None = typer.Option(None, help="시작 회계연도 필터"),
    end_year: int | None = typer.Option(None, help="종료 회계연도 필터"),
    ministry_code: str | None = typer.Option(None, help="특정 소관코드만 정규화"),
    overwrite: bool = typer.Option(False, help="기존 출력 파일이 있으면 덮어쓰기"),
) -> None:
    """월별 지출운용상황 원본 JSON을 분석용 테이블로 정규화합니다."""
    try:
        if start_year is not None and end_year is not None and start_year > end_year:
            raise ConfigError("--start-year는 --end-year보다 클 수 없습니다.")
        normalized_format = format.strip().lower()
        if normalized_format not in {"parquet", "csv", "both"}:
            raise ConfigError("--format은 parquet, csv, both 중 하나여야 합니다.")
        result = normalize_monthly(
            input_dir=input_dir,
            output_dir=output_dir,
            output_format=normalized_format,  # type: ignore[arg-type]
            start_year=start_year,
            end_year=end_year,
            ministry_code=ministry_code,
            overwrite=overwrite,
        )
    except (ConfigError, OSError, FileExistsError, ValueError) as exc:
        typer.echo(f"정규화 실패: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    summary = {
        key: result.summary[key]
        for key in (
            "files_read",
            "raw_record_count",
            "normalized_row_count",
            "masked_row_count",
            "duplicate_key_row_count",
            "cumulative_decrease_count",
            "execution_month_year_mismatch_count",
            "monthly_cumulative_mismatch_count",
            "raw_vs_normalized_difference",
            "failed_files",
        )
        if key in result.summary
    }
    typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))
    for path in result.output_paths:
        typer.echo(f"- {path}")
    if result.failed_files:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
