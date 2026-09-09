"""
institutional_scraper.py — Backward-compatibility shim.

The implementation has been decomposed into the institutional/ package.
"""

from institutional import (  # noqa: F401
    IST,
    _CACHE_FILENAME,
    _CACHE_TTL_HOURS,
    HEADERS,
    TACTICAL_PROVIDERS,
    BROKERAGE_PROVIDERS,
    _NIFTY_FLOOR,
    _NIFTY_CEIL,
    HEAVYWEIGHT_TICKERS,
    _SECTOR_MAP,
    _extract_levels,
    _extract_nifty_levels,
    _classify_bias,
    _classify_gap,
    _clean_text,
    _first_sentence,
    _et_search_urls,
    _fetch_article_body,
    _rss_articles,
    _build_provider_call,
    _build_consensus,
    _build_consensus_call,
    _action_from_text,
    _extract_brokerage_call,
    _fetch_brokerage_calls,
    _build_confluence_matrix,
    fetch_institutional_radar,
    get_cache_path,
    save_institutional_radar_cache,
    load_institutional_radar_cache,
    get_cached_institutional_radar,
    _patch_spot_derived_fields,
)
