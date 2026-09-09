import logging
"""
cognigraph/constants.py — Constants, versioning, and numeric/date utilities for CogniGraph.
"""

import re
from datetime import datetime, timezone
from typing import Any

from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default half-life for memory decay (weights halve every 30 days)
DEFAULT_HALF_LIFE_DAYS = 30.0

# Canonical schema version
COGNIGRAPH_SCHEMA_VERSION = 1


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Parse a float safely, stripping extraneous text (%, Cr, commas, etc.)."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        cleaned = re.sub(r"[^\d.-]", "", str(val).strip())
        return float(cleaned) if cleaned else default
    except Exception:
        return default


def _days_between(d1_val: Any, d2_val: Any) -> float:
    """Compute days between two date strings safely."""
    try:
        if not d1_val or not d2_val:
            return 0.0
        d1_str = str(d1_val)[:10]
        d2_str = str(d2_val)[:10]
        dt1 = datetime.strptime(d1_str, "%Y-%m-%d")
        dt2 = datetime.strptime(d2_str, "%Y-%m-%d")
        return abs((dt2 - dt1).total_seconds()) / 86400.0
    except Exception:
        return 0.0


def _today_str() -> str:
    """Return today's date string YYYY-MM-DD."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


