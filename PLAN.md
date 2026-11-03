# Spreadsheet-to-Web Mirror Engine — Plano de Implementação

> Documento salvo em 2026-11-02. Descreve a arquitetura e as decisões técnicas do projeto.

## Visão geral

Transformar arquivos `.xlsx` complexos em uma aplicação web interativa estilizada com
Tailwind CSS. O fluxo é dividido em duas camadas:

1. **Módulo de Processamento Local (Python / openpyxl)** — objeto desta primeira fase.
   - Lê o `.xlsx` local.
   - Clona a estrutura integral (abas, fontes, cores, bordas, larguras e fórmulas).
   - Aplica a **Convenção de Cores** (células fixas vs. editáveis).
   - Gera um `mirror.json` estruturado e um `template.xlsx` limpo.
2. **Camada Web (Tailwind CSS + Vanilla JS)** — fase seguinte.
   - Navegação por abas (`Sheet Tabs`).
   - Células editáveis como inputs; fixas como texto formatado.
   - Multi-projeto com alternância de contexto.
   - Auto-save em `sessionStorage`.
   - Geração do `.xlsx` final a partir do template + dados preenchidos.

## Estrutura de diretórios

```
sps_to_web/
├── PLAN.md
├── README.md
├── pyproject.toml
├── src/
│   └── spreadsheet_mirror/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py            # comandos: scan, process
│       ├── config.py         # convenção de cores configurável
│       ├── colors.py         # resolução rgb/indexed/theme + tint
│       ├── styles.py         # extração e deduplicação de estilos
│       ├── editability.py    # regras fixo vs. editável
│       ├── reader.py         # leitura (fórmulas + valores em cache)
│       ├── serializer.py     # mirror.json
│       ├── template.py       # template.xlsx limpo
│       └── pipeline.py       # orquestração ponta a ponta
├── tests/
│   ├── conftest.py
│   ├── test_colors.py
│   ├── test_styles.py
│   ├── test_editability.py
│   ├── test_reader.py
│   ├── test_serializer.py
│   ├── test_template.py
│   └── test_cli.py
└── examples/
```

## Módulo Python — decisões técnicas

### Leitura
- Duas cargas do mesmo arquivo: `data_only=False` (fórmulas) e `data_only=True`
  (valores em cache exibíveis). A segunda é opcional e controlada por configuração.
- Ignora arquivos temporários `~$*.xlsx`.
- Suporta arquivo único ou diretório (recursivo opcional).

### Clonagem
- Preserva todas as abas (inclusive ocultas/veryHidden), estado, cor da aba,
  larguras de coluna, alturas de linha, linhas/colunas ocultas, mesclagens,
  painéis congelados, fontes, preenchimentos, bordas, alinhamento, formato
  numérico e proteção.
- **Fórmulas são mantidas intactas** (string original).
- Limitações conhecidas do openpyxl: gráficos, imagens, tabelas dinâmicas,
  macros e alguns elementos condicionais podem não sobreviver ao round-trip.
  Documentado no README.

### Convenção de Cores (padrão)
Ordem de avaliação por célula:

1. Célula com fórmula → **fixa**.
2. Célula não-âncora de intervalo mesclado → **fixa** (omitida do JSON; a âncora carrega o span).
3. Linha em `header_rows` ou coluna em `header_cols` → **fixa**.
4. Preenchimento em `fixed_fill_colors` → **fixa**.
5. Preenchimento em `editable_fill_colors` → **editável** (salvo regras 1–3).
6. Preenchimento sólido não-branco → **fixa** (cabeçalho/rótulo).
7. Fonte em negrito (se `fixed_if_bold`) → **fixa**.
8. Caso contrário (fundo branco/padrão e sem fórmula) → **editável**.

Tudo configurável via JSON ou CLI. Valores editáveis são limpos no template.

### Cores
- Resolve `rgb`, `indexed` (tabela ECMA-376) e `theme`.
- Faz o parse de `wb.loaded_theme` (XML `a:clrScheme`) para obter a paleta do tema.
- Mapeamento do atributo `theme` (0–11) para o esquema:
  `0=lt1, 1=dk1, 2=lt2, 3=dk2, 4..9=accent1..6, 10=hlink, 11=folHlink`.
  (O XML lista `dk1` primeiro, mas o índice de célula começa em `lt1`.)
- Aplica `tint` (−1.0 a 1.0) por mistura linear em RGB:
  positivo → em direção ao branco; negativo → em direção ao preto.
- Saída canônica em `#RRGGBB` + metadados brutos (tipo, índice, tint).

### JSON (`mirror.json`)
Estrutura de alto nível:

```json
{
  "schema_version": "1.0.0",
  "meta": {
    "source": "arquivo.xlsx",
    "generated_at": "ISO-8601",
    "config": { "...": "..." },
    "theme": { "colors": { "lt1": "#FFFFFF", "dk1": "#000000" }, "index_map": {} },
    "warnings": []
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
  "sheets": [
    {
      "name": "Planilha1",
      "state": "visible",
      "tab_color": "#RRGGBB",
      "max_row": 10,
      "max_col": 5,
      "freeze_panes": "A2",
      "default_col_width": 8.43,
      "default_row_height": 15.0,
      "columns": [{ "index": 1, "letter": "A", "width": 12.5, "hidden": false }],
      "rows": [{ "index": 1, "height": 20.0, "hidden": false }],
      "merged_ranges": ["A1:B2"],
      "cells": [
        {
          "ref": "A1",
          "row": 1,
          "col": 1,
          "value": "Título",
          "formula": null,
          "cached_value": null,
          "data_type": "s",
          "value_type": "string",
          "editavel": false,
          "style": "s0",
          "merged": "A1:B2",
          "rowspan": 2,
          "colspan": 2
        }
      ]
    }
  ]
}
```

### Template (`template.xlsx`)
- Cópia do workbook original com os valores das células editáveis removidos.
- Fórmulas, estilos, mesclagens, dimensões e abas preservados.
- Usado na fase web para injeção dos dados e geração do `.xlsx` final.

### Saída
- Pasta por projeto: `<saida>/<slug>/mirror.json` + `template.xlsx`.
- `index.json` na raiz da saída listando os projetos processados.

## Camada Web (fase futura)
- `index.html` + `app.js` + `styles.css` (Tailwind via CDN ou build).
- Carrega `mirror.json`, renderiza abas e grade com `rowspan`/`colspan`.
- Edição em `sessionStorage` por projeto/aba; salvamento parcial permitido.
- Exportação: envia dados + template para um endpoint Python (ou usa SheetJS no
  navegador) para gerar o `.xlsx` final.

## Testes
- Fixtures geradas com openpyxl cobrindo múltiplas abas, fórmulas, estilos,
  merges, ocultos, datas, números e cores de tema.
- Testes de cores (rgb/indexed/theme/tint), estilos, editabilidade, JSON,
  template e CLI. Execução: `python -m pytest`.

## Ordem de implementação
1. Scaffold e configuração.
2. `colors.py` + `styles.py`.
3. `reader.py`.
4. `config.py` + `editability.py`.
5. `serializer.py` + `template.py` + `pipeline.py`.
6. `cli.py`.
7. Testes e smoke test com `.xlsx` real.

---

## Fase 2 — IA, chat e Prompt-to-Sheet (implementado)

### Decisões

1. **Credenciais no navegador, nunca no servidor**: a chave fica no
   `sessionStorage` (`mirrorEngine:llm:key:<provider>`) e é enviada por
   requisição ao Flask local, que a usa em memória e a descarta. Não há keystore
   em disco, `cryptography`, `keyring` ou logs de chave.
2. **`httpx` direto** para todos os provedores; sem LangChain/litellm. Reduz
   dependências e mantém controle sobre timeouts, erros e streaming.
3. **Catálogo com presets**: OpenAI, Gemini, Anthropic, OpenRouter, DeepSeek e
   Ollama. OpenRouter/DeepSeek usam o adaptador OpenAI-compatible com `base_url`
   configurável. Qualquer endpoint compatível é aceito.
4. **Streaming SSE** no Flask (`stream_with_context`) com fallback para resposta
   completa quando o corpo não é streamável.
5. **LLM propõe, usuário aplica**: o modelo devolve `{"acoes": [...]}`; o backend
   valida contra `mirror.json` (`editavel: true`, refs válidos, mesclagens e
   cabeçalhos) e o frontend só mescla no rascunho após confirmação.
6. **Ferramentas de leitura + proposta pura**: `read_range`, `search_cells`,
   `summarize_sheet`, `suggest_formula`, `propose_edits`. `search_cells` pesquisa
   por rótulo/coordenada em todas as abas e retorna `campos_editaveis_vizinhos`
   (direita/abaixo/esquerda/acima). Nenhuma ferramenta grava em disco.
7. **Antialucinação de coordenadas**: o system prompt proíbe chutar células; o
   backend faz busca estrutural automática dos termos/refs do pedido e rejeita
   ações cuja coordenada não tenha sido verificada por contexto, busca ou tool
   (`coordenada_nao_verificada`).
8. **Histórico local**: `<workspace>/.chats/<slug>.json`, escrita atômica,
   limite de mensagens e remoção recursiva de campos sensíveis.
9. **Prompt-to-Sheet**: a IA devolve uma spec JSON validada (abas, refs, limites,
   fórmulas e estilos); o Python gera um `.xlsx` real e roda o pipeline normal
   para produzir `mirror.json` e `template.xlsx`.
10. **Contexto compacto**: modos `selection`, `sheet` e `project`; limite de 400
    células, apenas estilos usados e aviso explícito de truncamento.
11. **Hardening**: base URL só `http/https`, allowlist opcional por env, limite
    de resposta (4 MB), rate limit em memória, redaction de chaves em erros e
    sanitização de HTML no frontend (`textContent`/`escapeHtml`).

### Módulos adicionados

```text
src/spreadsheet_mirror/llm/
├── base.py          # LLMProvider, ChatRequest/Response/Chunk, erros
├── registry.py      # catálogo, presets e fábrica
├── providers/       # openai.py, anthropic.py, gemini.py, ollama.py
├── context.py       # ContextBuilder
├── tools.py         # ferramentas e validate_edits
├── prompts.py       # system prompts + parsing de JSON
├── chat_store.py    # histórico por projeto
├── service.py       # ChatService (chat, stream, criação)
└── creation.py      # spec -> .xlsx -> pipeline
web/chat.js          # UI de configuração, chat, SSE e aplicação de edições
```

### Rotas adicionadas

`GET /api/llm/providers`, `GET /api/llm/models`, `POST /api/llm/test`,
`POST /api/projects/<slug>/chat`, `POST /api/projects/<slug>/chat/stream`,
`GET|DELETE /api/projects/<slug>/chat/history`,
`POST /api/projects/<slug>/chat/apply`, `POST /api/projects/create`.

### Resultado

- 171 testes passando (101 originais + 70 novos), sem chamadas de rede reais.
- Exportação `.xlsx` existente permanece inalterada.
- Versão do pacote: `0.2.0`.

