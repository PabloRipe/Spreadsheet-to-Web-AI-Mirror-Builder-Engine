"""Testes da convenção de cores (fixo vs. editável)."""

from __future__ import annotations

from openpyxl import Workbook
from openpyxl.styles import Border, Font, PatternFill, Side

from spreadsheet_mirror.colors import ThemePalette
from spreadsheet_mirror.config import MirrorConfig
from spreadsheet_mirror.editability import MergedLookup, determine_editability


def _fresh_cell():
    wb = Workbook()
    ws = wb.active
    return ws, ws["A1"]


def _editable(cell, merged, config):
    return determine_editability(cell, merged, config, ThemePalette())


def test_formula_is_fixed():
    _, cell = _fresh_cell()
    cell.value = "=1+1"
    editable, reasons = _editable(cell, None, MirrorConfig())
    assert editable is False
    assert "formula" in reasons


def test_merged_lookup_anchor_and_non_anchor():
    ws, _ = _fresh_cell()
    ws.merge_cells("A1:B2")
    ws["A1"] = "Título"
    lookup = MergedLookup(ws.merged_cells.ranges)
    anchor = lookup.find(1, 1)
    non_anchor = lookup.find(2, 2)
    assert anchor is not None and anchor.is_anchor
    assert anchor.rowspan == 2 and anchor.colspan == 2
    assert non_anchor is not None and not non_anchor.is_anchor
    assert lookup.find(10, 10) is None


def test_merged_non_anchor_is_fixed():
    ws, _ = _fresh_cell()
    ws.merge_cells("A1:B2")
    ws["A1"] = "Título"
    lookup = MergedLookup(ws.merged_cells.ranges)
    editable, reasons = _editable(ws["B2"], lookup.find(2, 2), MirrorConfig())
    assert editable is False
    assert "merged_non_anchor" in reasons


def test_merged_anchor_fixed_by_default():
    ws, _ = _fresh_cell()
    ws.merge_cells("A1:B2")
    ws["A1"] = "Título"
    lookup = MergedLookup(ws.merged_cells.ranges)
    editable, reasons = _editable(ws["A1"], lookup.find(1, 1), MirrorConfig())
    assert editable is False
    assert "merged" in reasons


def test_merged_anchor_can_be_editable_when_configured():
    ws, _ = _fresh_cell()
    ws.merge_cells("A1:B2")
    ws["A1"] = "Título"
    lookup = MergedLookup(ws.merged_cells.ranges)
    cfg = MirrorConfig(fixed_if_merged=False)
    editable, reasons = _editable(ws["A1"], lookup.find(1, 1), cfg)
    assert editable is True
    assert "default_editable" in reasons


def test_header_row_is_fixed():
    ws, _ = _fresh_cell()
    ws["A2"] = "x"
    editable, reasons = _editable(ws["A2"], None, MirrorConfig(header_rows=(2,)))
    assert editable is False
    assert "header" in reasons


def test_header_column_is_fixed():
    ws, _ = _fresh_cell()
    ws["B1"] = "x"
    editable, reasons = _editable(ws["B1"], None, MirrorConfig(header_cols=(2,)))
    assert editable is False
    assert "header" in reasons


def test_fixed_fill_is_fixed():
    _, cell = _fresh_cell()
    cell.value = "x"
    cell.fill = PatternFill("solid", fgColor="FF123456")
    cfg = MirrorConfig(fixed_fill_colors=("#123456",))
    editable, reasons = _editable(cell, None, cfg)
    assert editable is False
    assert "fixed_fill" in reasons


def test_editable_fill_is_editable():
    _, cell = _fresh_cell()
    cell.value = "x"
    cell.fill = PatternFill("solid", fgColor="FFABCDEF")
    cfg = MirrorConfig(editable_fill_colors=("#ABCDEF",))
    editable, reasons = _editable(cell, None, cfg)
    assert editable is True
    assert "editable_fill" in reasons


def test_non_white_fill_is_fixed():
    _, cell = _fresh_cell()
    cell.value = "x"
    cell.fill = PatternFill("solid", fgColor="FFFF0000")
    editable, reasons = _editable(cell, None, MirrorConfig())
    assert editable is False
    assert "formatted_fill" in reasons


def test_white_fill_is_editable():
    _, cell = _fresh_cell()
    cell.value = "x"
    cell.fill = PatternFill("solid", fgColor="FFFFFFFF")
    editable, reasons = _editable(cell, None, MirrorConfig())
    assert editable is True
    assert "editable_fill" in reasons


def test_bold_is_fixed():
    _, cell = _fresh_cell()
    cell.value = "x"
    cell.font = Font(bold=True)
    editable, reasons = _editable(cell, None, MirrorConfig())
    assert editable is False
    assert "bold" in reasons


def test_bold_can_be_editable_when_disabled():
    _, cell = _fresh_cell()
    cell.value = "x"
    cell.font = Font(bold=True)
    editable, reasons = _editable(cell, None, MirrorConfig(fixed_if_bold=False))
    assert editable is True
    assert "default_editable" in reasons


def test_italic_is_fixed_when_enabled():
    _, cell = _fresh_cell()
    cell.value = "x"
    cell.font = Font(italic=True)
    editable, reasons = _editable(cell, None, MirrorConfig(fixed_if_italic=True))
    assert editable is False
    assert "italic" in reasons


def test_underline_is_fixed_when_enabled():
    _, cell = _fresh_cell()
    cell.value = "x"
    cell.font = Font(underline="single")
    editable, reasons = _editable(cell, None, MirrorConfig(fixed_if_underline=True))
    assert editable is False
    assert "underline" in reasons


def test_font_color_is_fixed_when_configured():
    _, cell = _fresh_cell()
    cell.value = "x"
    cell.font = Font(color="FF112233")
    editable, reasons = _editable(cell, None, MirrorConfig(fixed_font_colors=("#112233",)))
    assert editable is False
    assert "font_color" in reasons


def test_border_is_fixed_when_enabled():
    _, cell = _fresh_cell()
    cell.value = "x"
    cell.border = Border(bottom=Side(style="thin", color="FF000000"))
    editable, reasons = _editable(cell, None, MirrorConfig(fixed_if_border=True))
    assert editable is False
    assert "border" in reasons


def test_no_fill_can_be_fixed_when_configured():
    _, cell = _fresh_cell()
    cell.value = "x"
    cfg = MirrorConfig(treat_no_fill_as_editable=False)
    editable, reasons = _editable(cell, None, cfg)
    assert editable is False
    assert "no_fill" in reasons


def test_default_cell_is_editable():
    _, cell = _fresh_cell()
    cell.value = "x"
    editable, reasons = _editable(cell, None, MirrorConfig())
    assert editable is True
    assert "default_editable" in reasons
