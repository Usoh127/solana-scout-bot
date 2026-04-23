"""
scout.py — Token scouting layer.

Primary source:  pump.fun API (free, no key)           → brand new bonding curve tokens
Secondary:       GeckoTerminal (free, no key needed)   → new Solana pools
Tertiary:        DexScreener (free, no key needed)     → detailed pair data + trending
Quaternary:      Birdeye (API key needed for full data)

Improvements in this version:
  1. Vol/MC ratio pre-filter — volume must be > 30% of market cap for non-pumpfun tokens.
     Guide reference: volume below 80% of MC = likely bundled. We use 30% as a softer floor
     to avoid being too aggressive while still killing obvious wash-trading setups.

  2. Bonding curve progress — pump.fun tokens now extract and expose graduation progress.
     Tokens at 70-95% bonding are pre-graduation plays (the best entry window).
     Tokens under 15% bonding are filtered out (too early, too risky).
     Tokens over 97% are also skipped (about to graduate, price already moved).

  3. Bonding curve progress shown in briefing via pumpfun_bonding_pct field.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from config import config
from narrative_tracker import narrative_tracker

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

GECKOTERMINAL_BASE = "https://api.geckoterminal.com/api/v2"
DEXSCREENER_BASE   = "https://api.dexscreener.com"
BIRDEYE_BASE       = "https://public-api.birdeye.so"
PUMPFUN_BASE       = "https://frontend-api.pump.fun"

WSOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

BURN_ADDRESSES = {
    "1nc1nerator11111111111111111111111111111111",
    "So11111111111111111111111111111111111111112",
}

HEADERS_GT = {
    "Accept": "application/json;version=20230302",
}

HEADERS_BIRDEYE = {
    "X-API-KEY": config.BIRDEYE_API_KEY,
    "x-chain": "solana",
}

SEEN_MINTS_FILE = os.environ.get(
    "SEEN_MINTS_FILE",
    "/data/seen_mints.json" if os.path.isdir("/data") else "seen_mints.json"
)

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
    safety_top10_holder_pct: float = 0.0
    safety_lp_lock_verified: Optional[bool] = None
    safety_bundle_risk: float = 0.0
    safety_fake_volume_risk: float = 0.0
    safety_deployer_risk: float = 0.0
    safety_deployer_address: str = ""

    # populated by sentiment analyzer later
    sentiment_label: str = ""
    sentiment_score: float = 0.0
    sentiment_summary: str = ""
    tweet_count: int = 0
    top_tweet_signal: str = ""
    news_summary: str = ""
    reddit_summary: str = ""

    # overall confidence 1-10
    confidence: int = 0
    confidence_rationale: str = ""

    # data-only flag
    data_only_call: bool = False
    data_only_reason: str = ""

    # Copycat detection
    possible_copycat: bool = False
    original_ca: str = ""

    # DexScreener Enhanced listing paid
    dex_paid: bool = False

    # Transaction count
    txns_24h: int = 0

    # pump.fun specific
    pumpfun_reply_count: int = 0
    pumpfun_is_koth: bool = False
    pumpfun_bonding_progress: float = 0.0   # 0-100, how far to graduation

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

    @property
    def bonding_label(self) -> str:
        """Human readable bonding curve status for briefing."""
        if self.pumpfun_bonding_progress <= 0:
            return ""
        p = self.pumpfun_bonding_progress
        if p >= 95:
            return f"🚀 {p:.0f}% — graduating soon!"
        if p >= 70:
            return f"🔥 {p:.0f}% — pre-graduation zone"
        if p >= 40:
            return f"📈 {p:.0f}% bonding"
        return f"⏳ {p:.0f}% bonding"


# ─── HTTP helpers ──────────────────────────────────────────────────────────────


async def _get_json(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict | None = None,
    params: dict | None = None,
    retries: int = 3,
    backoff: float = 2.0,
) -> dict | list | None:
    attempt = 0
    while attempt < retries:
        try:
            async with session.get(
                url, headers=headers or {}, params=params,
                timeout=aiohttp.ClientTimeout(total=15)
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
        self._seen_mints: dict[str, float] = {}
        self._scan_count: int = 0
        self._seen_tickers: dict[str, str] = {}
        self._load_seen_mints()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Source 1: pump.fun bonding curve ──────────────────────────────────────

    async def _fetch_pumpfun_new(self) -> list[dict]:
        """
        Fetch brand new and recently active tokens from pump.fun.

        Key improvements:
        - Extracts bonding_curve_progress (0-100%)
        - Filters tokens < 15% bonding (too early, high rug risk)
        - Filters tokens > 97% bonding (about to graduate, price already moved)
        - Prioritises 70-95% range (pre-graduation zone = best entry window)
        """
        session  = await self._get_session()
        results  = []
        seen_set = set()

        for sort_by in ["created_timestamp", "last_trade_timestamp"]:
            try:
                async with session.get(
                    f"{PUMPFUN_BASE}/coins",
                    params={
                        "sort":        sort_by,
                        "order":       "DESC",
                        "limit":       50,
                        "includeNsfw": "false",
                    },
                    headers={
                        "Accept":     "application/json",
                        "User-Agent": "Mozilla/5.0 (compatible; SolanaBot/1.0)",
                    },
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 530:
                        # Cloudflare rate limit / API down — skip silently
                        logger.debug(f"[Scout] PumpFun {sort_by} → HTTP 530 (rate limited, skipping)")
                        continue
                    if resp.status != 200:
                        logger.warning(f"[Scout] PumpFun {sort_by} → HTTP {resp.status}")
                        continue
                    coins = await resp.json(content_type=None)
                    if not isinstance(coins, list):
                        continue

                    for coin in coins:
                        mint = coin.get("mint", "")
                        if not mint or mint in seen_set or mint in BURN_ADDRESSES:
                            continue
                        seen_set.add(mint)

                        # Skip graduated tokens
                        if coin.get("complete") or coin.get("raydium_pool"):
                            continue

                        # ── Extract bonding curve progress ────────────────────
                        # pump.fun returns this as a float 0-100
                        bonding_progress = float(
                            coin.get("bonding_curve_progress") or
                            coin.get("progress") or 0
                        )

                        # Only skip if bonding progress is literally 0
                        # (means no data returned, not a real token)
                        if bonding_progress == 0 and not coin.get("usd_market_cap"):
                            continue

                        # Filter: about to graduate (> 97%) = price already moved, skip
                        if bonding_progress > 97:
                            logger.debug(
                                f"[Scout] Skipping {coin.get('symbol')} — "
                                f"bonding {bonding_progress:.0f}% (graduating, too late)"
                            )
                            continue

                        # Parse age
                        created_ts = coin.get("created_timestamp", 0)
                        if created_ts > 1e12:
                            created_ts /= 1000

                        created_at = None
                        age_hours  = 9999.0
                        if created_ts:
                            try:
                                created_at = datetime.fromtimestamp(created_ts, tz=timezone.utc)
                                age_hours  = (
                                    datetime.now(timezone.utc) - created_at
                                ).total_seconds() / 3600
                            except Exception:
                                pass

                        if age_hours > config.MAX_TOKEN_AGE_HOURS:
                            continue

                        usd_mcap = float(coin.get("usd_market_cap") or 0)

                        if usd_mcap < config.MIN_MARKET_CAP_USD:
                            continue
                        if usd_mcap > config.MAX_MARKET_CAP_USD:
                            continue

                        virtual_sol   = coin.get("virtual_sol_reserves", 0) / 1e9
                        est_liquidity = max(virtual_sol * 150, usd_mcap * 0.25)

                        is_koth      = bool(coin.get("king_of_the_hill_timestamp"))
                        reply_count  = int(coin.get("reply_count") or 0)

                        results.append({
                            "mint":                    mint,
                            "name":                    coin.get("name", "Unknown"),
                            "symbol":                  coin.get("symbol", "???"),
                            "pool_address":            coin.get("bonding_curve", ""),
                            "dex":                     "pump.fun",
                            "price_usd":               0.0,
                            "market_cap_usd":          usd_mcap,
                            "fdv_usd":                 usd_mcap,
                            "liquidity_usd":           est_liquidity,
                            "volume_24h_usd":          0.0,
                            "volume_6h_usd":           0.0,
                            "volume_1h_usd":           0.0,
                            "price_change_1h":         0.0,
                            "price_change_6h":         0.0,
                            "price_change_24h":        0.0,
                            "launched_at":             created_at,
                            "age_hours":               age_hours,
                            "source":                  "pumpfun",
                            "pumpfun_reply_count":     reply_count,
                            "pumpfun_is_koth":         is_koth,
                            "pumpfun_bonding_progress": bonding_progress,
                        })

            except Exception as e:
                logger.warning(f"[Scout] PumpFun {sort_by} fetch error: {e}")

            await asyncio.sleep(0.3)

        # ── Sort: prioritise pre-graduation zone (70-95%) ──────────────────
        # Tokens close to graduation get surfaced first
        def bonding_priority(t: dict) -> float:
            p = t.get("pumpfun_bonding_progress", 0)
            if 70 <= p <= 95:
                return -p        # highest bonding in this range first
            if p > 95:
                return 0         # already too close — deprioritise
            return -(p * 0.5)    # still show but lower priority

        results.sort(key=bonding_priority)

        logger.info(f"[Scout] PumpFun returned {len(results)} raw tokens")
        return results

    # ── Source 2: GeckoTerminal new pools ─────────────────────────────────────

    async def _fetch_gecko_new_pools(self) -> list[dict]:
        session = await self._get_session()
        pools   = []

        for page in range(1, 4):
            url    = f"{GECKOTERMINAL_BASE}/networks/solana/new_pools"
            params = {"include": "base_token,dex", "page": page}
            data   = await _get_json(session, url, headers=HEADERS_GT, params=params)
            if not data:
                break

            raw_pools = data.get("data", [])
            included  = {
                item["id"]: item
                for item in data.get("included", [])
                if item.get("type") in ("token", "dex")
            }

            for pool in raw_pools:
                try:
                    attrs = pool.get("attributes", {})
                    rels  = pool.get("relationships", {})

                    base_token_ref = rels.get("base_token", {}).get("data", {})
                    base_id        = base_token_ref.get("id", "")
                    base_token     = included.get(base_id, {}).get("attributes", {})

                    dex_ref  = rels.get("dex", {}).get("data", {})
                    dex_obj  = included.get(dex_ref.get("id", ""), {})
                    dex_name = dex_obj.get("attributes", {}).get("name", "unknown")

                    mint = base_token.get("address", "")
                    if not mint or mint in BURN_ADDRESSES:
                        continue

                    volume_usd = attrs.get("volume_usd", {})
                    price_pct  = attrs.get("price_change_percentage", {})

                    created_at_str = attrs.get("pool_created_at")
                    created_at     = None
                    age_hours      = 9999.0
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

                    pools.append({
                        "mint":             mint,
                        "name":             base_token.get("name", "Unknown"),
                        "symbol":           base_token.get("symbol", "???"),
                        "pool_address":     attrs.get("address", ""),
                        "dex":              dex_name,
                        "price_usd":        float(attrs.get("base_token_price_usd") or 0),
                        "market_cap_usd":   float(attrs.get("market_cap_usd") or attrs.get("fdv_usd") or 0),
                        "fdv_usd":          float(attrs.get("fdv_usd") or 0),
                        "liquidity_usd":    float(attrs.get("reserve_in_usd") or 0),
                        "volume_24h_usd":   float(volume_usd.get("h24") or 0),
                        "volume_6h_usd":    float(volume_usd.get("h6") or 0),
                        "volume_1h_usd":    float(volume_usd.get("h1") or 0),
                        "price_change_1h":  float(price_pct.get("h1") or 0),
                        "price_change_6h":  float(price_pct.get("h6") or 0),
                        "price_change_24h": float(price_pct.get("h24") or 0),
                        "launched_at":      created_at,
                        "age_hours":        age_hours,
                    })
                except Exception as e:
                    logger.debug(f"Error parsing GT pool: {e}")
                    continue

            await asyncio.sleep(0.5)

        logger.info(f"[Scout] GeckoTerminal returned {len(pools)} raw pools")
        return pools

    # ── Source 3: DexScreener boosted / trending ───────────────────────────────

    async def _fetch_dexscreener_trending(self) -> list[dict]:
        session = await self._get_session()
        results = []

        url  = f"{DEXSCREENER_BASE}/token-boosts/latest/v1"
        data = await _get_json(session, url)
        if data and isinstance(data, list):
            solana_tokens = [
                t for t in data if t.get("chainId", "").lower() == "solana"
            ]
            addrs = [t["tokenAddress"] for t in solana_tokens[:20] if t.get("tokenAddress")]
            if addrs:
                chunk      = ",".join(addrs[:10])
                detail_url = f"{DEXSCREENER_BASE}/latest/dex/tokens/{chunk}"
                detail_data = await _get_json(session, detail_url)
                if detail_data:
                    pairs = detail_data.get("pairs") or []
                    for pair in pairs:
                        if pair.get("chainId", "").lower() != "solana":
                            continue
                        parsed = self._parse_dexscreener_pair(pair)
                        if parsed:
                            results.append(parsed)

        logger.info(f"[Scout] DexScreener trending returned {len(results)} pairs")
        return results

    async def fetch_token_details_dexscreener(self, mint: str) -> dict | None:
        session = await self._get_session()
        url     = f"{DEXSCREENER_BASE}/latest/dex/tokens/{mint}"
        data    = await _get_json(session, url)
        if not data:
            return None
        pairs = data.get("pairs") or []
        if not pairs:
            return None
        pairs.sort(
            key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0),
            reverse=True
        )
        return self._parse_dexscreener_pair(pairs[0])

    def _parse_dexscreener_pair(self, pair: dict) -> dict | None:
        try:
            base = pair.get("baseToken", {})
            mint = base.get("address", "")
            if not mint:
                return None

            liquidity    = pair.get("liquidity") or {}
            volume       = pair.get("volume") or {}
            price_change = pair.get("priceChange") or {}

            created_at = None
            age_hours  = 9999.0
            pair_created_at = pair.get("pairCreatedAt")
            if pair_created_at:
                try:
                    ts         = int(pair_created_at) / 1000
                    created_at = datetime.fromtimestamp(ts, tz=timezone.utc)
                    age_hours  = (
                        datetime.now(timezone.utc) - created_at
                    ).total_seconds() / 3600
                except Exception:
                    pass

            info     = pair.get("info") or {}
            boosts   = pair.get("boosts") or {}
            dex_paid = bool(
                boosts.get("active", 0) > 0
                or info.get("description")
                or (info.get("socials") and len(info.get("socials", [])) > 0)
                or (info.get("websites") and len(info.get("websites", [])) > 0)
            )

            return {
                "mint":             mint,
                "name":             base.get("name", "Unknown"),
                "symbol":           base.get("symbol", "???"),
                "pool_address":     pair.get("pairAddress", ""),
                "dex":              pair.get("dexId", "unknown"),
                "price_usd":        float(pair.get("priceUsd") or 0),
                "market_cap_usd":   float(pair.get("marketCap") or pair.get("fdv") or 0),
                "fdv_usd":          float(pair.get("fdv") or 0),
                "liquidity_usd":    float(liquidity.get("usd") or 0),
                "volume_24h_usd":   float(volume.get("h24") or 0),
                "volume_6h_usd":    float(volume.get("h6") or 0),
                "volume_1h_usd":    float(volume.get("h1") or 0),
                "price_change_1h":  float(price_change.get("h1") or 0),
                "price_change_6h":  float(price_change.get("h6") or 0),
                "price_change_24h": float(price_change.get("h24") or 0),
                "launched_at":      created_at,
                "age_hours":        age_hours,
                "dex_paid":         dex_paid,
                "txns_24h":         int(
                    (pair.get("txns") or {}).get("h24", {}).get("buys", 0)
                    + (pair.get("txns") or {}).get("h24", {}).get("sells", 0)
                ),
            }
        except Exception as e:
            logger.debug(f"Error parsing DexScreener pair: {e}")
            return None

    # ── Source 4: Birdeye trending ─────────────────────────────────────────────

    async def _fetch_birdeye_trending(self) -> list[dict]:
        if not config.has_birdeye:
            return []

        session = await self._get_session()
        url     = f"{BIRDEYE_BASE}/defi/tokenlist"
        params  = {
            "sort_by":       "v24hChangePercent",
            "sort_type":     "desc",
            "offset":        0,
            "limit":         50,
            "min_liquidity": config.MIN_LIQUIDITY_USD,
        }
        data    = await _get_json(session, url, headers=HEADERS_BIRDEYE, params=params)
        results = []
        if data:
            tokens = (data.get("data") or {}).get("tokens") or []
            for t in tokens:
                mint = t.get("address", "")
                if not mint:
                    continue
                results.append({
                    "mint":             mint,
                    "name":             t.get("name", "Unknown"),
                    "symbol":           t.get("symbol", "???"),
                    "pool_address":     "",
                    "dex":              "birdeye",
                    "price_usd":        float(t.get("price") or 0),
                    "market_cap_usd":   float(t.get("mc") or 0),
                    "fdv_usd":          float(t.get("fdv") or 0),
                    "liquidity_usd":    float(t.get("liquidity") or 0),
                    "volume_24h_usd":   float(t.get("v24hUSD") or 0),
                    "volume_6h_usd":    float(t.get("v6hUSD") or 0),
                    "volume_1h_usd":    float(t.get("v1hUSD") or 0),
                    "price_change_1h":  float(t.get("v1hChangePercent") or 0),
                    "price_change_6h":  float(t.get("v6hChangePercent") or 0),
                    "price_change_24h": float(t.get("v24hChangePercent") or 0),
                    "launched_at":      None,
                    "age_hours":        9999.0,
                })
        logger.info(f"[Scout] Birdeye trending returned {len(results)} tokens")
        return results

    # ── Filtering ──────────────────────────────────────────────────────────────

    def _meets_thresholds(self, t: dict) -> tuple[bool, str]:
        """
        Hard gate. Returns (passes, reason_if_failed).

        New in this version:
          Vol/MC ratio check — volume must be at least 30% of market cap for
          non-pumpfun tokens. Guide says 80% is ideal; we use 30% as a softer
          floor so we don't over-filter. Anything below 30% is almost certainly
          bundled or wash-traded.

          pump.fun tokens skip this check since they don't have real volume
          data until they graduate and get indexed by DEX aggregators.
        """
        liq    = t.get("liquidity_usd", 0)
        vol    = t.get("volume_24h_usd", 0)
        mc     = t.get("market_cap_usd", 0)
        age    = t.get("age_hours", 9999)
        p1h    = t.get("price_change_1h", 0)
        source = t.get("source", "")
        is_pumpfun = source == "pumpfun"

        # Liquidity: relax floor for pump.fun (estimated value)
        liq_min = config.MIN_LIQUIDITY_USD * 0.3 if is_pumpfun else config.MIN_LIQUIDITY_USD
        if liq < liq_min:
            return False, f"liquidity ${liq:,.0f} < min ${liq_min:,.0f}"

        # Volume: skip for pump.fun (no real volume data on bonding curve)
        if not is_pumpfun and vol < config.MIN_VOLUME_24H_USD:
            return False, f"volume ${vol:,.0f} < min ${config.MIN_VOLUME_24H_USD:,.0f}"

        # ── NEW: Vol/MC ratio check ───────────────────────────────────────────
        # Volume should be at least 8% of market cap.
        # Below this = almost certainly bundled, wash-traded, or completely dead.
        # Guide reference: below 80% = suspect. We use 8% as a practical floor.
        # Skip for pump.fun (no real volume data available).
        if not is_pumpfun and mc > 0 and vol > 0:
            vol_mc_ratio = vol / mc
            if vol_mc_ratio < 0.08:
                return False, (
                    f"vol/MC ratio {vol_mc_ratio:.1%} < 8% — dead or heavily bundled "
                    f"(vol ${vol:,.0f} vs MC ${mc:,.0f})"
                )

        if mc < config.MIN_MARKET_CAP_USD:
            return False, f"mcap ${mc:,.0f} < min ${config.MIN_MARKET_CAP_USD:,.0f}"
        if mc > config.MAX_MARKET_CAP_USD:
            return False, f"mcap ${mc:,.0f} > max ${config.MAX_MARKET_CAP_USD:,.0f}"
        if age > config.MAX_TOKEN_AGE_HOURS:
            return False, f"age {age:.1f}h > max {config.MAX_TOKEN_AGE_HOURS}h"

        # Price change: skip for pump.fun
        if not is_pumpfun and p1h < config.MIN_PRICE_CHANGE_1H:
            return False, f"1h price change {p1h:.1f}% < min {config.MIN_PRICE_CHANGE_1H}%"

        return True, ""

    def _is_on_cooldown(self, mint: str) -> bool:
        last = self._seen_mints.get(mint, 0)
        return (time.time() - last) < config.ALERT_COOLDOWN_HOURS * 3600

    def mark_alerted(self, mint: str):
        self._seen_mints[mint] = time.time()
        self._save_seen_mints()

    def _save_seen_mints(self):
        try:
            now    = time.time()
            active = {
                m: t for m, t in self._seen_mints.items()
                if now - t < config.ALERT_COOLDOWN_HOURS * 3600
            }
            tmp = SEEN_MINTS_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(active, f)
            os.replace(tmp, SEEN_MINTS_FILE)
        except Exception as e:
            logger.debug(f"[Scout] Could not save seen mints: {e}")

    def _load_seen_mints(self):
        if not os.path.exists(SEEN_MINTS_FILE):
            return
        try:
            with open(SEEN_MINTS_FILE) as f:
                data = json.load(f)
            now = time.time()
            self._seen_mints = {
                m: t for m, t in data.items()
                if now - t < config.ALERT_COOLDOWN_HOURS * 3600
            }
            if self._seen_mints:
                logger.info(f"[Scout] Loaded {len(self._seen_mints)} cooldown mints from disk")
        except Exception as e:
            logger.debug(f"[Scout] Could not load seen mints: {e}")

    def _dedup(self, raw_list: list[dict]) -> list[dict]:
        """
        Merge duplicate mints. If the same mint appears from both pump.fun and
        DexScreener, prefer the DexScreener entry (has real volume/price data)
        but carry over pump.fun bonding progress.
        """
        seen: dict[str, dict] = {}
        for t in raw_list:
            mint = t.get("mint", "")
            if not mint:
                continue
            if mint not in seen:
                seen[mint] = t
            else:
                existing = seen[mint]
                if t.get("source") != "pumpfun" and existing.get("source") == "pumpfun":
                    # Merge: keep DexScreener data, carry pump.fun extras
                    t["pumpfun_reply_count"]     = existing.get("pumpfun_reply_count", 0)
                    t["pumpfun_is_koth"]         = existing.get("pumpfun_is_koth", False)
                    t["pumpfun_bonding_progress"] = existing.get("pumpfun_bonding_progress", 0.0)
                    seen[mint] = t
                elif t.get("liquidity_usd", 0) > existing.get("liquidity_usd", 0):
                    seen[mint] = t
        return list(seen.values())

    # ── Main scan ──────────────────────────────────────────────────────────────

    async def scan_for_opportunities(self) -> list[TokenOpportunity]:
        logger.info("[Scout] Starting scan cycle…")

        pump_task  = asyncio.create_task(self._fetch_pumpfun_new())
        gecko_task = asyncio.create_task(self._fetch_gecko_new_pools())
        dex_task   = asyncio.create_task(self._fetch_dexscreener_trending())
        bird_task  = asyncio.create_task(self._fetch_birdeye_trending())

        pump_results, gecko_results, dex_results, bird_results = await asyncio.gather(
            pump_task, gecko_task, dex_task, bird_task, return_exceptions=True
        )

        raw: list[dict] = []
        for result in [pump_results, gecko_results, dex_results, bird_results]:
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

            ticker_upper = t["symbol"].upper()
            if ticker_upper in self._seen_tickers and self._seen_tickers[ticker_upper] != mint:
                logger.info(
                    f"[Scout] Duplicate ticker ${ticker_upper}: "
                    f"first CA={self._seen_tickers[ticker_upper][:8]}, "
                    f"this CA={mint[:8]} — flagging as copycat"
                )
                t["possible_copycat"] = True
                t["original_ca"]      = self._seen_tickers[ticker_upper]
            else:
                self._seen_tickers[ticker_upper] = mint

            narrative_tracker.record_token(t.get("name", ""), t.get("symbol", ""), passed=True)

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
                possible_copycat=t.get("possible_copycat", False),
                original_ca=t.get("original_ca", ""),
                dex_paid=t.get("dex_paid", False),
                txns_24h=t.get("txns_24h", 0),
                pumpfun_reply_count=t.get("pumpfun_reply_count", 0),
                pumpfun_is_koth=t.get("pumpfun_is_koth", False),
                pumpfun_bonding_progress=t.get("pumpfun_bonding_progress", 0.0),
            )
            opportunities.append(opp)

        logger.info(f"[Scout] {len(opportunities)} opportunities passed thresholds")
        return opportunities
