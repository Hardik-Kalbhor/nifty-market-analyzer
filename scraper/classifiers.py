"""
scraper/classifiers.py — Sector/category classification, text normalization, and deduplication.
"""

import re
import logging
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup

from .models import NewsItem
from .constants import SECTOR_KEYWORDS, CATEGORY_KEYWORDS, PERSONAL_FINANCE_EXCLUSIONS

logger = logging.getLogger(__name__)

def _is_personal_finance_noise(text: str) -> bool:
    """Return True if article is retail personal finance advice (irrelevant to NIFTY)."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in PERSONAL_FINANCE_EXCLUSIONS)



def _clean_html(raw_html: str) -> str:
    """Remove HTML tags from a string."""
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def _classify_sector(text: str) -> str:
    """Classify a news headline/snippet into a market sector."""
    text_lower = text.lower()
    sector_scores: dict[str, int] = {}

    for sector, keywords in SECTOR_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in text_lower:
                score += 1
        if score > 0:
            sector_scores[sector] = score

    if not sector_scores:
        return "General"

    # Return the sector with the highest keyword match count
    return max(sector_scores, key=sector_scores.get)


def _classify_category(text: str, default_category: str = "general") -> str:
    """Classify news into analysis categories (macro, india, commodity, etc.)."""
    text_lower = text.lower()
    cat_scores: dict[str, int] = {}

    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            cat_scores[cat] = score

    if not cat_scores:
        return default_category

    return max(cat_scores, key=cat_scores.get)


def _is_recent(published_parsed, hours: int = 48) -> bool:
    """Check if a feed entry was published within the last N hours."""
    if not published_parsed:
        return True  # If no date, include it anyway

    try:
        pub_dt = datetime(*published_parsed[:6], tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return pub_dt >= cutoff
    except Exception:
        return True


def _format_date(published_parsed) -> str:
    """Format a feedparser date tuple into a human-readable string."""
    if not published_parsed:
        return datetime.now().strftime("%d %b %Y, %I:%M %p")
    try:
        dt = datetime(*published_parsed[:6])
        return dt.strftime("%d %b %Y, %I:%M %p")
    except Exception:
        return datetime.now().strftime("%d %b %Y, %I:%M %p")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Core Scraping Functions
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━




def _normalize_title(title: str) -> str:
    """Normalize a headline for fuzzy deduplication."""
    title = title.lower()
    title = re.sub(r"[^\w\s]", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def _deduplicate(items: list[NewsItem]) -> list[NewsItem]:
    """Remove duplicate articles based on normalized headlines and URLs."""
    seen_titles: set[str] = set()
    seen_links: set[str] = set()
    unique: list[NewsItem] = []

    for item in items:
        norm_title = _normalize_title(item.headline)
        # Check title similarity via word sets
        title_words = set(norm_title.split())

        # Exact link match
        if item.link and item.link in seen_links:
            continue

        # Exact title match
        if norm_title in seen_titles:
            continue

        # Fuzzy title match — check Jaccard similarity with existing
        is_dup = False
        for seen in seen_titles:
            seen_words = set(seen.split())
            if not seen_words or not title_words:
                continue
            intersection = len(title_words & seen_words)
            union = len(title_words | seen_words)
            if union > 0 and (intersection / union) > 0.65:
                is_dup = True
                break

        if is_dup:
            continue

        seen_titles.add(norm_title)
        if item.link:
            seen_links.add(item.link)
        unique.append(item)

    return unique


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main Public API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


