"""
wfs/constants.py — Constants, timezones, and numeric safety utilities for walk-forward simulation.
"""

from typing import Any
import pytz

TIMEZONE = pytz.timezone("Asia/Kolkata")
DEFAULT_RISK_FREE_RATE = 0.065
TRADING_DAYS_PER_YEAR = 252


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Safely cast value to float."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        cleaned = str(val).strip().replace(",", "").replace("%", "").replace("₹", "")
        return float(cleaned)
    except Exception:
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    """Safely cast value to int."""
    if val is None:
        return default
    if isinstance(val, int):
        return val
    try:
        return int(float(str(val).strip()))
    except Exception:
        return default
