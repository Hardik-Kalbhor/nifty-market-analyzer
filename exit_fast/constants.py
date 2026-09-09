"""
exit_fast/constants.py — Constants, timezone settings, and safe float helpers.
"""

import re
import logging
from datetime import datetime
from typing import Any
import pytz

logger = logging.getLogger("ExitFastPath")
TIMEZONE = pytz.timezone("Asia/Kolkata")

# Top 5 NIFTY heavyweights accounting for ~39% index weight
HEAVYWEIGHT_TICKERS = {
    "HDFCBANK.NS": {"name": "HDFC Bank", "weight": 11.5},
    "RELIANCE.NS": {"name": "Reliance", "weight": 9.2},
    "ICICIBANK.NS": {"name": "ICICI Bank", "weight": 8.1},
    "INFY.NS": {"name": "Infosys", "weight": 5.8},
    "TCS.NS": {"name": "TCS", "weight": 4.2},
}


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Safely convert any dirty, currency-prefixed, or comma-formatted value to float with zero-crash guarantee."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        s = str(val).strip().replace(",", "")
        m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
        return float(m.group(0)) if m else default
    except (ValueError, TypeError, Exception):
        return default


def _get_now_ist() -> datetime:
    """Return current timestamp in IST timezone (mockable for unit tests)."""
    return datetime.now(TIMEZONE)
