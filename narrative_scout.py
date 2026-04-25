"""
narrative_scout.py — Narrative-first token discovery.

Current scanner flow (reactive):
    find token → check if it fits a narrative → alert

New flow (proactive):
    detect hot narrative on X RIGHT NOW
    → search pump.fun/DexScreener for matching tokens
    → surface them before they build volume

Why this matters:
    By the time a token passes the scanner's financial thresholds
    (volume, liquidity, market cap), early entry is already gone.
    Finding it because the STORY is hot gets you in before the chart proves it.

Two discovery paths:
    1. Grok X search (if XAI_API_KEY set)
       Asks what crypto narratives are trending on X right now → keywords
       → hunts pump.fun for matching tokens

    2. NewsAPI + narrative_tracker fallback (no Grok needed)
       Uses existing macro narrative signals and top narrative_tracker themes
       → same keyword-based hunt

Tokens found here:
    - Get a "narrative_match" flag so the bot knows why they were surfaced
    - Bypass the social gate if under 20 minutes old (too young to have CT posts yet)
    - Still go through full safety + sentiment pipeline before alerting
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from config import config

logger = logging.getLogger(__name__)

PUMPFUN_BASE     = "https://frontend-api.pump.fun"
DEXSCREENER_BASE = "https://api.dexscreener.com"
XAI_BASE         = "https://api.x.ai/v1"

# How often to refresh narrative detection (seconds)
NARRATIVE_REFRESH_INTERVAL = 900   # 15 minutes — Grok costs money, don't over-call

# Age cutoff for narrative-found tokens — we specifically want very early
NARRATIVE_MAX_AGE_HOURS = 3.0

# Bonding curve sweet spot for narrative tokens
NARRATIVE_MIN_BONDING = 10.0   # at least 10% in — some real buying happened
NARRATIVE_MAX_BONDING = 97.0   # not about to graduate (price already moved)


# ── Data models ─────────────────────────────────────────────────────────────────

@dataclass
class NarrativeTheme:
    theme:    str          # "AI agents", "Dog memes", "Political"
    keywords: list[str]    # ["ai", "agent", "gpt"] — search terms
    heat:     str          # "hot", "rising", "cooling"
    source:   str          # "grok", "newsapi", "tracker"
    found_at: float = field(default_factory=time.time)


@dataclass
class NarrativeCandidate:
    """A token surfaced because it matched a hot narrative."""
    mint:              str
    name:              str
    symbol:            str
    pool_address:      str
    dex:               str
    market_cap_usd:    float
    liquidity_usd:     float
    bonding_progress:  float
    age_hours:         float
    launched_at:       Optional[datetime]
    matched_theme:     str          # which narrative triggered discovery
    matched_keyword:   str          # exact keyword that matched
    narrative_heat:    str          # "hot" / "rising" / "cooling"
    is_very_young:     bool         # under 20 minutes — bypass social gate
    source:            str = "narrative_scout"

    # These get filled in by scout.py when converting to TokenOpportunity
    price_usd:         float = 0.0
    volume_24h_usd:    float = 0.0
    volume_6h_usd:     float = 0.0
    volume_1h_usd:     float = 0.0
    price_change_1h:   float = 0.0
    price_change_6h:   float = 0.0
    price_change_24h:  float = 0.0


# ── NarrativeScout ─────────────────────────────────────────────────────────────

class NarrativeScout:
    """
    Runs narrative detection and token hunting.
    Called from TokenScout.scan_for_opportunities() alongside other sources.
    """

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._last_narrative_fetch: float = 0.0
        self._cached_themes:        list[NarrativeTheme] = []
        self._seen_mints:           set[str] = set()   # dedup within session

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    # ── Narrative detection ────────────────────────────────────────────────────

    async def _fetch_themes_grok(self) -> list[NarrativeTheme]:
        """
        Ask Grok what's trending on X crypto right now.
        Returns narrative themes with keywords to search for.
        """
        if not config.has_grok:
            return []

        session = await self._get_session()
        prompt = (
            "Search X crypto posts from the last 2 hours. "
            "What are the top 5 trending meme/narrative themes for Solana tokens right now? "
            "Examples: AI agents, dog coins, political events, viral animals, gaming, DeFi. "
            "Return ONLY valid JSON, no explanation, no markdown:\n"
            '{"narratives": ['
            '{"theme": "string", "keywords": ["word1", "word2", "word3"], '
            '"heat": "hot|rising|cooling"}'
            "]}"
        )

        try:
            headers = {
                "Authorization": f"Bearer {config.XAI_API_KEY}",
                "Content-Type":  "application/json",
            }
            payload = {
                "model": "grok-3-fast",
                "messages": [{"role": "user", "content": prompt}],
                "search_parameters": {
                    "mode": "on",
                    "sources": [{"type": "x"}],
                },
                "temperature": 0,
                "max_tokens":  500,
            }
            async with session.post(
                f"{XAI_BASE}/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    logger.debug(f"[NarrativeScout] Grok status {resp.status}")
                    return []
                data    = await resp.json(content_type=None)
                content = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )

                # Strip markdown fences if present
                content = content.strip()
                if content.startswith("```"):
                    lines   = content.splitlines()
                    content = "\n".join(
                        l for l in lines
                        if not l.startswith("```")
                    ).strip()

                parsed     = json.loads(content)
                narratives = parsed.get("narratives", [])

                themes = []
                for n in narratives[:5]:
                    theme    = str(n.get("theme", ""))
                    keywords = [str(k).lower() for k in n.get("keywords", [])][:5]
                    heat     = str(n.get("heat", "rising"))
                    if theme and keywords:
                        themes.append(NarrativeTheme(
                            theme=theme, keywords=keywords,
                            heat=heat, source="grok"
                        ))

                logger.info(
                    f"[NarrativeScout] Grok found {len(themes)} themes: "
                    + ", ".join(f"{t.theme}({t.heat})" for t in themes)
                )
                return themes

        except json.JSONDecodeError as e:
            logger.debug(f"[NarrativeScout] Grok JSON error: {e}")
            return []
        except Exception as e:
            logger.warning(f"[NarrativeScout] Grok error: {e}")
            return []

    def _fetch_themes_fallback(self) -> list[NarrativeTheme]:
        """
        Fallback when Grok is unavailable.
        Uses narrative_tracker's current top trends + NewsAPI macro signals.
        """
        try:
            from narrative_tracker import narrative_tracker
            from narrative_tracker import NARRATIVE_KEYWORDS

            themes = []

            # Use top trends from the existing tracker
            for trend in narrative_tracker.state.top_trends[:5]:
                keywords = NARRATIVE_KEYWORDS.get(trend.name, [])[:5]
                if keywords:
                    heat = (
                        "hot"    if "Hot"    in trend.strength else
                        "rising" if "Rising" in trend.strength else
                        "cooling"
                    )
                    themes.append(NarrativeTheme(
                        theme=trend.name,
                        keywords=keywords,
                        heat=heat,
                        source="tracker",
                    ))

            # Add macro signals from NewsAPI as extra themes
            for macro in narrative_tracker.state.macro_signals[:2]:
                # Extract keywords from macro signal name
                words = macro.lower().replace("narrative", "").split()
                kws   = [w for w in words if len(w) > 3]
                if kws:
                    themes.append(NarrativeTheme(
                        theme=macro,
                        keywords=kws[:4],
                        heat="rising",
                        source="newsapi",
                    ))

            logger.info(
                f"[NarrativeScout] Fallback: {len(themes)} themes from tracker"
            )
            return themes

        except Exception as e:
            logger.warning(f"[NarrativeScout] Fallback error: {e}")
            return []

    async def _refresh_themes_if_needed(self) -> list[NarrativeTheme]:
        """Refresh narrative themes at the configured interval."""
        now = time.time()
        if (now - self._last_narrative_fetch) < NARRATIVE_REFRESH_INTERVAL:
            return self._cached_themes

        # Try Grok first, fall back to tracker
        if config.has_grok:
            themes = await self._fetch_themes_grok()
        else:
            themes = []

        if not themes:
            themes = self._fetch_themes_fallback()

        if themes:
            self._cached_themes      = themes
            self._last_narrative_fetch = now

        return self._cached_themes

    # ── Token hunting ──────────────────────────────────────────────────────────

    async def _search_pumpfun_for_keyword(
        self, keyword: str, theme: NarrativeTheme
    ) -> list[NarrativeCandidate]:
        """
        Search pump.fun for tokens matching a narrative keyword.
        Uses the 'searchTerm' param on the pump.fun coins endpoint.
        """
        session  = await self._get_session()
        results  = []

        try:
            async with session.get(
                f"{PUMPFUN_BASE}/coins",
                params={
                    "searchTerm": keyword,
                    "sort":       "created_timestamp",
                    "order":      "DESC",
                    "limit":      30,
                    "includeNsfw": "false",
                },
                headers={
                    "Accept":     "application/json",
                    "User-Agent": "Mozilla/5.0 (compatible; SolanaBot/1.0)",
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 530:
                    logger.debug(f"[NarrativeScout] PumpFun rate limited for '{keyword}'")
                    return []
                if resp.status != 200:
                    return []
                coins = await resp.json(content_type=None)
                if not isinstance(coins, list):
                    return []

            now = datetime.now(timezone.utc)

            for coin in coins:
                mint = coin.get("mint", "")
                if not mint or mint in self._seen_mints:
                    continue

                # Skip graduated tokens — we want bonding curve plays
                if coin.get("complete") or coin.get("raydium_pool"):
                    continue

                bonding = float(
                    coin.get("bonding_curve_progress") or
                    coin.get("progress") or 0
                )

                # Filter bonding range
                if bonding < NARRATIVE_MIN_BONDING or bonding > NARRATIVE_MAX_BONDING:
                    continue

                # Age calculation
                created_ts = coin.get("created_timestamp", 0)
                if created_ts > 1e12:
                    created_ts /= 1000

                created_at = None
                age_hours  = 9999.0
                if created_ts:
                    try:
                        created_at = datetime.fromtimestamp(created_ts, tz=timezone.utc)
                        age_hours  = (now - created_at).total_seconds() / 3600
                    except Exception:
                        pass

                if age_hours > NARRATIVE_MAX_AGE_HOURS:
                    continue

                usd_mcap = float(coin.get("usd_market_cap") or 0)

                # Very early tokens may not have mcap yet — allow them through
                # with a lower floor since that's the whole point
                if usd_mcap > config.MAX_MARKET_CAP_USD:
                    continue

                is_very_young = age_hours < (20 / 60)   # under 20 minutes

                virtual_sol   = coin.get("virtual_sol_reserves", 0) / 1e9
                est_liquidity = max(virtual_sol * 150, usd_mcap * 0.25)

                self._seen_mints.add(mint)
                results.append(NarrativeCandidate(
                    mint             = mint,
                    name             = coin.get("name", "Unknown"),
                    symbol           = coin.get("symbol", "???"),
                    pool_address     = coin.get("bonding_curve", ""),
                    dex              = "pump.fun",
                    market_cap_usd   = usd_mcap,
                    liquidity_usd    = est_liquidity,
                    bonding_progress = bonding,
                    age_hours        = age_hours,
                    launched_at      = created_at,
                    matched_theme    = theme.theme,
                    matched_keyword  = keyword,
                    narrative_heat   = theme.heat,
                    is_very_young    = is_very_young,
                ))

        except Exception as e:
            logger.debug(f"[NarrativeScout] Pump.fun search error for '{keyword}': {e}")

        return results

    async def _search_dexscreener_for_keyword(
        self, keyword: str, theme: NarrativeTheme
    ) -> list[NarrativeCandidate]:
        """
        Search DexScreener for recently created Solana pairs matching a keyword.
        Catches tokens that have already graduated from pump.fun.
        """
        session = await self._get_session()
        results = []

        try:
            url = f"{DEXSCREENER_BASE}/latest/dex/search/?q={keyword}"
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=12)
            ) as resp:
                if resp.status != 200:
                    return []
                data  = await resp.json(content_type=None)
                pairs = data.get("pairs") or []

            now = datetime.now(timezone.utc)

            for pair in pairs:
                if pair.get("chainId", "").lower() != "solana":
                    continue

                base = pair.get("baseToken", {})
                mint = base.get("address", "")
                if not mint or mint in self._seen_mints:
                    continue

                # Parse age
                pair_created = pair.get("pairCreatedAt")
                created_at   = None
                age_hours    = 9999.0
                if pair_created:
                    try:
                        ts         = int(pair_created) / 1000
                        created_at = datetime.fromtimestamp(ts, tz=timezone.utc)
                        age_hours  = (now - created_at).total_seconds() / 3600
                    except Exception:
                        pass

                if age_hours > NARRATIVE_MAX_AGE_HOURS:
                    continue

                liq  = float((pair.get("liquidity") or {}).get("usd") or 0)
                mcap = float(pair.get("marketCap") or pair.get("fdv") or 0)
                vol  = (pair.get("volume") or {})

                if mcap > config.MAX_MARKET_CAP_USD:
                    continue

                is_very_young = age_hours < (20 / 60)

                self._seen_mints.add(mint)
                results.append(NarrativeCandidate(
                    mint             = mint,
                    name             = base.get("name", "Unknown"),
                    symbol           = base.get("symbol", "???"),
                    pool_address     = pair.get("pairAddress", ""),
                    dex              = pair.get("dexId", "unknown"),
                    market_cap_usd   = mcap,
                    liquidity_usd    = liq,
                    bonding_progress = 0.0,
                    age_hours        = age_hours,
                    launched_at      = created_at,
                    matched_theme    = theme.theme,
                    matched_keyword  = keyword,
                    narrative_heat   = theme.heat,
                    is_very_young    = is_very_young,
                    price_usd        = float(pair.get("priceUsd") or 0),
                    volume_24h_usd   = float(vol.get("h24") or 0),
                    volume_6h_usd    = float(vol.get("h6") or 0),
                    volume_1h_usd    = float(vol.get("h1") or 0),
                    price_change_1h  = float((pair.get("priceChange") or {}).get("h1") or 0),
                    price_change_6h  = float((pair.get("priceChange") or {}).get("h6") or 0),
                    price_change_24h = float((pair.get("priceChange") or {}).get("h24") or 0),
                ))

        except Exception as e:
            logger.debug(f"[NarrativeScout] DexScreener search error for '{keyword}': {e}")

        return results

    # ── Main scan ──────────────────────────────────────────────────────────────

    async def scan(self) -> list[NarrativeCandidate]:
        """
        Main entry point. Called from TokenScout.scan_for_opportunities().
        Returns narrative-matched token candidates.
        """
        themes = await self._refresh_themes_if_needed()

        if not themes:
            logger.debug("[NarrativeScout] No themes available, skipping")
            return []

        # Reset seen set each scan cycle
        self._seen_mints.clear()

        all_candidates: list[NarrativeCandidate] = []

        # Search each theme's top keywords
        # Prioritise hot themes and limit API calls
        for theme in sorted(themes, key=lambda t: 0 if t.heat == "hot" else 1):
            keywords_to_search = theme.keywords[:3]   # top 3 keywords per theme

            tasks = []
            for kw in keywords_to_search:
                tasks.append(self._search_pumpfun_for_keyword(kw, theme))
                tasks.append(self._search_dexscreener_for_keyword(kw, theme))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, list):
                    all_candidates.extend(r)

            await asyncio.sleep(0.3)   # gentle between themes

        # Deduplicate by mint (keep first occurrence — highest priority theme)
        seen: set[str] = set()
        deduped = []
        for c in all_candidates:
            if c.mint not in seen:
                seen.add(c.mint)
                deduped.append(c)

        # Sort: hot narratives first, younger tokens first within same heat
        deduped.sort(
            key=lambda c: (
                0 if c.narrative_heat == "hot" else
                1 if c.narrative_heat == "rising" else 2,
                c.age_hours,
            )
        )

        logger.info(
            f"[NarrativeScout] Found {len(deduped)} narrative candidates "
            f"across {len(themes)} themes"
        )
        if deduped:
            themes_found = set(c.matched_theme for c in deduped)
            logger.info(f"[NarrativeScout] Themes with hits: {themes_found}")

        return deduped[:20]   # cap at 20 per cycle

    def get_current_themes_summary(self) -> str:
        """For /scan status messages."""
        if not self._cached_themes:
            return "No narrative data yet"
        hot = [t.theme for t in self._cached_themes if t.heat == "hot"]
        rising = [t.theme for t in self._cached_themes if t.heat == "rising"]
        parts = []
        if hot:
            parts.append(f"🔥 {', '.join(hot)}")
        if rising:
            parts.append(f"📈 {', '.join(rising)}")
        source = self._cached_themes[0].source if self._cached_themes else "?"
        return " · ".join(parts) + f" (via {source})"


# Module-level singleton
narrative_scout = NarrativeScout()
