"""
early_detector.py — Three upgrades that directly target early meme discovery.

1. Young Token Gate Override
   Tokens under 20 minutes old skip the social signal requirement entirely.
   Reason: social confirmation (CT posts, tweets) comes AFTER price moves.
   Requiring it means you're structurally always arriving after the move.
   Young tokens get a different, gentler scoring pass.

2. Holder Velocity Tracking
   Holder count snapshots are recorded every scan cycle per token.
   A token growing 30%+ holders in one 60-120s window is actively spreading.
   This is a leading indicator that fires before volume builds.
   Tokens with strong velocity jump the queue.

3. Deployer Win-Rate Cache
   The current safety checker asks "has this deployer rugged before?"
   This adds: "has this deployer launched winners before?"
   A deployer with 2+ previous tokens that hit 500k+ market cap is a
   significant confidence signal. Results cached 24h per deployer to avoid
   burning Helius and DexScreener API calls.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import aiohttp

from config import config

logger = logging.getLogger(__name__)

DEXSCREENER_BASE = "https://api.dexscreener.com"

# ── Constants ──────────────────────────────────────────────────────────────────

YOUNG_TOKEN_MINUTES        = 20       # under this = bypass social gate
HOLDER_VELOCITY_THRESHOLD  = 0.30     # 30% holder growth in one window = flag
DEPLOYER_WIN_MCAP_USD      = 500_000  # previous token must have hit this to count as a win
DEPLOYER_CACHE_TTL         = 86400    # 24h cache for deployer win-rate results
DEPLOYER_WIN_BONUS_SCORE   = 2        # confidence score bonus for winning deployer


# ── Young token gate ───────────────────────────────────────────────────────────

def is_very_young(age_hours: float) -> bool:
    """True if token is under 20 minutes old."""
    return age_hours < (YOUNG_TOKEN_MINUTES / 60)


def should_bypass_social_gate(age_hours: float, price_change_1h: float = 0.0) -> tuple[bool, str]:
    """
    Determine if a token should skip the social signal requirement.

    Returns (should_bypass, reason).

    Young tokens bypass because CT posts come AFTER price movement —
    requiring them means you're always late.
    """
    if age_hours < (YOUNG_TOKEN_MINUTES / 60):
        return True, f"Token is only {age_hours * 60:.0f}min old — too early for CT posts"

    # Also bypass if it's under 2h and moving hard — social will catch up
    if age_hours < 2.0 and price_change_1h >= 50:
        return True, f"Fast mover ({price_change_1h:.0f}% 1h) under 2h — social lagging"

    return False, ""


# ── Holder velocity tracker ────────────────────────────────────────────────────

@dataclass
class HolderSnapshot:
    holder_count: int
    recorded_at:  float = field(default_factory=time.time)


class HolderVelocityTracker:
    """
    Records holder counts per token across scan cycles.
    Detects tokens with rapid holder growth — a leading indicator
    before volume and chart patterns confirm the move.
    """

    def __init__(self):
        # mint → list of HolderSnapshot (last 5 snapshots)
        self._snapshots: dict[str, list[HolderSnapshot]] = {}
        self._MAX_SNAPSHOTS = 5

    def record(self, mint: str, holder_count: int):
        """Record current holder count for a token."""
        if holder_count <= 0:
            return

        if mint not in self._snapshots:
            self._snapshots[mint] = []

        self._snapshots[mint].append(HolderSnapshot(holder_count=holder_count))

        # Keep only last N snapshots
        if len(self._snapshots[mint]) > self._MAX_SNAPSHOTS:
            self._snapshots[mint] = self._snapshots[mint][-self._MAX_SNAPSHOTS:]

    def get_velocity(self, mint: str, current_count: int) -> tuple[float, str]:
        """
        Calculate holder growth rate since last snapshot.
        Returns (growth_pct, description).

        growth_pct: 0.0 = no change, 0.5 = 50% growth, -0.2 = 20% drop
        """
        snapshots = self._snapshots.get(mint, [])

        if not snapshots or current_count <= 0:
            return 0.0, ""

        # Compare to earliest snapshot we have (most informative)
        first = snapshots[0]
        if first.holder_count <= 0:
            return 0.0, ""

        elapsed_min = (time.time() - first.recorded_at) / 60
        if elapsed_min < 0.5:
            # Too soon since last snapshot
            return 0.0, ""

        growth    = (current_count - first.holder_count) / first.holder_count
        rate_str  = f"{growth * 100:+.0f}% in {elapsed_min:.0f}min"

        if growth >= 0.50:
            return growth, f"🔥 Holder count exploding: {rate_str}"
        elif growth >= HOLDER_VELOCITY_THRESHOLD:
            return growth, f"📈 Holder velocity strong: {rate_str}"
        elif growth <= -0.20:
            return growth, f"📉 Holder count dropping: {rate_str}"
        else:
            return growth, f"Holders: {rate_str}"

    def has_strong_velocity(self, mint: str, current_count: int) -> bool:
        """Quick check — True if holder growth exceeds threshold."""
        velocity, _ = self.get_velocity(mint, current_count)
        return velocity >= HOLDER_VELOCITY_THRESHOLD

    def clear_old(self):
        """Remove snapshots older than 2 hours."""
        cutoff = time.time() - 7200
        to_remove = []
        for mint, snaps in self._snapshots.items():
            active = [s for s in snaps if s.recorded_at > cutoff]
            if not active:
                to_remove.append(mint)
            else:
                self._snapshots[mint] = active
        for mint in to_remove:
            del self._snapshots[mint]


# ── Deployer win-rate cache ────────────────────────────────────────────────────

@dataclass
class DeployerRecord:
    address:      str
    wins:         int          # previous tokens that hit DEPLOYER_WIN_MCAP_USD
    total:        int          # total previous tokens
    win_rate:     float        # wins / total
    best_token:   str          # name of best performing previous token
    best_mcap:    float        # peak mcap of best token
    cached_at:    float = field(default_factory=time.time)

    @property
    def is_fresh(self) -> bool:
        return (time.time() - self.cached_at) < DEPLOYER_CACHE_TTL

    def confidence_bonus(self) -> tuple[int, str]:
        """
        Returns (score_bonus, description) to add to confidence score.
        """
        if self.wins >= 3:
            return (
                DEPLOYER_WIN_BONUS_SCORE + 1,
                f"🏆 Serial winner deployer: {self.wins} prev tokens hit "
                f"${self.best_mcap / 1000:.0f}K+ MC"
            )
        if self.wins >= 2:
            return (
                DEPLOYER_WIN_BONUS_SCORE,
                f"✅ Proven deployer: {self.wins} prev tokens succeeded"
            )
        if self.wins == 1:
            return (
                1,
                f"✅ Deployer had 1 previous successful token "
                f"(${self.best_mcap / 1000:.0f}K+ MC)"
            )
        if self.total >= 5 and self.wins == 0:
            return (
                -1,
                f"⚠️ Deployer launched {self.total} tokens with none reaching "
                f"${DEPLOYER_WIN_MCAP_USD / 1000:.0f}K MC"
            )
        return 0, ""


class DeployerWinRateChecker:
    """
    Checks a deployer's track record for previous successful launches.
    Caches results 24h per deployer address.
    """

    def __init__(self):
        self._cache:   dict[str, DeployerRecord] = {}
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def check(self, deployer_address: str) -> Optional[DeployerRecord]:
        """
        Check deployer's win-rate.
        Returns cached result if available, otherwise queries Helius + DexScreener.
        """
        if not deployer_address or len(deployer_address) < 32:
            return None

        # Return cached result if fresh
        cached = self._cache.get(deployer_address)
        if cached and cached.is_fresh:
            logger.debug(
                f"[EarlyDetector] Deployer cache hit: "
                f"{deployer_address[:8]} ({cached.wins}/{cached.total} wins)"
            )
            return cached

        if not config.has_helius:
            return None

        session = await self._get_session()

        # Step 1: Get previous token mints from this deployer
        previous_mints: list[str] = []
        try:
            url    = f"https://api.helius.xyz/v0/addresses/{deployer_address}/transactions"
            params = {
                "api-key": config.HELIUS_API_KEY,
                "type":    "TOKEN_MINT",
                "limit":   20,
            }
            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=12),
            ) as resp:
                if resp.status == 200:
                    txns = await resp.json(content_type=None)
                    if isinstance(txns, list):
                        for tx in txns:
                            # Token mint transactions contain the mint address
                            for acct in tx.get("accountData", []):
                                mint = acct.get("account", "")
                                if mint and len(mint) > 30 and mint not in previous_mints:
                                    previous_mints.append(mint)
                                    if len(previous_mints) >= 10:
                                        break
                            if len(previous_mints) >= 10:
                                break
        except Exception as e:
            logger.debug(f"[EarlyDetector] Deployer mint fetch error: {e}")

        if not previous_mints:
            # Cache empty result so we don't keep retrying
            record = DeployerRecord(
                address=deployer_address, wins=0, total=0,
                win_rate=0.0, best_token="", best_mcap=0.0,
            )
            self._cache[deployer_address] = record
            return record

        # Step 2: Check each previous token's peak market cap on DexScreener
        wins      = 0
        best_mcap = 0.0
        best_name = ""

        # Check up to 8 previous tokens (limit API calls)
        for mint in previous_mints[:8]:
            try:
                url = f"{DEXSCREENER_BASE}/latest/dex/tokens/{mint}"
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=8)
                ) as resp:
                    if resp.status != 200:
                        continue
                    data  = await resp.json(content_type=None)
                    pairs = data.get("pairs") or []

                if not pairs:
                    continue

                # Get the highest market cap seen across all pairs for this token
                peak_mcap = max(
                    float(p.get("marketCap") or p.get("fdv") or 0)
                    for p in pairs
                )
                token_name = (pairs[0].get("baseToken") or {}).get("name", mint[:8])

                if peak_mcap >= DEPLOYER_WIN_MCAP_USD:
                    wins += 1
                    if peak_mcap > best_mcap:
                        best_mcap = peak_mcap
                        best_name = token_name

                await asyncio.sleep(0.2)   # gentle

            except Exception as e:
                logger.debug(f"[EarlyDetector] Token check error {mint[:8]}: {e}")
                continue

        total     = len(previous_mints)
        win_rate  = wins / total if total > 0 else 0.0

        record = DeployerRecord(
            address=deployer_address,
            wins=wins,
            total=total,
            win_rate=win_rate,
            best_token=best_name,
            best_mcap=best_mcap,
        )
        self._cache[deployer_address] = record

        if wins > 0:
            logger.info(
                f"[EarlyDetector] Deployer {deployer_address[:8]}: "
                f"{wins}/{total} wins, best: {best_name} "
                f"(${best_mcap / 1000:.0f}K)"
            )
        else:
            logger.debug(
                f"[EarlyDetector] Deployer {deployer_address[:8]}: "
                f"0/{total} wins"
            )

        return record


# ── Module-level singletons ────────────────────────────────────────────────────

holder_velocity = HolderVelocityTracker()
deployer_checker = DeployerWinRateChecker()
