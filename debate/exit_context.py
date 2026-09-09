"""
debate/exit_context.py — Exit debate context builder and scaling plan.
"""

import json
from typing import Any
from .constants import _safe_float

def _build_exit_debate_context(
    stage1_result: dict,
    position: dict,
    live_signals: dict,
    heavyweights: dict
) -> str:
    """Build concise context fed to all 3 exit debate agents."""
    side = position.get("position_side", "BUY_CE")
    strike = position.get("strike", "ATM")
    entry_spot = position.get("entry_spot") or live_signals.get("nifty_spot", 0)
    current_spot = live_signals.get("nifty_spot", entry_spot)
    risk_profile = position.get("risk_profile", "BALANCED").upper()
    dte = position.get("dte", "Unknown")

    entry_prem = position.get("entry_premium", 0)
    curr_prem = position.get("current_premium", 0)
    pnl_str = "N/A"
    if entry_prem and curr_prem and float(entry_prem) > 0:
        pct = round(((float(curr_prem) - float(entry_prem)) / float(entry_prem)) * 100, 1)
        pnl_str = f"{pct:+0.1f}% (Entry ₹{entry_prem} → Current ₹{curr_prem})"

    spot_diff = round(float(current_spot) - float(entry_spot), 1) if entry_spot else 0

    hw_summary = []
    if heavyweights and isinstance(heavyweights, dict):
        for sym, d in heavyweights.items():
            if isinstance(d, dict) and "name" in d:
                hw_summary.append(f"{d['name']}: {d.get('change_pct', 0):+.2f}%")
    hw_line = " | ".join(hw_summary) if hw_summary else "Heavyweights neutral"

    # Social sentiment & contrarian signals
    social = live_signals.get("social_sentiment") or stage1_result.get("social_sentiment") or {}
    social_mood = social.get("retail_mood", "NEUTRAL")
    social_score = social.get("retail_sentiment_score", 0)
    social_warn = social.get("contrarian_warning") or live_signals.get("contrarian_warning") or "None"
    buzz_items = social.get("top_buzz", [])
    buzz_str = ", ".join(buzz_items[:2]) if buzz_items else "Neutral chatter"

    # CogniGraph precedents
    cg_precedent = stage1_result.get("cognigraph_regime_precedent") or ""
    if not cg_precedent:
        try:
            from cognigraph import get_cognigraph
            cg = get_cognigraph()
            regime = cg.classify_regime(live_signals)
            traps = cg.get_top_traps(regime)
            cg_precedent = f"Regime: {regime}"
            if traps:
                cg_precedent += f" | Known Trap: {traps[0].get('setup')} -> {traps[0].get('cause')}"
        except Exception:
            cg_precedent = "Regime: Normal"

    return f"""LIVE POSITION DATA:
- Trade: {side} ({strike})
- Entry Spot: {entry_spot} | Current Spot: {current_spot} (Diff: {spot_diff:+.1f} pts)
- Option Premium P&L: {pnl_str}
- Trader Risk Profile: {risk_profile}
- Days to Expiry (DTE): {dte}

LIVE MARKET MICROSTRUCTURE:
- India VIX: {live_signals.get('india_vix', 'N/A')}
- Put-Call Ratio (PCR): {live_signals.get('pcr', 'N/A')}
- Max Pain: {live_signals.get('max_pain', 'N/A')}
- Call OI Wall (Resistance): {live_signals.get('top_oi_call_strike', 'N/A')}
- Put OI Floor (Support): {live_signals.get('top_oi_put_strike', 'N/A')}
- Top Heavyweights: {hw_line}

RETAIL SOCIAL SENTIMENT & CONTRARIAN SIGNALS:
- Retail Crowd Mood: {social_mood} (Score: {social_score:+d}/100)
- Contrarian Trap Alert: {social_warn}
- Social Chatter Buzz: {buzz_str}

COGNIGRAPH CAUSAL REGIME PRECEDENTS:
- {cg_precedent}

STAGE 1 INITIAL ADVISOR OPINION:
- Baseline Verdict: {stage1_result.get('verdict', 'HOLD_AND_RIDE')}
- Baseline Action: {stage1_result.get('action', '')}
- Baseline Reasoning: {stage1_result.get('reasoning', '')}
"""




def _determine_exit_consensus(runner: dict, guardian: dict, tactical: dict, risk_profile: str) -> tuple[str, str, str]:
    """Fallback consensus resolver if Gemini Exit Judge is unavailable."""
    v_run = runner.get("verdict", "HOLD_AND_RIDE")
    v_guard = guardian.get("verdict", "FULL_EXIT")
    v_tac = tactical.get("verdict", "PARTIAL_BOOK_50")

    votes = [v_run, v_guard, v_tac]
    vote_counts: dict[str, int] = {}
    for v in votes:
        vote_counts[v] = vote_counts.get(v, 0) + 1

    if max(vote_counts.values()) == 3:
        return votes[0], "UNANIMOUS", f"All three analysts unanimously agree on {votes[0]}."
    elif max(vote_counts.values()) == 2:
        maj = [k for k, count in vote_counts.items() if count == 2][0]
        return maj, "MAJORITY", f"Majority consensus reached on {maj}."

    # 3-way split -> resolve based on user's risk profile
    if risk_profile == "AGGRESSIVE":
        return v_run, "SPLIT", "3-way split: Aggressive trader profile prioritized Runner Analyst."
    elif risk_profile == "CONSERVATIVE":
        return v_guard, "SPLIT", "3-way split: Conservative trader profile prioritized Capital Guardian."
    else:
        return v_tac, "SPLIT", "3-way split: Balanced trader profile prioritized Tactical Scale-Out Manager."


def build_tiered_scale_out_plan(
    verdict: str,
    position: dict[str, Any] | None = None,
    live_spot: float = 0.0,
    trailing_sl: float = 0.0,
    consensus: str = "MAJORITY",
) -> dict[str, str]:
    """
    Synthesize a structured 3-tiered lot scale-out plan resolving Defender vs. Momentum Hawk tension:
      - Tier 1: Rapid Capital De-risking & Profit Lock (Defender priority)
      - Tier 2: Breakeven Stop Placement & Capital Shield (Tactical priority)
      - Tier 3: Trailing Trend Runner & Target 2 Expansion (Momentum Hawk priority)
    """
    pos = position or {}
    side = str(pos.get("position_side", "BUY_CE")).upper()
    is_bullish = side in ["BUY_CE", "LONG_FUTURES", "SHORT_PE"]
    entry_spot = _safe_float(pos.get("entry_spot") or pos.get("entry_price"), default=0.0)
    trailing_sl = _safe_float(trailing_sl, default=0.0)
    cost_str = f"{entry_spot:,.0f}" if entry_spot > 0 else "entry cost"
    trail_str = f"{trailing_sl:,.0f}" if trailing_sl > 0 else ("key support" if is_bullish else "key resistance")

    if verdict in ["PARTIAL_BOOK_50", "PARTIAL_BOOK_70", "TRAIL_SL_TO_COST", "TRAIL_SL_TIGHT"]:
        pct = "70%" if verdict == "PARTIAL_BOOK_70" else "50%"
        rem_pct = "30%" if verdict == "PARTIAL_BOOK_70" else "25%"
        runner_pct = "remaining" if verdict == "PARTIAL_BOOK_70" else "25%"
        return {
            "tier_1": f"Book {pct} lots at market to permanently secure accumulated gains (Capital Defender lock).",
            "tier_2": f"Move stop-loss on {rem_pct} lots strictly to {cost_str} to guarantee zero-risk status.",
            "tier_3": f"Trail {runner_pct} lots at {trail_str} for trend runner continuation toward Target 2 (Momentum Hawk runner).",
        }
    elif verdict in ["FULL_EXIT", "PRE_CLOSE_EXIT", "EMERGENCY_EXIT"]:
        return {
            "tier_1": "Exit 100% open lots immediately at market to halt structural loss.",
            "tier_2": "Cancel all pending limit targets and stop orders on trading broker terminal.",
            "tier_3": "Do not initiate re-entry until market structure confirms reversal.",
        }
    else:  # HOLD_AND_RIDE
        return {
            "tier_1": f"Hold full position while spot remains strictly favorable above {trail_str} (Hawk priority).",
            "tier_2": "Prepare to scale out 50% lots immediately if spot tests next psychological resistance.",
            "tier_3": f"Maintain dynamic trailing stop {trail_str} on 15-minute bar closes.",
        }


