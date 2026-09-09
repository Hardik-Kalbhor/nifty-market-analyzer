"""
scraper/core.py — Main orchestration pipeline for all news and sentiment feeds.
"""

import logging
import concurrent.futures
from datetime import datetime

from .models import NewsItem
from .constants import (
    GOOGLE_NEWS_RSS_QUERIES,
    DIRECT_RSS_FEEDS,
    REDDIT_SUBREDDITS,
    TELEGRAM_CHANNELS,
)
from .classifiers import _deduplicate
from .rss import fetch_google_news_rss, fetch_direct_rss
from .social import fetch_reddit_posts, fetch_telegram_channel

logger = logging.getLogger(__name__)

def scrape_all_news() -> list[dict]:
    """
    Master function: scrape all sources in parallel, deduplicate, classify sectors,
    and return a list of dicts ready for the analyzer.
    """
    all_items: list[NewsItem] = []

    # Parallel scraping of Google News, Direct RSS feeds, Reddit, and Telegram
    logger.info("Fetching news feeds concurrently in parallel...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=18) as executor:
        futures = []

        for qinfo in GOOGLE_NEWS_RSS_QUERIES:
            futures.append(
                executor.submit(fetch_google_news_rss, qinfo["query"], qinfo["category"], 6)
            )
        for finfo in DIRECT_RSS_FEEDS:
            futures.append(
                executor.submit(fetch_direct_rss, finfo["url"], finfo["source"], finfo["category"], 8)
            )
        for sub in REDDIT_SUBREDDITS:
            futures.append(
                executor.submit(fetch_reddit_posts, sub, 5, 20)
            )
        for chan in TELEGRAM_CHANNELS:
            futures.append(
                executor.submit(fetch_telegram_channel, chan, 15)
            )

        done, not_done = concurrent.futures.wait(futures, timeout=20)
        if not_done:
            logger.warning(f"{len(not_done)} news feed(s) did not finish in time — skipping them.")
            for f in not_done:
                f.cancel()

        for future in done:
            try:
                items = future.result()
                if items:
                    all_items.extend(items)
            except Exception as fe:
                logger.warning(f"Parallel RSS fetch error: {fe}")


    # Deduplicate
    logger.info(f"Total raw items: {len(all_items)}. Deduplicating...")
    unique_items = _deduplicate(all_items)
    logger.info(f"Unique items after dedup: {len(unique_items)}")

    # 4. Sort by published date — most recent first
    def _sort_key(item: NewsItem) -> datetime:
        """Parse the published_date string for sorting. Most recent first."""
        if not item.published_date:
            return datetime.min
        formats = [
            "%d %b %Y, %I:%M %p",  # "08 Apr 2026, 10:30 AM"
            "%d %b %Y",            # "08 Apr 2026"
            "%Y-%m-%d",            # "2026-04-08"
            "%d-%m-%Y",            # "08-04-2026"
            "%d/%m/%Y",            # "08/04/2026"
            "%B %d, %Y",           # "April 08, 2026"
        ]
        for fmt in formats:
            try:
                return datetime.strptime(item.published_date.strip(), fmt)
            except ValueError:
                continue
        return datetime.min

    unique_items.sort(key=_sort_key, reverse=True)
    logger.info("Sorted news items by published date (most recent first).")

    return [item.to_dict() for item in unique_items]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI Test
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    import json
    results = scrape_all_news()
    print(json.dumps(results[:5], indent=2, ensure_ascii=False))
    print(f"\nTotal news items: {len(results)}")
