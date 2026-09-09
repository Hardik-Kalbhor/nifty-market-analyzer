"""
test_production_readiness.py — Deep Production Verification & Feature Test Suite.
Verifies all routes, edge-case handling, security/path traversal, DOM elements, and WSGI entry points.
"""

import os
import sys
import json
import unittest
from unittest.mock import patch

# Ensure repo root is on sys.path
import server
from server import app
REPO_DIR = os.path.dirname(os.path.abspath(server.__file__))

class TestProductionReadiness(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        cls.patches = [
            patch("routes.advisor.fetch_all_market_signals", return_value={"nifty_spot": 24500.0, "india_vix": 14.5, "pcr": 1.05}),
            patch("routes.advisor.fetch_fii_dii_data", return_value={"fii_net_crores": 250.0, "dii_net_crores": 150.0}),
            patch("routes.advisor.scrape_all_news", return_value=[]),
            patch("server.fetch_all_market_signals", return_value={"nifty_spot": 24500.0, "india_vix": 14.5, "pcr": 1.05}),
            patch("server.fetch_fii_dii_data", return_value={"fii_net_crores": 250.0, "dii_net_crores": 150.0}),
            patch("server.scrape_all_news", return_value=[]),
            patch("exit.evaluator.fetch_heavyweight_stocks", return_value={
                "HDFCBANK.NS": {"name": "HDFC Bank", "weight": 11.5, "price": 1650.0, "change_pct": 0.5},
                "RELIANCE.NS": {"name": "Reliance", "weight": 9.2, "price": 2900.0, "change_pct": -0.2}
            })
        ]
        for p in cls.patches:
            p.start()

    @classmethod
    def tearDownClass(cls):
        for p in cls.patches:
            p.stop()

    # ── 1. Core Endpoints & Response Codes ────────────────────────────────────
    def test_01_index_html_loads(self):
        """Test GET / returns 200 and valid HTML."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("NIFTY Market Analyzer", html)
        self.assertIn("data-tab=\"btst\"", html)
        self.assertIn("data-tab=\"intraday\"", html)
        self.assertIn("data-tab=\"exit-advisor\"", html)
        self.assertIn("data-tab=\"history\"", html)
        self.assertIn("data-tab=\"cognigraph\"", html)

    def test_02_health_endpoint(self):
        """Test GET /api/health."""
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "ok")

    def test_03_history_endpoints_and_traversal_security(self):
        """Test GET /api/history, detail, and directory traversal security."""
        # 1. List history
        res = self.client.get("/api/history")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("manual", data)
        self.assertIn("scheduled", data)

        # 2. Get detail for an existing file if present
        if data.get("manual"):
            fname = data["manual"][0]["filename"]
            res_det = self.client.get(f"/api/history/{fname}")
            self.assertEqual(res_det.status_code, 200)
            det_data = res_det.get_json()
            self.assertEqual(det_data.get("status"), "success")
            self.assertIn("prediction", det_data["data"])
            self.assertIn("scores", det_data["data"])

        # 3. Path traversal attack neutralization
        res_evil = self.client.get("/api/history/../../../../../../etc/passwd")
        self.assertEqual(res_evil.status_code, 404)
        evil_data = res_evil.get_json(silent=True)
        if evil_data:
            self.assertEqual(evil_data.get("status"), "error")

        # 4. Non-existent file
        res_nonexist = self.client.get("/api/history/fake_non_existent_file.json")
        self.assertEqual(res_nonexist.status_code, 404)

    def test_04_memory_and_cognigraph_endpoints(self):
        """Test GET /api/memory and GET /api/cognigraph with personas."""
        # Memory
        res = self.client.get("/api/memory")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "ok")

        # CogniGraph base
        res_cg = self.client.get("/api/cognigraph")
        self.assertEqual(res_cg.status_code, 200)
        cg_data = res_cg.get_json()
        self.assertEqual(cg_data.get("status"), "ok")
        self.assertIn("total_triples", cg_data["data"])
        self.assertIn("active_triples", cg_data["data"])

        # CogniGraph with persona query param
        for persona in ["CONSERVATIVE", "AGGRESSIVE", "NEUTRAL"]:
            res_p = self.client.get(f"/api/cognigraph?persona={persona}")
            self.assertEqual(res_p.status_code, 200)
            p_data = res_p.get_json()
            self.assertEqual(p_data["data"]["requested_persona"], persona)

    def test_05_institutional_radar_endpoint(self):
        """Test GET /api/institutional-radar."""
        res = self.client.get("/api/institutional-radar")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "ok")
        self.assertIn("confluence_matrix", data["data"])
        self.assertIn("brokerage_calls", data["data"])

    def test_06_dreaming_status(self):
        """Test GET /api/dreaming/status."""
        res = self.client.get("/api/dreaming/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "ok")
        self.assertIn("total_axioms", data["data"])

    def test_07_trajectories_export_formats(self):
        """Test GET /api/trajectories/export for all formats."""
        for fmt in ["sharegpt", "alpaca", "dpo", "all"]:
            res = self.client.get(f"/api/trajectories/export?format={fmt}")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data.get("status"), "ok")

    def test_08_walk_forward_simulation_cached_and_run(self):
        """Test GET and POST /api/simulation/walk-forward."""
        # Cached GET
        res = self.client.get("/api/simulation/walk-forward")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "ok")

        # 1-month fresh simulation POST
        res_post = self.client.post("/api/simulation/walk-forward", json={
            "months": 1,
            "initial_capital": 50000.0,
            "risk_profile": "CONSERVATIVE"
        })
        self.assertEqual(res_post.status_code, 200)
        post_data = res_post.get_json()
        self.assertEqual(post_data.get("status"), "ok")
        self.assertIn("equity_curve", post_data["data"])

    # ── 2. Exit Advisor Deep Scenarios & Edge Cases ────────────────────────────
    def test_09_exit_advisor_scenarios(self):
        """Test Exit Advisor across multiple position types and edge cases."""
        # Standard BUY CE in profit
        res = self.client.post("/api/exit-advisor", json={
            "position_side": "BUY_CE",
            "trade_type": "BTST",
            "strike_name": "24500 CE",
            "entry_price": 100.0,
            "current_ltp": 130.0,
            "entry_spot": 24450.0,
            "quantity": 50
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("verdict", data["data"])
        self.assertIn("action", data["data"])
        self.assertIn("trailing_sl", data["data"])
        self.assertTrue("debate" in data["data"] or data["data"].get("is_fallback") is True)

        # Standard BUY PE in loss triggering fast-path hard stop (<= -50%)
        res_loss = self.client.post("/api/exit-advisor", json={
            "position_side": "BUY_PE",
            "trade_type": "INTRADAY",
            "strike_name": "24400 PE",
            "entry_price": 100.0,
            "current_ltp": 45.0,  # -55% loss
            "entry_spot": 24500.0,
            "quantity": 50
        })
        self.assertEqual(res_loss.status_code, 200)
        data_loss = res_loss.get_json()
        self.assertEqual(data_loss.get("status"), "success")
        self.assertIn("FULL_EXIT", data_loss["data"]["verdict"])

        # Short position (SHORT_CE) with profit (> +30% decay)
        res_short = self.client.post("/api/exit-advisor", json={
            "position_side": "SHORT_CE",
            "trade_type": "INTRADAY",
            "strike_name": "24700 CE",
            "entry_price": 100.0,
            "current_ltp": 60.0,  # +40% profit for option seller
            "entry_spot": 24500.0,
            "quantity": 50
        })
        self.assertEqual(res_short.status_code, 200)
        data_short = res_short.get_json()
        self.assertEqual(data_short.get("status"), "success")

    def test_10_exit_advisor_empty_and_corrupt_payload(self):
        """Test Exit Advisor handling when missing or partial fields are passed."""
        # Empty payload
        res = self.client.post("/api/exit-advisor", json={})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("verdict", data["data"])

        # Malformed values (negative price, zero quantity, string in float fields)
        res2 = self.client.post("/api/exit-advisor", json={
            "position_side": "INVALID_SIDE",
            "entry_price": "abc",
            "current_ltp": -10.0,
            "quantity": 0
        })
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertEqual(data2.get("status"), "success")

    # ── 3. OCR Extraction Edge Cases ──────────────────────────────────────────
    def test_11_ocr_endpoints_edge_cases(self):
        """Test OCR screenshot and text parsing with edge cases."""
        # Missing image
        res = self.client.post("/api/extract-screenshot")
        self.assertEqual(res.status_code, 400)

        # Empty OCR text
        res_empty = self.client.post("/api/extract-ocr-text", json={"raw_text": ""})
        self.assertEqual(res_empty.status_code, 400)

        # Valid text parsing
        res_valid = self.client.post("/api/extract-ocr-text", json={
            "raw_text": "NIFTY 24500 CE BUY 50 QTY AVG 120.50 LTP 165.00 P&L +2225.00",
            "has_green_badge": True
        })
        self.assertEqual(res_valid.status_code, 200)
        data = res_valid.get_json()
        self.assertEqual(data.get("status"), "success")
        pos = data.get("data", {})
        self.assertEqual(pos.get("position_side"), "BUY_CE")
        self.assertIn("24500", pos.get("strike", ""))
        self.assertEqual(pos.get("quantity"), 50)

    # ── 4. Frontend DOM Verification ───────────────────────────────────────────
    def test_12_frontend_dom_selectors_consistency(self):
        """Verify that every critical DOM ID referenced in static/script.js exists in templates/index.html."""
        html_path = os.path.join(REPO_DIR, "templates", "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()

        critical_ids = [
            "prediction-card", "prediction-value", "prediction-sentiment",
            "gauge-number", "gauge-fill", "btst-badge", "info-strip",
            "btst-debate-structure-badge", "btst-debate-consensus-badge",
            "intraday-debate-structure-badge", "intraday-debate-consensus-badge",
            "exit-advisor-debate-full-section", "exit-full-debate-structure-badge",
            "cognigraph-active-regime-badge", "dreaming-last-run-badge",
            "trajectory-episodes-count-badge", "exit-contrarian-shield",
            "exit-cognigraph-banner", "exit-scale-out-card"
        ]
        for cid in critical_ids:
            self.assertIn(f'id="{cid}"', html, f"Critical DOM element '{cid}' missing in index.html!")

    # ── 5. WSGI / Production Server Entry Point ────────────────────────────────
    def test_13_wsgi_app_exposed(self):
        """Verify server.py exposes 'app' as required by Gunicorn."""
        self.assertTrue(hasattr(server, "app"))
        self.assertEqual(server.app.name, "routes.app")

if __name__ == "__main__":
    unittest.main()
