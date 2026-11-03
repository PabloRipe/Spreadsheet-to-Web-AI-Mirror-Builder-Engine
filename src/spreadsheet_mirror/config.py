"""Configuração da convenção de cores e do pipeline de espelhamento."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping


@dataclass
class MirrorConfig:
    """Regras que determinam quais células são fixas ou editáveis.

    As regras são avaliadas na seguinte ordem (a primeira que casar vence):

    1. célula com fórmula -> fixa;
    2. célula não-âncora de mesclagem -> fixa/omitida;
    3. linha em ``header_rows`` ou coluna em ``header_cols`` -> fixa;
    4. preenchimento em ``fixed_fill_colors`` -> fixa;
    5. preenchimento em ``editable_fill_colors`` -> editável;
    6. preenchimento sólido diferente de branco -> fixa;
    7. fonte em negrito (se ``fixed_if_bold``) -> fixa;
    8. fundo branco/padrão e sem fórmula -> editável.
    """

    # Cabeçalhos explícitos (números de linha/coluna, base 1).
    header_rows: tuple[int, ...] = ()
    header_cols: tuple[int, ...] = ()

    # Heurísticas de formatação.
    fixed_if_bold: bool = True
    fixed_if_italic: bool = False
    fixed_if_underline: bool = False
    fixed_if_border: bool = False
    fixed_if_merged: bool = True
    fixed_font_colors: tuple[str, ...] = ()

    # Cores forçadas.
    fixed_fill_colors: tuple[str, ...] = ()
    editable_fill_colors: tuple[str, ...] = ("#FFFFFF",)
    treat_no_fill_as_editable: bool = True

    # Abas.
    ignore_hidden_sheets: bool = False

    # Limites e leitura.
    max_cells_per_sheet: int = 200_000
    read_cached_values: bool = True
    include_empty_cells: bool = False
    clear_editable_values: bool = True

    # Descoberta de arquivos.
    extensions: tuple[str, ...] = (".xlsx",)
    recursive: bool = False

    # Paleta de fallback do tema (nome -> #RRGGBB).
    theme_colors: Mapping[str, str] = field(default_factory=dict)

    # Sobrescreve o nome da pasta de saída por projeto.
    output_dir_name: str = "mirror_output"

    # ------------------------------------------------------------------
    # Serialização
    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key, value in list(data.items()):
            if isinstance(value, tuple):
                data[key] = list(value)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "MirrorConfig":
        if not data:
            return cls()
        valid = {f.name for f in fields(cls)}
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            if key not in valid:
                continue
            if key in {"header_rows", "header_cols", "fixed_fill_colors",
                       "editable_fill_colors", "fixed_font_colors", "extensions"}:
                value = tuple(value or ())
            kwargs[key] = value
        return cls(**kwargs)

    @classmethod
    def load(cls, path: str | Path) -> "MirrorConfig":
        with open(path, "r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))

    def save(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
