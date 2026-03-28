"""
Claude API integration — streams strategy analysis and modifications.
Uses claude-opus-4-6 with adaptive thinking.
"""
import json
import logging
import os
import re
from typing import AsyncGenerator, Optional

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert algorithmic trading strategy assistant with deep knowledge of quantitative finance, technical analysis, and risk management. You help traders analyze and improve their automated trading strategies.

When the user asks you to modify the strategy or when you identify improvements, you should:
1. Provide clear analysis of the current situation
2. Explain your reasoning and any trade-offs
3. If strategy changes are warranted, include them as a JSON block at the END of your response

Strategy updates must be in this exact format:
```json
{
  "strategy_updates": {
    "field_to_change": "new_value"
  }
}
```

Only include fields that need to change — they will be deep-merged into the current strategy config.

Examples of valid update structures:
- Change RSI threshold: {"conditions": {"entry": {"rsi_oversold": 30}}}
- Change symbols: {"symbols": ["AAPL", "MSFT", "TSLA"]}
- Change stop loss: {"conditions": {"exit": {"stop_loss_pct": 1.5}}}
- Enable/disable: {"enabled": true}

Keep responses concise and actionable. Flag any risk concerns clearly."""


class ClaudeClient:
    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self._client = None

        if not self.api_key:
            logger.warning("ANTHROPIC_API_KEY not set — Claude assistant disabled")
            return

        try:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
            logger.info("Claude client initialized (claude-opus-4-6)")
        except ImportError:
            logger.warning("anthropic package not installed")

    @property
    def available(self) -> bool:
        return self._client is not None

    def build_context(
        self,
        strategy: dict,
        account: dict,
        positions: list[dict],
        metrics: dict,
    ) -> str:
        """Build the context block injected into the Claude conversation."""
        pos_text = "\n".join(
            f"  {p['symbol']}: {p['qty']:.0f} shares @ ${p['avg_entry_price']:.2f}, "
            f"P&L: {p['unrealized_pl']:+.2f} ({p['unrealized_plpc']:+.2f}%)"
            for p in positions
        ) or "  (none)"

        return f"""--- CURRENT CONTEXT ---

STRATEGY CONFIG:
{json.dumps(strategy, indent=2)}

ACCOUNT (mode: {account.get('mode', 'unknown')}):
  Equity:       ${account.get('equity', 0):,.2f}
  Cash:         ${account.get('cash', 0):,.2f}
  Buying Power: ${account.get('buying_power', 0):,.2f}
  Daily P&L:    {account.get('daily_pnl', 0):+,.2f} ({account.get('daily_pnl_pct', 0):+.2f}%)

OPEN POSITIONS:
{pos_text}

PERFORMANCE METRICS:
  Closed Trades: {metrics.get('total_closed_trades', 0)}
  Win Rate:      {metrics.get('win_rate_pct', 0):.1f}%
  Wins / Losses: {metrics.get('wins', 0)} / {metrics.get('losses', 0)}

--- END CONTEXT ---"""

    async def stream_response(
        self,
        user_prompt: str,
        context: str,
    ) -> AsyncGenerator[str, None]:
        """
        Async generator that yields text chunks from Claude.
        Raises RuntimeError if client is unavailable.
        """
        if not self.available:
            yield "Claude is not available. Please set ANTHROPIC_API_KEY in your .env file."
            return

        full_message = f"{context}\n\nUser request: {user_prompt}"

        try:
            async with self._client.messages.stream(
                model="claude-opus-4-6",
                max_tokens=4096,
                thinking={"type": "adaptive"},
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": full_message}],
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception as e:
            logger.error(f"Claude stream error: {e}")
            yield f"\n\n[Error communicating with Claude: {e}]"

    def extract_strategy_updates(self, text: str) -> Optional[dict]:
        """
        Parse a ```json {...} ``` block containing strategy_updates from Claude's response.
        Returns the updates dict or None if not found.
        """
        match = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", text)
        if not match:
            return None
        try:
            data = json.loads(match.group(1))
            return data.get("strategy_updates")
        except (json.JSONDecodeError, AttributeError):
            return None
