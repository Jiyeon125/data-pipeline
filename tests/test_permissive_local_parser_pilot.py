from scripts.permissive_local_parser_pilot import (
    _chunks,
    _classify_license_text,
    _count_grounded_nodes,
    _opendataloader_table_rows,
    _same_row_matches,
    _write_csv,
)


def test_opendataloader_batches_avoid_windows_command_length_limit() -> None:
    rows = [{"input_pdf": str(index)} for index in range(161)]

    assert [len(batch) for batch in _chunks(rows)] == [80, 80, 1]


def test_csv_writer_supports_document_specific_fields(tmp_path) -> None:
    path = tmp_path / "mixed.csv"

    _write_csv(path, [{"plan": "1"}, {"report": "2"}])

    assert path.read_text(encoding="utf-8-sig").splitlines() == [
        "plan,report",
        "1,",
        ",2",
    ]


def test_license_gate_does_not_treat_lgpl_as_gpl() -> None:
    restricted, conditional = _classify_license_text("LGPL-3.0 AND MPL-2.0")

    assert restricted == []
    assert conditional == ["LGPL", "MPL"]


def test_license_gate_still_flags_gpl_and_agpl() -> None:
    restricted, conditional = _classify_license_text("GPL-3.0 OR AGPL-3.0")

    assert restricted == ["AGPL", "GPL"]
    assert conditional == []


def test_grounded_node_count_is_recursive() -> None:
    payload = {
        "kids": [
            {"type": "heading", "bounding box": [1, 2, 3, 4]},
            {"type": "table", "kids": [{"type": "cell", "bounding box": []}]},
        ]
    }

    assert _count_grounded_nodes(payload) == (3, 1)


def test_same_row_match_checks_repeated_indicator_rows() -> None:
    rows = ["고용률 설명", "| 고용률 | 목표 | 68.8 |", "68.8은 다른 지표 값"]

    assert _same_row_matches("고용률", {"target": "68.8"}, rows) == {"target": True}
    assert _same_row_matches("취업률", {"target": "68.8"}, rows) == {"target": False}


def test_opendataloader_rows_expand_merged_indicator_cells(tmp_path) -> None:
    path = tmp_path / "page.json"
    path.write_text(
        '{"kids":[{"type":"table","number of rows":2,"number of columns":2,'
        '"rows":[{"cells":[{"row number":1,"row span":2,"column number":1,'
        '"column span":1,"kids":[{"content":"고용률"}]},{"row number":1,'
        '"column number":2,"kids":[{"content":"목표"}]}]},{"cells":['
        '{"row number":2,"column number":2,"kids":[{"content":"68.8"}]}]}]}]}',
        encoding="utf-8",
    )

    assert _opendataloader_table_rows(path) == ["고용률 | 목표", "고용률 | 68.8"]
