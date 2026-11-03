"""Extração, canonicalização e deduplicação de estilos de célula."""

from __future__ import annotations

import json
from typing import Any

from .colors import ThemePalette, fill_to_dict, font_to_dict, resolve_color


def _border_side(side: Any, theme: ThemePalette) -> dict[str, Any] | None:
    if side is None:
        return None
    style = getattr(side, "style", None) or getattr(side, "border_style", None)
    color = resolve_color(getattr(side, "color", None), theme)
    if not style and not color:
        return None
    return {"style": style, "color": color}


def border_to_dict(border: Any, theme: ThemePalette | None = None) -> dict[str, Any] | None:
    if border is None:
        return None
    palette = theme or ThemePalette()
    result = {
        "left": _border_side(getattr(border, "left", None), palette),
        "right": _border_side(getattr(border, "right", None), palette),
        "top": _border_side(getattr(border, "top", None), palette),
        "bottom": _border_side(getattr(border, "bottom", None), palette),
        "diagonal": _border_side(getattr(border, "diagonal", None), palette),
        "diagonal_direction": getattr(border, "diagonal_direction", 0),
        "outline": bool(getattr(border, "outline", False)),
        "vertical": _border_side(getattr(border, "vertical", None), palette),
        "horizontal": _border_side(getattr(border, "horizontal", None), palette),
    }
    if not any(result[key] for key in ("left", "right", "top", "bottom", "diagonal", "vertical", "horizontal")):
        return None
    return result


def alignment_to_dict(alignment: Any) -> dict[str, Any] | None:
    if alignment is None:
        return None
    result = {
        "horizontal": getattr(alignment, "horizontal", None),
        "vertical": getattr(alignment, "vertical", None),
        "text_rotation": getattr(alignment, "text_rotation", None),
        "wrap_text": bool(getattr(alignment, "wrap_text", False)),
        "shrink_to_fit": bool(getattr(alignment, "shrink_to_fit", False)),
        "indent": getattr(alignment, "indent", 0),
        "relative_indent": getattr(alignment, "relativeIndent", 0),
        "justify_last_line": bool(getattr(alignment, "justifyLastLine", False)),
        "reading_order": getattr(alignment, "readingOrder", 0),
    }
    if not any(result[key] for key in ("horizontal", "vertical", "wrap_text", "shrink_to_fit", "indent", "text_rotation")):
        return None
    return result


def protection_to_dict(protection: Any) -> dict[str, Any] | None:
    if protection is None:
        return None
    locked = bool(getattr(protection, "locked", True))
    hidden = bool(getattr(protection, "hidden", False))
    if locked and not hidden:
        return None
    return {"locked": locked, "hidden": hidden}


def extract_style(cell: Any, theme: ThemePalette) -> dict[str, Any]:
    """Constrói um dicionário canônico de estilo para uma célula."""
    return {
        "font": font_to_dict(getattr(cell, "font", None), theme),
        "fill": fill_to_dict(getattr(cell, "fill", None), theme),
        "border": border_to_dict(getattr(cell, "border", None), theme),
        "alignment": alignment_to_dict(getattr(cell, "alignment", None)),
        "number_format": getattr(cell, "number_format", "General") or "General",
        "protection": protection_to_dict(getattr(cell, "protection", None)),
    }


def canonical_style_key(style: dict[str, Any]) -> str:
    """Chave estável para deduplicação de estilos."""
    return json.dumps(style, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class StyleRegistry:
    """Registra estilos únicos e devolve identificadores ``s0``, ``s1``..."""

    def __init__(self) -> None:
        self._styles: dict[str, dict[str, Any]] = {}
        self._by_key: dict[str, str] = {}

    def register(self, style: dict[str, Any]) -> str:
        key = canonical_style_key(style)
        style_id = self._by_key.get(key)
        if style_id is None:
            style_id = f"s{len(self._styles)}"
            self._by_key[key] = style_id
            self._styles[style_id] = style
        return style_id

    def to_dict(self) -> dict[str, dict[str, Any]]:
        return dict(self._styles)

    def __len__(self) -> int:
        return len(self._styles)
