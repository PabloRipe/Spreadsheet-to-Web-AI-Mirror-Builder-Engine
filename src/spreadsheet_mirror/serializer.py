"""Construção do ``mirror.json`` a partir de um workbook openpyxl."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal
from typing import Any

from openpyxl.utils import column_index_from_string, get_column_letter

from .colors import ThemePalette, resolve_color
from .config import MirrorConfig
from .editability import MergedLookup, determine_editability
from .reader import WorkbookData
from .styles import StyleRegistry, extract_style

SCHEMA_VERSION = "1.0.0"


def _json_value(value: Any, data_type: str | None = None) -> tuple[Any, str]:
    """Converte um valor de célula em algo seguro para JSON."""
    if value is None:
        return None, "null"
    if isinstance(value, bool):
        return value, "boolean"
    if isinstance(value, Decimal):
        return float(value), "number"
    if isinstance(value, (int, float)):
        return value, "number"
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat(), "datetime"
    if isinstance(value, _dt.timedelta):
        return value.total_seconds(), "duration"
    if isinstance(value, str):
        return value, "error" if data_type == "e" else "string"
    return str(value), "string"


def _formula_text(value: Any) -> str:
    text = value if isinstance(value, str) else getattr(value, "text", None)
    if not isinstance(text, str):
        text = str(value)
    return text if text.startswith("=") else f"={text}"


def _cached_cell(ws_values: Any, coordinate: str) -> Any:
    if ws_values is None:
        return None
    try:
        return ws_values[coordinate]
    except Exception:  # noqa: BLE001 - coordenadas fora do intervalo, etc.
        return None


def _column_metadata(ws: Any) -> list[dict[str, Any]]:
    columns: list[dict[str, Any]] = []
    for key, dimension in ws.column_dimensions.items():
        try:
            index = getattr(dimension, "min", None) or column_index_from_string(key)
            last = getattr(dimension, "max", None) or index
        except ValueError:
            continue
        columns.append(
            {
                "min": index,
                "max": last,
                "letter": get_column_letter(index),
                "width": getattr(dimension, "width", None),
                "hidden": bool(getattr(dimension, "hidden", False)),
                "best_fit": bool(getattr(dimension, "bestFit", False)),
                "collapsed": bool(getattr(dimension, "collapsed", False)),
                "outline_level": getattr(dimension, "outlineLevel", 0),
            }
        )
    columns.sort(key=lambda item: item["min"])
    return columns


def _row_metadata(ws: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, dimension in ws.row_dimensions.items():
        height = getattr(dimension, "height", None)
        if height is None:
            height = getattr(dimension, "ht", None)
        rows.append(
            {
                "index": index,
                "height": height,
                "hidden": bool(getattr(dimension, "hidden", False)),
                "collapsed": bool(getattr(dimension, "collapsed", False)),
                "outline_level": getattr(dimension, "outlineLevel", 0),
            }
        )
    rows.sort(key=lambda item: item["index"])
    return rows


def _serialize_sheet(
    ws: Any,
    ws_values: Any,
    config: MirrorConfig,
    theme: ThemePalette,
    registry: StyleRegistry,
) -> tuple[dict[str, Any], list[str], set[str]]:
    warnings: list[str] = []
    merged_lookup = MergedLookup(ws.merged_cells.ranges)

    max_row = ws.max_row or 1
    max_col = ws.max_column or 1
    if max_row * max_col > config.max_cells_per_sheet:
        allowed_rows = max(1, config.max_cells_per_sheet // max(1, max_col))
        warnings.append(
            f"'{ws.title}': intervalo {max_row}x{max_col} excede o limite de "
            f"{config.max_cells_per_sheet} células; truncado para {allowed_rows} linhas."
        )
        max_row = min(max_row, allowed_rows)

    cells: list[dict[str, Any]] = []
    editable_refs: set[str] = set()
    missing_cache = ws_values is None

    for row in ws.iter_rows(min_row=1, max_row=max_row, max_col=max_col):
        for cell in row:
            merged = merged_lookup.find(cell.row, cell.column)
            if merged is not None and not merged.is_anchor:
                continue

            value = getattr(cell, "value", None)
            data_type = getattr(cell, "data_type", None)
            has_style = bool(getattr(cell, "has_style", False))
            has_value = value is not None
            if not (has_value or has_style or merged is not None or config.include_empty_cells):
                continue

            editable, reasons = determine_editability(cell, merged, config, theme)
            style_id = registry.register(extract_style(cell, theme))

            formula = None
            cached_value = None
            value_type = "null"
            json_value = None

            is_formula = data_type == "f" or (isinstance(value, str) and value.startswith("="))
            if is_formula:
                formula = _formula_text(value)
                cached_cell = _cached_cell(ws_values, cell.coordinate) if not missing_cache else None
                cached_value = getattr(cached_cell, "value", None) if cached_cell is not None else None
                json_value, value_type = _json_value(cached_value, data_type)
            else:
                json_value, value_type = _json_value(value, data_type)

            cell_dict: dict[str, Any] = {
                "ref": cell.coordinate,
                "row": cell.row,
                "col": cell.column,
                "value": json_value,
                "value_type": value_type,
                "formula": formula,
                "cached_value": _json_value(cached_value, data_type)[0] if is_formula else None,
                "data_type": data_type,
                "editavel": editable,
                "editavel_motivo": reasons,
                "style": style_id,
            }
            if merged is not None:
                cell_dict["merged"] = merged.range
                cell_dict["rowspan"] = merged.rowspan
                cell_dict["colspan"] = merged.colspan
            cells.append(cell_dict)
            if editable:
                editable_refs.add(cell.coordinate)

    tab_color = resolve_color(getattr(ws.sheet_properties, "tabColor", None), theme)
    sheet_dict: dict[str, Any] = {
        "name": ws.title,
        "state": ws.sheet_state,
        "tab_color": tab_color,
        "max_row": max_row,
        "max_col": max_col,
        "freeze_panes": ws.freeze_panes,
        "default_col_width": ws.sheet_format.defaultColWidth,
        "default_row_height": ws.sheet_format.defaultRowHeight,
        "base_col_width": getattr(ws.sheet_format, "baseColWidth", None),
        "columns": _column_metadata(ws),
        "rows": _row_metadata(ws),
        "merged_ranges": [str(rng) for rng in ws.merged_cells.ranges],
        "cells": cells,
    }
    return sheet_dict, warnings, editable_refs


def _matching_values_sheet(workbook_data: WorkbookData, title: str) -> Any:
    if workbook_data.wb_values is None:
        return None
    try:
        return workbook_data.wb_values[title]
    except KeyError:
        return None


def serialize_workbook(
    workbook_data: WorkbookData,
    config: MirrorConfig | None = None,
) -> tuple[dict[str, Any], dict[str, set[str]], list[str]]:
    """Serializa o workbook completo para o dicionário do ``mirror.json``."""
    cfg = config or MirrorConfig()
    registry = StyleRegistry()
    sheets: list[dict[str, Any]] = []
    editable_by_sheet: dict[str, set[str]] = {}
    warnings: list[str] = list(workbook_data.warnings)
    total_cells = 0

    for ws in workbook_data.wb_formulas.worksheets:
        if ws.sheet_state != "visible" and cfg.ignore_hidden_sheets:
            warnings.append(f"Aba '{ws.title}' ignorada por estar oculta.")
            continue
        ws_values = _matching_values_sheet(workbook_data, ws.title)
        if ws_values is None and cfg.read_cached_values:
            warnings.append(f"Sem valores em cache para a aba '{ws.title}'.")
        sheet_dict, sheet_warnings, editable_refs = _serialize_sheet(
            ws, ws_values, cfg, workbook_data.theme, registry
        )
        warnings.extend(sheet_warnings)
        sheets.append(sheet_dict)
        editable_by_sheet[ws.title] = editable_refs
        total_cells += len(sheet_dict["cells"])

    generated_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
    source_path = workbook_data.path
    try:
        size_bytes = source_path.stat().st_size
    except OSError:
        size_bytes = None

    document = {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "source": source_path.name,
            "source_path": str(source_path.resolve()),
            "size_bytes": size_bytes,
            "generated_at": generated_at,
            "config": cfg.to_dict(),
            "theme": workbook_data.theme.to_dict(),
            "warnings": warnings,
            "stats": {
                "sheets": len(sheets),
                "styles": len(registry),
                "cells": total_cells,
            },
        },
        "styles": registry.to_dict(),
        "sheets": sheets,
    }
    return document, editable_by_sheet, warnings
