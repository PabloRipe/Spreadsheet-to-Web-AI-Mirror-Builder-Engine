"""Testes do serializador ``mirror.json``."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from spreadsheet_mirror.config import MirrorConfig
from spreadsheet_mirror.reader import load_workbook_data
from spreadsheet_mirror.serializer import SCHEMA_VERSION, serialize_workbook


def _serialize(path: Path, config: MirrorConfig | None = None):
    data = load_workbook_data(path, config)
    document, editable_by_sheet, warnings = serialize_workbook(data, config)
    return document, editable_by_sheet, warnings


def _sheet(document, name):
    return next(sheet for sheet in document["sheets"] if sheet["name"] == name)


def _cell(sheet, ref):
    return next(cell for cell in sheet["cells"] if cell["ref"] == ref)


def test_document_structure(sample_workbook: Path):
    document, editable_by_sheet, warnings = _serialize(sample_workbook)
    assert document["schema_version"] == SCHEMA_VERSION
    assert set(document) == {"schema_version", "meta", "styles", "sheets"}
    assert document["meta"]["source"] == "relatorio.xlsx"
    assert document["meta"]["stats"]["sheets"] == 2
    assert document["meta"]["stats"]["styles"] >= 3
    assert document["meta"]["theme"]["source"] == "workbook"
    assert document["styles"]
    assert "Vendas" in editable_by_sheet
    assert isinstance(warnings, list)


def test_sheet_metadata(sample_workbook: Path):
    document, _, _ = _serialize(sample_workbook)
    vendas = _sheet(document, "Vendas")
    assert vendas["state"] == "visible"
    assert vendas["max_row"] == 7
    assert vendas["max_col"] == 4
    assert vendas["freeze_panes"] == "A3"
    assert vendas["merged_ranges"] == ["A1:D1"]
    widths = {item["letter"]: item for item in vendas["columns"]}
    assert widths["A"]["width"] == 20
    assert widths["B"]["width"] == 12
    assert widths["C"]["hidden"] is True
    rows = {item["index"]: item for item in vendas["rows"]}
    assert rows[4]["height"] == 30
    entradas = _sheet(document, "Entradas")
    assert entradas["tab_color"]["hex"] == "#9BBB59"


def test_merged_cell_serialization(sample_workbook: Path):
    document, _, _ = _serialize(sample_workbook)
    vendas = _sheet(document, "Vendas")
    a1 = _cell(vendas, "A1")
    assert a1["merged"] == "A1:D1"
    assert a1["rowspan"] == 1
    assert a1["colspan"] == 4
    assert a1["editavel"] is False
    assert "merged" in a1["editavel_motivo"]
    refs = {cell["ref"] for cell in vendas["cells"]}
    assert {"B1", "C1", "D1"}.isdisjoint(refs)


def test_editability_flags(sample_workbook: Path):
    document, _, _ = _serialize(sample_workbook, MirrorConfig(header_rows=(2,)))
    vendas = _sheet(document, "Vendas")
    assert _cell(vendas, "A2")["editavel"] is False
    assert "header" in _cell(vendas, "A2")["editavel_motivo"]
    assert _cell(vendas, "B3")["editavel"] is True
    assert "default_editable" in _cell(vendas, "B3")["editavel_motivo"]
    assert _cell(vendas, "C3")["editavel"] is True
    assert _cell(vendas, "D3")["editavel"] is False
    assert "formula" in _cell(vendas, "D3")["editavel_motivo"]
    assert _cell(vendas, "A7")["editavel"] is False
    assert "bold" in _cell(vendas, "A7")["editavel_motivo"]


def test_style_deduplication(sample_workbook: Path):
    document, _, _ = _serialize(sample_workbook)
    vendas = _sheet(document, "Vendas")
    assert _cell(vendas, "A2")["style"] == _cell(vendas, "B2")["style"]


def test_formula_without_cached_value(sample_workbook: Path):
    document, _, _ = _serialize(sample_workbook)
    d3 = _cell(_sheet(document, "Vendas"), "D3")
    assert d3["formula"] == "=B3*C3"
    assert d3["value"] is None
    assert d3["cached_value"] is None
    assert d3["value_type"] == "null"


def test_formula_with_cached_value(cached_workbook: Path):
    document, _, _ = _serialize(cached_workbook)
    sheet = _sheet(document, "Calculos")
    a3 = _cell(sheet, "A3")
    b1 = _cell(sheet, "B1")
    assert a3["formula"] == "=SUM(A1:A2)"
    assert a3["value"] == 5
    assert a3["cached_value"] == 5
    assert a3["value_type"] == "number"
    assert b1["formula"] == "=A1*2"
    assert b1["value"] == 4


def test_value_types(tmp_path: Path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Tipos"
    ws["A1"] = 123
    ws["A2"] = 1.5
    ws["A3"] = True
    ws["A4"] = "texto"
    ws["A5"] = dt.date(2024, 1, 15)
    ws["A6"] = dt.datetime(2024, 1, 15, 10, 30)
    ws["A7"] = dt.timedelta(hours=2, minutes=30)
    ws["A8"] = "=1/0"
    ws["A8"].data_type = "e"
    for row in range(1, 9):
        ws.cell(row=row, column=2).fill = PatternFill("solid", fgColor="FFEEEEEE")
    path = tmp_path / "tipos.xlsx"
    wb.save(path)
    document, _, _ = _serialize(path)
    sheet = _sheet(document, "Tipos")
    types = {cell["ref"]: cell["value_type"] for cell in sheet["cells"]}
    assert types["A1"] == "number"
    assert types["A2"] == "number"
    assert types["A3"] == "boolean"
    assert types["A4"] == "string"
    assert types["A5"] == "datetime"
    assert types["A6"] == "datetime"
    assert types["A7"] == "duration"
    values = {cell["ref"]: cell["value"] for cell in sheet["cells"]}
    assert values["A7"] == 9000.0


def test_max_cells_warning(sample_workbook: Path):
    cfg = MirrorConfig(max_cells_per_sheet=4)
    document, _, _ = _serialize(sample_workbook, cfg)
    vendas = _sheet(document, "Vendas")
    assert vendas["max_row"] == 1
    assert any("excede o limite" in warning for warning in document["meta"]["warnings"])


def test_ignore_hidden_sheets(tmp_path: Path, sample_workbook: Path):
    wb = load_workbook(sample_workbook)
    wb["Entradas"].sheet_state = "hidden"
    hidden_path = tmp_path / "oculto.xlsx"
    wb.save(hidden_path)
    document, _, _ = _serialize(hidden_path, MirrorConfig(ignore_hidden_sheets=True))
    names = [sheet["name"] for sheet in document["sheets"]]
    assert names == ["Vendas"]
    assert any("ignorada" in warning for warning in document["meta"]["warnings"])


def test_include_empty_cells(tmp_path: Path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Vazia"
    ws["A1"] = "x"
    ws["B2"] = "y"
    path = tmp_path / "vazia.xlsx"
    wb.save(path)

    document, _, _ = _serialize(path, MirrorConfig())
    assert len(_sheet(document, "Vazia")["cells"]) == 2

    document, _, _ = _serialize(path, MirrorConfig(include_empty_cells=True))
    assert len(_sheet(document, "Vazia")["cells"]) == 4


def test_warning_when_cached_values_missing(sample_workbook: Path):
    from openpyxl import load_workbook

    from spreadsheet_mirror.colors import ThemePalette
    from spreadsheet_mirror.reader import WorkbookData

    wb = load_workbook(sample_workbook)
    data = WorkbookData(
        path=sample_workbook,
        wb_formulas=wb,
        theme=ThemePalette.from_workbook(wb),
        wb_values=None,
    )
    document, _, _ = serialize_workbook(data, MirrorConfig(read_cached_values=True))
    assert any("Sem valores em cache" in warning for warning in document["meta"]["warnings"])

    document, _, _ = serialize_workbook(data, MirrorConfig(read_cached_values=False))
    assert not any("Sem valores em cache" in warning for warning in document["meta"]["warnings"])


def test_config_serialized_as_lists(sample_workbook: Path):
    document, _, _ = _serialize(sample_workbook, MirrorConfig(header_rows=(2,)))
    assert document["meta"]["config"]["header_rows"] == [2]
