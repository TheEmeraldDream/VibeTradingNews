/* ─────────────────────────────────────────────────────────────
   News Aggregator — Frontend
   • WebSocket  : live snapshots (news + positions)
   • SSE        : streaming Claude analysis
   • REST       : news refresh
───────────────────────────────────────────────────────────── */

const API = 'http://localhost:8000';
const WS  = 'ws://localhost:8000/ws';

let ws          = null;
let streaming   = false;
let retryTimer  = null;
let activeFilter = 'ALL';
let allArticles  = [];

// ─── Init ────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initResizeHandles();
  connectWS();
  checkClaudeStatus();
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

// ─── WebSocket ───────────────────────────────────────────────
function connectWS() {
  if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
  ws = new WebSocket(WS);

  ws.onopen = () => {
    setBrokerStatus('connecting');
  };

  ws.onmessage = e => {
    const data = JSON.parse(e.data);
    if (data.type === 'snapshot') applySnapshot(data);
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
    setBrokerStatus(data.account.mode === 'demo' ? 'demo' : 'connected', data.account.mode);
  }
  if (data.positions !== undefined) renderHoldings(data.positions);
  if (data.news !== undefined) {
    allArticles = data.news;
    renderFilterChips(data.positions || []);
    renderNews();
  }
  if (data.news_updated) renderNewsTimestamp(data.news_updated);
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

// ─── Holdings ────────────────────────────────────────────────
function renderHoldings(positions) {
  const list = document.getElementById('holdingsList');
  document.getElementById('holdingsCount').textContent = positions.length;

  if (!positions.length) {
    list.innerHTML = '<div class="holdings-empty">No open positions</div>';
    return;
  }

  list.innerHTML = positions.map(p => {
    const pnlClass   = p.unrealized_pl >= 0 ? 'green' : 'red';
    const pnlSign    = p.unrealized_pl >= 0 ? '+' : '';
    const newsCount  = allArticles.filter(a => a.symbols.includes(p.symbol)).length;
    const isActive   = activeFilter === p.symbol ? ' active' : '';
    const newsLabel  = newsCount === 0 ? 'no news' : `${newsCount} article${newsCount === 1 ? '' : 's'}`;
    return `
      <div class="holding-item${isActive}" onclick="setFilter('${escHtml(p.symbol)}')">
        <div class="holding-top">
          <span class="holding-sym">${escHtml(p.symbol)}</span>
          <span class="holding-price">$${p.current_price.toFixed(2)}</span>
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
  }).join('');
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
  const filtered = activeFilter === 'ALL'
    ? allArticles
    : allArticles.filter(a => a.symbols.includes(activeFilter));

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
  const d = new Date(iso + 'Z');
  el.textContent = 'Updated ' + fmtTimeAgo(d.toISOString());
}

// ─── News refresh ────────────────────────────────────────────
async function refreshNews() {
  const btn = document.getElementById('refreshBtn');
  btn.disabled = true;
  btn.textContent = 'REFRESHING…';
  try {
    const res  = await fetch(`${API}/api/news/refresh`, { method: 'POST' });
    const data = await res.json();
    allArticles = data.articles || [];
    renderNews();
    if (data.last_updated) renderNewsTimestamp(data.last_updated);
  } catch (e) {
    console.error('Refresh failed:', e);
  } finally {
    btn.disabled = false;
    btn.textContent = 'REFRESH NEWS';
  }
}

// ─── Claude status ───────────────────────────────────────────
async function checkClaudeStatus() {
  try {
    const r = await fetch(`${API}/api/status`);
    const d = await r.json();
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
  input.value = 'Analyze the recent news for my holdings. Identify which articles are most likely driving price movements and explain the connections between news events and price changes.';
  sendPrompt();
}

function handleKey(e) {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    sendPrompt();
  }
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

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let   buf     = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const evt = JSON.parse(line.slice(6));
        if (evt.type === 'chunk') {
          accumulated += evt.text;
          updateClaudeMsg(textEl, accumulated);
        }
        if (evt.type === 'done') break;
      }
    }
  } catch (e) {
    updateClaudeMsg(textEl, accumulated + `\n\n[Connection error: ${e.message}]`);
  } finally {
    streaming = false;
    document.getElementById('sendBtn').disabled = false;
    document.getElementById('analyzeBtn').disabled = false;
    document.getElementById('claudeBadge').className = 'claude-badge online';
    // Remove cursor
    const cursor = textEl.querySelector('.cursor');
    if (cursor) cursor.remove();
    // Scroll to bottom
    const msgs = document.getElementById('chatMessages');
    msgs.scrollTop = msgs.scrollHeight;
  }
}

function updateClaudeMsg(el, text) {
  el.innerHTML = marked.parse(text) + '<span class="cursor"></span>';
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
  const mins = Math.floor(ms / 60000);
  if (mins < 60)  return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)   return `${hrs}h ago`;
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
