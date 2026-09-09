"""
analyzer/core.py — Main analysis orchestrator.

Contains: analyze_news (public entry point).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from .confluence import (
    check_signal_confluence,
    _detect_event_risk,
    _direction_from_scores,
)
from .summary import _extract_key_drivers, _generate_summary, _empty_result
from .pipeline import _score_news_items, _apply_market_signals

logger = logging.getLogger(__name__)


def analyze_news(
    news_items: list[dict],
    gift_nifty_change_pct: float | None = None,
    india_vix: float | None = None,
    india_vix_change_pct: float | None = None,
    pcr: float | None = None,
    global_market_changes: dict[str, float] | None = None,
    fii_net_cr: float | None = None,
) -> dict[str, Any]:
    """
    Main analysis function — fully enhanced version.

    Parameters
    ----------
    news_items : list[dict]
        News dicts from scraper. Must have: headline, snippet, sector,
        category, source, link, published_date.
    gift_nifty_change_pct : float | None
        GIFT Nifty / SGX Nifty % change vs previous close.
    india_vix : float | None; india_vix_change_pct : float | None
        VIX level and day % change.
    pcr : float | None
        Put-Call Ratio (total OI based).
    global_market_changes : dict | None
        Dict of market → % change (sp500, nasdaq, dow, nikkei, hangseng, dax, sgx).

    Returns
    -------
    dict  Complete prediction output with all signal details.
    """
    if not news_items:
        return _empty_result("No news data available for analysis.")

    (
        analyzed_news, total_bull_score, total_bear_score,
        all_bull_factors, all_bear_factors, combined_text, sector_sentiment
    ) = _score_news_items(news_items)

    (
        total_bull_score, total_bear_score, all_bull_factors, all_bear_factors,
        vix_result, vix_confidence_penalty,
        social_sentiment, normalization_factor,
        gift_bull, gift_bear, global_bull, global_bear,
        gift_direction, global_direction,
        pcr_bull, pcr_bear,
    ) = _apply_market_signals(
        total_bull_score, total_bear_score, all_bull_factors, all_bear_factors,
        gift_nifty_change_pct, india_vix, india_vix_change_pct, pcr,
        global_market_changes, news_items, fii_net_cr,
    )

    event_risk = _detect_event_risk(combined_text)
    score_diff = total_bull_score - total_bear_score
    score_total = total_bull_score + total_bear_score
    news_direction = _direction_from_scores(total_bull_score, total_bear_score)

    if score_total == 0:
        prediction, news_sentiment, raw_confidence = "FLAT", "MIXED", 30
    else:
        ratio = abs(score_diff) / score_total
        if score_diff > 5 and ratio > 0.20:
            prediction, news_sentiment = "GAP UP", "BULLISH"
        elif score_diff < -5 and ratio > 0.20:
            prediction, news_sentiment = "GAP DOWN", "BEARISH"
        else:
            prediction, news_sentiment = "FLAT", "MIXED"
        raw_confidence = min(85, int(30 + ratio * 70))

    confluence = check_signal_confluence(gift_direction, global_direction, news_direction)
    raw_confidence += confluence["confidence_modifier"] - vix_confidence_penalty

    if gift_nifty_change_pct is not None:
        if prediction == "GAP UP" and gift_nifty_change_pct > 0.5:
            raw_confidence = min(92, raw_confidence + 10)
        elif prediction == "GAP DOWN" and gift_nifty_change_pct < -0.5:
            raw_confidence = min(92, raw_confidence + 10)
        elif prediction == "GAP UP" and gift_nifty_change_pct < -0.5:
            raw_confidence = max(20, raw_confidence - 15)
        elif prediction == "GAP DOWN" and gift_nifty_change_pct > 0.5:
            raw_confidence = max(20, raw_confidence - 15)

    if event_risk == "HIGH":
        raw_confidence = max(20, raw_confidence - 20)
    elif event_risk == "MEDIUM":
        raw_confidence = max(25, raw_confidence - 10)
    if news_sentiment == "MIXED":
        raw_confidence = min(raw_confidence, 50)

    confidence = min(92, max(10, raw_confidence))
    no_trade = (
        event_risk == "HIGH" or confidence < 35
        or confluence["dominant_direction"] == "MIXED"
        or confluence["agree_count"] < 2
    )
    if no_trade:
        btst_bias = "NO TRADE"
    elif prediction == "GAP UP":
        btst_bias = "BUY CE"
    elif prediction == "GAP DOWN":
        btst_bias = "BUY PE"
    else:
        btst_bias = "NO TRADE"

    analyzed_news.sort(key=lambda x: max(x["bullish_score"], x["bearish_score"]), reverse=True)
    major_news = [
        {k: n[k] for k in (
            "headline", "source", "link", "published_date", "sector", "impact",
            "importance", "impact_score", "strength_level", "strength_badge",
            "bullish_score", "bearish_score",
        )}
        for n in analyzed_news[:20]
    ]

    key_drivers = _extract_key_drivers(
        total_bull_score, total_bear_score, all_bull_factors, all_bear_factors,
        event_risk, sector_sentiment, gift_nifty_change_pct, confluence,
    )

    sector_summary = [
        {
            "sector": sec,
            "sentiment": "BULLISH" if (data["bullish"] - data["bearish"]) > 1
                         else ("BEARISH" if (data["bullish"] - data["bearish"]) < -1 else "NEUTRAL"),
            "bullish_score": round(data["bullish"], 1),
            "bearish_score": round(data["bearish"], 1),
            "news_count": data["count"],
        }
        for sec, data in sorted(sector_sentiment.items(), key=lambda x: x[1]["count"], reverse=True)
    ]

    all_bull_factors.sort(key=lambda x: x.get("score", 0.0) if isinstance(x, dict) else 0.0, reverse=True)
    all_bear_factors.sort(key=lambda x: x.get("score", 0.0) if isinstance(x, dict) else 0.0, reverse=True)

    seen_bull: set[str] = set()
    bullish_factors: list[str] = []
    for f in all_bull_factors:
        txt = f["text"] if isinstance(f, dict) else str(f)
        if txt not in seen_bull:
            seen_bull.add(txt)
            bullish_factors.append(txt)

    seen_bear: set[str] = set()
    bearish_factors: list[str] = []
    for f in all_bear_factors:
        txt = f["text"] if isinstance(f, dict) else str(f)
        if txt not in seen_bear:
            seen_bear.add(txt)
            bearish_factors.append(txt)

    final_summary = _generate_summary(
        prediction, confidence, news_sentiment,
        total_bull_score, total_bear_score,
        bullish_factors, bearish_factors,
        event_risk, confluence, gift_nifty_change_pct, vix_result,
    )

    return {
        "prediction": prediction,
        "confidence": confidence,
        "btst_bias": btst_bias,
        "news_sentiment": news_sentiment,
        "major_news": major_news,
        "all_news": analyzed_news,
        "bullish_factors": bullish_factors[:10],
        "bearish_factors": bearish_factors[:10],
        "event_risk": event_risk,
        "key_drivers": key_drivers,
        "sector_summary": sector_summary,
        "final_summary": final_summary,
        "confluence": confluence,
        "scores": {
            "total_bullish": round(total_bull_score, 1),
            "total_bearish": round(total_bear_score, 1),
            "net_score": round(total_bull_score - total_bear_score, 1),
            "gift_nifty_bull": round(gift_bull, 1),
            "gift_nifty_bear": round(gift_bear, 1),
            "global_bull": round(global_bull, 1),
            "global_bear": round(global_bear, 1),
            "pcr_bull": round(pcr_bull, 1),
            "pcr_bear": round(pcr_bear, 1),
            "normalization_factor": round(normalization_factor, 3),
        },
        "market_signals": {
            "gift_nifty_change_pct": gift_nifty_change_pct,
            "india_vix": india_vix,
            "india_vix_change_pct": india_vix_change_pct,
            "india_vix_risk_level": vix_result.get("risk_level"),
            "pcr": pcr,
            "global_markets": global_market_changes or {},
        },
        "social_sentiment": social_sentiment,
        "analysis_timestamp": datetime.now().strftime("%d %b %Y, %I:%M %p IST"),
        "total_news_analyzed": len(news_items),
    }
