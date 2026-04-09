"""
executor.py — Trade execution via Jupiter Aggregator v6.

Flow:
  1. get_quote()      → GET /v6/quote (best route for inputMint → outputMint)
  2. get_swap_tx()    → POST /v6/swap (get serialized VersionedTransaction)
  3. sign_and_send()  → sign with wallet keypair, send via RPC
  4. confirm()        → poll until confirmed or timeout

The wallet private key is loaded ONCE at startup from .env (base58 format).
It is NEVER logged, printed, or exposed in any output.

All trades require explicit confirmation before execution — the bot layer
enforces this via Telegram prompts; executor.py never calls itself.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp
import base58  # pip install base58

from config import config

logger = logging.getLogger(__name__)

JUPITER_BASE = "https://quote-api.jup.ag/v6"
WSOL_MINT = "So11111111111111111111111111111111111111112"
SOL_DECIMALS = 9

# Confirmation polling
MAX_CONFIRM_RETRIES = 30
CONFIRM_POLL_INTERVAL = 2  # seconds


@dataclass
class TradeResult:
    success: bool
    tx_hash: str = ""
    error: str = ""
    input_amount: float = 0.0   # SOL or tokens
    output_amount: float = 0.0  # tokens or SOL
    price_impact_pct: float = 0.0
    route_label: str = ""


class TradeExecutor:
    def __init__(self):
        self._keypair = None
        self._pubkey: Optional[str] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._load_wallet()

    def _load_wallet(self):
        """
        Load keypair from base58 private key stored in .env.
        Supports both:
          - 88-char base58 secret key (Phantom export / solana-keygen export)
          - JSON byte array format [1,2,3,...]
        """
        raw_key = config.WALLET_PRIVATE_KEY.strip()
        if not raw_key:
            logger.error("[Executor] WALLET_PRIVATE_KEY is not set. Trading disabled.")
            return

        try:
            from solders.keypair import Keypair  # type: ignore

            # Try base58 first
            if raw_key.startswith("["):
                # JSON byte array
                import json
                byte_list = json.loads(raw_key)
                key_bytes = bytes(byte_list)
            else:
                key_bytes = base58.b58decode(raw_key)

            if len(key_bytes) == 64:
                self._keypair = Keypair.from_bytes(key_bytes)
            elif len(key_bytes) == 32:
                self._keypair = Keypair.from_seed(key_bytes)
            else:
                raise ValueError(f"Unexpected key length: {len(key_bytes)}")

            self._pubkey = str(self._keypair.pubkey())
            logger.info(f"[Executor] Wallet loaded: {self._pubkey[:8]}...{self._pubkey[-4:]}")
        except ImportError:
            logger.error("[Executor] solders not installed. Run: pip install solders")
        except Exception as e:
            logger.error(f"[Executor] Failed to load wallet: {e}")
            self._keypair = None

    @property
    def pubkey(self) -> Optional[str]:
        return self._pubkey

    @property
    def is_ready(self) -> bool:
        return self._keypair is not None and self._pubkey is not None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Jupiter quote ──────────────────────────────────────────────────────────

    async def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount_lamports: int,
        slippage_bps: Optional[int] = None,
    ) -> Optional[dict]:
        """
        Get best swap route from Jupiter v6.
        Retries with progressively higher slippage if initial quote fails.
        Memecoins moving fast need higher slippage to route successfully.
        """
        session = await self._get_session()

        # Slippage ladder: try configured slippage first, then escalate
        # 300 bps = 3%, 500 = 5%, 1000 = 10%, 2000 = 20%
        base_slippage = slippage_bps or config.SLIPPAGE_BPS
        slippage_ladder = [base_slippage, 500, 1000, 2000]
        # Remove duplicates while preserving order
        seen = set()
        slippage_ladder = [
            x for x in slippage_ladder
            if not (x in seen or seen.add(x))
        ]

        for slippage in slippage_ladder:
            params = {
                "inputMint":          input_mint,
                "outputMint":         output_mint,
                "amount":             str(amount_lamports),
                "slippageBps":        str(slippage),
                "onlyDirectRoutes":   "false",
                "asLegacyTransaction": "false",
            }
            for attempt in range(2):
                try:
                    async with session.get(
                        f"{JUPITER_BASE}/quote",
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json(content_type=None)
                            if slippage > base_slippage:
                                logger.info(
                                    f"[Executor] Quote succeeded with higher slippage "
                                    f"{slippage}bps ({slippage/100:.0f}%)"
                                )
                            logger.debug(
                                f"[Executor] Quote: {input_mint[:8]} to {output_mint[:8]}, "
                                f"impact={data.get('priceImpactPct', 'N/A')}%"
                            )
                            return data
                        elif resp.status == 429:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        else:
                            body = await resp.text()
                            logger.warning(
                                f"[Executor] Quote failed {resp.status} "
                                f"slippage={slippage}bps: {body[:150]}"
                            )
                            break  # Try next slippage tier
                except asyncio.TimeoutError:
                    logger.warning(f"[Executor] Quote timeout slippage={slippage}bps")
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.warning(f"[Executor] Quote error: {e}")
                    break

            await asyncio.sleep(0.3)  # small delay between slippage tiers

        logger.warning(
            f"[Executor] All slippage tiers failed for {output_mint[:8]}. "
            f"Token may not be routable on Jupiter yet — possibly too new or "
            f"pool type unsupported."
        )
        return None

    # ── Jupiter swap transaction ───────────────────────────────────────────────

    async def _get_swap_transaction(self, quote_response: dict) -> Optional[str]:
        """
        POST to Jupiter /v6/swap to get a base64-encoded VersionedTransaction.
        """
        if not self._pubkey:
            return None

        session = await self._get_session()
        payload = {
            "quoteResponse": quote_response,
            "userPublicKey": self._pubkey,
            "wrapAndUnwrapSol": True,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": config.PRIORITY_FEE_MICROLAMPORTS,
        }
        try:
            async with session.post(
                f"{JUPITER_BASE}/swap",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    return data.get("swapTransaction")
                else:
                    body = await resp.text()
                    logger.warning(f"[Executor] Swap tx error {resp.status}: {body[:200]}")
                    return None
        except Exception as e:
            logger.warning(f"[Executor] Get swap tx error: {e}")
            return None

    # ── Sign and send ──────────────────────────────────────────────────────────

    async def _sign_and_send(self, swap_transaction_b64: str) -> Optional[str]:
        """
        Deserialize, sign with wallet keypair, and send to RPC.
        Returns transaction signature string.
        """
        try:
            from solders.transaction import VersionedTransaction  # type: ignore
            from solders.keypair import Keypair  # type: ignore

            raw_tx = base64.b64decode(swap_transaction_b64)
            tx = VersionedTransaction.from_bytes(raw_tx)

            # Sign the transaction
            tx = VersionedTransaction(tx.message, [self._keypair])

            # Serialize signed tx
            signed_bytes = bytes(tx)

            # Send via RPC sendTransaction
            session = await self._get_session()
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendTransaction",
                "params": [
                    base64.b64encode(signed_bytes).decode("utf-8"),
                    {
                        "encoding": "base64",
                        "skipPreflight": False,
                        "preflightCommitment": "confirmed",
                        "maxRetries": 5,
                    },
                ],
            }
            async with session.post(
                config.helius_rpc_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json(content_type=None)
                if "error" in data:
                    err_msg = data["error"].get("message", str(data["error"]))
                    logger.error(f"[Executor] sendTransaction error: {err_msg}")
                    return None
                sig = data.get("result")
                if sig:
                    logger.info(f"[Executor] Transaction sent: {sig}")
                return sig

        except ImportError:
            logger.error("[Executor] solders not installed")
            return None
        except Exception as e:
            logger.error(f"[Executor] Sign/send error: {e}")
            return None

    # ── Confirm transaction ────────────────────────────────────────────────────

    async def _confirm_transaction(self, signature: str) -> bool:
        """
        Poll RPC until transaction is confirmed or timeout.
        """
        session = await self._get_session()
        for _ in range(MAX_CONFIRM_RETRIES):
            await asyncio.sleep(CONFIRM_POLL_INTERVAL)
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignatureStatuses",
                "params": [[signature], {"searchTransactionHistory": True}],
            }
            try:
                async with session.post(
                    config.helius_rpc_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json(content_type=None)
                    statuses = (data.get("result") or {}).get("value", [None])
                    status = statuses[0] if statuses else None
                    if status:
                        confirmation = status.get("confirmationStatus", "")
                        err = status.get("err")
                        if err:
                            logger.error(f"[Executor] Tx failed: {err}")
                            return False
                        if confirmation in ("confirmed", "finalized"):
                            logger.info(f"[Executor] Tx confirmed: {signature}")
                            return True
            except Exception as e:
                logger.debug(f"[Executor] Confirm poll error: {e}")
        logger.warning(f"[Executor] Tx confirmation timeout for {signature}")
        return False

    # ── Public API: buy ────────────────────────────────────────────────────────

    async def buy_token(self, mint: str, amount_sol: Optional[float] = None) -> TradeResult:
        """
        Buy {mint} using SOL. Amount defaults to config.BUY_AMOUNT_SOL.
        This function must only be called after explicit user confirmation.
        """
        if not self.is_ready:
            return TradeResult(success=False, error="Wallet not loaded. Check WALLET_PRIVATE_KEY in .env.")

        sol_amount = amount_sol or config.BUY_AMOUNT_SOL
        lamports = int(sol_amount * 10 ** SOL_DECIMALS)

        logger.info(f"[Executor] BUY {sol_amount} SOL → {mint}")

        quote = await self.get_quote(WSOL_MINT, mint, lamports)
        if not quote:
            return TradeResult(success=False, error="Failed to get quote from Jupiter.")

        price_impact = float(quote.get("priceImpactPct") or 0)
        if price_impact > 10:
            return TradeResult(
                success=False,
                error=f"Price impact too high: {price_impact:.2f}%. Trade aborted.",
            )

        route_plan = quote.get("routePlan") or []
        route_label = " → ".join(
            r.get("swapInfo", {}).get("label", "?") for r in route_plan[:3]
        )

        swap_tx = await self._get_swap_transaction(quote)
        if not swap_tx:
            return TradeResult(success=False, error="Failed to get swap transaction from Jupiter.")

        sig = await self._sign_and_send(swap_tx)
        if not sig:
            return TradeResult(success=False, error="Failed to sign/send transaction.")

        confirmed = await self._confirm_transaction(sig)
        if not confirmed:
            return TradeResult(
                success=False,
                tx_hash=sig,
                error="Transaction sent but confirmation timed out. Check tx manually.",
            )

        out_amount = int(quote.get("outAmount") or 0)
        out_decimals = int((quote.get("outputMint") or {}).get("decimals") or 9)
        out_tokens = out_amount / (10 ** out_decimals)

        return TradeResult(
            success=True,
            tx_hash=sig,
            input_amount=sol_amount,
            output_amount=out_tokens,
            price_impact_pct=price_impact,
            route_label=route_label,
        )

    # ── Public API: sell ───────────────────────────────────────────────────────

    async def sell_token(
        self, mint: str, token_amount: Optional[float] = None, decimals: int = 9
    ) -> TradeResult:
        """
        Sell {mint} tokens for SOL.
        If token_amount is None, sells entire wallet balance of that token.
        This function must only be called after explicit user confirmation.
        """
        if not self.is_ready:
            return TradeResult(success=False, error="Wallet not loaded.")

        # If no amount specified, look up wallet balance
        if token_amount is None:
            token_amount = await self._get_token_balance(mint, decimals)
            if token_amount is None or token_amount <= 0:
                return TradeResult(
                    success=False,
                    error=f"No balance found for {mint[:8]}... in wallet.",
                )

        amount_units = int(token_amount * 10 ** decimals)
        logger.info(f"[Executor] SELL {token_amount} of {mint} → SOL")

        quote = await self.get_quote(mint, WSOL_MINT, amount_units)
        if not quote:
            return TradeResult(success=False, error="Failed to get sell quote from Jupiter.")

        price_impact = float(quote.get("priceImpactPct") or 0)
        # On sells during a rug, price impact will be massive — still execute
        if price_impact > 50:
            logger.warning(f"[Executor] High price impact on sell: {price_impact:.1f}%")

        swap_tx = await self._get_swap_transaction(quote)
        if not swap_tx:
            return TradeResult(success=False, error="Failed to get swap transaction.")

        sig = await self._sign_and_send(swap_tx)
        if not sig:
            return TradeResult(success=False, error="Failed to sign/send sell transaction.")

        confirmed = await self._confirm_transaction(sig)

        out_amount = int(quote.get("outAmount") or 0)
        out_sol = out_amount / 10 ** SOL_DECIMALS

        return TradeResult(
            success=confirmed,
            tx_hash=sig,
            input_amount=token_amount,
            output_amount=out_sol,
            price_impact_pct=price_impact,
            error="" if confirmed else "Tx sent but not confirmed in time.",
        )

    # ── Wallet balance helper ──────────────────────────────────────────────────

    async def _get_token_balance(self, mint: str, decimals: int = 9) -> Optional[float]:
        """Get token balance for the loaded wallet."""
        if not self._pubkey:
            return None
        session = await self._get_session()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                self._pubkey,
                {"mint": mint},
                {"encoding": "jsonParsed", "commitment": "confirmed"},
            ],
        }
        try:
            async with session.post(
                config.helius_rpc_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json(content_type=None)
                accounts = (data.get("result") or {}).get("value", [])
                if not accounts:
                    return 0.0
                # Sum all accounts (usually just one)
                total = 0.0
                for acct in accounts:
                    parsed = acct["account"]["data"]["parsed"]["info"]["tokenAmount"]
                    total += float(parsed.get("uiAmount") or 0)
                return total
        except Exception as e:
            logger.warning(f"[Executor] Balance check error for {mint}: {e}")
            return None

    async def get_sol_balance(self) -> Optional[float]:
        """Get SOL balance of the loaded wallet."""
        if not self._pubkey:
            return None
        session = await self._get_session()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [self._pubkey, {"commitment": "confirmed"}],
        }
        try:
            async with session.post(
                config.helius_rpc_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json(content_type=None)
                lamports = (data.get("result") or {}).get("value", 0)
                return lamports / 10 ** SOL_DECIMALS
        except Exception as e:
            logger.warning(f"[Executor] SOL balance error: {e}")
            return None
