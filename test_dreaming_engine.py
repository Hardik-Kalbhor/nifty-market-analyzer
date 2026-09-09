"""
test_dreaming_engine.py — Unit Tests for 20:00 IST Post-Market Memory Consolidation Cycle.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from dreaming_engine import DreamingEngine, get_dreaming_engine
from cognigraph import CogniGraph
from memory_log import NiftyMemoryLog


class TestDreamingEngine(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="dreaming_test_")
        self.history_dir = Path(self.test_dir) / "history"
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.engine = DreamingEngine(history_dir=str(self.history_dir))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_harvest_episodes(self):
        """Verify harvesting accurately parses resolved episodes and ignores pending entries."""
        mem = NiftyMemoryLog(history_dir=str(self.history_dir))
        # Store 1 pending
        mem.store_prediction(
            trade_date="2026-09-08",
            prediction="GAP UP",
            btst_bias="BUY CE",
            confidence=75,
            reasoning="Strong global tech rally",
            fii_net=2200.0,
            india_vix=13.2,
        )
        # Manually create a resolved entry in memory_log.md using the official delimiter
        log_file = self.history_dir / "memory_log.md"
        resolved_block = (
            "\n\n<!-- ENTRY_END -->\n\n"
            "[2026-09-07 | GAP UP | BUY CE | 70% | resolved | CORRECT]\n"
            "REASONING:\n"
            "GIFT Nifty was up, FII bought ₹1500 Cr.\n"
            "OUTCOME:\n"
            "Actual: +0.45% (GAP UP) | CORRECT\n"
            "REFLECTION:\n"
            "FII cash buying sustained the opening drive.\n"
            "\n\n<!-- ENTRY_END -->\n\n"
        )
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(resolved_block)

        episodes = self.engine.harvest_episodes()
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["trade_date"], "2026-09-07")
        self.assertEqual(episodes[0]["outcome"], "CORRECT")
        self.assertAlmostEqual(episodes[0]["actual_gap_pct"], 0.45)

    def test_synthesize_macro_axioms_heuristic_fii_bear(self):
        """Test heuristic detection of FII heavy selling vs bullish prediction failure trap."""
        episodes = [
            {
                "trade_date": "2026-09-01",
                "prediction": "GAP UP",
                "btst_bias": "BUY CE",
                "fii_net": -2300.0,
                "india_vix": 14.5,
                "outcome": "WRONG",
            },
            {
                "trade_date": "2026-09-02",
                "prediction": "GAP UP",
                "btst_bias": "BUY CE",
                "fii_net": -1800.0,
                "india_vix": 15.0,
                "outcome": "PARTIAL",
            },
        ]
        axioms = self.engine.synthesize_macro_axioms_heuristic(episodes)
        axiom_ids = [a["axiom_id"] for a in axioms]
        self.assertIn("AXIOM_FII_OUTFLOW_BULLISH_VETO", axiom_ids)

    def test_synthesize_macro_axioms_heuristic_high_vix(self):
        """Test heuristic detection of elevated India VIX option decay trap."""
        episodes = [
            {
                "trade_date": "2026-09-03",
                "prediction": "GAP UP",
                "btst_bias": "BUY CE",
                "fii_net": 500.0,
                "india_vix": 18.2,
                "outcome": "WRONG",
            },
            {
                "trade_date": "2026-09-04",
                "prediction": "GAP DOWN",
                "btst_bias": "BUY PE",
                "fii_net": -400.0,
                "india_vix": 17.5,
                "outcome": "PARTIAL",
            },
        ]
        axioms = self.engine.synthesize_macro_axioms_heuristic(episodes)
        axiom_ids = [a["axiom_id"] for a in axioms]
        self.assertIn("AXIOM_HIGH_VIX_THETA_CRUSH", axiom_ids)

    def test_synthesize_macro_axioms_heuristic_fii_bull(self):
        """Test heuristic detection of institutional inflow follow-through."""
        episodes = [
            {"trade_date": "2026-08-20", "fii_net": 1800.0, "outcome": "CORRECT", "india_vix": 13.0},
            {"trade_date": "2026-08-21", "fii_net": 2200.0, "outcome": "CORRECT", "india_vix": 13.5},
            {"trade_date": "2026-08-22", "fii_net": 1200.0, "outcome": "CORRECT", "india_vix": 14.0},
        ]
        axioms = self.engine.synthesize_macro_axioms_heuristic(episodes)
        axiom_ids = [a["axiom_id"] for a in axioms]
        self.assertIn("AXIOM_INSTITUTIONAL_INFLOW_FOLLOW_THROUGH", axiom_ids)

    def test_synthesize_macro_axioms_llm(self):
        """Test LLM distillation parser extracting JSON axioms and fallback handling."""
        mock_response = (
            "Here is the distillation:\n"
            "[\n"
            "  {\n"
            "    \"axiom_id\": \"AXIOM_EARNINGS_VOL_DUMP\",\n"
            "    \"statement\": \"Holding overnight options into heavyweight results leads to IV crush.\",\n"
            "    \"subject\": \"Heavyweight_Earnings\",\n"
            "    \"relation\": \"triggers\",\n"
            "    \"target\": \"Implied_Volatility_Crush\",\n"
            "    \"polarity\": \"NEGATIVE\",\n"
            "    \"confidence\": 0.88\n"
            "  }\n"
            "]"
        )
        axioms = self.engine.synthesize_macro_axioms_llm(
            episodes=[{"trade_date": "2026-09-01", "outcome": "WRONG"}],
            llm_distill_fn=lambda prompt: mock_response,
        )
        self.assertEqual(len(axioms), 1)
        self.assertEqual(axioms[0]["axiom_id"], "AXIOM_EARNINGS_VOL_DUMP")
        self.assertEqual(axioms[0]["confidence"], 0.88)

    def test_merge_and_store_axioms_atomic(self):
        """Verify merging axioms updates observations and writes atomically to disk."""
        initial_axiom = {
            "axiom_id": "AXIOM_TEST_1",
            "statement": "Initial statement",
            "confidence": 0.80,
            "observation_count": 2,
            "evidence_dates": ["2026-09-01"],
            "last_validated": "2026-09-01",
        }
        self.engine.merge_and_store_axioms([initial_axiom])
        self.assertTrue((self.history_dir / "macro_axioms.json").exists())

        # Merge same axiom with update
        updated_axiom = {
            "axiom_id": "AXIOM_TEST_1",
            "statement": "Updated statement",
            "confidence": 0.90,
            "observation_count": 1,
            "evidence_dates": ["2026-09-02"],
            "last_validated": "2026-09-02",
        }
        self.engine.merge_and_store_axioms([updated_axiom])

        reloaded = DreamingEngine(history_dir=str(self.history_dir))
        ax = reloaded._axioms["AXIOM_TEST_1"]
        self.assertEqual(ax["observation_count"], 3)
        self.assertAlmostEqual(ax["confidence"], 0.84, places=2)
        self.assertIn("2026-09-02", ax["evidence_dates"])
        self.assertEqual(ax["statement"], "Updated statement")

    def test_cognigraph_decay_and_reinforce(self):
        """Verify CogniGraph bulk decay and edge reinforcement from macro axioms."""
        cg = CogniGraph(history_dir=str(self.history_dir))
        # Add a custom edge with old last_seen
        cg.add_or_update_triple(
            subject="TestSub",
            relation="invalidates",
            target="TestTar",
            polarity="NEGATIVE",
            regime="VIX_LOW|DTE_NEAR|FII_NEUT|GAP_FLAT",
            evidence_date="2026-01-01",
            weight_increment=0.1,
        )
        res = cg.decay_and_prune(threshold=0.2, max_idle_days=60.0)
        self.assertGreaterEqual(res["decayed"], 1)

        # Reinforce from axiom
        axiom = {
            "axiom_id": "AXIOM_REINFORCE_TEST",
            "subject": "FII_Flow",
            "relation": "drives",
            "target": "Nifty_Trend",
            "polarity": "POSITIVE",
            "regime": "VIX_LOW|DTE_MID|FII_BULL|GAP_STRONG_UP",
            "statement": "FII buying strongly drives trend.",
            "confidence": 0.85,
        }
        key = cg.reinforce_from_axiom(axiom)
        self.assertEqual(key, "FII_Flow->drives->Nifty_Trend")
        self.assertIn("FII_Flow->drives->Nifty_Trend", cg._triples)

    def test_skill_curator_audit(self):
        """Test categorization of skill playbooks into excelling, healthy, and needs_review."""
        from skills_engine import SkillCurator
        curator = SkillCurator(history_dir=str(self.history_dir))

        # Skill 1: Excelling (4 wins, 1 loss -> 80%)
        # Skill 2: Decayed (1 win, 3 losses -> 25%)
        curator._data["skills"] = {
            "alpha_playbook": {
                "activations": 5,
                "wins": 4,
                "losses": 1,
                "partials": 0,
                "last_activated": "2026-09-08",
            },
            "decayed_playbook": {
                "activations": 4,
                "wins": 1,
                "losses": 3,
                "partials": 0,
                "last_activated": "2026-09-08",
            },
        }
        curator._save_data()

        audit = self.engine.audit_skills()
        self.assertEqual(audit["total_skills"], 2)
        excelling_names = [s["name"] for s in audit["excelling_skills"]]
        needs_review_names = [s["name"] for s in audit["needs_review_skills"]]
        self.assertIn("alpha_playbook", excelling_names)
        self.assertIn("decayed_playbook", needs_review_names)
        self.assertTrue(len(audit["recommendations"]) >= 1)

    def test_format_macro_axioms_prompt(self):
        """Test formatted prompt block for daily LLM context injection."""
        self.engine._axioms = {
            "AX_1": {
                "axiom_id": "AX_1",
                "statement": "FII cash flows dominate morning gap direction.",
                "confidence": 0.88,
                "observation_count": 5,
            }
        }
        prompt = self.engine.format_macro_axioms_prompt(max_axioms=2)
        self.assertIn("CONSOLIDATED MACRO AXIOMS", prompt)
        self.assertIn("[AX_1] (Conf: 88%, validated 5x)", prompt)

    def test_full_consolidation_cycle(self):
        """End-to-end execution of run_consolidation_cycle generates dream_report.json."""
        # Create a mock resolved episode
        log_file = self.history_dir / "memory_log.md"
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(
                "[2026-09-06 | GAP UP | BUY CE | 70% | resolved | CORRECT]\n"
                "Actual: +0.50% (GAP UP)\n"
                "Reasoning: High institutional buying.\n"
                "Reflection: Followed through well.\n"
            )

        report = self.engine.run_consolidation_cycle(dry_run=False)
        self.assertEqual(report["status"], "COMPLETED")
        self.assertTrue((self.history_dir / "dream_report.json").exists())
        self.assertTrue((self.history_dir / "macro_axioms.json").exists())

    def test_memory_log_incorporates_macro_axioms(self):
        """Verify memory_log.load_past_context() injects consolidated macro axioms."""
        self.engine._axioms = {
            "AX_MACRO": {
                "axiom_id": "AX_MACRO",
                "statement": "Do not chase gaps when VIX > 18.",
                "confidence": 0.90,
                "observation_count": 4,
            }
        }
        self.engine._save_axioms()

        mem = NiftyMemoryLog(history_dir=str(self.history_dir))
        ctx = mem.load_past_context(n=5)
        self.assertIn("AX_MACRO", ctx)
        self.assertIn("Do not chase gaps when VIX > 18.", ctx)

    def test_corrupt_macro_axioms_file_resilience(self):
        """Verify engine gracefully initializes if macro_axioms.json is non-dict or corrupt."""
        axioms_file = self.history_dir / "macro_axioms.json"
        with open(axioms_file, "w", encoding="utf-8") as f:
            f.write("[\"not\", \"a\", \"valid\", \"schema\"]")
        # Should not raise exception
        engine = DreamingEngine(history_dir=str(self.history_dir))
        self.assertEqual(len(engine._axioms), 0)

    def test_clean_float_currency_and_signs(self):
        """Test _clean_float parses formatted Indian rupee amounts, commas, and negative signs."""
        from dreaming_engine import _clean_float
        self.assertEqual(_clean_float("₹-2,150.50 Cr"), -2150.5)
        self.assertEqual(_clean_float("+1,200 Cr"), 1200.0)
        self.assertEqual(_clean_float("18.5%"), 18.5)
        self.assertEqual(_clean_float(None, default=10.0), 10.0)
        self.assertEqual(_clean_float("invalid", default=5.0), 5.0)

    def test_merge_and_store_axioms_string_types(self):
        """Test merging axioms when confidence or observation_count are strings."""
        axiom = {
            "axiom_id": "AX_STRING_TEST",
            "statement": "Rule with string numbers",
            "confidence": "0.85",
            "observation_count": "3",
            "evidence_dates": ["2026-09-05"],
        }
        self.engine.merge_and_store_axioms([axiom])
        reloaded = DreamingEngine(history_dir=str(self.history_dir))
        self.assertIn("AX_STRING_TEST", reloaded._axioms)
        self.assertEqual(reloaded._axioms["AX_STRING_TEST"]["observation_count"], 3)

    def test_format_macro_axioms_prompt_corrupt_types(self):
        """Test prompt formatting when confidence is a string or observation_count missing."""
        self.engine._axioms = {
            "AX_CORRUPT": {
                "axiom_id": "AX_CORRUPT",
                "statement": "Resilient prompt format rule.",
                "confidence": "0.75",
                "observation_count": None,
            }
        }
        prompt = self.engine.format_macro_axioms_prompt(max_axioms=1)
        self.assertIn("[AX_CORRUPT] (Conf: 75%, validated 1x)", prompt)

    def test_cognigraph_decay_with_none_weights(self):
        """Test CogniGraph decay_and_prune handles triples with None weights and stale dates."""
        cg = CogniGraph(history_dir=str(self.history_dir))
        cg._triples["CorruptEdge->fails->Test"] = {
            "subject": "CorruptEdge",
            "relation": "fails",
            "target": "Test",
            "polarity": "NEGATIVE",
            "weight": None,
            "last_seen": "invalid-date",
            "count": 1,
            "regimes": [],
            "details": [],
            "evidence_dates": [],
        }
        res = cg.decay_and_prune(threshold=0.2, max_idle_days=60.0)
        self.assertIsInstance(res, dict)
        self.assertIn("decayed", res)

    def test_auto_scheduler_includes_dreaming_job(self):
        """Verify the 20:00 IST dreaming job is registered in auto_scheduler."""
        from auto_scheduler import init_scheduler
        sched = init_scheduler()
        job = sched.get_job("run_2000_dreaming")
        self.assertIsNotNone(job)
        sched.shutdown(wait=False)

    def test_cognigraph_reinforce_from_invalid_axiom(self):
        """Test CogniGraph reinforce_from_axiom returns None on invalid inputs."""
        cg = CogniGraph(history_dir=str(self.history_dir))
        self.assertIsNone(cg.reinforce_from_axiom(None))
        self.assertIsNone(cg.reinforce_from_axiom({}))
        self.assertIsNone(cg.reinforce_from_axiom({"subject": "SubOnly"}))


if __name__ == "__main__":
    unittest.main()
