"""
setup_portfolio.py — First-time setup and portfolio builder.

Called automatically by run.bat / run.sh on every launch.
Can also be run directly: python setup_portfolio.py

On first run:  creates setup.txt with instructions, then exits.
On later runs: reads setup.txt to write AI keys to .env and build
               local/portfolio.json from live Yahoo Finance prices.
"""
import json
import re
import sys
from pathlib import Path

ROOT      = Path(__file__).parent.parent
SETUP_TXT = ROOT / "setup.txt"
ENV_PATH  = ROOT / ".env"
LOCAL_DIR = ROOT / "local"
JSON_PATH = LOCAL_DIR / "portfolio.json"

SETUP_TEMPLATE = """\
# ════════════════════════════════════════════════════════════════
#  AUCTION HOUSE — SETUP
#
#  1. Fill in your AI key and holdings below
#  2. Save this file
#  3. Run run.bat again to launch with your data
#
#  The app opens in demo mode until you fill this in.
# ════════════════════════════════════════════════════════════════


# ── AI KEY ──────────────────────────────────────────────────────
#  Paste ONE key below (you only need one). Get yours from:
#    Claude (recommended) → https://console.anthropic.com
#    ChatGPT              → https://platform.openai.com/api-keys
#    Gemini               → https://aistudio.google.com/app/apikey

ANTHROPIC_API_KEY =
OPENAI_API_KEY    =
GOOGLE_API_KEY    =


# ── HOLDINGS ────────────────────────────────────────────────────
#  One holding per line:  Account, Symbol, Shares, Avg Cost Per Share
#
#  Account  — a label you choose (e.g. Brokerage, Roth IRA, 401k)
#  Symbol   — stock or fund ticker (e.g. AAPL, VTI, VTSNX)
#  Shares   — number of shares you hold (decimals are fine)
#  Avg Cost — your average purchase price per share
#
#  To include uninvested cash: use CASH as the Symbol,
#  set Shares to the dollar amount, and Avg Cost to 0.
#
#  Delete the examples below and add your own holdings:

Brokerage, VTI,   25,    220.00
Brokerage, AAPL,  10,    155.00
Brokerage, MSFT,   8,    340.00
Brokerage, CASH, 5000,     0.00
My 401(k), VTSNX, 100,  140.00
My 401(k), VFIAX,  20,  480.00
"""

KEY_RE = re.compile(
    r"^(ANTHROPIC_API_KEY|OPENAI_API_KEY|GOOGLE_API_KEY|GEMINI_API_KEY)\s*=\s*(.+)$"
)


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_setup(path: Path):
    ai_keys: dict[str, str] = {}
    holdings: list[dict] = []

    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        m = KEY_RE.match(line)
        if m:
            value = m.group(2).strip()
            if value:
                ai_keys[m.group(1)] = value
            continue

        # Holding line: 4 comma-separated values
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 4:
            account, symbol, shares_str, cost_str = parts
            try:
                holdings.append({
                    "account": account,
                    "symbol":  symbol.upper(),
                    "shares":  float(shares_str),
                    "avg_cost": float(cost_str),
                })
            except ValueError:
                print(f"  WARNING: skipping unrecognised line: {line!r}")

    return ai_keys, holdings


# ── .env writer ───────────────────────────────────────────────────────────────

def update_env(keys: dict[str, str]) -> None:
    existing: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()
    existing.update(keys)
    ENV_PATH.write_text(
        "\n".join(f"{k}={v}" for k, v in existing.items()) + "\n",
        encoding="utf-8",
    )


# ── Portfolio builder ─────────────────────────────────────────────────────────

def to_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def build_portfolio(holdings: list[dict]) -> dict:
    account_order = list(dict.fromkeys(h["account"] for h in holdings))
    account_ids   = {name: to_id(name) for name in account_order}

    stock_symbols = list(dict.fromkeys(
        h["symbol"] for h in holdings if h["symbol"] != "CASH"
    ))

    # Fetch live prices
    prices: dict[str, float] = {}
    if stock_symbols:
        try:
            import yfinance as yf
            print("  Fetching live prices from Yahoo Finance...")
            for sym in stock_symbols:
                try:
                    fi    = yf.Ticker(sym).fast_info
                    price = getattr(fi, "last_price", None) or getattr(fi, "regular_market_price", None)
                    if price:
                        prices[sym] = float(price)
                        print(f"    {sym}: ${float(price):,.2f}")
                    else:
                        print(f"    {sym}: no live data — using avg cost")
                except Exception as e:
                    print(f"    {sym}: fetch failed ({e}) — using avg cost")
        except ImportError:
            print("  yfinance not available — using avg cost prices")

    # Build positions
    out_positions: list[dict] = []
    total_market_value = 0.0
    total_cash         = 0.0

    for h in holdings:
        sym     = h["symbol"]
        qty     = h["shares"]
        entry   = h["avg_cost"]
        acct_id = account_ids[h["account"]]

        if sym == "CASH":
            total_cash += qty
            continue

        price     = prices.get(sym, entry)
        market_val = qty * price
        pl         = (price - entry) * qty
        plpc       = ((price - entry) / entry * 100) if entry else 0.0
        total_market_value += market_val

        out_positions.append({
            "symbol":          sym,
            "account":         acct_id,
            "qty":             round(qty, 6),
            "avg_entry_price": round(entry, 4),
            "current_price":   round(price, 4),
            "unrealized_pl":   round(pl, 2),
            "unrealized_plpc": round(plpc, 2),
        })

    equity   = total_market_value + total_cash
    accounts = [{"id": account_ids[n], "name": n} for n in account_order]

    return {
        "accounts": accounts,
        "account": {
            "equity":       round(equity, 2),
            "cash":         round(total_cash, 2),
            "buying_power": round(total_cash, 2),
            "daily_pnl":    0.0,
            "daily_pnl_pct": 0.0,
        },
        "positions": out_positions,
    }


# ── Public API (called from main.py settings endpoints) ──────────────────────

def get_raw_config() -> str:
    """Return current setup.txt content, or the blank template if it doesn't exist."""
    return SETUP_TXT.read_text(encoding="utf-8-sig") if SETUP_TXT.exists() else SETUP_TEMPLATE


def save_and_rebuild(content: str) -> dict:
    """
    Write content to setup.txt and rebuild local/portfolio.json.
    Returns a summary dict. AI key changes require a server restart to take effect.
    """
    SETUP_TXT.write_text(content, encoding="utf-8")
    ai_keys, holdings = parse_setup(SETUP_TXT)

    if ai_keys:
        update_env(ai_keys)

    if not holdings:
        return {"portfolio_built": False, "message": "No holdings found — app will run in demo mode."}

    portfolio = build_portfolio(holdings)
    LOCAL_DIR.mkdir(exist_ok=True)
    JSON_PATH.write_text(json.dumps(portfolio, indent=2), encoding="utf-8")
    return {
        "portfolio_built": True,
        "equity":    portfolio["account"]["equity"],
        "positions": len(portfolio["positions"]),
        "accounts":  len(portfolio.get("accounts", [])),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # First run: create setup.txt and continue in demo mode
    if not SETUP_TXT.exists():
        SETUP_TXT.write_text(SETUP_TEMPLATE, encoding="utf-8")
        print()
        print("  ┌───────────────────────────────────────────────────────┐")
        print("  │  SETUP REQUIRED                                       │")
        print("  │                                                       │")
        print("  │  setup.txt has been created in this folder.           │")
        print("  │  Open it, fill in your AI key and holdings,           │")
        print("  │  then run run.bat again to use your real data.        │")
        print("  │                                                       │")
        print("  │  Launching in demo mode for now.                      │")
        print("  └───────────────────────────────────────────────────────┘")
        print()
        return

    ai_keys, holdings = parse_setup(SETUP_TXT)

    # Write AI keys to .env
    if ai_keys:
        update_env(ai_keys)
        for k in ai_keys:
            print(f"  AI key configured: {k}")

    if not holdings:
        print("  No holdings found in setup.txt — running in demo mode.")
        return

    # Skip rebuild if setup.txt hasn't changed since last build
    if JSON_PATH.exists() and JSON_PATH.stat().st_mtime >= SETUP_TXT.stat().st_mtime:
        print("  Holdings unchanged — skipping rebuild.")
        return

    n_stocks   = sum(1 for h in holdings if h["symbol"] != "CASH")
    n_accounts = len(dict.fromkeys(h["account"] for h in holdings))
    print(f"  Building portfolio: {n_stocks} holding(s) across {n_accounts} account(s)")

    portfolio = build_portfolio(holdings)

    LOCAL_DIR.mkdir(exist_ok=True)
    JSON_PATH.write_text(json.dumps(portfolio, indent=2), encoding="utf-8")
    print(f"  Portfolio saved — equity: ${portfolio['account']['equity']:,.2f}")


if __name__ == "__main__":
    main()
