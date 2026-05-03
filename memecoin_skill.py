"""
╔══════════════════════════════════════════════════════════════════════════════════╗
║          MEMECOIN PROFITABILITY ARCHITECT — DUAL-FORMAT SKILL                   ║
║          Claude Reference Guide + Python Codex Module                           ║
║          Extracted from: The Ultimate Memecoin Playbook for Noobs               ║
║                          A Complete Meme Coin Guide (Spyzer)                   ║
╚══════════════════════════════════════════════════════════════════════════════════╝

════════════════════════════════════════════════════════════════════════════════════
PART 1 — CLAUDE-COMPATIBLE REFERENCE GUIDE
════════════════════════════════════════════════════════════════════════════════════

─── CORE PHILOSOPHY ────────────────────────────────────────────────────────────────
• Onchain markets are transparent and data-driven — NOT a casino when approached
  with structure. Every transaction is public and inspectable.
• Price lies, volume lies, hype lies — wallets do not lie.
• The edge is preparation: liquidity literacy, wallet reading, narrative timing,
  and emotional discipline.
• Most traders lose not to bad coin selection but to bad sizing, no exit plan,
  and emotional entries. Trade management > entry selection.


─── SECTION 1: TOKEN SAFETY CHECKLIST ─────────────────────────────────────────────
(Apply in this sequence before any entry. CONFIDENCE: HIGH)

STEP 1 — LIQUIDITY CHECK (GMGN / Dexscreener / Axiom)
  ✅ Liquidity > $5,000
  ✅ Liquidity LOCKED (not just present)
  ✅ Lock expiry is at least 1 week out
  ✅ Ideally: liquidity BURNT (permanent, safest)
  ❌ Unlocked liquidity → dev can rug instantly
  ❌ Liquidity < $1,000 → extreme slippage risk
  ❌ Suspicious relocks (locked, then unlocked, then relocked) → red flag

STEP 2 — CONTRACT PARAMETERS (Solscan / Axiom / GMGN)
  ✅ Mint authority: DISABLED
  ✅ Freeze authority: OFF
  ✅ Metadata: locked or stable
  ❌ Mint enabled → dev can inflate supply and drain pool
  ❌ Freeze enabled → honeypot (you can buy but not sell)

STEP 3 — DEPLOYER WALLET HISTORY (Axiom / Solscan)
  ✅ No rug history on previous projects
  ✅ No repeated suspicious patterns
  ✅ No sudden wallet funding right before deployment
  ✅ Funding source is not a known scam wallet
  ❌ If deployer has rug pattern: walk away immediately

STEP 4 — HOLDER DISTRIBUTION (Bubble Maps / Axiom / GMGN)
  ✅ No single wallet > 5% (caution zone)
  ✅ No single wallet > 3.5% in active trading conditions
  ✅ Top 10 holders combined < 20%
  ✅ Wallets are independent (not clustered/linked)
  ✅ Distribution spread looks organic across many wallet sizes
  ❌ Giant connected clusters → farm setup or coordinated dump
  ❌ Multiple wallets with identical holdings → multiwallet trap

STEP 5 — VOLUME / FEE RATIO TEST (Axiom / GMGN analytics tab)
  ✅ Fees ≈ 1/20 of 24h volume (5%)
  THRESHOLD: Fees should be ≥ 1/30 of volume (≈3.3%)
  ❌ Fees < 1/30 of volume → volume is fake (wash traded / botted)
  ❌ $1M volume with < 25 SOL fees → not organic
  Note: A 15k MC coin should have > 0.5 SOL in fees

STEP 6 — VOLUME vs MARKET CAP RATIO (Dexscreener)
  ✅ Volume ≥ 80% of MC (especially on new launches)
  ✅ Young coins: volume should significantly exceed MC
  ❌ Volume < 50% of MC on a new coin → supply-controlled / bundled
  ❌ High MC, very low volume → fake or manipulated price

STEP 7 — EARLY TRANSACTION PATTERNS (Solscan / GMGN / Axiom)
  ✅ Varied buy amounts (organic)
  ✅ Irregular timing between buys
  ✅ Mixed wallet types (not all fresh)
  ✅ Natural fear-selling present (not only buys)
  ❌ Identical buy amounts → botted
  ❌ Perfect timing intervals → automated
  ❌ No sells for extended period → controlled/fake
  ❌ Multiple fresh wallets (green leaf icon) in top holders → red flag
  ❌ "Staircase pattern" on chart → bundled


─── SECTION 2: FAKE VOLUME DETECTION SYSTEM ────────────────────────────────────────
(CONFIDENCE: HIGH — derived from guide's own stated method)

PRIMARY METHOD: Volume-to-Fee Ratio
  Formula: fee_ratio = fees_24h / volume_24h
  Threshold:
    fee_ratio ≥ 0.033 (1/30)  → organic range
    fee_ratio ≥ 0.050 (1/20)  → clean
    fee_ratio < 0.033          → FAKE VOLUME FLAG
    fee_ratio < 0.010          → LIKELY BOT/WASH TRADE — avoid

SECONDARY SIGNALS (visual confirmation):
  ❌ Smooth, unbroken upward chart with zero pullbacks
  ❌ Candles of identical size repeating
  ❌ Sells appear but price doesn't drop (bot immediately buys back)
  ❌ Price closes exactly where it opened after sells
  ❌ Volume very high but liquidity very low
     Example: $800k volume on $5k liquidity → physically impossible organically

SECONDARY SIGNALS (wallet confirmation via Bubble Maps):
  ❌ Wallets in connected clusters all trading similar amounts
  ❌ Multiple wallets funded from same source
  ❌ Sniping patterns: multiple wallets buying same second at launch


─── SECTION 3: BONDING CURVE MECHANICS & PLAYBOOK ──────────────────────────────────
(Solana pump.fun specific. CONFIDENCE: HIGH)

WHAT IT IS:
  A pricing mechanism where price increases as more tokens are bought.
  Ends when liquidity is added and the token becomes a real DEX pair.

THE 100K DIP-RECLAIM PATTERN (observed across hundreds of events):
  1. Token bonds → spikes to ~$100k market cap
  2. Dips 40–60%
  3. Either DIES (no reclaim) or forms a HIGHER HIGH
  Strong tokens: reclaim → this is where most strong moves begin

STRATEGIES:
  Strategy 1 — Pre-Bond Accumulation (lowest risk entry):
    Conditions: stable chart + clean distribution + rising holder count
                + natural volume + trustworthy deployer
    Action: buy before the bonding spike
    Exit: sell INTO the spike

  Strategy 2 — Post-Bond Spike Sell:
    Action: sell quickly into the bonding spike
    Do NOT hold through the spike hoping for continuation

  Strategy 3 — Dip Rebuy (moderate risk):
    Conditions: dip ~50% from bond high, new wallets entering,
                holder count growing, dev active, Axiom shows no new clusters
    Action: re-enter for reclaim play

  Strategy 4 — Hold Through Reclaim (HIGH RISK — experienced only):
    Hold from pre-bond through spike, dip, and sell into reclaim
    Beginners should NOT use this

PRE-BOND SIGNALS TO WATCH:
  ✅ Rising volume + rising holder count
  ✅ Clean distribution (no clusters)
  ✅ Steady new buys + dev activity increasing
  ✅ Whale entries beginning (Axiom)
  ✅ Social sentiment increasing
  ✅ GMGN shows pre-bond hype

BONDING TRAP RED FLAGS:
  ❌ Supply concentrated in top wallets
  ❌ Volume is fake (low fees)
  ❌ Heavy bundling
  ❌ Early snipers dominate supply
  ❌ Whales EXITING before bond (not entering)


─── SECTION 4: NARRATIVE TRADING FRAMEWORK ─────────────────────────────────────────
(CONFIDENCE: HIGH)

THREE NARRATIVE STAGES (must identify current stage):
  A. EMERGING (most profitable — enter here):
     Signals: multiple traders mention same idea independently,
              few wallets buying related tokens, small volume spikes
              in the same category, Axiom shows early accumulation,
              Telegram groups starting discussion, X threads referencing concept
     Action: enter small, build position

  B. PEAK (tradeable but high discipline required):
     Signals: everyone knows, tokens pump fast, FOMO everywhere,
              influencers loud, social media chaotic
     Strategy: enter small, take profit EARLY, watch whales (not influencers),
               use GMGN to monitor if whales exiting, short bursts not long holds

  C. END-STAGE (avoid as holder, watch as exit):
     Signals: holder count dropping, volume dropping, hype slowing,
              no new wallets, dev goes quiet, GMGN removes related tokens,
              conversation fading across groups
     Action: DO NOT hold hoping for revival. Exit.

NARRATIVE CONFIRMATION CHECKLIST (before entering narrative play):
  1. Confirm the narrative is real (not manufactured)
  2. Confirm chart has stable distribution (Bubble Maps)
  3. Confirm GMGN shows organic volume (fee ratio)
  4. Confirm Axiom shows real wallets entering
  5. Enter small → scale only after conviction → take profit as it grows

NARRATIVE HEAT AMPLIFIERS (signals narrative is strengthening):
  Smart money entries + social clusters + consistent buys +
  new wallets joining + volume spikes + dev announcements


─── SECTION 5: WALLET MONITORING & SMART MONEY TRACKING ────────────────────────────
(CONFIDENCE: HIGH)

SMART MONEY IDENTIFICATION (wallets that show):
  • Early entries before hype (not chasing)
  • High win rate across multiple tokens
  • Consistent exit timing at peaks
  • Organic historical wins (not single lucky trade)
  • Spread across many plays (not concentrated single tokens)
  • Avoid low-cap scams and obvious traps

HOW TO BUILD A PRIVATE SMART MONEY DATABASE:
  1. Find a coin that had a coordinated KOL push
  2. On GMGN/Dexscreener, zoom into the early acceleration candles (minute-by-minute)
  3. Click into the trades feeding the breakout candles
  4. Identify wallets that entered BEFORE the narrative formed
  5. Paste each wallet into GMGN wallet tracker
  6. Study: past buys, average hold time, how early they enter,
            win rate across multiple charts, narrative rotation patterns
  7. Repeat across 10–30 tokens to find recurring wallets
  8. These wallets won't appear on public leaderboards — that's the edge

WHALE BEHAVIOR TAXONOMY:
  Builder Whale:   accumulates slowly, holds through volatility (bullish signal)
  Swing Whale:     buys dips, sells tops repeatedly (follow their rhythm)
  Exit Whale:      accumulates early, nukes chart later (AVOID if identified)
  Bot Whale:       precise timing, pattern-based (detectable via Axiom)
  Narrative Whale: buys when narrative heats up (confirms narrative is real)

SMART MONEY EXIT SIGNALS (reduce/exit position when):
  • Token reaches peak mindshare
  • Volume spikes aggressively
  • Inexperienced traders flooding in
  • GMGN shows overextension
  • Axiom shows whales selling
  • Distribution tightening (supply concentrating)
  • Narrative slowing


─── SECTION 6: DEAD PLAY REVIVAL DETECTION ─────────────────────────────────────────
(CONFIDENCE: HIGH)

REVIVAL PATTERN SEQUENCE:
  1. Long flat/sideways period
  2. Small volume increases
  3. A few new buyers appear
  4. Holder count starts rising
  5. Early green candles form
  6. Narrative returns or connects to current meta
  7. Social interest appears
  8. Smart money steps in
  9. Chart wakes up violently
  → If you enter at step 2–4, you're ahead of the market

SAFE REVIVAL ENTRY CHECKLIST:
  ✅ Clean distribution (Bubble Maps)
  ✅ Liquidity still locked
  ✅ No rug history
  ✅ New wallets entering organically
  ✅ Small but consistent buys
  ✅ Slow rise in holder count
  ✅ Axiom shows whale interest
  ✅ Narrative connects to current market meta

FAKE REVIVAL RED FLAGS:
  ❌ Volume-to-fee ratio fails
  ❌ Repetitive buy patterns (botted)
  ❌ Multiwallet activity detected
  ❌ Unnatural price curve (too smooth)
  ❌ Deployer wallet moving suspiciously
  ❌ Price pumping with zero social mentions

WHY OG TOKENS ARE SOMETIMES SAFER:
  • Dev already had chance to rug (and didn't, or the token survived)
  • Existing community with proven holders
  • Often burnt liquidity
  • Known deployer history
  • Built-in mindshare (people remember them)


─── SECTION 7: CAPITAL MANAGEMENT RULES ────────────────────────────────────────────
(CONFIDENCE: HIGH)

PORTFOLIO BUCKETS:
  30% — High Conviction (deeply researched, closely followed)
  40% — Active Trades (narratives, new pairs, revivals, momentum)
  30% — Stability / Reserves (buffer for dips and surprise opportunities)

POSITION SIZING:
  • Risk 3–10% per trade maximum
  • NEVER all-in (or even half) on one play
  • Size so that if it goes to zero: you can still trade normally tomorrow
  • Scale conviction with size:
      Strong edge + few people know → larger size
      Public information + timing edge → smaller size
  • Spreading kills returns — concentrated conviction > thin diversification
  • Never martingale more than 3x

TAKE PROFIT TRIGGERS (do NOT wait for "a little more"):
  • Hit 2x → take first portion
  • Volume spikes → take portion
  • GMGN trends flip → take portion
  • Whales begin distributing → take portion
  • Narrative slowing → take portion
  • RULE: "Would I buy this coin right now at this price?" If NO → sell something

STOP-LOSS / EXIT TRIGGERS:
  • Chart structure breaks (lower low below expected support)
  • Whales exit heavily (Axiom confirmation)
  • Volume collapses
  • Distribution worsens (supply concentrating)
  • Your thesis changes
  → Never hold hope, never hold ego, never hold blind conviction

LOSING STREAK PROTOCOL:
  • Reduce size
  • Avoid revenge trades (most destructive habit)
  • Avoid new pairs and hype tokens
  • Trade only clean, confirmed setups
  • Rest if necessary
  • Losses are normal. Large losses are avoidable.


─── SECTION 8: TRADING WINDOWS (WAT = West Africa Time) ─────────────────────────────
(CONFIDENCE: MEDIUM — based on author observation, not universal law)

PRIME WINDOWS:
  6 PM – 10 PM WAT:  High volume, narrative rotation, smart money active,
                      clean breakouts, best for new pairs + revival plays
  3 AM –  7 AM WAT:  Asia wake-up, quiet but strong moves, early accumulation,
                      pre-migration setups work well here

PRE-PUMP SIGNAL WINDOW:
  ~2 AM WAT:  Early accumulation begins, first volume sparks, smart money probes

DANGER WINDOWS (avoid if beginner):
  11 AM – 2 PM WAT:  Slow chart, fake pumps, volume manipulation
  Post-midnight dead zone (no broader narrative): high rug probability,
                                                   high slippage, unpredictable candles

MOST RUGS OCCUR:
  • Low volume hours
  • Transition between time zones
  • Early mornings with no liquidity
  • Periods of rapid hype cooling


─── SECTION 9: MARTINGALE / CONTROLLED JEETING RULES ───────────────────────────────
(CONFIDENCE: HIGH — with strict conditions)

WHEN MARTINGALE WORKS:
  ✅ Liquidity > $10,000
  ✅ Volume > $100,000 per 24h
  ✅ Real distribution (Axiom + Bubble Maps confirmed)
  ✅ Natural volatility (predictable bounce rhythm)
  ✅ Mindshare active (narrative token)
  ✅ Holder count rising

WHEN MARTINGALE FAILS / STOP IMMEDIATELY:
  ❌ Liquidity low
  ❌ Volume fake (fee ratio fails)
  ❌ Token dying (holder count dropping)
  ❌ Whales exiting
  ❌ Distribution concentrating
  ❌ Social signals disappearing
  HARD RULE: Never double more than 3 times. Ever.

CONTROLLED JEETING SEQUENCE:
  1. Buy small on red candle
  2. Sell at clean 2x or logical resistance
  3. If dips again: double amount
  4. Sell again on next bounce
  5. Repeat until market structure changes
  6. After win: RESET to base amount (do not compound into increasing sizes)
  
  Works best on: mid-caps, tokens with active communities, high volatility + liquidity


─── SECTION 10: KOL / INFLUENCER TRUST FRAMEWORK ───────────────────────────────────
(CONFIDENCE: HIGH)

RED FLAGS (KOL is extracting, not informing):
  ❌ Gained following from one lucky trade (lottery ticket ≠ good trader)
  ❌ Posts coin → it pumps 3x in 10 min → then nukes to zero → post deleted
  ❌ Multiple KOLs posting same coin "independently" (coordinated bundle)
  ❌ Follower count inflated (bots)
  ❌ Can't trace their wallet confirming they actually hold what they're shilling

GREEN FLAGS:
  ✅ Writes full thesis with reasoning
  ✅ Gives updates as new info arrives (good AND bad)
  ✅ Admits when calls went wrong
  ✅ Consistent win rate over many months
  ✅ Wallet address shows they bought before posting bullishly
  ✅ Low-follower account that found coin early with genuine thesis
    (more valuable than large account shilling it)

RULE: Use KOL channels as information streams to surface coins.
       Do NOT use them as buy signals.
       If you can't explain in 2 sentences why you're buying → don't buy.


─── SECTION 11: COMMON CAPITAL-DRAINING MISTAKES ───────────────────────────────────
(CONFIDENCE: HIGH — explicitly stated in both guides)

1. Buying on FOMO (green candles, influencer posts, trending lists)
2. No written thesis before entry
3. No exit plan defined before entry
4. Ignoring holder distribution while chasing chart patterns
5. Martingale on weak/low-liquidity/dying tokens
6. Holding through narrative death ("hoping for revival")
7. Revenge trading after a loss (most accounts destroyed this way)
8. Oversizing due to overconfidence
9. Spreading capital across 20+ coins (winners don't move needle, losers add up)
10. Not taking profits on life-changing amounts (roundtrip trap)
11. Copying wallets blindly (leaderboard wallets have no edge by the time you see them)
12. Trusting social verification (gold/blue checkmark means nothing)
13. Clicking links in crypto DMs (phishing, drain links)
14. Keeping funds on CEX long-term (not your keys = not your wallet)


─── SECTION 12: REGULATORY NOTE ────────────────────────────────────────────────────
(CONFIDENCE: HIGH — guide text direct)

Both guides state explicitly:
  "The crypto market is unregulated in many jurisdictions."
  "Certain activities described may be restricted or illegal in your country or region."
  "It is solely your responsibility to ensure that your trading activities comply
   with the laws and regulations of your jurisdiction."
  
  Trading memecoins may involve unregistered securities, tax obligations, and AML
  compliance requirements depending on your jurisdiction. Guides do not specify
  thresholds, reporting requirements, or specific legal obligations.
  DYOR on local regulations.


════════════════════════════════════════════════════════════════════════════════════
PART 2 — PYTHON CODEX MODULE
════════════════════════════════════════════════════════════════════════════════════
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


# ─── ENUMS & DATA STRUCTURES ────────────────────────────────────────────────────

class RiskLevel(Enum):
    SAFE    = "SAFE"
    CAUTION = "CAUTION"
    HIGH    = "HIGH RISK"
    AVOID   = "AVOID"


class NarrativeStage(Enum):
    EMERGING    = "EMERGING"     # Most profitable — enter here
    PEAK        = "PEAK"         # Short burst only, high discipline
    END_STAGE   = "END-STAGE"    # Exit, do not hold
    UNKNOWN     = "UNKNOWN"


@dataclass
class TokenSafetyReport:
    overall_risk:       RiskLevel
    fake_volume:        bool
    liquidity_ok:       bool
    deployer_ok:        bool
    distribution_ok:    bool
    contract_ok:        bool
    flags:              list  = field(default_factory=list)
    green_flags:        list  = field(default_factory=list)
    score:              int   = 0      # 0–100, higher = safer
    recommendation:     str   = ""


@dataclass
class NarrativeReport:
    stage:              NarrativeStage
    confidence:         str    # "HIGH" / "MEDIUM" / "LOW"
    entry_recommended:  bool
    flags:              list   = field(default_factory=list)
    action:             str    = ""


@dataclass
class MartingaleReport:
    eligible:           bool
    reason:             str
    max_doubles:        int    = 3     # Hard limit from guides
    flags:              list   = field(default_factory=list)


@dataclass
class PositionSizeReport:
    suggested_pct:      float   # % of portfolio
    suggested_usd:      float
    bucket:             str     # "HIGH_CONVICTION" / "ACTIVE" / "SPECULATIVE"
    notes:              str     = ""


# ─── MODULE 1: FAKE VOLUME DETECTOR ─────────────────────────────────────────────

def detect_fake_volume(
    volume_24h: float,
    fees_24h: float,
    liquidity: Optional[float] = None
) -> dict:
    """
    Detect fake/washed volume using the volume-to-fee ratio method.

    From guides:
      Clean volume pays fees ~1/20 (5%) of total volume.
      Farmed volume pays almost none.
      Threshold: if fees < 1/30 of volume → volume is not organic.
      A $1M volume token should show 25–60 SOL in fees.
      A 15k MC coin should have > 0.5 SOL in fees.

    Args:
        volume_24h:  24-hour trading volume in USD
        fees_24h:    24-hour fees paid in USD
        liquidity:   Current liquidity in USD (optional, for secondary check)

    Returns:
        dict with keys: is_fake, fee_ratio, risk_level, flags, recommendation
    """
    flags = []
    result = {
        "is_fake": False,
        "fee_ratio": 0.0,
        "risk_level": RiskLevel.SAFE,
        "flags": flags,
        "recommendation": ""
    }

    if volume_24h <= 0:
        result["is_fake"] = True
        result["risk_level"] = RiskLevel.AVOID
        flags.append("Volume is zero or negative — data error or dead token")
        result["recommendation"] = "Do not enter."
        return result

    fee_ratio = fees_24h / volume_24h
    result["fee_ratio"] = round(fee_ratio, 4)

    if fee_ratio < 0.010:
        result["is_fake"] = True
        result["risk_level"] = RiskLevel.AVOID
        flags.append(
            f"Fee ratio {fee_ratio:.4f} is critically low (< 1%) "
            "— strong bot/wash-trade signal"
        )
    elif fee_ratio < 0.033:          # Below 1/30 threshold
        result["is_fake"] = True
        result["risk_level"] = RiskLevel.HIGH
        flags.append(
            f"Fee ratio {fee_ratio:.4f} is below 1/30 threshold (3.3%) "
            "— volume is likely not organic"
        )
    elif fee_ratio < 0.050:          # Below ideal 1/20
        result["risk_level"] = RiskLevel.CAUTION
        flags.append(
            f"Fee ratio {fee_ratio:.4f} is below clean range (5%) "
            "— monitor for bundling"
        )
    else:
        result["risk_level"] = RiskLevel.SAFE
        result["recommendation"] = "Volume appears organic. Continue to next checks."

    # Secondary: volume vs liquidity anomaly
    if liquidity is not None and liquidity > 0:
        vol_liq_ratio = volume_24h / liquidity
        if vol_liq_ratio > 100:
            result["is_fake"] = True
            flags.append(
                f"Volume ({volume_24h:,.0f}) is {vol_liq_ratio:.0f}x liquidity "
                f"({liquidity:,.0f}) — physically impossible organically"
            )
            result["risk_level"] = RiskLevel.AVOID

    if result["is_fake"]:
        result["recommendation"] = (
            "Fake volume detected. Do not enter. "
            "Real traders entering this chart will cause immediate collapse."
        )

    return result


# ─── MODULE 2: HOLDER DISTRIBUTION ANALYZER ─────────────────────────────────────

def analyze_holder_distribution(
    top_holder_pct: float,
    top10_combined_pct: float,
    has_wallet_clusters: bool,
    fresh_wallet_count_in_top10: int = 0,
    wallets_funded_same_source: int = 0
) -> dict:
    """
    Analyze holder distribution for rug / dump risk.

    From guides:
      - Top holder > 3.5% → caution in active trading
      - Top holder > 5%   → be cautious
      - Top 10 combined   > 20% → risky
      - Connected clusters → farm/coordinated dump
      - Wallets funded same source → multiwallet trap
      - Fresh wallets in top holders → red flag (especially new pairs)

    Args:
        top_holder_pct:             % held by single largest wallet
        top10_combined_pct:         % held by top 10 wallets combined
        has_wallet_clusters:        True if Bubble Maps shows connected clusters
        fresh_wallet_count_in_top10: Number of "fresh wallet" (green leaf) icons in top 10
        wallets_funded_same_source:  Number of wallets in top holders funded from same source

    Returns:
        dict with risk_level, flags, is_safe, recommendation
    """
    flags = []
    green_flags = []
    risk_score = 0    # Higher = riskier

    # Top holder concentration check
    if top_holder_pct > 5.0:
        flags.append(f"Top holder owns {top_holder_pct:.1f}% — DANGER ZONE (>5%)")
        risk_score += 3
    elif top_holder_pct > 3.5:
        flags.append(f"Top holder owns {top_holder_pct:.1f}% — CAUTION (>3.5%)")
        risk_score += 2
    else:
        green_flags.append(f"Top holder {top_holder_pct:.1f}% is within safe range")

    # Top 10 combined
    if top10_combined_pct > 30:
        flags.append(f"Top 10 wallets hold {top10_combined_pct:.1f}% — extreme concentration")
        risk_score += 3
    elif top10_combined_pct > 20:
        flags.append(f"Top 10 wallets hold {top10_combined_pct:.1f}% — elevated (>20%)")
        risk_score += 2
    else:
        green_flags.append(f"Top 10 combined {top10_combined_pct:.1f}% is within safe range")

    # Cluster / bundle indicators
    if has_wallet_clusters:
        flags.append(
            "Wallet clusters detected (Bubble Maps) — "
            "farm setup or coordinated dump risk"
        )
        risk_score += 4

    if fresh_wallet_count_in_top10 >= 3:
        flags.append(
            f"{fresh_wallet_count_in_top10} fresh wallets in top 10 — "
            "likely bundler wallets"
        )
        risk_score += 3
    elif fresh_wallet_count_in_top10 >= 1:
        flags.append(
            f"{fresh_wallet_count_in_top10} fresh wallet(s) in top 10 — monitor"
        )
        risk_score += 1

    if wallets_funded_same_source >= 5:
        flags.append(
            f"{wallets_funded_same_source} top wallets funded from same source — "
            "strong multiwallet indicator"
        )
        risk_score += 4
    elif wallets_funded_same_source >= 3:
        flags.append(
            f"{wallets_funded_same_source} wallets share funding source — suspicious"
        )
        risk_score += 2

    # Determine overall risk
    if risk_score >= 7:
        risk_level = RiskLevel.AVOID
        is_safe = False
        recommendation = "Distribution is dangerous. Do not enter."
    elif risk_score >= 4:
        risk_level = RiskLevel.HIGH
        is_safe = False
        recommendation = "Distribution has significant risks. Reduce size or avoid."
    elif risk_score >= 2:
        risk_level = RiskLevel.CAUTION
        is_safe = True
        recommendation = "Distribution has caution flags. Enter small if other checks pass."
    else:
        risk_level = RiskLevel.SAFE
        is_safe = True
        recommendation = "Distribution looks healthy. Proceed to next checks."

    return {
        "risk_level":      risk_level,
        "risk_score":      risk_score,
        "is_safe":         is_safe,
        "flags":           flags,
        "green_flags":     green_flags,
        "recommendation":  recommendation
    }


# ─── MODULE 3: FULL TOKEN SAFETY SCORER ─────────────────────────────────────────

def score_token_safety(
    liquidity_usd:              float,
    liquidity_locked:           bool,
    mint_authority_disabled:    bool,
    freeze_authority_off:       bool,
    volume_24h:                 float,
    fees_24h:                   float,
    top_holder_pct:             float,
    top10_combined_pct:         float,
    has_wallet_clusters:        bool,
    deployer_has_rug_history:   bool,
    deployer_sniped_own_token:  bool,
    early_buys_organic:         bool,     # True = looks organic
    volume_vs_mc_ratio:         Optional[float] = None,  # volume / MC
    fresh_wallets_in_top10:     int = 0,
    wallets_same_funding_source: int = 0
) -> TokenSafetyReport:
    """
    Comprehensive token safety scorer combining all guide checks.
    
    Score:  85–100 = SAFE
            65–84  = CAUTION
            40–64  = HIGH RISK
            0–39   = AVOID
    """
    flags = []
    green_flags = []
    score = 100    # Start at 100, deduct for each failure

    # --- Liquidity ---
    liquidity_ok = True
    if not liquidity_locked:
        flags.append("CRITICAL: Liquidity NOT locked — rug risk")
        score -= 35
        liquidity_ok = False
    if liquidity_usd < 1000:
        flags.append(f"Liquidity critically low: ${liquidity_usd:,.0f}")
        score -= 20
        liquidity_ok = False
    elif liquidity_usd < 5000:
        flags.append(f"Liquidity below safe threshold: ${liquidity_usd:,.0f} (need >$5k)")
        score -= 10
        liquidity_ok = False
    else:
        green_flags.append(f"Liquidity ${liquidity_usd:,.0f} is above $5k threshold")

    # --- Contract params ---
    contract_ok = True
    if not mint_authority_disabled:
        flags.append("CRITICAL: Mint authority is ENABLED — supply inflation risk")
        score -= 30
        contract_ok = False
    else:
        green_flags.append("Mint authority disabled ✓")

    if not freeze_authority_off:
        flags.append("CRITICAL: Freeze authority is ON — potential honeypot")
        score -= 30
        contract_ok = False
    else:
        green_flags.append("Freeze authority off ✓")

    # --- Deployer ---
    deployer_ok = True
    if deployer_has_rug_history:
        flags.append("CRITICAL: Deployer has rug history — walk away")
        score -= 30
        deployer_ok = False
    if deployer_sniped_own_token:
        flags.append("WARNING: Deployer sniped their own token at launch")
        score -= 15
        deployer_ok = False
    if deployer_ok:
        green_flags.append("Deployer history appears clean")

    # --- Fake volume ---
    volume_check = detect_fake_volume(volume_24h, fees_24h, liquidity_usd)
    if volume_check["is_fake"]:
        flags.append(f"Fake volume detected (fee ratio: {volume_check['fee_ratio']:.4f})")
        score -= 25

    if volume_vs_mc_ratio is not None:
        if volume_vs_mc_ratio < 0.5:
            flags.append(
                f"Volume/MC ratio {volume_vs_mc_ratio:.2f} — "
                "< 50% suggests supply control/bundle"
            )
            score -= 15
        elif volume_vs_mc_ratio < 0.8:
            flags.append(f"Volume/MC ratio {volume_vs_mc_ratio:.2f} — below ideal 80%")
            score -= 8

    # --- Distribution ---
    dist_check = analyze_holder_distribution(
        top_holder_pct, top10_combined_pct, has_wallet_clusters,
        fresh_wallets_in_top10, wallets_same_funding_source
    )
    distribution_ok = dist_check["is_safe"]
    flags.extend(dist_check["flags"])
    green_flags.extend(dist_check["green_flags"])
    score -= dist_check["risk_score"] * 4    # scale to score impact

    # --- Early transactions ---
    if not early_buys_organic:
        flags.append(
            "Early transactions look botted/inorganic "
            "(identical amounts, perfect timing)"
        )
        score -= 15
    else:
        green_flags.append("Early transactions appear organic")

    # Clamp score
    score = max(0, min(100, score))

    # Determine overall risk
    if score >= 85:
        overall_risk = RiskLevel.SAFE
        recommendation = (
            "Token passes safety checks. Proceed with normal position sizing. "
            "Continue to narrative and timing analysis."
        )
    elif score >= 65:
        overall_risk = RiskLevel.CAUTION
        recommendation = (
            "Moderate concerns. Enter small if narrative and timing are strong. "
            f"Review flags: {len(flags)} issue(s) found."
        )
    elif score >= 40:
        overall_risk = RiskLevel.HIGH
        recommendation = (
            "Multiple red flags. Consider avoiding unless you have high conviction "
            "and understand the specific risks. Size very small."
        )
    else:
        overall_risk = RiskLevel.AVOID
        recommendation = (
            "Token fails critical safety checks. Do not enter. "
            f"{len(flags)} red flag(s) found."
        )

    return TokenSafetyReport(
        overall_risk=overall_risk,
        fake_volume=volume_check["is_fake"],
        liquidity_ok=liquidity_ok,
        deployer_ok=deployer_ok,
        distribution_ok=distribution_ok,
        contract_ok=contract_ok,
        flags=flags,
        green_flags=green_flags,
        score=score,
        recommendation=recommendation
    )


# ─── MODULE 4: NARRATIVE STAGE DETECTOR ─────────────────────────────────────────

def detect_narrative_stage(
    holder_count_trend:        str,     # "rising" / "stable" / "falling"
    social_mentions_trend:     str,     # "rising" / "stable" / "falling"
    smart_money_entering:      bool,
    smart_money_exiting:       bool,
    volume_trend:              str,     # "rising" / "stable" / "falling"
    new_wallets_joining:       bool,
    dev_activity:              str,     # "active" / "quiet" / "silent"
    influencers_loud:          bool,
) -> NarrativeReport:
    """
    Determine current narrative stage and recommended action.
    
    From guides:
      Emerging: small signals, wallets accumulating quietly
      Peak:     everyone knows, FOMO everywhere, influencers loud
      End-Stage: holders dropping, volume drying, dev silent
    """
    flags = []
    emerging_score = 0
    peak_score = 0
    dying_score = 0

    # Emerging signals
    if smart_money_entering and not influencers_loud:
        emerging_score += 3
        flags.append("Smart money entering before public hype — emerging signal")
    if holder_count_trend == "rising" and not influencers_loud:
        emerging_score += 2
    if new_wallets_joining and social_mentions_trend == "stable":
        emerging_score += 2
    if dev_activity == "active" and social_mentions_trend in ("rising", "stable"):
        emerging_score += 1

    # Peak signals
    if influencers_loud:
        peak_score += 3
        flags.append("Influencers loudly promoting — peak narrative signal")
    if volume_trend == "rising" and social_mentions_trend == "rising":
        peak_score += 2
    if smart_money_entering and influencers_loud:
        peak_score += 1

    # Dying signals
    if holder_count_trend == "falling":
        dying_score += 3
        flags.append("Holder count falling — narrative collapse signal")
    if dev_activity == "silent":
        dying_score += 2
        flags.append("Dev went silent — narrative dying")
    if smart_money_exiting:
        dying_score += 3
        flags.append("Smart money exiting — exit now")
    if volume_trend == "falling" and social_mentions_trend == "falling":
        dying_score += 2
    if not new_wallets_joining and holder_count_trend == "falling":
        dying_score += 2

    # Determine stage
    max_score = max(emerging_score, peak_score, dying_score)

    if dying_score == max_score and dying_score >= 3:
        stage = NarrativeStage.END_STAGE
        entry_recommended = False
        action = (
            "Narrative is dying. Exit existing positions. Do not enter. "
            "Dead narratives rarely revive without a catalyst."
        )
        confidence = "HIGH" if dying_score >= 6 else "MEDIUM"

    elif peak_score == max_score and peak_score >= 3:
        stage = NarrativeStage.PEAK
        entry_recommended = True    # With strict discipline
        action = (
            "Peak narrative — if entering, size very small, take profit early, "
            "watch smart money (not influencers), set hard exit targets. "
            "Short burst only, not a hold."
        )
        confidence = "HIGH" if peak_score >= 5 else "MEDIUM"

    elif emerging_score == max_score and emerging_score >= 3:
        stage = NarrativeStage.EMERGING
        entry_recommended = True
        action = (
            "Emerging narrative — highest profit potential. "
            "Enter small, build position as conviction grows, "
            "scale before public attention peaks."
        )
        confidence = "HIGH" if emerging_score >= 5 else "MEDIUM"

    else:
        stage = NarrativeStage.UNKNOWN
        entry_recommended = False
        action = "Narrative stage unclear. Observe and gather more data before entry."
        confidence = "LOW"

    return NarrativeReport(
        stage=stage,
        confidence=confidence,
        entry_recommended=entry_recommended,
        flags=flags,
        action=action
    )


# ─── MODULE 5: MARTINGALE ELIGIBILITY CHECKER ───────────────────────────────────

def check_martingale_eligibility(
    liquidity_usd:       float,
    volume_24h:          float,
    fees_24h:            float,
    holder_count_rising: bool,
    whales_exiting:      bool,
    dev_active:          bool,
    volume_trend:        str,    # "rising" / "stable" / "falling"
    distribution_clean:  bool,
) -> MartingaleReport:
    """
    Check if a token qualifies for the Controlled Jeeting (martingale) strategy.

    From guides:
      Hard requirements:
        - Liquidity > $10,000
        - Volume > $100,000 / 24h
        - Real distribution (no clusters)
        - Natural volatility with predictable bounces
        - Mindshare/narrative active
      
      NEVER use on: low liquidity, fake volume, dying tokens,
                    tokens with whale exit, concentrating distribution
      
      HARD RULE: Never double more than 3 times.
    """
    flags = []
    eligible = True
    reasons_fail = []

    # Hard requirements
    if liquidity_usd < 10_000:
        eligible = False
        reasons_fail.append(
            f"Liquidity ${liquidity_usd:,.0f} < $10,000 minimum "
            "(price moves too sharply for martingale)"
        )

    if volume_24h < 100_000:
        eligible = False
        reasons_fail.append(
            f"Volume ${volume_24h:,.0f} < $100,000 minimum "
            "(need consistent buyers to support bounce cycles)"
        )

    # Fake volume check
    vol_check = detect_fake_volume(volume_24h, fees_24h)
    if vol_check["is_fake"]:
        eligible = False
        reasons_fail.append(
            "Volume is fake — martingale requires real buyer-driven bounces"
        )

    if not distribution_clean:
        eligible = False
        reasons_fail.append(
            "Distribution not clean — cluster traps will destroy martingale timing"
        )

    # Exit conditions (stop immediately if any of these)
    if whales_exiting:
        eligible = False
        reasons_fail.append(
            "Whales are exiting — stop martingale immediately, "
            "this is not a bounce, this is a dump"
        )
        flags.append("STOP: Whales exiting detected")

    if volume_trend == "falling":
        eligible = False
        reasons_fail.append(
            "Volume is falling — martingale needs consistent buying pressure"
        )

    if not holder_count_rising:
        flags.append(
            "Holder count not rising — martingale has lower reliability without growing mindshare"
        )

    if not dev_active:
        flags.append("Dev is quiet — reduces confidence in bounce sustainability")

    # Compile reason
    if eligible:
        reason = (
            "Token meets martingale conditions. "
            "Enter small on red candle, sell at 2x or clear resistance. "
            f"HARD LIMIT: Maximum 3 doubles. Reset to base after each win."
        )
    else:
        reason = "Token does NOT qualify for martingale. Reasons: " + "; ".join(reasons_fail)

    return MartingaleReport(
        eligible=eligible,
        reason=reason,
        max_doubles=3,
        flags=flags
    )


# ─── MODULE 6: POSITION SIZE CALCULATOR ─────────────────────────────────────────

def calculate_position_size(
    portfolio_size_usd: float,
    conviction_level:   str,     # "HIGH" / "MEDIUM" / "LOW"
    mc_at_entry:        float,   # Market cap at entry in USD
    is_new_pair:        bool = False
) -> PositionSizeReport:
    """
    Calculate recommended position size.

    From guides:
      - Risk 3–10% per trade
      - High conviction + few people know → larger size
      - Public info + timing edge → smaller size
      - Portfolio buckets: 30% HC / 40% Active / 30% Reserves
      - Sub-$500k MC new pairs: cap even lower (high risk category)
      - RULE: "If it goes to zero, can I still trade normally tomorrow?"
    """
    # Base allocation by conviction
    conviction_map = {
        "HIGH":   0.08,    # 8% of portfolio
        "MEDIUM": 0.05,    # 5% of portfolio
        "LOW":    0.03,    # 3% of portfolio
    }
    base_pct = conviction_map.get(conviction_level.upper(), 0.03)

    # Adjust for MC tier (lower MC = higher risk = smaller size)
    if mc_at_entry < 50_000:
        mc_multiplier = 0.5       # Very low cap, very high risk
        bucket = "SPECULATIVE"
    elif mc_at_entry < 500_000:
        mc_multiplier = 0.75      # Low cap
        bucket = "ACTIVE"
    elif mc_at_entry < 5_000_000:
        mc_multiplier = 1.0       # Mid cap
        bucket = "ACTIVE"
    else:
        mc_multiplier = 1.25      # Higher cap = more liquidity = less slippage risk
        bucket = "HIGH_CONVICTION"

    # New pair penalty
    if is_new_pair:
        mc_multiplier *= 0.8
        bucket = "SPECULATIVE"

    final_pct = base_pct * mc_multiplier
    final_pct = min(0.10, max(0.01, final_pct))    # Clamp to 1–10%
    suggested_usd = portfolio_size_usd * final_pct

    notes_parts = [
        f"Based on {conviction_level} conviction + ${mc_at_entry:,.0f} MC entry.",
        f"Represents {final_pct*100:.1f}% of ${portfolio_size_usd:,.0f} portfolio.",
        "Scale in: first entry at 50%, second at 30% on confirmation, third 20% on pattern.",
        "If this goes to zero, you should still be able to trade normally tomorrow.",
    ]
    if is_new_pair:
        notes_parts.append(
            "New pair penalty applied. These are the highest-risk entries."
        )

    return PositionSizeReport(
        suggested_pct=round(final_pct * 100, 2),
        suggested_usd=round(suggested_usd, 2),
        bucket=bucket,
        notes=" | ".join(notes_parts)
    )


# ─── MODULE 7: TRADING WINDOW EVALUATOR ─────────────────────────────────────────

def evaluate_trading_window(hour_WAT: int) -> dict:
    """
    Evaluate current time window for trading quality.

    From guides:
      Prime Window 1: 18:00–22:00 WAT (6PM–10PM)
        High volume, narrative rotation, smart money active, clean breakouts
      Prime Window 2: 03:00–07:00 WAT (3AM–7AM)
        Asia wake-up, quieter but strong moves, whales accumulate
      Pre-pump window: ~02:00 WAT
        Early accumulation, first volume sparks
      Danger Window 1: 11:00–14:00 WAT
        Slow, fake pumps, manipulation
      Danger Window 2: Late night with no broader narrative
        High rug probability, high slippage

    Args:
        hour_WAT: Current hour in West Africa Time (0–23)

    Returns:
        dict with window_type, quality, recommended_actions
    """
    h = hour_WAT % 24

    if 18 <= h <= 22:
        return {
            "window_type":   "PRIME_EVENING",
            "quality":       "HIGH",
            "recommended":   [
                "Trade new pairs",
                "Chase narrative breakouts",
                "Monitor trending tokens on GMGN",
                "Follow smart money signals in real time"
            ],
            "avoid": []
        }

    elif 3 <= h <= 7:
        return {
            "window_type":   "PRIME_ASIA",
            "quality":       "HIGH",
            "recommended":   [
                "Pre-migration setups",
                "Watch for early accumulation patterns",
                "Trade OG revival candidates",
                "Asia-driven narrative plays"
            ],
            "avoid": []
        }

    elif h == 2:
        return {
            "window_type":   "PRE_PUMP_WINDOW",
            "quality":       "MEDIUM_HIGH",
            "recommended":   [
                "Watch for first volume sparks",
                "Track smart money wallet movement on Axiom",
                "Position in pre-migration candidates"
            ],
            "avoid": ["Chasing already-running charts"]
        }

    elif 11 <= h <= 14:
        return {
            "window_type":   "DANGER_MIDDAY",
            "quality":       "LOW",
            "recommended":   [
                "Research and watchlist building (Axiom deep dives)",
                "Study holder behavior on existing positions",
                "Update deployer tracking"
            ],
            "avoid": [
                "Entering new pairs",
                "Acting on FOMO",
                "Chasing volume spikes — likely manufactured here"
            ]
        }

    elif 8 <= h <= 10:
        return {
            "window_type":   "MORNING_SLOW",
            "quality":       "MEDIUM",
            "recommended":   [
                "Research old/revival tokens",
                "Analyze token distributions on Bubble Maps",
                "Check dev activity on Axiom",
                "Update watchlists"
            ],
            "avoid": ["New pair trading — low volume makes rugs more likely"]
        }

    else:    # Late night / off-hours
        return {
            "window_type":   "LOW_VOLUME_OFFHOURS",
            "quality":       "LOW",
            "recommended":   [
                "Rest and recover",
                "Background research only",
                "Review trade journal"
            ],
            "avoid": [
                "Trading new pairs",
                "Emotional or revenge trades",
                "Acting on any calls during this window"
            ]
        }


# ─── MODULE 8: REVIVAL CANDIDATE SCORER ─────────────────────────────────────────

def score_revival_candidate(
    days_since_last_pump:    int,
    volume_rising:           bool,
    new_wallets_entering:    bool,
    holder_count_rising:     bool,
    dev_active:              bool,
    liquidity_locked:        bool,
    has_rug_history:         bool,
    narrative_fit:           bool,    # Does it connect to current market meta?
    has_wallet_clusters:     bool,
    volume_24h:              float,
    fees_24h:                float,
) -> dict:
    """
    Score a token as a dead-play revival candidate.

    From guides:
      Revival pattern: long flat → small volume increases → few new buyers →
                        holder count rises → early green candles → narrative returns →
                        social interest → smart money → violent breakout
      
      Enter at signal steps 2–4 (before crowd arrives at step 7–8).
      OG tokens safer: existing community, historical mindshare, often burnt liquidity.
    """
    flags = []
    score = 0
    disqualified = False
    disqualify_reasons = []

    # Hard disqualifiers
    if has_rug_history:
        disqualified = True
        disqualify_reasons.append("Token has rug history — not a safe revival candidate")

    if not liquidity_locked:
        disqualified = True
        disqualify_reasons.append("Liquidity not locked — still rug risk")

    if has_wallet_clusters:
        disqualified = True
        disqualify_reasons.append(
            "Wallet clusters still present — farm/insider control, not organic revival"
        )

    if disqualified:
        return {
            "revival_score":  0,
            "viable":         False,
            "flags":          disqualify_reasons,
            "recommendation": "Disqualified as revival candidate: " + "; ".join(disqualify_reasons)
        }

    # Fake volume check
    vol_check = detect_fake_volume(volume_24h, fees_24h)
    if vol_check["is_fake"]:
        flags.append("Revival volume looks fake — not organic reawakening")
        score -= 20
    else:
        score += 10
        flags.append("Volume appears organic ✓")

    # Revival signals
    if days_since_last_pump >= 30:
        score += 15
        flags.append(f"Token has been dormant {days_since_last_pump} days — OG play potential")
    elif days_since_last_pump >= 7:
        score += 8

    if volume_rising:
        score += 15
        flags.append("Volume rising from silence — revival signal step 2")

    if new_wallets_entering:
        score += 20
        flags.append("New wallets entering — revival signal step 3")

    if holder_count_rising:
        score += 20
        flags.append("Holder count rising — revival signal step 4 (strongest signal)")

    if dev_active:
        score += 10
        flags.append("Dev activity detected — revival signal")

    if narrative_fit:
        score += 15
        flags.append("Token fits current market meta — narrative catalyst present")

    # Normalize to 0–100
    score = max(0, min(100, score))

    if score >= 70:
        recommendation = (
            "Strong revival candidate. "
            "You are likely at signal steps 2–4, ahead of the crowd. "
            "Enter small with defined exit. Monitor Axiom for smart money confirmation."
        )
        viable = True
    elif score >= 40:
        recommendation = (
            "Moderate revival signals. Observe for 1–2 more sessions. "
            "Enter if holder count continues rising and narrative strengthens."
        )
        viable = True
    else:
        recommendation = (
            "Weak revival signals. Not enough evidence for entry. "
            "Add to watchlist and reassess."
        )
        viable = False

    return {
        "revival_score":  score,
        "viable":         viable,
        "flags":          flags,
        "recommendation": recommendation
    }


# ─── MODULE 9: FULL DECISION PIPELINE ───────────────────────────────────────────

def run_full_analysis(
    # Token basics
    token_name:                  str,
    liquidity_usd:               float,
    liquidity_locked:            bool,
    mint_authority_disabled:     bool,
    freeze_authority_off:        bool,
    volume_24h:                  float,
    fees_24h:                    float,
    # Holder data
    top_holder_pct:              float,
    top10_combined_pct:          float,
    has_wallet_clusters:         bool,
    deployer_has_rug_history:    bool,
    early_buys_organic:          bool,
    # Narrative
    holder_count_trend:          str,
    social_mentions_trend:       str,
    smart_money_entering:        bool,
    smart_money_exiting:         bool,
    volume_trend:                str,
    new_wallets_joining:         bool,
    dev_activity:                str,
    influencers_loud:            bool,
    # Portfolio
    portfolio_size_usd:          float,
    conviction_level:            str,
    current_hour_WAT:            int,
    mc_at_entry:                 float,
    # Optional extras
    volume_vs_mc_ratio:          Optional[float] = None,
    is_new_pair:                 bool = False,
    deployer_sniped_own_token:   bool = False,
    fresh_wallets_in_top10:      int  = 0,
    wallets_same_funding_source: int  = 0,
) -> dict:
    """
    Run the complete 5-stage decision pipeline on a token.
    
    Pipeline:
      Stage 1: Token Safety Score
      Stage 2: Narrative Stage Detection
      Stage 3: Trading Window Quality
      Stage 4: Position Size Calculation
      Stage 5: Final Recommendation
    
    Returns a full analysis report dict.
    """
    print(f"\n{'═'*65}")
    print(f"  FULL ANALYSIS: {token_name.upper()}")
    print(f"{'═'*65}")

    # Stage 1: Safety
    safety = score_token_safety(
        liquidity_usd=liquidity_usd,
        liquidity_locked=liquidity_locked,
        mint_authority_disabled=mint_authority_disabled,
        freeze_authority_off=freeze_authority_off,
        volume_24h=volume_24h,
        fees_24h=fees_24h,
        top_holder_pct=top_holder_pct,
        top10_combined_pct=top10_combined_pct,
        has_wallet_clusters=has_wallet_clusters,
        deployer_has_rug_history=deployer_has_rug_history,
        deployer_sniped_own_token=deployer_sniped_own_token,
        early_buys_organic=early_buys_organic,
        volume_vs_mc_ratio=volume_vs_mc_ratio,
        fresh_wallets_in_top10=fresh_wallets_in_top10,
        wallets_same_funding_source=wallets_same_funding_source
    )

    # Stage 2: Narrative
    narrative = detect_narrative_stage(
        holder_count_trend=holder_count_trend,
        social_mentions_trend=social_mentions_trend,
        smart_money_entering=smart_money_entering,
        smart_money_exiting=smart_money_exiting,
        volume_trend=volume_trend,
        new_wallets_joining=new_wallets_joining,
        dev_activity=dev_activity,
        influencers_loud=influencers_loud
    )

    # Stage 3: Timing
    window = evaluate_trading_window(current_hour_WAT)

    # Stage 4: Position size (only if we would actually enter)
    position = calculate_position_size(
        portfolio_size_usd=portfolio_size_usd,
        conviction_level=conviction_level,
        mc_at_entry=mc_at_entry,
        is_new_pair=is_new_pair
    )

    # Stage 5: Final decision
    will_enter = (
        safety.score >= 65
        and safety.overall_risk != RiskLevel.AVOID
        and narrative.entry_recommended
        and narrative.stage != NarrativeStage.END_STAGE
        and window["quality"] in ("HIGH", "MEDIUM_HIGH")
        and not smart_money_exiting
    )

    if safety.overall_risk == RiskLevel.AVOID or deployer_has_rug_history:
        final_decision = "DO NOT ENTER — Critical safety failures"
        final_rationale = "Token fails critical checks. No position size is appropriate."
    elif not narrative.entry_recommended:
        final_decision = "DO NOT ENTER — Narrative unfavorable"
        final_rationale = narrative.action
    elif window["quality"] == "LOW":
        final_decision = "WAIT — Poor trading window"
        final_rationale = (
            f"Token looks [{safety.overall_risk.value}] but current window "
            f"({window['window_type']}) is not suitable. "
            f"Revisit at 18:00 WAT or 03:00 WAT."
        )
    elif will_enter:
        final_decision = f"ENTER — {position.suggested_pct}% of portfolio (${position.suggested_usd:,.2f})"
        final_rationale = (
            f"Safety score {safety.score}/100. "
            f"Narrative: {narrative.stage.value} ({narrative.confidence} confidence). "
            f"Window: {window['window_type']}. {position.notes}"
        )
    else:
        final_decision = "MONITOR — Conditions partially met"
        final_rationale = (
            f"Safety: {safety.score}/100 ({safety.overall_risk.value}). "
            f"Narrative: {narrative.stage.value}. "
            "Wait for all conditions to align before entering."
        )

    report = {
        "token":            token_name,
        "safety":           safety,
        "narrative":        narrative,
        "window":           window,
        "position":         position,
        "will_enter":       will_enter,
        "final_decision":   final_decision,
        "final_rationale":  final_rationale
    }

    # Pretty print summary
    print(f"\n  SAFETY SCORE:    {safety.score}/100  [{safety.overall_risk.value}]")
    print(f"  NARRATIVE STAGE: {narrative.stage.value}  ({narrative.confidence} confidence)")
    print(f"  WINDOW QUALITY:  {window['quality']}  ({window['window_type']})")
    print(f"\n  ► DECISION: {final_decision}")
    print(f"\n  RATIONALE: {final_rationale}")

    if safety.flags:
        print(f"\n  RED FLAGS ({len(safety.flags)}):")
        for f in safety.flags[:5]:    # Show top 5
            print(f"    ✗ {f}")

    if safety.green_flags:
        print(f"\n  GREEN FLAGS ({len(safety.green_flags)}):")
        for f in safety.green_flags[:3]:
            print(f"    ✓ {f}")

    print(f"\n{'─'*65}\n")
    return report


"""
════════════════════════════════════════════════════════════════════════════════════
PART 3 — INTEGRATION LAYER
════════════════════════════════════════════════════════════════════════════════════

HOW THE REFERENCE GUIDE AND CODE MODULE WORK TOGETHER:

  STEP 1 — DATA GATHERING (use reference guide Section 1–3):
    Collect inputs from GMGN, Axiom, Bubble Maps, Solscan, Dexscreener.
    The reference guide tells you WHAT to check and WHERE.

  STEP 2 — AUTOMATED ANALYSIS (use Python functions):
    Pass collected data into the functions. The code implements the exact
    thresholds and decision logic from the guides.

  STEP 3 — CROSS-REFERENCE OUTPUT (use reference guide Section 4–10):
    The code output tells you whether to consider entry. The reference guide
    adds the qualitative layers (narrative stage, timing, KOL assessment)
    that require human judgment.

  STEP 4 — POSITION + TIMING (calculator + window evaluator):
    calculate_position_size() + evaluate_trading_window()
    These give you the "how much" and "when" answers.

WORKFLOW EXAMPLES:
  Scenario A — New pair just launched:
    run_full_analysis() with is_new_pair=True
    Threshold is intentionally tighter. Small size, exit plan required.

  Scenario B — Checking for fake volume only:
    detect_fake_volume(volume_24h=500_000, fees_24h=2_000)
    Quick standalone check before deeper analysis.

  Scenario C — Evaluating OG revival:
    score_revival_candidate() — tells you whether you're at signals 2–4
    If viable → run_full_analysis() for full decision

  Scenario D — Martingale timing:
    check_martingale_eligibility() — gates whether strategy applies at all
    If eligible → enter jeeting cycle per the Controlled Jeeting Sequence
    Always reset after a win; never double more than 3x.

TOOL MAPPING (what to check where):
  GMGN    → volume, fees, lock status, holder count, early transactions
  Axiom   → deployer history, top holders, clusters, smart money, alerts
  Solscan → raw contract data, mint/freeze authority, early tx detail
  BubbleMaps → wallet cluster visualization (has_wallet_clusters param)
  Dexscreener → chart patterns, MC vs volume ratio, price action

REFERENCE GUIDE SECTIONS BY USE CASE:
  "Is this token safe?"              → Section 1 + score_token_safety()
  "Is this volume real?"             → Section 2 + detect_fake_volume()
  "Should I enter the bonding curve?" → Section 3 (qualitative — no code needed)
  "What narrative stage is this?"    → Section 4 + detect_narrative_stage()
  "Who are the real traders here?"   → Section 5 (wallet tracking guide)
  "Is this a revival opportunity?"   → Section 6 + score_revival_candidate()
  "How much should I risk?"          → Section 7 + calculate_position_size()
  "Should I trade now?"              → Section 8 + evaluate_trading_window()
  "Can I use martingale here?"       → Section 9 + check_martingale_eligibility()
  "Should I trust this KOL?"        → Section 10 (qualitative — no code needed)
  "Am I making a common mistake?"    → Section 11 (pre-trade checklist)
"""


# ════════════════════════════════════════════════════════════════════════════════
# INTEGRATION EXAMPLES — run this file directly to see live demonstrations
# ════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":

    print("\n" + "╔" + "═"*63 + "╗")
    print("║    MEMECOIN PROFITABILITY ARCHITECT — DEMO RUNS             ║")
    print("╚" + "═"*63 + "╝")

    # ── EXAMPLE 1: Clean emerging token ─────────────────────────────────────
    print("\n[EXAMPLE 1] Clean emerging token at pre-bond stage")
    run_full_analysis(
        token_name                 = "EXAMPLECOIN",
        liquidity_usd              = 18_000,
        liquidity_locked           = True,
        mint_authority_disabled    = True,
        freeze_authority_off       = True,
        volume_24h                 = 340_000,
        fees_24h                   = 17_000,      # 5% → clean
        top_holder_pct             = 2.1,
        top10_combined_pct         = 14.5,
        has_wallet_clusters        = False,
        deployer_has_rug_history   = False,
        early_buys_organic         = True,
        holder_count_trend         = "rising",
        social_mentions_trend      = "rising",
        smart_money_entering       = True,
        smart_money_exiting        = False,
        volume_trend               = "rising",
        new_wallets_joining        = True,
        dev_activity               = "active",
        influencers_loud           = False,        # Not peak yet — emerging
        portfolio_size_usd         = 5_000,
        conviction_level           = "MEDIUM",
        current_hour_WAT           = 20,           # Prime window
        mc_at_entry                = 85_000,
        volume_vs_mc_ratio         = 4.0,
        is_new_pair                = False,
    )

    # ── EXAMPLE 2: Suspicious bundle-heavy new pair ──────────────────────────
    print("\n[EXAMPLE 2] Suspicious new pair with bundle indicators")
    run_full_analysis(
        token_name                   = "SCAMCOIN",
        liquidity_usd                = 3_200,
        liquidity_locked             = True,
        mint_authority_disabled      = True,
        freeze_authority_off         = False,     # Honeypot flag
        volume_24h                   = 900_000,
        fees_24h                     = 8_000,     # ~0.9% — fake volume
        top_holder_pct               = 8.7,
        top10_combined_pct           = 41.0,
        has_wallet_clusters          = True,
        deployer_has_rug_history     = False,
        early_buys_organic           = False,
        holder_count_trend           = "rising",
        social_mentions_trend        = "rising",
        smart_money_entering         = False,
        smart_money_exiting          = False,
        volume_trend                 = "rising",
        new_wallets_joining          = True,
        dev_activity                 = "active",
        influencers_loud             = True,
        portfolio_size_usd           = 5_000,
        conviction_level             = "LOW",
        current_hour_WAT             = 19,
        mc_at_entry                  = 200_000,
        volume_vs_mc_ratio           = 4.5,
        is_new_pair                  = True,
        fresh_wallets_in_top10       = 6,
        wallets_same_funding_source  = 7,
    )

    # ── EXAMPLE 3: Standalone fake volume check ──────────────────────────────
    print("\n[EXAMPLE 3] Quick fake volume check")
    result = detect_fake_volume(
        volume_24h=1_200_000,
        fees_24h=12_000,       # 1% → below 3.3% threshold
        liquidity=8_000
    )
    print(f"  Fee ratio: {result['fee_ratio']:.4f}")
    print(f"  Fake: {result['is_fake']}")
    print(f"  Risk: {result['risk_level'].value}")
    print(f"  Note: {result['recommendation']}")

    # ── EXAMPLE 4: Revival candidate check ──────────────────────────────────
    print("\n[EXAMPLE 4] OG token revival assessment")
    revival = score_revival_candidate(
        days_since_last_pump = 45,
        volume_rising        = True,
        new_wallets_entering = True,
        holder_count_rising  = True,
        dev_active           = False,
        liquidity_locked     = True,
        has_rug_history      = False,
        narrative_fit        = True,
        has_wallet_clusters  = False,
        volume_24h           = 85_000,
        fees_24h             = 5_100,   # 6% → clean
    )
    print(f"  Revival score: {revival['revival_score']}/100")
    print(f"  Viable:        {revival['viable']}")
    print(f"  Signals:       {', '.join(revival['flags'][:3])}")
    print(f"  Action:        {revival['recommendation']}")

    # ── EXAMPLE 5: Martingale check ──────────────────────────────────────────
    print("\n[EXAMPLE 5] Martingale eligibility check")
    mart = check_martingale_eligibility(
        liquidity_usd        = 45_000,
        volume_24h           = 380_000,
        fees_24h             = 19_000,    # ~5% → clean
        holder_count_rising  = True,
        whales_exiting       = False,
        dev_active           = True,
        volume_trend         = "stable",
        distribution_clean   = True,
    )
    print(f"  Eligible:   {mart.eligible}")
    print(f"  Max doubles: {mart.max_doubles}")
    print(f"  Verdict:    {mart.reason}")

    print("\n" + "═"*65)
    print("  All examples complete. Module ready for production use.")
    print("═"*65 + "\n")
