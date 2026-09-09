"""
test_dynamic_subagents.py — Unit Tests for Dynamic Subagent Delegation Engine.
"""

import unittest
from unittest.mock import patch, MagicMock
from dynamic_subagents import (
    SPECIALIST_SPECS,
    match_dynamic_subagents,
    evaluate_single_specialist,
    evaluate_dynamic_subagents,
    format_specialists_prompt,
    _generate_fallback_verdict,
)
from debate_engine import run_debate


class TestDynamicSubagents(unittest.TestCase):
    def test_specialist_specs_defined(self):
        """Verify all 5 domain specialists have complete prompt specifications."""
        expected = [
            "RBI_Policy_Quant",
            "Geopolitical_Crude_Analyst",
            "Options_Greeks_ZeroDTE_Quant",
            "Heavyweight_Earnings_Specialist",
            "FII_OrderFlow_Tracer",
        ]
        for name in expected:
            self.assertIn(name, SPECIALIST_SPECS)
            spec = SPECIALIST_SPECS[name]
            self.assertTrue(len(spec["system_prompt"]) > 50)
            self.assertTrue(len(spec["domain"]) > 5)

    def test_match_rbi_catalyst(self):
        """Verify RBI Policy Quant trigger matching."""
        news = [{"headline": "RBI MPC keeps repo rate unchanged at 6.5%, stance neutral"}]
        matched = match_dynamic_subagents(market_signals={}, news_items=news)
        self.assertIn("RBI_Policy_Quant", matched)

    def test_match_crude_catalyst(self):
        """Verify Crude & Geopolitical Analyst trigger matching."""
        news = [{"headline": "Brent crude surges 4% amid escalating Middle East tensions"}]
        matched = match_dynamic_subagents(market_signals={}, news_items=news)
        self.assertIn("Geopolitical_Crude_Analyst", matched)

    def test_match_zero_dte_catalyst(self):
        """Verify 0-DTE Options Greeks trigger matching on expiry day."""
        signals = {"dte": 0}
        matched = match_dynamic_subagents(market_signals=signals)
        self.assertIn("Options_Greeks_ZeroDTE_Quant", matched)

        # Also via fo_expiry_context
        stage1 = {"fo_expiry_context": "Weekly expiry today with heavy call writing"}
        matched_stage1 = match_dynamic_subagents(market_signals={}, stage1_result=stage1)
        self.assertIn("Options_Greeks_ZeroDTE_Quant", matched_stage1)

    def test_match_fii_orderflow_catalyst(self):
        """Verify FII Order Flow Tracer trigger matching on extreme institutional flows."""
        signals_dump = {"fii_net": -3400.0}
        matched = match_dynamic_subagents(market_signals=signals_dump)
        self.assertIn("FII_OrderFlow_Tracer", matched)

        signals_buy = {"fii_net": 2800.0}
        matched_buy = match_dynamic_subagents(market_signals=signals_buy)
        self.assertIn("FII_OrderFlow_Tracer", matched_buy)

    def test_match_heavyweight_earnings_catalyst(self):
        """Verify Heavyweight Earnings Specialist trigger matching."""
        heavyweights = {
            "RELIANCE.NS": {"change_pct": 2.4, "name": "Reliance"},
            "HDFCBANK.NS": {"change_pct": -0.3, "name": "HDFC Bank"},
        }
        matched = match_dynamic_subagents(market_signals={}, heavyweights=heavyweights)
        self.assertIn("Heavyweight_Earnings_Specialist", matched)

    def test_max_specialists_cap(self):
        """Verify specialist cap prevents committee dilution (max 2)."""
        news = [
            {"headline": "RBI repo rate decision today while crude oil spikes"},
        ]
        signals = {"fii_net": -4000.0, "dte": 0}
        heavyweights = {"RELIANCE.NS": {"change_pct": 3.0}}

        matched = match_dynamic_subagents(
            market_signals=signals,
            news_items=news,
            heavyweights=heavyweights,
            max_specialists=2,
        )
        self.assertLessEqual(len(matched), 2)

    def test_fallback_verdicts_generation(self):
        """Verify deterministic fallback verdicts when APIs are unreachable."""
        signals = {"india_vix": 16.5, "fii_net": -3200.0, "dte": 0}
        stage1 = {"prediction": "GAP UP", "btst_bias": "BUY CE"}

        for name in SPECIALIST_SPECS:
            verdict = _generate_fallback_verdict(name, signals, stage1)
            self.assertEqual(verdict["subagent"], name)
            self.assertIn(verdict["verdict"], {"FULL_BTST", "HALF_QUANTITY", "HEDGED_SPREAD", "STRICT_NO_TRADE"})
            self.assertGreaterEqual(verdict["confidence"], 50)
            self.assertTrue(len(verdict["specialist_rationale"]) > 10)

    def test_evaluate_dynamic_subagents_fallback(self):
        """Verify evaluate_dynamic_subagents handles offline mode gracefully."""
        matched = ["RBI_Policy_Quant", "FII_OrderFlow_Tracer"]
        signals = {"fii_net": -3000.0}
        news = [{"headline": "RBI policy review"}]
        stage1 = {"prediction": "GAP DOWN", "btst_bias": "BUY PE"}

        results = evaluate_dynamic_subagents(
            matched_names=matched,
            market_signals=signals,
            news_items=news,
            stage1_result=stage1,
            gemini_key="",
            groq_key="",
        )
        self.assertEqual(len(results), 2)
        names = [r["subagent"] for r in results]
        self.assertIn("RBI_Policy_Quant", names)
        self.assertIn("FII_OrderFlow_Tracer", names)

    def test_format_specialists_prompt(self):
        """Verify prompt formatting for judge injection."""
        verdicts = [
            {
                "subagent": "RBI_Policy_Quant",
                "verdict": "HALF_QUANTITY",
                "confidence": 75,
                "specialist_rationale": "Post-policy IV collapse risk warrants conservative positioning.",
            }
        ]
        prompt_str = format_specialists_prompt(verdicts)
        self.assertIn("DYNAMIC CATALYST SPECIALISTS", prompt_str)
        self.assertIn("RBI_Policy_Quant", prompt_str)
        self.assertIn("HALF_QUANTITY", prompt_str)
        self.assertIn("75% confidence", prompt_str)

    @patch("debate_engine._run_persona")
    @patch("debate_engine._run_judge")
    def test_run_debate_with_dynamic_subagents(self, mock_judge, mock_persona):
        """Verify run_debate integrates dynamic subagents and enriches returned dictionary."""
        mock_persona.return_value = {
            "verdict": "HALF_QUANTITY",
            "confidence": 70,
            "rationale": "Momentum vs theta balanced.",
        }
        mock_judge.return_value = {
            "btst_structure": "HALF_QUANTITY",
            "trade_instruction": "Buy 1 lot ATM CE with strict stop loss.",
            "debate_consensus": "UNANIMOUS",
            "confidence_adjustment": 5,
            "judge_rationale": "Specialists and committee agreed on risk reduction.",
        }

        stage1 = {
            "prediction": "GAP UP",
            "btst_bias": "BUY CE",
            "confidence": 65,
        }
        signals = {
            "nifty_spot": 24000,
            "india_vix": 13.0,
            "fii_net": 3500.0,
            "gift_nifty_change_pct": 0.45,
        }
        news = [{"headline": "RBI MPC rate cut expectation boosts sentiment"}]

        res = run_debate(
            stage1_result=stage1,
            market_signals=signals,
            groq_key="mock_groq",
            gemini_key="mock_gemini",
            news_items=news,
        )

        self.assertIn("dynamic_subagents", res["debate"])
        self.assertTrue(len(res["debate"]["dynamic_subagents"]) > 0)
        self.assertEqual(res["btst_structure"], "HALF_QUANTITY")
        self.assertIn("Specialists", res["ai_agent_provider"])


if __name__ == "__main__":
    unittest.main()
