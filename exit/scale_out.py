"""
exit/scale_out.py — Tiered scale out plan generation.
"""

from __future__ import annotations
from typing import Any
from exit_fast.constants import _safe_float

def generate_tiered_scale_out_plan(
    verdict: str,
    position: dict[str, Any] | None = None,
    live_spot: float = 0.0,
    trailing_sl: float = 0.0,
) -> dict[str, str]:
    """
    Generate structured, tiered lot scale-out plan (Tier 1: profit lock, Tier 2: breakeven trail, Tier 3: trend runner).
    """
    pos = position or {}
    side = str(pos.get("position_side", "BUY_CE")).upper()
    is_bullish = side in ["BUY_CE", "LONG_FUTURES", "SHORT_PE"]
    entry_spot = _safe_float(pos.get("entry_spot") or pos.get("entry_price"), default=0.0)
    trailing_sl = _safe_float(trailing_sl, default=0.0)
    cost_str = f"{entry_spot:,.0f}" if entry_spot > 0 else "entry cost"
    trail_str = f"{trailing_sl:,.0f}" if trailing_sl > 0 else ("key support" if is_bullish else "key resistance")

    if verdict in ["PARTIAL_BOOK_50", "PARTIAL_BOOK_70", "TRAIL_SL_TO_COST", "TRAIL_SL_TIGHT"]:
        pct = "70%" if verdict == "PARTIAL_BOOK_70" else "50%"
        rem_pct = "30%" if verdict == "PARTIAL_BOOK_70" else "25%"
        runner_pct = "remaining" if verdict == "PARTIAL_BOOK_70" else "25%"
        return {
            "tier_1": f"Book {pct} lots at market to lock in accumulated profits (Capital Defender lock).",
            "tier_2": f"Move stop-loss on {rem_pct} lots strictly to {cost_str} to guarantee zero-risk status.",
            "tier_3": f"Trail {runner_pct} lots at {trail_str} for trend runner continuation (Momentum Hawk runner).",
        }
    elif verdict in ["FULL_EXIT", "PRE_CLOSE_EXIT", "EMERGENCY_EXIT"]:
        return {
            "tier_1": "Exit 100% open lots immediately at market to halt structural loss.",
            "tier_2": "Cancel all pending limit targets and stop orders in trading terminal.",
            "tier_3": "Do not initiate re-entry until market structure confirms reversal.",
        }
    else:  # HOLD_AND_RIDE
        return {
            "tier_1": f"Hold full position while spot remains strictly favorable above {trail_str}.",
            "tier_2": "Prepare to scale out 50% lots immediately if spot tests next psychological resistance.",
            "tier_3": f"Maintain dynamic trailing stop {trail_str} on 15-minute bar closes.",
        }


