"""
analyzer/constants.py — Static data constants for the sentiment analysis engine.

Contains: negation words, bullish/bearish synonym dicts, morphological regex patterns,
keyword dicts, event risk keywords, category/sector weights, and global market weights.
"""

import re

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. NEGATION WORDS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

NEGATION_WORDS: list[str] = [
    "not", "no", "never", "without", "despite", "unlikely",
    "fails to", "fail to", "unable to", "didn't", "doesn't",
    "won't", "cannot", "can't", "hardly", "barely", "less than",
    "below expected", "misses", "missed", "contrary to",
    "rules out", "ruled out", "denies", "denied", "rejects",
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. SYNONYM DICTIONARY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BULLISH_SYNONYMS: dict[str, list[str]] = {
    "rate cut": [
        "rate reduction", "repo rate cut", "interest rate slash",
        "policy rate reduction", "rate slashed", "repo cut",
    ],
    "fii buying": [
        "foreign inflows", "fpi net buyers", "overseas investors buy",
        "foreign institutional buying", "fii net purchase",
        "foreign portfolio inflows",
    ],
    "crude fall": [
        "oil prices drop", "brent declines", "crude tumbles",
        "oil slips", "crude softens", "oil eases", "brent weakens",
    ],
    "inflation cool": [
        "price pressures ease", "inflation moderates", "cpi softens",
        "retail inflation dips", "wpi eases", "price rise slows",
    ],
    "gdp beat": [
        "economy outperforms", "growth exceeds estimate",
        "gdp surprises", "economic expansion beats",
    ],
    "earnings beat": [
        "profit beats estimate", "quarterly result exceeds",
        "net profit above forecast", "results top expectations",
        "earnings surprise", "beats street estimate",
    ],
    "ceasefire": [
        "truce declared", "hostilities end", "peace agreement",
        "conflict ends", "armistice", "war ends",
    ],
    "stimulus": [
        "fiscal support", "government spending boost", "relief package",
        "economic package", "bailout", "support measures",
    ],
    "rupee appreciat": [
        "rupee gains", "rupee strengthens", "inr rises",
        "rupee up against dollar", "rupee recovers",
    ],
}

BEARISH_SYNONYMS: dict[str, list[str]] = {
    "rate hike": [
        "rate increase", "repo rate hike", "interest rate raised",
        "policy rate increased", "rate raised", "borrowing cost rises",
    ],
    "fii selling": [
        "foreign outflows", "fpi net sellers", "overseas investors sell",
        "foreign institutional selling", "fii net selling",
        "foreign portfolio outflows", "capital outflows",
    ],
    "crude surge": [
        "oil prices spike", "brent jumps", "crude rallies",
        "oil soars", "crude shoots up", "oil price surge",
        "brent hits high",
    ],
    "inflation rise": [
        "price pressures build", "inflation accelerates", "cpi jumps",
        "retail inflation rises", "wpi climbs", "price rise quickens",
        "cost of living rises",
    ],
    "recession": [
        "economic contraction", "gdp shrinks", "negative growth",
        "economic downturn", "economy contracts", "growth slumps",
    ],
    "earnings miss": [
        "profit misses estimate", "quarterly result disappoints",
        "net profit below forecast", "results miss expectations",
        "earnings disappoint", "misses street estimate",
    ],
    "war": [
        "military conflict", "armed conflict", "hostilities begin",
        "troops deployed", "military offensive", "combat operations",
    ],
    "default": [
        "debt default", "bond default", "payment default",
        "fails to repay", "sovereign default", "credit event",
    ],
    "rupee depreciat": [
        "rupee falls", "rupee weakens", "inr drops",
        "rupee down against dollar", "rupee hits record low",
        "rupee plunges",
    ],
    "tariff": [
        "import duty raised", "customs duty hike", "trade barrier",
        "levy imposed", "duty increase", "protectionist measure",
    ],
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. REGEX MORPHOLOGICAL PATTERNS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# Regex patterns and keyword dicts are in patterns.py
from .patterns import (
    BULLISH_PATTERNS, BEARISH_PATTERNS,
    BULLISH_KEYWORDS, BEARISH_KEYWORDS,
    EVENT_RISK_KEYWORDS, CATEGORY_IMPORTANCE,
    SECTOR_WEIGHT, GLOBAL_MARKET_WEIGHTS,
)
