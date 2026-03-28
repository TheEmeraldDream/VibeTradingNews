"""
Broker connector — wraps Alpaca API with a mock fallback for demo mode.
Set ALPACA_API_KEY and ALPACA_SECRET_KEY in .env to connect live/paper.
"""
import os
import logging
import random
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Try importing alpaca-py; if missing, demo mode only
try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import (
        GetOrdersRequest,
        MarketOrderRequest,
        LimitOrderRequest,
    )
    from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False
    logger.warning("alpaca-py not installed — running in demo mode")


class BrokerClient:
    def __init__(self):
        self.api_key = os.getenv("ALPACA_API_KEY", "")
        self.secret_key = os.getenv("ALPACA_SECRET_KEY", "")
        self.paper = os.getenv("ALPACA_PAPER", "true").lower() == "true"
        self.connected = False
        self.mode = "demo"
        self._client = None
        self._data_client = None

        if ALPACA_AVAILABLE and self.api_key and self.secret_key:
            try:
                self._client = TradingClient(
                    self.api_key, self.secret_key, paper=self.paper
                )
                self._data_client = StockHistoricalDataClient(
                    self.api_key, self.secret_key
                )
                # Validate by fetching account
                self._client.get_account()
                self.connected = True
                self.mode = "paper" if self.paper else "live"
                logger.info(f"Broker connected — mode: {self.mode}")
            except Exception as e:
                logger.warning(f"Broker connection failed: {e}. Using demo mode.")

    # ------------------------------------------------------------------ #
    # Account                                                              #
    # ------------------------------------------------------------------ #

    def get_account(self) -> dict:
        if not self.connected:
            return self._mock_account()
        try:
            a = self._client.get_account()
            equity = float(a.equity)
            last_equity = float(a.last_equity)
            daily_pnl = equity - last_equity
            return {
                "equity": equity,
                "cash": float(a.cash),
                "buying_power": float(a.buying_power),
                "daily_pnl": daily_pnl,
                "daily_pnl_pct": (daily_pnl / last_equity * 100) if last_equity else 0,
                "mode": self.mode,
                "status": str(a.status),
            }
        except Exception as e:
            logger.error(f"get_account error: {e}")
            return self._mock_account()

    def _mock_account(self) -> dict:
        base = 100_000.0
        pnl = random.uniform(-500, 1500)
        return {
            "equity": base + pnl,
            "cash": 72_340.50,
            "buying_power": 144_681.00,
            "daily_pnl": pnl,
            "daily_pnl_pct": pnl / base * 100,
            "mode": "demo",
            "status": "ACTIVE",
        }

    # ------------------------------------------------------------------ #
    # Positions                                                            #
    # ------------------------------------------------------------------ #

    def get_positions(self) -> list[dict]:
        if not self.connected:
            return self._mock_positions()
        try:
            positions = self._client.get_all_positions()
            return [
                {
                    "symbol": p.symbol,
                    "qty": float(p.qty),
                    "side": "long" if float(p.qty) > 0 else "short",
                    "avg_entry_price": float(p.avg_entry_price),
                    "current_price": float(p.current_price),
                    "market_value": float(p.market_value),
                    "unrealized_pl": float(p.unrealized_pl),
                    "unrealized_plpc": float(p.unrealized_plpc) * 100,
                }
                for p in positions
            ]
        except Exception as e:
            logger.error(f"get_positions error: {e}")
            return self._mock_positions()

    def _mock_positions(self) -> list[dict]:
        mock = [
            ("AAPL", 15, 178.50, 184.20),
            ("NVDA", 5, 620.00, 645.80),
            ("MSFT", 8, 390.10, 385.50),
        ]
        result = []
        for sym, qty, entry, current in mock:
            pl = (current - entry) * qty
            plpc = (current - entry) / entry * 100
            result.append({
                "symbol": sym,
                "qty": float(qty),
                "side": "long",
                "avg_entry_price": entry,
                "current_price": current + random.uniform(-1, 1),
                "market_value": current * qty,
                "unrealized_pl": pl,
                "unrealized_plpc": plpc,
            })
        return result

    # ------------------------------------------------------------------ #
    # Orders                                                               #
    # ------------------------------------------------------------------ #

    def get_orders(self, limit: int = 20) -> list[dict]:
        if not self.connected:
            return self._mock_orders()
        try:
            orders = self._client.get_orders(
                filter=GetOrdersRequest(status=QueryOrderStatus.ALL, limit=limit)
            )
            return [
                {
                    "id": str(o.id),
                    "symbol": o.symbol,
                    "side": str(o.side.value),
                    "qty": float(o.qty or 0),
                    "filled_qty": float(o.filled_qty or 0),
                    "filled_avg_price": float(o.filled_avg_price or 0),
                    "type": str(o.type.value),
                    "status": str(o.status.value),
                    "created_at": o.created_at.isoformat() if o.created_at else "",
                }
                for o in orders
            ]
        except Exception as e:
            logger.error(f"get_orders error: {e}")
            return self._mock_orders()

    def _mock_orders(self) -> list[dict]:
        entries = [
            ("AAPL", "buy", 15, 178.50, "filled"),
            ("NVDA", "buy", 5, 620.00, "filled"),
            ("MSFT", "buy", 8, 390.10, "filled"),
            ("AMD", "buy", 10, 152.30, "canceled"),
            ("TSLA", "sell", 6, 245.80, "filled"),
            ("GOOGL", "buy", 3, 142.20, "pending_new"),
        ]
        now = datetime.utcnow()
        result = []
        for i, (sym, side, qty, price, status) in enumerate(entries):
            result.append({
                "id": f"mock-{i}",
                "symbol": sym,
                "side": side,
                "qty": float(qty),
                "filled_qty": float(qty) if status == "filled" else 0.0,
                "filled_avg_price": price if status == "filled" else 0.0,
                "type": "market",
                "status": status,
                "created_at": (now - timedelta(hours=i * 2)).isoformat(),
            })
        return result

    # ------------------------------------------------------------------ #
    # Trade execution                                                      #
    # ------------------------------------------------------------------ #

    def place_market_order(
        self, symbol: str, qty: float, side: str
    ) -> dict[str, Any]:
        if not self.connected:
            logger.info(f"[DEMO] Would place {side} {qty} {symbol}")
            return {"status": "demo_simulated", "symbol": symbol, "qty": qty, "side": side}
        try:
            order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
            req = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                time_in_force=TimeInForce.DAY,
            )
            order = self._client.submit_order(req)
            return {"status": "submitted", "id": str(order.id), "symbol": symbol}
        except Exception as e:
            logger.error(f"place_market_order error: {e}")
            return {"status": "error", "message": str(e)}

    # ------------------------------------------------------------------ #
    # Historical bars (for strategy indicators)                            #
    # ------------------------------------------------------------------ #

    def get_bars(self, symbol: str, limit: int = 50) -> list[dict]:
        """Return list of OHLCV dicts, newest last."""
        if not self.connected or self._data_client is None:
            return self._mock_bars(symbol, limit)
        try:
            end = datetime.utcnow()
            start = end - timedelta(days=limit * 2)
            req = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Day,
                start=start,
                end=end,
                limit=limit,
            )
            bars = self._data_client.get_stock_bars(req)
            df = bars.df
            if df.empty:
                return self._mock_bars(symbol, limit)
            return [
                {
                    "t": str(row.Index[1]) if hasattr(row.Index, "__len__") else str(row.Index),
                    "o": float(row.open),
                    "h": float(row.high),
                    "l": float(row.low),
                    "c": float(row.close),
                    "v": float(row.volume),
                }
                for row in df.itertuples()
            ]
        except Exception as e:
            logger.error(f"get_bars error for {symbol}: {e}")
            return self._mock_bars(symbol, limit)

    def _mock_bars(self, symbol: str, limit: int = 50) -> list[dict]:
        seed = sum(ord(c) for c in symbol)
        random.seed(seed)
        price = 100.0 + (seed % 400)
        bars = []
        now = datetime.utcnow()
        for i in range(limit):
            price += random.uniform(-3, 3)
            bars.append({
                "t": (now - timedelta(days=limit - i)).isoformat(),
                "o": round(price - random.uniform(0, 1), 2),
                "h": round(price + random.uniform(0, 2), 2),
                "l": round(price - random.uniform(0, 2), 2),
                "c": round(price, 2),
                "v": random.randint(500_000, 5_000_000),
            })
        random.seed()
        return bars
