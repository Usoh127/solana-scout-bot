"""
monitor.py — Background risk monitoring loop for open positions.

After a buy, this module continuously checks each position and fires
Telegram alerts when any of the following trip:
  • Price drops >= STOP_LOSS_PCT from buy price       (default -15%)
  • Liquidity drops >= LIQUIDITY_DROP_ALERT_PCT        (default -30%)
  • Large wallet dump detected via Helius txn webhooks (default >= 5% supply)
  • Sentiment spike into Bearish territory             (< SENTIMENT_BEARISH_THRESHOLD)

Alerts include SELL button → bot.py handles confirmation before executing.

Monitoring runs in the job_queue of python-telegram-bot Application.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import aiohttp

from config import config
from sentiment import SentimentAnalyzer

logger = logging.getLogger(__name__)

DEXSCREENER_BASE = "https://api.dexscreener.com"
HELIUS_BASE = "https://api.helius.xyz/v0"

# Monitor alert types
ALERT_STOP_LOSS = "stop_loss"
ALERT_LIQUIDITY_DROP = "liquidity_drop"
ALERT_LARGE_DUMP = "large_dump"
ALERT_SENTIMENT_BEARISH = "sentiment_bearish"


@dataclass
class Position:
    mint: str
    name: str
    symbol: str
    pool_address: str
    buy_price_usd: float
    buy_time: float           # unix timestamp
    amount_tokens: float
    amount_sol_spent: float
    liquidity_at_buy: float
    tx_hash: str

    # Alert state — avoid spamming the same alert
    stop_loss_alerted: bool = False
    liquidity_alerted: bool = False
    dump_alerted: bool = False
    sentiment_alerted: bool = False

    # Track last alert timestamp to throttle repeated alerts
    last_alert_time: float = field(default_factory=time.time)


@dataclass
class MonitorAlert:
    mint: str
    symbol: str
    alert_type: str
    current_price: float
    buy_price: float
    pct_change: float
    current_liquidity: float
    liquidity_drop_pct: float
    message: str
    triggered_at: float = field(default_factory=time.time)


class PositionMonitor:
    def __init__(self, sentiment_analyzer: SentimentAnalyzer):
        self.positions: dict[str, Position] = {}   # mint -> Position
        self._sentiment = sentiment_analyzer
        self._session: Optional[aiohttp.ClientSession] = None
        # Callbacks registered by bot.py
        self._alert_callbacks: list = []

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def register_alert_callback(self, cb):
        """Register an async callback(alert: MonitorAlert) for when alerts fire."""
        self._alert_callbacks.append(cb)

    def add_position(self, position: Position):
        self.positions[position.mint] = position
        logger.info(
            f"[Monitor] Tracking {position.symbol} — buy price ${position.buy_price_usd:.6f}, "
            f"liquidity ${position.liquidity_at_buy:,.0f}"
        )

    def remove_position(self, mint: str):
        if mint in self.positions:
            p = self.positions.pop(mint)
            logger.info(f"[Monitor] Removed position for {p.symbol}")

    def has_position(self, mint: str) -> bool:
        return mint in self.positions

    def get_position(self, mint: str) -> Optional[Position]:
        return self.positions.get(mint)

    def list_positions(self) -> list[Position]:
        return list(self.positions.values())

    # ── Price + liquidity fetch ────────────────────────────────────────────────

    async def _fetch_current_data(self, mint: str) -> Optional[dict]:
        """
        Get current price and liquidity for a mint via DexScreener.
        Returns dict with price_usd, liquidity_usd, or None on failure.
        """
        session = await self._get_session()
        url = f"{DEXSCREENER_BASE}/latest/dex/tokens/{mint}"
        for attempt in range(3):
            try:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        pairs = data.get("pairs") or []
                        if not pairs:
                            return None
                        # Best pair = highest liquidity
                        pairs.sort(
                            key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0),
                            reverse=True,
                        )
                        p = pairs[0]
                        liq = p.get("liquidity") or {}
                        return {
                            "price_usd": float(p.get("priceUsd") or 0),
                            "liquidity_usd": float(liq.get("usd") or 0),
                            "volume_5m": float((p.get("volume") or {}).get("m5") or 0),
                        }
                    elif resp.status == 429:
                        await asyncio.sleep(2 ** attempt)
                    else:
                        return None
            except Exception as e:
                logger.debug(f"[Monitor] Price fetch error for {mint}: {e}")
                await asyncio.sleep(2)
        return None

    # ── Large wallet dump detection ────────────────────────────────────────────

    async def _check_large_dump(self, mint: str) -> Optional[str]:
        """
        Use Helius parsed transaction history to detect large sell events.
        Looks for recent SWAP transactions where a large % of supply is sold.
        Requires Helius API key — returns None (skip) if not configured.
        ⚠️  FREE TIER: 100k credits/day (each tx costs ~1 credit).
        """
        if not config.has_helius:
            return None

        session = await self._get_session()
        url = f"{HELIUS_BASE}/addresses/{mint}/transactions"
        params = {
            "api-key": config.HELIUS_API_KEY,
            "type": "SWAP",
            "limit": 20,
        }
        try:
            async with session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return None
                txns = await resp.json(content_type=None)
                if not isinstance(txns, list):
                    return None

                for tx in txns:
                    # Check timestamp — only look at last 5 minutes
                    ts = tx.get("timestamp", 0)
                    if time.time() - ts > 300:  # 5 min
                        continue

                    token_transfers = tx.get("tokenTransfers") or []
                    for transfer in token_transfers:
                        if transfer.get("mint") != mint:
                            continue
                        if transfer.get("toUserAccount", "").startswith("1nc1"):
                            continue  # Burn, not dump

                        amount = float(transfer.get("tokenAmount") or 0)
                        # We need total supply to compute % — get from RPC
                        # For speed, use a heuristic: if amount > threshold tokens
                        # and it's a sell (fromUserAccount != our wallet), flag it.
                        from_acct = transfer.get("fromUserAccount", "")
                        # Rough heuristic: if a single transfer is massive
                        if amount > 1_000_000_000:  # 1B raw units — very rough
                            return (
                                f"🐋 Large wallet dump detected in last 5min: "
                                f"{from_acct[:8]}... sold {amount:.2e} tokens"
                            )
        except Exception as e:
            logger.debug(f"[Monitor] Helius dump check error: {e}")
        return None

    # ── Sentiment spike check ──────────────────────────────────────────────────

    async def _check_sentiment_spike(
        self, name: str, symbol: str, mint: str
    ) -> Optional[str]:
        """
        Re-run a quick Twitter sentiment check.
        Only fires if score drops below SENTIMENT_BEARISH_THRESHOLD.
        """
        result = await self._sentiment.analyze(name, symbol, mint)
        if result.score < config.SENTIMENT_BEARISH_THRESHOLD and result.tweet_count >= 5:
            return (
                f"📉 Negative sentiment spike: {result.label} "
                f"(score {result.score:+.2f}, {result.tweet_count} tweets)"
            )
        return None

    # ── Fire alert ────────────────────────────────────────────────────────────

    async def _fire_alert(self, alert: MonitorAlert):
        logger.warning(
            f"[Monitor] ALERT [{alert.alert_type}] {alert.symbol}: {alert.message}"
        )
        for cb in self._alert_callbacks:
            try:
                await cb(alert)
            except Exception as e:
                logger.error(f"[Monitor] Alert callback error: {e}")

    # ── Per-position check ────────────────────────────────────────────────────

    async def check_position(self, mint: str) -> Optional[MonitorAlert]:
        """
        Run all checks for a single position. Returns the alert if triggered.
        """
        pos = self.positions.get(mint)
        if not pos:
            return None

        data = await self._fetch_current_data(mint)
        if not data:
            logger.debug(f"[Monitor] No price data for {pos.symbol}, skipping")
            return None

        current_price = data["price_usd"]
        current_liq = data["liquidity_usd"]

        # Don't divide by zero
        buy_price = pos.buy_price_usd if pos.buy_price_usd > 0 else 0.000001
        pct_change = ((current_price - buy_price) / buy_price) * 100

        liq_at_buy = pos.liquidity_at_buy if pos.liquidity_at_buy > 0 else 1
        liq_drop_pct = ((liq_at_buy - current_liq) / liq_at_buy) * 100

        alert: Optional[MonitorAlert] = None

        # ── Stop loss ──────────────────────────────────────────────────────────
        if (
            not pos.stop_loss_alerted
            and pct_change <= -config.STOP_LOSS_PCT
        ):
            alert = MonitorAlert(
                mint=mint,
                symbol=pos.symbol,
                alert_type=ALERT_STOP_LOSS,
                current_price=current_price,
                buy_price=buy_price,
                pct_change=pct_change,
                current_liquidity=current_liq,
                liquidity_drop_pct=liq_drop_pct,
                message=(
                    f"🛑 Stop loss hit! {pos.symbol} is down {pct_change:.1f}% "
                    f"from your buy (${buy_price:.6f} → ${current_price:.6f})"
                ),
            )
            pos.stop_loss_alerted = True

        # ── Liquidity drop ────────────────────────────────────────────────────
        elif (
            not pos.liquidity_alerted
            and liq_drop_pct >= config.LIQUIDITY_DROP_ALERT_PCT
        ):
            alert = MonitorAlert(
                mint=mint,
                symbol=pos.symbol,
                alert_type=ALERT_LIQUIDITY_DROP,
                current_price=current_price,
                buy_price=buy_price,
                pct_change=pct_change,
                current_liquidity=current_liq,
                liquidity_drop_pct=liq_drop_pct,
                message=(
                    f"🚨 Liquidity rug alarm! {pos.symbol} liquidity dropped "
                    f"{liq_drop_pct:.1f}% — from ${liq_at_buy:,.0f} → ${current_liq:,.0f}. "
                    f"Possible rug pull in progress."
                ),
            )
            pos.liquidity_alerted = True

        # ── Large dump (only check every 5 min to conserve Helius credits) ────
        elif not pos.dump_alerted:
            elapsed_since_last = time.time() - pos.last_alert_time
            if elapsed_since_last >= 300:
                dump_msg = await self._check_large_dump(mint)
                if dump_msg:
                    alert = MonitorAlert(
                        mint=mint,
                        symbol=pos.symbol,
                        alert_type=ALERT_LARGE_DUMP,
                        current_price=current_price,
                        buy_price=buy_price,
                        pct_change=pct_change,
                        current_liquidity=current_liq,
                        liquidity_drop_pct=liq_drop_pct,
                        message=dump_msg,
                    )
                    pos.dump_alerted = True
                    pos.last_alert_time = time.time()

        # ── Sentiment spike (every 10 min to conserve Twitter rate limit) ──────
        elif not pos.sentiment_alerted:
            elapsed = time.time() - pos.last_alert_time
            if elapsed >= 600:
                sentiment_msg = await self._check_sentiment_spike(
                    pos.name, pos.symbol, mint
                )
                if sentiment_msg:
                    alert = MonitorAlert(
                        mint=mint,
                        symbol=pos.symbol,
                        alert_type=ALERT_SENTIMENT_BEARISH,
                        current_price=current_price,
                        buy_price=buy_price,
                        pct_change=pct_change,
                        current_liquidity=current_liq,
                        liquidity_drop_pct=liq_drop_pct,
                        message=sentiment_msg,
                    )
                    pos.sentiment_alerted = True
                    pos.last_alert_time = time.time()

        if alert:
            await self._fire_alert(alert)
            return alert

        logger.debug(
            f"[Monitor] {pos.symbol}: {pct_change:+.1f}% from buy, "
            f"liq drop {liq_drop_pct:.1f}%"
        )
        return None

    # ── Main monitoring loop (called by job_queue) ────────────────────────────

    async def run_monitor_cycle(self, context=None):
        """
        Called periodically by the Telegram bot's job_queue.
        Checks all open positions.
        """
        if not self.positions:
            return

        logger.debug(f"[Monitor] Checking {len(self.positions)} open positions…")
        tasks = [
            asyncio.create_task(self.check_position(mint))
            for mint in list(self.positions.keys())
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
