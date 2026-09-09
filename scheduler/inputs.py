"""
scheduler/inputs.py — Concurrent ingestion of market signals, news, FII/DII, and heavyweights.
"""

from __future__ import annotations

import concurrent.futures
import logging
from typing import Any

from scraper import scrape_all_news
from fii_dii_scraper import fetch_fii_dii_data
from market_signals_scraper import fetch_all_market_signals
from exit_fast_path import fetch_heavyweight_stocks

logger = logging.getLogger("AutoScheduler")


def gather_scheduled_inputs() -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any], dict[str, Any]]:
    """
    Concurrently fetch news, FII/DII data, market signals, and heavyweight stock data with a 25s timeout.
    Returns (news_items, fii_dii_data, market_signals, heavyweights).
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        f_news = executor.submit(scrape_all_news)
        f_fii = executor.submit(fetch_fii_dii_data)
        f_sig = executor.submit(fetch_all_market_signals)
        f_hw = executor.submit(fetch_heavyweight_stocks)

        done, _ = concurrent.futures.wait([f_news, f_fii, f_sig, f_hw], timeout=25.0)

    news_items = f_news.result() if f_news in done else []
    fii_dii_data = f_fii.result() if f_fii in done else None
    market_signals = f_sig.result() if f_sig in done else {}
    heavyweights = f_hw.result() if f_hw in done else {}

    return news_items, fii_dii_data, market_signals, heavyweights
