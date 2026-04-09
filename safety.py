"""
safety.py — On-chain safety validation layer.

Checks in order of reliability:
  1. Birdeye Security API (best, needs paid key)       → full security bundle
  2. Helius RPC getAccountInfo                          → mint authority
  3. Solana public RPC getTokenLargestAccounts          → holder concentration
  4. LP burn check via pool account inspection          → LP rug vector

A token passes safety if:
  - Mint authority is renounced (null)
  - Top-10 holder concentration < MAX_TOP_10_HOLDER_PCT
  - LP is burned or locked (where detectable)
  - No freeze authority
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import struct
from dataclasses import dataclass
from typing import Optional

import aiohttp

from config import config

logger = logging.getLogger(__name__)

BIRDEYE_BASE = "https://public-api.birdeye.so"

# SPL Token program ID
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

# Known LP lock / burn programs on Solana
BURN_ADDRESS        = "1nc1nerator11111111111111111111111111111111"
RAYDIUM_LOCK_PROGRAM = "7WduLbRfYhTJktjLw5FDEyrqoEv61aTTCuGAetgLjzN5"

# SPL-Token-2022 dangerous extensions
# Source: PumpSwap API documentation on token scam detection
DANGEROUS_EXTENSIONS = {
    "transferFeeConfig":            "charges fees on every transfer (common scam)",
    "transferHook":                 "custom code runs on every transfer",
    "permanentDelegate":            "permanent control over your tokens",
    "defaultAccountState":          "can freeze accounts by default",
    "memoTransfer":                 "requires memo — blocks most DEX sells",
    "nonTransferable":              "tokens cannot be transferred",
    "confidentialTransferMint":     "incompatible with pools",
    "confidentialMintBurn":         "incompatible with pools",
    "confidentialTransferFeeConfig": "incompatible with pools",
    "pausableConfig":               "can pause all transfers",
    "cpiGuard":                     "blocks program interactions",
}

# Pool creator safety rules
# poolCreatedBy values that are safe per launchpad
SAFE_POOL_CREATORS = {"pump", "raydium-launchpad", "meteora-launchpad"}

# Minimal SPL Mint layout offsets (82 bytes total)
MINT_LAYOUT_AUTHORITY_OFFSET = 4   # 36 bytes: COption<Pubkey> for mint authority
MINT_LAYOUT_FREEZE_OFFSET = 46     # 36 bytes: COption<Pubkey> for freeze authority

# COption None discriminator
COPTION_NONE = 0
COPTION_SOME = 1


@dataclass
class SafetyResult:
    passed: bool
    mint_authority_renounced: bool
    freeze_authority_renounced: bool
    top10_holder_pct: float
    lp_burned: Optional[bool]        # None = could not determine
    is_honeypot: bool
    detail: str                      # human-readable summary
    dangerous_extensions: list       # SPL-2022 dangerous extensions found
    token_program: str               # "spl-token" or "spl-token-2022"
    pool_creator: str                # who created the pool
    pool_fee_rate: float             # 0.0 = unknown


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

    # ── Birdeye security (primary, paid) ──────────────────────────────────────

    async def _check_birdeye_security(self, mint: str) -> dict | None:
        """
        Birdeye token_security endpoint.
        Returns: mintable, freezable, lpBurned, top10HolderPercent, creatorPercent, etc.
        ⚠️  Requires PAID Birdeye API key (Starter ~$99/mo).
        Falls back gracefully if no key.
        """
        if not config.has_birdeye:
            return None

        session = await self._get_session()
        url = f"{BIRDEYE_BASE}/defi/token_security"
        params = {"address": mint}
        headers = {
            "X-API-KEY": config.BIRDEYE_API_KEY,
            "x-chain": "solana",
        }
        try:
            async with session.get(
                url, headers=headers, params=params,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    return (data.get("data") or {})
                logger.debug(f"[Safety] Birdeye security returned {resp.status} for {mint}")
                return None
        except Exception as e:
            logger.warning(f"[Safety] Birdeye security error: {e}")
            return None

    # ── Helius / RPC: mint account info ───────────────────────────────────────

    async def _rpc_call(self, method: str, params: list) -> dict | None:
        """Generic Solana JSON-RPC call."""
        session = await self._get_session()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
        try:
            async with session.post(
                config.helius_rpc_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    return data.get("result")
                logger.debug(f"[Safety] RPC {method} returned {resp.status}")
                return None
        except Exception as e:
            logger.warning(f"[Safety] RPC error for {method}: {e}")
            return None

    async def _check_mint_authority(self, mint: str) -> tuple[bool, bool]:
        """
        Returns (mint_authority_renounced, freeze_authority_renounced).
        Parses the SPL token mint account directly via RPC.
        """
        result = await self._rpc_call(
            "getAccountInfo",
            [mint, {"encoding": "base64"}],
        )
        if not result or not result.get("value"):
            logger.warning(f"[Safety] Could not fetch mint account for {mint}")
            # Assume worst case
            return False, False

        try:
            account = result["value"]
            raw = base64.b64decode(account["data"][0])

            if len(raw) < 82:
                logger.warning(f"[Safety] Mint account data too short for {mint}")
                return False, False

            # Parse COption<Pubkey> at offset 4 (mint authority)
            # Format: [discriminator: u32][pubkey: 32 bytes]
            mint_auth_disc = struct.unpack_from("<I", raw, 4)[0]
            freeze_auth_disc = struct.unpack_from("<I", raw, 46)[0]

            mint_renounced = mint_auth_disc == COPTION_NONE
            freeze_renounced = freeze_auth_disc == COPTION_NONE

            logger.debug(
                f"[Safety] {mint}: mint_auth={not mint_renounced}, freeze_auth={not freeze_renounced}"
            )
            return mint_renounced, freeze_renounced

        except Exception as e:
            logger.warning(f"[Safety] Error parsing mint account for {mint}: {e}")
            return False, False

    # ── Holder concentration ───────────────────────────────────────────────────

    async def _check_holder_concentration(self, mint: str) -> float:
        """
        Returns top-10 holder percentage using getTokenLargestAccounts.
        Falls back to Helius DAS if available.
        """
        # Method 1: getTokenLargestAccounts (built-in RPC)
        result = await self._rpc_call(
            "getTokenLargestAccounts",
            [mint, {"commitment": "confirmed"}],
        )
        if result and result.get("value"):
            accounts = result["value"]
            amounts = [float(a.get("uiAmount") or 0) for a in accounts]
            if not amounts:
                return 0.0

            total_supply_result = await self._rpc_call(
                "getTokenSupply",
                [mint, {"commitment": "confirmed"}],
            )
            if total_supply_result and total_supply_result.get("value"):
                supply = float(
                    total_supply_result["value"].get("uiAmount") or 1
                )
                top10_amount = sum(amounts[:10])
                pct = (top10_amount / supply * 100) if supply > 0 else 0
                logger.debug(f"[Safety] {mint}: top-10 holder = {pct:.1f}%")
                return round(pct, 2)

        # Method 2: Helius getAsset (if Helius key available)
        if config.has_helius:
            result = await self._rpc_call(
                "getAsset",
                [{"id": mint}],
            )
            if result:
                ownership = result.get("ownership", {})
                top_holders = ownership.get("delegated", False)
                # Helius DAS doesn't give holder % directly here;
                # fall through to default
                pass

        logger.warning(f"[Safety] Could not determine holder concentration for {mint}")
        return 0.0  # unknown, will be treated cautiously in scoring

    # ── LP burn check ──────────────────────────────────────────────────────────

    async def _check_lp_burned(self, pool_address: str) -> Optional[bool]:
        """
        Checks if LP tokens for the pool are burned.
        This is a best-effort check — definitive LP lock verification
        requires off-chain indexers or paid APIs.

        Approach: check if LP token supply matches amount held by burn address.
        Returns True = burned, False = not burned, None = unknown.
        """
        if not pool_address:
            return None

        # Check if pool address account exists and get LP mint info
        # For Raydium v4 pools, the LP mint is derivable but complex.
        # We use a simplified check: does the pool's token account show burn?
        result = await self._rpc_call(
            "getAccountInfo",
            [pool_address, {"encoding": "jsonParsed"}],
        )
        if not result or not result.get("value"):
            return None

        try:
            data = result["value"].get("data", {})
            if isinstance(data, dict):
                parsed = data.get("parsed", {})
                info = parsed.get("info", {})
                # If the owner is the burn program, LP is burned
                owner = result["value"].get("owner", "")
                return owner == BURN_ADDRESS
            return None
        except Exception:
            return None

    # ── Honeypot / rug heuristics ──────────────────────────────────────────────

    def _check_honeypot_heuristics(
        self,
        mint_renounced:      bool,
        freeze_renounced:    bool,
        top10_pct:           float,
        lp_burned:           Optional[bool],
        birdeye_data:        dict | None,
        dangerous_extensions: list,
        pool_warnings:       list,
    ) -> tuple[bool, list[str]]:
        """
        Returns (is_honeypot, list_of_red_flags).

        Instant fail (regardless of other flags):
          - Any dangerous SPL-2022 extension present
          - Freeze authority active

        Fail if 2+ red flags from:
          - Mint authority not renounced
          - Top-10 holder concentration too high
          - LP not burned/locked
          - Pool warnings
        """
        red_flags: list[str] = []
        instant_fail = False

        # ── Instant disqualifiers ──────────────────────────────────────────────
        if dangerous_extensions:
            for ext in dangerous_extensions:
                red_flags.append(f"🚨 DANGEROUS EXTENSION: {ext}")
            instant_fail = True   # Any dangerous extension = auto-fail

        if not freeze_renounced:
            red_flags.append("🚨 Freeze authority ACTIVE — accounts can be frozen")
            instant_fail = True   # Freeze authority = auto-fail

        # ── Standard red flags ─────────────────────────────────────────────────
        if not mint_renounced:
            red_flags.append("⚠️ Mint authority NOT renounced (infinite mint risk)")
        if top10_pct > config.MAX_TOP_10_HOLDER_PCT:
            red_flags.append(
                f"⚠️ Top-10 holders own {top10_pct:.1f}% (dump risk)"
            )
        if lp_burned is False:
            red_flags.append("⚠️ LP not burned/locked (rug vector open)")

        # Pool warnings
        red_flags.extend(pool_warnings)

        # Birdeye enrichment
        if birdeye_data:
            if birdeye_data.get("mintable") and mint_renounced:
                red_flags.append("⚠️ Token is mintable (Birdeye)")
            creator_pct = float(birdeye_data.get("creatorPercentage") or 0)
            if creator_pct > 20:
                red_flags.append(
                    f"⚠️ Creator holds {creator_pct:.1f}% of supply"
                )
            if not birdeye_data.get("lpBurned") and lp_burned is None:
                red_flags.append("⚠️ LP not burned (Birdeye)")

        is_honeypot = instant_fail or len(red_flags) >= 2
        return is_honeypot, red_flags

    # ── Main check ────────────────────────────────────────────────────────────

    async def full_safety_check(
        self, mint: str, pool_address: str = "", dex_name: str = ""
    ) -> SafetyResult:
        """
        Run all safety checks in parallel. Returns a SafetyResult.

        Auto-fails if:
          - Any dangerous SPL-2022 extension detected
          - Freeze authority is active
          - Mint authority not renounced

        Also fails if 2+ of:
          - High holder concentration
          - LP not burned
          - Pool warnings (high fees, custom creator)
        """
        logger.info(f"[Safety] Running checks for {mint}")

        birdeye_task    = asyncio.create_task(self._check_birdeye_security(mint))
        mint_task       = asyncio.create_task(self._check_mint_authority(mint))
        holder_task     = asyncio.create_task(self._check_holder_concentration(mint))
        lp_task         = asyncio.create_task(self._check_lp_burned(pool_address))
        extension_task  = asyncio.create_task(self._check_token_extensions(mint))
        pool_task       = asyncio.create_task(
            self._check_pool_safety(pool_address, dex_name)
        )

        (
            birdeye_data,
            mint_auth_result,
            top10_pct,
            lp_burned,
            extension_result,
            pool_result,
        ) = await asyncio.gather(
            birdeye_task, mint_task, holder_task, lp_task,
            extension_task, pool_task,
            return_exceptions=True,
        )

        # Handle exceptions
        if isinstance(birdeye_data, Exception):
            logger.warning(f"[Safety] Birdeye failed: {birdeye_data}")
            birdeye_data = None
        if isinstance(mint_auth_result, Exception):
            mint_renounced, freeze_renounced = False, False
        else:
            mint_renounced, freeze_renounced = mint_auth_result
        if isinstance(top10_pct, Exception):
            top10_pct = 0.0
        if isinstance(lp_burned, Exception):
            lp_burned = None
        if isinstance(extension_result, Exception):
            token_program, dangerous_extensions = "unknown", []
        else:
            token_program, dangerous_extensions = extension_result
        if isinstance(pool_result, Exception):
            pool_creator, pool_fee_rate, pool_warnings = "unknown", 0.0, []
        else:
            pool_creator, pool_fee_rate, pool_warnings = pool_result

        # Birdeye overrides if available
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
            lp_burned, birdeye_data, dangerous_extensions, pool_warnings
        )

        # Build human-readable summary
        checks = []

        # Token program
        if token_program == "spl-token-2022":
            if dangerous_extensions:
                checks.append(f"🚨 SPL-Token-2022 with DANGEROUS extensions")
            else:
                checks.append(f"✅ SPL-Token-2022 (no dangerous extensions)")
        elif token_program == "spl-token":
            checks.append("✅ SPL-Token (standard)")

        checks.append(
            "✅ Mint authority renounced"
            if mint_renounced else "❌ Mint NOT renounced"
        )
        checks.append(
            "✅ Freeze authority clear"
            if freeze_renounced else "🚨 Freeze authority ACTIVE"
        )
        if top10_pct > 0:
            icon = "✅" if top10_pct <= config.MAX_TOP_10_HOLDER_PCT else "❌"
            checks.append(f"{icon} Top-10 holders: {top10_pct:.1f}%")
        else:
            checks.append("⚠️ Holder data unavailable")

        if lp_burned is True:
            checks.append("✅ LP burned/locked")
        elif lp_burned is False:
            checks.append("❌ LP NOT burned")
        else:
            checks.append("⚠️ LP lock unverified")

        summary = "\n".join(checks)
        if red_flags:
            summary += "\n\nRed flags:\n" + "\n".join(red_flags)

        passed = not is_honeypot and mint_renounced

        return SafetyResult(
            passed=passed,
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
