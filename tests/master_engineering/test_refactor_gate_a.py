from __future__ import annotations

import pandas as pd

from master_engineering.quality.refactor_gate_a import _scope


def test_gate_a_scope_is_four_ministries_and_2022_to_2024() -> None:
    frame = pd.DataFrame(
        {
            "ministry_code": ["019", "101", "102", "162"],
            "fiscal_year": [2022, 2023, 2025, 2024],
        }
    )

    scoped = _scope(frame)

    assert scoped.index.tolist() == [0, 3]
