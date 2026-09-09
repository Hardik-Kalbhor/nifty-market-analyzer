"""
subagents/fallback.py — Deterministic rule-based fallbacks for dynamic subagents.
"""

from typing import Any
from .matcher import _clean_numeric

def _generate_fallback_verdict(
    specialist_name: str,
    market_signals: dict[str, Any],
    stage1_result: dict[str, Any],
) -> dict[str, Any]:
    """Generate deterministic domain rule-based verdict when LLM is unavailable."""
    prop_bias = stage1_result.get("btst_bias", "NO TRADE")
    vix = _clean_numeric(market_signals.get("india_vix"), 13.5)
    fii = _clean_numeric(market_signals.get("fii_net"), 0.0)

    if specialist_name == "RBI_Policy_Quant":
        return {
            "subagent": "RBI_Policy_Quant",
            "verdict": "HEDGED_SPREAD" if "BUY" in prop_bias else "STRICT_NO_TRADE",
            "confidence": 75,
            "specialist_rationale": "Event implied volatility crush post-announcement severely penalizes naked premium. Favor hedged spreads.",
        }
    elif specialist_name == "Geopolitical_Crude_Analyst":
        return {
            "subagent": "Geopolitical_Crude_Analyst",
            "verdict": "HALF_QUANTITY" if "BUY" in prop_bias else "STRICT_NO_TRADE",
            "confidence": 70,
            "specialist_rationale": "Crude oil volatility injects headline gap risk into Indian equities. Size down exposure.",
        }
    elif specialist_name == "Options_Greeks_ZeroDTE_Quant":
        return {
            "subagent": "Options_Greeks_ZeroDTE_Quant",
            "verdict": "HALF_QUANTITY" if vix < 16.0 else "HEDGED_SPREAD",
            "confidence": 80,
            "specialist_rationale": "Overnight theta on 1-DTE options requires strict risk limits to avoid gap opening decay traps.",
        }
    elif specialist_name == "Heavyweight_Earnings_Specialist":
        return {
            "subagent": "Heavyweight_Earnings_Specialist",
            "verdict": "HEDGED_SPREAD",
            "confidence": 75,
            "specialist_rationale": "Heavyweight earnings divergence can unilaterally veto market momentum. Protect downside.",
        }
    elif specialist_name == "FII_OrderFlow_Tracer":
        if fii < -1500 and "BUY CE" in prop_bias:
            return {
                "subagent": "FII_OrderFlow_Tracer",
                "verdict": "STRICT_NO_TRADE",
                "confidence": 85,
                "specialist_rationale": "Heavy foreign institutional selling undermines Call buying; opening gap up likely to face institutional dumping.",
            }
        return {
            "subagent": "FII_OrderFlow_Tracer",
            "verdict": "HALF_QUANTITY",
            "confidence": 75,
            "specialist_rationale": "Institutional order flow shows high volume concentration. Exercise position sizing moderation.",
        }

    return {
        "subagent": specialist_name,
        "verdict": "HALF_QUANTITY",
        "confidence": 70,
        "specialist_rationale": "Domain specialist advises standard risk moderation.",
    }


