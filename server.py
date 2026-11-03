"""Camada web do Spreadsheet-to-Web Mirror Engine.

Expõe uma API Flask para listar projetos processados, enviar novas planilhas
``.xlsx``, ler o espelho JSON e gerar o arquivo final ``.xlsx`` a partir do
template limpo e dos dados preenchidos na interface.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from bisect import bisect_left
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

# Permite executar ``python server.py`` sem instalar o pacote.
_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from flask import (  # noqa: E402
    Flask,
    Response,
    abort,
    jsonify,
    request,
    send_file,
    send_from_directory,
    stream_with_context,
)
from openpyxl.utils import column_index_from_string, get_column_letter, range_boundaries  # noqa: E402
from werkzeug.exceptions import HTTPException  # noqa: E402

from spreadsheet_mirror.config import MirrorConfig  # noqa: E402
from spreadsheet_mirror.llm import (  # noqa: E402
    AuthError,
    ProviderError,
    RateLimitError,
    TimeoutError as LLMTimeoutError,
    catalog_public,
    create_provider,
    models_for,
    preset,
    validate_provider_config,
)
from spreadsheet_mirror.llm.base import redact_secrets  # noqa: E402
from spreadsheet_mirror.llm.chat_store import ChatStore, public_history  # noqa: E402
from spreadsheet_mirror.llm.creation import WorkbookSpecError, create_project_from_spec  # noqa: E402
from spreadsheet_mirror.llm.service import ChatService  # noqa: E402
from spreadsheet_mirror.llm.tools import validate_edits  # noqa: E402
from spreadsheet_mirror.pipeline import process_path  # noqa: E402
from spreadsheet_mirror.template import fill_template  # noqa: E402

SCHEMA_VERSION = "1.0.0"
PROJECT_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
CELL_REF_RE = re.compile(r"^[A-Z]+[1-9][0-9]*$")
UPLOAD_NAME_RE = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
MAX_UPLOAD_BYTES = 32 * 1024 * 1024
MAX_CHAT_MESSAGE_CHARS = 20_000

_PROCESS_LOCK = threading.Lock()
_RATE_LOCK = threading.Lock()
_RATE_BUCKETS: dict[str, list[float]] = {}



# ---------------------------------------------------------------------------
# Utilidades de caminhos e leitura
# ---------------------------------------------------------------------------
def _default_workspace() -> Path:
    return Path(os.environ.get("MIRROR_WORKSPACE", "mirror_output")).resolve()


def _default_web_dir() -> Path:
    return Path(__file__).resolve().parent / "web"


def _safe_slug(slug: str) -> str:
    if not PROJECT_SLUG_RE.fullmatch(slug or ""):
        abort(400, description="Identificador de projeto inválido.")
    return slug


def _project_dir(workspace: Path, slug: str) -> Path:
    slug = _safe_slug(slug)
    project = (workspace / slug).resolve()
    try:
        project.relative_to(workspace)
    except ValueError:
        abort(400, description="Caminho de projeto inválido.")
    if not project.is_dir():
        abort(404, description=f"Projeto '{slug}' não encontrado.")
    return project


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _scan_projects(workspace: Path) -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    if not workspace.is_dir():
        return projects
    for entry in sorted(workspace.iterdir()):
        if not entry.is_dir():
            continue
        mirror = entry / "mirror.json"
        if not mirror.exists():
            continue
        document = _read_json(mirror, {}) or {}
        meta = document.get("meta", {}) if isinstance(document, dict) else {}
        template = entry / "template.xlsx"
        projects.append(
            {
                "slug": entry.name,
                "source": meta.get("source_path") or str(meta.get("source") or ""),
                "source_name": meta.get("source") or entry.name,
                "mirror_json": str(mirror.relative_to(workspace).as_posix()),
                "template_xlsx": (
                    str(template.relative_to(workspace).as_posix()) if template.exists() else None
                ),
                "warnings": meta.get("warnings", []),
                "stats": meta.get("stats", {}),
            }
        )
    return projects


def _projects_payload(workspace: Path) -> dict[str, Any]:
    index = _read_json(workspace / "index.json")
    scanned = _scan_projects(workspace)
    by_slug: dict[str, dict[str, Any]] = {item["slug"]: item for item in scanned}

    if isinstance(index, dict) and isinstance(index.get("projects"), list):
        for item in index["projects"]:
            if isinstance(item, dict) and item.get("slug"):
                by_slug[str(item["slug"])] = item

    valid: list[dict[str, Any]] = []
    for slug, item in by_slug.items():
        if not PROJECT_SLUG_RE.fullmatch(slug):
            continue
        if not (workspace / slug / "mirror.json").exists():
            continue
        valid.append(item)

    valid.sort(key=lambda item: str(item.get("source_name") or item.get("slug") or ""))

    return {
        "schema_version": (
            index.get("schema_version") if isinstance(index, dict) else SCHEMA_VERSION
        ),
        "generated_at": index.get("generated_at") if isinstance(index, dict) else None,
        "workspace": str(workspace),
        "projects": valid,
    }


# ---------------------------------------------------------------------------
# Conversão de valores recebidos da web
# ---------------------------------------------------------------------------
def _merged_covered(sheet: Mapping[str, Any]) -> set[str]:
    covered: set[str] = set()
    for merged in sheet.get("merged_ranges", []) or []:
        try:
            min_col, min_row, max_col, max_row = range_boundaries(str(merged))
        except (ValueError, TypeError):
            continue
        for row in range(min_row, max_row + 1):
            for col in range(min_col, max_col + 1):
                if row == min_row and col == min_col:
                    continue
                covered.add(f"{get_column_letter(col)}{row}")
    return covered


def _sheet_index(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for sheet in document.get("sheets", []):
        if not isinstance(sheet, dict):
            continue
        name = sheet.get("name")
        if not isinstance(name, str):
            continue
        cells: dict[str, dict[str, Any]] = {}
        for cell in sheet.get("cells", []):
            if isinstance(cell, dict) and isinstance(cell.get("ref"), str):
                cells[cell["ref"].upper()] = cell
        index[name] = {
            "sheet": sheet,
            "cells": cells,
            "covered": _merged_covered(sheet),
        }
    return index


def _parse_ref(ref: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"\$?([A-Za-z]+)\$?(\d+)", str(ref).strip())
    if not match:
        return None
    try:
        col = column_index_from_string(match.group(1).upper())
    except ValueError:
        return None
    return int(match.group(2)), col


def _is_gap_editable(
    sheet: Mapping[str, Any],
    row: int,
    col: int,
    config: Mapping[str, Any],
) -> bool:
    header_rows = set(config.get("header_rows", []) or [])
    header_cols = set(config.get("header_cols", []) or [])
    if row in header_rows or col in header_cols:
        return False
    if config.get("treat_no_fill_as_editable", True) is False:
        return False
    return True


def _looks_like_date(value_type: str | None, number_format: str | None) -> bool:
    if value_type == "datetime":
        return True
    if not number_format:
        return False
    lowered = number_format.lower()
    tokens = ("yy", "mm", "dd", "hh", "ss", "m/", "/m", "h:", ":m")
    return any(token in lowered for token in tokens)


def _style_for_cell(cell: Mapping[str, Any] | None, document: Mapping[str, Any]) -> dict[str, Any]:
    if not cell:
        return {}
    style_id = cell.get("style")
    styles = document.get("styles", {})
    if isinstance(style_id, str) and isinstance(styles, Mapping):
        style = styles.get(style_id)
        if isinstance(style, Mapping):
            return dict(style)
    return {}


def _coerce_value(value: Any, cell: Mapping[str, Any] | None, style: Mapping[str, Any]) -> Any:
    """Converte a string recebida da web para o tipo original da célula."""
    if value is None:
        return None
    if not isinstance(value, str):
        return value

    text = value.strip()
    if text == "":
        return None

    value_type = cell.get("value_type") if cell else None
    number_format = style.get("number_format") if isinstance(style, Mapping) else None

    if _looks_like_date(value_type, number_format):
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y %H:%M",
            "%d/%m/%Y",
            "%d-%m-%Y",
        ):
            try:
                parsed = datetime.strptime(text, fmt)
                if fmt in {"%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"}:
                    return parsed.date()
                return parsed
            except ValueError:
                continue
        return text

    if value_type == "number":
        if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", text):
            normalized = text.replace(".", "")
        elif "," in text:
            normalized = text.replace(".", "").replace(",", ".")
        else:
            normalized = text
        try:
            number = float(normalized)
        except ValueError:
            return text
        return int(number) if number.is_integer() else number

    if value_type == "boolean":
        lowered = text.lower()
        if lowered in {"true", "1", "sim", "yes", "y", "verdadeiro"}:
            return True
        if lowered in {"false", "0", "não", "nao", "no", "n", "falso"}:
            return False
        return text

    if value_type == "duration":
        pattern = re.fullmatch(r"(\d+):(\d{1,2}):(\d{1,2})", text)
        if pattern:
            hours, minutes, seconds = (int(part) for part in pattern.groups())
            return timedelta(hours=hours, minutes=minutes, seconds=seconds)
        try:
            return timedelta(seconds=float(text.replace(",", ".")))
        except ValueError:
            return text

    return text


def _get_type_hint(
    cell_map: Mapping[str, Mapping[str, Any]],
    document: Mapping[str, Any],
    col_rows: Mapping[int, list[tuple[int, str]]],
    row_cols: Mapping[int, list[tuple[int, str]]],
    row: int,
    col: int,
) -> tuple[str | None, Mapping[str, Any]]:
    """Infere o tipo de uma célula vazia a partir das células vizinhas."""
    rows = col_rows.get(col, [])
    if rows:
        row_values = [r for r, _ in rows]
        idx = bisect_left(row_values, row)
        candidates = []
        if idx > 0:
            candidates.append(rows[idx - 1])
        if idx < len(rows):
            candidates.append(rows[idx])
        for _, ref in candidates:
            neighbor = cell_map.get(ref)
            if neighbor:
                value_type = neighbor.get("value_type")
                if value_type and value_type not in ("string", "null", "empty", "error"):
                    return value_type, _style_for_cell(neighbor, document)
        for _, ref in candidates:
            neighbor = cell_map.get(ref)
            if neighbor:
                value_type = neighbor.get("value_type")
                if value_type == "string":
                    return value_type, _style_for_cell(neighbor, document)

    cols = row_cols.get(row, [])
    if cols:
        col_values = [c for c, _ in cols]
        idx = bisect_left(col_values, col)
        candidates = []
        if idx > 0:
            candidates.append(cols[idx - 1])
        if idx < len(cols):
            candidates.append(cols[idx])
        for _, ref in candidates:
            neighbor = cell_map.get(ref)
            if neighbor:
                value_type = neighbor.get("value_type")
                if value_type and value_type not in ("string", "null", "empty", "error"):
                    return value_type, _style_for_cell(neighbor, document)
        for _, ref in candidates:
            neighbor = cell_map.get(ref)
            if neighbor:
                value_type = neighbor.get("value_type")
                if value_type == "string":
                    return value_type, _style_for_cell(neighbor, document)

    return None, {}


def _coerce_payload(
    data: Mapping[str, Any],
    document: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    index = _sheet_index(document)
    meta = document.get("meta", {}) if isinstance(document, Mapping) else {}
    config = meta.get("config", {}) if isinstance(meta, Mapping) else {}
    result: dict[str, dict[str, Any]] = {}
    for sheet_name, cells in data.items():
        if not isinstance(sheet_name, str) or not isinstance(cells, Mapping):
            continue
        entry = index.get(sheet_name)
        if not entry:
            continue
        sheet = entry["sheet"]
        cell_map = entry["cells"]
        covered = entry["covered"]
        max_row = int(sheet.get("max_row", 0) or 0)
        max_col = int(sheet.get("max_col", 0) or 0)

        col_rows: dict[int, list[tuple[int, str]]] = {}
        row_cols: dict[int, list[tuple[int, str]]] = {}
        for ref, cell in cell_map.items():
            parsed = _parse_ref(ref)
            if parsed:
                r, c = parsed
                col_rows.setdefault(c, []).append((r, ref))
                row_cols.setdefault(r, []).append((c, ref))
        for rows_list in col_rows.values():
            rows_list.sort(key=lambda item: item[0])
        for cols_list in row_cols.values():
            cols_list.sort(key=lambda item: item[0])

        sheet_cells: dict[str, Any] = {}
        for ref, value in cells.items():
            if not isinstance(ref, str):
                continue
            normalized_ref = ref.replace("$", "").upper()
            if not CELL_REF_RE.fullmatch(normalized_ref):
                continue
            if normalized_ref in covered:
                continue

            cell = cell_map.get(normalized_ref)
            if cell is not None:
                if cell.get("editavel") is not True:
                    continue
                style = _style_for_cell(cell, document)
                sheet_cells[normalized_ref] = _coerce_value(value, cell, style)
                continue

            parsed = _parse_ref(normalized_ref)
            if parsed is None:
                continue
            row, col = parsed
            if max_row and row > max_row:
                continue
            if max_col and col > max_col:
                continue
            if not _is_gap_editable(sheet, row, col, config):
                continue
            hint_type, hint_style = _get_type_hint(cell_map, document, col_rows, row_cols, row, col)
            hint_cell = {"value_type": hint_type} if hint_type else None
            sheet_cells[normalized_ref] = _coerce_value(value, hint_cell, hint_style)

        if sheet_cells:
            result[sheet_name] = sheet_cells
    return result


_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _safe_upload_name(filename: str) -> str:
    name = (filename or "").replace("\\", "/").split("/")[-1]
    name = UPLOAD_NAME_RE.sub("_", name).strip(" .")
    if not name:
        name = "planilha.xlsx"
    if name.lower().endswith(".xlsx"):
        stem, ext = name[:-5], name[-5:]
    else:
        stem, ext = name, ".xlsx"
    stem = stem.strip(" .")[:110] or "planilha"
    if stem.upper() in _WINDOWS_RESERVED:
        stem = f"_{stem}"
    return f"{stem}{ext}"


def _safe_download_name(filename: str, fallback: str) -> str:
    name = _safe_upload_name(filename)
    if not name.lower().endswith(".xlsx"):
        name = f"{name}.xlsx"
    return name or fallback


# ---------------------------------------------------------------------------
# Utilidades da camada LLM
# ---------------------------------------------------------------------------
def _check_rate_limit(key: str, limit: int = 20, window_s: float = 60.0) -> None:
    now = time.monotonic()
    with _RATE_LOCK:
        bucket = [item for item in _RATE_BUCKETS.get(key, []) if now - item < window_s]
        if len(bucket) >= limit:
            _RATE_BUCKETS[key] = bucket
            abort(429, description="Muitas requisições de IA. Aguarde um instante.")
        bucket.append(now)
        _RATE_BUCKETS[key] = bucket


def _provider_config_from_payload(payload: Mapping[str, Any] | None):
    data = payload if isinstance(payload, Mapping) else {}
    raw = data.get("provider") if isinstance(data.get("provider"), Mapping) else data
    try:
        return validate_provider_config(raw)
    except ValueError as exc:
        abort(400, description=str(exc))


def _raise_llm_error(exc: Exception, api_key: str | None = None) -> None:
    message = redact_secrets(exc, [api_key or ""])
    if isinstance(exc, AuthError):
        abort(401, description=message)
    if isinstance(exc, RateLimitError):
        abort(429, description=message)
    if isinstance(exc, LLMTimeoutError):
        abort(504, description=message)
    if isinstance(exc, ProviderError):
        abort(502, description=message)
    if isinstance(exc, (ValueError, WorkbookSpecError)):
        abort(400, description=message)
    abort(500, description=message)


def _draft_from_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    data = payload if isinstance(payload, Mapping) else {}
    draft = data.get("draft", data.get("data", {}))
    if draft is None:
        return {}
    if not isinstance(draft, Mapping):
        abort(400, description="O rascunho deve ser um objeto {aba: {ref: valor}}.")
    return {str(key): value for key, value in draft.items()}


def _first_sheet_name(document: Mapping[str, Any]) -> str | None:
    for sheet in document.get("sheets", []) or []:
        if isinstance(sheet, Mapping) and isinstance(sheet.get("name"), str):
            return sheet["name"]
    return None



# ---------------------------------------------------------------------------
# Aplicação Flask
# ---------------------------------------------------------------------------
def create_app(
    workspace: str | Path | None = None,
    web_dir: str | Path | None = None,
) -> Flask:
    workspace_path = Path(workspace).resolve() if workspace else _default_workspace()
    workspace_path.mkdir(parents=True, exist_ok=True)
    web_path = Path(web_dir).resolve() if web_dir else _default_web_dir()

    app = Flask(
        __name__,
        static_folder=str(web_path),
        static_url_path="/static",
    )
    app.config.update(
        WORKSPACE=str(workspace_path),
        WEB_DIR=str(web_path),
        MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
        JSON_SORT_KEYS=False,
        LLM_MAX_CONTEXT_CELLS=400,
        LLM_MAX_HISTORY_MESSAGES=40,
        LLM_DEFAULT_PROVIDER="openai",
    )

    def _provider_factory(config: Any) -> Any:
        factory = app.config.get("LLM_PROVIDER_FACTORY") or create_provider
        return factory(config)

    def _chat_store() -> ChatStore:
        return ChatStore(
            workspace_path,
            int(app.config.get("LLM_MAX_HISTORY_MESSAGES", 40) or 40),
        )

    def _chat_service(document: Mapping[str, Any], slug: str, draft: Mapping[str, Any]) -> ChatService:
        return ChatService(
            document,
            project_slug=slug,
            draft=draft,
            store=_chat_store(),
            max_context_cells=int(app.config.get("LLM_MAX_CONTEXT_CELLS", 400) or 400),
            max_history_messages=int(app.config.get("LLM_MAX_HISTORY_MESSAGES", 40) or 40),
            provider_factory=_provider_factory,
        )

    # -- rotas estáticas ---------------------------------------------------
    @app.get("/")
    def index() -> Any:
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/favicon.ico")
    def favicon() -> Any:
        icon = Path(app.static_folder) / "favicon.ico"
        if icon.exists():
            return send_from_directory(app.static_folder, "favicon.ico")
        return ("", 204)

    # -- API ---------------------------------------------------------------
    @app.get("/api/health")
    def health() -> Any:
        payload = _projects_payload(workspace_path)
        return jsonify(
            {
                "status": "ok",
                "workspace": str(workspace_path),
                "projects": len(payload["projects"]),
            }
        )

    @app.get("/api/projects")
    def list_projects() -> Any:
        return jsonify(_projects_payload(workspace_path))

    @app.get("/api/projects/<slug>/mirror")
    def project_mirror(slug: str) -> Any:
        project = _project_dir(workspace_path, slug)
        document = _read_json(project / "mirror.json")
        if document is None:
            abort(500, description="Espelho JSON ilegível.")
        return jsonify(document)

    @app.post("/api/upload")
    def upload() -> Any:
        file = request.files.get("file")
        if file is None or not file.filename:
            abort(400, description="Nenhum arquivo enviado.")
        raw_name = str(file.filename).strip()
        if not raw_name.lower().endswith(".xlsx"):
            abort(400, description="Envie um arquivo .xlsx.")
        original_name = _safe_upload_name(raw_name)

        temp_dir = Path(tempfile.mkdtemp(prefix="mirror_upload_"))
        source = temp_dir / original_name
        try:
            file.save(source)
            config = MirrorConfig()
            with _PROCESS_LOCK:
                result = process_path(source, workspace_path, config, overwrite=False)
            if result.failures:
                abort(400, description=result.failures[0][1])
            if not result.projects:
                abort(400, description="Não foi possível processar a planilha.")
            project = result.projects[0]
            manifest = project.to_manifest(workspace_path)
            manifest["source_name"] = original_name
            return jsonify({"project": manifest, "warnings": manifest.get("warnings", [])}), 201
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @app.post("/api/projects/<slug>/export")
    def export_project(slug: str) -> Any:
        project = _project_dir(workspace_path, slug)
        template_path = project / "template.xlsx"
        if not template_path.exists():
            abort(404, description="Template .xlsx não encontrado para este projeto.")

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            abort(400, description="Corpo JSON inválido.")
        raw_data = payload.get("data", {})
        if not isinstance(raw_data, Mapping):
            abort(400, description="O campo 'data' deve ser um objeto.")

        document = _read_json(project / "mirror.json", {}) or {}
        coerced = _coerce_payload(raw_data, document)

        filename = _safe_download_name(
            str(payload.get("filename") or ""),
            f"{slug}-preenchido.xlsx",
        )

        handle, temp_name = tempfile.mkstemp(suffix=".xlsx", prefix="mirror_export_")
        os.close(handle)
        temp_path = Path(temp_name)
        try:
            fill_template(template_path, coerced, temp_path)
            buffer = io.BytesIO(temp_path.read_bytes())
        except Exception as exc:  # noqa: BLE001 - devolvemos erro amigável
            abort(500, description=f"Falha ao gerar o arquivo: {exc}")
        finally:
            try:
                temp_path.unlink()
            except OSError:
                pass

        return send_file(
            buffer,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    # -- LLM / chat --------------------------------------------------------
    @app.get("/api/llm/providers")
    def llm_providers() -> Any:
        return jsonify(
            {
                "providers": catalog_public(),
                "default_provider": app.config.get("LLM_DEFAULT_PROVIDER", "openai"),
            }
        )

    @app.get("/api/llm/models")
    def llm_models() -> Any:
        provider_id = str(request.args.get("provider") or "").strip()
        if not provider_id or preset(provider_id) is None:
            abort(400, description="Provedor desconhecido.")
        return jsonify({"provider": provider_id, "models": models_for(provider_id)})

    @app.post("/api/llm/test")
    def llm_test() -> Any:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            abort(400, description="Corpo JSON inválido.")
        config = _provider_config_from_payload(payload)
        _check_rate_limit(f"llm-test:{config.id}")
        try:
            result = _provider_factory(config).validate()
        except Exception as exc:  # noqa: BLE001 - devolvemos erro estruturado
            _raise_llm_error(exc, config.api_key)
        return jsonify(
            {
                "ok": bool(result.ok),
                "provider": config.public_dict(),
                "detail": result.detail,
                "models": result.models,
            }
        )

    @app.get("/api/projects/<slug>/chat/history")
    def chat_history(slug: str) -> Any:
        _project_dir(workspace_path, slug)
        return jsonify(public_history(_chat_store().load(slug)))

    @app.delete("/api/projects/<slug>/chat/history")
    def chat_history_clear(slug: str) -> Any:
        _project_dir(workspace_path, slug)
        _chat_store().clear(slug)
        return jsonify({"ok": True, "project_slug": slug})

    @app.post("/api/projects/<slug>/chat")
    def chat_project(slug: str) -> Any:
        project = _project_dir(workspace_path, slug)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            abort(400, description="Corpo JSON inválido.")
        message = str(payload.get("message") or "").strip()
        if not message:
            abort(400, description="Informe uma mensagem para o chat.")
        if len(message) > MAX_CHAT_MESSAGE_CHARS:
            abort(400, description="Mensagem muito longa.")
        document = _read_json(project / "mirror.json", {}) or {}
        config = _provider_config_from_payload(payload)
        _check_rate_limit(f"chat:{slug}")
        service = _chat_service(document, slug, _draft_from_payload(payload))
        try:
            result = service.chat(
                message=message,
                provider_config=config,
                sheet=payload.get("sheet") or _first_sheet_name(document),
                selection=payload.get("selection"),
                context_mode=str(payload.get("context_mode") or "sheet"),
            )
        except Exception as exc:  # noqa: BLE001
            _raise_llm_error(exc, config.api_key)
        return jsonify(result)

    @app.post("/api/projects/<slug>/chat/stream")
    def chat_project_stream(slug: str) -> Any:
        project = _project_dir(workspace_path, slug)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            abort(400, description="Corpo JSON inválido.")
        message = str(payload.get("message") or "").strip()
        if not message:
            abort(400, description="Informe uma mensagem para o chat.")
        if len(message) > MAX_CHAT_MESSAGE_CHARS:
            abort(400, description="Mensagem muito longa.")
        document = _read_json(project / "mirror.json", {}) or {}
        config = _provider_config_from_payload(payload)
        _check_rate_limit(f"chat-stream:{slug}")
        service = _chat_service(document, slug, _draft_from_payload(payload))

        def generate():
            for event in service.stream_chat(
                message=message,
                provider_config=config,
                sheet=payload.get("sheet") or _first_sheet_name(document),
                selection=payload.get("selection"),
                context_mode=str(payload.get("context_mode") or "sheet"),
            ):
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/projects/<slug>/chat/apply")
    def chat_apply(slug: str) -> Any:
        project = _project_dir(workspace_path, slug)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            abort(400, description="Corpo JSON inválido.")
        edits = payload.get("edits", payload.get("acoes", payload.get("data")))
        if edits is None:
            abort(400, description="Envie 'edits' com as alterações propostas.")
        document = _read_json(project / "mirror.json", {}) or {}
        validated = validate_edits(
            document,
            edits,
            default_sheet=str(payload.get("sheet") or ""),
        )
        coerced = _coerce_payload(validated["aplicaveis"], document)
        return jsonify(
            {
                "aplicaveis": coerced,
                "rejeitadas": validated["rejeitadas"],
                "data": coerced,
            }
        )

    @app.post("/api/projects/create")
    def create_project() -> Any:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            abort(400, description="Corpo JSON inválido.")
        spec = payload.get("spec")
        generated: dict[str, Any] | None = None
        if spec is None:
            prompt = str(payload.get("prompt") or payload.get("message") or "").strip()
            if not prompt:
                abort(400, description="Descreva a planilha que deve ser criada.")
            config = _provider_config_from_payload(payload)
            _check_rate_limit(f"create:{config.id}", limit=10)
            service = _chat_service({}, "", {})
            try:
                generated = service.generate_workbook_spec(prompt, config)
            except Exception as exc:  # noqa: BLE001
                _raise_llm_error(exc, config.api_key)
            spec = generated["spec"]
        elif not isinstance(spec, Mapping):
            abort(400, description="A especificação deve ser um objeto JSON.")

        try:
            result = create_project_from_spec(spec, workspace_path, config=MirrorConfig())
        except (WorkbookSpecError, ValueError) as exc:
            abort(400, description=str(exc))
        except OSError as exc:
            abort(500, description=f"Falha ao criar a planilha: {exc}")

        manifest = result.to_manifest(workspace_path)
        return (
            jsonify(
                {
                    "project": manifest,
                    "warnings": manifest.get("warnings", []),
                    "spec_nome": str(spec.get("nome") or spec.get("name") or ""),
                    "provider": (generated or {}).get("provider"),
                    "model": (generated or {}).get("model"),
                    "usage": (generated or {}).get("usage", {}),
                }
            ),
            201,
        )

    # -- erros --------------------------------------------------------------
    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException) -> Any:
        if request.path.startswith("/api/"):
            return jsonify({"error": error.description or error.name}), error.code
        return error

    @app.errorhandler(413)
    def handle_too_large(error: Any) -> Any:
        return (
            jsonify(
                {
                    "error": "Arquivo muito grande. O limite é de 32 MB.",
                }
            ),
            413,
        )

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
