/* ─────────────────────────────────────────────────────────────
   Trading App — Frontend
   • WebSocket  : live dashboard updates every scan interval
   • SSE        : streaming Claude responses
   • REST       : one-shot commands (toggle, prompt)
───────────────────────────────────────────────────────────── */

const API   = 'http://localhost:8000';
const WS    = 'ws://localhost:8000/ws';

let ws          = null;
let streaming   = false;
let retryTimer  = null;
let equityChart = null;
const equityHistory = { labels: [], values: [] };
const MAX_POINTS = 60;

// ─── Init ────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initChart();
  connectWS();
  checkClaudeStatus();
});

// ─── Equity chart ────────────────────────────────────────────
function initChart() {
  const ctx = document.getElementById('equityChart').getContext('2d');

  const gradient = ctx.createLinearGradient(0, 0, 0, 160);
  gradient.addColorStop(0, 'rgba(0, 217, 126, 0.18)');
  gradient.addColorStop(1, 'rgba(0, 217, 126, 0)');

  equityChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: equityHistory.labels,
      datasets: [{
        data: equityHistory.values,
        borderColor: '#00d97e',
        borderWidth: 1.5,
        backgroundColor: gradient,
        pointRadius: 0,
        pointHoverRadius: 3,
        pointHoverBackgroundColor: '#00d97e',
        tension: 0.35,
        fill: true,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#181818',
          borderColor: '#252525',
          borderWidth: 1,
          titleColor: '#444',
          bodyColor: '#d8d8d8',
          titleFont: { family: "'JetBrains Mono', monospace", size: 9 },
          bodyFont: { family: "'JetBrains Mono', monospace", size: 11 },
          callbacks: {
            title: (items) => items[0].label,
            label: (item) => ' $' + Number(item.raw).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
          },
        },
      },
      scales: {
        x: {
          display: false,
        },
        y: {
          position: 'right',
          grid: { color: '#1a1a1a', drawBorder: false },
          border: { display: false },
          ticks: {
            color: '#444',
            font: { family: "'JetBrains Mono', monospace", size: 9 },
            maxTicksLimit: 4,
            callback: (v) => '$' + Number(v).toLocaleString('en-US', { notation: 'compact' }),
          },
        },
      },
    },
  });
}

function updateChart(equity) {
  if (!equityChart || equity == null) return;
  const now = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  equityHistory.labels.push(now);
  equityHistory.values.push(Number(equity));
  if (equityHistory.labels.length > MAX_POINTS) {
    equityHistory.labels.shift();
    equityHistory.values.shift();
  }
  // Recolor line red if trending down over last 5 points
  const vals = equityHistory.values;
  const trending = vals.length >= 2 ? vals[vals.length - 1] - vals[0] : 0;
  equityChart.data.datasets[0].borderColor = trending >= 0 ? '#00d97e' : '#ff4757';
  equityChart.update('none');
}

// ─── WebSocket ───────────────────────────────────────────────
function connectWS() {
  setStatus('connecting');
  ws = new WebSocket(WS);

  ws.onopen = () => {
    setStatus('connected');
    clearTimeout(retryTimer);
  };

  ws.onmessage = (evt) => {
    try {
      const data = JSON.parse(evt.data);
      if (data.type === 'snapshot') applySnapshot(data);
    } catch (_) {}
  };

  ws.onclose = () => {
    setStatus('disconnected');
    retryTimer = setTimeout(connectWS, 3000);
  };

  ws.onerror = () => {
    ws.close();
  };
}

function applySnapshot(data) {
  if (data.account)   renderAccount(data.account);
  if (data.positions) renderPositions(data.positions);
  if (data.orders)    renderOrders(data.orders);
  if (data.metrics)   renderMetrics(data.metrics);
  if (data.strategy)  renderStrategyParams(data.strategy);
  if (data.account)   updateToggleButton(data.strategy?.enabled ?? false);
}

// ─── Status indicator ────────────────────────────────────────
function setStatus(state) {
  const badge = document.getElementById('brokerStatus');
  const modes = { connecting: '', connected: 'connected', disconnected: 'disconnected', demo: 'demo' };
  badge.className = 'status-badge ' + (modes[state] || '');

  const labels = {
    connecting:   'CONNECTING…',
    connected:    'LIVE',
    disconnected: 'OFFLINE',
    demo:         'DEMO',
  };
  badge.querySelector('.label').textContent = labels[state] || state.toUpperCase();
}

async function checkClaudeStatus() {
  try {
    const res = await fetch(`${API}/api/status`);
    const s   = await res.json();
    const el  = document.getElementById('claudeBadge');
    el.classList.toggle('online', s.claude_available);
    el.textContent = s.claude_available ? '● ONLINE' : '● OFFLINE';

    // Apply broker mode to status
    if (s.broker_connected) {
      setStatus('connected');
    } else {
      setStatus('demo');
      document.getElementById('brokerStatus').classList.add('demo');
    }
  } catch (_) {}
}

// ─── Account ─────────────────────────────────────────────────
function renderAccount(a) {
  updateChart(a.equity);
  setText('equity',      fmt$(a.equity));
  setText('cash',        fmt$(a.cash));
  setText('buyingPower', fmt$(a.buying_power));

  const pnlEl = document.getElementById('dailyPnl');
  pnlEl.textContent = fmtPnl(a.daily_pnl, a.daily_pnl_pct);
  pnlEl.className = 'metric-value ' + (a.daily_pnl >= 0 ? 'green' : 'red');

  // Show mode on status badge if demo
  if (a.mode === 'demo') setStatus('demo');
}

// ─── Metrics ─────────────────────────────────────────────────
function renderMetrics(m) {
  const wr = m.win_rate_pct ?? 0;
  const wrEl = document.getElementById('winRate');
  wrEl.textContent = wr.toFixed(1) + '%';
  wrEl.className = 'metric-value ' + (wr >= 50 ? 'green' : wr >= 40 ? 'yellow' : 'red');

  setText('totalTrades', m.total_closed_trades ?? 0);
  setText('wins',        m.wins  ?? 0);
  setText('losses',      m.losses ?? 0);
}

// ─── Strategy params ─────────────────────────────────────────
function renderStrategyParams(s) {
  if (!s) return;
  const el = document.getElementById('strategyParams');
  const rows = [
    ['Strategy', s.name],
    ['Symbols',  (s.symbols || []).join(', ')],
    ['RSI buy',  `< ${s.entry_conditions?.rsi_oversold ?? '—'}`],
    ['MA',       `${s.entry_conditions?.ma_fast ?? '—'} / ${s.entry_conditions?.ma_slow ?? '—'}`],
    ['Stop',     `${s.exit_conditions?.stop_loss_pct ?? '—'}%`],
    ['Target',   `${s.exit_conditions?.take_profit_pct ?? '—'}%`],
    ['Max pos',  s.max_positions ?? '—'],
    ['Size',     `${s.position_size_pct ?? '—'}%`],
  ];
  el.innerHTML = rows.map(([k, v]) =>
    `<div><span class="param-key">${k}:</span> <span class="param-val">${v}</span></div>`
  ).join('');
}

// ─── Positions table ─────────────────────────────────────────
function renderPositions(positions) {
  document.getElementById('posCount').textContent = positions.length;
  const tbody = document.querySelector('#positionsTable tbody');
  if (positions.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="dim" style="text-align:center;padding:12px">No open positions</td></tr>';
    return;
  }
  tbody.innerHTML = positions.map(p => {
    const pnlClass = p.unrealized_pl >= 0 ? 'pos' : 'neg';
    return `<tr>
      <td class="sym">${p.symbol}</td>
      <td>${fmt(p.qty)}</td>
      <td>${fmt$(p.avg_entry_price)}</td>
      <td>${fmt$(p.current_price)}</td>
      <td class="${pnlClass}">${fmtSign$(p.unrealized_pl)}</td>
      <td class="${pnlClass}">${fmtSignPct(p.unrealized_plpc)}</td>
    </tr>`;
  }).join('');
}

// ─── Orders table ─────────────────────────────────────────────
function renderOrders(orders) {
  const tbody = document.querySelector('#ordersTable tbody');
  if (orders.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="dim" style="text-align:center;padding:12px">No orders</td></tr>';
    return;
  }
  tbody.innerHTML = orders.map(o => {
    const sideClass = o.side === 'buy' ? 'buy' : 'sell';
    const statusClass = {
      filled: 'status-filled',
      canceled: 'status-canceled',
      cancelled: 'status-canceled',
    }[o.status] || 'status-pending';

    const price = o.filled_avg_price > 0 ? fmt$(o.filled_avg_price) : '—';
    return `<tr>
      <td class="sym">${o.symbol}</td>
      <td class="${sideClass}">${o.side.toUpperCase()}</td>
      <td>${fmt(o.qty)}</td>
      <td>${price}</td>
      <td class="${statusClass}">${o.status.toUpperCase()}</td>
    </tr>`;
  }).join('');
}

// ─── Strategy toggle ─────────────────────────────────────────
function updateToggleButton(enabled) {
  const btn = document.getElementById('strategyToggle');
  btn.textContent = `STRATEGY: ${enabled ? 'ON' : 'OFF'}`;
  btn.className = 'btn-toggle' + (enabled ? ' active' : '');
}

async function toggleStrategy() {
  try {
    const res = await fetch(`${API}/api/strategy/toggle`, { method: 'POST' });
    const data = await res.json();
    updateToggleButton(data.enabled);
    appendSystemMsg(`Strategy ${data.enabled ? 'enabled' : 'disabled'}.`);
  } catch (e) {
    appendSystemMsg('Failed to toggle strategy: ' + e.message);
  }
}

// ─── Claude chat ─────────────────────────────────────────────
function handleKey(evt) {
  if (evt.key === 'Enter' && !evt.shiftKey) {
    evt.preventDefault();
    sendPrompt();
  }
}

async function sendPrompt() {
  if (streaming) return;

  const input = document.getElementById('promptInput');
  const prompt = input.value.trim();
  if (!prompt) return;

  input.value = '';
  appendUserMsg(prompt);

  // Disable input while streaming
  streaming = true;
  document.getElementById('sendBtn').disabled = true;
  document.getElementById('claudeBadge').className = 'claude-badge busy';

  // Create Claude message bubble (will stream into it)
  const msgEl = createClaudeMsg();

  try {
    const res = await fetch(`${API}/api/claude`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt }),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let fullText = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop(); // keep incomplete line

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const evt = JSON.parse(line.slice(6));
          if (evt.type === 'chunk') {
            fullText += evt.text;
            updateClaudeMsg(msgEl, fullText, true);
          } else if (evt.type === 'updates' && evt.strategy_updates) {
            appendUpdateMsg(evt.strategy_updates);
          } else if (evt.type === 'done') {
            updateClaudeMsg(msgEl, fullText, false);
          }
        } catch (_) {}
      }
    }

    // Finalize without cursor
    updateClaudeMsg(msgEl, fullText, false);

  } catch (e) {
    updateClaudeMsg(msgEl, `Error: ${e.message}`, false);
  } finally {
    streaming = false;
    document.getElementById('sendBtn').disabled = false;
    document.getElementById('claudeBadge').className = 'claude-badge online';
    // Refresh snapshot after strategy may have changed
    fetchSnapshot();
  }
}

// ─── Chat helpers ─────────────────────────────────────────────
function appendUserMsg(text) {
  const chat = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = 'chat-msg user';
  div.innerHTML = `<span class="msg-sender">YOU</span><span class="msg-text">${escHtml(text)}</span>`;
  chat.appendChild(div);
  scrollChat();
}

function createClaudeMsg() {
  const chat = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = 'chat-msg claude';
  const textEl = document.createElement('span');
  textEl.className = 'msg-text';
  textEl.innerHTML = '<span class="cursor"></span>';
  div.innerHTML = '<span class="msg-sender">CLAUDE</span>';
  div.appendChild(textEl);
  chat.appendChild(div);
  scrollChat();
  return textEl;
}

function updateClaudeMsg(el, text, streaming) {
  // Render markdown; add cursor if still streaming
  const rendered = typeof marked !== 'undefined'
    ? marked.parse(text)
    : escHtml(text).replace(/\n/g, '<br>');
  el.innerHTML = rendered + (streaming ? '<span class="cursor"></span>' : '');
  scrollChat();
}

function appendSystemMsg(text) {
  const chat = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = 'chat-msg system';
  div.innerHTML = `<span class="msg-sender">SYSTEM</span><span class="msg-text">${escHtml(text)}</span>`;
  chat.appendChild(div);
  scrollChat();
}

function appendUpdateMsg(updates) {
  const chat = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = 'chat-msg update';
  const keys = Object.keys(updates).join(', ');
  div.innerHTML = `<span class="msg-sender">STRATEGY UPDATED</span>
    <span class="msg-text">Applied changes: ${escHtml(keys)}</span>`;
  chat.appendChild(div);
  scrollChat();
}

function scrollChat() {
  const chat = document.getElementById('chatMessages');
  chat.scrollTop = chat.scrollHeight;
}

// ─── Snapshot fetch ───────────────────────────────────────────
async function fetchSnapshot() {
  try {
    const res  = await fetch(`${API}/api/snapshot`);
    const data = await res.json();
    applySnapshot(data);
  } catch (_) {}
}

// ─── Formatters ───────────────────────────────────────────────
const fmtNum = (n) => (n == null ? '—' : Number(n));
const fmt  = (n) => fmtNum(n).toLocaleString();
const fmt$ = (n) => n == null ? '—' : '$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtSign$ = (n) => n == null ? '—' : (n >= 0 ? '+$' : '-$') + Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtSignPct = (n) => n == null ? '—' : (n >= 0 ? '+' : '') + Number(n).toFixed(2) + '%';
const fmtPnl = (val, pct) => {
  const sign = val >= 0 ? '+' : '';
  return `${sign}${fmt$(val)} (${sign}${Number(pct).toFixed(2)}%)`;
};

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
