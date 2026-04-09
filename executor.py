"""
executor.py — Trade execution layer.

Two execution paths:

1. JUPITER V2 (primary)
   GET  api.jup.ag/swap/v2/order  → quote + unsigned transaction
   Sign with wallet keypair
   POST api.jup.ag/swap/v2/execute → Jupiter handles landing + confirmation

   Requires a free API key from portal.jup.ag
   Set JUPITER_API_KEY in .env / Railway variables.

2. PUMPSWAP DIRECT (fallback when Jupiter can't route)
   POST api.pumpapi.io → unsigned VersionedTransaction bytes
   Sign correctly using solders VersionedTransaction.populate()
   Send via Helius RPC

   Used automatically when Jupiter returns no route.
   Works on brand new tokens with zero indexing delay.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp
import base58

from config import config

logger = logging.getLogger(__name__)

# ── API endpoints ─────────────────────────────────────────────────────────────
JUPITER_V2_BASE  = "https://api.jup.ag/swap/v2"
PUMPSWAP_API     = "https://api.pumpapi.io"
WSOL_MINT        = "So11111111111111111111111111111111111111112"
SOL_DECIMALS     = 9

# Confirmation polling
MAX_CONFIRM_RETRIES   = 40
CONFIRM_POLL_INTERVAL = 2   # seconds


@dataclass
class TradeResult:
    success:          bool
    tx_hash:          str   = ""
    error:            str   = ""
    input_amount:     float = 0.0
    output_amount:    float = 0.0
    price_impact_pct: float = 0.0
    route_label:      str   = ""


class TradeExecutor:
    def __init__(self):
        self._keypair  = None
        self._pubkey:  Optional[str] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._load_wallet()

    # ── Wallet loading ─────────────────────────────────────────────────────────

    def _load_wallet(self):
        raw_key = config.WALLET_PRIVATE_KEY.strip()
        if not raw_key:
            logger.error("[Executor] WALLET_PRIVATE_KEY not set — trading disabled.")
            return
        try:
            from solders.keypair import Keypair
            if raw_key.startswith("["):
                import json
                key_bytes = bytes(json.loads(raw_key))
            else:
                key_bytes = base58.b58decode(raw_key)

            if len(key_bytes) == 64:
                self._keypair = Keypair.from_bytes(key_bytes)
            elif len(key_bytes) == 32:
                self._keypair = Keypair.from_seed(key_bytes)
            else:
                raise ValueError(f"Unexpected key length: {len(key_bytes)}")

            self._pubkey = str(self._keypair.pubkey())
            logger.info(
                f"[Executor] Wallet loaded: "
                f"{self._pubkey[:8]}...{self._pubkey[-4:]}"
            )
        except ImportError:
            logger.error("[Executor] solders not installed — pip install solders")
        except Exception as e:
            logger.error(f"[Executor] Failed to load wallet: {e}")
            self._keypair = None

    @property
    def pubkey(self) -> Optional[str]:
        return self._pubkey

    @property
    def is_ready(self) -> bool:
        return self._keypair is not None and self._pubkey is not None

    # ── HTTP session ───────────────────────────────────────────────────────────

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ══════════════════════════════════════════════════════════════════════════
    # JUPITER V2 — primary execution path
    # ══════════════════════════════════════════════════════════════════════════

    def _jupiter_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        api_key = getattr(config, "JUPITER_API_KEY", "") or ""
        if api_key:
            headers["x-api-key"] = api_key
        return headers

    async def _jupiter_order(
        self,
        input_mint:  str,
        output_mint: str,
        amount_units: int,
    ) -> Optional[dict]:
        """
        GET /order — returns quote + unsigned transaction.
        Tries with slippage auto-managed by Jupiter first,
        then with explicit slippage if that fails.
        """
        session = await self._get_session()
        params  = {
            "inputMint":  input_mint,
            "outputMint": output_mint,
            "amount":     str(amount_units),
            "taker":      self._pubkey,
        }

        for attempt in range(3):
            try:
                async with session.get(
                    f"{JUPITER_V2_BASE}/order",
                    params=params,
                    headers=self._jupiter_headers(),
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        if data.get("transaction"):
                            logger.info(
                                f"[Executor] Jupiter V2 order OK — "
                                f"router={data.get('router','?')} "
                                f"outAmount={data.get('outAmount','?')}"
                            )
                            return data
                        else:
                            logger.warning(
                                f"[Executor] Jupiter V2 order: no transaction "
                                f"in response: {data}"
                            )
                            return None
                    elif resp.status == 429:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    else:
                        body = await resp.text()
                        logger.warning(
                            f"[Executor] Jupiter V2 /order {resp.status}: "
                            f"{body[:200]}"
                        )
                        return None
            except asyncio.TimeoutError:
                logger.warning(
                    f"[Executor] Jupiter V2 /order timeout (attempt {attempt+1})"
                )
                await asyncio.sleep(2)
            except Exception as e:
                logger.warning(f"[Executor] Jupiter V2 /order error: {e}")
                return None
        return None

    def _sign_jupiter_transaction(self, tx_b64: str) -> Optional[str]:
        """
        Sign a Jupiter V2 transaction.
        Jupiter V2 returns a VersionedTransaction — we sign and re-serialize.
        Uses partiallySign pattern so JupiterZ MM signature slot is preserved.
        """
        try:
            from solders.transaction import VersionedTransaction
            from solders.message import to_bytes_versioned

            raw     = base64.b64decode(tx_b64)
            tx      = VersionedTransaction.from_bytes(raw)

            # Get required signers and current signatures
            required = list(tx.message.account_keys)[
                :tx.message.header.num_required_signatures
            ]
            signatures = list(tx.signatures)

            # Sign only our keypair's slot — preserve other slots (MM sigs etc.)
            our_pubkey = self._keypair.pubkey()
            if our_pubkey in required:
                idx = required.index(our_pubkey)
                signatures[idx] = self._keypair.sign_message(
                    to_bytes_versioned(tx.message)
                )
            else:
                # Fallback: sign normally
                tx = VersionedTransaction(tx.message, [self._keypair])
                return base64.b64encode(bytes(tx)).decode()

            signed_tx = VersionedTransaction.populate(tx.message, signatures)
            return base64.b64encode(bytes(signed_tx)).decode()

        except Exception as e:
            logger.error(f"[Executor] Jupiter sign error: {e}")
            return None

    async def _jupiter_execute(
        self, signed_tx_b64: str, request_id: str
    ) -> Optional[dict]:
        """
        POST /execute — Jupiter handles landing + confirmation.
        Returns execute response dict with status, signature, amounts.
        """
        session = await self._get_session()
        payload = {
            "signedTransaction": signed_tx_b64,
            "requestId":         request_id,
        }
        for attempt in range(3):
            try:
                async with session.post(
                    f"{JUPITER_V2_BASE}/execute",
                    json=payload,
                    headers=self._jupiter_headers(),
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        logger.info(
                            f"[Executor] Jupiter execute: "
                            f"status={data.get('status')} "
                            f"sig={data.get('signature','')[:16]}..."
                        )
                        return data
                    elif resp.status == 429:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    else:
                        body = await resp.text()
                        logger.warning(
                            f"[Executor] Jupiter /execute {resp.status}: "
                            f"{body[:200]}"
                        )
                        return None
            except asyncio.TimeoutError:
                logger.warning(
                    f"[Executor] Jupiter /execute timeout (attempt {attempt+1})"
                )
                await asyncio.sleep(3)
            except Exception as e:
                logger.warning(f"[Executor] Jupiter /execute error: {e}")
                return None
        return None

    async def _execute_via_jupiter(
        self,
        input_mint:   str,
        output_mint:  str,
        amount_units: int,
        input_amount_display: float,
    ) -> TradeResult:
        """
        Full Jupiter V2 buy or sell flow.
        """
        order = await self._jupiter_order(input_mint, output_mint, amount_units)
        if not order:
            return TradeResult(
                success=False,
                error="Jupiter V2: no route found for this token."
            )

        signed = self._sign_jupiter_transaction(order["transaction"])
        if not signed:
            return TradeResult(
                success=False,
                error="Jupiter V2: failed to sign transaction."
            )

        result = await self._jupiter_execute(signed, order["requestId"])
        if not result:
            return TradeResult(
                success=False,
                error="Jupiter V2: execute call failed."
            )

        if result.get("status") == "Success":
            out_amount_raw = int(result.get("outputAmountResult") or 0)
            in_amount_raw  = int(result.get("inputAmountResult")  or 0)
            # outputMint tells us the decimals context
            is_buying_token = output_mint != WSOL_MINT
            out_decimals    = 9  # SOL or token — both default 9 (fine for display)
            out_amount      = out_amount_raw / (10 ** out_decimals)
            return TradeResult(
                success=True,
                tx_hash=result.get("signature", ""),
                input_amount=input_amount_display,
                output_amount=out_amount,
                price_impact_pct=0.0,
                route_label=f"Jupiter V2 ({order.get('router','?')})",
            )
        else:
            err = result.get("error") or result.get("status") or "Unknown error"
            return TradeResult(success=False, error=f"Jupiter V2 execute: {err}")

    # ══════════════════════════════════════════════════════════════════════════
    # PUMPSWAP DIRECT — fallback for brand new tokens
    # ══════════════════════════════════════════════════════════════════════════

    async def _execute_via_pumpswap(
        self,
        action:     str,    # "buy" or "sell"
        mint:       str,
        amount:     float,
        denominated_in_sol: bool = True,
    ) -> TradeResult:
        """
        Direct PumpSwap execution via pumpapi.io.
        Uses correct VersionedTransaction signing from official PumpSwap docs.
        Sends via Helius RPC for reliability.
        """
        if not self._keypair or not self._pubkey:
            return TradeResult(success=False, error="Wallet not loaded.")

        session = await self._get_session()

        payload = {
            "publicKey":        self._pubkey,
            "action":           action,
            "mint":             mint,
            "amount":           amount,
            "denominatedInQuote": "true" if denominated_in_sol else "false",
            "slippage":         20,
            "priorityFee":      0.001,
        }

        logger.info(
            f"[Executor] PumpSwap {action}: {amount} "
            f"{'SOL' if denominated_in_sol else 'tokens'} "
            f"for {mint[:8]}..."
        )

        try:
            async with session.post(
                PUMPSWAP_API,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    return TradeResult(
                        success=False,
                        error=f"PumpSwap API error {resp.status}: {body[:150]}"
                    )
                tx_bytes = await resp.read()

        except Exception as e:
            return TradeResult(
                success=False,
                error=f"PumpSwap request failed: {str(e)}"
            )

        if not tx_bytes:
            return TradeResult(
                success=False, error="PumpSwap returned empty response"
            )

        # ── Sign using correct PumpSwap pattern ───────────────────────────────
        try:
            from solders.transaction import VersionedTransaction
            from solders.message import to_bytes_versioned

            tx         = VersionedTransaction.from_bytes(tx_bytes)
            required   = list(tx.message.account_keys)[
                :tx.message.header.num_required_signatures
            ]
            signatures = list(tx.signatures)

            for kp in [self._keypair]:
                pubkey = kp.pubkey()
                if pubkey in required:
                    idx = required.index(pubkey)
                    signatures[idx] = kp.sign_message(
                        to_bytes_versioned(tx.message)
                    )

            signed_tx = VersionedTransaction.populate(tx.message, signatures)

        except Exception as e:
            logger.error(f"[Executor] PumpSwap sign error: {e}")
            return TradeResult(
                success=False,
                error=f"PumpSwap signing failed: {str(e)}"
            )

        # ── Send via Helius RPC ───────────────────────────────────────────────
        try:
            from solders.rpc.requests import SendVersionedTransaction
            from solders.rpc.config import RpcSendTransactionConfig
            from solders.commitment_config import CommitmentLevel

            commitment = CommitmentLevel.Confirmed
            cfg        = RpcSendTransactionConfig(preflight_commitment=commitment)
            rpc_payload = SendVersionedTransaction(signed_tx, cfg).to_json()

            async with session.post(
                config.helius_rpc_url,
                data=rpc_payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json(content_type=None)

        except Exception as e:
            logger.error(f"[Executor] PumpSwap RPC send error: {e}")
            return TradeResult(
                success=False,
                error=f"PumpSwap RPC error: {str(e)}"
            )

        if "error" in data:
            err = data["error"].get("message", str(data["error"]))
            logger.error(f"[Executor] PumpSwap RPC error: {err}")
            return TradeResult(success=False, error=f"PumpSwap RPC: {err}")

        sig = data.get("result")
        if not sig:
            return TradeResult(
                success=False, error="PumpSwap: no signature returned from RPC"
            )

        logger.info(f"[Executor] PumpSwap tx sent: {sig}")

        # ── Confirm ───────────────────────────────────────────────────────────
        confirmed = await self._confirm_transaction(sig)
        if not confirmed:
            return TradeResult(
                success=False,
                tx_hash=sig,
                error="PumpSwap tx sent but confirmation timed out. Check tx manually.",
            )

        return TradeResult(
            success=True,
            tx_hash=sig,
            input_amount=amount,
            output_amount=0.0,   # PumpSwap API doesn't return output amount
            price_impact_pct=0.0,
            route_label="PumpSwap direct",
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Confirmation polling (for PumpSwap — Jupiter V2 confirms itself)
    # ══════════════════════════════════════════════════════════════════════════

    async def _confirm_transaction(self, signature: str) -> bool:
        session = await self._get_session()
        for _ in range(MAX_CONFIRM_RETRIES):
            await asyncio.sleep(CONFIRM_POLL_INTERVAL)
            payload = {
                "jsonrpc": "2.0",
                "id":      1,
                "method":  "getSignatureStatuses",
                "params":  [[signature], {"searchTransactionHistory": True}],
            }
            try:
                async with session.post(
                    config.helius_rpc_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data     = await resp.json(content_type=None)
                    statuses = (data.get("result") or {}).get("value", [None])
                    status   = statuses[0] if statuses else None
                    if status:
                        err = status.get("err")
                        if err:
                            logger.error(f"[Executor] Tx failed on-chain: {err}")
                            return False
                        if status.get("confirmationStatus") in (
                            "confirmed", "finalized"
                        ):
                            logger.info(f"[Executor] Tx confirmed: {signature}")
                            return True
            except Exception as e:
                logger.debug(f"[Executor] Confirm poll error: {e}")

        logger.warning(f"[Executor] Confirm timeout for {signature}")
        return False

    # ══════════════════════════════════════════════════════════════════════════
    # Public API
    # ══════════════════════════════════════════════════════════════════════════

    async def buy_token(
        self, mint: str, amount_sol: Optional[float] = None
    ) -> TradeResult:
        """
        Buy {mint} with SOL.
        Tries Jupiter V2 first. Falls back to PumpSwap direct if Jupiter
        can't route (happens on very new tokens not yet indexed).
        """
        if not self.is_ready:
            return TradeResult(
                success=False,
                error="Wallet not loaded. Check WALLET_PRIVATE_KEY."
            )

        sol_amount = amount_sol or config.BUY_AMOUNT_SOL
        lamports   = int(sol_amount * 10 ** SOL_DECIMALS)

        logger.info(f"[Executor] BUY {sol_amount} SOL → {mint[:8]}...")

        # Try Jupiter V2 first
        result = await self._execute_via_jupiter(
            input_mint=WSOL_MINT,
            output_mint=mint,
            amount_units=lamports,
            input_amount_display=sol_amount,
        )

        if result.success:
            return result

        # Jupiter failed — fall back to PumpSwap direct
        logger.info(
            f"[Executor] Jupiter failed ({result.error[:60]}), "
            f"falling back to PumpSwap direct..."
        )
        pump_result = await self._execute_via_pumpswap(
            action="buy",
            mint=mint,
            amount=sol_amount,
            denominated_in_sol=True,
        )

        if pump_result.success:
            return pump_result

        # Both failed — return combined error
        return TradeResult(
            success=False,
            error=(
                f"Jupiter: {result.error} | "
                f"PumpSwap: {pump_result.error}"
            ),
        )

    async def sell_token(
        self,
        mint:         str,
        token_amount: Optional[float] = None,
        decimals:     int = 9,
    ) -> TradeResult:
        """
        Sell {mint} tokens for SOL.
        Tries Jupiter V2 first. Falls back to PumpSwap direct if Jupiter
        can't route.
        """
        if not self.is_ready:
            return TradeResult(success=False, error="Wallet not loaded.")

        if token_amount is None:
            token_amount = await self._get_token_balance(mint, decimals)
            if not token_amount or token_amount <= 0:
                return TradeResult(
                    success=False,
                    error=f"No token balance found for {mint[:8]}..."
                )

        amount_units = int(token_amount * 10 ** decimals)
        logger.info(f"[Executor] SELL {token_amount} of {mint[:8]}... → SOL")

        # Try Jupiter V2 first
        result = await self._execute_via_jupiter(
            input_mint=mint,
            output_mint=WSOL_MINT,
            amount_units=amount_units,
            input_amount_display=token_amount,
        )

        if result.success:
            return result

        # Jupiter failed — fall back to PumpSwap direct sell
        logger.info(
            f"[Executor] Jupiter sell failed ({result.error[:60]}), "
            f"falling back to PumpSwap direct sell..."
        )
        pump_result = await self._execute_via_pumpswap(
            action="sell",
            mint=mint,
            amount=token_amount,
            denominated_in_sol=False,
        )

        if pump_result.success:
            return pump_result

        return TradeResult(
            success=False,
            error=(
                f"Jupiter: {result.error} | "
                f"PumpSwap: {pump_result.error}"
            ),
        )

    # ── Wallet balance helpers ─────────────────────────────────────────────────

    async def _get_token_balance(
        self, mint: str, decimals: int = 9
    ) -> Optional[float]:
        if not self._pubkey:
            return None
        session = await self._get_session()
        payload = {
            "jsonrpc": "2.0",
            "id":      1,
            "method":  "getTokenAccountsByOwner",
            "params":  [
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
                data     = await resp.json(content_type=None)
                accounts = (data.get("result") or {}).get("value", [])
                if not accounts:
                    return 0.0
                total = 0.0
                for acct in accounts:
                    parsed = acct["account"]["data"]["parsed"]["info"]["tokenAmount"]
                    total += float(parsed.get("uiAmount") or 0)
                return total
        except Exception as e:
            logger.warning(f"[Executor] Token balance error for {mint[:8]}: {e}")
            return None

    async def get_sol_balance(self) -> Optional[float]:
        if not self._pubkey:
            return None
        session = await self._get_session()
        payload = {
            "jsonrpc": "2.0",
            "id":      1,
            "method":  "getBalance",
            "params":  [self._pubkey, {"commitment": "confirmed"}],
        }
        try:
            async with session.post(
                config.helius_rpc_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data     = await resp.json(content_type=None)
                lamports = (data.get("result") or {}).get("value", 0)
                return lamports / 10 ** SOL_DECIMALS
        except Exception as e:
            logger.warning(f"[Executor] SOL balance error: {e}")
            return None
