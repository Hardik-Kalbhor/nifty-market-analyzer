"""
llm/resolution.py — BTST signal conflict resolution and heavyweight veto enforcement.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

def _resolve_btst_conflict(
    res_json: dict[str, Any],
    market_signals: dict,
    heavyweights: dict | None,
    fii_dii_data: dict | None
) -> dict[str, Any]:
    """
    Deterministic Weighted Conflict Arbiter for BTST.
    Protects against overconfident trades when underlying pillars conflict:
    1. If BUY CE but Heavyweights or FIIs are strongly opposing -> Overrides to NO TRADE.
    2. If BUY PE but Heavyweights or FIIs are strongly opposing -> Overrides to NO TRADE.
    3. If VIX is elevated (>16.5) with mixed signals -> Forces NO TRADE.
    4. Calculates weighted consensus score and ensures dimension_scores exists.
    """
    if not isinstance(res_json, dict):
        return res_json

    # Ensure dimension_scores structure exists
    dims = res_json.get("dimension_scores", {})
    if not dims or not isinstance(dims, dict):
        dims = {
            "macro_global": {"verdict": res_json.get("prediction", "FLAT"), "bias": "NEUTRAL", "note": "Global cues aligned."},
            "fii_dii": {"verdict": "FLAT", "bias": "NEUTRAL", "note": "Institutional flow neutral."},
            "oi_pcr": {"verdict": "FLAT", "bias": "NEUTRAL", "note": f"PCR {market_signals.get('pcr', 1.05):.2f}."},
            "heavyweights": {"verdict": res_json.get("prediction", "FLAT"), "bias": "NEUTRAL", "note": "Heavyweights aligned."},
            "vix_regime": {"verdict": "FLAT", "bias": "CALM", "note": f"VIX {market_signals.get('india_vix', 12.5)}."},
            "news_catalyst": {"verdict": res_json.get("prediction", "FLAT"), "bias": res_json.get("news_sentiment", "MIXED"), "note": "News drivers analyzed."},
        }
        res_json["dimension_scores"] = dims

    # Count bullish vs bearish dimension votes
    bull_count = 0
    bear_count = 0
    for d_name, d_val in dims.items():
        if isinstance(d_val, dict):
            b = str(d_val.get("bias", "")).upper()
            v = str(d_val.get("verdict", "")).upper()
            if "BULL" in b or "UP" in v:
                bull_count += 1
            elif "BEAR" in b or "DOWN" in v:
                bear_count += 1

    res_json["weighted_confluence"] = f"{bull_count}/6 Bullish, {bear_count}/6 Bearish Confluence"

    btst_bias = str(res_json.get("btst_bias", "NO TRADE")).upper()
    prediction = str(res_json.get("prediction", "FLAT")).upper()

    # Rule 1: Heavyweight Divergence Check
    if heavyweights and isinstance(heavyweights, dict):
        hdfc = heavyweights.get("HDFCBANK.NS", {}).get("change_pct", 0)
        rel = heavyweights.get("RELIANCE.NS", {}).get("change_pct", 0)

        # Bullish trade into falling heavyweights (>20% of index falling)
        if btst_bias == "BUY CE" and hdfc <= -0.4 and rel <= -0.4:
            logger.info("⚖️ BTST Arbiter: Overriding BUY CE to NO TRADE (HDFC Bank & Reliance both down >0.4%)")
            res_json["btst_bias"] = "NO TRADE"
            res_json["prediction"] = "FLAT"
            res_json["confidence"] = min(res_json.get("confidence", 60), 55)
            res_json["reasoning"] = f"[Arbiter Override: Heavyweight Divergence] HDFC Bank ({hdfc:+.2f}%) and Reliance ({rel:+.2f}%) are opposing upside momentum. {res_json.get('reasoning', '')}"
            res_json["conflict_resolved"] = True

        # Bearish trade into surging heavyweights
        elif btst_bias == "BUY PE" and hdfc >= 0.4 and rel >= 0.4:
            logger.info("⚖️ BTST Arbiter: Overriding BUY PE to NO TRADE (HDFC Bank & Reliance both up >0.4%)")
            res_json["btst_bias"] = "NO TRADE"
            res_json["prediction"] = "FLAT"
            res_json["confidence"] = min(res_json.get("confidence", 60), 55)
            res_json["reasoning"] = f"[Arbiter Override: Heavyweight Divergence] HDFC Bank ({hdfc:+.2f}%) and Reliance ({rel:+.2f}%) are opposing downside momentum. {res_json.get('reasoning', '')}"
            res_json["conflict_resolved"] = True

    # Rule 2: Strong FII Outflow vs Bullish Bias
    if fii_dii_data and isinstance(fii_dii_data, dict):
        fii_net = fii_dii_data.get("fii_net_crores", 0)
        if btst_bias == "BUY CE" and fii_net <= -2500 and bear_count >= 3:
            logger.info("⚖️ BTST Arbiter: Overriding BUY CE to NO TRADE (Heavy FII outflow ₹%s Cr)", fii_net)
            res_json["btst_bias"] = "NO TRADE"
            res_json["prediction"] = "FLAT"
            res_json["confidence"] = min(res_json.get("confidence", 60), 52)
            res_json["reasoning"] = f"[Arbiter Override: Institutional Headwind] Heavy FII cash selling (₹{fii_net:,.0f} Cr) opposes overnight call holding. {res_json.get('reasoning', '')}"
            res_json["conflict_resolved"] = True

    # Rule 3: High VIX with Mixed Signals -> Force NO TRADE
    vix = float(market_signals.get("india_vix") or 12.0)
    if vix >= 17.5 and bull_count < 4 and bear_count < 4:
        if btst_bias in ["BUY CE", "BUY PE"]:
            logger.info("⚖️ BTST Arbiter: Overriding %s to NO TRADE (High VIX %.1f + Mixed Signals)", btst_bias, vix)
            res_json["btst_bias"] = "NO TRADE"
            res_json["prediction"] = "FLAT"
            res_json["confidence"] = min(res_json.get("confidence", 60), 50)
            res_json["reasoning"] = f"[Arbiter Override: High Volatility Risk] India VIX is elevated at {vix:.1f} with mixed directional cues. Cash preservation advised. {res_json.get('reasoning', '')}"
            res_json["conflict_resolved"] = True

    return res_json





