"""
intraday/volatility.py — Volatility estimation and expected point-range calculation.
"""

from typing import Any
from .market_phase import _get_market_phase

def _estimate_volatility(
    event_risk: str,
    news_count: int,
    sentiment_score_diff: float,
) -> dict:
    """Estimate intraday volatility level."""
    vol_score = 0

    # Base volatility from news volume
    if news_count > 80:
        vol_score += 2
    elif news_count > 40:
        vol_score += 1

    # Event risk
    if event_risk == "HIGH":
        vol_score += 3
    elif event_risk == "MEDIUM":
        vol_score += 1

    # News sentiment divergence
    if abs(sentiment_score_diff) > 20:
        vol_score += 3
    elif abs(sentiment_score_diff) > 10:
        vol_score += 2
    elif abs(sentiment_score_diff) > 5:
        vol_score += 1

    # Apply market phase factor
    phase = _get_market_phase()
    vol_score = int(vol_score * phase["volatility_factor"])

    # Classify
    if vol_score >= 8:
        level = "EXTREME"
        expected_range = "200-400 pts"
        nifty_range_pct = "1.0-2.0%"
    elif vol_score >= 5:
        level = "HIGH"
        expected_range = "100-200 pts"
        nifty_range_pct = "0.5-1.0%"
    elif vol_score >= 3:
        level = "MODERATE"
        expected_range = "50-100 pts"
        nifty_range_pct = "0.25-0.5%"
    else:
        level = "LOW"
        expected_range = "30-50 pts"
        nifty_range_pct = "0.1-0.25%"

    return {
        "level": level,
        "score": vol_score,
        "expected_range": expected_range,
        "nifty_range_pct": nifty_range_pct,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Intraday Bias + Strategy
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

