"""Adaptador para Ollama local (sem exigência de chave)."""

from __future__ import annotations

from typing import Any, Iterator

from .._http import iter_ndjson, request_json
from ..base import ChatChunk, ChatRequest, ChatResponse, LLMProvider, normalize_base_url

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.1"


def _messages(request: ChatRequest) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if request.system_prompt:
        messages.append({"role": "system", "content": request.system_prompt})
    for message in request.messages:
        if not isinstance(message, dict):
            continue
        messages.append(
            {
                "role": str(message.get("role") or "user"),
                "content": str(message.get("content") or ""),
            }
        )
    return messages


class OllamaProvider(LLMProvider):
    id = "ollama"
    label = "Ollama (local)"
    requires_key = False

    def _base_url(self) -> str:
        return normalize_base_url(self.config.base_url, default=DEFAULT_BASE_URL)

    def _model(self, request: ChatRequest) -> str:
        return request.model or self.config.model or DEFAULT_MODEL

    def _payload(self, request: ChatRequest, *, stream: bool = False) -> dict[str, Any]:
        max_tokens = request.max_tokens if request.max_tokens is not None else self.config.max_tokens
        temperature = (
            request.temperature if request.temperature is not None else self.config.temperature
        )
        payload: dict[str, Any] = {
            "model": self._model(request),
            "messages": _messages(request),
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_predict": int(max_tokens or 2048),
            },
        }
        if request.response_format == "json":
            payload["format"] = "json"
        return payload

    def list_models(self) -> list[str]:
        payload = request_json(self, "GET", f"{self._base_url()}/api/tags")
        data = payload.get("models")
        models: list[str] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("name"):
                    models.append(str(item["name"]))
        return sorted(set(models)) or [DEFAULT_MODEL]

    def chat(self, request: ChatRequest) -> ChatResponse:
        payload = request_json(
            self,
            "POST",
            f"{self._base_url()}/api/chat",
            json_body=self._payload(request),
        )
        message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        usage: dict[str, Any] = {}
        if payload.get("prompt_eval_count") is not None or payload.get("eval_count") is not None:
            usage = {
                "prompt_tokens": payload.get("prompt_eval_count"),
                "completion_tokens": payload.get("eval_count"),
            }
        return ChatResponse(
            text=str(message.get("content") or ""),
            usage=usage,
            provider=self.id,
            model=self._model(request),
            raw=payload,
        )

    def stream(self, request: ChatRequest) -> Iterator[ChatChunk]:
        usage: dict[str, Any] = {}
        for event in iter_ndjson(
            self,
            f"{self._base_url()}/api/chat",
            json_body=self._payload(request, stream=True),
        ):
            message = event.get("message") if isinstance(event.get("message"), dict) else {}
            text = message.get("content")
            if text:
                yield ChatChunk(text=str(text), raw=event)
            if event.get("done"):
                if event.get("prompt_eval_count") is not None or event.get("eval_count") is not None:
                    usage = {
                        "prompt_tokens": event.get("prompt_eval_count"),
                        "completion_tokens": event.get("eval_count"),
                    }
                break
        yield ChatChunk(done=True, usage=usage)
