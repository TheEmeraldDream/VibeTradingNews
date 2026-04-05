/* ─────────────────────────────────────────────────────────────
   News Aggregator — Frontend
   • WebSocket  : live snapshots (news + positions)
   • SSE        : streaming Claude analysis
   • REST       : news refresh
───────────────────────────────────────────────────────────── */

// Auto-detect server URL from the page's own origin — works for local and deployed.
const API = window.location.origin;
const WS  = (window.location.protocol === 'https:' ? 'wss:' : 'ws:') + '//' + window.location.host + '/ws';

// Disable raw HTML pass-through in marked (prevents XSS from AI-generated content)
marked.use({
  renderer: {
    html: ({ raw }) => String(raw).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
  },
});

let ws          = null;
let streaming   = false;
let retryTimer  = null;
let activeFilter = 'ALL';
let allArticles  = [];
let allPositions = [];
let allAccounts  = [];
let enabledAccounts   = new Set();
let collapsedAccounts = new Set(JSON.parse(localStorage.getItem('collapsedAccounts') || '[]'));
let pnlChart          = null;
let pnlSeries         = null;
let activePeriod      = '1M';
let lastNewsUpdateIso = null;

// ─── Init ────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initResizeHandles();
  initPnlChart();
  connectWS();
  checkClaudeStatus();
  setInterval(() => { if (lastNewsUpdateIso) renderNewsTimestamp(lastNewsUpdateIso); }, 1000);
});

// ─── Panel resize ────────────────────────────────────────────
function initResizeHandles() {
  const grid = document.querySelector('main.grid');
  const saved = JSON.parse(localStorage.getItem('panelWidths') || '{}');
  if (saved.left)  grid.style.setProperty('--w-left',  saved.left);
  if (saved.right) grid.style.setProperty('--w-right', saved.right);

  document.querySelectorAll('.resize-handle').forEach(handle => {
    handle.addEventListener('mousedown', e => {
      e.preventDefault();
      const col    = handle.dataset.col;
      const startX = e.clientX;
      const prop   = col === 'left' ? '--w-left' : '--w-right';
      const min    = col === 'left' ? 160 : 220;
      const max    = col === 'left' ? 520 : 600;
      const cols   = getComputedStyle(grid).gridTemplateColumns.split(' ');
      const startW = col === 'left' ? parseFloat(cols[0]) : parseFloat(cols[4]);

      handle.classList.add('dragging');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';

      const onMove = e => {
        const delta = e.clientX - startX;
        const newW  = Math.min(max, Math.max(min,
          col === 'left' ? startW + delta : startW - delta
        ));
        grid.style.setProperty(prop, newW + 'px');
      };

      const onUp = () => {
        handle.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        const cols = getComputedStyle(grid).gridTemplateColumns.split(' ');
        localStorage.setItem('panelWidths', JSON.stringify({
          left: cols[0], right: cols[4],
        }));
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup',   onUp);
      };

      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup',   onUp);
    });
  });
}

// ─── P&L candlestick chart ───────────────────────────────────
function initPnlChart() {
  const container = document.getElementById('pnlChart');

  pnlChart = LightweightCharts.createChart(container, {
    height: 160,
    layout: {
      background: { color: '#0a0a0a' },
      textColor:  '#444444',
      fontFamily: "'JetBrains Mono', 'Fira Mono', monospace",
      fontSize:   10,
    },
    localization: {
      priceFormatter: v => '$' + Number(v).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 }),
    },
    grid: {
      vertLines: { color: '#181818' },
      horzLines: { color: '#181818' },
    },
    timeScale: {
      borderColor:     '#252525',
      fixLeftEdge:     true,
      fixRightEdge:    true,
    },
    rightPriceScale: {
      borderColor: '#252525',
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
    },
    handleScroll:  false,
    handleScale:   false,
  });

  pnlSeries = pnlChart.addCandlestickSeries({
    upColor:        '#00d97e',
    downColor:      '#ff4757',
    borderUpColor:   '#00d97e',
    borderDownColor: '#ff4757',
    wickUpColor:    '#00d97e',
    wickDownColor:  '#ff4757',
  });

  // Keep chart width in sync with its container as panels resize
  new ResizeObserver(() => {
    if (container.clientWidth > 0) pnlChart.resize(container.clientWidth, 160);
  }).observe(container);

  loadPnlHistory();
}

function setChartPeriod(period) {
  activePeriod = period;
  document.querySelectorAll('.range-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.period === period);
  });
  const picker = document.getElementById('chartDatePicker');
  if (period === 'CUSTOM') {
    picker.classList.add('visible');
    // Default end to today, start to 30 days ago
    const today = new Date();
    const prior = new Date(today);
    prior.setDate(prior.getDate() - 30);
    document.getElementById('chartEnd').value   = today.toISOString().slice(0, 10);
    document.getElementById('chartStart').value = prior.toISOString().slice(0, 10);
  } else {
    picker.classList.remove('visible');
    loadPnlHistory();
  }
}

function applyCustomRange() {
  const start = document.getElementById('chartStart').value;
  const end   = document.getElementById('chartEnd').value;
  if (start && end && start <= end) loadPnlHistory(start, end);
}

async function loadPnlHistory(customStart, customEnd) {
  let url = `${API}/api/pnl-history?period=${activePeriod}`;
  if (activePeriod === 'CUSTOM' && customStart && customEnd) {
    url += `&start=${customStart}&end=${customEnd}`;
  }
  const enabledSyms = getEnabledSymbols();
  if (enabledSyms && enabledSyms.length) {
    url += `&symbols=${enabledSyms.join(',')}`;
  }
  try {
    const res  = await fetch(url);
    const data = await res.json();
    if (Array.isArray(data) && data.length) {
      const intraday = activePeriod === '1D' || activePeriod === '5D';
      pnlChart.applyOptions({ timeScale: { timeVisible: intraday, secondsVisible: false } });
      pnlSeries.setData(data);
      pnlChart.timeScale().fitContent();
    }
  } catch (e) {
    console.error('P&L history load failed:', e);
  }
}

// ─── WebSocket ───────────────────────────────────────────────
function connectWS() {
  if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
  ws = new WebSocket(WS);

  ws.onopen = () => {
    setBrokerStatus('connecting');
  };

  ws.onmessage = e => {
    try {
      const data = JSON.parse(e.data);
      if (data.type === 'snapshot') applySnapshot(data);
    } catch (_) {}
  };

  ws.onerror = () => {};

  ws.onclose = () => {
    setBrokerStatus('disconnected');
    retryTimer = setTimeout(connectWS, 3000);
  };
}

function applySnapshot(data) {
  if (data.account) {
    renderAccount(data.account);
    setBrokerStatus(data.ai_available ? 'connected' : 'demo');
  }
  if (data.accounts !== undefined) initAccounts(data.accounts);
  if (data.positions !== undefined) renderHoldings(data.positions);
  if (data.news !== undefined) {
    allArticles = data.news;
    renderFilterChips(data.positions || []);
    renderNews();
  }
  if (data.news_updated) renderNewsTimestamp(data.news_updated);
  loadPnlHistory();
}

// ─── Account ─────────────────────────────────────────────────
function renderAccount(a) {
  setText('equity',      fmt$(a.equity));
  setText('cash',        fmt$(a.cash));
  setText('buyingPower', fmt$(a.buying_power));

  const pnlEl = document.getElementById('dailyPnl');
  pnlEl.textContent = fmtSignPct(a.daily_pnl, a.daily_pnl_pct);
  pnlEl.className = 'metric-value ' + (a.daily_pnl >= 0 ? 'green' : 'red');
}

// ─── Account management ──────────────────────────────────────
function initAccounts(accounts) {
  allAccounts = accounts;
  if (!accounts.length) return;

  const saved = localStorage.getItem('enabledAccounts');
  if (saved !== null) {
    try { enabledAccounts = new Set(JSON.parse(saved)); }
    catch (_) { enabledAccounts = new Set(accounts.map(a => a.id)); }
  } else {
    enabledAccounts = new Set(accounts.map(a => a.id));
    localStorage.setItem('enabledAccounts', JSON.stringify([...enabledAccounts]));
  }
}

function toggleAccount(accountId) {
  if (enabledAccounts.has(accountId)) {
    enabledAccounts.delete(accountId);
  } else {
    enabledAccounts.add(accountId);
  }
  localStorage.setItem('enabledAccounts', JSON.stringify([...enabledAccounts]));
  renderHoldings(allPositions);
  renderNews();
  loadPnlHistory();
}

function toggleCollapse(accountId) {
  if (collapsedAccounts.has(accountId)) {
    collapsedAccounts.delete(accountId);
  } else {
    collapsedAccounts.add(accountId);
  }
  localStorage.setItem('collapsedAccounts', JSON.stringify([...collapsedAccounts]));
  renderHoldings(allPositions);
}

// Returns symbols belonging to enabled accounts, or null if no accounts are configured.
function getEnabledSymbols() {
  if (!allAccounts.length) return null;
  return allPositions
    .filter(p => !p.account || enabledAccounts.has(p.account))
    .map(p => p.symbol);
}

// ─── Holdings ────────────────────────────────────────────────
function renderHoldings(positions) {
  allPositions = positions;
  const list = document.getElementById('holdingsList');
  document.getElementById('holdingsCount').textContent = positions.length;

  if (!positions.length) {
    list.innerHTML = '<div class="holdings-empty">No open positions</div>';
    return;
  }

  // Group positions by account
  const groups = new Map(); // accountId -> {name, positions[]}
  const ungrouped = [];
  for (const p of positions) {
    if (p.account) {
      if (!groups.has(p.account)) {
        const meta = allAccounts.find(a => a.id === p.account);
        groups.set(p.account, { name: meta ? meta.name : p.account, positions: [] });
      }
      groups.get(p.account).positions.push(p);
    } else {
      ungrouped.push(p);
    }
  }

  let html = '';
  for (const [accountId, { name, positions: acctPositions }] of groups) {
    const on        = enabledAccounts.has(accountId);
    const collapsed = collapsedAccounts.has(accountId);
    html += `
      <div class="account-group">
        <div class="account-header" onclick="toggleCollapse('${escHtml(accountId)}')">
          <div class="account-header-left">
            <span class="account-chevron${collapsed ? '' : ' open'}">▶</span>
            <span class="account-name">${escHtml(name.toUpperCase())}</span>
          </div>
          <span class="account-toggle ${on ? 'on' : 'off'}"
                onclick="event.stopPropagation(); toggleAccount('${escHtml(accountId)}')"
                title="${on ? 'Included in news & chart — click to exclude' : 'Excluded from news & chart — click to include'}">
            ${on ? 'ON' : 'OFF'}
          </span>
        </div>
        <div class="account-holdings${on ? '' : ' disabled'}${collapsed ? ' collapsed' : ''}">
          ${acctPositions.map(renderHoldingItem).join('')}
        </div>
      </div>`;
  }
  if (ungrouped.length) html += ungrouped.map(renderHoldingItem).join('');

  list.innerHTML = html;
}

function renderHoldingItem(p) {
  const pnlClass   = p.unrealized_pl >= 0 ? 'green' : 'red';
  const pnlSign    = p.unrealized_pl >= 0 ? '+' : '';
  const newsCount  = allArticles.filter(a => a.symbols.includes(p.symbol)).length;
  const isActive   = activeFilter === p.symbol ? ' active' : '';
  const newsLabel  = newsCount === 0 ? 'no news' : `${newsCount} article${newsCount === 1 ? '' : 's'}`;
  const stale      = p.price_source === 'file';
  const priceLabel = stale
    ? `<span class="holding-price stale" title="Live price unavailable — showing last known price">~$${p.current_price.toFixed(2)}</span>`
    : `<span class="holding-price">$${p.current_price.toFixed(2)}</span>`;
  return `
    <div class="holding-item${isActive}" onclick="setFilter('${escHtml(p.symbol)}')">
      <div class="holding-top">
        <span class="holding-sym">${escHtml(p.symbol)}</span>
        ${priceLabel}
      </div>
      <div class="holding-bottom">
        <span class="holding-qty dim">${p.qty.toFixed(0)} shares</span>
        <span class="holding-pnl ${pnlClass}">
          ${pnlSign}$${Math.abs(p.unrealized_pl).toFixed(2)}
          (${pnlSign}${p.unrealized_plpc.toFixed(2)}%)
        </span>
      </div>
      <div class="holding-news-count">${newsLabel}</div>
    </div>`;
}

// ─── News filter ─────────────────────────────────────────────
function renderFilterChips(positions) {
  const container = document.getElementById('filterChips');
  const syms = positions.map(p => p.symbol);

  const chips = ['ALL', ...syms].map(sym => {
    const active = sym === activeFilter ? ' active' : '';
    return `<button class="chip${active}" data-sym="${escHtml(sym)}" onclick="setFilter('${escHtml(sym)}')">${escHtml(sym)}</button>`;
  });
  container.innerHTML = chips.join('');
}

function setFilter(sym) {
  activeFilter = sym;
  document.querySelectorAll('.chip').forEach(c => {
    c.classList.toggle('active', c.dataset.sym === sym);
  });
  // Sync holding card active states
  document.querySelectorAll('.holding-item').forEach(el => {
    const s = el.querySelector('.holding-sym');
    el.classList.toggle('active', s && s.textContent === sym);
  });
  renderNews();
}

// ─── News feed ───────────────────────────────────────────────
function renderNews() {
  const list = document.getElementById('newsList');
  let filtered;
  if (activeFilter === 'ALL') {
    const enabledSyms = getEnabledSymbols();
    filtered = enabledSyms
      ? allArticles.filter(a => a.symbols.some(s => enabledSyms.includes(s)))
      : allArticles;
  } else {
    filtered = allArticles.filter(a => a.symbols.includes(activeFilter));
  }

  document.getElementById('newsCount').textContent = filtered.length;

  if (!filtered.length) {
    list.innerHTML = `<div class="news-empty">${allArticles.length ? 'No news for ' + escHtml(activeFilter) : 'No news available. Click REFRESH NEWS to fetch.'}</div>`;
    return;
  }

  list.innerHTML = filtered.map(a => {
    const sym     = a.symbols[0] || '';
    const timeAgo = fmtTimeAgo(a.published_at);
    const hasUrl  = a.url && a.url.startsWith('http');

    const headline = hasUrl
      ? `<a class="news-headline" href="${escHtml(a.url)}" target="_blank" rel="noopener">${escHtml(a.headline)}<span class="ext-icon">↗</span></a>`
      : `<span class="news-headline">${escHtml(a.headline)}</span>`;

    const source = hasUrl
      ? `<a class="news-source news-source-link" href="${escHtml(a.url)}" target="_blank" rel="noopener">${escHtml(a.source)}</a>`
      : `<span class="news-source dim">${escHtml(a.source)}</span>`;

    return `
      <div class="news-card">
        <div class="news-meta">
          <div class="news-meta-left">
            ${sym ? `<span class="sym-tag">${escHtml(sym)}</span>` : ''}
            ${source}
          </div>
          <span class="news-time dim">${timeAgo}</span>
        </div>
        ${headline}
        ${a.summary ? `<p class="news-summary">${escHtml(a.summary)}</p>` : ''}
      </div>`;
  }).join('');
}

function renderNewsTimestamp(iso) {
  const el = document.getElementById('newsUpdated');
  if (!el || !iso) return;
  lastNewsUpdateIso = iso;
  el.textContent = 'Updated ' + fmtTimeAgo(iso);
}

// ─── News refresh ────────────────────────────────────────────
async function refreshNews() {
  const btn = document.getElementById('refreshBtn');
  btn.disabled = true;
  btn.textContent = 'REFRESHING…';
  try {
    const res  = await fetch(`${API}/api/news/refresh`, { method: 'POST' });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Server error ${res.status}`);
    }
    const data = await res.json();
    allArticles = data.articles || [];
    renderNews();
    if (data.last_updated) renderNewsTimestamp(data.last_updated);
  } catch (e) {
    console.error('Refresh failed:', e);
    btn.textContent = 'REFRESH FAILED';
    setTimeout(() => { btn.textContent = 'REFRESH NEWS'; }, 3000);
  } finally {
    btn.disabled = false;
    if (btn.textContent === 'REFRESHING…') btn.textContent = 'REFRESH NEWS';
  }
}

// ─── Claude status ───────────────────────────────────────────
async function checkClaudeStatus() {
  try {
    const r = await fetch(`${API}/api/status`);
    const d = await r.json();
    setBrokerStatus(d.ai_available ? 'connected' : 'demo');
    const badge = document.getElementById('claudeBadge');
    badge.className = 'claude-badge ' + (d.ai_available ? 'online' : '');

    if (!d.ai_available) {
      const keys = d.ai_keys_in_env || [];
      if (keys.length > 0) {
        const names = { anthropic: 'Claude', openai: 'ChatGPT', google: 'Gemini' };
        const label = keys.map(k => names[k] || k).join(' / ');
        appendMsg('system', `${label} key found in .env but the provider failed to start — try restarting the server.`);
      } else {
        appendMsg('system', 'No AI key found in .env — open the .env file and add one of: ANTHROPIC_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY.');
      }
    }
  } catch (_) {}
}

// ─── Claude analysis ─────────────────────────────────────────
function triggerAnalysis() {
  const input = document.getElementById('promptInput');
  if (activeFilter === 'ALL') {
    input.value = 'Analyze the recent news for my holdings. Identify which articles are most likely driving price movements and explain the connections between news events and price changes.';
  } else {
    input.value = `Analyze the recent news for ${activeFilter}. What are the key headlines and how might they be driving price movement for this stock?`;
  }
  sendPrompt();
}

function handleKey(e) {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    sendPrompt();
  }
}

// Read a Server-Sent Events stream and call onChunk(text) for each chunk.
// Returns the full accumulated text.
async function readSSEStream(response, onChunk) {
  const reader  = response.body.getReader();
  const decoder = new TextDecoder();
  let   buf     = '';
  let   accumulated = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });

    // SSE lines end with \n; split on that and keep any incomplete line in buf
    // so we never try to parse a partial "data: ..." payload.
    const lines = buf.split('\n');
    buf = lines.pop();

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      let evt;
      try { evt = JSON.parse(line.slice(6)); } catch (_) { continue; }
      if (evt.type === 'chunk') {
        accumulated += evt.text;
        onChunk(accumulated);
      }
      if (evt.type === 'done') return accumulated;
    }
  }
  return accumulated;
}

async function sendPrompt() {
  if (streaming) return;
  const input = document.getElementById('promptInput');
  const prompt = input.value.trim();
  if (!prompt) return;

  input.value = '';
  streaming = true;
  document.getElementById('sendBtn').disabled = true;
  document.getElementById('analyzeBtn').disabled = true;
  document.getElementById('claudeBadge').className = 'claude-badge busy';

  appendMsg('user', prompt);
  const claudeEl = appendMsg('claude', '');
  const textEl   = claudeEl.querySelector('.msg-text');
  textEl.innerHTML = '<span class="cursor"></span>';

  let accumulated = '';

  try {
    const res = await fetch(`${API}/api/claude`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt }),
    });

    accumulated = await readSSEStream(res, text => updateClaudeMsg(textEl, text));
  } catch (e) {
    updateClaudeMsg(textEl, accumulated + `\n\n[Connection error: ${e.message}]`);
  } finally {
    streaming = false;
    document.getElementById('sendBtn').disabled = false;
    document.getElementById('analyzeBtn').disabled = false;
    document.getElementById('claudeBadge').className = 'claude-badge online';
    const cursor = textEl.querySelector('.cursor');
    if (cursor) cursor.remove();
    const msgs = document.getElementById('chatMessages');
    msgs.scrollTop = msgs.scrollHeight;
  }
}

function updateClaudeMsg(el, text) {
  el.innerHTML = DOMPurify.sanitize(marked.parse(text)) + '<span class="cursor"></span>';
  const msgs = document.getElementById('chatMessages');
  msgs.scrollTop = msgs.scrollHeight;
}

function appendMsg(type, text) {
  const msgs    = document.getElementById('chatMessages');
  const div     = document.createElement('div');
  div.className = `chat-msg ${type}`;
  const labels  = { user: 'YOU', claude: 'CLAUDE', system: 'SYSTEM' };
  div.innerHTML = `
    <span class="msg-sender">${labels[type] || type.toUpperCase()}</span>
    <span class="msg-text">${escHtml(text)}</span>`;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return div;
}

// ─── Settings modal ──────────────────────────────────────────
async function openSettings() {
  const status = document.getElementById('settingsStatus');
  status.textContent = 'Loading…';
  document.getElementById('settingsModal').classList.remove('hidden');
  try {
    const res = await fetch(`${API}/api/settings`);
    if (!res.ok) throw new Error(`${res.status}`);
    const data = await res.json();
    document.getElementById('settingsText').value = data.content || '';
    status.textContent = '';
  } catch (e) {
    status.textContent = `Failed to load: ${e.message}`;
  }
}

function closeSettings() {
  document.getElementById('settingsModal').classList.add('hidden');
}

async function saveSettings() {
  const btn    = document.getElementById('saveSettingsBtn');
  const status = document.getElementById('settingsStatus');
  btn.disabled = true;
  status.textContent = 'Saving & fetching live prices…';
  try {
    const content = document.getElementById('settingsText').value;
    const res = await fetch(`${API}/api/settings`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ content }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Server error ${res.status}`);
    }
    const data = await res.json();
    status.textContent = data.portfolio_built
      ? `Saved — ${data.positions} position(s), equity ${fmt$(data.equity)}`
      : (data.message || 'Saved.');
    setTimeout(closeSettings, 2000);
  } catch (e) {
    status.textContent = `Error: ${e.message}`;
    btn.disabled = false;
  }
}

// ─── Status badge ────────────────────────────────────────────
function setBrokerStatus(state, label) {
  const el = document.getElementById('brokerStatus');
  el.className = `status-badge ${state}`;
  const lbl = { connected: 'LIVE', demo: 'DEMO', disconnected: 'OFFLINE', connecting: 'CONNECTING' };
  el.querySelector('.label').textContent = label ? label.toUpperCase() : (lbl[state] || state.toUpperCase());
}

// ─── Formatting ──────────────────────────────────────────────
function fmt$(v) {
  return '$' + Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtSignPct(val, pct) {
  const sign = val >= 0 ? '+' : '';
  return `${sign}${fmt$(val)} (${sign}${Number(pct).toFixed(2)}%)`;
}

function fmtTimeAgo(iso) {
  if (!iso) return '';
  const ms   = Date.now() - new Date(iso).getTime();
  const secs = Math.floor(ms / 1000);
  if (secs < 60)   return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60)   return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)    return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}
