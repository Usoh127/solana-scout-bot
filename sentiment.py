"""
sentiment.py — Social and news sentiment validation layer.

Pipeline:
  1. Twitter API v2 (requires Bearer token — FREE tier: 10 req/15min)
     Fallback: ntscraper (Nitter scraper — no key, less reliable)
  2. Reddit via PRAW (FREE — needs client_id + secret, register at reddit.com/prefs/apps)
  3. NewsAPI (FREE tier: 100 req/day at newsapi.org)

All text is scored with VADER (fast, no GPU, no API needed).
Final label: Bullish > 0.15 / Bearish < -0.15 / Neutral in-between.

Policy:
  - If no social signal at all AND on-chain data isn't exceptional,
    the token is NOT surfaced. Caller must set data_only_call=True
    and provide data_only_reason if they want to override.
  - We NEVER recommend based only on chart patterns silently.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

import aiohttp
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from config import config

logger = logging.getLogger(__name__)

vader = SentimentIntensityAnalyzer()

TWITTER_BASE = "https://api.twitter.com/2"
NEWSAPI_BASE = "https://newsapi.org/v2"

# Nitter public instances (in priority order — fall through on failure)
NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
]


@dataclass
class SentimentResult:
    label: str          # Bullish / Neutral / Bearish
    score: float        # -1.0 to 1.0 (VADER compound)
    confidence: float   # 0.0 to 1.0 (data quality proxy)
    summary: str        # one-liner rationale

    # Twitter
    tweet_count: int = 0
    top_tweet_signal: str = ""
    twitter_avg_score: float = 0.0
    has_notable_account: bool = False

    # Reddit
    reddit_post_count: int = 0
    reddit_summary: str = ""

    # News
    news_article_count: int = 0
    news_summary: str = ""

    # Data availability flag
    has_any_signal: bool = False


class SentimentAnalyzer:
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._reddit  = None

        # ── Caches to protect free tier rate limits ───────────────────────────
        # NewsAPI: 100 req/day — cache results per ticker for 12 hours
        self._news_cache:    dict[str, tuple[float, tuple]] = {}
        # Twitter: 10 req/15min — cache per ticker for 15 minutes
        self._twitter_cache: dict[str, tuple[float, tuple]] = {}
        # Track if NewsAPI is rate limited today — stop hitting it until midnight
        self._newsapi_blocked_until: float = 0.0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _get_reddit(self):
        if self._reddit is None and config.has_reddit:
            try:
                import praw
                self._reddit = praw.Reddit(
                    client_id=config.REDDIT_CLIENT_ID,
                    client_secret=config.REDDIT_CLIENT_SECRET,
                    user_agent=config.REDDIT_USER_AGENT,
                )
                logger.info("[Sentiment] Reddit (PRAW) initialized")
            except Exception as e:
                logger.warning(f"[Sentiment] Reddit init failed: {e}")
        return self._reddit

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Utility ────────────────────────────────────────────────────────────────

    def _score_texts(self, texts: list[str]) -> tuple[float, float]:
        """
        Returns (avg_compound, std_dev) for a list of texts.
        VADER compound: -1.0 (most negative) to 1.0 (most positive).
        """
        if not texts:
            return 0.0, 0.0
        scores = [vader.polarity_scores(t)["compound"] for t in texts if t.strip()]
        if not scores:
            return 0.0, 0.0
        avg = sum(scores) / len(scores)
        variance = sum((s - avg) ** 2 for s in scores) / len(scores)
        std = variance ** 0.5
        return avg, std

    def _label_from_score(self, score: float) -> str:
        if score > 0.15:
            return "Bullish"
        if score < -0.15:
            return "Bearish"
        return "Neutral"

    # ── Twitter API v2 ─────────────────────────────────────────────────────────

    async def _search_twitter_v2(
        self, token_name: str, ticker: str, mint: str
    ) -> tuple[int, float, str, bool]:
        """
        Returns (tweet_count, avg_sentiment, top_signal, has_notable_account).
        Cache results per ticker for 15 minutes to protect the 10 req/15min limit.
        """
        if not config.has_twitter:
            return 0, 0.0, "", False

        # Check cache — 15 min TTL matches Twitter rate limit window
        now = time.time()
        cache_key = ticker.upper()
        cached = self._twitter_cache.get(cache_key)
        if cached:
            cached_at, result = cached
            if now - cached_at < 900:  # 15 minutes
                logger.debug(f"[Sentiment] Twitter cache hit for {ticker}")
                return result

        session = await self._get_session()
        headers = {"Authorization": f"Bearer {config.TWITTER_BEARER_TOKEN}"}

        # Build query: search by symbol + name + contract (fallback)
        # Keep it tight to avoid burning the rate limit budget
        query_candidates = [
            f"${ticker} lang:en -is:retweet",
            f'"{token_name}" solana lang:en -is:retweet',
            f"{mint[:8]} solana -is:retweet",
        ]

        tweets = []
        for query in query_candidates:
            params = {
                "query": query,
                "max_results": 50,
                "tweet.fields": "created_at,public_metrics,author_id,text",
                "expansions": "author_id",
                "user.fields": "public_metrics",
            }
            try:
                async with session.get(
                    f"{TWITTER_BASE}/tweets/search/recent",
                    headers=headers,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 429:
                        logger.warning("[Sentiment] Twitter rate limited, skipping")
                        break
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        meta = data.get("meta", {})
                        result_count = meta.get("result_count", 0)
                        if result_count > 0:
                            tweets = data.get("data", [])
                            users = {
                                u["id"]: u
                                for u in (data.get("includes") or {}).get("users", [])
                            }
                            logger.debug(
                                f"[Sentiment] Twitter query '{query}' → {result_count} tweets"
                            )
                            break  # Got results, stop trying other queries
                    else:
                        logger.debug(f"[Sentiment] Twitter {resp.status} for '{query}'")
            except asyncio.TimeoutError:
                logger.warning("[Sentiment] Twitter API timeout")
            except Exception as e:
                logger.warning(f"[Sentiment] Twitter error: {e}")

            await asyncio.sleep(0.3)

        if not tweets:
            result = (0, 0.0, "", False)
            self._twitter_cache[ticker.upper()] = (time.time(), result)
            return result

        texts = [t.get("text", "") for t in tweets]
        avg_score, _ = self._score_texts(texts)

        # Find top tweet by engagement
        top_tweet = ""
        has_notable = False
        max_engagement = 0
        for t in tweets:
            metrics = t.get("public_metrics", {})
            engagement = (
                metrics.get("like_count", 0)
                + metrics.get("retweet_count", 0) * 2
                + metrics.get("reply_count", 0)
            )
            if engagement > max_engagement:
                max_engagement = engagement
                text = t.get("text", "")
                top_tweet = text[:120] + "…" if len(text) > 120 else text

            # Check if any author has >10k followers
            author_id = t.get("author_id", "")
            if author_id and author_id in users:  # noqa: F821 (users defined in loop above)
                followers = users[author_id].get("public_metrics", {}).get(
                    "followers_count", 0
                )
                if followers >= 10000:
                    has_notable = True

        result = (len(tweets), avg_score, top_tweet, has_notable)
        self._twitter_cache[ticker.upper()] = (time.time(), result)
        return result

    # ── Nitter fallback ────────────────────────────────────────────────────────

    async def _search_twitter_nitter(
        self, token_name: str, ticker: str
    ) -> tuple[int, float, str]:
        """
        Fallback: scrape Nitter instance for tweet data.
        Less reliable but free and no API key needed.
        Uses ntscraper library.
        """
        try:
            from ntscraper import Nitter  # type: ignore
        except ImportError:
            logger.debug("[Sentiment] ntscraper not installed, skipping Nitter fallback")
            return 0, 0.0, ""

        for instance in NITTER_INSTANCES:
            try:
                scraper = Nitter(log_level=1, skip_instance_check=True)
                scraper.get_tweets(
                    f"${ticker}", mode="term", number=30, instance=instance
                )
                # ntscraper returns dict with 'tweets' key
                # We simulate a short async sleep since ntscraper is sync
                loop = asyncio.get_event_loop()
                results = await loop.run_in_executor(
                    None,
                    lambda: scraper.get_tweets(
                        f"#{ticker} OR ${ticker}", mode="term", number=30, instance=instance
                    ),
                )
                tweets = results.get("tweets", [])
                if not tweets:
                    continue

                texts = [t.get("text", "") for t in tweets]
                avg_score, _ = self._score_texts(texts)
                top = texts[0][:120] + "…" if texts[0] and len(texts[0]) > 120 else texts[0] if texts else ""
                logger.debug(f"[Sentiment] Nitter ({instance}) → {len(tweets)} tweets")
                return len(tweets), avg_score, top
            except Exception as e:
                logger.debug(f"[Sentiment] Nitter instance {instance} failed: {e}")
                continue

        return 0, 0.0, ""

    # ── Reddit ─────────────────────────────────────────────────────────────────

    async def _search_reddit(
        self, token_name: str, ticker: str
    ) -> tuple[int, float, str]:
        """
        Search r/solana, r/CryptoMoonShots, r/SolanaMemeCoins via PRAW.
        PRAW is synchronous — we run it in executor to avoid blocking.
        Returns (post_count, avg_sentiment, summary).
        FREE tier — just needs client_id + secret.
        """
        reddit = self._get_reddit()
        if not reddit:
            return 0, 0.0, ""

        subreddits = ["solana", "CryptoMoonShots", "SolanaMemeCoins", "altcoin"]
        query = f"{ticker} OR {token_name}"
        posts = []

        def _fetch_reddit():
            results = []
            for sub_name in subreddits:
                try:
                    sub = reddit.subreddit(sub_name)
                    for submission in sub.search(query, sort="new", time_filter="week", limit=10):
                        results.append(
                            f"{submission.title} {submission.selftext[:200]}"
                        )
                except Exception as e:
                    logger.debug(f"[Sentiment] Reddit r/{sub_name} error: {e}")
            return results

        try:
            loop = asyncio.get_event_loop()
            posts = await asyncio.wait_for(
                loop.run_in_executor(None, _fetch_reddit), timeout=15
            )
        except asyncio.TimeoutError:
            logger.warning("[Sentiment] Reddit search timed out")
            return 0, 0.0, ""
        except Exception as e:
            logger.warning(f"[Sentiment] Reddit error: {e}")
            return 0, 0.0, ""

        if not posts:
            return 0, 0.0, ""

        avg_score, _ = self._score_texts(posts)
        summary = f"{len(posts)} posts found on r/solana + related subreddits"
        return len(posts), avg_score, summary

    # ── NewsAPI ────────────────────────────────────────────────────────────────

    async def _search_news(self, token_name: str, ticker: str) -> tuple[int, float, str]:
        """
        Search NewsAPI for recent articles.
        Cache results per ticker for 12 hours to stay within 100 req/day limit.
        If rate limited, stop calling until next day reset.
        """
        if not config.has_news:
            return 0, 0.0, ""

        now = time.time()

        # If we know we are rate limited, do not even try
        if now < self._newsapi_blocked_until:
            logger.debug("[Sentiment] NewsAPI blocked until reset — using cache only")
            cached = self._news_cache.get(ticker)
            if cached:
                _, result = cached
                return result
            return 0, 0.0, ""

        # Check cache — 12 hour TTL
        cache_key = ticker.upper()
        cached = self._news_cache.get(cache_key)
        if cached:
            cached_at, result = cached
            if now - cached_at < 43200:  # 12 hours
                logger.debug(f"[Sentiment] NewsAPI cache hit for {ticker}")
                return result

        session = await self._get_session()
        params = {
            "q": f"{token_name} OR {ticker} solana",
            "sortBy": "publishedAt",
            "pageSize": 10,
            "language": "en",
            "apiKey": config.NEWS_API_KEY,
        }
        try:
            async with session.get(
                f"{NEWSAPI_BASE}/everything",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    articles = data.get("articles", [])
                    if not articles:
                        result = (0, 0.0, "")
                        self._news_cache[cache_key] = (now, result)
                        return result
                    texts = [
                        f"{a.get('title', '')} {a.get('description', '')}"
                        for a in articles
                    ]
                    avg_score, _ = self._score_texts(texts)
                    top = articles[0].get("title", "") if articles else ""
                    summary = (
                        f"{len(articles)} news articles — top: \"{top[:80]}\""
                        if top else f"{len(articles)} articles"
                    )
                    logger.debug(f"[Sentiment] NewsAPI → {len(articles)} articles")
                    result = (len(articles), avg_score, summary)
                    self._news_cache[cache_key] = (now, result)
                    return result
                elif resp.status == 429:
                    # Rate limited — block until midnight UTC
                    import datetime
                    tomorrow = datetime.datetime.utcnow().replace(
                        hour=0, minute=5, second=0, microsecond=0
                    ) + datetime.timedelta(days=1)
                    self._newsapi_blocked_until = tomorrow.timestamp()
                    logger.warning(
                        f"[Sentiment] NewsAPI rate limit hit — "
                        f"pausing until midnight UTC reset"
                    )
                    # Return cached result if available
                    cached = self._news_cache.get(cache_key)
                    if cached:
                        _, result = cached
                        return result
                else:
                    logger.debug(f"[Sentiment] NewsAPI returned {resp.status}")
                return 0, 0.0, ""
        except Exception as e:
            logger.warning(f"[Sentiment] NewsAPI error: {e}")
            return 0, 0.0, ""

    # ── Main analyze ───────────────────────────────────────────────────────────

    async def analyze(
        self,
        token_name: str,
        ticker: str,
        mint: str,
    ) -> SentimentResult:
        """
        Full sentiment pipeline. Runs Twitter, Reddit, and News in parallel.
        Returns SentimentResult with label, score, and formatted summaries.
        """
        logger.info(f"[Sentiment] Analyzing {ticker} ({token_name})")

        # Run all sources in parallel
        twitter_task = asyncio.create_task(
            self._search_twitter_v2(token_name, ticker, mint)
        )
        reddit_task = asyncio.create_task(self._search_reddit(token_name, ticker))
        news_task = asyncio.create_task(self._search_news(token_name, ticker))

        results = await asyncio.gather(
            twitter_task, reddit_task, news_task, return_exceptions=True
        )

        # Unpack twitter
        tweet_count, twitter_score, top_tweet, has_notable = 0, 0.0, "", False
        if isinstance(results[0], tuple):
            tweet_count, twitter_score, top_tweet, has_notable = results[0]
        elif isinstance(results[0], Exception):
            logger.warning(f"[Sentiment] Twitter task failed: {results[0]}")

        # If Twitter API got nothing, try Nitter fallback
        if tweet_count == 0:
            nitter_count, nitter_score, nitter_top = await self._search_twitter_nitter(
                token_name, ticker
            )
            if nitter_count > 0:
                tweet_count, twitter_score, top_tweet = nitter_count, nitter_score, nitter_top
                logger.info(f"[Sentiment] Nitter fallback: {tweet_count} tweets")

        # Unpack reddit
        reddit_count, reddit_score, reddit_summary = 0, 0.0, ""
        if isinstance(results[1], tuple):
            reddit_count, reddit_score, reddit_summary = results[1]
        elif isinstance(results[1], Exception):
            logger.warning(f"[Sentiment] Reddit task failed: {results[1]}")

        # Unpack news
        news_count, news_score, news_summary = 0, 0.0, ""
        if isinstance(results[2], tuple):
            news_count, news_score, news_summary = results[2]
        elif isinstance(results[2], Exception):
            logger.warning(f"[Sentiment] News task failed: {results[2]}")

        has_any = tweet_count > 0 or reddit_count > 0 or news_count > 0

        # Weighted score: Twitter > Reddit > News
        if has_any:
            weights = []
            weighted_sum = 0.0
            if tweet_count > 0:
                w = min(tweet_count / 50, 1.0) * 0.6  # up to 0.6 weight
                weighted_sum += twitter_score * w
                weights.append(w)
            if reddit_count > 0:
                w = min(reddit_count / 20, 1.0) * 0.3
                weighted_sum += reddit_score * w
                weights.append(w)
            if news_count > 0:
                w = min(news_count / 5, 1.0) * 0.1
                weighted_sum += news_score * w
                weights.append(w)
            total_weight = sum(weights) if weights else 1.0
            composite = weighted_sum / total_weight if total_weight > 0 else 0.0
            confidence = min(total_weight, 1.0)
        else:
            composite = 0.0
            confidence = 0.0

        label = self._label_from_score(composite)

        # Build summary line
        parts = []
        if tweet_count > 0:
            sentiment_emoji = "🟢" if twitter_score > 0.15 else "🔴" if twitter_score < -0.15 else "🟡"
            parts.append(f"{sentiment_emoji} {tweet_count} tweets (score: {twitter_score:+.2f})")
            if has_notable:
                parts.append("📢 Notable account mention detected")
        else:
            parts.append("📭 No Twitter signal found")

        if reddit_count > 0:
            parts.append(f"Reddit: {reddit_count} posts")
        if news_count > 0:
            parts.append(f"News: {news_count} articles")

        summary = " · ".join(parts) if parts else "No social signal"

        return SentimentResult(
            label=label,
            score=composite,
            confidence=confidence,
            summary=summary,
            tweet_count=tweet_count,
            top_tweet_signal=top_tweet,
            twitter_avg_score=twitter_score,
            has_notable_account=has_notable,
            reddit_post_count=reddit_count,
            reddit_summary=reddit_summary,
            news_article_count=news_count,
            news_summary=news_summary,
            has_any_signal=has_any,
        )
