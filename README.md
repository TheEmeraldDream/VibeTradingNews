# Auction House v2.5

A personal dashboard that pulls the latest financial news for your stock holdings and uses AI to explain what's moving your portfolio — all in one place.

---

## What it does

- **See your portfolio at a glance** — your total value, cash, and today's gains or losses update automatically.
- **News, filtered to what you own** — only shows articles relevant to your holdings. Click any stock to narrow the feed to that symbol.
- **Portfolio value chart** — candlestick chart of your total holdings market value over time. Choose from 1D, 5D, 1M, 3M, 6M, 1Y, or a custom date range.
- **Multiple accounts** — group holdings by brokerage account (e.g. taxable brokerage, 401k). Toggle each account on or off to control what appears in the news feed and chart.
- **AI analysis** — hit **ANALYZE** and the AI reads your holdings alongside the latest news to explain what's likely driving your prices. You can also ask questions in plain English.
- **Works without any accounts** — if you don't set up an AI key, the app runs in demo mode with sample data so you can still explore it.

---

## Getting started

### What you need

- **Python 3.11 or newer** — [download here](https://www.python.org/downloads/) if you don't have it.
- **An AI key** *(optional but recommended)* — the app supports Claude, ChatGPT, and Gemini. You only need one.

| AI | Where to get a key |
|---|---|
| Claude (Anthropic) | [console.anthropic.com](https://console.anthropic.com) |
| ChatGPT (OpenAI) | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| Gemini (Google) | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) |

---

### 1. Download the app

```bash
git clone https://github.com/TheEmeraldDream/VibeTradingNews.git
cd VibeTradingNews
```

### 2. Add your AI key

Open the `.env` file in any text editor and paste your key — you only need to fill in one:

```
ANTHROPIC_API_KEY=your-key-here
OPENAI_API_KEY=your-key-here
GOOGLE_API_KEY=your-key-here
```

> **Note:** Edit `.env`, not `.env.example`. The example file is a template and is not read by the app.

### 3. Launch

**Windows** — double-click `run.bat`, or run it from the terminal:
```
run.bat
```

**Mac / Linux:**
```bash
chmod +x run.sh && ./run.sh
```

The app will open automatically in your browser at `http://localhost:8000/app`.

---

## Using the dashboard

**Left — Holdings**
Your portfolio summary is at the top. Below it, holdings are grouped by account. Each stock shows its current price, your gain or loss, and how many news articles are linked to it.

- **Click a stock** to filter the news feed to that symbol.
- **Click an account name** (or the ▶ arrow) to collapse or expand that account group.
- **Click the ON / OFF badge** on an account to include or exclude it from the news feed and portfolio chart. This lets you, for example, view only your taxable brokerage holdings without your 401(k) cluttering the feed.

Prices fetched live from Yahoo Finance are shown normally. If live data is unavailable for a ticker (common with certain mutual fund share classes), the price is shown in grey italic with a `~` prefix indicating it is the last known value.

**Center — Portfolio chart + News**
The candlestick chart shows the total market value of your holdings over time. Use the period buttons (1D, 5D, 1M, 3M, 6M, 1Y) or **CUSTOM** to pick a date range. The chart automatically reflects which accounts are toggled on.

Below the chart, recent news articles for your enabled holdings appear newest first. Use the symbol buttons to filter by ticker, or click **ALL** to see everything. Headlines link directly to the original source. News updates automatically every 5 minutes, or click **REFRESH NEWS** to pull it immediately.

**Right — AI Analyst**
Click **ANALYZE NEWS IMPACT** for an automatic read on how recent news may be affecting your holdings. You can also type your own questions, for example:

- *"Why is NVDA down today?"*
- *"What's the biggest risk in my portfolio right now?"*
- *"Give me a summary of AAPL news this week."*

---

## Adding your real holdings

By default the app shows sample data. To use your actual portfolio, create a file at `local/portfolio.json` — this file stays on your computer and is never uploaded to GitHub.

### Single account (simple setup)

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
      "current_price": 182.00
    },
    {
      "symbol": "MSFT",
      "qty": 5,
      "avg_entry_price": 380.00,
      "current_price": 395.00
    }
  ]
}
```

### Multiple accounts

To group holdings by account and use the ON/OFF toggles, add an `"accounts"` array and an `"account"` field on each position:

```json
{
  "accounts": [
    { "id": "brokerage", "name": "Brokerage" },
    { "id": "401k",      "name": "My 401(k)" }
  ],
  "account": {
    "equity": 150000.00,
    "cash": 5000.00,
    "buying_power": 5000.00,
    "daily_pnl": 400.00,
    "daily_pnl_pct": 0.27
  },
  "positions": [
    {
      "symbol": "AAPL",
      "account": "brokerage",
      "qty": 10,
      "avg_entry_price": 170.00,
      "current_price": 182.00
    },
    {
      "symbol": "VTSNX",
      "account": "401k",
      "qty": 250,
      "avg_entry_price": 41.00,
      "current_price": 43.00
    }
  ]
}
```

Each position's `"account"` value must match an `"id"` in the `"accounts"` array. Positions with no `"account"` field are shown ungrouped. The `"equity"` in `"account"` should reflect the combined total across all accounts.

You can add as many accounts as you like. The ON/OFF toggle state for each account is remembered between browser sessions.

### Account fields

| Field | Description |
|---|---|
| `equity` | Total portfolio value across all accounts — cash plus the current market value of all positions |
| `cash` | Uninvested cash sitting in the account |
| `buying_power` | How much you can currently spend (often 2× cash for a margin account, or equal to cash for a standard account) |
| `daily_pnl` | Today's dollar gain or loss across the whole account |
| `daily_pnl_pct` | Today's gain or loss as a percentage of yesterday's closing equity |

### Position fields

| Field | Description |
|---|---|
| `symbol` | Stock ticker, e.g. `"AAPL"`. Mutual fund tickers (e.g. `"VTSNX"`) also work if Yahoo Finance carries them — the price will be shown as stale (`~`) if live data is unavailable |
| `account` | *(optional)* The `id` of the account this position belongs to, e.g. `"brokerage"` or `"401k"` |
| `qty` | Number of shares (or fund units) you hold |
| `avg_entry_price` | Your average cost per share — used to calculate unrealized P&L |
| `current_price` | Last known price per share. Only used as a fallback on first load — once the app starts, it fetches live prices from Yahoo Finance automatically |

Fill in your own values and save the file. The app picks it up on next launch and refreshes live prices from Yahoo Finance every five minutes.

---

## Privacy & security

- Your AI key and portfolio file are stored only on your machine — they are never uploaded or shared.
- The app only reads news and displays data. It cannot place trades or connect to a brokerage.
