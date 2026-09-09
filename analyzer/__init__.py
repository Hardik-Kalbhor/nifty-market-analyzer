"""
analyzer/__init__.py — Public interface for the analyzer package.

Re-exports every name that external callers previously imported from analyzer.py
so that all existing import statements continue to work without modification.
"""

# ── Constants ──────────────────────────────────────────────────────────────
from .constants import (
    NEGATION_WORDS,
    BULLISH_SYNONYMS,
    BEARISH_SYNONYMS,
)
from .patterns import (
    BULLISH_PATTERNS,
    BEARISH_PATTERNS,
    BULLISH_KEYWORDS,
    BEARISH_KEYWORDS,
    EVENT_RISK_KEYWORDS,
    CATEGORY_IMPORTANCE,
    SECTOR_WEIGHT,
    GLOBAL_MARKET_WEIGHTS,
)

# ── Sentiment scoring ──────────────────────────────────────────────────────
from .sentiment import (
    _is_negated,
    _get_recency_multiplier,
    _score_sentiment,
)

# ── Market microstructure scoring ──────────────────────────────────────────
from .scoring import (
    score_gift_nifty,
    score_india_vix,
    score_pcr,
    score_global_markets,
)

# ── Confluence & helpers ───────────────────────────────────────────────────
from .confluence import (
    check_signal_confluence,
    _determine_impact,
    _detect_event_risk,
    _direction_from_scores,
)

# ── Social sentiment ───────────────────────────────────────────────────────
from .social import _compute_social_sentiment

# ── Pipeline helpers ───────────────────────────────────────────────────────
from .pipeline import _score_news_items, _apply_market_signals

# ── Summary generators ─────────────────────────────────────────────────────
from .summary import _extract_key_drivers, _generate_summary, _empty_result

# ── Core orchestrator ──────────────────────────────────────────────────────
from .core import analyze_news

__all__ = [
    # Constants
    "NEGATION_WORDS", "BULLISH_SYNONYMS", "BEARISH_SYNONYMS",
    "BULLISH_PATTERNS", "BEARISH_PATTERNS",
    "BULLISH_KEYWORDS", "BEARISH_KEYWORDS",
    "EVENT_RISK_KEYWORDS", "CATEGORY_IMPORTANCE",
    "SECTOR_WEIGHT", "GLOBAL_MARKET_WEIGHTS",
    # Sentiment
    "_is_negated", "_get_recency_multiplier", "_score_sentiment",
    # Scoring
    "score_gift_nifty", "score_india_vix", "score_pcr", "score_global_markets",
    # Confluence
    "check_signal_confluence", "_determine_impact", "_detect_event_risk", "_direction_from_scores",
    # Social
    "_compute_social_sentiment",
    # Core
    "analyze_news", "_extract_key_drivers", "_generate_summary", "_empty_result",
]
