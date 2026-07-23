from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


class ConfigError(ValueError):
    """설정 파일이나 환경변수가 유효하지 않을 때 발생합니다."""


@dataclass(frozen=True)
class Settings:
    api_key: str
    page_size: int = 1000
    request_interval_seconds: float = 0.4
    timeout_seconds: float = 30.0
    settlement_dir: Path | None = None
    ministry_code: str | None = None

    @classmethod
    def from_env(cls, *, require_api_key: bool = True) -> "Settings":
        load_dotenv()

        api_key = os.environ.get("OPEN_FISCAL_API_KEY", "").strip()
        if require_api_key and not api_key:
            raise ConfigError("OPEN_FISCAL_API_KEY가 비어 있습니다. .env 파일을 확인하세요.")

        settlement_text = os.environ.get("OPEN_FISCAL_SETTLEMENT_DIR", "").strip()
        settlement_dir = Path(settlement_text) if settlement_text else None

        page_size = int(os.getenv("OPEN_FISCAL_PAGE_SIZE", "1000"))
        if not 1 <= page_size <= 1000:
            raise ConfigError("OPEN_FISCAL_PAGE_SIZE는 1~1000이어야 합니다.")

        return cls(
            api_key=api_key,
            page_size=page_size,
            request_interval_seconds=float(
                os.getenv("OPEN_FISCAL_REQUEST_INTERVAL_SECONDS", "0.4")
            ),
            timeout_seconds=float(os.getenv("OPEN_FISCAL_TIMEOUT", "30")),
            settlement_dir=settlement_dir,
            ministry_code=os.getenv("OPEN_FISCAL_MINISTRY_CODE", "").strip() or None,
        )


@dataclass(frozen=True)
class DatasetConfig:
    dataset_id: str
    name: str
    source_type: str
    enabled: bool = True
    url: str | None = None
    service_name: str | None = None
    parameter_map: dict[str, str] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    defaults: dict[str, str] = field(default_factory=dict)
    expected_fields: tuple[str, ...] = ()
    amount_fields: tuple[str, ...] = ()
    directory_env: str | None = None
    file_pattern: str | None = None

    @classmethod
    def from_mapping(cls, dataset_id: str, raw: dict[str, Any]) -> "DatasetConfig":
        if not isinstance(raw, dict):
            raise ConfigError(f"데이터셋 설정은 객체여야 합니다: {dataset_id}")

        source_type = str(raw.get("source_type", "")).strip()
        if source_type not in {"api", "local_csv"}:
            raise ConfigError(
                f"source_type은 api 또는 local_csv여야 합니다: {dataset_id}"
            )

        url = raw.get("url")
        if source_type == "api" and not url:
            raise ConfigError(f"API url이 비어 있습니다: {dataset_id}")

        return cls(
            dataset_id=dataset_id,
            name=str(raw.get("name", dataset_id)),
            source_type=source_type,
            enabled=bool(raw.get("enabled", True)),
            url=str(url) if url else None,
            service_name=(str(raw["service_name"]) if raw.get("service_name") else None),
            parameter_map={
                str(key): str(value)
                for key, value in (raw.get("parameter_map") or {}).items()
            },
            required=tuple(str(value) for value in (raw.get("required") or [])),
            defaults={
                str(key): str(value)
                for key, value in (raw.get("defaults") or {}).items()
            },
            expected_fields=tuple(
                str(value) for value in (raw.get("expected_fields") or [])
            ),
            amount_fields=tuple(
                str(value) for value in (raw.get("amount_fields") or [])
            ),
            directory_env=(
                str(raw["directory_env"]) if raw.get("directory_env") else None
            ),
            file_pattern=(str(raw["file_pattern"]) if raw.get("file_pattern") else None),
        )

    def build_params(self, logical_params: dict[str, Any]) -> dict[str, str]:
        missing = [
            name
            for name in self.required
            if logical_params.get(name) in (None, "") and name not in self.defaults
        ]
        if missing:
            raise ConfigError(
                f"[{self.dataset_id}] 필수 입력이 없습니다: {', '.join(missing)}"
            )

        result = dict(self.defaults)
        for logical_name, api_name in self.parameter_map.items():
            value = logical_params.get(logical_name)
            if value not in (None, ""):
                result[api_name] = str(value)
        return result


def load_yaml(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {config_path}")

    with config_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise ConfigError(f"YAML 최상위는 객체여야 합니다: {config_path}")
    return data


def load_datasets(path: str | Path) -> dict[str, DatasetConfig]:
    raw = load_yaml(path)
    items = raw.get("datasets")
    if not isinstance(items, dict):
        raise ConfigError("configs/datasets.yaml의 datasets는 객체(map)여야 합니다.")
    return {
        str(dataset_id): DatasetConfig.from_mapping(str(dataset_id), config)
        for dataset_id, config in items.items()
    }
