"""Regras da convenção de cores: célula fixa vs. editável."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openpyxl.utils import range_boundaries

from .colors import (
    ThemePalette,
    effective_fill_hex,
    normalize_hex,
    resolve_color,
)
from .config import MirrorConfig


@dataclass
class MergedInfo:
    range: str
    anchor: str
    rowspan: int
    colspan: int
    is_anchor: bool


class MergedLookup:
    """Localiza o intervalo mesclado que contém uma coordenada."""

    def __init__(self, ranges: Any = ()) -> None:
        self.ranges: list[tuple[str, int, int, int, int, str]] = []
        for merged in ranges:
            text = str(merged)
            try:
                min_col, min_row, max_col, max_row = range_boundaries(text)
            except ValueError:
                continue
            anchor = text.split(":")[0].replace("$", "")
            self.ranges.append((text, min_col, min_row, max_col, max_row, anchor))

    def find(self, row: int, column: int) -> MergedInfo | None:
        for text, min_col, min_row, max_col, max_row, anchor in self.ranges:
            if min_row <= row <= max_row and min_col <= column <= max_col:
                return MergedInfo(
                    range=text,
                    anchor=anchor,
                    rowspan=max_row - min_row + 1,
                    colspan=max_col - min_col + 1,
                    is_anchor=(row == min_row and column == min_col),
                )
        return None


def _normalized_set(values: tuple[str, ...] | list[str]) -> set[str]:
    return {value for value in (normalize_hex(item) for item in values) if value}


def _font_has_underline(font: Any) -> bool:
    underline = getattr(font, "underline", None)
    return bool(underline) and underline != "none"


def _border_is_visible(border: Any) -> bool:
    if border is None:
        return False
    for side_name in ("left", "right", "top", "bottom", "diagonal", "vertical", "horizontal"):
        side = getattr(border, side_name, None)
        if side is not None and getattr(side, "style", None):
            return True
    return False


def determine_editability(
    cell: Any,
    merged: MergedInfo | None,
    config: MirrorConfig,
    theme: ThemePalette,
) -> tuple[bool, list[str]]:
    """Retorna ``(editavel, motivos)`` para uma célula."""
    reasons: list[str] = []
    value = getattr(cell, "value", None)
    data_type = getattr(cell, "data_type", None)

    if data_type == "f" or (isinstance(value, str) and value.startswith("=")):
        reasons.append("formula")
        return False, reasons

    if merged is not None:
        if not merged.is_anchor:
            reasons.append("merged_non_anchor")
            return False, reasons
        if config.fixed_if_merged:
            reasons.append("merged")
            return False, reasons

    row = getattr(cell, "row", None)
    column = getattr(cell, "column", None)
    if row in config.header_rows or column in config.header_cols:
        reasons.append("header")
        return False, reasons

    fill_hex = normalize_hex(effective_fill_hex(getattr(cell, "fill", None), theme))
    fixed_fills = _normalized_set(config.fixed_fill_colors)
    editable_fills = _normalized_set(config.editable_fill_colors)

    if fill_hex and fill_hex in fixed_fills:
        reasons.append("fixed_fill")
        return False, reasons

    if fill_hex and fill_hex in editable_fills:
        reasons.append("editable_fill")
        return True, reasons

    if fill_hex and fill_hex != "#FFFFFF":
        reasons.append("formatted_fill")
        return False, reasons

    font = getattr(cell, "font", None)
    if font is not None:
        if config.fixed_if_bold and bool(getattr(font, "bold", False)):
            reasons.append("bold")
            return False, reasons
        if config.fixed_if_italic and bool(getattr(font, "italic", False)):
            reasons.append("italic")
            return False, reasons
        if config.fixed_if_underline and _font_has_underline(font):
            reasons.append("underline")
            return False, reasons
        if config.fixed_font_colors:
            font_color = resolve_color(getattr(font, "color", None), theme)
            font_hex = normalize_hex(font_color.get("hex")) if font_color else None
            if font_hex and font_hex in _normalized_set(config.fixed_font_colors):
                reasons.append("font_color")
                return False, reasons

    if config.fixed_if_border and _border_is_visible(getattr(cell, "border", None)):
        reasons.append("border")
        return False, reasons

    if not fill_hex and not config.treat_no_fill_as_editable:
        reasons.append("no_fill")
        return False, reasons

    reasons.append("default_editable")
    return True, reasons
