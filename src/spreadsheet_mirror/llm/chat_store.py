"""Persistência local do histórico de chat por projeto."""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "1.0.0"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SECRET_KEYS = {"api_key", "apikey", "authorization", "password", "secret", "token"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize(value: Any) -> Any:
    """Remove recursivamente campos que possam conter credenciais."""
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize(item)
            for key, item in value.items()
            if str(key).lower() not in SECRET_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    return value


class ChatStore:
    """Histórico JSON em ``<workspace>/.chats/<slug>.json``."""

    def __init__(self, workspace: str | Path, max_messages: int = 40) -> None:
        self.workspace = Path(workspace)
        self.max_messages = max(1, int(max_messages or 40))

    def _dir(self) -> Path:
        path = self.workspace / ".chats"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def path_for(self, slug: str) -> Path:
        if not SLUG_RE.fullmatch(str(slug or "")):
            raise ValueError("Identificador de projeto inválido.")
        return self._dir() / f"{slug}.json"

    def load(self, slug: str) -> dict[str, Any]:
        path = self.path_for(slug)
        if not path.exists():
            return {
                "schema_version": SCHEMA_VERSION,
                "project_slug": slug,
                "messages": [],
            }
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        messages = payload.get("messages") if isinstance(payload, dict) else []
        return {
            "schema_version": SCHEMA_VERSION,
            "project_slug": slug,
            "messages": [
                _sanitize(item)
                for item in (messages if isinstance(messages, list) else [])
                if isinstance(item, Mapping)
            ],
        }

    def append(self, slug: str, message: Mapping[str, Any]) -> dict[str, Any]:
        document = self.load(slug)
        entry = _sanitize(dict(message))
        entry.setdefault("created_at", _now())
        document["messages"].append(entry)
        if len(document["messages"]) > self.max_messages:
            document["messages"] = document["messages"][-self.max_messages :]
        self._write(slug, document)
        return document

    def append_many(self, slug: str, messages: list[Mapping[str, Any]]) -> dict[str, Any]:
        document = self.load(slug)
        for message in messages:
            entry = _sanitize(dict(message))
            entry.setdefault("created_at", _now())
            document["messages"].append(entry)
        if len(document["messages"]) > self.max_messages:
            document["messages"] = document["messages"][-self.max_messages :]
        self._write(slug, document)
        return document

    def clear(self, slug: str) -> None:
        path = self.path_for(slug)
        try:
            path.unlink()
        except FileNotFoundError:
            return

    def _write(self, slug: str, document: Mapping[str, Any]) -> None:
        path = self.path_for(slug)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "project_slug": slug,
            "messages": list(document.get("messages", [])),
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        handle, temp_name = tempfile.mkstemp(prefix=".chat_", suffix=".json", dir=str(path.parent))
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(text)
            os.replace(temp_name, path)
        finally:
            try:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
            except OSError:
                pass


def public_history(document: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": document.get("schema_version", SCHEMA_VERSION),
        "project_slug": document.get("project_slug"),
        "messages": copy.deepcopy(list(document.get("messages", []))),
    }
