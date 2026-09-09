"""
analyzer/pipeline.py — Per-item scoring loop and market-signal application helpers.

Contains: _score_news_items, _apply_market_signals.
"""

from typing import Any
from .constants import SECTOR_WEIGHT, CATEGORY_IMPORTANCE
from .sentiment import _score_sentiment, _get_recency_multiplier
from .scoring import score_gift_nifty, score_india_vix, score_pcr, score_global_markets
from .confluence import _determine_impact
from .social import _compute_social_sentiment

def _score_news_items(news_items: list[dict]) -> tuple[
    list[dict],           # analyzed_news
    float,                # total_bull_score
    float,                # total_bear_score
    list[dict],           # all_bull_factors
    list[dict],           # all_bear_factors
    str,                  # combined_text
    dict[str, dict],      # sector_sentiment
]:
    """Score each news item and aggregate bull/bear scores, factors, and sector data."""
    analyzed_news: list[dict] = []
    total_bull = 0.0
    total_bear = 0.0
    all_bull: list[dict] = []
    all_bear: list[dict] = []
    combined_text = ""
    sector_sentiment: dict[str, dict] = {}

    for item in news_items:
        text = f"{item.get('headline', '')} {item.get('snippet', '')}"
        combined_text += " " + text

        bull, bear, bull_kw, bear_kw = _score_sentiment(text)

        sector = item.get("sector", "General")
        bull *= SECTOR_WEIGHT.get(sector, 1.0)
        bear *= SECTOR_WEIGHT.get(sector, 1.0)

        recency_mult = _get_recency_multiplier(item.get("published_date", ""))
        bull *= recency_mult
        bear *= recency_mult

        category = item.get("category", "general")
        importance = CATEGORY_IMPORTANCE.get(category, "LOW")
        imp_mult = {"HIGH": 2.0, "MEDIUM": 1.5, "LOW": 1.0}.get(importance, 1.0)

        weighted_bull = bull * imp_mult
        weighted_bear = bear * imp_mult
        total_bull += weighted_bull
        total_bear += weighted_bear

        impact = _determine_impact(bull, bear)

        headline = item.get("headline", "")
        for kw in bull_kw:
            ftext = f"{kw.replace('_', ' ').title()} (+{round(weighted_bull,1)}) — {headline[:65]}"
            if not any(f["text"] == ftext for f in all_bull):
                all_bull.append({"text": ftext, "score": round(weighted_bull, 1)})

        for kw in bear_kw:
            ftext = f"{kw.replace('_', ' ').title()} (-{round(weighted_bear,1)}) — {headline[:65]}"
            if not any(f["text"] == ftext for f in all_bear):
                all_bear.append({"text": ftext, "score": round(weighted_bear, 1)})

        if sector not in sector_sentiment:
            sector_sentiment[sector] = {"bullish": 0.0, "bearish": 0.0, "count": 0}
        sector_sentiment[sector]["bullish"] += bull
        sector_sentiment[sector]["bearish"] += bear
        sector_sentiment[sector]["count"] += 1

        max_score = round(max(bull, bear), 1)
        if max_score >= 5.0:
            strength_level, strength_badge = "HIGH IMPACT", f"🔥 High Impact ({max_score})"
        elif max_score >= 2.5:
            strength_level, strength_badge = "MEDIUM IMPACT", f"⚡ Medium Impact ({max_score})"
        else:
            strength_level, strength_badge = "LOW IMPACT", f"📈 Low Impact ({max_score})"

        analyzed_news.append({
            "headline": headline,
            "source": item.get("source", ""),
            "link": item.get("link", ""),
            "published_date": item.get("published_date", ""),
            "sector": sector,
            "category": category,
            "impact": impact,
            "importance": importance,
            "bullish_score": round(bull, 1),
            "bearish_score": round(bear, 1),
            "impact_score": max_score,
            "strength_level": strength_level,
            "strength_badge": strength_badge,
            "recency_multiplier": round(recency_mult, 2),
        })

    return analyzed_news, total_bull, total_bear, all_bull, all_bear, combined_text, sector_sentiment



def _apply_market_signals(
    total_bull: float,
    total_bear: float,
    all_bull: list[dict],
    all_bear: list[dict],
    gift_nifty_change_pct: float | None,
    india_vix: float | None,
    india_vix_change_pct: float | None,
    pcr: float | None,
    global_market_changes: dict[str, float] | None,
    news_items: list[dict],
    fii_net_cr: float | None,
) -> tuple[
    float, float, list[dict], list[dict],
    dict, int,
    dict, float,
    float, float, float, float,
    str | None, str | None,
    float, float,
]:
    """Apply GIFT Nifty, VIX, PCR, global markets, and social sentiment boosts to scores."""
    news_count = len(news_items)
    normalization_factor = 1.0
    if news_count > 50:
        normalization_factor = (50 / news_count) ** 0.5
        total_bull *= normalization_factor
        total_bear *= normalization_factor

    gift_bull = gift_bear = 0.0
    gift_direction: str | None = None
    if gift_nifty_change_pct is not None:
        gift_bull, gift_bear, gift_factor = score_gift_nifty(gift_nifty_change_pct)
        total_bull += gift_bull
        total_bear += gift_bear
        gift_direction = (
            "BULLISH" if gift_nifty_change_pct > 0.25
            else ("BEARISH" if gift_nifty_change_pct < -0.25 else None)
        )
        if gift_factor:
            g_score = max(gift_bull, gift_bear)
            (all_bull if gift_bull > gift_bear else all_bear).append({"text": gift_factor, "score": g_score})

    vix_result: dict = {}
    vix_confidence_penalty = 0
    if india_vix is not None and india_vix_change_pct is not None:
        vix_result = score_india_vix(india_vix, india_vix_change_pct)
        vix_confidence_penalty = vix_result.get("confidence_penalty", 0)
        vix_bear_boost = vix_result.get("bear_boost", 0.0)
        if vix_bear_boost > 0:
            total_bear += vix_bear_boost
            all_bear.append({"text": vix_result["factor"], "score": abs(vix_bear_boost)})
        elif vix_bear_boost < 0:
            total_bull += abs(vix_bear_boost)
            all_bull.append({"text": vix_result["factor"], "score": abs(vix_bear_boost)})

    pcr_bull = pcr_bear = 0.0
    if pcr is not None:
        pcr_bull, pcr_bear, pcr_factor = score_pcr(pcr)
        total_bull += pcr_bull
        total_bear += pcr_bear
        if pcr_factor:
            p_score = max(pcr_bull, pcr_bear)
            if pcr_bull > pcr_bear:
                all_bull.append({"text": pcr_factor, "score": p_score})
            elif pcr_bear > pcr_bull:
                all_bear.append({"text": pcr_factor, "score": p_score})

    global_bull = global_bear = 0.0
    global_direction: str | None = None
    if global_market_changes:
        global_bull, global_bear, global_factors = score_global_markets(global_market_changes)
        total_bull += global_bull
        total_bear += global_bear
        global_direction = (
            "BULLISH" if global_bull > global_bear + 5
            else ("BEARISH" if global_bear > global_bull + 5 else None)
        )
        for f in global_factors:
            if "up" in f.lower():
                all_bull.append({"text": f, "score": 4.0})
            elif "down" in f.lower():
                all_bear.append({"text": f, "score": 4.0})

    social_sentiment = _compute_social_sentiment(news_items, fii_net_cr=fii_net_cr)
    if social_sentiment.get("contrarian_warning"):
        warn_msg = social_sentiment["contrarian_warning"]
        if "BULL TRAP" in warn_msg:
            all_bear.append({"text": f"⚠️ {warn_msg}", "score": 5.0})
        elif "BEAR TRAP" in warn_msg:
            all_bull.append({"text": f"⚠️ {warn_msg}", "score": 5.0})

    return (
        total_bull, total_bear, all_bull, all_bear,
        vix_result, vix_confidence_penalty,
        social_sentiment, normalization_factor,
        gift_bull, gift_bear, global_bull, global_bear,
        gift_direction, global_direction,
        pcr_bull, pcr_bear,
    )


