"""Utilitários HTTP compartilhados pelos adaptadores de provedor."""

from __future__ import annotations

import json
from typing import Any, Iterator

import httpx

from .base import (
    AuthError,
    ProviderError,
    RateLimitError,
    TimeoutError,
    redact_secrets,
)

MAX_RESPONSE_BYTES = 4 * 1024 * 1024


def _make_client(provider: Any) -> httpx.Client:
    timeout = provider.config.timeout_s
    try:
        timeout_value: Any = float(timeout)
    except (TypeError, ValueError):
        timeout_value = 60.0
    return httpx.Client(timeout=timeout_value, transport=provider.transport)


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            detail = error.get("message") or error.get("type")
            if detail:
                return str(detail)
        if error:
            return str(error)
        if payload.get("message"):
            return str(payload["message"])
    text = response.text.strip()
    return text[:500] if text else f"HTTP {response.status_code}"


def raise_for_status(provider: Any, response: httpx.Response) -> None:
    status = response.status_code
    if status < 400:
        return
    secret = provider.config.api_key or ""
    detail = redact_secrets(_error_detail(response), [secret])
    if status in (401, 403):
        raise AuthError(f"Credencial recusada pelo provedor '{provider.id}': {detail}")
    if status == 429:
        raise RateLimitError(f"Limite de uso do provedor '{provider.id}': {detail}")
    if status in (408, 504):
        raise TimeoutError(f"O provedor '{provider.id}' demorou para responder: {detail}")
    raise ProviderError(f"Falha no provedor '{provider.id}' (HTTP {status}): {detail}")


def request_json(
    provider: Any,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: Any = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    secret = provider.config.api_key or ""
    try:
        with _make_client(provider) as client:
            response = client.request(method, url, headers=headers, json=json_body, params=params)
    except httpx.TimeoutException as exc:
        raise TimeoutError(f"Timeout ao chamar o provedor '{provider.id}'.") from exc
    except httpx.HTTPError as exc:
        raise ProviderError(
            redact_secrets(f"Falha de rede ao chamar '{provider.id}': {exc}", [secret])
        ) from exc
    raise_for_status(provider, response)
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise ProviderError(
            f"Resposta do provedor '{provider.id}' excedeu o limite de "
            f"{MAX_RESPONSE_BYTES // (1024 * 1024)} MB."
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderError(f"Resposta inválida do provedor '{provider.id}'.") from exc
    return payload if isinstance(payload, dict) else {"data": payload}


def iter_sse(
    provider: Any,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: Any = None,
    params: dict[str, Any] | None = None,
) -> Iterator[str]:
    """Itera os payloads de eventos SSE (``data:``) de uma resposta streaming."""
    secret = provider.config.api_key or ""
    try:
        with _make_client(provider) as client:
            with client.stream(
                "POST", url, headers=headers, json=json_body, params=params
            ) as response:
                if response.status_code >= 400:
                    response.read()
                    raise_for_status(provider, response)
                for line in response.iter_lines():
                    text = line.strip()
                    if not text or not text.startswith("data:"):
                        continue
                    data = text[5:].strip()
                    if not data or data == "[DONE]":
                        if data == "[DONE]":
                            return
                        continue
                    yield data
    except httpx.TimeoutException as exc:
        raise TimeoutError(f"Timeout ao chamar o provedor '{provider.id}'.") from exc
    except httpx.HTTPError as exc:
        raise ProviderError(
            redact_secrets(f"Falha de rede ao chamar '{provider.id}': {exc}", [secret])
        ) from exc


def iter_ndjson(
    provider: Any,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: Any = None,
) -> Iterator[dict[str, Any]]:
    """Itera linhas NDJSON de uma resposta streaming (Ollama)."""
    secret = provider.config.api_key or ""
    try:
        with _make_client(provider) as client:
            with client.stream("POST", url, headers=headers, json=json_body) as response:
                if response.status_code >= 400:
                    response.read()
                    raise_for_status(provider, response)
                for line in response.iter_lines():
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        item = json.loads(text)
                    except ValueError:
                        continue
                    if isinstance(item, dict):
                        yield item
    except httpx.TimeoutException as exc:
        raise TimeoutError(f"Timeout ao chamar o provedor '{provider.id}'.") from exc
    except httpx.HTTPError as exc:
        raise ProviderError(
            redact_secrets(f"Falha de rede ao chamar '{provider.id}': {exc}", [secret])
        ) from exc
