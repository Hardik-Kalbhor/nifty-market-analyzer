"""
wfs/debate.py — Multi-persona debate committee simulation.
"""

from __future__ import annotations
import logging
from typing import Any, Optional
from .constants import _safe_float

logger = logging.getLogger("WalkForwardSimulation")

def simulate_debate_committee(
    dimensions: dict[str, Any],
    session: dict[str, Any],
    cognigraph_trap: Optional[str] = None,
    risk_profile: str = "BALANCED",
) -> dict[str, Any]:
    """
    Executes fast, deterministic multi-persona debate committee adjudication:
    - Momentum Hawk (Aggressive): Evaluates breakout & heavyweight strength.
    - Capital Defender (Conservative): Evaluates DTE, theta cost, VIX shock, and PCR wall.
    - Tactical Structurer (Neutral): Weights risk-reward, suggests lot sizing & scale-out plan.
    - Judge: Synthesizes final verdict, applies CogniGraph trap guardrail and scale-out tiers.
    """
    dimensions = dimensions or {}
    session = session or {}
    pa = (dimensions.get("price_action") or {}).get("verdict", "CONSOLIDATION")
    hw = (dimensions.get("heavyweights") or {}).get("verdict", "DIVERGENT")
    vix_regime = (dimensions.get("vix_regime") or {}).get("verdict", "NORMAL")
    contrarian = (dimensions.get("social_contrarian") or {}).get("verdict", "NEUTRAL")
    macro = (dimensions.get("macro_global") or {}).get("verdict", "NEUTRAL")
    pcr_state = (dimensions.get("oi_pcr") or {}).get("verdict", "BALANCED")

    bullish_votes = 0
    bearish_votes = 0

    if pa == "STRONG_BULLISH": bullish_votes += 2
    elif pa == "STRONG_BEARISH": bearish_votes += 2

    if hw == "BULLISH_ALIGNED": bullish_votes += 2
    elif hw == "BEARISH_ALIGNED": bearish_votes += 2

    if macro == "BULLISH_FLOW": bullish_votes += 1
    elif macro == "BEARISH_FLOW": bearish_votes += 1

    if pcr_state == "BULLISH_FLOOR": bullish_votes += 1
    elif pcr_state == "BEARISH_WALL": bearish_votes += 1

    # Contrarian overrides
    if contrarian == "BULL_TRAP_DANGER":
        bearish_votes += 3
        bullish_votes -= 2
    elif contrarian == "BEAR_TRAP_DANGER":
        bullish_votes += 3
        bearish_votes -= 2

    # VIX shock override
    if vix_regime == "VOLATILITY_SHOCK":
        return {
            "verdict": "EMERGENCY_EXIT",
            "position_side": "NO_TRADE",
            "confidence": 92,
            "action": "VIX Shock: Sit out or close open positions immediately.",
            "committee_consensus": "Conservative Guardrail Override (Volatility Surge)",
            "scale_out_plan": {
                "tier_1": "Exit 100% open lots immediately to prevent gamma whip-saw.",
                "tier_2": "Cancel all pending limit orders in broker terminal.",
                "tier_3": "Do not initiate re-entry until VIX stabilizes below 16.",
            }
        }

    net_score = bullish_votes - bearish_votes
    confidence = min(92, max(55, 60 + abs(net_score) * 5))

    if net_score >= 3:
        side = "BUY_CE"
        verdict = "FULL_BTST" if net_score >= 5 else "HALF_QUANTITY"
    elif net_score <= -3:
        side = "BUY_PE"
        verdict = "FULL_BTST" if net_score <= -5 else "HALF_QUANTITY"
    else:
        side = "NO_TRADE"
        verdict = "STRICT_NO_TRADE"

    # CogniGraph Failure Trap Invalidation
    if cognigraph_trap and side != "NO_TRADE":
        logger.info(f"CogniGraph guardrail intercepted trade: {cognigraph_trap}")
        if risk_profile == "CONSERVATIVE":
            verdict = "STRICT_NO_TRADE"
            side = "NO_TRADE"
        else:
            verdict = "HALF_QUANTITY"
            confidence = max(50, confidence - 15)

    if side == "BUY_CE":
        scale_plan = {
            "tier_1": "Book 50% lots at +0.25% gap gain (Target 1 Lock).",
            "tier_2": "Move stop-loss on 25% lots strictly to entry cost (Breakeven Defend).",
            "tier_3": "Trail remaining 25% lots with dynamic 15-min trailing stop for momentum runner.",
        }
    elif side == "BUY_PE":
        scale_plan = {
            "tier_1": "Book 50% lots at +0.25% down gap gain on puts (Target 1 Lock).",
            "tier_2": "Move stop-loss on 25% lots strictly to entry cost (Breakeven Defend).",
            "tier_3": "Trail remaining 25% lots with dynamic 15-min trailing stop for momentum runner.",
        }
    else:
        scale_plan = {
            "tier_1": "Preserve 100% capital in cash.",
            "tier_2": "No overnight risk exposure.",
            "tier_3": "Await clear market structure breakout.",
        }

    return {
        "verdict": verdict,
        "position_side": side,
        "confidence": confidence,
        "action": f"Initiate {verdict} on {side}" if side != "NO_TRADE" else "Stay in cash",
        "committee_consensus": f"Judge: {net_score:+d} Confluence ({'Bullish' if net_score > 0 else 'Bearish' if net_score < 0 else 'Neutral'})",
        "scale_out_plan": scale_plan,
        "cognigraph_trap_triggered": cognigraph_trap,
    }


