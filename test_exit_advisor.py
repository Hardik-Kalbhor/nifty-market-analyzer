"""
test_exit_advisor.py — Automated Unit Tests for Exit Advisor Engine
Verifies Fast-Path, Heavyweight Divergence, Option Stops, and Deterministic Fallback.
"""

import os
import sys
import unittest
from datetime import datetime
from unittest.mock import patch
import pytz

from exit_fast_path import evaluate_fast_path, generate_rule_based_fallback, fetch_heavyweight_stocks
from exit_analyzer import evaluate_exit_with_ai, _validate_and_ground_output, _resolve_dimension_conflict


class TestExitAdvisor(unittest.TestCase):

    def setUp(self):
        # Patch IST time to 11:30 AM so unit tests are immune to real-world 15:15 market close cutoffs
        self.patcher = patch("exit_fast_path._get_now_ist", return_value=datetime(2026, 9, 9, 11, 30, tzinfo=pytz.timezone("Asia/Kolkata")))
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_fast_path_vix_shock(self):
        """Test 1: Extreme VIX spike (>= 8.0%) must trigger EMERGENCY_EXIT in 0ms."""
        position = {
            "trade_type": "INTRADAY",
            "position_side": "BUY_CE",
            "entry_spot": 24200,
            "entry_premium": 120,
            "current_premium": 115
        }
        live_signals = {
            "nifty_spot": 24190,
            "india_vix": 19.5,
            "india_vix_change_pct": 8.5  # Shock spike
        }
        res = evaluate_fast_path(position, live_signals)
        self.assertIsNotNone(res)
        self.assertEqual(res["verdict"], "EMERGENCY_EXIT")
        self.assertTrue(res["is_fast_path"])
        print("✅ Test 1 Passed: Fast-Path VIX Shock triggered EMERGENCY_EXIT")

    def test_fast_path_hard_premium_stop(self):
        """Test 2: Option premium loss >= 28% triggers immediate FULL_EXIT for Buy & Sell."""
        # Long Call Loss: Premium drops from 100 to 70 (-30% loss)
        pos_long = {
            "trade_type": "INTRADAY",
            "position_side": "BUY_CE",
            "entry_spot": 24200,
            "entry_premium": 100,
            "current_premium": 70
        }
        res_long = evaluate_fast_path(pos_long, {"nifty_spot": 24150, "india_vix_change_pct": 0.5})
        self.assertIsNotNone(res_long)
        self.assertEqual(res_long["verdict"], "FULL_EXIT")

        # Short Call Profit: Premium drops from 91.35 to 56.25 (+38.4% profit!) -> Must NOT trigger loss stop
        pos_short_profit = {
            "trade_type": "INTRADAY",
            "position_side": "SHORT_CE",
            "entry_spot": 24226,
            "entry_premium": 91.35,
            "current_premium": 56.25
        }
        res_short_profit = evaluate_fast_path(pos_short_profit, {"nifty_spot": 24155, "india_vix_change_pct": 0.5})
        self.assertIsNone(res_short_profit, "Profitable short position must not trigger loss stop!")

        # Short Call Loss: Premium surges from 100 to 135 (-35% loss) -> Must trigger FULL_EXIT
        pos_short_loss = {
            "trade_type": "INTRADAY",
            "position_side": "SHORT_CE",
            "entry_spot": 24200,
            "entry_premium": 100,
            "current_premium": 135
        }
        res_short_loss = evaluate_fast_path(pos_short_loss, {"nifty_spot": 24280, "india_vix_change_pct": 0.5})
        self.assertIsNotNone(res_short_loss)
        self.assertEqual(res_short_loss["verdict"], "FULL_EXIT")

        print("✅ Test 2 Passed: Fast-Path Premium Hard Stop correctly handles Long loss, Short profit, and Short loss")

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

    def test_fast_path_pcr_extreme_bullish_trade(self):
        """Test 6: PCR < 0.70 (extreme bear wall) + bullish trade → TRAIL_SL_TIGHT."""
        position = {
            "trade_type": "INTRADAY",
            "position_side": "BUY_CE",
            "entry_spot": 24200,
            "entry_premium": 90,
            "current_premium": 110,
        }
        live_signals = {
            "nifty_spot": 24250,
            "india_vix": 12.5,
            "india_vix_change_pct": 0.3,
            "pcr": 0.62,  # Extreme bearish PCR → resistance ceiling
            "top_oi_call_strike": 24500,
            "top_oi_put_strike": 24000,
        }
        res = evaluate_fast_path(position, live_signals)
        self.assertIsNotNone(res, "PCR < 0.70 with bullish trade must trigger a fast-path result")
        self.assertEqual(res["verdict"], "TRAIL_SL_TIGHT")
        self.assertIn("PCR", res["engine"])
        print(f"✅ Test 6 Passed: PCR extreme ({live_signals['pcr']}) triggered {res['verdict']} for BUY_CE")

    def test_fast_path_oi_wall_proximity(self):
        """Test 7: Spot within 35pts of top OI Call strike + bullish → TRAIL_SL_TIGHT."""
        position = {
            "trade_type": "INTRADAY",
            "position_side": "BUY_CE",
            "entry_spot": 24200,
            "entry_premium": 85,
            "current_premium": 120,
        }
        live_signals = {
            "nifty_spot": 24465,        # Only 35pts below the 24500 OI wall
            "india_vix": 12.0,
            "india_vix_change_pct": 0.1,
            "pcr": 1.05,                # Neutral PCR (won't trigger PCR rule)
            "top_oi_call_strike": 24500,
            "top_oi_put_strike": 24000,
        }
        res = evaluate_fast_path(position, live_signals)
        self.assertIsNotNone(res, "OI wall proximity (35pts) must trigger fast-path result")
        self.assertEqual(res["verdict"], "TRAIL_SL_TIGHT")
        self.assertIn("OI", res["engine"])
        print(f"✅ Test 7 Passed: OI Wall proximity (35pts) triggered {res['verdict']} for BUY_CE")

    def test_fast_path_expiry_day_short_profit_lock(self):
        """Test 8: Tuesday (expiry day) + SHORT_CE + 42% profit → PARTIAL_BOOK_70."""
        position = {
            "trade_type": "INTRADAY",
            "position_side": "SHORT_CE",
            "entry_spot": 24300,
            "entry_premium": 95.0,
            "current_premium": 55.1,   # 42% decay → strong profit
        }
        live_signals = {
            "nifty_spot": 24250,
            "india_vix": 11.8,
            "india_vix_change_pct": 0.4,
            "pcr": 1.05,
            "top_oi_call_strike": 24500,
            "top_oi_put_strike": 24000,
        }
        # Patch is_expiry_day() to return True (simulate Tuesday expiry)
        with patch("exit_fast_path.is_expiry_day", return_value=True):
            res = evaluate_fast_path(position, live_signals)

        self.assertIsNotNone(res, "Expiry day + SHORT_CE + 42% profit must trigger fast-path")
        self.assertEqual(res["verdict"], "PARTIAL_BOOK_70")
        self.assertTrue(res.get("is_expiry_day"), "Result must carry is_expiry_day=True flag")
        print(f"✅ Test 8 Passed: Expiry Day Theta Lock triggered {res['verdict']} for SHORT_CE (+42% profit)")

    def test_conflict_resolution_override(self):
        """Test 9: Weighted conflict resolver upgrades HOLD to TRAIL_SL_TIGHT when agents disagree."""
        ai_output = {
            "verdict": "HOLD_AND_RIDE",  # AI says hold
            "confidence": 72,
            "trailing_sl": 24150,
            "reasoning": "Market looks stable.",
            "dimension_scores": {
                # Majority agents say TRAIL or EXIT
                "greeks_decay":  {"verdict": "TRAIL",  "note": "Near expiry, theta burning."},
                "vix_regime":    {"verdict": "TRAIL",  "note": "VIX rising."},
                "oi_pcr":        {"verdict": "EXIT",   "note": "PCR 0.65, heavy call wall."},
                "price_action":  {"verdict": "TRAIL",  "note": "Bearish engulfing on 15min."},
                "heavyweights":  {"verdict": "HOLD",   "note": "HDFC flat."},
                "macro_global":  {"verdict": "HOLD",   "note": "Global cues neutral."},
            }
        }
        resolved = _resolve_dimension_conflict(ai_output)
        # With 4 agents at severity 3-5 and 2 at 0, avg > 2 → should override HOLD (severity 0)
        self.assertNotEqual(resolved["verdict"], "HOLD_AND_RIDE", "Conflict resolver must override HOLD when majority say TRAIL/EXIT")
        self.assertTrue(resolved.get("conflict_resolved"), "conflict_resolved flag must be True when overridden")
        print(f"✅ Test 9 Passed: Conflict Resolution overrode HOLD_AND_RIDE → {resolved['verdict']}")

    def test_fast_path_contrarian_bull_trap(self):
        """Test 10: Retail Euphoria + FII Selling (Bull Trap) + Profitable BUY_CE triggers PARTIAL_BOOK_50."""
        position = {
            "trade_type": "INTRADAY",
            "position_side": "BUY_CE",
            "entry_spot": 24200,
            "entry_premium": 100,
            "current_premium": 125,  # +25% profit
        }
        live_signals = {
            "nifty_spot": 24260,
            "india_vix": 13.0,
            "contrarian_warning": "CONTRARIAN BULL TRAP RISK: Retail euphoria (+65/100) clashes with FII selling (-2,400 Cr)",
        }
        res = evaluate_fast_path(position, live_signals)
        self.assertIsNotNone(res, "Contrarian bull trap must trigger fast-path")
        self.assertEqual(res["verdict"], "PARTIAL_BOOK_50")
        self.assertIn("Contrarian Bull Trap", res["engine"])
        print(f"✅ Test 10 Passed: Fast-Path Contrarian Bull Trap triggered {res['verdict']}")

    def test_fast_path_contrarian_bear_trap(self):
        """Test 11: Retail Panic + FII Buying (Bear Trap) + Profitable BUY_PE triggers PARTIAL_BOOK_50."""
        position = {
            "trade_type": "INTRADAY",
            "position_side": "BUY_PE",
            "entry_spot": 24300,
            "entry_premium": 110,
            "current_premium": 135,  # +22.7% profit
        }
        live_signals = {
            "nifty_spot": 24240,
            "india_vix": 14.5,
            "contrarian_warning": "CONTRARIAN BEAR TRAP RISK: Retail panic (-55/100) clashes with FII buying (+1,800 Cr)",
        }
        res = evaluate_fast_path(position, live_signals)
        self.assertIsNotNone(res, "Contrarian bear trap must trigger fast-path")
        self.assertEqual(res["verdict"], "PARTIAL_BOOK_50")
        self.assertIn("Contrarian Bear Trap", res["engine"])
        print(f"✅ Test 11 Passed: Fast-Path Contrarian Bear Trap triggered {res['verdict']}")

    def test_contrarian_guardrail_clamp_and_prompt_enrichment(self):
        """Test 12: Contrarian guardrail clamps HOLD_AND_RIDE to TRAIL_SL_TIGHT & prompt includes CogniGraph/Social."""
        from exit_analyzer import build_exit_prompt_context

        # 1. Test Contrarian Guardrail Clamp
        raw_output = {
            "verdict": "HOLD_AND_RIDE",
            "confidence": 80,
            "trailing_sl": 24150,
            "reasoning": "Holding trend."
        }
        pos = {"position_side": "BUY_CE", "entry_spot": 24180}
        grounded = _validate_and_ground_output(
            raw_output, live_spot=24200, entry_spot=24180, position=pos,
            contrarian_warning="CONTRARIAN BULL TRAP RISK: Retail euphoria clashes with heavy FII selling"
        )
        self.assertEqual(grounded["verdict"], "TRAIL_SL_TIGHT")
        self.assertIn("Contrarian Trap Guardrail", grounded["reasoning"])

        # 2. Test Prompt Context Enrichment
        prompt = build_exit_prompt_context(
            position=pos,
            live_signals={"nifty_spot": 24200, "india_vix": 13.5},
            heavyweights={},
            news_items=[],
            social_sentiment={"retail_mood": "EUPHORIC / EXTREME GREED", "retail_sentiment_score": 60, "contrarian_warning": "BULL TRAP"},
            cognigraph_context="Active Causal Regime: VIX_MOD|FII_BEAR",
        )
        self.assertIn("RETAIL SOCIAL SENTIMENT & CONTRARIAN TRAP SIGNALS", prompt)
        self.assertIn("COGNIGRAPH CAUSAL REGIME PRECEDENTS & HISTORICAL TRAPS", prompt)
        self.assertIn("7 specialist dimensions", prompt)
        print("✅ Test 12 Passed: Contrarian Guardrail clamped HOLD → TRAIL_SL_TIGHT & Prompt Context verified")


if __name__ == "__main__":
    unittest.main()

