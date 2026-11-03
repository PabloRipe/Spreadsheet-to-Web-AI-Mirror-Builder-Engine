"""Catálogo e fábrica de provedores de LLM.

Nenhuma credencial é armazenada aqui. O catálogo apenas descreve presets que o
frontend pode exibir e o backend pode instanciar sob demanda.
"""

from __future__ import annotations

import os
from typing import Any, Mapping
from urllib.parse import urlparse

from .base import (
    LLMError,
    ProviderConfig,
    normalize_base_url,
)
from .providers.anthropic import AnthropicProvider
from .providers.gemini import GeminiProvider
from .providers.ollama import OllamaProvider
from .providers.openai import OpenAIProvider

PROVIDER_TYPES = ("openai", "anthropic", "gemini", "ollama", "openai_compatible")

PROVIDER_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "openai",
        "label": "OpenAI (GPT)",
        "type": "openai",
        "default_model": "gpt-4o-mini",
        "default_base_url": "https://api.openai.com/v1",
        "requires_key": True,
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"],
    },
    {
        "id": "gemini",
        "label": "Google (Gemini)",
        "type": "gemini",
        "default_model": "gemini-2.0-flash",
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta",
        "requires_key": True,
        "models": ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"],
    },
    {
        "id": "anthropic",
        "label": "Anthropic (Claude)",
        "type": "anthropic",
        "default_model": "claude-3-5-sonnet-latest",
        "default_base_url": "https://api.anthropic.com/v1",
        "requires_key": True,
        "models": [
            "claude-3-5-sonnet-latest",
            "claude-3-5-haiku-latest",
            "claude-sonnet-4-20250514",
        ],
    },
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "type": "openai",
        "default_model": "openai/gpt-4o-mini",
        "default_base_url": "https://openrouter.ai/api/v1",
        "requires_key": True,
        "models": [
            "openai/gpt-4o-mini",
            "anthropic/claude-3.5-sonnet",
            "google/gemini-2.0-flash-001",
        ],
    },
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "type": "openai",
        "default_model": "deepseek-chat",
        "default_base_url": "https://api.deepseek.com/v1",
        "requires_key": True,
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    {
        "id": "ollama",
        "label": "Ollama (local)",
        "type": "ollama",
        "default_model": "llama3.1",
        "default_base_url": "http://localhost:11434",
        "requires_key": False,
        "models": ["llama3.1", "qwen2.5", "mistral", "phi3"],
    },
    {
        "id": "openai_compatible",
        "label": "OpenAI-compatible (custom)",
        "type": "openai_compatible",
        "default_model": "",
        "default_base_url": "",
        "requires_key": True,
        "models": [],
    },
)

_BY_ID = {item["id"]: item for item in PROVIDER_CATALOG}
_BY_TYPE = {
    "openai": OpenAIProvider,
    "openai_compatible": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
}


def _validate_allowed_host(url: str) -> None:
    """Allowlist opcional via ``MIRROR_LLM_ALLOWED_HOSTS`` (separada por vírgulas)."""
    raw = os.environ.get("MIRROR_LLM_ALLOWED_HOSTS", "").strip()
    if not raw or not url:
        return
    allowed = {item.strip().lower() for item in raw.split(",") if item.strip()}
    host = (urlparse(url).hostname or "").lower()
    if allowed and host not in allowed:
        raise ValueError(f"Host do provedor não permitido: {host or '(vazio)'}.")


def catalog_public() -> list[dict[str, Any]]:
    """Lista de presets segura para o frontend."""
    return [
        {
            "id": item["id"],
            "label": item["label"],
            "type": item["type"],
            "default_model": item["default_model"],
            "default_base_url": item["default_base_url"],
            "requires_key": item["requires_key"],
            "models": list(item["models"]),
        }
        for item in PROVIDER_CATALOG
    ]


def preset(provider_id: str) -> dict[str, Any] | None:
    return _BY_ID.get(str(provider_id or ""))


def models_for(provider_id: str) -> list[str]:
    item = preset(provider_id)
    return list(item["models"]) if item else []


def build_config(data: Mapping[str, Any] | str | None) -> ProviderConfig:
    """Combina payload do cliente com o preset, validando o tipo."""
    if isinstance(data, str):
        data = {"id": data}
    if not isinstance(data, Mapping):
        data = {}
    provider_id = str(data.get("id") or data.get("provider") or "").strip()
    item = preset(provider_id) or {}
    provider_type = str(data.get("type") or item.get("type") or "").strip()
    if provider_type not in PROVIDER_TYPES:
        raise ValueError(
            "Tipo de provedor inválido. Use um de: " + ", ".join(PROVIDER_TYPES) + "."
        )
    base_url = normalize_base_url(
        data.get("base_url"),
        default=str(item.get("default_base_url") or ""),
    )
    model = str(data.get("model") or item.get("default_model") or "").strip()
    config = ProviderConfig.from_dict(
        {
            **dict(data),
            "id": provider_id or provider_type,
            "type": provider_type,
            "label": str(data.get("label") or item.get("label") or provider_type),
            "model": model,
            "base_url": base_url,
        }
    )
    return config


def create_provider(
    config: ProviderConfig | Mapping[str, Any] | str,
    *,
    transport: Any = None,
):
    """Instancia o adaptador adequado para a configuração."""
    if not isinstance(config, ProviderConfig):
        config = build_config(config)
    provider_type = config.type or (preset(config.id) or {}).get("type") or ""
    provider_cls = _BY_TYPE.get(provider_type)
    if provider_cls is None:
        raise ValueError(f"Provedor não suportado: '{config.type or config.id}'.")
    return provider_cls(config, transport=transport)


def validate_provider_config(data: Mapping[str, Any] | str | None) -> ProviderConfig:
    config = build_config(data)
    if not config.model:
        raise ValueError("Informe o modelo do provedor.")
    if config.type in {"openai", "openai_compatible"} and not config.base_url:
        raise ValueError("Informe a URL base do provedor compatível com OpenAI.")
    if config.type in {"anthropic", "gemini"} and not config.base_url:
        raise ValueError("Informe a URL base do provedor.")
    _validate_allowed_host(config.base_url)
    return config


__all__ = [
    "PROVIDER_TYPES",
    "PROVIDER_CATALOG",
    "catalog_public",
    "preset",
    "models_for",
    "build_config",
    "create_provider",
    "validate_provider_config",
    "LLMError",
]
