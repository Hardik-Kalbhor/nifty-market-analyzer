"""
dreaming/constants.py — Constants, timezone, and numeric clean helpers for dreaming engine.
"""

import re
import logging
from datetime import datetime
from typing import Any
import pytz

from typing import Any, Callable

import pytz

logger = logging.getLogger("DreamingEngine")
TIMEZONE = pytz.timezone("Asia/Kolkata")


def _clean_float(val: Any, default: float = 0.0) -> float:
    """Safely parse float from string or numeric, handling currencies, commas, and signs."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        s = str(val).strip().replace(",", "")
        m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
        if m:
            return float(m.group(0))
        return default
    except Exception:
        return default


def _now_ist_str() -> str:
    """Current timestamp in IST ISO format."""
    return datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S IST")


