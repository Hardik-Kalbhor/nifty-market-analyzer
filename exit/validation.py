"""
exit/validation.py — Output validation and quantitative grounding for AI exit recommendations.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

def _validate_and_ground_output(
    parsed: dict[str, Any],
    live_spot: float,
    entry_spot: float,
    position: dict[str, Any] | None = None,
    contrarian_warning: str = ""
) -> dict[str, Any]:
    """
    Validates output structure and verifies numerical claims to prevent AI hallucination.
    Enforces that trailing stop loss is on the mathematically valid side of live spot:
    - Bullish trades (BUY_CE, LONG_FUTURES, SHORT_PE): SL must be strictly BELOW live spot.
    - Bearish trades (BUY_PE, SHORT_FUTURES, SHORT_CE): SL must be strictly ABOVE live spot.
    Also clamps HOLD_AND_RIDE to TRAIL_SL_TIGHT if a contrarian trap opposes the trade.
    """
    valid_verdicts = {
        "HOLD_AND_RIDE", "PARTIAL_BOOK_50", "PARTIAL_BOOK_70",
        "TRAIL_SL_TO_COST", "TRAIL_SL_TIGHT", "FULL_EXIT",
        "PRE_CLOSE_EXIT", "EMERGENCY_EXIT"
    }

    # 1. Enforce valid verdict
    verdict = parsed.get("verdict", "").strip()
    if verdict not in valid_verdicts:
        logger.warning(f"AI returned invalid verdict '{verdict}', normalizing.")
        verdict = "TRAIL_SL_TIGHT" if "HOLD" in verdict else "FULL_EXIT"
        parsed["verdict"] = verdict

    # Contrarian Trap Clamp
    if position and contrarian_warning:
        c_warn = str(contrarian_warning).upper()
        side = str(position.get("position_side", "BUY_CE")).upper()
        is_bullish = side in ["BUY_CE", "LONG_FUTURES", "SHORT_PE"]
        is_bearish = side in ["BUY_PE", "SHORT_FUTURES", "SHORT_CE"]

        if is_bullish and "BULL TRAP" in c_warn and parsed["verdict"] == "HOLD_AND_RIDE":
            logger.info("🛡️ Contrarian Guardrail: Clamping HOLD_AND_RIDE to TRAIL_SL_TIGHT due to Bull Trap Risk.")
            parsed["verdict"] = "TRAIL_SL_TIGHT"
            parsed["reasoning"] = f"[Contrarian Trap Guardrail: Overrode HOLD due to retail euphoria / FII selling divergence] " + parsed.get("reasoning", "")
        elif is_bearish and "BEAR TRAP" in c_warn and parsed["verdict"] == "HOLD_AND_RIDE":
            logger.info("🛡️ Contrarian Guardrail: Clamping HOLD_AND_RIDE to TRAIL_SL_TIGHT due to Bear Trap Risk.")
            parsed["verdict"] = "TRAIL_SL_TIGHT"
            parsed["reasoning"] = f"[Contrarian Trap Guardrail: Overrode HOLD due to retail panic / FII buying divergence] " + parsed.get("reasoning", "")

    # 2. Enforce confidence boundaries
    conf = parsed.get("confidence", 75)
    try:
        conf = int(conf)
        parsed["confidence"] = max(10, min(95, conf))
    except Exception:
        parsed["confidence"] = 75

    # 3. Ground trailing stop loss level
    sl = parsed.get("trailing_sl")
    try:
        sl = float(sl)
        # If SL is wildly ungrounded (>5% away from current spot), clamp it reasonably
        if live_spot > 0 and abs(sl - live_spot) / live_spot > 0.05:
            logger.warning(f"Ungrounded SL {sl} detected (live spot {live_spot}), clamping.")
            sl = round(entry_spot if entry_spot > 0 else live_spot, 1)

        # Directional Grounding: Ensure SL is on the correct side of live spot
        if position and live_spot > 0:
            side = str(position.get("position_side", "BUY_CE")).upper()
            is_bullish = side in ["BUY_CE", "LONG_FUTURES", "SHORT_PE"]
            if is_bullish and sl >= live_spot:
                logger.warning(f"Bullish SL {sl} >= live spot {live_spot} detected — clamping below live spot.")
                safe_fallback = entry_spot if (0 < entry_spot < live_spot) else (live_spot - 30)
                sl = round(safe_fallback, 1)
            elif not is_bullish and sl <= live_spot:
                logger.warning(f"Bearish SL {sl} <= live spot {live_spot} detected — clamping above live spot.")
                safe_fallback = entry_spot if (entry_spot > live_spot) else (live_spot + 30)
                sl = round(safe_fallback, 1)

        parsed["trailing_sl"] = round(sl, 1)
    except Exception:
        parsed["trailing_sl"] = round(entry_spot if entry_spot > 0 else live_spot, 1)

    return parsed


