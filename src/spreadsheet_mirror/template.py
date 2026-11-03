"""Geração do ``template.xlsx`` limpo e injeção de dados para o ``.xlsx`` final."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from openpyxl import load_workbook
from openpyxl.workbook.workbook import Workbook


def clear_editable_values(
    workbook: Workbook,
    editable_by_sheet: dict[str, set[str]],
) -> None:
    """Remove os valores das células editáveis, preservando estilos e fórmulas."""
    for title, refs in editable_by_sheet.items():
        if title not in workbook.sheetnames:
            continue
        worksheet = workbook[title]
        for ref in refs:
            try:
                cell = worksheet[ref]
            except Exception:  # noqa: BLE001 - referência inválida em arquivos estranhos
                continue
            cell.value = None
            hyperlink = getattr(cell, "hyperlink", None)
            if hyperlink is not None:
                cell.hyperlink = None


def create_template(
    workbook: Workbook,
    editable_by_sheet: dict[str, set[str]],
    output_path: str | Path,
    clear_values: bool = True,
) -> Path:
    """Salva o workbook como template, limpando valores editáveis."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if clear_values:
        clear_editable_values(workbook, editable_by_sheet)
    workbook.save(destination)
    return destination


def fill_template(
    template_path: str | Path,
    data: Mapping[str, Mapping[str, Any]],
    output_path: str | Path,
) -> Path:
    """Injeta dados ``{aba: {ref: valor}}`` no template e salva o ``.xlsx`` final.

    Campos ausentes ou com valor ``None`` permanecem em branco. O salvamento
    preserva fórmulas, estilos e mesclagens do template; o Excel recalcula as
    fórmulas ao abrir o arquivo.
    """
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    workbook = load_workbook(filename=str(template_path))
    for sheet_name, cells in data.items():
        if sheet_name not in workbook.sheetnames:
            continue
        worksheet = workbook[sheet_name]
        for ref, value in cells.items():
            try:
                worksheet[ref].value = value
            except Exception:  # noqa: BLE001 - referência inválida
                continue
    workbook.save(destination)
    return destination
