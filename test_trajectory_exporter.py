"""
test_trajectory_exporter.py — Unit Tests for Trajectory Dataset Exporter.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from trajectory_exporter import TrajectoryExporter, get_trajectory_exporter
from server import app


class TestTrajectoryExporter(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.exporter = TrajectoryExporter(history_dir=self.test_dir)

        # Create a sample memory_log.md in test_dir
        self.sample_memory = (
            "[2026-09-01 | GAP DOWN | NO TRADE | 68% | resolved]\n\n"
            "REASONING:\n"
            "Global equity weakness and FII selling suggest caution.\n"
            "GIFT Nifty: -0.21%\n"
            "FII Net: ₹-3,397 Cr\n"
            "India VIX: 11.71\n"
            "Debate Committee: STRICT_NO_TRADE (MAJORITY)\n\n"
            "OUTCOME:\n"
            "Market opened at 24000 (-0.45% gap down). Prediction was CORRECT.\n\n"
            "REFLECTION:\n"
            "The directional bias was correct. Global cues and FII selling dominated.\n\n"
            "<!-- ENTRY_END -->\n\n"
            "[2026-09-02 | GAP UP | BUY CE | 72% | resolved]\n\n"
            "REASONING:\n"
            "Strong US tech rally and positive GIFT Nifty.\n"
            "GIFT Nifty: +0.45%\n"
            "FII Net: ₹+1,200 Cr\n"
            "India VIX: 12.30\n"
            "Debate Committee: HALF_QUANTITY (UNANIMOUS)\n\n"
            "OUTCOME:\n"
            "Market opened at 24150 (+0.52% gap up). Prediction was CORRECT.\n\n"
            "REFLECTION:\n"
            "Momentum follow-through held firmly. Half-sizing protected against theta decay.\n\n"
            "<!-- ENTRY_END -->\n\n"
        )
        with open(os.path.join(self.test_dir, "memory_log.md"), "w", encoding="utf-8") as f:
            f.write(self.sample_memory)

        # Create a sample analysis_2026-09-01_1515.json
        self.sample_analysis_1 = {
            "prediction": "GAP DOWN",
            "confidence": 68,
            "btst_bias": "NO TRADE",
            "btst_structure": "STRICT_NO_TRADE",
            "debate_consensus": "MAJORITY",
            "trade_instruction": "Stand aside and avoid taking overnight directional risk.",
            "market_signals": {
                "gift_nifty_change_pct": -0.21,
                "india_vix": 11.71,
                "fii_net": -3397.0,
                "pcr": 0.66,
            },
            "bullish_factors": ["Reliance +2.00%"],
            "bearish_factors": ["FII net outflow -₹3397 Cr", "GIFT Nifty -0.21%"],
            "debate": {
                "aggressive": {"verdict": "HALF_QUANTITY", "confidence": 55, "rationale": "Slight momentum."},
                "conservative": {"verdict": "STRICT_NO_TRADE", "confidence": 80, "rationale": "High theta risk."},
                "neutral": {"verdict": "STRICT_NO_TRADE", "confidence": 75, "rationale": "Risk unfavorable."},
            },
        }
        with open(os.path.join(self.test_dir, "analysis_2026-09-01_1515.json"), "w", encoding="utf-8") as f:
            json.dump(self.sample_analysis_1, f)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_collect_trajectories(self):
        """Verify episodes are collected and joined with analysis files."""
        episodes = self.exporter.collect_trajectories()
        self.assertEqual(len(episodes), 2)
        dates = [ep["trade_date"] for ep in episodes]
        self.assertIn("2026-09-01", dates)
        self.assertIn("2026-09-02", dates)

        ep1 = next(ep for ep in episodes if ep["trade_date"] == "2026-09-01")
        self.assertEqual(ep1["btst_structure"], "STRICT_NO_TRADE")
        self.assertEqual(ep1["debate_consensus"], "MAJORITY")
        self.assertAlmostEqual(ep1["actual_gap_pct"], -0.45)
        self.assertEqual(ep1["market_signals"]["gift_nifty_change_pct"], -0.21)

    def test_export_sharegpt_format(self):
        """Verify ShareGPT multi-turn SFT conversation structure."""
        sharegpt_data = self.exporter.export_sharegpt()
        self.assertEqual(len(sharegpt_data), 2)

        item = sharegpt_data[0]
        self.assertIn("id", item)
        self.assertIn("conversations", item)
        convs = item["conversations"]
        self.assertGreaterEqual(len(convs), 3)

        roles = [c["from"] for c in convs]
        self.assertEqual(roles[0], "system")
        self.assertEqual(roles[1], "human")
        self.assertEqual(roles[2], "gpt")

        # Check post-market reflection turn
        if len(convs) >= 5:
            self.assertEqual(roles[3], "human")
            self.assertEqual(roles[4], "gpt")
            self.assertIn("Post-Mortem Reflection", convs[4]["value"])

    def test_export_dpo_format(self):
        """Verify DPO pairwise preference schema (prompt, chosen, rejected)."""
        dpo_data = self.exporter.export_dpo()
        self.assertEqual(len(dpo_data), 2)

        item = dpo_data[0]
        self.assertIn("id", item)
        self.assertIn("prompt", item)
        self.assertIn("chosen", item)
        self.assertIn("rejected", item)
        self.assertIn("metadata", item)

        self.assertIn("Calibrated Verdict", item["chosen"])
        self.assertIn("FULL_BTST", item["rejected"])  # Overaggressive rejected counter-thesis
        self.assertIn("trade_date", item["metadata"])

    def test_export_alpaca_format(self):
        """Verify Alpaca single-turn instruction format."""
        alpaca_data = self.exporter.export_alpaca()
        self.assertEqual(len(alpaca_data), 2)

        item = alpaca_data[0]
        self.assertIn("instruction", item)
        self.assertIn("input", item)
        self.assertIn("output", item)
        self.assertIn("metadata", item)
        self.assertTrue(len(item["input"]) > 20)
        self.assertTrue(len(item["output"]) > 20)

    def test_export_all_atomic_jsonl(self):
        """Verify export_all writes valid JSONL files to disk atomically."""
        summary = self.exporter.export_all()
        self.assertEqual(summary["status"], "success")
        self.assertEqual(summary["total_exported"], 2)

        files = summary["files"]
        for key in ["sharegpt", "dpo", "alpaca"]:
            self.assertIn(key, files)
            path = Path(files[key])
            self.assertTrue(path.exists())
            self.assertGreater(path.stat().st_size, 0)

            # Check lines are valid JSON
            with open(path, "r", encoding="utf-8") as f:
                lines = [json.loads(line) for line in f if line.strip()]
                self.assertEqual(len(lines), 2)

    def test_server_api_trajectories_export(self):
        """Verify Flask /api/trajectories/export endpoint."""
        client = app.test_client()

        # Patch get_history_dir in server.py to use test_dir
        with patch("server.get_history_dir", return_value=self.test_dir):
            # 1. ShareGPT format
            res = client.get("/api/trajectories/export?format=sharegpt")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["format"], "sharegpt")
            self.assertEqual(data["count"], 2)

            # 2. DPO format
            res_dpo = client.get("/api/trajectories/export?format=dpo")
            self.assertEqual(res_dpo.status_code, 200)
            data_dpo = res_dpo.get_json()
            self.assertEqual(data_dpo["format"], "dpo")
            self.assertEqual(data_dpo["count"], 2)

            # 3. Alpaca format
            res_alp = client.get("/api/trajectories/export?format=alpaca")
            self.assertEqual(res_alp.status_code, 200)
            data_alp = res_alp.get_json()
            self.assertEqual(data_alp["format"], "alpaca")
            self.assertEqual(data_alp["count"], 2)

            # 4. All (JSONL file generation)
            res_all = client.get("/api/trajectories/export?format=all")
            self.assertEqual(res_all.status_code, 200)
            data_all = res_all.get_json()
            self.assertEqual(data_all["status"], "ok")
            self.assertEqual(data_all["data"]["total_exported"], 2)


if __name__ == "__main__":
    unittest.main()
