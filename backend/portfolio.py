"""
Portfolio reader — loads holdings from local/portfolio.json if present,
otherwise falls back to generic mock data for demo mode.

When a local portfolio is present, current prices are fetched live from
yfinance (via fetch_live_prices, called through run_in_executor in main.py)
so P&L is always calculated against real market prices.
"""
import json
import logging
import random
import time
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

_PORTFOLIO_TTL = 30   # seconds before re-reading the file from disk
_PRICE_TTL     = 60   # seconds before re-fetching live prices


class PortfolioReader:
    mode = "demo"
    connected = False

    def __init__(self):
        self._portfolio_cache: dict | None = None
        self._portfolio_cache_time: float = 0
        self._price_cache: dict[str, float] = {}
        self._price_cache_time: float = 0

    # ------------------------------------------------------------------ #
    # Internal helpers                                                      #
    # ------------------------------------------------------------------ #

    def _local_portfolio(self) -> dict | None:
        now = time.monotonic()
        if self._portfolio_cache is not None and now - self._portfolio_cache_time < _PORTFOLIO_TTL:
            return self._portfolio_cache
        path = Path(__file__).parent.parent / "local" / "portfolio.json"
        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)
                self._portfolio_cache = data
                self._portfolio_cache_time = now
                return data
            except Exception:
                pass
        self._portfolio_cache = None
        return None

    def fetch_live_prices(self, symbols: list[str]) -> dict[str, float]:
        """
        Fetch current prices from yfinance for all symbols.
        Blocking — call via asyncio.get_running_loop().run_in_executor().
        Results are cached for _PRICE_TTL seconds.
        """
        now = time.monotonic()
        if self._price_cache and now - self._price_cache_time < _PRICE_TTL:
            return self._price_cache
        if not YFINANCE_AVAILABLE or not symbols:
            return self._price_cache
        prices = {}
        for sym in symbols:
            try:
                fi = yf.Ticker(sym).fast_info
                price = getattr(fi, "last_price", None) or getattr(fi, "regular_market_price", None)
                if price:
                    prices[sym] = float(price)
            except Exception as e:
                logger.warning(f"Live price fetch failed for {sym}: {e}")
        if prices:
            self._price_cache = prices
            self._price_cache_time = now
        return self._price_cache

    # ------------------------------------------------------------------ #
    # Account                                                              #
    # ------------------------------------------------------------------ #

    def get_account(self) -> dict:
        local = self._local_portfolio()
        if local and "account" in local:
            a = local["account"]
            return {
                "equity":        a.get("equity", 0),
                "cash":          a.get("cash", 0),
                "buying_power":  a.get("buying_power", 0),
                "daily_pnl":     a.get("daily_pnl", 0),
                "daily_pnl_pct": a.get("daily_pnl_pct", 0),
                "mode":          "demo",
                "status":        "ACTIVE",
            }
        base = 100_000.0
        pnl = random.uniform(-500, 1500)
        return {
            "equity":        base + pnl,
            "cash":          72_340.50,
            "buying_power":  144_681.00,
            "daily_pnl":     pnl,
            "daily_pnl_pct": pnl / base * 100,
            "mode":          "demo",
            "status":        "ACTIVE",
        }

    # ------------------------------------------------------------------ #
    # Positions                                                            #
    # ------------------------------------------------------------------ #

    def get_positions(self) -> list[dict]:
        local = self._local_portfolio()
        if local and "positions" in local:
            result = []
            for p in local["positions"]:
                qty   = float(p["qty"])
                entry = float(p["avg_entry_price"])
                # Use live price if cached, otherwise fall back to file value
                price = self._price_cache.get(p["symbol"], float(p.get("current_price", entry)))
                pl    = (price - entry) * qty
                plpc  = (price - entry) / entry * 100
                result.append({
                    "symbol":          p["symbol"],
                    "qty":             qty,
                    "side":            "long",
                    "avg_entry_price": entry,
                    "current_price":   round(price, 2),
                    "market_value":    round(price * qty, 2),
                    "unrealized_pl":   round(pl, 2),
                    "unrealized_plpc": round(plpc, 2),
                })
            return result
        mock = [
            ("AAPL", 15, 178.50, 184.20),
            ("NVDA", 5,  620.00, 645.80),
            ("MSFT", 8,  390.10, 385.50),
        ]
        result = []
        for sym, qty, entry, current in mock:
            current += random.uniform(-1, 1)
            pl  = (current - entry) * qty
            plpc = (current - entry) / entry * 100
            result.append({
                "symbol":          sym,
                "qty":             float(qty),
                "side":            "long",
                "avg_entry_price": entry,
                "current_price":   round(current, 2),
                "market_value":    round(current * qty, 2),
                "unrealized_pl":   round(pl, 2),
                "unrealized_plpc": round(plpc, 2),
            })
        return result
