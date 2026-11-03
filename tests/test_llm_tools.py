"""Testes das ferramentas de planilha e da validação de edições."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from spreadsheet_mirror.llm.tools import (
    execute_tool,
    propose_edits,
    read_range,
    search_cells,
    suggest_formula,
    summarize_sheet,
    tool_definitions,
    validate_edits,
)


def _document() -> dict[str, Any]:
    return {
        "meta": {"config": {"header_rows": [2]}},
        "styles": {"s0": {"font": {"bold": True}}},
        "sheets": [
            {
                "name": "Vendas",
                "state": "visible",
                "max_row": 5,
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
                        "col": 1,
                        "value": "Produto",
                        "value_type": "string",
                        "editavel": False,
                        "style": "s0",
                    },
                    {
                        "ref": "A3",
                        "row": 3,
                        "col": 1,
                        "value": "Item",
                        "value_type": "string",
                        "editavel": True,
                        "style": "s0",
                    },
                    {
                        "ref": "B3",
                        "row": 3,
                        "col": 2,
                        "value": 10,
                        "value_type": "number",
                        "editavel": True,
                        "style": "s0",
                    },
                    {
                        "ref": "C3",
                        "row": 3,
                        "col": 3,
                        "value": 20,
                        "value_type": "number",
                        "formula": "=B3*2",
                        "editavel": False,
                        "style": "s0",
                    },
                ],
            }
        ],
    }


def test_validate_edits_accepts_only_editable_cells():
    result = validate_edits(
        _document(),
        [
            {"aba": "Vendas", "coordenada": "A3", "novo_valor": "Novo"},
            {"aba": "Vendas", "coordenada": "B3", "novo_valor": 1500},
            {"aba": "Vendas", "coordenada": "A4", "novo_valor": "Livre"},
        ],
    )
    assert result["aplicaveis"] == {"Vendas": {"A3": "Novo", "B3": 1500, "A4": "Livre"}}
    assert result["rejeitadas"] == []


def test_validate_edits_rejects_fixed_merged_header_and_invalid():
    result = validate_edits(
        _document(),
        [
            {"aba": "Vendas", "coordenada": "A1", "novo_valor": "x"},
            {"aba": "Vendas", "coordenada": "B1", "novo_valor": "x"},
            {"aba": "Vendas", "coordenada": "A2", "novo_valor": "x"},
            {"aba": "Vendas", "coordenada": "C3", "novo_valor": "x"},
            {"aba": "Vendas", "coordenada": "A99", "novo_valor": "x"},
            {"aba": "Vendas", "coordenada": "ZZZ", "novo_valor": "x"},
            {"aba": "Inexistente", "coordenada": "A3", "novo_valor": "x"},
            {"aba": "Vendas", "coordenada": "A4", "novo_valor": "=SUM(A1:A3)"},
        ],
    )
    reasons = {(item["coordenada"], item["motivo"]) for item in result["rejeitadas"]}
    assert ("A1", "celula_fixa") in reasons
    assert ("B1", "mesclada_nao_ancora") in reasons
    assert ("A2", "celula_fixa") in reasons
    assert ("C3", "celula_fixa") in reasons
    assert ("A99", "fora_dimensao") in reasons
    assert ("ZZZ", "coordenada_invalida") in reasons
    assert ("A3", "aba_inexistente") in reasons
    assert ("A4", "formula_em_celula_vazia") in reasons
    assert result["aplicaveis"] == {}


def test_validate_edits_accepts_mapping_payload():
    result = validate_edits(_document(), {"Vendas": {"A3": "ok"}})
    assert result["aplicaveis"] == {"Vendas": {"A3": "ok"}}


def test_propose_edits_is_pure_and_normalizes():
    document = _document()
    snapshot = copy.deepcopy(document)
    result = propose_edits(document, "Vendas", [{"ref": "B3", "value": 99}])
    assert result["normalizado"] == {"Vendas": {"B3": 99}}
    assert result["aplicaveis"] == {"Vendas": {"B3": 99}}
    assert document == snapshot


def test_read_range_search_and_summary():
    document = _document()
    result = read_range(document, "Vendas", "A2:C4", draft={"A3": "Rascunho"})
    refs = [cell["ref"] for cell in result["cells"]]
    assert refs == ["A2", "B2", "C2", "A3", "B3", "C3", "A4", "B4", "C4"]
    a3 = next(cell for cell in result["cells"] if cell["ref"] == "A3")
    assert a3["valor_rascunho"] == "Rascunho"

    found = search_cells(document, "Vendas", "item")
    assert found["matches"][0]["ref"] == "A3"
    assert search_cells(document, "Vendas", "")["matches"] == []

    summary = summarize_sheet(document, "Vendas")
    assert summary["abas"][0]["contagem"] == {"fixas": 3, "editaveis": 2}
    assert "celulas" not in summary["abas"][0]

    formula = suggest_formula(document, "Vendas", "A3", "multiplicar por 2")
    assert formula["target_ref"] == "A3"
    assert any(item["posicao"] == "acima" for item in formula["vizinhos"])


def test_read_range_and_search_raise_for_unknown_sheet():
    with pytest.raises(ValueError):
        read_range(_document(), "Nope", "A1")
    with pytest.raises(ValueError):
        search_cells(_document(), "Nope", "x")
    with pytest.raises(ValueError):
        read_range(_document(), "Vendas", "inválido")


def test_execute_tool_dispatch_and_unknown():
    document = _document()
    assert execute_tool("summarize_sheet", {"sheet": "Vendas"}, document)["abas"]
    assert execute_tool("search_cells", {"sheet": "Vendas", "query": "Item"}, document)["matches"]
    assert execute_tool(
        "propose_edits", {"sheet": "Vendas", "edits": [{"ref": "A3", "value": "x"}]}, document
    )["normalizado"]
    with pytest.raises(ValueError):
        execute_tool("drop_table", {}, document)


def test_tool_definitions_provider_formats():
    openai = tool_definitions("openai")
    assert openai[0]["type"] == "function"
    anthropic = tool_definitions("anthropic")
    assert "input_schema" in anthropic[0]
    gemini = tool_definitions("gemini")
    assert "functionDeclarations" in gemini[0]
    assert {item["function"]["name"] for item in openai} == {
        "read_range",
        "search_cells",
        "summarize_sheet",
        "suggest_formula",
        "propose_edits",
    }
