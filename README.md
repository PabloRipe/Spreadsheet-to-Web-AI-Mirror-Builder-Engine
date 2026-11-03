# Spreadsheet-to-Web AI Mirror & Builder Engine

Transforme planilhas `.xlsx` complexas em espelhos web interativos, edite-as por
chat com múltiplos provedores de LLM e crie planilhas do zero a partir de um
prompt — mantendo fórmulas, estilos e a exportação final `.xlsx`.

O projeto combina:

1. **Motor local (Python + openpyxl)** — lê o `.xlsx`, clona abas, estilos,
   mesclagens, larguras e fórmulas, aplica a convenção de cores (fixo vs.
   editável) e gera `mirror.json` + `template.xlsx`.
2. **Camada web (Flask + Tailwind CDN + Vanilla JS)** — renderiza a planilha,
   salva rascunhos em `sessionStorage`, exporta o `.xlsx` final e oferece:
   - configuração de provedor/modelo/chave de IA no navegador;
   - chat contextual por projeto/aba/seleção com streaming (SSE);
   - aplicação de edições sugeridas somente em células editáveis;
   - **Prompt-to-Sheet**: geração de uma planilha completa do zero via IA.

Repositório: <https://github.com/PabloRipe/Spreadsheet-to-Web-AI-Mirror-Builder-Engine>

---

## Requisitos

- Python 3.9 ou superior
- `pip`
- Navegador moderno (Chrome, Edge, Firefox ou Safari)

Não há dependência de Node.js: o Tailwind é carregado via CDN.

---

## Instalação

```bash
git clone https://github.com/PabloRipe/Spreadsheet-to-Web-AI-Mirror-Builder-Engine.git
cd Spreadsheet-to-Web-AI-Mirror-Builder-Engine
```

### Opção 1 — instalação completa (desenvolvimento + IA + servidor)

```bash
python -m venv .venv
```

Ativação:

- **Windows (PowerShell):**
  ```powershell
  .venv\Scripts\Activate.ps1
  ```
- **Linux/macOS:**
  ```bash
  source .venv/bin/activate
  ```

```bash
pip install -e ".[dev,web,llm]"
```

### Opção 2 — instalação mínima

```bash
pip install -r requirements.txt
```

---

## Uso

### 1. Processar uma planilha pela linha de comando

```bash
spreadsheet-mirror process caminho/planilha.xlsx -o saida/
```

Processar todos os `.xlsx` de um diretório (recursivo):

```bash
spreadsheet-mirror process caminho/pasta -o saida/ --recursive
```

Listar planilhas encontradas:

```bash
spreadsheet-mirror scan caminho/pasta --recursive
```

Saída:

```text
saida/
├── index.json
└── minha-planilha/
    ├── mirror.json
    └── template.xlsx
```

### 2. Executar a camada web

```bash
python server.py
```

Servidor em `http://localhost:5000`. Para outra porta:

```powershell
$env:PORT=8000; python server.py
```

Produção local (WSGI `waitress`):

```bash
waitress-serve --port=8000 server:app
```

### 3. Usar a interface web

1. Clique em **Enviar planilha** e selecione um `.xlsx` (ou arraste para a área).
2. Escolha o projeto no seletor superior e navegue pelas abas.
3. Preencha apenas as células editáveis (fundo branco). Células fixas
   (cabeçalhos, fórmulas, mesclagens e preenchimentos coloridos) não são
   editáveis.
4. Os valores são salvos automaticamente em `sessionStorage`.
5. Clique em **Gerar .xlsx** para baixar o arquivo final.

---

## Configuração dos provedores de IA

Clique em **IA** no cabeçalho:

| Provedor | Chave | URL base padrão |
| --- | --- | --- |
| OpenAI (GPT) | obrigatória | `https://api.openai.com/v1` |
| Google (Gemini) | obrigatória | `https://generativelanguage.googleapis.com/v1beta` |
| Anthropic (Claude) | obrigatória | `https://api.anthropic.com/v1` |
| OpenRouter | obrigatória | `https://openrouter.ai/api/v1` |
| DeepSeek | obrigatória | `https://api.deepseek.com/v1` |
| Ollama (local) | não exigida | `http://localhost:11434` |

Também é possível usar qualquer endpoint **OpenAI-compatible** informando a URL
base e o modelo. O botão **Testar conexão** consulta a lista de modelos da
credencial; modelos padrão são editáveis.

### Privacidade das chaves

- A chave fica **apenas no `sessionStorage`** da aba do navegador
  (`mirrorEngine:llm:key:<provider>`), que é limpo ao fechar a aba.
- O servidor Flask **não grava chaves em disco, não as registra em log e não as
  devolve em respostas HTTP**. Cada requisição envia a chave em memória ao
  servidor local, que a repassa ao provedor e a descarta.
- O histórico de chat (`mirror_output/.chats/<slug>.json`) contém apenas
  mensagens e ações — nunca credenciais.
- Opcionalmente, restrinja os hosts permitidos com
  `MIRROR_LLM_ALLOWED_HOSTS=api.openai.com,localhost`.

> Atenção: `sessionStorage` é acessível a JavaScript da mesma origem. Não
> carregue scripts de terceiros na página e mantenha o servidor local em
> ambiente confiável.

---

## Chat de IA

No painel **Chat IA**:

1. Escolha **Editar planilha** ou **Criar do zero**.
2. No modo edição, selecione o contexto enviado ao modelo:
   - **Aba atual** — resumo e células da aba ativa;
   - **Seleção** — intervalo como `A1:C10` (ou a célula em foco);
   - **Projeto inteiro** — resumo de todas as abas.
3. Envie o pedido. A resposta usa streaming e pode propor edições.
4. Cada cartão de edições mostra células válidas e rejeitadas. Clique em
   **Aplicar** para mesclar no rascunho ou **Descartar** para ignorar.

Regras de segurança do fluxo:

- O LLM **propõe** alterações; nada é gravado no `.xlsx` sem confirmação.
- Só células com `editavel: true` podem ser alteradas. Células fixas,
  cabeçalhos, fórmulas e não-âncoras de mesclagem são rejeitados pelo backend.
- O histórico por projeto é persistido em `<workspace>/.chats/<slug>.json` e pode
  ser limpo pelo botão **Limpar**.

### Prompt-to-Sheet

No modo **Criar do zero**, descreva a planilha. O modelo devolve uma
especificação JSON com abas, células e fórmulas; o backend valida tamanhos e
referências e gera um novo projeto com:

- `.xlsx` real (fórmulas preservadas);
- `mirror.json` com células editáveis/fixas;
- `template.xlsx` limpo para o fluxo normal de preenchimento e exportação.

---

## Variáveis de ambiente

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `PORT` | `5000` | Porta usada por `python server.py`. |
| `MIRROR_WORKSPACE` | `./mirror_output` | Diretório dos projetos processados, templates e histórico. |
| `MIRROR_LLM_ALLOWED_HOSTS` | vazio | Allowlist opcional de hosts separados por vírgula. |

---

## API HTTP

| Método | Rota | Descrição |
| --- | --- | --- |
| GET | `/` | Interface web. |
| GET | `/api/health` | Status do servidor e quantidade de projetos. |
| GET | `/api/projects` | Lista de projetos processados. |
| GET | `/api/projects/<slug>/mirror` | Retorna o `mirror.json` do projeto. |
| POST | `/api/upload` | Envia `.xlsx` (`multipart/form-data`, campo `file`). |
| POST | `/api/projects/<slug>/export` | Gera o `.xlsx` final com os dados preenchidos. |
| GET | `/api/llm/providers` | Provedores e modelos padrão (sem segredos). |
| GET | `/api/llm/models?provider=` | Modelos sugeridos do provedor. |
| POST | `/api/llm/test` | Valida credencial/provedor. |
| POST | `/api/projects/<slug>/chat` | Chat contextual (resposta completa). |
| POST | `/api/projects/<slug>/chat/stream` | Chat com streaming SSE. |
| GET | `/api/projects/<slug>/chat/history` | Histórico do projeto. |
| DELETE | `/api/projects/<slug>/chat/history` | Limpa o histórico. |
| POST | `/api/projects/<slug>/chat/apply` | Valida edições e devolve dados normalizados. |
| POST | `/api/projects/create` | Cria planilha do zero (`prompt` ou `spec`). |

Exemplo de payload de chat:

```json
{
  "message": "Preencha B3 com 1500 e C3 com =B3*0.1",
  "sheet": "Vendas",
  "context_mode": "sheet",
  "draft": {"Vendas": {"A3": "Produto X"}},
  "provider": {
    "id": "openai",
    "type": "openai",
    "model": "gpt-4o-mini",
    "base_url": "https://api.openai.com/v1",
    "temperature": 0.2,
    "max_tokens": 2048,
    "api_key": "sua-chave"
  }
}
```

O limite de upload é de **32 MB**. Requisições de IA têm rate limit simples em
memória (20/min por projeto; 10/min para criação) e timeouts configuráveis.

---

## Convenção de cores (fixo vs. editável)

Por padrão, uma célula é **fixa** quando:

- contém fórmula;
- é parte não-âncora de um intervalo mesclado;
- está nas linhas/colunas de cabeçalho configuradas;
- tem preenchimento sólido diferente de branco;
- tem fonte em negrito, itálico/sublinhado/borda quando habilitados.

Caso contrário (fundo branco/padrão e sem fórmula), a célula é **editável** e seu
valor é removido do template. As regras podem ser ajustadas via JSON de
configuração ou flags da CLI (consulte `spreadsheet_mirror.config.MirrorConfig`).

---

## Estrutura do projeto

```text
.
├── server.py                     # API Flask e arquivos estáticos
├── web/
│   ├── index.html                # Interface (Tailwind CDN)
│   ├── app.js                    # Grade, rascunhos, exportação, bridge
│   ├── chat.js                   # Configuração de IA, chat e streaming
│   └── styles.css
├── src/spreadsheet_mirror/
│   ├── cli.py                    # scan/process
│   ├── config.py                 # convenção de cores
│   ├── reader.py                 # leitura de .xlsx
│   ├── colors.py                 # cores RGB/indexed/theme
│   ├── styles.py                 # estilos, dimensões e mesclagens
│   ├── editability.py            # fixo vs. editável
│   ├── serializer.py             # mirror.json
│   ├── template.py               # template.xlsx e preenchimento
│   ├── pipeline.py               # orquestração em lote
│   └── llm/
│       ├── base.py               # tipos e interface de provedor
│       ├── registry.py           # catálogo e fábrica de provedores
│       ├── providers/            # OpenAI/compatible, Anthropic, Gemini, Ollama
│       ├── context.py            # contexto compacto do espelho
│       ├── tools.py              # ferramentas e validação de edições
│       ├── prompts.py            # system prompts e parsing JSON
│       ├── chat_store.py         # histórico local por projeto
│       ├── service.py            # chat, streaming e Prompt-to-Sheet
│       └── creation.py           # geração de .xlsx a partir de spec
├── tests/                        # suíte pytest
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## Testes

```bash
python -m pytest
```

Estado atual: **165 testes passando**. Nenhum teste faz chamada de rede real;
os provedores usam `httpx.MockTransport` e o chat usa provedor fake.

---

## Limitações conhecidas

- O round-trip do openpyxl preserva fórmulas, estilos, mesclagens e dimensões,
  mas não gráficos, imagens, tabelas dinâmicas, macros VBA ou parte da
  formatação condicional.
- Fórmulas sem valor em cache ficam `null` no espelho até o Excel recalcular.
- Planilhas grandes são truncadas por `max_cells_per_sheet` (200.000 por padrão).
- O contexto do chat é limitado a 400 células por padrão (`LLM_MAX_CONTEXT_CELLS`).
- Requisições de IA dependem de internet, exceto Ollama local.
- `sessionStorage` pode falhar em modo privado/limites; a UI avisa e mantém a
  sessão em memória quando possível.

---

## Licença

MIT.
