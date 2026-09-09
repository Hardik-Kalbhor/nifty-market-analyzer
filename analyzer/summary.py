"""
analyzer/summary.py — Key driver extraction, narrative summary generation, and empty result factory.

Contains: _extract_key_drivers, _generate_summary, _empty_result.
"""

from datetime import datetime
from typing import Any


def _extract_key_drivers(
    bull_total: float,
    bear_total: float,
    bull_factors: list,
    bear_factors: list,
    event_risk: str,
    sector_sentiment: dict,
    gift_nifty_change_pct: float | None = None,
    confluence: dict | None = None,
) -> list[str]:
    drivers: list[str] = []

    if gift_nifty_change_pct is not None:
        direction = "up" if gift_nifty_change_pct > 0 else "down"
        drivers.append(f"GIFT Nifty {direction} {gift_nifty_change_pct:+.2f}% — primary gap predictor")

    if bull_total > bear_total:
        drivers.append(f"Net bullish sentiment (score: +{round(bull_total - bear_total, 1)})")
    elif bear_total > bull_total:
        drivers.append(f"Net bearish sentiment (score: {round(bull_total - bear_total, 1)})")
    else:
        drivers.append("Balanced signals — no directional edge")

    if confluence:
        drivers.append(
            f"Signal confluence: {confluence['agree_count']}/{confluence['total_signals']} "
            f"signals agree ({confluence['recommendation']})"
        )

    sorted_sectors = sorted(
        sector_sentiment.items(),
        key=lambda x: abs(x[1]["bullish"] - x[1]["bearish"]),
        reverse=True,
    )
    for sec, data in sorted_sectors[:2]:
        net = data["bullish"] - data["bearish"]
        if abs(net) > 1:
            direction = "bullish" if net > 0 else "bearish"
            drivers.append(f"{sec} sector showing {direction} signals")

    if event_risk == "HIGH":
        drivers.append("⚠️ High event risk — major economic event upcoming")
    elif event_risk == "MEDIUM":
        drivers.append("Moderate event risk — watch for volatility")

    if bull_factors:
        b_text = bull_factors[0]["text"] if isinstance(bull_factors[0], dict) else str(bull_factors[0])
        drivers.append(f"Top bullish: {b_text.split(' (')[0]}")
    if bear_factors:
        br_text = bear_factors[0]["text"] if isinstance(bear_factors[0], dict) else str(bear_factors[0])
        drivers.append(f"Top bearish risk: {br_text.split(' (')[0]}")

    return drivers[:8]


def _generate_summary(
    prediction: str,
    confidence: int,
    sentiment: str,
    bull_score: float,
    bear_score: float,
    bull_factors: list,
    bear_factors: list,
    event_risk: str,
    confluence: dict | None = None,
    gift_nifty_change_pct: float | None = None,
    vix_result: dict | None = None,
) -> str:
    parts: list[str] = []

    if gift_nifty_change_pct is not None:
        direction = "up" if gift_nifty_change_pct > 0 else "down"
        parts.append(
            f"GIFT Nifty is {direction} {gift_nifty_change_pct:+.2f}%, "
            f"indicating {'positive' if gift_nifty_change_pct > 0 else 'negative'} opening bias."
        )

    if vix_result and vix_result.get("risk_level") in ("HIGH", "MEDIUM"):
        parts.append(f"⚠️ {vix_result['factor']}.")

    if prediction == "GAP UP":
        parts.append(
            f"Overall market sentiment is BULLISH with a net positive score of "
            f"+{round(bull_score - bear_score, 1)}."
        )
    elif prediction == "GAP DOWN":
        parts.append(
            f"Overall market sentiment is BEARISH with a net negative score of "
            f"{round(bull_score - bear_score, 1)}."
        )
    else:
        parts.append("Market sentiment is MIXED — bullish and bearish signals are balanced.")

    if confluence:
        parts.append(
            f"Signal confluence: {confluence['agree_count']} of "
            f"{confluence['total_signals']} signals agree — {confluence['recommendation']}."
        )

    if bull_factors:
        b_text = bull_factors[0]["text"] if isinstance(bull_factors[0], dict) else str(bull_factors[0])
        parts.append(f"Key bullish driver: {b_text.split(' (')[0]}.")
    if bear_factors:
        br_text = bear_factors[0]["text"] if isinstance(bear_factors[0], dict) else str(bear_factors[0])
        parts.append(f"Key bearish risk: {br_text.split(' (')[0]}.")

    if event_risk == "HIGH":
        parts.append(
            "⚠️ HIGH EVENT RISK — major event imminent (RBI/Fed/Budget/Data release). "
            "Confidence reduced. Consider avoiding BTST trades."
        )
    elif event_risk == "MEDIUM":
        parts.append("Moderate event risk present. Maintain smaller positions.")

    parts.append(f"NIFTY next-day opening prediction: {prediction} (Confidence: {confidence}%).")

    return " ".join(parts)


def _empty_result(reason: str) -> dict[str, Any]:
    return {
        "prediction": "FLAT",
        "confidence": 10,
        "btst_bias": "NO TRADE",
        "news_sentiment": "MIXED",
        "major_news": [],
        "all_news": [],
        "bullish_factors": [],
        "bearish_factors": [],
        "event_risk": "LOW",
        "key_drivers": [reason],
        "sector_summary": [],
        "final_summary": reason,
        "confluence": {},
        "scores": {
            "total_bullish": 0, "total_bearish": 0, "net_score": 0,
            "gift_nifty_bull": 0, "gift_nifty_bear": 0,
            "global_bull": 0, "global_bear": 0,
            "pcr_bull": 0, "pcr_bear": 0,
            "normalization_factor": 1.0,
        },
        "market_signals": {},
        "social_sentiment": {
            "retail_sentiment_score": 0,
            "retail_mood": "NEUTRAL / NO DATA",
            "sample_count": 0,
            "contrarian_warning": "",
            "top_buzz": [],
            "source_breakdown": {"reddit": 0, "telegram": 0, "twitter": 0},
        },
        "analysis_timestamp": datetime.now().strftime("%d %b %Y, %I:%M %p IST"),
        "total_news_analyzed": 0,
    }
