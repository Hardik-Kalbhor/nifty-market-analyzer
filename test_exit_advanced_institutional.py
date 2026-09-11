"""
test_exit_advanced_institutional.py — Comprehensive Validation of All 8 Institutional Exit Advisor Upgrades:
- Gap 1: Numeric ECI Score (0-100) & 5-Pillar Breakdown
- Gap 2: MFE / MAE Excursion Tracking & Rule 9 MFE Breakeven Lock & Rule 10 MAE Bleed
- Gap 3: Adaptive ATR-14 Scaled Trailing Stop
- Gap 4: CVD Proxy Divergence
- Gap 5: COI Writing Velocity & ATM Wall Detection
- Gap 6: BTST Morning Execution (0.6% Pre-Market MOO & 9:16 Failed Gap Kill-Switch)
- Gap 7: Dead-Money Stagnation Timeout Clock (Rule 12 & STAGNATION_EXIT)
- Gap 8: IV Crush Alarm for Option Buyers (Rule 11)
- Session Management & Manual Exit Endpoint Lifecycle
"""

import os
import sys
import unittest
from datetime import datetime
from unittest.mock import patch
import pytz

from exit_fast_path import evaluate_fast_path, generate_rule_based_fallback
from exit_analyzer import evaluate_exit_with_ai
from exit.enricher import enrich_position
from exit.eci_scorer import compute_eci_score
from exit.session_manager import TradeSessionManager, get_trade_session_manager
from market_signals.option_chain import _compute_coi_velocity
from market_signals.core import compute_atr_from_bars, compute_cvd_from_bars

TIMEZONE = pytz.timezone("Asia/Kolkata")


class TestAdvancedInstitutionalExitAdvisor(unittest.TestCase):

    def setUp(self):
        # Patch IST time to 11:30 AM for normal intraday tests
        self.patcher = patch(
            "exit_fast.rules_critical._get_now_ist",
            return_value=datetime(2026, 9, 9, 11, 30, tzinfo=TIMEZONE)
        )
        self.patcher_new = patch(
            "exit_fast.rules_new._get_now_ist",
            return_value=datetime(2026, 9, 9, 11, 30, tzinfo=TIMEZONE)
        )
        self.patcher.start()
        self.patcher_new.start()

    def tearDown(self):
        self.patcher.stop()
        self.patcher_new.stop()

    # ── GAP 1: Numeric ECI Score (0-100) & Breakdown ─────────────────────────
    def test_gap1_numeric_eci_score_and_breakdown(self):
        """Gap 1: Verify ECI score is an integer (0-100), has 5 pillars, and aligns with urgency."""
        position = {
            "trade_type": "INTRADAY",
            "position_side": "BUY_CE",
            "entry_spot": 24200,
            "entry_premium": 100,
        }
        live_signals = {
            "nifty_spot": 24220,
            "india_vix": 13.5,
            "india_vix_change_pct": 0.5,
            "pcr": 1.10,
            "atr_14_1min": 18.0,
            "cvd_divergence": "POSITIVE",
        }
        res = evaluate_exit_with_ai(position, live_signals, [])

        self.assertIn("eci_score", res)
        self.assertIsInstance(res["eci_score"], int)
        self.assertGreaterEqual(res["eci_score"], 0)
        self.assertLessEqual(res["eci_score"], 100)

        self.assertIn("eci_breakdown", res)
        breakdown = res["eci_breakdown"]
        for pillar in ["price_action", "order_flow", "oi_greeks", "time_decay", "macro_intermarket"]:
            self.assertIn(pillar, breakdown)
            self.assertIsInstance(breakdown[pillar], int)
            self.assertGreaterEqual(breakdown[pillar], 0)
            self.assertLessEqual(breakdown[pillar], 100)

        # Urgency should be one of the standard calibrated labels
        self.assertIn(res["urgency"], ["NORMAL", "MEDIUM", "HIGH", "CRITICAL"])
        print(f"✅ Gap 1 Passed: ECI Score = {res['eci_score']}/100, Urgency = {res['urgency']}, Breakdown = {breakdown}")

    # ── GAP 2: MFE / MAE Excursion Tracking & Breakeven Lock ──────────────────
    def test_gap2_rule9_mfe_breakeven_lock(self):
        """Gap 2: Position reached >= 1.5R peak, then retraced below +0.5R -> TRAIL_SL_TO_COST."""
        position = {
            "trade_type": "INTRADAY",
            "position_side": "BUY_CE",
            "entry_spot": 24200,
            "mfe_spot": 24430,  # Peak was +0.95% (+1.58R)
            "mfe_locked": True,
            "current_r": 0.25,   # Retraced to +0.25R
        }
        live_signals = {
            "nifty_spot": 24230,
            "india_vix": 13.5,
            "india_vix_change_pct": 0.0,
        }
        res = evaluate_fast_path(position, live_signals)

        self.assertIsNotNone(res)
        self.assertEqual(res["verdict"], "TRAIL_SL_TO_COST")
        self.assertEqual(res["trailing_sl"], 24200.0)  # Locked strictly at entry cost
        self.assertTrue(res.get("mfe_locked"))
        self.assertEqual(res["urgency"], "HIGH")
        print(f"✅ Gap 2 Passed (Rule 9): MFE Breakeven Lock triggered SL at cost {res['trailing_sl']}")

    def test_gap2_rule10_mae_rapid_bleed(self):
        """Gap 2: Adverse excursion reaches -0.38% without recovery -> Pre-emptive FULL_EXIT."""
        position = {
            "trade_type": "INTRADAY",
            "position_side": "BUY_CE",
            "entry_spot": 24200,
            "mae_pct": -0.38,
            "favorable_move_pct": -0.30,
            "mfe_locked": False,
        }
        live_signals = {
            "nifty_spot": 24127,
            "india_vix": 14.0,
            "india_vix_change_pct": 1.0,
        }
        res = evaluate_fast_path(position, live_signals)

        self.assertIsNotNone(res)
        self.assertEqual(res["verdict"], "FULL_EXIT")
        self.assertEqual(res["urgency"], "HIGH")
        self.assertIn("MAE Adverse Bleed", res["engine"])
        print(f"✅ Gap 2 Passed (Rule 10): MAE Bleed pre-emptively cut failing position")

    # ── GAP 3: Adaptive ATR-14 Scaled Trailing Stop ───────────────────────────
    def test_gap3_atr_scaled_trailing_stop(self):
        """Gap 3: Verify enricher computes ATR trail correctly for Long and Short trades."""
        live_signals = {
            "nifty_spot": 24500.0,
            "atr_14_1min": 22.0,  # 22 points ATR
        }
        # Long trade: trail below spot by 1.5 * ATR = 24500 - 33 = 24467
        pos_long = {"position_side": "BUY_CE", "entry_spot": 24480, "atr_multiplier": 1.5}
        enr_long = enrich_position(pos_long, live_signals)
        self.assertEqual(enr_long["atr_trail_level"], 24467.0)

        # Short trade: trail above spot by 1.5 * ATR = 24500 + 33 = 24533
        pos_short = {"position_side": "BUY_PE", "entry_spot": 24520, "atr_multiplier": 1.5}
        enr_short = enrich_position(pos_short, live_signals)
        self.assertEqual(enr_short["atr_trail_level"], 24533.0)

        # Helper ATR calculation test
        bars = [
            {"high": 24510, "low": 24490, "close": 24505},
            {"high": 24520, "low": 24500, "close": 24515},
            {"high": 24530, "low": 24510, "close": 24525},
        ]
        atr_calc = compute_atr_from_bars(bars, period=2)
        self.assertGreater(atr_calc, 0.0)
        print(f"✅ Gap 3 Passed: Long ATR Trail = {enr_long['atr_trail_level']}, Short ATR Trail = {enr_short['atr_trail_level']}")

    # ── GAP 4: CVD Volume Delta Proxy ─────────────────────────────────────────
    def test_gap4_cvd_proxy_divergence(self):
        """Gap 4: Verify compute_cvd_from_bars classifies net volume delta."""
        bars_bull = [
            {"open": 24500, "close": 24510, "volume": 1000},
            {"open": 24510, "close": 24520, "volume": 1500},
        ]
        cvd_bull = compute_cvd_from_bars(bars_bull)
        self.assertEqual(cvd_bull, "POSITIVE")

        bars_bear = [
            {"open": 24520, "close": 24505, "volume": 2000},
            {"open": 24505, "close": 24490, "volume": 2500},
        ]
        cvd_bear = compute_cvd_from_bars(bars_bear)
        self.assertEqual(cvd_bear, "NEGATIVE")
        print(f"✅ Gap 4 Passed: CVD proxy correctly resolves POSITIVE and NEGATIVE delta flows")

    # ── GAP 5: COI Writing Velocity & ATM Wall Detection ─────────────────────
    def test_gap5_rule13_coi_velocity_wall(self):
        """Gap 5: ATM Call OI +25% spike in 5 min on Long CE -> TRAIL_SL_TIGHT + OI_RESISTANCE_BUILD."""
        position = {
            "trade_type": "INTRADAY",
            "position_side": "BUY_CE",
            "entry_spot": 24200,
        }
        live_signals = {
            "nifty_spot": 24220,
            "coi_call_change_pct": 24.5,  # Aggressive Call writing
            "coi_put_change_pct": -12.0,  # Put unwinding
        }
        res = evaluate_fast_path(position, live_signals)

        self.assertIsNotNone(res)
        self.assertEqual(res["verdict"], "TRAIL_SL_TIGHT")
        self.assertEqual(res.get("coi_alert"), "OI_RESISTANCE_BUILD")
        self.assertEqual(res["urgency"], "HIGH")
        self.assertIn("COI Velocity Wall", res["engine"])

        # Test rolling COI velocity computation helper
        now_ts = 1000.0
        # Observation 1 at t=700 (5 min ago): OI = 100,000
        _compute_coi_velocity(24500, "CE", 100000, now_ts=700.0)
        # Observation 2 at t=1000: OI = 125,000 (+25%)
        delta = _compute_coi_velocity(24500, "CE", 125000, now_ts=now_ts)
        self.assertEqual(delta, 25.0)
        print(f"✅ Gap 5 Passed: COI velocity computed +25.0% and triggered TRAIL_SL_TIGHT resistance wall")

    # ── GAP 6: BTST Morning Execution Engine ─────────────────────────────────
    def test_gap6_rule14_btst_premarket_moo_staging(self):
        """Gap 6: Pre-market 09:08 AM with GIFT indicative gap >= 0.60% -> PARTIAL_BOOK_70."""
        pre_market_time = datetime(2026, 9, 10, 9, 8, tzinfo=TIMEZONE)
        position = {
            "trade_type": "BTST",
            "position_side": "BUY_CE",
            "entry_spot": 24200,
        }
        live_signals = {
            "nifty_spot": 24200,
            "gift_nifty_indicative": 24360,  # +0.66% gap
        }
        res = evaluate_fast_path(position, live_signals, current_time=pre_market_time)

        self.assertIsNotNone(res)
        self.assertEqual(res["verdict"], "PARTIAL_BOOK_70")
        self.assertIn("BTST Pre-Market Gap Lock", res["engine"])
        print(f"✅ Gap 6 Passed (Part A): Pre-market 9:08 AM staged 70% MOO exit on +0.66% gap")

    def test_gap6_rule14_btst_failed_gap_fade_killswitch(self):
        """Gap 6: Market open 09:16 AM, Nifty breaks below 1-min low -> EMERGENCY_EXIT kill-switch."""
        open_time = datetime(2026, 9, 10, 9, 16, tzinfo=TIMEZONE)
        position = {
            "trade_type": "BTST",
            "position_side": "BUY_CE",
            "entry_spot": 24200,
        }
        live_signals = {
            "nifty_spot": 24230,
            "open_1min_low": 24250,  # Spot dropped below 1-min low
        }
        res = evaluate_fast_path(position, live_signals, current_time=open_time)

        self.assertIsNotNone(res)
        self.assertEqual(res["verdict"], "EMERGENCY_EXIT")
        self.assertEqual(res["urgency"], "CRITICAL")
        self.assertIn("BTST Failed Gap Fade", res["engine"])
        print(f"✅ Gap 6 Passed (Part B): 9:16 AM Failed Gap-and-Go activated EMERGENCY_EXIT kill-switch")

    # ── GAP 7: Dead-Money Stagnation Timeout Clock ────────────────────────────
    def test_gap7_rule12_stagnation_timeout_exit(self):
        """Gap 7: Trade idle for 38 minutes with flat spot -> STAGNATION_EXIT."""
        position = {
            "trade_type": "INTRADAY",
            "position_side": "BUY_CE",
            "entry_spot": 24200,
            "elapsed_minutes": 38.0,
            "favorable_move_pct": 0.04,  # flat move
        }
        live_signals = {
            "nifty_spot": 24210,
        }
        res = evaluate_fast_path(position, live_signals)

        self.assertIsNotNone(res)
        self.assertEqual(res["verdict"], "STAGNATION_EXIT")
        self.assertEqual(res["urgency"], "HIGH")
        self.assertIn("Dead-Money Timeout", res["engine"])

        # BTST trade should be exempt from intraday stagnation clock
        pos_btst = dict(position)
        pos_btst["trade_type"] = "BTST"
        res_btst = evaluate_fast_path(pos_btst, live_signals)
        self.assertIsNone(res_btst)
        print(f"✅ Gap 7 Passed: 38-minute dead money triggered STAGNATION_EXIT (BTST properly exempt)")

    # ── GAP 8: IV Crush Alarm for Option Buyers ──────────────────────────────
    def test_gap8_rule11_iv_crush_alarm(self):
        """Gap 8: India VIX drops -4.5% -> FULL_EXIT for BUY_CE; No stop for SHORT_CE seller."""
        pos_buyer = {
            "trade_type": "INTRADAY",
            "position_side": "BUY_CE",
            "entry_spot": 24200,
        }
        live_signals = {
            "nifty_spot": 24205,
            "india_vix_change_pct": -4.5,  # VIX collapse
        }
        res_buyer = evaluate_fast_path(pos_buyer, live_signals)

        self.assertIsNotNone(res_buyer)
        self.assertEqual(res_buyer["verdict"], "FULL_EXIT")
        self.assertEqual(res_buyer["urgency"], "CRITICAL")
        self.assertIn("IV Crush Alarm", res_buyer["engine"])

        # Option seller should NOT be stopped out (sellers profit from IV crush)
        pos_seller = {
            "trade_type": "INTRADAY",
            "position_side": "SHORT_CE",
            "entry_spot": 24200,
        }
        res_seller = evaluate_fast_path(pos_seller, live_signals)
        self.assertIsNone(res_seller)
        print(f"✅ Gap 8 Passed: VIX -4.5% triggered IV Crush FULL_EXIT for buyer, preserved seller position")

    # ── Session Management & Manual Exit Endpoint Lifecycle ──────────────────
    def test_session_manager_and_excursions(self):
        """Verify TradeSessionManager tracks peak/trough, MFE/MAE, and manual closing."""
        sm = TradeSessionManager()
        pos = {
            "position_side": "BUY_CE",
            "entry_spot": 24200,
            "entry_premium": 100,
        }
        sess = sm.create_or_get_session(pos, live_spot=24200)
        sid = sess["session_id"]
        self.assertEqual(sess["status"], "ACTIVE")

        # Spot rises to 24350 (+0.62% = +1.03R)
        sm.record_poll(sid, current_spot=24350, verdict="HOLD_AND_RIDE", eci_score=25)
        updated = sm.get_session(sid)
        self.assertEqual(updated["peak_spot"], 24350.0)
        self.assertEqual(updated["mfe_pct"], 0.62)

        # User clicks manual "Exit" button
        closed = sm.close_session(sid, exit_spot=24340, exit_premium=130, reason="MANUAL_EXIT")
        self.assertEqual(closed["status"], "CLOSED")
        self.assertEqual(closed["realized_spot_pnl_pct"], 0.58)
        self.assertEqual(closed["realized_premium_pnl_pct"], 30.0)
        print(f"✅ Session Management Passed: Session {sid} tracked peak {updated['peak_spot']} and closed with +30% P&L")


if __name__ == "__main__":
    unittest.main()
