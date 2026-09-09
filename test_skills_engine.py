"""
test_skills_engine.py — Unit Tests for Procedural Skills Engine & Curator.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from skills_engine import SkillsEngine, SkillCurator, _parse_frontmatter


class TestSkillsEngine(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.skills_dir = Path(self.test_dir) / "skills"
        self.history_dir = Path(self.test_dir) / "history"
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)

        # Create a sample test skill
        sample_skill = (
            "---\n"
            "name: test_expiry_playbook\n"
            "description: Test rules for expiry day\n"
            "triggers:\n"
            "  - dte_near_or_zero\n"
            "  - fo_expiry\n"
            "priority: 95\n"
            "---\n\n"
            "# Test Expiry Directives\n"
            "1. Pinning check.\n"
            "2. Mandate hedged spread.\n"
        )
        sample_dir = self.skills_dir / "test_expiry"
        sample_dir.mkdir()
        (sample_dir / "SKILL.md").write_text(sample_skill, encoding="utf-8")

        self.engine = SkillsEngine(skills_dir=str(self.skills_dir), history_dir=str(self.history_dir))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_parse_frontmatter(self):
        """Verify frontmatter parser correctly extracts metadata and body."""
        text = (
            "---\n"
            "name: sample\n"
            "priority: 80\n"
            "triggers:\n"
            "  - cue_one\n"
            "  - cue_two\n"
            "---\n\n"
            "Content body line 1\n"
            "Content body line 2"
        )
        meta, body = _parse_frontmatter(text)
        self.assertEqual(meta.get("name"), "sample")
        self.assertEqual(meta.get("priority"), 80)
        self.assertEqual(meta.get("triggers"), ["cue_one", "cue_two"])
        self.assertIn("Content body line 1", body)

    def test_reload_skills(self):
        """Verify engine discovers and loads skills from directory."""
        count = self.engine.reload_skills()
        self.assertEqual(count, 1)
        self.assertIn("test_expiry_playbook", self.engine._skills_cache)

    def test_dte_expiry_trigger_match(self):
        """Verify DTE <= 1 triggers the expiry playbook."""
        matched = self.engine.match_skills(signals={"dte": 1})
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["name"], "test_expiry_playbook")

        # DTE > 1 should not trigger
        matched_far = self.engine.match_skills(signals={"dte": 4})
        self.assertEqual(len(matched_far), 0)

    def test_format_skills_prompt(self):
        """Verify matched skills format into an injection-ready prompt block."""
        matched = self.engine.match_skills(signals={"dte": 0})
        prompt_block = self.engine.format_skills_prompt(matched)
        self.assertIn("ACTIVE PROCEDURAL TRADING PLAYBOOKS", prompt_block)
        self.assertIn("test_expiry_playbook", prompt_block)
        self.assertIn("Mandate hedged spread", prompt_block)

    def test_curator_lifecycle(self):
        """Verify SkillCurator tracks activations, outcomes, win rates, and health."""
        curator = self.engine.curator

        # 1. Record activation for a trade
        curator.record_activations("2026-09-01", ["test_expiry_playbook"])
        curator.record_activations("2026-09-02", ["test_expiry_playbook"])
        curator.record_activations("2026-09-03", ["test_expiry_playbook"])

        # 2. Record outcomes
        curator.record_outcome("2026-09-01", "✅ CORRECT (+0.45%)")
        curator.record_outcome("2026-09-02", "✅ CORRECT (+0.60%)")
        curator.record_outcome("2026-09-03", "❌ WRONG (-0.30%)")

        report = curator.get_report()
        self.assertIn("test_expiry_playbook", report)
        skill_stat = report["test_expiry_playbook"]

        self.assertEqual(skill_stat["activations"], 3)
        self.assertEqual(skill_stat["wins"], 2)
        self.assertEqual(skill_stat["losses"], 1)
        self.assertAlmostEqual(skill_stat["win_pct"], 66.7, places=1)
        self.assertEqual(skill_stat["health_status"], "HEALTHY")

    def test_built_in_playbooks(self):
        """Verify the 4 official built-in playbooks load and match their respective conditions."""
        real_skills_dir = Path(__file__).parent / "skills"
        real_engine = SkillsEngine(skills_dir=str(real_skills_dir), history_dir=str(self.history_dir))

        self.assertGreaterEqual(len(real_engine._skills_cache), 4)
        self.assertIn("expiry_day_pinning", real_engine._skills_cache)
        self.assertIn("rbi_mpc_iv_crush", real_engine._skills_cache)
        self.assertIn("heavyweight_divergence", real_engine._skills_cache)
        self.assertIn("fii_dii_divergence", real_engine._skills_cache)

        # 1. Test RBI trigger
        rbi_news = [{"headline": "RBI MPC begins meeting, repo rate decision awaited"}]
        rbi_matched = real_engine.match_skills(news_items=rbi_news)
        self.assertTrue(any(s["name"] == "rbi_mpc_iv_crush" for s in rbi_matched))

        # 2. Test Heavyweight divergence trigger
        hw_dict = {
            "HDFCBANK": {"change_pct": -0.65},
            "RELIANCE": {"change_pct": -0.55},
        }
        stage1_bullish = {"prediction": "GAP UP", "btst_bias": "BUY CE"}
        hw_matched = real_engine.match_skills(heavyweights=hw_dict, stage1_result=stage1_bullish)
        self.assertTrue(any(s["name"] == "heavyweight_divergence" for s in hw_matched))

        # 3. Test FII/DII divergence trigger
        fii_dii_dict = {
            "fii_net_crores": -2800.0,
            "dii_net_crores": 3100.0,
        }
        inst_matched = real_engine.match_skills(fii_dii=fii_dii_dict)
        self.assertTrue(any(s["name"] == "fii_dii_divergence" for s in inst_matched))

    def test_frontmatter_bom_and_booleans(self):
        """Verify frontmatter parser handles UTF-8 BOM, booleans, and CRLF line endings."""
        text_with_bom = "\ufeff---\r\nname: bom_test\r\nenabled: true\r\npriority: 70\r\n---\r\nBody text"
        meta, body = _parse_frontmatter(text_with_bom)
        self.assertEqual(meta["name"], "bom_test")
        self.assertEqual(meta["enabled"], True)
        self.assertEqual(meta["priority"], 70)
        self.assertEqual(body, "Body text")

    def test_clean_numeric_and_defensive_types(self):
        """Verify _clean_numeric handles currency symbols, percentage characters, and malformed inputs."""
        from skills_engine import _clean_numeric
        self.assertEqual(_clean_numeric("₹-2,150 Cr"), -2150.0)
        self.assertEqual(_clean_numeric("+0.45%"), 0.45)
        self.assertEqual(_clean_numeric("-0.60%"), -0.60)
        self.assertEqual(_clean_numeric(None), 0.0)
        self.assertEqual(_clean_numeric("N/A"), 0.0)
        self.assertEqual(_clean_numeric(123.45), 123.45)

    def test_heavyweights_none_and_corrupt_resilience(self):
        """Verify match_skills does not crash if heavyweights dict has None values or malformed strings."""
        real_skills_dir = Path(__file__).parent / "skills"
        real_engine = SkillsEngine(skills_dir=str(real_skills_dir), history_dir=str(self.history_dir))

        # Test with None entry, missing change_pct, and string format
        corrupt_hw = {
            "HDFCBANK": None,
            "RELIANCE": {"change_pct": "corrupt"},
        }
        matched = real_engine.match_skills(
            heavyweights=corrupt_hw,
            stage1_result={"prediction": "GAP UP", "btst_bias": "BUY CE"}
        )
        self.assertIsInstance(matched, list)

    def test_fii_dii_formatted_strings(self):
        """Verify match_skills detects institutional absorption when FII/DII are currency-formatted strings."""
        real_skills_dir = Path(__file__).parent / "skills"
        real_engine = SkillsEngine(skills_dir=str(real_skills_dir), history_dir=str(self.history_dir))

        fii_dii_strings = {
            "fii_net_crores": "₹-2,450 Cr",
            "dii_net_crores": "₹+2,800 Cr",
        }
        matched = real_engine.match_skills(fii_dii=fii_dii_strings)
        self.assertTrue(any(s["name"] == "fii_dii_divergence" for s in matched))

    def test_news_items_malformed_resilience(self):
        """Verify match_skills handles news lists with None or non-dict items without raising exceptions."""
        real_skills_dir = Path(__file__).parent / "skills"
        real_engine = SkillsEngine(skills_dir=str(real_skills_dir), history_dir=str(self.history_dir))

        malformed_news = [
            None,
            "RBI monetary policy announcement expected tomorrow",
            {"headline": None},
            {"other_key": "some value"},
        ]
        matched = real_engine.match_skills(news_items=malformed_news)
        self.assertTrue(any(s["name"] == "rbi_mpc_iv_crush" for s in matched))

    def test_curator_concurrent_atomic_writes(self):
        """Verify SkillCurator handles concurrent writes from multiple threads without file corruption."""
        import concurrent.futures

        curator = self.engine.curator

        def worker(i: int):
            date_str = f"2026-03-{i:02d}"
            curator.record_activations(date_str, ["test_expiry_playbook"])
            curator.record_outcome(date_str, "✅ CORRECT" if i % 2 == 0 else "❌ WRONG")
            return curator.get_report()

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(worker, i) for i in range(1, 11)]
            results = [f.result(timeout=10) for f in futures]

        self.assertEqual(len(results), 10)
        final_report = curator.get_report()
        self.assertIn("test_expiry_playbook", final_report)
        self.assertEqual(final_report["test_expiry_playbook"]["activations"], 10)


if __name__ == "__main__":
    unittest.main()

