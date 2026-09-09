"""
debate/intraday_context.py — Intraday debate verdicts, prompts, and context builder.
"""

import json
from typing import Any
from .constants import _safe_float
from .context import _format_retail_score

INTRADAY_VERDICTS = {
    "TREND_BUY_CALLS", "TREND_BUY_PUTS", "RANGE_OPTION_SELLING",
    "SCALP_DIPS_ONLY", "SCALP_PULLBACKS_ONLY", "STRICT_WAIT_AND_WATCH"
}

_INTRADAY_MOMENTUM_SYSTEM = """You are the MOMENTUM & TREND SCALPER in a 3-person Intraday NIFTY Trading Committee.
Your ONE goal: identify directional thrust, breakout velocity, and high-momentum call/put buying setups.
Focus ONLY on:
- Opening Range Breakout (ORB) or directional trend continuation
- Heavyweight alignment (e.g. Reliance, HDFC Bank, ICICI Bank pushing directionally)
- GIFT Nifty gap extension and sector breadth (Bank Nifty & IT)
- Aggressive directional momentum for quick option buying scalps

Output ONLY valid JSON (no markdown, no extra text):
{
  "persona": "MOMENTUM_SCALPER",
  "verdict": "TREND_BUY_CALLS" | "TREND_BUY_PUTS" | "SCALP_DIPS_ONLY" | "SCALP_PULLBACKS_ONLY",
  "confidence": <integer 50-95>,
  "trigger_level": <number: breakout spot price trigger>,
  "rationale": "<2-3 sentences explaining the momentum thrust or why trend continuation is favoured>"
}"""

_INTRADAY_MEAN_REVERSION_SYSTEM = """You are the MEAN-REVERSION & WALL DEFENDER (Option Seller) in a 3-person Intraday NIFTY Trading Committee.
Your ONE goal: identify where the market will stall, resist, or chop, and advocate for capital defense and option writing.
Focus ONLY on:
- Call/Put Open Interest resistance walls and Max Pain pinning
- Overextended moves prone to gap fade or mean reversion
- Afternoon low-volume chop, premium erosion, and non-directional option selling (Strangles / Straddles / Iron Condors)
- Why directional option buyers risk heavy theta burn

Output ONLY valid JSON (no markdown, no extra text):
{
  "persona": "WALL_DEFENDER",
  "verdict": "RANGE_OPTION_SELLING" | "SCALP_PULLBACKS_ONLY" | "STRICT_WAIT_AND_WATCH",
  "confidence": <integer 50-95>,
  "key_wall": <number: key OI resistance/support strike>,
  "rationale": "<2-3 sentences explaining why the move will stall or why range-bound option selling is safer>"
}"""

_INTRADAY_TACTICAL_SYSTEM = """You are the TACTICAL RISK & SCALP MANAGER in a 3-person Intraday NIFTY Trading Committee.
Your ONE goal: find the highest-probability, asymmetric risk-reward entry zone with strict stop-loss management.
Focus ONLY on:
- Waiting for key pullbacks (e.g. VWAP test, prior day high/low retest) rather than chasing green/red candles
- Minimum 1:2 risk-to-reward ratio and specific invalidation stop-loss placement
- Avoiding midday chop traps (11:30 - 13:30 IST)
- Tactical lot scaling and defensive position sizing

Output ONLY valid JSON (no markdown, no extra text):
{
  "persona": "TACTICAL_SCALPER",
  "verdict": "SCALP_DIPS_ONLY" | "SCALP_PULLBACKS_ONLY" | "RANGE_OPTION_SELLING" | "STRICT_WAIT_AND_WATCH",
  "confidence": <integer 50-95>,
  "entry_zone": "<string: e.g. '24420-24450'>",
  "stop_loss": <number: strict invalidation stop-loss spot level>,
  "rationale": "<2-3 sentences on entry timing, level retest, and asymmetric risk-reward execution>"
}"""

_INTRADAY_JUDGE_SYSTEM = """You are the INTRADAY SYNTHESIS JUDGE for the 3-person NIFTY Intraday Trading Committee.
You receive:
1. Momentum Scalper (aggressive trend / breakout)
2. Mean-Reversion Defender (conservative range / option seller)
3. Tactical Risk Manager (asymmetric pullback entries / strict SL)
4. Live market signals (NIFTY Spot, India VIX, PCR, Max Pain, Market Phase, Heavyweights)

Your role:
- Synthesize the 3 perspectives into ONE clear, actionable Intraday Trade Plan for today.
- If signals are conflicting or VIX is erratic, prioritize capital protection (STRICT_WAIT_AND_WATCH or RANGE_OPTION_SELLING).
- Provide specific entry zone, target, and invalidation stop loss (SL must be mathematically sound relative to spot).

Output ONLY valid JSON (no markdown, no extra text):
{
  "structure": "TREND_BUY_CALLS" | "TREND_BUY_PUTS" | "RANGE_OPTION_SELLING" | "SCALP_DIPS_ONLY" | "SCALP_PULLBACKS_ONLY" | "STRICT_WAIT_AND_WATCH",
  "action_plan": "<1-2 sentence concrete execution plan, e.g. 'Wait for pullback towards 24,420. Buy 24,500 CE with SL at 24,385. Target 24,520.'>",
  "entry_zone": "<string: e.g. '24,420 - 24,450'>",
  "target": <number: profit target spot level>,
  "stop_loss": <number: invalidation stop loss spot level>,
  "debate_consensus": "UNANIMOUS" | "MAJORITY" | "SPLIT",
  "confidence_adjustment": <integer, e.g. +5 or -10 or 0>,
  "judge_rationale": "<2-3 sentences synthesizing why this structure wins given the market phase and persona debate>"
}"""

_MOMENTUM_SCALPER_SYSTEM = _INTRADAY_MOMENTUM_SYSTEM
_WALL_DEFENDER_SYSTEM = _INTRADAY_MEAN_REVERSION_SYSTEM
_TACTICAL_RISK_SYSTEM = _INTRADAY_TACTICAL_SYSTEM


def _build_intraday_debate_context(
    intraday_result: dict[str, Any],
    market_signals: dict[str, Any],
    heavyweights: dict[str, Any],
    news_sentiment: str,
) -> str:
    """Builds a structured prompt for intraday persona agents."""
    if not isinstance(intraday_result, dict):
        intraday_result = {}
    if not isinstance(market_signals, dict):
        market_signals = {}
    if not isinstance(heavyweights, dict):
        heavyweights = {}

    bias_dict = intraday_result.get("intraday_bias", {}) if isinstance(intraday_result.get("intraday_bias"), dict) else {}
    pat_dict = intraday_result.get("intraday_pattern", {}) if isinstance(intraday_result.get("intraday_pattern"), dict) else {}
    phase_dict = intraday_result.get("market_phase", {}) if isinstance(intraday_result.get("market_phase"), dict) else {}
    vol_dict = intraday_result.get("volatility", {}) if isinstance(intraday_result.get("volatility"), dict) else {}

    live_spot = market_signals.get("nifty_spot", 0)
    vix = market_signals.get("india_vix", 12.0)
    pcr = market_signals.get("pcr", 1.0)
    max_pain = market_signals.get("max_pain", "N/A")
    top_call = market_signals.get("top_oi_call_strike", "N/A")
    top_put = market_signals.get("top_oi_put_strike", "N/A")

    hw_lines = []
    for sym, d in (heavyweights or {}).items():
        if isinstance(d, dict):
            hw_lines.append(f"  • {d.get('name', sym)}: ₹{d.get('price', 0)} ({d.get('change_pct', 0):+.2f}%)")
    hw_text = "\n".join(hw_lines) if hw_lines else "  • Heavyweights: Normal"

    # Social Sentiment
    social = market_signals.get("social_sentiment") or intraday_result.get("social_sentiment") or {}
    if not isinstance(social, dict):
        social = {}
    social_line = ""
    sample_count = int(social.get("sample_count") or 0)
    if sample_count > 0 or social.get("retail_mood"):
        mood_str = str(social.get("retail_mood") or "NEUTRAL")
        score_str = _format_retail_score(social.get("retail_sentiment_score"))
        social_line = f"\n- Retail Crowd Sentiment: {mood_str} ({score_str}/100)"
        warn = str(social.get("contrarian_warning") or "").strip()
        if warn:
            social_line += f" | ⚠️ {warn}"

    return f"""NIFTY 50 LIVE INTRADAY CONTEXT:
- Live NIFTY Spot: {live_spot}
- Intraday Baseline Bias: {bias_dict.get('bias', 'NEUTRAL')} (Confidence: {bias_dict.get('confidence', 50)}%)
- Expected Pattern: {pat_dict.get('pattern', 'RANGE-BOUND')} — {pat_dict.get('description', '')}
- Market Phase: {phase_dict.get('phase', 'MARKET HOURS')} — {phase_dict.get('description', '')}
- Volatility: {vol_dict.get('level', 'MODERATE')} (Range: {vol_dict.get('expected_range', '50-100 pts')})
- News Sentiment: {news_sentiment}
- India VIX: {vix} | Option Chain PCR: {pcr} | Max Pain: {max_pain}
- Top Call OI Wall: {top_call} | Top Put OI Floor: {top_put}{social_line}

HEAVYWEIGHT STOCK MOVERS:
{hw_text}

INTRADAY BASELINE STRATEGY:
- Strategy: {pat_dict.get('strategy', 'Strict risk management')}
- Option Strategy: {pat_dict.get('option_strategy', 'Monitor key levels')}
"""




def _determine_intraday_consensus(momentum: dict, defender: dict, tactical: dict) -> tuple[str, str, str]:
    """Fallback consensus resolver if Gemini Intraday Judge is unavailable."""
    v_mom = momentum.get("verdict", "SCALP_DIPS_ONLY")
    v_def = defender.get("verdict", "RANGE_OPTION_SELLING")
    v_tac = tactical.get("verdict", "STRICT_WAIT_AND_WATCH")

    votes = [v_mom, v_def, v_tac]
    vote_counts: dict[str, int] = {}
    for v in votes:
        vote_counts[v] = vote_counts.get(v, 0) + 1

    if max(vote_counts.values()) == 3:
        return votes[0], "UNANIMOUS", f"All three analysts unanimously agree on {votes[0]}."
    elif max(vote_counts.values()) == 2:
        maj = [k for k, count in vote_counts.items() if count == 2][0]
        return maj, "MAJORITY", f"Majority consensus reached on {maj}."

    return v_tac, "SPLIT", "3-way split: Defaulted to Tactical Scalper's risk-calibrated plan."


