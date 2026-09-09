"""
test_cognigraph.py — Test Suite for CogniGraph Memory Layer.

Verifies:
  1. Deterministic regime bucketing (VIX, DTE, FII flow, Gap intent).
  2. Causal triple addition, updates, and exponential half-life time-decay.
  3. Ingestion of resolved episodes & rule-based triple extraction.
  4. Persona-conditioned retrieval (Conservative, Aggressive, Neutral, Judge).
  5. Integration with memory_log and debate_engine.
"""

import math
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from cognigraph import CogniGraph, get_cognigraph


class TestCogniGraph(unittest.TestCase):

    def setUp(self):
        # Create a fresh temporary directory for each test
        self.test_dir = tempfile.mkdtemp()
        self.cg = CogniGraph(history_dir=self.test_dir, half_life_days=30.0)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Regime Classification
    # ─────────────────────────────────────────────────────────────────────────

    def test_regime_classification_low_vix_near_expiry(self):
        signals = {
            "india_vix": 11.8,
            "dte": 1,
            "fii_net": 2200,
            "gift_nifty_change_pct": 0.45,
        }
        stage1 = {"prediction": "GAP UP", "fo_expiry_context": "Next day expiry"}
        regime = self.cg.classify_regime(signals, stage1)
        self.assertEqual(regime, "VIX_LOW|DTE_NEAR|FII_BULL|GAP_STRONG_UP")

    def test_regime_classification_high_vix_expiry_day(self):
        signals = {
            "india_vix": 18.5,
            "dte": 0,
            "fii_net": -2500,
            "gift_nifty_change_pct": -0.35,
        }
        stage1 = {"prediction": "GAP DOWN", "fo_expiry_context": "Expiry today"}
        regime = self.cg.classify_regime(signals, stage1)
        self.assertEqual(regime, "VIX_HIGH|DTE_EXPIRY|FII_BEAR|GAP_DOWN")

    def test_regime_classification_moderate_vix_flat(self):
        signals = {
            "india_vix": 14.5,
            "dte": 3,
            "fii_net": 100,
            "gift_nifty_change_pct": 0.05,
        }
        stage1 = {"prediction": "FLAT", "fo_expiry_context": "Monthly series"}
        regime = self.cg.classify_regime(signals, stage1)
        self.assertEqual(regime, "VIX_MOD|DTE_MID|FII_NEUT|GAP_FLAT")

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Causal Triples & Exponential Time Decay
    # ─────────────────────────────────────────────────────────────────────────

    def test_add_and_decay_triple(self):
        t0_str = "2026-08-01"
        self.cg.add_or_update_triple(
            subject="CUSTOM_FACTOR",
            relation="failed_due_to",
            target="CUSTOM_FAILURE",
            polarity="NEGATIVE",
            regime="VIX_MOD|DTE_NEAR|FII_BEAR|GAP_MILD_UP",
            detail="Theta decay was 40%",
            evidence_date=t0_str,
            weight_increment=2.0,
        )

        edge_key = "CUSTOM_FACTOR->failed_due_to->CUSTOM_FAILURE"
        self.assertIn(edge_key, self.cg._triples)
        self.assertEqual(self.cg._triples[edge_key]["weight"], 2.0)
        self.assertEqual(self.cg._triples[edge_key]["count"], 1)

        # After 30 days (1 half-life), decay should be approx 0.5
        decay_30 = self.cg._compute_decay(t0_str, "2026-08-31")
        self.assertAlmostEqual(decay_30, 0.5, delta=0.01)

        # After 60 days (2 half-lives), decay should be approx 0.25
        decay_60 = self.cg._compute_decay(t0_str, "2026-09-30")
        self.assertAlmostEqual(decay_60, 0.25, delta=0.01)

        # Reinforce edge on day 30
        self.cg.add_or_update_triple(
            subject="CUSTOM_FACTOR",
            relation="failed_due_to",
            target="CUSTOM_FAILURE",
            polarity="NEGATIVE",
            regime="VIX_MOD|DTE_NEAR|FII_BEAR|GAP_MILD_UP",
            detail="Second theta burn",
            evidence_date="2026-08-31",
            weight_increment=1.0,
        )
        edge = self.cg._triples[edge_key]
        self.assertEqual(edge["count"], 2)
        # Weight should be (2.0 * 0.5) + 1.0 = 2.0
        self.assertAlmostEqual(edge["weight"], 2.0, delta=0.05)

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Resolution Ingestion & Triples Extraction
    # ─────────────────────────────────────────────────────────────────────────

    def test_ingest_wrong_resolution_extracts_failure_modes(self):
        signals = {"india_vix": 15.0, "dte": 1, "gift_nifty_change_pct": 0.25}
        stage1 = {"prediction": "GAP UP", "btst_bias": "BUY CE"}

        episode = self.cg.ingest_resolution(
            trade_date="2026-09-01",
            prediction="GAP UP",
            btst_bias="BUY CE",
            confidence=75,
            actual_gap_pct=-0.10,
            outcome="❌ WRONG",
            reflection="The call failed because overnight theta decay eroded 35% of option value and HDFC heavyweight divergence pulled the index down.",
            market_signals=signals,
            stage1_result=stage1,
            trade_structure="FULL_BTST",
        )

        self.assertEqual(episode["outcome"], "WRONG")
        self.assertIn("2026-09-01", self.cg._episodes)

        # Verify extracted triples
        triples = self.cg._episodes["2026-09-01"]["triples"]
        self.assertTrue(any("Theta_Decay" in t for t in triples))
        self.assertTrue(any("Heavyweight_Divergence" in t for t in triples))

    def test_ingest_correct_resolution_extracts_catalysts(self):
        signals = {"india_vix": 12.5, "dte": 2, "fii_net": 2100, "gift_nifty_change_pct": 0.60}
        stage1 = {"prediction": "GAP UP", "btst_bias": "BUY CE"}

        episode = self.cg.ingest_resolution(
            trade_date="2026-09-02",
            prediction="GAP UP",
            btst_bias="BUY CE",
            confidence=80,
            actual_gap_pct=0.55,
            outcome="✅ CORRECT",
            reflection="US rally and institutional FII buying sustained the opening gap-up continuation.",
            market_signals=signals,
            stage1_result=stage1,
            trade_structure="FULL_BTST",
        )

        self.assertEqual(episode["outcome"], "CORRECT")
        triples = self.cg._episodes["2026-09-02"]["triples"]
        self.assertTrue(any("Institutional" in t or "Momentum" in t for t in triples))

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Persona-Conditioned Retrieval
    # ─────────────────────────────────────────────────────────────────────────

    def test_persona_conditioned_retrieval(self):
        signals = {"india_vix": 14.5, "dte": 1, "fii_net": -500, "gift_nifty_change_pct": 0.30}
        stage1 = {"prediction": "GAP UP", "btst_bias": "BUY CE"}

        # Conservative Agent Query
        cons_mem = self.cg.get_agent_memory("CONSERVATIVE", signals, stage1)
        self.assertIn("COGNIGRAPH CAUSAL RISK PRECEDENTS", cons_mem)
        self.assertIn("Antipattern:", cons_mem)

        # Aggressive Agent Query
        agg_mem = self.cg.get_agent_memory("AGGRESSIVE", signals, stage1)
        self.assertIn("COGNIGRAPH MOMENTUM PRECEDENTS", agg_mem)
        self.assertIn("Catalyst:", agg_mem)

        # Neutral Agent Query
        neut_mem = self.cg.get_agent_memory("NEUTRAL", signals, stage1)
        self.assertIn("COGNIGRAPH STRUCTURAL CONTEXT", neut_mem)

        # Judge Calibration Query (Sparse baseline)
        judge_mem_sparse = self.cg.get_judge_calibration(signals, stage1)
        self.assertIn("COGNIGRAPH REGIME CALIBRATION", judge_mem_sparse)

        # Ingest an episode to test populated Judge calibration
        self.cg.ingest_resolution(
            trade_date="2026-09-03",
            prediction="GAP UP",
            btst_bias="BUY CE",
            confidence=80,
            actual_gap_pct=0.45,
            outcome="CORRECT",
            reflection="Momentum carried through.",
            market_signals=signals,
            stage1_result=stage1,
        )
        judge_mem_populated = self.cg.get_judge_calibration(signals, stage1)
        self.assertIn("COGNIGRAPH REGIME CALIBRATION FOR JUDGE", judge_mem_populated)
        self.assertIn("Matching Historical Sessions: 1", judge_mem_populated)

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Persistence & Reloading
    # ─────────────────────────────────────────────────────────────────────────

    def test_persistence_and_reload(self):
        self.cg.add_or_update_triple(
            subject="CUSTOM_TEST_FACTOR",
            relation="impacts",
            target="NIFTY_OPEN",
            polarity="POSITIVE",
            regime="VIX_LOW|DTE_NEAR|FII_BULL|GAP_STRONG_UP",
            detail="Test persistence detail",
            evidence_date="2026-09-05",
        )
        self.cg.save()

        # Create a new instance pointing to the same directory
        cg_loaded = CogniGraph(history_dir=self.test_dir)
        edge_key = "CUSTOM_TEST_FACTOR->impacts->NIFTY_OPEN"
        self.assertIn(edge_key, cg_loaded._triples)
        self.assertEqual(cg_loaded._triples[edge_key]["details"][-1], "Test persistence detail")

    # ─────────────────────────────────────────────────────────────────────────
    # 6. Memory Log & Debate Engine Integration Checks
    # ─────────────────────────────────────────────────────────────────────────

    def test_memory_log_get_stats_includes_cognigraph(self):
        import memory_log
        ml = memory_log.NiftyMemoryLog(history_dir=self.test_dir)
        stats = ml.get_stats()
        self.assertIn("cognigraph", stats)
        cg_stats = stats["cognigraph"]
        self.assertIn("total_triples", cg_stats)
        self.assertIn("active_triples", cg_stats)

    def test_debate_engine_persona_memory_injection(self):
        from debate_engine import run_debate

        stage1 = {
            "btst_bias": "BUY CE",
            "prediction": "GAP UP",
            "confidence": 75,
            "reasoning": "GIFT Nifty up 0.45%",
        }
        signals = {
            "india_vix": 14.2,
            "gift_nifty_change_pct": 0.45,
            "nifty_spot": 25200,
        }

        # Mock Groq & Gemini calls so no external API keys are required
        mock_groq_resp = {
            "persona": "AGGRESSIVE",
            "verdict": "FULL_BTST",
            "confidence": 85,
            "rationale": "Overnight momentum supported by CogniGraph catalysts.",
        }
        mock_judge_resp = {
            "btst_structure": "HALF_QUANTITY",
            "trade_instruction": "Take half size due to regime risk calibration.",
            "debate_consensus": "MAJORITY",
            "confidence_adjustment": -5,
            "judge_rationale": "Calibrated by CogniGraph historical regime win rate.",
        }

        with patch("debate_engine._run_persona", return_value=mock_groq_resp) as mock_persona, \
             patch("debate_engine._run_judge", return_value=mock_judge_resp) as mock_judge:

            result = run_debate(stage1, signals, groq_key="mock_groq", gemini_key="mock_gemini")

            self.assertEqual(result["btst_structure"], "HALF_QUANTITY")
            self.assertEqual(result["debate_consensus"], "MAJORITY")
            # Verify _run_persona was called 3 times (AGGRESSIVE, CONSERVATIVE, NEUTRAL)
            self.assertEqual(mock_persona.call_count, 3)
            # Verify judge was called once
            mock_judge.assert_called_once()

    # ─────────────────────────────────────────────────────────────────────────
    # 7. Audit Edge Cases & Resilience Tests
    # ─────────────────────────────────────────────────────────────────────────

    def test_audit_safe_float_and_dirty_inputs(self):
        signals = {
            "india_vix": "15.4%",
            "fii_net": "+2,400.50 Cr",
            "gift_nifty_change_pct": "+0.42%",
            "dte": "1",
        }
        stage1 = {"prediction": "GAP UP"}
        regime = self.cg.classify_regime(signals, stage1)
        self.assertEqual(regime, "VIX_MOD|DTE_NEAR|FII_BULL|GAP_STRONG_UP")

    def test_audit_none_and_invalid_signals_handling(self):
        # Non-dict inputs or None
        regime_none = self.cg.classify_regime(None, None)
        self.assertEqual(regime_none, "VIX_MOD|DTE_NEAR|FII_NEUT|GAP_FLAT")

        regime_corrupt = self.cg.classify_regime("not a dict", 12345)
        self.assertEqual(regime_corrupt, "VIX_MOD|DTE_NEAR|FII_NEUT|GAP_FLAT")

    def test_audit_days_between_invalid_formats(self):
        from cognigraph import _days_between
        self.assertEqual(_days_between(None, "2026-09-01"), 0.0)
        self.assertEqual(_days_between("invalid-date", "2026-09-01"), 0.0)
        self.assertEqual(_days_between("2026-09-01", "2026-09-11"), 10.0)

    def test_audit_ingest_resolution_with_none_values(self):
        episode = self.cg.ingest_resolution(
            trade_date="2026-09-09",
            prediction=None,
            btst_bias=None,
            confidence=None,
            actual_gap_pct=None,
            outcome="WRONG",
            reflection=None,
            market_signals=None,
            stage1_result=None,
        )
        self.assertEqual(episode["confidence"], 50)
        self.assertEqual(episode["actual_gap_pct"], 0.0)
        self.assertEqual(episode["prediction"], "FLAT")

    def test_audit_neutral_empty_history_baseline_advice(self):
        neut_mem = self.cg.get_agent_memory("NEUTRAL", {})
        self.assertIn("COGNIGRAPH STRUCTURAL CONTEXT", neut_mem)
        self.assertIn("Baseline Structural Advice", neut_mem)


if __name__ == "__main__":
    unittest.main()
