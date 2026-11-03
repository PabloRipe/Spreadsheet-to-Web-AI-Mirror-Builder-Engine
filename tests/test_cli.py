"""Testes da interface de linha de comando."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from spreadsheet_mirror.cli import main


def test_scan_file(sample_workbook: Path, capsys):
    code = main(["scan", str(sample_workbook)])
    captured = capsys.readouterr()
    assert code == 0
    assert str(sample_workbook) in captured.out
    assert "Total: 1" in captured.out


def test_scan_empty_directory(tmp_path: Path, capsys):
    empty = tmp_path / "vazia"
    empty.mkdir()
    code = main(["scan", str(empty)])
    captured = capsys.readouterr()
    assert code == 0
    assert "Nenhuma planilha encontrada" in captured.out


def test_scan_invalid_path(tmp_path: Path, capsys):
    code = main(["scan", str(tmp_path / "nao-existe")])
    captured = capsys.readouterr()
    assert code == 2
    assert "Erro" in captured.err


def test_process_generates_outputs(sample_workbook: Path, tmp_path: Path, capsys):
    out = tmp_path / "saida"
    code = main(["process", str(sample_workbook), "-o", str(out), "--overwrite", "-v"])
    captured = capsys.readouterr()
    assert code == 0
    project = out / "relatorio"
    assert (project / "mirror.json").exists()
    assert (project / "template.xlsx").exists()
    assert (out / "index.json").exists()
    assert "Projetos gerados: 1" in captured.out
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert index["projects"][0]["slug"] == "relatorio"
    document = json.loads((project / "mirror.json").read_text(encoding="utf-8"))
    assert document["meta"]["source"] == "relatorio.xlsx"


def test_process_json_only(sample_workbook: Path, tmp_path: Path):
    out = tmp_path / "saida"
    code = main(["process", str(sample_workbook), "-o", str(out), "--json-only", "--overwrite"])
    assert code == 0
    project = out / "relatorio"
    assert (project / "mirror.json").exists()
    assert not (project / "template.xlsx").exists()


def test_process_template_only(sample_workbook: Path, tmp_path: Path):
    out = tmp_path / "saida"
    code = main(["process", str(sample_workbook), "-o", str(out), "--template-only", "--overwrite"])
    assert code == 0
    project = out / "relatorio"
    assert not (project / "mirror.json").exists()
    assert (project / "template.xlsx").exists()


def test_process_conflicting_flags(sample_workbook: Path, tmp_path: Path, capsys):
    code = main(
        [
            "process",
            str(sample_workbook),
            "-o",
            str(tmp_path / "saida"),
            "--json-only",
            "--template-only",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "mutuamente exclusivos" in captured.err


def test_process_invalid_path(tmp_path: Path, capsys):
    code = main(["process", str(tmp_path / "nao-existe"), "-o", str(tmp_path / "saida")])
    captured = capsys.readouterr()
    assert code == 2
    assert "Erro" in captured.err


def test_process_without_overwrite_uses_suffix(sample_workbook: Path, tmp_path: Path):
    out = tmp_path / "saida"
    project = out / "relatorio"
    project.mkdir(parents=True)
    code = main(["process", str(sample_workbook), "-o", str(out)])
    assert code == 0
    assert (out / "relatorio-2" / "mirror.json").exists()
    assert (out / "relatorio-2" / "template.xlsx").exists()


def test_process_with_config_override(sample_workbook: Path, tmp_path: Path):
    out = tmp_path / "saida"
    code = main(
        [
            "process",
            str(sample_workbook),
            "-o",
            str(out),
            "--overwrite",
            "--header-rows",
            "2",
            "--no-fixed-if-bold",
        ]
    )
    assert code == 0
    document = json.loads((out / "relatorio" / "mirror.json").read_text(encoding="utf-8"))
    assert document["meta"]["config"]["header_rows"] == [2]
    assert document["meta"]["config"]["fixed_if_bold"] is False


def test_process_recursive(tmp_path: Path, sample_workbook: Path):
    sub = tmp_path / "sub"
    sub.mkdir()
    shutil.copy(sample_workbook, sub / "outro.xlsx")
    out = tmp_path / "saida"
    code = main(["process", str(tmp_path), "-o", str(out), "--recursive", "--overwrite"])
    assert code == 0
    slugs = {path.name for path in out.iterdir() if path.is_dir()}
    assert "relatorio" in slugs
    assert "outro" in slugs


def test_process_duplicate_slugs(tmp_path: Path, sample_workbook: Path):
    sub = tmp_path / "sub"
    sub.mkdir()
    shutil.copy(sample_workbook, sub / "relatorio.xlsx")
    out = tmp_path / "saida"
    code = main(["process", str(tmp_path), "-o", str(out), "--recursive", "--overwrite"])
    assert code == 0
    slugs = sorted(path.name for path in out.iterdir() if path.is_dir())
    assert "relatorio" in slugs
    assert "relatorio-2" in slugs
