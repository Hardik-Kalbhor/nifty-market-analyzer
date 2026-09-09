"""
intraday/core.py — Main intraday prediction orchestrator and summary generator.
"""

import logging
from datetime import datetime
from typing import Any

import debate_engine
from .constants import IST
from .market_phase import _get_market_phase
from .patterns import _detect_intraday_pattern
from .volatility import _estimate_volatility
from .bias import _generate_intraday_bias

logger = logging.getLogger(__name__)

def generate_intraday_prediction(
    news_sentiment: str,
    gap_prediction: str,
    event_risk: str,
    scores: dict,
    bullish_factors: list[str],
    bearish_factors: list[str],
    sector_summary: list[dict],
) -> dict[str, Any]:
    """
    Generate complete intraday prediction using available data.

    Parameters
    ----------
    news_sentiment : str
        Overall news sentiment (BULLISH/BEARISH/MIXED).
    gap_prediction : str
        BTST gap prediction (GAP UP/GAP DOWN/FLAT).
    event_risk : str
        Event risk level (HIGH/MEDIUM/LOW).
    scores : dict
        News sentiment scores from analyzer.
    bullish_factors, bearish_factors : list[str]
        Key factors from the news analyzer.
    sector_summary : list[dict]
        Sector-wise sentiment breakdown.

    Returns
    -------
    dict
        Complete intraday prediction with bias, pattern, strategy, and more.
    """
    logger.info("Generating intraday prediction...")

    # ── Market phase ──
    market_phase = _get_market_phase()

    # ── Sentiment score ──
    score_diff = scores.get("net_score", 0)
    news_count = scores.get("total_bullish", 0) + scores.get("total_bearish", 0)

    # ── Intraday pattern ──
    intraday_pattern = _detect_intraday_pattern(
        gap_prediction, news_sentiment, score_diff, event_risk,
    )

    # ── Volatility estimation ──
    volatility = _estimate_volatility(
        event_risk, int(news_count), score_diff,
    )

    # ── Intraday bias ──
    intraday_bias = _generate_intraday_bias(
        score_diff, event_risk, volatility["level"], gap_prediction,
    )

    # ── Key intraday drivers ──
    intraday_drivers = []

    # Add news-based drivers
    if news_sentiment == "BULLISH":
        intraday_drivers.append("News sentiment strongly bullish — supports upside intraday")
    elif news_sentiment == "BEARISH":
        intraday_drivers.append("News sentiment strongly bearish — supports downside intraday")
    else:
        intraday_drivers.append("News sentiment mixed — choppy intraday expected")

    if event_risk == "HIGH":
        intraday_drivers.append("⚠️ HIGH EVENT RISK — Market can whipsaw violently. Reduce position sizes!")

    # Add score context
    if abs(score_diff) > 15:
        direction = "bullish" if score_diff > 0 else "bearish"
        intraday_drivers.append(f"Strong {direction} sentiment score ({score_diff:+.1f}) — trending day likely")
    elif abs(score_diff) > 5:
        direction = "bullish" if score_diff > 0 else "bearish"
        intraday_drivers.append(f"Moderate {direction} sentiment score ({score_diff:+.1f})")

    # Add sector highlights relevant to intraday
    bullish_sectors = [s["sector"] for s in sector_summary if s.get("sentiment") == "BULLISH"]
    bearish_sectors = [s["sector"] for s in sector_summary if s.get("sentiment") == "BEARISH"]

    if bullish_sectors:
        intraday_drivers.append(f"Bullish sectors for intraday: {', '.join(bullish_sectors[:3])}")
    if bearish_sectors:
        intraday_drivers.append(f"Bearish sectors for intraday: {', '.join(bearish_sectors[:3])}")

    # ── Intraday summary ──
    summary = _generate_intraday_summary(
        intraday_bias, intraday_pattern, market_phase,
        volatility, event_risk, score_diff,
    )

    return {
        "intraday_bias": intraday_bias,
        "intraday_pattern": intraday_pattern,
        "market_phase": market_phase,
        "volatility": volatility,
        "intraday_drivers": intraday_drivers[:8],
        "intraday_summary": summary,
    }


def _generate_intraday_summary(
    bias: dict,
    pattern: dict,
    phase: dict,
    volatility: dict,
    event_risk: str,
    score_diff: float,
) -> str:
    """Generate a human-readable intraday summary."""
    parts = []

    # Sentiment summary
    if score_diff > 5:
        parts.append(f"News sentiment is bullish with a net positive score of +{score_diff:.1f}.")
    elif score_diff < -5:
        parts.append(f"News sentiment is bearish with a net negative score of {score_diff:.1f}.")
    else:
        parts.append("News sentiment is mixed with no clear directional bias.")

    # Bias
    parts.append(f"Intraday bias is {bias['bias']} with {bias['confidence']}% confidence.")

    # Pattern
    parts.append(f"Expected pattern: {pattern['pattern']} — {pattern['description']}")

    # Volatility
    parts.append(
        f"Expected volatility: {volatility['level']} "
        f"(NIFTY range: {volatility['expected_range']}, ~{volatility['nifty_range_pct']})."
    )

    # Market phase
    parts.append(f"Current market phase: {phase['phase']} — {phase['description']}")

    # Event risk warning
    if event_risk == "HIGH":
        parts.append(
            "⚠️ HIGH EVENT RISK: Major event imminent. Markets may swing wildly. "
            "Intraday traders should use strict stop-losses and reduced position sizes."
        )

    return " ".join(parts)
