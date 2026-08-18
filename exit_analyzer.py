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
You are an elite NIFTY 50 Options Trader & Risk Manager acting as an AI Live Position Exit Advisor.
Your objective is to evaluate an open live position (BTST or Intraday) against real-time market data, constituent heavyweights, India VIX, and breaking news.

VALID VERDICTS (Choose STRICTLY ONE of these):
- "HOLD_AND_RIDE": Trend is strong, heavyweights aligned, no threat catalysts.
- "PARTIAL_BOOK_50": Target 1 reached (+0.25% to +0.45% spot move or +20% to +35% option gain). Lock 50%, trail SL to cost.
- "PARTIAL_BOOK_70": Target 2 reached (+0.50%+ spot move, or BTST morning gap realized). Lock 70%, trail remaining 30%.
- "TRAIL_SL_TO_COST": Momentum slowing or consolidation near resistance/support. Shift SL to entry breakeven.
- "TRAIL_SL_TIGHT": Move trailing stop closer to current spot to protect unrealized gains.
- "FULL_EXIT": Invalidation: Heavyweights opposing trade, structural breakdown, or adverse move >0.25%.
- "PRE_CLOSE_EXIT": Mandatory intraday square-off approaching 15:15 IST.
- "EMERGENCY_EXIT": Severe adverse shock, sudden VIX spike, or opposing global crash.

STRICT RISK RULES:
1. BTST Trades: Morning window (09:15-09:30 IST) is for PROFIT BOOKING. If gap is in favor, recommend PARTIAL_BOOK (50-70%). Never let an overnight winning gap turn into a loss.
2. Heavyweight Confluence: HDFC Bank (11.5%) + Reliance (9.2%) represent >20% of NIFTY. If they are moving AGAINST the user's position, do NOT recommend HOLD; recommend FULL_EXIT or TRAIL_SL_TIGHT.
3. European Open Window (13:15-13:45 IST): If DAX/FTSE or German market cues are reversing, tighten stops.
4. Numerical Grounding: State exact realistic price levels. Do NOT invent arbitrary numbers. Trailing SL must be consistent with the live Nifty spot or entry level.

Return ONLY a valid JSON object matching this schema:
{
  "verdict": "HOLD_AND_RIDE" | "PARTIAL_BOOK_50" | "PARTIAL_BOOK_70" | "TRAIL_SL_TO_COST" | "TRAIL_SL_TIGHT" | "FULL_EXIT" | "PRE_CLOSE_EXIT" | "EMERGENCY_EXIT",
  "action": "Immediate step-by-step instruction (e.g. 'Book 70% lots at market, move SL on remaining 30% to 24,180')",
  "confidence": number (10-95),
  "urgency": "NORMAL" | "MEDIUM" | "HIGH" | "CRITICAL",
  "trailing_sl": number (suggested stop loss spot level),
  "thesis_status": "INTACT" | "WEAKENING" | "INVALIDATED",
  "heavyweight_pulse": "Brief 1-line summary of HDFC Bank & Reliance alignment",
  "reasoning": "2-3 crisp sentences explaining the catalyst and risk-reward rationale"
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
    news_items: list[dict]
) -> str:
    """
    Builds rich, structured prompt with live position status, P&L %, heavyweights, and signals.
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

    # Calculate underlying movement
    spot_diff = round(current_spot - entry_spot, 1)
    spot_pct = round(((current_spot - entry_spot) / entry_spot) * 100, 2) if entry_spot > 0 else 0.0

    is_bullish = side in ["BUY_CE", "LONG_FUTURES", "SHORT_PE"]
    favorable_move = spot_pct if is_bullish else -spot_pct

    # Option P&L
    prem_info = "N/A (Tracking Spot)"
    if entry_premium > 0 and current_premium > 0:
        pnl_pct = round(((current_premium - entry_premium) / entry_premium) * 100, 1)
        prem_info = f"Entry: ₹{entry_premium} ➔ Current: ₹{current_premium} ({pnl_pct:+.1f}%)"

    # Heavyweight table
    hw_lines = []
    for sym, d in heavyweights.items():
        hw_lines.append(f"  • {d['name']} ({d['weight']}% weight): ₹{d['price']} ({d['change_pct']:+.2f}%)")
    hw_text = "\n".join(hw_lines) if hw_lines else "  • Heavyweight data loading..."

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
    - Entry NIFTY Spot: {entry_spot} | Live NIFTY Spot: {current_spot} (Diff: {spot_diff:+.1f} pts, {spot_pct:+.2f}%)
    - Directional Performance: {favorable_move:+.2f}% {'Favorable' if favorable_move >= 0 else 'Adverse'}
    - Option Premium Status: {prem_info}
    - Entry Time: {entry_time} | Risk Profile: {risk_profile}
    - {time_ctx}

    === LIVE MARKET MICROSTRUCTURE ===
    - NIFTY 50 Change: {live_signals.get('nifty_pct', 'N/A')}%
    - India VIX: {live_signals.get('india_vix', 'N/A')} (Intraday Change: {live_signals.get('india_vix_change_pct', 'N/A')}%)
    - Bank Nifty: {live_signals.get('sectoral_signals', {}).get('bank_nifty_pct', 'N/A')}%
    - IT Nifty: {live_signals.get('sectoral_signals', {}).get('it_nifty_pct', 'N/A')}%
    - Global Asian / US Cues: {json.dumps(live_signals.get('global_market_changes', {}))}

    === TOP 5 NIFTY CONSTITUENT HEAVYWEIGHTS (~39% Index Impact) ===
{hw_text}

    === BREAKING NEWS HEADLINES ===
{news_text}

    Evaluate this live trade against the rules and return the JSON exit recommendation.
    """


def evaluate_exit_with_ai(
    position: dict[str, Any],
    live_signals: dict[str, Any],
    news_items: list[dict]
) -> dict[str, Any]:
    """
    Main evaluation pipeline:
    1. Stage 1: Deterministic Fast-Path (0-10ms)
    2. Stage 2: Heavyweight & Context Aggregation (≤350ms)
    3. Stage 3: Deep AI Reasoning via Groq / Gemini (≤1200ms)
    4. Stage 4: Output Validation, Numerical Grounding & Safety Fallback
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

    user_prompt = build_exit_prompt_context(position, live_signals, heavyweights, news_items)

    # --- STAGE 3: AI Inference (Groq Primary -> Gemini Fallback) ---
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
                    grounded["engine"] = f"Groq AI ({model})"
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
                    grounded["engine"] = f"Google Gemini ({model})"
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
