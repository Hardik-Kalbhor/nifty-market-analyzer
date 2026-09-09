"""
scraper package — Multi-source financial news & sentiment scraper.
"""

from .models import NewsItem
from .constants import (
    SECTOR_KEYWORDS,
    PERSONAL_FINANCE_EXCLUSIONS,
    CATEGORY_KEYWORDS,
    GOOGLE_NEWS_RSS_QUERIES,
    DIRECT_RSS_FEEDS,
    REDDIT_SUBREDDITS,
    TELEGRAM_CHANNELS,
    SPAM_PROMO_REGEX,
    HEADERS,
)
from .classifiers import (
    _is_personal_finance_noise,
    _clean_html,
    _classify_sector,
    _classify_category,
    _is_recent,
    _format_date,
    _normalize_title,
    _deduplicate,
)
from .rss import (
    fetch_google_news_rss,
    fetch_direct_rss,
)
from .social import (
    fetch_reddit_posts,
    fetch_telegram_channel,
)
from .core import scrape_all_news

__all__ = [
    "NewsItem",
    "SECTOR_KEYWORDS",
    "PERSONAL_FINANCE_EXCLUSIONS",
    "CATEGORY_KEYWORDS",
    "GOOGLE_NEWS_RSS_QUERIES",
    "DIRECT_RSS_FEEDS",
    "REDDIT_SUBREDDITS",
    "TELEGRAM_CHANNELS",
    "SPAM_PROMO_REGEX",
    "HEADERS",
    "_is_personal_finance_noise",
    "_clean_html",
    "_classify_sector",
    "_classify_category",
    "_is_recent",
    "_format_date",
    "_normalize_title",
    "_deduplicate",
    "fetch_google_news_rss",
    "fetch_direct_rss",
    "fetch_reddit_posts",
    "fetch_telegram_channel",
    "scrape_all_news",
]
