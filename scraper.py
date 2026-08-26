"""
scraper.py — Multi-source financial news scraper for Indian markets.
Fetches news from RSS feeds (Google News, Livemint, Economic Times)
without requiring any API keys.
"""

import re
import time
import random
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from dataclasses import dataclass, field, asdict

import concurrent.futures
import requests
import feedparser
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Data Models
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class NewsItem:
    """Represents a single scraped news article."""
    headline: str
    source: str
    published_date: str
    link: str
    snippet: str = ""
    sector: str = "General"
    category: str = "general"  # macro, india, commodity, corporate, event

    def to_dict(self) -> dict:
        return asdict(self)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Sector Classification Keywords
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SECTOR_KEYWORDS: dict[str, list[str]] = {
    "Banking & Finance": [
        "bank", "banking", "nbfc", "npa", "credit", "loan", "deposit",
        "hdfc", "icici", "kotak", "axis bank", "sbi", "pnb", "bob",
        "bajaj finance", "bajaj finserv", "rbi", "reserve bank", "interest rate",
        "monetary policy", "repo rate", "lending", "financial services",
        "insurance", "lic", "mutual fund",
    ],
    "Information Technology": [
        "infosys", "tcs", "wipro", "hcl tech", "tech mahindra", "l&t technology",
        "it sector", "information technology", "software", "saas", "cloud computing",
        "artificial intelligence", " ai ", "digital transformation", "cybersecurity",
        "it services", "mphasis", "persistent", "coforge", "ltimindtree",
    ],
    "Pharma & Healthcare": [
        "pharma", "pharmaceutical", "drug", "fda", "usfda", "healthcare",
        "hospital", "sun pharma", "dr reddy", "cipla", "lupin", "biocon",
        "divi's lab", "apollo hospital", "max health", "fortis", "medicine",
        "vaccine", "generic drug", "biosimilar",
    ],
    "Automobile": [
        "auto", "automobile", "car", "vehicle", "ev ", "electric vehicle",
        "maruti", "tata motors", "mahindra", "bajaj auto", "hero motocorp",
        "eicher", "ashok leyland", "tvs motor", "ola electric",
        "two-wheeler", "passenger vehicle", "commercial vehicle",
    ],
    "Energy & Oil": [
        "oil", "petroleum", "crude", "brent", "opec", "natural gas",
        "reliance", "ongc", "ioc", "bpcl", "hpcl", "gail",
        "adani green", "adani energy", "ntpc", "power grid", "tata power",
        "renewable energy", "solar", "wind energy", "coal",
    ],
    "Metals & Mining": [
        "metal", "steel", "iron ore", "copper", "aluminium", "zinc", "gold",
        "silver", "tata steel", "jsw steel", "hindalco", "vedanta",
        "coal india", "nmdc", "mining", "commodity metal",
    ],
    "FMCG": [
        "fmcg", "consumer goods", "hindustan unilever", "itc", "nestle",
        "britannia", "dabur", "marico", "godrej consumer", "colgate",
        "procter", "consumer staple", "packaged food",
    ],
    "Real Estate & Infrastructure": [
        "real estate", "realty", "housing", "dlf", "godrej properties",
        "oberoi realty", "prestige", "brigade", "infrastructure", "infra",
        "construction", "cement", "ultratech", "ambuja", "acc",
        "l&t", "larsen", "road", "highway", "smart city",
    ],
    "Telecom & Media": [
        "telecom", "jio", "airtel", "vodafone", "idea", "bsnl",
        "5g", "spectrum", "broadband", "media", "zee", "star",
        "disney", "hotstar", "ott",
    ],
    "Defence & Aerospace": [
        "defence", "defense", "hal", "bharat electronics", "bel",
        "bharat dynamics", "missile", "fighter jet", "military",
        "aerospace", "drdo", "naval", "army", "air force",
    ],
    "Agriculture": [
        "agriculture", "agri", "crop", "monsoon", "kharif", "rabi",
        "msp", "fertilizer", "urea", "pesticide", "food grain",
        "wheat", "rice", "sugar", "cotton",
    ],
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Personal Finance & Retail Advice Exclusions
# (Filters out noise articles irrelevant to NIFTY 50)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PERSONAL_FINANCE_EXCLUSIONS: list[str] = [
    "credit score", "cibil", "loan guarantor", "guarantor", "itr ", "tax return",
    "form 16", "form 26as", "huf ", "nro bank account", "nre account",
    "personal finance", "saving account", "credit card limit", "fixed deposit",
    "home loan eligibility", "health insurance premium", "term insurance policy",
    "epf withdrawal", "ppf interest", "gift tax", "income tax slab",
]


def _is_personal_finance_noise(text: str) -> bool:
    """Return True if article is retail personal finance advice (irrelevant to NIFTY)."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in PERSONAL_FINANCE_EXCLUSIONS)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# News Category Keywords (for analyzer)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "macro": [
        "us economy", "fed", "federal reserve", "inflation", "cpi", "wpi",
        "gdp", "trade war", "tariff", "us market", "wall street", "s&p 500",
        "nasdaq", "dow jones", "treasury", "bond yield", "dollar index",
        "global recession", "imf", "world bank", "us jobs", "nonfarm",
        "ecb", "bank of japan", "china economy", "europe economy",
    ],
    "india": [
        "rbi", "reserve bank", "nifty", "sensex", "bse", "nse",
        "fii", "dii", "india gdp", "indian economy", "rupee",
        "fiscal deficit", "gst", "tax", "modi", "budget", "sebi",
        "indian market", "domestic", "india growth",
    ],
    "commodity": [
        "crude", "oil", "brent", "wti", "gold", "silver", "copper",
        "commodity", "opec", "natural gas", "metal price",
    ],
    "corporate": [
        "earnings", "quarterly result", "profit", "revenue", "order",
        "acquisition", "merger", "ipo", "buyback", "dividend",
        "upgrade", "downgrade", "rating", "target price",
    ],
    "event": [
        "rbi policy", "fed meeting", "fomc", "budget", "election",
        "g20", "g7", "cpi data", "jobs report", "expiry",
    ],
    "geopolitical": [
        "war", "conflict", "tension", "sanction", "missile", "attack",
        "ceasefire", "peace", "nato", "russia", "ukraine", "china taiwan",
        "middle east", "iran", "israel", "north korea",
    ],
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RSS Feed Sources
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GOOGLE_NEWS_RSS_QUERIES: list[dict[str, str]] = [
    # India-specific
    {"query": "NIFTY 50 stock market India today", "category": "india"},
    {"query": "RBI monetary policy India", "category": "india"},
    {"query": "FII DII activity India stock market", "category": "india"},
    {"query": "Indian economy GDP growth", "category": "india"},
    {"query": "Sensex NIFTY market today", "category": "india"},
    # Global macro
    {"query": "US Federal Reserve interest rate", "category": "macro"},
    {"query": "US inflation CPI data", "category": "macro"},
    {"query": "Wall Street S&P 500 Nasdaq today", "category": "macro"},
    {"query": "global economy recession 2025 2026", "category": "macro"},
    # Commodities
    {"query": "crude oil price today Brent WTI", "category": "commodity"},
    {"query": "gold price today international", "category": "commodity"},
    # Geopolitics
    {"query": "geopolitical tension war trade conflict", "category": "geopolitical"},
    # Corporate India
    {"query": "India corporate earnings quarterly results", "category": "corporate"},
    {"query": "India IT sector Infosys TCS Wipro", "category": "corporate"},
    {"query": "India banking sector HDFC ICICI SBI", "category": "corporate"},
]

DIRECT_RSS_FEEDS: list[dict[str, str]] = [
    {"url": "https://www.livemint.com/rss/markets", "source": "Livemint", "category": "india"},
    {"url": "https://www.livemint.com/rss/money", "source": "Livemint", "category": "india"},
    {"url": "https://www.livemint.com/rss/industry", "source": "Livemint", "category": "corporate"},
    {
        "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "source": "Economic Times",
        "category": "india",
    },
    {
        "url": "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms",
        "source": "Economic Times",
        "category": "macro",
    },
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Scraper Utilities
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


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

            combined_text = f"{headline} {snippet}"

            if _is_personal_finance_noise(combined_text):
                continue

            items.append(
                NewsItem(
                    headline=headline,
                    source=source,
                    published_date=_format_date(entry.get("published_parsed")),
                    link=link,
                    snippet=snippet[:300],
                    sector=_classify_sector(combined_text),
                    category=_classify_category(combined_text, default_category=category),
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Deduplication
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


def scrape_all_news() -> list[dict]:
    """
    Master function: scrape all sources in parallel, deduplicate, classify sectors,
    and return a list of dicts ready for the analyzer.
    """
    all_items: list[NewsItem] = []

    # Parallel scraping of Google News and Direct RSS feeds
    logger.info("Fetching news feeds concurrently in parallel...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=14) as executor:
        futures = []

        for qinfo in GOOGLE_NEWS_RSS_QUERIES:
            futures.append(
                executor.submit(fetch_google_news_rss, qinfo["query"], qinfo["category"], 6)
            )
        for finfo in DIRECT_RSS_FEEDS:
            futures.append(
                executor.submit(fetch_direct_rss, finfo["url"], finfo["source"], finfo["category"], 8)
            )


        done, not_done = concurrent.futures.wait(futures, timeout=18)
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
