"""
scraper/constants.py — Keywords, feeds, queries, and headers for scraping.
"""

import re



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
    "social_sentiment": [
        "retail trader", "retail investors", "reddit", "fintwit", "bull gang",
        "bear gang", "call buyers", "put buyers", "short squeeze", "yolo",
        "loss porn", "profit booking", "fomo", "options buying", "expiry zero hero",
    ],
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RSS Feed Sources & Social Channels
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
    # FinTwit / Twitter sentiment (syndicated via Google News RSS)
    {"query": "site:x.com NIFTY 50 OR Bank Nifty", "category": "social_sentiment"},
    {"query": "site:twitter.com NIFTY stock market India", "category": "social_sentiment"},
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

REDDIT_SUBREDDITS: list[str] = [
    "IndianStockMarket",
    "dalalstreetbets",
]

TELEGRAM_CHANNELS: list[str] = [
    "CNBCTV18Live",
    "moneycontrolcom",
]

SPAM_PROMO_REGEX = re.compile(
    r"(join\s+(vip|channel|premium|group)|guaranteed\s+profit|dm\s+for|whatsapp\s+us|call\s+now|contact\s+@|\+91\s*\d{10}|100%\s+accuracy|free\s+trial|jackpot\s+call|sure\s+shot|multibagger\s+calls)",
    re.I
)

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


