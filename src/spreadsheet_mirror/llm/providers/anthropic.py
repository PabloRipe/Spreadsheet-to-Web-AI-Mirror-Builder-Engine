"""Adaptador para a API da Anthropic (Claude)."""

from __future__ import annotations

import json
from typing import Any, Iterator

from .._http import iter_sse, request_json
from ..base import ChatChunk, ChatRequest, ChatResponse, LLMProvider, normalize_base_url

DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
DEFAULT_MODEL = "claude-3-5-sonnet-latest"
ANTHROPIC_VERSION = "2023-06-01"


def _messages(request: ChatRequest) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for message in request.messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        if role == "system":
            continue
        if role not in {"user", "assistant"}:
            role = "user"
        messages.append({"role": role, "content": str(message.get("content") or "")})
    return messages


class AnthropicProvider(LLMProvider):
    id = "anthropic"
    label = "Anthropic (Claude)"
    requires_key = True

    def _base_url(self) -> str:
        return normalize_base_url(self.config.base_url, default=DEFAULT_BASE_URL)

    def _headers(self) -> dict[str, str]:
        key = self.require_key()
        return {
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": ANTHROPIC_VERSION,
        }

    def _model(self, request: ChatRequest) -> str:
        return request.model or self.config.model or DEFAULT_MODEL

    def _payload(self, request: ChatRequest, *, stream: bool = False) -> dict[str, Any]:
        max_tokens = request.max_tokens if request.max_tokens is not None else self.config.max_tokens
        payload: dict[str, Any] = {
            "model": self._model(request),
            "max_tokens": int(max_tokens or 2048),
            "messages": _messages(request),
            "temperature": (
                request.temperature
                if request.temperature is not None
                else self.config.temperature
            ),
        }
        if request.system_prompt:
            payload["system"] = request.system_prompt
        if request.tools:
            payload["tools"] = request.tools
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
            f"{self._base_url()}/messages",
            headers=self._headers(),
            json_body=self._payload(request),
        )
        blocks = payload.get("content")
        texts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if block_type == "text":
                    texts.append(str(block.get("text") or ""))
                elif block_type == "tool_use":
                    tool_calls.append(
                        {
                            "id": block.get("id"),
                            "name": block.get("name"),
                            "arguments": block.get("input"),
                        }
                    )
        usage = payload.get("usage")
        return ChatResponse(
            text="".join(texts),
            tool_calls=tool_calls,
            usage=usage if isinstance(usage, dict) else {},
            provider=self.id,
            model=self._model(request),
            raw=payload,
        )

    def stream(self, request: ChatRequest) -> Iterator[ChatChunk]:
        url = f"{self._base_url()}/messages"
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
            event_type = event.get("type")
            if event_type == "content_block_delta":
                delta = event.get("delta") if isinstance(event.get("delta"), dict) else {}
                text = delta.get("text")
                if text:
                    yield ChatChunk(text=str(text), raw=event)
            elif event_type == "message_delta":
                delta = event.get("delta") if isinstance(event.get("delta"), dict) else {}
                if isinstance(delta.get("usage"), dict):
                    usage = delta["usage"]
                if isinstance(event.get("usage"), dict):
                    usage = event["usage"]
        yield ChatChunk(done=True, usage=usage)
