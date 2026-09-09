"""
intraday_analyzer.py — Backward-compatibility shim.

The implementation has been decomposed into the intraday/ package.
"""

from intraday import (  # noqa: F401
    IST,
    _get_market_phase,
    _detect_intraday_pattern,
    _estimate_volatility,
    _generate_intraday_bias,
    generate_intraday_prediction,
    _generate_intraday_summary,
)
