"""Testes de resolução de cores."""

from __future__ import annotations

import pytest
from openpyxl import load_workbook
from openpyxl.styles import Color, PatternFill
from openpyxl.styles.colors import Color as OxColor

from spreadsheet_mirror.colors import (
    ThemePalette,
    apply_tint,
    effective_fill_hex,
    fill_to_dict,
    normalize_hex,
    parse_theme_xml,
    resolve_color,
)


def test_normalize_hex_variants():
    assert normalize_hex("FFFFFF") == "#FFFFFF"
    assert normalize_hex("FFFFFFFF") == "#FFFFFF"
    assert normalize_hex("#4f81bd") == "#4F81BD"
    assert normalize_hex("zzzzzz") is None
    assert normalize_hex(None) is None
    assert normalize_hex("12345") is None


def test_apply_tint_lighten_and_darken():
    assert apply_tint("#000000", 1.0) == "#FFFFFF"
    assert apply_tint("#FFFFFF", -1.0) == "#000000"
    assert apply_tint("#4F81BD", 0.5) == "#A7C0DE"
    assert apply_tint("#4F81BD", -0.5) == "#28405E"
    assert apply_tint("#4F81BD", 0.0) == "#4F81BD"
    assert apply_tint(None, 0.5) is None


def test_parse_theme_xml_from_default_theme(tmp_path):
    wb = load_workbook(_save_default(tmp_path))
    palette = ThemePalette.from_workbook(wb)
    assert palette.source == "workbook"
    assert palette.colors["lt1"] == "#FFFFFF"
    assert palette.colors["dk1"] == "#000000"
    assert palette.colors["accent1"] == "#4F81BD"
    assert palette.color_for_index(4) == "#4F81BD"


def _save_default(tmp_path):
    from openpyxl import Workbook

    path = tmp_path / "theme.xlsx"
    Workbook().save(path)
    return path


def test_parse_theme_xml_handles_invalid():
    assert parse_theme_xml(None) == {}
    assert parse_theme_xml(b"not xml") == {}


def test_theme_fallback_when_missing():
    from openpyxl import Workbook

    palette = ThemePalette.from_workbook(Workbook())
    assert palette.source == "fallback"
    assert palette.colors["dk2"] == "#1F497D"


def test_resolve_rgb():
    color = OxColor(rgb="FF4F81BD")
    result = resolve_color(color)
    assert result["hex"] == "#4F81BD"
    assert result["type"] == "rgb"
    assert result["resolved"] is True


def test_resolve_rgb_with_tint():
    color = OxColor(rgb="FF4F81BD", tint=0.5)
    result = resolve_color(color)
    assert result["hex"] == "#A7C0DE"
    assert result["tint"] == 0.5


def test_resolve_indexed():
    color = OxColor(indexed=2)
    result = resolve_color(color)
    assert result["hex"] == "#FF0000"
    assert result["indexed"] == 2


def test_resolve_theme_uses_index_mapping():
    theme = ThemePalette()
    color = OxColor(theme=4)
    result = resolve_color(color, theme)
    assert result["hex"] == "#4F81BD"
    assert result["theme"] == 4
    assert result["theme_name"] == "accent1"


def test_resolve_theme_lt1_dk1_swap():
    theme = ThemePalette()
    light = resolve_color(OxColor(theme=0), theme)
    dark = resolve_color(OxColor(theme=1), theme)
    assert light["hex"] == "#FFFFFF"
    assert dark["hex"] == "#000000"


def test_resolve_auto():
    color = OxColor(auto=True)
    result = resolve_color(color)
    assert result["type"] == "auto"
    assert result["hex"] == "#000000"


def test_effective_fill_hex_none():
    assert effective_fill_hex(None) is None
    assert effective_fill_hex(PatternFill()) is None


def test_effective_fill_hex_solid():
    fill = PatternFill("solid", fgColor="FF4F81BD")
    assert effective_fill_hex(fill) == "#4F81BD"


def test_fill_to_dict_default_is_none():
    assert fill_to_dict(PatternFill()) is None


def test_fill_to_dict_solid():
    fill = PatternFill("solid", fgColor="FF4F81BD")
    data = fill_to_dict(fill)
    assert data["kind"] == "pattern"
    assert data["pattern_type"] == "solid"
    assert data["fg_color"]["hex"] == "#4F81BD"


def test_resolve_color_none():
    assert resolve_color(None) is None


def test_resolve_color_string():
    result = resolve_color("FF4F81BD")
    assert result["hex"] == "#4F81BD"
