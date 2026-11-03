"""Testes do construtor de contexto para o chat."""

from __future__ import annotations

from typing import Any

from spreadsheet_mirror.llm.context import ContextBuilder, build_context, expand_range


def _document() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "meta": {
            "source": "vendas.xlsx",
            "config": {"header_rows": [2], "treat_no_fill_as_editable": True},
        },
        "styles": {
            "s0": {
                "font": {"name": "Calibri", "size": 11, "bold": True, "color": {"hex": "#ffffff"}},
                "fill": {"pattern_type": "solid", "fg_color": {"hex": "#4F81BD"}},
                "number_format": "General",
                "alignment": {"horizontal": "center", "wrap_text": True},
            },
            "s1": {
                "font": {"name": "Calibri", "size": 11},
                "fill": {"pattern_type": "solid", "fg_color": {"hex": "#FFFFFF"}},
                "number_format": "R$ #,##0.00",
                "alignment": {},
            },
            "s2": {"font": {}, "fill": {}, "number_format": "General"},
        },
        "sheets": [
            {
                "name": "Vendas",
                "state": "visible",
                "max_row": 6,
                "max_col": 3,
                "merged_ranges": ["A1:C1"],
                "cells": [
                    {
                        "ref": "A1",
                        "row": 1,
                        "col": 1,
                        "value": "Título",
                        "value_type": "string",
                        "editavel": False,
                        "style": "s0",
                        "merged": "A1:C1",
                    },
                    {
                        "ref": "A2",
                        "row": 2,
                        "col": 2,
                        "value": "Produto",
                        "value_type": "string",
                        "editavel": False,
                        "style": "s0",
                    },
                    {
                        "ref": "A3",
                        "row": 3,
                        "col": 1,
                        "value": "Produto 1",
                        "value_type": "string",
                        "editavel": True,
                        "style": "s1",
                    },
                    {
                        "ref": "B3",
                        "row": 3,
                        "col": 2,
                        "value": 10,
                        "value_type": "number",
                        "editavel": True,
                        "style": "s1",
                    },
                    {
                        "ref": "C3",
                        "row": 3,
                        "col": 3,
                        "value": 20,
                        "value_type": "number",
                        "formula": "=B3*2",
                        "editavel": False,
                        "style": "s2",
                    },
                ],
            },
            {
                "name": "Entradas",
                "state": "hidden",
                "max_row": 2,
                "max_col": 2,
                "merged_ranges": [],
                "cells": [
                    {
                        "ref": "A1",
                        "row": 1,
                        "col": 1,
                        "value": "Nome",
                        "value_type": "string",
                        "editavel": False,
                        "style": "s0",
                    }
                ],
            },
        ],
    }


def test_expand_range_variants():
    assert expand_range("B2:C4") == (2, 2, 3, 4)
    assert expand_range("C5") == (3, 5, 3, 5)
    assert expand_range("inválido") is None
    assert expand_range("") is None


def test_selection_mode_includes_only_requested_cells_and_draft():
    context = build_context(
        _document(),
        "selection",
        sheet="Vendas",
        selection="A2:B4",
        draft={"Vendas": {"A3": "Novo produto"}},
    )
    sheet = context["abas"][0]
    refs = [cell["ref"] for cell in sheet["celulas"]]
    assert refs == ["A2", "A3", "B3", "A4", "B4"]
    assert "B1" not in refs
    cell_a3 = next(cell for cell in sheet["celulas"] if cell["ref"] == "A3")
    assert cell_a3["valor_rascunho"] == "Novo produto"
    assert cell_a3["estilo"]["fill"] == "#FFFFFF"
    assert sheet["contagem"]["fixas"] == 3
    assert sheet["contagem"]["editaveis"] == 2
    assert context["estilos_usados"]
    assert "A1" not in context["estilos_usados"]


def test_sheet_mode_contains_cells_and_styles_used():
    context = build_context(_document(), "sheet", sheet="Vendas")
    sheet = context["abas"][0]
    assert sheet["nome"] == "Vendas"
    assert sheet["cabecalhos_detectados"] == [2]
    assert any(cell["ref"] == "C3" and cell.get("formula") == "=B3*2" for cell in sheet["celulas"])
    assert set(context["estilos_usados"]) <= {"s0", "s1", "s2"}
    assert "s2" in context["estilos_usados"]


def test_project_mode_only_summaries():
    context = build_context(_document(), "project")
    assert [item["nome"] for item in context["abas"]] == ["Vendas", "Entradas"]
    assert all("celulas" not in item for item in context["abas"])
    assert any("resumos" in warning for warning in context["avisos"])


def test_context_truncates_cells():
    builder = ContextBuilder(_document(), max_context_cells=2)
    context = builder.build("sheet", sheet="Vendas")
    cells = context["abas"][0]["celulas"]
    assert len(cells) <= 2
    assert any("truncado" in warning.lower() for warning in context["avisos"])


def test_invalid_selection_falls_back_to_sheet():
    context = build_context(_document(), "selection", sheet="Vendas", selection="???")
    assert context["abas"][0]["celulas"]
    assert any("Seleção inválida" in warning for warning in context["avisos"])
