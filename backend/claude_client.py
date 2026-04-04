"""
AI client — streams financial news analysis.
Supports Anthropic Claude, OpenAI GPT, and Google Gemini.
Auto-detects provider from available API keys (priority: Anthropic → OpenAI → Google).
Set AI_PROVIDER=anthropic|openai|google in .env to override.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a financial news analyst. The user holds a portfolio of stocks and wants to understand how recent news affects their positions.

Your job:
1. Identify which news articles are most likely driving price movements in the user's holdings
2. Explain the causal chain — why would this specific news move the price?
3. Distinguish sentiment-driven short-term moves from fundamental changes
4. Flag material risks or opportunities based on the news
5. Be specific: reference article headlines and their timing when drawing correlations

Keep responses concise and actionable. Lead with the most impactful observations for the user's actual holdings."""

_PROVIDER_PRIORITY = ["anthropic", "openai", "google"]


class AIClient:
    def __init__(self):
        self._provider: str | None = None
        self._client = None

        preferred = os.getenv("AI_PROVIDER", "").lower()
        order = ([preferred] if preferred in _PROVIDER_PRIORITY else []) + \
                [p for p in _PROVIDER_PRIORITY if p != preferred]

        for provider in order:
            if self._init_provider(provider):
                break

        if not self._provider:
            logger.warning("No AI API key found — AI assistant disabled")

    def _init_provider(self, provider: str) -> bool:
        if provider == "anthropic":
            api_key = os.getenv("ANTHROPIC_API_KEY", "")
            if not api_key:
                return False
            try:
                import anthropic
                self._client = anthropic.AsyncAnthropic(api_key=api_key)
                self._provider = "anthropic"
                logger.info("AI client initialized (claude-opus-4-6)")
                return True
            except ImportError:
                logger.warning("anthropic package not installed")
                return False

        if provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY", "")
            if not api_key:
                return False
            try:
                import openai
                self._client = openai.AsyncOpenAI(api_key=api_key)
                self._provider = "openai"
                logger.info("AI client initialized (gpt-4o)")
                return True
            except ImportError:
                logger.warning("openai package not installed")
                return False

        if provider == "google":
            api_key = os.getenv("GOOGLE_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
            if not api_key:
                return False
            try:
                from google import genai
                self._client = genai.Client(api_key=api_key)
                self._provider = "google"
                logger.info("AI client initialized (gemini-2.0-flash)")
                return True
            except ImportError:
                logger.warning("google-genai package not installed")
                return False

        return False

    @property
    def available(self) -> bool:
        return self._client is not None

    @property
    def provider(self) -> str:
        return self._provider or "none"

    def build_context(
        self,
        account: dict,
        positions: list[dict],
        news: list[dict],
    ) -> str:
        pos_lines = "\n".join(
            f"  {p['symbol']}: {p['qty']:.0f} shares @ ${p['avg_entry_price']:.2f} entry, "
            f"current ${p['current_price']:.2f} "
            f"(P&L: {p['unrealized_pl']:+.2f}, {p['unrealized_plpc']:+.2f}%)"
            for p in positions
        ) or "  (none)"

        cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
        recent = [
            a for a in news
            if datetime.fromisoformat(a.get("published_at", "1970-01-01T00:00:00+00:00")) > cutoff
        ]

        news_lines = []
        for a in recent[:25]:
            pub = a.get("published_at", "")[:16].replace("T", " ")
            syms = ", ".join(a.get("symbols", []))
            summary = a.get("summary", "")[:200]
            news_lines.append(
                f"[{pub}] {syms} · {a.get('source', '')}\n"
                f"  {a.get('headline', '')}\n"
                f"  {summary}"
            )

        news_block = "\n\n".join(news_lines) if news_lines else "  (no recent news)"

        return f"""--- PORTFOLIO CONTEXT ---

ACCOUNT (mode: {account.get('mode', 'unknown')}):
  Equity:    ${account.get('equity', 0):,.2f}
  Daily P&L: {account.get('daily_pnl', 0):+,.2f} ({account.get('daily_pnl_pct', 0):+.2f}%)

HOLDINGS:
{pos_lines}

RECENT NEWS (last 48 hours, newest first):
{news_block}

--- END CONTEXT ---"""

    async def stream_response(
        self,
        user_prompt: str,
        context: str,
    ) -> AsyncGenerator[str, None]:
        if not self.available:
            yield (
                "No AI provider configured. "
                "Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY in your .env file."
            )
            return

        full_message = f"{context}\n\nUser request: {user_prompt}"

        if self._provider == "anthropic":
            async for chunk in self._stream_anthropic(full_message):
                yield chunk
        elif self._provider == "openai":
            async for chunk in self._stream_openai(full_message):
                yield chunk
        elif self._provider == "google":
            async for chunk in self._stream_google(full_message):
                yield chunk

    async def _stream_anthropic(self, message: str) -> AsyncGenerator[str, None]:
        try:
            async with self._client.messages.stream(
                model="claude-opus-4-6",
                max_tokens=4096,
                thinking={"type": "adaptive"},
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": message}],
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception as e:
            logger.error(f"Anthropic stream error: {e}")
            yield f"\n\n[Error: {e}]"

    async def _stream_openai(self, message: str) -> AsyncGenerator[str, None]:
        try:
            stream = await self._client.chat.completions.create(
                model="gpt-4o",
                max_tokens=4096,
                stream=True,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": message},
                ],
            )
            async for chunk in stream:
                text = chunk.choices[0].delta.content
                if text:
                    yield text
        except Exception as e:
            logger.error(f"OpenAI stream error: {e}")
            yield f"\n\n[Error: {e}]"

    async def _stream_google(self, message: str) -> AsyncGenerator[str, None]:
        try:
            from google.genai import types
            async for chunk in self._client.aio.models.generate_content_stream(
                model="gemini-2.0-flash",
                contents=message,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    max_output_tokens=4096,
                ),
            ):
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            logger.error(f"Gemini stream error: {e}")
            yield f"\n\n[Error: {e}]"
