"""
exit_fast/core.py — Main fast-path evaluation orchestrator.
"""

import logging
from datetime import datetime
from typing import Any, Optional

from .constants import _safe_float
from .scale_out import _build_scale_out_plan
from .rules import _evaluate_fast_path_rules

logger = logging.getLogger(__name__)

def evaluate_fast_path(position: dict[str, Any], live_signals: dict[str, Any], current_time: Optional[datetime] = None) -> Optional[dict[str, Any]]:
    """
    Deterministic safety engine executing in <10ms.
    Evaluates hard circuit breakers in priority order:
    1. 15:15 IST Mandatory Pre-Close Square-Off for Intraday Trades
    2. Extreme India VIX Spike (>= 4.0% intraday jump)
    3. Severe Adverse Spot Invalidation (>= 0.60% adverse underlying move)
    4. Hard Stop Loss Hit on Option Premium (e.g. >= 25-30% loss)
    """
    res = _evaluate_fast_path_rules(position, live_signals, current_time=current_time)
    if res is not None:
        if "scale_out_plan" not in res:
            side = str(position.get("position_side", "BUY_CE")).upper()
            is_bullish = side in ["BUY_CE", "LONG_FUTURES", "SHORT_PE"]
            entry_spot = _safe_float(position.get("entry_spot"), 0.0)
            trailing_sl = _safe_float(res.get("trailing_sl"), 0.0)
            res["scale_out_plan"] = _build_scale_out_plan(
                res.get("verdict", "FULL_EXIT"), entry_spot, trailing_sl, is_bullish
            )
        return res
    return None


