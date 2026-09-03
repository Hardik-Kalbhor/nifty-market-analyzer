"""
test_intraday_debate.py — Comprehensive unit tests for 3-Analyst Intraday Debate Committee.
"""

import unittest
from unittest.mock import patch
import debate_engine


class TestIntradayDebate(unittest.TestCase):

    def setUp(self):
        self.sample_intraday = {
            "intraday_bias": {"bias": "BULLISH", "confidence": 70, "icon": "🟢"},
            "intraday_pattern": {
                "pattern": "TRENDING UP",
                "description": "Strong upside momentum.",
                "strategy": "Buy on dips",
                "option_strategy": "Buy ATM Call options"
            },
            "market_phase": {"phase": "TREND FORMATION", "description": "Morning trend active"},
            "volatility": {"level": "MODERATE", "expected_range": "50-100 pts"},
            "intraday_drivers": ["Bullish momentum", "FII net buyers"],
            "intraday_summary": "Intraday bias is BULLISH."
        }
        self.sample_signals = {
            "nifty_spot": 24000.0,
            "india_vix": 12.5,
            "pcr": 1.15,
            "max_pain": 24000,
            "top_oi_call_strike": 24200,
            "top_oi_put_strike": 23800,
        }
        self.sample_heavyweights = {
            "RELIANCE": {"name": "Reliance Industries", "price": 2950, "change_pct": 1.2},
            "HDFCBANK": {"name": "HDFC Bank", "price": 1680, "change_pct": 0.8},
        }

    def test_determine_intraday_consensus_unanimous(self):
        m = {"verdict": "TREND_BUY_CALLS"}
        d = {"verdict": "TREND_BUY_CALLS"}
        t = {"verdict": "TREND_BUY_CALLS"}
        struct, cons, note = debate_engine._determine_intraday_consensus(m, d, t)
        self.assertEqual(struct, "TREND_BUY_CALLS")
        self.assertEqual(cons, "UNANIMOUS")

    def test_determine_intraday_consensus_majority(self):
        m = {"verdict": "SCALP_DIPS_ONLY"}
        d = {"verdict": "RANGE_OPTION_SELLING"}
        t = {"verdict": "SCALP_DIPS_ONLY"}
        struct, cons, note = debate_engine._determine_intraday_consensus(m, d, t)
        self.assertEqual(struct, "SCALP_DIPS_ONLY")
        self.assertEqual(cons, "MAJORITY")

    def test_determine_intraday_consensus_split(self):
        m = {"verdict": "TREND_BUY_CALLS"}
        d = {"verdict": "RANGE_OPTION_SELLING"}
        t = {"verdict": "STRICT_WAIT_AND_WATCH"}
        struct, cons, note = debate_engine._determine_intraday_consensus(m, d, t)
        self.assertEqual(struct, "STRICT_WAIT_AND_WATCH")
        self.assertEqual(cons, "SPLIT")

    @patch("debate_engine._groq_call")
    @patch("debate_engine._gemini_call")
    def test_run_intraday_debate_success(self, mock_gemini, mock_groq):
        # Mock Groq responses for the 3 personas
        def mock_groq_side_effect(system_prompt, context, key):
            if "MOMENTUM" in system_prompt:
                return {
                    "persona": "MOMENTUM_SCALPER",
                    "verdict": "TREND_BUY_CALLS",
                    "confidence": 85,
                    "trigger_level": 24050,
                    "rationale": "Strong opening thrust with HDFC Bank push."
                }
            elif "MEAN-REVERSION" in system_prompt:
                return {
                    "persona": "WALL_DEFENDER",
                    "verdict": "RANGE_OPTION_SELLING",
                    "confidence": 65,
                    "key_wall": 24200,
                    "rationale": "Heavy Call OI at 24200 will cap runaway upside."
                }
            elif "TACTICAL" in system_prompt:
                return {
                    "persona": "TACTICAL_SCALPER",
                    "verdict": "SCALP_DIPS_ONLY",
                    "confidence": 80,
                    "entry_zone": "23980 - 24000",
                    "stop_loss": 23940,
                    "rationale": "Enter on VWAP test with 1:2.5 risk-reward."
                }
            return None

        mock_groq.side_effect = mock_groq_side_effect

        # Mock Gemini Judge
        mock_gemini.return_value = {
            "structure": "SCALP_DIPS_ONLY",
            "action_plan": "Wait for dip into 23980-24000 support, buy ATM Call with SL 23940, target 24100.",
            "entry_zone": "23980 - 24000",
            "target": 24100,
            "stop_loss": 23940,
            "debate_consensus": "MAJORITY",
            "confidence_adjustment": 5,
            "judge_rationale": "Momentum supports longs, but Call OI wall at 24200 limits extension. Dip buying is highest expectancy."
        }

        result = debate_engine.run_intraday_debate(
            intraday_result=self.sample_intraday,
            market_signals=self.sample_signals,
            heavyweights=self.sample_heavyweights,
            news_sentiment="BULLISH",
            groq_key="test-groq-key",
            gemini_key="test-gemini-key"
        )

        self.assertIn("debate", result)
        deb = result["debate"]
        self.assertEqual(deb["structure"], "SCALP_DIPS_ONLY")
        self.assertEqual(deb["consensus"], "MAJORITY")
        self.assertEqual(deb["momentum_scalper"]["verdict"], "TREND_BUY_CALLS")
        self.assertEqual(deb["wall_defender"]["verdict"], "RANGE_OPTION_SELLING")
        self.assertEqual(deb["tactical_scalper"]["verdict"], "SCALP_DIPS_ONLY")
        self.assertLess(deb["stop_loss"], 24000.0) # SL must be below spot for bullish
        self.assertGreater(deb["target"], 24000.0)  # Target above spot

    @patch("debate_engine._groq_call")
    def test_run_intraday_debate_grounding_bearish(self, mock_groq):
        # Test bearish stop-loss grounding: SL must be strictly ABOVE spot
        def mock_groq_side_effect(system_prompt, context, key):
            return {
                "verdict": "TREND_BUY_PUTS",
                "confidence": 75,
                "rationale": "Breakdown below opening low."
            }

        mock_groq.side_effect = mock_groq_side_effect

        # No Gemini key provided -> tests fallback + grounding
        result = debate_engine.run_intraday_debate(
            intraday_result=self.sample_intraday,
            market_signals=self.sample_signals,
            heavyweights=self.sample_heavyweights,
            news_sentiment="BEARISH",
            groq_key="test-groq-key",
            gemini_key=""
        )

        self.assertIn("debate", result)
        deb = result["debate"]
        self.assertEqual(deb["structure"], "TREND_BUY_PUTS")
        # For PUTS, SL must be strictly above spot (24000)
        self.assertGreater(deb["stop_loss"], 24000.0)
        # Target must be strictly below spot (24000)
        self.assertLess(deb["target"], 24000.0)


if __name__ == "__main__":
    unittest.main()
