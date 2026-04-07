"""
scout.py — Token scouting layer.

Primary source:  GeckoTerminal (free, no key needed)  → new Solana pools
Secondary:       DexScreener (free, no key needed)    → detailed pair data
Tertiary:        Birdeye (API key needed for full data)

Tokens are filtered against ALL configured thresholds before being returned.
If a token doesn't meet MIN_LIQUIDITY_USD or MIN_VOLUME_24H_USD it is silently
dropped — it never reaches the sentiment or briefing layers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from config import config

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

GECKOTERMINAL_BASE = "https://api.geckoterminal.com/api/v2"
DEXSCREENER_BASE = "https://api.dexscreener.com"
BIRDEYE_BASE = "https://public-api.birdeye.so"

# Wrapped SOL mint address
WSOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Known rug/honeypot indicator: these are burn addresses / known bad actors
BURN_ADDRESSES = {
    "1nc1nerator11111111111111111111111111111111",
    "So11111111111111111111111111111111111111112",  # wsol itself isn't a token
}

HEADERS_GT = {
    "Accept": "application/json;version=20230302",
}

HEADERS_BIRDEYE = {
    "X-API-KEY": config.BIRDEYE_API_KEY,
    "x-chain": "solana",
}

# ─── Data model ───────────────────────────────────────────────────────────────


@dataclass
class TokenOpportunity:
    mint: str
    name: str
    symbol: str
    pool_address: str
    dex: str

    price_usd: float
    market_cap_usd: float
    fdv_usd: float
    liquidity_usd: float
    volume_24h_usd: float
    volume_6h_usd: float
    volume_1h_usd: float

    price_change_1h: float
    price_change_6h: float
    price_change_24h: float

    launched_at: Optional[datetime]
    age_hours: float

    # populated by safety checker later
    safety_passed: Optional[bool] = None
    safety_detail: str = ""

    # populated by sentiment analyzer later
    sentiment_label: str = ""        # Bullish / Neutral / Bearish
    sentiment_score: float = 0.0     # -1 to 1
    sentiment_summary: str = ""
    tweet_count: int = 0
    top_tweet_signal: str = ""
    news_summary: str = ""
    reddit_summary: str = ""

    # overall confidence 1-10 set by briefing builder
    confidence: int = 0
    confidence_rationale: str = ""

    # data-only flag: set when chart is strong but social signal is weak
    data_only_call: bool = False
    data_only_reason: str = ""

    # internal: track when we first saw this token so we don't re-alert
    first_seen: float = field(default_factory=time.time)

    @property
    def age_str(self) -> str:
        if self.age_hours < 1:
            return f"{int(self.age_hours * 60)}m old"
        return f"{self.age_hours:.1f}h old"

    @property
    def price_action_summary(self) -> str:
        lines = []
        if self.price_change_1h:
            sign = "+" if self.price_change_1h > 0 else ""
            lines.append(f"{sign}{self.price_change_1h:.1f}% (1h)")
        if self.price_change_6h:
            sign = "+" if self.price_change_6h > 0 else ""
            lines.append(f"{sign}{self.price_change_6h:.1f}% (6h)")
        if self.price_change_24h:
            sign = "+" if self.price_change_24h > 0 else ""
            lines.append(f"{sign}{self.price_change_24h:.1f}% (24h)")
        return "  |  ".join(lines) if lines else "no data"


# ─── HTTP helpers ──────────────────────────────────────────────────────────────


async def _get_json(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict | None = None,
    params: dict | None = None,
    retries: int = 3,
    backoff: float = 2.0,
) -> dict | list | None:
    """GET JSON with exponential backoff on 429/5xx."""
    attempt = 0
    while attempt < retries:
        try:
            async with session.get(
                url, headers=headers or {}, params=params, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 429:
                    wait = backoff ** attempt
                    logger.warning(f"Rate limited on {url}, waiting {wait}s")
                    await asyncio.sleep(wait)
                    attempt += 1
                    continue
                if resp.status >= 500:
                    wait = backoff ** attempt
                    logger.warning(f"Server error {resp.status} on {url}, retry in {wait}s")
                    await asyncio.sleep(wait)
                    attempt += 1
                    continue
                if resp.status == 200:
                    return await resp.json(content_type=None)
                logger.warning(f"HTTP {resp.status} for {url}")
                return None
        except asyncio.TimeoutError:
            logger.warning(f"Timeout on {url} (attempt {attempt + 1}/{retries})")
            attempt += 1
            await asyncio.sleep(backoff ** attempt)
        except aiohttp.ClientError as e:
            logger.warning(f"Client error on {url}: {e}")
            attempt += 1
            await asyncio.sleep(backoff)
    return None


# ─── Scout class ──────────────────────────────────────────────────────────────


class TokenScout:
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._seen_mints: dict[str, float] = {}  # mint -> last_alerted timestamp

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Source 1: GeckoTerminal new pools ─────────────────────────────────────

    async def _fetch_gecko_new_pools(self) -> list[dict]:
        """
        Fetch the most recently created Solana pools from GeckoTerminal.
        Returns raw pool dicts with base_token info included.
        Free, no API key required.
        """
        session = await self._get_session()
        pools = []

        for page in range(1, 4):  # pages 1-3, ~60 pools total
            url = f"{GECKOTERMINAL_BASE}/networks/solana/new_pools"
            params = {"include": "base_token,dex", "page": page}
            data = await _get_json(session, url, headers=HEADERS_GT, params=params)
            if not data:
                break

            raw_pools = data.get("data", [])
            included = {
                item["id"]: item
                for item in data.get("included", [])
                if item.get("type") in ("token", "dex")
            }

            for pool in raw_pools:
                try:
                    attrs = pool.get("attributes", {})
                    rels = pool.get("relationships", {})

                    # Resolve base token
                    base_token_ref = rels.get("base_token", {}).get("data", {})
                    base_id = base_token_ref.get("id", "")
                    base_token = included.get(base_id, {}).get("attributes", {})

                    # Resolve DEX name
                    dex_ref = rels.get("dex", {}).get("data", {})
                    dex_obj = included.get(dex_ref.get("id", ""), {})
                    dex_name = dex_obj.get("attributes", {}).get("name", "unknown")

                    mint = base_token.get("address", "")
                    if not mint or mint in BURN_ADDRESSES:
                        continue

                    # Parse volume
                    volume_usd = attrs.get("volume_usd", {})
                    # Parse price changes
                    price_pct = attrs.get("price_change_percentage", {})
                    # Parse pool created time
                    created_at_str = attrs.get("pool_created_at")
                    created_at = None
                    age_hours = 9999.0
                    if created_at_str:
                        try:
                            created_at = datetime.fromisoformat(
                                created_at_str.replace("Z", "+00:00")
                            )
                            age_hours = (
                                datetime.now(timezone.utc) - created_at
                            ).total_seconds() / 3600
                        except Exception:
                            pass

                    pools.append(
                        {
                            "mint": mint,
                            "name": base_token.get("name", "Unknown"),
                            "symbol": base_token.get("symbol", "???"),
                            "pool_address": attrs.get("address", ""),
                            "dex": dex_name,
                            "price_usd": float(attrs.get("base_token_price_usd") or 0),
                            "market_cap_usd": float(attrs.get("market_cap_usd") or attrs.get("fdv_usd") or 0),
                            "fdv_usd": float(attrs.get("fdv_usd") or 0),
                            "liquidity_usd": float(attrs.get("reserve_in_usd") or 0),
                            "volume_24h_usd": float(volume_usd.get("h24") or 0),
                            "volume_6h_usd": float(volume_usd.get("h6") or 0),
                            "volume_1h_usd": float(volume_usd.get("h1") or 0),
                            "price_change_1h": float(price_pct.get("h1") or 0),
                            "price_change_6h": float(price_pct.get("h6") or 0),
                            "price_change_24h": float(price_pct.get("h24") or 0),
                            "launched_at": created_at,
                            "age_hours": age_hours,
                        }
                    )
                except Exception as e:
                    logger.debug(f"Error parsing GT pool: {e}")
                    continue

            await asyncio.sleep(0.5)  # be polite to GT

        logger.info(f"[Scout] GeckoTerminal returned {len(pools)} raw pools")
        return pools

    # ── Source 2: DexScreener new pairs on PumpSwap / Meteora ─────────────────

    async def _fetch_dexscreener_trending(self) -> list[dict]:
        """
        Fetch NEW pairs from PumpSwap, Meteora, Orca and Raydium via DexScreener.
        Catches tokens early — before they trend — by watching DEX-specific new pair feeds.
        Free, no key needed.
        """
        session = await self._get_session()
        results = []

        dex_targets = ["pump-fun", "meteora", "meteora-dlmm", "orca", "raydium"]

        for dex_id in dex_targets:
            url = f"{DEXSCREENER_BASE}/latest/dex/search"
            params = {"q": f"SOL {dex_id}"}
            data = await _get_json(session, url, params=params)
            if not data:
                continue

            pairs = data.get("pairs") or []

            # Only Solana pairs from our target DEXes
            solana_pairs = [
                p for p in pairs
                if p.get("chainId", "").lower() == "solana"
                and p.get("dexId", "").lower() in dex_targets
            ]

            # Sort by creation time — newest first
            solana_pairs.sort(
                key=lambda p: int(p.get("pairCreatedAt") or 0),
                reverse=True
            )

            for pair in solana_pairs[:15]:  # top 15 newest per DEX
                parsed = self._parse_dexscreener_pair(pair)
                if parsed:
                    results.append(parsed)

            await asyncio.sleep(0.3)  # be polite to DexScreener

        logger.info(f"[Scout] DexScreener new pairs returned {len(results)} pairs")
        return results

    async def fetch_token_details_dexscreener(self, mint: str) -> dict | None:
        """Fetch current data for a specific mint from DexScreener."""
        session = await self._get_session()
        url = f"{DEXSCREENER_BASE}/latest/dex/tokens/{mint}"
        data = await _get_json(session, url)
        if not data:
            return None
        pairs = data.get("pairs") or []
        if not pairs:
            return None
        # Return the pair with highest liquidity
        pairs.sort(key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0), reverse=True)
        return self._parse_dexscreener_pair(pairs[0])

    def _parse_dexscreener_pair(self, pair: dict) -> dict | None:
        try:
            base = pair.get("baseToken", {})
            mint = base.get("address", "")
            if not mint:
                return None

            liquidity = pair.get("liquidity") or {}
            volume = pair.get("volume") or {}
            price_change = pair.get("priceChange") or {}

            created_at = None
            age_hours = 9999.0
            pair_created_at = pair.get("pairCreatedAt")
            if pair_created_at:
                try:
                    ts = int(pair_created_at) / 1000  # ms -> s
                    created_at = datetime.fromtimestamp(ts, tz=timezone.utc)
                    age_hours = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600
                except Exception:
                    pass

            return {
                "mint": mint,
                "name": base.get("name", "Unknown"),
                "symbol": base.get("symbol", "???"),
                "pool_address": pair.get("pairAddress", ""),
                "dex": pair.get("dexId", "unknown"),
                "price_usd": float(pair.get("priceUsd") or 0),
                "market_cap_usd": float(pair.get("marketCap") or pair.get("fdv") or 0),
                "fdv_usd": float(pair.get("fdv") or 0),
                "liquidity_usd": float(liquidity.get("usd") or 0),
                "volume_24h_usd": float(volume.get("h24") or 0),
                "volume_6h_usd": float(volume.get("h6") or 0),
                "volume_1h_usd": float(volume.get("h1") or 0),
                "price_change_1h": float(price_change.get("h1") or 0),
                "price_change_6h": float(price_change.get("h6") or 0),
                "price_change_24h": float(price_change.get("h24") or 0),
                "launched_at": created_at,
                "age_hours": age_hours,
            }
        except Exception as e:
            logger.debug(f"Error parsing DexScreener pair: {e}")
            return None

    # ── Source 3: Birdeye trending (if API key set) ────────────────────────────

    async def _fetch_birdeye_trending(self) -> list[dict]:
        if not config.has_birdeye:
            return []

        session = await self._get_session()
        url = f"{BIRDEYE_BASE}/defi/tokenlist"
        params = {
            "sort_by": "v24hChangePercent",
            "sort_type": "desc",
            "offset": 0,
            "limit": 50,
            "min_liquidity": config.MIN_LIQUIDITY_USD,
        }
        data = await _get_json(session, url, headers=HEADERS_BIRDEYE, params=params)
        results = []
        if data:
            tokens = (data.get("data") or {}).get("tokens") or []
            for t in tokens:
                mint = t.get("address", "")
                if not mint:
                    continue
                results.append(
                    {
                        "mint": mint,
                        "name": t.get("name", "Unknown"),
                        "symbol": t.get("symbol", "???"),
                        "pool_address": "",
                        "dex": "birdeye",
                        "price_usd": float(t.get("price") or 0),
                        "market_cap_usd": float(t.get("mc") or 0),
                        "fdv_usd": float(t.get("fdv") or 0),
                        "liquidity_usd": float(t.get("liquidity") or 0),
                        "volume_24h_usd": float(t.get("v24hUSD") or 0),
                        "volume_6h_usd": float(t.get("v6hUSD") or 0),
                        "volume_1h_usd": float(t.get("v1hUSD") or 0),
                        "price_change_1h": float(t.get("v1hChangePercent") or 0),
                        "price_change_6h": float(t.get("v6hChangePercent") or 0),
                        "price_change_24h": float(t.get("v24hChangePercent") or 0),
                        "launched_at": None,
                        "age_hours": 9999.0,
                    }
                )
        logger.info(f"[Scout] Birdeye trending returned {len(results)} tokens")
        return results

    # ── Filtering ──────────────────────────────────────────────────────────────

    def _meets_thresholds(self, t: dict) -> tuple[bool, str]:
        """
        Hard gate. Returns (passes, reason_if_failed).
        These are non-negotiable — if a token fails here it is dropped permanently.
        """
        liq = t.get("liquidity_usd", 0)
        vol = t.get("volume_24h_usd", 0)
        mc = t.get("market_cap_usd", 0)
        age = t.get("age_hours", 9999)
        p1h = t.get("price_change_1h", 0)

        if liq < config.MIN_LIQUIDITY_USD:
            return False, f"liquidity ${liq:,.0f} < min ${config.MIN_LIQUIDITY_USD:,.0f}"
        if vol < config.MIN_VOLUME_24H_USD:
            return False, f"volume ${vol:,.0f} < min ${config.MIN_VOLUME_24H_USD:,.0f}"
        if mc < config.MIN_MARKET_CAP_USD:
            return False, f"mcap ${mc:,.0f} < min ${config.MIN_MARKET_CAP_USD:,.0f}"
        if mc > config.MAX_MARKET_CAP_USD:
            return False, f"mcap ${mc:,.0f} > max ${config.MAX_MARKET_CAP_USD:,.0f}"
        if age > config.MAX_TOKEN_AGE_HOURS:
            return False, f"age {age:.1f}h > max {config.MAX_TOKEN_AGE_HOURS}h"
        if p1h < config.MIN_PRICE_CHANGE_1H:
            return False, f"1h price change {p1h:.1f}% < min {config.MIN_PRICE_CHANGE_1H}%"
        return True, ""

    def _is_on_cooldown(self, mint: str) -> bool:
        """Don't re-alert the same token within ALERT_COOLDOWN_HOURS."""
        last = self._seen_mints.get(mint, 0)
        return (time.time() - last) < config.ALERT_COOLDOWN_HOURS * 3600

    def mark_alerted(self, mint: str):
        self._seen_mints[mint] = time.time()

    # ── Dedup ──────────────────────────────────────────────────────────────────

    def _dedup(self, raw_list: list[dict]) -> list[dict]:
        """Merge duplicate mints, keeping the entry with more data."""
        seen: dict[str, dict] = {}
        for t in raw_list:
            mint = t.get("mint", "")
            if not mint:
                continue
            if mint not in seen or (
                t.get("liquidity_usd", 0) > seen[mint].get("liquidity_usd", 0)
            ):
                seen[mint] = t
        return list(seen.values())

    # ── Main scan ──────────────────────────────────────────────────────────────

    async def scan_for_opportunities(self) -> list[TokenOpportunity]:
        """
        Full scan cycle. Returns list of TokenOpportunity objects that have
        passed ALL configured thresholds and are not on cooldown.
        """
        logger.info("[Scout] Starting scan cycle…")

        # Gather from all sources in parallel
        gecko_task = asyncio.create_task(self._fetch_gecko_new_pools())
        dex_task = asyncio.create_task(self._fetch_dexscreener_trending())
        bird_task = asyncio.create_task(self._fetch_birdeye_trending())

        gecko_results, dex_results, bird_results = await asyncio.gather(
            gecko_task, dex_task, bird_task, return_exceptions=True
        )

        raw: list[dict] = []
        for result in [gecko_results, dex_results, bird_results]:
            if isinstance(result, list):
                raw.extend(result)
            elif isinstance(result, Exception):
                logger.warning(f"[Scout] Source error: {result}")

        raw = self._dedup(raw)
        logger.info(f"[Scout] {len(raw)} unique tokens after dedup")

        opportunities: list[TokenOpportunity] = []
        for t in raw:
            mint = t.get("mint", "")
            if self._is_on_cooldown(mint):
                continue

            passes, reason = self._meets_thresholds(t)
            if not passes:
                logger.debug(f"[Scout] {t.get('symbol')} dropped: {reason}")
                continue

            opp = TokenOpportunity(
                mint=mint,
                name=t["name"],
                symbol=t["symbol"],
                pool_address=t.get("pool_address", ""),
                dex=t.get("dex", "unknown"),
                price_usd=t["price_usd"],
                market_cap_usd=t["market_cap_usd"],
                fdv_usd=t["fdv_usd"],
                liquidity_usd=t["liquidity_usd"],
                volume_24h_usd=t["volume_24h_usd"],
                volume_6h_usd=t["volume_6h_usd"],
                volume_1h_usd=t["volume_1h_usd"],
                price_change_1h=t["price_change_1h"],
                price_change_6h=t["price_change_6h"],
                price_change_24h=t["price_change_24h"],
                launched_at=t.get("launched_at"),
                age_hours=t["age_hours"],
            )
            opportunities.append(opp)

        logger.info(f"[Scout] {len(opportunities)} opportunities passed thresholds")
        return opportunities
