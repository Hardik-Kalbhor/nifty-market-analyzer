"""
exit/eci_scorer.py — Exit Conviction Index (ECI) Quantitative Multi-Factor Scoring Engine.
Computes a calibrated 0-100 score of exit urgency based on 5 weighted pillars.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Institutional pillar weights (sum = 1.0)
W_PRICE_ACTION = 0.25
W_ORDER_FLOW = 0.20
W_OI_GREEKS = 0.25
W_TIME_DECAY = 0.15
W_MACRO_INTERMARKET = 0.15

_VERDICT_SCORE_BASE = {
    "HOLD": 20,
    "HOLD_AND_RIDE": 15,
    "PARTIAL_BOOK": 52,
    "PARTIAL_BOOK_50": 50,
    "PARTIAL_BOOK_70": 68,
    "TRAIL": 62,
    "TRAIL_SL_TO_COST": 60,
    "TRAIL_SL_TIGHT": 70,
    "EXIT": 90,
    "FULL_EXIT": 92,
    "STAGNATION_EXIT": 84,
    "PRE_CLOSE_EXIT": 98,
    "EMERGENCY_EXIT": 96,
}


def _get_verdict_base(verdict_str: Any, default: int = 40) -> int:
    v = str(verdict_str or "").strip().upper()
    for k, score in _VERDICT_SCORE_BASE.items():
        if k in v:
            return score
    return default


def compute_eci_score(
    result: dict[str, Any],
    position: dict[str, Any],
    live_signals: dict[str, Any],
) -> tuple[int, dict[str, int], str]:
    """
    Computes:
    - eci_score: integer 0 - 100
    - eci_breakdown: dict of 5 pillar scores (0 - 100 each)
    - urgency: "NORMAL" | "MEDIUM" | "HIGH" | "CRITICAL"
    """
    verdict = str(result.get("verdict", "")).upper()
    is_fast_path = bool(result.get("is_fast_path", False))
    dim_scores = result.get("dimension_scores", {}) or {}

    side = str(position.get("position_side", "BUY_CE")).upper()
    is_bullish = side in ["BUY_CE", "LONG_FUTURES", "SHORT_PE"]
    is_option_buyer = side in ["BUY_CE", "BUY_PE"]

    # 1. Price Action Pillar (Base + Excursion + Retracement)
    pa_dim = dim_scores.get("price_action", {})
    pa_base = _get_verdict_base(pa_dim.get("verdict") or verdict, default=35)
    favorable_move = float(position.get("favorable_move_pct", 0.0) or 0.0)
    current_r = float(position.get("current_r", 0.0) or 0.0)
    mfe_locked = bool(position.get("mfe_locked", False))

    pa_mod = 0
    if mfe_locked and current_r < 0.50:
        pa_mod += 20  # retrace after 1.5R favorable run
    if favorable_move <= -0.30:
        pa_mod += 25  # severe adverse spot move
    elif favorable_move >= 0.50:
        pa_mod += 15  # Target 2 expansion — profit taking urgency
    elif favorable_move >= 0.25:
        pa_mod += 8   # Target 1 reached
    s_price_action = max(5, min(100, pa_base + pa_mod))

    # 2. Order Flow Pillar (CVD divergence, COI writing acceleration, LOB)
    of_dim = dim_scores.get("order_flow", {})
    of_base = _get_verdict_base(of_dim.get("verdict"), default=30)
    coi_alert = result.get("coi_alert") or position.get("coi_alert")
    coi_call = float(live_signals.get("coi_call_change_pct", 0.0) or 0.0)
    coi_put = float(live_signals.get("coi_put_change_pct", 0.0) or 0.0)
    cvd_dir = str(live_signals.get("cvd_divergence", "NEUTRAL")).upper()

    of_mod = 0
    if coi_alert:
        of_mod += 30
    elif (is_bullish and coi_call >= 15.0) or (not is_bullish and coi_put >= 15.0):
        of_mod += 22
    if is_bullish and cvd_dir == "NEGATIVE":
        of_mod += 18  # price up while institutional CVD lower (absorption/distribution)
    elif not is_bullish and cvd_dir == "POSITIVE":
        of_mod += 18  # price down while institutional CVD positive (accumulation floor)
    if "BULL TRAP" in str(result.get("contrarian_alert", "")).upper() or "BEAR TRAP" in str(result.get("contrarian_alert", "")).upper():
        of_mod += 15
    s_order_flow = max(5, min(100, of_base + of_mod))

    # 3. OI & Greeks Pillar (COI wall, PCR, Theta, IV Crush)
    oi_dim = dim_scores.get("oi_pcr", {})
    greeks_dim = dim_scores.get("greeks_decay", {})
    vix_dim = dim_scores.get("vix_regime", {})
    oi_base = int((_get_verdict_base(oi_dim.get("verdict"), 30) + _get_verdict_base(greeks_dim.get("verdict"), 30) + _get_verdict_base(vix_dim.get("verdict"), 30)) / 3)

    vix_change = float(live_signals.get("india_vix_change_pct", 0.0) or 0.0)
    pcr = float(live_signals.get("pcr", 1.05) or 1.05)
    oi_mod = 0
    if is_option_buyer and vix_change <= -3.5:
        oi_mod += 35  # IV crush disaster
    elif is_option_buyer and vix_change <= -2.0:
        oi_mod += 18
    elif vix_change >= 6.0:
        oi_mod += 25  # VIX volatility shock
    if (is_bullish and pcr < 0.70) or (not is_bullish and pcr > 1.45):
        oi_mod += 18  # extreme PCR structural opposition
    s_oi_greeks = max(5, min(100, oi_base + oi_mod))

    # 4. Time Decay & Dead-Money Stagnation Pillar
    time_base = _get_verdict_base(greeks_dim.get("verdict"), default=25)
    elapsed_minutes = float(position.get("elapsed_minutes", 0.0) or 0.0)
    trade_type = str(position.get("trade_type", "INTRADAY")).upper()

    td_mod = 0
    if trade_type != "BTST":
        if elapsed_minutes >= 35.0 and abs(favorable_move) <= 0.10:
            td_mod += 40  # stagnation exit condition
        elif elapsed_minutes >= 20.0 and abs(favorable_move) <= 0.05:
            td_mod += 20  # stagnation warning
    if verdict == "PRE_CLOSE_EXIT":
        td_mod += 50
    s_time_decay = max(5, min(100, time_base + td_mod))

    # 5. Macro & Heavyweight Intermarket Pillar
    macro_dim = dim_scores.get("macro_global", {})
    hw_dim = dim_scores.get("heavyweights", {})
    macro_base = int((_get_verdict_base(macro_dim.get("verdict"), 30) + _get_verdict_base(hw_dim.get("verdict"), 30)) / 2)

    macro_mod = 0
    hw_alignment = str(result.get("heavyweight_alignment", "")).upper()
    if "BEARISH" in hw_alignment and is_bullish:
        macro_mod += 20
    elif "BULLISH" in hw_alignment and not is_bullish:
        macro_mod += 20
    s_macro = max(5, min(100, macro_base + macro_mod))

    # Fast-path overrides ensure hard circuit breakers produce high conviction
    if is_fast_path:
        if verdict in ("EMERGENCY_EXIT", "PRE_CLOSE_EXIT"):
            s_price_action = max(s_price_action, 95)
            s_oi_greeks = max(s_oi_greeks, 95)
            s_time_decay = max(s_time_decay, 95)
        elif verdict == "FULL_EXIT":
            s_price_action = max(s_price_action, 88)
            s_oi_greeks = max(s_oi_greeks, 85)
        elif verdict == "STAGNATION_EXIT":
            s_time_decay = max(s_time_decay, 90)
            s_price_action = max(s_price_action, 75)

    # Calculate weighted composite ECI
    raw_eci = (
        (W_PRICE_ACTION * s_price_action)
        + (W_ORDER_FLOW * s_order_flow)
        + (W_OI_GREEKS * s_oi_greeks)
        + (W_TIME_DECAY * s_time_decay)
        + (W_MACRO_INTERMARKET * s_macro)
    )
    final_eci = int(max(5, min(98, round(raw_eci))))

    # Calibrate urgency tier strictly from ECI score
    if final_eci < 40:
        urgency = "NORMAL"
    elif final_eci < 70:
        urgency = "MEDIUM"
    elif final_eci < 85:
        urgency = "HIGH"
    else:
        urgency = "CRITICAL"

    breakdown = {
        "price_action": int(s_price_action),
        "order_flow": int(s_order_flow),
        "oi_greeks": int(s_oi_greeks),
        "time_decay": int(s_time_decay),
        "macro_intermarket": int(s_macro),
    }

    return final_eci, breakdown, urgency
