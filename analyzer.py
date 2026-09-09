"""
analyzer.py — Backward-compatibility shim.

The implementation has been split into the analyzer/ package.
This file re-exports everything so existing callers (e.g. server.py, auto_scheduler.py)
continue to work without modification.
"""

from analyzer import (  # noqa: F401
    NEGATION_WORDS, BULLISH_SYNONYMS, BEARISH_SYNONYMS,
    BULLISH_PATTERNS, BEARISH_PATTERNS,
    BULLISH_KEYWORDS, BEARISH_KEYWORDS,
    EVENT_RISK_KEYWORDS, CATEGORY_IMPORTANCE,
    SECTOR_WEIGHT, GLOBAL_MARKET_WEIGHTS,
    _is_negated, _get_recency_multiplier, _score_sentiment,
    score_gift_nifty, score_india_vix, score_pcr, score_global_markets,
    check_signal_confluence, _determine_impact, _detect_event_risk, _direction_from_scores,
    _compute_social_sentiment,
    analyze_news, _extract_key_drivers, _generate_summary, _empty_result,
)
