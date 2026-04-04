"""
News Aggregator — FastAPI backend
Run: uvicorn main:app --reload --port 8000
Open: http://localhost:8000/app
"""
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv, dotenv_values
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
from claude_client import AIClient
from news import NewsAggregator

# ------------------------------------------------------------------ #
# Globals                                                              #
# ------------------------------------------------------------------ #

broker = BrokerClient()
news_aggregator = NewsAggregator()
ai_client = AIClient()

news_cache: dict[str, Any] = {"articles": [], "last_updated": None}


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
# Background news refresh                                              #
# ------------------------------------------------------------------ #

async def _news_refresh() -> None:
    """Fetch news for current holdings every 5 minutes and broadcast."""
    while True:
        try:
            positions = broker.get_positions()
            symbols = [p["symbol"] for p in positions]
            news_cache["articles"] = news_aggregator.get_news(symbols)
            from datetime import datetime
            news_cache["last_updated"] = datetime.utcnow().isoformat()
            logger.info(f"News refreshed — {len(news_cache['articles'])} articles for {symbols}")
        except Exception as e:
            logger.error(f"News refresh error: {e}")

        try:
            await ws_manager.broadcast(_build_snapshot())
        except Exception as e:
            logger.error(f"Broadcast error: {e}")

        await asyncio.sleep(300)


def _build_snapshot() -> dict[str, Any]:
    return {
        "type": "snapshot",
        "account": broker.get_account(),
        "positions": broker.get_positions(),
        "news": news_cache.get("articles", []),
        "news_updated": news_cache.get("last_updated"),
    }


# ------------------------------------------------------------------ #
# App lifecycle                                                        #
# ------------------------------------------------------------------ #

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_news_refresh())
    logger.info(f"News aggregator started — broker mode: {broker.mode}")
    yield
    task.cancel()


app = FastAPI(title="News Aggregator", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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


@app.get("/api/news")
async def get_news():
    return {
        "articles": news_cache.get("articles", []),
        "last_updated": news_cache.get("last_updated"),
    }


@app.post("/api/news/refresh")
async def refresh_news():
    positions = broker.get_positions()
    symbols = [p["symbol"] for p in positions]
    news_cache["articles"] = news_aggregator.get_news(symbols)
    from datetime import datetime
    news_cache["last_updated"] = datetime.utcnow().isoformat()
    await ws_manager.broadcast(_build_snapshot())
    return {
        "articles": news_cache["articles"],
        "last_updated": news_cache["last_updated"],
    }


@app.get("/api/snapshot")
async def get_snapshot():
    return _build_snapshot()


def _env_keys_configured() -> list[str]:
    """Read .env file directly and return which AI providers have keys set."""
    env_path = Path(__file__).parent.parent / ".env"
    vals = dotenv_values(env_path) if env_path.exists() else {}
    found = []
    if vals.get("ANTHROPIC_API_KEY", "").strip():
        found.append("anthropic")
    if vals.get("OPENAI_API_KEY", "").strip():
        found.append("openai")
    if vals.get("GOOGLE_API_KEY", "").strip() or vals.get("GEMINI_API_KEY", "").strip():
        found.append("google")
    return found


@app.get("/api/status")
async def get_status():
    return {
        "broker_mode": broker.mode,
        "broker_connected": broker.connected,
        "ai_available": ai_client.available,
        "ai_provider": ai_client.provider,
        "ai_keys_in_env": _env_keys_configured(),
        "news_demo": news_aggregator.demo,
        "news_article_count": len(news_cache.get("articles", [])),
        "news_last_updated": news_cache.get("last_updated"),
    }


# ------------------------------------------------------------------ #
# Claude SSE endpoint                                                  #
# ------------------------------------------------------------------ #

@app.post("/api/claude")
async def claude_prompt(body: dict):
    """
    Stream Claude's news analysis as Server-Sent Events.
    Body: {"prompt": "..."}
    Events:
      data: {"type": "chunk", "text": "..."}
      data: {"type": "done"}
    """
    user_prompt = body.get("prompt", "").strip()
    if not user_prompt:
        return {"error": "prompt is required"}

    context = ai_client.build_context(
        account=broker.get_account(),
        positions=broker.get_positions(),
        news=news_cache.get("articles", []),
    )

    async def generate():
        try:
            async for chunk in ai_client.stream_response(user_prompt, context):
                payload = json.dumps({"type": "chunk", "text": chunk})
                yield f"data: {payload}\n\n"
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
    try:
        await websocket.send_json(_build_snapshot())
    except Exception:
        pass

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# ------------------------------------------------------------------ #
# Entry point                                                          #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
