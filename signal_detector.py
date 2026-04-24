"""
signal_detector.py — Multi-wallet convergence detection with trust-weighted scoring.

Ported and expanded from the TypeScript memcoins-trading-agent.

The core insight from SOUL.md:
  "When 2-5 wallets you respect all touch the same token within minutes of
  each other — that's not coincidence. That's a call."

How it works:
  1. Every WalletBuyAlert from wallet_tracker feeds into record_buy()
  2. A rolling window (default 5 min) tracks buys per token mint
  3. When 2+ wallets buy the same mint → ConvergenceSignal fires
  4. Signal strength = wallet count × weighted trust score

Trust scores (persisted in SQLite via signal_logger):
  - New wallet starts at 1.0
  - Win (>1.5x outcome)  → trust += 0.25 (capped at 3.0)
  - Loss (<1.0x outcome) → trust -= 0.15
  - Rug (0x)             → trust -= 0.40 (floor 0.2)
  - Wallets below 0.5 trust require 3+ others to trigger a signal

Position sizing from SOUL.md:
  2 wallets → 15% of MAX_SOL
  3 wallets → 35% of MAX_SOL
  4 wallets → 60% of MAX_SOL
  5 wallets → 100% of MAX_SOL
  Final size adjusted by weighted trust and composite score.
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Optional

from config import config

logger = logging.getLogger(__name__)

DB_FILE = os.environ.get(
    "LOGGER_DB_FILE",
    "/data/signal_log.db" if os.path.isdir("/data") else "signal_log.db",
)

# Rolling convergence window
SIGNAL_WINDOW_SECONDS = int(os.environ.get("SIGNAL_WINDOW_SECONDS", "300"))   # 5 min
MIN_WALLETS_FOR_SIGNAL = int(os.environ.get("MIN_WALLETS_FOR_SIGNAL", "2"))

# Trust bounds
TRUST_MAX   = 3.0
TRUST_MIN   = 0.2
TRUST_START = 1.0

# Wallets below this trust score need 3+ companions to trigger
TRUST_LONE_THRESHOLD = 0.5


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class BuyEvent:
    wallet_address: str
    wallet_name:    str
    token_mint:     str
    token_symbol:   str
    token_name:     str
    sol_spent:      float
    tx_signature:   str
    timestamp:      float = field(default_factory=time.time)


@dataclass
class ConvergenceSignal:
    token_mint:      str
    token_symbol:    str
    token_name:      str

    wallet_count:    int
    wallets:         list[str]            # addresses
    wallet_names:    list[str]            # human labels
    wallet_trusts:   list[float]          # trust score per wallet

    weighted_trust:  float                # sum(trust) / count
    total_sol_spent: float                # combined SOL across all buys
    window_seconds:  float                # how fast they converged

    recommended_sol:  float               # calculated position size
    signal_strength:  str                 # "🔥 Strong" / "⚡ Moderate" / "👀 Weak"

    first_buy_at:    float
    detected_at:     float = field(default_factory=time.time)


# ── SignalDetector ─────────────────────────────────────────────────────────────

class SignalDetector:
    """
    Tracks wallet buy events in a rolling window.
    Fires a ConvergenceSignal when ≥ MIN_WALLETS_FOR_SIGNAL wallets
    buy the same token within SIGNAL_WINDOW_SECONDS.
    """

    def __init__(self):
        # mint → deque of BuyEvent (within rolling window)
        self._events: dict[str, collections.deque] = collections.defaultdict(
            lambda: collections.deque()
        )
        # trust scores: wallet_address → float
        self._trust_scores: dict[str, float] = {}

        # Cooldown: don't re-fire convergence for the same mint for 30 min
        self._fired: dict[str, float] = {}
        self.FIRED_COOLDOWN = 1800  # 30 minutes

        # Callbacks registered by bot.py
        self._callbacks: list = []

        self._load_trust_scores()

    # ── Trust persistence ──────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_trust_table(self):
        try:
            with self._conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS wallet_trust (
                        address     TEXT PRIMARY KEY,
                        name        TEXT,
                        trust_score REAL DEFAULT 1.0,
                        win_count   INTEGER DEFAULT 0,
                        loss_count  INTEGER DEFAULT 0,
                        rug_count   INTEGER DEFAULT 0,
                        updated_at  REAL
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.error(f"[Signal] Trust table create error: {e}")

    def _load_trust_scores(self):
        self._ensure_trust_table()
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT address, trust_score FROM wallet_trust"
                ).fetchall()
                for row in rows:
                    self._trust_scores[row["address"]] = row["trust_score"]
            if self._trust_scores:
                logger.info(
                    f"[Signal] Loaded trust scores for "
                    f"{len(self._trust_scores)} wallets"
                )
        except Exception as e:
            logger.warning(f"[Signal] Could not load trust scores: {e}")

    def get_trust(self, wallet_address: str) -> float:
        return self._trust_scores.get(wallet_address, TRUST_START)

    def set_trust(self, wallet_address: str, wallet_name: str, score: float):
        score = max(TRUST_MIN, min(TRUST_MAX, score))
        self._trust_scores[wallet_address] = score
        try:
            with self._conn() as conn:
                conn.execute("""
                    INSERT INTO wallet_trust (address, name, trust_score, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(address) DO UPDATE SET
                        name        = excluded.name,
                        trust_score = excluded.trust_score,
                        updated_at  = excluded.updated_at
                """, (wallet_address, wallet_name, score, time.time()))
                conn.commit()
        except Exception as e:
            logger.warning(f"[Signal] Trust save error: {e}")

    def update_trust_from_outcome(
        self,
        wallet_address: str,
        wallet_name:    str,
        outcome_type:   str,   # "win" / "loss" / "rug"
        multiplier:     float,
    ):
        """
        Called after a trade is closed via /close.
        Adjusts trust score based on whether the wallet's call worked out.
        """
        current = self.get_trust(wallet_address)
        delta   = 0.0
        col     = ""

        if outcome_type == "win" and multiplier >= 1.5:
            # Scale reward with how big the win was
            if multiplier >= 5.0:
                delta = 0.40
            elif multiplier >= 3.0:
                delta = 0.25
            else:
                delta = 0.15
            col = "win_count"
        elif outcome_type == "rug":
            delta = -0.40
            col   = "rug_count"
        else:  # loss
            delta = -0.15
            col   = "loss_count"

        new_score = max(TRUST_MIN, min(TRUST_MAX, current + delta))
        self._trust_scores[wallet_address] = new_score

        try:
            with self._conn() as conn:
                if col:
                    conn.execute(f"""
                        INSERT INTO wallet_trust
                            (address, name, trust_score, {col}, updated_at)
                        VALUES (?, ?, ?, 1, ?)
                        ON CONFLICT(address) DO UPDATE SET
                            name        = excluded.name,
                            trust_score = ?,
                            {col}       = {col} + 1,
                            updated_at  = excluded.updated_at
                    """, (wallet_address, wallet_name, new_score, time.time(), new_score))
                conn.commit()
        except Exception as e:
            logger.warning(f"[Signal] Trust update error: {e}")

        direction = "↑" if delta > 0 else "↓"
        logger.info(
            f"[Signal] Trust {direction}: {wallet_name} "
            f"{current:.2f} → {new_score:.2f} ({outcome_type} {multiplier:.1f}x)"
        )

    def get_all_trust_scores(self) -> list[dict]:
        """Return all wallet trust scores for /wallets command display."""
        try:
            with self._conn() as conn:
                rows = conn.execute("""
                    SELECT address, name, trust_score, win_count, loss_count, rug_count
                    FROM wallet_trust ORDER BY trust_score DESC
                """).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    # ── Callbacks ──────────────────────────────────────────────────────────────

    def register_callback(self, cb):
        self._callbacks.append(cb)

    async def _fire_callbacks(self, signal: ConvergenceSignal):
        for cb in self._callbacks:
            try:
                await cb(signal)
            except Exception as e:
                logger.error(f"[Signal] Callback error: {e}")

    # ── Core detection ─────────────────────────────────────────────────────────

    def _prune(self, mint: str):
        """Remove events outside the rolling window."""
        cutoff = time.time() - SIGNAL_WINDOW_SECONDS
        dq = self._events[mint]
        while dq and dq[0].timestamp < cutoff:
            dq.popleft()

    def _on_cooldown(self, mint: str) -> bool:
        last = self._fired.get(mint, 0)
        return (time.time() - last) < self.FIRED_COOLDOWN

    def _compute_position_size(
        self,
        wallet_count:    int,
        weighted_trust:  float,
        composite_score: int = 5,
    ) -> float:
        """
        Size from SOUL.md, adjusted by trust and score.
        """
        base_pct = {
            2: 0.15,
            3: 0.35,
            4: 0.60,
        }.get(min(wallet_count, 4), 1.00)

        if wallet_count >= 5:
            base_pct = 1.00

        # Trust multiplier: avg trust of 1.0 = no change; 2.0 = 1.5x size
        trust_mult = min(1.5, 0.75 + (weighted_trust * 0.25))

        # Score multiplier: only penalise low scores
        score_mult = 0.5 if composite_score <= 3 else 1.0

        size = config.BUY_AMOUNT_SOL * base_pct * trust_mult * score_mult
        return round(max(config.BUY_AMOUNT_SOL * 0.10, min(config.BUY_AMOUNT_SOL, size)), 4)

    def _signal_strength(
        self, wallet_count: int, weighted_trust: float
    ) -> str:
        score = wallet_count * weighted_trust
        if score >= 6.0:
            return "🔥 Strong"
        if score >= 3.0:
            return "⚡ Moderate"
        return "👀 Weak"

    async def record_buy(self, event: BuyEvent) -> Optional[ConvergenceSignal]:
        """
        Record a wallet buy event.
        Returns a ConvergenceSignal if the threshold is reached, else None.
        """
        mint = event.token_mint

        # Filter low-trust lone wallets early
        trust = self.get_trust(event.wallet_address)
        if trust < TRUST_LONE_THRESHOLD:
            # Allow through only if there are already other wallets in window
            self._prune(mint)
            if len(self._events[mint]) == 0:
                logger.debug(
                    f"[Signal] Low-trust wallet {event.wallet_name} "
                    f"({trust:.2f}) on {mint[:8]} — waiting for companions"
                )
                # Still record so future wallets can form a quorum
                self._events[mint].append(event)
                return None

        self._events[mint].append(event)
        self._prune(mint)

        events_in_window = list(self._events[mint])
        # Deduplicate by wallet address (keep latest from each)
        seen: dict[str, BuyEvent] = {}
        for ev in events_in_window:
            seen[ev.wallet_address] = ev
        unique_events = list(seen.values())

        wallet_count = len(unique_events)

        if wallet_count < MIN_WALLETS_FOR_SIGNAL:
            logger.info(
                f"[Signal] {wallet_count}/{MIN_WALLETS_FOR_SIGNAL} wallets "
                f"on {event.token_symbol or mint[:8]} — watching"
            )
            return None

        if self._on_cooldown(mint):
            logger.debug(f"[Signal] {mint[:8]} still on cooldown — skipping")
            return None

        # Build signal
        wallets      = [ev.wallet_address for ev in unique_events]
        wallet_names = [ev.wallet_name    for ev in unique_events]
        trusts       = [self.get_trust(addr) for addr in wallets]
        weighted_trust = sum(trusts) / len(trusts) if trusts else 1.0
        total_sol    = sum(ev.sol_spent for ev in unique_events)
        first_ts     = min(ev.timestamp for ev in unique_events)
        window_secs  = time.time() - first_ts

        position_sol = self._compute_position_size(wallet_count, weighted_trust)
        strength     = self._signal_strength(wallet_count, weighted_trust)

        signal = ConvergenceSignal(
            token_mint      = mint,
            token_symbol    = event.token_symbol or "???",
            token_name      = event.token_name   or "Unknown",
            wallet_count    = wallet_count,
            wallets         = wallets,
            wallet_names    = wallet_names,
            wallet_trusts   = trusts,
            weighted_trust  = weighted_trust,
            total_sol_spent = total_sol,
            window_seconds  = window_secs,
            recommended_sol = position_sol,
            signal_strength = strength,
            first_buy_at    = first_ts,
        )

        self._fired[mint] = time.time()

        logger.info(
            f"[Signal] 🔔 CONVERGENCE on ${signal.token_symbol}: "
            f"{wallet_count} wallets in {window_secs:.0f}s "
            f"(trust={weighted_trust:.2f}, {strength})"
        )

        await self._fire_callbacks(signal)
        return signal

    def format_for_telegram(self, signal: ConvergenceSignal) -> str:
        """Build the Telegram message for a convergence alert."""
        wallet_lines = ""
        for name, trust, sol in zip(
            signal.wallet_names, signal.wallet_trusts,
            [0.0] * len(signal.wallet_names)  # sol per wallet not stored on signal
        ):
            trust_bar = "⭐" * min(3, int(trust))
            wallet_lines += f"  {trust_bar} {name} (trust {trust:.2f})\n"

        window_str = (
            f"{signal.window_seconds:.0f}s" if signal.window_seconds < 120
            else f"{signal.window_seconds / 60:.1f}min"
        )

        return (
            f"🚨 <b>WALLET CONVERGENCE SIGNAL</b>\n"
            f"{'━' * 28}\n"
            f"🪙 <b>${signal.token_symbol}</b>  {signal.token_name}\n"
            f"📍 <code>{signal.token_mint}</code>\n\n"
            f"👥 <b>{signal.wallet_count} wallets</b> bought within {window_str}\n"
            f"{wallet_lines}\n"
            f"💰 Combined spent: <b>{signal.total_sol_spent:.3f} SOL</b>\n"
            f"🎯 Avg wallet trust: <b>{signal.weighted_trust:.2f}/3.0</b>\n"
            f"📶 Signal strength: <b>{signal.signal_strength}</b>\n\n"
            f"💸 Recommended size: <b>{signal.recommended_sol} SOL</b>\n"
            f"<i>Running full safety + sentiment check…</i>"
        )

    def get_window_summary(self) -> str:
        """Summary of recent convergence activity — for /scan output."""
        active = 0
        for mint, dq in self._events.items():
            self._prune(mint)
            if len(dq) >= 2:
                active += 1
        return f"{active} mint(s) with 2+ wallet buys in last {SIGNAL_WINDOW_SECONDS // 60}min"


# Module-level singleton
signal_detector = SignalDetector()
