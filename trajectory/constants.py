"""
trajectory/constants.py — Constants and numeric cleanup helpers for Trajectory Exporter.
"""

from __future__ import annotations

import re
from typing import Any

_SYSTEM_PROMPT = (
    "You are a Senior Quantitative Options Strategist and Risk Arbiter for the NIFTY 50 index. "
    "Your objective is to evaluate multi-dimensional market signals (GIFT Nifty momentum, FII/DII order flows, "
    "options open interest and Max Pain gravity, heavyweight index contributions, India VIX regime, and macro news) "
    "and synthesize a strictly calibrated overnight BTST (Buy Today, Sell Tomorrow) or intraday trade structure. "
    "Prioritize capital preservation over directional greed, mandate spread hedging when theta decay or event risk "
    "is elevated, and strictly enforce defined stop loss boundaries."
)


def _clean_float(val: Any, default: float = 0.0) -> float:
    """Safely parse float from string or numeric."""
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
