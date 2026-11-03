"""Constrói contexto compacto do ``mirror.json`` para o chat de IA."""

from __future__ import annotations

import re
from typing import Any, Mapping

from openpyxl.utils import get_column_letter, range_boundaries

_CELL_RE = re.compile(r"^\$?([A-Za-z]+)\$?(\d+)$")
_MAX_MERGED = 50
_MAX_LISTED_CELLS = 400


def parse_ref(ref: str) -> tuple[int, int] | None:
    match = _CELL_RE.fullmatch(str(ref or "").strip())
    if not match:
        return None
    letters, digits = match.groups()
    col = 0
    for char in letters.upper():
        col = col * 26 + (ord(char) - 64)
    return int(digits), col


def expand_range(selection: str | None) -> tuple[int, int, int, int] | None:
    """Aceita ``A1:C10`` ou uma única célula e devolve limites 1-based."""
    text = str(selection or "").strip().replace("$", "")
    if not text:
        return None
    if ":" in text:
        try:
            return range_boundaries(text)
        except (TypeError, ValueError):
            return None
    parsed = parse_ref(text)
    if not parsed:
        return None
    row, col = parsed
    return col, row, col, row


def _style_summary(style: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(style, Mapping):
        return {}
    font = style.get("font") if isinstance(style.get("font"), Mapping) else {}
    fill = style.get("fill") if isinstance(style.get("fill"), Mapping) else {}
    alignment = style.get("alignment") if isinstance(style.get("alignment"), Mapping) else {}
    summary: dict[str, Any] = {}
    for key in ("name", "size", "bold", "italic"):
        if font.get(key) not in (None, False, ""):
            summary[key] = font.get(key)
    color = font.get("color") if isinstance(font.get("color"), Mapping) else {}
    if color.get("hex"):
        summary["font_color"] = color["hex"]
    if fill.get("pattern_type") == "solid":
        fg = fill.get("fg_color") if isinstance(fill.get("fg_color"), Mapping) else {}
        if fg.get("hex"):
            summary["fill"] = fg["hex"]
    if style.get("number_format") and style["number_format"] != "General":
        summary["number_format"] = style["number_format"]
    if alignment.get("horizontal") or alignment.get("wrap_text"):
        summary["alignment"] = {
            key: alignment.get(key)
            for key in ("horizontal", "vertical", "wrap_text")
            if alignment.get(key) not in (None, False)
        }
    return summary


def _merged_covered(sheet: Mapping[str, Any]) -> set[str]:
    covered: set[str] = set()
    for merged in sheet.get("merged_ranges", []) or []:
        try:
            min_col, min_row, max_col, max_row = range_boundaries(str(merged))
        except (TypeError, ValueError):
            continue
        for row in range(min_row, max_row + 1):
            for col in range(min_col, max_col + 1):
                if row == min_row and col == min_col:
                    continue
                covered.add(f"{get_column_letter(col)}{row}")
    return covered


def _sheet_lookup(document: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    sheets: dict[str, Mapping[str, Any]] = {}
    for sheet in document.get("sheets", []) or []:
        if isinstance(sheet, Mapping) and isinstance(sheet.get("name"), str):
            sheets[sheet["name"]] = sheet
    return sheets


def _config(document: Mapping[str, Any]) -> Mapping[str, Any]:
    meta = document.get("meta") if isinstance(document.get("meta"), Mapping) else {}
    config = meta.get("config") if isinstance(meta.get("config"), Mapping) else {}
    return config


def _gap_editable(
    document: Mapping[str, Any], sheet: Mapping[str, Any], row: int, col: int
) -> bool:
    config = _config(document)
    if row in set(config.get("header_rows", []) or []):
        return False
    if col in set(config.get("header_cols", []) or []):
        return False
    if config.get("treat_no_fill_as_editable", True) is False:
        return False
    max_row = int(sheet.get("max_row") or 0)
    max_col = int(sheet.get("max_col") or 0)
    if max_row and row > max_row:
        return False
    if max_col and col > max_col:
        return False
    return True


def _header_rows(sheet: Mapping[str, Any], document: Mapping[str, Any]) -> list[int]:
    config = _config(document)
    explicit = [int(item) for item in (config.get("header_rows") or []) if str(item).isdigit()]
    if explicit:
        return sorted(explicit)
    detected: list[int] = []
    for cell in sheet.get("cells", []) or []:
        if not isinstance(cell, Mapping) or cell.get("editavel") is True:
            continue
        if cell.get("value_type") != "string" or not cell.get("value"):
            continue
        try:
            row = int(cell.get("row") or 0)
        except (TypeError, ValueError):
            continue
        if row and row not in detected:
            detected.append(row)
    return sorted(detected)[:3]


def _cell_payload(
    document: Mapping[str, Any],
    cell: Mapping[str, Any],
    draft: Mapping[str, Any],
) -> dict[str, Any]:
    ref = str(cell.get("ref") or "")
    styles = document.get("styles") if isinstance(document.get("styles"), Mapping) else {}
    style = styles.get(cell.get("style")) if isinstance(cell.get("style"), str) else None
    payload: dict[str, Any] = {
        "ref": ref,
        "valor": cell.get("value"),
        "tipo": cell.get("value_type"),
        "editavel": bool(cell.get("editavel")),
    }
    if cell.get("formula"):
        payload["formula"] = cell["formula"]
    if cell.get("merged"):
        payload["mesclado"] = cell["merged"]
    if ref.upper() in draft:
        payload["valor_rascunho"] = draft[ref.upper()]
    summary = _style_summary(style if isinstance(style, Mapping) else None)
    if summary:
        payload["estilo"] = summary
    return payload


def _sheet_summary(document: Mapping[str, Any], sheet: Mapping[str, Any]) -> dict[str, Any]:
    cells = [cell for cell in sheet.get("cells", []) or [] if isinstance(cell, Mapping)]
    fixed = sum(1 for cell in cells if cell.get("editavel") is not True)
    editable = len(cells) - fixed
    merged = [str(item) for item in (sheet.get("merged_ranges") or [])]
    return {
        "nome": sheet.get("name"),
        "estado": sheet.get("state"),
        "linhas": sheet.get("max_row"),
        "colunas": sheet.get("max_col"),
        "mesclagens": merged[:_MAX_MERGED],
        "cabecalhos_detectados": _header_rows(sheet, document),
        "contagem": {"fixas": fixed, "editaveis": editable},
    }


class ContextBuilder:
    """Monta o contexto enviado ao LLM sem expor o workbook inteiro."""

    def __init__(
        self,
        document: Mapping[str, Any],
        *,
        draft: Mapping[str, Mapping[str, Any]] | None = None,
        max_context_cells: int = 400,
        project_slug: str = "",
    ) -> None:
        self.document = document if isinstance(document, Mapping) else {}
        self.draft = draft if isinstance(draft, Mapping) else {}
        self.max_context_cells = max(1, int(max_context_cells or 400))
        self.project_slug = project_slug

    def build(
        self,
        mode: str = "sheet",
        *,
        sheet: str | None = None,
        selection: str | None = None,
    ) -> dict[str, Any]:
        mode = mode if mode in {"selection", "sheet", "project"} else "sheet"
        sheets = _sheet_lookup(self.document)
        active_name = sheet if sheet in sheets else next(iter(sheets), "")
        meta = self.document.get("meta") if isinstance(self.document.get("meta"), Mapping) else {}
        context: dict[str, Any] = {
            "projeto": {
                "slug": self.project_slug,
                "arquivo": meta.get("source"),
                "abas": len(sheets),
            },
            "modo": mode,
            "aba_ativa": active_name,
            "abas": [],
            "avisos": [],
        }

        chosen = [sheets[active_name]] if active_name and mode in {"selection", "sheet"} else []
        if mode == "project":
            chosen = list(sheets.values())

        if mode == "project":
            context["abas"] = [_sheet_summary(self.document, item) for item in chosen]
            context["avisos"].append(
                "Modo projeto: apenas resumos por aba; use o modo seleção para detalhes de células."
            )
            return context

        remaining = self.max_context_cells
        styles_used: dict[str, Any] = {}
        for item in chosen:
            summary = _sheet_summary(self.document, item)
            cells_payload: list[dict[str, Any]] = []
            draft = self.draft.get(str(item.get("name")), {}) if isinstance(self.draft, Mapping) else {}
            if not isinstance(draft, Mapping):
                draft = {}
            cell_map = {
                str(cell.get("ref")).upper(): cell
                for cell in item.get("cells", []) or []
                if isinstance(cell, Mapping) and cell.get("ref")
            }
            covered = _merged_covered(item)

            refs: list[str] = []
            if mode == "selection" and selection:
                bounds = expand_range(selection)
                if bounds:
                    min_col, min_row, max_col, max_row = bounds
                    max_row = min(max_row, int(item.get("max_row") or max_row))
                    max_col = min(max_col, int(item.get("max_col") or max_col))
                    for row in range(min_row, max_row + 1):
                        for col in range(min_col, max_col + 1):
                            refs.append(f"{get_column_letter(col)}{row}")
                else:
                    context["avisos"].append(f"Seleção inválida ignorada: {selection!r}.")
            if not refs:
                refs = sorted(
                    cell_map,
                    key=lambda ref: (
                        (parse_ref(ref) or (0, 0))[0],
                        (parse_ref(ref) or (0, 0))[1],
                    ),
                )

            for ref in refs:
                if remaining <= 0:
                    break
                if ref in covered:
                    continue
                cell = cell_map.get(ref)
                if cell is None:
                    parsed = parse_ref(ref)
                    if not parsed:
                        continue
                    row, col = parsed
                    if not _gap_editable(self.document, item, row, col):
                        continue
                    cell = {
                        "ref": ref,
                        "value": None,
                        "value_type": "null",
                        "editavel": True,
                    }
                cells_payload.append(_cell_payload(self.document, cell, draft))
                styles_used[str(cell.get("style") or "")] = True
                remaining -= 1

            if remaining <= 0 and len(cells_payload) >= self.max_context_cells:
                summary["celulas"] = cells_payload
                context["abas"].append(summary)
                context["avisos"].append(
                    f"Contexto truncado em {self.max_context_cells} células."
                )
                break

            summary["celulas"] = cells_payload
            context["abas"].append(summary)

        styles = self.document.get("styles") if isinstance(self.document.get("styles"), Mapping) else {}
        used_ids = [key for key in styles_used if key and key in styles]
        context["estilos_usados"] = {
            key: _style_summary(styles.get(key) if isinstance(styles.get(key), Mapping) else None)
            for key in sorted(used_ids, key=lambda value: int(value[1:]) if value[1:].isdigit() else 0)
        }
        return context


def build_context(
    document: Mapping[str, Any],
    mode: str = "sheet",
    *,
    sheet: str | None = None,
    selection: str | None = None,
    draft: Mapping[str, Mapping[str, Any]] | None = None,
    max_context_cells: int = 400,
    project_slug: str = "",
) -> dict[str, Any]:
    return ContextBuilder(
        document,
        draft=draft,
        max_context_cells=max_context_cells,
        project_slug=project_slug,
    ).build(mode, sheet=sheet, selection=selection)
