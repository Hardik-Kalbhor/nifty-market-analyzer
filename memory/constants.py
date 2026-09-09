"""
memory/constants.py — Delimiters, regexes, timezone settings, and prompts for memory log.
"""

import re

try:
    import pytz
    TIMEZONE = pytz.timezone("Asia/Kolkata")
except ImportError:
    from zoneinfo import ZoneInfo
    TIMEZONE = ZoneInfo("Asia/Kolkata")

# A gap is "UP" if actual open is >= +0.20% above prev close, "DOWN" if <= -0.20%
GAP_UP_THRESHOLD = 0.20     # %
GAP_DOWN_THRESHOLD = -0.20  # %

# Hard delimiter — cannot appear in LLM prose, safe as entry boundary
_SEPARATOR = "\n\n<!-- ENTRY_END -->\n\n"

# Pre-compiled regex for parsing entries
_TAG_RE = re.compile(
    r"^\[(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})"
    r"\s*\|\s*(?P<prediction>GAP UP|GAP DOWN|FLAT)"
    r"\s*\|\s*(?P<btst_bias>BUY CE|BUY PE|NO TRADE)"
    r"\s*\|\s*(?P<confidence>[0-9]+)%"
    r"\s*\|\s*(?P<status>[^\]]+)\]$",
    re.IGNORECASE,
)
_REASONING_RE = re.compile(r"REASONING:\n(.*?)(?=\nOUTCOME:|\nREFLECTION:|\Z)", re.DOTALL)
_OUTCOME_RE = re.compile(r"OUTCOME:\n(.*?)(?=\nREFLECTION:|\Z)", re.DOTALL)
_REFLECTION_RE = re.compile(r"REFLECTION:\n(.*?)$", re.DOTALL)

# Reflection system prompt — compact, re-injected verbatim into future prompts
_REFLECTION_SYSTEM_PROMPT = (
    "You are a NIFTY 50 trading analyst reviewing your own past BTST gap prediction "
    "now that the actual market outcome is known.\n\n"
    "Write exactly 2-3 sentences of plain prose. No bullets, no headers, no markdown.\n\n"
    "Cover in order:\n"
    "1. Was the directional call correct? (mention actual gap % if available)\n"
    "2. Which part of the thesis held or failed? (GIFT Nifty, FII flows, heavyweights, VIX, news)\n"
    "3. One concrete lesson for the next similar analysis.\n\n"
    "Be specific and terse. Your output is stored verbatim and re-read by future analysts "
    "so every word must earn its place. Write in past tense."
)
