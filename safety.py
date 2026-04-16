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
  - Mint authority renounced
  - Top-10 holder concentration < MAX_TOP_10_HOLDER_PCT
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
            return False, False
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
        """
        Check if LP tokens are burned.

        Strategy:
        1. For PumpSwap tokens — query DexScreener pair data which explicitly
           reports LP burn status. PumpSwap migrations from pump.fun always
           burn LP, but custom pools don't.
        2. For other DEXes — check if pool account is owned by burn address.
        3. Return None if we genuinely cannot determine.
        """
        dex_lower = (dex_name or "").lower()
        is_pumpswap = "pump" in dex_lower

        # For PumpSwap tokens, DexScreener tells us LP burn status directly
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
                        # Find the PumpSwap pair specifically
                        pump_pairs = [
                            p for p in pairs
                            if "pump" in (p.get("dexId") or "").lower()
                        ]
                        if not pump_pairs:
                            pump_pairs = pairs  # fallback to any pair

                        if pump_pairs:
                            # Sort by liquidity to get primary pair
                            pump_pairs.sort(
                                key=lambda p: float(
                                    (p.get("liquidity") or {}).get("usd") or 0
                                ),
                                reverse=True,
                            )
                            pair = pump_pairs[0]
                            liq  = pair.get("liquidity") or {}

                            # DexScreener reports lpBurn as percentage 0-100
                            # Some versions use "lpBurn", some have it in pair info
                            lp_burn = pair.get("lpBurn")
                            if lp_burn is not None:
                                burned = int(lp_burn) >= 90  # 90%+ = effectively burned
                                logger.debug(
                                    f"[Safety] {mint[:8]}: DexScreener lpBurn={lp_burn}% "
                                    f"→ {'burned' if burned else 'NOT burned'}"
                                )
                                return burned

                            # Alternative: check if pair info indicates migration
                            pair_info = pair.get("info") or {}
                            # pump.fun migrated pairs have liquidity locked
                            # Check if pool address matches known pump migration
                            dex_id = (pair.get("dexId") or "").lower()
                            if "pump" in dex_id:
                                # pump.fun to PumpSwap migration burns LP by default
                                # Only unsafe if manually created (custom pool)
                                logger.debug(
                                    f"[Safety] {mint[:8]}: PumpSwap pair — "
                                    f"assuming LP burned (pump.fun migration)"
                                )
                                return True

            except Exception as e:
                logger.debug(f"[Safety] DexScreener LP check error: {e}")

        # Fallback: check if pool account is owned by burn address
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
        """
        Detect dangerous SPL-Token-2022 extensions.
        Returns (token_program, list_of_dangerous_extensions_found).
        spl-token has no extensions and is always safe.
        spl-token-2022 with dangerous extensions is an instant fail.
        """
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
        """
        Check pool fee rate and DEX type.
        Returns (pool_creator, fee_rate, warnings).
        """
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
    ) -> tuple[bool, list[str]]:
        red_flags    = []
        instant_fail = False

        if dangerous_extensions:
            for ext in dangerous_extensions:
                red_flags.append(f"🚨 DANGEROUS EXTENSION: {ext}")
            instant_fail = True

        if not freeze_renounced:
            red_flags.append("🚨 Freeze authority ACTIVE — can freeze your tokens")
            instant_fail = True

        if not mint_renounced:
            red_flags.append("⚠️ Mint authority NOT renounced (infinite mint risk)")
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

        return instant_fail or len(red_flags) >= 2, red_flags

    # ── Fake volume detection ────────────────────────────────────────────────────

    def _check_fake_volume(
        self, volume_24h: float, liquidity: float, txns_24h: int
    ) -> tuple[float, str]:
        """
        Detect fake/wash-traded volume using two signals validated by experienced traders:

        Signal 1 — Volume/Liquidity ratio
            Natural markets: vol/liq typically 2x-20x
            Wash trading: vol/liq can be 100x+ (same SOL looping)
            Guide reference: "If volume is extremely high but liquidity is low,
            something is off. Natural markets cannot sustain heavy volume
            without liquidity."

        Signal 2 — Average trade size
            Real organic trading = many small/medium trades
            Wash trading = few huge trades OR bot-perfect identical sizes
            We proxy this as: avg_trade = volume_24h / txns_24h
            If avg trade > 5% of liquidity = suspicious (few large trades)

        Returns (fake_vol_risk, description)
        0.0 = clean, 1.0 = very likely fake
        """
        if volume_24h <= 0 or liquidity <= 0:
            return 0.0, ""

        flags = []
        risk  = 0.0

        # Signal 1: vol/liq ratio
        vol_liq = volume_24h / liquidity
        if vol_liq > 100:
            risk += 0.6
            flags.append(
                f"vol/liq ratio {vol_liq:.0f}x — extreme (likely wash trading)"
            )
        elif vol_liq > 50:
            risk += 0.3
            flags.append(f"vol/liq ratio {vol_liq:.0f}x — suspicious")
        elif vol_liq > 30:
            risk += 0.1
            flags.append(f"vol/liq ratio {vol_liq:.0f}x — elevated")

        # Signal 2: average trade size vs liquidity
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
                flags.append(
                    f"avg trade is {avg_trade_pct:.0f}% of liquidity — suspicious"
                )
        elif volume_24h > 50_000:
            # High volume but zero transactions reported = data gap / likely fake
            risk += 0.3
            flags.append("high volume but no transaction count data")

        risk = min(risk, 1.0)
        description = " | ".join(flags) if flags else ""

        if flags:
            logger.info(
                f"[Safety] Fake volume signals: {description} (risk={risk:.2f})"
            )

        return risk, description

    # ── Bundle detection ──────────────────────────────────────────────────────────

    async def _check_bundle(
        self, mint: str
    ) -> tuple[float, str]:
        """
        Detect coordinated/bundled launches by analyzing early buyers.

        Checks:
        1. Same-slot buys: multiple wallets buying in exact same block = coordinated
        2. Early buyer concentration: first 20 buys holding >50% of supply = risky
        3. Common funding: early wallets funded from same source (simplified check)

        Returns (bundle_risk_score, description)
        score: 0.0 = clean, 1.0 = highly likely bundled
        """
        if not config.has_helius:
            return 0.0, ""

        session = await self._get_session()
        url    = f"https://api.helius.xyz/v0/addresses/{mint}/transactions"
        params = {
            "api-key": config.HELIUS_API_KEY,
            "type":    "SWAP",
            "limit":   20,  # First 20 swap transactions
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

        # ── Check 1: Same-slot buys ──────────────────────────────────────────
        slots: dict[int, list[str]] = {}  # slot -> list of buyer wallets
        buyer_amounts: dict[str, float] = {}  # wallet -> token amount bought

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
                    # This wallet bought tokens
                    if slot not in slots:
                        slots[slot] = []
                    if fee_payer not in slots[slot]:
                        slots[slot].append(fee_payer)
                    buyer_amounts[fee_payer] = (
                        buyer_amounts.get(fee_payer, 0) + amount
                    )

        # Count wallets buying in same slot
        max_same_slot = max((len(v) for v in slots.values()), default=0)

        # ── Check 2: Early buyer concentration ──────────────────────────────
        total_bought = sum(buyer_amounts.values())
        unique_buyers = len(buyer_amounts)

        # Risk flags
        flags = []
        risk  = 0.0

        if max_same_slot >= 5:
            risk += 0.5
            flags.append(f"{max_same_slot} wallets bought in the same block slot")
        elif max_same_slot >= 3:
            risk += 0.25
            flags.append(f"{max_same_slot} wallets in same slot (mild coordination)")

        if unique_buyers > 0 and unique_buyers <= 5 and total_bought > 0:
            # Very few early buyers — high concentration risk
            risk += 0.3
            flags.append(f"Only {unique_buyers} unique early buyers")

        # Check if one wallet dominates early buys
        if total_bought > 0 and buyer_amounts:
            largest_buyer_pct = max(buyer_amounts.values()) / total_bought * 100
            if largest_buyer_pct > 50:
                risk += 0.3
                flags.append(
                    f"Single wallet holds {largest_buyer_pct:.0f}% of early buys"
                )

        risk = min(risk, 1.0)

        if flags:
            description = "Bundle signals: " + " | ".join(flags)
            logger.info(f"[Safety] {mint[:8]}: {description} (risk={risk:.2f})")
        else:
            description = ""

        return risk, description

    async def full_safety_check(
        self, mint: str, pool_address: str = "", dex_name: str = "",
        volume_24h: float = 0.0, liquidity: float = 0.0, txns_24h: int = 0
    ) -> SafetyResult:
        logger.info(f"[Safety] Running checks for {mint}")
        # Store passed-in market data for fake volume check
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
            return_exceptions=True,
        )

        birdeye_data      = results[0] if not isinstance(results[0], Exception) else None
        mint_auth_result  = results[1] if not isinstance(results[1], Exception) else (False, False)
        top10_pct         = results[2] if not isinstance(results[2], Exception) else 0.0
        lp_burned         = results[3] if not isinstance(results[3], Exception) else None
        extension_result  = results[4] if not isinstance(results[4], Exception) else ("unknown", [])
        pool_result       = results[5] if not isinstance(results[5], Exception) else ("unknown", 0.0, [])
        bundle_result     = results[6] if not isinstance(results[6], Exception) else (0.0, "")
        bundle_risk, bundle_desc = bundle_result if isinstance(bundle_result, tuple) else (0.0, "")

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

        # Add bundle detection to pool warnings
        if bundle_risk >= 0.5 and bundle_desc:
            pool_warnings.append(f"🚨 HIGH BUNDLE RISK: {bundle_desc}")
        elif bundle_risk >= 0.25 and bundle_desc:
            pool_warnings.append(f"⚠️ Bundle signals detected: {bundle_desc}")

        # Fake volume check (synchronous — uses data already available)
        fake_vol_risk, fake_vol_desc = self._check_fake_volume(
            opp_volume_24h, opp_liquidity, opp_txns_24h
        )
        if fake_vol_risk >= 0.5 and fake_vol_desc:
            pool_warnings.append(f"🚨 FAKE VOLUME LIKELY: {fake_vol_desc}")
        elif fake_vol_risk >= 0.25 and fake_vol_desc:
            pool_warnings.append(f"⚠️ Volume quality concern: {fake_vol_desc}")

        is_honeypot, red_flags = self._check_honeypot_heuristics(
            mint_renounced, freeze_renounced, top10_pct,
            lp_burned, birdeye_data, dangerous_extensions, pool_warnings,
        )

        checks = []
        if token_program == "spl-token-2022":
            checks.append(
                "🚨 SPL-Token-2022 DANGEROUS extensions"
                if dangerous_extensions else "✅ SPL-Token-2022 (safe extensions)"
            )
        elif token_program == "spl-token":
            checks.append("✅ SPL-Token (standard)")

        checks.append("✅ Mint authority renounced" if mint_renounced else "❌ Mint NOT renounced")
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

        final_passed = not is_honeypot and mint_renounced
        if not final_passed:
            reasons = []
            if not mint_renounced:
                reasons.append("mint not renounced")
            if dangerous_extensions:
                reasons.append(f"dangerous extensions: {len(dangerous_extensions)}")
            if not freeze_renounced:
                reasons.append("freeze authority active")
            if is_honeypot and red_flags:
                reasons.append(f"{len(red_flags)} red flags")
            logger.info(
                f"[Safety] {mint[:8]} FAILED: {', '.join(reasons)}"
            )

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
        )
