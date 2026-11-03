"""Testes do histórico de chat por projeto."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spreadsheet_mirror.llm.chat_store import ChatStore, public_history


def test_append_load_and_clear(tmp_path: Path):
    store = ChatStore(tmp_path)
    assert store.load("projeto")["messages"] == []
    store.append("projeto", {"role": "user", "content": "Olá"})
    store.append("projeto", {"role": "assistant", "content": "Oi!", "provider": "fake"})
    document = store.load("projeto")
    assert [item["content"] for item in document["messages"]] == ["Olá", "Oi!"]
    assert document["messages"][0]["created_at"]
    assert document["schema_version"] == "1.0.0"
    path = tmp_path / ".chats" / "projeto.json"
    assert path.exists()
    assert "api_key" not in path.read_text(encoding="utf-8")

    store.clear("projeto")
    assert not path.exists()
    store.clear("projeto")


def test_store_trims_messages(tmp_path: Path):
    store = ChatStore(tmp_path, max_messages=3)
    for index in range(6):
        store.append("p", {"role": "user", "content": f"m{index}"})
    messages = store.load("p")["messages"]
    assert [item["content"] for item in messages] == ["m3", "m4", "m5"]


def test_store_removes_secret_fields(tmp_path: Path):
    store = ChatStore(tmp_path)
    store.append(
        "p",
        {
            "role": "assistant",
            "content": "ok",
            "metadata": {"api_key": "sk-secret", "nested": {"token": "abc", "keep": 1}},
        },
    )
    text = (tmp_path / ".chats" / "p.json").read_text(encoding="utf-8")
    assert "sk-secret" not in text
    assert '"keep": 1' in text


def test_invalid_slug_and_corrupt_file(tmp_path: Path):
    store = ChatStore(tmp_path)
    with pytest.raises(ValueError):
        store.load("../escape")
    path = tmp_path / ".chats"
    path.mkdir()
    (path / "p.json").write_text("{inválido", encoding="utf-8")
    assert store.load("p")["messages"] == []


def test_append_many_and_public_history_copy(tmp_path: Path):
    store = ChatStore(tmp_path)
    store.append_many("p", [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}])
    document = store.load("p")
    published = public_history(document)
    published["messages"].clear()
    assert document["messages"]
    data = json.loads((tmp_path / ".chats" / "p.json").read_text(encoding="utf-8"))
    assert len(data["messages"]) == 2
