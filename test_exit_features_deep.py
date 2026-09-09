"""
test_exit_features_deep.py — Rigorous Debugging & Boundary Test Suite
Validates all edge cases, null inputs, boundary conditions, and end-to-end flows
for the Live Exit Advisor with CogniGraph and Social Contrarian Intelligence.
"""

import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock

from exit_fast_path import (
    evaluate_fast_path,
    generate_rule_based_fallback,
    fetch_heavyweight_stocks,
    is_expiry_day,
)
from exit_analyzer import (
    EXIT_SYSTEM_PROMPT,
    _AGENT_WEIGHTS,
    _VERDICT_SEVERITY,
    _validate_and_ground_output,
    _resolve_dimension_conflict,
    generate_tiered_scale_out_plan,
    build_exit_prompt_context,
    evaluate_exit_with_ai,
)
from debate_engine import build_tiered_scale_out_plan


class TestExitFeaturesDeep(unittest.TestCase):

    def setUp(self):
        # Verify Agent Weights sum to 1.00
        total_weight = sum(_AGENT_WEIGHTS.values())
        self.assertAlmostEqual(total_weight, 1.00, places=2, msg=f"Agent weights must sum to 1.00, got {total_weight}")

    # ── 1. Null, Empty, and Corrupted Input Safety ──────────────────────────
    def test_fast_path_empty_and_null_inputs(self):
        """Fast-path must never throw exception on empty dicts, missing keys, or None values."""
        try:
            res1 = evaluate_fast_path({}, {})
            self.assertIsNone(res1)

            res2 = evaluate_fast_path({"trade_type": None, "position_side": None}, {"nifty_spot": None})
            self.assertIsNone(res2)

            res3 = evaluate_fast_path({"entry_spot": "invalid", "entry_premium": None}, {"nifty_spot": "24000"})
            self.assertIsNone(res3)

            res4 = evaluate_fast_path({"position_side": "BUY_CE"}, {"contrarian_warning": None, "social_sentiment": None})
            self.assertIsNone(res4)
        except Exception as e:
            self.fail(f"evaluate_fast_path raised unexpected exception on dirty inputs: {e}")

    # ── 2. Boundary Testing on Fast-Path Contrarian Bull Trap (Rule 8) ──────
    def test_contrarian_bull_trap_boundary_spot_gain(self):
        """Rule 8: Bull trap with spot gain >= 0.15% triggers PARTIAL_BOOK_50; < 0.15% triggers TRAIL_SL_TIGHT."""
        c_warn = "CONTRARIAN BULL TRAP RISK: Retail euphoria clashes with FII selling"

        # Case A: Spot gain is +0.14% (< 0.15%) -> TRAIL_SL_TIGHT
        pos_tight = {"position_side": "BUY_CE", "entry_spot": 24000, "entry_premium": 0, "current_premium": 0}
        sig_tight = {"nifty_spot": 24033, "contrarian_warning": c_warn}  # +0.1375%
        res_tight = evaluate_fast_path(pos_tight, sig_tight)
        self.assertIsNotNone(res_tight)
        self.assertEqual(res_tight["verdict"], "TRAIL_SL_TIGHT")
        self.assertIn("Tighten stop-loss", res_tight["action"])

        # Case B: Spot gain is +0.16% (>= 0.15%) -> PARTIAL_BOOK_50
        pos_book = {"position_side": "BUY_CE", "entry_spot": 24000, "entry_premium": 0, "current_premium": 0}
        sig_book = {"nifty_spot": 24040, "contrarian_warning": c_warn}  # +0.166%
        res_book = evaluate_fast_path(pos_book, sig_book)
        self.assertIsNotNone(res_book)
        self.assertEqual(res_book["verdict"], "PARTIAL_BOOK_50")
        self.assertIn("Book 50% profits", res_book["action"])

    def test_contrarian_bull_trap_boundary_premium_gain(self):
        """Rule 8: Bull trap with option gain >= 15% triggers PARTIAL_BOOK_50; < 15% triggers TRAIL_SL_TIGHT."""
        c_warn = "CONTRARIAN BULL TRAP RISK: Retail euphoria clashes with FII selling"

        # Premium gain +14% (< 15%)
        pos_tight = {"position_side": "BUY_CE", "entry_spot": 24000, "entry_premium": 100, "current_premium": 114}
        sig_tight = {"nifty_spot": 24005, "contrarian_warning": c_warn}
        res_tight = evaluate_fast_path(pos_tight, sig_tight)
        self.assertIsNotNone(res_tight)
        self.assertEqual(res_tight["verdict"], "TRAIL_SL_TIGHT")

        # Premium gain +15% (>= 15%)
        pos_book = {"position_side": "BUY_CE", "entry_spot": 24000, "entry_premium": 100, "current_premium": 115}
        sig_book = {"nifty_spot": 24005, "contrarian_warning": c_warn}
        res_book = evaluate_fast_path(pos_book, sig_book)
        self.assertIsNotNone(res_book)
        self.assertEqual(res_book["verdict"], "PARTIAL_BOOK_50")

    def test_contrarian_bull_trap_short_put(self):
        """Rule 8: Bull trap also protects SHORT_PE (bullish option writing trade)."""
        c_warn = "CONTRARIAN BULL TRAP RISK: Extreme greed vs institutional selling"
        pos = {"position_side": "SHORT_PE", "entry_spot": 24000, "entry_premium": 100, "current_premium": 80}
        sig = {"nifty_spot": 24050, "contrarian_warning": c_warn}
        res = evaluate_fast_path(pos, sig)
        self.assertIsNotNone(res)
        self.assertEqual(res["verdict"], "PARTIAL_BOOK_50")

    # ── 3. Boundary Testing on Fast-Path Contrarian Bear Trap (Rule 9) ──────
    def test_contrarian_bear_trap_boundary_conditions(self):
        """Rule 9: Bear trap protects BUY_PE, SHORT_CE, and SHORT_FUTURES against short squeeze."""
        c_warn = "CONTRARIAN BEAR TRAP RISK: Retail panic vs aggressive FII buying"

        # Case A: BUY_PE with +18% option gain
        pos_pe = {"position_side": "BUY_PE", "entry_spot": 24300, "entry_premium": 100, "current_premium": 118}
        sig_pe = {"nifty_spot": 24270, "contrarian_warning": c_warn}
        res_pe = evaluate_fast_path(pos_pe, sig_pe)
        self.assertIsNotNone(res_pe)
        self.assertEqual(res_pe["verdict"], "PARTIAL_BOOK_50")
        self.assertIn("Contrarian Bear Trap", res_pe["engine"])

        # Case B: SHORT_CE with +25% profit (premium dropped from 120 to 90)
        pos_ce = {"position_side": "SHORT_CE", "entry_spot": 24300, "entry_premium": 120, "current_premium": 90}
        sig_ce = {"nifty_spot": 24260, "contrarian_warning": c_warn}
        res_ce = evaluate_fast_path(pos_ce, sig_ce)
        self.assertIsNotNone(res_ce)
        self.assertEqual(res_ce["verdict"], "PARTIAL_BOOK_50")

        # Case C: Bearish trade but flat/at cost -> TRAIL_SL_TIGHT
        pos_flat = {"position_side": "BUY_PE", "entry_spot": 24300, "entry_premium": 100, "current_premium": 100}
        sig_flat = {"nifty_spot": 24300, "contrarian_warning": c_warn}
        res_flat = evaluate_fast_path(pos_flat, sig_flat)
        self.assertIsNotNone(res_flat)
        self.assertEqual(res_flat["verdict"], "TRAIL_SL_TIGHT")

    # ── 4. Contrarian Warning Non-Interference ──────────────────────────────
    def test_contrarian_warning_does_not_trigger_for_aligned_trades(self):
        """A Bull Trap warning should NOT penalize a BEARISH trade (which benefits from bull traps!)."""
        c_bull_trap = "CONTRARIAN BULL TRAP RISK: Retail euphoria vs FII selling"
        pos = {"position_side": "BUY_PE", "entry_spot": 24200, "entry_premium": 100, "current_premium": 105}
        sig = {"nifty_spot": 24190, "contrarian_warning": c_bull_trap}
        res = evaluate_fast_path(pos, sig)
        self.assertIsNone(res, "Bull Trap warning must not trigger on a Bearish trade")

    # ── 5. Rule-Based Fallback Engine Contrarian Integration ────────────────
    def test_rule_based_fallback_contrarian_clamp(self):
        """Rule-based fallback must clamp HOLD_AND_RIDE to TRAIL_SL_TIGHT when contrarian trap opposes trade."""
        pos = {"position_side": "BUY_CE", "entry_spot": 24000}
        sig = {"nifty_spot": 24020, "contrarian_warning": "CONTRARIAN BULL TRAP RISK: FII selling"}
        hw = {
            "RELIANCE.NS": {"change_pct": 0.8},
            "HDFCBANK.NS": {"change_pct": 0.5},
            "ICICIBANK.NS": {"change_pct": 0.4},
        }
        fallback = generate_rule_based_fallback(pos, sig, hw)
        self.assertEqual(fallback["verdict"], "TRAIL_SL_TIGHT")
        self.assertIn("Contrarian Trap Warning", fallback["action"])

    # ── 6. AI Output Validation & Directional Clamping ──────────────────────
    def test_validate_output_contrarian_clamp(self):
        """_validate_and_ground_output must clamp HOLD_AND_RIDE if contrarian trap opposes trade."""
        pos = {"position_side": "BUY_CE", "entry_spot": 24100}
        raw_ai = {
            "verdict": "HOLD_AND_RIDE",
            "confidence": 85,
            "trailing_sl": 24050,
            "reasoning": "Strong momentum."
        }
        res = _validate_and_ground_output(
            raw_ai, live_spot=24150, entry_spot=24100, position=pos,
            contrarian_warning="CONTRARIAN BULL TRAP RISK: Retail euphoria"
        )
        self.assertEqual(res["verdict"], "TRAIL_SL_TIGHT")
        self.assertIn("Contrarian Trap Guardrail", res["reasoning"])

    # ── 7. Conflict Resolution with 7 Dimensions ────────────────────────────
    def test_resolve_dimension_conflict_with_social_contrarian(self):
        """Conflict resolver upgrades verdict when SOCIAL_CONTRARIAN and peers flag risk."""
        parsed = {
            "verdict": "HOLD_AND_RIDE",
            "confidence": 75,
            "dimension_scores": {
                "greeks_decay": {"verdict": "TRAIL", "note": "Theta elevated"},
                "vix_regime": {"verdict": "TRAIL", "note": "VIX rising"},
                "social_contrarian": {"verdict": "EXIT", "note": "Bull trap peak"},
                "oi_pcr": {"verdict": "TRAIL", "note": "Call wall"},
                "price_action": {"verdict": "HOLD", "note": "Near support"},
                "heavyweights": {"verdict": "HOLD", "note": "HDFC flat"},
                "macro_global": {"verdict": "HOLD", "note": "Cues mixed"},
            }
        }
        resolved = _resolve_dimension_conflict(parsed)
        self.assertNotEqual(resolved["verdict"], "HOLD_AND_RIDE")
        self.assertTrue(resolved.get("conflict_resolved"))
        self.assertEqual(resolved.get("original_ai_verdict"), "HOLD_AND_RIDE")

    # ── 8. Prompt Context Formatting with CogniGraph and Social Pulse ───────
    def test_build_exit_prompt_context_enrichment(self):
        """Prompt context must format 7 dimensions, CogniGraph precedents, and Social Pulse cleanly."""
        pos = {
            "trade_type": "INTRADAY",
            "position_side": "BUY_CE",
            "strike": "24500 CE",
            "entry_spot": 24450,
            "entry_premium": 120,
            "current_premium": 150,
        }
        sig = {
            "nifty_spot": 24520,
            "india_vix": 13.8,
            "pcr": 1.15,
        }
        hw = {"RELIANCE.NS": {"name": "Reliance", "weight": 9.2, "price": 2950, "change_pct": 0.45}}
        social = {
            "retail_sentiment_score": 65,
            "retail_mood": "EUPHORIC / EXTREME GREED",
            "contrarian_warning": "CONTRARIAN BULL TRAP RISK: FII net selling -2,100 Cr",
            "top_buzz": ["Nifty to 25k today!", "Calls printing"],
        }
        cg_text = """Active Causal Regime: VIX_MOD|FII_BEAR
Historical Failure Traps: BUY_CE failed due to Theta_Decay"""

        prompt = build_exit_prompt_context(
            pos, sig, hw, [], fii_dii_data=None, social_sentiment=social, cognigraph_context=cg_text
        )

        self.assertIn("RETAIL SOCIAL SENTIMENT & CONTRARIAN TRAP SIGNALS", prompt)
        self.assertIn("EUPHORIC / EXTREME GREED", prompt)
        self.assertIn("CONTRARIAN BULL TRAP RISK", prompt)
        self.assertIn("COGNIGRAPH CAUSAL REGIME PRECEDENTS & HISTORICAL TRAPS", prompt)
        self.assertIn("VIX_MOD|FII_BEAR", prompt)
        self.assertIn("7 specialist dimensions", prompt)

    # ── 9. Full Offline Evaluate Pipeline ───────────────────────────────────
    def test_evaluate_exit_with_ai_offline_fallback(self):
        """evaluate_exit_with_ai must succeed and return complete schema even if external AI is unreachable."""
        pos = {
            "instrument": "NIFTY 24400 PE",
            "position_side": "BUY_PE",
            "entry_spot": 24400,
            "entry_premium": 110,
            "current_premium": 95,
        }
        sig = {"nifty_spot": 24420, "india_vix": 14.0}
        res = evaluate_exit_with_ai(pos, sig, news_items=[], fii_dii_data=None)

        self.assertIn("verdict", res)
        self.assertIn("action", res)
        self.assertIn("trailing_sl", res)
        self.assertIn("social_sentiment", res)
        self.assertIn("cognigraph_regime_precedent", res)
        self.assertTrue(res.get("is_fallback"))
        self.assertIn("scale_out_plan", res)

    # ── 10. Tiered Scale-Out Plan Generation & Debate Integration ───────────
    def test_generate_tiered_scale_out_plan_partial_book(self):
        """generate_tiered_scale_out_plan must generate 3 distinct actionable lot tiers for profit booking."""
        pos = {"position_side": "BUY_CE", "entry_spot": 24500}
        plan = generate_tiered_scale_out_plan("PARTIAL_BOOK_50", position=pos, live_spot=24580, trailing_sl=24500)
        self.assertIn("tier_1", plan)
        self.assertIn("tier_2", plan)
        self.assertIn("tier_3", plan)
        self.assertIn("50%", plan["tier_1"])
        self.assertIn("24,500", plan["tier_2"])
        self.assertIn("runner", plan["tier_3"].lower())

    def test_debate_engine_scale_out_plan_synthesis(self):
        """debate_engine.build_tiered_scale_out_plan synthesizes Defender vs Momentum Hawk compromise."""
        pos = {"position_side": "BUY_PE", "entry_spot": 24300}
        plan = build_tiered_scale_out_plan("TRAIL_SL_TIGHT", position=pos, live_spot=24220, trailing_sl=24260)
        self.assertIn("tier_1", plan)
        self.assertIn("tier_2", plan)
        self.assertIn("tier_3", plan)
        self.assertIn("Defender", plan["tier_1"])
        self.assertIn("Hawk", plan["tier_3"])

    def test_conflict_resolution_attaches_scale_out_plan_and_action(self):
        """Conflict resolution override attaches scale_out_plan and formats structured multi-tier action."""
        pos = {"position_side": "BUY_CE", "entry_spot": 24100}
        parsed = {
            "verdict": "HOLD_AND_RIDE",
            "confidence": 75,
            "dimension_scores": {
                "greeks_decay": {"verdict": "FULL_EXIT", "note": "Theta burn"},
                "vix_regime": {"verdict": "FULL_EXIT", "note": "VIX dumping"},
                "social_contrarian": {"verdict": "FULL_EXIT", "note": "Bull trap"},
                "oi_pcr": {"verdict": "FULL_EXIT", "note": "Call wall"},
                "price_action": {"verdict": "HOLD", "note": "Holding 20 EMA"},
                "heavyweights": {"verdict": "HOLD", "note": "Reliance flat"},
                "macro_global": {"verdict": "HOLD", "note": "Asian cues flat"},
            }
        }
        res = _resolve_dimension_conflict(parsed, position=pos, live_spot=24130)
        self.assertTrue(res.get("conflict_resolved"))
        self.assertIn("scale_out_plan", res)
        self.assertIn("Tier 1:", res.get("action", ""))
        self.assertIn("Tier 2:", res.get("action", ""))

    def test_rule_based_fallback_includes_scale_out_plan(self):
        """Deterministic rule fallback must include complete scale_out_plan with 3 tiers."""
        pos = {
            "position_side": "BUY_CE",
            "entry_spot": 24200,
            "trade_type": "INTRADAY",
            "entry_premium": 100,
            "current_premium": 140,
        }
        sig = {"nifty_spot": 24280}  # +0.33% move -> Target 1
        hw = {}
        res = generate_rule_based_fallback(pos, sig, hw)
        self.assertIn("scale_out_plan", res)
        self.assertIn("tier_1", res["scale_out_plan"])
        self.assertIn("tier_2", res["scale_out_plan"])
        self.assertIn("tier_3", res["scale_out_plan"])

    # ── 11. Dirty OCR / Currency String Immunity ────────────────────────────
    def test_dirty_ocr_inputs_in_scale_out_plan(self):
        """Scale-out plan generators must safely parse formatted currency and comma strings."""
        pos = {
            "position_side": "BUY_CE",
            "entry_spot": "₹24,500.50",
            "entry_price": "₹120.00",
        }
        plan_analyzer = generate_tiered_scale_out_plan(
            "PARTIAL_BOOK_50", position=pos, live_spot="24,580.0", trailing_sl="₹24,500"
        )
        self.assertIn("24,500", plan_analyzer["tier_2"])

        plan_debate = build_tiered_scale_out_plan(
            "PARTIAL_BOOK_70", position=pos, live_spot="24,580.0", trailing_sl="₹24,500"
        )
        self.assertIn("24,500", plan_debate["tier_2"])

    # ── 12. Dreaming Engine Robustness on Corrupted/Null Records ────────────
    def test_audit_exit_effectiveness_corrupted_records_immunity(self):
        """Dreaming audit must not crash on None, empty dicts, or missing numeric values."""
        from dreaming_engine import DreamingEngine
        import tempfile
        import shutil

        temp_dir = tempfile.mkdtemp()
        try:
            engine = DreamingEngine(history_dir=temp_dir)
            corrupted_episodes = [
                {},  # completely empty
                {"position": None, "live_spot": None, "verdict": None},
                {"position": {"entry_spot": "invalid", "entry_price": None}, "live_spot": "₹24,200"},
                {"verdict": "HOLD_AND_RIDE", "contrarian_warning": "BULL TRAP RISK", "position": {}},
            ]
            audit = engine.audit_exit_effectiveness(corrupted_episodes, settlement_spot="24,100")
            self.assertIsInstance(audit, dict)
            self.assertEqual(audit["total_exits_audited"], 4)
            self.assertGreaterEqual(len(audit["lethal_hold_errors"]), 1)

            # Test axiom synthesis with missing dates
            axioms = engine.synthesize_exit_macro_axioms(audit, corrupted_episodes)
            self.assertTrue(len(axioms) >= 1)
            for ax in axioms:
                self.assertTrue(len(ax["evidence_dates"]) >= 1)
                self.assertIsNotNone(ax["evidence_dates"][0])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
