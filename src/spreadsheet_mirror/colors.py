"""Resolução de cores do openpyxl (rgb, indexed e theme) e aplicação de tint.

O atributo ``theme`` de uma célula usa a numeração de "cores do tema" do
OOXML, que não é a ordem em que os elementos aparecem no XML do tema:

    0 -> lt1   (fundo 1)
    1 -> dk1   (texto 1)
    2 -> lt2   (fundo 2)
    3 -> dk2   (texto 2)
    4 -> accent1 ... 9 -> accent6
    10 -> hlink
    11 -> folHlink
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from openpyxl.styles.colors import COLOR_INDEX

DRAWINGML_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

DEFAULT_THEME_COLORS: dict[str, str] = {
    "dk1": "#000000",
    "lt1": "#FFFFFF",
    "dk2": "#1F497D",
    "lt2": "#EEECE1",
    "accent1": "#4F81BD",
    "accent2": "#C0504D",
    "accent3": "#9BBB59",
    "accent4": "#8064A2",
    "accent5": "#4BACC6",
    "accent6": "#F79646",
    "hlink": "#0000FF",
    "folHlink": "#800080",
}

# Índice usado pelo atributo "theme" -> nome no clrScheme.
THEME_INDEX_TO_NAME: dict[int, str] = {
    0: "lt1",
    1: "dk1",
    2: "lt2",
    3: "dk2",
    4: "accent1",
    5: "accent2",
    6: "accent3",
    7: "accent4",
    8: "accent5",
    9: "accent6",
    10: "hlink",
    11: "folHlink",
}

SYS_COLOR_FALLBACK: dict[str, str] = {
    "window": "#FFFFFF",
    "windowText": "#000000",
    "menu": "#FFFFFF",
    "menuText": "#000000",
    "highlight": "#0078D7",
    "highlightText": "#FFFFFF",
    "btnFace": "#F0F0F0",
    "btnText": "#000000",
    "btnShadow": "#808080",
    "grayText": "#808080",
    "titleText": "#000000",
    "inactiveBorder": "#FFFFFF",
    "inactiveCaption": "#FFFFFF",
    "inactiveCaptionText": "#000000",
    "activeBorder": "#FFFFFF",
    "activeCaption": "#FFFFFF",
    "activeCaptionText": "#000000",
    "appWorkspace": "#FFFFFF",
    "background": "#FFFFFF",
    "3dDarkShadow": "#808080",
    "3dLight": "#FFFFFF",
    "scrollbar": "#C0C0C0",
}

PRESET_COLORS: dict[str, str] = {
    "black": "#000000",
    "white": "#FFFFFF",
    "red": "#FF0000",
    "green": "#008000",
    "blue": "#0000FF",
    "yellow": "#FFFF00",
    "cyan": "#00FFFF",
    "magenta": "#FF00FF",
    "gray": "#808080",
    "grey": "#808080",
    "darkGray": "#A9A9A9",
    "lightGray": "#D3D3D3",
    "orange": "#FFA500",
    "purple": "#800080",
    "brown": "#A52A2A",
    "pink": "#FFC0CB",
}

_HEX_RE = re.compile(r"^[0-9A-F]{6}$")


def normalize_hex(value: Any) -> str | None:
    """Normaliza ``RRGGBB`` ou ``AARRGGBB`` (com/sem ``#``) para ``#RRGGBB``."""
    if value is None:
        return None
    text = str(value).strip().lstrip("#").upper()
    if len(text) == 8:
        text = text[2:]
    if len(text) != 6 or not _HEX_RE.fullmatch(text):
        return None
    return f"#{text}"


def _clamp(value: float) -> int:
    return max(0, min(255, int(round(value))))


def apply_tint(hex_color: str | None, tint: float | None) -> str | None:
    """Aplica o ``tint`` OOXML misturando em RGB.

    Valores positivos clareiam em direção ao branco; negativos escurecem em
    direção ao preto. A implementação segue a fórmula linear documentada pela
    Microsoft para o atributo ``tint`` de cores de célula.
    """
    base = normalize_hex(hex_color)
    if base is None:
        return None
    tint_value = float(tint or 0.0)
    if not tint_value:
        return base
    tint_value = max(-1.0, min(1.0, tint_value))
    channels = [int(base[i:i + 2], 16) for i in (1, 3, 5)]
    if tint_value > 0:
        adjusted = [c + (255 - c) * tint_value for c in channels]
    else:
        adjusted = [c * (1.0 + tint_value) for c in channels]
    return "#{:02X}{:02X}{:02X}".format(*(_clamp(c) for c in adjusted))


def _indexed_hex(index: int | None) -> str | None:
    if index is None:
        return None
    if 0 <= index < len(COLOR_INDEX):
        return normalize_hex(COLOR_INDEX[index])
    # 64 e 65 são reservados para as cores de sistema.
    if index == 64:
        return "#000000"
    if index == 65:
        return "#FFFFFF"
    return None


def _parse_scheme_color(element: ET.Element) -> str | None:
    tag = element.tag.split("}")[-1]
    if tag == "srgbClr":
        return normalize_hex(element.get("val"))
    if tag == "sysClr":
        last = element.get("lastClr")
        if last:
            return normalize_hex(last)
        return SYS_COLOR_FALLBACK.get(element.get("val", ""), "#000000")
    if tag == "scrgbClr":
        try:
            r = float(element.get("r", "0")) / 100.0 * 255.0
            g = float(element.get("g", "0")) / 100.0 * 255.0
            b = float(element.get("b", "0")) / 100.0 * 255.0
        except ValueError:
            return None
        return "#{:02X}{:02X}{:02X}".format(_clamp(r), _clamp(g), _clamp(b))
    if tag == "prstClr":
        return PRESET_COLORS.get(element.get("val", ""))
    return None


def parse_theme_xml(raw: bytes | str | None) -> dict[str, str]:
    """Extrai as cores do ``clrScheme`` do XML de tema do workbook."""
    if not raw:
        return {}
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return {}
    scheme = root.find(f".//{DRAWINGML_NS}clrScheme")
    if scheme is None:
        return {}
    colors: dict[str, str] = {}
    for child in scheme:
        name = child.tag.split("}")[-1]
        color_element = next(iter(child), None)
        if color_element is None:
            continue
        value = _parse_scheme_color(color_element)
        if value:
            colors[name] = value
    return colors


def _parse_font_scheme(raw: bytes | str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return {}
    scheme = root.find(f".//{DRAWINGML_NS}fontScheme")
    if scheme is None:
        return {}
    fonts: dict[str, str] = {}
    for major in scheme.findall(f".//{DRAWINGML_NS}majorFont"):
        latin = major.find(f"{DRAWINGML_NS}latin")
        if latin is not None:
            fonts["major"] = latin.get("typeface", "")
            break
    for minor in scheme.findall(f".//{DRAWINGML_NS}minorFont"):
        latin = minor.find(f"{DRAWINGML_NS}latin")
        if latin is not None:
            fonts["minor"] = latin.get("typeface", "")
            break
    return fonts


@dataclass
class ThemePalette:
    """Paleta de cores do tema, com fallback para o tema padrão do Office."""

    colors: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_THEME_COLORS))
    source: str = "fallback"
    font_scheme: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_workbook(cls, workbook: Any) -> "ThemePalette":
        raw = getattr(workbook, "loaded_theme", None)
        parsed = parse_theme_xml(raw)
        if not parsed:
            return cls()
        merged = dict(DEFAULT_THEME_COLORS)
        merged.update(parsed)
        return cls(
            colors=merged,
            source="workbook",
            font_scheme=_parse_font_scheme(raw),
        )

    def color_for_index(self, index: int | None) -> str | None:
        name = THEME_INDEX_TO_NAME.get(index) if index is not None else None
        if name is None:
            return None
        return self.colors.get(name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "colors": dict(self.colors),
            "font_scheme": dict(self.font_scheme),
            "index_map": {str(k): v for k, v in THEME_INDEX_TO_NAME.items()},
        }


def _empty_color() -> dict[str, Any]:
    return {
        "hex": None,
        "type": None,
        "tint": 0.0,
        "theme": None,
        "theme_name": None,
        "indexed": None,
        "auto": None,
        "rgb": None,
        "resolved": False,
    }


def resolve_color(
    color: Any,
    theme: ThemePalette | None = None,
    default_auto: str | None = "#000000",
) -> dict[str, Any] | None:
    """Resolve um ``openpyxl.styles.Color`` para um dicionário com ``hex``."""
    if color is None:
        return None
    if isinstance(color, str):
        base = normalize_hex(color)
        if base is None:
            return None
        result = _empty_color()
        result.update({"hex": base, "type": "rgb", "rgb": color, "resolved": True})
        return result

    palette = theme or ThemePalette()
    color_type = getattr(color, "type", None)
    tint = float(getattr(color, "tint", 0.0) or 0.0)
    result = _empty_color()
    result["type"] = color_type
    result["tint"] = tint

    if color_type == "theme":
        index = getattr(color, "theme", None)
        result["theme"] = index
        name = THEME_INDEX_TO_NAME.get(index)
        result["theme_name"] = name
        base = palette.color_for_index(index)
        if base:
            result["hex"] = apply_tint(base, tint)
            result["resolved"] = True
        return result

    if color_type == "indexed":
        index = getattr(color, "indexed", None)
        result["indexed"] = index
        base = _indexed_hex(index)
        if base:
            result["hex"] = apply_tint(base, tint)
            result["resolved"] = True
        return result

    if color_type == "auto":
        auto = getattr(color, "auto", True)
        result["auto"] = bool(auto)
        if default_auto:
            result["hex"] = default_auto
            result["resolved"] = True
        return result

    base = normalize_hex(getattr(color, "rgb", None))
    if base:
        result["rgb"] = getattr(color, "rgb", None)
        result["type"] = "rgb"
        result["hex"] = apply_tint(base, tint)
        result["resolved"] = True
    return result


def _side_to_dict(side: Any, theme: ThemePalette) -> dict[str, Any] | None:
    if side is None:
        return None
    style = getattr(side, "style", None) or getattr(side, "border_style", None)
    color = resolve_color(getattr(side, "color", None), theme)
    if not style and not color:
        return None
    return {"style": style, "color": color}


def _gradient_to_dict(fill: Any, theme: ThemePalette) -> dict[str, Any]:
    stops = []
    for stop in getattr(fill, "stop", ()) or ():
        stops.append(
            {
                "position": float(getattr(stop, "position", 0.0) or 0.0),
                "color": resolve_color(getattr(stop, "color", None), theme),
            }
        )
    return {
        "kind": "gradient",
        "gradient_type": getattr(fill, "type", None),
        "degree": getattr(fill, "degree", None),
        "left": getattr(fill, "left", None),
        "right": getattr(fill, "right", None),
        "top": getattr(fill, "top", None),
        "bottom": getattr(fill, "bottom", None),
        "stop": stops,
    }


def fill_to_dict(fill: Any, theme: ThemePalette | None = None) -> dict[str, Any] | None:
    """Representa ``PatternFill``/``GradientFill`` de forma serializável."""
    if fill is None:
        return None
    palette = theme or ThemePalette()
    fill_type = getattr(fill, "fill_type", None)
    pattern_type = getattr(fill, "patternType", None)
    if fill_type == "gradient" or pattern_type == "gradient" or hasattr(fill, "stop"):
        return _gradient_to_dict(fill, palette)
    if fill_type in (None, "none") and pattern_type in (None, "none"):
        return None
    fg = resolve_color(getattr(fill, "fgColor", None), palette)
    bg = resolve_color(getattr(fill, "bgColor", None), palette)
    return {
        "kind": "pattern",
        "pattern_type": pattern_type or fill_type,
        "fg_color": fg,
        "bg_color": bg,
    }


def effective_fill_hex(fill: Any, theme: ThemePalette | None = None) -> str | None:
    """Retorna o hex visível do preenchimento (ou ``None`` se não houver)."""
    if fill is None:
        return None
    palette = theme or ThemePalette()
    fill_type = getattr(fill, "fill_type", None)
    pattern_type = getattr(fill, "patternType", None)
    if fill_type in (None, "none") and pattern_type in (None, "none"):
        return None
    if hasattr(fill, "stop") and fill_type != "pattern":
        for stop in getattr(fill, "stop", ()) or ():
            resolved = resolve_color(getattr(stop, "color", None), palette)
            if resolved and resolved.get("hex"):
                return resolved["hex"]
        return None
    fg = resolve_color(getattr(fill, "fgColor", None), palette)
    bg = resolve_color(getattr(fill, "bgColor", None), palette)
    if fill_type == "solid":
        for candidate in (fg, bg):
            if candidate and candidate.get("hex"):
                return candidate["hex"]
        return None
    for candidate in (fg, bg):
        if candidate and candidate.get("hex"):
            return candidate["hex"]
    return None


def font_to_dict(font: Any, theme: ThemePalette | None = None) -> dict[str, Any] | None:
    if font is None:
        return None
    palette = theme or ThemePalette()
    return {
        "name": getattr(font, "name", None),
        "size": getattr(font, "size", None) or getattr(font, "sz", None),
        "bold": bool(getattr(font, "bold", False) or getattr(font, "b", False)),
        "italic": bool(getattr(font, "italic", False) or getattr(font, "i", False)),
        "underline": getattr(font, "underline", None),
        "strike": bool(getattr(font, "strike", False)),
        "color": resolve_color(getattr(font, "color", None), palette),
        "family": getattr(font, "family", None),
        "scheme": getattr(font, "scheme", None),
        "vert_align": getattr(font, "vertAlign", None),
        "outline": bool(getattr(font, "outline", False)),
        "shadow": bool(getattr(font, "shadow", False)),
        "condense": bool(getattr(font, "condense", False)),
        "extend": bool(getattr(font, "extend", False)),
        "charset": getattr(font, "charset", None),
    }
