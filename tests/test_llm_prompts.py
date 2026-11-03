"""Testes do system prompt e do parsing de saída estruturada."""

from __future__ import annotations

import pytest

from spreadsheet_mirror.llm.prompts import (
    build_create_system_prompt,
    build_edit_system_prompt,
    extract_actions,
    extract_workbook_spec,
)


def test_build_edit_prompt_injects_context():
    prompt = build_edit_system_prompt({"abas": [{"nome": "Vendas"}]})
    assert "editavel" in prompt
    assert '"abas":[{"nome":"Vendas"}]' in prompt
    assert "acoes" in prompt


def test_build_create_prompt():
    prompt = build_create_system_prompt()
    assert "abas" in prompt
    assert "formula" in prompt


def test_extract_actions_from_fenced_block():
    text = (
        "Vou atualizar o preço.\n\n"
        '```json\n{"acoes": [{"aba": "Vendas", "coordenada": "b5", "novo_valor": 1500},'
        ' {"sheet": "Vendas", "ref": "C5", "value": "=B5*0.1"}]}\n```'
    )
    result = extract_actions(text)
    assert result["found"] is True
    assert result["reply"] == "Vou atualizar o preço."
    assert result["acoes"] == [
        {"aba": "Vendas", "coordenada": "B5", "novo_valor": 1500},
        {"aba": "Vendas", "coordenada": "C5", "novo_valor": "=B5*0.1"},
    ]


def test_extract_actions_from_raw_json_and_empty_list():
    result = extract_actions('Pronto. {"acoes": []}')
    assert result["found"] is True
    assert result["acoes"] == []
    assert result["reply"] == "Pronto."


def test_extract_actions_ignores_invalid_items_and_plain_text():
    result = extract_actions('{"acoes": [{"aba": "", "coordenada": "A1", "novo_valor": 1}, "x"]}')
    assert result["acoes"] == []
    assert result["errors"]

    plain = extract_actions("Só conversa, sem alterações.")
    assert plain["found"] is False
    assert plain["reply"] == "Só conversa, sem alterações."


def test_extract_workbook_spec_from_fence_and_raw():
    fence = '```json\n{"nome": "X", "abas": [{"nome": "A", "celulas": []}]}\n```'
    assert extract_workbook_spec(fence)["abas"][0]["nome"] == "A"
    raw = '{"abas": [{"nome": "B"}]}'
    assert extract_workbook_spec(raw)["abas"][0]["nome"] == "B"


def test_extract_workbook_spec_raises():
    with pytest.raises(ValueError):
        extract_workbook_spec("nada aqui")
    with pytest.raises(ValueError):
        extract_workbook_spec('{"nome": "sem abas"}')
