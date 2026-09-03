"""
debate_engine.py — Multi-Persona Risk Debate Engine for BTST Options Trading.

Implements a 3-agent debate committee that stress-tests the Stage 1 BTST analysis:

  Aggressive Agent  (Groq) — makes the strongest case FOR capturing momentum
  Conservative Agent (Groq) — focuses on theta decay, DTE, IV crush, Max Pain
  Neutral Agent     (Groq) — balances risk-to-reward, recommends trade structure
  Judge             (Gemini Flash) — synthesises all 3 into a calibrated verdict

The 3 Groq agents run in PARALLEL via ThreadPoolExecutor (~1.5s total).
Gemini Flash synthesis runs sequentially after (~1.5-2s).
Total debate overhead: ~3-4s — acceptable for the 15:15 IST scheduled run.

Graceful fallback: any failure at any stage returns Stage 1 result unchanged.
No new dependencies — uses only `requests` (already in requirements.txt).
"""

import concurrent.futures
import json
import logging
import os
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

_GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

_GROQ_MODELS   = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b"]
_GEMINI_MODELS = ["gemini-2.5-flash", "gemini-flash-latest"]

# Valid trade structure outputs
TRADE_STRUCTURES = {"FULL_BTST", "HALF_QUANTITY", "HEDGED_SPREAD", "STRICT_NO_TRADE"}

# ─────────────────────────────────────────────────────────────────────────────
# Persona system prompts (narrow, focused — this is where Groq excels)
# ─────────────────────────────────────────────────────────────────────────────

_AGGRESSIVE_SYSTEM = """You are the AGGRESSIVE analyst in a 3-person BTST Risk Committee for NIFTY 50 options trading.

Your ONE job: make the strongest possible case FOR taking this overnight BTST position.
Focus ONLY on: GIFT Nifty gap direction, US/Asian/European market momentum, FII net buying,
positive news catalysts, NIFTY heavyweight alignment with trade direction, and gap probability.

DO NOT consider theta decay, DTE, Max Pain pinning, or IV crush — those are not your domain.

Output ONLY valid JSON (no markdown, no extra text):
{
  "persona": "AGGRESSIVE",
  "verdict": "FULL_BTST" | "HALF_QUANTITY" | "STRICT_NO_TRADE",
  "confidence": <integer 50-95>,
  "rationale": "<2-3 sentences citing the strongest momentum/directional signals for or against the trade>"
}"""

_CONSERVATIVE_SYSTEM = """You are the CONSERVATIVE analyst in a 3-person BTST Risk Committee for NIFTY 50 options trading.

Your ONE job: identify every capital-preservation reason to reduce or avoid the BTST position.
Focus ONLY on: DTE (Days To Expiry) and overnight theta decay cost, IV crush risk post-event,
Max Pain level proximity to spot (pinning risk), India VIX level (flag if >14.0),
heavyweight divergence from trade direction, and F&O expiry timing risk.

DO NOT consider raw momentum or global cues — that is not your domain.

Output ONLY valid JSON (no markdown, no extra text):
{
  "persona": "CONSERVATIVE",
  "verdict": "FULL_BTST" | "HALF_QUANTITY" | "HEDGED_SPREAD" | "STRICT_NO_TRADE",
  "confidence": <integer 50-95>,
  "rationale": "<2-3 sentences citing the strongest theta/risk/pinning concerns>"
}"""

_NEUTRAL_SYSTEM = """You are the NEUTRAL analyst in a 3-person BTST Risk Committee for NIFTY 50 options trading.

Your ONE job: weigh the Aggressive analyst's momentum case against the Conservative analyst's
risk concerns and recommend the trade STRUCTURE that optimises risk-to-reward.

Consider: what position size makes the overnight risk acceptable given the theta cost?
Is a spread (buy CE/PE + sell a further strike) better than an outright position?
A half-quantity position cuts theta loss in half while preserving most of the directional gain.

Output ONLY valid JSON (no markdown, no extra text):
{
  "persona": "NEUTRAL",
  "verdict": "FULL_BTST" | "HALF_QUANTITY" | "HEDGED_SPREAD" | "STRICT_NO_TRADE",
  "confidence": <integer 50-95>,
  "rationale": "<2-3 sentences explaining why this structure is the optimal risk-reward balance>"
}"""

_JUDGE_SYSTEM = """You are the SYNTHESIS JUDGE for a 3-person BTST Risk Committee for NIFTY 50 options trading.
You receive the verdicts from the Aggressive, Conservative, and Neutral analysts, plus the full Stage 1 analysis.

Your job: weigh the 3 verdicts and synthesise a FINAL calibrated trade recommendation.

Rules:
1. If all 3 agree → use that structure, boost confidence by +5 (cap at 90).
2. If 2/3 agree → use the majority structure, keep confidence from Stage 1.
3. If all 3 split → default to the Conservative verdict, reduce confidence by -10.
4. The Conservative analyst has veto power on FULL_BTST if DTE=1 OR VIX>17 — downgrade to HALF_QUANTITY.
5. trade_instruction must be specific: mention lot size (1 lot vs 2 lots), strike proximity to spot, and SL level.

Output ONLY valid JSON (no markdown, no extra text):
{
  "btst_structure": "FULL_BTST" | "HALF_QUANTITY" | "HEDGED_SPREAD" | "STRICT_NO_TRADE",
  "trade_instruction": "<specific 1-2 sentence actionable instruction with lot size, strike, SL level>",
  "debate_consensus": "UNANIMOUS" | "MAJORITY" | "SPLIT",
  "confidence_adjustment": <integer, e.g. +5 or -10 or 0>,
  "judge_rationale": "<2 sentences explaining how the 3 verdicts were weighed>"
}"""

# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_debate_context(stage1_result: dict, market_signals: dict) -> str:
    """
    Build the shared context block fed to all 3 debate agents AND the judge.
    Keeps it concise — agents only need the key numbers, not the full news dump.
    """
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
    for name, d in dim_scores.items():
        if isinstance(d, dict):
            dim_summary.append(f"  {name}: {d.get('bias','?')} — {d.get('note','')}")

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
  F&O Context: {fo_context}

Dimension Verdicts:
{chr(10).join(dim_summary) if dim_summary else "  (not available)"}

Top Bullish Factors: {bull_factors}
Top Bearish Factors: {bear_factors}
─────────────────────────────────────────
Given all of the above, provide your verdict as the {{persona}} analyst."""


def _groq_call(system_prompt: str, user_content: str, groq_key: str, timeout: int = 8) -> dict | None:
    """Single Groq API call with model fallback. Returns parsed JSON or None."""
    headers = {
        "Authorization": f"Bearer {groq_key}",
        "Content-Type": "application/json",
    }
    for model in _GROQ_MODELS:
        try:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_content},
                ],
                "temperature": 0.3,
                "response_format": {"type": "json_object"},
            }
            r = requests.post(_GROQ_URL, headers=headers, json=payload, timeout=timeout)
            if r.status_code == 200:
                text = r.json()["choices"][0]["message"]["content"]
                return json.loads(text)
            logger.debug(f"Debate Groq ({model}): HTTP {r.status_code}")
        except Exception as e:
            logger.debug(f"Debate Groq ({model}) error: {e}")
    return None


def _gemini_call(system_prompt: str, user_content: str, gemini_key: str, timeout: int = 12) -> dict | None:
    """Single Gemini Flash call with model fallback. Returns parsed JSON or None."""
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"role": "user", "parts": [{"text": system_prompt + "\n\n" + user_content}]}],
        "generationConfig": {"response_mime_type": "application/json"},
    }
    for model in _GEMINI_MODELS:
        try:
            url = _GEMINI_URL.format(model=model, key=gemini_key)
            r = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if r.status_code == 200:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text)
            elif r.status_code == 429:
                logger.warning(f"Debate Gemini ({model}): 429 rate limit — skipping to next model")
            else:
                logger.debug(f"Debate Gemini ({model}): HTTP {r.status_code}")
        except Exception as e:
            logger.debug(f"Debate Gemini ({model}) error: {e}")
    return None


def _run_persona(persona_name: str, system_prompt: str, context: str, groq_key: str) -> dict:
    """Run a single persona agent and return its verdict dict (with fallback)."""
    t0 = time.time()
    result = _groq_call(system_prompt, context, groq_key)
    elapsed = round(time.time() - t0, 2)

    if result and isinstance(result, dict) and result.get("verdict") in TRADE_STRUCTURES:
        logger.info(f"[Debate] {persona_name}: {result.get('verdict')} "
                    f"(conf={result.get('confidence')}%) in {elapsed}s")
        return result

    # Fallback verdict if Groq fails or returns invalid structure
    logger.warning(f"[Debate] {persona_name} failed or returned invalid JSON — using fallback verdict")
    return {
        "persona": persona_name,
        "verdict": "HALF_QUANTITY",   # safe middle ground on failure
        "confidence": 50,
        "rationale": f"{persona_name} agent unavailable — defaulting to half-size caution.",
        "_fallback": True,
    }


def _run_judge(
    aggressive: dict,
    conservative: dict,
    neutral: dict,
    stage1_result: dict,
    market_signals: dict,
    gemini_key: str,
) -> dict | None:
    """Run the Gemini synthesis judge. Returns judge output dict or None."""
    judge_context = f"""DEBATE RESULTS:

AGGRESSIVE analyst: {json.dumps(aggressive, indent=2)}

CONSERVATIVE analyst: {json.dumps(conservative, indent=2)}

NEUTRAL analyst: {json.dumps(neutral, indent=2)}

ORIGINAL STAGE 1 ANALYSIS:
  btst_bias:  {stage1_result.get('btst_bias')}
  prediction: {stage1_result.get('prediction')}
  confidence: {stage1_result.get('confidence')}%
  vix:        {market_signals.get('india_vix', 'N/A')}
  max_pain:   {market_signals.get('max_pain', 'N/A')}
  fo_context: {stage1_result.get('fo_expiry_context', 'No expiry today')}

Synthesise the 3 verdicts into a final calibrated trade structure."""

    t0 = time.time()
    result = _gemini_call(_JUDGE_SYSTEM, judge_context, gemini_key)
    elapsed = round(time.time() - t0, 2)

    if result and isinstance(result, dict) and result.get("btst_structure") in TRADE_STRUCTURES:
        logger.info(f"[Debate] Judge: {result.get('btst_structure')} "
                    f"({result.get('debate_consensus')}) in {elapsed}s")
        return result

    logger.warning(f"[Debate] Judge failed or returned invalid response — skipping synthesis")
    return None


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


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def run_debate(
    stage1_result: dict[str, Any],
    market_signals: dict[str, Any],
    groq_key: str,
    gemini_key: str,
) -> dict[str, Any]:
    """
    Run the 3-agent debate + synthesis judge and merge results into stage1_result.

    Returns an enriched copy of stage1_result with these additional fields:
      btst_structure   — "FULL_BTST" | "HALF_QUANTITY" | "HEDGED_SPREAD" | "STRICT_NO_TRADE"
      trade_instruction — specific 1-2 sentence actionable trade instruction
      debate_consensus — "UNANIMOUS" | "MAJORITY" | "SPLIT"
      debate           — { aggressive, conservative, neutral } verdicts
      ai_agent_provider — updated to reflect debate layer

    On any unhandled failure, returns stage1_result UNCHANGED (safe fallback).
    Only runs when btst_bias is BUY CE or BUY PE (no point debating a confirmed NO TRADE).
    """
    btst_bias = str(stage1_result.get("btst_bias", "NO TRADE")).upper()
    if btst_bias == "NO TRADE":
        logger.info("[Debate] Skipping debate — Stage 1 already resolved to NO TRADE.")
        return stage1_result

    if not groq_key:
        logger.warning("[Debate] GROQ_API_KEY not set — skipping debate.")
        return stage1_result

    logger.info(f"[Debate] Starting 3-agent debate for {btst_bias}...")
    t_start = time.time()

    # Build shared context once (used by all 3 agents)
    context = _build_debate_context(stage1_result, market_signals)

    # ── Stage 2a: 3 Groq agents in PARALLEL ────────────────────────────────
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            fut_agg  = executor.submit(_run_persona, "AGGRESSIVE",  _AGGRESSIVE_SYSTEM,  context, groq_key)
            fut_cons = executor.submit(_run_persona, "CONSERVATIVE", _CONSERVATIVE_SYSTEM, context, groq_key)
            fut_neut = executor.submit(_run_persona, "NEUTRAL",      _NEUTRAL_SYSTEM,      context, groq_key)

            aggressive  = fut_agg.result(timeout=12)
            conservative = fut_cons.result(timeout=12)
            neutral     = fut_neut.result(timeout=12)
    except Exception as e:
        logger.error(f"[Debate] Parallel agent execution failed: {e} — returning Stage 1 unchanged.")
        return stage1_result

    t_debate = round(time.time() - t_start, 2)
    logger.info(f"[Debate] 3 agents completed in {t_debate}s")

    # ── Stage 2b: Gemini synthesis judge ───────────────────────────────────
    judge_result = None
    if gemini_key:
        try:
            judge_result = _run_judge(aggressive, conservative, neutral, stage1_result, market_signals, gemini_key)
        except Exception as e:
            logger.warning(f"[Debate] Judge failed: {e} — using vote-based fallback.")

    # ── Determine final structure ───────────────────────────────────────────
    if judge_result:
        btst_structure     = judge_result.get("btst_structure", "HALF_QUANTITY")
        trade_instruction  = judge_result.get("trade_instruction", "Proceed with reduced size.")
        debate_consensus   = judge_result.get("debate_consensus", "MAJORITY")
        conf_adj           = int(judge_result.get("confidence_adjustment", 0))
        judge_rationale    = judge_result.get("judge_rationale", "")
    else:
        # Vote-based fallback when Gemini is unavailable
        btst_structure, debate_consensus = _determine_consensus(aggressive, conservative, neutral)
        trade_instruction  = f"Take {btst_structure.replace('_', ' ').title()} position. Debate consensus: {debate_consensus}."
        conf_adj           = +5 if debate_consensus == "UNANIMOUS" else (-10 if debate_consensus == "SPLIT" else 0)
        judge_rationale    = "Gemini judge unavailable — majority vote applied."

    # Clamp confidence between 10 and 90
    orig_confidence = int(stage1_result.get("confidence", 60))
    new_confidence  = max(10, min(90, orig_confidence + conf_adj))

    t_total = round(time.time() - t_start, 2)
    logger.info(f"[Debate] Complete in {t_total}s — {btst_structure} ({debate_consensus}), "
                f"confidence {orig_confidence}% → {new_confidence}%")

    # ── Merge debate results into Stage 1 result ───────────────────────────
    enriched = dict(stage1_result)
    enriched.update({
        "btst_structure":    btst_structure,
        "trade_instruction": trade_instruction,
        "debate_consensus":  debate_consensus,
        "confidence":        new_confidence,
        "debate": {
            "aggressive":  {
                "verdict":   aggressive.get("verdict"),
                "confidence": aggressive.get("confidence"),
                "rationale":  aggressive.get("rationale"),
            },
            "conservative": {
                "verdict":   conservative.get("verdict"),
                "confidence": conservative.get("confidence"),
                "rationale":  conservative.get("rationale"),
            },
            "neutral": {
                "verdict":   neutral.get("verdict"),
                "confidence": neutral.get("confidence"),
                "rationale":  neutral.get("rationale"),
            },
            "judge_rationale": judge_rationale,
        },
        "ai_agent_provider": (
            enriched.get("ai_agent_provider", "Groq")
            + " → Debate (3×Groq + Gemini Judge)"
        ),
    })

    return enriched


# ─────────────────────────────────────────────────────────────────────────────
# Exit Advisor Multi-Persona Debate Engine
# ─────────────────────────────────────────────────────────────────────────────

EXIT_VERDICTS = {
    "HOLD_AND_RIDE",
    "PARTIAL_BOOK_50",
    "PARTIAL_BOOK_70",
    "TRAIL_SL_TO_COST",
    "TRAIL_SL_TIGHT",
    "FULL_EXIT",
    "PRE_CLOSE_EXIT",
    "EMERGENCY_EXIT",
}

_EXIT_RUNNER_SYSTEM = """You are the RUNNER ANALYST (Momentum & Profit Expansion) in a 3-person Live Position Exit Committee.
Your ONE goal: make the case for letting winning trades run and not cutting profits short prematurely.
Focus ONLY on:
- Underlying spot momentum and breakout continuation
- Heavyweight alignment (HDFC Bank & Reliance supporting the move)
- Favorable global market tailwinds
- Why trailing wide is superior to selling too early

CRITICAL ON suggested_sl:
- For BUY_CE / Long trades: stop loss MUST be strictly BELOW current spot.
- For BUY_PE / Short trades: stop loss MUST be strictly ABOVE current spot.

DO NOT recommend panic selling on minor counter-trend pullbacks.
Output ONLY valid JSON (no markdown, no extra text):
{
  "persona": "RUNNER",
  "verdict": "HOLD_AND_RIDE" | "PARTIAL_BOOK_50" | "TRAIL_SL_TO_COST",
  "confidence": <integer 50-95>,
  "suggested_sl": <number: suggested stop loss spot level on correct side of spot>,
  "rationale": "<2-3 sentences explaining why upward momentum or trend continuation justifies staying in or trailing wide>"
}"""

_EXIT_GUARDIAN_SYSTEM = """You are the CAPITAL GUARDIAN (Risk & Capital Defense) in a 3-person Live Position Exit Committee.
Your ONE goal: protect trading capital and identify every reason why the position is in immediate danger.
Focus ONLY on:
- Theta decay urgency (especially if DTE <= 1 or afternoon session past 13:00 IST)
- Proximity to Call/Put OI resistance walls or Max Pain pin zones
- India VIX contraction (IV crush) or sudden volatility shocks
- Heavyweight divergence (e.g. HDFC Bank or Reliance turning adverse)

CRITICAL ON suggested_sl:
- For BUY_CE / Long trades: stop loss MUST be strictly BELOW current spot.
- For BUY_PE / Short trades: stop loss MUST be strictly ABOVE current spot.

Output ONLY valid JSON (no markdown, no extra text):
{
  "persona": "CAPITAL_GUARDIAN",
  "verdict": "FULL_EXIT" | "TRAIL_SL_TIGHT" | "PARTIAL_BOOK_70",
  "confidence": <integer 50-95>,
  "suggested_sl": <number: suggested tight stop loss spot level on correct side of spot>,
  "rationale": "<2-3 sentences citing the most critical theta, resistance, or reversal risks>"
}"""

_EXIT_TACTICAL_SYSTEM = """You are the TACTICAL SCALE-OUT MANAGER in a 3-person Live Position Exit Committee.
Your ONE goal: find the optimal balance between locking in profits and keeping exposure open without emotional stress.
Focus ONLY on:
- Scaling out (e.g. booking 50% or 70% to make the trade free of financial risk)
- Moving stop loss to cost/breakeven to eliminate downside risk
- Lot-by-lot execution strategy based on current P&L %

CRITICAL ON suggested_sl:
- For BUY_CE / Long trades: stop loss MUST be strictly BELOW current spot.
- For BUY_PE / Short trades: stop loss MUST be strictly ABOVE current spot.
- NEVER confuse option expiry breakeven (strike + premium) with the underlying spot trailing stop loss!

Output ONLY valid JSON (no markdown, no extra text):
{
  "persona": "TACTICAL_MANAGER",
  "verdict": "PARTIAL_BOOK_50" | "PARTIAL_BOOK_70" | "TRAIL_SL_TO_COST" | "TRAIL_SL_TIGHT",
  "confidence": <integer 50-95>,
  "suggested_sl": <number: suggested breakeven or trailing stop loss level on correct side of spot>,
  "rationale": "<2-3 sentences on how lot scaling and SL adjustment achieves maximum risk-adjusted reward>"
}"""

_EXIT_JUDGE_SYSTEM = """You are the EXIT SYNTHESIS JUDGE for a 3-person Live Position Exit Committee.
You receive:
1. The Runner Analyst's perspective (momentum)
2. The Capital Guardian's perspective (capital defense)
3. The Tactical Scale-Out Manager's perspective (risk-reward de-risking)
4. The trader's live open position details and their stated Risk Profile (AGGRESSIVE, BALANCED, CONSERVATIVE)

Rules:
- AGGRESSIVE trader: lean towards Runner Analyst (favour HOLD_AND_RIDE or PARTIAL_BOOK_50 with wide trailing SL).
- BALANCED trader: lean towards Tactical Manager (favour PARTIAL_BOOK_50 and TRAIL_SL_TO_COST).
- CONSERVATIVE trader: give veto power to Capital Guardian (favour TRAIL_SL_TIGHT or FULL_EXIT if theta or resistance is high).
- Trailing SL must be on the CORRECT side of spot: strictly BELOW spot for BUY_CE/Longs, strictly ABOVE spot for BUY_PE/Shorts. Within 1.5% of live NIFTY spot.
- Provide a concrete, lot-by-lot action instruction.

Output ONLY valid JSON (no markdown, no extra text):
{
  "verdict": "HOLD_AND_RIDE" | "PARTIAL_BOOK_50" | "PARTIAL_BOOK_70" | "TRAIL_SL_TO_COST" | "TRAIL_SL_TIGHT" | "FULL_EXIT",
  "action": "<specific lot-by-lot instruction, e.g. 'Book 50% profit (1 lot) at market. Trail remaining 1 lot SL to breakeven (24,450)'>",
  "trailing_sl": <number: specific spot level for trailing stop loss on correct side of spot>,
  "debate_consensus": "UNANIMOUS" | "MAJORITY" | "SPLIT",
  "confidence_adjustment": <integer, e.g. +5 or -10 or 0>,
  "judge_rationale": "<2 sentences explaining how the committee verdicts were synthesized against the trader risk profile>"
}"""


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

STAGE 1 INITIAL ADVISOR OPINION:
- Baseline Verdict: {stage1_result.get('verdict', 'HOLD_AND_RIDE')}
- Baseline Action: {stage1_result.get('action', '')}
- Baseline Reasoning: {stage1_result.get('reasoning', '')}
"""


def _run_exit_persona(persona_name: str, system_prompt: str, context: str, groq_key: str, live_spot: float, is_bullish: bool = True) -> dict:
    """Execute a single exit persona agent with safe fallback."""
    t0 = time.time()
    result = _groq_call(system_prompt, context, groq_key)
    elapsed = round(time.time() - t0, 2)

    if result and isinstance(result, dict) and result.get("verdict") in EXIT_VERDICTS:
        logger.info(f"[ExitDebate] {persona_name}: {result.get('verdict')} (conf={result.get('confidence')}%) in {elapsed}s")
        return result

    logger.warning(f"[ExitDebate] {persona_name} failed or returned invalid verdict — using fallback.")
    fallback_sl = round(live_spot * 0.995, 1) if (is_bullish and live_spot) else (round(live_spot * 1.005, 1) if live_spot else 0)
    return {
        "persona": persona_name,
        "verdict": "PARTIAL_BOOK_50",
        "confidence": 60,
        "suggested_sl": fallback_sl,
        "rationale": f"{persona_name} agent unavailable — defaulting to prudent partial de-risking.",
        "_fallback": True,
    }


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


def run_exit_debate(
    stage1_result: dict[str, Any],
    position: dict[str, Any],
    live_signals: dict[str, Any],
    heavyweights: dict[str, Any],
    groq_key: str,
    gemini_key: str,
) -> dict[str, Any]:
    """
    Run the 3-analyst Exit Debate committee (Runner, Capital Guardian, Tactical Manager)
    plus the Gemini Flash Exit Judge.

    Bypasses debate on emergency exits or fast-path triggers.
    Enriches stage1_result with calibrated verdict, action plan, trailing SL, and debate breakdown.
    """
    verdict = stage1_result.get("verdict", "")
    if stage1_result.get("is_fast_path") or verdict in ("EMERGENCY_EXIT", "PRE_CLOSE_EXIT"):
        logger.info(f"[ExitDebate] Bypassing debate — Fast-Path/Emergency verdict: {verdict}")
        return stage1_result

    if not groq_key:
        logger.warning("[ExitDebate] GROQ_API_KEY not set — skipping exit debate.")
        return stage1_result

    live_spot = float(live_signals.get("nifty_spot") or position.get("entry_spot") or 0)
    risk_profile = str(position.get("risk_profile", "BALANCED")).upper()
    side = str(position.get("position_side", "BUY_CE")).upper()
    is_bullish = side in ["BUY_CE", "LONG_FUTURES", "SHORT_PE"]

    logger.info(f"[ExitDebate] Commencing 3-analyst Exit Debate for {side} (Risk: {risk_profile})...")
    t_start = time.time()

    context = _build_exit_debate_context(stage1_result, position, live_signals, heavyweights)

    # ── Stage 1: 3 Groq Exit Personas in PARALLEL ───────────────────────────
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            fut_runner = executor.submit(_run_exit_persona, "RUNNER", _EXIT_RUNNER_SYSTEM, context, groq_key, live_spot, is_bullish)
            fut_guard  = executor.submit(_run_exit_persona, "GUARDIAN", _EXIT_GUARDIAN_SYSTEM, context, groq_key, live_spot, is_bullish)
            fut_tac    = executor.submit(_run_exit_persona, "TACTICAL", _EXIT_TACTICAL_SYSTEM, context, groq_key, live_spot, is_bullish)

            runner_res   = fut_runner.result(timeout=10)
            guardian_res = fut_guard.result(timeout=10)
            tactical_res = fut_tac.result(timeout=10)
    except Exception as e:
        logger.error(f"[ExitDebate] Parallel exit persona execution failed: {e} — returning Stage 1.")
        return stage1_result

    # If all 3 personas failed (Groq down/offline), safely return Stage 1 result
    if runner_res.get("_fallback") and guardian_res.get("_fallback") and tactical_res.get("_fallback"):
        logger.warning("[ExitDebate] All 3 personas failed — returning Stage 1 result unchanged.")
        return stage1_result

    t_personas = round(time.time() - t_start, 2)
    logger.info(f"[ExitDebate] 3 personas finished in {t_personas}s")

    # ── Stage 2: Gemini Flash Exit Judge ────────────────────────────────────
    judge_res = None
    if gemini_key:
        judge_context = f"""EXIT DEBATE SUBMISSIONS:

RUNNER ANALYST:
{json.dumps(runner_res, indent=2)}

CAPITAL GUARDIAN:
{json.dumps(guardian_res, indent=2)}

TACTICAL SCALE-OUT MANAGER:
{json.dumps(tactical_res, indent=2)}

POSITION CONTEXT:
- Trade: {position.get('position_side')} ({position.get('strike')})
- Live Spot: {live_spot}
- Trader Risk Profile: {risk_profile}
- Baseline Verdict: {stage1_result.get('verdict')}

Synthesize the 3 analyst submissions into a final calibrated exit recommendation."""

        try:
            t0 = time.time()
            judge_res = _gemini_call(_EXIT_JUDGE_SYSTEM, judge_context, gemini_key, timeout=10)
            logger.info(f"[ExitDebate] Judge completed in {round(time.time() - t0, 2)}s")
        except Exception as e:
            logger.warning(f"[ExitDebate] Gemini Exit Judge failed: {e} — using rule fallback.")

    # ── Stage 3: Merge and Finalize ─────────────────────────────────────────
    if judge_res and isinstance(judge_res, dict) and judge_res.get("verdict") in EXIT_VERDICTS:
        final_verdict    = judge_res["verdict"]
        final_action     = judge_res.get("action", stage1_result.get("action", ""))
        final_sl         = judge_res.get("trailing_sl", stage1_result.get("trailing_sl"))
        consensus        = judge_res.get("debate_consensus", "MAJORITY")
        conf_adj         = int(judge_res.get("confidence_adjustment", 0))
        judge_rationale  = judge_res.get("judge_rationale", "")
    else:
        final_verdict, consensus, fallback_note = _determine_exit_consensus(
            runner_res, guardian_res, tactical_res, risk_profile
        )
        final_action = f"Execute {final_verdict.replace('_', ' ').title()}. Committee consensus: {consensus}."
        final_sl = tactical_res.get("suggested_sl") or stage1_result.get("trailing_sl") or live_spot
        conf_adj = +5 if consensus == "UNANIMOUS" else (-10 if consensus == "SPLIT" else 0)
        judge_rationale = f"Gemini Judge offline — {fallback_note}"

    orig_conf = int(stage1_result.get("confidence", 75))
    final_conf = max(10, min(95, orig_conf + conf_adj))

    enriched = dict(stage1_result)
    enriched.update({
        "verdict": final_verdict,
        "action": final_action,
        "trailing_sl": final_sl,
        "confidence": final_conf,
        "debate_consensus": consensus,
        "debate": {
            "runner_analyst": {
                "verdict": runner_res.get("verdict"),
                "confidence": runner_res.get("confidence"),
                "suggested_sl": runner_res.get("suggested_sl"),
                "rationale": runner_res.get("rationale"),
            },
            "capital_guardian": {
                "verdict": guardian_res.get("verdict"),
                "confidence": guardian_res.get("confidence"),
                "suggested_sl": guardian_res.get("suggested_sl"),
                "rationale": guardian_res.get("rationale"),
            },
            "tactical_manager": {
                "verdict": tactical_res.get("verdict"),
                "confidence": tactical_res.get("confidence"),
                "suggested_sl": tactical_res.get("suggested_sl"),
                "rationale": tactical_res.get("rationale"),
            },
            "judge_rationale": judge_rationale,
        },
        "engine": (
            str(enriched.get("engine", "AI Evaluator"))
            + " → Exit Committee (3×Groq + Gemini Judge)"
        ),
    })

    t_total = round(time.time() - t_start, 2)
    logger.info(f"[ExitDebate] Successfully calibrated exit to '{final_verdict}' ({consensus}) in {t_total}s.")
    return enriched


# ─────────────────────────────────────────────────────────────────────────────
# 3-Analyst Intraday Debate Committee (Momentum Scalper, Wall Defender, Tactical Risk)
# ─────────────────────────────────────────────────────────────────────────────

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


def _build_intraday_debate_context(
    intraday_result: dict[str, Any],
    market_signals: dict[str, Any],
    heavyweights: dict[str, Any],
    news_sentiment: str,
) -> str:
    """Builds a structured prompt for intraday persona agents."""
    bias_dict = intraday_result.get("intraday_bias", {})
    pat_dict = intraday_result.get("intraday_pattern", {})
    phase_dict = intraday_result.get("market_phase", {})
    vol_dict = intraday_result.get("volatility", {})

    live_spot = market_signals.get("nifty_spot", 0)
    vix = market_signals.get("india_vix", 12.0)
    pcr = market_signals.get("pcr", 1.0)
    max_pain = market_signals.get("max_pain", "N/A")
    top_call = market_signals.get("top_oi_call_strike", "N/A")
    top_put = market_signals.get("top_oi_put_strike", "N/A")

    hw_lines = []
    for sym, d in (heavyweights or {}).items():
        hw_lines.append(f"  • {d.get('name', sym)}: ₹{d.get('price', 0)} ({d.get('change_pct', 0):+.2f}%)")
    hw_text = "\n".join(hw_lines) if hw_lines else "  • Heavyweights: Normal"

    return f"""NIFTY 50 LIVE INTRADAY CONTEXT:
- Live NIFTY Spot: {live_spot}
- Intraday Baseline Bias: {bias_dict.get('bias', 'NEUTRAL')} (Confidence: {bias_dict.get('confidence', 50)}%)
- Expected Pattern: {pat_dict.get('pattern', 'RANGE-BOUND')} — {pat_dict.get('description', '')}
- Market Phase: {phase_dict.get('phase', 'MARKET HOURS')} — {phase_dict.get('description', '')}
- Volatility: {vol_dict.get('level', 'MODERATE')} (Range: {vol_dict.get('expected_range', '50-100 pts')})
- News Sentiment: {news_sentiment}
- India VIX: {vix} | Option Chain PCR: {pcr} | Max Pain: {max_pain}
- Top Call OI Wall: {top_call} | Top Put OI Floor: {top_put}

HEAVYWEIGHT STOCK MOVERS:
{hw_text}

INTRADAY BASELINE STRATEGY:
- Strategy: {pat_dict.get('strategy', 'Strict risk management')}
- Option Strategy: {pat_dict.get('option_strategy', 'Monitor key levels')}
"""


def _run_intraday_persona(
    persona_name: str,
    system_prompt: str,
    context: str,
    groq_key: str,
    live_spot: float,
) -> dict:
    """Execute a single intraday persona with resilient fallback."""
    t0 = time.time()
    result = _groq_call(system_prompt, context, groq_key)
    elapsed = round(time.time() - t0, 2)

    if result and isinstance(result, dict) and result.get("verdict") in INTRADAY_VERDICTS:
        logger.info(f"[IntradayDebate] {persona_name}: {result.get('verdict')} ({result.get('confidence')}%) in {elapsed}s")
        return result

    logger.warning(f"[IntradayDebate] {persona_name} failed/invalid — using fallback.")
    return {
        "persona": persona_name,
        "verdict": "SCALP_DIPS_ONLY" if persona_name == "MOMENTUM" else "STRICT_WAIT_AND_WATCH",
        "confidence": 60,
        "trigger_level": round(live_spot, 1) if live_spot else 0,
        "key_wall": round(live_spot, 1) if live_spot else 0,
        "stop_loss": round(live_spot * 0.997, 1) if live_spot else 0,
        "rationale": f"{persona_name} agent offline — adopting prudent level-to-level wait-and-watch approach.",
        "_fallback": True,
    }


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


def run_intraday_debate(
    intraday_result: dict[str, Any],
    market_signals: dict[str, Any],
    heavyweights: dict[str, Any],
    news_sentiment: str,
    groq_key: str,
    gemini_key: str,
) -> dict[str, Any]:
    """
    Runs the 3-analyst Intraday Risk Debate committee:
    1. Momentum & Trend Scalper (Groq)
    2. Mean-Reversion & Wall Defender (Groq)
    3. Tactical Risk & Scalp Manager (Groq)
    4. Gemini Flash Intraday Synthesis Judge

    Enriches intraday_result with 'debate' breakdown, calibrated 'structure', and exact action plan.
    """
    if not groq_key:
        logger.warning("[IntradayDebate] GROQ_API_KEY not set — skipping intraday debate.")
        return intraday_result

    live_spot = float(market_signals.get("nifty_spot", 0))
    logger.info(f"[IntradayDebate] Starting 3-Analyst Intraday Debate (Spot: {live_spot})...")
    t_start = time.time()

    context = _build_intraday_debate_context(intraday_result, market_signals, heavyweights, news_sentiment)

    # ── Stage 1: 3 Groq Personas in Parallel ────────────────────────────────
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            fut_mom = executor.submit(_run_intraday_persona, "MOMENTUM", _INTRADAY_MOMENTUM_SYSTEM, context, groq_key, live_spot)
            fut_def = executor.submit(_run_intraday_persona, "DEFENDER", _INTRADAY_MEAN_REVERSION_SYSTEM, context, groq_key, live_spot)
            fut_tac = executor.submit(_run_intraday_persona, "TACTICAL", _INTRADAY_TACTICAL_SYSTEM, context, groq_key, live_spot)

            mom_res = fut_mom.result(timeout=10)
            def_res = fut_def.result(timeout=10)
            tac_res = fut_tac.result(timeout=10)
    except Exception as e:
        logger.error(f"[IntradayDebate] Parallel execution failed: {e} — returning base result.")
        return intraday_result

    # If all 3 personas failed, return untouched
    if mom_res.get("_fallback") and def_res.get("_fallback") and tac_res.get("_fallback"):
        logger.warning("[IntradayDebate] All 3 personas failed — returning base intraday result.")
        return intraday_result

    t_personas = round(time.time() - t_start, 2)
    logger.info(f"[IntradayDebate] 3 personas finished in {t_personas}s")

    # ── Stage 2: Gemini Flash Intraday Judge ─────────────────────────────────
    judge_res = None
    if gemini_key:
        judge_context = f"""INTRADAY DEBATE SUBMISSIONS:

MOMENTUM & TREND SCALPER:
{json.dumps(mom_res, indent=2)}

MEAN-REVERSION & WALL DEFENDER:
{json.dumps(def_res, indent=2)}

TACTICAL RISK & SCALP MANAGER:
{json.dumps(tac_res, indent=2)}

MARKET CONTEXT:
- Live NIFTY Spot: {live_spot}
- Current Market Phase: {intraday_result.get('market_phase', {}).get('phase', 'MARKET HOURS')}
- Volatility Regime: {intraday_result.get('volatility', {}).get('level', 'MODERATE')}
- India VIX: {market_signals.get('india_vix', 12.0)} | PCR: {market_signals.get('pcr', 1.0)}
"""
        judge_raw = _gemini_call(_INTRADAY_JUDGE_SYSTEM, judge_context, gemini_key)
        if judge_raw and isinstance(judge_raw, dict) and judge_raw.get("structure") in INTRADAY_VERDICTS:
            judge_res = judge_raw
            logger.info(f"[IntradayDebate] Gemini Judge: {judge_res.get('structure')} ({judge_res.get('debate_consensus')})")

    if judge_res:
        final_structure = judge_res.get("structure", "SCALP_DIPS_ONLY")
        final_action = judge_res.get("action_plan", "Trade with disciplined level-to-level risk management.")
        entry_zone = judge_res.get("entry_zone", f"{round(live_spot - 20, 1)} - {round(live_spot + 20, 1)}")
        target = judge_res.get("target") or round(live_spot + 50, 1)
        stop_loss = judge_res.get("stop_loss") or round(live_spot - 30, 1)
        consensus = judge_res.get("debate_consensus", "MAJORITY")
        conf_adj = int(judge_res.get("confidence_adjustment", 0))
        judge_rationale = judge_res.get("judge_rationale", "")
    else:
        fallback_struct, consensus, fallback_note = _determine_intraday_consensus(mom_res, def_res, tac_res)
        final_structure = fallback_struct
        final_action = f"Committee consensus: {fallback_struct}. Execute with strict stop loss."
        entry_zone = tac_res.get("entry_zone", f"{round(live_spot - 25, 1)} - {round(live_spot, 1)}")
        target = round(live_spot + 45, 1)
        stop_loss = tac_res.get("stop_loss") or round(live_spot - 30, 1)
        conf_adj = +5 if consensus == "UNANIMOUS" else (-10 if consensus == "SPLIT" else 0)
        judge_rationale = f"Gemini Judge offline — {fallback_note}"

    # Grounding Stop Loss & Target relative to spot
    if live_spot > 0:
        try:
            stop_loss = float(stop_loss)
            target = float(target)
            if "PUT" in final_structure or "BEAR" in final_structure:
                # Bearish trade: SL must be ABOVE spot, Target BELOW spot
                if stop_loss <= live_spot:
                    stop_loss = round(live_spot + 30, 1)
                if target >= live_spot:
                    target = round(live_spot - 50, 1)
            else:
                # Bullish trade: SL must be BELOW spot, Target ABOVE spot
                if stop_loss >= live_spot:
                    stop_loss = round(live_spot - 30, 1)
                if target <= live_spot:
                    target = round(live_spot + 50, 1)
        except Exception:
            stop_loss = round(live_spot - 30, 1)
            target = round(live_spot + 50, 1)

    base_bias = intraday_result.get("intraday_bias") or {}
    orig_conf = int(base_bias.get("confidence", 65))
    final_conf = max(10, min(95, orig_conf + conf_adj))

    enriched = dict(intraday_result)
    bias_copy = dict(base_bias)
    bias_copy["confidence"] = final_conf
    enriched["intraday_bias"] = bias_copy
    enriched["debate"] = {
        "momentum_scalper": {
            "verdict": mom_res.get("verdict"),
            "confidence": mom_res.get("confidence"),
            "trigger_level": mom_res.get("trigger_level"),
            "rationale": mom_res.get("rationale"),
        },
        "wall_defender": {
            "verdict": def_res.get("verdict"),
            "confidence": def_res.get("confidence"),
            "key_wall": def_res.get("key_wall"),
            "rationale": def_res.get("rationale"),
        },
        "tactical_scalper": {
            "verdict": tac_res.get("verdict"),
            "confidence": tac_res.get("confidence"),
            "entry_zone": tac_res.get("entry_zone"),
            "stop_loss": tac_res.get("stop_loss"),
            "rationale": tac_res.get("rationale"),
        },
        "structure": final_structure,
        "action_plan": final_action,
        "entry_zone": entry_zone,
        "target": target,
        "stop_loss": stop_loss,
        "consensus": consensus,
        "judge_rationale": judge_rationale,
    }

    t_total = round(time.time() - t_start, 2)
    logger.info(f"[IntradayDebate] Committee concluded: '{final_structure}' ({consensus}) in {t_total}s.")
    return enriched
