"""Fixtures compartilhadas dos testes."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side


def _build_sales_workbook() -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "Vendas"

    ws["A1"] = "Relatório de Vendas"
    ws.merge_cells("A1:D1")
    ws["A1"].font = Font(bold=True, size=14, color="FFFFFFFF")
    ws["A1"].fill = PatternFill("solid", fgColor="FF1F497D")
    ws["A1"].alignment = Alignment(horizontal="center")

    for index, header in enumerate(("Produto", "Quantidade", "Preço", "Total"), start=1):
        cell = ws.cell(row=2, column=index, value=header)
        cell.font = Font(bold=True, color="FFFFFFFF")
        cell.fill = PatternFill("solid", fgColor="FF4F81BD")

    for row in range(3, 6):
        ws.cell(row=row, column=1, value=f"Produto {row - 2}")
        ws.cell(row=row, column=2, value=row - 2)
        ws.cell(row=row, column=3, value=10.5)
        ws.cell(row=row, column=4, value=f"=B{row}*C{row}")

    ws["A7"] = "Total Geral"
    ws["A7"].font = Font(bold=True)
    ws["D7"] = "=SUM(D3:D5)"
    ws["D7"].font = Font(bold=True)
    ws["D7"].fill = PatternFill("solid", fgColor="FFFFF2CC")
    ws["D7"].border = Border(bottom=Side(style="double", color="FF000000"))

    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].hidden = True
    ws.row_dimensions[4].height = 30
    ws.freeze_panes = "A3"

    entries = wb.create_sheet("Entradas")
    entries["A1"] = "Nome"
    entries["B1"] = "Valor"
    entries["A1"].font = Font(bold=True)
    entries["B1"].font = Font(bold=True)
    entries["A2"] = "Exemplo"
    entries["B2"] = 100.0
    entries.sheet_properties.tabColor = "FF9BBB59"
    return wb


@pytest.fixture
def sample_workbook(tmp_path: Path) -> Path:
    path = tmp_path / "relatorio.xlsx"
    _build_sales_workbook().save(path)
    return path


def _inject_cached_value(path: Path, sheet_xml: str, cell_ref: str, value: str) -> None:
    with zipfile.ZipFile(path, "r") as archive:
        items = {name: archive.read(name) for name in archive.namelist()}
    xml = items[sheet_xml].decode("utf-8")
    pattern = re.compile(
        rf'(<c r="{re.escape(cell_ref)}"[^>]*>)(.*?)(</c>)',
        re.DOTALL,
    )

    def _replace(match: re.Match[str]) -> str:
        inner = re.sub(r"<v>.*?</v>", "", match.group(2), flags=re.DOTALL)
        inner = re.sub(r"<v\s*/>", "", inner)
        return f"{match.group(1)}{inner}<v>{value}</v>{match.group(3)}"

    updated, count = pattern.subn(_replace, xml, count=1)
    if not count:
        raise AssertionError(f"Não foi possível injetar valor em {cell_ref}")
    items[sheet_xml] = updated.encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in items.items():
            archive.writestr(name, payload)


@pytest.fixture
def cached_workbook(tmp_path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Calculos"
    ws["A1"] = 2
    ws["A2"] = 3
    ws["A3"] = "=SUM(A1:A2)"
    ws["B1"] = "=A1*2"
    path = tmp_path / "cache.xlsx"
    wb.save(path)
    _inject_cached_value(path, "xl/worksheets/sheet1.xml", "A3", "5")
    _inject_cached_value(path, "xl/worksheets/sheet1.xml", "B1", "4")
    return path
