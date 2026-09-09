"""
exit_fast/scale_out.py — Deterministic scale out plan generator.
"""

from typing import Any

def _build_scale_out_plan(verdict: str, entry_spot: float, trailing_sl: float, is_bullish: bool = True) -> dict[str, str]:
    cost_str = f"{entry_spot:,.0f}" if entry_spot > 0 else "entry cost"
    trail_str = f"{trailing_sl:,.0f}" if trailing_sl > 0 else ("key support" if is_bullish else "key resistance")
    if verdict in ["PARTIAL_BOOK_50", "PARTIAL_BOOK_70", "TRAIL_SL_TO_COST", "TRAIL_SL_TIGHT"]:
        pct = "70%" if verdict == "PARTIAL_BOOK_70" else "50%"
        rem_pct = "30%" if verdict == "PARTIAL_BOOK_70" else "25%"
        runner_pct = "remaining" if verdict == "PARTIAL_BOOK_70" else "25%"
        return {
            "tier_1": f"Book {pct} lots at market to lock in gains (Capital Defender lock).",
            "tier_2": f"Move stop-loss on {rem_pct} lots strictly to {cost_str} for breakeven capital defense.",
            "tier_3": f"Trail {runner_pct} lots at {trail_str} for runner continuation (Momentum Hawk runner).",
        }
    elif verdict in ["FULL_EXIT", "PRE_CLOSE_EXIT", "EMERGENCY_EXIT"]:
        return {
            "tier_1": "Exit 100% open lots immediately at market to halt structural loss.",
            "tier_2": "Cancel all open broker orders in trading terminal.",
            "tier_3": "Do not initiate re-entry until market structure confirms reversal.",
        }
    else:  # HOLD_AND_RIDE or other
        return {
            "tier_1": f"Hold full position while spot remains strictly favorable above {trail_str}.",
            "tier_2": "Prepare to scale out 50% lots immediately if spot tests next psychological resistance.",
            "tier_3": f"Maintain dynamic trailing stop {trail_str} on 15-minute bar closes.",
        }


