"""Testes do template limpo e da injeção de dados."""

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from spreadsheet_mirror.reader import load_workbook_data
from spreadsheet_mirror.serializer import serialize_workbook
from spreadsheet_mirror.template import create_template, fill_template


def _make_template(sample_workbook: Path, tmp_path: Path, clear_values: bool = True):
    data = load_workbook_data(sample_workbook)
    _, editable_by_sheet, _ = serialize_workbook(data)
    template_path = tmp_path / "template.xlsx"
    create_template(data.wb_formulas, editable_by_sheet, template_path, clear_values=clear_values)
    return template_path, editable_by_sheet


def test_create_template_clears_editable_and_preserves_fixed(sample_workbook: Path, tmp_path: Path):
    template_path, editable_by_sheet = _make_template(sample_workbook, tmp_path)
    assert "B3" in editable_by_sheet["Vendas"]
    assert "C3" in editable_by_sheet["Vendas"]

    wb = load_workbook(template_path)
    ws = wb["Vendas"]
    assert ws["B3"].value is None
    assert ws["C3"].value is None
    assert ws["A2"].value == "Produto"
    assert ws["A7"].value == "Total Geral"
    assert ws["D3"].value == "=B3*C3"
    assert ws["D7"].value == "=SUM(D3:D5)"
    assert ws["A2"].font.bold is True
    assert ws["A2"].fill.fill_type == "solid"
    assert "A1:D1" in [str(item) for item in ws.merged_cells.ranges]
    assert ws.column_dimensions["A"].width == 20
    assert ws.freeze_panes == "A3"

    entradas = wb["Entradas"]
    assert entradas["A2"].value is None
    assert entradas["B2"].value is None
    assert entradas["A1"].value == "Nome"
    assert entradas.sheet_properties.tabColor.rgb == "FF9BBB59"


def test_create_template_without_clearing(sample_workbook: Path, tmp_path: Path):
    template_path, _ = _make_template(sample_workbook, tmp_path, clear_values=False)
    wb = load_workbook(template_path)
    assert wb["Vendas"]["B3"].value == 1
    assert wb["Vendas"]["C3"].value == 10.5


def test_fill_template_injects_values_and_keeps_formulas(sample_workbook: Path, tmp_path: Path):
    template_path, _ = _make_template(sample_workbook, tmp_path)
    final_path = tmp_path / "final.xlsx"
    fill_template(
        template_path,
        {
            "Vendas": {"B3": 7, "C3": 2.5},
            "Entradas": {"A2": "Maria", "B2": 250.0},
        },
        final_path,
    )
    wb = load_workbook(final_path)
    assert wb["Vendas"]["B3"].value == 7
    assert wb["Vendas"]["C3"].value == 2.5
    assert wb["Vendas"]["D3"].value == "=B3*C3"
    assert wb["Vendas"]["A2"].value == "Produto"
    assert wb["Entradas"]["A2"].value == "Maria"
    assert wb["Entradas"]["B2"].value == 250.0
    assert wb["Entradas"]["A1"].value == "Nome"


def test_fill_template_ignores_unknown_sheet(sample_workbook: Path, tmp_path: Path):
    template_path, _ = _make_template(sample_workbook, tmp_path)
    final_path = tmp_path / "final.xlsx"
    fill_template(template_path, {"Inexistente": {"A1": "x"}}, final_path)
    assert final_path.exists()
