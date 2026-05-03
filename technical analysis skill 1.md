---
name: tradingview-pro
description: "Master TradingView for professional chart analysis. Use when the user asks to set up TradingView, analyze a chart, add indicators, draw support/resistance, use Fibonacci, build alerts, plan a trade with risk/reward, write Pine Script, calculate position sizes, or practice with replay/paper trading. Triggers on phrases like 'TradingView setup', 'how do I draw', 'add indicator', 'set an alert', 'plan my trade', 'Pine Script', 'support and resistance', 'Fibonacci retracement', 'RSI', 'moving average', 'ATR', 'position size', or 'paper trade'."
---

# TradingView Pro

Claude guides you through TradingView setup, chart analysis, and professional workflows. Claude executes everything it can directly (Pine Script code, position sizing math, alert logic, watchlist templates) and gives you exact click paths for the GUI steps you must do yourself.

**Metadata:**
- Source: "Detailed Guide On How To Use TradingView Like A Pro" — https://youtu.be/cPNVa7-CXE4
- Generated: May 2026
- Target environment: Claude.ai web/app chat (no TradingView MCP connector confirmed — GUI steps are HAND OFF)
- Estimated time: Varies by task — 5 min for single features, 30 min for full setup
- Tool dependencies: tradingview.com account (free tier sufficient for most steps)

## Before Starting [EXECUTE]

I'll ask which part of TradingView you want help with so I can go straight to the right section. Common starting points:

1. **Full setup** — account creation through first live chart
2. **Drawing tools** — support/resistance zones, trend lines, Fibonacci
3. **Indicators** — Volume, MA, RSI, ATR setup and interpretation
4. **Alerts** — price and indicator-based alert conditions
5. **Trade planning** — Long/Short position tool + position sizing
6. **Pine Script** — writing custom indicators or strategies
7. **Practice** — Replay Mode or Paper Trading workflow

Tell me where to start, or describe what you're trying to do and I'll pick the right section.

---

## Step 1 — Account & Interface Setup [HAND OFF]

Tell the user: "Go to **tradingview.com** → click **Get Started** (top right) → sign up with Google or email. Then open your first chart: **Products → Super Charts**."

**Plan recommendation:**
- Free plan: 1 chart/tab, 2 indicators/chart — fine for learning
- Essential (~$15/mo): 5 indicators, no ads — upgrade when free limit frustrates you
- Premium (~$30/mo): 10 indicators, Volume Profile, intraday replay — for serious traders

**First settings to apply:**
- Dark mode: Profile picture (top right) → "Dark theme"
- Chart colors: Right-click chart → Settings → Symbol tab
- Background/grid: Right-click → Settings → Canvas tab

Wait for confirmation before continuing.

---

## Step 2 — Opening Any Market [HAND OFF] then [EXECUTE]

Tell the user: "Click the **symbol search bar** at the top-left of the chart. Always type the **ticker symbol**, not the full name."

Common tickers:
- Bitcoin → `BTC` or `BTCUSD`
- Ethereum → `ETH`
- Tesla → `TSLA`
- S&P 500 → `SPX`
- EUR/USD forex → `EURUSD`

If you see multiple results (e.g., BTCUSD on Bitstamp vs Coinbase), pick the exchange with the highest volume — it gives more reliable price data.

**Timeframe selection** (click the timeframe buttons at the top):
- Day trading: 5m, 15m, 1h
- Swing trading: 4h, 1D
- Position/investing: 1W, 1M

[EXECUTE] If you tell me the asset and your trading style, I'll recommend the exact timeframe combination to use.

---

## Step 3 — Navigation Mastery [HAND OFF]

Tell the user the essential controls:

**Mouse navigation:**
- Zoom time axis: Scroll wheel on chart
- Zoom price axis: Left-click + drag on the right price axis
- Pan chart: Left-click + drag anywhere on the chart

**Log vs Linear scale** (bottom-right of chart):
- Linear (default): Use for short-term/day trading
- Log: Use for long-term charts and assets with large % moves (e.g., Bitcoin history) — tick the "Log" checkbox

**Keyboard shortcuts cheat sheet (give these to the user):**

| Action | Shortcut |
|--------|----------|
| Trend line | Alt+T |
| Horizontal line | Alt+H |
| Fibonacci retracement | Alt+F |
| Rectangle | Alt+R |
| Create alert | Alt+A |
| Screenshot chart | Alt+S |
| Symbol search | / |
| Undo | Ctrl+Z |
| Copy object | Ctrl+C then Ctrl+V |
| Replay play/pause | Shift+↓ |

---

## Step 4 — Drawing Tools: Support & Resistance [HAND OFF] then [EXECUTE]

**Horizontal lines** (basic):
Tell the user: "Left sidebar → Trend Line Tools → Horizontal Line (or Alt+H) → click on the chart to place."

**Resistance/support zones** (recommended method):
Tell the user: "Left sidebar → Geometric Shapes → Rectangle → click twice to define zone boundaries. Use a semi-transparent fill — right-click rectangle → Settings → Style."

[EXECUTE] Tell me the asset (e.g., BTC) and paste the current price or a screenshot description. I'll suggest the key price zones to mark based on round numbers, historical structure, and common psychological levels.

**When to draw zones (not lines):** Real markets respect *zones*, not perfect prices. Draw rectangles wide enough to capture the wicks, not just the candle bodies.

---

## Step 5 — Drawing Tools: Trend Lines & Channels [HAND OFF] then [EXECUTE]

Tell the user: "Left sidebar → Trend Line → click two points (connect two lows for uptrend, two highs for downtrend)."

**Parallel channel:**
Tell the user: "Draw one trend line → Ctrl+C, Ctrl+V to copy it → drag the copy to the opposite side of the price action. This maintains the exact same angle."

[EXECUTE] If you describe the price structure (e.g., "BTC making higher lows since January, three visible lows at $60k, $65k, $70k"), I'll tell you exactly where to anchor your trend line points.

---

## Step 6 — Fibonacci Retracement [HAND OFF] then [EXECUTE]

Tell the user: "Left sidebar → Gann and Fibonacci Tools → Fib Retracement → click the swing low, drag to the swing high (for retracements in an uptrend) or swing high to swing low (in downtrend)."

**Key Fibonacci levels:**
- **0.382 (38.2%)** — shallow retracement, strong trend
- **0.5 (50%)** — midpoint, frequent reaction zone
- **0.618 (61.8%)** — "golden ratio", strongest level for entries
- **0.786 (78.6%)** — deep retracement, trend weakening

[EXECUTE] Tell me the swing high and swing low prices. I'll calculate every Fibonacci level for you, explain which levels are most significant, and suggest entry zones.

Example prompt: "Swing low $58,000, swing high $73,000 on BTC — where are the Fib levels?"

---

## Step 7 — Essential Indicators [HAND OFF + EXECUTE]

Tell the user: "Click **Indicators** button (top toolbar) → search by name → click to add."

**Free plan note:** 2 indicators maximum per chart. Upgrade to Essential (5) or Premium (10+) if needed.

### Volume
Tell the user: "Search 'Volume' → add the basic Volume indicator. No settings to change."

**How to read it:** High-volume candles = conviction. A bullish pattern (hammer, engulfing) with high volume is a much stronger signal than the same pattern with low volume.

### Moving Average (SMA / EMA)
Tell the user: "Search 'Moving Average' → add SMA. Click gear icon → set Length."

**Recommended settings:**
- 20-period: Short-term trend
- 50-period: Medium-term trend
- 200-period: Long-term trend / institutional benchmark

**How to read it:** Price above MA = bullish bias. Price below = bearish. MA acts as dynamic support/resistance.

### RSI (Relative Strength Index)
Tell the user: "Search 'RSI' → add it. Default length 14 is fine."

**How to read it:**
- Above 70: Overbought (potential reversal down)
- Below 30: Oversold (potential reversal up)
- Divergence: Price makes new high but RSI doesn't → momentum weakening

### ATR (Average True Range)
Tell the user: "Search 'ATR' → add it. Default length 14 is fine."

**How to use it:** ATR tells you the average daily price range. Use it to set stop-losses and size positions.

[EXECUTE] Give me the current ATR value and your account size, and I'll calculate your exact stop-loss distance and position size using the 1-2% risk rule.

---

## Step 8 — Position Sizing Calculator [EXECUTE]

This is a full EXECUTE step — I do all the math.

Tell me:
1. Account size (e.g., $5,000)
2. Risk per trade (I'll default to 1% = $50)
3. Entry price
4. Stop-loss price (or ATR value to set a 1.5×ATR stop)
5. Target price (to calculate risk/reward ratio)

I'll output:

```
Account:        $5,000
Risk per trade: 1% = $50
Entry:          $65,000
Stop-loss:      $63,500 (distance: $1,500)
Position size:  $50 / $1,500 = 0.033 BTC
Position value: $2,145
Target:         $69,500
R/R ratio:      3:1 ✅ (minimum is 2:1)
```

For the Long/Short Position tool on TradingView (visual version):
Tell the user: "Left sidebar → Long Position tool (green) or Short Position tool (red) → click entry price → set stop and target. The tool shows R/R ratio automatically in the colored box."

---

## Step 9 — Setting TradingView Alerts [HAND OFF + EXECUTE]

**Price alerts:**
Tell the user: "Alt+A → Condition: [symbol] → [Crossing, Greater Than, etc.] → set price level → set notification method (email, app, webhook) → Create."

**Indicator alerts:**
Tell the user: "Alt+A → Condition: [indicator name e.g. RSI(14)] → [Crossing, Greater Than] → value → Create."

**Webhook alerts (for automation):**
Tell the user: "In the alert creation dialog → select 'Webhook URL' → paste your endpoint URL."

[EXECUTE] Tell me what market condition you want to alert on (e.g., "RSI crosses below 30 on BTC daily" or "price breaks above $73,000"), and I'll write the exact alert condition syntax for you, including the alert message text and any webhook payload you need.

---

## Step 10 — Replay Mode (Backtesting Without Indicators) [HAND OFF]

Tell the user:
1. "Click the **Replay** button in the top toolbar (looks like a play button with a clock)"
2. "Click a point in chart history — the chart freezes there"
3. "Use **Shift+↓** to play forward candle by candle, or **Shift+→** to step one candle at a time"
4. "Draw levels and make decisions as if it's live — then see what actually happened"
5. "Click **Stop Replay** when done"

**Best practice:** Replay at 4h or daily timeframe. Mark your levels first, then replay forward to see if your analysis held. Track your decisions in a trade journal.

[EXECUTE] Tell me what you want to practice (e.g., "Fibonacci entries on BTC") and I'll design a structured replay session — which timeframe to use, what to mark first, what decision rules to apply, and how to score each replay result.

---

## Step 11 — Paper Trading [HAND OFF + EXECUTE]

Tell the user:
1. "Click the **Trading Panel** button at the bottom of the chart (looks like a briefcase)"
2. "Select **Paper Trading** as the broker"
3. "Your virtual balance appears — default is usually $100,000"
4. "To place a trade: click **Buy** or **Sell** → set quantity → always set a **Stop Loss** and **Take Profit** before confirming"

**Paper trading best practices:**
- Trade as if it's real money — same position sizes, same emotions
- Log every trade: entry reason, stop, target, outcome
- Run 20 trades minimum before judging a strategy's performance

[EXECUTE] Tell me your strategy (entry rules, stop placement, target), and I'll create a paper trading evaluation template — a simple scorecard you can fill in after each trade to track edge, win rate, and average R.

---

## Step 12 — Custom Pine Script Indicators [EXECUTE]

This is fully EXECUTE — I write the code, you paste it.

Tell the user: "Open the **Pine Script Editor** at the bottom → click **Open** → paste the code → click **Add to Chart**."

[EXECUTE] Tell me what indicator or alert logic you want to build. Examples:

- "RSI that turns red when overbought and green when oversold"
- "Alert me when a 20 EMA crosses above the 50 EMA"
- "Color candles when volume is 2× the 20-period average"
- "Show me the ATR-based stop-loss level as a line below price"

I'll write complete, tested Pine Script v5 code with comments explaining each line.

---

## When You Return

**Same session:** Tell me where you left off and I'll pick up without repeating setup steps.

**New session:** Save this config note and upload it next time:

```
TradingView session config:
- Asset(s) I trade: [e.g., BTC, ETH, TSLA]
- Timeframes I use: [e.g., 4h for analysis, 1h for entries]
- Indicators on chart: [e.g., 20 EMA, 50 EMA, RSI 14, ATR 14]
- Account size: [e.g., $10,000]
- Risk per trade: [e.g., 1%]
- Current skill level: [beginner/intermediate/advanced]
```

---

## Common Errors and Fixes

**"I can't add more than 2 indicators"** — Free plan limit. Options: (1) upgrade to Essential, (2) combine two indicators into one Pine Script, or (3) remove one before adding another.

**"My trend lines disappeared after reloading"** — You likely didn't save the layout. Tell the user: "Top toolbar → Save button (floppy disk icon) → Save layout. Or Ctrl+S."

**"Fibonacci levels don't look right"** — Check direction: for uptrend retracements, drag from swing LOW to swing HIGH. Dragging the wrong direction inverts all levels.

**"Alert fired but no notification"** — Check: (1) TradingView app notifications are enabled on your phone, (2) email alerts aren't going to spam, (3) the alert condition is still active (alerts expire on free plan after a set period).

**"RSI shows overbought but price keeps going up"** — RSI can stay overbought in strong trends. Use RSI divergence (price higher high, RSI lower high) as the real signal, not just the 70 level alone.

---

## Go Deeper

- TradingView official Pine Script v5 reference: https://www.tradingview.com/pine-script-reference/v5/
- TradingView chart settings guide: https://www.tradingview.com/support/solutions/43000502950
- TradingView alerts documentation: https://www.tradingview.com/support/solutions/43000520149
