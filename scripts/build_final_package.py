from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "exports" / "frozen_manual_v1_20260731"

DATA_FILES = (
    Path("data/analytics/multi_ministry_priority_scenarios/candidate_population.csv"),
    Path("data/analytics/multi_ministry_priority_scenarios/full_population_review_work_queue.csv"),
    Path("data/analytics/multi_ministry_priority_scenarios/scenario_scores.csv"),
    Path("data/analytics/multi_ministry_priority_scenarios/rank_stability.csv"),
    Path("data/analytics/multi_ministry_priority_scenarios/scenario_spearman.csv"),
    Path("data/analytics/multi_ministry_priority_scenarios/top_k_overlap.csv"),
    Path("data/analytics/multi_ministry_priority_scenarios/analysis_summary.json"),
    Path("data/analytics/priority_case_evidence_review/selected_cases.csv"),
    Path("data/analytics/priority_case_evidence_review/case_validation_summary.json"),
    Path("data/analytics/definition_validation/definition_validation_summary.json"),
    Path("data/analytics/m3_audit/m3_methodology_audit_summary.json"),
    Path("data/analytics/decision_support/decision_support_summary.json"),
)

DOCUMENT_FILES = (
    Path("docs/FINAL_REPORT.md"),
    Path("docs/MANUAL_V1_BASELINE_FREEZE.md"),
    Path("docs/ANALYSIS_DECISIONS.md"),
    Path("docs/MVP_ANALYSIS_COMPLETION_AUDIT.md"),
    Path("docs/REPRODUCIBILITY.md"),
    Path("docs/FINAL_QA.md"),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_package(output_dir: Path = DEFAULT_OUTPUT) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_files: list[dict[str, object]] = []
    dictionary_rows: list[dict[str, object]] = []

    for relative in (*DATA_FILES, *DOCUMENT_FILES):
        source = ROOT / relative
        if not source.is_file():
            raise FileNotFoundError(f"필수 패키지 입력이 없습니다: {relative}")

        group = "data" if relative in DATA_FILES else "docs"
        destination = output_dir / group / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

        item: dict[str, object] = {
            "source": relative.as_posix(),
            "packaged_path": destination.relative_to(output_dir).as_posix(),
            "bytes": destination.stat().st_size,
            "sha256": _sha256(destination),
        }
        if source.suffix.lower() == ".csv":
            frame = pd.read_csv(source, low_memory=False)
            item["row_count"] = len(frame)
            item["column_count"] = len(frame.columns)
            for column in frame.columns:
                dictionary_rows.append(
                    {
                        "file": source.name,
                        "column": column,
                        "dtype": str(frame[column].dtype),
                        "missing_count": int(frame[column].isna().sum()),
                    }
                )
        manifest_files.append(item)

    dictionary_path = output_dir / "DATA_DICTIONARY.csv"
    pd.DataFrame(dictionary_rows).to_csv(dictionary_path, index=False, encoding="utf-8-sig")
    manifest_files.append(
        {
            "source": "generated",
            "packaged_path": dictionary_path.relative_to(output_dir).as_posix(),
            "bytes": dictionary_path.stat().st_size,
            "sha256": _sha256(dictionary_path),
            "row_count": len(dictionary_rows),
            "column_count": 4,
        }
    )
    manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "baseline_id": "manual-v1-20260731",
        "scope": "4개 부처 2022~2024 점검 우선순위 기준선",
        "interpretation": "최종 정책 우선순위가 아닌 사람 검토용 탐색 산출물",
        "excluded": [
            "원본 PDF·수기 엑셀·API 원본",
            "환경변수·인증키",
            "외부 LLM 산출물",
        ],
        "files": manifest_files,
    }
    manifest_path = output_dir / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    for item in manifest_files:
        packaged = output_dir / str(item["packaged_path"])
        if _sha256(packaged) != item["sha256"]:
            raise RuntimeError(f"패키지 해시 검증 실패: {packaged}")
    packaged_files = {
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*")
        if path.is_file() and path != manifest_path
    }
    expected_files = {str(item["packaged_path"]) for item in manifest_files}
    if packaged_files != expected_files:
        raise RuntimeError(
            f"패키지 파일 목록 불일치: extra={packaged_files - expected_files}, "
            f"missing={expected_files - packaged_files}"
        )

    print(
        f"final package: {len(manifest_files)} files, "
        f"{len(dictionary_rows)} dictionary rows -> {output_dir}"
    )
    return manifest_path


if __name__ == "__main__":
    build_package()
