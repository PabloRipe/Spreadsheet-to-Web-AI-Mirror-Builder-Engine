"""Testes do modo Prompt-to-Sheet (criação de planilha do zero)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from spreadsheet_mirror.llm.creation import (
    WorkbookSpecError,
    create_project_from_spec,
    validate_spec,
)


def _spec(name: str = "Relatório de Vendas") -> dict:
    return {
        "nome": name,
        "abas": [
            {
                "nome": "Vendas",
                "cor": "#4F81BD",
                "colunas": [{"letra": "A", "largura": 24}, {"letra": "B", "largura": 12}],
                "mesclagens": ["A1:C1"],
                "celulas": [
                    {
                        "ref": "A1",
                        "valor": "Relatório de Vendas",
                        "estilo": {"bold": True, "fill": "#1F497D", "font_color": "#FFFFFF"},
                    },
                    {"ref": "A2", "valor": "Produto", "estilo": {"bold": True, "fill": "#4F81BD"}},
                    {"ref": "B2", "valor": "Quantidade", "estilo": {"bold": True, "fill": "#4F81BD"}},
                    {"ref": "C2", "valor": "Total", "estilo": {"bold": True, "fill": "#4F81BD"}},
                    {"ref": "A3", "valor": "Exemplo"},
                    {"ref": "B3", "valor": 10, "estilo": {"number_format": "0"}},
                    {"ref": "C3", "formula": "=B3*2"},
                ],
            }
        ],
    }


def _mirror_cells(workspace: Path, slug: str):
    document = json.loads((workspace / slug / "mirror.json").read_text(encoding="utf-8"))
    sheet = document["sheets"][0]
    return sheet, {cell["ref"]: cell for cell in sheet["cells"]}


def test_create_project_from_spec_generates_real_xlsx(tmp_path: Path):
    result = create_project_from_spec(_spec(), tmp_path)
    assert result.slug == "relatorio-de-vendas"
    project_dir = tmp_path / result.slug
    assert (project_dir / "mirror.json").exists()
    assert (project_dir / "template.xlsx").exists()
    assert (project_dir / f"{result.slug}.xlsx").exists()

    workbook = load_workbook(project_dir / f"{result.slug}.xlsx")
    sheet = workbook["Vendas"]
    assert sheet["A1"].value == "Relatório de Vendas"
    assert sheet["A1"].font.bold is True
    assert sheet["C3"].value == "=B3*2"
    assert sheet.column_dimensions["A"].width == 24
    assert "A1:C1" in [str(item) for item in sheet.merged_cells.ranges]

    sheet_data, cells = _mirror_cells(tmp_path, result.slug)
    assert sheet_data["name"] == "Vendas"
    assert cells["A2"]["editavel"] is False
    assert cells["A3"]["editavel"] is True
    assert cells["B3"]["editavel"] is True
    assert cells["C3"]["editavel"] is False
    assert cells["C3"]["formula"] == "=B3*2"


def test_duplicate_name_gets_unique_slug(tmp_path: Path):
    first = create_project_from_spec(_spec(), tmp_path)
    second = create_project_from_spec(_spec(), tmp_path)
    assert first.slug == "relatorio-de-vendas"
    assert second.slug == "relatorio-de-vendas-2"


def test_template_clears_editable_values(tmp_path: Path):
    result = create_project_from_spec(_spec(), tmp_path)
    template = load_workbook(tmp_path / result.slug / "template.xlsx")
    assert template["Vendas"]["A3"].value is None
    assert template["Vendas"]["B3"].value is None
    assert template["Vendas"]["C3"].value == "=B3*2"


def test_validate_spec_normalizes_and_rejects_invalid():
    normalized = validate_spec(
        {
            "nome": "X",
            "abas": [
                {
                    "nome": "Aba:Inválida/1",
                    "celulas": [
                        {"ref": "a1", "valor": "ok"},
                        {"ref": "B2", "formula": "SUM(A1:A1)"},
                    ],
                }
            ],
        }
    )
    assert normalized["abas"][0]["nome"] == "Aba_Inválida_1"
    assert normalized["abas"][0]["celulas"][0]["ref"] == "A1"
    assert normalized["abas"][0]["celulas"][1]["formula"] == "=SUM(A1:A1)"

    with pytest.raises(WorkbookSpecError):
        validate_spec({})
    with pytest.raises(WorkbookSpecError):
        validate_spec({"abas": []})
    with pytest.raises(WorkbookSpecError):
        validate_spec({"abas": [{"nome": "A", "celulas": [{"ref": "ZZZZ1", "valor": 1}]}]})
    with pytest.raises(WorkbookSpecError):
        validate_spec({"abas": [{"nome": "A", "celulas": [{"ref": "A201", "valor": 1}]}]})
    with pytest.raises(WorkbookSpecError):
        validate_spec({"abas": [{"nome": "A", "celulas": [{"ref": "A1", "valor": {"x": 1}}]}]})
    with pytest.raises(WorkbookSpecError):
        validate_spec({"abas": [{"nome": "A", "celulas": [{"ref": "A1", "valor": 1, "estilo": {"fill": "nope"}}]}]})
    with pytest.raises(WorkbookSpecError):
        validate_spec({"abas": [{"nome": "A", "celulas": [{"ref": "A1", "valor": 1}]}, {"nome": "a"}]})
    with pytest.raises(WorkbookSpecError):
        validate_spec({"abas": [{"nome": "A", "celulas": [{"ref": "A1", "valor": 1}, {"ref": "A1", "valor": 2}]}]})
    with pytest.raises(WorkbookSpecError):
        validate_spec({"abas": [{"nome": f"A{i}"} for i in range(11)]})
