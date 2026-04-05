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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, load_dotenv
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

from portfolio import PortfolioReader
from claude_client import AIClient
from news import NewsAggregator

# ------------------------------------------------------------------ #
# Globals                                                              #
# ------------------------------------------------------------------ #

portfolio = PortfolioReader()
news_aggregator = NewsAggregator()
ai_client = AIClient()

news_cache: dict[str, Any] = {"articles": [], "last_updated": None}

# ------------------------------------------------------------------ #
# Rate limiter                                                         #
# ------------------------------------------------------------------ #

limiter = Limiter(key_func=get_remote_address)

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
            logger.debug(f"Dropping dead WebSocket connection ({len(dead)} total)")
            self.disconnect(ws)


ws_manager = ConnectionManager()


# ------------------------------------------------------------------ #
# Background news refresh                                              #
# ------------------------------------------------------------------ #

async def _do_refresh() -> None:
    """Fetch live prices and news articles, updating news_cache in place."""
    loop = asyncio.get_running_loop()
    positions = portfolio.get_positions()
    symbols = [p["symbol"] for p in positions]
    if symbols:
        await loop.run_in_executor(None, portfolio.fetch_live_prices, symbols)
    news_cache["articles"] = await loop.run_in_executor(
        None, news_aggregator.get_news, symbols
    )
    news_cache["last_updated"] = datetime.now(timezone.utc).isoformat()
    logger.info(f"News refreshed — {len(news_cache['articles'])} articles for {symbols}")


async def _news_refresh() -> None:
    """Background loop: refresh prices + news every 5 minutes and broadcast to all clients."""
    while True:
        try:
            await _do_refresh()
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
        "account": portfolio.get_account(),
        "positions": portfolio.get_positions(),
        "news": news_cache.get("articles", []),
        "news_updated": news_cache.get("last_updated"),
        "ai_available": ai_client.available,
    }


# ------------------------------------------------------------------ #
# App lifecycle                                                        #
# ------------------------------------------------------------------ #

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_news_refresh())
    logger.info(f"News aggregator started — mode: {portfolio.mode}")
    yield
    task.cancel()


# Disable auto-generated API docs in production; re-enable locally by
# setting DOCS_ENABLED=true in .env.
_docs = os.getenv("DOCS_ENABLED", "false").lower() == "true"
app = FastAPI(
    title="News Aggregator",
    lifespan=lifespan,
    docs_url="/docs" if _docs else None,
    redoc_url=None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Security headers ───────────────────────────────────────────────

class _SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


app.add_middleware(_SecurityHeaders)

# ── CORS ───────────────────────────────────────────────────────────
# When the frontend is served by this server (the default), no CORS
# config is needed — requests are same-origin.
# Set ALLOWED_ORIGINS=https://yourdomain.com if the frontend lives
# on a different host (comma-separated for multiple origins).

_allowed_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
if _allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/app", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


# ------------------------------------------------------------------ #
# Request models                                                       #
# ------------------------------------------------------------------ #

class PromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=4000)

    @field_validator("prompt")
    @classmethod
    def strip_and_require(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("prompt must not be blank")
        return v


# ------------------------------------------------------------------ #
# REST endpoints                                                       #
# ------------------------------------------------------------------ #

@app.get("/")
async def root():
    return {"status": "ok", "portfolio_mode": portfolio.mode, "ui": "/app"}


@app.get("/api/account")
async def get_account():
    try:
        return portfolio.get_account()
    except Exception as e:
        logger.error(f"Failed to read account: {e}")
        raise HTTPException(status_code=500, detail="Failed to read account data")


@app.get("/api/positions")
async def get_positions():
    try:
        return portfolio.get_positions()
    except Exception as e:
        logger.error(f"Failed to read positions: {e}")
        raise HTTPException(status_code=500, detail="Failed to read positions")


@app.get("/api/news")
async def get_news():
    return {
        "articles": news_cache.get("articles", []),
        "last_updated": news_cache.get("last_updated"),
    }


@app.post("/api/news/refresh")
@limiter.limit("5/minute")
async def refresh_news(request: Request):
    try:
        await _do_refresh()
    except Exception as e:
        logger.error(f"Manual news refresh failed: {e}")
        raise HTTPException(status_code=503, detail="News refresh failed — check server logs")
    try:
        await ws_manager.broadcast(_build_snapshot())
    except Exception as e:
        logger.warning(f"Broadcast after manual refresh failed: {e}")
    return {
        "articles": news_cache["articles"],
        "last_updated": news_cache["last_updated"],
    }


@app.get("/api/pnl-history")
async def get_pnl_history(period: str = "1M", start: str = None, end: str = None):
    if period not in ("1D", "5D", "1M", "3M", "6M", "1Y", "CUSTOM"):
        raise HTTPException(status_code=400, detail=f"Invalid period '{period}'")
    if period == "CUSTOM" and not (start and end):
        raise HTTPException(status_code=400, detail="CUSTOM period requires start and end dates")
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: portfolio.get_pnl_history(period, start, end)
        )
    except Exception as e:
        logger.error(f"Failed to build P&L history: {e}")
        raise HTTPException(status_code=500, detail="Failed to build P&L history")


@app.get("/api/snapshot")
async def get_snapshot():
    try:
        return _build_snapshot()
    except Exception as e:
        logger.error(f"Failed to build snapshot: {e}")
        raise HTTPException(status_code=500, detail="Failed to build snapshot")


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
        "portfolio_mode": portfolio.mode,
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
@limiter.limit("10/minute")
async def claude_prompt(request: Request, body: PromptRequest):
    """
    Stream Claude's news analysis as Server-Sent Events.
    Events:
      data: {"type": "chunk", "text": "..."}
      data: {"type": "done"}
    """
    try:
        context = ai_client.build_context(
            account=portfolio.get_account(),
            positions=portfolio.get_positions(),
            news=news_cache.get("articles", []),
        )
    except Exception as e:
        logger.error(f"Failed to build analysis context: {e}")
        raise HTTPException(status_code=500, detail="Failed to build analysis context")

    async def generate():
        try:
            async for chunk in ai_client.stream_response(body.prompt, context):
                payload = json.dumps({"type": "chunk", "text": chunk})
                yield f"data: {payload}\n\n"
        except Exception as e:
            logger.error(f"Claude SSE error: {e}")
            payload = json.dumps({"type": "chunk", "text": "\n\n[Analysis failed. Please try again.]"})
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
    except Exception as e:
        logger.warning(f"Failed to send initial snapshot: {e}")

    try:
        # Keep the connection open; the client doesn't send messages,
        # but receive_text() lets us detect when it disconnects.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# ------------------------------------------------------------------ #
# Entry point                                                          #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host=host, port=port, reload=True)
