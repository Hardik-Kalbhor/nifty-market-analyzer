"""
institutional/constants.py — Provider configurations, headers, and thresholds for institutional radar.
"""

import logging
import pytz
from typing import Optional
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



