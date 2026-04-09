"""
monitor.py — Background risk monitoring loop for open positions.

Monitors every open position every 30s and handles:

AUTOMATIC EXITS (no confirmation needed):
  • TP1 @ 2x          — auto-sell 50%, capital recovered, moonbag rides free
  • TP2 @ 3x          — auto-sell another 30%, lock more profit
  • Trailing stop      — sells remainder if price drops from peak:
                          > New token (<5min):   15% trailing
                          > Fast pump (>500% in 10min): 15% trailing
                          > Normal:              25% trailing
  • New launch rug     — token <30min old + liquidity drops 20% in one cycle → exit
  • Volume death       — 1h volume drops 80% from entry volume → exit
  • Peak trailing      — tracks peak from moment of buy, not just after TP1

MANUAL ALERTS (SELL button sent to Telegram):
  • Stop loss          — price drops >= STOP_LOSS_PCT from buy
  • Liquidity alarm    — liquidity drops >= LIQUIDITY_DROP_ALERT_PCT
  • Whale dump         — large wallet sell detected via Helius
  • Sentiment spike    — Twitter goes bearish on the token
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

# Lazy executor import to avoid circular dependency
_executor = None

def _get_executor():
    global _executor
    if _executor is None:
        from executor import TradeExecutor
        _executor = TradeExecutor()
    return _executor

DEXSCREENER_BASE = "https://api.dexscreener.com"
HELIUS_BASE      = "https://api.helius.xyz/v0"

# Alert type constants
ALERT_STOP_LOSS        = "stop_loss"
ALERT_LIQUIDITY_DROP   = "liquidity_drop"
ALERT_LARGE_DUMP       = "large_dump"
ALERT_SENTIMENT_BEARISH = "sentiment_bearish"
ALERT_TAKE_PROFIT      = "take_profit"
ALERT_AUTO_EXIT        = "auto_exit"


# ─── Position ─────────────────────────────────────────────────────────────────

@dataclass
class Position:
    mint:             str
    name:             str
    symbol:           str
    pool_address:     str
    buy_price_usd:    float
    buy_time:         float   # unix timestamp
    amount_tokens:    float
    amount_sol_spent: float
    liquidity_at_buy: float
    tx_hash:          str

    # ── Manual alert state (fire once each) ───────────────────────────────────
    stop_loss_alerted:  bool = False
    liquidity_alerted:  bool = False
    dump_alerted:       bool = False
    sentiment_alerted:  bool = False
    last_alert_time:    float = field(default_factory=time.time)

    # ── Auto take-profit state ────────────────────────────────────────────────
    tp1_hit:            bool  = False   # fired at 2x
    tp2_hit:            bool  = False   # fired at 3x
    tokens_remaining:   float = 0.0     # updated after each auto-sell
    capital_recovered:  bool  = False

    # ── Peak / trailing stop tracking ─────────────────────────────────────────
    # Tracked from the MOMENT of buy — not just after TP1
    peak_price:         float = 0.0

    # ── Volume tracking for death check ───────────────────────────────────────
    volume_at_buy:      float = 0.0     # 1h volume when we bought
    last_volume_1h:     float = 0.0     # last seen 1h volume

    # ── Fast liquidity drop detection ─────────────────────────────────────────
    last_liquidity:     float = 0.0     # liquidity in previous cycle

    # ── Price velocity tracking ───────────────────────────────────────────────
    # If token pumped >500% in first 10min, use tighter trailing stop
    fast_pump_detected: bool  = False

    # ── Age at buy ────────────────────────────────────────────────────────────
    token_age_at_buy:   float = 0.0     # age in hours when we bought


# ─── Alert ────────────────────────────────────────────────────────────────────

@dataclass
class MonitorAlert:
    mint:              str
    symbol:            str
    alert_type:        str
    current_price:     float
    buy_price:         float
    pct_change:        float
    current_liquidity: float
    liquidity_drop_pct: float
    message:           str
    triggered_at:      float = field(default_factory=time.time)


# ─── Monitor ──────────────────────────────────────────────────────────────────

class PositionMonitor:
    def __init__(self, sentiment_analyzer: SentimentAnalyzer):
        self.positions: dict[str, Position] = {}
        self._sentiment  = sentiment_analyzer
        self._session:   Optional[aiohttp.ClientSession] = None
        self._alert_callbacks: list = []

    # ── Session ───────────────────────────────────────────────────────────────

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Position management ───────────────────────────────────────────────────

    def register_alert_callback(self, cb):
        self._alert_callbacks.append(cb)

    def add_position(self, position: Position):
        # Initialise derived fields on first add
        if position.tokens_remaining == 0.0:
            position.tokens_remaining = position.amount_tokens
        if position.peak_price == 0.0:
            position.peak_price = position.buy_price_usd
        if position.last_liquidity == 0.0:
            position.last_liquidity = position.liquidity_at_buy
        self.positions[position.mint] = position
        logger.info(
            f"[Monitor] Tracking {position.symbol} — "
            f"buy ${position.buy_price_usd:.8f}, "
            f"liq ${position.liquidity_at_buy:,.0f}, "
            f"age {position.token_age_at_buy:.1f}h"
        )

    def remove_position(self, mint: str):
        if mint in self.positions:
            p = self.positions.pop(mint)
            logger.info(f"[Monitor] Removed position: {p.symbol}")

    def has_position(self, mint: str) -> bool:
        return mint in self.positions

    def get_position(self, mint: str) -> Optional[Position]:
        return self.positions.get(mint)

    def list_positions(self) -> list[Position]:
        return list(self.positions.values())

    # ── Price / liquidity / volume fetch ──────────────────────────────────────

    async def _fetch_current_data(self, mint: str) -> Optional[dict]:
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
                        pairs.sort(
                            key=lambda p: float(
                                (p.get("liquidity") or {}).get("usd") or 0
                            ),
                            reverse=True,
                        )
                        p   = pairs[0]
                        liq = p.get("liquidity") or {}
                        vol = p.get("volume")    or {}
                        return {
                            "price_usd":    float(p.get("priceUsd") or 0),
                            "liquidity_usd": float(liq.get("usd") or 0),
                            "volume_1h":    float(vol.get("h1")  or 0),
                            "volume_5m":    float(vol.get("m5")  or 0),
                        }
                    elif resp.status == 429:
                        await asyncio.sleep(2 ** attempt)
                    else:
                        return None
            except Exception as e:
                logger.debug(f"[Monitor] Price fetch error {mint}: {e}")
                await asyncio.sleep(2)
        return None

    # ── Helius large dump detection ────────────────────────────────────────────

    async def _check_large_dump(self, mint: str) -> Optional[str]:
        if not config.has_helius:
            return None
        session = await self._get_session()
        url    = f"{HELIUS_BASE}/addresses/{mint}/transactions"
        params = {"api-key": config.HELIUS_API_KEY, "type": "SWAP", "limit": 20}
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
                    if time.time() - tx.get("timestamp", 0) > 300:
                        continue
                    for transfer in (tx.get("tokenTransfers") or []):
                        if transfer.get("mint") != mint:
                            continue
                        amount = float(transfer.get("tokenAmount") or 0)
                        if amount > 1_000_000_000:
                            acct = transfer.get("fromUserAccount", "")
                            return (
                                f"🐋 Large dump detected: "
                                f"{acct[:8]}... sold {amount:.2e} tokens in last 5min"
                            )
        except Exception as e:
            logger.debug(f"[Monitor] Helius error: {e}")
        return None

    # ── Sentiment spike check ──────────────────────────────────────────────────

    async def _check_sentiment_spike(
        self, name: str, symbol: str, mint: str
    ) -> Optional[str]:
        result = await self._sentiment.analyze(name, symbol, mint)
        if result.score < config.SENTIMENT_BEARISH_THRESHOLD and result.tweet_count >= 5:
            return (
                f"📉 Sentiment turned bearish: {result.label} "
                f"(score {result.score:+.2f}, {result.tweet_count} tweets)"
            )
        return None

    # ── Fire alert ─────────────────────────────────────────────────────────────

    async def _fire_alert(self, alert: MonitorAlert):
        logger.warning(
            f"[Monitor] ALERT [{alert.alert_type}] {alert.symbol}: {alert.message[:80]}"
        )
        for cb in self._alert_callbacks:
            try:
                await cb(alert)
            except Exception as e:
                logger.error(f"[Monitor] Alert callback error: {e}")

    # ── Auto-sell helper ───────────────────────────────────────────────────────

    async def _auto_sell(
        self, pos: Position, tokens: float, reason: str
    ) -> tuple[bool, str]:
        """
        Execute an automatic sell. Returns (success, message).
        Clamps tokens to pos.tokens_remaining to avoid over-selling.
        """
        executor = _get_executor()
        tokens   = min(tokens, pos.tokens_remaining)
        if tokens <= 0:
            return False, "No tokens remaining to sell"
        result = await executor.sell_token(pos.mint, tokens)
        if result.success:
            pos.tokens_remaining -= tokens
            logger.info(
                f"[Monitor] Auto-sell OK: {pos.symbol} — {reason} — "
                f"{tokens:,.0f} tokens → {result.output_amount:.4f} SOL"
            )
            return True, f"solscan.io/tx/{result.tx_hash}"
        else:
            logger.error(f"[Monitor] Auto-sell FAILED: {pos.symbol} — {result.error}")
            return False, result.error

    # ── Determine trailing stop % for this position ────────────────────────────

    def _trailing_stop_pct(self, pos: Position) -> float:
        """
        Returns the trailing stop drawdown % to use for this position.

        Tighter stops for:
          - Very new tokens (< 5 min at buy time)
          - Fast pumps (>500% in first 10 min)
          - After TP2 (house money, protect gains)
        Normal otherwise.
        """
        # After TP2 — most capital secured, protect remaining gains tightly
        if pos.tp2_hit:
            return 20.0

        # Fast pump detected — violent reversal likely
        if pos.fast_pump_detected:
            return 15.0

        # Very new token at time of buy
        if pos.token_age_at_buy < (5 / 60):   # < 5 minutes
            return 15.0

        # Young token (< 30 min)
        if pos.token_age_at_buy < 0.5:
            return 20.0

        # Normal
        return 25.0

    # ── Core auto take-profit / trailing stop logic ────────────────────────────

    async def _check_auto_exits(
        self, pos: Position, current_price: float, current_liq: float,
        volume_1h: float, volume_5m: float
    ) -> Optional[MonitorAlert]:
        """
        Checks and executes all automatic exits.
        Returns a MonitorAlert if an exit fired, else None.
        """
        buy_price  = pos.buy_price_usd if pos.buy_price_usd > 0 else 1e-9
        multiplier = current_price / buy_price
        now        = time.time()
        age_min    = (now - pos.buy_time) / 60   # age of our POSITION in minutes

        # ── Update peak price (track from moment of buy) ───────────────────────
        if current_price > pos.peak_price:
            pos.peak_price = current_price

        # ── Detect fast pump (>500% in first 10 min) ──────────────────────────
        if not pos.fast_pump_detected and age_min <= 10 and multiplier >= 6.0:
            pos.fast_pump_detected = True
            logger.info(
                f"[Monitor] Fast pump flag set for {pos.symbol}: "
                f"{multiplier:.1f}x in {age_min:.1f}min — tighter trailing stop active"
            )

        # ── Initialise volume baseline ─────────────────────────────────────────
        if pos.volume_at_buy == 0.0 and volume_1h > 0:
            pos.volume_at_buy  = volume_1h
            pos.last_volume_1h = volume_1h

        pct_change  = (multiplier - 1) * 100
        liq_at_buy  = pos.liquidity_at_buy if pos.liquidity_at_buy > 0 else 1
        liq_drop    = ((liq_at_buy - current_liq) / liq_at_buy) * 100

        # ════════════════════════════════════════════════════════════════════════
        # EXIT 1 — New launch fast rug detection
        # Token under 30 min old + liquidity dropped >= 20% since last cycle
        # ════════════════════════════════════════════════════════════════════════
        token_age_min = pos.token_age_at_buy * 60 + age_min
        if pos.last_liquidity > 0 and token_age_min < 30:
            cycle_liq_drop = (
                (pos.last_liquidity - current_liq) / pos.last_liquidity
            ) * 100
            if cycle_liq_drop >= 20.0 and pos.tokens_remaining > 0:
                logger.warning(
                    f"[Monitor] NEW LAUNCH RUG ALARM: {pos.symbol} — "
                    f"liq dropped {cycle_liq_drop:.1f}% in one cycle"
                )
                ok, detail = await self._auto_sell(
                    pos, pos.tokens_remaining, "new launch rug alarm"
                )
                msg = (
                    f"🚨 <b>NEW LAUNCH RUG ALARM — AUTO EXIT</b>\n\n"
                    f"Token: <b>${pos.symbol}</b> (only {token_age_min:.0f}min old)\n"
                    f"Liquidity crashed {cycle_liq_drop:.1f}% in 30 seconds\n"
                    f"{'Auto-sold all tokens' if ok else 'SELL FAILED — act manually!'}\n"
                    f"{detail}"
                )
                pos.last_liquidity = current_liq
                return MonitorAlert(
                    mint=pos.mint, symbol=pos.symbol,
                    alert_type=ALERT_AUTO_EXIT,
                    current_price=current_price, buy_price=buy_price,
                    pct_change=pct_change, current_liquidity=current_liq,
                    liquidity_drop_pct=liq_drop, message=msg,
                )

        # Update last liquidity for next cycle comparison
        pos.last_liquidity = current_liq

        # ════════════════════════════════════════════════════════════════════════
        # EXIT 2 — Volume death check
        # 1h volume dropped 80%+ from when we bought → nobody trading → exit
        # ════════════════════════════════════════════════════════════════════════
        if (
            pos.volume_at_buy > 0
            and volume_1h > 0
            and volume_1h < pos.volume_at_buy * 0.20   # 80% drop
            and pos.tokens_remaining > 0
            and age_min > 10                            # give it 10min to settle
        ):
            logger.warning(
                f"[Monitor] VOLUME DEATH: {pos.symbol} — "
                f"1h vol dropped from ${pos.volume_at_buy:,.0f} to ${volume_1h:,.0f}"
            )
            ok, detail = await self._auto_sell(
                pos, pos.tokens_remaining, "volume death"
            )
            msg = (
                f"💀 <b>VOLUME DEATH — AUTO EXIT</b>\n\n"
                f"Token: <b>${pos.symbol}</b>\n"
                f"1h volume collapsed: ${pos.volume_at_buy:,.0f} → ${volume_1h:,.0f}\n"
                f"Nobody is trading this anymore\n"
                f"{'Auto-sold all tokens' if ok else 'SELL FAILED — act manually!'}\n"
                f"{detail}"
            )
            return MonitorAlert(
                mint=pos.mint, symbol=pos.symbol,
                alert_type=ALERT_AUTO_EXIT,
                current_price=current_price, buy_price=buy_price,
                pct_change=pct_change, current_liquidity=current_liq,
                liquidity_drop_pct=liq_drop, message=msg,
            )

        # Update volume tracking
        if volume_1h > 0:
            pos.last_volume_1h = volume_1h

        # ════════════════════════════════════════════════════════════════════════
        # EXIT 3 — TP1 @ 2x: sell 50%, capital recovered
        # ════════════════════════════════════════════════════════════════════════
        if not pos.tp1_hit and multiplier >= 2.0:
            tokens_to_sell = pos.tokens_remaining * 0.50
            logger.info(f"[Monitor] TP1 @ 2x for {pos.symbol}")
            ok, detail = await self._auto_sell(pos, tokens_to_sell, "TP1 2x")
            pos.tp1_hit         = True
            pos.capital_recovered = True
            msg = (
                f"✅ <b>AUTO TAKE-PROFIT 1 — 2x HIT</b>\n\n"
                f"Token: <b>${pos.symbol}</b>\n"
                f"Sold 50% of position\n"
                f"{'Capital recovered — moonbag riding free' if ok else 'SELL FAILED — act manually!'}\n"
                f"Remaining: {pos.tokens_remaining:,.0f} tokens\n"
                f"{detail}"
            )
            return MonitorAlert(
                mint=pos.mint, symbol=pos.symbol,
                alert_type=ALERT_TAKE_PROFIT,
                current_price=current_price, buy_price=buy_price,
                pct_change=pct_change, current_liquidity=current_liq,
                liquidity_drop_pct=liq_drop, message=msg,
            )

        # ════════════════════════════════════════════════════════════════════════
        # EXIT 4 — TP2 @ 3x: sell another 30%
        # ════════════════════════════════════════════════════════════════════════
        if pos.tp1_hit and not pos.tp2_hit and multiplier >= 3.0:
            tokens_to_sell = pos.amount_tokens * 0.30
            logger.info(f"[Monitor] TP2 @ 3x for {pos.symbol}")
            ok, detail = await self._auto_sell(pos, tokens_to_sell, "TP2 3x")
            pos.tp2_hit = True
            msg = (
                f"✅ <b>AUTO TAKE-PROFIT 2 — 3x HIT</b>\n\n"
                f"Token: <b>${pos.symbol}</b>\n"
                f"Sold another 30% of original position\n"
                f"{'Profit locked' if ok else 'SELL FAILED — act manually!'}\n"
                f"Moonbag remaining: {pos.tokens_remaining:,.0f} tokens\n"
                f"{detail}"
            )
            return MonitorAlert(
                mint=pos.mint, symbol=pos.symbol,
                alert_type=ALERT_TAKE_PROFIT,
                current_price=current_price, buy_price=buy_price,
                pct_change=pct_change, current_liquidity=current_liq,
                liquidity_drop_pct=liq_drop, message=msg,
            )

        # ════════════════════════════════════════════════════════════════════════
        # EXIT 5 — Trailing stop
        # Fires from the moment of buy (not just after TP1)
        # Tightness depends on token age and pump velocity
        # ════════════════════════════════════════════════════════════════════════
        if pos.peak_price > 0 and pos.tokens_remaining > 0:
            trail_pct     = self._trailing_stop_pct(pos)
            drawdown      = (
                (pos.peak_price - current_price) / pos.peak_price
            ) * 100

            # Only fire trailing stop if price already moved meaningfully
            # (avoid firing on flat/noise if we just bought)
            already_moved = multiplier >= 1.10   # at least 10% up at some point

            if already_moved and drawdown >= trail_pct:
                logger.warning(
                    f"[Monitor] TRAILING STOP: {pos.symbol} — "
                    f"down {drawdown:.1f}% from peak ${pos.peak_price:.8f}"
                )
                ok, detail = await self._auto_sell(
                    pos, pos.tokens_remaining, f"trailing stop -{trail_pct}%"
                )
                peak_mult = pos.peak_price / buy_price
                msg = (
                    f"🛑 <b>TRAILING STOP TRIGGERED</b>\n\n"
                    f"Token: <b>${pos.symbol}</b>\n"
                    f"Peak: {peak_mult:.2f}x (${pos.peak_price:.8f})\n"
                    f"Current: ${current_price:.8f} (down {drawdown:.1f}% from peak)\n"
                    f"Trailing stop: {trail_pct}%"
                    f"{' (fast pump mode)' if pos.fast_pump_detected else ''}\n"
                    f"{'Auto-sold all remaining tokens' if ok else 'SELL FAILED — act manually!'}\n"
                    f"{detail}"
                )
                return MonitorAlert(
                    mint=pos.mint, symbol=pos.symbol,
                    alert_type=ALERT_AUTO_EXIT,
                    current_price=current_price, buy_price=buy_price,
                    pct_change=pct_change, current_liquidity=current_liq,
                    liquidity_drop_pct=liq_drop, message=msg,
                )

        return None

    # ── Per-position check ─────────────────────────────────────────────────────

    async def check_position(self, mint: str) -> Optional[MonitorAlert]:
        pos = self.positions.get(mint)
        if not pos:
            return None

        data = await self._fetch_current_data(mint)
        if not data:
            logger.debug(f"[Monitor] No data for {pos.symbol}, skipping")
            return None

        current_price = data["price_usd"]
        current_liq   = data["liquidity_usd"]
        volume_1h     = data["volume_1h"]
        volume_5m     = data["volume_5m"]

        buy_price   = pos.buy_price_usd if pos.buy_price_usd > 0 else 1e-9
        pct_change  = ((current_price - buy_price) / buy_price) * 100
        liq_at_buy  = pos.liquidity_at_buy if pos.liquidity_at_buy > 0 else 1
        liq_drop    = ((liq_at_buy - current_liq) / liq_at_buy) * 100

        # ── Run all automatic exits first ─────────────────────────────────────
        auto_alert = await self._check_auto_exits(
            pos, current_price, current_liq, volume_1h, volume_5m
        )
        if auto_alert:
            await self._fire_alert(auto_alert)
            # If position fully closed, remove it
            if pos.tokens_remaining <= 0:
                self.remove_position(mint)
            return auto_alert

        # ── Manual alert checks (require user to tap SELL) ────────────────────
        alert: Optional[MonitorAlert] = None

        # Stop loss — dynamic: tighter for new tokens
        stop_pct = config.STOP_LOSS_PCT
        if pos.token_age_at_buy < (5 / 60):   # under 5min at buy
            stop_pct = min(stop_pct, 10.0)
        elif pos.token_age_at_buy < 0.5:       # under 30min at buy
            stop_pct = min(stop_pct, 12.0)

        if not pos.stop_loss_alerted and pct_change <= -stop_pct:
            alert = MonitorAlert(
                mint=mint, symbol=pos.symbol,
                alert_type=ALERT_STOP_LOSS,
                current_price=current_price, buy_price=buy_price,
                pct_change=pct_change, current_liquidity=current_liq,
                liquidity_drop_pct=liq_drop,
                message=(
                    f"🛑 Stop loss hit! {pos.symbol} down {pct_change:.1f}% "
                    f"from buy (${buy_price:.8f} to ${current_price:.8f})"
                ),
            )
            pos.stop_loss_alerted = True

        elif not pos.liquidity_alerted and liq_drop >= config.LIQUIDITY_DROP_ALERT_PCT:
            alert = MonitorAlert(
                mint=mint, symbol=pos.symbol,
                alert_type=ALERT_LIQUIDITY_DROP,
                current_price=current_price, buy_price=buy_price,
                pct_change=pct_change, current_liquidity=current_liq,
                liquidity_drop_pct=liq_drop,
                message=(
                    f"🚨 Liquidity alarm! {pos.symbol} liq dropped "
                    f"{liq_drop:.1f}% — ${liq_at_buy:,.0f} to ${current_liq:,.0f}"
                ),
            )
            pos.liquidity_alerted = True

        elif not pos.dump_alerted:
            if time.time() - pos.last_alert_time >= 300:
                dump_msg = await self._check_large_dump(mint)
                if dump_msg:
                    alert = MonitorAlert(
                        mint=mint, symbol=pos.symbol,
                        alert_type=ALERT_LARGE_DUMP,
                        current_price=current_price, buy_price=buy_price,
                        pct_change=pct_change, current_liquidity=current_liq,
                        liquidity_drop_pct=liq_drop, message=dump_msg,
                    )
                    pos.dump_alerted      = True
                    pos.last_alert_time   = time.time()

        elif not pos.sentiment_alerted:
            if time.time() - pos.last_alert_time >= 600:
                sent_msg = await self._check_sentiment_spike(
                    pos.name, pos.symbol, mint
                )
                if sent_msg:
                    alert = MonitorAlert(
                        mint=mint, symbol=pos.symbol,
                        alert_type=ALERT_SENTIMENT_BEARISH,
                        current_price=current_price, buy_price=buy_price,
                        pct_change=pct_change, current_liquidity=current_liq,
                        liquidity_drop_pct=liq_drop, message=sent_msg,
                    )
                    pos.sentiment_alerted = True
                    pos.last_alert_time   = time.time()

        if alert:
            await self._fire_alert(alert)
            return alert

        logger.debug(
            f"[Monitor] {pos.symbol}: {pct_change:+.1f}% from buy | "
            f"peak {pos.peak_price / buy_price:.2f}x | "
            f"liq drop {liq_drop:.1f}%"
        )
        return None

    # ── Main loop ──────────────────────────────────────────────────────────────

    async def run_monitor_cycle(self, context=None):
        if not self.positions:
            return
        logger.debug(f"[Monitor] Checking {len(self.positions)} positions…")
        tasks = [
            asyncio.create_task(self.check_position(mint))
            for mint in list(self.positions.keys())
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
