"""
exit/context_helpers.py — Sub-formatting helpers for building exit prompt context.
"""

import json
from typing import Any
from datetime import datetime

def format_moneyness(strike: Any, side: str, current_spot: float) -> str:
    moneyness_text = "Strike: N/A"
    try:
        strike_num = float("".join(c for c in str(strike) if c.isdigit() or c == "."))
        if strike_num > 0 and current_spot > 0:
            if "CE" in str(side).upper() or "CE" in str(strike).upper():
                gap = current_spot - strike_num
                if gap >= 50:
                    moneyness_text = f"Strike {strike_num:.0f} CE: ITM by {gap:.0f}pts (spot {current_spot:.0f})"
                elif gap >= -50:
                    moneyness_text = f"Strike {strike_num:.0f} CE: ATM (spot {current_spot:.0f}, gap {abs(gap):.0f}pts)"
                else:
                    moneyness_text = (
                        f"Strike {strike_num:.0f} CE: OTM by {abs(gap):.0f}pts "
                        f"(needs +{abs(gap):.0f}pt NIFTY rally to reach ATM)"
                    )
            elif "PE" in str(side).upper() or "PE" in str(strike).upper():
                gap = strike_num - current_spot
                if gap >= 50:
                    moneyness_text = f"Strike {strike_num:.0f} PE: ITM by {gap:.0f}pts (spot {current_spot:.0f})"
                elif gap >= -50:
                    moneyness_text = f"Strike {strike_num:.0f} PE: ATM (spot {current_spot:.0f}, gap {abs(gap):.0f}pts)"
                else:
                    moneyness_text = (
                        f"Strike {strike_num:.0f} PE: OTM by {abs(gap):.0f}pts "
                        f"(needs -{abs(gap):.0f}pt NIFTY drop to reach ATM)"
                    )
    except Exception:
        moneyness_text = f"Strike: {strike}"
    return moneyness_text


def format_dte(dte: Any) -> str:
    from exit_fast_path import is_expiry_day as _is_expiry_day
    expiry_day = _is_expiry_day()
    if dte is not None:
        try:
            dte_int = int(dte)
            if expiry_day or dte_int == 0:
                return "⚠️ WEEKLY EXPIRY TODAY — theta collapse accelerating post-13:00 IST. Short sellers: lock profits aggressively."
            elif dte_int <= 2:
                return f"⚠️ {dte_int} DTE — near-expiry theta collapse in effect. Short sellers should lock profits."
            elif dte_int <= 5:
                return f"{dte_int} DTE — elevated theta burn rate. Tighten management."
            else:
                return f"{dte_int} DTE — normal theta decay."
        except Exception:
            return f"DTE: {dte}"
    elif expiry_day:
        return "⚠️ WEEKLY EXPIRY TODAY (Tuesday) — theta collapse accelerating. Short sellers: lock profits aggressively."
    else:
        return "DTE: Not specified (assume normal decay)."


def format_social_and_cognigraph(
    fii_dii_data: dict[str, Any] | None,
    news_items: list[dict],
    social_sentiment: dict[str, Any] | None,
    cognigraph_context: str | None,
    live_signals: dict[str, Any],
) -> tuple[str, str]:
    if social_sentiment is None:
        try:
            from analyzer import _compute_social_sentiment
            fii_val = fii_dii_data.get("fii_net_crores") if fii_dii_data else None
            social_sentiment = _compute_social_sentiment(news_items, fii_net_cr=fii_val)
        except Exception:
            social_sentiment = {}

    if social_sentiment:
        retail_score = social_sentiment.get("retail_sentiment_score", 0)
        retail_mood = social_sentiment.get("retail_mood", "NEUTRAL")
        contrarian_warn = social_sentiment.get("contrarian_warning", "") or "None"
        buzz_items = social_sentiment.get("top_buzz", [])
        buzz_str = ", ".join(buzz_items[:3]) if buzz_items else "No dominant chatter"
        social_text = (
            f"  • Retail Social Mood: {retail_mood} (Score: {retail_score:+d}/100 across Reddit/Telegram/Twitter)\n"
            f"  • Contrarian Trap Warning: {contrarian_warn}\n"
            f"  • Trending Social Chatter: {buzz_str}"
        )
    else:
        social_text = "  • Social sentiment data unavailable (Neutral baseline assumed)."

    if cognigraph_context is None:
        try:
            from cognigraph import get_cognigraph
            cg = get_cognigraph()
            regime = cg.classify_regime(live_signals)
            traps = cg.get_top_traps(regime)
            persona_mem = cg.get_agent_memory("CONSERVATIVE", live_signals)
            cg_lines = [f"  • Active Causal Regime: {regime}"]
            if traps:
                cg_lines.append("  • Historical Failure Traps in this Regime:")
                for t in traps[:3]:
                    cg_lines.append(f"    - [{t.get('setup', '')}] {t.get('relation', '')} {t.get('cause', '')} (Weight: {t.get('weight', 1.0):.2f})")
            if persona_mem:
                cg_lines.append(f"  • Regime Causal Precedents:\n{persona_mem}")
            cognigraph_text = "\n".join(cg_lines)
        except Exception as cg_err:
            cognigraph_text = f"  • CogniGraph context unavailable: {cg_err}"
    else:
        cognigraph_text = cognigraph_context

    return social_text, cognigraph_text
