"""Testes de extração e deduplicação de estilos."""

from __future__ import annotations

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection, Side

from spreadsheet_mirror.colors import ThemePalette
from spreadsheet_mirror.styles import (
    StyleRegistry,
    alignment_to_dict,
    border_to_dict,
    canonical_style_key,
    extract_style,
    protection_to_dict,
)


def _cell_with_style():
    wb = Workbook()
    ws = wb.active
    cell = ws["A1"]
    cell.value = "x"
    cell.font = Font(name="Arial", size=12, bold=True, italic=True, underline="single", color="FF112233")
    cell.fill = PatternFill("solid", fgColor="FF445566")
    cell.border = Border(
        left=Side(style="thin", color="FF000000"),
        right=Side(style="medium", color="FF111111"),
        top=Side(style="dashed", color="FF222222"),
        bottom=Side(style="double", color="FF333333"),
    )
    cell.alignment = Alignment(horizontal="center", vertical="top", wrap_text=True, indent=2)
    cell.number_format = "0.00"
    cell.protection = Protection(locked=False, hidden=True)
    return cell


def test_extract_style_roundtrip():
    cell = _cell_with_style()
    style = extract_style(cell, ThemePalette())
    assert style["font"]["name"] == "Arial"
    assert style["font"]["size"] == 12
    assert style["font"]["bold"] is True
    assert style["font"]["italic"] is True
    assert style["font"]["underline"] == "single"
    assert style["font"]["color"]["hex"] == "#112233"
    assert style["fill"]["pattern_type"] == "solid"
    assert style["fill"]["fg_color"]["hex"] == "#445566"
    assert style["border"]["left"]["style"] == "thin"
    assert style["border"]["bottom"]["style"] == "double"
    assert style["alignment"]["horizontal"] == "center"
    assert style["alignment"]["wrap_text"] is True
    assert style["number_format"] == "0.00"
    assert style["protection"] == {"locked": False, "hidden": True}


def test_border_to_dict_returns_none_for_default():
    assert border_to_dict(Border()) is None


def test_alignment_to_dict_returns_none_for_default():
    assert alignment_to_dict(Alignment()) is None


def test_protection_to_dict_returns_none_for_default():
    assert protection_to_dict(Protection()) is None


def test_style_registry_deduplicates():
    registry = StyleRegistry()
    style_a = {"font": {"bold": True}, "fill": None}
    style_b = {"fill": None, "font": {"bold": True}}
    style_c = {"font": {"bold": False}, "fill": None}
    id_a = registry.register(style_a)
    id_b = registry.register(style_b)
    id_c = registry.register(style_c)
    assert id_a == "s0"
    assert id_b == "s0"
    assert id_c == "s1"
    assert len(registry) == 2
    assert registry.to_dict()["s0"] == style_a


def test_canonical_style_key_is_stable():
    first = canonical_style_key({"b": 1, "a": 2})
    second = canonical_style_key({"a": 2, "b": 1})
    assert first == second


def test_extract_style_default_cell():
    wb = Workbook()
    ws = wb.active
    style = extract_style(ws["A1"], ThemePalette())
    assert style["fill"] is None
    assert style["border"] is None
    assert style["alignment"] is None
    assert style["protection"] is None
    assert style["number_format"] == "General"
    assert style["font"]["name"] == "Calibri"
