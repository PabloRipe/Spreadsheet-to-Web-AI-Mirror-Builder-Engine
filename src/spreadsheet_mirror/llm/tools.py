"""Ferramentas de planilha expostas ao LLM (somente leitura + proposta pura)."""

from __future__ import annotations

import re
from typing import Any, Mapping

from openpyxl.utils import get_column_letter, range_boundaries

from .context import ContextBuilder, parse_ref

REF_RE = re.compile(r"^[A-Z]+[1-9][0-9]*$")

TOOL_SCHEMAS: tuple[dict[str, Any], ...] = (
    {
        "name": "read_range",
        "description": "Lê células de um intervalo de uma aba do espelho.",
        "parameters": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "range": {"type": "string", "description": "Intervalo A1:C10"},
            },
            "required": ["sheet", "range"],
        },
    },
    {
        "name": "search_cells",
        "description": (
            "Busca um termo (rótulo/campo) ou uma coordenada no espelho e retorna "
            "os campos editáveis vizinhos (direita/abaixo/esquerda/acima). Obrigatória "
            "antes de propor edições quando a coordenada não é conhecida com certeza. "
            "Se 'sheet' for omitida, pesquisa em todas as abas."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string", "description": "Opcional; omitir busca em todas as abas."},
                "query": {"type": "string", "description": "Texto do rótulo/campo ou coordenada (ex.: 'Faturamento Anual' ou 'B7')."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
        },
    },
    {
        "name": "summarize_sheet",
        "description": "Resume uma aba (dimensões, cabeçalhos, mesclagens e contagem).",
        "parameters": {
            "type": "object",
            "properties": {"sheet": {"type": "string"}},
            "required": ["sheet"],
        },
    },
    {
        "name": "suggest_formula",
        "description": "Sugere uma fórmula para uma célula, com base nos vizinhos e na intenção.",
        "parameters": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "target_ref": {"type": "string"},
                "intent": {"type": "string"},
            },
            "required": ["sheet", "target_ref", "intent"],
        },
    },
    {
        "name": "propose_edits",
        "description": "Valida uma proposta de edição; não grava nada.",
        "parameters": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ref": {"type": "string"},
                            "value": {},
                        },
                        "required": ["ref", "value"],
                    },
                },
            },
            "required": ["sheet", "edits"],
        },
    },
)


def tool_definitions(provider_type: str = "openai") -> list[dict[str, Any]]:
    """Converte o schema comum para o formato do provedor."""
    if provider_type == "anthropic":
        return [
            {
                "name": item["name"],
                "description": item["description"],
                "input_schema": item["parameters"],
            }
            for item in TOOL_SCHEMAS
        ]
    if provider_type == "gemini":
        return [
            {
                "functionDeclarations": [
                    {
                        "name": item["name"],
                        "description": item["description"],
                        "parameters": item["parameters"],
                    }
                    for item in TOOL_SCHEMAS
                ]
            }
        ]
    return [
        {
            "type": "function",
            "function": {
                "name": item["name"],
                "description": item["description"],
                "parameters": item["parameters"],
            },
        }
        for item in TOOL_SCHEMAS
    ]


def _sheets(document: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for sheet in document.get("sheets", []) or []:
        if isinstance(sheet, Mapping) and isinstance(sheet.get("name"), str):
            result[sheet["name"]] = sheet
    return result


def _cells(sheet: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for cell in sheet.get("cells", []) or []:
        if isinstance(cell, Mapping) and isinstance(cell.get("ref"), str):
            result[cell["ref"].upper()] = cell
    return result


def _config(document: Mapping[str, Any]) -> Mapping[str, Any]:
    meta = document.get("meta") if isinstance(document.get("meta"), Mapping) else {}
    return meta.get("config") if isinstance(meta.get("config"), Mapping) else {}


def _covered(sheet: Mapping[str, Any]) -> set[str]:
    covered: set[str] = set()
    for merged in sheet.get("merged_ranges", []) or []:
        try:
            min_col, min_row, max_col, max_row = range_boundaries(str(merged))
        except (TypeError, ValueError):
            continue
        for row in range(min_row, max_row + 1):
            for col in range(min_col, max_col + 1):
                if row == min_row and col == min_col:
                    continue
                covered.add(f"{get_column_letter(col)}{row}")
    return covered


def _normalize_edits(edits: Any, default_sheet: str = "") -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if isinstance(edits, Mapping):
        for sheet_name, cells in edits.items():
            if not isinstance(cells, Mapping):
                continue
            for ref, value in cells.items():
                normalized.append({"aba": str(sheet_name), "coordenada": str(ref), "novo_valor": value})
        return normalized
    if not isinstance(edits, (list, tuple)):
        return normalized
    for item in edits:
        if not isinstance(item, Mapping):
            continue
        sheet = str(item.get("aba") or item.get("sheet") or default_sheet or "")
        ref = str(item.get("coordenada") or item.get("ref") or "")
        if "novo_valor" in item:
            value = item.get("novo_valor")
        else:
            value = item.get("value")
        normalized.append({"aba": sheet, "coordenada": ref, "novo_valor": value})
    return normalized


def validate_edits(
    document: Mapping[str, Any],
    edits: Any,
    *,
    default_sheet: str = "",
) -> dict[str, Any]:
    """Valida edições e devolve ``{aplicaveis, rejeitadas}`` sem efeitos colaterais."""
    sheets = _sheets(document)
    config = _config(document)
    header_rows = {int(item) for item in (config.get("header_rows") or []) if str(item).isdigit()}
    header_cols = {int(item) for item in (config.get("header_cols") or []) if str(item).isdigit()}
    treat_no_fill = config.get("treat_no_fill_as_editable", True) is not False

    aplicaveis: dict[str, dict[str, Any]] = {}
    rejeitadas: list[dict[str, Any]] = []

    for edit in _normalize_edits(edits, default_sheet):
        aba = edit["aba"]
        ref = edit["coordenada"].replace("$", "").upper()
        value = edit["novo_valor"]
        rejection = _validate_one(
            sheets,
            aba,
            ref,
            value,
            header_rows=header_rows,
            header_cols=header_cols,
            treat_no_fill=treat_no_fill,
        )
        if rejection:
            rejeitadas.append({"aba": aba, "coordenada": ref, "motivo": rejection})
            continue
        aplicaveis.setdefault(aba, {})[ref] = value

    return {"aplicaveis": aplicaveis, "rejeitadas": rejeitadas}


def _validate_one(
    sheets: Mapping[str, Mapping[str, Any]],
    aba: str,
    ref: str,
    value: Any,
    *,
    header_rows: set[int],
    header_cols: set[int],
    treat_no_fill: bool,
) -> str | None:
    if not aba or aba not in sheets:
        return "aba_inexistente"
    if not REF_RE.fullmatch(ref):
        return "coordenada_invalida"
    parsed = parse_ref(ref)
    if parsed is None:
        return "coordenada_invalida"
    row, col = parsed
    sheet = sheets[aba]
    covered = _covered(sheet)
    if ref in covered:
        return "mesclada_nao_ancora"

    cell = _cells(sheet).get(ref)
    if cell is not None:
        if cell.get("editavel") is not True:
            return "celula_fixa"
        if isinstance(value, str) and value.startswith("=") and cell.get("formula"):
            return "celula_com_formula_fixa"
        return None

    if row in header_rows or col in header_cols:
        return "cabecalho_fixo"
    if not treat_no_fill:
        return "sem_preenchimento_fixo"
    max_row = int(sheet.get("max_row") or 0)
    max_col = int(sheet.get("max_col") or 0)
    if max_row and row > max_row:
        return "fora_dimensao"
    if max_col and col > max_col:
        return "fora_dimensao"
    if isinstance(value, str) and value.startswith("="):
        return "formula_em_celula_vazia"
    return None


def propose_edits(
    document: Mapping[str, Any],
    sheet: str,
    edits: Any,
) -> dict[str, Any]:
    """Propõe edições normalizadas; nunca grava no espelho ou no template."""
    result = validate_edits(document, edits, default_sheet=sheet)
    result["normalizado"] = result["aplicaveis"]
    return result


def read_range(
    document: Mapping[str, Any],
    sheet: str,
    range_text: str,
    *,
    draft: Mapping[str, Any] | None = None,
    limit: int = 400,
) -> dict[str, Any]:
    sheets = _sheets(document)
    if sheet not in sheets:
        raise ValueError(f"Aba inexistente: {sheet}")
    try:
        min_col, min_row, max_col, max_row = range_boundaries(str(range_text).replace("$", ""))
    except (TypeError, ValueError):
        raise ValueError("Intervalo inválido.")
    cell_map = _cells(sheets[sheet])
    draft = draft if isinstance(draft, Mapping) else {}
    cells: list[dict[str, Any]] = []
    for row in range(min_row, max_row + 1):
        for col in range(min_col, max_col + 1):
            if len(cells) >= limit:
                break
            ref = f"{get_column_letter(col)}{row}"
            cell = cell_map.get(ref)
            payload = {
                "ref": ref,
                "valor": cell.get("value") if cell else None,
                "tipo": cell.get("value_type") if cell else "null",
                "editavel": bool(cell.get("editavel")) if cell else False,
            }
            if cell and cell.get("formula"):
                payload["formula"] = cell["formula"]
            if ref in draft:
                payload["valor_rascunho"] = draft[ref]
            cells.append(payload)
    return {"sheet": sheet, "range": range_text, "cells": cells, "truncated": len(cells) >= limit}


_NEIGHBOR_DIRECTIONS = (
    (0, 1, "direita"),
    (1, 0, "abaixo"),
    (0, -1, "esquerda"),
    (-1, 0, "acima"),
)


def _gap_editable(
    document: Mapping[str, Any],
    sheet: Mapping[str, Any],
    row: int,
    col: int,
) -> bool:
    config = _config(document)
    header_rows = {int(item) for item in (config.get("header_rows") or []) if str(item).isdigit()}
    header_cols = {int(item) for item in (config.get("header_cols") or []) if str(item).isdigit()}
    if row in header_rows or col in header_cols:
        return False
    if config.get("treat_no_fill_as_editable", True) is False:
        return False
    max_row = int(sheet.get("max_row") or 0)
    max_col = int(sheet.get("max_col") or 0)
    if max_row and row > max_row:
        return False
    if max_col and col > max_col:
        return False
    return True


def _editable_neighbors(
    document: Mapping[str, Any],
    sheet_name: str,
    sheet: Mapping[str, Any],
    row: int,
    col: int,
) -> list[dict[str, Any]]:
    """Campos editáveis adjacentes a um rótulo (prioriza direita e abaixo)."""
    cell_map = _cells(sheet)
    covered = _covered(sheet)
    max_row = int(sheet.get("max_row") or 0)
    max_col = int(sheet.get("max_col") or 0)
    neighbours: list[dict[str, Any]] = []
    for delta_row, delta_col, direction in _NEIGHBOR_DIRECTIONS:
        new_row, new_col = row + delta_row, col + delta_col
        if new_row < 1 or new_col < 1:
            continue
        if max_row and new_row > max_row:
            continue
        if max_col and new_col > max_col:
            continue
        ref = f"{get_column_letter(new_col)}{new_row}"
        if ref in covered:
            continue
        cell = cell_map.get(ref)
        if cell is not None:
            if cell.get("editavel") is not True:
                continue
            neighbours.append(
                {
                    "aba": sheet_name,
                    "ref": ref,
                    "direcao": direction,
                    "valor_atual": cell.get("value"),
                    "tipo": cell.get("value_type"),
                    "editavel": True,
                }
            )
        elif _gap_editable(document, sheet, new_row, new_col):
            neighbours.append(
                {
                    "aba": sheet_name,
                    "ref": ref,
                    "direcao": direction,
                    "valor_atual": None,
                    "tipo": "null",
                    "editavel": True,
                }
            )
    return neighbours


def _ref_match(
    document: Mapping[str, Any],
    sheet_name: str,
    sheet: Mapping[str, Any],
    ref: str,
) -> dict[str, Any] | None:
    parsed = parse_ref(ref)
    if parsed is None:
        return None
    row, col = parsed
    covered = _covered(sheet)
    if ref in covered:
        return {
            "aba": sheet_name,
            "ref": ref,
            "valor": None,
            "formula": None,
            "editavel": False,
            "motivo": "mesclada_nao_ancora",
            "campos_editaveis_vizinhos": [],
        }
    cell = _cells(sheet).get(ref)
    if cell is not None:
        return {
            "aba": sheet_name,
            "ref": ref,
            "valor": cell.get("value"),
            "formula": cell.get("formula"),
            "editavel": bool(cell.get("editavel")),
            "campos_editaveis_vizinhos": _editable_neighbors(
                document, sheet_name, sheet, row, col
            ),
        }
    editable = _gap_editable(document, sheet, row, col)
    return {
        "aba": sheet_name,
        "ref": ref,
        "valor": None,
        "formula": None,
        "editavel": editable,
        "motivo": "celula_vazia_editavel" if editable else "celula_vazia_fixa",
        "campos_editaveis_vizinhos": (
            _editable_neighbors(document, sheet_name, sheet, row, col) if editable else []
        ),
    }


def search_cells(
    document: Mapping[str, Any],
    sheet: str | None,
    query: str,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    """Busca texto ou coordenada e retorna candidatos + vizinhos editáveis.

    ``sheet`` vazio/``None`` pesquisa em todas as abas. Esta é a ferramenta de
    ancoragem estrutural: o agente deve usá-la antes de propor coordenadas que
    não estejam explícitas no contexto.
    """
    sheets = _sheets(document)
    if sheet:
        if sheet not in sheets:
            raise ValueError(f"Aba inexistente: {sheet}")
        target_sheets = [(sheet, sheets[sheet])]
    else:
        target_sheets = list(sheets.items())

    raw_query = str(query or "").strip()
    needle = raw_query.lower()
    normalized_ref = raw_query.replace("$", "").upper()
    max_results = max(1, int(limit or 20))
    as_ref = bool(REF_RE.fullmatch(normalized_ref))

    if not raw_query:
        return {"sheet": sheet or None, "query": query, "matches": [], "abas_pesquisadas": []}

    matches: list[dict[str, Any]] = []
    for sheet_name, sheet_data in target_sheets:
        if as_ref:
            match = _ref_match(document, sheet_name, sheet_data, normalized_ref)
            if match is not None:
                matches.append(match)
            continue
        for ref, cell in sorted(_cells(sheet_data).items()):
            haystack = f"{cell.get('value') or ''} {cell.get('formula') or ''}".lower()
            if needle not in haystack:
                continue
            parsed = parse_ref(ref)
            neighbours = (
                _editable_neighbors(document, sheet_name, sheet_data, parsed[0], parsed[1])
                if parsed
                else []
            )
            matches.append(
                {
                    "aba": sheet_name,
                    "ref": ref,
                    "valor": cell.get("value"),
                    "formula": cell.get("formula"),
                    "editavel": bool(cell.get("editavel")),
                    "campos_editaveis_vizinhos": neighbours,
                }
            )
            if len(matches) >= max_results:
                break
        if len(matches) >= max_results:
            break

    matches.sort(
        key=lambda item: (
            0 if item.get("campos_editaveis_vizinhos") else 1,
            str(item.get("aba") or ""),
            (parse_ref(str(item.get("ref") or "")) or (0, 0))[0],
            (parse_ref(str(item.get("ref") or "")) or (0, 0))[1],
        )
    )
    matches = matches[:max_results]
    return {
        "sheet": sheet or None,
        "query": query,
        "matches": matches,
        "abas_pesquisadas": [name for name, _ in target_sheets],
        "orientacao": (
            "Use 'campos_editaveis_vizinhos' para localizar o campo de valor. "
            "Rótulos geralmente são fixos; o campo editável costuma estar à direita ou abaixo."
        ),
    }


def summarize_sheet(document: Mapping[str, Any], sheet: str) -> dict[str, Any]:
    context = ContextBuilder(document).build("sheet", sheet=sheet)
    for item in context.get("abas", []):
        item.pop("celulas", None)
    return context


def suggest_formula(
    document: Mapping[str, Any],
    sheet: str,
    target_ref: str,
    intent: str,
) -> dict[str, Any]:
    parsed = parse_ref(target_ref)
    if parsed is None:
        raise ValueError("Referência alvo inválida.")
    row, col = parsed
    neighbours: list[dict[str, Any]] = []
    sheets = _sheets(document)
    if sheet in sheets:
        cell_map = _cells(sheets[sheet])
        for delta_row, delta_col, label in (
            (-1, 0, "acima"),
            (0, -1, "esquerda"),
            (0, 1, "direita"),
            (1, 0, "abaixo"),
        ):
            new_row, new_col = row + delta_row, col + delta_col
            if new_row < 1 or new_col < 1:
                continue
            ref = f"{get_column_letter(new_col)}{new_row}"
            cell = cell_map.get(ref)
            if cell:
                neighbours.append(
                    {
                        "posicao": label,
                        "ref": ref,
                        "valor": cell.get("value"),
                        "formula": cell.get("formula"),
                        "editavel": bool(cell.get("editavel")),
                    }
                )
    return {
        "sheet": sheet,
        "target_ref": target_ref.upper(),
        "intent": intent,
        "vizinhos": neighbours,
        "observacao": "Fórmulas propostas devem ser confirmadas pelo usuário e só valem em células editáveis.",
    }


def execute_tool(
    name: str,
    arguments: Mapping[str, Any] | None,
    document: Mapping[str, Any],
    *,
    draft: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    args = dict(arguments or {}) if isinstance(arguments, Mapping) else {}
    if name == "read_range":
        return read_range(document, str(args.get("sheet") or ""), str(args.get("range") or ""), draft=draft)
    if name == "search_cells":
        return search_cells(
            document,
            str(args.get("sheet") or ""),
            str(args.get("query") or ""),
            limit=int(args.get("limit") or 20),
        )
    if name == "summarize_sheet":
        return summarize_sheet(document, str(args.get("sheet") or ""))
    if name == "suggest_formula":
        return suggest_formula(
            document,
            str(args.get("sheet") or ""),
            str(args.get("target_ref") or ""),
            str(args.get("intent") or ""),
        )
    if name == "propose_edits":
        return propose_edits(document, str(args.get("sheet") or ""), args.get("edits"))
    raise ValueError(f"Ferramenta desconhecida: {name}")


__all__ = [
    "TOOL_SCHEMAS",
    "tool_definitions",
    "validate_edits",
    "propose_edits",
    "read_range",
    "search_cells",
    "summarize_sheet",
    "suggest_formula",
    "execute_tool",
]
