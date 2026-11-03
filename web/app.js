/* Spreadsheet Mirror Engine — frontend em JavaScript puro. */
(() => {
  'use strict';

  const STORAGE_PREFIX = 'mirrorEngine';

  const state = {
    projects: [],
    project: null,
    mirror: null,
    activeSheetName: null,
    activeSheet: null,
    draft: {},
    saveTimer: null,
    busyCount: 0,
    storageErrorShown: false,
  };

  const els = {
    projectSelect: document.getElementById('project-select'),
    refreshProjects: document.getElementById('refresh-projects'),
    uploadButton: document.getElementById('upload-button'),
    exportButton: document.getElementById('export-button'),
    fileInput: document.getElementById('file-input'),
    emptyState: document.getElementById('empty-state'),
    emptyUploadButton: document.getElementById('empty-upload-button'),
    dropZone: document.getElementById('drop-zone'),
    workspace: document.getElementById('workspace'),
    warningsBanner: document.getElementById('warnings-banner'),
    warningsSummary: document.getElementById('warnings-summary'),
    warningsCount: document.getElementById('warnings-count'),
    warningsList: document.getElementById('warnings-list'),
    sheetTabs: document.getElementById('sheet-tabs'),
    sheetInfo: document.getElementById('sheet-info'),
    clearSheet: document.getElementById('clear-sheet'),
    spreadsheet: document.getElementById('spreadsheet'),
    gridScroll: document.getElementById('grid-scroll'),
    gridEmpty: document.getElementById('grid-empty'),
    autosaveIndicator: document.getElementById('autosave-indicator'),
    autosaveText: document.getElementById('autosave-text'),
    projectStats: document.getElementById('project-stats'),
    toastContainer: document.getElementById('toast-container'),
    loadingOverlay: document.getElementById('loading-overlay'),
    loadingMessage: document.getElementById('loading-message'),
  };

  /* ------------------------------------------------------------------ */
  /* Utilidades                                                          */
  /* ------------------------------------------------------------------ */
  const escapeHtml = (value) =>
    String(value ?? '').replace(/[&<>"']/g, (char) => {
      switch (char) {
        case '&': return '&amp;';
        case '<': return '&lt;';
        case '>': return '&gt;';
        case '"': return '&quot;';
        case "'": return '&#39;';
        default: return char;
      }
    });
  const escapeAttr = escapeHtml;

  const colToLetter = (input) => {
    let n = Number(input);
    let letters = '';
    while (n > 0) {
      const remainder = (n - 1) % 26;
      letters = String.fromCharCode(65 + remainder) + letters;
      n = Math.floor((n - 1) / 26);
    }
    return letters || 'A';
  };

  const letterToCol = (letters) => {
    let n = 0;
    for (const char of String(letters).toUpperCase()) {
      n = n * 26 + (char.charCodeAt(0) - 64);
    }
    return n;
  };

  const parseRef = (ref) => {
    const match = /^\$?([A-Za-z]+)\$?(\d+)$/.exec(String(ref ?? '').trim());
    if (!match) return null;
    const col = letterToCol(match[1]);
    const row = Number(match[2]);
    if (!col || !row) return null;
    return { row, col };
  };

  const formatRef = (row, col) => `${colToLetter(col)}${row}`;
  const unique = (items) => [...new Set(items)];

  const safeColor = (value, fallback = null) => {
    const text = String(value ?? '').trim();
    return /^#[0-9a-fA-F]{6}$/.test(text) ? text : fallback;
  };

  const storage = {
    get(key, fallback = null) {
      try {
        const raw = window.sessionStorage.getItem(key);
        return raw ? JSON.parse(raw) : fallback;
      } catch (error) {
        console.warn('Falha ao ler sessionStorage', error);
        return fallback;
      }
    },
    set(key, value) {
      try {
        window.sessionStorage.setItem(key, JSON.stringify(value));
        return true;
      } catch (error) {
        console.warn('Falha ao gravar sessionStorage', error);
        return false;
      }
    },
    remove(key) {
      try {
        window.sessionStorage.removeItem(key);
      } catch (error) {
        console.warn('Falha ao remover do sessionStorage', error);
      }
    },
  };

  const draftKey = (slug, sheetName) => `${STORAGE_PREFIX}:draft:${slug}:${sheetName}`;
  const lastContextKey = `${STORAGE_PREFIX}:lastContext`;
  const lastSheetKey = (slug) => `${STORAGE_PREFIX}:lastSheet:${slug}`;

  const showToast = (message, type = 'info', timeout = 4200) => {
    if (!els.toastContainer) return;
    const colors = {
      info: 'bg-slate-900 text-white',
      success: 'bg-emerald-600 text-white',
      warning: 'bg-amber-500 text-white',
      error: 'bg-rose-600 text-white',
    };
    const toast = document.createElement('div');
    toast.className = `toast pointer-events-auto rounded-xl px-4 py-3 text-sm shadow-lg ${colors[type] || colors.info}`;
    toast.textContent = String(message ?? '');
    els.toastContainer.appendChild(toast);
    window.setTimeout(() => {
      toast.classList.add('toast-hidden');
      window.setTimeout(() => toast.remove(), 300);
    }, timeout);
  };

  const setBusy = (busy, message = 'Carregando...') => {
    if (busy) {
      state.busyCount += 1;
      if (els.loadingMessage) els.loadingMessage.textContent = message;
    } else {
      state.busyCount = Math.max(0, state.busyCount - 1);
    }
    const visible = state.busyCount > 0;
    if (els.loadingOverlay) {
      els.loadingOverlay.classList.toggle('hidden', !visible);
      els.loadingOverlay.classList.toggle('flex', visible);
    }
    document.body.classList.toggle('overflow-hidden', visible);
  };

  const fetchJSON = async (url, options = {}) => {
    const headers = { Accept: 'application/json', ...(options.headers || {}) };
    if (options.body && !(options.body instanceof FormData)) {
      headers['Content-Type'] = headers['Content-Type'] || 'application/json';
    }
    const response = await fetch(url, { ...options, headers });
    let payload = null;
    const contentType = response.headers.get('Content-Type') || '';
    if (contentType.includes('application/json')) {
      payload = await response.json().catch(() => null);
    }
    if (!response.ok) {
      const error = new Error((payload && payload.error) || `Erro ${response.status}`);
      error.status = response.status;
      error.payload = payload;
      throw error;
    }
    return payload;
  };

  /* ------------------------------------------------------------------ */
  /* Formatação de valores e estilos                                     */
  /* ------------------------------------------------------------------ */
  const countDecimals = (format) => {
    if (!format || typeof format !== 'string') return null;
    const match = /[0#]\.([0#]+)/.exec(format);
    return match ? match[1].length : null;
  };

  const formatNumber = (value, style) => {
    if (value === null || value === undefined || value === '') return '';
    const number = Number(value);
    if (Number.isNaN(number)) return String(value);
    const format = style && typeof style.number_format === 'string' ? style.number_format : 'General';

    if (format.includes('%')) {
      const decimals = countDecimals(format);
      const formatted = new Intl.NumberFormat('pt-BR', {
        minimumFractionDigits: decimals ?? 0,
        maximumFractionDigits: decimals ?? 2,
      }).format(number * 100);
      return `${formatted}%`;
    }

    if (format.includes('R$') || format.includes('$')) {
      const currency = format.includes('R$') ? 'BRL' : 'USD';
      const decimals = countDecimals(format);
      try {
        return new Intl.NumberFormat('pt-BR', {
          style: 'currency',
          currency,
          minimumFractionDigits: decimals ?? 2,
          maximumFractionDigits: decimals ?? 2,
        }).format(number);
      } catch (error) {
        return String(value);
      }
    }

    const decimals = countDecimals(format);
    if (decimals !== null) {
      return new Intl.NumberFormat('pt-BR', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      }).format(number);
    }
    return new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 10 }).format(number);
  };

  const formatDateTime = (value) => {
    if (value === null || value === undefined || value === '') return '';
    const text = String(value);
    if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
      const [year, month, day] = text.split('-').map(Number);
      const date = new Date(year, month - 1, day);
      return Number.isNaN(date.getTime()) ? text : date.toLocaleDateString('pt-BR');
    }
    const date = new Date(text);
    if (Number.isNaN(date.getTime())) return text;
    return date.toLocaleString('pt-BR');
  };

  const formatDuration = (value) => {
    const total = Number(value);
    if (Number.isNaN(total)) return String(value);
    const sign = total < 0 ? '-' : '';
    const abs = Math.abs(total);
    const hours = Math.floor(abs / 3600);
    const minutes = Math.floor((abs % 3600) / 60);
    const seconds = Math.floor(abs % 60);
    return `${sign}${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  };

  const formatCellValue = (cell, style) => {
    if (!cell) return '';
    if (cell.value_type === 'null' || cell.value === null || cell.value === undefined) {
      return cell.formula ? String(cell.formula) : '';
    }
    switch (cell.value_type) {
      case 'number': return formatNumber(cell.value, style);
      case 'boolean': return cell.value ? 'Sim' : 'Não';
      case 'datetime': return formatDateTime(cell.value);
      case 'duration': return formatDuration(cell.value);
      case 'error': return String(cell.value);
      default: return String(cell.value);
    }
  };

  const borderStyleMap = {
    thin: '1px solid',
    medium: '2px solid',
    thick: '3px solid',
    dashed: '1px dashed',
    dotted: '1px dotted',
    double: '3px double',
    hair: '1px solid',
    mediumDashed: '2px dashed',
    dashDot: '1px dashed',
    mediumDashDot: '2px dashed',
    dashDotDot: '1px dashed',
    mediumDashDotDot: '2px dashed',
    slantDashDot: '1px dashed',
  };

  const borderCss = (side) => {
    if (!side || !side.style) return '';
    if (side.style === 'none') return 'none';
    const cssStyle = borderStyleMap[side.style] || '1px solid';
    const color = safeColor(side.color && side.color.hex, '#cbd5e1');
    return `${cssStyle} ${color}`;
  };

  const fillCss = (fill) => {
    if (!fill || typeof fill !== 'object') return null;
    const stops = Array.isArray(fill.stop) ? fill.stop : null;
    if (fill.kind === 'gradient' || fill.pattern_type === 'gradient' || stops) {
      if (!stops || !stops.length) return null;
      const parts = stops.map((stop) => {
        const color = safeColor(stop && stop.color && stop.color.hex, '#ffffff');
        const position = Number(stop && stop.position);
        const percent = Number.isFinite(position) ? Math.round(position * 100) : 0;
        return `${color} ${percent}%`;
      });
      const degree = Number(fill.degree);
      return `linear-gradient(${Number.isFinite(degree) ? degree : 90}deg, ${parts.join(', ')})`;
    }
    if (fill.pattern_type === 'solid') {
      return safeColor(fill.fg_color && fill.fg_color.hex, null)
        || safeColor(fill.bg_color && fill.bg_color.hex, null);
    }
    return safeColor(fill.bg_color && fill.bg_color.hex, null)
      || safeColor(fill.fg_color && fill.fg_color.hex, null);
  };

  const sanitizeFontName = (name) => String(name ?? '').replace(/[^A-Za-z0-9 _-]/g, '').trim();

  const horizontalAlign = (alignment, valueType) => {
    const horizontal = alignment && alignment.horizontal;
    if (horizontal === 'center' || horizontal === 'centerContinuous') return 'center';
    if (horizontal === 'right') return 'right';
    if (horizontal === 'justify' || horizontal === 'distributed') return 'justify';
    if (horizontal === 'left' || horizontal === 'fill') return 'left';
    if (horizontal === 'general' || !horizontal) return valueType === 'number' ? 'right' : 'left';
    return 'left';
  };

  const verticalAlign = (alignment) => {
    const vertical = alignment && alignment.vertical;
    if (vertical === 'top') return 'top';
    if (vertical === 'center' || vertical === 'middle' || vertical === 'justify' || vertical === 'distributed') {
      return 'middle';
    }
    return 'bottom';
  };

  const getStyle = (cell) => {
    if (!cell || !cell.style || !state.mirror || !state.mirror.styles) return {};
    const style = state.mirror.styles[cell.style];
    return style && typeof style === 'object' ? style : {};
  };

  const styleToCss = (style, cell) => {
    const css = [];
    const font = (style && style.font) || {};
    const alignment = (style && style.alignment) || {};
    const border = (style && style.border) || {};
    const fill = (style && style.fill) || null;
    const valueType = cell && cell.value_type;
    const theme = state.mirror && state.mirror.meta && state.mirror.meta.theme;
    const fontScheme = theme && theme.font_scheme;

    const background = fillCss(fill);
    if (background) css.push(`background:${background}`);

    const fontName = sanitizeFontName(font.name)
      || sanitizeFontName(fontScheme && fontScheme.minor)
      || 'Calibri';
    css.push(`font-family:'${fontName}', 'Segoe UI', Arial, sans-serif`);

    const fontSize = Number(font.size);
    css.push(`font-size:${Number.isFinite(fontSize) && fontSize > 0 ? fontSize : 11}pt`);
    css.push(`font-weight:${font.bold ? 700 : 400}`);
    css.push(`font-style:${font.italic ? 'italic' : 'normal'}`);

    const decorations = [];
    if (font.underline && font.underline !== 'none') decorations.push('underline');
    if (font.strike) decorations.push('line-through');
    if (decorations.length) css.push(`text-decoration:${decorations.join(' ')}`);
    if (font.underline === 'double') css.push('text-decoration-style:double');
    if (font.shadow) css.push('text-shadow:1px 1px 1px rgba(15,23,42,.35)');
    css.push(`color:${safeColor(font.color && font.color.hex, '#0f172a')}`);

    css.push(`text-align:${horizontalAlign(alignment, valueType)}`);
    css.push(`vertical-align:${verticalAlign(alignment)}`);
    if (alignment.wrap_text) {
      css.push('white-space:pre-wrap', 'word-break:break-word');
    } else {
      css.push('white-space:nowrap');
    }
    const indent = Number(alignment.indent);
    if (Number.isFinite(indent) && indent > 0) {
      css.push(`padding-left:${4 + indent * 8}px`);
    }

    const sides = [
      ['left', 'border-left'],
      ['right', 'border-right'],
      ['top', 'border-top'],
      ['bottom', 'border-bottom'],
    ];
    for (const [key, property] of sides) {
      const value = borderCss(border[key]);
      if (value) css.push(`${property}:${value}`);
    }
    return css.join(';');
  };

  /* ------------------------------------------------------------------ */
  /* Dimensões, mesclagens e congelamento                                */
  /* ------------------------------------------------------------------ */
  const buildDimensions = (sheet) => {
    const defaultColWidth = Number(sheet.default_col_width);
    const safeDefaultColWidth = Number.isFinite(defaultColWidth) && defaultColWidth > 0 ? defaultColWidth : 8.43;
    const defaultRowHeight = Number(sheet.default_row_height);
    const safeDefaultRowHeight = Number.isFinite(defaultRowHeight) && defaultRowHeight > 0 ? defaultRowHeight : 15;

    const maxCol = Math.max(1, Number(sheet.max_col) || 1);
    const maxRow = Math.max(1, Number(sheet.max_row) || 1);

    const colWidths = new Map();
    for (const column of Array.isArray(sheet.columns) ? sheet.columns : []) {
      if (!column) continue;
      const start = column.min != null
        ? Number(column.min)
        : column.letter
          ? letterToCol(column.letter)
          : null;
      if (!Number.isFinite(start) || start < 1) continue;
      const end = column.max != null ? Number(column.max) : start;
      const width = Number(column.width);
      const safeWidth = Number.isFinite(width) && width > 0 ? width : safeDefaultColWidth;
      for (let col = start; col <= end; col += 1) {
        colWidths.set(col, safeWidth);
      }
    }

    const rowHeights = new Map();
    for (const row of Array.isArray(sheet.rows) ? sheet.rows : []) {
      if (!row) continue;
      const index = Number(row.index);
      if (!Number.isFinite(index) || index < 1) continue;
      const height = Number(row.height);
      const safeHeight = Number.isFinite(height) && height > 0 ? height : safeDefaultRowHeight;
      rowHeights.set(index, safeHeight);
    }

    const widths = [];
    for (let col = 1; col <= maxCol; col += 1) {
      const width = colWidths.get(col) ?? safeDefaultColWidth;
      widths.push(Math.max(20, Math.round(width * 7 + 5)));
    }

    const heights = [];
    for (let row = 1; row <= maxRow; row += 1) {
      const height = rowHeights.get(row) ?? safeDefaultRowHeight;
      heights.push(Math.max(20, Math.round(height * 1.3333)));
    }

    return { widths, heights, maxRow, maxCol };
  };

  const parseMergedRanges = (sheet) => {
    const covered = new Set();
    const anchors = new Map();
    for (const range of Array.isArray(sheet.merged_ranges) ? sheet.merged_ranges : []) {
      const text = String(range ?? '').replace(/\$/g, '');
      const parts = text.split(':');
      if (parts.length !== 2) continue;
      const start = parseRef(parts[0]);
      const end = parseRef(parts[1]);
      if (!start || !end) continue;
      const minRow = Math.min(start.row, end.row);
      const maxRow = Math.max(start.row, end.row);
      const minCol = Math.min(start.col, end.col);
      const maxCol = Math.max(start.col, end.col);
      for (let row = minRow; row <= maxRow; row += 1) {
        for (let col = minCol; col <= maxCol; col += 1) {
          const ref = formatRef(row, col);
          if (row === minRow && col === minCol) {
            anchors.set(ref, {
              row,
              col,
              rowspan: maxRow - minRow + 1,
              colspan: maxCol - minCol + 1,
              range: text,
            });
          } else {
            covered.add(ref);
          }
        }
      }
    }
    return { covered, anchors };
  };

  const parseFreeze = (freezePanes) => {
    if (!freezePanes) return { rows: 0, cols: 0 };
    const parsed = parseRef(freezePanes);
    if (!parsed) return { rows: 0, cols: 0 };
    return { rows: Math.max(0, parsed.row - 1), cols: Math.max(0, parsed.col - 1) };
  };

  const isGapEditable = (sheet, row, col) => {
    const config = (state.mirror && state.mirror.meta && state.mirror.meta.config) || {};
    const headerRows = Array.isArray(config.header_rows) ? config.header_rows : [];
    const headerCols = Array.isArray(config.header_cols) ? config.header_cols : [];
    if (headerRows.includes(row) || headerCols.includes(col)) return false;
    if (config.treat_no_fill_as_editable === false) return false;
    return true;
  };

  /* ------------------------------------------------------------------ */
  /* Renderização                                                        */
  /* ------------------------------------------------------------------ */
  const renderProjects = () => {
    if (!els.projectSelect) return;
    const current = state.project && state.project.slug ? state.project.slug : '';
    const options = ['<option value="">Selecione um projeto</option>'];
    for (const project of state.projects) {
      if (!project || !project.slug) continue;
      const label = project.source_name || project.slug;
      options.push(`<option value="${escapeAttr(project.slug)}">${escapeHtml(label)}</option>`);
    }
    els.projectSelect.innerHTML = options.join('');
    els.projectSelect.value = state.projects.some((project) => project.slug === current) ? current : '';

    const hasProjects = state.projects.length > 0;
    if (els.emptyState) {
      els.emptyState.classList.toggle('hidden', hasProjects);
      els.emptyState.classList.toggle('flex', !hasProjects);
    }
    if (els.workspace) {
      els.workspace.classList.toggle('hidden', !hasProjects);
      els.workspace.classList.toggle('flex', hasProjects);
    }
    if (els.exportButton) els.exportButton.disabled = !state.project || !state.mirror;
    if (els.clearSheet) els.clearSheet.disabled = !state.activeSheet;
  };

  const renderSheetTabs = () => {
    if (!els.sheetTabs) return;
    const sheets = (state.mirror && Array.isArray(state.mirror.sheets)) ? state.mirror.sheets : [];
    els.sheetTabs.innerHTML = sheets.map((sheet) => {
      if (!sheet || !sheet.name) return '';
      const active = sheet.name === state.activeSheetName;
      const color = safeColor(sheet.tab_color && sheet.tab_color.hex, '#6366f1');
      const hidden = sheet.state && sheet.state !== 'visible';
      const title = `${sheet.name}${hidden ? ' (oculta)' : ''}`;
      return `<button type="button" role="tab" aria-selected="${active ? 'true' : 'false'}" data-sheet="${escapeAttr(sheet.name)}" title="${escapeAttr(title)}" class="sheet-tab${active ? ' active' : ''}"><span class="tab-dot" style="background:${escapeAttr(color)}"></span><span>${escapeHtml(sheet.name)}</span>${hidden ? '<span class="tab-hidden">oculta</span>' : ''}</button>`;
    }).join('');
  };

  const renderWarnings = () => {
    const warnings = [];
    const metaWarnings = state.mirror && state.mirror.meta && state.mirror.meta.warnings;
    if (Array.isArray(metaWarnings)) warnings.push(...metaWarnings);
    const projectWarnings = state.project && state.project.warnings;
    if (Array.isArray(projectWarnings)) warnings.push(...projectWarnings);
    const uniqueWarnings = unique(warnings.filter(Boolean));

    if (!uniqueWarnings.length) {
      if (els.warningsBanner) els.warningsBanner.classList.add('hidden');
      if (els.warningsSummary) {
        els.warningsSummary.classList.add('hidden');
        els.warningsSummary.classList.remove('inline-flex');
      }
      return;
    }

    if (els.warningsBanner) els.warningsBanner.classList.remove('hidden');
    if (els.warningsSummary) {
      els.warningsSummary.classList.remove('hidden');
      els.warningsSummary.classList.add('inline-flex');
      els.warningsSummary.textContent = `${uniqueWarnings.length} aviso(s) do processamento`;
    }
    if (els.warningsCount) els.warningsCount.textContent = `(${uniqueWarnings.length})`;
    if (els.warningsList) {
      els.warningsList.innerHTML = uniqueWarnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join('');
    }
  };

  const renderStats = () => {
    if (!els.projectStats) return;
    const stats = (state.mirror && state.mirror.meta && state.mirror.meta.stats)
      || (state.project && state.project.stats)
      || {};
    const parts = [];
    if (stats.sheets != null) parts.push(`Abas: ${stats.sheets}`);
    if (stats.styles != null) parts.push(`Estilos: ${stats.styles}`);
    if (stats.cells != null) parts.push(`Células: ${stats.cells}`);
    els.projectStats.textContent = parts.join(' · ');
  };

  const renderCell = (sheet, cell, position) => {
    const style = getStyle(cell);
    const cssParts = [];
    const baseCss = styleToCss(style, cell);
    if (baseCss) cssParts.push(baseCss);

    const background = fillCss(style && style.fill) || '#ffffff';
    const classes = ['cell'];
    const isEditable = Boolean(cell && cell.editavel);
    const isFormulaDisplay = Boolean(cell && cell.formula && (cell.value === null || cell.value === undefined));
    if (isEditable) classes.push('cell-editable');
    if (isFormulaDisplay) classes.push('cell-formula');
    if (cell && cell.value_type === 'error') classes.push('cell-error');
    if (style && style.alignment && style.alignment.wrap_text) classes.push('cell-wrap');

    if (position.isStickyRow && position.isStickyCol) {
      classes.push('sticky-both-cell');
      cssParts.push('position:sticky', `top:${position.rowOffsets[position.row - 1] || 0}px`, `left:${position.colOffsets[position.col - 1] || 0}px`, 'z-index:3', `background:${background}`);
    } else if (position.isStickyRow) {
      classes.push('sticky-row-cell');
      cssParts.push('position:sticky', `top:${position.rowOffsets[position.row - 1] || 0}px`, 'z-index:2', `background:${background}`);
    } else if (position.isStickyCol) {
      classes.push('sticky-col-cell');
      cssParts.push('position:sticky', `left:${position.colOffsets[position.col - 1] || 0}px`, 'z-index:1', `background:${background}`);
    }

    const attrs = [
      `class="${escapeAttr(classes.join(' '))}"`,
      `style="${escapeAttr(cssParts.join(';'))}"`,
    ];
    if (cell && cell.rowspan && cell.rowspan > 1) attrs.push(`rowspan="${Number(cell.rowspan)}"`);
    if (cell && cell.colspan && cell.colspan > 1) attrs.push(`colspan="${Number(cell.colspan)}"`);

    const titles = [];
    if (cell && cell.formula) titles.push(`Fórmula: ${cell.formula}`);
    if (cell && cell.merged) titles.push(`Mesclado: ${cell.merged}`);
    if (titles.length) attrs.push(`title="${escapeAttr(titles.join(' · '))}"`);

    if (isEditable) {
      const ref = cell.ref;
      const currentValue = state.draft && Object.prototype.hasOwnProperty.call(state.draft, ref)
        ? state.draft[ref]
        : '';
      const placeholder = formatCellValue(cell, style);
      const inputMode = cell.value_type === 'number' ? ' inputmode="decimal"' : '';
      const input = `<input class="cell-input" type="text" data-ref="${escapeAttr(ref)}" value="${escapeAttr(currentValue)}" placeholder="${escapeAttr(placeholder)}" aria-label="Célula ${escapeAttr(ref)} da aba ${escapeAttr(sheet.name)}" autocomplete="off" spellcheck="false"${inputMode}>`;
      return `<td ${attrs.join(' ')}>${input}</td>`;
    }

    const display = formatCellValue(cell, style);
    const content = display === '' ? '&nbsp;' : escapeHtml(display);
    return `<td ${attrs.join(' ')}>${content}</td>`;
  };

  const renderGrid = () => {
    if (!els.spreadsheet) return;
    const sheet = state.activeSheet;
    if (!sheet) {
      els.spreadsheet.innerHTML = '';
      return;
    }

    const { widths, heights, maxRow, maxCol } = buildDimensions(sheet);
    const totalWidth = widths.reduce((sum, width) => sum + width, 0);
    const frozen = parseFreeze(sheet.freeze_panes);
    const frozenRows = Math.min(frozen.rows, maxRow);
    const frozenCols = Math.min(frozen.cols, maxCol);

    const rowOffsets = [0];
    for (let index = 0; index < frozenRows; index += 1) {
      rowOffsets.push(rowOffsets[index] + (heights[index] || 20));
    }
    const colOffsets = [0];
    for (let index = 0; index < frozenCols; index += 1) {
      colOffsets.push(colOffsets[index] + (widths[index] || 60));
    }

    const { covered, anchors } = parseMergedRanges(sheet);
    const cellMap = new Map();
    for (const cell of Array.isArray(sheet.cells) ? sheet.cells : []) {
      if (cell && cell.ref) cellMap.set(String(cell.ref).toUpperCase(), cell);
    }

    const colgroup = widths.map((width) => `<col style="width:${width}px">`).join('');
    const rows = [];
    for (let row = 1; row <= maxRow; row += 1) {
      const rowHeight = heights[row - 1] || 20;
      const cells = [];
      for (let col = 1; col <= maxCol; col += 1) {
        const ref = formatRef(row, col);
        if (covered.has(ref)) continue;

        const anchor = anchors.get(ref);
        let cell = cellMap.get(ref);
        if (!cell) {
          const editable = anchor
            ? ((state.mirror && state.mirror.meta && state.mirror.meta.config && state.mirror.meta.config.fixed_if_merged === false)
              ? isGapEditable(sheet, row, col)
              : false)
            : isGapEditable(sheet, row, col);
          cell = {
            ref,
            row,
            col,
            value: null,
            value_type: 'null',
            formula: null,
            cached_value: null,
            editavel: editable,
            editavel_motivo: editable ? ['default_editable'] : ['gap_fixed'],
            style: null,
            merged: anchor ? anchor.range : undefined,
            rowspan: anchor ? anchor.rowspan : undefined,
            colspan: anchor ? anchor.colspan : undefined,
          };
        } else if (anchor && !cell.merged) {
          cell = { ...cell, merged: anchor.range, rowspan: anchor.rowspan, colspan: anchor.colspan };
        }

        cells.push(renderCell(sheet, cell, {
          row,
          col,
          isStickyRow: row <= frozenRows,
          isStickyCol: col <= frozenCols,
          rowOffsets,
          colOffsets,
        }));
      }
      rows.push(`<tr style="height:${rowHeight}px">${cells.join('')}</tr>`);
    }

    els.spreadsheet.innerHTML = `<colgroup>${colgroup}</colgroup><tbody>${rows.join('')}</tbody>`;
    els.spreadsheet.style.width = `${totalWidth}px`;
    els.spreadsheet.style.tableLayout = 'fixed';
    if (els.gridScroll) {
      els.gridScroll.scrollTop = 0;
      els.gridScroll.scrollLeft = 0;
    }
  };

  const renderSheet = () => {
    const sheet = state.activeSheet;
    if (!sheet || !state.project) return;
    state.draft = loadDraftForSheet(state.project.slug, sheet.name);
    renderGrid();
    if (els.sheetInfo) {
      const cellsCount = Array.isArray(sheet.cells) ? sheet.cells.length : 0;
      els.sheetInfo.textContent = `${sheet.name} · ${Math.max(1, Number(sheet.max_row) || 1)} linhas × ${Math.max(1, Number(sheet.max_col) || 1)} colunas · ${cellsCount} células no espelho`;
    }
    if (els.clearSheet) els.clearSheet.disabled = false;
  };

  const renderProject = () => {
    if (!state.mirror) {
      showEmptyState();
      return;
    }
    if (els.emptyState) {
      els.emptyState.classList.add('hidden');
      els.emptyState.classList.remove('flex');
    }
    if (els.workspace) {
      els.workspace.classList.remove('hidden');
      els.workspace.classList.add('flex');
    }
    renderProjects();
    renderSheetTabs();
    renderWarnings();
    renderStats();
    renderSheet();
  };

  const showEmptyState = () => {
    state.project = null;
    state.mirror = null;
    state.activeSheet = null;
    state.activeSheetName = null;
    state.draft = {};
    if (els.spreadsheet) els.spreadsheet.innerHTML = '';
    if (els.sheetTabs) els.sheetTabs.innerHTML = '';
    if (els.sheetInfo) els.sheetInfo.textContent = '';
    if (els.projectStats) els.projectStats.textContent = '';
    if (els.warningsBanner) els.warningsBanner.classList.add('hidden');
    if (els.warningsSummary) {
      els.warningsSummary.classList.add('hidden');
      els.warningsSummary.classList.remove('inline-flex');
    }
    if (els.emptyState) {
      const title = els.emptyState.querySelector('h2');
      if (title) {
        title.textContent = state.projects.length ? 'Nenhum projeto selecionado' : 'Nenhum projeto carregado';
      }
      els.emptyState.classList.remove('hidden');
      els.emptyState.classList.add('flex');
    }
    if (els.workspace) {
      els.workspace.classList.add('hidden');
      els.workspace.classList.remove('flex');
    }
    if (els.projectSelect) els.projectSelect.value = '';
    if (els.exportButton) els.exportButton.disabled = true;
    if (els.clearSheet) els.clearSheet.disabled = true;
  };

  /* ------------------------------------------------------------------ */
  /* Rascunhos e persistência                                            */
  /* ------------------------------------------------------------------ */
  const loadDraftForSheet = (slug, sheetName) => {
    if (!slug || !sheetName) return {};
    const draft = storage.get(draftKey(slug, sheetName), {});
    return draft && typeof draft === 'object' ? draft : {};
  };

  const updateAutosaveIndicator = () => {
    if (!els.autosaveText) return;
    const time = new Date().toLocaleTimeString('pt-BR');
    els.autosaveText.textContent = `Rascunho salvo no navegador às ${time}.`;
  };

  const saveDraftNow = () => {
    window.clearTimeout(state.saveTimer);
    state.saveTimer = null;
    if (!state.project || !state.project.slug || !state.activeSheetName) return;
    const key = draftKey(state.project.slug, state.activeSheetName);
    const hasValues = state.draft && Object.keys(state.draft).length > 0;
    let saved = true;
    if (hasValues) {
      saved = storage.set(key, state.draft);
    } else {
      storage.remove(key);
    }
    storage.set(lastSheetKey(state.project.slug), state.activeSheetName);
    storage.set(lastContextKey, { project: state.project.slug, sheet: state.activeSheetName });
    if (!saved && !state.storageErrorShown) {
      state.storageErrorShown = true;
      showToast('Não foi possível salvar o rascunho no navegador. O limite de armazenamento pode ter sido atingido.', 'warning');
    }
    updateAutosaveIndicator();
  };

  const scheduleSave = () => {
    window.clearTimeout(state.saveTimer);
    state.saveTimer = window.setTimeout(() => {
      saveDraftNow();
    }, 300);
  };

  const onGridInput = (event) => {
    const input = event.target && event.target.closest ? event.target.closest('input.cell-input') : null;
    if (!input) return;
    const ref = input.dataset.ref;
    if (!ref) return;
    if (!state.draft) state.draft = {};
    state.draft[ref] = input.value;
    if (els.autosaveText) els.autosaveText.textContent = 'Salvando rascunho...';
    scheduleSave();
  };

  const onGridFocusOut = (event) => {
    const input = event.target && event.target.closest ? event.target.closest('input.cell-input') : null;
    if (input) saveDraftNow();
  };

  /* ------------------------------------------------------------------ */
  /* API e fluxo de projetos                                             */
  /* ------------------------------------------------------------------ */
  const loadProjects = async () => {
    const payload = await fetchJSON('/api/projects');
    state.projects = Array.isArray(payload && payload.projects) ? payload.projects : [];
    renderProjects();
    return state.projects;
  };

  const loadProject = async (slug, preferredSheet = null) => {
    if (!slug) {
      showEmptyState();
      return;
    }
    setBusy(true, 'Carregando projeto...');
    try {
      const mirror = await fetchJSON(`/api/projects/${encodeURIComponent(slug)}/mirror`);
      const sheets = mirror && Array.isArray(mirror.sheets) ? mirror.sheets : [];
      if (!sheets.length) throw new Error('O projeto não contém abas.');
      const project = state.projects.find((item) => item.slug === slug) || { slug, source_name: slug };

      state.project = project;
      state.mirror = mirror;
      const savedSheet = storage.get(lastSheetKey(slug), null);
      const candidates = [preferredSheet, savedSheet, sheets[0].name];
      const sheetName = candidates.find((name) => name && sheets.some((sheet) => sheet.name === name)) || sheets[0].name;
      state.activeSheetName = sheetName;
      state.activeSheet = sheets.find((sheet) => sheet.name === sheetName) || sheets[0];
      state.draft = loadDraftForSheet(slug, sheetName);
      storage.set(lastContextKey, { project: slug, sheet: sheetName });
      storage.set(lastSheetKey(slug), sheetName);
      renderProject();
      window.dispatchEvent(new CustomEvent('mirror:project-loaded', { detail: { slug, sheet: sheetName } }));
    } catch (error) {
      showToast(error.message || 'Falha ao carregar o projeto.', 'error');
      if (els.projectSelect && state.project && state.project.slug) {
        els.projectSelect.value = state.project.slug;
      }
      if (!state.mirror) showEmptyState();
    } finally {
      setBusy(false);
    }
  };

  const switchSheet = (name) => {
    if (!state.mirror || !state.project) return;
    if (name === state.activeSheetName) return;
    saveDraftNow();
    const sheet = state.mirror.sheets.find((item) => item.name === name);
    if (!sheet) return;
    state.activeSheetName = name;
    state.activeSheet = sheet;
    state.draft = loadDraftForSheet(state.project.slug, name);
    storage.set(lastContextKey, { project: state.project.slug, sheet: name });
    storage.set(lastSheetKey(state.project.slug), name);
    renderSheetTabs();
    renderSheet();
    window.dispatchEvent(new CustomEvent('mirror:project-loaded', {
      detail: { slug: state.project.slug, sheet: name },
    }));
  };

  const refreshProjects = async () => {
    saveDraftNow();
    setBusy(true, 'Atualizando projetos...');
    try {
      const currentSlug = state.project && state.project.slug ? state.project.slug : null;
      const currentSheet = state.activeSheetName || null;
      await loadProjects();
      if (!state.projects.length) {
        showEmptyState();
        return;
      }
      const target = state.projects.some((project) => project.slug === currentSlug)
        ? currentSlug
        : state.projects[0].slug;
      await loadProject(target, currentSheet);
      showToast('Lista de projetos atualizada.', 'success');
    } catch (error) {
      showToast(error.message || 'Falha ao atualizar os projetos.', 'error');
    } finally {
      setBusy(false);
    }
  };

  const uploadFile = async (file) => {
    if (!file) return;
    if (!/\.xlsx$/i.test(file.name || '')) {
      showToast('Envie um arquivo com extensão .xlsx.', 'error');
      return;
    }
    saveDraftNow();
    setBusy(true, 'Enviando e processando a planilha...');
    try {
      const form = new FormData();
      form.append('file', file);
      const response = await fetch('/api/upload', {
        method: 'POST',
        body: form,
        headers: { Accept: 'application/json' },
      });
      let payload = null;
      const contentType = response.headers.get('Content-Type') || '';
      if (contentType.includes('application/json')) {
        payload = await response.json().catch(() => null);
      }
      if (!response.ok) {
        throw new Error((payload && payload.error) || `Erro ${response.status}`);
      }
      const project = payload && payload.project;
      if (!project || !project.slug) throw new Error('Resposta inválida do servidor.');

      await loadProjects();
      await loadProject(project.slug);
      showToast(`Planilha "${project.source_name || project.slug}" enviada com sucesso.`, 'success');
      if (Array.isArray(payload.warnings) && payload.warnings.length) {
        showToast(`O processamento gerou ${payload.warnings.length} aviso(s).`, 'warning');
      }
    } catch (error) {
      showToast(error.message || 'Falha ao enviar a planilha.', 'error');
    } finally {
      setBusy(false);
      if (els.fileInput) els.fileInput.value = '';
    }
  };

  const collectProjectDrafts = () => {
    const data = {};
    if (!state.project || !state.project.slug || !state.mirror || !Array.isArray(state.mirror.sheets)) {
      return data;
    }
    saveDraftNow();
    for (const sheet of state.mirror.sheets) {
      if (!sheet || !sheet.name) continue;
      const draft = loadDraftForSheet(state.project.slug, sheet.name);
      if (draft && Object.keys(draft).length) {
        data[sheet.name] = draft;
      }
    }
    return data;
  };

  const exportProject = async () => {
    if (!state.project || !state.project.slug || !state.mirror) return;
    const data = collectProjectDrafts();
    const baseName = String(state.project.source_name || state.project.slug).replace(/\.xlsx$/i, '');
    const filename = `${baseName}_preenchido.xlsx`;

    setBusy(true, 'Gerando o arquivo .xlsx...');
    if (els.exportButton) els.exportButton.disabled = true;
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(state.project.slug)}/export`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        },
        body: JSON.stringify({ data, filename }),
      });
      if (!response.ok) {
        let message = `Erro ${response.status}`;
        const contentType = response.headers.get('Content-Type') || '';
        if (contentType.includes('application/json')) {
          const payload = await response.json().catch(() => null);
          message = (payload && payload.error) || message;
        }
        throw new Error(message);
      }
      const blob = await response.blob();
      let downloadName = filename;
      const disposition = response.headers.get('Content-Disposition') || '';
      const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
      if (utf8Match) {
        try {
          downloadName = decodeURIComponent(utf8Match[1]);
        } catch (error) {
          downloadName = filename;
        }
      } else {
        const simpleMatch = /filename="?([^";]+)"?/i.exec(disposition);
        if (simpleMatch) downloadName = simpleMatch[1];
      }

      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = downloadName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1500);
      showToast('Arquivo .xlsx gerado. O download deve começar.', 'success');
    } catch (error) {
      showToast(error.message || 'Falha ao gerar o arquivo .xlsx.', 'error');
    } finally {
      setBusy(false);
      if (els.exportButton) els.exportButton.disabled = !state.project || !state.mirror;
    }
  };

  const clearActiveSheetDraft = () => {
    if (!state.project || !state.project.slug || !state.activeSheetName) return;
    const confirmed = window.confirm(`Limpar todos os valores preenchidos na aba "${state.activeSheetName}"?`);
    if (!confirmed) return;
    storage.remove(draftKey(state.project.slug, state.activeSheetName));
    state.draft = {};
    renderGrid();
    updateAutosaveIndicator();
    showToast('Rascunho da aba limpo.', 'info');
  };

  /* ------------------------------------------------------------------ */
  /* Eventos e inicialização                                             */
  /* ------------------------------------------------------------------ */
  const bindEvents = () => {
    if (els.projectSelect) {
      els.projectSelect.addEventListener('change', (event) => {
        const slug = event.target.value;
        saveDraftNow();
        if (!slug) {
          showEmptyState();
          return;
        }
        loadProject(slug);
      });
    }
    if (els.refreshProjects) els.refreshProjects.addEventListener('click', refreshProjects);
    if (els.uploadButton) els.uploadButton.addEventListener('click', () => els.fileInput && els.fileInput.click());
    if (els.emptyUploadButton) els.emptyUploadButton.addEventListener('click', () => els.fileInput && els.fileInput.click());
    if (els.fileInput) {
      els.fileInput.addEventListener('change', (event) => {
        const file = event.target.files && event.target.files[0];
        if (file) uploadFile(file);
      });
    }
    if (els.exportButton) els.exportButton.addEventListener('click', exportProject);
    if (els.clearSheet) els.clearSheet.addEventListener('click', clearActiveSheetDraft);
    if (els.sheetTabs) {
      els.sheetTabs.addEventListener('click', (event) => {
        const button = event.target && event.target.closest ? event.target.closest('button[data-sheet]') : null;
        if (button && button.dataset.sheet) switchSheet(button.dataset.sheet);
      });
    }
    if (els.spreadsheet) {
      els.spreadsheet.addEventListener('input', onGridInput);
      els.spreadsheet.addEventListener('focusout', onGridFocusOut);
    }
    window.addEventListener('beforeunload', saveDraftNow);

    if (els.dropZone) {
      ['dragenter', 'dragover'].forEach((type) => {
        els.dropZone.addEventListener(type, (event) => {
          event.preventDefault();
          els.dropZone.classList.add('border-indigo-500', 'bg-indigo-50');
        });
      });
      ['dragleave', 'drop'].forEach((type) => {
        els.dropZone.addEventListener(type, () => {
          els.dropZone.classList.remove('border-indigo-500', 'bg-indigo-50');
        });
      });
    }

    document.addEventListener('dragover', (event) => {
      if (event.dataTransfer && event.dataTransfer.types && event.dataTransfer.types.includes('Files')) {
        event.preventDefault();
      }
    });
    document.addEventListener('drop', (event) => {
      if (!event.dataTransfer || !event.dataTransfer.types || !event.dataTransfer.types.includes('Files')) return;
      event.preventDefault();
      const file = event.dataTransfer.files && event.dataTransfer.files[0];
      if (file) uploadFile(file);
    });
  };

  const init = async () => {
    bindEvents();
    setBusy(true, 'Carregando projetos...');
    try {
      await loadProjects();
      if (!state.projects.length) {
        showEmptyState();
        return;
      }
      const lastContext = storage.get(lastContextKey, {}) || {};
      let slug = lastContext.project;
      if (!state.projects.some((project) => project.slug === slug)) {
        slug = state.projects[0].slug;
      }
      let preferredSheet = null;
      if (lastContext.project === slug && typeof lastContext.sheet === 'string') {
        preferredSheet = lastContext.sheet;
      }
      await loadProject(slug, preferredSheet);
    } catch (error) {
      showToast(error.message || 'Falha ao carregar os projetos.', 'error');
      showEmptyState();
    } finally {
      setBusy(false);
    }
  };

  /* ------------------------------------------------------------------ */
  /* API pública para a camada de chat                                   */
  /* ------------------------------------------------------------------ */
  const applyDraftEdits = (data) => {
    if (!state.project || !state.project.slug || !data || typeof data !== 'object') return 0;
    let applied = 0;
    for (const [sheetName, cells] of Object.entries(data)) {
      if (!cells || typeof cells !== 'object') continue;
      const existing = sheetName === state.activeSheetName
        ? (state.draft || {})
        : loadDraftForSheet(state.project.slug, sheetName);
      const merged = { ...existing };
      for (const [ref, value] of Object.entries(cells)) {
        if (!ref) continue;
        merged[String(ref).toUpperCase()] = value;
        applied += 1;
      }
      if (sheetName === state.activeSheetName) {
        state.draft = merged;
      }
      const key = draftKey(state.project.slug, sheetName);
      if (Object.keys(merged).length) storage.set(key, merged);
      else storage.remove(key);
    }
    if (applied) {
      saveDraftNow();
      renderGrid();
      updateAutosaveIndicator();
      window.dispatchEvent(new CustomEvent('mirror:draft-updated', { detail: { applied } }));
    }
    return applied;
  };

  window.MirrorApp = {
    getContext() {
      const active = document.activeElement;
      return {
        slug: state.project && state.project.slug ? state.project.slug : null,
        project: state.project,
        sheet: state.activeSheetName,
        mirror: state.mirror,
        draft: state.draft || {},
        focusedRef: active && active.dataset ? active.dataset.ref || null : null,
        hasProjects: state.projects.length > 0,
      };
    },
    applyDraftEdits,
    openProject(slug) {
      if (!slug) return Promise.resolve();
      saveDraftNow();
      return loadProject(slug);
    },
    async refreshAndOpen(slug) {
      await loadProjects();
      await loadProject(slug);
    },
    showToast,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
