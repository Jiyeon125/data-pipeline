from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

from open_fiscal_pipeline.client import OpenFiscalClient
from open_fiscal_pipeline.config import Settings, load_datasets


def main() -> None:
    parser = argparse.ArgumentParser(
        description="월별 지출운용상황 전체 결과에서 소관명에 해당하는 OFFC_CD를 찾습니다."
    )
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--ministry", required=True)
    parser.add_argument("--execution-month")
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--max-pages", type=int, default=200)
    parser.add_argument(
        "--config-path",
        type=Path,
        default=Path("configs/datasets.yaml"),
    )
    args = parser.parse_args()

    settings = Settings.from_env()
    dataset = load_datasets(args.config_path)["monthly_expenditure"]

    logical = {
        "year": args.year,
        "execution_month": args.execution_month,
        "ministry_code": None,
        "account_code": None,
    }
    params = dataset.build_params(logical)

    matches: list[dict[str, object]] = []
    code_counts: Counter[str] = Counter()
    scanned = 0

    with OpenFiscalClient(settings) as client:
        for page_index in range(1, args.max_pages + 1):
            page = client.request_page(
                dataset,
                page_index=page_index,
                page_size=args.page_size,
                params=params,
            )
            scanned += len(page.parsed.records)

            for record in page.parsed.records:
                if str(record.get("OFFC_NM", "")).strip() != args.ministry:
                    continue
                code = str(record.get("OFFC_CD", "")).strip()
                if code:
                    code_counts[code] += 1
                if len(matches) < 20:
                    matches.append(
                        {
                            "OFFC_CD": record.get("OFFC_CD"),
                            "OFFC_NM": record.get("OFFC_NM"),
                            "EXE_M": record.get("EXE_M"),
                            "FSCL_CD": record.get("FSCL_CD"),
                            "FSCL_NM": record.get("FSCL_NM"),
                            "PGM_CD": record.get("PGM_CD"),
                            "PGM_NM": record.get("PGM_NM"),
                            "SACTV_CD": record.get("SACTV_CD"),
                            "SACTV_NM": record.get("SACTV_NM"),
                        }
                    )

            total = page.parsed.total_count
            if total is not None and page_index >= math.ceil(total / args.page_size):
                break
            if page.parsed.is_no_data or not page.parsed.records:
                break

    result = {
        "year": args.year,
        "execution_month": args.execution_month,
        "target_ministry": args.ministry,
        "scanned_record_count": scanned,
        "matched_record_count": sum(code_counts.values()),
        "ministry_code_counts": dict(code_counts),
        "sample_matches": matches,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
