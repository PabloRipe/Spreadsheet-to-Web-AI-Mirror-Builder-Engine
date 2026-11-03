"""Orquestração do processamento: leitura, JSON, template e índice."""

from __future__ import annotations

import datetime as _dt
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import MirrorConfig
from .reader import WorkbookData, find_spreadsheets, load_workbook_data
from .serializer import SCHEMA_VERSION, serialize_workbook
from .template import create_template


class PipelineError(Exception):
    """Erro durante o processamento de um arquivo."""


@dataclass
class ProjectResult:
    source: Path
    slug: str
    output_dir: Path
    mirror_json: Path | None = None
    template_xlsx: Path | None = None
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_manifest(self, base: Path) -> dict[str, Any]:
        def relative(path: Path | None) -> str | None:
            if path is None:
                return None
            try:
                return path.relative_to(base).as_posix()
            except ValueError:
                return str(path)

        return {
            "slug": self.slug,
            "source": str(self.source.resolve()),
            "source_name": self.source.name,
            "mirror_json": relative(self.mirror_json),
            "template_xlsx": relative(self.template_xlsx),
            "warnings": list(self.warnings),
            "stats": dict(self.stats),
        }


@dataclass
class BatchResult:
    projects: list[ProjectResult] = field(default_factory=list)
    failures: list[tuple[Path, str]] = field(default_factory=list)
    index_path: Path | None = None


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-").lower()
    return text or "planilha"


def _unique_slug(base: str, used: set[str], output_root: Path, overwrite: bool) -> str:
    slug = base
    counter = 2
    while True:
        taken = slug in used
        exists = (output_root / slug).exists()
        if not taken and (overwrite or not exists):
            used.add(slug)
            return slug
        slug = f"{base}-{counter}"
        counter += 1


def process_file(
    source: str | Path,
    output_root: str | Path,
    config: MirrorConfig | None = None,
    *,
    write_json: bool = True,
    write_template: bool = True,
    overwrite: bool = False,
    slug: str | None = None,
) -> ProjectResult:
    """Processa um único ``.xlsx`` e grava ``mirror.json``/``template.xlsx``."""
    cfg = config or MirrorConfig()
    file_path = Path(source)
    base = Path(output_root)
    chosen_slug = slug or slugify(file_path.stem)
    project_dir = base / chosen_slug

    if project_dir.exists() and not overwrite:
        raise PipelineError(
            f"A pasta de saída já existe: {project_dir}. Use --overwrite para substituir."
        )
    project_dir.mkdir(parents=True, exist_ok=True)

    data: WorkbookData = load_workbook_data(file_path, cfg)
    document, editable_by_sheet, warnings = serialize_workbook(data, cfg)

    result = ProjectResult(
        source=file_path,
        slug=chosen_slug,
        output_dir=project_dir,
        warnings=list(warnings),
        stats=document.get("meta", {}).get("stats", {}),
    )

    if write_json:
        mirror_path = project_dir / "mirror.json"
        with open(mirror_path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        result.mirror_json = mirror_path

    if write_template:
        template_path = project_dir / "template.xlsx"
        create_template(
            data.wb_formulas,
            editable_by_sheet,
            template_path,
            clear_values=cfg.clear_editable_values,
        )
        result.template_xlsx = template_path

    return result


def update_index(output_root: str | Path, projects: list[ProjectResult]) -> Path:
    """Atualiza (ou cria) o ``index.json`` da pasta de saída."""
    base = Path(output_root)
    base.mkdir(parents=True, exist_ok=True)
    index_path = base / "index.json"

    existing: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "projects": []}
    if index_path.exists():
        try:
            loaded = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, json.JSONDecodeError):
            pass

    by_slug = {
        item.get("slug"): item
        for item in existing.get("projects", [])
        if isinstance(item, dict) and item.get("slug")
    }
    for project in projects:
        by_slug[project.slug] = project.to_manifest(base)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "projects": sorted(by_slug.values(), key=lambda item: item.get("slug", "")),
    }
    index_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return index_path


def process_path(
    path: str | Path,
    output_root: str | Path,
    config: MirrorConfig | None = None,
    *,
    write_json: bool = True,
    write_template: bool = True,
    overwrite: bool = False,
) -> BatchResult:
    """Processa um arquivo ou diretório e atualiza o índice ao final."""
    cfg = config or MirrorConfig()
    sources = find_spreadsheets(path, cfg)
    result = BatchResult()
    used_slugs: set[str] = set()
    base = Path(output_root)

    for source in sources:
        base_slug = slugify(source.stem)
        chosen = _unique_slug(base_slug, used_slugs, base, overwrite)
        try:
            project = process_file(
                source,
                base,
                cfg,
                write_json=write_json,
                write_template=write_template,
                overwrite=overwrite,
                slug=chosen,
            )
            result.projects.append(project)
        except Exception as exc:  # noqa: BLE001 - continuamos no lote
            result.failures.append((source, str(exc)))

    if result.projects:
        result.index_path = update_index(base, result.projects)
    return result
