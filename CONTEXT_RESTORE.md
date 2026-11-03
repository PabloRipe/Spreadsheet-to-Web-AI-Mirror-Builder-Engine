# CONTEXT_RESTORE — Spreadsheet-to-Web Mirror Engine

> Documento de restauração de contexto para qualquer sessão de LLM continuar o projeto sem perder decisões.
> Última atualização: 2026-11-02.
> Repositório: https://github.com/PabloRipe/Spreadsheet-to-Web-AI-Mirror-Builder-Engine
> Branch: `main` · Status geral: **Fase 1 e Fase 2 concluídas** (espelho + web + Multi-LLM + chat + Prompt-to-Sheet).
> Versão do pacote: `0.2.0` · Suíte: **171 testes passando**.

---

## 0. Como usar este documento (instruções para a próxima sessão de LLM)

1. Leia este arquivo antes de alterar qualquer código.
2. Leia também `PLAN.md` (decisões originais de arquitetura) e `README.md` (instalação/uso).
3. Rode a suíte antes de começar: `python -m pytest -q` — estado atual: **171 testes passando**.
4. Não quebre o contrato JSON existente (`schema_version: "1.0.0"`). Campos novos só podem ser **opcionais e retrocompatíveis**.
5. Mantenha o estilo atual: Python 3.9+, dataclasses, `from __future__ import annotations`, sem dependências desnecessárias.
6. Não coloque chaves de API, segredos ou dados sensíveis no repositório, em logs ou em respostas HTTP.
7. A Fase 2 deve **estender** o sistema existente; não reescrever o pipeline local nem a camada web já funcional.
8. Preserve o uso de `sessionStorage` para rascunhos (não migrar para `localStorage` sem decisão explícita).
9. Se precisar de contexto do escopo original, consulte `prompt.txt`.

---

## 1. Visão geral do sistema

O **Spreadsheet-to-Web Mirror Engine** transforma planilhas `.xlsx` complexas em um espelho web interativo e estilizado com Tailwind CSS. O sistema:

- lê a planilha local;
- clona a estrutura integral de todas as abas (fontes, cores, bordas, larguras, mesclagens e fórmulas);
- aplica uma **convenção de cores** que separa células **fixas** de **editáveis**;
- gera um `template.xlsx` limpo (fórmulas/estilos preservados, valores editáveis em branco);
- exporta um `mirror.json` estruturado para a interface web;
- permite preencher parcial ou integralmente, alternar entre múltiplos projetos e gerar um `.xlsx` final.

A arquitetura tem duas camadas:

1. **Módulo de Processamento Local** — Python + `openpyxl`.
2. **Camada Web** — Flask + Tailwind CSS (CDN) + JavaScript puro (sem Node.js).

A **Fase 2** adiciona inteligência: Multi-LLM, chaves de API locais e chat integrado.

---

## 2. Stack utilizada

| Camada | Tecnologia | Observações |
| --- | --- | --- |
| Linguagem | Python ≥ 3.9 | Dataclasses, type hints, `from __future__ import annotations` |
| Planilhas | `openpyxl >= 3.1` | Leitura em duas cargas: fórmulas e valores em cache |
| Web server | `Flask >= 3.0` | `server.py`, sem framework JS |
| Produção local | `waitress >= 3.0` | Opcional (`Procfile`/`README`) |
| Testes | `pytest >= 8` | 171 testes passando |
| LLM | `httpx >= 0.27` | Adaptadores diretos, streaming SSE, sem SDK pesado |
| Frontend | HTML5 + Tailwind CSS via CDN | `https://cdn.tailwindcss.com`, sem build Node |
| Frontend JS | JavaScript puro (Vanilla JS) | `web/app.js`, `web/chat.js`, `web/index.html`, `web/styles.css` |
| Estado do navegador | `sessionStorage` | Rascunhos, preferências de IA e chaves de API por aba |
| Contrato de dados | JSON | `mirror.json`, `index.json`, histórico `.chats`, API JSON |
| Empacotamento | `pyproject.toml` | Console script `spreadsheet-mirror` |

Dependências de `pyproject.toml`:

```toml
dependencies = ["openpyxl>=3.1", "Flask>=3.0"]
[project.optional-dependencies]
dev = ["pytest>=8"]
web = ["waitress>=3.0"]
llm = ["httpx>=0.27"]
```

`requirements.txt` contém: `openpyxl>=3.1`, `Flask>=3.0`, `waitress>=3.0`,
`httpx>=0.27`.

> Observação: existem `Dockerfile`, `.dockerignore` e `Procfile` no repositório, mas Docker **não** é o foco atual. O deploy local recomendado é `python server.py` ou `waitress-serve`.

---

## 3. Estrutura de diretórios e responsabilidades

```text
sps_to_web/
├── CONTEXT_RESTORE.md        # este documento
├── PLAN.md                   # plano original de arquitetura
├── README.md                 # instalação, uso e API
├── prompt.txt                # escopo original do projeto
├── pyproject.toml
├── requirements.txt
├── server.py                 # camada web Flask (API + arquivos estáticos)
├── Dockerfile / Procfile / .dockerignore
├── src/spreadsheet_mirror/
│   ├── __init__.py           # versão 0.2.0
│   ├── __main__.py           # python -m spreadsheet_mirror
│   ├── cli.py                # comandos scan e process
│   ├── config.py             # MirrorConfig (convenção de cores configurável)
│   ├── colors.py             # resolução rgb/indexed/theme + tint + tema
│   ├── styles.py             # extração, canonicalização e deduplicação de estilos
│   ├── editability.py        # regras fixo vs. editável
│   ├── reader.py             # descoberta/leitura (fórmulas + valores em cache)
│   ├── serializer.py         # construção do mirror.json
│   ├── template.py           # template.xlsx limpo + injeção de dados
│   ├── pipeline.py           # orquestração ponta a ponta + index.json
│   └── llm/
│       ├── __init__.py       # exports da camada LLM
│       ├── base.py           # LLMProvider, ChatRequest/Response/Chunk, erros
│       ├── registry.py       # catálogo/presets e fábrica de provedores
│       ├── _http.py          # utilitários httpx, erros e streaming
│       ├── providers/        # openai.py, anthropic.py, gemini.py, ollama.py
│       ├── context.py        # ContextBuilder (selection/sheet/project)
│       ├── prompts.py        # system prompts e parsing de JSON
│       ├── tools.py          # ferramentas + validate_edits/propose_edits
│       ├── chat_store.py     # histórico por projeto em .chats/<slug>.json
│       ├── service.py        # ChatService (chat, SSE, Prompt-to-Sheet)
│       └── creation.py       # spec JSON -> .xlsx -> pipeline
├── tests/                    # 171 testes (pytest)
│   ├── conftest.py
│   ├── test_colors.py
│   ├── test_styles.py
│   ├── test_editability.py
│   ├── test_reader.py
│   ├── test_serializer.py
│   ├── test_template.py
│   ├── test_cli.py
│   ├── test_web.py
│   ├── test_web_ui.py
│   ├── test_llm_providers.py
│   ├── test_llm_context.py
│   ├── test_llm_tools.py
│   ├── test_llm_prompts.py
│   ├── test_llm_service.py
│   ├── test_chat_store.py
│   ├── test_prompt_to_sheet.py
│   └── test_llm_chat_api.py
└── web/
    ├── index.html            # UI Tailwind + modal de IA + painel de chat
    ├── app.js                # estado, abas, grid, upload/export, bridge MirrorApp
    ├── chat.js               # configuração de provedor, chat, SSE e aplicação
    └── styles.css            # estilos auxiliares
```

---

## 4. Fluxo ponta a ponta

### 4.1 Processamento local (CLI)

```text
arquivo .xlsx
  → find_spreadsheets()
  → load_workbook_data()        (data_only=False + data_only=True)
  → serialize_workbook()        (estilos, células, editabilidade)
  → create_template()           (template.xlsx com editáveis em branco)
  → mirror.json + template.xlsx
  → update_index()              (index.json na raiz da saída)
```

Comandos:

```bash
spreadsheet-mirror scan caminho/planilha.xlsx
spreadsheet-mirror process caminho/planilha.xlsx -o saida/
spreadsheet-mirror process caminho/pasta -o saida/ --recursive
```

Saída:

```text
saida/
├── index.json
└── minha-planilha/
    ├── mirror.json
    └── template.xlsx
```

### 4.2 Camada web

```text
Upload (POST /api/upload, multipart/form-data, campo "file")
  → salva temporariamente
  → process_path() no workspace
  → devolve manifest do projeto (201)

Listagem (GET /api/projects)
  → lê index.json + varre pastas com mirror.json
  → devolve projetos válidos

Leitura (GET /api/projects/<slug>/mirror)
  → devolve mirror.json completo

Exportação (POST /api/projects/<slug>/export)
  → recebe JSON { "data": { "Aba": { "A1": valor } }, "filename": "..." }
  → coerce valores conforme value_type/number_format
  → fill_template() no template.xlsx
  → devolve .xlsx como anexo
```

No navegador, o usuário escolhe o projeto, alterna abas, preenche células editáveis e o rascunho é salvo automaticamente em `sessionStorage`.

### 4.3 Camada de IA (Fase 2)

```text
Configuração (modal IA, chave no sessionStorage)
  → GET /api/llm/providers (presets)
  → POST /api/llm/test (valida credencial)

Chat por projeto
  → POST /api/projects/<slug>/chat[/stream]
      {message, sheet, selection, context_mode, draft, provider{api_key}}
  → ContextBuilder(mirror.json + draft) → system prompt
  → provedor (httpx) → resposta + {"acoes": [...]}
  → validate_edits() contra editavel/mesclagens/cabeçalhos
  → histórico em <workspace>/.chats/<slug>.json
  → frontend mostra cartões Aplicar/Descartar

Aplicar
  → POST /api/projects/<slug>/chat/apply {edits}
  → _coerce_payload() → dados normalizados
  → MirrorApp.applyDraftEdits() mescla no rascunho da aba

Prompt-to-Sheet
  → POST /api/projects/create {prompt, provider}
  → LLM devolve spec JSON → validate_spec()
  → openpyxl gera .xlsx real → process_file() → mirror.json/template.xlsx
```

---

## 5. Contrato JSON

### 5.1 `mirror.json` — estrutura de topo

```json
{
  "schema_version": "1.0.0",
  "meta": {
    "source": "planilha.xlsx",
    "source_path": "C:\\caminho\\planilha.xlsx",
    "size_bytes": 123456,
    "generated_at": "2026-11-02T12:00:00+00:00",
    "config": {},
    "theme": {
      "source": "workbook",
      "colors": { "dk1": "#000000", "lt1": "#FFFFFF" },
      "font_scheme": { "major": "Calibri Light", "minor": "Calibri" },
      "index_map": { "0": "lt1", "1": "dk1" }
    },
    "warnings": [],
    "stats": { "sheets": 2, "styles": 14, "cells": 320 }
  },
  "styles": {
    "s0": {
      "font": {},
      "fill": {},
      "border": {},
      "alignment": {},
      "number_format": "General",
      "protection": {}
    }
  },
  "sheets": []
}
```

Campos de `meta`:

| Campo | Tipo | Descrição |
| --- | --- | --- |
| `source` | string | Nome do arquivo original |
| `source_path` | string | Caminho absoluto do arquivo original |
| `size_bytes` | number/null | Tamanho do arquivo |
| `generated_at` | string (ISO-8601 UTC) | Momento da geração |
| `config` | object | `MirrorConfig.to_dict()` usado na geração |
| `theme` | object | Tema resolvido (`source`, `colors`, `font_scheme`, `index_map`) |
| `warnings` | string[] | Avisos de leitura/truncamento etc. |
| `stats` | object | `{ sheets, styles, cells }` |

### 5.2 `mirror.json` — objeto de aba (`sheets[]`)

```json
{
  "name": "Planilha1",
  "state": "visible",
  "tab_color": {
    "hex": "#4F81BD",
    "type": "theme",
    "tint": 0.0,
    "theme": 4,
    "theme_name": "accent1",
    "indexed": null,
    "auto": null,
    "rgb": null
  },
  "max_row": 10,
  "max_col": 5,
  "freeze_panes": "A2",
  "default_col_width": 8.43,
  "default_row_height": 15.0,
  "base_col_width": 8,
  "columns": [
    {
      "min": 1,
      "max": 1,
      "letter": "A",
      "width": 12.5,
      "hidden": false,
      "best_fit": false,
      "collapsed": false,
      "outline_level": 0
    }
  ],
  "rows": [
    {
      "index": 1,
      "height": 20.0,
      "hidden": false,
      "collapsed": false,
      "outline_level": 0
    }
  ],
  "merged_ranges": ["A1:B2"],
  "cells": []
}
```

Campos de aba:

| Campo | Tipo | Descrição |
| --- | --- | --- |
| `name` | string | Nome da aba |
| `state` | string | `visible`, `hidden` ou `veryHidden` |
| `tab_color` | object/null | Cor resolvida da aba |
| `max_row` / `max_col` | number | Dimensões consideradas (pode ser truncado) |
| `freeze_panes` | string/null | Ex.: `"A2"` |
| `default_col_width` | number/null | Largura padrão |
| `default_row_height` | number/null | Altura padrão |
| `base_col_width` | number/null | Largura base do formato |
| `columns[]` | object[] | Metadados de colunas (min/max, letra, largura, ocultas) |
| `rows[]` | object[] | Metadados de linhas (índice, altura, ocultas) |
| `merged_ranges` | string[] | Intervalos mesclados |
| `cells[]` | object[] | Células âncora não vazias (ou com estilo) |

### 5.3 `mirror.json` — objeto de célula (`cells[]`)

```json
{
  "ref": "A1",
  "row": 1,
  "col": 1,
  "value": "Título",
  "value_type": "string",
  "formula": null,
  "cached_value": null,
  "data_type": "s",
  "editavel": false,
  "editavel_motivo": ["bold"],
  "style": "s0",
  "merged": "A1:B2",
  "rowspan": 2,
  "colspan": 2
}
```

Campos de célula:

| Campo | Tipo | Descrição |
| --- | --- | --- |
| `ref` | string | Coordenada A1 |
| `row` / `col` | number | Índice 1-based |
| `value` | any | Valor exibível (para fórmula, valor em cache quando disponível) |
| `value_type` | string | `null`, `boolean`, `number`, `datetime`, `duration`, `string`, `error` |
| `formula` | string/null | Fórmula com `=` quando aplicável |
| `cached_value` | any/null | Valor em cache da fórmula, quando lido |
| `data_type` | string/null | Tipo bruto do openpyxl (`s`, `n`, `f`, `b`, `e`, etc.) |
| `editavel` | boolean | `true` somente para células editáveis |
| `editavel_motivo` | string[] | Motivos da decisão (ver §6) |
| `style` | string | ID do estilo em `styles` (`s0`, `s1`, ...) |
| `merged` | string | Presente apenas se a célula for âncora de mesclagem |
| `rowspan` / `colspan` | number | Presentes apenas em células mescladas |

Regras de valor:

- Células com fórmula: `formula` contém o texto com `=`, `value` contém o valor em cache quando `read_cached_values=True`; caso contrário, `value` pode ser `null`.
- `Decimal` vira `float`; datas/horas viram string ISO-8601; `timedelta` vira segundos.
- Células não-âncora de mesclagem são **omitidas**.
- Células vazias só entram se `include_empty_cells=True` ou se tiverem estilo/mesclagem.

### 5.4 `mirror.json` — objeto de estilo (`styles{}`)

IDs são gerados por deduplicação canônica (`StyleRegistry`): `s0`, `s1`, ...

```json
{
  "font": {
    "name": "Calibri",
    "size": 11,
    "bold": false,
    "italic": false,
    "underline": null,
    "strike": false,
    "color": { "hex": "#000000", "type": "theme", "tint": 0.0, "theme": 1, "theme_name": "dk1" },
    "family": 2,
    "scheme": "minor",
    "vert_align": null,
    "outline": false,
    "shadow": false,
    "condense": false,
    "extend": false,
    "charset": null
  },
  "fill": {
    "kind": "pattern",
    "pattern_type": "solid",
    "fg_color": { "hex": "#FFFFFF", "type": "rgb", "tint": 0.0 },
    "bg_color": null
  },
  "border": {
    "left": { "style": "thin", "color": { "hex": "#000000", "type": "rgb" } },
    "right": null,
    "top": null,
    "bottom": null,
    "diagonal": null,
    "diagonal_direction": 0,
    "outline": false,
    "vertical": null,
    "horizontal": null
  },
  "alignment": {
    "horizontal": "left",
    "vertical": "center",
    "text_rotation": 0,
    "wrap_text": false,
    "shrink_to_fit": false,
    "indent": 0,
    "relative_indent": 0,
    "justify_last_line": false,
    "reading_order": 0
  },
  "number_format": "General",
  "protection": { "locked": true, "hidden": false }
}
```

Objeto de cor resolvido (`resolve_color`):

| Campo | Descrição |
| --- | --- |
| `hex` | Cor final `#RRGGBB` (com tint aplicado quando aplicável) |
| `type` | `rgb`, `theme`, `indexed`, `auto` ou `None` |
| `tint` | Fator de tint aplicado |
| `theme` / `theme_name` | Índice/nome do tema quando `type="theme"` |
| `indexed` | Índice da paleta quando `type="indexed"` |
| `auto` | Valor de cor automática quando aplicável |
| `rgb` | Valor RGB bruto quando `type="rgb"` |

### 5.5 `index.json` — manifesto de projetos

```json
{
  "schema_version": "1.0.0",
  "generated_at": "2026-11-02T12:00:00+00:00",
  "projects": [
    {
      "slug": "minha-planilha",
      "source": "C:\\caminho\\planilha.xlsx",
      "source_name": "planilha.xlsx",
      "mirror_json": "minha-planilha/mirror.json",
      "template_xlsx": "minha-planilha/template.xlsx",
      "warnings": [],
      "stats": { "sheets": 2, "styles": 14, "cells": 320 }
    }
  ]
}
```

### 5.6 Contrato de exportação (API)

Requisição:

```http
POST /api/projects/minha-planilha/export
Content-Type: application/json
```

```json
{
  "filename": "planilha-preenchida.xlsx",
  "data": {
    "Planilha1": {
      "B2": "Novo valor",
      "C2": 1500.5,
      "D2": "2026-11-02"
    }
  }
}
```

Regras:

- `data` deve ser objeto `{ aba: { ref: valor } }`.
- Apenas referências válidas são consideradas.
- Valores são convertidos conforme `value_type` e `number_format` da célula (datas, números com separadores, booleanos `sim/true/1`, etc.).
- Campos ausentes/`null` permanecem em branco no template.
- Fórmulas e estilos do template são preservados; o Excel recalcula ao abrir.

### 5.7 Chaves de `sessionStorage` (frontend)

Prefixo: `mirrorEngine`.

| Chave | Formato | Uso |
| --- | --- | --- |
| `mirrorEngine:draft:<slug>:<aba>` | `{ "A1": "valor", ... }` | Rascunho de uma aba |
| `mirrorEngine:lastContext` | `{ "project": "<slug>", "sheet": "<aba>" }` | Último projeto/aba |
| `mirrorEngine:lastSheet:<slug>` | string | Última aba do projeto |
| `mirrorEngine:llm:settings` | `{provider, type, model, base_url, temperature, max_tokens}` | Preferências de IA (sem chave) |
| `mirrorEngine:llm:key:<provider>` | string | Chave de API da aba (sensível) |
| `mirrorEngine:llm:ui` | `{mode, contextMode}` | Preferências do painel de chat |

> `sessionStorage` é limpo ao fechar a aba. Isso é intencional (privacidade). Não trocar por `localStorage` sem decisão explícita. A chave de API fica **somente** em `mirrorEngine:llm:key:<provider>` e nunca é persistida no servidor.

---

## 6. Regra de Convenção de Cores (fixo vs. editável)

Implementada em `config.py` (`MirrorConfig`) e `editability.py` (`determine_editability`). A ordem é **first-match-wins** (a primeira regra que casar decide).

### 6.1 Ordem oficial das regras

1. **Fórmula** (`data_type == "f"` ou valor começa com `=`) → **fixa** (`formula`).
2. **Não-âncora de mesclagem** → **fixa/omitida** (`merged_non_anchor`).
3. **Âncora de mesclagem** com `fixed_if_merged=True` (padrão) → **fixa** (`merged`).
4. **Cabeçalho explícito** (`header_rows` ou `header_cols`) → **fixa** (`header`).
5. **Preenchimento em `fixed_fill_colors`** → **fixa** (`fixed_fill`).
6. **Preenchimento em `editable_fill_colors`** → **editável** (`editable_fill`).
7. **Preenchimento sólido diferente de branco** (`#FFFFFF`) → **fixa** (`formatted_fill`).
8. **Negrito** com `fixed_if_bold=True` (padrão) → **fixa** (`bold`).
9. **Itálico** com `fixed_if_italic=True` → **fixa** (`italic`).
10. **Sublinhado** com `fixed_if_underline=True` → **fixa** (`underline`).
11. **Cor de fonte em `fixed_font_colors`** → **fixa** (`font_color`).
12. **Borda visível** com `fixed_if_border=True` → **fixa** (`border`).
13. **Sem preenchimento** e `treat_no_fill_as_editable=False` → **fixa** (`no_fill`).
14. **Caso contrário** → **editável** (`default_editable`).

Os motivos retornados em `editavel_motivo` são exatamente as strings entre parênteses acima.

### 6.2 Defaults do `MirrorConfig`

| Campo | Default | Efeito |
| --- | --- | --- |
| `header_rows` | `()` | Linhas fixas explícitas |
| `header_cols` | `()` | Colunas fixas explícitas |
| `fixed_if_bold` | `True` | Negrito = fixa |
| `fixed_if_italic` | `False` | Itálico = fixa? |
| `fixed_if_underline` | `False` | Sublinhado = fixa? |
| `fixed_if_border` | `False` | Borda = fixa? |
| `fixed_if_merged` | `True` | Âncora mesclada = fixa |
| `fixed_font_colors` | `()` | Cores de fonte fixas |
| `fixed_fill_colors` | `()` | Cores de fundo fixas |
| `editable_fill_colors` | `("#FFFFFF",)` | Branco = editável |
| `treat_no_fill_as_editable` | `True` | Sem fundo = editável |
| `ignore_hidden_sheets` | `False` | Ignorar abas ocultas |
| `max_cells_per_sheet` | `200000` | Truncamento de abas gigantes |
| `read_cached_values` | `True` | Ler valores em cache de fórmulas |
| `include_empty_cells` | `False` | Incluir células vazias |
| `clear_editable_values` | `True` | Limpar editáveis no template |
| `extensions` | `(".xlsx",)` | Extensões aceitas |
| `recursive` | `False` | Busca recursiva |
| `theme_colors` | `{}` | Override de cores do tema |
| `output_dir_name` | `"mirror_output"` | Pasta de saída |

Configuração pode ser sobrescrita por JSON via `--config` na CLI ou por flags (`--header-rows`, `--header-cols`, `--no-fixed-if-bold`, etc. — consulte `spreadsheet_mirror.config.MirrorConfig`).

### 6.3 Resolução de cores

`colors.py` resolve cores `rgb`, `indexed`, `theme` e `auto`, aplicando `tint` quando presente:

- `normalize_hex` aceita `RRGGBB` ou `AARRGGBB`, com/sem `#`, e devolve `#RRGGBB`.
- Mapeamento de tema OOXML: `0→lt1`, `1→dk1`, `2→lt2`, `3→dk2`, `4..9→accent1..6`, `10→hlink`, `11→folHlink`.
- Fallback de tema padrão do Office em `DEFAULT_THEME_COLORS`.
- `ThemePalette.from_workbook()` lê o tema real do arquivo; `theme_colors` da configuração pode sobrescrever.
- `tab_color` e cores de estilo são serializadas como objeto resolvido (não apenas string hex).

---

## 7. Estado atual — Fase 1 concluída

### 7.1 Entregue e funcionando

- **Leitura local**: arquivo único ou diretório, `.xlsx` (e extensões configuráveis), com leitura dupla (`data_only=False` e `data_only=True`).
- **Clone estrutural**: abas visíveis/ocultas/veryHidden, estados, cores de aba, mesclagens, larguras/alturas, linhas/colunas ocultas, freeze panes, estilos, bordas, alinhamento, formatos numéricos e proteção.
- **Convenção de cores**: regras first-match-wins configuráveis; resolução de cores de tema/indexed/rgb com tint.
- **Serialização**: `mirror.json` com `schema_version "1.0.0"`, estilos deduplicados e células com flags de editabilidade.
- **Template**: `template.xlsx` com fórmulas/estilos/mesclagens preservados e valores editáveis limpos.
- **Pipeline em lote**: `process_file`, `process_path`, `update_index`, slugs únicos (`-2`, `-3`...), tratamento de falhas por arquivo.
- **CLI**: `scan` e `process`, com `--recursive`, `--extensions`, `--json-only`, `--template-only`, `--overwrite`, `--verbose` e flags de configuração.
- **Camada web MVP** (já implementada):
  - Flask com API e arquivos estáticos;
  - upload `.xlsx` (limite 32 MB);
  - listagem de projetos;
  - leitura de `mirror.json`;
  - exportação `.xlsx` preenchido;
  - UI Tailwind com abas, grade, células editáveis/fixas, múltiplos projetos;
  - autosave em `sessionStorage`;
  - limpeza de rascunho por aba.
- **Camada de IA (Fase 2)**:
  - modal de provedor/modelo/chave (chave no `sessionStorage`);
  - chat contextual com modos seleção/aba/projeto;
  - streaming SSE e histórico por projeto;
  - aplicação de edições somente em células editáveis;
  - Prompt-to-Sheet com validação e geração de `.xlsx` real.
- **Testes**: **171 testes passando** (`python -m pytest -q`).

### 7.2 API HTTP existente

| Método | Rota | Descrição |
| --- | --- | --- |
| GET | `/` | Interface web (`web/index.html`) |
| GET | `/favicon.ico` | Favicon ou 204 |
| GET | `/api/health` | Status + quantidade de projetos |
| GET | `/api/projects` | Lista de projetos (index + varredura) |
| GET | `/api/projects/<slug>/mirror` | Retorna `mirror.json` do projeto |
| POST | `/api/upload` | Upload `.xlsx` (`multipart/form-data`, campo `file`); retorna 201 |
| POST | `/api/projects/<slug>/export` | Gera `.xlsx` final a partir de `{data: ...}` |
| GET | `/api/llm/providers` | Provedores/modelos padrão, sem segredos |
| GET | `/api/llm/models?provider=<id>` | Modelos sugeridos do provedor |
| POST | `/api/llm/test` | Valida credencial/provedor (chave em memória) |
| POST | `/api/projects/<slug>/chat` | Chat contextual (resposta completa) |
| POST | `/api/projects/<slug>/chat/stream` | Chat com streaming SSE |
| GET | `/api/projects/<slug>/chat/history` | Histórico persistido do projeto |
| DELETE | `/api/projects/<slug>/chat/history` | Limpa o histórico do projeto |
| POST | `/api/projects/<slug>/chat/apply` | Valida edições e devolve dados normalizados |
| POST | `/api/projects/create` | Prompt-to-Sheet (`prompt` ou `spec`) |

### 7.3 Limitações conhecidas

- O round-trip do openpyxl preserva fórmulas, estilos, mesclagens e dimensões, mas **não** preserva gráficos, imagens, tabelas dinâmicas, macros VBA ou parte da formatação condicional.
- Células com fórmula usam valor em cache quando disponível; sem cache, o valor pode ser `null` até o Excel recalcular.
- Planilhas muito grandes são truncadas por `max_cells_per_sheet` (200.000 por padrão), com aviso em `meta.warnings`.
- O frontend usa Tailwind via CDN (sem build); não há bundler nem Node.js.

### 7.4 Comandos úteis

```bash
# instalação completa (dev + web)
pip install -e ".[dev,web]"

# testes
python -m pytest -q

# processar planilha
spreadsheet-mirror process caminho/planilha.xlsx -o saida/

# subir servidor
python server.py
# ou produção local
waitress-serve --listen=0.0.0.0:5000 server:app
```

Variáveis de ambiente: `PORT` (padrão `5000`), `MIRROR_WORKSPACE` (padrão `mirror_output`).

---

## 8. Fase 2 — implementação executada

> Escopo: **Módulo Multi-LLM**, **chaves locais no navegador**, **Chat Integrado** e
> **Prompt-to-Sheet**. Tudo abaixo foi implementado e coberto por testes.
> A suíte final tem **171 testes verdes**.

### Princípios adotados

- **Local-first**: o motor continua funcionando sem internet e sem LLM.
- **Não quebrar contrato**: `schema_version` continua `1.0.0`; nada mudou no `mirror.json`.
- **Sem segredos no servidor**: a chave fica no `sessionStorage` e é enviada por
  requisição; o Flask apenas a usa em memória, nunca grava/loga/devolve.
- **Sem reescrever o frontend**: Tailwind CDN + Vanilla JS.
- **Sem Docker/Node** como requisito.
- **LLM propõe, usuário confirma**: ferramentas são puras; a exportação existente aplica.

### F2.1 — Configuração stateless e chaves no `sessionStorage` (concluído)

**Decisão:** substituir o keystore criptografado em disco por um modelo stateless.
O `prompt.txt` v2.0 exige privacidade total: o servidor local **não grava chaves**.
Portanto não há `cryptography`, `keyring`, `platformdirs`, `keys.enc` nem
`MIRROR_MASTER_KEY`.

**Arquivos implementados:**

```text
src/spreadsheet_mirror/llm/base.py       # ProviderConfig público + erros
src/spreadsheet_mirror/llm/registry.py   # catálogo/presets + validação
tests/test_llm_providers.py
tests/test_web_ui.py
```

**Comportamento:**

1. `ProviderConfig` recebe `id`, `type`, `model`, `base_url`, `api_key`,
   `temperature`, `max_tokens`, `timeout_s` por payload; `public_dict()` nunca
   inclui a chave.
2. O frontend guarda preferências em `mirrorEngine:llm:settings` e a chave em
   `mirrorEngine:llm:key:<provider>` (sessionStorage).
3. Endpoints: `GET /api/llm/providers`, `GET /api/llm/models`,
   `POST /api/llm/test`. Não existem endpoints de cadastro/listagem de chaves.
4. `.gitignore` ignora `*.enc` apenas como salvaguarda; nenhum arquivo de chave é
   criado.

**Critérios de aceitação — atendidos:**

- `GET /api/llm/providers` e `/api/llm/test` nunca retornam o texto da chave.
- Logs e mensagens de erro passam por `redact_secrets`.
- Testes verificam `public_dict`, ausência de chave na UI e payloads inválidos.
- A chave não sobrevive ao fechamento da aba — comportamento intencional.

### F2.2 — Módulo Multi-LLM (concluído)

**Objetivo:** suportar múltiplos provedores com uma interface única.

**Arquivos novos:**

```text
src/spreadsheet_mirror/llm/base.py
src/spreadsheet_mirror/llm/registry.py
src/spreadsheet_mirror/llm/providers/__init__.py
src/spreadsheet_mirror/llm/providers/openai.py
src/spreadsheet_mirror/llm/providers/anthropic.py
src/spreadsheet_mirror/llm/providers/gemini.py
src/spreadsheet_mirror/llm/providers/ollama.py
src/spreadsheet_mirror/llm/providers/openai_compatible.py
tests/test_llm_providers.py
```

**Tarefas:**

1. Definir interface abstrata:

```python
class LLMProvider(ABC):
    id: str
    label: str

    def validate(self) -> ValidationResult: ...
    def list_models(self) -> list[str]: ...
    def chat(self, request: ChatRequest) -> ChatResponse: ...
    def stream(self, request: ChatRequest) -> Iterator[ChatChunk]: ...
```

2. `ChatRequest`: `messages`, `system_prompt`, `model`, `temperature`, `max_tokens`, `tools`, `response_format`, `context`.
3. `ChatResponse`: `text`, `tool_calls`, `usage`, `provider`, `model`, `raw` (opcional).
4. `ChatChunk` para streaming (SSE).
5. Adaptadores:
   - OpenAI e OpenAI-compatible (base URL configurável);
   - Anthropic;
   - Gemini;
   - Ollama local (HTTP em `http://localhost:11434` por padrão).
6. `registry.py`: carrega `LLMSettings`, instancia provedores sob demanda, resolve `default_provider`, aplica cadeia de fallback.
7. Taxonomia de erros: `AuthError`, `RateLimitError`, `TimeoutError`, `ProviderError`.
8. Usar `httpx` diretamente (sem LangChain/SDK pesado) para manter o controle e as dependências previsíveis.
9. Testes com `httpx.MockTransport` (sem chamadas reais).

**Critérios de aceitação:**

- Pelo menos **dois provedores** configuráveis e selecionáveis (recomendado: Ollama local + OpenAI-compatible).
- Troca de provedor por configuração sem alterar código.
- Fallback funciona quando o provedor primário falha.
- Nenhum teste faz chamada de rede real.

### F2.3 — Context builder e ferramentas de planilha (concluído)

**Objetivo:** transformar `mirror.json` em contexto compacto e permitir ações seguras via tool calling.

**Arquivos novos:**

```text
src/spreadsheet_mirror/llm/context.py
src/spreadsheet_mirror/llm/tools.py
tests/test_llm_context.py
tests/test_llm_tools.py
```

**Tarefas:**

1. `ContextBuilder` com modos:
   - `selection`: aba + intervalo selecionado;
   - `sheet`: aba inteira resumida;
   - `project`: resumo de todas as abas.
2. Resumo deve conter:
   - meta do projeto e abas (nome, estado, dimensões, mesclagens);
   - cabeçalhos detectados e contagem de células fixas/editáveis;
   - para o intervalo selecionado: `ref`, `value`, `formula`, `value_type`, `editavel`, resumo de estilo;
   - nunca enviar todo o `styles` por padrão; enviar apenas estilos usados na seleção.
3. Limite de tokens: `max_context_cells` (padrão 400); truncar linhas/colunas com aviso no prompt.
4. Ferramentas (tool calling):
   - `read_range(sheet, range)`;
   - `search_cells(sheet, query, limit)`;
   - `summarize_sheet(sheet)`;
   - `suggest_formula(sheet, target_ref, intent)`;
   - `propose_edits(sheet, edits: [{ref, value}])`.
5. `propose_edits` deve:
   - validar `ref`, existência da aba e `editavel == true`;
   - rejeitar fórmulas em células fixas e referências mescladas não-âncora;
   - retornar apenas uma proposta normalizada (`{sheet: {ref: value}}`), **sem gravar** no `mirror.json`/`template.xlsx`.

**Critérios de aceitação:**

- Context builder não envia segredos nem o workbook inteiro por acidente.
- Edições em células fixas são rejeitadas com erro claro.
- `propose_edits` é puro (sem efeitos colaterais em disco).
- Testes cobrem truncamento, seleção, mesclagens e rejeições.

### F2.4 — API de chat e persistência de histórico (concluído)

**Objetivo:** expor o chat por projeto/aba e persistir histórico sem perder contexto.

**Arquivos novos/alterados:**

```text
src/spreadsheet_mirror/llm/chat_store.py
src/spreadsheet_mirror/llm/service.py
server.py (novas rotas ou blueprint)
tests/test_llm_chat_api.py
```

**Tarefas:**

1. `ChatStore` local em `<workspace>/.chats/<slug>.json`:
   - escrita atômica;
   - limite de mensagens por `max_history_messages`;
   - estrutura: `{schema_version, project_slug, messages: [{role, content, created_at, provider?, model?, tool_calls?}]}`;
   - nunca armazenar chaves.
2. `ChatService`:
   - carrega `mirror.json` + rascunho atual (recebido no payload ou lido de um store de rascunho do servidor, se existir);
   - monta contexto com `ContextBuilder`;
   - chama provedor configurado;
   - retorna resposta + tool calls + edições sugeridas.
3. Endpoints:
   - `GET /api/llm/providers` → provedores habilitados e modelos;
   - `GET /api/llm/models?provider=<id>`;
   - `POST /api/projects/<slug>/chat` → `{message, sheet, selection?, provider?, model?}`;
   - `POST /api/projects/<slug>/chat/stream` → SSE;
   - `GET /api/projects/<slug>/chat/history`;
   - `DELETE /api/projects/<slug>/chat/history`;
   - `POST /api/projects/<slug>/chat/apply` → valida `{edits}` e devolve dados normalizados para o frontend mesclar no rascunho.
4. Tratamento de erros consistente com o restante da API (`{error: "..."}` e status adequado).
5. Testes com provedor fake (sem rede).

**Critérios de aceitação:**

- Histórico persiste por projeto e sobrevive a reinício do servidor.
- `chat/apply` nunca aceita célula fixa.
- Streaming funciona no Flask (SSE) e é testável com provedor fake.
- Nenhum endpoint retorna chave.

### F2.5 — Interface de chat integrada (concluído)

**Objetivo:** disponibilizar configuração de provedores e chat dentro da UI existente.

**Arquivos alterados/novos:**

```text
web/index.html        # painel/modal de configurações + painel de chat
web/chat.js           # novo módulo de chat (Vanilla JS)
web/app.js            # integração com projeto/aba/seleção atuais
web/styles.css        # estilos auxiliares
```

**Tarefas:**

1. Modal de configurações:
   - provedor padrão, modelo, base URL, temperatura;
   - cadastro/remoção de chave (campo senha, nunca exibida de volta);
   - botão “Testar conexão”.
2. Painel de chat:
   - seletor de contexto: seleção atual / aba / projeto;
   - histórico com streaming;
   - cartões de tool calls e edições propostas com “Aplicar” / “Descartar”;
   - indicador de provedor/modelo e uso de tokens quando disponível.
3. Persistência de UI em `sessionStorage` (preferências de IA; a chave fica em
   chave separada `mirrorEngine:llm:key:<provider>`): `mirrorEngine:llm:ui`.
4. Aplicar edições:
   - receber dados normalizados de `chat/apply`;
   - mesclar no `state.draft` da aba atual;
   - atualizar inputs e salvar em `sessionStorage`;
   - o usuário continua exportando pelo botão existente.
5. Acessibilidade: foco no modal, `aria-*`, contraste, teclado.

**Critérios de aceitação:**

- Chat responde sobre a aba/projeto atual.
- “Aplicar” atualiza apenas células editáveis e não perde rascunho.
- Nenhuma chave aparece no DOM, no console ou em objetos de configuração não
  intencionais; ela existe apenas em `mirrorEngine:llm:key:<provider>`.
- UI funciona com provedor local (Ollama) e com provedor remoto configurado.

### F2.6 — Hardening, documentação e release (concluído)

**Objetivo:** fechar a Fase 2 com segurança, testes e documentação.

**Tarefas:**

1. Segurança:
   - validar `base_url` (apenas `http/https`, sem `file://`); opcional allowlist;
   - timeouts e limites de tamanho de resposta;
   - rate limit simples por sessão/projeto;
   - redigir chaves em logs e mensagens de erro;
   - sanitizar HTML no frontend (já há `escapeHtml`).
2. Testes:
   - manter os 101 originais verdes;
   - adicionar testes de providers/context/tools/prompts/chat/creation/UI;
   - teste de integração Flask com provedor fake.
3. Documentação:
   - atualizar `README.md` (configuração, provedores, chat);
   - atualizar `PLAN.md` (decisões da Fase 2);
   - atualizar este `CONTEXT_RESTORE.md`.
4. Versionamento: `pyproject.toml` e `__init__.py` em `0.2.0`.
5. Commit/deploy (quando solicitado pelo usuário).

**Critérios de aceitação:**

- `python -m pytest -q` verde (**171 testes**).
- Nenhum segredo no repositório (`git grep` por padrões de chave).
- Documentação cobre instalação, configuração de provedores, uso do chat e limitações.

### Ordem de execução (executada)

1. **F2.1** — configuração stateless + endpoints + testes.
2. **F2.2** — interface de provedores + adaptadores + registry + testes.
3. **F2.3** — context builder + tools + testes.
4. **F2.4** — chat store + service + endpoints + testes.
5. **F2.5** — UI de configurações + chat + integração com rascunho.
6. **F2.6** — hardening + docs + release.

### Definition of Done da Fase 2

- Pelo menos 2 provedores configuráveis (Ollama local + remotos/compatíveis).
- Chaves no `sessionStorage` do navegador; servidor stateless e sem persistência.
- Chat contextual por projeto/aba com histórico persistido.
- Edições sugeridas pelo LLM só podem ser aplicadas em células `editavel: true`.
- Exportação `.xlsx` continua funcionando pelo fluxo existente.
- Prompt-to-Sheet gera projeto completo com fórmulas reais.
- Testes existentes + novos passando; documentação atualizada.

---

## 9. Decisões arquiteturais já tomadas (não reabrir sem justificativa)

1. **Contrato JSON como interface estável** entre backend e frontend; `schema_version` versiona mudanças.
2. **Convenção de cores first-match-wins** e configurável via `MirrorConfig` (JSON/CLI).
3. **Duas cargas do workbook** (fórmulas + valores em cache) para preservar fórmulas e exibir resultados.
4. **Template separado do espelho**: `mirror.json` descreve; `template.xlsx` é a base para o arquivo final.
5. **Editáveis são limpos no template** (`clear_editable_values=True`), preservando fórmulas/estilos.
6. **Slugs únicos por pasta de saída**; conflitos recebem sufixo `-2`, `-3`, ...
7. **Frontend sem build**: Tailwind CDN + Vanilla JS.
8. **Rascunhos em `sessionStorage`**, não no servidor e não em `localStorage`.
9. **Flask** como servidor web (não FastAPI).
10. **Segurança de upload**: limite 32 MB, apenas `.xlsx`, nomes saneados, slug validado por regex.
11. **Chaves de LLM ficam no `sessionStorage` do navegador**; o servidor é stateless e nunca grava/loga chaves.
12. **LLM propõe, usuário confirma**: sem escrita direta em disco pelo modelo.
13. **Streaming via SSE** com fallback para resposta completa.
14. **Prompt-to-Sheet**: spec JSON validada → openpyxl → pipeline normal.
15. **Histórico de chat local** em `<workspace>/.chats/<slug>.json`, sem credenciais.
16. **Antialucinação de coordenadas**: o system prompt proíbe chutar células;
    `search_cells` aceita rótulo ou coordenada, pesquisa em todas as abas quando
    `sheet` é omitido e retorna `campos_editaveis_vizinhos`.
17. **Busca estrutural automática + evidência**: antes de chamar o LLM, o serviço
    busca termos/refs do pedido; toda action precisa estar em `evidence`
    (contexto, busca ou tool) senão é rejeitada como `coordenada_nao_verificada`.

---

## 10. Armadilhas conhecidas e pontos de atenção

- **Não alterar** `SCHEMA_VERSION` sem atualizar `serializer.py`, `server.py`, `pipeline.py` e testes.
- **Células mescladas**: apenas a âncora é serializada; não-âncoras são omitidas. Ao aplicar edições, valide isso.
- **Cores de tema**: o índice OOXML não é a ordem do XML; use `THEME_INDEX_TO_NAME`.
- **Fórmulas sem cache**: `value` pode ser `null`; não trate como célula vazia para editabilidade (fórmula sempre é fixa).
- **Células com estilo mas sem valor**: podem aparecer no JSON por causa de `has_style`; não assuma que todas têm conteúdo.
- **Truncamento**: `max_cells_per_sheet` pode cortar linhas; avisos vão para `meta.warnings`.
- **Upload**: o nome do arquivo é saneado; não confie no nome original para caminhos.
- **Exportação**: valores são coagidos; strings vazias viram `None`; datas aceitam vários formatos.
- **sessionStorage**: pode falhar (modo privado/limites); o frontend já trata falhas com `console.warn`.
- **Chaves de API**: nunca persistir no servidor/disco/logs; sempre redigir com `redact_secrets`. A chave Gemini vai na query string — erros do httpx são redigidos, mas cuidado ao adicionar novos logs.
- **SSE**: use `stream_with_context`; erros dentro do gerador viram evento `{"type":"error"}` com a chave redigida.
- **Prompt-to-Sheet**: valide refs/limites antes de criar células; fórmulas devem começar com `=`; nunca aceitar `dict`/`list` como valor de célula.
- **Chat apply**: `chat/apply` revalida contra `mirror.json`; não confie apenas no frontend.
- **Coordenadas alucinadas**: `coordenada_nao_verificada` significa que a célula não apareceu no contexto, na busca automática nem em tool call. Rótulos fixos devem ser ligados ao vizinho editável via `campos_editaveis_vizinhos` (direita/abaixo).
- **Busca**: `search_cells(document, None, termo)` pesquisa todas as abas; com `sheet` inexistente ainda levanta `ValueError`.
- **Histórico**: `.chats/<slug>.json` usa escrita atômica (`os.replace`); não gravar payload de provedor com chave.
- **Windows/PowerShell**: o ambiente atual é Windows; cuidado com `LF`/`CRLF` e caminhos.

---

## 11. Checklist para retomar a implementação

- [x] Ler `CONTEXT_RESTORE.md`, `PLAN.md` e `README.md`.
- [x] Rodar `python -m pytest -q` e confirmar 171 testes verdes.
- [x] Confirmar que o contrato JSON não foi quebrado (`schema_version` 1.0.0).
- [x] Implementar F2.1 (config stateless + chaves no sessionStorage) com testes.
- [x] Implementar F2.2 (multi-LLM) com testes usando mock.
- [x] Implementar F2.3 (contexto + ferramentas) com testes.
- [x] Implementar F2.4 (chat API + histórico) com testes.
- [x] Implementar F2.5 (UI de chat + configurações).
- [x] Implementar Prompt-to-Sheet com testes.
- [x] Executar F2.6 (hardening, docs, release 0.2.0).
- [x] Atualizar este documento.
- [ ] Deploy no repositório remoto (executado ao final desta sessão).
