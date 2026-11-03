"""Adaptador para OpenAI e APIs compatíveis (OpenRouter, DeepSeek etc.)."""

from __future__ import annotations

import json
from typing import Any, Iterator

from .._http import iter_sse, request_json
from ..base import ChatChunk, ChatRequest, ChatResponse, LLMProvider, normalize_base_url

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


def _messages(request: ChatRequest) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if request.system_prompt:
        messages.append({"role": "system", "content": request.system_prompt})
    for message in request.messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        content = message.get("content")
        if content is None:
            content = ""
        messages.append({"role": role, "content": content})
    return messages


def _parse_tool_calls(raw: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return calls
    for item in raw:
        if not isinstance(item, dict):
            continue
        function = item.get("function") if isinstance(item.get("function"), dict) else {}
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError:
                pass
        calls.append(
            {
                "id": item.get("id"),
                "name": function.get("name"),
                "arguments": arguments,
            }
        )
    return calls


class OpenAIProvider(LLMProvider):
    id = "openai"
    label = "OpenAI / compatível"
    requires_key = True

    def _base_url(self) -> str:
        return normalize_base_url(self.config.base_url, default=DEFAULT_BASE_URL)

    def _headers(self) -> dict[str, str]:
        key = self.require_key()
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
        if self.id == "openrouter":
            headers["HTTP-Referer"] = "http://localhost"
            headers["X-Title"] = "Spreadsheet Mirror Engine"
        return headers

    def _model(self, request: ChatRequest) -> str:
        return request.model or self.config.model or DEFAULT_MODEL

    def _payload(self, request: ChatRequest, *, stream: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model(request),
            "messages": _messages(request),
            "temperature": (
                request.temperature
                if request.temperature is not None
                else self.config.temperature
            ),
        }
        max_tokens = request.max_tokens if request.max_tokens is not None else self.config.max_tokens
        if max_tokens:
            payload["max_tokens"] = int(max_tokens)
        if request.tools:
            payload["tools"] = request.tools
        if request.response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        elif isinstance(request.response_format, dict):
            payload["response_format"] = request.response_format
        if stream:
            payload["stream"] = True
        return payload

    def list_models(self) -> list[str]:
        payload = request_json(self, "GET", f"{self._base_url()}/models", headers=self._headers())
        data = payload.get("data")
        models: list[str] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("id"):
                    models.append(str(item["id"]))
        return sorted(set(models)) or [DEFAULT_MODEL]

    def chat(self, request: ChatRequest) -> ChatResponse:
        payload = request_json(
            self,
            "POST",
            f"{self._base_url()}/chat/completions",
            headers=self._headers(),
            json_body=self._payload(request),
        )
        choices = payload.get("choices")
        text = ""
        tool_calls: list[dict[str, Any]] = []
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else {}
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, list):
                text = "".join(
                    str(part.get("text") or "")
                    for part in content
                    if isinstance(part, dict)
                )
            elif content is not None:
                text = str(content)
            if isinstance(message, dict):
                tool_calls = _parse_tool_calls(message.get("tool_calls"))
        return ChatResponse(
            text=text,
            tool_calls=tool_calls,
            usage=payload.get("usage") if isinstance(payload.get("usage"), dict) else {},
            provider=self.id,
            model=self._model(request),
            raw=payload,
        )

    def stream(self, request: ChatRequest) -> Iterator[ChatChunk]:
        url = f"{self._base_url()}/chat/completions"
        usage: dict[str, Any] = {}
        for data in iter_sse(
            self,
            url,
            headers=self._headers(),
            json_body=self._payload(request, stream=True),
        ):
            try:
                event = json.loads(data)
            except ValueError:
                continue
            if isinstance(event.get("usage"), dict):
                usage = event["usage"]
            choices = event.get("choices")
            if not isinstance(choices, list) or not choices:
                continue
            delta = choices[0].get("delta") if isinstance(choices[0], dict) else {}
            text = delta.get("content") if isinstance(delta, dict) else None
            if text:
                yield ChatChunk(text=str(text), raw=event)
        yield ChatChunk(done=True, usage=usage)
