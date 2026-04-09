"""
bot.py — Solana Alpha Scout Bot: main entry point.

Architecture: python-telegram-bot v20+ (async) running as a long-lived process.
  • CommandHandlers:  /start, /scan, /positions, /balance, /help, /stop
  • CallbackQueryHandlers: BUY, SKIP, CONFIRM_BUY, CONFIRM_SELL, SELL, CANCEL
  • Job Queue: background scan cycle + position monitor cycle

All trades require EXPLICIT user confirmation via inline keyboard.
No action is ever executed without a confirmation prompt.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from config import config
from executor import TradeExecutor
from monitor import MonitorAlert, Position, PositionMonitor
from safety import SafetyChecker
from scout import TokenOpportunity, TokenScout
from sentiment import SentimentAnalyzer

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s │ %(name)-18s │ %(levelname)-8s │ %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
# Quieter loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logger = logging.getLogger("SolanaScoutBot")

# ── Module-level singletons ───────────────────────────────────────────────────

scout = TokenScout()
safety_checker = SafetyChecker()
sentiment_analyzer = SentimentAnalyzer()
executor = TradeExecutor()
monitor = PositionMonitor(sentiment_analyzer)

# ── Auth guard ────────────────────────────────────────────────────────────────


def _is_authorized(update: Update) -> bool:
    """Only the configured user ID can interact with this bot."""
    allowed = config.TELEGRAM_ALLOWED_USER_ID
    if allowed == 0:
        # Not set: first run, log the user ID so they can configure it
        uid = update.effective_user.id if update.effective_user else "unknown"
        logger.warning(
            f"[Auth] TELEGRAM_ALLOWED_USER_ID not set. "
            f"Incoming user ID: {uid} — set this in .env to lock the bot."
        )
        return True  # Open until configured
    return (update.effective_user.id if update.effective_user else 0) == allowed


async def _unauthorized(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "🔒 Unauthorized. This bot is private.", parse_mode=ParseMode.HTML
    )


# ── Briefing builder ──────────────────────────────────────────────────────────


def _fmt_usd(n: float) -> str:
    if n >= 1_000_000:
        return f"${n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"${n / 1_000:.1f}K"
    return f"${n:.2f}"


def _compute_confidence(opp: TokenOpportunity) -> tuple[int, str]:
    """
    Score 1-10 with hard penalties for holder concentration and LP issues.
    """
    import re
    score = 0
    reasons = []
    penalties = []

    if opp.safety_passed:
        score += 3
        reasons.append("clean on-chain ✅")
    else:
        reasons.append("safety flags ❌")

    if opp.price_change_1h >= 50:
        score += 2
        reasons.append("ripping 1h momentum 🚀")
    elif opp.price_change_1h >= 20:
        score += 1
        reasons.append("solid 1h momentum 📈")

    if opp.sentiment_label == "Bullish" and opp.tweet_count >= 20:
        score += 3
        reasons.append("strong social signal 🔥")
    elif opp.sentiment_label == "Bullish":
        score += 2
        reasons.append("bullish sentiment 📣")
    elif opp.sentiment_label == "Neutral" and opp.tweet_count > 5:
        score += 1
        reasons.append("neutral/quiet socials")
    elif opp.data_only_call:
        reasons.append("⚠️ data-only (no socials)")

    vol_liq_ratio = opp.volume_24h_usd / opp.liquidity_usd if opp.liquidity_usd > 0 else 0
    if vol_liq_ratio >= 2:
        score += 2
        reasons.append("vol/liq ratio 🔥")
    elif vol_liq_ratio >= 0.5:
        score += 1
        reasons.append("decent vol/liq")

    holder_pct = 0.0
    if opp.safety_detail:
        for line in opp.safety_detail.splitlines():
            if "Top-10 holders" in line or "top-10" in line.lower():
                match = re.search(r"(\d+\.?\d*)%", line)
                if match:
                    holder_pct = float(match.group(1))
                    break

    if holder_pct >= 60:
        score -= 3
        penalties.append(f"🚨 top-10 own {holder_pct:.0f}% — extreme dump risk")
    elif holder_pct >= 45:
        score -= 2
        penalties.append(f"⚠️ top-10 own {holder_pct:.0f}% — high dump risk")
    elif holder_pct >= 35:
        score -= 1
        penalties.append(f"⚠️ top-10 own {holder_pct:.0f}% — elevated dump risk")

    if opp.safety_detail and "LP lock unverified" in opp.safety_detail:
        score -= 1
        penalties.append("⚠️ LP lock unverified")

    score = max(1, min(10, score))
    rationale = " · ".join((reasons[:2] + penalties[:2]))
    return score, rationale


def _build_briefing(opp: TokenOpportunity) -> tuple[str, InlineKeyboardMarkup]:
    """Build the formatted Telegram briefing message + action buttons."""

    opp.confidence, opp.confidence_rationale = _compute_confidence(opp)

    # Emoji indicators
    sentiment_emoji = {
        "Bullish": "🟢", "Bearish": "🔴", "Neutral": "🟡"
    }.get(opp.sentiment_label, "⚪")
    safety_icon = "✅" if opp.safety_passed else "❌"
    conf_emoji = "🔥" if opp.confidence >= 7 else "⚡" if opp.confidence >= 5 else "🌡️"

    # Data-only warning block
    data_only_block = ""
    if opp.data_only_call:
        data_only_block = (
            f"\n⚠️ <b>DATA-ONLY CALL</b> — weak social signal\n"
            f"<i>Reason: {html.escape(opp.data_only_reason)}</i>\n"
        )

    # Shorten mint for display
    short_mint = f"{opp.mint[:6]}...{opp.mint[-4:]}"

    # Twitter signal block
    twitter_block = ""
    if opp.tweet_count > 0:
        twitter_block = (
            f"  ├ {opp.tweet_count} tweets · score {opp.sentiment_score:+.2f}\n"
        )
        if opp.top_tweet_signal:
            twitter_block += (
                f"  └ <i>\"{html.escape(opp.top_tweet_signal[:100])}\"</i>\n"
            )
        if opp.has_notable_account if hasattr(opp, "has_notable_account") else False:
            twitter_block += "  └ 📢 Notable account active\n"
    else:
        twitter_block = "  └ 📭 No Twitter signal\n"

    reddit_block = f"  └ {html.escape(opp.reddit_summary)}\n" if opp.reddit_summary else ""
    news_block = (
        f"\n🌐 <b>Market Context</b> <i>(general, not token-specific)</i>\n"
        f"  └ {html.escape(opp.news_summary)}\n"
        if opp.news_summary else ""
    )

    # Launch time
    launched_str = f"{opp.age_str}"
    if opp.launched_at:
        launched_str = (
            opp.launched_at.strftime("%b %d %H:%M UTC") + f" ({opp.age_str})"
        )

    text = (
        f"🔎 <b>NEW RUNNER ALERT</b>\n"
        f"{'━' * 28}\n"
        f"🪙 <b>{html.escape(opp.name)}</b>  <code>${html.escape(opp.symbol)}</code>\n"
        f"📍 <code>{opp.mint}</code>\n"
        f"🏊 DEX: {html.escape(opp.dex.title())}\n\n"
        f"💰 <b>Financials</b>\n"
        f"  ├ Price:    <code>${opp.price_usd:.8f}</code>\n"
        f"  ├ MCap:     <b>{_fmt_usd(opp.market_cap_usd)}</b>\n"
        f"  ├ FDV:      {_fmt_usd(opp.fdv_usd)}\n"
        f"  ├ Liq:      {_fmt_usd(opp.liquidity_usd)}\n"
        f"  └ Vol 24h:  {_fmt_usd(opp.volume_24h_usd)}\n\n"
        f"📊 <b>Price Action</b>\n"
        f"  └ {opp.price_action_summary}\n\n"
        f"⏱️ <b>Launch</b>: {launched_str}\n\n"
        f"{safety_icon} <b>On-Chain Safety</b>\n"
        f"<pre>{html.escape(opp.safety_detail)}</pre>\n\n"
        f"{sentiment_emoji} <b>Sentiment: {opp.sentiment_label}</b>\n"
        f"{twitter_block}"
        f"{reddit_block}"
        f"{html.escape(opp.sentiment_summary)}\n"
        f"{news_block}"
        f"{data_only_block}\n"
        f"{conf_emoji} <b>Confidence: {opp.confidence}/10</b>\n"
        f"<i>{html.escape(opp.confidence_rationale)}</i>\n\n"
        f"{'━' * 28}\n"
        f"💸 Buy size: <b>{config.BUY_AMOUNT_SOL} SOL</b>  · Slippage: {config.SLIPPAGE_BPS / 100:.1f}%"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🟢 BUY", callback_data=f"BUY_{opp.mint}"),
                InlineKeyboardButton("⏭️ SKIP", callback_data=f"SKIP_{opp.mint}"),
            ]
        ]
    )

    return text, keyboard


def _build_risk_alert_message(alert: MonitorAlert) -> tuple[str, InlineKeyboardMarkup]:
    """Format a risk monitoring alert with SELL button."""
    change_str = f"{alert.pct_change:+.1f}%"
    liq_str = _fmt_usd(alert.current_liquidity)

    alert_icons = {
        "stop_loss": "🛑",
        "liquidity_drop": "🚨",
        "large_dump": "🐋",
        "sentiment_bearish": "📉",
    }
    icon = alert_icons.get(alert.alert_type, "⚠️")

    text = (
        f"{icon} <b>RISK ALERT — {html.escape(alert.symbol)}</b>\n"
        f"{'━' * 28}\n"
        f"{html.escape(alert.message)}\n\n"
        f"📊 Current:  <code>${alert.current_price:.8f}</code>  ({change_str})\n"
        f"💧 Liq now:  {liq_str}"
        f"  ({alert.liquidity_drop_pct:+.1f}% from buy)\n\n"
        f"Do you want to exit this position?"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔴 SELL NOW", callback_data=f"SELL_{alert.mint}"),
                InlineKeyboardButton("🚫 IGNORE", callback_data=f"IGNORE_{alert.mint}"),
            ]
        ]
    )
    return text, keyboard


# ── Alert callback from monitor ───────────────────────────────────────────────


async def _on_risk_alert(alert: MonitorAlert, app: Application):
    """Called by PositionMonitor when a risk condition trips."""
    chat_id = config.TELEGRAM_ALLOWED_USER_ID or app.bot_data.get("chat_id", 0)
    if not chat_id:
        logger.warning("[Bot] No chat_id configured for risk alert delivery")
        return
    try:
        text, keyboard = _build_risk_alert_message(alert)
        await app.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.error(f"[Bot] Failed to send risk alert: {e}")


# ── Command handlers ──────────────────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return await _unauthorized(update, context)

    # Save chat_id for outbound risk alerts
    context.bot_data["chat_id"] = update.effective_chat.id

    uid = update.effective_user.id
    logger.info(f"[Bot] /start from user {uid}")

    wallet_str = (
        f"{executor.pubkey[:8]}...{executor.pubkey[-4:]}"
        if executor.pubkey else "⚠️ Not loaded"
    )

    await update.message.reply_text(
        f"👋 <b>Solana Alpha Scout</b> is online\n\n"
        f"🔑 Wallet: <code>{wallet_str}</code>\n"
        f"💰 Buy size: <b>{config.BUY_AMOUNT_SOL} SOL</b>\n"
        f"🔴 Stop loss: <b>{config.STOP_LOSS_PCT}%</b>\n"
        f"📡 Scanning every <b>{config.SCAN_INTERVAL_SECONDS}s</b>\n\n"
        f"Commands:\n"
        f"  /scan — manual scan now\n"
        f"  /positions — open positions\n"
        f"  /balance — SOL balance\n"
        f"  /help — all commands\n\n"
        f"<i>Auto-scan is running in the background. "
        f"Briefings will be sent here automatically.</i>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return await _unauthorized(update, context)
    await update.message.reply_text(
        "<b>Solana Alpha Scout — Commands</b>\n\n"
        "/start     — show status\n"
        "/scan      — trigger manual scan\n"
        "/positions — list open positions\n"
        "/balance   — check wallet SOL balance\n"
        "/stop      — stop background scanning\n"
        "/help      — this message\n\n"
        "<b>Thresholds (set in .env)</b>\n"
        f"  Min liquidity:  ${config.MIN_LIQUIDITY_USD:,.0f}\n"
        f"  Min 24h volume: ${config.MIN_VOLUME_24H_USD:,.0f}\n"
        f"  Max MCap:       ${config.MAX_MARKET_CAP_USD:,.0f}\n"
        f"  Max age:        {config.MAX_TOKEN_AGE_HOURS}h\n"
        f"  Stop loss:      -{config.STOP_LOSS_PCT}%\n"
        f"  Liq drop alert: -{config.LIQUIDITY_DROP_ALERT_PCT}%",
        parse_mode=ParseMode.HTML,
    )


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return await _unauthorized(update, context)
    msg = await update.message.reply_text("🔍 Fetching balance…")
    balance = await executor.get_sol_balance()
    if balance is None:
        await msg.edit_text("❌ Could not fetch balance. Check RPC config.")
    else:
        await msg.edit_text(
            f"💰 Wallet balance: <b>{balance:.4f} SOL</b>",
            parse_mode=ParseMode.HTML,
        )


async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return await _unauthorized(update, context)

    positions = monitor.list_positions()
    if not positions:
        await update.message.reply_text("📭 No open positions.")
        return

    lines = ["<b>📂 Open Positions</b>\n"]
    for p in positions:
        age_min = int((time.time() - p.buy_time) / 60)
        lines.append(
            f"• <b>${p.symbol}</b>  {p.mint[:6]}...{p.mint[-4:]}\n"
            f"  Buy: ${p.buy_price_usd:.8f}  |  {p.amount_sol_spent:.3f} SOL\n"
            f"  Held {age_min}min\n"
        )

    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return await _unauthorized(update, context)
    # Remove the scan job
    jobs = context.job_queue.get_jobs_by_name("auto_scan")
    for job in jobs:
        job.schedule_removal()
    await update.message.reply_text(
        "⏹️ Auto-scan stopped. Use /scan for manual scans."
    )


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return await _unauthorized(update, context)

    # Save chat_id
    context.bot_data["chat_id"] = update.effective_chat.id

    msg = await update.message.reply_text(
        "🔍 Scanning Solana DEXs… hang tight"
    )
    await _run_scan_cycle(context, chat_id=update.effective_chat.id, status_msg=msg)


# ── Core scan cycle ───────────────────────────────────────────────────────────


async def _run_scan_cycle(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: Optional[int] = None,
    status_msg=None,
):
    """
    Full scan cycle: scout → safety → sentiment → briefing.
    Sends briefings to Telegram for each validated opportunity.
    """
    target_chat = chat_id or context.bot_data.get("chat_id")
    if not target_chat:
        logger.warning("[Bot] No chat_id set, cannot send briefings")
        return

    try:
        opportunities = await scout.scan_for_opportunities()

        if not opportunities:
            if status_msg:
                await status_msg.edit_text(
                    "🔍 Scan complete — no tokens met thresholds right now. "
                    "Will check again shortly."
                )
            logger.info("[Bot] Scan found no qualifying tokens")
            return

        if status_msg:
            await status_msg.edit_text(
                f"🔍 Found {len(opportunities)} candidate(s) — running safety + sentiment checks…"
            )

        briefings_sent = 0
        for opp in opportunities[:5]:  # Cap at 5 per cycle to avoid spam
            try:
                # Safety check
                safety_result = await safety_checker.full_safety_check(
                    opp.mint, opp.pool_address
                )
                opp.safety_passed = safety_result.passed
                opp.safety_detail = safety_result.detail

                if not safety_result.passed:
                    logger.info(
                        f"[Bot] {opp.symbol} failed safety check — skipping"
                    )
                    continue

                # Sentiment analysis
                sentiment_result = await sentiment_analyzer.analyze(
                    opp.name, opp.symbol, opp.mint
                )
                opp.sentiment_label = sentiment_result.label
                opp.sentiment_score = sentiment_result.score
                opp.sentiment_summary = sentiment_result.summary
                opp.tweet_count = sentiment_result.tweet_count
                opp.top_tweet_signal = sentiment_result.top_tweet_signal
                opp.reddit_summary = sentiment_result.reddit_summary
                opp.news_summary = sentiment_result.news_summary
                # Annotate notable account attr for briefing
                opp.has_notable_account = sentiment_result.has_notable_account

                # Social signal gate
                if not sentiment_result.has_any_signal:
                    # Check if on-chain data is exceptional enough to justify surfacing
                    vol_liq = opp.volume_24h_usd / opp.liquidity_usd if opp.liquidity_usd > 0 else 0
                    is_exceptional = (
                        opp.price_change_1h >= 100
                        and vol_liq >= 3
                        and opp.liquidity_usd >= config.MIN_LIQUIDITY_USD * 3
                    )
                    if is_exceptional:
                        opp.data_only_call = True
                        opp.data_only_reason = (
                            f"{opp.price_change_1h:.0f}% 1h move, "
                            f"{vol_liq:.1f}x vol/liq ratio, no social data found"
                        )
                        logger.info(
                            f"[Bot] {opp.symbol} has no social signal but exceptional "
                            f"on-chain data — surfacing as DATA-ONLY call"
                        )
                    else:
                        logger.info(
                            f"[Bot] {opp.symbol} skipped — no social signal and "
                            f"on-chain data not exceptional enough"
                        )
                        continue

                # Build and send briefing
                text, keyboard = _build_briefing(opp)

                # Store token data for when user taps BUY
                context.bot_data[f"opp_{opp.mint}"] = opp

                await context.bot.send_message(
                    chat_id=target_chat,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
                scout.mark_alerted(opp.mint)
                briefings_sent += 1

                await asyncio.sleep(0.5)  # avoid hitting Telegram rate limit

            except Exception as e:
                logger.error(f"[Bot] Error processing {opp.symbol}: {e}", exc_info=True)
                continue

        summary = f"✅ Scan done — {briefings_sent} briefing(s) sent."
        if briefings_sent == 0:
            summary = "🔍 Scan done — all candidates filtered (safety/sentiment). Watching…"

        if status_msg:
            await status_msg.edit_text(summary)

    except Exception as e:
        logger.error(f"[Bot] Scan cycle error: {e}", exc_info=True)
        if status_msg:
            await status_msg.edit_text(f"❌ Scan error: {str(e)[:100]}")


async def _auto_scan_job(context: ContextTypes.DEFAULT_TYPE):
    """Job queue callback for automatic scanning."""
    logger.info("[Bot] Auto-scan triggered by job queue")
    await _run_scan_cycle(context)


# ── Callback query handlers ───────────────────────────────────────────────────


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # ACK immediately

    if not _is_authorized(update):
        await query.message.reply_text("🔒 Unauthorized.")
        return

    data = query.data or ""

    if data.startswith("BUY_"):
        await _handle_buy_intent(query, context, data[4:])

    elif data.startswith("SKIP_"):
        mint = data[5:]
        opp: Optional[TokenOpportunity] = context.bot_data.get(f"opp_{mint}")
        sym = opp.symbol if opp else mint[:8]
        await query.edit_message_text(
            f"⏭️ Skipped <b>${sym}</b>.", parse_mode=ParseMode.HTML
        )

    elif data.startswith("CONFIRM_BUY_"):
        await _handle_confirm_buy(query, context, data[12:])

    elif data.startswith("SELL_"):
        await _handle_sell_intent(query, context, data[5:])

    elif data.startswith("CONFIRM_SELL_"):
        await _handle_confirm_sell(query, context, data[13:])

    elif data.startswith("IGNORE_"):
        mint = data[7:]
        pos = monitor.get_position(mint)
        sym = pos.symbol if pos else mint[:8]
        await query.edit_message_text(
            f"🚫 Alert ignored for <b>${sym}</b>. Still monitoring.",
            parse_mode=ParseMode.HTML,
        )

    elif data == "CANCEL_BUY":
        await query.edit_message_text("❌ Buy cancelled.")

    elif data == "CANCEL_SELL":
        await query.edit_message_text("❌ Sell cancelled.")


async def _handle_buy_intent(query, context, mint: str):
    """User tapped BUY — show confirmation prompt. DO NOT execute yet."""
    opp: Optional[TokenOpportunity] = context.bot_data.get(f"opp_{mint}")
    if not opp:
        await query.edit_message_text("⚠️ Token data expired. Run /scan again.")
        return

    if not executor.is_ready:
        await query.edit_message_text(
            "❌ Wallet not configured. Set WALLET_PRIVATE_KEY in .env."
        )
        return

    # Build confirmation message
    conf_text = (
        f"⚠️ <b>CONFIRM BUY</b>\n\n"
        f"You're about to buy <b>${html.escape(opp.symbol)}</b>\n"
        f"Token:  <code>{opp.mint}</code>\n"
        f"Amount: <b>{config.BUY_AMOUNT_SOL} SOL</b>\n"
        f"Price:  <code>${opp.price_usd:.8f}</code>\n"
        f"Slippage: {config.SLIPPAGE_BPS / 100:.1f}%\n\n"
        f"<b>This action is irreversible. Confirm?</b>"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ YES, BUY IT", callback_data=f"CONFIRM_BUY_{mint}"),
                InlineKeyboardButton("❌ Cancel", callback_data="CANCEL_BUY"),
            ]
        ]
    )
    await query.edit_message_text(
        conf_text, parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def _handle_confirm_buy(query, context, mint: str):
    """User confirmed the buy — execute the trade."""
    opp: Optional[TokenOpportunity] = context.bot_data.get(f"opp_{mint}")
    if not opp:
        await query.edit_message_text("⚠️ Token data expired.")
        return

    await query.edit_message_text(
        f"⏳ Executing buy of <b>${html.escape(opp.symbol)}</b>…",
        parse_mode=ParseMode.HTML,
    )

    result = await executor.buy_token(mint)

    if result.success:
        tx_link = f"https://solscan.io/tx/{result.tx_hash}"
        await query.edit_message_text(
            f"✅ <b>Buy executed!</b>\n\n"
            f"Token: <b>${html.escape(opp.symbol)}</b>\n"
            f"Spent: <b>{result.input_amount:.4f} SOL</b>\n"
            f"Got:   <code>{result.output_amount:,.2f}</code> tokens\n"
            f"Impact: {result.price_impact_pct:.2f}%\n"
            f"Route: {html.escape(result.route_label)}\n\n"
            f"🔗 <a href='{tx_link}'>View on Solscan</a>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        # Register position with monitor
        position = Position(
            mint=opp.mint,
            name=opp.name,
            symbol=opp.symbol,
            pool_address=opp.pool_address,
            buy_price_usd=opp.price_usd,
            buy_time=time.time(),
            amount_tokens=result.output_amount,
            amount_sol_spent=result.input_amount,
            liquidity_at_buy=opp.liquidity_usd,
            tx_hash=result.tx_hash,
            token_age_at_buy=opp.age_hours,
            volume_at_buy=opp.volume_1h_usd,
        )
        monitor.add_position(position)
        logger.info(f"[Bot] Position opened: {opp.symbol}")
    else:
        await query.edit_message_text(
            f"❌ <b>Buy failed</b>\n\n<code>{html.escape(result.error)}</code>",
            parse_mode=ParseMode.HTML,
        )


async def _handle_sell_intent(query, context, mint: str):
    """User tapped SELL (from risk alert) — show confirmation. DO NOT execute yet."""
    pos = monitor.get_position(mint)
    if not pos:
        await query.edit_message_text("⚠️ Position not found (may have been closed).")
        return

    conf_text = (
        f"⚠️ <b>CONFIRM SELL</b>\n\n"
        f"Sell all <b>${html.escape(pos.symbol)}</b>?\n"
        f"Buy price: <code>${pos.buy_price_usd:.8f}</code>\n"
        f"Tokens:    <code>{pos.amount_tokens:,.2f}</code>\n\n"
        f"<b>Confirm market sell?</b>"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ YES, SELL ALL", callback_data=f"CONFIRM_SELL_{mint}"),
                InlineKeyboardButton("❌ Cancel", callback_data="CANCEL_SELL"),
            ]
        ]
    )
    await query.edit_message_text(
        conf_text, parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def _handle_confirm_sell(query, context, mint: str):
    """User confirmed the sell — execute the exit."""
    pos = monitor.get_position(mint)
    if not pos:
        await query.edit_message_text("⚠️ Position not found.")
        return

    await query.edit_message_text(
        f"⏳ Selling <b>${html.escape(pos.symbol)}</b>…",
        parse_mode=ParseMode.HTML,
    )

    result = await executor.sell_token(mint, pos.amount_tokens)

    if result.success:
        pnl_sol = result.output_amount - pos.amount_sol_spent
        pnl_pct = (pnl_sol / pos.amount_sol_spent) * 100 if pos.amount_sol_spent > 0 else 0
        pnl_str = f"{'+' if pnl_sol >= 0 else ''}{pnl_sol:.4f} SOL ({pnl_pct:+.1f}%)"
        tx_link = f"https://solscan.io/tx/{result.tx_hash}"

        await query.edit_message_text(
            f"✅ <b>Sold ${html.escape(pos.symbol)}</b>\n\n"
            f"Received: <b>{result.output_amount:.4f} SOL</b>\n"
            f"PnL:      <b>{pnl_str}</b>\n"
            f"Impact:   {result.price_impact_pct:.2f}%\n\n"
            f"🔗 <a href='{tx_link}'>View on Solscan</a>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        monitor.remove_position(mint)
    else:
        await query.edit_message_text(
            f"❌ <b>Sell failed</b>\n\n<code>{html.escape(result.error)}</code>\n\n"
            f"<i>Tx hash (if sent): {result.tx_hash or 'N/A'}</i>",
            parse_mode=ParseMode.HTML,
        )


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    errors = config.validate()
    if errors:
        logger.error(
            f"[Bot] Missing required config: {errors}. "
            f"Check your .env file. Exiting."
        )
        return

    logger.info("[Bot] Building Telegram Application…")
    app = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .build()
    )

    # Register alert callback (needs reference to app for outbound messages)
    monitor.register_alert_callback(
        lambda alert: _on_risk_alert(alert, app)
    )

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("positions", cmd_positions))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("stop", cmd_stop))

    # Inline keyboard callbacks
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Background jobs
    jq = app.job_queue
    # Auto scan
    jq.run_repeating(
        _auto_scan_job,
        interval=config.SCAN_INTERVAL_SECONDS,
        first=30,  # First scan after 30s startup delay
        name="auto_scan",
    )
    # Position monitor
    jq.run_repeating(
        monitor.run_monitor_cycle,
        interval=config.MONITOR_INTERVAL_SECONDS,
        first=60,
        name="position_monitor",
    )

    logger.info(
        f"[Bot] 🚀 Solana Alpha Scout online\n"
        f"      Wallet: {executor.pubkey or 'NOT LOADED'}\n"
        f"      Scan every {config.SCAN_INTERVAL_SECONDS}s\n"
        f"      Monitor every {config.MONITOR_INTERVAL_SECONDS}s\n"
        f"      Allowed user: {config.TELEGRAM_ALLOWED_USER_ID or 'ANY (set TELEGRAM_ALLOWED_USER_ID!)'}"
    )

    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
    )


if __name__ == "__main__":
    main()
