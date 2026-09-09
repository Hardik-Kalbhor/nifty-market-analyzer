"""
memory_fts/constants.py — Query sanitization and search constants for SQLite FTS5.
"""

from __future__ import annotations

import re


def _sanitize_fts_query(text: str) -> str:
    """
    Sanitize raw free-form text or headlines into a safe SQLite FTS5 query string.
    - Strips non-alphanumeric characters.
    - Retains 2-letter financial/options terms (ce, pe, oi, it, up).
    - Quotes every token (e.g. "term") to prevent FTS5 syntax errors from reserved words (not, near, and, or).
    - Joins tokens with OR for broad BM25 recall.
    """
    if not text:
        return ""

    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", text)
    raw_tokens = [t.strip().lower() for t in cleaned.split() if t.strip()]

    # Critical financial & options abbreviations that must not be discarded
    financial_short_terms = {"ce", "pe", "oi", "it", "up"}
    stop_words = {
        "the", "and", "for", "with", "this", "that", "from", "are", "was", "will",
        "has", "have", "had", "its", "into", "been", "also", "about", "after", "over",
        "all", "any", "not", "near", "but", "out"
    }

    meaningful = []
    for tok in raw_tokens:
        if tok in stop_words:
            continue
        if len(tok) >= 3 or tok in financial_short_terms:
            meaningful.append(tok)

    if not meaningful:
        return ""

    # Wrap each token in double quotes so FTS5 treats it as a literal word
    quoted_tokens = [f'"{tok}"' for tok in meaningful[:12]]
    return " OR ".join(quoted_tokens)
