"""
test_integration_subagents_trajectories.py — Comprehensive Integration and Edge-Case Test Suite
for Dynamic Subagents and Trajectory Dataset Exporter.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from dynamic_subagents import (
    match_dynamic_subagents,
    evaluate_single_specialist,
    evaluate_dynamic_subagents,
    format_specialists_prompt,
    _generate_fallback_verdict,
)
from trajectory_exporter import TrajectoryExporter, get_trajectory_exporter
from debate_engine import run_debate
from dreaming_engine import DreamingEngine
from server import app


class TestIntegrationSubagentsAndTrajectories(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.exporter = TrajectoryExporter(history_dir=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_empty_and_corrupt_history_dir(self):
        """Verify TrajectoryExporter handles empty directories and corrupt JSON files without raising exceptions."""
        empty_dir = tempfile.mkdtemp()
        try:
            exp_empty = TrajectoryExporter(history_dir=empty_dir)
            episodes = exp_empty.collect_trajectories()
            self.assertEqual(episodes, [])

            # Exporting empty dataset should succeed and write valid empty files
            summary = exp_empty.export_all()
            self.assertEqual(summary["status"], "success")
            self.assertEqual(summary["total_exported"], 0)
            for fpath in summary["files"].values():
                self.assertTrue(os.path.exists(fpath))

            # Add a corrupt analysis JSON file
            corrupt_file = os.path.join(empty_dir, "analysis_2026-09-01_1515.json")
            with open(corrupt_file, "w", encoding="utf-8") as cf:
                cf.write('{"unclosed_json: ')

            # Also add an array JSON file
            array_file = os.path.join(empty_dir, "analysis_2026-09-02_1515.json")
            with open(array_file, "w", encoding="utf-8") as af:
                af.write('[1, 2, 3]')

            # Should not crash
            episodes_corrupt = exp_empty.collect_trajectories()
            self.assertEqual(episodes_corrupt, [])
        finally:
            shutil.rmtree(empty_dir, ignore_errors=True)

    def test_pure_memory_log_without_analysis_files(self):
        """Verify regex extraction of market signals when analysis_*.json does not exist."""
        memory_content = (
            "[2026-09-05 | GAP UP | BUY CE | 75% | resolved]\n\n"
            "REASONING:\n"
            "GIFT Nifty: +0.65%\n"
            "FII Net: ₹+2,850 Cr\n"
            "India VIX: 12.45\n"
            "PCR 1.15\n"
            "Debate Committee: FULL_BTST (UNANIMOUS)\n\n"
            "OUTCOME:\n"
            "Opened at 24200 (+0.70% gap up). Prediction was CORRECT.\n\n"
            "REFLECTION:\n"
            "Strong institutional flows drove opening follow-through.\n\n"
            "<!-- ENTRY_END -->\n\n"
        )
        with open(os.path.join(self.test_dir, "memory_log.md"), "w", encoding="utf-8") as f:
            f.write(memory_content)

        episodes = self.exporter.collect_trajectories()
        self.assertEqual(len(episodes), 1)
        ep = episodes[0]
        self.assertEqual(ep["trade_date"], "2026-09-05")
        self.assertAlmostEqual(ep["market_signals"]["gift_nifty_change_pct"], 0.65)
        self.assertAlmostEqual(ep["market_signals"]["fii_net"], 2850.0)
        self.assertAlmostEqual(ep["market_signals"]["india_vix"], 12.45)
        self.assertAlmostEqual(ep["market_signals"]["pcr"], 1.15)
        self.assertEqual(ep["btst_structure"], "FULL_BTST")

    def test_pending_trades_filter(self):
        """Verify include_pending filters or retains unresolved entries."""
        memory_content = (
            "[2026-09-01 | GAP DOWN | NO TRADE | 60% | resolved]\n\n"
            "REASONING:\nGlobal cues soft.\n\n"
            "OUTCOME:\nGap -0.30% CORRECT.\n\n"
            "REFLECTION:\nThesis held.\n\n"
            "<!-- ENTRY_END -->\n\n"
            "[2026-09-02 | GAP UP | BUY CE | 70% | pending]\n\n"
            "REASONING:\nStrong global cues.\n\n"
            "<!-- ENTRY_END -->\n\n"
        )
        with open(os.path.join(self.test_dir, "memory_log.md"), "w", encoding="utf-8") as f:
            f.write(memory_content)

        # Default excludes pending
        eps_resolved = self.exporter.collect_trajectories(include_pending=False)
        self.assertEqual(len(eps_resolved), 1)
        self.assertEqual(eps_resolved[0]["trade_date"], "2026-09-01")

        # Explicitly include pending
        eps_all = self.exporter.collect_trajectories(include_pending=True)
        self.assertEqual(len(eps_all), 2)
        dates = [e["trade_date"] for e in eps_all]
        self.assertIn("2026-09-01", dates)
        self.assertIn("2026-09-02", dates)

    def test_dynamic_subagents_priority_and_cap(self):
        """Verify dynamic subagents select top 2 specialists when all 5 catalyst conditions fire simultaneously."""
        news = [
            {"headline": "RBI MPC rate cut decision announced today"},
            {"headline": "Brent crude oil spikes 5% on Middle East tensions"},
            {"headline": "HDFC Bank Q1 quarterly results beat analyst estimates"},
        ]
        signals = {"fii_net": -5200.0, "dte": 0}
        heavyweights = {"HDFCBANK.NS": {"change_pct": 2.5}}

        matched = match_dynamic_subagents(
            market_signals=signals,
            news_items=news,
            heavyweights=heavyweights,
            max_specialists=2,
        )

        self.assertEqual(len(matched), 2)
        # Priorities: RBI (10), 0-DTE (9), Crude (8), Earnings (7), FII (6)
        # Top 2 should be RBI_Policy_Quant and Options_Greeks_ZeroDTE_Quant
        self.assertEqual(matched[0], "RBI_Policy_Quant")
        self.assertEqual(matched[1], "Options_Greeks_ZeroDTE_Quant")

    def test_dynamic_subagents_malformed_llm_and_exception_resilience(self):
        """Verify evaluate_single_specialist falls back to deterministic verdict on invalid JSON or unapproved verdict."""
        # Test malformed verdict from LLM
        with patch("requests.post") as mock_post:
            # Mock Gemini returning invalid verdict
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "candidates": [
                    {"content": {"parts": [{"text": '{"verdict": "YOLO_CALLS", "confidence": 99}'}]}}
                ]
            }
            mock_post.return_value = mock_resp

            verdict = evaluate_single_specialist(
                specialist_name="RBI_Policy_Quant",
                market_signals={},
                news_items=[],
                stage1_result={"btst_bias": "BUY CE"},
                gemini_key="mock_key",
            )
            # Should have fallen back to deterministic fallback verdict
            self.assertEqual(verdict["subagent"], "RBI_Policy_Quant")
            self.assertEqual(verdict["verdict"], "HEDGED_SPREAD")

    def test_evaluate_dynamic_subagents_partial_failure(self):
        """Verify evaluate_dynamic_subagents recovers if one specialist throws an exception."""
        with patch("dynamic_subagents.evaluate_single_specialist") as mock_eval:
            def side_effect(name, *args, **kwargs):
                if name == "RBI_Policy_Quant":
                    raise RuntimeError("Simulated thread crash")
                return {
                    "subagent": name,
                    "verdict": "HALF_QUANTITY",
                    "confidence": 75,
                    "specialist_rationale": "Crude risk.",
                }
            mock_eval.side_effect = side_effect

            results = evaluate_dynamic_subagents(
                matched_names=["RBI_Policy_Quant", "Geopolitical_Crude_Analyst"],
                market_signals={},
                news_items=[],
                stage1_result={"btst_bias": "BUY CE"},
            )

            self.assertEqual(len(results), 2)
            names = [r["subagent"] for r in results]
            self.assertIn("RBI_Policy_Quant", names)
            self.assertIn("Geopolitical_Crude_Analyst", names)

    @patch("debate_engine._gemini_call")
    def test_debate_pure_gemini_execution(self, mock_gemini):
        """Verify debate engine runs with Gemini alone when Groq key is empty."""
        mock_gemini.return_value = {
            "btst_structure": "HALF_QUANTITY",
            "trade_instruction": "Buy 1 lot ATM CE spread.",
            "debate_consensus": "MAJORITY",
            "confidence_adjustment": 0,
            "judge_rationale": "Pure Gemini synthesis successful.",
            "verdict": "HALF_QUANTITY",
            "confidence": 70,
            "rationale": "Solid risk profile.",
        }

        stage1 = {"prediction": "GAP UP", "btst_bias": "BUY CE", "confidence": 65}
        signals = {"nifty_spot": 24000, "india_vix": 12.5, "fii_net": 1200.0}

        res = run_debate(
            stage1_result=stage1,
            market_signals=signals,
            groq_key="",
            gemini_key="mock_gemini_key",
        )

        self.assertEqual(res["btst_structure"], "HALF_QUANTITY")
        self.assertIn("Gemini Judge", res["ai_agent_provider"])

    def test_dreaming_consolidation_with_trajectory_export(self):
        """Verify DreamingEngine consolidation cycle automatically exports trajectory datasets to disk."""
        # Seed test_dir with resolved memory
        memory_content = (
            "[2026-09-03 | GAP UP | BUY CE | 70% | resolved]\n\n"
            "REASONING:\n"
            "FII Net: ₹+2,100 Cr\n"
            "India VIX: 12.10\n"
            "GIFT Nifty: +0.40%\n"
            "Debate Committee: FULL_BTST (UNANIMOUS)\n\n"
            "OUTCOME:\n"
            "Actual gap was +0.48% (CORRECT).\n\n"
            "REFLECTION:\n"
            "FII flows provided decisive gap momentum.\n\n"
            "<!-- ENTRY_END -->\n\n"
        )
        with open(os.path.join(self.test_dir, "memory_log.md"), "w", encoding="utf-8") as f:
            f.write(memory_content)

        engine = DreamingEngine(history_dir=self.test_dir)
        report = engine.run_consolidation_cycle(dry_run=False)

        self.assertEqual(report["status"], "COMPLETED")
        self.assertIn("trajectory_export", report)
        self.assertEqual(report["trajectory_export"]["status"], "success")
        self.assertEqual(report["trajectory_export"]["total_exported"], 1)

        # Check files on disk
        for fname in ["trajectories_sharegpt.jsonl", "trajectories_dpo.jsonl", "trajectories_alpaca.jsonl"]:
            fpath = os.path.join(self.test_dir, fname)
            self.assertTrue(os.path.exists(fpath))
            with open(fpath, "r", encoding="utf-8") as jf:
                lines = [line.strip() for line in jf if line.strip()]
                self.assertEqual(len(lines), 1)

    def test_api_endpoints_edge_cases(self):
        """Verify Flask /api/trajectories/export edge cases, POST methods, and fallbacks."""
        # Seed test_dir
        memory_content = (
            "[2026-09-04 | GAP DOWN | BUY PE | 65% | resolved]\n\n"
            "REASONING:\n"
            "Crude oil shock.\n"
            "OUTCOME:\n"
            "Gap -0.50% CORRECT.\n\n"
            "REFLECTION:\n"
            "OMC weakness led Nifty lower.\n\n"
            "<!-- ENTRY_END -->\n\n"
        )
        with open(os.path.join(self.test_dir, "memory_log.md"), "w", encoding="utf-8") as f:
            f.write(memory_content)

        client = app.test_client()

        with patch("server.get_history_dir", return_value=self.test_dir):
            # 1. POST request with DPO format
            res_post = client.post(
                "/api/trajectories/export",
                json={"format": "dpo", "include_pending": False},
            )
            self.assertEqual(res_post.status_code, 200)
            data_post = res_post.get_json()
            self.assertEqual(data_post["format"], "dpo")
            self.assertEqual(data_post["count"], 1)

            # 2. GET request with invalid format -> falls back to 'all'
            res_invalid = client.get("/api/trajectories/export?format=nonexistent_format")
            self.assertEqual(res_invalid.status_code, 200)
            data_inv = res_invalid.get_json()
            self.assertEqual(data_inv["status"], "ok")
            self.assertIn("trajectories_sharegpt.jsonl", data_inv["data"]["files"]["sharegpt"])


if __name__ == "__main__":
    unittest.main()
