"""Camada Multi-LLM do Spreadsheet Mirror Engine.

As credenciais são sempre fornecidas em memória pelo cliente web e nunca são
persistidas pelo servidor.
"""

from __future__ import annotations

from .base import (
    AuthError,
    ChatChunk,
    ChatRequest,
    ChatResponse,
    LLMError,
    LLMProvider,
    ProviderConfig,
    ProviderError,
    ProviderTimeoutError,
    RateLimitError,
    TimeoutError,
    ValidationResult,
)
from .registry import (
    PROVIDER_CATALOG,
    PROVIDER_TYPES,
    build_config,
    catalog_public,
    create_provider,
    models_for,
    preset,
    validate_provider_config,
)

__all__ = [
    "AuthError",
    "ChatChunk",
    "ChatRequest",
    "ChatResponse",
    "LLMError",
    "LLMProvider",
    "ProviderConfig",
    "ProviderError",
    "ProviderTimeoutError",
    "RateLimitError",
    "TimeoutError",
    "ValidationResult",
    "PROVIDER_CATALOG",
    "PROVIDER_TYPES",
    "build_config",
    "catalog_public",
    "create_provider",
    "models_for",
    "preset",
    "validate_provider_config",
]
