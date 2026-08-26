"""
institutional_scraper.py — Institutional BTST & Next-Day Prediction Radar.

Scrapes and aggregates:
  1. Tactical Next-Day Outlooks (Religare, Anand Rathi, HDFC Sec, IndiaCharts, Consensus)
     → next_day_bias, S1/S2, R1/R2, expected_gap, actionable_thesis
  2. Strategic Brokerage Calls on NIFTY Heavyweights
     → institution, stock, action, target_price, upside_pct, sector_impact

All data is served from a local disk cache written by the scheduler at:
  08:30 IST (pre-market), 15:15 IST (BTST window), 17:30 IST (post-market).

The dashboard load hits the cache at 0ms latency.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

import pytz
import requests
import feedparser

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")
_CACHE_FILENAME = "institutional_radar_cache.json"
_CACHE_TTL_HOURS = 14  # cache is valid for ~14 hours (one trading day)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Provider Metadata
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TACTICAL_PROVIDERS = [
    {"key": "religare",    "name": "Religare Broking",     "analyst": "Ajit Mishra"},
    {"key": "anand_rathi", "name": "Anand Rathi Research",  "analyst": "Research Desk"},
    {"key": "hdfc_sec",    "name": "HDFC Securities",       "analyst": "Technical Desk"},
    {"key": "indiacharts", "name": "IndiaCharts / Strike",  "analyst": "Rohit Srivastava"},
    {"key": "consensus",   "name": "Street Consensus",      "analyst": "ET / Moneycontrol"},
]

BROKERAGE_PROVIDERS = [
    "Morgan Stanley", "Goldman Sachs", "Jefferies",
    "JPMorgan", "CLSA", "Bernstein", "Nomura",
    "Kotak Institutional Equities", "Motilal Oswal",
    "ICICI Securities", "HDFC Securities", "Nuvama",
]

# Google News RSS searches for brokerage calls
BROKERAGE_RSS_QUERIES = [
    "Nifty Morgan Stanley Goldman Sachs target India",
    "Jefferies CLSA India stock upgrade downgrade target",
    "Kotak Motilal ICICI Nifty market prediction tomorrow",
    "Religare Anand Rathi Nifty prediction tomorrow support resistance",
    "HDFC Securities Nifty Bank Nifty tomorrow technical analysis",
    "India stock market tomorrow prediction support resistance level",
    "Nifty next day analysis broker report",
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Bias Text Classification
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _classify_bias(text: str) -> str:
    """Return BULLISH, BEARISH, or RANGEBOUND from text."""
    t = text.lower()
    bull_kw = ["bullish", "positive", "upside", "buy", "long", "gap up", "rally", "overweight", "upgrade"]
    bear_kw = ["bearish", "negative", "downside", "sell", "short", "gap down", "decline", "underweight", "downgrade"]
    score = sum(1 for kw in bull_kw if kw in t) - sum(1 for kw in bear_kw if kw in t)
    if score > 0:
        return "BULLISH"
    if score < 0:
        return "BEARISH"
    return "RANGEBOUND"


def _extract_nifty_levels(text: str) -> dict:
    """Extract support/resistance levels from text using regex."""
    # Match patterns like: 24,100 / 24100 / 24,350 etc.
    numbers = re.findall(r'\b2[0-9][,\s]?[0-9]{3}\b', text)
    cleaned = []
    for n in numbers:
        try:
            val = int(n.replace(",", "").replace(" ", ""))
            if 20000 <= val <= 30000:
                cleaned.append(val)
        except ValueError:
            continue
    cleaned = sorted(set(cleaned))
    return cleaned


def _action_from_text(text: str) -> str:
    """Classify brokerage action from headline text."""
    t = text.lower()
    if any(k in t for k in ["strong buy", "overweight", "outperform", "add", "upgrade"]):
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RSS Feed Fetcher
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _fetch_rss_articles(query: str, max_items: int = 8) -> list[dict]:
    """Fetch Google News RSS for a given query and return list of article dicts."""
    try:
        encoded = requests.utils.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en-IN&gl=IN&ceid=IN:en"
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:max_items]:
            items.append({
                "title": entry.get("title", ""),
                "summary": entry.get("summary", ""),
                "published": entry.get("published", ""),
                "link": entry.get("link", "#"),
            })
        return items
    except Exception as e:
        logger.warning(f"RSS fetch failed for '{query}': {e}")
        return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Tactical Desk Scraping
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _build_tactical_provider_calls(articles: list[dict]) -> dict[str, dict]:
    """
    Map scraped articles to provider-specific calls.
    Returns a dict: provider_key -> { next_day_bias, s1, s2, r1, r2, expected_gap, thesis, source_headline }
    """
    provider_kw = {
        "religare":    ["religare", "ajit mishra"],
        "anand_rathi": ["anand rathi"],
        "hdfc_sec":    ["hdfc securities", "hdfc sec", "nagaraj shetti"],
        "indiacharts": ["indiacharts", "strike money", "rohit srivastava"],
    }

    provider_hits: dict[str, list[dict]] = {p: [] for p in provider_kw}

    for art in articles:
        combined = (art.get("title", "") + " " + art.get("summary", "")).lower()
        for pkey, keywords in provider_kw.items():
            if any(kw in combined for kw in keywords):
                provider_hits[pkey].append(art)

    result: dict[str, dict] = {}

    for pkey, hits in provider_hits.items():
        if not hits:
            continue
        # Use first matching article
        best = hits[0]
        combined_text = best.get("title", "") + " " + best.get("summary", "")
        levels = _extract_nifty_levels(combined_text)
        bias = _classify_bias(combined_text)

        # Derive S/R from sorted levels: below spot = supports, above spot = resistances
        # Without live spot, use the median to split
        supports = [l for l in levels if l < 24500][:4]  # rough pre-split
        resistances = [l for l in levels if l >= 24100][:4]

        s1 = supports[-1] if len(supports) >= 1 else None
        s2 = supports[-2] if len(supports) >= 2 else None
        r1 = resistances[0] if len(resistances) >= 1 else None
        r2 = resistances[1] if len(resistances) >= 2 else None

        # Thesis: first sentence of summary
        thesis_raw = best.get("summary", best.get("title", ""))
        thesis = re.split(r'[.!?]', thesis_raw)[0].strip()
        if len(thesis) > 140:
            thesis = thesis[:140] + "..."

        result[pkey] = {
            "next_day_bias": bias,
            "s1": s1,
            "s2": s2,
            "r1": r1,
            "r2": r2,
            "expected_gap": "Positive" if bias == "BULLISH" else ("Negative" if bias == "BEARISH" else "Flat"),
            "thesis": thesis,
            "source_headline": best.get("title", ""),
            "source_link": best.get("link", "#"),
        }

    return result


def _build_consensus_call(provider_calls: dict) -> dict:
    """Aggregate provider calls into a street consensus row."""
    if not provider_calls:
        return {}

    bias_counts = {"BULLISH": 0, "BEARISH": 0, "RANGEBOUND": 0}
    all_s1, all_s2, all_r1, all_r2 = [], [], [], []

    for call in provider_calls.values():
        b = call.get("next_day_bias", "RANGEBOUND")
        bias_counts[b] = bias_counts.get(b, 0) + 1
        if call.get("s1"): all_s1.append(call["s1"])
        if call.get("s2"): all_s2.append(call["s2"])
        if call.get("r1"): all_r1.append(call["r1"])
        if call.get("r2"): all_r2.append(call["r2"])

    dominant_bias = max(bias_counts, key=bias_counts.get)
    total = sum(bias_counts.values()) or 1
    bull_pct = round(bias_counts["BULLISH"] / total * 100)
    bear_pct = round(bias_counts["BEARISH"] / total * 100)

    def _zone(vals: list) -> Optional[str]:
        if not vals:
            return None
        mn, mx = min(vals), max(vals)
        return f"{mn:,} — {mx:,}" if mn != mx else f"{mn:,}"

    return {
        "next_day_bias": dominant_bias,
        "bull_pct": bull_pct,
        "bear_pct": bear_pct,
        "s1": _zone(all_s1),
        "s2": _zone(all_s2),
        "r1": _zone(all_r1),
        "r2": _zone(all_r2),
        "expected_gap": "Positive" if dominant_bias == "BULLISH" else ("Negative" if dominant_bias == "BEARISH" else "Flat"),
        "thesis": f"{bull_pct}% of desks bullish, {bear_pct}% bearish for tomorrow's session.",
        "source_headline": "Aggregated across institutional desk reports",
        "source_link": "#",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Brokerage Radar Scraping
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
    "NIFTY": "NIFTY50", "Nifty": "NIFTY50",
}

def _extract_brokerage_call(article: dict) -> Optional[dict]:
    """Extract structured brokerage call from article dict."""
    title = article.get("title", "")
    summary = article.get("summary", "")
    combined = title + " " + summary

    # Match institution
    institution = None
    for inst in BROKERAGE_PROVIDERS:
        if inst.lower() in combined.lower():
            institution = inst
            break
    if not institution:
        return None

    # Match heavyweight stock
    stock_symbol = "NIFTY50"
    stock_name = "NIFTY 50"
    for name, sym in HEAVYWEIGHT_TICKERS.items():
        if name.lower() in combined.lower():
            stock_symbol = sym
            stock_name = name
            break

    action = _action_from_text(combined)

    # Extract target price
    target_match = re.search(r'(?:target|TP|price target)[^\d]*₹?\s*(\d[\d,]*)', combined, re.IGNORECASE)
    target_price = None
    if target_match:
        try:
            target_price = int(target_match.group(1).replace(",", ""))
        except ValueError:
            pass

    # Sector
    sector_map = {
        "HDFCBANK": "Banking & Finance", "ICICIBANK": "Banking & Finance",
        "AXISBANK": "Banking & Finance", "SBIN": "Banking & Finance",
        "RELIANCE": "Energy & Oil", "INFY": "Information Technology",
        "TCS": "Information Technology", "BHARTIARTL": "Telecom",
        "LT": "Infrastructure", "ITC": "FMCG", "NIFTY50": "Broad Market",
    }
    sector = sector_map.get(stock_symbol, "Equity Markets")

    # Short thesis
    thesis = re.split(r'[.!?]', summary)[0].strip() if summary else title
    if len(thesis) > 120:
        thesis = thesis[:120] + "..."

    return {
        "institution": institution,
        "stock_name": stock_name,
        "stock_symbol": stock_symbol,
        "action": action,
        "target_price": target_price,
        "upside_pct": None,  # computed later if we have a live price
        "sector": sector,
        "thesis": thesis,
        "source_link": article.get("link", "#"),
        "published": article.get("published", ""),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Confluence Matrix Builder
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _build_confluence_matrix(provider_calls: dict, consensus: dict, nifty_spot: Optional[float] = None) -> dict:
    """
    Build the structured matrix data used by the frontend table.
    Providers are in columns; levels (R2, R1, Spot, S1, S2) are in rows.
    """
    providers_ordered = []
    for p in TACTICAL_PROVIDERS:
        key = p["key"]
        if key == "consensus":
            call = consensus
        else:
            call = provider_calls.get(key, {})
        providers_ordered.append({
            "key": key,
            "name": p["name"],
            "analyst": p["analyst"],
            "call": call,
        })

    # Compute consensus numeric zones for upside/downside distance display
    def _parse_zone_low(zone_str) -> Optional[int]:
        if not zone_str:
            return None
        try:
            return int(str(zone_str).replace(",", "").split("—")[0].strip())
        except (ValueError, IndexError):
            return None

    consensus_s1 = _parse_zone_low(consensus.get("s1"))
    consensus_r1_str = consensus.get("r1", "")
    consensus_r1 = _parse_zone_low(consensus_r1_str)

    upside_pts, downside_pts, rr_ratio = None, None, None
    if nifty_spot and consensus_r1 and consensus_s1:
        upside_pts = round(consensus_r1 - nifty_spot)
        downside_pts = round(nifty_spot - consensus_s1)
        if downside_pts and downside_pts > 0:
            rr_ratio = round(upside_pts / downside_pts, 2)

    return {
        "providers": providers_ordered,
        "nifty_spot": nifty_spot,
        "upside_pts": upside_pts,
        "downside_pts": downside_pts,
        "rr_ratio": rr_ratio,
        "consensus_bias": consensus.get("next_day_bias", "RANGEBOUND"),
        "bull_pct": consensus.get("bull_pct", 0),
        "bear_pct": consensus.get("bear_pct", 0),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main Fetch & Cache Functions
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_institutional_radar(nifty_spot: Optional[float] = None) -> dict:
    """
    Full scrape: fetches news, classifies provider calls, builds confluence matrix
    and brokerage radar. Returns structured dict ready for JSON serialization.
    """
    logger.info("🏛️ Fetching Institutional BTST Radar data...")

    # 1. Fetch articles for tactical desk calls
    tactical_articles = []
    for query in [
        "Religare Anand Rathi Nifty tomorrow support resistance",
        "HDFC Securities Nifty Bank Nifty tomorrow technical level",
        "Nifty prediction tomorrow market analyst India",
        "IndiaCharts Strike Money Nifty analysis tomorrow",
    ]:
        tactical_articles.extend(_fetch_rss_articles(query, max_items=6))
        time.sleep(0.3)

    # 2. Fetch articles for brokerage radar
    brokerage_articles = []
    for query in BROKERAGE_RSS_QUERIES[:4]:  # limit to 4 to save time
        brokerage_articles.extend(_fetch_rss_articles(query, max_items=5))
        time.sleep(0.3)

    # 3. Build provider calls
    provider_calls = _build_tactical_provider_calls(tactical_articles + brokerage_articles)
    consensus = _build_consensus_call(provider_calls) if provider_calls else {}

    # 4. Build confluence matrix
    matrix = _build_confluence_matrix(provider_calls, consensus, nifty_spot)

    # 5. Build brokerage radar
    brokerage_calls = []
    seen_inst_stock = set()
    for art in brokerage_articles + tactical_articles:
        call = _extract_brokerage_call(art)
        if not call:
            continue
        dedup_key = f"{call['institution']}_{call['stock_symbol']}"
        if dedup_key in seen_inst_stock:
            continue
        seen_inst_stock.add(dedup_key)
        brokerage_calls.append(call)

    now_ist = datetime.now(IST)
    result = {
        "fetched_at_ist": now_ist.strftime("%d %b %Y, %I:%M %p IST"),
        "fetched_ts": now_ist.timestamp(),
        "nifty_spot": nifty_spot,
        "consensus_bias": consensus.get("next_day_bias", "RANGEBOUND"),
        "bull_pct": consensus.get("bull_pct", 0),
        "bear_pct": consensus.get("bear_pct", 0),
        "provider_calls": provider_calls,
        "consensus": consensus,
        "confluence_matrix": matrix,
        "brokerage_calls": brokerage_calls[:12],  # cap to 12
        "tactical_articles_found": len(tactical_articles),
        "brokerage_articles_found": len(brokerage_articles),
    }
    logger.info(
        f"✅ Institutional Radar fetched: {len(provider_calls)} desk calls, "
        f"{len(brokerage_calls)} brokerage calls. Consensus: {consensus.get('next_day_bias')}"
    )
    return result


def get_cache_path(history_dir: str) -> str:
    return os.path.join(history_dir, _CACHE_FILENAME)


def save_institutional_radar_cache(data: dict, history_dir: str) -> None:
    """Persist radar data to disk as JSON."""
    try:
        os.makedirs(history_dir, exist_ok=True)
        path = get_cache_path(history_dir)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"💾 Institutional Radar cached to {path}")
    except Exception as e:
        logger.warning(f"Could not cache institutional radar: {e}")


def load_institutional_radar_cache(history_dir: str) -> Optional[dict]:
    """Load cached radar data if it is fresh enough (within TTL)."""
    try:
        path = get_cache_path(history_dir)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ts = data.get("fetched_ts", 0)
        age_hours = (time.time() - ts) / 3600
        if age_hours > _CACHE_TTL_HOURS:
            logger.info(f"Institutional Radar cache stale ({age_hours:.1f}h). Needs refresh.")
            return None
        return data
    except Exception as e:
        logger.warning(f"Could not load institutional radar cache: {e}")
        return None


def get_cached_institutional_radar(
    history_dir: str,
    nifty_spot: Optional[float] = None,
    force_refresh: bool = False,
) -> dict:
    """
    Primary entry point: return cached data if fresh, else fetch + cache + return.
    Called by auto_scheduler.py (scheduled) and server.py (/api/institutional-radar).
    """
    if not force_refresh:
        cached = load_institutional_radar_cache(history_dir)
        if cached:
            return cached
    data = fetch_institutional_radar(nifty_spot=nifty_spot)
    save_institutional_radar_cache(data, history_dir)
    return data
