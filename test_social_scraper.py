"""
test_social_scraper.py — Unit test suite for Social & Retail Sentiment Intelligence.
Tests:
  1. Reddit JSON parsing & noise filtering.
  2. Telegram web preview HTML parsing & anti-spam filtering.
  3. Twitter/FinTwit syndication normalization.
  4. Analyzer social sentiment scoring & contrarian trap alerts.
  5. Debate engine prompt injection.
  6. CogniGraph social priors.
"""

import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

import scraper
import analyzer
import debate_engine
from cognigraph import get_cognigraph


class TestSocialScraper(unittest.TestCase):

    def test_reddit_json_parsing(self):
        """Test Reddit JSON parsing, filtering by score, and noise exclusion."""
        fake_payload = {
            "data": {
                "children": [
                    {
                        "data": {
                            "title": "Nifty all time high incoming bulls celebrate",
                            "selftext": "Everyone buying call options today! Massive rally!",
                            "score": 45,
                            "stickied": False,
                            "over_18": False,
                            "created_utc": 1775730000,
                            "permalink": "/r/IndianStockMarket/comments/123/nifty_ath/",
                        }
                    },
                    {
                        # Low score (< 5), should be filtered out
                        "data": {
                            "title": "Random stock query",
                            "selftext": "Should I buy 1 share?",
                            "score": 2,
                            "stickied": False,
                            "over_18": False,
                            "created_utc": 1775730000,
                            "permalink": "/r/IndianStockMarket/comments/124/random/",
                        }
                    },
                    {
                        # Personal finance noise, should be filtered out
                        "data": {
                            "title": "How to improve my CIBIL credit score and fixed deposit rates",
                            "selftext": "Looking for loan guarantor advice",
                            "score": 50,
                            "stickied": False,
                            "over_18": False,
                            "created_utc": 1775730000,
                            "permalink": "/r/IndianStockMarket/comments/125/credit_score/",
                        }
                    },
                    {
                        # Stickied post, should be filtered out
                        "data": {
                            "title": "Daily discussion thread",
                            "selftext": "Rules and guidelines",
                            "score": 100,
                            "stickied": True,
                            "over_18": False,
                            "created_utc": 1775730000,
                            "permalink": "/r/IndianStockMarket/comments/126/daily/",
                        }
                    }
                ]
            }
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_payload

        with patch("requests.get", return_value=mock_resp):
            items = scraper.fetch_reddit_posts("IndianStockMarket", min_score=5, limit=10)

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.headline, "Nifty all time high incoming bulls celebrate")
        self.assertEqual(item.source, "Reddit (r/IndianStockMarket)")
        self.assertEqual(item.category, "social_sentiment")
        self.assertTrue("https://www.reddit.com/r/IndianStockMarket/comments/123/nifty_ath/" in item.link)

    def test_reddit_network_failure_fail_silent(self):
        """Test Reddit scraper handles exceptions cleanly and returns empty list."""
        with patch("requests.get", side_effect=Exception("Connection refused")):
            items = scraper.fetch_reddit_posts("IndianStockMarket")
            self.assertEqual(items, [])

    def test_telegram_html_parsing_and_spam_filter(self):
        """Test Telegram web preview HTML parsing and anti-spam regex filtering."""
        fake_html = """
        <div class="tgme_widget_message_wrap">
            <div class="tgme_widget_message_text">
                JOIN VIP CHANNEL FOR GUARANTEED PROFIT CALLS! WhatsApp us at +91 9876543210 for 100% accuracy jackpot calls!
            </div>
        </div>
        <div class="tgme_widget_message_wrap">
            <a class="tgme_widget_message_date" href="https://t.me/CNBCTV18Live/999">
                <time datetime="2026-04-08T09:30:00+00:00"></time>
            </a>
            <div class="tgme_widget_message_text">
                RBI Governor announces repo rate remains unchanged at 6.5%. Inflation trajectory remains well within comfort band.
            </div>
        </div>
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = fake_html.encode("utf-8")

        with patch("requests.get", return_value=mock_resp):
            items = scraper.fetch_telegram_channel("CNBCTV18Live", limit=5)

        # The spam message must be filtered out, leaving only the legitimate financial flash
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertIn("repo rate remains unchanged", item.headline.lower())
        self.assertEqual(item.source, "Telegram (@CNBCTV18Live)")
        self.assertEqual(item.category, "breaking_flash")
        self.assertEqual(item.link, "https://t.me/CNBCTV18Live/999")

    def test_telegram_network_failure_fail_silent(self):
        """Test Telegram scraper handles exceptions cleanly and returns empty list."""
        with patch("requests.get", side_effect=Exception("Timeout")):
            items = scraper.fetch_telegram_channel("CNBCTV18Live")
            self.assertEqual(items, [])

    def test_twitter_google_news_syndication(self):
        """Test Twitter / FinTwit detection in Google News RSS scraper."""
        fake_feed = MagicMock()
        now_tuple = datetime.now(timezone.utc).timetuple()[:6]
        fake_feed.entries = [
            {
                "title": "NIFTY option chain showing massive call buildup at 24500 - x.com",
                "summary": "FinTwit traders predicting big breakout tomorrow on NIFTY 50 index",
                "link": "https://news.google.com/rss/articles/CBMiRGh0dHBzOi8veC5jb20vdHJhZGVyL3N0YXR1cy8xMjM",
                "published_parsed": now_tuple,
            }
        ]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"<rss></rss>"

        with patch("requests.get", return_value=mock_resp), patch("feedparser.parse", return_value=fake_feed):
            items = scraper.fetch_google_news_rss("site:x.com NIFTY 50", category="social_sentiment", max_items=5)

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.source, "Twitter (FinTwit)")
        self.assertEqual(item.category, "social_sentiment")

    def test_analyzer_social_sentiment_euphoria_contrarian_trap(self):
        """Test analyzer detects retail euphoria and flags CONTRARIAN BULL TRAP against negative FII."""
        sample_social_news = [
            {
                "headline": "Nifty surges to all-time high as retail bulls celebrate massive rally",
                "snippet": "Reddit traders buying heavy call options expecting huge opening gap up",
                "source": "Reddit (r/IndianStockMarket)",
                "category": "social_sentiment",
                "sector": "General",
                "published_date": "09 Sep 2026",
                "link": "https://reddit.com/post1",
            },
            {
                "headline": "FinTwit sentiment extremely bullish on NIFTY breakout",
                "snippet": "Traders anticipate rally to continue unabated",
                "source": "Twitter (FinTwit)",
                "category": "social_sentiment",
                "sector": "General",
                "published_date": "09 Sep 2026",
                "link": "https://x.com/post2",
            }
        ]

        # FII is heavily selling cash (-2,800 Cr)
        result = analyzer.analyze_news(sample_social_news, fii_net_cr=-2800.0)

        self.assertIn("social_sentiment", result)
        social = result["social_sentiment"]
        self.assertGreater(social["retail_sentiment_score"], 40)
        self.assertEqual(social["retail_mood"], "EUPHORIC / EXTREME GREED")
        self.assertEqual(social["sample_count"], 2)
        self.assertEqual(social["source_breakdown"]["reddit"], 1)
        self.assertEqual(social["source_breakdown"]["twitter"], 1)

        # Contrarian Bull Trap Warning must be triggered
        self.assertIn("CONTRARIAN BULL TRAP RISK", social["contrarian_warning"])
        self.assertIn("-2,800 Cr", social["contrarian_warning"])

        # Factor should also be present in bearish factors as a risk caution
        bear_texts = " ".join(result.get("bearish_factors", []))
        self.assertIn("BULL TRAP", bear_texts)

    def test_analyzer_social_sentiment_panic_contrarian_bear_trap(self):
        """Test analyzer detects retail panic and flags CONTRARIAN BEAR TRAP against positive FII."""
        sample_panic_news = [
            {
                "headline": "Markets crash as recession fears trigger massive retail panic selling",
                "snippet": "Traders dump stocks and buy put options expecting deeper fall",
                "source": "Reddit (r/dalalstreetbets)",
                "category": "social_sentiment",
                "sector": "General",
                "published_date": "09 Sep 2026",
                "link": "https://reddit.com/panic1",
            }
        ]

        # FII is heavily buying cash (+2,500 Cr)
        result = analyzer.analyze_news(sample_panic_news, fii_net_cr=2500.0)

        social = result["social_sentiment"]
        self.assertLess(social["retail_sentiment_score"], -40)
        self.assertEqual(social["retail_mood"], "PANIC / EXTREME FEAR")
        self.assertIn("CONTRARIAN BEAR TRAP RISK", social["contrarian_warning"])
        self.assertIn("+2,500 Cr", social["contrarian_warning"])

    def test_debate_context_social_injection(self):
        """Test _build_debate_context formats social sentiment and contrarian warnings for agents."""
        stage1_result = {
            "btst_bias": "BUY CE",
            "prediction": "GAP UP",
            "confidence": 70,
            "reasoning": "Strong global cues",
            "social_sentiment": {
                "retail_sentiment_score": 75,
                "retail_mood": "EUPHORIC / EXTREME GREED",
                "sample_count": 8,
                "contrarian_warning": "CONTRARIAN BULL TRAP RISK: Heavy retail call buying vs FII selling",
                "top_buzz": ["Nifty ATH celebration on Reddit", "Calls galore"],
            }
        }
        market_signals = {"nifty_spot": 24650, "india_vix": 13.2}

        context = debate_engine._build_debate_context(stage1_result, market_signals)
        self.assertIn("Social & Retail Sentiment (Reddit/Telegram/FinTwit):", context)
        self.assertIn("Retail Mood: EUPHORIC / EXTREME GREED (+75/100 from 8 posts)", context)
        self.assertIn("⚠️ CONTRARIAN BULL TRAP RISK", context)
        self.assertIn("Trending Buzz: Nifty ATH celebration on Reddit", context)

    def test_cognigraph_has_social_priors(self):
        """Test CogniGraph has retail contrarian priors primed."""
        cg = get_cognigraph()
        trap_key = "Retail_Euphoria_Trap->invalidated_by->Institutional_FII_Dumping"
        panic_key = "Retail_Panic_Bottom->countered_by->DII_Accumulation"
        self.assertIn(trap_key, cg._triples)
        self.assertIn(panic_key, cg._triples)
        self.assertEqual(cg._triples[trap_key]["polarity"], "NEGATIVE")

    def test_audit_analyzer_edge_cases(self):
        """Audit test: Analyzer handles None news, dirty elements, None headlines, and dirty fii_net_cr."""
        # None news_items
        res1 = analyzer._compute_social_sentiment(None)
        self.assertEqual(res1["sample_count"], 0)

        # Dirty list elements
        res2 = analyzer._compute_social_sentiment([None, "bad", 123, {}])
        self.assertEqual(res2["sample_count"], 0)

        # None headline & snippet
        res3 = analyzer._compute_social_sentiment([
            {"headline": None, "snippet": None, "source": "Reddit (r/IndianStockMarket)", "category": "social_sentiment"}
        ])
        self.assertNotIn("None", res3["top_buzz"])

        # String fii_net_cr coercion
        res4 = analyzer._compute_social_sentiment(
            [{"headline": "Nifty surges to all-time high bulls rally", "snippet": "", "source": "Reddit", "category": "social_sentiment"}],
            fii_net_cr="-2500"
        )
        self.assertIn("CONTRARIAN BULL TRAP RISK", res4["contrarian_warning"])

    def test_audit_debate_context_edge_cases(self):
        """Audit test: Debate context builders handle None args, float/string/None scores without format crashes."""
        # None args in BTST debate context
        c1 = debate_engine._build_debate_context(None, None)
        self.assertIn("STAGE 1 ANALYSIS CONTEXT", c1)

        # None, string, float retail_sentiment_score
        c2 = debate_engine._build_debate_context({"social_sentiment": {"retail_sentiment_score": None, "retail_mood": "BULLISH", "sample_count": 5}}, {})
        self.assertIn("+0/100", c2)

        c3 = debate_engine._build_debate_context({"social_sentiment": {"retail_sentiment_score": "80", "retail_mood": "BULLISH", "sample_count": 5}}, {})
        self.assertIn("+80/100", c3)

        c4 = debate_engine._build_debate_context({"social_sentiment": {"retail_sentiment_score": 80.5, "retail_mood": "BULLISH", "sample_count": 5}}, {})
        self.assertTrue("+80/100" in c4 or "+81/100" in c4)

        # None args in Intraday debate context
        ic1 = debate_engine._build_intraday_debate_context(None, None, None, "NEUTRAL")
        self.assertIn("NIFTY 50 LIVE INTRADAY CONTEXT", ic1)

        ic2 = debate_engine._build_intraday_debate_context({}, {"social_sentiment": {"retail_sentiment_score": "65", "retail_mood": "BULLISH", "sample_count": 2}}, {}, "NEUTRAL")
        self.assertIn("+65/100", ic2)

    def test_audit_reddit_scraper_malformed_json(self):
        """Audit test: Reddit scraper handles null data blocks, null scores, and missing fields."""
        malformed_cases = [
            {"data": None},
            {"data": {"children": None}},
            {"data": {"children": [None, "invalid", {"data": None}]}},
            {"data": {"children": [{"data": {"title": None, "selftext": None, "score": None, "created_utc": None}}]}},
        ]
        for payload in malformed_cases:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = payload
            with patch("requests.get", return_value=mock_resp):
                items = scraper.fetch_reddit_posts("IndianStockMarket")
                self.assertIsInstance(items, list)


if __name__ == "__main__":
    unittest.main()
