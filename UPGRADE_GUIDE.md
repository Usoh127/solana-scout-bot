# UPGRADE GUIDE — Convergence Engine Integration
# ================================================
# From: solana-scout-bot (reactive scanner)
# To:   scout-bot + memcoins-agent convergence detection
#
# New capabilities after this upgrade:
#   ✅ Multi-wallet convergence detection (2-5 wallets → priority alert)
#   ✅ Trust-weighted wallet scoring (wins/losses update trust)
#   ✅ Trust-weighted position sizing (SOUL.md formula)
#   ✅ /signal command — live convergence window view
#   ✅ Convergence alerts fire before scanner even sees the token
#   ✅ /close now updates trust scores automatically

# ──────────────────────────────────────────────────────────────────────────────
# STEP 1: New files (copy to your repo root)
# ──────────────────────────────────────────────────────────────────────────────
#   signal_detector.py  ← convergence engine + trust scoring
#   wallet_tracker.py   ← replaces existing (adds convergence integration)
#
# These replace or add alongside your existing files.
# signal_detector.py is brand new — just drop it in.
# wallet_tracker.py replaces the existing one entirely.

# ──────────────────────────────────────────────────────────────────────────────
# STEP 2: bot.py — 8 targeted changes
# ──────────────────────────────────────────────────────────────────────────────

# ── 2a. Add import at top (after existing imports) ─────────────────────────────
"""
from signal_detector import signal_detector, ConvergenceSignal
"""

# ── 2b. Replace _on_wallet_alert with _on_wallet_alert_v2 ─────────────────────
# Find the existing function:
#   async def _on_wallet_alert(alert: "WalletBuyAlert", app):
# Replace its entire body with the version from BOT_ADDITIONS.py Section 8.

# ── 2c. Add new functions to bot.py ───────────────────────────────────────────
# Copy these complete functions from BOT_ADDITIONS.py into bot.py:
#   _on_convergence_signal()
#   _process_convergence_signal()
#   _build_convergence_briefing()
#   _update_wallet_trust_from_close()
#   cmd_wallets_with_trust()       ← replaces cmd_wallets
#   cmd_close_with_trust()         ← replaces cmd_close
#   cmd_signal()                   ← new command

# ── 2d. In main(), replace this line: ─────────────────────────────────────────
#   wallet_tracker.register_alert_callback(lambda alert: _on_wallet_alert(alert, app))
# With:
#   wallet_tracker.register_alert_callback(lambda alert: _on_wallet_alert_v2(alert, app))
#   signal_detector.register_callback(lambda sig: _on_convergence_signal(sig, app))

# ── 2e. In main(), replace cmd_wallets and cmd_close handlers: ────────────────
# REMOVE:
#   app.add_handler(CommandHandler("wallets", cmd_wallets))
#   app.add_handler(CommandHandler("close", cmd_close))
# ADD:
#   app.add_handler(CommandHandler("wallets", cmd_wallets_with_trust))
#   app.add_handler(CommandHandler("close", cmd_close_with_trust))
#   app.add_handler(CommandHandler("signal", cmd_signal))

# ── 2f. In set_my_commands list inside main(), add: ───────────────────────────
#   ("signal", "Show active convergence signals"),

# ──────────────────────────────────────────────────────────────────────────────
# STEP 3: .env additions
# ──────────────────────────────────────────────────────────────────────────────
"""
# Convergence detection
SIGNAL_WINDOW_SECONDS=300     # 5min window for multi-wallet buys
MIN_WALLETS_FOR_SIGNAL=2      # minimum wallets to trigger convergence alert
"""

# ──────────────────────────────────────────────────────────────────────────────
# STEP 4: requirements.txt — no new dependencies needed
# ──────────────────────────────────────────────────────────────────────────────
# signal_detector.py uses: asyncio, collections, json, logging, os, sqlite3, time
# All are stdlib. No pip installs required.

# ──────────────────────────────────────────────────────────────────────────────
# HOW THE CONVERGENCE FLOW WORKS
# ──────────────────────────────────────────────────────────────────────────────
#
# 1. Wallet A buys $TOKEN → Helius webhook → wallet_tracker.handle_webhook()
# 2. WalletBuyAlert created → enriched via DexScreener
# 3. signal_detector.record_buy(BuyEvent) called
#    → 1 wallet: logged to window, watching
#    → 2+ wallets within SIGNAL_WINDOW_SECONDS: ConvergenceSignal fired
# 4. _on_convergence_signal() receives it
#    → Sends INSTANT preview to Telegram (you see it NOW)
#    → Kicks off full safety + sentiment pipeline in background
# 5. _build_convergence_briefing() sends PRIORITY alert with:
#    → Wallet breakdown + trust scores
#    → Trust-weighted position size (SOUL.md formula)
#    → Full safety + sentiment data
# 6. You tap BUY → same confirmation flow as scanner alerts
# 7. After /close, trust scores are updated automatically

# ──────────────────────────────────────────────────────────────────────────────
# TRUST SCORING REFERENCE
# ──────────────────────────────────────────────────────────────────────────────
#
# Starting trust: 1.0
# Win >5x:    +0.40  (capped at 3.0)
# Win 3-5x:   +0.25
# Win 1.5-3x: +0.15
# Loss:        -0.15
# Rug:         -0.40 (floor at 0.2)
#
# Wallets below 0.5 trust:
#   → Their buy is still recorded but won't trigger a signal alone
#   → 3+ other wallets needed to count them in a convergence
#
# Position size formula (from SOUL.md):
#   2 wallets → 15% of BUY_AMOUNT_SOL × trust_mult
#   3 wallets → 35% of BUY_AMOUNT_SOL × trust_mult
#   4 wallets → 60% of BUY_AMOUNT_SOL × trust_mult
#   5 wallets → 100% of BUY_AMOUNT_SOL × trust_mult
#
# Trust multiplier:
#   avg_trust 1.0 → no size change
#   avg_trust 2.0 → 1.25× size
#   avg_trust 3.0 → 1.50× size (max)

# ──────────────────────────────────────────────────────────────────────────────
# FINDING GOOD WALLETS TO TRACK
# ──────────────────────────────────────────────────────────────────────────────
#
# Tools:
#   - Cielo Finance (cielo.finance) — filter by win rate > 30%
#   - Solscan leaderboards — look for consistent early entrants
#   - GMGN.ai — wallet analytics for Solana meme traders
#
# What to look for:
#   - Buys within first 10 min of token launch
#   - Consistent exits at 2-3x (not moon bags)
#   - Multiple tokens hit per week
#   - Small, frequent buys (0.5-3 SOL) = scout wallet
#   - Large, infrequent buys (5-20 SOL) = conviction wallet (higher trust weight)
#
# Start with 10-15 wallets. The convergence engine handles the rest.
# After 20+ /close entries, trust scores self-calibrate.
