"""Testes dos adaptadores Multi-LLM (sem chamadas de rede reais)."""

from __future__ import annotations

import json
from typing import Any, Callable

import httpx
import pytest

from spreadsheet_mirror.llm import (
    AuthError,
    ChatRequest,
    ProviderError,
    RateLimitError,
    build_config,
    catalog_public,
    create_provider,
    models_for,
    preset,
)
from spreadsheet_mirror.llm.providers.anthropic import AnthropicProvider
from spreadsheet_mirror.llm.providers.gemini import GeminiProvider
from spreadsheet_mirror.llm.providers.ollama import OllamaProvider
from spreadsheet_mirror.llm.providers.openai import OpenAIProvider


def _provider(cls, handler: Callable[[httpx.Request], httpx.Response], **overrides: Any):
    data: dict[str, Any] = {"id": cls.id, "api_key": "sk-test-123456", "model": "test-model"}
    data.update(overrides)
    config = build_config(data)
    return cls(config, transport=httpx.MockTransport(handler))


def _json_request(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content.decode("utf-8")) if request.content else {}


def test_catalog_contains_required_providers():
    ids = {item["id"] for item in catalog_public()}
    assert {"openai", "gemini", "anthropic", "openrouter", "deepseek", "ollama"} <= ids
    assert all("api_key" not in item for item in catalog_public())


def test_presets_and_models():
    assert preset("deepseek")["type"] == "openai"
    assert preset("openrouter")["default_base_url"].startswith("https://openrouter.ai")
    assert "llama3.1" in models_for("ollama")
    assert models_for("desconhecido") == []


def test_build_config_applies_defaults_and_normalizes_url():
    config = build_config({"provider": "deepseek"})
    assert config.id == "deepseek"
    assert config.type == "openai"
    assert config.model == "deepseek-chat"
    assert config.base_url == "https://api.deepseek.com/v1"
    assert config.public_dict()["has_key"] is False


def test_build_config_rejects_invalid_type_and_url():
    with pytest.raises(ValueError):
        build_config({"id": "x", "type": "invalido"})
    with pytest.raises(ValueError):
        build_config({"id": "x", "type": "openai", "base_url": "file:///etc/passwd"})
    with pytest.raises(ValueError):
        build_config({"id": "x", "type": "openai", "base_url": "ftp://host"})


def test_optional_host_allowlist(monkeypatch):
    from spreadsheet_mirror.llm.registry import validate_provider_config

    monkeypatch.setenv("MIRROR_LLM_ALLOWED_HOSTS", "api.example.com,localhost")
    assert validate_provider_config(
        {"id": "openai", "model": "m", "base_url": "https://api.example.com/v1"}
    ).base_url.endswith("/v1")
    with pytest.raises(ValueError):
        validate_provider_config(
            {"id": "openai", "model": "m", "base_url": "https://evil.example.org/v1"}
        )


def test_openai_chat_parses_text_usage_and_tool_calls():
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["payload"] = _json_request(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "Olá!",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "function": {
                                        "name": "propose_edits",
                                        "arguments": '{"sheet": "Vendas"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    provider = _provider(OpenAIProvider, handler, base_url="https://api.example.com/v1")
    response = provider.chat(
        ChatRequest(
            messages=[{"role": "user", "content": "Oi"}],
            system_prompt="Seja breve",
            model="gpt-x",
            temperature=0.1,
            max_tokens=100,
            response_format="json",
        )
    )
    assert seen["url"].endswith("/chat/completions")
    assert seen["auth"] == "Bearer sk-test-123456"
    assert seen["payload"]["model"] == "gpt-x"
    assert seen["payload"]["messages"][0]["role"] == "system"
    assert seen["payload"]["response_format"] == {"type": "json_object"}
    assert seen["payload"]["max_tokens"] == 100
    assert response.text == "Olá!"
    assert response.usage["prompt_tokens"] == 10
    assert response.tool_calls[0]["name"] == "propose_edits"
    assert response.tool_calls[0]["arguments"] == {"sheet": "Vendas"}


def test_openai_stream_and_models():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "m2"}, {"id": "m1"}]})
        body = (
            'data: {"choices":[{"delta":{"content":"A"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"B"}}],"usage":{"total_tokens":3}}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    provider = _provider(OpenAIProvider, handler)
    chunks = list(provider.stream(ChatRequest(messages=[{"role": "user", "content": "x"}])))
    assert "".join(chunk.text for chunk in chunks) == "AB"
    assert chunks[-1].done is True
    assert chunks[-1].usage["total_tokens"] == 3
    assert provider.list_models() == ["m1", "m2"]


def test_openai_errors_are_taxonomic_and_redacted():
    def unauthorized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "chave sk-secret-999 inválida"}})

    provider = _provider(OpenAIProvider, unauthorized, api_key="sk-secret-999")
    with pytest.raises(AuthError) as excinfo:
        provider.chat(ChatRequest(messages=[]))
    assert "sk-secret-999" not in str(excinfo.value)
    assert "***" in str(excinfo.value)

    def limited(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "slow down"}})

    with pytest.raises(RateLimitError):
        _provider(OpenAIProvider, limited).chat(ChatRequest(messages=[]))

    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(ProviderError):
        _provider(OpenAIProvider, broken).chat(ChatRequest(messages=[]))


def test_openai_requires_key():
    provider = OpenAIProvider(build_config({"id": "openai"}))
    with pytest.raises(AuthError):
        provider.chat(ChatRequest(messages=[]))


def test_anthropic_chat_and_stream():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = _json_request(request)
        if payload.get("stream"):
            body = (
                'data: {"type":"content_block_delta","delta":{"text":"Oi"}}\n\n'
                'data: {"type":"message_delta","usage":{"output_tokens":7}}\n\n'
            )
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        assert request.headers["x-api-key"] == "sk-test-123456"
        assert payload["system"] == "sys"
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "Cla"},
                    {"type": "text", "text": "ude"},
                    {"type": "tool_use", "id": "t1", "name": "x", "input": {"a": 1}},
                ],
                "usage": {"input_tokens": 4, "output_tokens": 2},
            },
        )

    provider = _provider(AnthropicProvider, handler)
    response = provider.chat(
        ChatRequest(messages=[{"role": "user", "content": "Oi"}], system_prompt="sys")
    )
    assert response.text == "Claude"
    assert response.tool_calls[0]["arguments"] == {"a": 1}
    assert response.usage["output_tokens"] == 2

    chunks = list(provider.stream(ChatRequest(messages=[], system_prompt="sys")))
    assert "".join(chunk.text for chunk in chunks) == "Oi"
    assert chunks[-1].usage["output_tokens"] == 7


def test_gemini_chat_stream_and_models():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"models": [{"name": "models/gemini-x"}]})
        payload = _json_request(request)
        assert request.url.params["key"] == "sk-test-123456"
        if ":streamGenerateContent" in str(request.url):
            body = 'data: {"candidates":[{"content":{"parts":[{"text":"A"}]}}]}\n\n'
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        assert payload["systemInstruction"]["parts"][0]["text"] == "sys"
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "Gem"}, {"text": "ini"}]}}],
                "usageMetadata": {
                    "promptTokenCount": 3,
                    "candidatesTokenCount": 2,
                    "totalTokenCount": 5,
                },
            },
        )

    provider = _provider(GeminiProvider, handler, model="gemini-x")
    response = provider.chat(
        ChatRequest(messages=[{"role": "user", "content": "Oi"}], system_prompt="sys")
    )
    assert response.text == "Gemini"
    assert response.usage["total_tokens"] == 5
    chunks = list(provider.stream(ChatRequest(messages=[], system_prompt="sys")))
    assert "".join(chunk.text for chunk in chunks) == "A"
    assert provider.list_models() == ["gemini-x"]


def test_ollama_chat_streams_without_key():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"models": [{"name": "llama3.1"}]})
        if _json_request(request).get("stream"):
            body = (
                '{"message":{"content":"Ol"},"done":false}\n'
                '{"message":{"content":"á"},"done":true,"prompt_eval_count":2,"eval_count":1}\n'
            )
            return httpx.Response(200, text=body)
        return httpx.Response(
            200,
            json={
                "message": {"content": "Olá local"},
                "prompt_eval_count": 3,
                "eval_count": 2,
            },
        )

    provider = OllamaProvider(
        build_config({"id": "ollama", "model": "llama3.1"}),
        transport=httpx.MockTransport(handler),
    )
    response = provider.chat(ChatRequest(messages=[{"role": "user", "content": "Oi"}]))
    assert response.text == "Olá local"
    assert response.usage["completion_tokens"] == 2
    chunks = list(provider.stream(ChatRequest(messages=[])))
    assert "".join(chunk.text for chunk in chunks) == "Olá"
    assert chunks[-1].usage["prompt_tokens"] == 2
    assert provider.list_models() == ["llama3.1"]


def test_create_provider_routes_types():
    assert isinstance(create_provider({"id": "openai"}), OpenAIProvider)
    assert isinstance(create_provider({"id": "deepseek"}), OpenAIProvider)
    assert isinstance(create_provider({"id": "anthropic"}), AnthropicProvider)
    assert isinstance(create_provider({"id": "gemini"}), GeminiProvider)
    assert isinstance(create_provider({"id": "ollama"}), OllamaProvider)
    with pytest.raises(ValueError):
        create_provider({"id": "x", "type": "desconhecido"})


def test_stream_fallback_uses_chat():
    from spreadsheet_mirror.llm.base import ChatResponse, LLMProvider

    class Fake(LLMProvider):
        id = "fake"

        def list_models(self):
            return ["fake"]

        def chat(self, request: ChatRequest):
            return ChatResponse(text="fallback", usage={"total_tokens": 1})

    provider = Fake(build_config({"id": "ollama", "model": "x"}))
    chunks = list(provider.stream(ChatRequest(messages=[])))
    assert chunks[0].text == "fallback"
    assert chunks[0].done is True
