"""
analyzer/scoring.py — Market microstructure signal scoring functions.

Contains: score_gift_nifty, score_india_vix, score_pcr, score_global_markets.
These pure scoring functions take market data and return directional boost values.
"""

from typing import Any
from .constants import GLOBAL_MARKET_WEIGHTS


def score_gift_nifty(gift_change_pct: float) -> tuple[float, float, str]:
    """
    Score GIFT Nifty / SGX Nifty % change vs previous close.
    This is the single strongest predictor (~65-70% directional accuracy).
    Weight: 2.5x FII score.

    Args:
        gift_change_pct: e.g. +0.8 means GIFT Nifty up 0.8%
    Returns:
        (bull_boost, bear_boost, factor_string)
    """
    if gift_change_pct > 1.5:
        return 20, 0, f"GIFT Nifty strongly up +{gift_change_pct:.2f}% — high gap-up probability"
    elif gift_change_pct > 0.75:
        return 14, 0, f"GIFT Nifty up +{gift_change_pct:.2f}% — gap-up likely"
    elif gift_change_pct > 0.25:
        return 8,  0, f"GIFT Nifty mildly positive +{gift_change_pct:.2f}%"
    elif gift_change_pct > 0:
        return 3,  0, f"GIFT Nifty marginally positive +{gift_change_pct:.2f}%"
    elif gift_change_pct < -1.5:
        return 0, 20, f"GIFT Nifty sharply down {gift_change_pct:.2f}% — high gap-down probability"
    elif gift_change_pct < -0.75:
        return 0, 14, f"GIFT Nifty down {gift_change_pct:.2f}% — gap-down likely"
    elif gift_change_pct < -0.25:
        return 0,  8, f"GIFT Nifty mildly negative {gift_change_pct:.2f}%"
    else:
        return 0,  3, f"GIFT Nifty marginally negative {gift_change_pct:.2f}%"


def score_india_vix(vix_value: float, vix_change_pct: float) -> dict[str, Any]:
    """
    Score India VIX level and direction.
    VIX is a confidence modifier, not a direction predictor.

    Args:
        vix_value: current VIX reading (e.g. 13.5)
        vix_change_pct: day's % change in VIX (e.g. +5.2)
    Returns:
        dict with confidence_penalty, bear_boost, risk_level, factor
    """
    if vix_value > 22:
        risk_level = "HIGH"
        confidence_penalty = 18
        factor = f"India VIX elevated at {vix_value:.1f} — high uncertainty, avoid leveraged trades"
    elif vix_value > 17:
        risk_level = "MEDIUM"
        confidence_penalty = 10
        factor = f"India VIX moderately high at {vix_value:.1f} — reduce position size"
    elif vix_value < 11:
        risk_level = "COMPLACENCY"
        confidence_penalty = 5
        factor = f"India VIX very low at {vix_value:.1f} — complacency risk, gap may be smaller"
    else:
        risk_level = "LOW"
        confidence_penalty = 0
        factor = f"India VIX normal at {vix_value:.1f} — stable conditions"

    bear_boost = 0.0
    if vix_change_pct > 15:
        bear_boost = 12
        factor += f" | VIX spiked +{vix_change_pct:.1f}% — panic signal"
    elif vix_change_pct > 8:
        bear_boost = 7
        factor += f" | VIX rising +{vix_change_pct:.1f}% — caution"
    elif vix_change_pct < -8:
        bear_boost = -4  # Negative bear = slight bull
        factor += f" | VIX cooling {vix_change_pct:.1f}% — fear receding"

    return {
        "risk_level": risk_level,
        "confidence_penalty": confidence_penalty,
        "bear_boost": bear_boost,
        "factor": factor,
    }


def score_pcr(pcr: float) -> tuple[float, float, str]:
    """
    Score Put-Call Ratio (PCR) using contrarian logic.
    PCR = Total Put OI / Total Call OI

    Contrarian because:
      High PCR (>1.3) → too many puts bought → market may bounce
      Low PCR (<0.8)  → too many calls bought → market may fall

    Args:
        pcr: e.g. 1.25
    Returns:
        (bull_boost, bear_boost, factor_string)
    """
    if pcr > 1.6:
        return 12, 0, f"PCR extremely high at {pcr:.2f} — contrarian STRONG BULLISH (excessive put buying)"
    elif pcr > 1.3:
        return 7,  0, f"PCR elevated at {pcr:.2f} — contrarian bullish signal"
    elif pcr > 1.0:
        return 3,  0, f"PCR at {pcr:.2f} — slight put dominance, mild bullish tilt"
    elif pcr < 0.6:
        return 0, 12, f"PCR extremely low at {pcr:.2f} — contrarian STRONG BEARISH (excessive call buying)"
    elif pcr < 0.8:
        return 0,  7, f"PCR low at {pcr:.2f} — contrarian bearish signal"
    else:
        return 0,  0, f"PCR neutral at {pcr:.2f} — no directional bias"


def score_global_markets(market_changes: dict[str, float]) -> tuple[float, float, list[str]]:
    """
    Score global market closing % changes for next-day Nifty gap prediction.

    Args:
        market_changes: {"sp500": +1.2, "nasdaq": +0.8, "nikkei": -0.3, ...}
    Returns:
        (bull_boost, bear_boost, factor_list)
    """
    bull = 0.0
    bear = 0.0
    factors: list[str] = []

    for market, change_pct in market_changes.items():
        w = GLOBAL_MARKET_WEIGHTS.get(market.lower(), 1.0)
        label = market.upper()

        if change_pct > 1.5:
            boost = round(6 * w, 1)
            bull += boost
            factors.append(f"{label} strongly up +{change_pct:.1f}% (boost: +{boost})")
        elif change_pct > 0.5:
            boost = round(3 * w, 1)
            bull += boost
            factors.append(f"{label} up +{change_pct:.1f}%")
        elif change_pct < -1.5:
            boost = round(6 * w, 1)
            bear += boost
            factors.append(f"{label} sharply down {change_pct:.1f}% (drag: -{boost})")
        elif change_pct < -0.5:
            boost = round(3 * w, 1)
            bear += boost
            factors.append(f"{label} down {change_pct:.1f}%")
        # -0.5 to +0.5 → neutral, no factor added

    return bull, bear, factors
