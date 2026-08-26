"""
exit_analyzer.py — AI-Evaluated Live Position Exit Advisor Engine
Integrates live options P&L, constituent heavyweights, India VIX, global cues,
and breaking news to provide professional, grounded exit recommendations.
"""

import os
import re
import json
import logging
import requests
from datetime import datetime
from typing import Any, Optional
import pytz
from dotenv import load_dotenv

from exit_fast_path import (
    evaluate_fast_path,
    fetch_heavyweight_stocks,
    generate_rule_based_fallback,
    TIMEZONE
)

load_dotenv()
logger = logging.getLogger("ExitAnalyzer")

EXIT_SYSTEM_PROMPT = """
You are an elite NIFTY 50 Options Risk Management AI. You evaluate open option positions by internally reasoning from SIX specialist perspectives, then synthesising a final verdict.

STEP 1 — EVALUATE EACH DIMENSION INTERNALLY:

1. GREEKS_DECAY Agent: Assess option premium status, DTE (days to expiry), moneyness (ITM/ATM/OTM), theta decay rate, and whether the premium is decaying beneficially (short) or adversely (long).
2. OI_PCR Agent: Evaluate Put-Call Ratio, Max Pain level vs current spot, top OI Call strike (resistance wall) and top OI Put strike (support floor). Is the OI structure supportive or opposing the trade?
3. HEAVYWEIGHTS Agent: HDFC Bank (11.5%) + Reliance (9.2%) = 20.7% of NIFTY. Are they aligned or diverging from the trade direction? Include ICICI Bank, Infosys, TCS.
4. PRICE_ACTION Agent: Consider time of day (morning ORB, midday consolidation, European open 13:30 IST, pre-close 15:15), BTST gap behaviour, and NIFTY spot % move vs entry.
5. VIX_REGIME Agent: Assess India VIX level and intraday change. VIX <12 = calm (favour HOLD), VIX 12-16 = moderate, VIX >16 = elevated (favour tighter stops), VIX spike >5% = tighten immediately.
6. MACRO_GLOBAL Agent: Evaluate FII/DII institutional flow (net buyer/seller bias), global cues (S&P500, NASDAQ, Nikkei, DAX), and breaking news sentiment impact.

STEP 2 — CONFLICT RESOLUTION:
If agents disagree, use this priority order: VIX_REGIME > GREEKS_DECAY > OI_PCR > PRICE_ACTION > HEAVYWEIGHTS > MACRO_GLOBAL.
When 3+ agents recommend EXIT/tighten and 1-2 recommend HOLD, always choose the more conservative (protective) verdict.

VALID FINAL VERDICTS:
- "HOLD_AND_RIDE": All/majority agents aligned bullish/bearish — trend intact.
- "PARTIAL_BOOK_50": Target 1 hit (+25-45% option gain or +0.25-0.45% favorable spot move).
- "PARTIAL_BOOK_70": Target 2 hit (+50%+ option gain or +0.5%+ spot move or BTST gap realized).
- "TRAIL_SL_TO_COST": Momentum slowing — move SL to breakeven to make trade risk-free.
- "TRAIL_SL_TIGHT": Multiple agents flagging risk — tighten stop to protect gains.
- "FULL_EXIT": Thesis invalidated — heavyweights opposing, adverse move >0.25%, or structural breakdown.
- "PRE_CLOSE_EXIT": 15:15 IST or later — mandatory intraday square-off.
- "EMERGENCY_EXIT": Severe adverse shock, VIX spike, flash crash.

STRICT RULES:
1. Never recommend HOLD if HDFC Bank + Reliance are both moving >0.4% AGAINST the position.
2. BTST morning gap (09:15-09:30): If gap is in favor >0.15%, always recommend PARTIAL_BOOK (50-70%).
3. Trailing SL must be within 1% of current live Nifty spot. Do NOT invent arbitrary numbers.

Return ONLY a valid JSON object:
{
  "verdict": "<one of the 8 valid verdicts>",
  "action": "<immediate step-by-step instruction with specific lot sizes and price levels>",
  "confidence": <number 10-95>,
  "urgency": "NORMAL" | "MEDIUM" | "HIGH" | "CRITICAL",
  "trailing_sl": <number: suggested stop loss spot level>,
  "thesis_status": "INTACT" | "WEAKENING" | "INVALIDATED",
  "heavyweight_pulse": "<1-line summary of HDFC Bank & Reliance alignment>",
  "reasoning": "<2-3 crisp sentences: catalyst + risk-reward rationale + recommended action>",
  "dimension_scores": {
    "greeks_decay": {"verdict": "<HOLD|PARTIAL_BOOK|TRAIL|EXIT>", "note": "<1 crisp line: key theta/delta/moneyness insight>"},
    "oi_pcr": {"verdict": "<HOLD|PARTIAL_BOOK|TRAIL|EXIT>", "note": "<1 line: PCR level, max pain proximity, OI wall>"},
    "heavyweights": {"verdict": "<HOLD|PARTIAL_BOOK|TRAIL|EXIT>", "note": "<1 line: HDFC+Reliance % change and alignment>"},
    "price_action": {"verdict": "<HOLD|PARTIAL_BOOK|TRAIL|EXIT>", "note": "<1 line: time-of-day context and spot % move>"},
    "vix_regime": {"verdict": "<HOLD|PARTIAL_BOOK|TRAIL|EXIT>", "note": "<1 line: VIX level and intraday change assessment>"},
    "macro_global": {"verdict": "<HOLD|PARTIAL_BOOK|TRAIL|EXIT>", "note": "<1 line: FII/DII flow + global market cue>"}
  },
  "fii_dii_context": "<1 line: FII net ₹X Cr + DII net ₹Y Cr + combined sentiment>",
  "expiry_context": "<1 line: DTE count, expiry day status, theta urgency>"
}
"""


def _validate_and_ground_output(
    parsed: dict[str, Any],
    live_spot: float,
    entry_spot: float
) -> dict[str, Any]:
    """
    Validates output structure and verifies numerical claims to prevent AI hallucination.
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
        parsed["trailing_sl"] = round(sl, 1)
    except Exception:
        parsed["trailing_sl"] = round(entry_spot if entry_spot > 0 else live_spot, 1)

    return parsed


def build_exit_prompt_context(
    position: dict[str, Any],
    live_signals: dict[str, Any],
    heavyweights: dict[str, Any],
    news_items: list[dict],
    fii_dii_data: dict[str, Any] | None = None
) -> str:
    """
    Builds rich, structured prompt with live position status, P&L %, heavyweights,
    FII/DII flow, option chain data, DTE, strike moneyness, and expiry day context.
    """
    now_ist = datetime.now(TIMEZONE)
    trade_type = str(position.get("trade_type", "INTRADAY")).upper()
    side = str(position.get("position_side", "BUY_CE")).upper()
    strike = position.get("strike", "At-The-Money")
    entry_spot = float(position.get("entry_spot") or live_signals.get("nifty_spot") or 0)
    current_spot = float(live_signals.get("nifty_spot") or entry_spot)

    entry_premium = float(position.get("entry_premium") or 0)
    current_premium = float(position.get("current_premium") or 0)
    entry_time = position.get("entry_time", "Earlier today")
    risk_profile = position.get("risk_profile", "BALANCED").upper()
    dte = position.get("dte")  # Days to Expiry (optional, user-supplied)

    # Calculate underlying movement
    spot_diff = round(current_spot - entry_spot, 1)
    spot_pct = round(((current_spot - entry_spot) / entry_spot) * 100, 2) if entry_spot > 0 else 0.0

    is_bullish = side in ["BUY_CE", "LONG_FUTURES", "SHORT_PE"]
    favorable_move = spot_pct if is_bullish else -spot_pct

    # Option P&L
    prem_info = "N/A (Tracking Spot)"
    pnl_pct = None
    if entry_premium > 0 and current_premium > 0:
        if side in ["SHORT_CE", "SHORT_PE"]:
            pnl_pct = round(((entry_premium - current_premium) / entry_premium) * 100, 1)
        else:
            pnl_pct = round(((current_premium - entry_premium) / entry_premium) * 100, 1)
        prem_info = f"Entry: ₹{entry_premium} ➔ Current: ₹{current_premium} ({pnl_pct:+.1f}% P&L)"

    # Strike Moneyness
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

    # DTE and expiry day context
    from exit_fast_path import is_expiry_day as _is_expiry_day
    expiry_day = _is_expiry_day()
    if dte is not None:
        try:
            dte_int = int(dte)
            if expiry_day or dte_int == 0:
                dte_text = "⚠️ WEEKLY EXPIRY TODAY — theta collapse accelerating post-13:00 IST. Short sellers: lock profits aggressively."
            elif dte_int <= 2:
                dte_text = f"⚠️ {dte_int} DTE — near-expiry theta collapse in effect. Short sellers should lock profits."
            elif dte_int <= 5:
                dte_text = f"{dte_int} DTE — elevated theta burn rate. Tighten management."
            else:
                dte_text = f"{dte_int} DTE — normal theta decay."
        except Exception:
            dte_text = f"DTE: {dte}"
    elif expiry_day:
        dte_text = "⚠️ WEEKLY EXPIRY TODAY (Thursday) — theta collapse accelerating. Short sellers: lock profits aggressively."
    else:
        dte_text = "DTE: Not specified (assume normal decay)."

    # Heavyweight table
    hw_lines = []
    for sym, d in heavyweights.items():
        hw_lines.append(f"  • {d['name']} ({d['weight']}% weight): ₹{d['price']} ({d['change_pct']:+.2f}%)")
    hw_text = "\n".join(hw_lines) if hw_lines else "  • Heavyweight data loading..."

    # Option Chain / OI Data
    pcr = live_signals.get("pcr", 1.05)
    max_pain = live_signals.get("max_pain", "N/A")
    top_oi_call = live_signals.get("top_oi_call_strike", "N/A")
    top_oi_put = live_signals.get("top_oi_put_strike", "N/A")
    pcr_interp = (
        "BEARISH (heavy call writing = resistance ceiling)" if pcr < 0.80 else
        "BULLISH (heavy put writing = support floor)" if pcr > 1.30 else
        "NEUTRAL"
    )
    oi_text = (
        f"  • PCR: {pcr:.2f} → {pcr_interp}\n"
        f"  • Max Pain: {max_pain} | Top Call OI Wall: {top_oi_call} | Top Put OI Floor: {top_oi_put}"
    )

    # FII/DII Institutional Flow
    if fii_dii_data:
        fii_net = fii_dii_data.get("fii_net_crores", 0)
        dii_net = fii_dii_data.get("dii_net_crores", 0)
        inst_sentiment = fii_dii_data.get("institutional_sentiment", "NEUTRAL")
        fii_dii_text = (
            f"  • FII: ₹{fii_net:+.0f} Cr | DII: ₹{dii_net:+.0f} Cr | "
            f"Combined: ₹{fii_net + dii_net:+.0f} Cr → {inst_sentiment}"
        )
    else:
        fii_dii_text = "  • FII/DII data unavailable."

    # Compact news (top 8)
    compact_news = [
        f"  • [{it.get('category', 'Market')}] {it.get('headline')}"
        for it in news_items[:8]
    ]
    news_text = "\n".join(compact_news) if compact_news else "  • No breaking market-moving headlines."

    # Time-of-day context
    time_ctx = f"Current Time: {now_ist.strftime('%H:%M:%S IST')}."
    if now_ist.hour == 9 and now_ist.minute <= 30:
        time_ctx += " ⚠️ MORNING OPENING GAP / 15-MIN ORB PHASE. High volatility and gap-fill risk."
    elif now_ist.hour == 13 and 15 <= now_ist.minute <= 45:
        time_ctx += " ⚠️ EUROPEAN MARKET OPEN WINDOW (13:30 IST). Watch for afternoon trend shift."
    elif now_ist.hour == 15 and now_ist.minute >= 0:
        time_ctx += " ⚠️ PRE-CLOSE INTRADAY AUTO-SQUARE-OFF WINDOW."

    return f"""
    === USER'S LIVE OPEN POSITION ===
    - Trade Type: {trade_type} ({'Overnight BTST' if trade_type == 'BTST' else 'Intraday Day Trade'})
    - Position Side: {side} ({strike})
    - {moneyness_text}
    - Entry NIFTY Spot: {entry_spot} | Live NIFTY Spot: {current_spot} (Diff: {spot_diff:+.1f} pts, {spot_pct:+.2f}%)
    - Directional Performance: {favorable_move:+.2f}% {'Favorable ✅' if favorable_move >= 0 else 'Adverse ❌'}
    - Option Premium Status: {prem_info}
    - Entry Time: {entry_time} | Risk Profile: {risk_profile}
    - {time_ctx}
    - Expiry / Theta Context: {dte_text}

    === LIVE MARKET MICROSTRUCTURE ===
    - NIFTY 50 Change: {live_signals.get('nifty_pct', 'N/A')}%
    - India VIX: {live_signals.get('india_vix', 'N/A')} (Intraday Change: {live_signals.get('india_vix_change_pct', 'N/A')}%)
    - Bank Nifty: {live_signals.get('sectoral_signals', {}).get('bank_nifty_pct', 'N/A')}%
    - IT Nifty: {live_signals.get('sectoral_signals', {}).get('it_nifty_pct', 'N/A')}%
    - Global Asian / US Cues: {json.dumps(live_signals.get('global_market_changes', {}))}

    === OPTION CHAIN — OI STRUCTURE ===
{oi_text}

    === INSTITUTIONAL FLOW (FII / DII) ===
{fii_dii_text}

    === TOP 5 NIFTY CONSTITUENT HEAVYWEIGHTS (~39% Index Impact) ===
{hw_text}

    === BREAKING NEWS HEADLINES ===
{news_text}

    Evaluate this live trade across all 6 specialist dimensions, then synthesise a final verdict. Return the JSON exit recommendation.
    """


# Verdict severity mapping for conflict resolution (higher = more urgent/conservative)
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
# Weights for each specialist dimension
_AGENT_WEIGHTS = {
    "greeks_decay": 0.25,
    "vix_regime": 0.20,
    "oi_pcr": 0.20,
    "price_action": 0.15,
    "heavyweights": 0.10,
    "macro_global": 0.10,
}


def _resolve_dimension_conflict(parsed: dict[str, Any]) -> dict[str, Any]:
    """
    Cross-validates the LLM's final verdict against dimension_scores using
    weighted scoring. If 4+ dimensions are more conservative than the LLM verdict,
    upgrade to the safer option. Adds 'conflict_resolved' flag if overridden.
    """
    dimension_scores = parsed.get("dimension_scores", {})
    if not dimension_scores or len(dimension_scores) < 3:
        return parsed  # Not enough data to override

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
        # Find the verdict matching the weighted average severity
        target_severity = round(avg_severity)
        target_severity = max(0, min(7, target_severity))
        # Reverse map: pick verdict closest to target severity
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

    return parsed


def evaluate_exit_with_ai(
    position: dict[str, Any],
    live_signals: dict[str, Any],
    news_items: list[dict],
    fii_dii_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Main evaluation pipeline:
    1. Stage 1: Deterministic Fast-Path (0-10ms) — 7 safety rules
    2. Stage 2: Heavyweight & Context Aggregation (≤350ms)
    3. Stage 3: Single enriched multi-perspective AI call (Groq → Gemini fallback) (≤1200ms)
    4. Stage 4: Output Validation, Weighted Conflict Resolution & Safety Fallback
    """
    # --- STAGE 1: Fast-Path Deterministic Check ---
    fast_result = evaluate_fast_path(position, live_signals)
    if fast_result:
        logger.info(f"⚡ Fast-Path Triggered: {fast_result['verdict']}")
        return fast_result

    # --- STAGE 2: Heavyweight Constituent Scrape ---
    heavyweights = fetch_heavyweight_stocks()
    live_spot = float(live_signals.get("nifty_spot") or 0)
    entry_spot = float(position.get("entry_spot") or live_spot)

    user_prompt = build_exit_prompt_context(
        position, live_signals, heavyweights, news_items, fii_dii_data
    )

    # --- STAGE 3: AI Inference (Groq Primary → Gemini Fallback) ---
    groq_key = os.environ.get("GROQ_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")

    # Try Groq Cloud (ultra-fast ~800ms)
    if groq_key:
        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json"
            }
            for model in ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b"]:
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": EXIT_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"}
                }
                res = requests.post(url, headers=headers, json=payload, timeout=6.0)
                if res.status_code == 200:
                    raw_text = res.json()["choices"][0]["message"]["content"]
                    parsed = json.loads(raw_text)
                    grounded = _validate_and_ground_output(parsed, live_spot, entry_spot)
                    grounded = _resolve_dimension_conflict(grounded)
                    grounded["engine"] = f"Groq AI ({model}) — Multi-Perspective 6-Agent"
                    grounded["heavyweights"] = heavyweights
                    grounded["is_fast_path"] = False
                    grounded["is_fallback"] = False
                    logger.info(f"✅ Groq Exit Advisor Decision: {grounded['verdict']} ({grounded['confidence']}%)")
                    return grounded
        except Exception as groq_err:
            logger.warning(f"Groq Exit Advisor error: {groq_err}")

    # Fallback to Google Gemini
    if gemini_key:
        try:
            for model in ["gemini-2.5-flash", "gemini-flash-latest"]:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
                headers = {"Content-Type": "application/json"}
                payload = {
                    "contents": [
                        {"role": "user", "parts": [{"text": EXIT_SYSTEM_PROMPT + "\n\n" + user_prompt}]}
                    ],
                    "generationConfig": {"response_mime_type": "application/json"}
                }
                res = requests.post(url, headers=headers, json=payload, timeout=7.0)
                if res.status_code == 200:
                    raw_text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = json.loads(raw_text)
                    grounded = _validate_and_ground_output(parsed, live_spot, entry_spot)
                    grounded = _resolve_dimension_conflict(grounded)
                    grounded["engine"] = f"Google Gemini ({model}) — Multi-Perspective 6-Agent"
                    grounded["heavyweights"] = heavyweights
                    grounded["is_fast_path"] = False
                    grounded["is_fallback"] = False
                    logger.info(f"✅ Gemini Exit Advisor Decision: {grounded['verdict']} ({grounded['confidence']}%)")
                    return grounded
        except Exception as gemini_err:
            logger.warning(f"Gemini Exit Advisor error: {gemini_err}")

    # --- STAGE 4: Deterministic Mathematical Fallback ---
    logger.warning("All AI models offline/timed out. Engaging Rule-Based Fallback Advisor.")
    fallback = generate_rule_based_fallback(position, live_signals, heavyweights)
    fallback["heavyweights"] = heavyweights
    return fallback

