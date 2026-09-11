"""
exit_fast/rules_new.py — Advanced deterministic exit rules (MFE Lock, MAE Bleed, IV Crush, Stagnation Clock, COI Velocity, BTST Failed Gap).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional
from .constants import _safe_float, _get_now_ist

logger = logging.getLogger(__name__)


def evaluate_new_rules(
    position: dict[str, Any],
    live_signals: dict[str, Any],
    current_time: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """
    Evaluates 6 advanced quantitative deterministic rules:
    - Rule 9: MFE Breakeven Lock (>= 1.5R favorable peak)
    - Rule 10: Pre-emptive MAE Bleed liquidation
    - Rule 11: IV Crush Alarm for option buyers
    - Rule 12: Dead-Money Stagnation Timeout Clock
    - Rule 13: COI Writing Velocity Surge (ATM Call/Put resistance/support wall)
    - Rule 14: BTST Gap Execution (Pre-market MOO staging & failed gap fade)
    """
    now_ist = current_time or _get_now_ist()
    trade_type = str(position.get("trade_type", "INTRADAY")).upper()
    side = str(position.get("position_side", "BUY_CE")).upper()
    is_bullish = side in ["BUY_CE", "LONG_FUTURES", "SHORT_PE"]
    is_option_buyer = side in ["BUY_CE", "BUY_PE"]

    entry_spot = _safe_float(position.get("entry_spot"), 0.0)
    current_spot = _safe_float(live_signals.get("nifty_spot"), entry_spot)
    entry_premium = _safe_float(position.get("entry_premium") or position.get("entry_price") or position.get("buy_price") or position.get("avg_price"), 0.0)
    current_premium = _safe_float(position.get("current_premium") or position.get("current_ltp") or position.get("current_price") or position.get("ltp"), 0.0)

    # Excursion & R-multiple metrics
    spot_diff = current_spot - entry_spot if entry_spot > 0 else 0.0
    spot_pct = (spot_diff / entry_spot) * 100.0 if entry_spot > 0 else 0.0
    favorable_move = spot_pct if is_bullish else -spot_pct
    current_r = _safe_float(position.get("current_r"), round(favorable_move / 0.60, 2))

    mfe_pct = _safe_float(position.get("mfe_pct"), favorable_move)
    mae_pct = _safe_float(position.get("mae_pct"), 0.0)
    mfe_r = _safe_float(position.get("mfe_r"), round(mfe_pct / 0.60, 2))
    mfe_locked = bool(position.get("mfe_locked") or (mfe_r >= 1.5))
    elapsed_minutes = _safe_float(position.get("elapsed_minutes"), 0.0)

    vix_change_pct = _safe_float(live_signals.get("india_vix_change_pct"), 0.0)

    # ── Rule 9: MFE Breakeven Lock (1.5R Peak Excursion) ───────────────────────
    # If trade hit >= 1.5R favorable peak, but has fallen below +0.5R,
    # force stop strictly to cost to enforce "never let a winner become a loser".
    if mfe_locked and current_r < 0.50 and entry_spot > 0:
        cost_sl = round(entry_spot, 1)
        return {
            "verdict": "TRAIL_SL_TO_COST",
            "action": f"MFE Lock Activated: Move stop-loss strictly to breakeven ({cost_sl}) to protect capital.",
            "confidence": 88,
            "urgency": "HIGH",
            "engine": "Deterministic Fast-Path (MFE Breakeven Lock)",
            "reasoning": (
                f"Trade attained a peak favorable excursion of +{mfe_pct:.2f}% ({mfe_r:.1f}R), but momentum has "
                f"cooled to {current_r:+.2f}R. Moving stop strictly to entry cost {cost_sl} eliminates all downside risk."
            ),
            "trailing_sl": cost_sl,
            "is_fast_path": True,
            "mfe_locked": True,
        }

    # ── Rule 10: MAE Rapid Bleed Pre-Emptive Cut ──────────────────────────────
    # If adverse excursion reaches -0.35% or worse without any prior MFE lock,
    # cut pre-emptively before the catastrophic -0.60% hard stop.
    if mae_pct <= -0.35 and favorable_move <= -0.25 and not mfe_locked:
        return {
            "verdict": "FULL_EXIT",
            "action": "Pre-emptive risk exit: Liquidate immediately before hard stop breach.",
            "confidence": 86,
            "urgency": "HIGH",
            "engine": "Deterministic Fast-Path (MAE Adverse Bleed)",
            "reasoning": (
                f"Maximum Adverse Excursion reached {mae_pct:.2f}% ({round(spot_diff, 1)} pts) with negative momentum. "
                f"Pre-emptive liquidation prevents a full 1R (-0.60%) hard loss."
            ),
            "trailing_sl": round(current_spot, 1),
            "is_fast_path": True,
        }

    # ── Rule 11: IV Crush Alarm (Option Buyers Only) ───────────────────────────
    # Severe drop in India VIX (>= -4.0% intraday) burns option buyer time premium rapidly.
    if is_option_buyer:
        if vix_change_pct <= -4.0:
            return {
                "verdict": "FULL_EXIT",
                "action": "IV Crush Emergency: Liquidate long option immediately to halt volatility crush.",
                "confidence": 91,
                "urgency": "CRITICAL",
                "engine": "Deterministic Fast-Path (IV Crush Alarm)",
                "reasoning": (
                    f"India VIX collapsed by {vix_change_pct:.2f}%. Rapid implied volatility contraction is deflating "
                    f"option buyer premiums regardless of underlying price action. Exit immediately."
                ),
                "trailing_sl": round(current_spot, 1),
                "is_fast_path": True,
            }
        # Moderate VIX drop (>= -2.5%) combined with > 25% premium loss on flat spot
        if vix_change_pct <= -2.5 and entry_premium > 0 and current_premium > 0:
            prem_pnl = ((current_premium - entry_premium) / entry_premium) * 100.0
            if prem_pnl <= -25.0 and abs(spot_pct) < 0.20:
                return {
                    "verdict": "PARTIAL_BOOK_70",
                    "action": "De-risk 70% position: Volatility burn destroying option value despite flat spot.",
                    "confidence": 84,
                    "urgency": "HIGH",
                    "engine": "Deterministic Fast-Path (IV Burn De-risking)",
                    "reasoning": (
                        f"India VIX dropped {vix_change_pct:.2f}% while option premium decayed {prem_pnl:.1f}% "
                        f"(₹{entry_premium} → ₹{current_premium}) despite Nifty moving only {spot_pct:+.2f}%. De-risk immediately."
                    ),
                    "trailing_sl": round(current_spot, 1),
                    "is_fast_path": True,
                }

    # ── Rule 12: Dead-Money Stagnation Timeout Clock ──────────────────────────
    # Alpha half-life: If directional setup does not expand within 35 mins, liberate margin.
    if trade_type != "BTST" and elapsed_minutes > 0:
        if elapsed_minutes >= 35.0 and abs(favorable_move) <= 0.10:
            return {
                "verdict": "STAGNATION_EXIT",
                "action": f"Dead-money exit: Close trade. Setup has idled for {elapsed_minutes:.0f} mins with zero expansion.",
                "confidence": 82,
                "urgency": "HIGH",
                "engine": "Deterministic Fast-Path (Dead-Money Timeout)",
                "reasoning": (
                    f"Position has been open for {elapsed_minutes:.0f} minutes with negligible move ({favorable_move:+.2f}%). "
                    f"Directional alpha has expired and theta decay is actively eroding expectancy. Free margin for active setups."
                ),
                "trailing_sl": round(current_spot, 1),
                "is_fast_path": True,
                "elapsed_minutes": elapsed_minutes,
            }
        if elapsed_minutes >= 20.0 and abs(favorable_move) <= 0.05:
            trail_sl = round(current_spot * 0.9985 if is_bullish else current_spot * 1.0015, 1)
            return {
                "verdict": "TRAIL_SL_TIGHT",
                "action": f"Stagnation warning: Idling for {elapsed_minutes:.0f} mins. Tighten stop to recent 1-min swing.",
                "confidence": 76,
                "urgency": "MEDIUM",
                "engine": "Deterministic Fast-Path (Stagnation Warning)",
                "reasoning": (
                    f"Trade has idled for {elapsed_minutes:.0f} minutes with near-zero price movement ({favorable_move:+.2f}%). "
                    f"Tighten stop-loss to {trail_sl} to guard against sudden adverse chop."
                ),
                "trailing_sl": trail_sl,
                "is_fast_path": True,
                "elapsed_minutes": elapsed_minutes,
            }

    # ── Rule 13: COI Velocity (ATM Strike Resistance/Support Build) ────────────
    # Real-time institutional writing surge: ATM Call OI +20% in 5 min = wall being erected.
    coi_call = _safe_float(live_signals.get("coi_call_change_pct"), 0.0)
    coi_put = _safe_float(live_signals.get("coi_put_change_pct"), 0.0)

    if is_bullish and coi_call >= 20.0 and coi_put <= -10.0 and current_spot > 0:
        tight_sl = round(current_spot * 0.9985, 1)
        return {
            "verdict": "TRAIL_SL_TIGHT",
            "action": f"COI Alert: ATM Call writing spiked +{coi_call:.0f}% in 5 min. Tighten stop to {tight_sl}.",
            "confidence": 82,
            "urgency": "HIGH",
            "engine": "Deterministic Fast-Path (COI Velocity Wall)",
            "reasoning": (
                f"Aggressive institutional Call writing detected: ATM Call OI surged +{coi_call:.1f}% in 5 minutes "
                f"while Put writers unwound ({coi_put:+.1f}%). Institutions are building an immediate resistance ceiling."
            ),
            "trailing_sl": tight_sl,
            "is_fast_path": True,
            "coi_alert": "OI_RESISTANCE_BUILD",
        }

    if not is_bullish and coi_put >= 20.0 and coi_call <= -10.0 and current_spot > 0:
        tight_sl = round(current_spot * 1.0015, 1)
        return {
            "verdict": "TRAIL_SL_TIGHT",
            "action": f"COI Alert: ATM Put writing spiked +{coi_put:.0f}% in 5 min. Tighten stop to {tight_sl}.",
            "confidence": 82,
            "urgency": "HIGH",
            "engine": "Deterministic Fast-Path (COI Velocity Floor)",
            "reasoning": (
                f"Aggressive institutional Put writing detected: ATM Put OI surged +{coi_put:.1f}% in 5 minutes "
                f"while Call writers unwound ({coi_call:+.1f}%). Institutions are building a strong support floor."
            ),
            "trailing_sl": tight_sl,
            "is_fast_path": True,
            "coi_alert": "OI_SUPPORT_BUILD",
        }

    # ── Rule 14: BTST Gap Execution Engine ─────────────────────────────────────
    if trade_type == "BTST":
        # Pre-Market 09:00 - 09:14 IST: Lock gap if GIFT indicative exceeds 0.60%
        if now_ist.hour == 9 and now_ist.minute < 15:
            gift_ind = _safe_float(live_signals.get("gift_nifty_indicative"), 0.0)
            if gift_ind > 0 and entry_spot > 0:
                indicative_gap = ((gift_ind - entry_spot) / entry_spot) * 100.0 if is_bullish else ((entry_spot - gift_ind) / entry_spot) * 100.0
                if indicative_gap >= 0.60:
                    return {
                        "verdict": "PARTIAL_BOOK_70",
                        "action": f"Pre-Market Lock: Stage 70% MOO exit for 09:15:00 AM (indicative gap +{indicative_gap:.2f}%).",
                        "confidence": 89,
                        "urgency": "HIGH",
                        "engine": "Deterministic Fast-Path (BTST Pre-Market Gap Lock)",
                        "reasoning": (
                            f"Overnight GIFT Nifty gap of +{indicative_gap:.2f}% ({gift_ind:.1f}) exceeds institutional Target 1 "
                            f"(> 0.60%). Stage a 70% Market-On-Open (MOO) limit exit at 09:15:00 IST to eliminate gap-fade risk."
                        ),
                        "trailing_sl": round(entry_spot, 1),
                        "is_fast_path": True,
                    }

        # Market Open 09:15 - 09:20 IST: Failed Gap-and-Go Kill-Switch
        if now_ist.hour == 9 and 15 <= now_ist.minute <= 20:
            open_low = _safe_float(live_signals.get("open_1min_low"), 0.0)
            if is_bullish and open_low > 0 and current_spot < open_low:
                return {
                    "verdict": "EMERGENCY_EXIT",
                    "action": "BTST Kill-Switch: Nifty broke opening 1-min low. Liquidate overnight long immediately.",
                    "confidence": 92,
                    "urgency": "CRITICAL",
                    "engine": "Deterministic Fast-Path (BTST Failed Gap Fade)",
                    "reasoning": (
                        f"Failed Gap-and-Go: Nifty opened with an overnight gap but has broken below the 09:15–09:16 AM "
                        f"1-minute low ({open_low:.1f}). Emergency kill-switch activated to lock remaining overnight profit."
                    ),
                    "trailing_sl": round(current_spot, 1),
                    "is_fast_path": True,
                }

    return None
