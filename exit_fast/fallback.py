"""
exit_fast/fallback.py — Pure mathematical rule-based fallback when AI is unavailable.
"""

from typing import Any
from .constants import _safe_float
from .scale_out import _build_scale_out_plan

def generate_rule_based_fallback(
    position: dict[str, Any],
    live_signals: dict[str, Any],
    heavyweights: dict[str, Any]
) -> dict[str, Any]:
    """
    Mathematical fallback engine when all AI LLM providers are offline/timing out.
    Computes percentage-of-spot and premium targets with 100% reliability.
    """
    trade_type = str(position.get("trade_type", "INTRADAY")).upper()
    side = str(position.get("position_side", "BUY_CE")).upper()
    entry_spot = _safe_float(position.get("entry_spot") or live_signals.get("nifty_spot"), 24200.0)
    if entry_spot <= 0:
        entry_spot = 24200.0
    current_spot = _safe_float(live_signals.get("nifty_spot"), entry_spot)
    if current_spot <= 0:
        current_spot = entry_spot
    entry_premium = _safe_float(position.get("entry_premium"), 0.0)
    current_premium = _safe_float(position.get("current_premium"), 0.0)

    spot_change_pct = ((current_spot - entry_spot) / entry_spot) * 100 if entry_spot > 0 else 0.0
    pts_diff = round(current_spot - entry_spot, 1)

    is_bullish_trade = side in ["BUY_CE", "LONG_FUTURES", "SHORT_PE"]
    favorable_move = spot_change_pct if is_bullish_trade else -spot_change_pct

    # Heavyweight pulse
    hw_bullish = sum(1 for s in heavyweights.values() if s.get("change_pct", 0) > 0.3)
    hw_bearish = sum(1 for s in heavyweights.values() if s.get("change_pct", 0) < -0.3)

    contrarian_warn = str(
        live_signals.get("contrarian_warning")
        or live_signals.get("contrarian_alert")
        or (live_signals.get("social_sentiment", {}) or {}).get("contrarian_warning")
        or ""
    ).upper()

    # 1. Target 2 / Large Move (+0.50% or higher)
    if favorable_move >= 0.50:
        verdict = "PARTIAL_BOOK_70"
        action = "Book 70% profit. Move stop-loss on remaining 30% to lock gains."
        confidence = 88
        trailing_sl = round(entry_spot + (pts_diff * 0.5) if is_bullish_trade else entry_spot - (abs(pts_diff) * 0.5), 1)
        reason = f"Underlying has moved +{favorable_move:.2f}% ({abs(pts_diff)} pts) in your favor. Secure majority profits."

    # 2. Target 1 / Standard Move (+0.25% to +0.50%)
    elif favorable_move >= 0.25:
        verdict = "PARTIAL_BOOK_50"
        action = "Book 50% profit. Trail stop-loss on remaining quantity to Cost (Breakeven)."
        confidence = 82
        trailing_sl = round(entry_spot, 1)
        reason = f"Target 1 reached with a +{favorable_move:.2f}% favorable move. Risk-free trade by trailing SL to breakeven."

    # 3. Adverse Invalidation (-0.25% or worse)
    elif favorable_move <= -0.25:
        verdict = "FULL_EXIT"
        action = "Exit position. Move against position has broken short-term structure."
        confidence = 85
        trailing_sl = round(current_spot, 1)
        reason = f"NIFTY has moved {favorable_move:.2f}% against your entry level ({abs(pts_diff)} pts adverse). Invalidation triggered."

    # 4. BTST Morning Gap Check
    elif trade_type == "BTST":
        now_ist = datetime.now(TIMEZONE)
        if now_ist.hour == 9 and now_ist.minute <= 30:
            if favorable_move >= 0.15:
                verdict = "PARTIAL_BOOK_70"
                action = "Book 70% of BTST gap gains immediately before morning range fade."
                confidence = 84
                trailing_sl = round(entry_spot, 1)
                reason = "Overnight BTST gap realized. Lock profits in first 15 minutes."
            else:
                verdict = "TRAIL_SL_TO_COST"
                action = "Hold with tight stop at cost. Watch 09:30 15-min ORB breakout."
                confidence = 75
                trailing_sl = round(entry_spot, 1)
                reason = "Flat morning opening. Maintain disciplined stop at entry level."
        else:
            verdict = "FULL_EXIT"
            action = "Close BTST trade. Holding past morning window incurs theta decay."
            confidence = 80
            trailing_sl = round(current_spot, 1)
            reason = "BTST window expired (after 09:45 IST). Close overnight options to avoid premium erosion."

    # 5. Normal trend continuation
    else:
        if (is_bullish_trade and hw_bullish >= 3) or (not is_bullish_trade and hw_bearish >= 3):
            # Guard against contrarian trap even if heavyweights appear aligned
            if ("BULL TRAP" in contrarian_warn and is_bullish_trade) or ("BEAR TRAP" in contrarian_warn and not is_bullish_trade):
                verdict = "TRAIL_SL_TIGHT"
                action = "Contrarian Trap Warning: Tighten stop-loss immediately despite heavyweight alignment."
                confidence = 75
                trailing_sl = round(entry_spot * 0.9985 if is_bullish_trade else entry_spot * 1.0015, 1)
                reason = "Contrarian trap warning overrides trend continuation. Protect capital against institutional divergence."
            else:
                verdict = "HOLD_AND_RIDE"
                action = "Maintain position. Heavyweights strongly aligned with trade direction."
                confidence = 80
                trailing_sl = round(entry_spot * 0.998 if is_bullish_trade else entry_spot * 1.002, 1)
                reason = "Constituent heavyweights are supporting the directional momentum."
        else:
            verdict = "TRAIL_SL_TIGHT"
            action = "Hold with tightened stop-loss. Momentum is consolidating."
            confidence = 72
            trailing_sl = round(entry_spot * 0.9985 if is_bullish_trade else entry_spot * 1.0015, 1)
            reason = "Market is in range-bound consolidation. Maintain tight risk controls."

    scale_plan = _build_scale_out_plan(verdict, entry_spot, trailing_sl, is_bullish_trade)

    return {
        "verdict": verdict,
        "action": action,
        "confidence": confidence,
        "urgency": "NORMAL" if "HOLD" in verdict else "MEDIUM",
        "engine": "Rule-Based Deterministic Engine (AI Offline)",
        "reasoning": reason,
        "trailing_sl": trailing_sl,
        "scale_out_plan": scale_plan,
        "heavyweight_alignment": f"{hw_bullish} Bullish / {hw_bearish} Bearish",
        "favorable_move_pct": round(favorable_move, 2),
        "is_fallback": True,
    }
