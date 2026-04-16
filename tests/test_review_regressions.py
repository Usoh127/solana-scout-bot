import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch

from bot import _build_briefing, _run_scan_cycle
from narrative_tracker import NarrativeTrend, narrative_tracker
from scout import TokenOpportunity


class FakeBot:
    def __init__(self):
        self.sent_messages = []

    async def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)


class FakeContext:
    def __init__(self):
        self.bot = FakeBot()
        self.bot_data = {"chat_id": 12345}


class FakeSafetyResult:
    def __init__(self, passed=True, detail="safe"):
        self.passed = passed
        self.detail = detail


class FakeSentimentResult:
    def __init__(self):
        self.label = "Bullish"
        self.score = 0.7
        self.summary = "Strong social chatter"
        self.tweet_count = 25
        self.top_tweet_signal = "Token is trending"
        self.reddit_summary = ""
        self.news_summary = ""
        self.has_notable_account = True
        self.has_any_signal = True


def make_opportunity() -> TokenOpportunity:
    return TokenOpportunity(
        mint="Mint111111111111111111111111111111111111111",
        name="Doge Agent",
        symbol="DOGEAI",
        pool_address="Pool111111111111111111111111111111111111111",
        dex="raydium",
        price_usd=0.001,
        market_cap_usd=150_000,
        fdv_usd=150_000,
        liquidity_usd=50_000,
        volume_24h_usd=250_000,
        volume_6h_usd=120_000,
        volume_1h_usd=45_000,
        price_change_1h=35.0,
        price_change_6h=90.0,
        price_change_24h=120.0,
        launched_at=None,
        age_hours=0.4,
    )


class ReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        self.original_state = narrative_tracker.state
        self.original_macro = narrative_tracker._macro_signals.copy()

    def tearDown(self):
        narrative_tracker.state = self.original_state
        narrative_tracker._macro_signals = self.original_macro

    def test_briefing_renders_narrative_fit_line_when_state_is_fresh(self):
        opp = make_opportunity()
        opp.safety_passed = True
        opp.safety_detail = "safe"
        opp.sentiment_label = "Bullish"
        opp.sentiment_summary = "Bullish"
        opp.tweet_count = 20

        narrative_tracker.state.top_trends = [
            NarrativeTrend(
                name="AI / Agents",
                count=6,
                strength="🔥 Hot",
                examples=["DOGEAI"],
                source="scan",
            )
        ]
        narrative_tracker.state.macro_signals = []
        narrative_tracker.state.last_updated = time.time()

        text, _ = _build_briefing(opp)

        self.assertIn("Fits trending narrative", text)
        self.assertIn("Market Narrative", text)

    def test_narrative_alert_suppressed_when_state_is_stale(self):
        opp = make_opportunity()
        opp.safety_passed = True
        opp.safety_detail = "safe"
        opp.sentiment_label = "Bullish"
        opp.sentiment_summary = "Bullish"
        opp.tweet_count = 20

        narrative_tracker.state.top_trends = [
            NarrativeTrend(
                name="AI / Agents",
                count=6,
                strength="🔥 Hot",
                examples=["DOGEAI"],
                source="scan",
            )
        ]
        narrative_tracker.state.last_updated = 0

        text, _ = _build_briefing(opp)

        self.assertNotIn("Market Narrative", text)
        self.assertNotIn("Fits trending narrative", text)

    def test_narrative_update_clears_stale_trends_when_no_data(self):
        narrative_tracker.state.top_trends = [
            NarrativeTrend(
                name="Dogs",
                count=3,
                strength="📈 Rising",
                examples=["DOGE"],
                source="scan",
            )
        ]
        narrative_tracker.state.last_updated = 0
        narrative_tracker._scan_events.clear()
        narrative_tracker._boost_categories.clear()
        narrative_tracker._macro_signals = []

        with patch.object(
            narrative_tracker, "_fetch_boost_narratives", AsyncMock()
        ), patch.object(
            narrative_tracker, "_fetch_macro_narratives", AsyncMock()
        ):
            asyncio.run(narrative_tracker.update())

        self.assertEqual([], narrative_tracker.state.top_trends)
        self.assertEqual(0, narrative_tracker.state.total_tokens_seen)

    def test_scan_cycle_passes_market_data_into_safety_check(self):
        opp = make_opportunity()
        context = FakeContext()

        with patch("bot.scout.scan_for_opportunities", AsyncMock(return_value=[opp])), \
             patch("bot.narrative_tracker.update", AsyncMock()), \
             patch("bot.safety_checker.full_safety_check", AsyncMock(return_value=FakeSafetyResult())) as safety_mock, \
             patch("bot.sentiment_analyzer.analyze", AsyncMock(return_value=FakeSentimentResult())):
            asyncio.run(_run_scan_cycle(context))

        self.assertEqual(1, safety_mock.await_count)
        _, kwargs = safety_mock.await_args
        self.assertEqual(opp.volume_24h_usd, kwargs["volume_24h"])
        self.assertEqual(opp.liquidity_usd, kwargs["liquidity"])
        self.assertEqual(opp.txns_24h, kwargs["txns_24h"])


if __name__ == "__main__":
    unittest.main()
