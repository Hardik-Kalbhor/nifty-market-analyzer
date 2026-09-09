"""
test_phase3_ui_and_apis.py — Phase 3 UI & Cognitive Operator Console Integration Suite
Validates templates/index.html, static/style.css, static/script.js, and Flask APIs.
"""

import os
import unittest
from server import app


class TestPhase3UIAndAPIs(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        cls.repo_dir = os.path.dirname(__file__)

    # ── 1. HTML Template Verification ──────────────────────────────────────────
    def test_index_html_contains_phase3_elements(self):
        """index.html must include new tab, scale-out cards, contrarian shield, and cognigraph console."""
        html_path = os.path.join(self.repo_dir, "templates", "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()

        # Tab navigation
        self.assertIn('data-tab="cognigraph"', html)
        self.assertIn('id="tab-cognigraph"', html)

        # Tab content container
        self.assertIn('id="content-cognigraph"', html)
        self.assertIn('id="cognigraph-active-regime-badge"', html)
        self.assertIn('id="cognigraph-persona-pills"', html)
        self.assertIn('id="dreaming-last-run-badge"', html)
        self.assertIn('id="dreaming-metric-score"', html)
        self.assertIn('id="trajectory-episodes-count-badge"', html)

        # Exit Advisor visual upgrades
        self.assertIn('id="exit-contrarian-shield"', html)
        self.assertIn('id="exit-cognigraph-banner"', html)
        self.assertIn('id="exit-scale-out-card"', html)
        self.assertIn('id="tier-1-row"', html)
        self.assertIn('id="tier-2-row"', html)
        self.assertIn('id="tier-3-row"', html)
        self.assertIn('id="exit-full-scale-out-box"', html)
        self.assertIn("7-Perspective Specialist Analysis", html)

        # Cache busting version
        self.assertTrue("?v=29.0" in html or "?v=30.0" in html)

    # ── 2. CSS Styles Verification ─────────────────────────────────────────────
    def test_style_css_contains_phase3_styles(self):
        """style.css must contain styling for persona pills, traps, macro axioms, and scale-out rows."""
        css_path = os.path.join(self.repo_dir, "static", "style.css")
        with open(css_path, "r", encoding="utf-8") as f:
            css = f.read()

        self.assertIn(".persona-pill-btn", css)
        self.assertIn(".persona-pill-btn.active", css)
        self.assertIn(".trap-card-item", css)
        self.assertIn(".macro-axiom-card", css)
        self.assertIn(".scale-out-tier-row", css)

    # ── 3. JavaScript Implementation Verification ──────────────────────────────
    def test_script_js_contains_phase3_logic(self):
        """script.js must contain social_contrarian in _DIMENSION_META and CogniGraph console loaders."""
        js_path = os.path.join(self.repo_dir, "static", "script.js")
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()

        self.assertIn("social_contrarian:", js)
        self.assertIn("loadCogniGraphData", js)
        self.assertIn("loadDreamingData", js)
        self.assertIn("loadTrajectoryStats", js)
        self.assertIn("initCogniGraphTabListeners", js)
        self.assertIn("exit-scale-out-card", js)
        self.assertIn("exit-contrarian-shield", js)
        self.assertIn("exit-cognigraph-banner", js)
        self.assertIn("exit-full-scale-out-box", js)

    # ── 4. Cognitive API Endpoints Verification ────────────────────────────────
    def test_cognigraph_api_endpoints(self):
        """GET /api/cognigraph must return valid metrics and persona memory projections."""
        r1 = self.client.get("/api/cognigraph")
        self.assertEqual(r1.status_code, 200)
        d1 = r1.get_json()
        self.assertEqual(d1["status"], "ok")
        self.assertIn("total_triples", d1["data"])

        # Test Conservative Persona
        r2 = self.client.get("/api/cognigraph?persona=CONSERVATIVE")
        self.assertEqual(r2.status_code, 200)
        d2 = r2.get_json()
        self.assertEqual(d2["data"]["requested_persona"], "CONSERVATIVE")

        # Test Aggressive Persona
        r3 = self.client.get("/api/cognigraph?persona=AGGRESSIVE")
        self.assertEqual(r3.status_code, 200)
        d3 = r3.get_json()
        self.assertEqual(d3["data"]["requested_persona"], "AGGRESSIVE")

    def test_dreaming_api_endpoints(self):
        """GET /api/dreaming/status and POST /api/dreaming/run must return status 200."""
        r_status = self.client.get("/api/dreaming/status")
        self.assertEqual(r_status.status_code, 200)
        d_status = r_status.get_json()
        self.assertEqual(d_status["status"], "ok")
        self.assertIn("macro_axioms", d_status["data"])

        r_run = self.client.post("/api/dreaming/run")
        self.assertEqual(r_run.status_code, 200)
        d_run = r_run.get_json()
        self.assertEqual(d_run["status"], "success")

    def test_trajectory_exporter_api_endpoints(self):
        """GET /api/trajectories/export formats (sharegpt, alpaca, dpo) must return status 200."""
        for fmt in ["sharegpt", "alpaca", "dpo"]:
            r = self.client.get(f"/api/trajectories/export?format={fmt}")
            self.assertEqual(r.status_code, 200)
            d = r.get_json()
            self.assertEqual(d["status"], "ok")
            self.assertEqual(d["format"], fmt)
            self.assertIn("count", d)


if __name__ == "__main__":
    unittest.main()
