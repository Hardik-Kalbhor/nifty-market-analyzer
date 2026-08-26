"""
institutional_scraper.py — Institutional BTST & Next-Day Prediction Radar.

Strategy (v2):
  EACH provider gets a dedicated ET Markets search URL using their analyst name.
  For every match we fetch the full article body (not just the RSS summary) and
  run level extraction over the complete text — giving us real S1/S2/R1/R2 numbers.

  Providers:
    Tactical (next-day S/R + bias):
      Religare Broking   → Ajit Mishra
      Anand Rathi        → Ganesh Dongre / Jigar Patel
      HDFC Securities    → Nagaraj Shetti / Vinay Rajani
      IndiaCharts/Strike → Rohit Srivastava
      Street Consensus   → aggregated

    Strategic (brokerage calls on heavyweights):
      Morgan Stanley, Goldman Sachs, Jefferies, JPMorgan, CLSA,
      Kotak Institutional Equities, Motilal Oswal, ICICI Securities, Nuvama

  Cache: written by auto_scheduler.py every scheduled run (5×/day).
  Dashboard hits disk cache at 0ms latency — no scraping on page load.
"""

import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Optional

import pytz
import requests
import feedparser
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")
_CACHE_FILENAME = "institutional_radar_cache.json"
_CACHE_TTL_HOURS = 14  # valid for one trading day

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
# Provider Config
# Each provider has:
#   key       — internal ID
#   name      — display name
#   analyst   — analyst name(s) shown in table
#   et_query  — ET Markets search query to find today's article
#   rss_query — Google News RSS quoted query as fallback
#   kw_match  — keywords that must appear in title/body to confirm relevance
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TACTICAL_PROVIDERS = [
    {
        "key": "religare",
        "name": "Religare Broking",
        "analyst": "Ajit Mishra",
        "et_query": "Ajit Mishra Nifty support resistance",
        "rss_query": '("Ajit Mishra" OR "Religare") Nifty',
        "kw_match": ["ajit mishra", "religare"],
    },
    {
        "key": "anand_rathi",
        "name": "Anand Rathi",
        "analyst": "Ganesh Dongre",
        "et_query": "Anand Rathi Nifty support resistance outlook",
        "rss_query": '("Anand Rathi" OR "Ganesh Dongre" OR "Jigar Patel") Nifty',
        "kw_match": ["anand rathi", "ganesh dongre", "jigar patel", "mehul kothari"],
    },
    {
        "key": "hdfc_sec",
        "name": "HDFC Securities",
        "analyst": "Nagaraj Shetti",
        "et_query": "Nagaraj Shetti Nifty support resistance",
        "rss_query": '("HDFC Securities" OR "Nagaraj Shetti" OR "Vinay Rajani") Nifty',
        "kw_match": ["nagaraj shetti", "vinay rajani", "hdfc securities", "hdfc sec"],
    },
    {
        "key": "indiacharts",
        "name": "IndiaCharts / Strike",
        "analyst": "Rohit Srivastava",
        "et_query": "Rohit Srivastava Nifty support resistance",
        "rss_query": '("Rohit Srivastava" OR "IndiaCharts" OR "Strike Money") Nifty',
        "kw_match": ["rohit srivastava", "indiacharts", "strike money"],
    },
]


BROKERAGE_PROVIDERS = [
    "Morgan Stanley", "Goldman Sachs", "Jefferies",
    "JPMorgan", "CLSA", "Bernstein", "Nomura",
    "Kotak Institutional Equities", "Motilal Oswal",
    "ICICI Securities", "HDFC Securities", "Nuvama",
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Core Text Utilities
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_NIFTY_FLOOR = 22000
_NIFTY_CEIL  = 28000


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
    rss_articles = _rss_articles(provider["rss_query"], max_items=10)
    for art in rss_articles:
        title = art.get("title", "")
        summary = art.get("summary", "")
        combined = title + " " + summary
        if any(kw in combined.lower() for kw in kw_match):
            matching_texts.append(combined)
            if not best_title:
                best_title = title
                best_link = art.get("link", "#")
                best_thesis = _first_sentence(title)

    if not matching_texts:
        logger.info(f"No content found for provider: {provider['key']}")
        return None

    combined_all = " ".join(matching_texts)
    levels = _extract_levels(combined_all)
    bias = _classify_bias(combined_all)
    gap = _classify_gap(bias, combined_all)

    # Split levels into supports and resistances relative to spot (or median)
    if nifty_spot and levels:
        supports = [lvl for lvl in levels if lvl < nifty_spot]
        resistances = [lvl for lvl in levels if lvl >= nifty_spot]
    elif len(levels) >= 2:
        mid_idx = len(levels) // 2
        supports = levels[:mid_idx]
        resistances = levels[mid_idx:]
    elif len(levels) == 1:
        supports = []
        resistances = levels
    else:
        supports = []
        resistances = []

    s1 = supports[-1] if len(supports) >= 1 else None
    s2 = supports[-2] if len(supports) >= 2 else None
    r1 = resistances[0] if len(resistances) >= 1 else None
    r2 = resistances[1] if len(resistances) >= 2 else None

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

def _build_confluence_matrix(
    provider_calls: dict,
    consensus: dict,
    nifty_spot: Optional[float],
) -> dict:
    providers_ordered = []
    all_providers = TACTICAL_PROVIDERS + [{"key": "consensus", "name": "Street Consensus", "analyst": "ET / MC"}]
    for p in all_providers:
        key = p["key"]
        call = consensus if key == "consensus" else provider_calls.get(key, {})
        providers_ordered.append({"key": key, "name": p["name"], "analyst": p["analyst"], "call": call})

    def _parse_low(zone_str) -> Optional[int]:
        if not zone_str:
            return None
        try:
            return int(str(zone_str).replace(",", "").split("—")[0].strip())
        except (ValueError, IndexError):
            return None

    upside_pts = downside_pts = rr_ratio = None
    cr1 = _parse_low(consensus.get("r1"))
    cs1 = _parse_low(consensus.get("s1"))
    if nifty_spot and cr1 and cs1:
        upside_pts = round(cr1 - nifty_spot)
        downside_pts = round(nifty_spot - cs1)
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
# Main Fetch & Cache
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_institutional_radar(nifty_spot: Optional[float] = None) -> dict:
    """
    Full scrape: ET Markets article body per provider → level extraction,
    then brokerage radar via RSS. Returns structured dict.
    """
    logger.info("🏛️ Institutional Radar: Starting per-provider ET scrape...")

    provider_calls: dict = {}
    for p in TACTICAL_PROVIDERS:
        logger.info(f"  → Fetching {p['name']} ({p['analyst']})...")
        call = _build_provider_call(p, nifty_spot=nifty_spot)
        if call:
            provider_calls[p["key"]] = call
            logger.info(
                f"  ✅ {p['name']}: bias={call['next_day_bias']}, "
                f"R1={call.get('r1')}, S1={call.get('s1')}, "
                f"levels_raw={call.get('raw_levels_found', [])[:6]}"
            )
        else:
            logger.warning(f"  ⚠️  {p['name']}: No data found")
        time.sleep(0.3)  # polite delay between providers


    consensus = _build_consensus(provider_calls) if provider_calls else {}
    matrix = _build_confluence_matrix(provider_calls, consensus, nifty_spot)

    logger.info("🏛️ Institutional Radar: Fetching brokerage radar...")
    brokerage_calls = _fetch_brokerage_calls()

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
        "brokerage_calls": brokerage_calls,
        "providers_fetched": len(provider_calls),
        "brokerage_fetched": len(brokerage_calls),
    }

    logger.info(
        f"✅ Institutional Radar done: {len(provider_calls)}/4 providers, "
        f"{len(brokerage_calls)} brokerage calls. "
        f"Consensus: {consensus.get('next_day_bias')}"
    )
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Cache Helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_cache_path(history_dir: str) -> str:
    return os.path.join(history_dir, _CACHE_FILENAME)


def save_institutional_radar_cache(data: dict, history_dir: str) -> None:
    try:
        os.makedirs(history_dir, exist_ok=True)
        path = get_cache_path(history_dir)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"💾 Institutional Radar cached → {path}")
    except Exception as e:
        logger.warning(f"Cache save failed: {e}")


def load_institutional_radar_cache(history_dir: str) -> Optional[dict]:
    import time as _t
    try:
        path = get_cache_path(history_dir)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        age_hours = (_t.time() - data.get("fetched_ts", 0)) / 3600
        if age_hours > _CACHE_TTL_HOURS:
            logger.info(f"Institutional Radar cache stale ({age_hours:.1f}h). Needs refresh.")
            return None
        return data
    except Exception as e:
        logger.warning(f"Cache load failed: {e}")
        return None


def get_cached_institutional_radar(
    history_dir: str,
    nifty_spot: Optional[float] = None,
    force_refresh: bool = False,
) -> dict:
    """
    Primary entry point.
    Returns cached data if fresh; otherwise fetches, caches, and returns.
    Called by auto_scheduler.py (scheduled) and server.py (/api/institutional-radar).
    """
    if not force_refresh:
        cached = load_institutional_radar_cache(history_dir)
        if cached:
            return cached
    data = fetch_institutional_radar(nifty_spot=nifty_spot)
    save_institutional_radar_cache(data, history_dir)
    return data
