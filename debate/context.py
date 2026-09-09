"""
debate/context.py — Debate context builder and consensus determination.
"""

import json
from typing import Any
from .constants import _safe_float

def _format_retail_score(val: Any) -> str:
    """Safely format retail sentiment score with sign (+/-) without format code crashes."""
    try:
        if val is None:
            return "+0"
        r_int = int(round(float(val)))
        return f"{r_int:+d}"
    except (ValueError, TypeError):
        return "+0"


def _build_debate_context(stage1_result: dict, market_signals: dict) -> str:
    """
    Build the shared context block fed to all 3 debate agents AND the judge.
    Keeps it concise — agents only need the key numbers, not the full news dump.
    """
    if not isinstance(stage1_result, dict):
        stage1_result = {}
    if not isinstance(market_signals, dict):
        market_signals = {}

    btst_bias    = stage1_result.get("btst_bias", "NO TRADE")
    prediction   = stage1_result.get("prediction", "FLAT")
    confidence   = stage1_result.get("confidence", 50)
    reasoning    = stage1_result.get("reasoning", "")
    bull_factors = stage1_result.get("bullish_factors", [])[:3]
    bear_factors = stage1_result.get("bearish_factors", [])[:3]
    dim_scores   = stage1_result.get("dimension_scores", {})
    fo_context   = stage1_result.get("fo_expiry_context", "")

    vix     = market_signals.get("india_vix", "N/A")
    pcr     = market_signals.get("pcr", "N/A")
    max_pain = market_signals.get("max_pain", "N/A")
    spot    = market_signals.get("nifty_spot", "N/A")
    gift    = market_signals.get("gift_nifty_change_pct", 0)

    dim_summary = []
    if isinstance(dim_scores, dict):
        for name, d in dim_scores.items():
            if isinstance(d, dict):
                dim_summary.append(f"  {name}: {d.get('bias','?')} — {d.get('note','')}")

    # Social & Retail Sentiment
    social = stage1_result.get("social_sentiment") or market_signals.get("social_sentiment") or {}
    if not isinstance(social, dict):
        social = {}
    social_section = ""
    sample_count = int(social.get("sample_count") or 0)
    if sample_count > 0 or social.get("retail_mood"):
        score_str = _format_retail_score(social.get("retail_sentiment_score"))
        retail_mood = str(social.get("retail_mood") or "NEUTRAL")
        contrarian_warning = str(social.get("contrarian_warning") or "").strip()
        top_buzz = social.get("top_buzz") if isinstance(social.get("top_buzz"), list) else []

        social_section = f"\nSocial & Retail Sentiment (Reddit/Telegram/FinTwit):\n  Retail Mood: {retail_mood} ({score_str}/100 from {sample_count} posts)"
        if contrarian_warning:
            social_section += f"\n  ⚠️ {contrarian_warning}"
        if top_buzz:
            clean_buzz = [str(b).strip() for b in top_buzz if b]
            if clean_buzz:
                social_section += f"\n  Trending Buzz: {'; '.join(clean_buzz[:2])}"

    return f"""STAGE 1 ANALYSIS CONTEXT (from 6-agent swarm):
─────────────────────────────────────────
BTST Direction: {btst_bias}
Gap Prediction: {prediction}
Stage 1 Confidence: {confidence}%
Stage 1 Reasoning: {reasoning}

Key Numbers:
  Nifty Spot:  {spot}
  GIFT Nifty:  {gift:+.2f}% overnight
  India VIX:   {vix}  (flag if >14.0 — risk elevated)
  PCR:         {pcr}  (>1.25 bullish, <0.80 bearish)
  Max Pain:    {max_pain}
  F&O Context: {fo_context}{social_section}

Dimension Verdicts:
{chr(10).join(dim_summary) if dim_summary else "  (not available)"}

Top Bullish Factors: {bull_factors}
Top Bearish Factors: {bear_factors}
─────────────────────────────────────────
Given all of the above, provide your verdict as the {{persona}} analyst."""




def _determine_consensus(aggressive: dict, conservative: dict, neutral: dict) -> tuple[str, str]:
    """
    Fallback consensus without Gemini judge.
    Returns (btst_structure, debate_consensus).
    """
    votes = [
        aggressive.get("verdict", "HALF_QUANTITY"),
        conservative.get("verdict", "HALF_QUANTITY"),
        neutral.get("verdict", "HALF_QUANTITY"),
    ]
    # Count votes
    vote_counts: dict[str, int] = {}
    for v in votes:
        vote_counts[v] = vote_counts.get(v, 0) + 1

    max_votes = max(vote_counts.values())
    if max_votes == 3:
        return list(vote_counts.keys())[0], "UNANIMOUS"
    elif max_votes == 2:
        majority = [k for k, v in vote_counts.items() if v == 2][0]
        return majority, "MAJORITY"
    else:
        # 3-way split → Conservative wins
        return conservative.get("verdict", "HALF_QUANTITY"), "SPLIT"


