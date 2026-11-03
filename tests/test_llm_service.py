"""Testes do serviço de chat e da orquestração de ferramentas."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from spreadsheet_mirror.llm.base import (
    ChatChunk,
    ChatRequest,
    ChatResponse,
    LLMProvider,
    ProviderConfig,
)
from spreadsheet_mirror.llm.chat_store import ChatStore
from spreadsheet_mirror.llm.service import ChatService


def _document() -> dict[str, Any]:
    return {
        "meta": {"source": "vendas.xlsx", "config": {"header_rows": [2]}},
        "styles": {"s0": {"font": {"bold": True}}},
        "sheets": [
            {
                "name": "Vendas",
                "state": "visible",
                "max_row": 5,
                "max_col": 3,
                "merged_ranges": ["A1:C1"],
                "cells": [
                    {"ref": "A1", "row": 1, "col": 1, "value": "Título", "value_type": "string", "editavel": False, "style": "s0"},
                    {"ref": "A2", "row": 2, "col": 1, "value": "Produto", "value_type": "string", "editavel": False, "style": "s0"},
                    {"ref": "A3", "row": 3, "col": 1, "value": "Item", "value_type": "string", "editavel": True, "style": "s0"},
                    {"ref": "B3", "row": 3, "col": 2, "value": 10, "value_type": "number", "editavel": True, "style": "s0"},
                ],
            }
        ],
    }


class FakeProvider(LLMProvider):
    id = "fake"
    label = "Fake"
    requires_key = False

    def __init__(self, config: ProviderConfig, responses: list[ChatResponse], stream_text: str = "stream") -> None:
        super().__init__(config)
        self.responses = list(responses)
        self.stream_text = stream_text
        self.requests: list[ChatRequest] = []

    def list_models(self) -> list[str]:
        return ["fake-model"]

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        if self.responses:
            return self.responses.pop(0)
        return ChatResponse(text='{"acoes": []}', provider="fake", model="fake-model")

    def stream(self, request: ChatRequest):
        self.requests.append(request)
        yield ChatChunk(text=self.stream_text)
        yield ChatChunk(done=True, usage={"total_tokens": 2})


def _config() -> ProviderConfig:
    return ProviderConfig(id="fake", type="openai", model="fake-model", api_key="sk-hidden")


def test_chat_extracts_validates_and_persists(tmp_path: Path):
    store = ChatStore(tmp_path)
    provider = FakeProvider(
        _config(),
        [
            ChatResponse(
                text=(
                    "Vou preencher.\n"
                    '{"acoes": [{"aba": "Vendas", "coordenada": "B3", "novo_valor": 1500},'
                    ' {"aba": "Vendas", "coordenada": "A1", "novo_valor": "x"}]}'
                ),
                usage={"total_tokens": 9},
                provider="fake",
                model="fake-model",
            )
        ],
    )
    service = ChatService(
        _document(),
        project_slug="vendas",
        store=store,
        provider_factory=lambda config: provider,
    )
    result = service.chat(message="Preencha B3", provider_config=_config(), sheet="Vendas")

    assert result["reply"] == "Vou preencher."
    assert result["aplicaveis"] == {"Vendas": {"B3": 1500}}
    assert result["rejeitadas"][0]["motivo"] == "celula_fixa"
    assert result["usage"]["total_tokens"] == 9
    assert "sk-hidden" not in str(result)

    history = store.load("vendas")["messages"]
    assert [item["role"] for item in history] == ["user", "assistant"]
    assert history[1]["actions"][0]["coordenada"] == "B3"


def test_chat_passes_history_and_context(tmp_path: Path):
    store = ChatStore(tmp_path)
    store.append("vendas", {"role": "user", "content": "mensagem anterior"})
    store.append("vendas", {"role": "assistant", "content": "resposta anterior"})
    provider = FakeProvider(_config(), [ChatResponse(text='{"acoes": []}')])
    service = ChatService(
        _document(),
        project_slug="vendas",
        store=store,
        draft={"Vendas": {"B3": 77}},
        provider_factory=lambda config: provider,
    )
    service.chat(message="E agora?", provider_config=_config(), sheet="Vendas")

    request = provider.requests[0]
    assert request.messages[0]["content"] == "mensagem anterior"
    assert request.messages[-1]["content"] == "E agora?"
    assert "Contexto atual" in request.system_prompt
    assert '"valor_rascunho":77' in request.system_prompt
    assert request.tools


def test_chat_executes_tool_calls_before_final_answer(tmp_path: Path):
    provider = FakeProvider(
        _config(),
        [
            ChatResponse(
                text="",
                tool_calls=[
                    {"name": "read_range", "arguments": {"sheet": "Vendas", "range": "A1:B3"}},
                    {"name": "propose_edits", "arguments": {"sheet": "Vendas", "edits": [{"ref": "B3", "value": 42}]}},
                ],
                provider="fake",
                model="fake-model",
            ),
            ChatResponse(
                text='Concluído. {"acoes": []}', provider="fake", model="fake-model"
            ),
        ],
    )
    service = ChatService(
        _document(),
        project_slug="vendas",
        provider_factory=lambda config: provider,
    )
    result = service.chat(message="Leia e proponha", provider_config=_config(), sheet="Vendas")
    assert result["aplicaveis"] == {"Vendas": {"B3": 42}}
    assert result["reply"] == "Concluído."
    assert len(provider.requests) == 2
    assert "Resultados das ferramentas" in provider.requests[1].messages[-1]["content"]
    assert provider.requests[1].tools is None


def test_chat_rejects_empty_message_and_invalid_provider_factory(tmp_path: Path):
    service = ChatService(_document(), project_slug="p")
    with pytest.raises(ValueError):
        service.chat(message="   ", provider_config=_config())

    def bad_factory(config):
        return object()

    broken = ChatService(_document(), project_slug="p", provider_factory=bad_factory)
    with pytest.raises(TypeError):
        broken.chat(message="oi", provider_config=_config())


def test_stream_chat_events_and_persistence(tmp_path: Path):
    store = ChatStore(tmp_path)
    provider = FakeProvider(
        _config(),
        [],
        stream_text='Resposta {"acoes": [{"aba": "Vendas", "coordenada": "A3", "novo_valor": "Novo"}]}',
    )
    service = ChatService(
        _document(), project_slug="vendas", store=store, provider_factory=lambda config: provider
    )
    events = list(
        service.stream_chat(message="Atualize", provider_config=_config(), sheet="Vendas")
    )
    assert events[0]["type"] == "meta"
    assert any(event["type"] == "delta" for event in events)
    done = events[-1]
    assert done["type"] == "done"
    assert done["aplicaveis"] == {"Vendas": {"A3": "Novo"}}
    assert store.load("vendas")["messages"]


def test_stream_chat_reports_errors():
    class Exploding(FakeProvider):
        def stream(self, request):
            raise RuntimeError("falhou sk-hidden")

    provider = Exploding(_config(), [])
    service = ChatService(_document(), project_slug="p", provider_factory=lambda config: provider)
    events = list(service.stream_chat(message="oi", provider_config=_config()))
    assert events[-1]["type"] == "error"
    assert "sk-hidden" not in events[-1]["error"]


def test_generate_workbook_spec(tmp_path: Path):
    spec_text = (
        '```json\n{"nome": "Nova", "abas": [{"nome": "Dados", "celulas": ['
        '{"ref": "A1", "valor": "Nome", "estilo": {"bold": true}},'
        '{"ref": "A2", "valor": "X"}]}]}\n```'
    )
    provider = FakeProvider(_config(), [ChatResponse(text=spec_text, provider="fake", model="fake-model")])
    service = ChatService({}, project_slug="", provider_factory=lambda config: provider)
    result = service.generate_workbook_spec("Crie uma planilha", _config())
    assert result["spec"]["abas"][0]["nome"] == "Dados"
    with pytest.raises(ValueError):
        service.generate_workbook_spec("  ", _config())
