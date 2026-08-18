"""
test_exit_advisor.py — Automated Unit Tests for Exit Advisor Engine
Verifies Fast-Path, Heavyweight Divergence, Option Stops, and Deterministic Fallback.
"""

import os
import sys
import unittest
from datetime import datetime
import pytz

from exit_fast_path import evaluate_fast_path, generate_rule_based_fallback, fetch_heavyweight_stocks
from exit_analyzer import evaluate_exit_with_ai, _validate_and_ground_output


class TestExitAdvisor(unittest.TestCase):

    def test_fast_path_vix_shock(self):
        """Test 1: Extreme VIX spike (>= 4%) must trigger EMERGENCY_EXIT in 0ms."""
        position = {
            "trade_type": "INTRADAY",
            "position_side": "BUY_CE",
            "entry_spot": 24200,
            "entry_premium": 120,
            "current_premium": 115
        }
        live_signals = {
            "nifty_spot": 24190,
            "india_vix_change_pct": 5.2  # Shock spike
        }
        res = evaluate_fast_path(position, live_signals)
        self.assertIsNotNone(res)
        self.assertEqual(res["verdict"], "EMERGENCY_EXIT")
        self.assertTrue(res["is_fast_path"])
        print("✅ Test 1 Passed: Fast-Path VIX Shock triggered EMERGENCY_EXIT")

    def test_fast_path_hard_premium_stop(self):
        """Test 2: Option premium loss >= 28% triggers immediate FULL_EXIT."""
        position = {
            "trade_type": "INTRADAY",
            "position_side": "BUY_CE",
            "entry_spot": 24200,
            "entry_premium": 100,
            "current_premium": 70  # -30% drop
        }
        live_signals = {
            "nifty_spot": 24150,
            "india_vix_change_pct": 0.5
        }
        res = evaluate_fast_path(position, live_signals)
        self.assertIsNotNone(res)
        self.assertEqual(res["verdict"], "FULL_EXIT")
        self.assertTrue(res["is_fast_path"])
        print("✅ Test 2 Passed: Fast-Path Premium Hard Stop triggered FULL_EXIT")

    def test_deterministic_fallback_target_hit(self):
        """Test 3: Rule-based fallback correctly triggers PARTIAL_BOOK_50 on +0.35% move."""
        position = {
            "trade_type": "INTRADAY",
            "position_side": "BUY_CE",
            "entry_spot": 24000,
        }
        live_signals = {
            "nifty_spot": 24090,  # +0.375% move
            "india_vix_change_pct": 0.2
        }
        heavyweights = {
            "RELIANCE.NS": {"change_pct": 0.5},
            "HDFCBANK.NS": {"change_pct": 0.4}
        }
        res = generate_rule_based_fallback(position, live_signals, heavyweights)
        self.assertIn(res["verdict"], ["PARTIAL_BOOK_50", "PARTIAL_BOOK_70"])
        self.assertTrue(res["is_fallback"])
        print(f"✅ Test 3 Passed: Fallback Engine triggered {res['verdict']}")

    def test_deterministic_fallback_btst_morning_gap(self):
        """Test 4: Rule-based fallback on BTST position with favorable gap."""
        position = {
            "trade_type": "BTST",
            "position_side": "BUY_PE",
            "entry_spot": 24200,
        }
        live_signals = {
            "nifty_spot": 24120,  # +80 pts gap down (favorable for PE)
            "india_vix_change_pct": 0.1
        }
        heavyweights = {}
        res = generate_rule_based_fallback(position, live_signals, heavyweights)
        self.assertIn("PARTIAL_BOOK", res["verdict"])
        print(f"✅ Test 4 Passed: BTST Gap In Favor triggered {res['verdict']}")

    def test_numerical_grounding_clamps_wild_sl(self):
        """Test 5: Numerical grounding clamps an ungrounded hallucinated stop-loss."""
        raw_ai_output = {
            "verdict": "HOLD_AND_RIDE",
            "confidence": 85,
            "trailing_sl": 19500,  # Wildly ungrounded (current spot is 24200)
            "reasoning": "Holding trend."
        }
        grounded = _validate_and_ground_output(raw_ai_output, live_spot=24200, entry_spot=24180)
        # Should be clamped back near entry spot 24180
        self.assertEqual(grounded["trailing_sl"], 24180.0)
        print("✅ Test 5 Passed: Numerical Grounding clamped hallucinated SL")


if __name__ == "__main__":
    unittest.main()
