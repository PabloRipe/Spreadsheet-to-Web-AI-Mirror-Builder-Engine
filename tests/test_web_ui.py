"""Testes estáticos da interface de chat e da configuração de IA."""

from __future__ import annotations

from pathlib import Path

from server import create_app

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def test_index_has_chat_and_settings_elements():
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    for element_id in (
        "chat-panel",
        "chat-toggle-button",
        "chat-messages",
        "chat-input",
        "chat-send",
        "chat-context-mode",
        "chat-mode-create",
        "llm-settings-modal",
        "llm-provider",
        "llm-api-key",
        "llm-test-button",
        "llm-save-button",
    ):
        assert f'id="{element_id}"' in html
    assert "sessionStorage" in html
    assert "/static/chat.js" in html


def test_chat_js_never_persists_key_in_settings_object():
    source = (WEB_DIR / "chat.js").read_text(encoding="utf-8")
    assert "KEY_PREFIX" in source
    assert "localStorage" not in source
    assert "writeStorage(SETTINGS_KEY, form)" not in source
    assert "console.log" not in source
    # A chave só é montada para requisições; nunca é escrita no objeto de settings.
    settings_block = source.split("state.settings = {", 1)[1].split("};", 1)[0]
    assert "api_key" not in settings_block


def test_app_js_exposes_chat_bridge():
    source = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert "window.MirrorApp" in source
    assert "applyDraftEdits" in source
    assert "getContext" in source
    assert "refreshAndOpen" in source


def test_web_serves_chat_assets(tmp_path: Path):
    app = create_app(workspace=tmp_path / "workspace", web_dir=WEB_DIR)
    app.config.update(TESTING=True)
    client = app.test_client()
    index = client.get("/")
    assert index.status_code == 200
    assert b"/static/chat.js" in index.data
    chat = client.get("/static/chat.js")
    assert chat.status_code == 200
    assert b"mirrorEngine:llm:settings" in chat.data
