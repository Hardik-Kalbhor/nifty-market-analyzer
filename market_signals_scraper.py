"""
market_signals_scraper.py — Backward-compatibility shim.

The implementation has been decomposed into the market_signals/ package.
"""

from market_signals import (  # noqa: F401
    HEADERS,
    _fetch_yahoo_chart_quote,
    _fetch_nse_indices,
    _fetch_global_markets_and_gift,
    _fetch_groww_option_chain_fallback,
    _fetch_option_chain_data,
    fetch_all_market_signals,
)
