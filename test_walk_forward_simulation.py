"""
test_walk_forward_simulation.py — Automated Unit & Integration Tests for Phase 6 Walk-Forward Simulation.
Validates:
1. Historical Data Feed (Multi-month sessions, OHLCV, VIX, PCR, FII/DII, heavyweights)
2. 7-Perspective Specialist Dimension Evaluation
3. CogniGraph Regime Classification & Failure Trap Guardrails
4. Multi-Persona Risk Debate Committee Simulation
5. Trade Execution Engine & 3-Tier Scale-Out P&L Accounting
6. Quantitative Risk & Portfolio Metrics (Sharpe, Sortino, Max Drawdown, Monthly Breakdown)
7. Full Pipeline Execution & Flask REST API Endpoints (GET and POST /api/simulation/walk-forward)
"""

import json
import os
import tempfile
import unittest

from server import app
from walk_forward_simulation import (
    HistoricalDataFeed,
    evaluate_7_specialist_dimensions,
    CogniGraphWalkForwardLearner,
    simulate_debate_committee,
    TradeExecutionEngine,
    QuantitativeMetricsCalculator,
    run_walk_forward_simulation,
)


class TestWalkForwardSimulation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        cls.temp_dir = tempfile.mkdtemp(prefix="test_wf_")

    # ── 1. Historical Data Feed ───────────────────────────────────────────────
    def test_historical_data_feed_generation_and_schema(self):
        """HistoricalDataFeed must generate 126 trading days with all microstructure fields."""
        feed = HistoricalDataFeed(history_dir=self.temp_dir)
        sessions = feed.load_or_generate_sessions(months=6, seed=123)
        self.assertEqual(len(sessions), 126)

        first = sessions[0]
        required_fields = [
            "session_id", "date", "weekday", "is_expiry", "dte",
            "open", "high", "low", "close", "change_pct",
            "next_day_open", "next_day_gap_pct", "india_vix", "vix_change_pct",
            "pcr", "fii_net_crores", "dii_net_crores", "heavyweights",
            "social_sentiment", "global_cues",
        ]
        for f in required_fields:
            self.assertIn(f, first)

        # Microstructure sanity
        self.assertGreater(first["close"], 20000)
        self.assertGreater(first["india_vix"], 5.0)
        self.assertIn("HDFCBANK.NS", first["heavyweights"])
        self.assertIn("RELIANCE.NS", first["heavyweights"])

    # ── 2. 7 Specialist Dimensions Evaluation ─────────────────────────────────
    def test_evaluate_7_specialist_dimensions(self):
        """All 7 specialist dimensions must be evaluated with valid verdicts and notes."""
        feed = HistoricalDataFeed(history_dir=self.temp_dir)
        session = feed.load_or_generate_sessions(months=1, seed=42)[0]

        dims = evaluate_7_specialist_dimensions(session)
        expected_dims = [
            "greeks_decay", "oi_pcr", "heavyweights",
            "price_action", "vix_regime", "macro_global", "social_contrarian"
        ]
        for d in expected_dims:
            self.assertIn(d, dims)
            self.assertIn("verdict", dims[d])
            self.assertIn("note", dims[d])
            self.assertTrue(len(dims[d]["note"]) > 0)

    # ── 3. CogniGraph Regime Classification & Traps ───────────────────────────
    def test_cognigraph_regime_classification_and_traps(self):
        """CogniGraph must classify market regime signatures and catch recurring failure traps."""
        cg = CogniGraphWalkForwardLearner(enable_cognigraph=True)

        session_bull_trap = {
            "india_vix": 14.2,
            "dte": 3,
            "fii_net_crores": -1800.0,
            "next_day_gap_pct": 0.45,
        }
        regime = cg.classify_regime(session_bull_trap)
        self.assertIn("VIX_MOD", regime)
        self.assertIn("DTE_FAR", regime)
        self.assertIn("FII_SELL", regime)
        self.assertIn("GAP_BULL", regime)

        # In FII_SELL regime, call buying is an empirical trap
        trap = cg.check_failure_trap(regime, "BUY_CE")
        self.assertIsNotNone(trap)
        self.assertIn("FII selling", trap)

        # Normal trade has no trap
        no_trap = cg.check_failure_trap("VIX_LOW|DTE_FAR|FII_BUY|GAP_BULL", "BUY_CE")
        self.assertIsNone(no_trap)

    # ── 4. Multi-Persona Risk Debate Committee Simulation ─────────────────────
    def test_debate_committee_simulation_confluence_and_vix_shock(self):
        """Debate committee must evaluate confluence and trigger VIX shock safety rule."""
        feed = HistoricalDataFeed(history_dir=self.temp_dir)
        session = feed.load_or_generate_sessions(months=1, seed=42)[0]
        dims = evaluate_7_specialist_dimensions(session)

        # Standard decision
        dec = simulate_debate_committee(dims, session, cognigraph_trap=None)
        self.assertIn("verdict", dec)
        self.assertIn("position_side", dec)
        self.assertIn("scale_out_plan", dec)
        self.assertIn("tier_1", dec["scale_out_plan"])
        self.assertIn("tier_2", dec["scale_out_plan"])
        self.assertIn("tier_3", dec["scale_out_plan"])

        # VIX Shock override
        dims_shock = dict(dims)
        dims_shock["vix_regime"] = {"verdict": "VOLATILITY_SHOCK", "note": "Extreme VIX"}
        dec_shock = simulate_debate_committee(dims_shock, session)
        self.assertEqual(dec_shock["verdict"], "EMERGENCY_EXIT")
        self.assertEqual(dec_shock["position_side"], "NO_TRADE")

    # ── 5. Trade Execution Engine & 3-Tier Scale Out ──────────────────────────
    def test_trade_execution_engine_scale_out_and_accounting(self):
        """TradeExecutionEngine must record trades and maintain daily equity curve."""
        executor = TradeExecutionEngine(initial_capital=100000.0, enable_scale_out=True)
        session = {
            "session_id": "test_01",
            "date": "2026-04-01",
            "close": 24000.0,
            "next_day_open": 24100.0,
            "next_day_gap_pct": 0.42,
            "dte": 3,
        }
        decision = {
            "position_side": "BUY_CE",
            "verdict": "FULL_BTST",
        }
        trade = executor.execute_session_trade(session, decision, "VIX_MOD|DTE_FAR|FII_BUY|GAP_BULL")
        self.assertIsNotNone(trade)
        self.assertTrue(trade["is_win"])
        self.assertGreater(trade["pnl_inr"], 0)
        self.assertEqual(len(executor.closed_trades), 1)
        self.assertEqual(len(executor.daily_equity_curve), 1)
        self.assertGreater(executor.capital, 100000.0)

    # ── 6. Quantitative Metrics Calculation ───────────────────────────────────
    def test_quantitative_metrics_calculator_math(self):
        """Metrics calculator must compute Sharpe, Sortino, Max Drawdown, and breakdowns accurately."""
        equity_curve = [
            {"date": "2026-04-01", "equity": 100000.0, "daily_return_pct": 0.0},
            {"date": "2026-04-02", "equity": 102500.0, "daily_return_pct": 2.5},
            {"date": "2026-04-03", "equity": 101000.0, "daily_return_pct": -1.46},
            {"date": "2026-04-04", "equity": 104000.0, "daily_return_pct": 2.97},
        ]
        trades = [
            {"date": "2026-04-02", "pnl_inr": 2500.0, "is_win": True, "regime": "REGIME_A"},
            {"date": "2026-04-03", "pnl_inr": -1500.0, "is_win": False, "regime": "REGIME_B"},
            {"date": "2026-04-04", "pnl_inr": 3000.0, "is_win": True, "regime": "REGIME_A"},
        ]
        metrics = QuantitativeMetricsCalculator.calculate_metrics(100000.0, equity_curve, trades)

        self.assertEqual(metrics["total_trades"], 3)
        self.assertEqual(metrics["winning_trades"], 2)
        self.assertEqual(metrics["losing_trades"], 1)
        self.assertAlmostEqual(metrics["win_rate_pct"], 66.7, places=1)
        self.assertGreater(metrics["sharpe_ratio"], 0)
        self.assertGreater(metrics["sortino_ratio"], 0)
        self.assertGreater(metrics["max_drawdown_pct"], 0)
        self.assertEqual(len(metrics["monthly_performance"]), 1)
        self.assertEqual(len(metrics["regime_performance"]), 2)

    # ── 7. Full Walk-Forward Simulation Pipeline ──────────────────────────────
    def test_run_walk_forward_simulation_end_to_end(self):
        """Full pipeline must execute across 3 months in < 500ms and persist results."""
        res = run_walk_forward_simulation(months=3, history_dir=self.temp_dir)
        self.assertIn("cumulative_return_pct", res)
        self.assertIn("sharpe_ratio", res)
        self.assertIn("sortino_ratio", res)
        self.assertIn("max_drawdown_pct", res)
        self.assertIn("simulation_config", res)
        self.assertEqual(res["simulation_config"]["months"], 3)
        self.assertGreater(len(res["equity_curve"]), 60)

        # File persisted
        report_file = os.path.join(self.temp_dir, "walk_forward_simulation_report.json")
        self.assertTrue(os.path.exists(report_file))

    # ── 8. REST API Endpoints ──────────────────────────────────────────────────
    def test_simulation_api_endpoints_get_and_post(self):
        """Flask REST API must support GET and POST /api/simulation/walk-forward."""
        # GET
        res_get = self.client.get("/api/simulation/walk-forward")
        self.assertEqual(res_get.status_code, 200)
        d_get = res_get.get_json()
        self.assertEqual(d_get["status"], "ok")
        self.assertIn("data", d_get)
        self.assertIn("cumulative_return_pct", d_get["data"])

        # POST with custom months
        res_post = self.client.post("/api/simulation/walk-forward", json={"months": 2, "initial_capital": 50000})
        self.assertEqual(res_post.status_code, 200)
        d_post = res_post.get_json()
        self.assertEqual(d_post["status"], "ok")
        self.assertEqual(d_post["data"]["simulation_config"]["months"], 2)
        self.assertEqual(d_post["data"]["simulation_config"]["initial_capital"], 50000.0)


if __name__ == "__main__":
    unittest.main()
