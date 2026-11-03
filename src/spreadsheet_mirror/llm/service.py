"""Orquestração do chat contextual e do modo Prompt-to-Sheet."""

from __future__ import annotations

import json
from typing import Any, Iterator, Mapping

from .base import ChatRequest, LLMProvider, ProviderConfig, redact_secrets
from .chat_store import ChatStore
from .context import ContextBuilder
from .creation import validate_spec
from .prompts import (
    build_create_system_prompt,
    build_edit_system_prompt,
    extract_actions,
    extract_workbook_spec,
)
from .registry import create_provider
from .tools import execute_tool, propose_edits, tool_definitions, validate_edits

MAX_MESSAGE_CHARS = 20_000
MAX_TOOL_ROUNDS = 3


def _provider_factory_default(config: ProviderConfig) -> LLMProvider:
    return create_provider(config)


def _merge_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for item in actions:
        if not isinstance(item, Mapping):
            continue
        aba = str(item.get("aba") or "")
        ref = str(item.get("coordenada") or "").upper()
        if not aba or not ref:
            continue
        merged[(aba, ref)] = {
            "aba": aba,
            "coordenada": ref,
            "novo_valor": item.get("novo_valor"),
        }
    return list(merged.values())


def _tool_result_payload(results: list[dict[str, Any]]) -> str:
    return (
        "Resultados das ferramentas consultadas:\n"
        + json.dumps(results, ensure_ascii=False)
        + "\nAgora responda ao usuário e devolva o bloco final {\"acoes\": [...]}."
    )


class ChatService:
    """Executa chat sobre um ``mirror.json`` com histórico persistido."""

    def __init__(
        self,
        document: Mapping[str, Any],
        *,
        project_slug: str = "",
        draft: Mapping[str, Mapping[str, Any]] | None = None,
        store: ChatStore | None = None,
        max_context_cells: int = 400,
        max_history_messages: int = 40,
        provider_factory: Any = None,
    ) -> None:
        self.document = document if isinstance(document, Mapping) else {}
        self.project_slug = project_slug
        self.draft = draft if isinstance(draft, Mapping) else {}
        self.store = store
        self.max_context_cells = max_context_cells
        self.max_history_messages = max(1, int(max_history_messages or 40))
        self.provider_factory = provider_factory or _provider_factory_default

    # -- helpers ----------------------------------------------------------
    def _make_provider(self, config: ProviderConfig) -> LLMProvider:
        provider = self.provider_factory(config)
        if not isinstance(provider, LLMProvider):
            raise TypeError("A fábrica de provedores deve retornar um LLMProvider.")
        return provider

    def _history(self) -> list[dict[str, Any]]:
        if not self.store or not self.project_slug:
            return []
        stored = self.store.load(self.project_slug)
        messages = stored.get("messages", [])
        trimmed = messages[-self.max_history_messages :]
        result: list[dict[str, Any]] = []
        for item in trimmed:
            if not isinstance(item, Mapping):
                continue
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and isinstance(content, str) and content:
                result.append({"role": role, "content": content})
        return result

    def _build_context(
        self, *, sheet: str | None, selection: str | None, context_mode: str
    ) -> dict[str, Any]:
        return ContextBuilder(
            self.document,
            draft=self.draft,
            max_context_cells=self.max_context_cells,
            project_slug=self.project_slug,
        ).build(context_mode, sheet=sheet, selection=selection)

    def _finalize(
        self,
        *,
        raw_text: str,
        extra_actions: list[dict[str, Any]],
        sheet: str | None,
        context_mode: str,
        usage: Mapping[str, Any] | None,
        provider: str,
        model: str,
    ) -> dict[str, Any]:
        parsed = extract_actions(raw_text)
        actions = _merge_actions(list(parsed["acoes"]) + list(extra_actions))
        validated = validate_edits(self.document, actions, default_sheet=sheet or "")
        reply = parsed["reply"] or raw_text.strip()
        return {
            "reply": reply,
            "acoes": actions,
            "aplicaveis": validated["aplicaveis"],
            "rejeitadas": validated["rejeitadas"],
            "usage": dict(usage or {}),
            "provider": provider,
            "model": model,
            "sheet": sheet,
            "context_mode": context_mode,
            "errors": list(parsed.get("errors", [])),
        }

    def _persist(self, message: str, result: Mapping[str, Any]) -> None:
        if not self.store or not self.project_slug:
            return
        self.store.append_many(
            self.project_slug,
            [
                {"role": "user", "content": message},
                {
                    "role": "assistant",
                    "content": result.get("reply", ""),
                    "provider": result.get("provider"),
                    "model": result.get("model"),
                    "actions": result.get("acoes", []),
                },
            ],
        )

    # -- chat -------------------------------------------------------------
    def chat(
        self,
        *,
        message: str,
        provider_config: ProviderConfig | Mapping[str, Any] | str,
        sheet: str | None = None,
        selection: str | None = None,
        context_mode: str = "sheet",
        provider: LLMProvider | None = None,
    ) -> dict[str, Any]:
        text = str(message or "").strip()
        if not text:
            raise ValueError("Informe uma mensagem para o chat.")
        if len(text) > MAX_MESSAGE_CHARS:
            raise ValueError(f"A mensagem excede {MAX_MESSAGE_CHARS} caracteres.")

        config = (
            provider_config
            if isinstance(provider_config, ProviderConfig)
            else ProviderConfig.from_dict(provider_config)
        )
        active = provider or self._make_provider(config)
        context = self._build_context(sheet=sheet, selection=selection, context_mode=context_mode)
        system_prompt = build_edit_system_prompt(context)
        messages = self._history()
        messages.append({"role": "user", "content": text})

        request = ChatRequest(
            messages=messages,
            system_prompt=system_prompt,
            model=config.model,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            tools=tool_definitions(config.type),
        )

        extra_actions: list[dict[str, Any]] = []
        response = active.chat(request)
        rounds = 0
        while response.tool_calls and rounds < MAX_TOOL_ROUNDS:
            rounds += 1
            results: list[dict[str, Any]] = []
            for call in response.tool_calls:
                name = str(call.get("name") or "")
                arguments = call.get("arguments")
                if not isinstance(arguments, Mapping):
                    arguments = {}
                if name == "propose_edits":
                    proposal = propose_edits(
                        self.document,
                        str(arguments.get("sheet") or sheet or ""),
                        arguments.get("edits"),
                    )
                    normalized = proposal.get("normalizado", {})
                    for aba, cells in normalized.items():
                        for ref, value in cells.items():
                            extra_actions.append(
                                {"aba": aba, "coordenada": ref, "novo_valor": value}
                            )
                    results.append({"tool": name, "result": proposal})
                    continue
                try:
                    results.append(
                        {"tool": name, "result": execute_tool(name, arguments, self.document)}
                    )
                except (ValueError, KeyError) as exc:
                    results.append({"tool": name, "error": str(exc)})
            request.messages.append({"role": "assistant", "content": response.text or ""})
            request.messages.append({"role": "user", "content": _tool_result_payload(results)})
            request.tools = None
            response = active.chat(request)

        result = self._finalize(
            raw_text=response.text,
            extra_actions=extra_actions,
            sheet=sheet,
            context_mode=context_mode,
            usage=response.usage,
            provider=response.provider or config.id,
            model=response.model or config.model,
        )
        self._persist(text, result)
        return result

    # -- streaming --------------------------------------------------------
    def stream_chat(
        self,
        *,
        message: str,
        provider_config: ProviderConfig | Mapping[str, Any] | str,
        sheet: str | None = None,
        selection: str | None = None,
        context_mode: str = "sheet",
        provider: LLMProvider | None = None,
    ) -> Iterator[dict[str, Any]]:
        text = str(message or "").strip()
        if not text:
            yield {"type": "error", "error": "Informe uma mensagem para o chat."}
            return
        if len(text) > MAX_MESSAGE_CHARS:
            yield {"type": "error", "error": f"A mensagem excede {MAX_MESSAGE_CHARS} caracteres."}
            return

        config = (
            provider_config
            if isinstance(provider_config, ProviderConfig)
            else ProviderConfig.from_dict(provider_config)
        )
        try:
            active = provider or self._make_provider(config)
            context = self._build_context(
                sheet=sheet, selection=selection, context_mode=context_mode
            )
            messages = self._history()
            messages.append({"role": "user", "content": text})
            request = ChatRequest(
                messages=messages,
                system_prompt=build_edit_system_prompt(context),
                model=config.model,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
            )
            yield {
                "type": "meta",
                "provider": config.id,
                "model": config.model,
                "sheet": sheet,
                "context_mode": context_mode,
            }
            accumulated: list[str] = []
            usage: dict[str, Any] = {}
            model = config.model
            for chunk in active.stream(request):
                if chunk.text:
                    accumulated.append(chunk.text)
                    yield {"type": "delta", "text": chunk.text}
                if chunk.done:
                    usage = dict(chunk.usage or {})
                    break
            result = self._finalize(
                raw_text="".join(accumulated),
                extra_actions=[],
                sheet=sheet,
                context_mode=context_mode,
                usage=usage,
                provider=config.id,
                model=model,
            )
            self._persist(text, result)
            yield {"type": "done", **result}
        except Exception as exc:  # noqa: BLE001 - erro devolvido como evento SSE
            yield {
                "type": "error",
                "error": redact_secrets(exc, [getattr(config, "api_key", "") or ""]),
            }

    # -- prompt-to-sheet --------------------------------------------------
    def generate_workbook_spec(
        self,
        prompt: str,
        provider_config: ProviderConfig | Mapping[str, Any] | str,
        *,
        provider: LLMProvider | None = None,
    ) -> dict[str, Any]:
        text = str(prompt or "").strip()
        if not text:
            raise ValueError("Descreva a planilha que deve ser criada.")
        if len(text) > MAX_MESSAGE_CHARS:
            raise ValueError(f"O pedido excede {MAX_MESSAGE_CHARS} caracteres.")
        config = (
            provider_config
            if isinstance(provider_config, ProviderConfig)
            else ProviderConfig.from_dict(provider_config)
        )
        active = provider or self._make_provider(config)
        request = ChatRequest(
            messages=[{"role": "user", "content": text}],
            system_prompt=build_create_system_prompt(),
            model=config.model,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            response_format="json",
        )
        response = active.chat(request)
        spec = extract_workbook_spec(response.text)
        normalized = validate_spec(spec)
        return {
            "spec": normalized,
            "usage": dict(response.usage or {}),
            "provider": response.provider or config.id,
            "model": response.model or config.model,
        }


__all__ = ["ChatService", "MAX_MESSAGE_CHARS"]
