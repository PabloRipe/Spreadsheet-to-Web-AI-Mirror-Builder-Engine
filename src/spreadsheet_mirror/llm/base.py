"""Tipos e interface comuns aos provedores de LLM.

As credenciais são recebidas em memória a cada requisição e nunca são
persistidas, serializadas ou registradas em log.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping
from urllib.parse import urlparse


class LLMError(Exception):
    """Erro base dos provedores de LLM."""


class AuthError(LLMError):
    """Credencial ausente, inválida ou sem permissão."""


class RateLimitError(LLMError):
    """Provedor recusou a requisição por limite de uso."""


class TimeoutError(LLMError):  # noqa: A001 - nome público definido pelo contrato
    """O provedor demorou mais que o timeout configurado."""


ProviderTimeoutError = TimeoutError


class ProviderError(LLMError):
    """Falha genérica de comunicação ou resposta do provedor."""


def redact_secrets(text: Any, secrets: list[str] | tuple[str, ...] = ()) -> str:
    """Remove credenciais de mensagens antes de expor/logar."""
    value = str(text or "")
    for secret in secrets:
        if secret and len(secret) >= 4:
            value = value.replace(secret, "***")
    return value


def normalize_base_url(value: Any, *, default: str = "") -> str:
    """Valida e normaliza uma URL de base (apenas http/https)."""
    text = str(value or "").strip() or default
    text = text.rstrip("/")
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("A URL do provedor deve usar http:// ou https://.")
    return text


@dataclass
class ValidationResult:
    ok: bool
    provider: str = ""
    detail: str = ""
    models: list[str] = field(default_factory=list)


@dataclass
class ChatRequest:
    messages: list[dict[str, Any]] = field(default_factory=list)
    system_prompt: str = ""
    model: str = ""
    temperature: float | None = None
    max_tokens: int | None = None
    tools: list[dict[str, Any]] | None = None
    response_format: str | None = None
    context: Mapping[str, Any] | None = None


@dataclass
class ChatResponse:
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    provider: str = ""
    model: str = ""
    raw: Any = None


@dataclass
class ChatChunk:
    text: str = ""
    done: bool = False
    usage: dict[str, Any] = field(default_factory=dict)
    raw: Any = None


@dataclass
class ProviderConfig:
    """Configuração de um provedor, montada a partir do navegador."""

    id: str = ""
    type: str = ""
    label: str = ""
    model: str = ""
    base_url: str = ""
    api_key: str | None = None
    enabled: bool = True
    temperature: float = 0.2
    max_tokens: int = 2048
    timeout_s: float = 60.0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "ProviderConfig":
        if not isinstance(data, Mapping):
            return cls()
        return cls(
            id=str(data.get("id") or data.get("provider") or ""),
            type=str(data.get("type") or ""),
            label=str(data.get("label") or ""),
            model=str(data.get("model") or ""),
            base_url=str(data.get("base_url") or ""),
            api_key=(str(data["api_key"]) if data.get("api_key") else None),
            enabled=bool(data.get("enabled", True)),
            temperature=_coerce_float(data.get("temperature"), 0.2),
            max_tokens=_coerce_int(data.get("max_tokens"), 2048),
            timeout_s=_coerce_float(data.get("timeout_s"), 60.0),
        )

    def public_dict(self) -> dict[str, Any]:
        """Representação sem credencial, segura para respostas HTTP."""
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "model": self.model,
            "base_url": self.base_url,
            "enabled": self.enabled,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout_s": self.timeout_s,
            "has_key": bool(self.api_key),
        }


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class LLMProvider(ABC):
    """Interface única para todos os provedores."""

    id: str = ""
    label: str = ""
    requires_key: bool = True

    def __init__(
        self,
        config: ProviderConfig,
        *,
        transport: Any = None,
    ) -> None:
        self.config = config
        self.transport = transport
        if config.id:
            self.id = config.id
        if config.label:
            self.label = config.label

    # -- metadados --------------------------------------------------------
    def default_model(self) -> str:
        return self.config.model

    def require_key(self) -> str:
        key = (self.config.api_key or "").strip()
        if self.requires_key and not key:
            raise AuthError(f"Informe a chave de API do provedor '{self.id}'.")
        return key

    # -- interface --------------------------------------------------------
    def validate(self) -> ValidationResult:
        try:
            models = self.list_models()
        except AuthError as exc:
            return ValidationResult(False, self.id, redact_secrets(exc, [self.config.api_key or ""]))
        except LLMError as exc:
            return ValidationResult(False, self.id, redact_secrets(exc, [self.config.api_key or ""]))
        return ValidationResult(True, self.id, "Conexão validada.", models)

    @abstractmethod
    def list_models(self) -> list[str]:
        """Lista modelos disponíveis para a credencial informada."""

    @abstractmethod
    def chat(self, request: ChatRequest) -> ChatResponse:
        """Executa uma chamada síncrona de chat."""

    def stream(self, request: ChatRequest) -> Iterator[ChatChunk]:
        """Streaming com fallback: provedores podem sobrescrever."""
        response = self.chat(request)
        yield ChatChunk(text=response.text, done=True, usage=response.usage)
