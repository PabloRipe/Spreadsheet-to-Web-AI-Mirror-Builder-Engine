"""Testes de descoberta e leitura de planilhas."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from spreadsheet_mirror.config import MirrorConfig
from spreadsheet_mirror.reader import (
    SpreadsheetError,
    find_spreadsheets,
    load_workbook_data,
)


def test_find_single_file(sample_workbook: Path):
    found = find_spreadsheets(sample_workbook)
    assert found == [sample_workbook]


def test_find_directory_skips_temp_and_non_recursive(tmp_path: Path, sample_workbook: Path):
    sub = tmp_path / "sub"
    sub.mkdir()
    shutil.copy(sample_workbook, sub / "outro.xlsx")
    (tmp_path / "~$bloqueado.xlsx").write_bytes(b"")
    found = find_spreadsheets(tmp_path)
    assert sample_workbook in found
    assert sub / "outro.xlsx" not in found
    assert all(not path.name.startswith("~$") for path in found)


def test_find_directory_recursive(tmp_path: Path, sample_workbook: Path):
    sub = tmp_path / "sub"
    sub.mkdir()
    nested = sub / "outro.xlsx"
    shutil.copy(sample_workbook, nested)
    found = find_spreadsheets(tmp_path, MirrorConfig(recursive=True))
    assert sample_workbook in found
    assert nested in found


def test_find_unsupported_extension(tmp_path: Path):
    file_path = tmp_path / "arquivo.txt"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(SpreadsheetError):
        find_spreadsheets(file_path)


def test_find_missing_path(tmp_path: Path):
    with pytest.raises(SpreadsheetError):
        find_spreadsheets(tmp_path / "nao-existe.xlsx")


def test_load_workbook_data(sample_workbook: Path):
    data = load_workbook_data(sample_workbook)
    assert data.wb_formulas is not None
    assert data.wb_values is not None
    assert data.theme.source == "workbook"
    assert data.theme.colors["accent1"] == "#4F81BD"
    assert data.wb_formulas["Vendas"]["D3"].value == "=B3*C3"
    assert data.wb_values["Vendas"]["D3"].value is None


def test_load_workbook_without_cached_values(sample_workbook: Path):
    data = load_workbook_data(sample_workbook, MirrorConfig(read_cached_values=False))
    assert data.wb_values is None
    assert data.wb_formulas["Vendas"]["D3"].value == "=B3*C3"


def test_load_workbook_cached_values(cached_workbook: Path):
    data = load_workbook_data(cached_workbook)
    assert data.wb_values is not None
    assert data.wb_values["Calculos"]["A3"].value == 5
    assert data.wb_values["Calculos"]["B1"].value == 4
    assert data.wb_formulas["Calculos"]["A3"].value == "=SUM(A1:A2)"


def test_theme_override_from_config(sample_workbook: Path):
    cfg = MirrorConfig(theme_colors={"accent1": "#123456"})
    data = load_workbook_data(sample_workbook, cfg)
    assert data.theme.source == "config"
    assert data.theme.colors["accent1"] == "#123456"


def test_invalid_xlsx_raises(tmp_path: Path):
    broken = tmp_path / "quebrado.xlsx"
    broken.write_text("isto não é um xlsx", encoding="utf-8")
    with pytest.raises(SpreadsheetError):
        load_workbook_data(broken)
