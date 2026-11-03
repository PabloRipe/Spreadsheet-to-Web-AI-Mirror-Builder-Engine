"""Criação de planilhas do zero a partir de uma especificação JSON (Prompt-to-Sheet)."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any, Mapping

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from ..config import MirrorConfig
from ..pipeline import ProjectResult, process_file, slugify

REF_RE = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")
HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")
FORBIDDEN_SHEET = re.compile(r"[\[\]:*?/\\]")

MAX_SHEETS = 10
MAX_ROWS = 200
MAX_COLS = 50
MAX_CELLS = 20_000


class WorkbookSpecError(ValueError):
    """Especificação de planilha inválida."""


def _hex(value: Any) -> str | None:
    if value in (None, ""):
        return None
    match = HEX_RE.fullmatch(str(value).strip())
    if not match:
        raise WorkbookSpecError(f"Cor inválida: {value!r}.")
    return f"FF{match.group(1).upper()}"


def _col_number(letters: str) -> int:
    total = 0
    for char in letters:
        total = total * 26 + (ord(char) - 64)
    return total


def _sheet_name(value: Any, index: int) -> str:
    name = str(value or "").strip() or f"Planilha{index + 1}"
    name = FORBIDDEN_SHEET.sub("_", name)[:31].strip() or f"Planilha{index + 1}"
    return name


def validate_spec(spec: Mapping[str, Any] | None) -> dict[str, Any]:
    """Valida e normaliza uma especificação de workbook."""
    if not isinstance(spec, Mapping):
        raise WorkbookSpecError("A especificação deve ser um objeto JSON.")
    abas = spec.get("abas")
    if not isinstance(abas, list) or not abas:
        raise WorkbookSpecError("A especificação precisa de ao menos uma aba em 'abas'.")
    if len(abas) > MAX_SHEETS:
        raise WorkbookSpecError(f"Limite de {MAX_SHEETS} abas excedido.")

    normalized_sheets: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    total_cells = 0
    for index, aba in enumerate(abas):
        if not isinstance(aba, Mapping):
            raise WorkbookSpecError(f"A aba #{index + 1} deve ser um objeto.")
        name = _sheet_name(aba.get("nome") or aba.get("name"), index)
        lowered = name.lower()
        if lowered in seen_names:
            raise WorkbookSpecError(f"Aba duplicada: '{name}'.")
        seen_names.add(lowered)

        cells = aba.get("celulas", aba.get("cells", []))
        if not isinstance(cells, list):
            raise WorkbookSpecError(f"'celulas' da aba '{name}' deve ser uma lista.")
        total_cells += len(cells)
        if total_cells > MAX_CELLS:
            raise WorkbookSpecError(f"Limite de {MAX_CELLS} células excedido.")

        normalized_cells: list[dict[str, Any]] = []
        seen_refs: set[str] = set()
        for item in cells:
            if not isinstance(item, Mapping):
                raise WorkbookSpecError(f"Célula inválida na aba '{name}'.")
            ref = str(item.get("ref") or "").replace("$", "").upper().strip()
            match = REF_RE.fullmatch(ref)
            if not match:
                raise WorkbookSpecError(f"Referência inválida na aba '{name}': {ref!r}.")
            row = int(match.group(2))
            col = _col_number(match.group(1))
            if row > MAX_ROWS or col > MAX_COLS:
                raise WorkbookSpecError(
                    f"Célula {ref} fora do limite de {MAX_ROWS} linhas x {MAX_COLS} colunas."
                )
            if ref in seen_refs:
                raise WorkbookSpecError(f"Célula duplicada na aba '{name}': {ref}.")
            seen_refs.add(ref)

            formula = item.get("formula")
            value = item.get("valor", item.get("value"))
            if formula is not None:
                formula = str(formula).strip()
                if not formula.startswith("="):
                    formula = f"={formula}"
            else:
                formula = None
            if formula is None and isinstance(value, (dict, list)):
                raise WorkbookSpecError(f"Valor inválido em {name}!{ref}: use tipo escalar.")

            style = item.get("estilo", item.get("style"))
            if style is not None and not isinstance(style, Mapping):
                raise WorkbookSpecError(f"Estilo inválido em {name}!{ref}.")
            style = style or {}
            if style:
                _hex(style.get("fill"))
                _hex(style.get("font_color"))
            normalized_cells.append(
                {"ref": ref, "row": row, "col": col, "value": value, "formula": formula, "style": style}
            )

        columns = aba.get("colunas", aba.get("columns", []))
        if not isinstance(columns, list):
            raise WorkbookSpecError(f"'colunas' da aba '{name}' deve ser uma lista.")
        normalized_columns: list[dict[str, Any]] = []
        for column in columns:
            if not isinstance(column, Mapping):
                continue
            letter = str(column.get("letra") or column.get("letter") or "").upper().strip()
            width = column.get("largura", column.get("width"))
            if not letter:
                continue
            try:
                width_value = float(width)
            except (TypeError, ValueError):
                continue
            if 1 <= width_value <= 255:
                normalized_columns.append({"letra": letter, "largura": width_value})

        merges = aba.get("mesclagens", aba.get("merges", []))
        normalized_merges: list[str] = []
        if isinstance(merges, list):
            for merged in merges:
                text = str(merged or "").replace("$", "").upper().strip()
                if ":" in text and all(REF_RE.fullmatch(part) for part in text.split(":")):
                    normalized_merges.append(text)

        normalized_sheets.append(
            {
                "nome": name,
                "cor": _hex(aba.get("cor") or aba.get("color")),
                "celulas": normalized_cells,
                "colunas": normalized_columns,
                "mesclagens": normalized_merges,
            }
        )

    return {
        "nome": str(spec.get("nome") or spec.get("name") or "planilha-ia"),
        "abas": normalized_sheets,
    }


def _apply_style(cell: Any, style: Mapping[str, Any]) -> None:
    font_kwargs: dict[str, Any] = {}
    if "bold" in style:
        font_kwargs["bold"] = bool(style.get("bold"))
    if "italic" in style:
        font_kwargs["italic"] = bool(style.get("italic"))
    color = _hex(style.get("font_color"))
    if color:
        font_kwargs["color"] = color
    try:
        size = float(style.get("font_size") or 0)
    except (TypeError, ValueError):
        size = 0
    if size > 0:
        font_kwargs["size"] = size
    if font_kwargs:
        cell.font = Font(**font_kwargs)

    fill = _hex(style.get("fill"))
    if fill:
        cell.fill = PatternFill("solid", fgColor=fill)

    number_format = style.get("number_format") or style.get("formato")
    if number_format:
        cell.number_format = str(number_format)

    if style.get("wrap"):
        cell.alignment = Alignment(wrap_text=True, vertical="center")


def _build_workbook(spec: Mapping[str, Any]) -> Workbook:
    workbook = Workbook()
    default = workbook.active
    for index, aba in enumerate(spec["abas"]):
        worksheet = default if index == 0 else workbook.create_sheet()
        worksheet.title = aba["nome"]
        if aba.get("cor"):
            worksheet.sheet_properties.tabColor = aba["cor"]
        for column in aba["colunas"]:
            worksheet.column_dimensions[column["letra"]].width = column["largura"]
        for item in aba["celulas"]:
            cell = worksheet[item["ref"]]
            if item["formula"]:
                cell.value = item["formula"]
            elif item["value"] is not None:
                cell.value = item["value"]
            if item["style"]:
                _apply_style(cell, item["style"])
        for merged in aba["mesclagens"]:
            try:
                worksheet.merge_cells(merged)
            except ValueError:
                continue
    return workbook


def _unique_project_slug(base: str, workspace: Path) -> str:
    slug = slugify(base) or "planilha-ia"
    candidate = slug
    counter = 2
    while (workspace / candidate).exists():
        candidate = f"{slug}-{counter}"
        counter += 1
    return candidate


def create_project_from_spec(
    spec: Mapping[str, Any],
    workspace: str | Path,
    *,
    config: MirrorConfig | None = None,
) -> ProjectResult:
    """Gera um ``.xlsx`` real, espelha e devolve o projeto criado."""
    normalized = validate_spec(spec)
    base = Path(workspace).resolve()
    base.mkdir(parents=True, exist_ok=True)
    project_slug = _unique_project_slug(normalized["nome"], base)
    project_dir = base / project_slug
    project_dir.mkdir(parents=True, exist_ok=True)
    source_path = project_dir / f"{project_slug}.xlsx"

    workbook = _build_workbook(normalized)
    workbook.save(source_path)

    try:
        return process_file(
            source_path,
            base,
            config or MirrorConfig(),
            overwrite=True,
            slug=project_slug,
        )
    except Exception:
        shutil.rmtree(project_dir, ignore_errors=True)
        raise
