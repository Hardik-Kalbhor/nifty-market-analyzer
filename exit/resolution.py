"""
exit/resolution.py — Conflict resolution between specialist dimensions.
"""

from __future__ import annotations
import logging
from typing import Any
from .scale_out import generate_tiered_scale_out_plan

logger = logging.getLogger(__name__)


_VERDICT_SEVERITY = {
    "HOLD_AND_RIDE": 0,
    "PARTIAL_BOOK_50": 1,
    "PARTIAL_BOOK_70": 2,
    "TRAIL_SL_TO_COST": 3,
    "TRAIL_SL_TIGHT": 4,
    "FULL_EXIT": 5,
    "PRE_CLOSE_EXIT": 6,
    "EMERGENCY_EXIT": 7,
}

_AGENT_WEIGHTS = {
    "greeks_decay": 0.20,
    "vix_regime": 0.18,
    "social_contrarian": 0.15,
    "oi_pcr": 0.17,
    "price_action": 0.12,
    "heavyweights": 0.10,
    "macro_global": 0.08,
}


def _resolve_dimension_conflict(
    parsed: dict[str, Any],
    position: dict[str, Any] | None = None,
    live_spot: float = 0.0,
) -> dict[str, Any]:
    """
    Cross-validates the LLM's final verdict against dimension_scores using
    weighted scoring. If 4+ dimensions are more conservative than the LLM verdict,
    upgrade to the safer option. Adds 'conflict_resolved' flag and generates
    a structured multi-tiered lot scale_out_plan.
    """
    dimension_scores = parsed.get("dimension_scores", {})
    if not dimension_scores or len(dimension_scores) < 3:
        if "scale_out_plan" not in parsed:
            parsed["scale_out_plan"] = generate_tiered_scale_out_plan(
                parsed.get("verdict", "HOLD_AND_RIDE"),
                position=position,
                live_spot=live_spot,
                trailing_sl=parsed.get("trailing_sl", 0.0),
            )
        return parsed

    ai_verdict = parsed.get("verdict", "HOLD_AND_RIDE")
    ai_severity = _VERDICT_SEVERITY.get(ai_verdict, 0)

    # Map dimension short verdicts to severity
    dim_verdict_map = {
        "HOLD": 0, "HOLD_AND_RIDE": 0,
        "PARTIAL_BOOK": 1, "PARTIAL_BOOK_50": 1, "PARTIAL_BOOK_70": 2,
        "TRAIL_SL_TO_COST": 3, "TRAIL": 3, "TRAIL_SL_TIGHT": 4,
        "EXIT": 5, "FULL_EXIT": 5, "EMERGENCY_EXIT": 7,
    }

    weighted_severity = 0.0
    total_weight = 0.0
    for dim, weight in _AGENT_WEIGHTS.items():
        dim_data = dimension_scores.get(dim, {})
        dim_verdict = str(dim_data.get("verdict", "HOLD")).upper()
        # Match partial strings
        severity = 0
        for k, v in dim_verdict_map.items():
            if k in dim_verdict:
                severity = v
                break
        weighted_severity += severity * weight
        total_weight += weight

    avg_severity = weighted_severity / total_weight if total_weight > 0 else 0

    # If weighted agent severity is 2+ levels above LLM verdict → override to safer option
    if avg_severity >= ai_severity + 2:
        target_severity = round(avg_severity)
        target_severity = max(0, min(7, target_severity))
        reverse_map = {v: k for k, v in _VERDICT_SEVERITY.items()}
        new_verdict = reverse_map.get(target_severity, ai_verdict)
        logger.info(
            f"⚖️ Conflict Resolution: AI said '{ai_verdict}' (severity {ai_severity}), "
            f"weighted agents avg {avg_severity:.1f} → overriding to '{new_verdict}'"
        )
        parsed["verdict"] = new_verdict
        parsed["conflict_resolved"] = True
        parsed["original_ai_verdict"] = ai_verdict
        if "reasoning" in parsed:
            parsed["reasoning"] = (
                f"[Conflict Resolution Override: {ai_verdict} → {new_verdict}] " + parsed["reasoning"]
            )

    # Attach structured 3-tier scale out plan
    scale_out = generate_tiered_scale_out_plan(
        parsed.get("verdict", ai_verdict),
        position=position,
        live_spot=live_spot,
        trailing_sl=parsed.get("trailing_sl", 0.0),
    )
    parsed["scale_out_plan"] = scale_out
    if parsed.get("conflict_resolved"):
        parsed["action"] = f"Tier 1: {scale_out['tier_1']} Tier 2: {scale_out['tier_2']} Tier 3: {scale_out['tier_3']}"

    return parsed


