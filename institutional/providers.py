"""
institutional/providers.py — Institutional desk provider scrapers and Street Consensus builder.
"""

import os
import time
import logging
from typing import Optional
from .parsers import (
    _et_search_urls, _fetch_article_body, _clean_text, _rss_articles,
    _extract_levels, _classify_bias, _classify_gap, _first_sentence,
    _llm_extract_call,
)

logger = logging.getLogger(__name__)

def _build_provider_call(provider: dict, nifty_spot: Optional[float] = None) -> Optional[dict]:
    """
    Fetch articles for this provider from ET search and Google News RSS,
    extract full body/summaries, parse levels across matching articles, and determine bias + thesis.
    """
    kw_match = provider["kw_match"]
    matching_texts: list[str] = []
    best_title = ""
    best_link = "#"
    best_thesis = ""

    # --- Primary: ET Markets search ---
    et_hits = _et_search_urls(provider["et_query"], max_urls=6)
    for title, url in et_hits:
        title_lower = title.lower()
        if not any(kw in title_lower for kw in kw_match):
            continue
        body = _fetch_article_body(url)
        if not body:
            continue
        if "nifty" in body.lower() or any(kw in body.lower() for kw in kw_match):
            matching_texts.append(body)
            if not best_title:
                best_title = title
                best_link = url
                best_thesis = _first_sentence(title)
        time.sleep(0.2)

    # --- Supplementary / Fallback: Google News RSS ---
    # RSS summary is usually an HTML snippet like <a href="actual-url">title</a>
    # We extract the actual source URL and fetch its full body for level extraction.
    rss_articles = _rss_articles(provider["rss_query"], max_items=10)
    for art in rss_articles:
        title   = art.get("title", "")
        summary = art.get("summary", "")
        combined = title + " " + summary
        if not any(kw in combined.lower() for kw in kw_match):
            continue

        # Try to fetch the actual article body from the canonical URL in the summary
        import re as _re
        href_match = _re.search(r'href=["\']([^"\']+)["\']', summary)
        article_body = ""
        actual_link = art.get("link", "#")
        if href_match:
            candidate_url = href_match.group(1)
            # Only follow if it looks like a real article URL (not a google redirect)
            if candidate_url.startswith("http") and "google.com" not in candidate_url:
                actual_link = candidate_url
                article_body = _fetch_article_body(candidate_url)
                if article_body:
                    logger.info(f"[Radar] RSS body fetched from {candidate_url[:60]}... ({len(article_body)} chars)")

        # Merge: use real body if we got it, otherwise fall back to title+summary snippet
        text_to_add = article_body if article_body else combined
        matching_texts.append(text_to_add)

        if not best_title:
            best_title  = title
            best_link   = actual_link
            best_thesis = _first_sentence(title)

    if not matching_texts:
        logger.info(f"No content found for provider: {provider['key']}")
        return None

    combined_all = " ".join(matching_texts)

    # ── LLM extraction (Groq) → keyword fallback ─────────────────────────────
    groq_key = os.environ.get("GROQ_API_KEY", "")
    llm_result = _llm_extract_call(
        text=combined_all,
        analyst_name=provider.get("analyst", provider["key"]),
        nifty_spot=nifty_spot,
        groq_key=groq_key,
    )

    if llm_result:
        # LLM gave us structured output — use it directly
        return {
            "next_day_bias": llm_result["bias"],
            "s1": llm_result.get("s1"),
            "s2": llm_result.get("s2"),
            "r1": llm_result.get("r1"),
            "r2": llm_result.get("r2"),
            "expected_gap": llm_result.get("expected_gap", "Flat"),
            "thesis": llm_result.get("thesis") or best_thesis or _first_sentence(best_title or combined_all),
            "source_headline": best_title,
            "source_link": best_link,
            "raw_levels_found": llm_result.get("raw_levels", [])[:10],
            "extraction_engine": "LLM",
        }

    # ── Keyword fallback (Groq offline / no key / rate-limited) ──────────────
    logger.info(f"[Radar] {provider['key']}: using keyword extraction fallback")
    levels = _extract_levels(combined_all)
    bias   = _classify_bias(combined_all)
    gap    = _classify_gap(bias, combined_all)

    if nifty_spot and levels:
        supports    = [lvl for lvl in levels if lvl < nifty_spot]
        resistances = [lvl for lvl in levels if lvl >= nifty_spot]
    elif len(levels) >= 2:
        mid_idx     = len(levels) // 2
        supports    = levels[:mid_idx]
        resistances = levels[mid_idx:]
    elif len(levels) == 1:
        supports    = []
        resistances = levels
    else:
        supports    = []
        resistances = []

    s1 = supports[-1]    if len(supports)    >= 1 else None
    s2 = supports[-2]    if len(supports)    >= 2 else None
    r1 = resistances[0]  if len(resistances) >= 1 else None
    r2 = resistances[1]  if len(resistances) >= 2 else None

    return {
        "next_day_bias": bias,
        "s1": s1,
        "s2": s2,
        "r1": r1,
        "r2": r2,
        "expected_gap": gap,
        "thesis": best_thesis or _first_sentence(best_title or combined_all),
        "source_headline": best_title,
        "source_link": best_link,
        "raw_levels_found": levels[:10],
        "extraction_engine": "keywords",
    }




# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Consensus Builder
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _build_consensus(provider_calls: dict) -> dict:
    """Aggregate provider calls into a street consensus row."""
    if not provider_calls:
        return {}

    bias_counts = {"BULLISH": 0, "BEARISH": 0, "RANGEBOUND": 0}
    s1_vals, s2_vals, r1_vals, r2_vals = [], [], [], []

    for call in provider_calls.values():
        b = call.get("next_day_bias", "RANGEBOUND")
        bias_counts[b] = bias_counts.get(b, 0) + 1
        if call.get("s1"): s1_vals.append(call["s1"])
        if call.get("s2"): s2_vals.append(call["s2"])
        if call.get("r1"): r1_vals.append(call["r1"])
        if call.get("r2"): r2_vals.append(call["r2"])

    dominant = max(bias_counts, key=bias_counts.get)
    total = sum(bias_counts.values()) or 1
    bull_pct = round(bias_counts["BULLISH"] / total * 100)
    bear_pct = round(bias_counts["BEARISH"] / total * 100)

    def _zone(vals: list) -> Optional[str]:
        if not vals:
            return None
        mn, mx = min(vals), max(vals)
        return f"{mn:,} — {mx:,}" if mn != mx else f"{mn:,}"

    return {
        "next_day_bias": dominant,
        "bull_pct": bull_pct,
        "bear_pct": bear_pct,
        "s1": _zone(s1_vals),
        "s2": _zone(s2_vals),
        "r1": _zone(r1_vals),
        "r2": _zone(r2_vals),
        "expected_gap": ("Positive" if dominant == "BULLISH"
                         else "Negative" if dominant == "BEARISH" else "Flat"),
        "thesis": (f"{bull_pct}% of desks bullish, {bear_pct}% bearish — "
                   f"Street leans {dominant.lower()} for tomorrow's session."),
        "source_headline": "Aggregated across institutional desk reports",
        "source_link": "#",
    }


_build_consensus_call = _build_consensus



# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Brokerage Radar (Heavyweight Stock Calls)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

HEAVYWEIGHT_TICKERS = {
    "HDFC Bank": "HDFCBANK", "HDFC": "HDFCBANK",
    "Reliance": "RELIANCE", "RIL": "RELIANCE",
    "ICICI Bank": "ICICIBANK",
    "Infosys": "INFY",
    "TCS": "TCS",
    "Bharti Airtel": "BHARTIARTL", "Airtel": "BHARTIARTL",
    "L&T": "LT", "Larsen": "LT",
    "ITC": "ITC",
    "Axis Bank": "AXISBANK",
    "SBI": "SBIN",
    "Nifty": "NIFTY50", "NIFTY": "NIFTY50",
}

_SECTOR_MAP = {
    "HDFCBANK": "Banking & Finance", "ICICIBANK": "Banking & Finance",
    "AXISBANK": "Banking & Finance", "SBIN": "Banking & Finance",
    "RELIANCE": "Energy & Oil", "INFY": "Information Technology",
    "TCS": "Information Technology", "BHARTIARTL": "Telecom",
    "LT": "Infrastructure", "ITC": "FMCG", "NIFTY50": "Broad Market",
}


