# Auction House v2.5 — Project Context

A personal news aggregator dashboard. Pulls financial news for stock holdings and uses AI to explain what's driving prices. No trading, no brokerage connections — read-only news + analysis.

---

## Stack

| Layer | Tech |
|---|---|
| Backend | FastAPI + Python 3.11+, port 8000 |
| Frontend | Static HTML/CSS/JS at `/app` |
| News | yfinance (real Yahoo Finance data, no key needed) |
| AI | Anthropic Claude / OpenAI GPT / Google Gemini (one key required) |
| Real-time | WebSocket (`/ws`) for live snapshots, SSE for AI streaming |

---

## File Structure

```
trading-app/
├── backend/
│   ├── main.py          # FastAPI app, routes, WebSocket, SSE endpoint
│   ├── portfolio.py     # PortfolioReader — loads local/portfolio.json or mock data
│   ├── news.py          # NewsAggregator — yfinance or mock fallback
│   ├── claude_client.py # AIClient — Anthropic / OpenAI / Google, auto-detected
│   └── requirements.txt
├── frontend/
│   ├── index.html       # Three-panel layout: Holdings | News | AI Chat
│   ├── app.js           # WebSocket client, SSE consumer, rendering
│   └── style.css        # Dark terminal theme, JetBrains Mono
├── .env                 # API keys (not committed) — copy from .env.example
├── .env.example         # Template
├── run.bat              # Windows launcher (double-click or terminal)
└── run.sh               # Mac/Linux launcher
```

---

## Key Design Decisions

- **No brokerage API** — portfolio data comes from `local/portfolio.json` (user-created, gitignored) or hardcoded mock data. The app cannot place trades.
- **AI provider auto-detection** — `AIClient` checks env keys in order: Anthropic → OpenAI → Google. Set `AI_PROVIDER=anthropic|openai|google` to force one.
- **Default AI model** — `claude-opus-4-6` with `thinking: {"type": "adaptive"}` and streaming.
- **XSS prevention** — `marked.use()` escapes raw HTML tokens before rendering AI responses as markdown.
- **Prompt size limit** — `/api/claude` rejects prompts over 4000 characters before any AI call.
- **News refresh** — background task fetches news every 5 minutes via yfinance; also manually triggerable via `POST /api/news/refresh`.

---

## Running Locally

**Windows:** double-click `run.bat` or run it from terminal
**Mac/Linux:** `chmod +x run.sh && ./run.sh`

App opens at `http://localhost:8000/app`.

---

## Adding Real Holdings

Create `local/portfolio.json` (gitignored):

```json
{
  "account": {
    "equity": 50000.00,
    "cash": 5000.00,
    "buying_power": 5000.00,
    "daily_pnl": 250.00,
    "daily_pnl_pct": 0.50
  },
  "positions": [
    {
      "symbol": "AAPL",
      "qty": 10,
      "avg_entry_price": 170.00,
      "current_price": 182.00,
      "unrealized_pl": 120.00,
      "unrealized_plpc": 7.06
    }
  ]
}
```

---

## AI Keys

Edit `trading-app/.env` (not `.env.example`):

```
ANTHROPIC_API_KEY=your-key-here
# or
OPENAI_API_KEY=your-key-here
# or
GOOGLE_API_KEY=your-key-here
```

Only one key needed.

---

## GitHub

- Remote: `https://github.com/TheEmeraldDream/VibeTradingNews.git`
- Default branch: `main`
- Git identity: `TheEmeraldDream`
