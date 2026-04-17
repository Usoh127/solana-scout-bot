"""
wallet_tracker.py — Alpha wallet tracking via Helius webhooks.

Monitors a list of known profitable wallets for SWAP transactions.
When a tracked wallet buys a token:
  1. Extract the token mint from the swap
  2. Run full safety check
  3. Fire a Telegram alert with wallet name + token details

Architecture:
  - Helius webhook POSTs to /webhook on our Railway URL
  - We run a lightweight aiohttp server alongside the Telegram bot
  - Wallet list persisted to wallets.json — survives restarts

Setup:
  1. Add HELIUS_WEBHOOK_SECRET to .env (any random string, for security)
  2. Add RAILWAY_PUBLIC_URL to .env (e.g. https://yourapp.railway.app)
  3. Use /addwallet command in Telegram to add wallets
  4. Bot auto-registers them with Helius webhook
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable

import aiohttp
from aiohttp import web

from config import config

logger = logging.getLogger(__name__)

# Persistence file
WALLETS_FILE = os.environ.get(
    "WALLETS_FILE",
    "/data/wallets.json" if os.path.isdir("/data") else "wallets.json"
)

HELIUS_WEBHOOK_API = "https://api.helius.xyz/v0/webhooks"

# Solana token program IDs (to identify swap outputs)
WSOL_MINT = "So11111111111111111111111111111111111111112"


# ─── Data models ──────────────────────────────────────────────────────────────

@dataclass
class TrackedWallet:
    address:    str
    name:       str           # human label e.g. "Alpha Whale 1"
    added_at:   float = field(default_factory=time.time)
    buy_count:  int   = 0     # how many buys we've seen from this wallet
    win_count:  int   = 0     # how many of those went up (future feature)
    notes:      str   = ""    # optional notes about this wallet


@dataclass
class WalletBuyAlert:
    wallet_address: str
    wallet_name:    str
    token_mint:     str
    token_name:     str
    token_symbol:   str
    sol_spent:      float
    tx_signature:   str
    detected_at:    float = field(default_factory=time.time)


# ─── WalletTracker ────────────────────────────────────────────────────────────

class WalletTracker:
    def __init__(self):
        self.wallets:    dict[str, TrackedWallet] = {}   # address -> wallet
        self._webhook_id: Optional[str] = None
        self._session:   Optional[aiohttp.ClientSession] = None

        # Callbacks registered by bot.py to handle alerts
        self._alert_callbacks: list[Callable] = []

        # Load saved wallets
        self._load_wallets()

    # ── Session ───────────────────────────────────────────────────────────────

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save_wallets(self):
        """
        Save wallets to file AND print as env-var format so you can
        copy it into Railway variables for true persistence across deploys.
        """
        try:
            data = {addr: asdict(w) for addr, w in self.wallets.items()}
            # Save to file (works locally, lost on Railway redeploy)
            try:
                tmp = WALLETS_FILE + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(data, f, indent=2)
                os.replace(tmp, WALLETS_FILE)
            except Exception:
                pass
            # Also save to env var format for Railway persistence
            env_val = json.dumps(data)
            logger.info(
                f"[WalletTracker] Saved {len(data)} wallets. "
                f"To persist across redeploys, set Railway variable:\n"
                f"TRACKED_WALLETS={env_val}"
            )
        except Exception as e:
            logger.error(f"[WalletTracker] Failed to save wallets: {e}")

    def _load_wallets(self):
        """
        Load wallets from TRACKED_WALLETS env var first (Railway persistent),
        then fall back to local file.
        """
        # Priority 1: TRACKED_WALLETS Railway variable
        env_data = os.environ.get("TRACKED_WALLETS", "")
        if env_data:
            try:
                data = json.loads(env_data)
                for addr, w_dict in data.items():
                    try:
                        self.wallets[addr] = TrackedWallet(**w_dict)
                    except Exception as e:
                        logger.warning(f"[WalletTracker] Could not load wallet {addr}: {e}")
                if self.wallets:
                    logger.info(
                        f"[WalletTracker] Loaded {len(self.wallets)} wallets "
                        f"from TRACKED_WALLETS env var"
                    )
                    return
            except Exception as e:
                logger.warning(f"[WalletTracker] Could not parse TRACKED_WALLETS: {e}")

        # Priority 2: Local file
        if not os.path.exists(WALLETS_FILE):
            logger.info("[WalletTracker] No wallets file — starting fresh")
            return
        try:
            with open(WALLETS_FILE) as f:
                data = json.load(f)
            for addr, w_dict in data.items():
                try:
                    self.wallets[addr] = TrackedWallet(**w_dict)
                except Exception as e:
                    logger.warning(f"[WalletTracker] Could not load wallet {addr}: {e}")
            logger.info(
                f"[WalletTracker] Loaded {len(self.wallets)} wallets from file"
            )
        except Exception as e:
            logger.error(f"[WalletTracker] Failed to load wallets: {e}")

    # ── Wallet management ─────────────────────────────────────────────────────

    def add_wallet(self, address: str, name: str, notes: str = "") -> bool:
        """Add a wallet to track. Returns True if new, False if already exists."""
        if address in self.wallets:
            return False
        self.wallets[address] = TrackedWallet(
            address=address, name=name, notes=notes
        )
        self._save_wallets()
        logger.info(f"[WalletTracker] Added wallet: {name} ({address[:8]}...)")
        return True

    def remove_wallet(self, address: str) -> Optional[TrackedWallet]:
        """Remove a wallet. Returns the removed wallet or None."""
        wallet = self.wallets.pop(address, None)
        if wallet:
            self._save_wallets()
            logger.info(f"[WalletTracker] Removed wallet: {wallet.name}")
        return wallet

    def get_wallet(self, address: str) -> Optional[TrackedWallet]:
        return self.wallets.get(address)

    def list_wallets(self) -> list[TrackedWallet]:
        return list(self.wallets.values())

    async def get_sol_balance(self, address: str) -> Optional[float]:
        """Fetch SOL balance for a tracked wallet."""
        session = await self._get_session()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [address, {"commitment": "confirmed"}],
        }
        try:
            async with session.post(
                config.helius_rpc_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json(content_type=None)
                lamports = (data.get("result") or {}).get("value", 0)
                return lamports / 1e9
        except Exception as e:
            logger.warning(f"[WalletTracker] SOL balance error for {address[:8]}: {e}")
            return None

    async def get_all_wallet_balances(
        self,
    ) -> list[tuple[TrackedWallet, Optional[float]]]:
        """Fetch SOL balances for every tracked wallet."""
        balances = []
        for wallet in self.list_wallets():
            balance = await self.get_sol_balance(wallet.address)
            balances.append((wallet, balance))
            await asyncio.sleep(0.1)
        return balances

    # ── Helius webhook registration ────────────────────────────────────────────

    async def register_webhook(self, public_url: str) -> bool:
        """
        Register or update our Helius webhook with current wallet list.
        Called on startup and whenever wallets are added/removed.

        Helius free tier: 1 webhook, up to 100k addresses.
        """
        if not config.has_helius:
            logger.warning(
                "[WalletTracker] No Helius API key — webhook registration skipped"
            )
            return False

        if not public_url:
            logger.warning(
                "[WalletTracker] No RAILWAY_PUBLIC_URL set — cannot register webhook"
            )
            return False

        webhook_url = f"{public_url.rstrip('/')}/webhook"
        addresses   = list(self.wallets.keys())

        session = await self._get_session()

        # Check if we already have a webhook registered
        try:
            async with session.get(
                f"{HELIUS_WEBHOOK_API}?api-key={config.HELIUS_API_KEY}",
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    existing = await resp.json(content_type=None)
                    if existing:
                        self._webhook_id = existing[0].get("webhookID")
                        logger.info(
                            f"[WalletTracker] Found existing webhook: {self._webhook_id}"
                        )
        except Exception as e:
            logger.warning(f"[WalletTracker] Could not fetch existing webhooks: {e}")

        payload = {
            "webhookURL":       webhook_url,
            "transactionTypes": ["SWAP"],
            "accountAddresses": addresses,
            "webhookType":      "enhanced",
            "authHeader":       self._webhook_secret(),
        }

        try:
            if self._webhook_id:
                # Update existing webhook
                url = f"{HELIUS_WEBHOOK_API}/{self._webhook_id}?api-key={config.HELIUS_API_KEY}"
                async with session.put(
                    url, json=payload,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status in (200, 201):
                        logger.info(
                            f"[WalletTracker] Webhook updated — "
                            f"watching {len(addresses)} wallets"
                        )
                        return True
                    body = await resp.text()
                    logger.warning(f"[WalletTracker] Webhook update failed: {body[:200]}")
                    return False
            else:
                # Create new webhook
                url = f"{HELIUS_WEBHOOK_API}?api-key={config.HELIUS_API_KEY}"
                async with session.post(
                    url, json=payload,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json(content_type=None)
                        self._webhook_id = data.get("webhookID")
                        logger.info(
                            f"[WalletTracker] Webhook created ({self._webhook_id}) — "
                            f"watching {len(addresses)} wallets"
                        )
                        return True
                    body = await resp.text()
                    logger.warning(f"[WalletTracker] Webhook create failed: {body[:200]}")
                    return False
        except Exception as e:
            logger.error(f"[WalletTracker] Webhook registration error: {e}")
            return False

    def _webhook_secret(self) -> str:
        """Auth header value sent by Helius so we know it's really them."""
        return os.environ.get("HELIUS_WEBHOOK_SECRET", "solana-scout-webhook")

    def verify_webhook(self, auth_header: str) -> bool:
        """Verify incoming webhook is from Helius."""
        expected = self._webhook_secret()
        return auth_header == expected

    # ── Transaction parsing ────────────────────────────────────────────────────

    def _parse_swap_buy(
        self, tx: dict, wallet_address: str
    ) -> Optional[WalletBuyAlert]:
        """
        Parse a Helius enhanced transaction to detect if the tracked wallet
        bought a new token (not just swapped between known tokens).

        Returns WalletBuyAlert if it looks like a memecoin buy, else None.
        """
        try:
            # Get the wallet object
            wallet = self.wallets.get(wallet_address)
            if not wallet:
                return None

            signature = tx.get("signature", "")
            tx_type   = tx.get("type", "")

            # Only process SWAP transactions
            if "SWAP" not in tx_type.upper():
                return None

            # Look for token transfers in the transaction
            token_transfers = tx.get("tokenTransfers", [])
            native_transfers = tx.get("nativeTransfers", [])

            # Find SOL spent (native transfer from wallet)
            sol_spent = 0.0
            for transfer in native_transfers:
                if transfer.get("fromUserAccount") == wallet_address:
                    sol_spent += transfer.get("amount", 0) / 1e9

            # Find the token received (not WSOL, not known stablecoins)
            SKIP_MINTS = {
                WSOL_MINT,
                "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
                "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
            }

            token_received = None
            for transfer in token_transfers:
                to_acct   = transfer.get("toUserAccount", "")
                mint      = transfer.get("mint", "")
                amount    = transfer.get("tokenAmount", 0)

                if to_acct == wallet_address and mint not in SKIP_MINTS and amount > 0:
                    token_received = {
                        "mint":   mint,
                        "amount": amount,
                    }
                    break

            if not token_received or not sol_spent:
                return None

            # Get token name/symbol from transaction description or account data
            token_name   = token_received["mint"][:8] + "..."
            token_symbol = "???"

            # Try to extract from description
            description = tx.get("description", "")
            if "swapped" in description.lower():
                parts = description.split(" for ")
                if len(parts) > 1:
                    token_part = parts[-1].strip()
                    if "$" in token_part:
                        token_symbol = token_part.split("$")[-1].split(" ")[0]
                        token_name   = token_symbol

            # Also check events
            events = tx.get("events", {})
            swap   = events.get("swap", {})
            if swap:
                inner_swaps = swap.get("innerSwaps", [])
                for s in inner_swaps:
                    out = s.get("tokenOutputs", [])
                    for o in out:
                        if o.get("mint") == token_received["mint"]:
                            token_symbol = o.get("symbol", token_symbol)
                            token_name   = o.get("name", token_name)
                            break

            wallet.buy_count += 1
            self._save_wallets()

            return WalletBuyAlert(
                wallet_address=wallet_address,
                wallet_name=wallet.name,
                token_mint=token_received["mint"],
                token_name=token_name,
                token_symbol=token_symbol,
                sol_spent=sol_spent,
                tx_signature=signature,
            )

        except Exception as e:
            logger.warning(f"[WalletTracker] Parse error: {e}")
            return None

    # ── Alert callbacks ───────────────────────────────────────────────────────

    def register_alert_callback(self, cb: Callable):
        self._alert_callbacks.append(cb)

    async def _enrich_token_info(
        self, mint: str, symbol: str, name: str
    ) -> tuple[str, str]:
        """
        If symbol is unknown, query DexScreener to get real token name/ticker.
        Free, no API key needed.
        """
        if symbol not in ("???", "") and not name.endswith("..."):
            return name, symbol
        try:
            session = await self._get_session()
            url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    return name, symbol
                data = await resp.json(content_type=None)
                pairs = data.get("pairs") or []
                if not pairs:
                    return name, symbol
                pairs.sort(
                    key=lambda p: float(
                        (p.get("liquidity") or {}).get("usd") or 0
                    ),
                    reverse=True,
                )
                base = pairs[0].get("baseToken") or {}
                enriched_name   = base.get("name", name)
                enriched_symbol = base.get("symbol", symbol)
                logger.info(
                    f"[WalletTracker] Enriched {mint[:8]} "
                    f"→ ${enriched_symbol} ({enriched_name})"
                )
                return enriched_name, enriched_symbol
        except Exception as e:
            logger.debug(f"[WalletTracker] Enrichment error: {e}")
            return name, symbol

    async def _fire_alert(self, alert: WalletBuyAlert):
        for cb in self._alert_callbacks:
            try:
                await cb(alert)
            except Exception as e:
                logger.error(f"[WalletTracker] Alert callback error: {e}")

    # ── Webhook HTTP handler ───────────────────────────────────────────────────

    async def handle_webhook(self, request: web.Request) -> web.Response:
        """
        Receives POST from Helius when a tracked wallet transacts.
        Verifies auth, parses the swap, fires alert if it's a new token buy.
        """
        # Verify it's really Helius
        auth = request.headers.get("Authorization", "")
        if not self.verify_webhook(auth):
            logger.warning("[WalletTracker] Webhook received with invalid auth")
            return web.Response(status=401, text="Unauthorized")

        try:
            body = await request.json()
        except Exception:
            return web.Response(status=400, text="Bad request")

        # Helius sends an array of transactions
        if not isinstance(body, list):
            body = [body]

        for tx in body:
            try:
                # Find which of our tracked wallets is involved
                fee_payer    = tx.get("feePayer", "")
                account_data = tx.get("accountData", [])
                involved     = set()

                if fee_payer in self.wallets:
                    involved.add(fee_payer)

                for acct in account_data:
                    addr = acct.get("account", "")
                    if addr in self.wallets:
                        involved.add(addr)

                for wallet_addr in involved:
                    alert = self._parse_swap_buy(tx, wallet_addr)
                    if alert:
                        # Enrich unknown token names from DexScreener
                        alert.token_name, alert.token_symbol = (
                            await self._enrich_token_info(
                                alert.token_mint,
                                alert.token_symbol,
                                alert.token_name,
                            )
                        )
                        logger.info(
                            f"[WalletTracker] {alert.wallet_name} bought "
                            f"${alert.token_symbol} ({alert.token_name}) "
                            f"— {alert.sol_spent:.3f} SOL"
                        )
                        await self._fire_alert(alert)

            except Exception as e:
                logger.warning(f"[WalletTracker] Error processing tx: {e}")

        return web.Response(status=200, text="OK")

    # ── Polling fallback (when no webhook URL set) ────────────────────────────

    async def poll_wallets_once(self) -> list[WalletBuyAlert]:
        """
        Fallback: poll recent transactions for each wallet.
        Used when RAILWAY_PUBLIC_URL is not set and webhooks can't be registered.
        Checks last 5 minutes of activity.
        """
        if not config.has_helius or not self.wallets:
            return []

        alerts = []
        session = await self._get_session()
        cutoff  = time.time() - 300  # 5 minutes ago

        for addr, wallet in list(self.wallets.items()):
            try:
                url    = f"https://api.helius.xyz/v0/addresses/{addr}/transactions"
                params = {
                    "api-key": config.HELIUS_API_KEY,
                    "type":    "SWAP",
                    "limit":   5,
                }
                async with session.get(
                    url, params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        continue
                    txns = await resp.json(content_type=None)
                    if not isinstance(txns, list):
                        continue

                    for tx in txns:
                        ts = tx.get("timestamp", 0)
                        if ts < cutoff:
                            break   # transactions are newest-first
                        alert = self._parse_swap_buy(tx, addr)
                        if alert:
                            alert.token_name, alert.token_symbol = (
                                await self._enrich_token_info(
                                    alert.token_mint,
                                    alert.token_symbol,
                                    alert.token_name,
                                )
                            )
                            alerts.append(alert)

            except Exception as e:
                logger.debug(f"[WalletTracker] Poll error for {addr[:8]}: {e}")

            await asyncio.sleep(0.2)  # be gentle with rate limits

        return alerts

    # ── Web server ────────────────────────────────────────────────────────────

    def create_web_app(self) -> web.Application:
        """Create the aiohttp web app for receiving Helius webhooks."""
        app = web.Application()
        app.router.add_post("/webhook", self.handle_webhook)
        app.router.add_get("/health", self._health_check)
        return app

    async def _health_check(self, request: web.Request) -> web.Response:
        return web.Response(
            text=f"OK — tracking {len(self.wallets)} wallets",
            status=200
        )

    async def start_web_server(self, port: int = 8080):
        """Start the webhook receiver web server."""
        app    = self.create_web_app()
        runner = web.AppRunner(app)
        await runner.setup()
        site   = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info(f"[WalletTracker] Webhook server running on port {port}")
        return runner
