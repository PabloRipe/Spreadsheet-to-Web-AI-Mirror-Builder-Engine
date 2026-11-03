/* Spreadsheet Mirror Engine — chat e configuração de provedores de IA. */
(() => {
  'use strict';

  const SETTINGS_KEY = 'mirrorEngine:llm:settings';
  const KEY_PREFIX = 'mirrorEngine:llm:key:';
  const UI_KEY = 'mirrorEngine:llm:ui';

  const FALLBACK_PROVIDERS = [
    { id: 'openai', label: 'OpenAI (GPT)', type: 'openai', default_model: 'gpt-4o-mini', default_base_url: 'https://api.openai.com/v1', requires_key: true, models: ['gpt-4o-mini', 'gpt-4o'] },
    { id: 'gemini', label: 'Google (Gemini)', type: 'gemini', default_model: 'gemini-2.0-flash', default_base_url: 'https://generativelanguage.googleapis.com/v1beta', requires_key: true, models: ['gemini-2.0-flash'] },
    { id: 'anthropic', label: 'Anthropic (Claude)', type: 'anthropic', default_model: 'claude-3-5-sonnet-latest', default_base_url: 'https://api.anthropic.com/v1', requires_key: true, models: ['claude-3-5-sonnet-latest'] },
    { id: 'openrouter', label: 'OpenRouter', type: 'openai', default_model: 'openai/gpt-4o-mini', default_base_url: 'https://openrouter.ai/api/v1', requires_key: true, models: ['openai/gpt-4o-mini'] },
    { id: 'deepseek', label: 'DeepSeek', type: 'openai', default_model: 'deepseek-chat', default_base_url: 'https://api.deepseek.com/v1', requires_key: true, models: ['deepseek-chat'] },
    { id: 'ollama', label: 'Ollama (local)', type: 'ollama', default_model: 'llama3.1', default_base_url: 'http://localhost:11434', requires_key: false, models: ['llama3.1'] },
  ];

  const REASON_LABELS = {
    aba_inexistente: 'aba inexistente',
    coordenada_invalida: 'coordenada inválida',
    mesclada_nao_ancora: 'célula mesclada (não-âncora)',
    celula_fixa: 'célula fixa',
    cabecalho_fixo: 'cabeçalho fixo',
    sem_preenchimento_fixo: 'célula sem preenchimento configurada como fixa',
    fora_dimensao: 'fora da dimensão da aba',
    formula_em_celula_vazia: 'fórmula em célula vazia',
    celula_com_formula_fixa: 'fórmula em célula fixa',
    coordenada_nao_verificada: 'coordenada não confirmada por busca estrutural',
  };

  const state = {
    providers: [],
    settings: {
      provider: 'openai',
      type: 'openai',
      model: '',
      base_url: '',
      temperature: 0.2,
      max_tokens: 2048,
    },
    ui: { mode: 'edit', contextMode: 'sheet' },
    sending: false,
    panelOpen: false,
    historyLoadedFor: null,
    returnFocus: null,
  };

  const els = {
    settingsButton: document.getElementById('llm-settings-button'),
    chatToggle: document.getElementById('chat-toggle-button'),
    panel: document.getElementById('chat-panel'),
    chatClose: document.getElementById('chat-close'),
    chatClear: document.getElementById('chat-clear-history'),
    messages: document.getElementById('chat-messages'),
    input: document.getElementById('chat-input'),
    send: document.getElementById('chat-send'),
    sendLabel: document.getElementById('chat-send-label'),
    status: document.getElementById('chat-status'),
    providerBadge: document.getElementById('chat-provider-badge'),
    modeEdit: document.getElementById('chat-mode-edit'),
    modeCreate: document.getElementById('chat-mode-create'),
    contextRow: document.getElementById('chat-context-row'),
    contextMode: document.getElementById('chat-context-mode'),
    selection: document.getElementById('chat-selection'),
    settingsModal: document.getElementById('llm-settings-modal'),
    settingsClose: document.getElementById('llm-settings-close'),
    settingsProvider: document.getElementById('llm-provider'),
    settingsModel: document.getElementById('llm-model'),
    settingsModelList: document.getElementById('llm-model-list'),
    settingsBaseUrl: document.getElementById('llm-base-url'),
    settingsTemperature: document.getElementById('llm-temperature'),
    settingsMaxTokens: document.getElementById('llm-max-tokens'),
    settingsApiKey: document.getElementById('llm-api-key'),
    testButton: document.getElementById('llm-test-button'),
    saveButton: document.getElementById('llm-save-button'),
    testStatus: document.getElementById('llm-test-status'),
  };

  /* ------------------------------------------------------------------ */
  /* Armazenamento e configurações                                      */
  /* ------------------------------------------------------------------ */
  const readStorage = (key, fallback = null) => {
    try {
      const raw = window.sessionStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (error) {
      return fallback;
    }
  };

  const writeStorage = (key, value) => {
    try {
      window.sessionStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch (error) {
      return false;
    }
  };

  const removeStorage = (key) => {
    try {
      window.sessionStorage.removeItem(key);
    } catch (error) {
      /* ignore */
    }
  };

  const getKey = (providerId) => {
    try {
      return window.sessionStorage.getItem(`${KEY_PREFIX}${providerId}`) || '';
    } catch (error) {
      return '';
    }
  };

  const setKey = (providerId, value) => {
    try {
      if (value) window.sessionStorage.setItem(`${KEY_PREFIX}${providerId}`, value);
      else window.sessionStorage.removeItem(`${KEY_PREFIX}${providerId}`);
    } catch (error) {
      /* ignore */
    }
  };

  const providerMeta = (providerId) => state.providers.find((item) => item.id === providerId) || null;

  const normalizeSettings = () => {
    const stored = readStorage(SETTINGS_KEY, {}) || {};
    const ui = readStorage(UI_KEY, {}) || {};
    const meta = providerMeta(stored.provider) || state.providers[0] || null;
    const providerId = meta && (!stored.provider || stored.provider === meta.id)
      ? meta.id
      : (stored.provider && providerMeta(stored.provider) ? stored.provider : ((meta && meta.id) || 'openai'));
    state.settings = {
      provider: providerId,
      type: String(stored.type || (meta && meta.type) || 'openai'),
      model: String(stored.model || (meta && meta.default_model) || ''),
      base_url: String(stored.base_url || (meta && meta.default_base_url) || ''),
      temperature: Number.isFinite(Number(stored.temperature)) ? Number(stored.temperature) : 0.2,
      max_tokens: Number.isFinite(Number(stored.max_tokens)) ? Number(stored.max_tokens) : 2048,
    };
    state.ui = {
      mode: ui.mode === 'create' ? 'create' : 'edit',
      contextMode: ['selection', 'project', 'sheet'].includes(ui.contextMode) ? ui.contextMode : 'sheet',
    };
  };

  const saveUi = () => writeStorage(UI_KEY, state.ui);

  const hasKeyFor = (providerId) => Boolean(getKey(providerId).trim());

  const updateBadge = () => {
    if (!els.providerBadge) return;
    const meta = providerMeta(state.settings.provider);
    const label = meta ? meta.label : state.settings.provider || 'Provedor';
    const model = state.settings.model || (meta && meta.default_model) || '';
    if (!model) {
      els.providerBadge.textContent = 'Configure um provedor em IA';
      return;
    }
    const needsKey = meta ? meta.requires_key : true;
    const missingKey = needsKey && !hasKeyFor(state.settings.provider);
    els.providerBadge.textContent = `${label} · ${model}${missingKey ? ' · falta a chave' : ''}`;
  };

  const fillProviderSelect = () => {
    if (!els.settingsProvider) return;
    els.settingsProvider.replaceChildren();
    for (const provider of state.providers) {
      const option = document.createElement('option');
      option.value = provider.id;
      option.textContent = provider.label;
      els.settingsProvider.appendChild(option);
    }
    els.settingsProvider.value = state.settings.provider;
    fillModelDatalist(state.settings.provider);
  };

  const fillModelDatalist = (providerId) => {
    if (!els.settingsModelList) return;
    els.settingsModelList.replaceChildren();
    const meta = providerMeta(providerId);
    for (const model of (meta && meta.models) || []) {
      const option = document.createElement('option');
      option.value = model;
      els.settingsModelList.appendChild(option);
    }
  };

  const loadFormFromSettings = () => {
    const meta = providerMeta(state.settings.provider);
    if (els.settingsProvider) els.settingsProvider.value = state.settings.provider;
    if (els.settingsModel) els.settingsModel.value = state.settings.model || (meta && meta.default_model) || '';
    if (els.settingsBaseUrl) els.settingsBaseUrl.value = state.settings.base_url || (meta && meta.default_base_url) || '';
    if (els.settingsTemperature) els.settingsTemperature.value = String(state.settings.temperature);
    if (els.settingsMaxTokens) els.settingsMaxTokens.value = String(state.settings.max_tokens);
    if (els.settingsApiKey) {
      els.settingsApiKey.value = '';
      els.settingsApiKey.placeholder = hasKeyFor(state.settings.provider)
        ? 'Chave salva nesta aba (deixe em branco para manter)'
        : (meta && meta.requires_key ? 'Cole a chave da API' : 'Não exigida para este provedor');
    }
    fillModelDatalist(state.settings.provider);
    hideTestStatus();
  };

  const applyProviderDefaults = (providerId) => {
    const meta = providerMeta(providerId);
    if (!meta) return;
    if (els.settingsModel) els.settingsModel.value = meta.default_model || '';
    if (els.settingsBaseUrl) els.settingsBaseUrl.value = meta.default_base_url || '';
    if (els.settingsApiKey) {
      els.settingsApiKey.value = '';
      els.settingsApiKey.placeholder = hasKeyFor(providerId)
        ? 'Chave salva nesta aba (deixe em branco para manter)'
        : (meta.requires_key ? 'Cole a chave da API' : 'Não exigida para este provedor');
    }
    fillModelDatalist(providerId);
  };

  const readForm = () => {
    const providerId = els.settingsProvider ? els.settingsProvider.value : state.settings.provider;
    const meta = providerMeta(providerId);
    const apiKeyInput = els.settingsApiKey ? els.settingsApiKey.value.trim() : '';
    const storedKey = getKey(providerId).trim();
    return {
      provider: providerId,
      type: (meta && meta.type) || 'openai',
      model: (els.settingsModel && els.settingsModel.value.trim()) || (meta && meta.default_model) || '',
      base_url: (els.settingsBaseUrl && els.settingsBaseUrl.value.trim()) || (meta && meta.default_base_url) || '',
      temperature: Number(els.settingsTemperature ? els.settingsTemperature.value : 0.2),
      max_tokens: Number(els.settingsMaxTokens ? els.settingsMaxTokens.value : 2048),
      api_key: apiKeyInput || storedKey,
      requires_key: meta ? Boolean(meta.requires_key) : true,
    };
  };

  const configFromSettings = () => {
    const meta = providerMeta(state.settings.provider);
    return {
      id: state.settings.provider,
      type: state.settings.type || (meta && meta.type) || 'openai',
      model: state.settings.model || (meta && meta.default_model) || '',
      base_url: state.settings.base_url || (meta && meta.default_base_url) || '',
      temperature: state.settings.temperature,
      max_tokens: state.settings.max_tokens,
      api_key: getKey(state.settings.provider),
    };
  };

  const showTestStatus = (message, type) => {
    if (!els.testStatus) return;
    const classes = {
      info: 'bg-slate-100 text-slate-700',
      success: 'bg-emerald-50 text-emerald-700',
      error: 'bg-rose-50 text-rose-700',
    };
    els.testStatus.className = `mt-3 rounded-lg px-3 py-2 text-xs ${classes[type] || classes.info}`;
    els.testStatus.textContent = String(message || '');
  };

  const hideTestStatus = () => {
    if (!els.testStatus) return;
    els.testStatus.classList.add('hidden');
    els.testStatus.textContent = '';
  };

  /* ------------------------------------------------------------------ */
  /* Modal de configurações                                             */
  /* ------------------------------------------------------------------ */
  const openSettings = () => {
    if (!els.settingsModal) return;
    state.returnFocus = document.activeElement;
    loadFormFromSettings();
    els.settingsModal.classList.remove('hidden');
    els.settingsModal.classList.add('flex');
    window.setTimeout(() => els.settingsProvider && els.settingsProvider.focus(), 0);
  };

  const closeSettings = () => {
    if (!els.settingsModal) return;
    els.settingsModal.classList.add('hidden');
    els.settingsModal.classList.remove('flex');
    if (state.returnFocus && state.returnFocus.focus) state.returnFocus.focus();
    state.returnFocus = null;
  };

  const saveSettings = () => {
    const form = readForm();
    if (!form.model) {
      showTestStatus('Informe o modelo do provedor.', 'error');
      return;
    }
    if (!form.base_url) {
      showTestStatus('Informe a URL base do provedor.', 'error');
      return;
    }
    if (form.requires_key && !form.api_key) {
      showTestStatus('Informe a chave de API para este provedor.', 'error');
      return;
    }
    if (els.settingsApiKey && els.settingsApiKey.value.trim()) {
      setKey(form.provider, els.settingsApiKey.value.trim());
      els.settingsApiKey.value = '';
    }
    state.settings = {
      provider: form.provider,
      type: form.type,
      model: form.model,
      base_url: form.base_url,
      temperature: form.temperature,
      max_tokens: form.max_tokens,
    };
    writeStorage(SETTINGS_KEY, state.settings);
    updateBadge();
    closeSettings();
    notify('Configuração de IA salva nesta aba.', 'success');
  };

  const testConnection = async () => {
    if (!els.testButton) return;
    const form = readForm();
    if (form.requires_key && !form.api_key) {
      showTestStatus('Informe a chave de API para testar.', 'error');
      return;
    }
    els.testButton.disabled = true;
    showTestStatus('Testando conexão...', 'info');
    try {
      const response = await fetch('/api/llm/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ provider: form }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error((payload && payload.error) || `Erro ${response.status}`);
      if (!payload || !payload.ok) {
        showTestStatus((payload && payload.detail) || 'O provedor não confirmou a conexão.', 'error');
        return;
      }
      const models = Array.isArray(payload.models) && payload.models.length
        ? ` Modelos: ${payload.models.slice(0, 4).join(', ')}.`
        : '';
      showTestStatus(`Conexão validada.${models}`, 'success');
    } catch (error) {
      showTestStatus(error.message || 'Falha ao testar a conexão.', 'error');
    } finally {
      els.testButton.disabled = false;
    }
  };

  /* ------------------------------------------------------------------ */
  /* Painel de chat                                                     */
  /* ------------------------------------------------------------------ */
  const notify = (message, type = 'info') => {
    if (window.MirrorApp && typeof window.MirrorApp.showToast === 'function') {
      window.MirrorApp.showToast(message, type);
      return;
    }
    if (type === 'error') console.warn(message);
  };

  const setStatus = (message, type = 'info') => {
    if (!els.status) return;
    if (!message) {
      els.status.classList.add('hidden');
      els.status.textContent = '';
      return;
    }
    const classes = {
      info: 'bg-slate-100 text-slate-600',
      success: 'bg-emerald-50 text-emerald-700',
      error: 'bg-rose-50 text-rose-700',
      warning: 'bg-amber-50 text-amber-800',
    };
    els.status.className = `mb-2 rounded-lg px-2 py-1 text-[11px] ${classes[type] || classes.info}`;
    els.status.textContent = message;
  };

  const scrollMessages = () => {
    if (els.messages) els.messages.scrollTop = els.messages.scrollHeight;
  };

  const clearMessages = () => {
    if (!els.messages) return;
    els.messages.replaceChildren();
  };

  const showEmptyChat = () => {
    if (!els.messages) return;
    clearMessages();
    const empty = document.createElement('p');
    empty.id = 'chat-empty';
    empty.className = 'rounded-xl border border-dashed border-slate-300 bg-white px-3 py-4 text-xs text-slate-500';
    empty.textContent = state.ui.mode === 'create'
      ? 'Descreva a planilha que deve ser criada do zero. A IA vai gerar um novo projeto .xlsx.'
      : 'Configure um provedor em IA e peça alterações na planilha atual ou descreva uma planilha nova.';
    els.messages.appendChild(empty);
  };

  const appendMessage = (role, text) => {
    if (!els.messages) return null;
    const empty = document.getElementById('chat-empty');
    if (empty) empty.remove();
    const row = document.createElement('div');
    row.className = role === 'user' ? 'flex justify-end' : 'flex justify-start';
    const bubble = document.createElement('div');
    bubble.className = role === 'user'
      ? 'max-w-[86%] whitespace-pre-wrap break-words rounded-2xl rounded-br-sm bg-indigo-600 px-3 py-2 text-sm text-white shadow-sm'
      : 'max-w-[90%] whitespace-pre-wrap break-words rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm';
    bubble.textContent = String(text || '');
    if (role === 'assistant') bubble.dataset.role = 'assistant';
    row.appendChild(bubble);
    els.messages.appendChild(row);
    scrollMessages();
    return bubble;
  };

  const displayValue = (value) => {
    if (value === null || value === undefined) return '(vazio)';
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  };

  const appendEditsCard = (result, slug, sheet) => {
    const aplicaveis = result && result.aplicaveis && typeof result.aplicaveis === 'object'
      ? result.aplicaveis
      : {};
    const rejeitadas = Array.isArray(result && result.rejeitadas) ? result.rejeitadas : [];
    let count = 0;
    for (const cells of Object.values(aplicaveis)) {
      if (cells && typeof cells === 'object') count += Object.keys(cells).length;
    }
    if (!count && !rejeitadas.length) return;

    if (!els.messages) return;
    const card = document.createElement('div');
    card.className = 'rounded-xl border border-slate-200 bg-white p-3 text-xs text-slate-700 shadow-sm';

    const title = document.createElement('p');
    title.className = 'font-semibold text-slate-900';
    title.textContent = count ? `${count} edição(ões) proposta(s)` : 'Nenhuma edição aplicável';
    card.appendChild(title);

    if (count) {
      const list = document.createElement('ul');
      list.className = 'mt-1 space-y-0.5 text-[11px] text-slate-600';
      let shown = 0;
      for (const [sheetName, cells] of Object.entries(aplicaveis)) {
        if (!cells || typeof cells !== 'object') continue;
        for (const [ref, value] of Object.entries(cells)) {
          if (shown >= 12) break;
          const item = document.createElement('li');
          item.className = 'truncate';
          item.textContent = `${sheetName}!${ref} = ${displayValue(value)}`;
          list.appendChild(item);
          shown += 1;
        }
      }
      card.appendChild(list);
    }

    if (rejeitadas.length) {
      const rejected = document.createElement('p');
      rejected.className = 'mt-1 text-[11px] text-rose-700';
      rejected.textContent = `Rejeitadas: ${rejeitadas
        .slice(0, 6)
        .map((item) => `${item.aba || ''}!${item.coordenada || ''} (${REASON_LABELS[item.motivo] || item.motivo})`)
        .join(', ')}`;
      card.appendChild(rejected);
    }

    if (count) {
      const actions = document.createElement('div');
      actions.className = 'mt-2 flex gap-2';
      const apply = document.createElement('button');
      apply.type = 'button';
      apply.className = 'inline-flex h-8 items-center rounded-lg bg-emerald-600 px-3 text-xs font-semibold text-white transition hover:bg-emerald-700';
      apply.textContent = 'Aplicar';
      const discard = document.createElement('button');
      discard.type = 'button';
      discard.className = 'inline-flex h-8 items-center rounded-lg border border-slate-300 bg-white px-3 text-xs font-medium text-slate-600 transition hover:bg-slate-50';
      discard.textContent = 'Descartar';

      discard.addEventListener('click', () => card.remove());
      apply.addEventListener('click', async () => {
        if (!slug) return;
        apply.disabled = true;
        discard.disabled = true;
        try {
          const response = await fetch(`/api/projects/${encodeURIComponent(slug)}/chat/apply`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
            body: JSON.stringify({ sheet, edits: aplicaveis }),
          });
          const payload = await response.json().catch(() => null);
          if (!response.ok) throw new Error((payload && payload.error) || `Erro ${response.status}`);
          const applied = window.MirrorApp && window.MirrorApp.applyDraftEdits
            ? window.MirrorApp.applyDraftEdits(payload.data || payload.aplicaveis || {})
            : 0;
          setStatus(`${applied} valor(es) aplicado(s) no rascunho.`, 'success');
          notify(`${applied} valor(es) aplicado(s) no rascunho.`, 'success');
          card.remove();
        } catch (error) {
          apply.disabled = false;
          discard.disabled = false;
          setStatus(error.message || 'Falha ao aplicar as edições.', 'error');
        }
      });

      actions.appendChild(apply);
      actions.appendChild(discard);
      card.appendChild(actions);
    } else {
      const discard = document.createElement('button');
      discard.type = 'button';
      discard.className = 'mt-2 inline-flex h-8 items-center rounded-lg border border-slate-300 bg-white px-3 text-xs font-medium text-slate-600';
      discard.textContent = 'Descartar';
      discard.addEventListener('click', () => card.remove());
      card.appendChild(discard);
    }

    els.messages.appendChild(card);
    scrollMessages();
  };

  const appendCreateCard = (payload) => {
    if (!els.messages) return;
    const project = payload && payload.project ? payload.project : {};
    const card = document.createElement('div');
    card.className = 'rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900 shadow-sm';
    const title = document.createElement('p');
    title.className = 'font-semibold';
    title.textContent = 'Planilha criada com sucesso';
    const detail = document.createElement('p');
    detail.className = 'mt-1 break-words';
    detail.textContent = `Projeto: ${project.source_name || project.slug || 'novo'}`;
    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'mt-2 inline-flex h-8 items-center rounded-lg bg-emerald-600 px-3 text-xs font-semibold text-white transition hover:bg-emerald-700';
    open.textContent = 'Abrir planilha';
    open.addEventListener('click', async () => {
      open.disabled = true;
      try {
        if (window.MirrorApp && window.MirrorApp.refreshAndOpen) {
          await window.MirrorApp.refreshAndOpen(project.slug);
          notify('Projeto criado aberto na grade.', 'success');
        }
      } catch (error) {
        notify(error.message || 'Falha ao abrir o projeto criado.', 'error');
      } finally {
        open.disabled = false;
      }
    });
    card.appendChild(title);
    card.appendChild(detail);
    card.appendChild(open);
    els.messages.appendChild(card);
    scrollMessages();
  };

  const loadHistory = async () => {
    const context = window.MirrorApp && window.MirrorApp.getContext ? window.MirrorApp.getContext() : null;
    const slug = context && context.slug;
    if (!slug) {
      state.historyLoadedFor = null;
      showEmptyChat();
      return;
    }
    if (state.historyLoadedFor === slug) return;
    state.historyLoadedFor = slug;
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(slug)}/chat/history`, {
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) throw new Error('Não foi possível carregar o histórico.');
      const payload = await response.json();
      clearMessages();
      const messages = Array.isArray(payload.messages) ? payload.messages.slice(-24) : [];
      if (!messages.length) {
        showEmptyChat();
        return;
      }
      for (const message of messages) {
        if (!message || typeof message.content !== 'string' || !message.content) continue;
        if (message.role === 'user' || message.role === 'assistant') {
          appendMessage(message.role, message.content);
        }
      }
      scrollMessages();
    } catch (error) {
      showEmptyChat();
    }
  };

  const setMode = (mode) => {
    state.ui.mode = mode === 'create' ? 'create' : 'edit';
    saveUi();
    const editActive = state.ui.mode === 'edit';
    if (els.modeEdit) {
      els.modeEdit.setAttribute('aria-selected', editActive ? 'true' : 'false');
      els.modeEdit.className = `flex-1 rounded-md px-2 py-1.5 transition ${editActive ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500'}`;
    }
    if (els.modeCreate) {
      els.modeCreate.setAttribute('aria-selected', editActive ? 'false' : 'true');
      els.modeCreate.className = `flex-1 rounded-md px-2 py-1.5 transition ${editActive ? 'text-slate-500' : 'bg-white text-slate-900 shadow-sm'}`;
    }
    if (els.contextRow) els.contextRow.classList.toggle('hidden', !editActive);
    if (els.sendLabel) els.sendLabel.textContent = editActive ? 'Enviar' : 'Criar planilha';
    if (els.input) {
      els.input.placeholder = editActive
        ? 'Ex.: preencha a coluna B com os valores da coluna A multiplicados por 2'
        : 'Ex.: crie uma planilha de controle de despesas com categorias, orçamento e total';
    }
    showEmptyChat();
    if (editActive) {
      state.historyLoadedFor = null;
      loadHistory();
    }
  };

  const setContextMode = (mode) => {
    state.ui.contextMode = ['selection', 'project', 'sheet'].includes(mode) ? mode : 'sheet';
    saveUi();
    if (els.contextMode) els.contextMode.value = state.ui.contextMode;
    if (els.selection) els.selection.classList.toggle('hidden', state.ui.contextMode !== 'selection');
  };

  const openPanel = () => {
    if (!els.panel) return;
    state.panelOpen = true;
    els.panel.classList.remove('hidden');
    els.panel.classList.add('flex');
    els.panel.setAttribute('aria-hidden', 'false');
    if (els.chatToggle) els.chatToggle.setAttribute('aria-expanded', 'true');
    updateBadge();
    state.historyLoadedFor = null;
    setMode(state.ui.mode);
    setContextMode(state.ui.contextMode);
    const context = window.MirrorApp && window.MirrorApp.getContext ? window.MirrorApp.getContext() : null;
    if (!context || !context.slug) showEmptyChat();
    window.setTimeout(() => els.input && els.input.focus(), 0);
  };

  const closePanel = () => {
    if (!els.panel) return;
    state.panelOpen = false;
    els.panel.classList.add('hidden');
    els.panel.classList.remove('flex');
    els.panel.setAttribute('aria-hidden', 'true');
    if (els.chatToggle) els.chatToggle.setAttribute('aria-expanded', 'false');
  };

  const setSending = (sending) => {
    state.sending = sending;
    if (els.send) els.send.disabled = sending;
    if (els.sendLabel) {
      const create = state.ui.mode === 'create';
      els.sendLabel.textContent = sending ? 'Aguarde...' : (create ? 'Criar planilha' : 'Enviar');
    }
  };

  const streamChat = async (slug, payload, onDelta) => {
    const response = await fetch(`/api/projects/${encodeURIComponent(slug)}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const errorPayload = await response.json().catch(() => null);
      throw new Error((errorPayload && errorPayload.error) || `Erro ${response.status}`);
    }
    if (!response.body) {
      const fallback = await fetch(`/api/projects/${encodeURIComponent(slug)}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await fallback.json().catch(() => null);
      if (!fallback.ok) throw new Error((data && data.error) || `Erro ${fallback.status}`);
      if (data && data.reply) onDelta(data.reply);
      return data;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let doneResult = null;
    const handleBlock = (block) => {
      for (const line of block.split('\n')) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data:')) continue;
        const raw = trimmed.slice(5).trim();
        if (!raw) continue;
        let event;
        try {
          event = JSON.parse(raw);
        } catch (error) {
          continue;
        }
        if (event.type === 'delta' && event.text) onDelta(event.text);
        else if (event.type === 'done') doneResult = event;
        else if (event.type === 'error') throw new Error(event.error || 'Falha no chat.');
      }
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let index = buffer.indexOf('\n\n');
      while (index >= 0) {
        const block = buffer.slice(0, index);
        buffer = buffer.slice(index + 2);
        handleBlock(block);
        index = buffer.indexOf('\n\n');
      }
    }
    buffer += decoder.decode();
    if (buffer.trim()) handleBlock(buffer);
    if (!doneResult) throw new Error('Resposta incompleta do servidor.');
    return doneResult;
  };

  const ensureConfigured = () => {
    const config = configFromSettings();
    const meta = providerMeta(config.id);
    const requiresKey = meta ? meta.requires_key : true;
    if (!config.model || (requiresKey && !config.api_key)) {
      notify('Configure o provedor e a chave de API em IA.', 'warning');
      openSettings();
      return null;
    }
    return config;
  };

  const sendMessage = async () => {
    if (state.sending) return;
    const text = els.input ? els.input.value.trim() : '';
    if (!text) return;
    const config = ensureConfigured();
    if (!config) return;

    if (state.ui.mode === 'create') {
      if (els.input) els.input.value = '';
      appendMessage('user', text);
      setSending(true);
      setStatus('Gerando a planilha com a IA...', 'info');
      try {
        const response = await fetch('/api/projects/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ prompt: text, provider: config }),
        });
        const payload = await response.json().catch(() => null);
        if (!response.ok) throw new Error((payload && payload.error) || `Erro ${response.status}`);
        appendCreateCard(payload);
        setStatus('Planilha criada. Abra o projeto para preencher e exportar.', 'success');
        notify('Planilha criada com sucesso.', 'success');
        state.historyLoadedFor = null;
      } catch (error) {
        setStatus(error.message || 'Falha ao criar a planilha.', 'error');
        notify(error.message || 'Falha ao criar a planilha.', 'error');
      } finally {
        setSending(false);
      }
      return;
    }

    const context = window.MirrorApp && window.MirrorApp.getContext ? window.MirrorApp.getContext() : null;
    if (!context || !context.slug || !context.sheet) {
      notify('Selecione ou envie uma planilha antes de usar o chat.', 'warning');
      return;
    }

    const selection = state.ui.contextMode === 'selection'
      ? ((els.selection && els.selection.value.trim()) || context.focusedRef || '')
      : '';
    if (state.ui.contextMode === 'selection' && !selection) {
      notify('Informe um intervalo (ex.: A1:C10) ou focalize uma célula.', 'warning');
      return;
    }

    const payload = {
      message: text,
      sheet: context.sheet,
      context_mode: state.ui.contextMode,
      selection,
      draft: { [context.sheet]: context.draft || {} },
      provider: config,
    };

    if (els.input) els.input.value = '';
    appendMessage('user', text);
    let bubble = appendMessage('assistant', '');
    let accumulated = '';
    setSending(true);
    setStatus('Consultando o provedor...', 'info');

    try {
      const result = await streamChat(context.slug, payload, (delta) => {
        accumulated += delta;
        if (bubble) bubble.textContent = accumulated;
        scrollMessages();
      });
      if (!accumulated && result && result.reply) {
        accumulated = result.reply;
        if (bubble) bubble.textContent = accumulated;
      }
      if (bubble && !accumulated) {
        bubble.textContent = 'Sem resposta textual do provedor.';
      }
      appendEditsCard(result, context.slug, context.sheet);
      setStatus('Resposta recebida. Revise as edições antes de aplicar.', 'success');
      state.historyLoadedFor = context.slug;
    } catch (error) {
      if (bubble && bubble.parentElement) bubble.parentElement.remove();
      setStatus(error.message || 'Falha no chat.', 'error');
      notify(error.message || 'Falha no chat.', 'error');
    } finally {
      setSending(false);
      scrollMessages();
    }
  };

  const clearHistory = async () => {
    const context = window.MirrorApp && window.MirrorApp.getContext ? window.MirrorApp.getContext() : null;
    if (!context || !context.slug) return;
    if (!window.confirm('Limpar todo o histórico de chat deste projeto?')) return;
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(context.slug)}/chat/history`, {
        method: 'DELETE',
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) throw new Error('Falha ao limpar o histórico.');
      state.historyLoadedFor = null;
      showEmptyChat();
      notify('Histórico de chat limpo.', 'info');
    } catch (error) {
      notify(error.message || 'Falha ao limpar o histórico.', 'error');
    }
  };

  /* ------------------------------------------------------------------ */
  /* Eventos                                                            */
  /* ------------------------------------------------------------------ */
  const trapFocus = (event) => {
    if (!els.settingsModal || els.settingsModal.classList.contains('hidden')) return;
    if (event.key !== 'Tab') return;
    const focusable = els.settingsModal.querySelectorAll(
      'button, input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const bindEvents = () => {
    if (els.settingsButton) els.settingsButton.addEventListener('click', openSettings);
    if (els.settingsClose) els.settingsClose.addEventListener('click', closeSettings);
    if (els.settingsModal) {
      els.settingsModal.addEventListener('click', (event) => {
        if (event.target === els.settingsModal) closeSettings();
      });
    }
    if (els.settingsProvider) {
      els.settingsProvider.addEventListener('change', () => applyProviderDefaults(els.settingsProvider.value));
    }
    if (els.testButton) els.testButton.addEventListener('click', testConnection);
    if (els.saveButton) els.saveButton.addEventListener('click', saveSettings);
    if (els.chatToggle) {
      els.chatToggle.addEventListener('click', () => {
        if (state.panelOpen) closePanel();
        else openPanel();
      });
    }
    if (els.chatClose) els.chatClose.addEventListener('click', closePanel);
    if (els.chatClear) els.chatClear.addEventListener('click', clearHistory);
    if (els.send) els.send.addEventListener('click', sendMessage);
    if (els.input) {
      els.input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
          event.preventDefault();
          sendMessage();
        }
      });
    }
    if (els.modeEdit) els.modeEdit.addEventListener('click', () => setMode('edit'));
    if (els.modeCreate) els.modeCreate.addEventListener('click', () => setMode('create'));
    if (els.contextMode) {
      els.contextMode.addEventListener('change', () => setContextMode(els.contextMode.value));
    }
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        if (els.settingsModal && !els.settingsModal.classList.contains('hidden')) closeSettings();
        else if (state.panelOpen) closePanel();
      }
      trapFocus(event);
    });
    window.addEventListener('mirror:project-loaded', () => {
      state.historyLoadedFor = null;
      updateBadge();
      if (state.panelOpen) loadHistory();
    });
    window.addEventListener('mirror:draft-updated', () => {
      setStatus('Rascunho atualizado pelas edições da IA.', 'success');
    });
  };

  const init = async () => {
    bindEvents();
    try {
      const response = await fetch('/api/llm/providers', { headers: { Accept: 'application/json' } });
      const payload = await response.json();
      state.providers = Array.isArray(payload.providers) && payload.providers.length
        ? payload.providers
        : FALLBACK_PROVIDERS;
    } catch (error) {
      state.providers = FALLBACK_PROVIDERS;
    }
    normalizeSettings();
    fillProviderSelect();
    loadFormFromSettings();
    updateBadge();
    setMode(state.ui.mode);
    setContextMode(state.ui.contextMode);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
