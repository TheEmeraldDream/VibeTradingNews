"""
Strategy engine — configurable via JSON, modifiable by Claude.
Uses RSI and moving-average crossover signals by default.
"""
import copy
import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_STRATEGY: dict = {
    "name": "RSI + MA Crossover",
    "description": (
        "Enters long when RSI is oversold and fast MA crosses above slow MA. "
        "Exits on RSI overbought, stop-loss, or take-profit."
    ),
    "enabled": False,
    "symbols": ["AAPL", "MSFT", "NVDA", "AMD", "GOOGL"],
    "conditions": {
        "entry": {
            "rsi_period": 14,
            "rsi_oversold": 35,
            "ma_fast": 10,
            "ma_slow": 20,
            "use_rsi": True,
            "use_ma_crossover": True,
        },
        "exit": {
            "stop_loss_pct": 2.0,
            "take_profit_pct": 5.0,
            "rsi_overbought": 70,
            "use_rsi_exit": True,
        },
    },
    "position_sizing": {
        "max_positions": 5,
        "position_size_pct": 10.0,
        "max_portfolio_risk_pct": 5.0,
    },
    "schedule": {
        "scan_interval_seconds": 60,
        "trading_hours_only": True,
    },
}


def _deep_merge(base: dict, updates: dict) -> dict:
    """Recursively merge updates into base (non-destructive to base)."""
    result = copy.deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def calculate_rsi(closes: list[float], period: int = 14) -> float:
    """Wilder's RSI. Returns 50.0 if insufficient data."""
    if len(closes) < period + 1:
        return 50.0
    arr = np.array(closes, dtype=float)
    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def calculate_ma(closes: list[float], period: int) -> float:
    if len(closes) < period:
        return closes[-1] if closes else 0.0
    return float(np.mean(closes[-period:]))


class StrategyEngine:
    def __init__(self, broker):
        self.broker = broker
        self.strategy: dict = copy.deepcopy(DEFAULT_STRATEGY)
        self.trade_log: list[dict] = []   # closed trades for win-rate tracking
        self.signals: list[dict] = []     # most recent scan signals

    # ------------------------------------------------------------------ #
    # Config management                                                    #
    # ------------------------------------------------------------------ #

    def apply_updates(self, updates: dict) -> None:
        """Deep-merge Claude's updates into the live strategy."""
        self.strategy = _deep_merge(self.strategy, updates)
        logger.info(f"Strategy updated: {list(updates.keys())}")

    def get_summary(self) -> dict:
        """Return a human-readable summary of the current strategy."""
        s = self.strategy
        return {
            "name": s["name"],
            "description": s["description"],
            "enabled": s["enabled"],
            "symbols": s["symbols"],
            "entry_conditions": {
                "rsi_oversold": s["conditions"]["entry"]["rsi_oversold"],
                "ma_fast": s["conditions"]["entry"]["ma_fast"],
                "ma_slow": s["conditions"]["entry"]["ma_slow"],
            },
            "exit_conditions": {
                "stop_loss_pct": s["conditions"]["exit"]["stop_loss_pct"],
                "take_profit_pct": s["conditions"]["exit"]["take_profit_pct"],
            },
            "max_positions": s["position_sizing"]["max_positions"],
            "position_size_pct": s["position_sizing"]["position_size_pct"],
        }

    # ------------------------------------------------------------------ #
    # Indicator calculation                                                #
    # ------------------------------------------------------------------ #

    def _analyze_symbol(self, symbol: str) -> Optional[dict]:
        """Fetch bars and compute indicators. Returns signal dict or None."""
        cfg = self.strategy["conditions"]
        entry = cfg["entry"]
        rsi_period = entry.get("rsi_period", 14)
        ma_fast = entry.get("ma_fast", 10)
        ma_slow = entry.get("ma_slow", 20)
        needed = max(rsi_period + 5, ma_slow + 5)

        bars = self.broker.get_bars(symbol, limit=needed)
        if len(bars) < ma_slow + 2:
            return None

        closes = [b["c"] for b in bars]
        rsi = calculate_rsi(closes, rsi_period)
        fast = calculate_ma(closes, ma_fast)
        slow = calculate_ma(closes, ma_slow)
        fast_prev = calculate_ma(closes[:-1], ma_fast)
        slow_prev = calculate_ma(closes[:-1], ma_slow)
        current_price = closes[-1]
        volume = bars[-1].get("v", 0)

        return {
            "symbol": symbol,
            "price": current_price,
            "rsi": rsi,
            "ma_fast": fast,
            "ma_slow": slow,
            "crossover": fast > slow and fast_prev <= slow_prev,  # bullish cross
            "crossunder": fast < slow and fast_prev >= slow_prev,  # bearish cross
            "volume": volume,
        }

    # ------------------------------------------------------------------ #
    # Strategy execution                                                   #
    # ------------------------------------------------------------------ #

    def run_once(self) -> list[dict]:
        """
        Scan all symbols, check entry/exit signals, place orders.
        Returns list of actions taken (for logging).
        """
        if not self.strategy["enabled"]:
            return []

        s = self.strategy
        entry_cfg = s["conditions"]["entry"]
        exit_cfg = s["conditions"]["exit"]
        sizing = s["position_sizing"]

        account = self.broker.get_account()
        positions = self.broker.get_positions()
        open_symbols = {p["symbol"] for p in positions}
        equity = account.get("equity", 100_000)

        actions = []
        new_signals = []

        # ---- Exit checks for open positions ----
        for pos in positions:
            sym = pos["symbol"]
            plpc = pos["unrealized_plpc"]
            signal = self._analyze_symbol(sym)
            if signal:
                new_signals.append(signal)

            stop = exit_cfg["stop_loss_pct"]
            target = exit_cfg["take_profit_pct"]
            rsi_ob = exit_cfg.get("rsi_overbought", 70)
            use_rsi_exit = exit_cfg.get("use_rsi_exit", True)

            should_exit = False
            reason = ""

            if plpc <= -stop:
                should_exit = True
                reason = f"stop-loss ({plpc:.2f}%)"
            elif plpc >= target:
                should_exit = True
                reason = f"take-profit ({plpc:.2f}%)"
            elif use_rsi_exit and signal and signal["rsi"] >= rsi_ob:
                should_exit = True
                reason = f"RSI overbought ({signal['rsi']:.1f})"

            if should_exit:
                result = self.broker.place_market_order(sym, abs(pos["qty"]), "sell")
                action = {"type": "exit", "symbol": sym, "reason": reason, "result": result}
                actions.append(action)
                self.trade_log.append({
                    "symbol": sym,
                    "side": "sell",
                    "pnl_pct": plpc,
                    "profitable": plpc > 0,
                    "reason": reason,
                })
                logger.info(f"EXIT {sym}: {reason}")

        # ---- Entry checks for non-held symbols ----
        max_pos = sizing.get("max_positions", 5)
        current_pos_count = len(positions)

        for sym in s["symbols"]:
            if current_pos_count >= max_pos:
                break
            if sym in open_symbols:
                continue

            signal = self._analyze_symbol(sym)
            if not signal:
                continue
            new_signals.append(signal)

            rsi_os = entry_cfg.get("rsi_oversold", 35)
            use_rsi = entry_cfg.get("use_rsi", True)
            use_ma = entry_cfg.get("use_ma_crossover", True)

            rsi_ok = (not use_rsi) or (signal["rsi"] <= rsi_os)
            ma_ok = (not use_ma) or signal["crossover"]

            if rsi_ok and ma_ok:
                size_pct = sizing.get("position_size_pct", 10.0) / 100.0
                position_value = equity * size_pct
                qty = position_value / signal["price"]
                qty = max(1, int(qty))

                result = self.broker.place_market_order(sym, qty, "buy")
                action = {
                    "type": "entry",
                    "symbol": sym,
                    "qty": qty,
                    "price": signal["price"],
                    "rsi": signal["rsi"],
                    "result": result,
                }
                actions.append(action)
                current_pos_count += 1
                open_symbols.add(sym)
                logger.info(
                    f"ENTRY {sym}: qty={qty}, price={signal['price']:.2f}, rsi={signal['rsi']:.1f}"
                )

        self.signals = new_signals[-20:]  # keep recent signals
        return actions

    # ------------------------------------------------------------------ #
    # Metrics                                                              #
    # ------------------------------------------------------------------ #

    def get_metrics(self) -> dict:
        closed = self.trade_log
        total = len(closed)
        wins = sum(1 for t in closed if t.get("profitable"))
        win_rate = (wins / total * 100) if total else 0.0
        return {
            "total_closed_trades": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate_pct": round(win_rate, 1),
            "recent_signals": self.signals[-10:],
        }
