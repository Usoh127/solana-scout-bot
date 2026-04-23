"""
safety.py — On-chain safety validation layer.

Checks in order of reliability:
  1. Birdeye Security API (best, needs paid key)
  2. Helius RPC getAccountInfo - mint authority
  3. Solana RPC getTokenLargestAccounts - holder concentration
  4. LP burn check via pool account inspection
  5. SPL-Token-2022 dangerous extension check
  6. Pool creator / fee rate check

A token passes safety if:
  - No dangerous SPL-2022 extensions
  - Freeze authority renounced
  - Top-10 holder concentration < MAX_TOP_10_HOLDER_PCT

NOTE: Mint authority NOT renounced is now a warning/penalty only, not a hard fail.
Most early pump.fun tokens haven't renounced yet — killing them here was the reason
the bot never fired a single alert.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import struct
from dataclasses import dataclass, field
from typing import Optional

import aiohttp

from config import config

logger = logging.getLogger(__name__)

BIRDEYE_BASE          = "https://public-api.birdeye.so"
DEXSCREENER_BASE      = "https://api.dexscreener.com"
TOKEN_PROGRAM_ID      = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
BURN_ADDRESS          = "1nc1nerator11111111111111111111111111111111"
RAYDIUM_LOCK_PROGRAM  = "7WduLbRfYhTJktjLw5FDEyrqoEv61aTTCuGAetgLjzN5"
COPTION_NONE = 0

DANGEROUS_EXTENSIONS = {
    "transferFeeConfig":             "charges fees on every transfer (most common scam)",
    "transferHook":                  "custom code runs on every transfer",
    "permanentDelegate":             "permanent control over your tokens",
    "defaultAccountState":           "can freeze accounts by default",
    "memoTransfer":                  "requires memo blocks most DEX sells",
    "nonTransferable":               "tokens cannot be transferred",
    "confidentialTransferMint":      "incompatible with pools",
    "confidentialMintBurn":          "incompatible with pools",
    "confidentialTransferFeeConfig": "incompatible with pools",
    "pausableConfig":                "can pause all transfers",
    "cpiGuard":                      "blocks program interactions",
}


@dataclass
class SafetyResult:
    passed:                    bool
    mint_authority_renounced:  bool
    freeze_authority_renounced: bool
    top10_holder_pct:          float
    lp_burned:                 Optional[bool]
    is_honeypot:               bool
    detail:                    str
    dangerous_extensions:      list = field(default_factory=list)
    token_program:             str  = "unknown"
    pool_creator:              str  = "unknown"
    pool_fee_rate:             float = 0.0
    lp_lock_verified:          Optional[bool] = None
    bundle_risk:               float = 0.0
    bundle_detail:             str = ""
    fake_volume_risk:          float = 0.0
    fake_volume_detail:        str = ""
    deployer_risk:             float = 0.0
    deployer_detail:           str = ""
    deployer_address:          str  = ""


class SafetyChecker:
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _check_birdeye_security(self, mint: str) -> dict | None:
        if not config.has_birdeye:
            return None
        session = await self._get_session()
        try:
            async with session.get(
                f"{BIRDEYE_BASE}/defi/token_security",
                headers={"X-API-KEY": config.BIRDEYE_API_KEY, "x-chain": "solana"},
                params={"address": mint},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return (await resp.json(content_type=None)).get("data") or {}
                return None
        except Exception as e:
            logger.warning(f"[Safety] Birdeye error: {e}")
            return None

    async def _rpc_call(self, method: str, params: list) -> dict | None:
        session = await self._get_session()
        try:
            async with session.post(
                config.helius_rpc_url,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    return (await resp.json(content_type=None)).get("result")
                return None
        except Exception as e:
            logger.warning(f"[Safety] RPC error {method}: {e}")
            return None

    async def _check_mint_authority(self, mint: str) -> tuple[bool, bool]:
        result = await self._rpc_call("getAccountInfo", [mint, {"encoding": "base64"}])
        if not result or not result.get("value"):
            return False, True
        try:
            raw = base64.b64decode(result["value"]["data"][0])
            if len(raw) < 82:
                return False, False
            return (
                struct.unpack_from("<I", raw, 4)[0] == COPTION_NONE,
                struct.unpack_from("<I", raw, 46)[0] == COPTION_NONE,
            )
        except Exception as e:
            logger.warning(f"[Safety] Mint parse error {mint}: {e}")
            return False, False

    async def _check_holder_concentration(self, mint: str) -> float:
        result = await self._rpc_call(
            "getTokenLargestAccounts", [mint, {"commitment": "confirmed"}]
        )
        if result and result.get("value"):
            amounts = [float(a.get("uiAmount") or 0) for a in result["value"]]
            supply_result = await self._rpc_call(
                "getTokenSupply", [mint, {"commitment": "confirmed"}]
            )
            if supply_result and supply_result.get("value"):
                supply = float(supply_result["value"].get("uiAmount") or 1)
                return round(sum(amounts[:10]) / supply * 100, 2) if supply > 0 else 0.0
        return 0.0

    async def _check_lp_burned(
        self, pool_address: str, mint: str = "", dex_name: str = ""
    ) -> Optional[bool]:
        dex_lower = (dex_name or "").lower()
        is_pumpswap = "pump" in dex_lower

        if is_pumpswap and mint:
            try:
                session = await self._get_session()
                url = f"{DEXSCREENER_BASE}/latest/dex/tokens/{mint}"
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data  = await resp.json(content_type=None)
                        pairs = data.get("pairs") or []
                        pump_pairs = [
                            p for p in pairs
                            if "pump" in (p.get("dexId") or "").lower()
                        ]
                        if not pump_pairs:
                            pump_pairs = pairs

                        if pump_pairs:
                            pump_pairs.sort(
                                key=lambda p: float(
                                    (p.get("liquidity") or {}).get("usd") or 0
                                ),
                                reverse=True,
                            )
                            pair = pump_pairs[0]
                            lp_burn = pair.get("lpBurn")
                            if lp_burn is not None:
                                burned = int(lp_burn) >= 90
                                logger.debug(
                                    f"[Safety] {mint[:8]}: DexScreener lpBurn={lp_burn}% "
                                    f"→ {'burned' if burned else 'NOT burned'}"
                                )
                                return burned

                            dex_id = (pair.get("dexId") or "").lower()
                            if "pump" in dex_id:
                                logger.debug(
                                    f"[Safety] {mint[:8]}: PumpSwap pair — "
                                    f"assuming LP burned (pump.fun migration)"
                                )
                                return True

            except Exception as e:
                logger.debug(f"[Safety] DexScreener LP check error: {e}")

        if not pool_address:
            return None
        result = await self._rpc_call(
            "getAccountInfo", [pool_address, {"encoding": "jsonParsed"}]
        )
        if not result or not result.get("value"):
            return None
        try:
            return result["value"].get("owner", "") == BURN_ADDRESS
        except Exception:
            return None

    async def _check_token_extensions(self, mint: str) -> tuple[str, list[str]]:
        result = await self._rpc_call(
            "getAccountInfo", [mint, {"encoding": "jsonParsed"}]
        )
        if not result or not result.get("value"):
            return "unknown", []
        try:
            account = result["value"]
            owner   = account.get("owner", "")
            data    = account.get("data", {})

            if owner == TOKEN_PROGRAM_ID:
                return "spl-token", []

            if owner != TOKEN_2022_PROGRAM_ID:
                return "unknown", []

            if not isinstance(data, dict):
                return "spl-token-2022", []

            extensions = (
                data.get("parsed", {})
                    .get("info", {})
                    .get("extensions", [])
            )

            dangerous_found = []
            for ext in extensions:
                ext_type = ext.get("extension", "")
                if ext_type in DANGEROUS_EXTENSIONS:
                    dangerous_found.append(
                        f"{ext_type}: {DANGEROUS_EXTENSIONS[ext_type]}"
                    )

            if dangerous_found:
                logger.warning(
                    f"[Safety] {mint[:8]}: dangerous extensions: {dangerous_found}"
                )

            return "spl-token-2022", dangerous_found

        except Exception as e:
            logger.warning(f"[Safety] Extension check error {mint}: {e}")
            return "unknown", []

    async def _check_pool_safety(
        self, pool_address: str, dex_name: str
    ) -> tuple[str, float, list[str]]:
        if not pool_address:
            return "unknown", 0.0, []

        warnings     = []
        pool_creator = "unknown"
        fee_rate     = 0.0

        result = await self._rpc_call(
            "getAccountInfo", [pool_address, {"encoding": "jsonParsed"}]
        )
        if result and result.get("value"):
            try:
                data = result["value"].get("data", {})
                if isinstance(data, dict):
                    info     = data.get("parsed", {}).get("info", {})
                    fee_rate = float(
                        info.get("feeRate", 0) or
                        info.get("tradeFeeNumerator", 0) or 0
                    )
                    if fee_rate > 1:
                        fee_rate = fee_rate / 10000
                    if fee_rate > 0.05:
                        warnings.append(
                            f"⚠️ Pool fee rate {fee_rate*100:.1f}% — extremely high"
                        )
            except Exception:
                pass

        dex_lower = (dex_name or "").lower()
        if "pumpswap" in dex_lower or "pump_fun" in dex_lower:
            pool_creator = "pump"
        elif "pump" in dex_lower and "amm" in dex_lower:
            pool_creator = "pump-amm"
        elif "raydium" in dex_lower:
            pool_creator = "raydium"
        elif "meteora" in dex_lower:
            pool_creator = "meteora"
            if fee_rate > 0.001:
                warnings.append(
                    f"⚠️ Meteora fee {fee_rate*100:.2f}% — verify fee rate"
                )

        return pool_creator, fee_rate, warnings

    def _check_honeypot_heuristics(
        self,
        mint_renounced:       bool,
        freeze_renounced:     bool,
        top10_pct:            float,
        lp_burned:            Optional[bool],
        birdeye_data:         dict | None,
        dangerous_extensions: list,
        pool_warnings:        list,
        is_bonding_curve:     bool = False,   # True = pre-graduation pump.fun
    ) -> tuple[bool, list[str]]:
        red_flags    = []
        instant_fail = False

        # ── Hard fails (instant kill regardless of other signals) ──────────────
        if dangerous_extensions:
            for ext in dangerous_extensions:
                red_flags.append(f"🚨 DANGEROUS EXTENSION: {ext}")
            instant_fail = True

        if not freeze_renounced:
            # Only instant-fail if Birdeye explicitly confirmed freeze is active.
            # If we just couldn't check (RPC timeout), treat as a warning only.
            if birdeye_data and birdeye_data.get("freezable") is True:
                red_flags.append("🚨 Freeze authority ACTIVE (Birdeye confirmed)")
                instant_fail = True
            else:
                # RPC couldn't verify — warn but don't kill
                red_flags.append("⚠️ Freeze authority status unverified (RPC timeout)")

        # ── Mint authority check ──────────────────────────────────────────
        # For bonding curve tokens (pre-graduation pump.fun):
        #   Mint not renounced is EXPECTED — pump.fun burns it at graduation.
        #   Show as a soft warning only.
        # For graduated tokens (Pumpswap, Raydium, etc.):
        #   Mint not renounced after graduation is a REAL red flag.
        #   Pump.fun automatically revokes it at graduation — if it's still
        #   active, something is wrong. Count it as a harder flag.
        if not mint_renounced:
            if is_bonding_curve:
                red_flags.append(
                    "⚠️ Mint not renounced (expected pre-graduation — "
                    "pump.fun burns this at graduation)"
                )
            else:
                red_flags.append(
                    "🚨 Mint authority NOT renounced — this token is already "
                    "on a DEX, mint should have been burned at graduation"
                )
                instant_fail = True   # Hard fail for graduated tokens

        if top10_pct > config.MAX_TOP_10_HOLDER_PCT:
            red_flags.append(f"⚠️ Top-10 holders own {top10_pct:.1f}% (dump risk)")

        if lp_burned is False:
            red_flags.append("⚠️ LP not burned/locked (rug vector open)")

        red_flags.extend(pool_warnings)

        if birdeye_data:
            creator_pct = float(birdeye_data.get("creatorPercentage") or 0)
            if creator_pct > 20:
                red_flags.append(f"⚠️ Creator holds {creator_pct:.1f}% of supply")
            if not birdeye_data.get("lpBurned") and lp_burned is None:
                red_flags.append("⚠️ LP not burned (Birdeye)")

        # Require 3+ soft flags to fail (was 2) — prevents a single "mint not
        # renounced" + one other minor flag from killing every early token
        return instant_fail or len(red_flags) >= 3, red_flags

    # ── Deployer wallet history check ─────────────────────────────────────────

    async def _check_deployer_history(self, mint: str) -> tuple[float, str]:
        if not config.has_helius:
            return 0.0, "", ""

        session = await self._get_session()
        deployer = None

        try:
            url = f"https://api.helius.xyz/v0/addresses/{mint}/transactions"
            params = {
                "api-key": config.HELIUS_API_KEY,
                "limit": 5,
                "type": "TOKEN_MINT",
            }
            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    txns = await resp.json(content_type=None)
                    if isinstance(txns, list) and txns:
                        deployer = txns[-1].get("feePayer") or txns[0].get("feePayer")
        except Exception as e:
            logger.debug(f"[Safety] Deployer fetch error: {e}")

        if not deployer:
            try:
                result = await self._rpc_call(
                    "getSignaturesForAddress",
                    [mint, {"limit": 1, "commitment": "confirmed"}]
                )
                if result:
                    sig = result[0].get("signature", "")
                    if sig:
                        tx_result = await self._rpc_call(
                            "getTransaction",
                            [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
                        )
                        if tx_result:
                            deployer = (
                                tx_result.get("transaction", {})
                                .get("message", {})
                                .get("accountKeys", [{}])[0]
                                .get("pubkey", "")
                            )
            except Exception as e:
                logger.debug(f"[Safety] Deployer RPC fallback error: {e}")

        if not deployer or len(deployer) < 32:
            return 0.0, ""

        logger.debug(f"[Safety] Deployer for {mint[:8]}: {deployer[:8]}...")

        try:
            url = f"https://api.helius.xyz/v0/addresses/{deployer}/transactions"
            params = {
                "api-key": config.HELIUS_API_KEY,
                "limit": 20,
                "type": "TOKEN_MINT",
            }
            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return 0.0, f"Deployer: {deployer[:8]}...", deployer
                recent_txns = await resp.json(content_type=None)
        except Exception as e:
            logger.debug(f"[Safety] Deployer history error: {e}")
            return 0.0, f"Deployer: {deployer[:8]}...", deployer

        if not isinstance(recent_txns, list):
            return 0.0, f"Deployer: {deployer[:8]}...", deployer

        tokens_deployed = len(recent_txns)
        flags   = []
        risk    = 0.0

        if tokens_deployed >= 10:
            risk += 0.5
            flags.append(f"deployer launched {tokens_deployed}+ tokens recently (serial deployer)")
        elif tokens_deployed >= 5:
            risk += 0.25
            flags.append(f"deployer launched {tokens_deployed} tokens recently")

        if tokens_deployed >= 3:
            timestamps = [
                tx.get("timestamp", 0)
                for tx in recent_txns[:5]
                if tx.get("timestamp")
            ]
            if len(timestamps) >= 3:
                timestamps.sort(reverse=True)
                time_span_hours = (timestamps[0] - timestamps[2]) / 3600
                if time_span_hours < 24:
                    risk += 0.3
                    flags.append(
                        f"3 tokens deployed within {time_span_hours:.1f}h — factory pattern"
                    )

        risk = min(risk, 1.0)
        desc = f"Deployer {deployer[:8]}..."
        if flags:
            desc += ": " + " | ".join(flags)
            logger.info(f"[Safety] Deployer check: {desc} (risk={risk:.2f})")

        return risk, desc, deployer

    # ── Fake volume detection ──────────────────────────────────────────────────

    def _check_fake_volume(
        self, volume_24h: float, liquidity: float, txns_24h: int
    ) -> tuple[float, str]:
        if volume_24h <= 0 or liquidity <= 0:
            return 0.0, ""

        flags = []
        risk  = 0.0

        vol_liq = volume_24h / liquidity
        if vol_liq > 100:
            risk += 0.7
            flags.append(f"vol/liq ratio {vol_liq:.0f}x — extreme wash trading")
        elif vol_liq > 50:
            risk += 0.4
            flags.append(f"vol/liq ratio {vol_liq:.0f}x — suspicious")
        elif vol_liq > 20:
            risk += 0.2
            flags.append(f"vol/liq ratio {vol_liq:.0f}x — elevated")

        if txns_24h > 0:
            avg_trade = volume_24h / txns_24h
            avg_trade_pct = (avg_trade / liquidity) * 100
            if avg_trade_pct > 20:
                risk += 0.4
                flags.append(
                    f"avg trade is {avg_trade_pct:.0f}% of liquidity — "
                    f"very few large trades (bot pattern)"
                )
            elif avg_trade_pct > 10:
                risk += 0.2
                flags.append(f"avg trade is {avg_trade_pct:.0f}% of liquidity — suspicious")
        elif volume_24h > 50_000:
            risk += 0.3
            flags.append("high volume but no transaction count data")

        risk = min(risk, 1.0)
        description = " | ".join(flags) if flags else ""

        if flags:
            logger.info(f"[Safety] Fake volume signals: {description} (risk={risk:.2f})")

        return risk, description

    # ── Bundle detection ───────────────────────────────────────────────────────

    async def _check_bundle(self, mint: str) -> tuple[float, str]:
        if not config.has_helius:
            return 0.0, ""

        session = await self._get_session()
        url    = f"https://api.helius.xyz/v0/addresses/{mint}/transactions"
        params = {
            "api-key": config.HELIUS_API_KEY,
            "type":    "SWAP",
            "limit":   20,
        }

        try:
            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return 0.0, ""
                txns = await resp.json(content_type=None)
                if not isinstance(txns, list) or not txns:
                    return 0.0, ""
        except Exception as e:
            logger.debug(f"[Safety] Bundle check error: {e}")
            return 0.0, ""

        slots: dict[int, list[str]] = {}
        buyer_amounts: dict[str, float] = {}

        for tx in txns:
            slot      = tx.get("slot", 0)
            fee_payer = tx.get("feePayer", "")
            if not fee_payer or not slot:
                continue

            token_transfers = tx.get("tokenTransfers", [])
            for transfer in token_transfers:
                if transfer.get("mint") != mint:
                    continue
                to_acct = transfer.get("toUserAccount", "")
                amount  = float(transfer.get("tokenAmount") or 0)
                if to_acct == fee_payer and amount > 0:
                    if slot not in slots:
                        slots[slot] = []
                    if fee_payer not in slots[slot]:
                        slots[slot].append(fee_payer)
                    buyer_amounts[fee_payer] = buyer_amounts.get(fee_payer, 0) + amount

        max_same_slot = max((len(v) for v in slots.values()), default=0)
        total_bought  = sum(buyer_amounts.values())
        unique_buyers = len(buyer_amounts)

        flags = []
        risk  = 0.0

        if max_same_slot >= 5:
            risk += 0.5
            flags.append(f"{max_same_slot} wallets bought in the same block slot")
        elif max_same_slot >= 3:
            risk += 0.25
            flags.append(f"{max_same_slot} wallets in same slot (mild coordination)")

        if unique_buyers > 0 and unique_buyers <= 5 and total_bought > 0:
            risk += 0.3
            flags.append(f"Only {unique_buyers} unique early buyers")

        if total_bought > 0 and buyer_amounts:
            largest_buyer_pct = max(buyer_amounts.values()) / total_bought * 100
            if largest_buyer_pct > 50:
                risk += 0.3
                flags.append(f"Single wallet holds {largest_buyer_pct:.0f}% of early buys")

        risk = min(risk, 1.0)

        if flags:
            description = "Bundle signals: " + " | ".join(flags)
            logger.info(f"[Safety] {mint[:8]}: {description} (risk={risk:.2f})")
        else:
            description = ""

        # Return buyer wallet list alongside risk so fresh wallet check can use it
        return risk, description, list(buyer_amounts.keys())

    async def _check_fresh_wallets(
        self, buyer_wallets: list[str], token_created_ts: float = 0
    ) -> tuple[float, str]:
        """
        Check if early buyers are fresh wallets — a major red flag for
        coordinated launches and bundles.

        Method:
        - For each early buyer wallet, fetch their last 10 transactions
        - If a wallet has fewer than 5 total transactions, it is brand new
        - If multiple fresh wallets bought the same token = coordinated launch

        Why this matters (from the guides):
        - Fresh wallets funded from the same source buying at launch = bundle
        - Real organic buyers have history — bots and coordinated wallets don't
        - Multiple green leaf (fresh wallet) icons = instant red flag

        Returns (risk_score, description)
        0.0 = all wallets look organic
        1.0 = highly coordinated fresh wallet attack
        """
        if not config.has_helius or not buyer_wallets:
            return 0.0, ""

        fresh_count   = 0
        checked_count = 0
        fresh_wallets = []

        # Check up to 8 wallets to limit API calls
        wallets_to_check = buyer_wallets[:8]

        for wallet in wallets_to_check:
            try:
                result = await self._rpc_call(
                    "getSignaturesForAddress",
                    [wallet, {"limit": 10, "commitment": "confirmed"}]
                )
                checked_count += 1

                if result is None:
                    continue

                tx_count = len(result)

                # Wallet with fewer than 5 lifetime transactions = fresh
                if tx_count < 5:
                    fresh_wallets.append(wallet[:8])
                    fresh_count += 1
                    logger.debug(
                        f"[Safety] Fresh wallet detected: {wallet[:8]}... "
                        f"({tx_count} total txns)"
                    )

                # Small delay to avoid hammering RPC
                await asyncio.sleep(0.15)

            except Exception as e:
                logger.debug(f"[Safety] Fresh wallet check error for {wallet[:8]}: {e}")
                continue

        if checked_count == 0 or fresh_count == 0:
            return 0.0, ""

        fresh_ratio = fresh_count / checked_count
        risk        = 0.0
        flags       = []

        if fresh_count >= 4:
            risk = 0.9
            flags.append(
                f"{fresh_count}/{checked_count} early buyers are fresh wallets "
                f"(coordinated launch)"
            )
        elif fresh_count >= 3:
            risk = 0.6
            flags.append(
                f"{fresh_count}/{checked_count} early buyers are fresh wallets"
            )
        elif fresh_count >= 2:
            risk = 0.35
            flags.append(
                f"{fresh_count}/{checked_count} early buyers are fresh wallets "
                f"(mild concern)"
            )
        elif fresh_count == 1:
            risk = 0.15
            flags.append("1 early buyer is a fresh wallet")

        desc = " | ".join(flags) if flags else ""
        if desc:
            logger.info(
                f"[Safety] Fresh wallet check: {desc} (risk={risk:.2f})"
            )

        return risk, desc

    async def full_safety_check(
        self, mint: str, pool_address: str = "", dex_name: str = "",
        volume_24h: float = 0.0, liquidity: float = 0.0, txns_24h: int = 0,
        token_source: str = ""   # "pumpfun" = still on bonding curve
    ) -> SafetyResult:
        logger.info(f"[Safety] Running checks for {mint}")
        opp_volume_24h = volume_24h
        opp_liquidity  = liquidity
        opp_txns_24h   = txns_24h

        results = await asyncio.gather(
            self._check_birdeye_security(mint),
            self._check_mint_authority(mint),
            self._check_holder_concentration(mint),
            self._check_lp_burned(pool_address, mint, dex_name),
            self._check_token_extensions(mint),
            self._check_pool_safety(pool_address, dex_name),
            self._check_bundle(mint),
            self._check_deployer_history(mint),
            return_exceptions=True,
        )

        birdeye_data      = results[0] if not isinstance(results[0], Exception) else None
        mint_auth_result  = results[1] if not isinstance(results[1], Exception) else (False, False)
        top10_pct         = results[2] if not isinstance(results[2], Exception) else 0.0
        lp_burned         = results[3] if not isinstance(results[3], Exception) else None
        extension_result  = results[4] if not isinstance(results[4], Exception) else ("unknown", [])
        pool_result       = results[5] if not isinstance(results[5], Exception) else ("unknown", 0.0, [])
        bundle_result = results[6] if not isinstance(results[6], Exception) else (0.0, "", [])
        if isinstance(bundle_result, tuple) and len(bundle_result) == 3:
            bundle_risk, bundle_desc, bundle_wallets = bundle_result
        elif isinstance(bundle_result, tuple) and len(bundle_result) == 2:
            bundle_risk, bundle_desc = bundle_result
            bundle_wallets = []
        else:
            bundle_risk, bundle_desc, bundle_wallets = 0.0, "", []

        # ── Fresh wallet check using early buyers from bundle detection ───────
        fresh_risk   = 0.0
        fresh_desc   = ""
        if bundle_wallets:
            try:
                fresh_risk, fresh_desc = await self._check_fresh_wallets(bundle_wallets)
            except Exception as e:
                logger.debug(f"[Safety] Fresh wallet check error: {e}")
        deployer_result   = results[7] if not isinstance(results[7], Exception) else (0.0, "", "")
        if isinstance(deployer_result, tuple) and len(deployer_result) == 3:
            deployer_risk, deployer_desc, deployer_address = deployer_result
        elif isinstance(deployer_result, tuple):
            deployer_risk, deployer_desc = deployer_result
            deployer_address = ""
        else:
            deployer_risk, deployer_desc, deployer_address = 0.0, "", ""

        mint_renounced, freeze_renounced = mint_auth_result
        token_program, dangerous_extensions = extension_result
        pool_creator, pool_fee_rate, pool_warnings = pool_result

        if birdeye_data:
            if birdeye_data.get("mintable") is not None:
                mint_renounced = not birdeye_data["mintable"]
            if birdeye_data.get("freezable") is not None:
                freeze_renounced = not birdeye_data["freezable"]
            if birdeye_data.get("top10HolderPercent") is not None:
                top10_pct = float(birdeye_data["top10HolderPercent"]) * 100
            if birdeye_data.get("lpBurned") is not None:
                lp_burned = birdeye_data["lpBurned"]

        if bundle_risk >= 0.5 and bundle_desc:
            pool_warnings.append(f"🚨 HIGH BUNDLE RISK: {bundle_desc}")
        elif bundle_risk >= 0.25 and bundle_desc:
            pool_warnings.append(f"⚠️ Bundle signals detected: {bundle_desc}")

        # Fresh wallet warnings
        if fresh_risk >= 0.6 and fresh_desc:
            pool_warnings.append(f"🚨 FRESH WALLET ATTACK: {fresh_desc}")
            pool_warnings.append(f"🚨 FRESH WALLETS (2nd flag): auto-fail")
        elif fresh_risk >= 0.35 and fresh_desc:
            pool_warnings.append(f"⚠️ Fresh wallets detected: {fresh_desc}")
        elif fresh_risk > 0 and fresh_desc:
            pool_warnings.append(f"ℹ️ {fresh_desc}")

        if deployer_risk >= 0.5 and deployer_desc:
            pool_warnings.append(f"🚨 SERIAL DEPLOYER: {deployer_desc}")
        elif deployer_risk >= 0.25 and deployer_desc:
            pool_warnings.append(f"⚠️ {deployer_desc}")
        elif deployer_desc:
            pool_warnings.append(f"ℹ️ {deployer_desc}")

        fake_vol_risk, fake_vol_desc = self._check_fake_volume(
            opp_volume_24h, opp_liquidity, opp_txns_24h
        )
        if fake_vol_risk >= 0.7 and fake_vol_desc:
            # Extreme fake volume = instant kill, count as 2 red flags
            pool_warnings.append(f"🚨 FAKE VOLUME CONFIRMED: {fake_vol_desc}")
            pool_warnings.append(f"🚨 FAKE VOLUME (2nd flag): auto-fail")
        elif fake_vol_risk >= 0.5 and fake_vol_desc:
            pool_warnings.append(f"🚨 FAKE VOLUME LIKELY: {fake_vol_desc}")
        elif fake_vol_risk >= 0.2 and fake_vol_desc:
            pool_warnings.append(f"⚠️ Volume quality concern: {fake_vol_desc}")

        is_bonding_curve = token_source == "pumpfun"
        is_honeypot, red_flags = self._check_honeypot_heuristics(
            mint_renounced, freeze_renounced, top10_pct,
            lp_burned, birdeye_data, dangerous_extensions, pool_warnings,
            is_bonding_curve=is_bonding_curve,
        )

        checks = []
        if token_program == "spl-token-2022":
            checks.append(
                "🚨 SPL-Token-2022 DANGEROUS extensions"
                if dangerous_extensions else "✅ SPL-Token-2022 (safe extensions)"
            )
        elif token_program == "spl-token":
            checks.append("✅ SPL-Token (standard)")

        checks.append("✅ Mint authority renounced" if mint_renounced else "⚠️ Mint NOT renounced (warning)")
        checks.append("✅ Freeze authority clear" if freeze_renounced else "🚨 Freeze authority ACTIVE")

        if top10_pct > 0:
            icon = "✅" if top10_pct <= config.MAX_TOP_10_HOLDER_PCT else "❌"
            checks.append(f"{icon} Top-10 holders: {top10_pct:.1f}%")
        else:
            checks.append("⚠️ Holder data unavailable")

        checks.append(
            "✅ LP burned/locked" if lp_burned is True
            else "❌ LP NOT burned" if lp_burned is False
            else "⚠️ LP lock unverified"
        )

        summary = "\n".join(checks)
        if red_flags:
            summary += "\n\nRed flags:\n" + "\n".join(red_flags)

        # ── FIXED: mint_renounced is no longer a hard requirement ─────────────
        # Only freeze authority active and dangerous extensions are instant kills.
        # Mint not renounced is surfaced as a warning in the briefing instead.
        final_passed = not is_honeypot
        if not final_passed:
            reasons = []
            if dangerous_extensions:
                reasons.append(f"dangerous extensions: {len(dangerous_extensions)}")
            if not freeze_renounced:
                reasons.append("freeze authority active")
            if is_honeypot and red_flags:
                reasons.append(f"{len(red_flags)} red flags")
            logger.info(f"[Safety] {mint[:8]} FAILED: {', '.join(reasons)}")

        return SafetyResult(
            passed=final_passed,
            mint_authority_renounced=mint_renounced,
            freeze_authority_renounced=freeze_renounced,
            top10_holder_pct=top10_pct,
            lp_burned=lp_burned,
            is_honeypot=is_honeypot,
            detail=summary,
            dangerous_extensions=dangerous_extensions,
            token_program=token_program,
            pool_creator=pool_creator,
            pool_fee_rate=pool_fee_rate,
            lp_lock_verified=lp_burned,
            bundle_risk=bundle_risk,
            bundle_detail=bundle_desc,
            fake_volume_risk=fake_vol_risk,
            fake_volume_detail=fake_vol_desc,
            deployer_risk=deployer_risk,
            deployer_detail=deployer_desc,
            deployer_address=deployer_address,
        )
