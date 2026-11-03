"""Interface de linha de comando do Spreadsheet-to-Web Mirror Engine."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .config import MirrorConfig
from .pipeline import BatchResult, process_path
from .reader import SpreadsheetError, find_spreadsheets


def _add_config_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        help="Arquivo JSON com a configuração da convenção de cores.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Busca planilhas recursivamente em subdiretórios.",
    )
    parser.add_argument(
        "--extensions",
        nargs="+",
        metavar="EXT",
        help="Extensões aceitas (padrão: .xlsx).",
    )
    parser.add_argument(
        "--header-rows",
        nargs="+",
        type=int,
        metavar="N",
        help="Números de linha (base 1) tratados como cabeçalho fixo.",
    )
    parser.add_argument(
        "--header-cols",
        nargs="+",
        type=int,
        metavar="N",
        help="Números de coluna (base 1) tratados como cabeçalho fixo.",
    )
    parser.add_argument(
        "--no-fixed-if-bold",
        action="store_true",
        help="Não tratar automaticamente células em negrito como fixas.",
    )
    parser.add_argument(
        "--include-empty-cells",
        action="store_true",
        help="Incluir no JSON todas as células do intervalo, mesmo vazias.",
    )
    parser.add_argument(
        "--max-cells",
        type=int,
        metavar="N",
        help="Limite de células por aba (padrão: 200000).",
    )
    parser.add_argument(
        "--no-cached-values",
        action="store_true",
        help="Não tentar ler valores em cache das fórmulas.",
    )


def _build_config(args: argparse.Namespace) -> MirrorConfig:
    config = MirrorConfig.load(args.config) if args.config else MirrorConfig()

    if args.recursive:
        config.recursive = True
    if args.extensions:
        config.extensions = tuple(args.extensions)
    if args.header_rows is not None:
        config.header_rows = tuple(args.header_rows)
    if args.header_cols is not None:
        config.header_cols = tuple(args.header_cols)
    if args.no_fixed_if_bold:
        config.fixed_if_bold = False
    if args.include_empty_cells:
        config.include_empty_cells = True
    if args.max_cells is not None:
        config.max_cells_per_sheet = args.max_cells
    if args.no_cached_values:
        config.read_cached_values = False
    return config


def _print_batch(result: BatchResult, verbose: bool) -> None:
    print(f"Projetos gerados: {len(result.projects)}")
    for project in result.projects:
        print(f"  - {project.slug}  ({project.output_dir})")
        if verbose:
            if project.mirror_json:
                print(f"      mirror.json  : {project.mirror_json}")
            if project.template_xlsx:
                print(f"      template.xlsx: {project.template_xlsx}")
            if project.stats:
                stats = project.stats
                print(
                    "      abas: {sheets} | estilos: {styles} | células: {cells}".format(
                        sheets=stats.get("sheets", 0),
                        styles=stats.get("styles", 0),
                        cells=stats.get("cells", 0),
                    )
                )
            for warning in project.warnings:
                print(f"      aviso: {warning}")
    if result.failures:
        print(f"Falhas: {len(result.failures)}", file=sys.stderr)
        for source, error in result.failures:
            print(f"  - {source}: {error}", file=sys.stderr)
    if result.index_path:
        print(f"Índice: {result.index_path}")


def _command_scan(args: argparse.Namespace) -> int:
    config = _build_config(args)
    try:
        found = find_spreadsheets(args.path, config)
    except SpreadsheetError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    if not found:
        print("Nenhuma planilha encontrada.")
        return 0
    for path in found:
        print(path)
    print(f"Total: {len(found)}")
    return 0


def _command_process(args: argparse.Namespace) -> int:
    config = _build_config(args)
    if args.json_only and args.template_only:
        print("Erro: --json-only e --template-only são mutuamente exclusivos.", file=sys.stderr)
        return 2
    write_json = not args.template_only
    write_template = not args.json_only

    try:
        result = process_path(
            args.path,
            args.output,
            config,
            write_json=write_json,
            write_template=write_template,
            overwrite=args.overwrite,
        )
    except SpreadsheetError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2

    _print_batch(result, verbose=args.verbose)
    return 1 if result.failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spreadsheet-mirror",
        description="Clona planilhas .xlsx em um espelho JSON + template limpo.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="Lista planilhas encontradas em um caminho.")
    scan.add_argument("path", type=Path, help="Arquivo ou diretório a inspecionar.")
    _add_config_arguments(scan)
    scan.set_defaults(func=_command_scan)

    process = subparsers.add_parser(
        "process",
        help="Processa planilhas e gera mirror.json/template.xlsx.",
    )
    process.add_argument("path", type=Path, help="Arquivo ou diretório de planilhas.")
    process.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("mirror_output"),
        help="Diretório de saída (padrão: ./mirror_output).",
    )
    process.add_argument(
        "--overwrite",
        action="store_true",
        help="Sobrescreve pastas de saída existentes.",
    )
    process.add_argument("--json-only", action="store_true", help="Gera apenas mirror.json.")
    process.add_argument("--template-only", action="store_true", help="Gera apenas template.xlsx.")
    process.add_argument("-v", "--verbose", action="store_true", help="Exibe detalhes da saída.")
    _add_config_arguments(process)
    process.set_defaults(func=_command_process)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
