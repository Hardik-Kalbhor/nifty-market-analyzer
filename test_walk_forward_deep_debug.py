"""
test_walk_forward_deep_debug.py — Deep Debugging, Boundary, and Stress Tests for Phase 6.

Validates:
1. Zero Trades & Flat Return Anomaly (Sortino and Sharpe must be 0.0, not -15.87)
2. Capital Depletion & Margin Call Guard (< ₹15,000 capital halts entries, no ZeroDivisionError)
3. Malformed, Null & Corrupt Session Dictionary Fuzzing
4. Extreme Market Shock Scenarios (VIX > 40, Gap Crash, Emergency Exits)
5. Flask API Parameter Fuzzing & Malformed Inputs (strings, negative, currency symbols)
6. Dynamic Risk Profile Position Sizing (Conservative = 1 lot, Balanced = 2 lots, Aggressive = 3 lots)
7. CogniGraph Walk-Forward Trap Adaptation Under Sequential Losses
8. Corrupt Cache File Recovery (Invalid JSON on disk recovered cleanly)
9. Frontend Zero-Variance & Dynamic Baseline Hardening in static assets
10. High-Speed Sub-Second Benchmark (< 100ms for 126 sessions)
"""

import json
import os
import tempfile
import time
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
    _safe_float,
    _safe_int,
)


class TestWalkForwardDeepDebug(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        cls.temp_dir = tempfile.mkdtemp(prefix="test_wf_debug_")

    # ── 1. Zero Trades Sortino & Sharpe Anomaly ─────────────────────────────────
    def test_zero_trades_sortino_and_sharpe_zero(self):
        """When total_trades is 0 or daily variance is 0, Sharpe and Sortino must be 0.0."""
        equity_curve = [
            {"date": "2026-04-01", "equity": 100000.0, "daily_return_pct": 0.0},
            {"date": "2026-04-02", "equity": 100000.0, "daily_return_pct": 0.0},
            {"date": "2026-04-03", "equity": 100000.0, "daily_return_pct": 0.0},
        ]
        trades = []  # No trades taken
        metrics = QuantitativeMetricsCalculator.calculate_metrics(100000.0, equity_curve, trades)

        self.assertEqual(metrics["total_trades"], 0)
        self.assertEqual(metrics["sharpe_ratio"], 0.0)
        self.assertEqual(metrics["sortino_ratio"], 0.0)
        self.assertEqual(metrics["cumulative_return_pct"], 0.0)

    # ── 2. Capital Depletion & Margin Call Guard ────────────────────────────────
    def test_capital_depletion_and_margin_call_protection(self):
        """Starting with capital below margin threshold (< ₹15,000) halts execution cleanly."""
        executor = TradeExecutionEngine(initial_capital=10000.0)
        session = {
            "session_id": "depleted_01",
            "date": "2026-04-01",
            "close": 24000.0,
            "next_day_open": 24100.0,
            "next_day_gap_pct": 0.40,
            "dte": 3,
        }
        decision = {
            "position_side": "BUY_CE",
            "verdict": "FULL_BTST",
        }
        trade = executor.execute_session_trade(session, decision, "REGIME_TEST")
        self.assertIsNone(trade)
        self.assertTrue(executor.is_bankrupt)
        self.assertEqual(len(executor.daily_equity_curve), 1)
        self.assertEqual(executor.daily_equity_curve[0]["equity"], 10000.0)

    # ── 3. Malformed, Null & Corrupt Session Fuzzing ───────────────────────────
    def test_malformed_and_null_session_fuzzing(self):
        """Engine must handle None, empty dicts, and corrupted string fields without crashing."""
        fuzzed_sessions = [
            None,
            {},
            {
                "india_vix": None,
                "dte": "0",
                "pcr": "0.65",
                "change_pct": "-0.85%",
                "fii_net_crores": "₹-2,500.5",
                "heavyweights": None,
                "social_sentiment": None,
                "global_cues": None,
            },
            {
                "india_vix": "invalid",
                "dte": None,
                "pcr": None,
                "change_pct": None,
                "fii_net_crores": None,
                "heavyweights": {
                    "HDFCBANK.NS": None,
                    "RELIANCE.NS": {"change_pct": "not_a_number"},
                },
                "social_sentiment": {"contrarian_warning": None, "mood": None},
                "global_cues": {"sp500_pct": None},
            },
        ]

        cg = CogniGraphWalkForwardLearner(enable_cognigraph=True)

        for sess in fuzzed_sessions:
            dims = evaluate_7_specialist_dimensions(sess)
            self.assertIsInstance(dims, dict)
            self.assertIn("price_action", dims)
            self.assertIn("vix_regime", dims)

            regime = cg.classify_regime(sess)
            self.assertIsInstance(regime, str)

            dec = simulate_debate_committee(dims, sess)
            self.assertIn("verdict", dec)
            self.assertIn("position_side", dec)

    # ── 4. Extreme Market Shock Scenarios ──────────────────────────────────────
    def test_extreme_market_shocks_trigger_emergency_exit(self):
        """Surging VIX and flash crashes must trigger immediate emergency exit."""
        session_shock = {
            "session_id": "shock_01",
            "date": "2026-05-15",
            "close": 23500.0,
            "change_pct": -3.2,
            "india_vix": 28.5,
            "vix_change_pct": 18.5,
            "dte": 1,
            "pcr": 0.55,
            "fii_net_crores": -6500.0,
            "heavyweights": {
                "HDFCBANK.NS": {"change_pct": -4.1},
                "RELIANCE.NS": {"change_pct": -3.5},
            },
            "social_sentiment": {"mood": "PANIC", "contrarian_warning": ""},
            "global_cues": {"sp500_pct": -2.8},
        }

        dims = evaluate_7_specialist_dimensions(session_shock)
        self.assertEqual(dims["vix_regime"]["verdict"], "VOLATILITY_SHOCK")

        dec = simulate_debate_committee(dims, session_shock)
        self.assertEqual(dec["verdict"], "EMERGENCY_EXIT")
        self.assertEqual(dec["position_side"], "NO_TRADE")
        self.assertIn("100% open lots immediately", dec["scale_out_plan"]["tier_1"])

    # ── 5. Flask API Parameter Fuzzing ─────────────────────────────────────────
    def test_api_parameter_fuzzing_and_graceful_handling(self):
        """API must gracefully handle non-numeric strings, currency symbols, and extreme bounds."""
        # Fuzzed GET
        res_fuzz_get = self.client.get("/api/simulation/walk-forward?months=xyz&initial_capital=invalid&force_run=false")
        self.assertEqual(res_fuzz_get.status_code, 200)

        # Fuzzed POST
        res_fuzz_post = self.client.post("/api/simulation/walk-forward", json={
            "months": "15",              # Exceeds max 12 -> clamped
            "initial_capital": "₹5,00,000", # String with INR symbol -> cast
            "risk_profile": "UNKNOWN_RISK",# Unknown profile -> falls back to BALANCED
            "enable_cognigraph": "no",
            "enable_scale_out": "0",
        })
        self.assertEqual(res_fuzz_post.status_code, 200)
        data = res_fuzz_post.get_json()["data"]
        self.assertEqual(data["simulation_config"]["months"], 12)
        self.assertEqual(data["simulation_config"]["initial_capital"], 500000.0)
        self.assertEqual(data["simulation_config"]["risk_profile"], "BALANCED")
        self.assertFalse(data["simulation_config"]["enable_cognigraph"])
        self.assertFalse(data["simulation_config"]["enable_scale_out"])

    # ── 6. Dynamic Risk Profile Position Sizing ────────────────────────────────
    def test_dynamic_risk_profile_position_sizing(self):
        """Aggressive profile uses up to 3 lots, Balanced uses 2 lots, Conservative uses 1 lot."""
        session = {
            "session_id": "sess_size_01",
            "date": "2026-06-01",
            "close": 24200.0,
            "next_day_open": 24300.0,
            "next_day_gap_pct": 0.41,
            "dte": 3,
        }
        decision = {
            "position_side": "BUY_CE",
            "verdict": "FULL_BTST",
        }

        # Aggressive
        exec_agg = TradeExecutionEngine(initial_capital=200000.0, risk_profile="AGGRESSIVE")
        trd_agg = exec_agg.execute_session_trade(session, decision, "REGIME")
        self.assertEqual(trd_agg["lots"], 3)

        # Balanced
        exec_bal = TradeExecutionEngine(initial_capital=200000.0, risk_profile="BALANCED")
        trd_bal = exec_bal.execute_session_trade(session, decision, "REGIME")
        self.assertEqual(trd_bal["lots"], 2)

        # Conservative
        exec_con = TradeExecutionEngine(initial_capital=200000.0, risk_profile="CONSERVATIVE")
        trd_con = exec_con.execute_session_trade(session, decision, "REGIME")
        self.assertEqual(trd_con["lots"], 1)

    # ── 7. CogniGraph Walk-Forward Trap Adaptation ─────────────────────────────
    def test_cognigraph_walk_forward_trap_adaptation(self):
        """CogniGraph must learn and store failure traps after recurring losses in a regime."""
        cg = CogniGraphWalkForwardLearner(enable_cognigraph=True)
        regime = "VIX_MOD|DTE_FAR|FII_NEUT|GAP_FLAT"

        # Initially no trap
        trap_init = cg.check_failure_trap(regime, "BUY_CE")
        self.assertIsNone(trap_init)

        # Record 2 consecutive severe losses under this regime
        cg.record_trade_outcome(regime, "BUY_CE", -25.0, "Severe slippage gap down")
        cg.record_trade_outcome(regime, "BUY_CE", -30.0, "Choppy whip-saw")

        # Now trap must trigger
        trap_learned = cg.check_failure_trap(regime, "BUY_CE")
        self.assertIsNotNone(trap_learned)
        self.assertIn("Walk-Forward Learned Trap", trap_learned)

    # ── 8. Corrupt Cache File Recovery ─────────────────────────────────────────
    def test_corrupt_cache_file_recovery(self):
        """Corrupt JSON in cache file must not crash API and must regenerate cleanly."""
        report_file = os.path.join(self.temp_dir, "historical_simulation_data.json")
        with open(report_file, "w", encoding="utf-8") as f:
            f.write("{ INVALID JSON CORRUPT DATA ...")

        feed = HistoricalDataFeed(history_dir=self.temp_dir)
        # Should catch JSONDecodeError and regenerate synthetic data cleanly
        sessions = feed.load_or_generate_sessions(months=1)
        self.assertGreater(len(sessions), 15)

    # ── 9. Frontend Asset Hardening Verification ───────────────────────────────
    def test_frontend_script_and_template_hardening(self):
        """script.js must contain zero-variance protection and dynamic initial_capital."""
        js_path = os.path.join(os.path.dirname(__file__), "static", "script.js")
        with open(js_path, "r", encoding="utf-8") as f:
            js_content = f.read()

        self.assertIn("maxVal - minVal < 1e-6", js_content)
        self.assertIn("baseCapital", js_content)
        self.assertIn("renderEquityCurveSVG(data.equity_curve || [], data.initial_capital)", js_content)

    # ── 10. Sub-Second Execution Benchmark ─────────────────────────────────────
    def test_sub_second_execution_benchmark(self):
        """6 months (126 sessions) must execute in under 100ms."""
        t0 = time.perf_counter()
        res = run_walk_forward_simulation(months=6, history_dir=self.temp_dir)
        t_elapsed = (time.perf_counter() - t0) * 1000

        self.assertLess(t_elapsed, 100.0, f"Execution took {t_elapsed:.1f}ms (expected < 100ms)")
        self.assertEqual(res["simulation_config"]["sessions_count"], 126)


if __name__ == "__main__":
    unittest.main()
