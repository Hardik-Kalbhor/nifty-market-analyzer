"""
analyzer/patterns.py — Regex morphological patterns and keyword dicts.

Contains: BULLISH_PATTERNS, BEARISH_PATTERNS, BULLISH_KEYWORDS, BEARISH_KEYWORDS,
EVENT_RISK_KEYWORDS, CATEGORY_IMPORTANCE, SECTOR_WEIGHT, GLOBAL_MARKET_WEIGHTS.
"""

import re

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. REGEX MORPHOLOGICAL PATTERNS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BULLISH_PATTERNS: list[tuple[re.Pattern, int, str]] = [
    (re.compile(r'crude\s*(oil\s*)?(fell?|fall(?:s|ing|en)?|drop(?:s|ped|ping)?|declin\w*|slump\w*|tumbl\w*|eas\w*|soft\w*)', re.I), 3, "crude_fall"),
    (re.compile(r'(oil|brent)\s*(price\s*)?(fell?|fall\w*|drop\w*|declin\w*|eas\w*|soft\w*|slip\w*)', re.I), 3, "oil_fall"),
    (re.compile(r'inflation\s*(fell?|fall\w*|cool\w*|eas\w*|declin\w*|drop\w*|slow\w*|moder\w*|dip\w*)', re.I), 3, "inflation_cool"),
    (re.compile(r'cpi\s*(fell?|fall\w*|drop\w*|declin\w*|cool\w*|eas\w*|low\w*)', re.I), 2, "cpi_cool"),
    (re.compile(r'f(ii|pi)\s*(net\s*)?(buy\w*|purchas\w*|inflow\w*)', re.I), 3, "fii_buying"),
    (re.compile(r'foreign\s*(institutional|portfolio)?\s*(investor\w*)?\s*(buy\w*|inflow\w*|purchas\w*)', re.I), 3, "foreign_inflow"),
    (re.compile(r'(interest\s*|repo\s*|policy\s*)?rate\s*(cut\w*|reduc\w*|slash\w*|lower\w*)', re.I), 3, "rate_cut"),
    (re.compile(r'(rbi|fed|central\s*bank)\s*cut\w*\s*(rate\w*)?', re.I), 3, "central_bank_cut"),
    (re.compile(r'gdp\s*(grew?|grow\w*|expand\w*|beat\w*|surpass\w*|outperform\w*)', re.I), 2, "gdp_growth"),
    (re.compile(r'economic?\s*(recover\w*|expan\w*|boom\w*|rebound\w*)', re.I), 2, "economic_recovery"),
    (re.compile(r'(profit|earnings?|revenue|result\w*)\s*(beat\w*|surpass\w*|exceed\w*|top\w*|outperform\w*)', re.I), 3, "earnings_beat"),
    (re.compile(r'(net\s*profit|pat)\s*(jump\w*|surge\w*|soar\w*|rise\w*|rose|climb\w*)', re.I), 2, "profit_jump"),
    (re.compile(r'rupee\s*(strength\w*|appreciat\w*|gain\w*|rise\w*|rose|recover\w*|climb\w*)', re.I), 2, "rupee_strength"),
    (re.compile(r'(market|nifty|sensex|index)\s*(rally\w*|surge\w*|soar\w*|jump\w*|climb\w*|rise\w*)', re.I), 2, "market_rally"),
    (re.compile(r'(monetary|fiscal)\s*(eas\w*|stimul\w*|support\w*|accommodat\w*)', re.I), 2, "monetary_easing"),
    (re.compile(r'(ceasefire|truce|peace\s*(deal|talk\w*|agreement)|de.escalat\w*)', re.I), 3, "peace"),
    (re.compile(r'pmi\s*(above\s*50|expan\w*|improv\w*|rise\w*|rose|climb\w*)', re.I), 2, "pmi_expansion"),
    (re.compile(r'gst\s*(collection\w*|revenue\w*)\s*(rise\w*|jump\w*|high\w*|record\w*|beat\w*)', re.I), 2, "gst_collection"),
]

BEARISH_PATTERNS: list[tuple[re.Pattern, int, str]] = [
    (re.compile(r'crude\s*(oil\s*)?(rose|rise\w*|surge\w*|spike\w*|jump\w*|soar\w*|rally\w*|climb\w*)', re.I), 3, "crude_rise"),
    (re.compile(r'(oil|brent)\s*(price\s*)?(rose|rise\w*|surge\w*|spike\w*|jump\w*|soar\w*|rally\w*)', re.I), 3, "oil_rise"),
    (re.compile(r'inflation\s*(rose|rise\w*|surge\w*|spike\w*|jump\w*|acceler\w*|climb\w*|high\w*)', re.I), 3, "inflation_rise"),
    (re.compile(r'cpi\s*(rose|rise\w*|surge\w*|spike\w*|jump\w*|high\w*|climb\w*)', re.I), 2, "cpi_rise"),
    (re.compile(r'f(ii|pi)\s*(net\s*)?(sell\w*|outflow\w*)', re.I), 3, "fii_selling"),
    (re.compile(r'foreign\s*(institutional|portfolio)?\s*(investor\w*)?\s*(sell\w*|outflow\w*|exit\w*|flee\w*)', re.I), 3, "foreign_outflow"),
    (re.compile(r'(interest\s*|repo\s*|policy\s*)?rate\s*(hike\w*|increas\w*|rais\w*|tighten\w*)', re.I), 3, "rate_hike"),
    (re.compile(r'(rbi|fed|central\s*bank)\s*(hike\w*|rais\w*|increas\w*)\s*(rate\w*)?', re.I), 3, "central_bank_hike"),
    (re.compile(r'gdp\s*(shrank?|shrink\w*|contract\w*|declin\w*|miss\w*|fell?|fall\w*)', re.I), 2, "gdp_contraction"),
    (re.compile(r'economic?\s*(contraction\w*|slowdown\w*|recession\w*|weakness\w*|declin\w*)', re.I), 2, "economic_weakness"),
    (re.compile(r'(profit|earnings?|revenue|result\w*)\s*(miss\w*|disappoint\w*|fall\w*|drop\w*|declin\w*|below\w*)', re.I), 3, "earnings_miss"),
    (re.compile(r'(net\s*profit|pat)\s*(fell?|fall\w*|drop\w*|declin\w*|shrink\w*|plunge\w*)', re.I), 2, "profit_fall"),
    (re.compile(r'rupee\s*(weaken\w*|depreciat\w*|fell?|fall\w*|drop\w*|plunge\w*|hit\w*\s*low)', re.I), 2, "rupee_weak"),
    (re.compile(r'(market|nifty|sensex|index)\s*(crash\w*|plunge\w*|slump\w*|fell?|fall\w*|drop\w*|declin\w*)', re.I), 2, "market_fall"),
    (re.compile(r'(war|conflict|sanction\w*|invasion|escalat\w*|missile\s*strike\w*|military\s*action)', re.I), 3, "geopolitical_risk"),
    (re.compile(r'pmi\s*(below\s*50|contract\w*|declin\w*|fell?|fall\w*|weaken\w*)', re.I), 2, "pmi_contraction"),
    (re.compile(r'(layoff\w*|job\s*cut\w*|retrench\w*|unemploy\w*\s*rise\w*|jobless\s*claim\w*)', re.I), 2, "job_loss"),
    (re.compile(r'(default\w*|fraud\w*|scam\w*|ponzi|money\s*launder\w*)', re.I), 3, "default_fraud"),
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. ORIGINAL KEYWORD DICTS (fallback layer)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BULLISH_KEYWORDS: dict[str, int] = {
    "rate cut": 3, "dovish": 3, "easing": 2, "accommodative": 2,
    "pause on rate": 2, "rate unchanged": 1, "lower interest rate": 3,
    "policy support": 2, "stimulus": 3, "quantitative easing": 2,
    "liquidity injection": 2, "fii buying": 3, "fii inflow": 3,
    "fii net buyer": 3, "dii buying": 2, "dii inflow": 2,
    "dii support": 2, "foreign inflow": 3, "fpi inflow": 3,
    "fpi buying": 3, "institutional buying": 2, "inflation cool": 3,
    "inflation eas": 2, "inflation fall": 2, "inflation decline": 2,
    "cpi fell": 2, "cpi drop": 2, "cpi lower": 2, "inflation below": 2,
    "inflation slow": 2, "gdp growth": 2, "gdp beat": 3,
    "gdp expand": 2, "strong economy": 2, "economic recovery": 2,
    "economic growth": 2, "recovery": 1, "robust growth": 2,
    "manufacturing pmi": 1, "services pmi": 1, "pmi expand": 2,
    "job growth": 2, "employment rise": 2, "crude fall": 3,
    "crude drop": 3, "crude declin": 3, "oil price fall": 3,
    "oil price drop": 3, "oil prices ease": 2, "brent fall": 2,
    "brent declin": 2, "gold rally": 1, "ceasefire": 3,
    "peace talk": 2, "peace deal": 3, "trade deal": 2,
    "de-escalat": 2, "diplomatic solution": 2, "tension eas": 2,
    "strong earnings": 3, "beat estimate": 3, "profit surge": 3,
    "profit jump": 2, "revenue growth": 2, "revenue beat": 2,
    "order win": 2, "record profit": 3, "upgrade": 2,
    "outperform": 2, "strong result": 2, "better-than-expected": 3,
    "above estimate": 2, "earnings beat": 3, "dividend declared": 1,
    "buyback": 1, "rally": 2, "market surge": 2, "market jump": 2,
    "bullish": 2, "all-time high": 2, "breakout": 2, "gap up": 2,
    "green": 1, "market gain": 2, "positive close": 1,
    "buying interest": 2, "rupee strength": 2, "rupee appreciat": 2,
    "gst collection": 2, "reform": 1, "disinvestment": 1,
    "privatisation": 1, "Make in India": 1,
}

BEARISH_KEYWORDS: dict[str, int] = {
    "rate hike": 3, "hawkish": 3, "tightening": 2, "restrictive": 2,
    "rate increase": 3, "higher interest rate": 3,
    "quantitative tightening": 2, "liquidity drain": 2,
    "tapering": 2, "fii selling": 3, "fii outflow": 3,
    "fii net seller": 3, "foreign outflow": 3, "fpi outflow": 3,
    "fpi selling": 3, "capital flight": 3, "institutional selling": 2,
    "inflation rise": 3, "inflation surge": 3, "inflation spike": 3,
    "inflation high": 2, "inflation above": 2, "inflation accelerat": 2,
    "cpi rose": 2, "cpi surge": 3, "cpi jump": 2, "cpi higher": 2,
    "cpi spike": 3, "price pressure": 2, "cost push": 2,
    "recession": 3, "slowdown": 2, "contraction": 3, "gdp miss": 2,
    "gdp contract": 3, "gdp decline": 2, "economic weakness": 2,
    "weak economy": 2, "unemployment rise": 2, "jobless claim": 2,
    "layoff": 2, "job loss": 2, "pmi contract": 2, "crude surge": 3,
    "crude spike": 3, "crude rally": 2, "crude jump": 2,
    "crude ris": 2, "oil price surge": 3, "oil price spike": 3,
    "oil price rise": 2, "oil price jump": 2, "brent surge": 2,
    "brent spike": 2, "brent jump": 2, "war": 3, "conflict": 2,
    "escalat": 2, "sanction": 2, "missile strike": 3,
    "military action": 3, "invasion": 3, "tension rise": 2,
    "tension escalat": 2, "geopolitical risk": 2, "trade war": 2,
    "tariff": 2, "ban": 1, "blockade": 2, "weak earnings": 3,
    "miss estimate": 3, "profit decline": 2, "profit drop": 2,
    "profit fall": 2, "revenue miss": 2, "revenue decline": 2,
    "revenue drop": 2, "downgrade": 2, "underperform": 2,
    "weak result": 2, "below estimate": 2, "earnings miss": 3,
    "loss widen": 2, "guidance cut": 3, "red flag": 2, "fraud": 3,
    "scam": 3, "default": 3, "crash": 3, "sell-off": 3,
    "selloff": 3, "plunge": 3, "slump": 2, "bearish": 2,
    "gap down": 2, "correction": 2, "panic": 2, "fear": 1,
    "red": 1, "market decline": 2, "market fall": 2,
    "market drop": 2, "negative close": 1, "selling pressure": 2,
    "rupee weaken": 2, "rupee depreciat": 2, "rupee fall": 2,
    "rupee hit low": 3, "current account deficit": 2,
    "fiscal deficit widen": 2, "rating downgrade": 3,
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Event Risk & Weighting Constants
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EVENT_RISK_KEYWORDS: list[str] = [
    "rbi policy", "rbi meet", "monetary policy committee", "mpc meet",
    "fed meeting", "fomc", "fomc meeting", "fed decision",
    "union budget", "budget session", "interim budget",
    "cpi data releas", "inflation data", "gdp data releas",
    "jobs report", "nonfarm payroll",
    "election result", "election outcome",
    "expiry day", "monthly expiry", "weekly expiry",
    "f&o expiry",
]

CATEGORY_IMPORTANCE: dict[str, str] = {
    "macro": "HIGH", "india": "HIGH", "geopolitical": "HIGH",
    "commodity": "MEDIUM", "corporate": "MEDIUM",
    "event": "HIGH", "general": "LOW",
}

SECTOR_WEIGHT: dict[str, float] = {
    "Banking & Finance": 1.5, "Information Technology": 1.3,
    "Energy & Oil": 1.2, "FMCG": 1.1, "Automobile": 1.0,
    "Pharma & Healthcare": 1.0, "Metals & Mining": 0.9,
    "Real Estate & Infrastructure": 0.9, "Telecom & Media": 0.8,
    "Defence & Aerospace": 0.7, "Agriculture": 0.7, "General": 1.0,
}

GLOBAL_MARKET_WEIGHTS: dict[str, float] = {
    "sp500": 3.0,
    "nasdaq": 2.5,
    "dow": 2.0,
    "nikkei": 2.0,
    "hangseng": 1.5,
    "dax": 1.0,
    "sgx": 1.5,
}
