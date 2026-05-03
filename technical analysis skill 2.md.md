---
name: technical-analysis-trade-setup
description: "Applies a complete rules-based technical analysis framework to evaluate trade opportunities across any market (forex, crypto, stocks). Give Claude a chart screenshot or describe market conditions and receive: trend classification, key S/R levels, indicator readings, candlestick/chart/breakout pattern identification, ATR-based stop and target calculations, and a scored trade setup summary. Trigger with: 'analyse this chart', 'is this a good trade setup', 'find entry patterns', 'check this double bottom', 'calculate my stops', 'what pattern is this', 'score my trade setup'."
---

# Technical Analysis Trade Setup Evaluator

Claude analyses chart screenshots or verbal descriptions using a complete rules-based TA framework covering trend, structure, indicators, candlestick patterns, chart patterns, and breakout patterns — then scores the setup and outputs a specific trade plan with ATR-based stops and targets.

**Metadata:**
- Source: "The Only Technical Analysis Video You Will Ever Need — Full Course Beginner To Advanced" by EAP Training — https://youtu.be/eynxyoKgpng
- Generated: May 2026
- Target environment: Claude.ai web/app chat
- Estimated time: 3–8 minutes per setup (5 execute steps, 1 hand-off, 1 decision)
- Tool dependencies: None required. Chart image upload strongly recommended for best results.

---

## Before Starting

Claude needs one of the following:

**Option A — Chart screenshot (preferred):**
Upload an image of the chart. Ideally it shows: visible candles, the 20/50/200 MA lines, ATR indicator value, and any drawn S/R levels.

**Option B — Verbal description:**
State: asset name, timeframe, trend direction you see, current ATR value, where price is relative to any key levels, and any patterns you notice.

If neither is provided, ask:
"To analyse this setup I need either a chart screenshot or a description of: asset, timeframe, trend direction, ATR value, and where price is now relative to key S/R levels."

---

## Step 1 — Classify Trend [EXECUTE]

Claude analyses the chart using these objective rules:

**Uptrend:** Price is making higher highs AND higher lows. Remains valid until price breaks AND closes below the lowest low of the most recent pullback.

**Downtrend:** Price is making lower lows AND lower highs. Remains valid until price breaks AND closes above the highest high of the most recent pullback.

**Consolidation:** Neither condition is clearly met. No trend-based setups apply — skip to Step 5 to check for reversal patterns only.

**20 MA volatility filter:**
- Price consistently above the 20 MA → highly volatile uptrend (flag patterns valid, breakout setups preferred)
- Price consistently below the 20 MA → highly volatile downtrend (same)
- Price chopping around the 20 MA → trend is weak; reduce confidence on all setups

**Higher timeframe alignment check:**
If the user provides only one timeframe, Claude asks: "What is the trend on the next higher timeframe? (e.g. if you're trading the 1H, what does the Daily look like?) Higher timeframe alignment adds significant accuracy."

Claude states: "**Trend:** [UPTREND / DOWNTREND / CONSOLIDATION]. **20 MA filter:** [ABOVE / BELOW / MIXED]. **Higher TF alignment:** [BULLISH / BEARISH / UNKNOWN — please confirm]."

---

## Step 2 — Identify Key S/R Levels and Area of Value [EXECUTE]

Claude scans the chart for:

- **Previous swing highs that price has broken** → now act as support in an uptrend (break-and-retest zones)
- **Previous swing lows that price has broken** → now act as resistance in a downtrend
- **20, 50, and 200 MA** as dynamic S/R areas (the more respected, the stronger the level)
- **Levels touched multiple times** → more touches = stronger level

Claude identifies and labels:
- The **current area of value** — where to watch for entry: the broken S/R level price is pulling back to
- The **stop zone** — just beyond the area of value (direction depends on trade)
- The **target zone** — next significant S/R level in the direction of the trend

Claude notes any major S/R level that sits between the area of value and the target (a potential obstacle that could cut the trade short).

---

## Step 3 — Read ATR and Calculate Stop/Target Distances [EXECUTE]

If the ATR value is not visible in the screenshot, Claude asks: "What is the ATR value shown on your chart right now?"

**Stop loss calculation (1× ATR rule):**
1. Find the nearest swing low (for a long) or swing high (for a short) to the intended entry
2. Measure the distance from entry to that swing point in pips/points
3. Add 1× ATR to that distance — this is the minimum stop
4. Example: swing low is 30 pips from entry, ATR = 67 → stop = 30 + 67 = **97 pips below entry**

This ensures the stop accounts for normal market volatility and avoids being wicked out by noise.

**Target calculation — Claude presents both methods:**

- **Method A (structure-based):** Target = next major S/R level. Claude calculates the reward:risk. Minimum: 1:1. Ideal: 2:1 or better. If the next S/R level gives less than 1:1, state "poor reward:risk — consider waiting for a deeper pullback or skip this setup."

- **Method B (ATR multiple):** Target = stop distance × 2 from entry (gives 2:1 R:R automatically). Example: 97-pip stop → target 194 pips from entry.

**Break-even rule:** When price reaches the first major S/R level or banks 1× ATR in profit, move stop to entry (break-even). This protects capital on trades that retrace.

---

## Step 4 — Identify Entry Pattern [EXECUTE]

Claude scans for one of three valid candlestick entry patterns at the area of value. These are only valid when they form at or very near the area of value identified in Step 2 — not in the middle of open space.

**38.2% Candle (strongest signal — most specific):**
- *Bullish:* Candle has a long lower wick and the body closes in the upper portion of the candle's range. Objective rule: draw a Fibonacci retracement from the candle's low to its high — the **entire body** must be above the 38.2% level.
- *Bearish:* Long upper wick. Draw Fib from candle's high to its low — the **entire body** must be below the 38.2% level.

**Engulfing Candle:**
- *Bullish:* A green candle whose body is **larger than the previous red candle's body**, with a color change from red to green.
- *Bearish:* A red candle whose body is larger than the previous green candle's body, with a color change from green to red.
- Note: body size comparison only — wicks do not count.

**Close Above / Close Below Candle:**
- *Bullish (Close Above):* Candle closes above the **high** of the previous candle.
- *Bearish (Close Below):* Candle closes below the **low** of the previous candle.

Claude states: "**Entry pattern:** [PATTERN NAME or NONE]. **Direction:** [BULLISH / BEARISH]. **Valid:** [YES / NO / WAIT — reason]."

If no pattern has formed yet: "The area of value is set up — wait for one of the three entry patterns to print before entering. Do not enter on anticipation alone."

---

## Step 5 — Scan for Chart and Breakout Patterns [EXECUTE]

Claude checks whether any larger patterns (10–100 candles) are present. These work best when aligned with the higher timeframe trend from Step 1.

**Double Bottom (bullish — reversal or continuation):**
- Two lows at roughly the same price level
- A neckline = the pullback high between the two lows
- Validation: price breaks AND closes above the neckline
- Termination zone rule: draw a box from the lowest body of bottom 1 to the lowest wick. Bottom 2 must touch this zone but NOT close below it. If it closes below, the pattern is invalidated.
- Entry method: wait for neckline break → pullback to neckline → bullish entry pattern from Step 4

**Double Top (bearish — reversal or continuation):**
- Two highs at roughly the same price level
- Neckline = the pullback low between the two tops
- Validation: price breaks AND closes below the neckline
- Termination zone: box from highest body of top 1 to highest wick. Top 2 must touch but NOT close above this zone.
- Entry method: neckline break → pullback → bearish entry pattern

**Bull Flag (trend continuation — only valid above the 20 MA):**
- Impulsive move up, followed by a small consolidation of 3–10 candles (the "flag")
- Entry: breakout candle that closes above the top of the consolidation range
- Stop: 1× ATR below the lowest low of the consolidation
- Target: next major resistance level

**Bear Flag (trend continuation — only valid below the 20 MA):**
- Impulsive move down, followed by small consolidation
- Entry: breakout candle closing below the consolidation low
- Same ATR stop logic, inverted

**Ascending Wedge (bullish breakout — takes 20–100 candles):**
- Flat or declining resistance level + rising support trendline (buyers stepping in higher each time)
- Breakout: price closes above the resistance
- Preferred entry: wait for pullback to the former resistance (now support) → bullish entry pattern
- Stop: 1× ATR below the swing low at entry

**Descending Wedge (bearish breakout):**
- Flat or rising support + falling resistance (sellers stepping in lower each time)
- Entry after breakout: pullback to former support (now resistance) → bearish entry pattern

Claude states: "**Chart/breakout pattern:** [PATTERN / NONE]. **Stage:** [FORMING / CONFIRMED / BROKEN OUT / PULLED BACK — ENTRY READY]. **Trade now:** [YES / WAIT — what to wait for]."

---

## Step 6 — Check RSI Confluence [EXECUTE]

If the RSI is visible on the chart, Claude reads it and adds or subtracts confluence:

| RSI Condition | What it adds |
|---|---|
| Above 70 (overbought) + bearish pattern at resistance | Confluence for short |
| Below 30 (oversold) + bullish pattern at support | Confluence for long |
| Bearish divergence: price making higher highs, RSI making lower highs | Reversal signal — confluence for short |
| Bullish divergence: price making lower lows, RSI making higher lows | Reversal signal — confluence for long |
| RSI 40–60, no divergence | Neutral — no confluence added |

Claude states: "**RSI reading:** [value or range]. **Confluence:** [ADDS BULLISH / ADDS BEARISH / NEUTRAL — reason]."

---

## Step 7 — Score the Setup and Output the Trade Plan [DECIDE]

Claude scores all factors and presents the full trade plan:

**Setup Scorecard:**

| Factor | Met? |
|---|---|
| 1. Trend identified and clear (Step 1) | ✅ / ❌ |
| 2. Higher timeframe trend aligned | ✅ / ❌ |
| 3. Price at a defined area of value (Step 2) | ✅ / ❌ |
| 4. Valid entry pattern printed (Step 4) | ✅ / ❌ |
| 5. ATR-based stop gives ≥1:1 reward:risk (Step 3) | ✅ / ❌ |
| 6. Chart or breakout pattern confirmed (Step 5) | ✅ / ❌ (optional) |
| 7. RSI confluence present (Step 6) | ✅ / ❌ (optional) |

**Decision thresholds:**
- **5–7 ✅ → STRONG SETUP** — trade with your planned position size
- **3–4 ✅ → MODERATE SETUP** — trade with half size or wait for one more confluence factor
- **0–2 ✅ → NO TRADE** — too many conditions missing; mark the level and wait

Claude outputs the final plan in this format:

```
═══════════════════════════════════════
TRADE PLAN
═══════════════════════════════════════
Asset / Timeframe : [e.g. EUR/USD Daily]
Direction         : LONG / SHORT
Setup score       : X / 7

Entry             : [price level or candle condition to wait for]
Stop loss         : [price] ([X] pips from entry)
Break-even trigger: [price — when to move stop to entry]
Target 1          : [price] ([X] pips — partial exit or break-even trigger)
Target 2          : [price] ([X] pips — full exit)
Reward : Risk     : X : 1

Verdict           : STRONG / MODERATE / NO TRADE

Notes             : [any caveats — S/R obstacle between entry and target,
                     pattern not yet confirmed, waiting conditions, etc.]
═══════════════════════════════════════
```

The user decides whether to take the trade. Claude does not predict outcomes.

---

## Step 8 — Platform Setup (First Time Only) [HAND OFF]

Tell the user:
"To set up the indicators needed for this framework on TradingView:

1. Click **Indicators** (top toolbar) → search **ATR** → select 'Average True Range' (Built-ins) → default 14-period length is correct
2. Click **Indicators** again → search **Moving Average** → add three separate instances → set lengths to **20**, **50**, and **200** (use distinct colors for each)
3. Click **Indicators** → search **RSI** → select 'Relative Strength Index' → default 14-period → in settings, add horizontal lines at **30** and **70**

To draw S/R zones: use the **Rectangle tool** to shade the zone (not just a single line) — this better represents an area rather than an exact price.

To read the current ATR value: look at the indicator panel below the main chart — the number next to the ATR label is the current value in pips/points for that timeframe."

Wait for confirmation before continuing.

---

## When the User Returns

**Same session:** Context is retained — skip Steps 1–2, go straight to the new chart.

**New session:** Ask the user to upload a new chart or re-describe conditions. Suggest saving this config:

"Save this as `ta-config.md` and paste it at the start of your next session:

```
Asset(s) I trade: [e.g. EUR/USD, BTC/USD]
Primary timeframe: [e.g. 4H]
Higher TF for alignment: [e.g. Daily]
Indicators on chart: ATR (14), MA-20, MA-50, MA-200, RSI (14)
Preferred entry pattern: [38.2 / Engulfing / Close above-below]
Min reward:risk I accept: [e.g. 1.5:1]
Notes: [anything else relevant to your trading]
```"

---

## Common Errors and Fixes

**"My stop keeps getting hit even though I'm right on direction."**
You're likely using a fixed pip stop that ignores volatility. Recalculate using the ATR: distance to swing point + 1× ATR = your minimum stop. A 10-pip stop on a Daily chart with a 150-pip ATR will be hit by normal noise nearly every time.

**"The double bottom looked perfect but the trade failed."**
Check all three rules: (1) Did bottom 2 touch the termination zone but NOT close below it? (2) Did the neckline break with a full candle close above — not just a wick? (3) Was the higher timeframe (e.g. Daily) in an uptrend when you traded it on the 1H? All three must pass.

**"The 38.2 candle triggered but price reversed against me immediately."**
Verify the objective rule: the FULL body (not the wick) must be above the 38.2 Fibonacci level drawn on that individual candle from its own low to its own high. If any part of the body is below that level, the candle is not valid.

**"My flag pattern entry failed."**
Flag patterns are only reliable when price is above (bull) or below (bear) the 20 MA at the time of the consolidation. If the consolidation dropped more than 1× ATR away from the 20 MA, the high-volatility trend filter fails and the flag loses its edge.

**"I keep seeing great setups in consolidation."**
Consolidation by definition means neither trend condition is met. No trend continuation setups apply. Only look for double tops/bottoms as potential reversal setups during consolidation, and only trade those in the direction of the higher timeframe trend.

---

## Go Deeper

- TradingView ATR indicator documentation: https://www.tradingview.com/support/solutions/43000501958
- TradingView Fibonacci Retracement tool guide (for the 38.2 candle rule): https://www.tradingview.com/support/solutions/43000502458
- Original full video — live chart examples of every concept above: https://youtu.be/eynxyoKgpng
