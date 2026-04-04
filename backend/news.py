"""
News aggregator — fetches financial news via:
  1. Yahoo Finance (yfinance — always available, real news + URLs, no key needed)
  2. Mock data    (last resort if yfinance unavailable)
"""
import logging
import random
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    logger.warning("yfinance not installed — pip install yfinance")


class NewsAggregator:
    def __init__(self):
        if YFINANCE_AVAILABLE:
            logger.info("News: Yahoo Finance (yfinance)")
        else:
            logger.warning("News: mock data only")

    @property
    def demo(self) -> bool:
        return not YFINANCE_AVAILABLE

    def get_news(self, symbols: list[str], limit: int = 40) -> list[dict]:
        if not symbols:
            return []
        if YFINANCE_AVAILABLE:
            return self._yfinance_news(symbols, limit)
        return self._mock_news(symbols)

    # ------------------------------------------------------------------ #
    # Yahoo Finance (yfinance)                                             #
    # ------------------------------------------------------------------ #

    def _yfinance_news(self, symbols: list[str], limit: int) -> list[dict]:
        # Keyed by article uid so duplicates accumulate symbol tags instead of being dropped
        articles_by_id: dict[str, dict] = {}
        per_sym = max(10, limit // max(len(symbols), 1))

        for sym in symbols:
            try:
                items = yf.Ticker(sym).news or []
                for item in items[:per_sym]:
                    # yfinance >= 0.2.50 wraps everything under item['content']
                    c   = item.get("content") or item
                    uid = item.get("id") or c.get("id") or c.get("uuid", "")
                    if not uid:
                        continue

                    if uid in articles_by_id:
                        # Article already seen from another symbol — just add this symbol tag
                        if sym not in articles_by_id[uid]["symbols"]:
                            articles_by_id[uid]["symbols"].append(sym)
                        continue

                    # URL: prefer canonical (direct to source), fall back to clickThrough
                    canonical = (c.get("canonicalUrl") or {}).get("url", "")
                    clickthru = (c.get("clickThroughUrl") or {}).get("url", "")
                    url = canonical or clickthru or c.get("link", "")

                    # Published date
                    pub_raw = c.get("pubDate") or c.get("displayTime", "")
                    try:
                        pub_dt = datetime.fromisoformat(pub_raw.replace("Z", "+00:00"))
                    except (ValueError, AttributeError):
                        pub_ts = c.get("providerPublishTime", 0)
                        try:
                            pub_dt = datetime.fromtimestamp(int(pub_ts), tz=timezone.utc)
                        except (TypeError, ValueError, OSError):
                            pub_dt = datetime.now(timezone.utc)

                    source = (c.get("provider") or {}).get("displayName") or c.get("publisher", "")

                    articles_by_id[uid] = {
                        "id":           uid,
                        "headline":     c.get("title") or "",
                        "summary":      c.get("summary") or c.get("description") or "",
                        "author":       "",
                        "source":       source,
                        "url":          url,
                        "symbols":      [sym],
                        "published_at": pub_dt.isoformat(),
                    }
            except Exception as e:
                logger.error(f"yfinance news error for {sym}: {e}")

        articles = sorted(articles_by_id.values(), key=lambda a: a["published_at"], reverse=True)
        return articles[:limit]

    # ------------------------------------------------------------------ #
    # Mock (last resort)                                                   #
    # ------------------------------------------------------------------ #

    def _mock_news(self, symbols: list[str]) -> list[dict]:
        templates = [
            ("{sym} Q{q} earnings beat estimates; EPS ${eps:.2f} vs ${est:.2f} expected",
             "{sym} reported Q{q} earnings of ${eps:.2f} per share, topping analyst expectations of ${est:.2f}. Revenue also beat, driven by strong demand and margin expansion across key segments."),
            ("Analysts raise {sym} price target to ${pt} following strong guidance",
             "Multiple Wall Street firms raised their price targets on {sym} after the company issued upbeat forward guidance, citing robust demand, improving margins, and continued market share gains."),
            ("{sym} completes ${deal}B acquisition to expand into {market}",
             "{sym} closed its ${deal}B deal targeting the {market} space. Management called the acquisition immediately accretive and said it accelerates the company's long-term growth strategy."),
            ("{sym} under regulatory scrutiny over {topic}; shares slide",
             "Regulators announced an inquiry into {sym}'s {topic} practices. The company said it is cooperating fully and does not expect any material financial impact from the investigation."),
            ("{sym} COO departure announced; leadership transition underway",
             "{sym} confirmed its COO will step down at month-end. The board named an interim leader while conducting a permanent executive search."),
            ("{sym} new product launch receives strong early demand signals",
             "{sym} unveiled its latest product lineup. Early reviews and pre-order data suggest demand is exceeding internal targets, according to sources with knowledge of supply chain projections."),
            ("{sym} cuts full-year outlook citing supply chain headwinds",
             "{sym} trimmed its full-year revenue guidance by 3-5%, pointing to supply chain disruptions. Management expects normalization by year-end but flagged ongoing risks."),
            ("{sym} board extends buyback by $2B; dividend raised 8%",
             "The board of {sym} approved a $2B expansion of its share repurchase program and raised the quarterly dividend by 8%, signaling confidence in the company's near-term cash flow outlook."),
        ]
        markets = ["enterprise AI", "cloud infrastructure", "Southeast Asia", "clean energy"]
        topics  = ["data privacy", "antitrust", "labor practices", "export compliance"]
        now     = datetime.now(timezone.utc)
        articles = []
        idx = 0
        per = max(3, 20 // max(len(symbols), 1))
        for sym in symbols:
            rng = random.Random(sum(ord(c) for c in sym) + 7)
            for _ in range(per):
                th, ts = rng.choice(templates)
                hrs    = rng.randint(1, 120)
                q      = rng.randint(1, 4)
                eps    = round(rng.uniform(1.5, 6.0), 2)
                est    = round(eps - rng.uniform(0.05, 0.4), 2)
                pt     = rng.randint(120, 700)
                deal   = round(rng.uniform(0.5, 20), 1)
                market = rng.choice(markets)
                topic  = rng.choice(topics)
                fmt    = dict(sym=sym, q=q, eps=eps, est=est, pt=pt, deal=deal, market=market, topic=topic)
                articles.append({
                    "id":           f"mock-{idx}",
                    "headline":     th.format(**fmt),
                    "summary":      ts.format(**fmt),
                    "author":       "",
                    "source":       rng.choice(["Reuters", "Bloomberg", "Benzinga", "MarketWatch"]),
                    "url":          "",
                    "symbols":      [sym],
                    "published_at": (now - timedelta(hours=hrs)).isoformat(),
                })
                idx += 1
        articles.sort(key=lambda a: a["published_at"], reverse=True)
        return articles
