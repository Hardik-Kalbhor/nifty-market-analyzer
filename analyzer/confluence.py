"""
analyzer/confluence.py — Signal confluence and helper logic.

Contains: check_signal_confluence, _determine_impact, _detect_event_risk,
_direction_from_scores.
"""

from typing import Any
from .constants import EVENT_RISK_KEYWORDS


def check_signal_confluence(
    gift_direction: str | None,
    global_direction: str | None,
    news_direction: str,
) -> dict[str, Any]:
    """
    Count how many independent signals agree on direction.
    High confluence → higher confidence & trade recommendation.
    Low confluence  → mixed signals → NO TRADE.

    Returns:
        dict with count, direction, confidence_modifier, recommendation
    """
    signals = [gift_direction, global_direction, news_direction]
    active_signals = [s for s in signals if s is not None]

    bull_count = active_signals.count("BULLISH")
    bear_count = active_signals.count("BEARISH")

    if bull_count > bear_count:
        dominant = "BULLISH"
        agree_count = bull_count
    elif bear_count > bull_count:
        dominant = "BEARISH"
        agree_count = bear_count
    else:
        dominant = "MIXED"
        agree_count = 0

    total = len(active_signals)

    if agree_count == total and total >= 3:
        conf_modifier = +15
        recommendation = "STRONG — all signals aligned"
    elif agree_count >= 3:
        conf_modifier = +8
        recommendation = "GOOD — majority signals aligned"
    elif agree_count == 2 and total >= 3:
        conf_modifier = -10
        recommendation = "WEAK — signals diverging, reduce size"
    else:
        conf_modifier = -20
        recommendation = "NO TRADE — signals conflicting"

    return {
        "bull_count": bull_count,
        "bear_count": bear_count,
        "dominant_direction": dominant,
        "agree_count": agree_count,
        "total_signals": total,
        "confidence_modifier": conf_modifier,
        "recommendation": recommendation,
    }


def _determine_impact(bull_score: float, bear_score: float) -> str:
    diff = bull_score - bear_score
    if diff > 1:
        return "BULLISH"
    elif diff < -1:
        return "BEARISH"
    return "NEUTRAL"


def _detect_event_risk(all_text: str) -> str:
    text_lower = all_text.lower()
    event_count = sum(1 for kw in EVENT_RISK_KEYWORDS if kw in text_lower)
    if event_count >= 3:
        return "HIGH"
    elif event_count >= 1:
        return "MEDIUM"
    return "LOW"


def _direction_from_scores(bull: float, bear: float) -> str:
    diff = bull - bear
    if diff > 3:
        return "BULLISH"
    elif diff < -3:
        return "BEARISH"
    return "NEUTRAL"
