"""
config.py — Central config loaded from .env.
All thresholds are runtime-configurable. No magic numbers anywhere else.
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _require(key: str) -> str:
    val = os.getenv(key, "")
    if not val:
        logger.warning(f"[CONFIG] {key} is not set — some features will be disabled.")
    return val


def _float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        logger.warning(f"[CONFIG] Invalid float for {key}, using default {default}")
        return default


def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        logger.warning(f"[CONFIG] Invalid int for {key}, using default {default}")
        return default


class Config:
    # ── Telegram ─────────────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")
    # Allowlist: only this Telegram user ID can operate the bot.
    # Run the bot, send /start, copy your numeric ID from the console log.
    TELEGRAM_ALLOWED_USER_ID: int = _int("TELEGRAM_ALLOWED_USER_ID", 0)

    # ── Solana wallet ─────────────────────────────────────────────────────────
    # Export your private key from Phantom as a base58 string (NOT the seed phrase).
    WALLET_PRIVATE_KEY: str = _require("WALLET_PRIVATE_KEY")
    SOLANA_RPC_URL: str = os.getenv(
        "SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"
    )

    # ── Trade execution ───────────────────────────────────────────────────────
    BUY_AMOUNT_SOL: float = _float("BUY_AMOUNT_SOL", 0.1)
    SLIPPAGE_BPS: int = _int("SLIPPAGE_BPS", 300)  # 3%
    # Priority fee in micro-lamports (helps land txns during congestion)
    PRIORITY_FEE_MICROLAMPORTS: int = _int("PRIORITY_FEE_MICROLAMPORTS", 50000)

    # ── Scouting thresholds ───────────────────────────────────────────────────
    MIN_LIQUIDITY_USD: float = _float("MIN_LIQUIDITY_USD", 20_000)
    MIN_VOLUME_24H_USD: float = _float("MIN_VOLUME_24H_USD", 10_000)
    MIN_MARKET_CAP_USD: float = _float("MIN_MARKET_CAP_USD", 50_000)
    MAX_MARKET_CAP_USD: float = _float("MAX_MARKET_CAP_USD", 5_000_000)
    MAX_TOKEN_AGE_HOURS: int = _int("MAX_TOKEN_AGE_HOURS", 72)
    MIN_PRICE_CHANGE_1H: float = _float("MIN_PRICE_CHANGE_1H", 10.0)   # %
    MIN_PRICE_CHANGE_6H: float = _float("MIN_PRICE_CHANGE_6H", 20.0)   # %

    # ── On-chain safety ───────────────────────────────────────────────────────
    MAX_TOP_10_HOLDER_PCT: float = _float("MAX_TOP_10_HOLDER_PCT", 40.0)

    # ── Risk management ───────────────────────────────────────────────────────
    STOP_LOSS_PCT: float = _float("STOP_LOSS_PCT", 15.0)
    LIQUIDITY_DROP_ALERT_PCT: float = _float("LIQUIDITY_DROP_ALERT_PCT", 30.0)
    # If a single wallet dumps >= this % of supply in one tx, alert
    LARGE_DUMP_THRESHOLD_PCT: float = _float("LARGE_DUMP_THRESHOLD_PCT", 5.0)
    # Negative sentiment spike: if compound score drops below this, alert
    SENTIMENT_BEARISH_THRESHOLD: float = _float("SENTIMENT_BEARISH_THRESHOLD", -0.3)

    # ── Scanning intervals ────────────────────────────────────────────────────
    SCAN_INTERVAL_SECONDS: int = _int("SCAN_INTERVAL_SECONDS", 120)
    MONITOR_INTERVAL_SECONDS: int = _int("MONITOR_INTERVAL_SECONDS", 30)
    # Don't re-alert the same token within this window (hours)
    ALERT_COOLDOWN_HOURS: int = _int("ALERT_COOLDOWN_HOURS", 6)

    # ── External API keys ─────────────────────────────────────────────────────
    # Twitter API v2 Bearer Token — free tier at developer.twitter.com
    # ⚠️  FREE TIER LIMIT: 10 search requests / 15 min, 500k tweets / month
    TWITTER_BEARER_TOKEN: str = os.getenv("TWITTER_BEARER_TOKEN", "")

    # NewsAPI — free tier: 100 requests/day at newsapi.org
    # ⚠️  FREE TIER: 100 req/day, no commercial use
    NEWS_API_KEY: str = os.getenv("NEWS_API_KEY", "")

    # Reddit via PRAW — free, create app at reddit.com/prefs/apps
    REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
    REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
    REDDIT_USER_AGENT: str = os.getenv("REDDIT_USER_AGENT", "SolanaScoutBot/1.0")

    # Helius — free tier: 100k credits/day at helius.dev
    # Used for holder concentration + large tx alerts
    HELIUS_API_KEY: str = os.getenv("HELIUS_API_KEY", "")

    # Birdeye — free tier at birdeye.so (token security endpoint)
    # ⚠️  PAID TIER needed for full security data (~$99/mo Starter)
    # Free alternative: we fall back to Helius + on-chain RPC checks
    BIRDEYE_API_KEY: str = os.getenv("BIRDEYE_API_KEY", "")

    # ── Derived helpers ───────────────────────────────────────────────────────
    @property
    def helius_rpc_url(self) -> str:
        if self.HELIUS_API_KEY:
            return f"https://mainnet.helius-rpc.com/?api-key={self.HELIUS_API_KEY}"
        return self.SOLANA_RPC_URL

    @property
    def has_twitter(self) -> bool:
        return bool(self.TWITTER_BEARER_TOKEN)

    @property
    def has_news(self) -> bool:
        return bool(self.NEWS_API_KEY)

    @property
    def has_reddit(self) -> bool:
        return bool(self.REDDIT_CLIENT_ID and self.REDDIT_CLIENT_SECRET)

    @property
    def has_birdeye(self) -> bool:
        return bool(self.BIRDEYE_API_KEY)

    @property
    def has_helius(self) -> bool:
        return bool(self.HELIUS_API_KEY)

    def validate(self) -> list[str]:
        """Return list of critical missing config keys."""
        errors = []
        if not self.TELEGRAM_BOT_TOKEN:
            errors.append("TELEGRAM_BOT_TOKEN")
        if not self.WALLET_PRIVATE_KEY:
            errors.append("WALLET_PRIVATE_KEY")
        return errors


# Singleton
config = Config()
