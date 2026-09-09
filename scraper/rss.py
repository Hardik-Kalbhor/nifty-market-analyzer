"""
scraper/rss.py — RSS feed fetchers (Google News RSS and direct RSS feeds).
"""

import logging
import requests
import feedparser
from typing import Optional

from .models import NewsItem
from .constants import HEADERS
from .classifiers import (
    _clean_html,
    _classify_sector,
    _classify_category,
    _is_recent,
    _format_date,
    _is_personal_finance_noise,
)

logger = logging.getLogger(__name__)

def fetch_google_news_rss(query: str, category: str = "general", max_items: int = 8) -> list[NewsItem]:
    """Fetch news from Google News RSS search with strict timeout."""
    encoded_query = requests.utils.quote(query)
    url = (
        f"https://news.google.com/rss/search?"
        f"q={encoded_query}&hl=en-IN&gl=IN&ceid=IN:en"
    )

    items: list[NewsItem] = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=6)
        if resp.status_code != 200:
            return []
        feed = feedparser.parse(resp.content)

        for entry in feed.entries[:max_items]:
            if not _is_recent(entry.get("published_parsed"), hours=48):
                continue

            headline = _clean_html(entry.get("title", ""))
            snippet = _clean_html(entry.get("summary", entry.get("description", "")))
            link = entry.get("link", "")

            # Google News titles often end with " - Source Name"
            source = "Google News"
            if " - " in headline:
                parts = headline.rsplit(" - ", 1)
                if len(parts) == 2 and len(parts[1]) < 50:
                    source = parts[1].strip()
                    headline = parts[0].strip()

            # Clean up Twitter / X syndication sources
            link_str = str(link or "").lower()
            source_str = str(source or "").lower()
            if any(t in link_str or t in source_str for t in ("x.com", "twitter.com", "twitter")):
                source = "Twitter (FinTwit)"
                category = "social_sentiment"

            combined_text = f"{headline} {snippet}"

            if _is_personal_finance_noise(combined_text):
                continue

            final_cat = "social_sentiment" if (category == "social_sentiment" or source == "Twitter (FinTwit)") else _classify_category(combined_text, default_category=category)

            items.append(
                NewsItem(
                    headline=headline,
                    source=source,
                    published_date=_format_date(entry.get("published_parsed")),
                    link=link,
                    snippet=snippet[:300],
                    sector=_classify_sector(combined_text),
                    category=final_cat,
                )
            )
    except Exception as e:
        logger.warning(f"Error fetching Google News RSS for '{query}': {e}")

    return items


def fetch_direct_rss(url: str, source_name: str, category: str = "general", max_items: int = 10) -> list[NewsItem]:
    """Fetch news from a direct RSS feed URL (Livemint, ET, etc.) with strict timeout."""
    items: list[NewsItem] = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=6)
        if resp.status_code != 200:
            return []
        feed = feedparser.parse(resp.content)

        for entry in feed.entries[:max_items]:
            if not _is_recent(entry.get("published_parsed"), hours=48):
                continue

            headline = _clean_html(entry.get("title", ""))
            snippet = _clean_html(
                entry.get("summary", entry.get("description", ""))
            )
            link = entry.get("link", "")

            combined_text = f"{headline} {snippet}"

            if _is_personal_finance_noise(combined_text):
                continue

            items.append(
                NewsItem(
                    headline=headline,
                    source=source_name,
                    published_date=_format_date(entry.get("published_parsed")),
                    link=link,
                    snippet=snippet[:300],
                    sector=_classify_sector(combined_text),
                    category=_classify_category(combined_text, default_category=category),
                )
            )
    except Exception as e:
        logger.warning(f"Error fetching direct RSS from '{source_name}': {e}")

    return items


