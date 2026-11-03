"""Testes da camada web Flask."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

import server
from server import _coerce_value, _safe_download_name, _safe_upload_name, create_app

WEB_DIR = Path(server.__file__).resolve().parent / "web"


@pytest.fixture
def web_app(tmp_path: Path):
    workspace = tmp_path / "workspace"
    app = create_app(workspace=workspace, web_dir=WEB_DIR)
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def client(web_app):
    return web_app.test_client()


def _upload(client, sample_workbook: Path, filename: str = "relatorio.xlsx"):
    with open(sample_workbook, "rb") as handle:
        response = client.post(
            "/api/upload",
            data={"file": (handle, filename)},
            content_type="multipart/form-data",
        )
    return response


def _load_response_workbook(response):
    return load_workbook(io.BytesIO(response.data))


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["projects"] == 0


def test_index_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Spreadsheet Mirror" in response.data


def test_projects_empty(client):
    response = client.get("/api/projects")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["projects"] == []
    assert payload["workspace"]


def test_upload_requires_file(client):
    response = client.post("/api/upload", data={}, content_type="multipart/form-data")
    assert response.status_code == 400
    assert "Nenhum arquivo" in response.get_json()["error"]


def test_upload_rejects_non_xlsx(client, sample_workbook: Path):
    with open(sample_workbook, "rb") as handle:
        response = client.post(
            "/api/upload",
            data={"file": (handle, "planilha.txt")},
            content_type="multipart/form-data",
        )
    assert response.status_code == 400
    assert "xlsx" in response.get_json()["error"]


def test_upload_and_list_projects(client, sample_workbook: Path):
    response = _upload(client, sample_workbook)
    assert response.status_code == 201, response.get_data(as_text=True)
    payload = response.get_json()
    slug = payload["project"]["slug"]
    assert slug == "relatorio"
    assert payload["project"]["source_name"] == "relatorio.xlsx"

    projects_response = client.get("/api/projects")
    projects = projects_response.get_json()["projects"]
    assert len(projects) == 1
    assert projects[0]["slug"] == slug
    assert projects[0]["stats"]["sheets"] == 2

    mirror_response = client.get(f"/api/projects/{slug}/mirror")
    assert mirror_response.status_code == 200
    document = mirror_response.get_json()
    assert document["meta"]["source"] == "relatorio.xlsx"
    assert [sheet["name"] for sheet in document["sheets"]] == ["Vendas", "Entradas"]


def test_upload_duplicate_names_creates_unique_slugs(client, sample_workbook: Path):
    first = _upload(client, sample_workbook)
    second = _upload(client, sample_workbook)
    assert first.status_code == 201
    assert second.status_code == 201
    first_slug = first.get_json()["project"]["slug"]
    second_slug = second.get_json()["project"]["slug"]
    assert first_slug == "relatorio"
    assert second_slug == "relatorio-2"


def test_export_generates_xlsx_with_values(client, sample_workbook: Path):
    upload = _upload(client, sample_workbook)
    slug = upload.get_json()["project"]["slug"]

    response = client.post(
        f"/api/projects/{slug}/export",
        json={
            "data": {
                "Vendas": {"B3": "7", "C3": "2.5", "B7": "123"},
                "Entradas": {"A2": "Maria", "B2": "250"},
            },
            "filename": "resultado.xlsx",
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert "attachment" in response.headers.get("Content-Disposition", "")

    workbook = _load_response_workbook(response)
    sheet = workbook["Vendas"]
    assert sheet["B3"].value == 7
    assert sheet["C3"].value == 2.5
    assert sheet["B7"].value == 123
    assert sheet["D3"].value == "=B3*C3"
    assert sheet["D7"].value == "=SUM(D3:D5)"
    assert sheet["A1"].value == "Relatório de Vendas"
    assert sheet["A2"].value == "Produto"
    assert sheet["A2"].font.bold is True
    assert sheet["A2"].fill.fill_type == "solid"
    assert "A1:D1" in [str(item) for item in sheet.merged_cells.ranges]

    entries = workbook["Entradas"]
    assert entries["A2"].value == "Maria"
    assert entries["B2"].value == 250
    assert entries["A1"].value == "Nome"


def test_export_ignores_fixed_and_covered_cells(client, sample_workbook: Path):
    upload = _upload(client, sample_workbook)
    slug = upload.get_json()["project"]["slug"]

    response = client.post(
        f"/api/projects/{slug}/export",
        json={
            "data": {
                "Vendas": {
                    "A1": "TENTATIVA",
                    "B1": "TENTATIVA",
                    "A2": "TENTATIVA",
                    "B3": "10",
                }
            }
        },
    )
    assert response.status_code == 200
    workbook = _load_response_workbook(response)
    sheet = workbook["Vendas"]
    assert sheet["A1"].value == "Relatório de Vendas"
    assert sheet["B1"].value is None
    assert sheet["A2"].value == "Produto"
    assert sheet["B3"].value == 10


def test_export_ignores_unknown_sheets_and_refs(client, sample_workbook: Path):
    upload = _upload(client, sample_workbook)
    slug = upload.get_json()["project"]["slug"]

    response = client.post(
        f"/api/projects/{slug}/export",
        json={
            "data": {
                "Inexistente": {"A1": "x"},
                "Vendas": {"ZZZ": "x", "B3": "3"},
            }
        },
    )
    assert response.status_code == 200
    workbook = _load_response_workbook(response)
    assert workbook["Vendas"]["B3"].value == 3


def test_export_without_data(client, sample_workbook: Path):
    upload = _upload(client, sample_workbook)
    slug = upload.get_json()["project"]["slug"]
    response = client.post(f"/api/projects/{slug}/export", json={"data": {}})
    assert response.status_code == 200
    workbook = _load_response_workbook(response)
    assert workbook["Vendas"]["B3"].value is None
    assert workbook["Vendas"]["D3"].value == "=B3*C3"


def test_export_invalid_json(client, sample_workbook: Path):
    upload = _upload(client, sample_workbook)
    slug = upload.get_json()["project"]["slug"]
    response = client.post(
        f"/api/projects/{slug}/export",
        data="não é json",
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "JSON" in response.get_json()["error"]


def test_export_unknown_project(client):
    response = client.post("/api/projects/inexistente/export", json={"data": {}})
    assert response.status_code == 404
    assert "não encontrado" in response.get_json()["error"]


def test_unknown_project_mirror(client):
    response = client.get("/api/projects/inexistente/mirror")
    assert response.status_code == 404


def test_invalid_slug(client):
    response = client.get("/api/projects/slug%20invalido/mirror")
    assert response.status_code == 400


def test_projects_scan_without_index(client, web_app, sample_workbook: Path):
    _upload(client, sample_workbook)
    workspace = Path(web_app.config["WORKSPACE"])
    index = workspace / "index.json"
    if index.exists():
        index.unlink()
    response = client.get("/api/projects")
    assert response.status_code == 200
    projects = response.get_json()["projects"]
    assert len(projects) == 1
    assert projects[0]["slug"] == "relatorio"


def test_coerce_value_types():
    cell_number = {"value_type": "number", "style": "s0"}
    style = {"number_format": "General"}
    assert _coerce_value("1234", cell_number, style) == 1234
    assert _coerce_value("1234,56", cell_number, style) == 1234.56
    assert _coerce_value("1.234,56", cell_number, style) == 1234.56
    assert _coerce_value("", cell_number, style) is None
    assert _coerce_value(None, cell_number, style) is None

    cell_bool = {"value_type": "boolean", "style": "s0"}
    assert _coerce_value("sim", cell_bool, style) is True
    assert _coerce_value("não", cell_bool, style) is False
    assert _coerce_value("talvez", cell_bool, style) == "talvez"

    cell_date = {"value_type": "datetime", "style": "s0"}
    date_style = {"number_format": "dd/mm/yyyy"}
    result = _coerce_value("15/01/2024", cell_date, date_style)
    assert result.year == 2024
    assert result.month == 1
    assert result.day == 15

    cell_duration = {"value_type": "duration", "style": "s0"}
    duration = _coerce_value("02:30:00", cell_duration, style)
    assert duration.total_seconds() == 9000


def test_safe_upload_name():
    assert _safe_upload_name("relatório final.xlsx") == "relatório final.xlsx"
    assert _safe_upload_name("../../etc/passwd.xlsx") == "passwd.xlsx"
    assert _safe_upload_name("planilha (1).xlsx") == "planilha (1).xlsx"
    assert _safe_upload_name("CON.xlsx") == "_CON.xlsx"
    assert _safe_upload_name("arquivo.txt") == "arquivo.txt.xlsx"
    assert _safe_upload_name("") == "planilha.xlsx"
    long_name = "a" * 200 + ".xlsx"
    safe = _safe_upload_name(long_name)
    assert safe.endswith(".xlsx")
    assert len(safe) <= 115


def test_safe_download_name():
    assert _safe_download_name("resultado.xlsx", "fallback.xlsx") == "resultado.xlsx"
    assert _safe_download_name("", "fallback.xlsx") == "planilha.xlsx"
    assert _safe_download_name("resultado", "fallback.xlsx") == "resultado.xlsx"
