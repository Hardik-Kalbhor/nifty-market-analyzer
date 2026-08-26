"""
test_btst_agents.py — Automated Unit Tests for 6-Agent BTST Intelligence & Arbiter
Verifies 6-Agent Swarm Context, Weighted Confluence, and Safety Invalidation Rules.
"""

import unittest
from llm_analyzer import _build_user_content, _resolve_btst_conflict, _get_fo_expiry_context


class TestBtstAgents(unittest.TestCase):

    def test_build_user_content_rich_aggregation(self):
        """Test 1: User prompt builder integrates news, heavyweights, FII/DII, and signals safely."""
        news_items = [{"headline": "Reliance hits all-time high on 5G expansion", "sector": "Energy", "category": "Corporate"}]
        market_signals = {
            "nifty_spot": 24250.0,
            "nifty_pct": 0.45,
            "india_vix": 11.2,
            "india_vix_change_pct": -3.5,
            "pcr": 1.28,
            "max_pain": 24200,
            "top_oi_call_strike": 24500,
            "top_oi_put_strike": 24000,
            "gift_nifty_change_pct": 0.52,
            "sectoral_signals": {"bank_nifty_pct": 0.65, "it_nifty_pct": -0.2},
            "global_market_changes": {"sp500": 0.4, "nasdaq": 0.8}
        }
        fii_dii = {
            "fii_net_crores": 1450,
            "dii_net_crores": 820,
            "institutional_sentiment": "BULLISH"
        }
        heavyweights = {
            "HDFCBANK.NS": {"name": "HDFC Bank", "weight": 11.5, "price": 1650.0, "change_pct": 0.75},
            "RELIANCE.NS": {"name": "Reliance Industries", "weight": 9.2, "price": 2980.0, "change_pct": 0.60},
        }

        prompt = _build_user_content(news_items, market_signals, fii_dii, heavyweights)
        self.assertIn("HDFC Bank", prompt)
        self.assertIn("Reliance Industries", prompt)
        self.assertIn("FII: ₹+1450 Cr", prompt)
        self.assertIn("GIFT Nifty Overnight Change: +0.52%", prompt)
        self.assertIn("Put-Call Ratio (PCR): 1.28", prompt)
        print("✅ Test 1 Passed: Enriched Prompt Context Builder generates all 6 dimensions")

    def test_arbiter_heavyweight_divergence_buy_ce(self):
        """Test 2: BUY CE with falling heavyweights (>20% index weight dropping) -> Overridden to NO TRADE."""
        raw_ai = {
            "prediction": "GAP UP",
            "confidence": 75,
            "btst_bias": "BUY CE",
            "news_sentiment": "BULLISH",
            "dimension_scores": {
                "macro_global": {"verdict": "GAP UP", "bias": "BULLISH", "note": "Global strong"},
                "fii_dii": {"verdict": "FLAT", "bias": "NEUTRAL", "note": "FII flat"},
                "oi_pcr": {"verdict": "GAP UP", "bias": "BULLISH", "note": "PCR 1.15"},
                "heavyweights": {"verdict": "GAP DOWN", "bias": "BEARISH", "note": "HDFC & Reliance falling"},
                "vix_regime": {"verdict": "FLAT", "bias": "CALM", "note": "VIX 11.0"},
                "news_catalyst": {"verdict": "GAP UP", "bias": "BULLISH", "note": "News positive"}
            }
        }
        heavyweights = {
            "HDFCBANK.NS": {"change_pct": -0.65},
            "RELIANCE.NS": {"change_pct": -0.52},
        }
        res = _resolve_btst_conflict(raw_ai, {"india_vix": 11.0}, heavyweights, None)
        self.assertEqual(res["btst_bias"], "NO TRADE", "Heavyweight drop must override BUY CE to NO TRADE")
        self.assertEqual(res["prediction"], "FLAT")
        self.assertTrue(res.get("conflict_resolved"))
        print(f"✅ Test 2 Passed: Heavyweight divergence overrode BUY CE -> {res['btst_bias']}")

    def test_arbiter_heavyweight_divergence_buy_pe(self):
        """Test 3: BUY PE with surging heavyweights -> Overridden to NO TRADE."""
        raw_ai = {
            "prediction": "GAP DOWN",
            "confidence": 72,
            "btst_bias": "BUY PE",
            "news_sentiment": "BEARISH",
            "dimension_scores": {
                "macro_global": {"verdict": "GAP DOWN", "bias": "BEARISH", "note": "US down"},
                "heavyweights": {"verdict": "GAP UP", "bias": "BULLISH", "note": "HDFC & Reliance surging"},
            }
        }
        heavyweights = {
            "HDFCBANK.NS": {"change_pct": 0.85},
            "RELIANCE.NS": {"change_pct": 0.70},
        }
        res = _resolve_btst_conflict(raw_ai, {"india_vix": 12.0}, heavyweights, None)
        self.assertEqual(res["btst_bias"], "NO TRADE")
        self.assertEqual(res["prediction"], "FLAT")
        self.assertTrue(res.get("conflict_resolved"))
        print(f"✅ Test 3 Passed: Heavyweight rally overrode BUY PE -> {res['btst_bias']}")

    def test_arbiter_fii_selling_headwind(self):
        """Test 4: BUY CE with heavy FII cash dump (-₹3,200 Cr) and 3 bearish dimensions -> NO TRADE."""
        raw_ai = {
            "prediction": "GAP UP",
            "confidence": 68,
            "btst_bias": "BUY CE",
            "news_sentiment": "BULLISH",
            "dimension_scores": {
                "macro_global": {"verdict": "GAP UP", "bias": "BULLISH", "note": "US green"},
                "fii_dii": {"verdict": "GAP DOWN", "bias": "BEARISH", "note": "FII heavy selling"},
                "oi_pcr": {"verdict": "GAP DOWN", "bias": "BEARISH", "note": "Call writing"},
                "heavyweights": {"verdict": "GAP DOWN", "bias": "BEARISH", "note": "Banks weak"},
                "vix_regime": {"verdict": "FLAT", "bias": "CALM", "note": "VIX 13.0"},
                "news_catalyst": {"verdict": "GAP UP", "bias": "BULLISH", "note": "Positive news"}
            }
        }
        fii_dii = {"fii_net_crores": -3200, "institutional_sentiment": "STRONG_BEARISH"}
        res = _resolve_btst_conflict(raw_ai, {"india_vix": 13.0}, {}, fii_dii)
        self.assertEqual(res["btst_bias"], "NO TRADE")
        self.assertTrue(res.get("conflict_resolved"))
        print(f"✅ Test 4 Passed: FII cash selling overrode BUY CE -> {res['btst_bias']}")

    def test_arbiter_high_vix_preservation(self):
        """Test 5: Elevated VIX (18.5) with split consensus -> Forces NO TRADE for capital preservation."""
        raw_ai = {
            "prediction": "GAP UP",
            "confidence": 65,
            "btst_bias": "BUY CE",
            "news_sentiment": "MIXED",
            "dimension_scores": {
                "macro_global": {"verdict": "GAP UP", "bias": "BULLISH", "note": "GIFT green"},
                "fii_dii": {"verdict": "FLAT", "bias": "NEUTRAL", "note": "FII flat"},
                "oi_pcr": {"verdict": "GAP DOWN", "bias": "BEARISH", "note": "Heavy call OI"},
                "heavyweights": {"verdict": "FLAT", "bias": "NEUTRAL", "note": "HDFC flat"},
                "vix_regime": {"verdict": "FLAT", "bias": "ELEVATED", "note": "VIX 18.5 high"},
                "news_catalyst": {"verdict": "GAP UP", "bias": "BULLISH", "note": "Earnings mixed"}
            }
        }
        res = _resolve_btst_conflict(raw_ai, {"india_vix": 18.5}, {}, None)
        self.assertEqual(res["btst_bias"], "NO TRADE")
        self.assertTrue(res.get("conflict_resolved"))
        print(f"✅ Test 5 Passed: High VIX risk overrode to NO TRADE")

    def test_arbiter_high_confluence_preserved(self):
        """Test 6: High Confluence (5/6 Bullish) preserves BUY CE and sets weighted confluence text."""
        raw_ai = {
            "prediction": "GAP UP",
            "confidence": 84,
            "btst_bias": "BUY CE",
            "news_sentiment": "BULLISH",
            "dimension_scores": {
                "macro_global": {"verdict": "GAP UP", "bias": "BULLISH", "note": "GIFT Nifty +0.65%"},
                "fii_dii": {"verdict": "GAP UP", "bias": "BULLISH", "note": "FII +1800 Cr"},
                "oi_pcr": {"verdict": "GAP UP", "bias": "BULLISH", "note": "PCR 1.35"},
                "heavyweights": {"verdict": "GAP UP", "bias": "BULLISH", "note": "HDFC +1.2%, Reliance +0.8%"},
                "vix_regime": {"verdict": "FLAT", "bias": "CALM", "note": "VIX 10.5"},
                "news_catalyst": {"verdict": "GAP UP", "bias": "BULLISH", "note": "Strong corporate results"}
            }
        }
        heavyweights = {
            "HDFCBANK.NS": {"change_pct": 1.2},
            "RELIANCE.NS": {"change_pct": 0.8},
        }
        fii_dii = {"fii_net_crores": 1800, "institutional_sentiment": "BULLISH"}
        res = _resolve_btst_conflict(raw_ai, {"india_vix": 10.5}, heavyweights, fii_dii)
        self.assertEqual(res["btst_bias"], "BUY CE")
        self.assertEqual(res["prediction"], "GAP UP")
        self.assertIn("5/6 Bullish", res["weighted_confluence"])
        self.assertFalse(res.get("conflict_resolved", False))
        print(f"✅ Test 6 Passed: High Bullish Confluence preserved: {res['weighted_confluence']}")


if __name__ == "__main__":
    unittest.main()
