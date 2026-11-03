"""Adaptador para Google Gemini (Generative Language API)."""

from __future__ import annotations

import json
from typing import Any, Iterator

from .._http import iter_sse, request_json
from ..base import ChatChunk, ChatRequest, ChatResponse, LLMProvider, normalize_base_url

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-2.0-flash"


def _model_name(value: str) -> str:
    text = str(value or "").strip()
    return text[7:] if text.startswith("models/") else text


def _contents(request: ChatRequest) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []
    for message in request.messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        if role == "system":
            continue
        contents.append(
            {
                "role": "model" if role in {"assistant", "model"} else "user",
                "parts": [{"text": str(message.get("content") or "")}],
            }
        )
    return contents


class GeminiProvider(LLMProvider):
    id = "gemini"
    label = "Google Gemini"
    requires_key = True

    def _base_url(self) -> str:
        return normalize_base_url(self.config.base_url, default=DEFAULT_BASE_URL)

    def _key(self) -> str:
        return self.require_key()

    def _model(self, request: ChatRequest) -> str:
        return _model_name(request.model or self.config.model or DEFAULT_MODEL)

    def _payload(self, request: ChatRequest) -> dict[str, Any]:
        max_tokens = request.max_tokens if request.max_tokens is not None else self.config.max_tokens
        temperature = (
            request.temperature if request.temperature is not None else self.config.temperature
        )
        payload: dict[str, Any] = {
            "contents": _contents(request),
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": int(max_tokens or 2048),
            },
        }
        if request.response_format == "json":
            payload["generationConfig"]["responseMimeType"] = "application/json"
        if request.system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": request.system_prompt}]}
        return payload

    def list_models(self) -> list[str]:
        payload = request_json(
            self,
            "GET",
            f"{self._base_url()}/models",
            params={"key": self._key()},
        )
        data = payload.get("models")
        models: list[str] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("name"):
                    models.append(_model_name(str(item["name"])))
        return sorted(set(models)) or [DEFAULT_MODEL]

    def chat(self, request: ChatRequest) -> ChatResponse:
        model = self._model(request)
        payload = request_json(
            self,
            "POST",
            f"{self._base_url()}/models/{model}:generateContent",
            params={"key": self._key()},
            json_body=self._payload(request),
        )
        texts: list[str] = []
        candidates = payload.get("candidates")
        if isinstance(candidates, list) and candidates:
            content = candidates[0].get("content") if isinstance(candidates[0], dict) else {}
            parts = content.get("parts") if isinstance(content, dict) else None
            if isinstance(parts, list):
                for part in parts:
                    if isinstance(part, dict) and part.get("text"):
                        texts.append(str(part["text"]))
        raw_usage = payload.get("usageMetadata")
        usage: dict[str, Any] = {}
        if isinstance(raw_usage, dict):
            usage = {
                "prompt_tokens": raw_usage.get("promptTokenCount"),
                "completion_tokens": raw_usage.get("candidatesTokenCount"),
                "total_tokens": raw_usage.get("totalTokenCount"),
            }
        return ChatResponse(
            text="".join(texts),
            usage=usage,
            provider=self.id,
            model=model,
            raw=payload,
        )

    def stream(self, request: ChatRequest) -> Iterator[ChatChunk]:
        model = self._model(request)
        url = f"{self._base_url()}/models/{model}:streamGenerateContent"
        for data in iter_sse(
            self,
            url,
            params={"key": self._key(), "alt": "sse"},
            json_body=self._payload(request),
        ):
            try:
                event = json.loads(data)
            except ValueError:
                continue
            candidates = event.get("candidates")
            if not isinstance(candidates, list) or not candidates:
                continue
            content = candidates[0].get("content") if isinstance(candidates[0], dict) else {}
            parts = content.get("parts") if isinstance(content, dict) else None
            if isinstance(parts, list):
                for part in parts:
                    if isinstance(part, dict) and part.get("text"):
                        yield ChatChunk(text=str(part["text"]), raw=event)
        yield ChatChunk(done=True)
