"""
institutional/brokerage.py — Global & domestic brokerage calls extraction on NIFTY heavyweights.
"""

import re
import time
import logging
from typing import Optional
from .constants import BROKERAGE_PROVIDERS, HEAVYWEIGHT_TICKERS, _SECTOR_MAP
from .parsers import _rss_articles, _clean_text, _first_sentence

logger = logging.getLogger(__name__)

def _action_from_text(text: str) -> str:
    """Classify brokerage action from text."""
    t = text.lower()
    if any(k in t for k in ["strong buy", "overweight", "outperform", "add", "upgrade", "initiates"]):
        return "BUY"
    if any(k in t for k in ["downgrade", "underperform", "underweight", "reduce"]):
        return "SELL"
    if any(k in t for k in [
        "target raised", "target hike", "price target increase",
        "raises price target", "hikes price target", "lifts price target",
        "raises target", "hikes target", "lifts target", "raises tp",
    ]):
        return "TARGET RAISED"
    if any(k in t for k in [
        "target cut", "target reduce", "price target lower",
        "cuts price target", "lowers price target", "cuts target",
    ]):
        return "TARGET CUT"
    if any(k in t for k in ["neutral", "hold", "equal-weight", "market perform"]):
        return "HOLD"
    return "NEUTRAL"


def _extract_brokerage_call(article: dict) -> Optional[dict]:
    """Parse a brokerage call from an article dict."""
    title = article.get("title", "")
    summary = article.get("summary", "")
    combined = title + " " + summary

    institution = next(
        (inst for inst in BROKERAGE_PROVIDERS if inst.lower() in combined.lower()),
        None,
    )
    if not institution:
        return None

    stock_symbol = "NIFTY50"
    stock_name = "NIFTY 50"
    for name, sym in HEAVYWEIGHT_TICKERS.items():
        if name.lower() in combined.lower():
            stock_symbol = sym
            stock_name = name
            break

    action = _action_from_text(combined)

    target_match = re.search(
        r"(?:target|TP|price target)[^\d]{1,20}₹?\s*(\d[\d,]{1,6})",
        combined, re.IGNORECASE,
    )
    target_price = None
    if target_match:
        try:
            val = int(target_match.group(1).replace(",", ""))
            if val >= 100:  # Real target prices in INR
                target_price = val
        except ValueError:
            pass

    clean_summary = _clean_text(summary)
    thesis = _first_sentence(clean_summary if len(clean_summary) > 20 else title, max_len=120)

    return {
        "institution": institution,
        "stock_name": stock_name,
        "stock_symbol": stock_symbol,
        "action": action,
        "target_price": target_price,
        "upside_pct": None,
        "sector": _SECTOR_MAP.get(stock_symbol, "Equity Markets"),
        "thesis": thesis,
        "source_link": article.get("link", "#"),
        "published": article.get("published", ""),
    }



def _fetch_brokerage_calls() -> list[dict]:
    """Fetch brokerage radar calls for heavyweight stocks."""
    brokerage_rss_queries = [
        '"Morgan Stanley" OR "Goldman Sachs" India stock upgrade downgrade target',
        '"Jefferies" OR "CLSA" OR "JPMorgan" India Nifty stock target',
        '"Kotak" OR "Motilal Oswal" OR "ICICI Securities" stock upgrade rating',
        '"Nuvama" OR "Bernstein" India equity target outperform',
    ]
    articles = []
    for q in brokerage_rss_queries:
        articles.extend(_rss_articles(q, max_items=5))
        time.sleep(0.3)

    calls: list[dict] = []
    seen: set[str] = set()
    for art in articles:
        call = _extract_brokerage_call(art)
        if not call:
            continue
        key = f"{call['institution']}_{call['stock_symbol']}"
        if key in seen:
            continue
        seen.add(key)
        calls.append(call)

    return calls[:14]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Confluence Matrix
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

