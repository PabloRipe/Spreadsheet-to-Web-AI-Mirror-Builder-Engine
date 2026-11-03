"""Descoberta e leitura de arquivos de planilha."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.workbook.workbook import Workbook

from .colors import ThemePalette, normalize_hex
from .config import MirrorConfig


class SpreadsheetError(Exception):
    """Erro ao localizar ou ler um arquivo de planilha."""


@dataclass
class WorkbookData:
    path: Path
    wb_formulas: Workbook
    theme: ThemePalette
    wb_values: Workbook | None = None
    warnings: list[str] = field(default_factory=list)


def find_spreadsheets(path: str | Path, config: MirrorConfig | None = None) -> list[Path]:
    """Localiza arquivos com as extensões configuradas.

    Aceita um arquivo único ou um diretório. Arquivos temporários do Excel
    (``~$*.xlsx``) são ignorados.
    """
    cfg = config or MirrorConfig()
    target = Path(path)
    if not target.exists():
        raise SpreadsheetError(f"Caminho não encontrado: {target}")

    extensions = {ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in cfg.extensions}

    if target.is_file():
        if target.suffix.lower() not in extensions:
            raise SpreadsheetError(
                f"Extensão não suportada: {target.suffix}. Esperado: {', '.join(sorted(extensions))}"
            )
        return [target]

    pattern = "**/*" if cfg.recursive else "*"
    found: list[Path] = []
    for candidate in sorted(target.glob(pattern)):
        if not candidate.is_file():
            continue
        if candidate.name.startswith("~$"):
            continue
        if candidate.suffix.lower() in extensions:
            found.append(candidate)
    return found


def _apply_config_theme(theme: ThemePalette, config: MirrorConfig) -> ThemePalette:
    overrides = {name: normalize_hex(value) for name, value in (config.theme_colors or {}).items()}
    overrides = {name: value for name, value in overrides.items() if value}
    if not overrides:
        return theme
    merged = dict(theme.colors)
    merged.update(overrides)
    return ThemePalette(colors=merged, source="config", font_scheme=dict(theme.font_scheme))


def load_workbook_data(path: str | Path, config: MirrorConfig | None = None) -> WorkbookData:
    """Carrega o workbook preservando fórmulas e, opcionalmente, valores em cache."""
    cfg = config or MirrorConfig()
    file_path = Path(path)
    keep_vba = file_path.suffix.lower() in {".xlsm", ".xltm"}
    warnings: list[str] = []

    try:
        wb_formulas = load_workbook(filename=str(file_path), data_only=False, keep_vba=keep_vba)
    except Exception as exc:  # noqa: BLE001 - repassado como erro de domínio
        raise SpreadsheetError(f"Falha ao ler {file_path.name}: {exc}") from exc

    wb_values = None
    if cfg.read_cached_values:
        try:
            wb_values = load_workbook(filename=str(file_path), data_only=True, keep_vba=keep_vba)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Não foi possível ler os valores em cache: {exc}")

    theme = _apply_config_theme(ThemePalette.from_workbook(wb_formulas), cfg)
    return WorkbookData(
        path=file_path,
        wb_formulas=wb_formulas,
        theme=theme,
        wb_values=wb_values,
        warnings=warnings,
    )
