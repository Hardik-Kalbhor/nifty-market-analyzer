"""
institutional/parsers.py — Article search, text cleaning, level extraction, and bias classifiers.
"""

import re
import logging
import requests
import feedparser
from bs4 import BeautifulSoup
from typing import Optional

from .constants import HEADERS, _NIFTY_FLOOR, _NIFTY_CEIL

logger = logging.getLogger(__name__)

def _extract_levels(text: str) -> list[int]:
    """Extract NIFTY-range (22,000–28,000) price levels from text."""
    nums = re.findall(r"\b(2[2-7][,\s]?[0-9]{3}(?:\.[0-9]{1,2})?)\b", text)
    out: list[int] = []
    for n in nums:
        try:
            v = float(n.replace(",", "").replace(" ", ""))
            if _NIFTY_FLOOR <= v <= _NIFTY_CEIL:
                out.append(int(v))
        except ValueError:
            pass
    return sorted(set(out))


_extract_nifty_levels = _extract_levels


def _classify_bias(text: str) -> str:
    """Return BULLISH / BEARISH / RANGEBOUND from text."""
    t = text.lower()
    bull_kw = ["bullish", "upside", "rally", "buy on dips", "positive bias",
               "gap up", "overweight", "add", "long", "buy call",
               "support holding", "uptrend", "higher levels"]
    bear_kw = ["bearish", "downside", "breakdown", "sell", "decline", "caution",
               "gap down", "underweight", "negative bias", "short", "sell call",
               "downtrend", "lower levels", "correction"]
    bull = sum(1 for k in bull_kw if k in t)
    bear = sum(1 for k in bear_kw if k in t)
    if bull > bear:
        return "BULLISH"
    if bear > bull:
        return "BEARISH"
    return "RANGEBOUND"


def _classify_gap(bias: str, text: str) -> str:
    t = text.lower()
    if "gap up" in t or "positive gap" in t:
        return "Positive"
    if "gap down" in t or "negative gap" in t:
        return "Negative"
    if bias == "BULLISH":
        return "Positive"
    if bias == "BEARISH":
        return "Negative"
    return "Flat"


def _clean_text(html_or_text: str) -> str:
    """Strip HTML tags and excess whitespace from RSS summary/title."""
    if not html_or_text:
        return ""
    clean = re.sub(r"<[^>]+>", " ", html_or_text)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def _first_sentence(text: str, max_len: int = 150) -> str:
    cleaned = _clean_text(text)
    s = re.split(r"[.!?]", cleaned.strip())[0].strip()
    return (s[:max_len] + "...") if len(s) > max_len else s



# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Article Fetcher — ET Markets search + body extraction
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_ET_SEARCH = "https://economictimes.indiatimes.com/searchresult.cms?query={query}&site=et"
_SESSION = requests.Session()
_SESSION.headers.update(HEADERS)


def _et_search_urls(query: str, max_urls: int = 5) -> list[tuple[str, str]]:
    """Return [(title, url)] from ET Markets search results for query."""
    try:
        url = _ET_SEARCH.format(query=requests.utils.quote(query))
        resp = _SESSION.get(url, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            title = a.text.strip()
            if "articleshow" in href and len(title) > 20:
                full = ("https://economictimes.indiatimes.com" + href
                        if href.startswith("/") else href)
                results.append((title[:100], full))
                if len(results) >= max_urls:
                    break
        return results
    except Exception as e:
        logger.warning(f"ET search failed for '{query}': {e}")
        return []


def _fetch_article_body(url: str, timeout: int = 10) -> str:
    """Fetch an article page and return its cleaned text body."""
    try:
        resp = _SESSION.get(url, timeout=timeout)
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        # Try common ET article body selectors
        body = (soup.find(id="articleText")
                or soup.find(class_="artText")
                or soup.find(class_="article_body")
                or soup.find(class_="story-content")
                or soup.find("article"))
        return (body.get_text(" ", strip=True)[:5000]
                if body else soup.get_text(" ", strip=True)[:5000])
    except Exception as e:
        logger.debug(f"Article fetch failed for {url}: {e}")
        return ""


def _rss_articles(query: str, max_items: int = 6) -> list[dict]:
    """Fallback: Google News RSS for a quoted query."""
    try:
        encoded = requests.utils.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en-IN&gl=IN&ceid=IN:en"
        feed = feedparser.parse(url)
        return [
            {
                "title": e.get("title", ""),
                "summary": e.get("summary", ""),
                "link": e.get("link", "#"),
            }
            for e in feed.entries[:max_items]
        ]
    except Exception as e:
        logger.warning(f"RSS fallback failed for '{query}': {e}")
        return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Per-Provider Tactical Desk Call Builder
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

