"""
exit_fast/rules_market.py — Market structure and sentiment exit rules (Theta, PCR, OI walls, Contrarian traps).
"""

from datetime import datetime
from typing import Any, Optional
from .constants import _safe_float, _get_now_ist
from .market import is_expiry_day


def _check_is_expiry_day() -> bool:
    import sys
    shim = sys.modules.get("exit_fast_path")
    if shim and hasattr(shim, "is_expiry_day") and shim.is_expiry_day != is_expiry_day:
        return shim.is_expiry_day()
    return is_expiry_day()


def evaluate_market_rules(
    position: dict[str, Any],
    live_signals: dict[str, Any],
    current_time: Optional[datetime] = None
) -> Optional[dict[str, Any]]:

    now_ist = current_time or _get_now_ist()
    trade_type = str(position.get("trade_type", "INTRADAY")).upper()
    side = str(position.get("position_side", "BUY_CE")).upper()
    entry_spot = _safe_float(position.get("entry_spot"), 0.0)
    current_spot = _safe_float(live_signals.get("nifty_spot"), 0.0)
    entry_premium = _safe_float(position.get("entry_premium"), 0.0)
    current_premium = _safe_float(position.get("current_premium"), 0.0)
    # 5. Expiry Day Theta Profit Lock (Tuesday only — short sellers)
    # On expiry day, theta collapses dramatically in the last 2 hours.
    # If a short option seller is already at +40%+ profit, lock it before whipsaw.
    if _check_is_expiry_day() and entry_premium > 0 and current_premium > 0:
        is_short = side in ["SHORT_CE", "SHORT_PE"]
        if is_short:
            prem_pnl_pct = ((entry_premium - current_premium) / entry_premium) * 100
            if prem_pnl_pct >= 40.0:
                return {
                    "verdict": "PARTIAL_BOOK_70",
                    "action": f"EXPIRY DAY: Book 70% profit now (premium decayed {prem_pnl_pct:.1f}%). Trail remaining 30% with tight SL.",
                    "confidence": 88,
                    "urgency": "HIGH",
                    "engine": "Deterministic Fast-Path (Expiry Day Theta Lock)",
                    "reasoning": (
                        f"Today is weekly NIFTY expiry day (Tuesday). Premium has decayed {prem_pnl_pct:.1f}% "
                        f"(₹{entry_premium} → ₹{current_premium}). Theta collapse accelerates sharply post-13:00 IST — "
                        f"lock the majority of gains before option expiry volatility whipsaw."
                    ),
                    "trailing_sl": round(current_spot, 2) if current_spot > 0 else round(entry_spot, 2),
                    "is_fast_path": True,
                    "is_expiry_day": True,
                }

    # 6. PCR Extreme — Option Chain Sentiment Warning
    # PCR < 0.70: heavy call writing = bearish market structure (resistance ahead for bulls)
    # PCR > 1.50: heavy put writing = bullish market structure (support for bulls, resistance for bears)
    pcr = _safe_float(live_signals.get("pcr"), 1.05)
    is_bullish_trade = side in ["BUY_CE", "LONG_FUTURES", "SHORT_PE"]
    is_bearish_trade = side in ["BUY_PE", "SHORT_FUTURES", "SHORT_CE"]

    if pcr < 0.70 and is_bullish_trade and current_spot > 0:
        return {
            "verdict": "TRAIL_SL_TIGHT",
            "action": f"Tighten stop-loss immediately. PCR at {pcr:.2f} signals aggressive call writers building a resistance ceiling.",
            "confidence": 78,
            "urgency": "MEDIUM",
            "engine": "Deterministic Fast-Path (PCR Extreme Bear Wall)",
            "reasoning": (
                f"PCR is at {pcr:.2f} (extreme bearish zone < 0.70). Aggressive call writers are building "
                f"a strong resistance ceiling above current spot {current_spot}. Bullish trade momentum at risk. "
                f"Trail stop-loss tightly to protect existing gains."
            ),
            "trailing_sl": round(current_spot * 0.9985, 1),
            "is_fast_path": True,
        }

    if pcr > 1.50 and is_bearish_trade and current_spot > 0:
        return {
            "verdict": "TRAIL_SL_TIGHT",
            "action": f"Tighten stop-loss immediately. PCR at {pcr:.2f} signals heavy put writing forming a support floor.",
            "confidence": 78,
            "urgency": "MEDIUM",
            "engine": "Deterministic Fast-Path (PCR Extreme Bull Floor)",
            "reasoning": (
                f"PCR is at {pcr:.2f} (extreme bullish zone > 1.50). Put writers are forming a strong support floor "
                f"below current spot {current_spot}. Bearish trade momentum at risk. Trail stop-loss tightly."
            ),
            "trailing_sl": round(current_spot * 1.0015, 1),
            "is_fast_path": True,
        }

    # 7. OI Wall Proximity — Spot approaching major resistance/support
    top_oi_call = live_signals.get("top_oi_call_strike")
    top_oi_put = live_signals.get("top_oi_put_strike")

    if current_spot > 0 and top_oi_call and is_bullish_trade:
        top_call_val = _safe_float(top_oi_call, 0.0)
        if top_call_val > 0:
            gap_to_call_wall = top_call_val - current_spot
            if 0 < gap_to_call_wall <= 50:
                return {
                    "verdict": "TRAIL_SL_TIGHT",
                    "action": f"Spot is {gap_to_call_wall:.0f}pts from max OI Call wall at {top_oi_call}. Tighten stop — resistance zone ahead.",
                    "confidence": 80,
                    "urgency": "MEDIUM",
                    "engine": "Deterministic Fast-Path (OI Resistance Wall)",
                    "reasoning": (
                        f"Current NIFTY spot ({current_spot}) is only {gap_to_call_wall:.0f}pts away from the "
                        f"highest Call OI strike at {top_oi_call}, which acts as a strong resistance wall. "
                        f"Bullish momentum likely to stall here. Trail stop-loss to protect gains."
                    ),
                    "trailing_sl": round(current_spot * 0.9985, 1),
                    "is_fast_path": True,
                }

    if current_spot > 0 and top_oi_put and is_bearish_trade:
        top_put_val = _safe_float(top_oi_put, 0.0)
        if top_put_val > 0:
            gap_to_put_wall = current_spot - top_put_val
            if 0 < gap_to_put_wall <= 50:
                return {
                    "verdict": "TRAIL_SL_TIGHT",
                    "action": f"Spot is {gap_to_put_wall:.0f}pts from max OI Put wall at {top_oi_put}. Tighten stop — support zone ahead.",
                    "confidence": 80,
                    "urgency": "MEDIUM",
                    "engine": "Deterministic Fast-Path (OI Support Wall)",
                    "reasoning": (
                        f"Current NIFTY spot ({current_spot}) is only {gap_to_put_wall:.0f}pts above the "
                        f"highest Put OI strike at {top_oi_put}, which acts as a strong support wall. "
                        f"Bearish momentum likely to stall here. Trail stop-loss to protect gains."
                    ),
                    "trailing_sl": round(current_spot * 1.0015, 1),
                    "is_fast_path": True,
                }

    # 8. Contrarian Bull Trap — Retail Euphoria vs Institutional FII Selling
    contrarian_warn = str(
        live_signals.get("contrarian_warning")
        or live_signals.get("contrarian_alert")
        or (live_signals.get("social_sentiment", {}) or {}).get("contrarian_warning")
        or ""
    ).upper()

    if "BULL TRAP" in contrarian_warn and is_bullish_trade:
        prem_gain = 0.0
        if entry_premium > 0 and current_premium > 0:
            is_short = side in ["SHORT_CE", "SHORT_PE", "SHORT_FUTURES"]
            prem_gain = ((entry_premium - current_premium) / entry_premium) * 100 if is_short else ((current_premium - entry_premium) / entry_premium) * 100
        spot_gain = ((current_spot - entry_spot) / entry_spot) * 100 if entry_spot > 0 else 0.0

        is_in_profit = prem_gain >= 15.0 or spot_gain >= 0.15
        target_verdict = "PARTIAL_BOOK_50" if is_in_profit else "TRAIL_SL_TIGHT"
        return {
            "verdict": target_verdict,
            "action": (
                "CONTRARIAN ALERT: Book 50% profits immediately and trail SL tight." if is_in_profit
                else "CONTRARIAN ALERT: Tighten stop-loss immediately. Do NOT add to long positions."
            ),
            "confidence": 85,
            "urgency": "HIGH",
            "engine": "Deterministic Fast-Path (Contrarian Bull Trap)",
            "reasoning": (
                "Contrarian Bull Trap detected: Retail euphoria on social channels clashes with institutional "
                "FII net cash selling. Smart money is distributing into retail liquidity. Protect capital."
            ),
            "trailing_sl": round(current_spot * 0.9985, 1) if current_spot > 0 else round(entry_spot, 1),
            "is_fast_path": True,
            "contrarian_alert": "BULL_TRAP_RISK",
        }

    # 9. Contrarian Bear Trap — Retail Panic vs Institutional FII Buying
    if "BEAR TRAP" in contrarian_warn and is_bearish_trade:
        prem_gain = 0.0
        if entry_premium > 0 and current_premium > 0:
            is_short = side in ["SHORT_CE", "SHORT_PE", "SHORT_FUTURES"]
            prem_gain = ((entry_premium - current_premium) / entry_premium) * 100 if is_short else ((current_premium - entry_premium) / entry_premium) * 100
        spot_gain = ((entry_spot - current_spot) / entry_spot) * 100 if entry_spot > 0 else 0.0

        is_in_profit = prem_gain >= 15.0 or spot_gain >= 0.15
        target_verdict = "PARTIAL_BOOK_50" if is_in_profit else "TRAIL_SL_TIGHT"
        return {
            "verdict": target_verdict,
            "action": (
                "CONTRARIAN ALERT: Book 50% profits on puts immediately and trail SL tight." if is_in_profit
                else "CONTRARIAN ALERT: Tighten stop-loss immediately. Watch for sharp short covering squeeze."
            ),
            "confidence": 85,
            "urgency": "HIGH",
            "engine": "Deterministic Fast-Path (Contrarian Bear Trap)",
            "reasoning": (
                "Contrarian Bear Trap detected: Retail panic and put buying on social channels clash with aggressive "
                "institutional FII buying. High probability of violent short squeeze trapping late retail bears."
            ),
            "trailing_sl": round(current_spot * 1.0015, 1) if current_spot > 0 else round(entry_spot, 1),
            "is_fast_path": True,
            "contrarian_alert": "BEAR_TRAP_RISK",
        }

    return None




    return None
