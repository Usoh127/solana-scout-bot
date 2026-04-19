"""
logger.py — Signal quality logger.

Every alert the bot fires gets automatically logged to a local SQLite database
with a full snapshot of the signal data at the moment of detection.

You close a trade manually via Telegram:
    /close <CA> <outcome>
    Examples:
        /close ABC123 3.5x
        /close ABC123 rugged
        /close ABC123 -50%

Stats are available any time via:
    /stats          — overall performance summary
    /stats wallets  — which wallets lead to winners
    /stats sources  — pumpfun vs gecko vs dexscreener performance

A weekly digest fires automatically every Sunday at 9am WAT.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

DB_FILE = os.environ.get(
    "LOGGER_DB_FILE",
    "/data/signal_log.db" if os.path.isdir("/data") else "signal_log.db"
)


# ─── Schema ───────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    mint                TEXT NOT NULL UNIQUE,
    symbol              TEXT,
    name                TEXT,
    source              TEXT,           -- pumpfun / gecko / dexscreener
    dex                 TEXT,
    alerted_at          REAL,           -- unix timestamp
    age_hours           REAL,
    market_cap_usd      REAL,
    liquidity_usd       REAL,
    volume_24h_usd      REAL,
    price_usd           REAL,
    price_change_1h     REAL,
    price_change_6h     REAL,
    price_change_24h    REAL,
    confidence          INTEGER,
    sentiment_label     TEXT,
    sentiment_score     REAL,
    tweet_count         INTEGER,
    safety_passed       INTEGER,        -- 1 or 0
    top10_holder_pct    REAL,
    bundle_risk         REAL,
    fake_volume_risk    REAL,
    deployer_risk       REAL,
    data_only_call      INTEGER,        -- 1 or 0
    pumpfun_reply_count INTEGER,
    pumpfun_is_koth     INTEGER,        -- 1 or 0
    did_buy             INTEGER DEFAULT 0,  -- 1 if user tapped BUY

    -- Outcome fields (filled by /close command)
    outcome             TEXT,           -- e.g. "3.5x", "rugged", "-50%"
    outcome_multiplier  REAL,           -- parsed numeric e.g. 3.5, 0.5, 0.0
    outcome_type        TEXT,           -- "win" / "loss" / "rug" / "unknown"
    closed_at           REAL,
    time_to_close_hours REAL
);

CREATE TABLE IF NOT EXISTS wallet_performance (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address  TEXT,
    wallet_name     TEXT,
    alert_mint      TEXT,
    outcome_type    TEXT,
    outcome_multiplier REAL,
    logged_at       REAL
);
"""


# ─── SignalLogger ──────────────────────────────────────────────────────────────

class SignalLogger:
    def __init__(self):
        self._db_path = DB_FILE
        self._init_db()

    def _init_db(self):
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.executescript(SCHEMA)
                conn.commit()
            logger.info(f"[Logger] DB ready at {self._db_path}")
        except Exception as e:
            logger.error(f"[Logger] DB init error: {e}")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Log an alert ──────────────────────────────────────────────────────────

    def log_alert(self, opp) -> bool:
        """
        Called automatically every time the bot sends a briefing.
        Captures the full signal snapshot at alert time.
        Returns True if logged, False if already exists (duplicate alert).
        """
        try:
            # Determine source from dex field
            dex = (opp.dex or "").lower()
            if "pump" in dex:
                source = "pumpfun"
            elif hasattr(opp, "pumpfun_reply_count") and opp.pumpfun_reply_count > 0:
                source = "pumpfun"
            else:
                source = dex if dex else "unknown"

            with self._conn() as conn:
                conn.execute("""
                    INSERT OR IGNORE INTO alerts (
                        mint, symbol, name, source, dex, alerted_at, age_hours,
                        market_cap_usd, liquidity_usd, volume_24h_usd, price_usd,
                        price_change_1h, price_change_6h, price_change_24h,
                        confidence, sentiment_label, sentiment_score, tweet_count,
                        safety_passed, top10_holder_pct, bundle_risk,
                        fake_volume_risk, deployer_risk, data_only_call,
                        pumpfun_reply_count, pumpfun_is_koth
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?,
                        ?, ?, ?,
                        ?, ?
                    )
                """, (
                    opp.mint,
                    opp.symbol,
                    opp.name,
                    source,
                    opp.dex,
                    time.time(),
                    opp.age_hours,
                    opp.market_cap_usd,
                    opp.liquidity_usd,
                    opp.volume_24h_usd,
                    opp.price_usd,
                    opp.price_change_1h,
                    opp.price_change_6h,
                    opp.price_change_24h,
                    opp.confidence,
                    opp.sentiment_label,
                    opp.sentiment_score,
                    opp.tweet_count,
                    1 if opp.safety_passed else 0,
                    opp.safety_top10_holder_pct,
                    opp.safety_bundle_risk,
                    opp.safety_fake_volume_risk,
                    opp.safety_deployer_risk,
                    1 if opp.data_only_call else 0,
                    getattr(opp, "pumpfun_reply_count", 0),
                    1 if getattr(opp, "pumpfun_is_koth", False) else 0,
                ))
                conn.commit()
                logger.info(f"[Logger] Logged alert: {opp.symbol} ({opp.mint[:8]})")
                return True
        except Exception as e:
            logger.error(f"[Logger] log_alert error: {e}")
            return False

    def mark_bought(self, mint: str):
        """Called when user confirms a BUY — marks did_buy = 1."""
        try:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE alerts SET did_buy = 1 WHERE mint = ?", (mint,)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"[Logger] mark_bought error: {e}")

    # ── Close a trade ─────────────────────────────────────────────────────────

    def close_trade(self, mint: str, outcome_raw: str) -> tuple[bool, str]:
        """
        Parse and store the outcome of an alert.
        outcome_raw examples: "3.5x", "rugged", "-50%", "2x", "breakeven"
        Returns (success, message).
        """
        outcome_raw  = outcome_raw.strip().lower()
        multiplier   = None
        outcome_type = "unknown"

        if outcome_raw in ("rug", "rugged", "rug pull"):
            multiplier   = 0.0
            outcome_type = "rug"
        elif outcome_raw in ("breakeven", "even", "0"):
            multiplier   = 1.0
            outcome_type = "loss"
        else:
            # Try to parse "3.5x" or "3.5X"
            if outcome_raw.endswith("x"):
                try:
                    multiplier = float(outcome_raw[:-1])
                    outcome_type = "win" if multiplier >= 1.5 else "loss"
                except ValueError:
                    pass
            # Try to parse "-50%" or "50%"
            elif outcome_raw.endswith("%"):
                try:
                    pct = float(outcome_raw[:-1])
                    multiplier   = 1 + (pct / 100)
                    outcome_type = "win" if multiplier >= 1.5 else "loss"
                except ValueError:
                    pass

        if multiplier is None:
            return False, (
                f"Couldn't parse outcome '{outcome_raw}'.\n"
                f"Use formats like: 3.5x, rugged, -50%, 2x"
            )

        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT alerted_at FROM alerts WHERE mint = ?", (mint,)
                ).fetchone()

                if not row:
                    return False, f"No alert found for CA `{mint[:8]}...` — was it logged?"

                alerted_at        = row["alerted_at"]
                now               = time.time()
                time_to_close_hrs = (now - alerted_at) / 3600

                conn.execute("""
                    UPDATE alerts SET
                        outcome             = ?,
                        outcome_multiplier  = ?,
                        outcome_type        = ?,
                        closed_at           = ?,
                        time_to_close_hours = ?
                    WHERE mint = ?
                """, (
                    outcome_raw,
                    multiplier,
                    outcome_type,
                    now,
                    time_to_close_hrs,
                    mint,
                ))
                conn.commit()

            emoji = "✅" if outcome_type == "win" else "☠️" if outcome_type == "rug" else "❌"
            return True, (
                f"{emoji} Outcome logged for `{mint[:8]}...`\n"
                f"Result: {outcome_raw} ({outcome_type}) "
                f"in {time_to_close_hrs:.1f}h"
            )
        except Exception as e:
            logger.error(f"[Logger] close_trade error: {e}")
            return False, f"DB error: {e}"

    # ── Stats ─────────────────────────────────────────────────────────────────

    def get_stats(self, mode: str = "overall") -> str:
        """Generate a stats summary. mode: overall / wallets / sources"""
        try:
            with self._conn() as conn:
                if mode == "overall":
                    return self._stats_overall(conn)
                elif mode == "sources":
                    return self._stats_sources(conn)
                else:
                    return self._stats_overall(conn)
        except Exception as e:
            logger.error(f"[Logger] get_stats error: {e}")
            return "Error generating stats."

    def _stats_overall(self, conn) -> str:
        total = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
        if total == 0:
            return "📊 No alerts logged yet. The bot needs to fire some alerts first."

        closed = conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE outcome IS NOT NULL"
        ).fetchone()[0]

        if closed == 0:
            return (
                f"📊 <b>Signal Log Stats</b>\n\n"
                f"Total alerts fired: <b>{total}</b>\n"
                f"Outcomes logged: <b>0</b>\n\n"
                f"<i>Use /close &lt;CA&gt; &lt;outcome&gt; to log results.</i>"
            )

        wins = conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE outcome_type = 'win'"
        ).fetchone()[0]
        rugs = conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE outcome_type = 'rug'"
        ).fetchone()[0]
        losses = conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE outcome_type = 'loss'"
        ).fetchone()[0]

        win_rate = (wins / closed * 100) if closed > 0 else 0

        avg_mult_row = conn.execute(
            "SELECT AVG(outcome_multiplier) FROM alerts WHERE outcome IS NOT NULL"
        ).fetchone()[0]
        avg_mult = avg_mult_row or 0

        best_row = conn.execute(
            "SELECT symbol, outcome_multiplier FROM alerts "
            "WHERE outcome_type = 'win' ORDER BY outcome_multiplier DESC LIMIT 1"
        ).fetchone()
        best = f"${best_row['symbol']} ({best_row['outcome_multiplier']:.1f}x)" if best_row else "N/A"

        avg_time_row = conn.execute(
            "SELECT AVG(time_to_close_hours) FROM alerts WHERE outcome IS NOT NULL"
        ).fetchone()[0]
        avg_time = avg_time_row or 0

        # Confidence score correlation
        avg_conf_wins = conn.execute(
            "SELECT AVG(confidence) FROM alerts WHERE outcome_type = 'win'"
        ).fetchone()[0] or 0
        avg_conf_loss = conn.execute(
            "SELECT AVG(confidence) FROM alerts WHERE outcome_type IN ('loss','rug')"
        ).fetchone()[0] or 0

        # Source breakdown
        source_rows = conn.execute("""
            SELECT source, COUNT(*) as cnt,
                   SUM(CASE WHEN outcome_type='win' THEN 1 ELSE 0 END) as wins
            FROM alerts WHERE outcome IS NOT NULL
            GROUP BY source
        """).fetchall()
        source_lines = ""
        for r in source_rows:
            sr = (r["wins"] / r["cnt"] * 100) if r["cnt"] > 0 else 0
            source_lines += f"  • {r['source']}: {r['wins']}/{r['cnt']} wins ({sr:.0f}%)\n"

        return (
            f"📊 <b>Signal Log — Overall Stats</b>\n"
            f"{'━' * 28}\n"
            f"Total alerts:    <b>{total}</b>\n"
            f"Outcomes logged: <b>{closed}</b>\n\n"
            f"✅ Wins:   <b>{wins}</b>\n"
            f"❌ Losses: <b>{losses}</b>\n"
            f"☠️ Rugs:   <b>{rugs}</b>\n"
            f"🎯 Win rate: <b>{win_rate:.1f}%</b>\n\n"
            f"📈 Avg multiplier: <b>{avg_mult:.2f}x</b>\n"
            f"🏆 Best trade: <b>{best}</b>\n"
            f"⏱ Avg time to close: <b>{avg_time:.1f}h</b>\n\n"
            f"🧠 Confidence (winners): <b>{avg_conf_wins:.1f}/10</b>\n"
            f"🧠 Confidence (losers):  <b>{avg_conf_loss:.1f}/10</b>\n\n"
            f"<b>By source:</b>\n{source_lines}"
        )

    def _stats_sources(self, conn) -> str:
        rows = conn.execute("""
            SELECT source,
                   COUNT(*) as total,
                   SUM(CASE WHEN outcome_type='win' THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN outcome_type='rug' THEN 1 ELSE 0 END) as rugs,
                   AVG(CASE WHEN outcome IS NOT NULL THEN outcome_multiplier END) as avg_mult
            FROM alerts
            GROUP BY source
            ORDER BY wins DESC
        """).fetchall()

        if not rows:
            return "📊 No source data yet."

        lines = ["📊 <b>Performance by Source</b>\n" + "━" * 28]
        for r in rows:
            wr = (r["wins"] / r["total"] * 100) if r["total"] > 0 else 0
            lines.append(
                f"\n<b>{r['source']}</b>\n"
                f"  Alerts: {r['total']} | Wins: {r['wins']} | Rugs: {r['rugs']}\n"
                f"  Win rate: {wr:.0f}% | Avg: {r['avg_mult']:.2f}x"
                if r["avg_mult"] else
                f"\n<b>{r['source']}</b>\n"
                f"  Alerts: {r['total']} | Wins: {r['wins']} | Rugs: {r['rugs']}\n"
                f"  Win rate: {wr:.0f}%"
            )
        return "\n".join(lines)

    # ── Weekly digest ─────────────────────────────────────────────────────────

    def get_weekly_digest(self) -> str:
        """Summary of the past 7 days — sent automatically every Sunday."""
        try:
            cutoff = time.time() - (7 * 24 * 3600)
            with self._conn() as conn:
                total = conn.execute(
                    "SELECT COUNT(*) FROM alerts WHERE alerted_at > ?", (cutoff,)
                ).fetchone()[0]

                closed = conn.execute(
                    "SELECT COUNT(*) FROM alerts WHERE alerted_at > ? AND outcome IS NOT NULL",
                    (cutoff,)
                ).fetchone()[0]

                if total == 0:
                    return "📅 <b>Weekly Digest</b>\n\nNo alerts fired this week."

                wins = conn.execute(
                    "SELECT COUNT(*) FROM alerts WHERE alerted_at > ? AND outcome_type = 'win'",
                    (cutoff,)
                ).fetchone()[0]
                rugs = conn.execute(
                    "SELECT COUNT(*) FROM alerts WHERE alerted_at > ? AND outcome_type = 'rug'",
                    (cutoff,)
                ).fetchone()[0]

                win_rate = (wins / closed * 100) if closed > 0 else 0

                best_row = conn.execute(
                    "SELECT symbol, outcome_multiplier FROM alerts "
                    "WHERE alerted_at > ? AND outcome_type = 'win' "
                    "ORDER BY outcome_multiplier DESC LIMIT 1",
                    (cutoff,)
                ).fetchone()
                best = f"${best_row['symbol']} ({best_row['outcome_multiplier']:.1f}x)" if best_row else "None"

                now_str = datetime.now(timezone.utc).strftime("%b %d, %Y")

                return (
                    f"📅 <b>Weekly Digest — {now_str}</b>\n"
                    f"{'━' * 28}\n"
                    f"Alerts this week: <b>{total}</b>\n"
                    f"Outcomes logged:  <b>{closed}</b>\n"
                    f"✅ Wins: <b>{wins}</b>  ☠️ Rugs: <b>{rugs}</b>\n"
                    f"🎯 Win rate: <b>{win_rate:.1f}%</b>\n"
                    f"🏆 Best: <b>{best}</b>\n\n"
                    f"<i>Use /stats for full breakdown.</i>"
                )
        except Exception as e:
            logger.error(f"[Logger] weekly digest error: {e}")
            return "Error generating weekly digest."


# Module-level singleton
signal_logger = SignalLogger()
