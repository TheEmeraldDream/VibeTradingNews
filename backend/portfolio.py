"""
Portfolio reader — loads holdings from local/portfolio.json if present,
otherwise falls back to generic mock data for demo mode.

When a local portfolio is present, current prices are fetched live from
yfinance (via fetch_live_prices, called through run_in_executor in main.py)
so P&L is always calculated against real market prices.
"""
import json
import logging
import math
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

_PORTFOLIO_TTL = 30   # seconds before re-reading the file from disk
_PRICE_TTL     = 60   # seconds before re-fetching live prices


# Demo holdings shown to new users before they configure a portfolio.
# avg_entry_price values are approximate historical costs — not used for display,
# only for unrealized P&L once live prices are fetched.
_DEMO_HOLDINGS = [
    {"symbol": "AAPL", "qty": 15.0, "avg_entry_price": 178.50},
    {"symbol": "NVDA", "qty":  5.0, "avg_entry_price": 620.00},
    {"symbol": "MSFT", "qty":  8.0, "avg_entry_price": 390.10},
]
_DEMO_CASH = 5_000.0


class PortfolioReader:
    def __init__(self):
        self._portfolio_cache: dict | None = None
        self._portfolio_cache_time: float = 0
        self._price_cache: dict[str, float] = {}
        self._prev_close_cache: dict[str, float] = {}
        self._price_cache_time: float = 0
        self._portfolio_path = Path(__file__).parent.parent / "local" / "portfolio.json"
        self.mode = "local" if self._portfolio_path.exists() else "demo"

    # ------------------------------------------------------------------ #
    # Internal helpers                                                      #
    # ------------------------------------------------------------------ #

    def _local_portfolio(self) -> dict | None:
        now = time.monotonic()
        if self._portfolio_cache is not None and now - self._portfolio_cache_time < _PORTFOLIO_TTL:
            return self._portfolio_cache
        path = self._portfolio_path
        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)
                self._portfolio_cache = data
                self._portfolio_cache_time = now
                return data
            except Exception as e:
                logger.error(f"Failed to read portfolio file: {e}")
        self._portfolio_cache = None
        return None

    def fetch_live_prices(self, symbols: list[str], force: bool = False) -> dict[str, float]:
        """
        Fetch current prices and previous close from yfinance for all symbols.
        Blocking — call via asyncio.get_running_loop().run_in_executor().
        Results are cached for _PRICE_TTL seconds; pass force=True to bypass the cache
        (used on every news refresh so prices are always current).

        Data quality: yfinance wraps Yahoo Finance's unofficial API (15-min delayed
        for free tier). Prices are validated to be finite and positive before caching;
        symbols that return bad data fall back to their last cached value.
        """
        now = time.monotonic()
        if not force and self._price_cache and now - self._price_cache_time < _PRICE_TTL:
            return self._price_cache
        if not YFINANCE_AVAILABLE or not symbols:
            return self._price_cache
        prices: dict[str, float] = {}
        prev_closes: dict[str, float] = {}
        for sym in symbols:
            try:
                fi = yf.Ticker(sym).fast_info
                raw = getattr(fi, "last_price", None) or getattr(fi, "regular_market_price", None)
                prev = getattr(fi, "previous_close", None)

                if raw is not None and math.isfinite(float(raw)) and float(raw) > 0:
                    prices[sym] = float(raw)
                else:
                    logger.warning(
                        f"Skipping invalid price for {sym}: {raw!r} "
                        f"(keeping cached value if available)"
                    )
                if prev is not None and math.isfinite(float(prev)) and float(prev) > 0:
                    prev_closes[sym] = float(prev)
            except Exception as e:
                logger.warning(f"Live price fetch failed for {sym}: {e}")

        if prices:
            # Merge into cache so symbols that failed keep their last good value
            self._price_cache.update(prices)
            self._prev_close_cache.update(prev_closes)
            self._price_cache_time = now
        return self._price_cache

    def reset_cache(self) -> None:
        """Invalidate all caches so the next read fetches fresh data."""
        self._portfolio_cache = None
        self._portfolio_cache_time = 0
        self._price_cache = {}
        self._prev_close_cache = {}
        self._price_cache_time = 0
        self.mode = "local" if self._portfolio_path.exists() else "demo"

    # ------------------------------------------------------------------ #
    # Account                                                              #
    # ------------------------------------------------------------------ #

    def _live_daily_pnl(self, positions: list[dict]) -> tuple[float, float]:
        """
        Compute today's P&L from live price vs previous close.
        Returns (daily_pnl, daily_pnl_pct). Falls back to (0, 0) if data unavailable.
        """
        if not self._prev_close_cache:
            return 0.0, 0.0
        pnl = 0.0
        prev_equity = 0.0
        for p in positions:
            sym  = p["symbol"]
            qty  = p["qty"]
            cur  = self._price_cache.get(sym)
            prev = self._prev_close_cache.get(sym)
            if cur and prev:
                pnl        += (cur - prev) * qty
                prev_equity += prev * qty
        if prev_equity == 0:
            return 0.0, 0.0
        return round(pnl, 2), round(pnl / prev_equity * 100, 2)

    def get_account(self) -> dict:
        local = self._local_portfolio()
        if local and "account" in local:
            a = local["account"]
            positions = self.get_positions()
            daily_pnl, daily_pnl_pct = self._live_daily_pnl(positions)
            if daily_pnl == 0.0:
                # Fall back to stored values if live daily data isn't ready yet
                daily_pnl     = a.get("daily_pnl", 0)
                daily_pnl_pct = a.get("daily_pnl_pct", 0)
            return {
                "equity":        a.get("equity", 0),
                "cash":          a.get("cash", 0),
                "buying_power":  a.get("buying_power", 0),
                "daily_pnl":     daily_pnl,
                "daily_pnl_pct": daily_pnl_pct,
                "mode":          self.mode,
                "status":        "ACTIVE",
            }

        # Demo mode: fetch live prices for demo symbols so new users see real data
        demo_syms = [h["symbol"] for h in _DEMO_HOLDINGS]
        if YFINANCE_AVAILABLE:
            self.fetch_live_prices(demo_syms)
        positions = self.get_positions()
        market_value = sum(p["market_value"] for p in positions)
        equity = round(market_value + _DEMO_CASH, 2)
        daily_pnl, daily_pnl_pct = self._live_daily_pnl(positions)
        return {
            "equity":        equity,
            "cash":          _DEMO_CASH,
            "buying_power":  _DEMO_CASH * 2,
            "daily_pnl":     daily_pnl,
            "daily_pnl_pct": daily_pnl_pct,
            "mode":          "demo",
            "status":        "ACTIVE",
        }

    def get_accounts(self) -> list[dict]:
        local = self._local_portfolio()
        if local and "accounts" in local:
            return local["accounts"]
        return []

    def _position_dict(self, symbol: str, qty: float, entry: float, price: float,
                       price_source: str = "live", account: str = "") -> dict:
        pl   = (price - entry) * qty
        plpc = ((price - entry) / entry * 100) if entry else 0.0
        return {
            "symbol":          symbol,
            "qty":             qty,
            "side":            "long",
            "avg_entry_price": entry,
            "current_price":   round(price, 2),
            "market_value":    round(price * qty, 2),
            "unrealized_pl":   round(pl, 2),
            "unrealized_plpc": round(plpc, 2),
            "price_source":    price_source,
            "account":         account,
        }

    # ------------------------------------------------------------------ #
    # Positions                                                            #
    # ------------------------------------------------------------------ #

    def get_positions(self) -> list[dict]:
        local = self._local_portfolio()
        if local and "positions" in local:
            result = []
            for p in local["positions"]:
                qty    = float(p["qty"])
                entry  = float(p["avg_entry_price"])
                sym    = p["symbol"]
                acct   = p.get("account", "")
                if sym in self._price_cache:
                    price  = self._price_cache[sym]
                    source = "live"
                else:
                    price  = float(p.get("current_price", entry))
                    source = "file"
                result.append(self._position_dict(sym, qty, entry, price, source, acct))
            return result

        # Demo mode: use live prices from yfinance so new users see real market data
        demo_syms = [h["symbol"] for h in _DEMO_HOLDINGS]
        if YFINANCE_AVAILABLE:
            self.fetch_live_prices(demo_syms)
        return [
            self._position_dict(
                h["symbol"], h["qty"], h["avg_entry_price"],
                self._price_cache.get(h["symbol"], h["avg_entry_price"]),
                "live" if h["symbol"] in self._price_cache else "demo",
                "demo",
            )
            for h in _DEMO_HOLDINGS
        ]

    # ------------------------------------------------------------------ #
    # P&L history (candlestick chart)                                      #
    # ------------------------------------------------------------------ #

    # Maps UI period codes to yfinance period string and candle interval.
    # "1h" intervals return Unix-timestamp keys; "1d" returns date-string keys.
    _PERIOD_CFG: dict[str, dict] = {
        "1D": {"yf_period": "1d",  "interval": "1h"},
        "5D": {"yf_period": "5d",  "interval": "1h"},
        "1M": {"yf_period": "1mo", "interval": "1d"},
        "3M": {"yf_period": "3mo", "interval": "1d"},
        "6M": {"yf_period": "6mo", "interval": "1d"},
        "1Y": {"yf_period": "1y",  "interval": "1d"},
    }

    def get_pnl_history(
        self,
        period: str = "1M",
        start: str | None = None,
        end: str | None = None,
        symbol_filter: list[str] | None = None,
    ) -> list[dict]:
        """
        Returns portfolio holdings market-value OHLC candles (sum of qty * price per symbol).
        Each entry: {time, open, high, low, close} — values are total holdings market value in $.
        Cash is excluded (not available historically), so this tracks equity minus cash balance.
        - Standard periods (1D/5D/1M/3M/6M/1Y): hourly candles for 1D/5D, daily otherwise.
        - CUSTOM period: daily candles between `start` and `end` (YYYY-MM-DD strings).
        - symbol_filter: if provided, only include positions whose symbol is in the list.
        """
        local = self._local_portfolio()
        if local and "positions" in local and YFINANCE_AVAILABLE:
            positions = local["positions"]
            if symbol_filter is not None:
                allowed = set(symbol_filter)
                positions = [p for p in positions if p["symbol"] in allowed]
            return self._live_pnl_history(positions, period, start, end)

        # Demo mode: use real yfinance history for demo symbols
        if YFINANCE_AVAILABLE:
            candles = self._live_pnl_history(_DEMO_HOLDINGS, period, start, end)
            if candles:
                return candles
        return self._demo_pnl_history(period, start, end)

    def _live_pnl_history(
        self,
        positions: list[dict],
        period: str,
        start: str | None,
        end: str | None,
    ) -> list[dict]:
        import yfinance as yf

        cfg      = self._PERIOD_CFG.get(period, self._PERIOD_CFG["1M"])
        interval = "1d" if period == "CUSTOM" else cfg["interval"]
        intraday = interval != "1d"
        candles: dict = {}

        for p in positions:
            sym = p["symbol"]
            qty = float(p["qty"])
            try:
                if period == "CUSTOM" and start and end:
                    hist = yf.Ticker(sym).history(start=start, end=end, interval=interval)
                else:
                    hist = yf.Ticker(sym).history(period=cfg["yf_period"], interval=interval)

                for ts, row in hist.iterrows():
                    # Intraday: use Unix timestamps so lightweight-charts handles time zones;
                    # daily: date strings are cleaner and avoid DST edge cases.
                    key = int(ts.timestamp()) if intraday else ts.strftime("%Y-%m-%d")
                    if key not in candles:
                        candles[key] = {"open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0}
                    # Market value (not P&L from entry) so the y-axis aligns with equity
                    candles[key]["open"]  += row["Open"]  * qty
                    candles[key]["high"]  += row["High"]  * qty
                    candles[key]["low"]   += row["Low"]   * qty
                    candles[key]["close"] += row["Close"] * qty
            except Exception as e:
                logger.warning(f"P&L history fetch failed for {sym}: {e}")

        return sorted(
            [{"time": k, "open": round(v["open"], 2), "high": round(v["high"], 2),
              "low": round(v["low"], 2), "close": round(v["close"], 2)}
             for k, v in candles.items()],
            key=lambda x: x["time"],
        )

    # Approximate total market value of the demo positions used in get_positions()
    _DEMO_BASE_VALUE = 15 * 184.20 + 5 * 645.80 + 8 * 385.50  # ≈ $9,076

    def _demo_pnl_history(
        self,
        period: str,
        start: str | None,
        end: str | None,
    ) -> list[dict]:
        """Deterministic mock portfolio-value history for demo mode."""
        cfg      = self._PERIOD_CFG.get(period, self._PERIOD_CFG["1M"])
        intraday = period in ("1D", "5D")
        rng      = random.Random(42)
        result   = []
        value    = self._DEMO_BASE_VALUE  # start at realistic market value, not 0

        if period == "CUSTOM" and start and end:
            start_d = datetime.strptime(start, "%Y-%m-%d").date()
            end_d   = datetime.strptime(end,   "%Y-%m-%d").date()
            d = start_d
            while d <= end_d:
                if d.weekday() < 5:
                    result.append(self._demo_candle(rng, d.strftime("%Y-%m-%d"), value))
                    value = result[-1]["close"]
                d += timedelta(days=1)
            return result

        if intraday:
            # Generate hourly candles across the last N trading days
            trading_days_needed = 1 if period == "1D" else 5
            today = datetime.now().date()
            days_collected = 0
            d = today
            while days_collected < trading_days_needed:
                if d.weekday() < 5:
                    # Market hours: 9:30–16:00 → ~7 hourly bars
                    for hour in (10, 11, 12, 13, 14, 15, 16):
                        ts = int(datetime(d.year, d.month, d.day, hour).timestamp())
                        c  = self._demo_candle(rng, ts, value)
                        result.append(c)
                        value = c["close"]
                    days_collected += 1
                d -= timedelta(days=1)
            return sorted(result, key=lambda x: x["time"])

        # Daily candles — walk back the required number of trading days
        days_map = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365}
        num_days = days_map.get(period, 30)
        today    = datetime.now().date()
        trading_days: list = []
        d = today
        while len(trading_days) < num_days:
            if d.weekday() < 5:
                trading_days.append(d)
            d -= timedelta(days=1)
        trading_days.reverse()

        for d in trading_days:
            c = self._demo_candle(rng, d.strftime("%Y-%m-%d"), value)
            result.append(c)
            value = c["close"]
        return result

    @staticmethod
    def _demo_candle(rng: random.Random, time_key, value: float) -> dict:
        # Daily move of ~0.5% avg, ~2% vol — realistic for a small equity portfolio
        change = rng.gauss(value * 0.005, value * 0.02)
        open_  = value
        close  = max(value + change, 1.0)  # prevent negative market value
        wick   = abs(rng.gauss(0, value * 0.008))
        high   = max(open_, close) + wick
        low    = max(min(open_, close) - wick, 1.0)
        return {
            "time":  time_key,
            "open":  round(open_, 2),
            "high":  round(high, 2),
            "low":   round(low, 2),
            "close": round(close, 2),
        }
