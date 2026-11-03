"""Testes de integração Flask da camada LLM/chat."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import server
from server import create_app
from spreadsheet_mirror.llm.base import ChatChunk, ChatRequest, ChatResponse, LLMProvider

WEB_DIR = Path(server.__file__).resolve().parent / "web"
PROVIDER = {"id": "openai", "type": "openai", "model": "fake-model", "api_key": "sk-very-secret"}


class ApiFakeProvider(LLMProvider):
    id = "fake"
    label = "Fake"
    requires_key = False

    def __init__(self, config, responses=None, stream_text: str = "") -> None:
        super().__init__(config)
        self.responses = list(responses or [])
        self.stream_text = stream_text
        self.requests: list[ChatRequest] = []

    def list_models(self) -> list[str]:
        return ["fake-model", "fake-model-2"]

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        if self.responses:
            return self.responses.pop(0)
        return ChatResponse(text='{"acoes": []}', provider="fake", model="fake-model")

    def stream(self, request: ChatRequest):
        self.requests.append(request)
        for part in self.stream_text.split("|"):
            yield ChatChunk(text=part)
        yield ChatChunk(done=True, usage={"total_tokens": 3})


@pytest.fixture
def web_app(tmp_path: Path):
    app = create_app(workspace=tmp_path / "workspace", web_dir=WEB_DIR)
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def client(web_app):
    return web_app.test_client()


def _install_fake(app, responses=None, stream_text: str = "") -> None:
    app.config["LLM_PROVIDER_FACTORY"] = lambda config: ApiFakeProvider(
        config, responses=responses, stream_text=stream_text
    )


def _upload(client, sample_workbook: Path) -> str:
    with open(sample_workbook, "rb") as handle:
        response = client.post(
            "/api/upload",
            data={"file": (handle, "relatorio.xlsx")},
            content_type="multipart/form-data",
        )
    assert response.status_code == 201
    return response.get_json()["project"]["slug"]


def test_llm_providers_and_models(client):
    response = client.get("/api/llm/providers")
    assert response.status_code == 200
    payload = response.get_json()
    ids = {item["id"] for item in payload["providers"]}
    assert {"openai", "gemini", "anthropic", "openrouter", "deepseek", "ollama"} <= ids
    assert payload["default_provider"] == "openai"

    models = client.get("/api/llm/models?provider=ollama")
    assert models.status_code == 200
    assert "llama3.1" in models.get_json()["models"]
    assert client.get("/api/llm/models?provider=nope").status_code == 400


def test_llm_test_never_echoes_key(client, web_app):
    _install_fake(web_app)
    response = client.post("/api/llm/test", json={"provider": PROVIDER})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["models"] == ["fake-model", "fake-model-2"]
    assert payload["provider"]["has_key"] is True
    assert "sk-very-secret" not in response.get_data(as_text=True)


def test_llm_test_invalid_payload(client):
    assert client.post("/api/llm/test", json={"provider": {"id": "x", "type": "nope"}}).status_code == 400
    response = client.post(
        "/api/llm/test",
        json={"provider": {**PROVIDER, "base_url": "file:///etc/passwd"}},
    )
    assert response.status_code == 400


def test_chat_api_and_history(client, web_app, sample_workbook: Path):
    slug = _upload(client, sample_workbook)
    _install_fake(
        web_app,
        responses=[
            ChatResponse(
                text=(
                    "Preenchi os valores.\n"
                    '{"acoes": [{"aba": "Vendas", "coordenada": "B3", "novo_valor": 7},'
                    ' {"aba": "Vendas", "coordenada": "A1", "novo_valor": "hack"}]}'
                ),
                usage={"total_tokens": 12},
                provider="fake",
                model="fake-model",
            )
        ],
    )
    response = client.post(
        f"/api/projects/{slug}/chat",
        json={
            "message": "Preencha B3 com 7",
            "sheet": "Vendas",
            "context_mode": "sheet",
            "draft": {"Vendas": {"C3": "2.5"}},
            "provider": PROVIDER,
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["aplicaveis"] == {"Vendas": {"B3": 7}}
    assert payload["rejeitadas"][0]["motivo"] == "celula_fixa"
    assert payload["usage"]["total_tokens"] == 12
    assert "sk-very-secret" not in response.get_data(as_text=True)

    history = client.get(f"/api/projects/{slug}/chat/history")
    assert history.status_code == 200
    messages = history.get_json()["messages"]
    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert "sk-very-secret" not in history.get_data(as_text=True)

    cleared = client.delete(f"/api/projects/{slug}/chat/history")
    assert cleared.status_code == 200
    assert client.get(f"/api/projects/{slug}/chat/history").get_json()["messages"] == []


def test_chat_api_validation_errors(client, web_app, sample_workbook: Path):
    slug = _upload(client, sample_workbook)
    _install_fake(web_app)
    assert client.post(f"/api/projects/{slug}/chat", json={"provider": PROVIDER}).status_code == 400
    assert (
        client.post(f"/api/projects/{slug}/chat", json={"message": "oi", "provider": {"id": "x"}}).status_code
        == 400
    )
    assert client.post("/api/projects/inexistente/chat", json={"message": "oi"}).status_code == 404


def test_chat_stream_sse(client, web_app, sample_workbook: Path):
    slug = _upload(client, sample_workbook)
    _install_fake(
        web_app,
        stream_text='Vou atualizar.|{"acoes": [{"aba": "Vendas", "coordenada": "B3", "novo_valor": 9}]}',
    )
    response = client.post(
        f"/api/projects/{slug}/chat/stream",
        json={"message": "Atualize", "sheet": "Vendas", "provider": PROVIDER},
        buffered=True,
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["Content-Type"]
    body = response.get_data(as_text=True)
    assert '"type": "meta"' in body
    assert '"type": "delta"' in body
    assert '"type": "done"' in body
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    done = [event for event in events if event["type"] == "done"][0]
    assert done["aplicaveis"] == {"Vendas": {"B3": 9}}
    assert "sk-very-secret" not in body


def test_chat_apply_validates_and_coerces(client, sample_workbook: Path):
    slug = _upload(client, sample_workbook)
    response = client.post(
        f"/api/projects/{slug}/chat/apply",
        json={
            "sheet": "Vendas",
            "edits": [
                {"ref": "B3", "value": "7"},
                {"ref": "C3", "value": "2.5"},
                {"ref": "A1", "value": "x"},
                {"ref": "B1", "value": "x"},
            ],
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data"] == {"Vendas": {"B3": 7, "C3": 2.5}}
    assert {item["motivo"] for item in payload["rejeitadas"]} == {"celula_fixa", "mesclada_nao_ancora"}

    assert client.post(f"/api/projects/{slug}/chat/apply", json={}).status_code == 400


def test_create_project_with_spec(client, tmp_path: Path):
    spec = {
        "nome": "Planilha Criada",
        "abas": [
            {
                "nome": "Dados",
                "celulas": [
                    {"ref": "A1", "valor": "Nome", "estilo": {"bold": True, "fill": "#4F81BD"}},
                    {"ref": "A2", "valor": "Exemplo"},
                ],
            }
        ],
    }
    response = client.post("/api/projects/create", json={"spec": spec})
    assert response.status_code == 201, response.get_data(as_text=True)
    payload = response.get_json()
    slug = payload["project"]["slug"]
    assert slug == "planilha-criada"
    assert (Path(client.application.config["WORKSPACE"]) / slug / "mirror.json").exists()

    projects = client.get("/api/projects").get_json()["projects"]
    assert any(item["slug"] == slug for item in projects)

    invalid = client.post("/api/projects/create", json={"spec": {"abas": []}})
    assert invalid.status_code == 400


def test_create_project_from_prompt_uses_provider(client, web_app):
    _install_fake(
        web_app,
        responses=[
            ChatResponse(
                text='```json\n{"nome": "Gerada", "abas": [{"nome": "A", "celulas": [{"ref": "A1", "valor": "X"}]}]}\n```',
                provider="fake",
                model="fake-model",
                usage={"total_tokens": 5},
            )
        ],
    )
    response = client.post(
        "/api/projects/create",
        json={"prompt": "Crie uma planilha simples", "provider": PROVIDER},
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["project"]["slug"] == "gerada"
    assert payload["provider"] == "fake"
    assert "sk-very-secret" not in response.get_data(as_text=True)

    assert (
        client.post("/api/projects/create", json={"provider": PROVIDER}).status_code
        == 400
    )
