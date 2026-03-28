# VibeTrading

> *"You are not prepared."* — But your portfolio will be.

An automated trading terminal with a dark minimalist UI and a Claude AI assistant that reads your strategy, understands your positions, and modifies parameters on the fly — all from natural language.

![Dashboard](assets/dashboard.png)

---

## What it does

- **Live dashboard** — equity, cash, P&L, positions, and orders update in real time over WebSocket. No refresh needed. Just stare at the numbers going up (hopefully).
- **Strategy engine** — RSI + Moving Average Crossover with fully configurable parameters. Think of it as your passive income farm, but for stonks.
- **Claude assistant** — Type a message in plain English. Claude reads your current strategy, account state, and open positions, then applies changes live. It's like having a warlock in your raid who actually knows what they're doing.
- **Demo mode** — Runs without any API keys using realistic mock data. Safe to explore before you commit your gold.

![Chat panel](assets/chat.png)

---

## Requirements

- Python 3.11+
- An [Alpaca](https://alpaca.markets) account — paper trading is free and a good way to test before going all-in
- An [Anthropic](https://console.anthropic.com) API key for the Claude assistant

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/TheEmeraldDream/VibeTrading.git
cd VibeTrading
```

### 2. Configure your keys

Copy the env template and fill it in:

```bash
cp .env.example .env
```

```env
ANTHROPIC_API_KEY=sk-ant-...        # Powers the Claude assistant
ALPACA_API_KEY=PKxxxxxxxxxxxxxxxx    # From your Alpaca dashboard
ALPACA_SECRET_KEY=xxxxxxxxxxxxxxxx  # Keep this one close to your chest
ALPACA_PAPER=true                   # true = paper trading. Recommended before you YOLO.
```

> **No keys?** The app boots in **demo mode** automatically — mock data, no real orders. Good for getting a feel before you pull aggro on your own account.

### 3. Launch

**Windows** — double-click `run.bat`, or from a terminal:

```
run.bat
```

**Mac / Linux:**

```bash
chmod +x run.sh && ./run.sh
```

The script handles everything: virtual environment creation, dependency installation, and opening your browser. Your only job is to show up.

---

## Running the app manually

If you prefer to drive stick:

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate      # Mac/Linux
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Then open `http://localhost:8000/app`.

---

## Using the dashboard

![Positions table](assets/positions.png)

### Account panel (left)
Shows your equity, cash, buying power, and daily P&L. The numbers glow green or red depending on how the market is treating you today. Silence your inner goblin — focus on the long game.

### Positions & Orders (center)
Live table of your open positions with unrealized P&L and percentage. Recent orders below. If everything is red, consider logging off and doing a dungeon run instead.

### Strategy toggle
The **STRATEGY: ON / OFF** button in the header enables or disables the trading engine. When on, the scanner wakes up every 60 seconds (configurable), checks your symbols, and places orders based on the strategy config.

> First time enabling it? Think of it as your opening /ready check.

---

## Talking to Claude

![Claude assistant](assets/claude-chat.png)

The chat panel on the right is where the magic happens. Type anything in plain English:

- `"Tighten my stop losses to 1.5%"`
- `"Add TSLA to the watchlist"`
- `"My win rate is terrible, what's wrong?"`
- `"Make the strategy more conservative, I'm taking too much damage"`
- `"What's my current position sizing?"`

Claude reads your live context — current config, account balance, open positions, and performance metrics — before every response. If it decides changes are needed, it applies them automatically and shows a **STRATEGY UPDATED** confirmation in the chat.

---

## Strategy config

The default strategy is defined in `backend/strategy.py` and can be modified at runtime through Claude or the REST API.

| Parameter | Default | Description |
|---|---|---|
| `symbols` | AAPL, MSFT, NVDA, AMD, GOOGL | Your farming route |
| `rsi_period` | 14 | RSI lookback period |
| `rsi_oversold` | 35 | RSI threshold to trigger a buy signal |
| `ma_fast` / `ma_slow` | 10 / 20 | Moving average crossover periods |
| `stop_loss_pct` | 2.0% | Where you admit the trade isn't going your way |
| `take_profit_pct` | 5.0% | Where you collect your loot |
| `max_positions` | 5 | Maximum simultaneous positions |
| `position_size_pct` | 10.0% | % of equity per trade |
| `scan_interval_seconds` | 60 | How often the engine sweeps your symbols |

---

## Project structure

```
VibeTrading/
├── .env.example          # Key template — never commit the real .env
├── run.bat               # Windows launcher
├── run.sh                # Mac/Linux launcher
├── backend/
│   ├── main.py           # FastAPI app — REST, WebSocket, SSE
│   ├── broker.py         # Alpaca connector with demo fallback
│   ├── strategy.py       # RSI + MA crossover engine
│   ├── claude_client.py  # Claude API streaming integration
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
└── assets/               # Screenshots for this README
```

---

## Security

- `.env` is in `.gitignore` — your API keys stay local
- The app binds to `localhost:8000` only — not exposed to your network
- Paper trading mode is the default — no real money moves until you explicitly switch

---

*For the Horde. And for passive income.*
