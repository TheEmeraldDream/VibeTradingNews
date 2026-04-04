# Auction House v2.5

A personal dashboard that pulls the latest financial news for your stock holdings and uses AI to explain what's moving your portfolio — all in one place.

---

## What it does

- **See your portfolio at a glance** — your total value, cash, and today's gains or losses update automatically.
- **News, filtered to what you own** — only shows articles relevant to your holdings. Click any stock to narrow the feed to that symbol.
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
Your portfolio summary is at the top. Below it, each stock you own shows its current price, your gain or loss, and how many news articles are linked to it. Click a stock to filter the news feed.

**Center — News**
Recent articles for everything you hold, newest first. Use the buttons at the top to filter by symbol, or click **ALL** to see everything. Headlines link directly to the original source. News updates automatically every 5 minutes, or click **REFRESH NEWS** to pull it immediately.

**Right — AI Analyst**
Click **ANALYZE NEWS IMPACT** for an automatic read on how recent news may be affecting your holdings. You can also type your own questions, for example:

- *"Why is NVDA down today?"*
- *"What's the biggest risk in my portfolio right now?"*
- *"Give me a summary of AAPL news this week."*

---

## Adding your real holdings

By default the app shows sample data. To use your actual portfolio, create a file at `local/portfolio.json` — this file stays on your computer and is never uploaded to GitHub.

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
    },
    {
      "symbol": "MSFT",
      "qty": 5,
      "avg_entry_price": 380.00,
      "current_price": 395.00,
      "unrealized_pl": 75.00,
      "unrealized_plpc": 3.95
    }
  ]
}
```

Fill in your own symbols, quantities, and prices. The app picks this up automatically on next launch.

---

## Privacy & security

- Your AI key and portfolio file are stored only on your machine — they are never uploaded or shared.
- The app only reads news and displays data. It cannot place trades or connect to a brokerage.
