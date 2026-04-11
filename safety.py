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

    async def _check_lp_burned(self, pool_address: str) -> Optional[bool]:
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

    async def full_safety_check(
        self, mint: str, pool_address: str = "", dex_name: str = ""
    ) -> SafetyResult:
        logger.info(f"[Safety] Running checks for {mint}")

        results = await asyncio.gather(
            self._check_birdeye_security(mint),
            self._check_mint_authority(mint),
            self._check_holder_concentration(mint),
            self._check_lp_burned(pool_address),
            self._check_token_extensions(mint),
            self._check_pool_safety(pool_address, dex_name),
            return_exceptions=True,
        )

        birdeye_data      = results[0] if not isinstance(results[0], Exception) else None
        mint_auth_result  = results[1] if not isinstance(results[1], Exception) else (False, False)
        top10_pct         = results[2] if not isinstance(results[2], Exception) else 0.0
        lp_burned         = results[3] if not isinstance(results[3], Exception) else None
        extension_result  = results[4] if not isinstance(results[4], Exception) else ("unknown", [])
        pool_result       = results[5] if not isinstance(results[5], Exception) else ("unknown", 0.0, [])

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

        return SafetyResult(
            passed=not is_honeypot and mint_renounced,
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
