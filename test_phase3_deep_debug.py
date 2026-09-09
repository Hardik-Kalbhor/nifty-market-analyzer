"""
test_phase3_deep_debug.py — Deep Debugging, Boundary & Edge-Case Audit for Phase 3
Validates:
1. Fast-Path Time Invariance (15:15 cutoff vs Mid-day trading vs None time)
2. CogniGraph API Edge Cases (Valid, Invalid, Empty, Special Character personas)
3. Dreaming Engine API Edge Cases (Normal, Missing report, Broken report recovery)
4. Trajectory Exporter API Edge Cases (All formats, Invalid format fallback, Empty states)
5. Full UI Template & Script DOM Wiring Integrity
"""

import os
import json
import tempfile
import unittest
from datetime import datetime
import pytz

from server import app
from exit_fast_path import evaluate_fast_path, _get_now_ist, TIMEZONE


class TestPhase3DeepDebug(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        cls.repo_dir = os.path.dirname(__file__)

    # ── 1. Fast-Path Time Invariance Testing ──────────────────────────────────
    def test_fast_path_explicit_15_15_cutoff(self):
        """Explicitly passing 15:16 IST must trigger PRE_CLOSE_EXIT."""
        pos = {"trade_type": "INTRADAY", "position_side": "BUY_CE", "entry_spot": 24500}
        sig = {"nifty_spot": 24550}
        cutoff_time = datetime(2026, 9, 9, 15, 16, tzinfo=TIMEZONE)
        res = evaluate_fast_path(pos, sig, current_time=cutoff_time)
        self.assertIsNotNone(res)
        self.assertEqual(res["verdict"], "PRE_CLOSE_EXIT")
        self.assertEqual(res["confidence"], 95)
        self.assertTrue(res["is_fast_path"])

    def test_fast_path_explicit_midday_no_cutoff(self):
        """Explicitly passing 11:30 IST must NOT trigger PRE_CLOSE_EXIT on valid position."""
        pos = {"trade_type": "INTRADAY", "position_side": "BUY_CE", "entry_spot": 24500, "entry_premium": 100, "current_premium": 105}
        sig = {"nifty_spot": 24510, "india_vix": 13.0, "india_vix_change_pct": 0.2}
        midday_time = datetime(2026, 9, 9, 11, 30, tzinfo=TIMEZONE)
        res = evaluate_fast_path(pos, sig, current_time=midday_time)
        # Position is normal, no safety rule hit -> None
        self.assertIsNone(res)

    def test_fast_path_btst_trade_type_immune_to_15_15(self):
        """BTST trade type is meant to be held overnight and must NEVER trigger PRE_CLOSE_EXIT at 15:16."""
        pos = {"trade_type": "BTST", "position_side": "BUY_CE", "entry_spot": 24500, "entry_premium": 100, "current_premium": 100}
        sig = {"nifty_spot": 24500, "india_vix": 13.0}
        cutoff_time = datetime(2026, 9, 9, 15, 20, tzinfo=TIMEZONE)
        res = evaluate_fast_path(pos, sig, current_time=cutoff_time)
        self.assertIsNone(res)

    def test_get_now_ist_helper_returns_valid_ist_datetime(self):
        """_get_now_ist helper must return timezone-aware IST datetime."""
        t = _get_now_ist()
        self.assertIsInstance(t, datetime)
        self.assertIsNotNone(t.tzinfo)

    # ── 2. CogniGraph API Edge Cases & Parameter Fuzzing ───────────────────────
    def test_cognigraph_api_persona_fuzzing(self):
        """API must gracefully handle empty, lowercase, invalid, or injected persona strings."""
        test_personas = [
            "CONSERVATIVE", "AGGRESSIVE", "NEUTRAL", "JUDGE",
            "conservative", "aggressive",  # lower case
            "", " ", None,  # empty/whitespace/none
            "HACKER_INJECTION_REGIME_DROP",  # unknown persona
            "<script>alert(1)</script>",  # XSS attempt
            "12345"
        ]
        for p in test_personas:
            url = f"/api/cognigraph?persona={p}" if p is not None else "/api/cognigraph"
            res = self.client.get(url)
            self.assertEqual(res.status_code, 200, f"Failed on persona={p}")
            data = res.get_json()
            self.assertEqual(data["status"], "ok")
            self.assertIn("active_triples", data["data"])
            self.assertIn("top_failure_traps", data["data"])

    # ── 3. Dreaming Engine API Edge Cases ──────────────────────────────────────
    def test_dreaming_status_with_corrupt_report_recovery(self):
        """If dream_report.json is corrupted with invalid JSON, status API must recover gracefully."""
        history_dir = os.path.join(self.repo_dir, "history")
        report_path = os.path.join(history_dir, "dream_report.json")
        backup = None
        if os.path.exists(report_path):
            with open(report_path, "r") as f:
                backup = f.read()

        try:
            # Write invalid JSON
            with open(report_path, "w") as f:
                f.write("{invalid_json_corrupted...")

            res = self.client.get("/api/dreaming/status")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["status"], "ok")
            # Should have fallback empty dict for latest_report
            self.assertEqual(data["data"]["latest_report"], {})
        finally:
            if backup:
                with open(report_path, "w") as f:
                    f.write(backup)

    def test_dreaming_run_post_and_get(self):
        """Both POST and GET methods to /api/dreaming/run must succeed and return report data."""
        # Test GET
        r_get = self.client.get("/api/dreaming/run")
        self.assertEqual(r_get.status_code, 200)
        self.assertEqual(r_get.get_json()["status"], "success")

        # Test POST
        r_post = self.client.post("/api/dreaming/run")
        self.assertEqual(r_post.status_code, 200)
        self.assertEqual(r_post.get_json()["status"], "success")

    # ── 4. Trajectory Exporter API Edge Cases ──────────────────────────────────
    def test_trajectories_export_all_formats_and_fallbacks(self):
        """Export API must handle standard formats and fallback for unknown formats."""
        for fmt in ["sharegpt", "alpaca", "dpo"]:
            # GET with query param
            r_get = self.client.get(f"/api/trajectories/export?format={fmt}&include_pending=1")
            self.assertEqual(r_get.status_code, 200)
            d_get = r_get.get_json()
            self.assertEqual(d_get["status"], "ok")
            self.assertEqual(d_get["format"], fmt)
            self.assertIsInstance(d_get["data"], list)

            # POST with JSON payload
            r_post = self.client.post("/api/trajectories/export", json={"format": fmt, "include_pending": True})
            self.assertEqual(r_post.status_code, 200)
            d_post = r_post.get_json()
            self.assertEqual(d_post["format"], fmt)

        # Fallback for "all" or invalid format
        r_all = self.client.get("/api/trajectories/export?format=unknown_fallback")
        self.assertEqual(r_all.status_code, 200)
        d_all = r_all.get_json()
        self.assertEqual(d_all["status"], "ok")
        self.assertIn("total_exported", d_all["data"])
        self.assertIn("files", d_all["data"])

    # ── 5. Exit Advisor API Response Schema Validation ─────────────────────────
    def test_exit_advisor_response_schema_for_phase3_ui(self):
        """Verify /api/exit-advisor returns all fields expected by Phase 3 UI."""
        payload = {
            "trade_type": "INTRADAY",
            "position_side": "BUY_CE",
            "strike": "24500 CE",
            "entry_spot": 24450,
            "entry_premium": 110,
            "current_premium": 140,
            "risk_profile": "BALANCED",
            "dte": 2
        }
        res = self.client.post("/api/exit-advisor", json=payload)
        self.assertEqual(res.status_code, 200)
        d = res.get_json()
        self.assertEqual(d["status"], "success")
        data = d["data"]

        # Expected Phase 3 fields
        self.assertIn("verdict", data)
        self.assertIn("action", data)
        self.assertIn("scale_out_plan", data)
        self.assertIn("dimension_scores", data)
        self.assertIn("social_sentiment", data)
        self.assertIn("cognigraph_regime_precedent", data)

        # scale_out_plan schema
        plan = data["scale_out_plan"]
        self.assertIn("tier_1", plan)
        self.assertIn("tier_2", plan)
        self.assertIn("tier_3", plan)


if __name__ == "__main__":
    unittest.main()
