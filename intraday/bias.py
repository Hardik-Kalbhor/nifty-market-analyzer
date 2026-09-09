"""
intraday/bias.py — Intraday trading bias and strategy generator.
"""

from typing import Any

def _generate_intraday_bias(
    news_score_diff: float,
    event_risk: str,
    volatility_level: str,
    gap_prediction: str,
) -> dict:
    """Generate the intraday trading bias and actionable levels."""
    total_score = news_score_diff / 5  # Normalize news score

    if event_risk == "HIGH" or volatility_level == "EXTREME":
        bias = "VOLATILE — AVOID"
        icon = "⚡"
        confidence = 25
    elif total_score > 5:
        bias = "STRONGLY BULLISH"
        icon = "🟢🟢"
        confidence = min(80, 50 + int(total_score * 3))
    elif total_score > 2:
        bias = "BULLISH"
        icon = "🟢"
        confidence = min(70, 40 + int(total_score * 4))
    elif total_score > 0:
        bias = "MILDLY BULLISH"
        icon = "🟡🟢"
        confidence = min(55, 35 + int(total_score * 5))
    elif total_score > -2:
        bias = "MILDLY BEARISH"
        icon = "🟡🔴"
        confidence = min(55, 35 + int(abs(total_score) * 5))
    elif total_score > -5:
        bias = "BEARISH"
        icon = "🔴"
        confidence = min(70, 40 + int(abs(total_score) * 4))
    else:
        bias = "STRONGLY BEARISH"
        icon = "🔴🔴"
        confidence = min(80, 50 + int(abs(total_score) * 3))

    # Build strategy
    strategies = []
    if "BULLISH" in bias:
        strategies.append("Buy CE (Call Options) on morning dips")
        strategies.append("Sell PE (Put Options) for premium collection")
        if gap_prediction == "GAP UP":
            strategies.append("Trail SL at opening price — let winners run")
        elif gap_prediction == "GAP DOWN":
            strategies.append("Buy on gap down — anticipate recovery")
    elif "BEARISH" in bias:
        strategies.append("Buy PE (Put Options) on morning bounce")
        strategies.append("Sell CE (Call Options) for premium collection")
        if gap_prediction == "GAP DOWN":
            strategies.append("Trail SL at opening price — let winners run")
        elif gap_prediction == "GAP UP":
            strategies.append("Sell on gap up — anticipate reversal")
    else:
        strategies.append("Wait for directional clarity before taking trades")
        strategies.append("If forced to trade, sell straddle/strangle for premium")
        strategies.append("Keep position sizes very small")

    return {
        "bias": bias,
        "icon": icon,
        "confidence": confidence,
        "strategies": strategies,
        "total_score": round(total_score, 1),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main Public API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


