"""
ta_filter.py — TA-based signal quality filter for Solana Scout Bot.

Fetches OHLCV candles from DexScreener, computes ATR, RSI, trend,
entry patterns, and flag detection. Returns a scored TAResult.

No new pip dependencies — uses only aiohttp (already in requirements.txt).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

DEXSCREENER_OHLCV_BASE = "https://api.dexscreener.com/dex/ohlcv/solana"

# Simple in-process cache: pool_address -> (timestamp, list[dict])
_ohlcv_cache: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL = 60.0          # seconds
_RATE_LIMIT_DELAY = 1.0    # seconds between OHLCV fetches


@dataclass
class TAResult:
    atr_value:              float           = 0.0
    rsi:                    Optional[float] = None
    bearish_divergence:     bool            = False
    trend:                  str             = "UNKNOWN"   # UPTREND/DOWNTREND/CONSOLIDATION/UNKNOWN
    entry_pattern:          str             = "none"      # 38.2_candle/engulfing/close_above/none
    flag_detected:          bool            = False
    flag_is_fresh:          bool            = False
    is_extended:            bool            = False
    ta_score:               int             = 0
    ta_verdict:             str             = "UNKNOWN"   # STRONG/DECENT/CAUTION/AVOID/UNKNOWN
    ta_summary:             str             = ""
    suggested_stop_pct:     float           = 0.0
    nearest_resistance_usd: float           = 0.0


# ── HTTP helpers ──────────────────────────────────────────────────────────────

_session: Optional[aiohttp.ClientSession] = None


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session


# ── 1. Fetch OHLCV ────────────────────────────────────────────────────────────

async def fetch_ohlcv(
    pool_address: str,
    resolution: str = "15",
    limit: int = 96,
) -> list[dict]:
    """
    Fetch OHLCV candles from DexScreener.
    Returns a list of dicts sorted oldest→newest, or [] on failure.
    """
    if not pool_address or len(pool_address) < 20:
        # pump.fun bonding-curve tokens have no real pool address
        return []

    now = time.time()
    cached = _ohlcv_cache.get(pool_address)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]

    await asyncio.sleep(_RATE_LIMIT_DELAY)

    session = await _get_session()
    url = f"{DEXSCREENER_OHLCV_BASE}/{pool_address}"
    params = {"res": resolution, "limit": limit}

    try:
        async with session.get(
            url, params=params, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status != 200:
                logger.debug(f"[TA] OHLCV {resp.status} for {pool_address[:8]}")
                return []
            data = await resp.json(content_type=None)

        # DexScreener returns {"ohlcv": [...]} or similar; normalise
        raw = data if isinstance(data, list) else (
            data.get("ohlcv") or data.get("data") or []
        )

        candles = []
        for c in raw:
            try:
                candles.append({
                    "t": float(c.get("t") or c.get("time") or c.get("timestamp") or 0),
                    "o": float(c.get("o") or c.get("open") or 0),
                    "h": float(c.get("h") or c.get("high") or 0),
                    "l": float(c.get("l") or c.get("low") or 0),
                    "c": float(c.get("c") or c.get("close") or 0),
                    "v": float(c.get("v") or c.get("volume") or 0),
                })
            except Exception:
                continue

        candles.sort(key=lambda x: x["t"])
        _ohlcv_cache[pool_address] = (now, candles)
        logger.debug(f"[TA] Fetched {len(candles)} candles for {pool_address[:8]}")
        return candles

    except Exception as e:
        logger.debug(f"[TA] OHLCV fetch error: {e}")
        return []


# ── 2. ATR (14-period EMA of True Range) ─────────────────────────────────────

def _calc_atr(candles: list[dict], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0.0

    trs = []
    for i in range(1, len(candles)):
        high  = candles[i]["h"]
        low   = candles[i]["l"]
        prev_c = candles[i - 1]["c"]
        tr = max(high - low, abs(high - prev_c), abs(low - prev_c))
        trs.append(tr)

    # Wilder smoothing: SMA for first value, then EMA
    atr = sum(trs[:period]) / period
    k = 1 / period
    for tr in trs[period:]:
        atr = tr * k + atr * (1 - k)

    return atr


# ── 3. RSI + bearish divergence ───────────────────────────────────────────────

def _calc_rsi(candles: list[dict], period: int = 14) -> Optional[float]:
    closes = [c["c"] for c in candles]
    if len(closes) < period + 1:
        return None

    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _check_bearish_divergence(candles: list[dict]) -> bool:
    """
    Bearish divergence: price making higher highs while RSI makes lower highs
    over the last 10 candles.
    """
    window = candles[-10:]
    if len(window) < 6:
        return False

    highs = [c["h"] for c in window]
    closes = [c["c"] for c in window]

    # Compute a mini RSI series (simplified: just compare mid-point vs end)
    mid = len(window) // 2
    price_hh = highs[-1] > highs[mid]       # price making higher high
    if not price_hh:
        return False

    rsi_first = _calc_rsi(candles[:-5], 14)
    rsi_last  = _calc_rsi(candles, 14)
    if rsi_first is None or rsi_last is None:
        return False

    rsi_lower_high = rsi_last < rsi_first   # RSI making lower high
    return rsi_lower_high


# ── 4. Trend detection ────────────────────────────────────────────────────────

def _detect_trend(candles: list[dict]) -> str:
    if len(candles) < 20:
        return "UNKNOWN"

    window = candles[-20:]
    highs  = [c["h"] for c in window]
    lows   = [c["l"] for c in window]

    def find_swings(values, higher=True):
        """Find local pivots (swing highs or lows)."""
        pivots = []
        for i in range(1, len(values) - 1):
            if higher:
                if values[i] > values[i - 1] and values[i] > values[i + 1]:
                    pivots.append(values[i])
            else:
                if values[i] < values[i - 1] and values[i] < values[i + 1]:
                    pivots.append(values[i])
        return pivots

    swing_highs = find_swings(highs, higher=True)
    swing_lows  = find_swings(lows,  higher=False)

    hh_count = sum(
        1 for i in range(1, len(swing_highs)) if swing_highs[i] > swing_highs[i - 1]
    )
    hl_count = sum(
        1 for i in range(1, len(swing_lows)) if swing_lows[i] > swing_lows[i - 1]
    )
    ll_count = sum(
        1 for i in range(1, len(swing_lows)) if swing_lows[i] < swing_lows[i - 1]
    )
    lh_count = sum(
        1 for i in range(1, len(swing_highs)) if swing_highs[i] < swing_highs[i - 1]
    )

    if hh_count >= 2 and hl_count >= 2:
        return "UPTREND"
    if ll_count >= 2 and lh_count >= 2:
        return "DOWNTREND"
    return "CONSOLIDATION"


def _above_20sma(candles: list[dict]) -> Optional[bool]:
    """True if last close > 20-period SMA, False if below, None if not enough data."""
    if len(candles) < 20:
        return None
    sma = sum(c["c"] for c in candles[-20:]) / 20
    return candles[-1]["c"] > sma


# ── 5. Entry pattern detection ────────────────────────────────────────────────

def _detect_entry_pattern(candles: list[dict]) -> str:
    """
    Checks the two most recent completed candles.
    Returns pattern name or 'none'.
    """
    if len(candles) < 2:
        return "none"

    prev = candles[-2]
    curr = candles[-1]

    c_open  = curr["o"]
    c_close = curr["c"]
    c_high  = curr["h"]
    c_low   = curr["l"]

    p_open  = prev["o"]
    p_close = prev["c"]
    p_high  = prev["h"]

    candle_range = c_high - c_low
    if candle_range == 0:
        return "none"

    body_top    = max(c_open, c_close)
    body_bottom = min(c_open, c_close)

    # --- 38.2 candle ---
    fib_382 = c_low + candle_range * 0.382
    # Bullish: entire body above 38.2% level (upper 61.8% of candle)
    if body_bottom >= fib_382 and c_close > c_open:
        return "38.2_candle"
    # Bearish: entire body below 61.8% level (lower 61.8% of candle)
    fib_618 = c_low + candle_range * 0.618
    if body_top <= fib_618 and c_close < c_open:
        return "38.2_candle"

    # --- Engulfing ---
    prev_body = abs(p_close - p_open)
    curr_body = abs(c_close - c_open)
    color_change_bullish = p_close < p_open and c_close > c_open
    color_change_bearish = p_close > p_open and c_close < c_open

    if curr_body > prev_body and color_change_bullish:
        return "engulfing"
    if curr_body > prev_body and color_change_bearish:
        return "engulfing"

    # --- Close above / Close below ---
    if c_close > p_high:
        return "close_above"
    if c_close < prev["l"]:
        return "close_below"

    return "none"


# ── 6. Flag pattern detection ────────────────────────────────────────────────

def _detect_flag(candles: list[dict], atr: float) -> tuple[bool, bool, bool]:
    """
    Returns (flag_detected, flag_is_fresh, is_extended).
    is_extended = last 4 candles moved > 3× ATR.
    """
    if len(candles) < 15 or atr == 0:
        return False, False, False

    window = candles[-30:]

    # Find largest single-candle move (the "pole")
    moves = [abs(c["c"] - c["o"]) for c in window]
    if not moves:
        return False, False, False

    pole_idx  = max(range(len(moves)), key=lambda i: moves[i])
    pole_size = moves[pole_idx]

    if pole_size < atr * 0.5:
        return False, False, False

    # Consolidation candles must follow the pole
    post_pole = window[pole_idx + 1:]
    if len(post_pole) < 3:
        return False, False, False

    consol = post_pole[:10]
    if len(consol) < 3:
        return False, False, False

    consol_range = max(c["h"] for c in consol) - min(c["l"] for c in consol)
    flag_detected  = consol_range < pole_size * 0.4
    flag_is_fresh  = flag_detected and len(post_pole) < 5

    # Extended check: last 4 candles moved > 3× ATR
    recent_move = abs(candles[-1]["c"] - candles[-4]["o"]) if len(candles) >= 4 else 0
    is_extended  = recent_move > atr * 3

    return flag_detected, flag_is_fresh, is_extended


# ── 7 & 8. Score, verdict, stop suggestion ───────────────────────────────────

def _score_and_verdict(
    atr:                float,
    rsi:                Optional[float],
    bearish_divergence: bool,
    trend:              str,
    entry_pattern:      str,
    flag_detected:      bool,
    flag_is_fresh:      bool,
    is_extended:        bool,
    current_price:      float,
    candles:            list[dict],
) -> tuple[int, str, str, float, float]:
    """Returns (ta_score, ta_verdict, ta_summary, suggested_stop_pct, nearest_resistance_usd)."""

    score = 0

    if trend == "UPTREND":
        score += 1
    if entry_pattern != "none":
        score += 1
    if rsi is not None and 40 <= rsi <= 65:
        score += 1
    if flag_detected and flag_is_fresh:
        score += 1
    if bearish_divergence:
        score -= 1
    if is_extended:
        score -= 1
    if rsi is not None and rsi > 75:
        score -= 1

    if score >= 4:
        verdict = "STRONG"
    elif score >= 2:
        verdict = "DECENT"
    elif score == 1:
        verdict = "CAUTION"
    else:
        verdict = "AVOID"

    # ATR-based stop
    suggested_stop_pct = 0.0
    if atr > 0 and current_price > 0:
        raw_pct = (atr / current_price) * 100 * 1.5
        suggested_stop_pct = max(8.0, min(35.0, raw_pct))

    # Nearest resistance (highest wick above current price in last 20 candles)
    recent = candles[-20:] if len(candles) >= 20 else candles
    resistance_wicks = [c["h"] for c in recent if c["h"] > current_price]
    nearest_resistance = min(resistance_wicks) if resistance_wicks else 0.0

    # Build summary line
    parts = [f"Trend: {trend}", f"Pattern: {entry_pattern}"]
    if rsi is not None:
        parts.append(f"RSI: {rsi:.0f}")
    if flag_detected:
        parts.append("Flag: ✅ fresh" if flag_is_fresh else "Flag: detected")
    if is_extended:
        parts.append("⚠️ extended")
    if bearish_divergence:
        parts.append("⚠️ RSI divergence")
    summary = " | ".join(parts)

    return score, verdict, summary, suggested_stop_pct, nearest_resistance


# ── Public entry point ────────────────────────────────────────────────────────

async def run_ta_analysis(pool_address: str, current_price: float) -> TAResult:
    """
    Full TA pipeline. Returns TAResult with verdict=UNKNOWN if candles unavailable.
    Never raises — degrades gracefully.
    """
    try:
        candles = await fetch_ohlcv(pool_address)

        if not candles or len(candles) < 15:
            return TAResult(
                ta_verdict="UNKNOWN",
                ta_summary="Insufficient candle data (pre-graduation or new pool)",
            )

        atr               = _calc_atr(candles)
        rsi               = _calc_rsi(candles)
        bearish_div       = _check_bearish_divergence(candles)
        trend             = _detect_trend(candles)
        entry_pattern     = _detect_entry_pattern(candles)
        flag_det, flag_fresh, is_ext = _detect_flag(candles, atr)

        score, verdict, summary, stop_pct, resistance = _score_and_verdict(
            atr=atr,
            rsi=rsi,
            bearish_divergence=bearish_div,
            trend=trend,
            entry_pattern=entry_pattern,
            flag_detected=flag_det,
            flag_is_fresh=flag_fresh,
            is_extended=is_ext,
            current_price=current_price,
            candles=candles,
        )

        result = TAResult(
            atr_value=atr,
            rsi=rsi,
            bearish_divergence=bearish_div,
            trend=trend,
            entry_pattern=entry_pattern,
            flag_detected=flag_det,
            flag_is_fresh=flag_fresh,
            is_extended=is_ext,
            ta_score=score,
            ta_verdict=verdict,
            ta_summary=summary,
            suggested_stop_pct=stop_pct,
            nearest_resistance_usd=resistance,
        )
        logger.info(
            f"[TA] {pool_address[:8]} → {verdict} (score={score}) | {summary}"
        )
        return result

    except Exception as e:
        logger.warning(f"[TA] run_ta_analysis error: {e}")
        return TAResult(ta_verdict="UNKNOWN", ta_summary=f"TA error: {str(e)[:60]}")
