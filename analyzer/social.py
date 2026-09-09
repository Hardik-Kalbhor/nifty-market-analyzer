"""
analyzer/social.py — Social & retail sentiment computation.

Contains: _compute_social_sentiment.
Processes Reddit, Telegram, Twitter items to produce a retail sentiment score
and detect contrarian traps against institutional FII flows.
"""

from typing import Any
from .sentiment import _score_sentiment


def _compute_social_sentiment(
    news_items: list[dict] | None,
    fii_net_cr: float | int | str | None = None
) -> dict[str, Any]:
    """
    Compute retail and social sentiment metrics across Reddit, Telegram, and Twitter.
    Detects retail euphoria vs panic and flags contrarian traps against institutional positioning.
    Guaranteed crash-proof against None, dirty strings, and malformed entries.
    """
    _empty: dict[str, Any] = {
        "retail_sentiment_score": 0,
        "retail_mood": "NEUTRAL / NO DATA",
        "sample_count": 0,
        "contrarian_warning": "",
        "top_buzz": [],
        "source_breakdown": {"reddit": 0, "telegram": 0, "twitter": 0},
    }

    if not isinstance(news_items, list):
        return _empty

    social_items = [
        item for item in news_items
        if isinstance(item, dict) and (
            item.get("category") in ("social_sentiment", "breaking_flash")
            or any(
                src in str(item.get("source") or "").lower()
                for src in ("reddit", "telegram", "twitter", "x.com", "fintwit")
            )
        )
    ]

    if not social_items:
        return _empty

    total_bull = 0.0
    total_bear = 0.0
    buzz_list: list[str] = []
    source_counts = {"reddit": 0, "telegram": 0, "twitter": 0}

    for item in social_items:
        src = str(item.get("source") or "").lower()
        if "reddit" in src:
            source_counts["reddit"] += 1
        elif "telegram" in src:
            source_counts["telegram"] += 1
        elif "twitter" in src or "x.com" in src or "fintwit" in src:
            source_counts["twitter"] += 1

        hl_val = item.get("headline")
        sn_val = item.get("snippet")
        hl_clean = str(hl_val).strip() if hl_val is not None else ""
        sn_clean = str(sn_val).strip() if sn_val is not None else ""
        text = f"{hl_clean} {sn_clean}".strip()

        bull, bear, _, _ = _score_sentiment(text)
        total_bull += bull
        total_bear += bear

        if hl_clean and hl_clean not in buzz_list:
            buzz_list.append(hl_clean)

    combined_volume = total_bull + total_bear
    raw_score = ((total_bull - total_bear) / combined_volume * 100.0) if combined_volume > 0 else 0.0
    sentiment_score = max(-100, min(100, int(round(raw_score))))

    if sentiment_score >= 40:
        retail_mood = "EUPHORIC / EXTREME GREED"
    elif sentiment_score >= 15:
        retail_mood = "BULLISH / OPTIMISTIC"
    elif sentiment_score <= -40:
        retail_mood = "PANIC / EXTREME FEAR"
    elif sentiment_score <= -15:
        retail_mood = "BEARISH / PESSIMISTIC"
    else:
        retail_mood = "NEUTRAL / BALANCED"

    fii_val: float | None = None
    if fii_net_cr is not None:
        try:
            fii_val = float(fii_net_cr)
        except (ValueError, TypeError):
            fii_val = None

    contrarian_warning = ""
    if sentiment_score >= 40 and fii_val is not None and fii_val < -1000:
        contrarian_warning = (
            f"CONTRARIAN BULL TRAP RISK: Retail euphoria ({sentiment_score:+d}/100) on social channels "
            f"clashes with heavy institutional FII cash selling ({fii_val:+,.0f} Cr). "
            f"High risk of opening gap fading."
        )
    elif sentiment_score <= -40 and fii_val is not None and fii_val > 1000:
        contrarian_warning = (
            f"CONTRARIAN BEAR TRAP RISK: Retail panic / put buying ({sentiment_score:+d}/100) "
            f"clashes with aggressive institutional FII buying (+{fii_val:,.0f} Cr). "
            f"High probability of short squeeze."
        )

    return {
        "retail_sentiment_score": sentiment_score,
        "retail_mood": retail_mood,
        "sample_count": len(social_items),
        "contrarian_warning": contrarian_warning,
        "top_buzz": buzz_list[:5],
        "source_breakdown": source_counts,
    }
