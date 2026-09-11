"""
exit_fast/rules.py — Unified fast-path rule evaluation engine.
"""

from datetime import datetime
from typing import Any, Optional

from .rules_critical import evaluate_critical_rules
from .rules_market import evaluate_market_rules
from .rules_new import evaluate_new_rules


def _evaluate_fast_path_rules(
    position: dict[str, Any],
    live_signals: dict[str, Any],
    current_time: Optional[datetime] = None
) -> Optional[dict[str, Any]]:
    """Evaluate deterministic safety rules in order of quantitative priority."""
    # 1. Critical stops & emergency conditions (Pre-close, VIX shock, Spot invalidation, Hard stop)
    critical_result = evaluate_critical_rules(position, live_signals, current_time)
    if critical_result is not None:
        return critical_result

    # 2. Market structure, OI walls, theta, and contrarian traps
    market_result = evaluate_market_rules(position, live_signals, current_time)
    if market_result is not None:
        return market_result

    # 3. Advanced quantitative rules (MFE Lock, MAE Bleed, IV Crush, Stagnation Clock, COI Velocity, BTST Gap)
    return evaluate_new_rules(position, live_signals, current_time)
