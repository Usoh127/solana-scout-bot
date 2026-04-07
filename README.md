# 🔍 Solana Alpha Scout Bot

A Telegram bot that monitors Solana DEXs for early-stage token opportunities,
validates them with on-chain safety checks and social sentiment, delivers
degen-coded briefings to your Telegram, and executes buys/sells via Jupiter —
but only after you explicitly confirm every trade.

---

## Architecture

**Python + `python-telegram-bot` v21 (async)** — chosen over Node.js/Telegraf
because the Solana ecosystem has better Python tooling (`solders` for tx signing),
VADER sentiment is a single pip install, and the async bot framework handles
concurrent scan + monitor loops without extra infra. Everything runs in a single
`bot.py` process with `job_queue` managing background tasks.

```
scout.py        ← GeckoTerminal + DexScreener + Birdeye
safety.py       ← Birdeye security API + Helius RPC + on-chain checks
sentiment.py    ← Twitter v2 + Nitter fallback + Reddit + NewsAPI + VADER
executor.py     ← Jupiter v6 quote → swap → sign → send
monitor.py      ← Background position risk loop
bot.py          ← Telegram handlers, briefing builder, confirmation flows
config.py       ← All .env config with sane defaults
```

---

## Setup

### 1. Prerequisites

- Python 3.11+
- A Telegram account
- A Solana wallet (**use a fresh hot wallet, not your main**)
- SOL in that wallet to trade with

### 2. Clone and install

```bash
git clone <your-repo>
cd solana_scout_bot
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Create your Telegram bot

1. Open Telegram, start a chat with **@BotFather**
2. Send `/newbot` and follow prompts
3. Copy the token (looks like `123456789:AAGmv...`)

### 4. Configure `.env`

```bash
cp .env.example .env
nano .env   # or use any text editor
```

**Required fields:**
| Key | Where to get it |
|-----|----------------|
| `TELEGRAM_BOT_TOKEN` | @BotFather → `/newbot` |
| `TELEGRAM_ALLOWED_USER_ID` | Send `/start` to bot first, your ID prints to console |
| `WALLET_PRIVATE_KEY` | Phantom → Settings → Security → Export Private Key (base58) |

**Recommended:**
| Key | Cost | Why |
|-----|------|-----|
| `HELIUS_API_KEY` | Free (100k credits/day) | Better RPC, holder checks, dump detection |
| `TWITTER_BEARER_TOKEN` | Free (developer.twitter.com) | Core sentiment signal |
| `REDDIT_CLIENT_ID/SECRET` | Free (reddit.com/prefs/apps) | Secondary sentiment |
| `NEWS_API_KEY` | Free (100 req/day) | News mentions |

**Paid APIs (optional but upgrades quality):**
| Key | Cost | What it unlocks |
|-----|------|----------------|
| `BIRDEYE_API_KEY` | ~$99/mo Starter | Full token security bundle (LP burn, creator %) |
| Twitter Basic API | $100/mo | 500k tweets/mo vs scraper fallback |

### 5. Export your wallet private key

> ⚠️ **SECURITY**: Only use a dedicated degen wallet. Never put your main wallet key anywhere.

In Phantom:
1. Click the hamburger menu → Settings
2. Security & Privacy → Export Private Key
3. Enter your password
4. Copy the base58 key (starts with a letter/number, ~88 chars)
5. Paste into `WALLET_PRIVATE_KEY` in `.env`

### 6. Run the bot

```bash
python bot.py
```

You'll see:
```
12:00:00 │ SolanaScoutBot    │ INFO     │ 🚀 Solana Alpha Scout online
          Wallet: AbCd1234...xyz
          Scan every 120s
          Monitor every 30s
```

Send `/start` to your bot in Telegram to activate it.

### 7. (Optional) Install Nitter scraper fallback

If you don't have a Twitter API key:
```bash
pip install ntscraper
```
Nitter instances are unreliable — get a free Twitter API key when possible.

---

## Usage

| Command | What it does |
|---------|-------------|
| `/start` | Shows status, wallet, config |
| `/scan` | Triggers an immediate manual scan |
| `/positions` | Lists open positions |
| `/balance` | Shows wallet SOL balance |
| `/stop` | Pauses auto-scanning |
| `/help` | Full command reference |

### Trade flow

```
[Auto-scan fires every 2min]
        ↓
[Scout: GeckoTerminal + DexScreener find new pools]
        ↓
[Filter: liquidity, volume, mcap, age, price momentum]
        ↓
[Safety: mint authority, freeze, holder concentration, LP burn]
        ↓
[Sentiment: Twitter + Reddit + News → Bullish/Neutral/Bearish]
        ↓
[Briefing sent to Telegram with BUY / SKIP buttons]
        ↓
    [User taps BUY]
        ↓
[Confirmation prompt — "YES, BUY IT" / "Cancel"]
        ↓
    [User confirms]
        ↓
[Jupiter quote → swap tx → sign → send → confirm]
        ↓
[Position registered with monitor]
        ↓
[Monitor checks every 30s: price, liquidity, dumps, sentiment]
        ↓
[Risk alert fires → SELL / IGNORE buttons]
        ↓
    [User taps SELL]
        ↓
[Confirmation prompt → Jupiter market sell]
```

---

## Paid API tier summary

| API | Free tier | When you need paid |
|-----|-----------|-------------------|
| GeckoTerminal | ✅ Fully free | Never |
| DexScreener | ✅ Fully free | Never |
| Helius | ✅ Free (100k credits/day) | High-volume trading |
| Twitter v2 | ⚠️ 10 req/15min, limited | > 1 scan/min |
| NewsAPI | ⚠️ 100 req/day, no commercial | Commercial use |
| Reddit PRAW | ✅ Fully free | Never |
| Birdeye security | ❌ Very limited free | Safety accuracy |
| Jupiter | ✅ Fully free | Never |

---

## Risk disclaimer

This bot trades real money on Solana memecoins. These are **extremely high-risk**
assets. Rug pulls, honeypots, and flash dumps are common. The bot's safety checks
reduce but cannot eliminate risk. Never invest more than you can afford to lose entirely.
Start with a small amount (0.05–0.1 SOL per trade) until you understand the system.

---

## Running as a background service (systemd)

```ini
# /etc/systemd/system/solgem-bot.service
[Unit]
Description=Solana Alpha Scout Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/solana_scout_bot
ExecStart=/home/ubuntu/solana_scout_bot/venv/bin/python bot.py
Restart=always
RestartSec=10
EnvironmentFile=/home/ubuntu/solana_scout_bot/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable solgem-bot
sudo systemctl start solgem-bot
sudo journalctl -u solgem-bot -f
```

---

## Customizing thresholds

All thresholds live in `.env` — no code changes needed:

```bash
# Smaller bag, more opportunities
MIN_LIQUIDITY_USD=10000
MIN_VOLUME_24H_USD=5000
MIN_MARKET_CAP_USD=25000
MAX_MARKET_CAP_USD=2000000

# Tighter stops for volatile sessions
STOP_LOSS_PCT=10.0
LIQUIDITY_DROP_ALERT_PCT=20.0

# More frequent scanning (watch rate limits)
SCAN_INTERVAL_SECONDS=60
```
