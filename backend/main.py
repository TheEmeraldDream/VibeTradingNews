"""
Trading App — FastAPI backend
Run: uvicorn main:app --reload --port 8000
Open: http://localhost:8000
"""
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

from broker import BrokerClient
from claude_client import ClaudeClient
from strategy import StrategyEngine

# ------------------------------------------------------------------ #
# Globals                                                              #
# ------------------------------------------------------------------ #

broker = BrokerClient()
strategy_engine = StrategyEngine(broker)
claude_client = ClaudeClient()


# ------------------------------------------------------------------ #
# WebSocket manager                                                    #
# ------------------------------------------------------------------ #

class ConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws) if hasattr(self._connections, "discard") else None
        if ws in self._connections:
            self._connections.remove(ws)

    async def broadcast(self, data: dict) -> None:
        dead = []
        for ws in self._connections:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


ws_manager = ConnectionManager()


# ------------------------------------------------------------------ #
# Background market scanner                                            #
# ------------------------------------------------------------------ #

async def _market_scanner() -> None:
    """Scan symbols, push orders, broadcast live metrics."""
    while True:
        interval = strategy_engine.strategy.get("schedule", {}).get(
            "scan_interval_seconds", 60
        )
        try:
            if strategy_engine.strategy.get("enabled"):
                actions = strategy_engine.run_once()
                if actions:
                    logger.info(f"Scanner actions: {actions}")
        except Exception as e:
            logger.error(f"Scanner error: {e}")

        # Broadcast current state to all WebSocket clients
        try:
            snapshot = _build_snapshot()
            await ws_manager.broadcast(snapshot)
        except Exception as e:
            logger.error(f"Broadcast error: {e}")

        await asyncio.sleep(interval)


def _build_snapshot() -> dict[str, Any]:
    return {
        "type": "snapshot",
        "account": broker.get_account(),
        "positions": broker.get_positions(),
        "orders": broker.get_orders(limit=10),
        "metrics": strategy_engine.get_metrics(),
        "strategy": strategy_engine.get_summary(),
    }


# ------------------------------------------------------------------ #
# App lifecycle                                                        #
# ------------------------------------------------------------------ #

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_market_scanner())
    logger.info(f"Trading app started — broker mode: {broker.mode}")
    yield
    task.cancel()


app = FastAPI(title="Trading App", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/app", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


# ------------------------------------------------------------------ #
# REST endpoints                                                       #
# ------------------------------------------------------------------ #

@app.get("/")
async def root():
    return {"status": "ok", "broker_mode": broker.mode, "ui": "/app"}


@app.get("/api/account")
async def get_account():
    return broker.get_account()


@app.get("/api/positions")
async def get_positions():
    return broker.get_positions()


@app.get("/api/orders")
async def get_orders():
    return broker.get_orders()


@app.get("/api/strategy")
async def get_strategy():
    return strategy_engine.strategy


@app.put("/api/strategy")
async def update_strategy(updates: dict):
    strategy_engine.apply_updates(updates)
    return {"status": "updated", "strategy": strategy_engine.strategy}


@app.post("/api/strategy/toggle")
async def toggle_strategy():
    current = strategy_engine.strategy.get("enabled", False)
    strategy_engine.apply_updates({"enabled": not current})
    return {"enabled": strategy_engine.strategy["enabled"]}


@app.get("/api/metrics")
async def get_metrics():
    return strategy_engine.get_metrics()


@app.get("/api/snapshot")
async def get_snapshot():
    return _build_snapshot()


@app.get("/api/status")
async def get_status():
    return {
        "broker_mode": broker.mode,
        "broker_connected": broker.connected,
        "claude_available": claude_client.available,
        "strategy_enabled": strategy_engine.strategy.get("enabled", False),
    }


# ------------------------------------------------------------------ #
# Claude SSE endpoint                                                  #
# ------------------------------------------------------------------ #

@app.post("/api/claude")
async def claude_prompt(body: dict):
    """
    Stream Claude's response as Server-Sent Events.
    Body: {"prompt": "..."}
    Events:
      data: {"type": "chunk", "text": "..."}
      data: {"type": "updates", "strategy_updates": {...}}
      data: {"type": "done"}
    """
    user_prompt = body.get("prompt", "").strip()
    if not user_prompt:
        return {"error": "prompt is required"}

    context = claude_client.build_context(
        strategy=strategy_engine.strategy,
        account=broker.get_account(),
        positions=broker.get_positions(),
        metrics=strategy_engine.get_metrics(),
    )

    async def generate():
        full_text = ""
        try:
            async for chunk in claude_client.stream_response(user_prompt, context):
                full_text += chunk
                payload = json.dumps({"type": "chunk", "text": chunk})
                yield f"data: {payload}\n\n"

            # After full response, check for strategy updates
            updates = claude_client.extract_strategy_updates(full_text)
            if updates:
                strategy_engine.apply_updates(updates)
                payload = json.dumps({"type": "updates", "strategy_updates": updates})
                yield f"data: {payload}\n\n"
                logger.info(f"Applied Claude strategy updates: {list(updates.keys())}")

        except Exception as e:
            logger.error(f"Claude SSE error: {e}")
            payload = json.dumps({"type": "chunk", "text": f"\n\n[Error: {e}]"})
            yield f"data: {payload}\n\n"

        yield 'data: {"type": "done"}\n\n'

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ------------------------------------------------------------------ #
# WebSocket                                                            #
# ------------------------------------------------------------------ #

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    # Push immediate snapshot on connect
    try:
        await websocket.send_json(_build_snapshot())
    except Exception:
        pass

    try:
        while True:
            # Just keep the connection alive; scanner handles broadcasting
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# ------------------------------------------------------------------ #
# Entry point                                                          #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
