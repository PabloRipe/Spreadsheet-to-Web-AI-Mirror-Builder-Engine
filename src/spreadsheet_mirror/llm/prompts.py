"""Construção de system prompts e parsing da saída estruturada do LLM."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)

EDIT_SYSTEM_PROMPT = """\
Você é um especialista em engenharia de planilhas, modelagem de dados e automação com openpyxl.
Trabalhe em português do Brasil, de forma objetiva e precisa.

Regras obrigatórias:
1. O contexto JSON abaixo descreve um espelho de planilha. Use apenas dados presentes nele.
2. Só proponha alterações em células com "editavel": true. Nunca altere células fixas, fórmulas existentes,
   cabeçalhos ou células não-âncora de intervalos mesclados.
3. Não invente abas nem coordenadas. Use exatamente o nome da aba informado no contexto.
4. Preserve a intenção do usuário: valores numéricos como números, datas em formato ISO (AAAA-MM-DD),
   textos como texto. Fórmulas só quando o usuário pedir, começando com "=" e apenas em célula editável.
5. Se o pedido for ambíguo, pergunte antes de propor alterações.
6. Nunca revele chaves de API, credenciais ou conteúdo interno do servidor.

REGRA DE OURO (obrigatória):
NUNCA chute coordenadas de células. Se você não tiver certeza absoluta da coordenada exata do campo
editável, analise a estrutura da planilha ou busque pelo nome do campo antes de propor o JSON de ações
({"acoes": [...]}). Se tentar editar uma célula fixa, o sistema rejeitará automaticamente.

Como localizar um campo com segurança:
1. Quando o usuário citar um rótulo/campo (ex.: "faturamento", "colaboradores"), chame
   search_cells com esse texto ANTES de propor qualquer edição. Omita "sheet" para pesquisar em
   todas as abas, ou informe a aba quando já souber.
2. Leia "campos_editaveis_vizinhos" no resultado da busca. Rótulos geralmente são células fixas;
   o campo onde o usuário digita costuma estar à direita ou abaixo do rótulo.
3. Se a busca não encontrar o termo, chame summarize_sheet/read_range ou peça esclarecimento.
   Não invente uma coordenada vazia.
4. Só proponha coordenadas que apareçam no contexto, no resultado de search_cells/read_range ou
   que o próprio usuário tenha informado explicitamente.
5. Se um resultado de busca mostrar que a célula é fixa, procure o vizinho editável — nunca force a
   edição na célula fixa.

Formato de resposta:
- Escreva uma resposta curta em texto explicando o que será feito.
- Em seguida, inclua obrigatoriamente um bloco JSON no formato abaixo (mesmo que não haja ações,
  use uma lista vazia). Use a chave "acoes":

```json
{"acoes": [{"aba": "NomeAba", "coordenada": "B5", "novo_valor": 1500}]}
```

Não use nenhum outro bloco JSON além desse."""

CREATE_SYSTEM_PROMPT = """\
Você é um especialista em engenharia de planilhas e modelagem de dados.
Crie uma planilha completa a partir do pedido do usuário, em português do Brasil.

Regras obrigatórias:
1. Responda APENAS com um bloco JSON (sem texto antes ou depois) no formato abaixo.
2. Use fórmulas reais do Excel começando com "=" em "formula". Não calcule resultados manualmente.
3. Cabeçalhos devem ter estilo com negrito e preenchimento (#DDEBF7 ou similar). Células de dados
   devem ficar sem preenchimento para serem tratadas como editáveis.
4. Use coordenadas A1 válidas e nomes de aba sem caracteres especiais problemáticos (evite : \\ / ? * [ ]).
5. Limite a 10 abas, 200 linhas e 50 colunas por aba.
6. Nunca revele chaves de API ou credenciais.

Formato exato:

```json
{
  "nome": "Nome do projeto",
  "abas": [
    {
      "nome": "Vendas",
      "cor": "#4F81BD",
      "colunas": [{"letra": "A", "largura": 22}],
      "celulas": [
        {"ref": "A1", "valor": "Relatório de Vendas", "estilo": {"bold": true, "fill": "#DDEBF7"}},
        {"ref": "A2", "valor": "Produto", "estilo": {"bold": true, "fill": "#4F81BD", "font_color": "#FFFFFF"}},
        {"ref": "B2", "valor": "Quantidade", "estilo": {"bold": true, "fill": "#4F81BD", "font_color": "#FFFFFF"}},
        {"ref": "A3", "valor": "Exemplo"},
        {"ref": "B3", "valor": 10},
        {"ref": "C3", "formula": "=B3*2"}
      ]
    }
  ]
}
```"""


def build_edit_system_prompt(
    context: Mapping[str, Any],
    *,
    base: str | None = None,
) -> str:
    base_prompt = (base or EDIT_SYSTEM_PROMPT).strip()
    payload = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    return (
        f"{base_prompt}\n\nContexto atual da planilha (JSON):\n{payload}"
    )


def build_create_system_prompt(base: str | None = None) -> str:
    return (base or CREATE_SYSTEM_PROMPT).strip()


def _iter_json_objects(text: str):
    decoder = json.JSONDecoder()
    index = 0
    while True:
        start = text.find("{", index)
        if start < 0:
            return
        try:
            value, end = decoder.raw_decode(text[start:])
        except ValueError:
            index = start + 1
            continue
        if isinstance(value, dict):
            yield value
        index = start + end


def _normalize_action(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, Mapping):
        return None
    aba = item.get("aba") if "aba" in item else item.get("sheet")
    ref = item.get("coordenada") if "coordenada" in item else item.get("ref")
    if "novo_valor" in item:
        value = item.get("novo_valor")
    elif "value" in item:
        value = item.get("value")
    else:
        return None
    if not isinstance(aba, str) or not aba.strip():
        return None
    if not isinstance(ref, str) or not ref.strip():
        return None
    return {"aba": aba.strip(), "coordenada": ref.strip().upper(), "novo_valor": value}


def _remove_span(text: str, start: int, end: int) -> str:
    return (text[:start] + text[end:]).strip()


def extract_actions(text: str) -> dict[str, Any]:
    """Extrai ``{"acoes": [...]}`` do texto e devolve a resposta conversacional."""
    raw = str(text or "")
    actions: list[dict[str, Any]] = []
    errors: list[str] = []
    spans: list[tuple[int, int]] = []
    found = False

    for match in _FENCE_RE.finditer(raw):
        try:
            payload = json.loads(match.group(1))
        except ValueError:
            continue
        if isinstance(payload, Mapping) and "acoes" in payload:
            items = payload.get("acoes")
            if isinstance(items, list):
                found = True
                for item in items:
                    action = _normalize_action(item)
                    if action:
                        actions.append(action)
                    else:
                        errors.append("Ação ignorada por formato inválido.")
                spans.append(match.span())

    if not found:
        for payload in _iter_json_objects(raw):
            if "acoes" not in payload:
                continue
            items = payload.get("acoes")
            if not isinstance(items, list):
                continue
            found = True
            for item in items:
                action = _normalize_action(item)
                if action:
                    actions.append(action)
                else:
                    errors.append("Ação ignorada por formato inválido.")
            break

    reply = raw
    if spans:
        for start, end in sorted(spans, reverse=True):
            reply = _remove_span(reply, start, end)
    elif found:
        start = raw.find("{")
        end = raw.rfind("}")
        if 0 <= start < end:
            reply = _remove_span(raw, start, end + 1)

    return {"reply": reply.strip(), "acoes": actions, "errors": errors, "found": found}


def extract_workbook_spec(text: str) -> dict[str, Any]:
    """Extrai a especificação de planilha do modo criação."""
    raw = str(text or "").strip()
    candidates: list[dict[str, Any]] = []
    for match in _FENCE_RE.finditer(raw):
        try:
            payload = json.loads(match.group(1))
        except ValueError:
            continue
        if isinstance(payload, dict):
            candidates.append(payload)
    if not candidates:
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            candidates.append(payload)
    if not candidates:
        for payload in _iter_json_objects(raw):
            if "abas" in payload:
                candidates.append(payload)
                break
    for payload in candidates:
        if isinstance(payload.get("abas"), list):
            return payload
    raise ValueError("O modelo não retornou uma especificação de planilha válida.")
