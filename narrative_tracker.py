"""
narrative_tracker.py — Detect trending meme narratives from free data sources.

Three data streams, all free:

1. Self-learning scan stream
   Our scanner sees 70+ tokens per scan, ~4,200/hour.
   We track names/tickers of tokens passing thresholds in a rolling 2h window.
   Keyword clustering reveals which themes are hot right now.

2. DexScreener top boosts (free, no key)
   /token-boosts/top/v1 shows which Solana tokens devs are actively promoting.
   If multiple boosted tokens share a theme — that theme is heating up.

3. NewsAPI macro narrative detection (free tier, already have key)
   Repurposed from per-token sentiment to crypto category scanning.
   Detects broad narratives: AI, political, gaming, DeFi infrastructure, etc.

Output: NarrativeState updated every scan cycle, surfaced in every alert.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import aiohttp

from config import config

logger = logging.getLogger(__name__)

DEXSCREENER_BASE = "https://api.dexscreener.com"

# ── Narrative keyword taxonomy ─────────────────────────────────────────────────
# Maps theme name → list of keywords to match against token name/ticker/description
# Order matters — first match wins for primary category
NARRATIVE_KEYWORDS: dict[str, list[str]] = {
    "AI / Agents": [
        "ai", "agent", "gpt", "llm", "neural", "intelligence",
        "artificial", "openai", "claude", "gemini", "copilot",
        "robot", "bot", "machine", "deep",
    ],
    "Dogs": [
        "dog", "doge", "shib", "inu", "puppy", "woof", "bark",
        "hound", "pup", "canine", "retriever", "husky", "poodle",
        "dachshund", "bulldog", "labrador", "corgi", "shiba",
    ],
    "Cats": [
        "cat", "kitty", "meow", "neko", "purr", "kitten",
        "feline", "catcoin", "tabby", "persian",
    ],
    "Political / Trump": [
        "trump", "maga", "america", "usa", "president", "gop",
        "republican", "democrat", "election", "vote", "political",
        "congress", "white house", "patriot",
    ],
    "Elon / Tesla": [
        "elon", "musk", "tesla", "spacex", "mars", "doge",
        "x corp", "grok", "starship", "neuralink",
    ],
    "Pepe / Frogs": [
        "pepe", "frog", "rarpepe", "sadboi", "feels", "meme frog",
        "wojak", "chad", "npc",
    ],
    "Anime / Japan": [
        "anime", "waifu", "manga", "otaku", "kawaii", "sensei",
        "ninja", "samurai", "sakura", "tokyo", "japan",
    ],
    "Viral Animals": [
        "monkey", "ape", "bear", "bull", "fish", "shark",
        "whale", "bird", "penguin", "hamster", "rat", "pig",
        "cow", "horse", "lion", "tiger", "wolf", "fox",
        "rabbit", "duck", "owl", "crab",
    ],
    "Gaming": [
        "game", "gaming", "play", "rpg", "nft", "guild",
        "quest", "dungeon", "warrior", "legend", "clash",
        "pixel", "minecraft", "roblox", "fortnite",
    ],
    "DeFi / Finance": [
        "defi", "yield", "swap", "liquidity", "stake", "earn",
        "vault", "protocol", "finance", "lending", "borrow",
        "dao", "governance", "treasury",
    ],
    "Meme Culture": [
        "lol", "based", "gigachad", "ngmi", "wagmi", "gm",
        "lfg", "moon", "wen", "ser", "fren", "degen",
        "cope", "seethe", "touch grass",
    ],
}

# Macro crypto narrative keywords for NewsAPI scanning
MACRO_NARRATIVE_KEYWORDS: dict[str, list[str]] = {
    "AI narrative":        ["artificial intelligence", "ai agent", "chatgpt", "llm", "openai"],
    "Political narrative": ["trump crypto", "us crypto policy", "crypto regulation", "sec crypto"],
    "Memecoin season":     ["memecoin", "meme coin", "solana meme", "pump.fun", "bonding curve"],
    "DeFi narrative":      ["defi", "decentralized finance", "yield farming", "tvl"],
    "Institutional":       ["bitcoin etf", "institutional crypto", "blackrock", "grayscale"],
}


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class NarrativeTrend:
    name:       str           # e.g. "Dogs", "AI / Agents"
    count:      int           # tokens seen in this category in rolling window
    strength:   str           # "🔥 Hot", "📈 Rising", "💤 Cooling"
    examples:   list[str]     # up to 3 example token names/tickers
    source:     str           # "scan", "boosts", "news", "mixed"


@dataclass
class NarrativeState:
    top_trends:     list[NarrativeTrend] = field(default_factory=list)
    macro_signals:  list[str]            = field(default_factory=list)
    last_updated:   float                = 0.0
    total_tokens_seen: int               = 0

    def is_fresh(self, max_age_seconds: int = 120) -> bool:
        return (time.time() - self.last_updated) < max_age_seconds

    def top_narrative(self) -> Optional[str]:
        if self.top_trends:
            return self.top_trends[0].name
        return None

    def format_for_alert(self) -> str:
        """Short summary for inclusion in token alerts."""
        if not self.top_trends:
            return ""

        lines = ["🧠 <b>Market Narrative</b>"]
        for t in self.top_trends[:3]:
            ex = ", ".join(f"${e}" for e in t.examples[:2]) if t.examples else ""
            lines.append(
                f"  {t.strength} <b>{t.name}</b>"
                + (f" — e.g. {ex}" if ex else "")
            )

        if self.macro_signals:
            lines.append(f"  📰 Macro: {self.macro_signals[0]}")

        return "\n".join(lines)


# ── NarrativeTracker ──────────────────────────────────────────────────────────

class NarrativeTracker:
    """
    Tracks trending narratives from three free sources.
    Updated automatically on each scan cycle.
    """

    WINDOW_SECONDS = 7200   # 2-hour rolling window
    BOOST_INTERVAL = 900    # fetch DexScreener boosts every 15 min
    NEWS_INTERVAL  = 3600   # fetch NewsAPI macro narrative every hour

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self.state = NarrativeState()

        # Rolling window: deque of (timestamp, category, token_name, ticker)
        self._scan_events: collections.deque = collections.deque()

        # Boost fetch tracking
        self._last_boost_fetch: float = 0.0
        self._boost_categories: collections.Counter = collections.Counter()

        # NewsAPI macro narrative
        self._last_news_fetch: float = 0.0
        self._macro_signals: list[str] = []

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    # ── Keyword matching ───────────────────────────────────────────────────────

    def _categorize_token(self, name: str, ticker: str) -> Optional[str]:
        """Return the first matching narrative category for a token."""
        text = f"{name} {ticker}".lower()
        for category, keywords in NARRATIVE_KEYWORDS.items():
            for kw in keywords:
                if re.search(r'\b' + re.escape(kw) + r'\b', text):
                    return category
                # Also match partial for short tokens (e.g. "DOGE")
                if len(kw) >= 4 and kw in text:
                    return category
        return None

    # ── Source 1: Scan stream ──────────────────────────────────────────────────

    def record_token(self, name: str, ticker: str, passed: bool = True):
        """
        Called by the scanner for every token that passes thresholds.
        Adds to the rolling window for narrative detection.
        """
        if not passed:
            return
        category = self._categorize_token(name, ticker)
        if category:
            self._scan_events.append((time.time(), category, name, ticker))

    def _get_scan_counts(self) -> collections.Counter:
        """Return category counts from scan stream within rolling window."""
        cutoff = time.time() - self.WINDOW_SECONDS
        # Prune old events
        while self._scan_events and self._scan_events[0][0] < cutoff:
            self._scan_events.popleft()
        counts: collections.Counter = collections.Counter()
        examples: dict[str, list[str]] = {}
        for ts, cat, name, ticker in self._scan_events:
            counts[cat] += 1
            if cat not in examples:
                examples[cat] = []
            if ticker not in examples[cat] and len(examples[cat]) < 3:
                examples[cat].append(ticker)
        return counts, examples

    # ── Source 2: DexScreener boosts ──────────────────────────────────────────

    async def _fetch_boost_narratives(self):
        """
        Fetch top boosted tokens on DexScreener — free, no key needed.
        Tokens that devs are paying to boost reveal what themes they're betting on.
        """
        if time.time() - self._last_boost_fetch < self.BOOST_INTERVAL:
            return

        try:
            session = await self._get_session()
            url = f"{DEXSCREENER_BASE}/token-boosts/top/v1"
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return
                data = await resp.json(content_type=None)

            if not isinstance(data, list):
                return

            self._boost_categories.clear()
            for item in data:
                if item.get("chainId") != "solana":
                    continue
                desc     = item.get("description", "") or ""
                address  = item.get("tokenAddress", "")
                # Try to categorize from description
                category = None
                for cat, keywords in NARRATIVE_KEYWORDS.items():
                    for kw in keywords:
                        if kw in desc.lower():
                            category = cat
                            break
                    if category:
                        break
                if category:
                    self._boost_categories[category] += 1

            self._last_boost_fetch = time.time()
            if self._boost_categories:
                logger.info(
                    f"[Narrative] DexScreener boost categories: "
                    f"{dict(self._boost_categories.most_common(3))}"
                )

        except Exception as e:
            logger.debug(f"[Narrative] Boost fetch error: {e}")

    # ── Source 3: NewsAPI macro narratives ────────────────────────────────────

    async def _fetch_macro_narratives(self):
        """
        Use existing NewsAPI key to detect macro crypto narratives.
        Checks once per hour — stays well within 100 req/day limit.
        """
        if not config.has_news:
            return
        if time.time() - self._last_news_fetch < self.NEWS_INTERVAL:
            return

        try:
            session = await self._get_session()
            params = {
                "q": "solana OR memecoin OR crypto narrative",
                "sortBy": "publishedAt",
                "pageSize": 20,
                "language": "en",
                "apiKey": config.NEWS_API_KEY,
            }
            async with session.get(
                "https://newsapi.org/v2/everything",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return
                data = await resp.json(content_type=None)

            articles = data.get("articles", [])
            combined_text = " ".join(
                f"{a.get('title', '')} {a.get('description', '')}".lower()
                for a in articles
            )

            found_macros = []
            for signal_name, keywords in MACRO_NARRATIVE_KEYWORDS.items():
                hits = sum(1 for kw in keywords if kw in combined_text)
                if hits >= 2:
                    found_macros.append((hits, signal_name))

            found_macros.sort(reverse=True)
            self._macro_signals = [name for _, name in found_macros[:3]]
            self._last_news_fetch = time.time()

            if self._macro_signals:
                logger.info(
                    f"[Narrative] Macro signals detected: {self._macro_signals}"
                )

        except Exception as e:
            logger.debug(f"[Narrative] NewsAPI macro fetch error: {e}")

    # ── Main update cycle ──────────────────────────────────────────────────────

    async def update(self):
        """
        Called once per scan cycle. Refreshes narrative state from all sources.
        Fast — only does network calls when intervals expire.
        """
        # Fetch external sources (rate-limited internally)
        await asyncio.gather(
            self._fetch_boost_narratives(),
            self._fetch_macro_narratives(),
            return_exceptions=True,
        )

        # Build combined category scores
        scan_counts, scan_examples = self._get_scan_counts()

        # Merge scan + boost scores
        combined: collections.Counter = collections.Counter()
        combined.update(scan_counts)
        for cat, cnt in self._boost_categories.items():
            combined[cat] += cnt * 2  # boost signal weighted 2x

        if not combined:
            # No data yet — state stays empty
            self.state.last_updated = time.time()
            return

        # Classify trend strength
        max_count = max(combined.values()) if combined else 1
        trends = []
        for cat, count in combined.most_common(5):
            ratio = count / max_count
            if ratio >= 0.7:
                strength = "🔥 Hot"
            elif ratio >= 0.4:
                strength = "📈 Rising"
            else:
                strength = "💤 Fading"

            examples = scan_examples.get(cat, [])[:3]

            trends.append(NarrativeTrend(
                name=cat,
                count=count,
                strength=strength,
                examples=examples,
                source="mixed" if cat in self._boost_categories else "scan",
            ))

        self.state.top_trends    = trends
        self.state.macro_signals = self._macro_signals.copy()
        self.state.last_updated  = time.time()
        self.state.total_tokens_seen = len(self._scan_events)

        logger.debug(
            f"[Narrative] State updated — top: "
            + ", ".join(f"{t.name}({t.count})" for t in trends[:3])
        )

    def get_token_narrative_fit(
        self, name: str, ticker: str
    ) -> tuple[bool, str]:
        """
        Check if a specific token fits the current top narrative.
        Returns (fits_narrative, description)
        """
        if not self.state.top_trends:
            return False, ""

        category = self._categorize_token(name, ticker)
        if not category:
            return False, ""

        top_names = [t.name for t in self.state.top_trends[:2]]
        if category in top_names:
            trend = next(t for t in self.state.top_trends if t.name == category)
            return True, (
                f"Fits trending narrative: {category} ({trend.strength})"
            )

        return False, f"Category: {category} (not currently trending)"


# Module-level singleton
narrative_tracker = NarrativeTracker()
