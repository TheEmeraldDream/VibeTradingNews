# VibeTrading

Automated trading app with a dark minimalist GUI and a Claude AI strategy assistant.

- **Live dashboard** — account metrics, open positions, recent orders via WebSocket
- **Strategy engine** — RSI + Moving Average Crossover, fully configurable via JSON
- **Claude assistant** — chat to modify your strategy in real-time; changes apply instantly
- **Demo mode** — runs without any API keys using mock data

---

## Requirements

- Python 3.11+
- An [Alpaca](https://alpaca.markets) account (paper trading is free)
- An [Anthropic](https://console.anthropic.com) API key (for Claude assistant)

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/TheEmeraldDream/VibeTrading.git
cd VibeTrading
```

### 2. Create a virtual environment

```bash
cd backend
python -m venv venv
```

Activate it:

- **Windows:** `venv\Scripts\activate`
- **Mac/Linux:** `source venv/bin/activate`

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy the example file to `.env` at the project root:

```bash
# From the VibeTrading root directory
cp .env.example .env
```

Open `.env` and fill in your keys:

```env
ANTHROPIC_API_KEY=sk-ant-...        # Required for Claude assistant
ALPACA_API_KEY=PKxxxxxxxxxxxxxxxx    # From alpaca.markets dashboard
ALPACA_SECRET_KEY=xxxxxxxxxxxxxxxx  # From alpaca.markets dashboard
ALPACA_PAPER=true                   # true = paper trading, false = live
```

> **No API keys?** The app runs in **demo mode** automatically — all data is mocked and no real orders are placed.

---

## Running the App

Start the backend from the `backend/` directory:

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Then open your browser:

```
http://localhost:8000/app
```

The backend serves the frontend automatically — no separate web server needed.

---

## Usage

### Dashboard

The left panel shows account equity, cash, buying power, daily P&L, and performance metrics. The center panel shows open positions and recent orders. Both update live via WebSocket.

### Strategy Toggle

Click **STRATEGY: OFF / ON** in the header to enable or disable the trading engine. When enabled, the scanner runs every 60 seconds (configurable) and places orders based on the current strategy config.

### Claude Assistant

Type a prompt in the chat panel on the right and press **Enter** or **SEND**. Examples:

- `"Tighten my stop losses to 1.5%"`
- `"Add TSLA and AMZN to the watchlist"`
- `"Why is my win rate low?"`
- `"Switch to a more conservative position size"`

Claude reads your current strategy config, account state, and positions before responding. If strategy changes are warranted, it applies them automatically and shows a **STRATEGY UPDATED** confirmation.

---

## Project Structure

```
VibeTrading/
├── .env.example          # Environment variable template
├── backend/
│   ├── main.py           # FastAPI app, WebSocket, SSE endpoints
│   ├── broker.py         # Alpaca connector with demo fallback
│   ├── strategy.py       # RSI + MA crossover engine
│   ├── claude_client.py  # Claude API streaming integration
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
└── research_agent/
    └── research-agent.agent.md
```

---

## Strategy Config

The default strategy is defined in `backend/strategy.py`. Key parameters:

| Parameter | Default | Description |
|---|---|---|
| `symbols` | AAPL, MSFT, NVDA, AMD, GOOGL | Symbols to scan |
| `rsi_period` | 14 | RSI lookback period |
| `rsi_oversold` | 35 | RSI buy threshold |
| `ma_fast` / `ma_slow` | 10 / 20 | MA crossover periods |
| `stop_loss_pct` | 2.0% | Stop loss |
| `take_profit_pct` | 5.0% | Take profit |
| `max_positions` | 5 | Max simultaneous positions |
| `position_size_pct` | 10.0% | % of equity per position |
| `scan_interval_seconds` | 60 | How often the engine scans |

All parameters can be changed at runtime by asking Claude.
