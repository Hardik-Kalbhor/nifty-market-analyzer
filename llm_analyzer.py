"""
llm_analyzer.py — AI Agent Analysis Engine supporting Gemini API & Grok (xAI) API.
Complements rule-based NLP with Deep LLM Context, NIFTY 50 Stock Weightages,
Numerical Scale Evaluation, and Multi-Agent Reasoning.
"""

import os
import json
import logging
import requests
from typing import Any, Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# NIFTY 50 Top Stock Weightages Matrix
NIFTY_50_WEIGHTS = {
    "HDFC Bank": 11.5,
    "Reliance Industries": 9.2,
    "ICICI Bank": 8.1,
    "Infosys": 5.8,
    "TCS": 4.2,
    "ITC": 4.1,
    "Larsen & Toubro": 3.9,
    "Axis Bank": 3.3,
    "State Bank of India": 3.1,
    "Bharti Airtel": 2.9,
    "Kotak Mahindra Bank": 2.7,
    "Mahindra & Mahindra": 2.2,
    "Tata Motors": 2.1,
}

SYSTEM_PROMPT = """
You are an elite NIFTY 50 Market Intelligence Engine & BTST Risk Manager acting as a 6-Specialist AI Agent Swarm.
Your objective is to evaluate overnight market data across SIX specialist dimensions, resolve conflicts with risk priority, and predict tomorrow's opening gap and BTST trading bias.

STEP 1 — EVALUATE EACH SPECIALIST DIMENSION INTERNALLY:
1. MACRO_GLOBAL Agent: GIFT Nifty % change, US Markets (S&P 500, NASDAQ), European (DAX), and Asian indices. (Bias: BULLISH / BEARISH / NEUTRAL).
2. FII_DII Agent: Net institutional cash flows (FII net + DII net). (Bias: BULLISH / BEARISH / NEUTRAL).
3. OI_PCR Agent: Put-Call Ratio (PCR >1.25 Bullish, <0.80 Bearish), Max Pain pinning level, Top Call OI (resistance wall) and Top Put OI (support floor).
4. HEAVYWEIGHTS Agent: Live performance and news of top 5 NIFTY constituents (HDFC Bank 11.5%, Reliance 9.2%, ICICI Bank 8.1%, Infosys 5.8%, TCS 4.2% = ~39% index weight).
5. VIX_REGIME Agent: India VIX level (<12.0 = Calm, 12-16 = Normal, >16.0 = Elevated risk), expected gap range in points.
6. NEWS_CATALYST Agent: Breaking news sentiment across heavyweights and high-impact sectors (Banking, IT, Auto, Energy).

STEP 2 — SYNTHESIS & STRICT RISK MANAGEMENT RULES:
1. BTST Direction Rules:
   - "BUY CE": Strong confluence across Macro, Heavyweights, and News (minimum 4/6 dimensions Bullish with NO major opposing Heavyweight breakdown).
   - "BUY PE": Strong confluence across Macro, Heavyweights, and News (minimum 4/6 dimensions Bearish with NO major opposing Heavyweight rally).
   - "NO TRADE": Signal conflict (e.g. Bullish news vs Bearish FII/Heavyweights), high VIX (>16.5) with uncertainty, flat market cues, or weekly/monthly expiry pin risk.
2. Opening Gap Predictions:
   - "GAP UP": Expected opening gap >= +0.20% (+50 pts).
   - "GAP DOWN": Expected opening gap <= -0.20% (-50 pts).
   - "FLAT": Expected opening gap between -0.20% and +0.20% (±50 pts).
3. Heavyweight Confluence Rule:
   If HDFC Bank (11.5%) + Reliance (9.2%) are both moving against trade direction (>0.3% adverse), DO NOT recommend that direction. Recommend NO TRADE.
4. F&O Expiry Rule:
   On weekly/monthly expiry day (or eve of expiry), option writers defend Max Pain. Bias towards Max Pain pin zone. Reduce confidence by 10%.

Return ONLY a valid JSON object in this exact schema:
{
  "prediction": "GAP UP" | "GAP DOWN" | "FLAT",
  "confidence": number (10-92),
  "btst_bias": "BUY CE" | "BUY PE" | "NO TRADE",
  "news_sentiment": "BULLISH" | "BEARISH" | "MIXED",
  "dimension_scores": {
    "macro_global": {"verdict": "GAP UP" | "GAP DOWN" | "FLAT", "bias": "BULLISH" | "BEARISH" | "NEUTRAL", "note": "<1 line: GIFT Nifty, US/Asian cues summary>"},
    "fii_dii": {"verdict": "GAP UP" | "GAP DOWN" | "FLAT", "bias": "BULLISH" | "BEARISH" | "NEUTRAL", "note": "<1 line: FII/DII net flow in ₹ Cr and institutional bias>"},
    "oi_pcr": {"verdict": "GAP UP" | "GAP DOWN" | "FLAT", "bias": "BULLISH" | "BEARISH" | "NEUTRAL", "note": "<1 line: PCR level, Max Pain proximity, key OI walls>"},
    "heavyweights": {"verdict": "GAP UP" | "GAP DOWN" | "FLAT", "bias": "BULLISH" | "BEARISH" | "NEUTRAL", "note": "<1 line: HDFC Bank + Reliance % changes and alignment>"},
    "vix_regime": {"verdict": "GAP UP" | "GAP DOWN" | "FLAT", "bias": "BULLISH" | "BEARISH" | "CALM" | "ELEVATED", "note": "<1 line: VIX level, intraday change, expected gap size>"},
    "news_catalyst": {"verdict": "GAP UP" | "GAP DOWN" | "FLAT", "bias": "BULLISH" | "BEARISH" | "MIXED", "note": "<1 line: key news drivers and heavyweight sector pulse>"}
  },
  "weighted_confluence": "<e.g. 5/6 Bullish Confluence | High Probability>",
  "bullish_factors": ["list of bullish drivers sorted in STRICT DESCENDING ORDER of NIFTY impact"],
  "bearish_factors": ["list of bearish drivers sorted in STRICT DESCENDING ORDER of NIFTY impact"],
  "nifty_heavyweight_impact": "<summary of impact from top Nifty stocks>",
  "reasoning": "<crisp 2-3 sentence explanation of the gap prediction and BTST trade rationale>"
}
"""


def _get_fo_expiry_context() -> str:
    """
    Compute F&O expiry context for today (IST).
    Weekly expiry = every Thursday. Monthly expiry = last Thursday of the month.
    """
    from datetime import date, timedelta
    import calendar
    import pytz
    from datetime import datetime
    today = datetime.now(pytz.timezone("Asia/Kolkata")).date()

    # Find the last Thursday of this month
    year, month = today.year, today.month
    last_day = calendar.monthrange(year, month)[1]
    last_thu = max(
        date(year, month, d)
        for d in range(last_day, 0, -1)
        if date(year, month, d).weekday() == 3
    )

    is_weekly_expiry = today.weekday() == 3  # Thursday
    is_monthly_expiry = is_weekly_expiry and today == last_thu
    tomorrow_is_expiry = (today + timedelta(days=1)).weekday() == 3

    if is_monthly_expiry:
        return "⚠️ TODAY IS MONTHLY F&O EXPIRY. Strong pin-to-Max-Pain bias. Force NO TRADE unless a massive catalyst exists."
    elif is_weekly_expiry:
        return "⚠️ TODAY IS WEEKLY F&O EXPIRY (Thursday). Option writers defend Max Pain. Bias FLAT. Reduce confidence by 10%."
    elif tomorrow_is_expiry:
        return "📅 TOMORROW IS F&O EXPIRY (Thursday). BTST positions carry overnight expiry risk — prefer NO TRADE or very tight targets."
    return "No F&O expiry today or tomorrow."


def _build_user_content(
    news_items: list[dict],
    market_signals: dict,
    fii_dii_data: dict | None = None,
    heavyweights: dict | None = None,
) -> str:
    """Build enriched user prompt with all market signals, live heavyweights, FII/DII, and F&O expiry context."""
    compact_news = [
        {"headline": item.get("headline"), "sector": item.get("sector"), "category": item.get("category")}
        for item in news_items[:15]
    ]

    nifty_spot = market_signals.get("nifty_spot")
    nifty_pct = market_signals.get("nifty_pct")
    max_pain = market_signals.get("max_pain")
    top_call = market_signals.get("top_oi_call_strike")
    top_put = market_signals.get("top_oi_put_strike")
    fo_context = _get_fo_expiry_context()

    spot_line = f"Nifty 50 Spot: {nifty_spot} ({nifty_pct:+.2f}%)" if nifty_spot else "Nifty 50 Spot: Market closed / unavailable"
    if max_pain:
        oi_line = f"Max Pain: {max_pain} | Top Call OI Wall (Resistance): {top_call} | Top Put OI Floor (Support): {top_put}"
    else:
        oi_line = "PCR/Max Pain/OI Strikes: Neutral defaults (Use PCR if available)"

    vix_val = market_signals.get("india_vix")
    vix_chg = market_signals.get("india_vix_change_pct")
    vix_str = f"{vix_val:.2f} ({vix_chg:+.2f}%)" if (vix_val is not None and vix_chg is not None) else (f"{vix_val:.2f}" if vix_val is not None else "12.5 (Estimated Calm)")

    gift_chg = market_signals.get("gift_nifty_change_pct")
    gift_str = f"{gift_chg:+.2f}%" if gift_chg is not None else "0.00%"

    pcr_val = market_signals.get("pcr")
    pcr_str = f"{pcr_val:.2f}" if pcr_val is not None else "1.05"

    bank_pct = market_signals.get("sectoral_signals", {}).get("bank_nifty_pct")
    bank_str = f"{bank_pct:+.2f}%" if bank_pct is not None else "0.00%"

    it_pct = market_signals.get("sectoral_signals", {}).get("it_nifty_pct")
    it_str = f"{it_pct:+.2f}%" if it_pct is not None else "0.00%"

    # Live Heavyweights (~39% NIFTY impact)
    hw_lines = []
    if heavyweights:
        for sym, d in heavyweights.items():
            if isinstance(d, dict) and "name" in d:
                hw_lines.append(f"  • {d['name']} ({d.get('weight', 0)}% weight): ₹{d.get('price', 0)} ({d.get('change_pct', 0):+.2f}%)")
    hw_text = "\n".join(hw_lines) if hw_lines else "  • Heavyweights live feed loading..."

    # FII/DII Institutional Flow
    if fii_dii_data and isinstance(fii_dii_data, dict):
        fii_net = fii_dii_data.get("fii_net_crores", 0)
        dii_net = fii_dii_data.get("dii_net_crores", 0)
        inst_sent = fii_dii_data.get("institutional_sentiment", "NEUTRAL")
        fii_text = f"  • FII: ₹{fii_net:+.0f} Cr | DII: ₹{dii_net:+.0f} Cr | Net: ₹{fii_net + dii_net:+.0f} Cr ({inst_sent})"
    else:
        fii_text = "  • FII/DII data unavailable."

    return f"""
    NIFTY 50 Multi-Source Input Data:

    📰 Scraped News Articles ({len(compact_news)} items):
{json.dumps(compact_news, indent=2)}

    📊 Live Market Microstructure Signals:
    - {spot_line}
    - GIFT Nifty Overnight Change: {gift_str}
    - India VIX: {vix_str}
    - Put-Call Ratio (PCR): {pcr_str} (>1.25 Bullish, <0.80 Bearish)
    - {oi_line}
    - Bank Nifty: {bank_str}
    - IT Nifty: {it_str}
    - Global Market Cues: {json.dumps(market_signals.get('global_market_changes', {}))}

    🏛️ Institutional Cash Flows (FII / DII):
{fii_text}

    🏢 Top 5 NIFTY Heavyweights (~39% Index Impact):
{hw_text}

    📅 F&O Expiry Context: {fo_context}

    Evaluate across all 6 specialist dimensions and produce the BTST prediction JSON.
    """


# Weights for each BTST specialist dimension
_BTST_WEIGHTS = {
    "macro_global": 0.25,
    "fii_dii": 0.20,
    "heavyweights": 0.20,
    "oi_pcr": 0.15,
    "news_catalyst": 0.10,
    "vix_regime": 0.10,
}


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





class GeminiQuotaError(Exception):
    """Raised when Gemini API quota or rate limit (429) is hit."""
    def __init__(self, message: str, retry_after: str = "60s"):
        super().__init__(message)
        self.retry_after = retry_after


def extract_gemini_retry_delay(res_data: dict, headers: dict) -> str:
    """Extract or calculate the exact refresh duration for Gemini quota."""
    # 1. HTTP header Retry-After
    if "Retry-After" in headers:
        return f"{headers['Retry-After']} seconds"

    # 2. Check JSON details
    if isinstance(res_data, dict):
        error = res_data.get("error", {})
        details = error.get("details", [])
        for d in details:
            if isinstance(d, dict) and "retryDelay" in d:
                return str(d["retryDelay"])
        
        # Check message content
        msg = error.get("message", "")
        if "check your plan" in msg or "quota" in msg.lower():
            if "free_tier" in msg.lower() or "minute" in msg.lower():
                return "60 seconds (per-minute RPM refresh)"
            return "60 seconds (free tier rate window)"

    return "60 seconds"


def analyze_with_gemini(
    news_items: list[dict],
    market_signals: dict,
    api_key: str,
    fii_dii_data: dict | None = None,
    heavyweights: dict | None = None,
) -> dict[str, Any]:
    """
    Analyze market data strictly using Google Gemini AI Agent.
    If quota is reached (429), raises GeminiQuotaError with exact refresh time.
    """
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set.")

    user_content = _build_user_content(news_items, market_signals, fii_dii_data, heavyweights)

    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": SYSTEM_PROMPT + "\n\n" + user_content}]}
        ],
        "generationConfig": {"response_mime_type": "application/json"}
    }

    last_error = None
    last_status = None
    retry_delay = "60s"

    # Try gemini-2.5-flash and gemini-flash-latest
    for model in ["gemini-2.5-flash", "gemini-flash-latest"]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=12)
            last_status = response.status_code

            if response.status_code == 200:
                result_text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
                logger.info(f"Successfully received Gemini AI Agent analysis response using '{model}'!")
                res_json = json.loads(result_text)
                res_json = _resolve_btst_conflict(res_json, market_signals, heavyweights, fii_dii_data)
                res_json["ai_agent_provider"] = f"Google Gemini ({model}) — 6-Agent Swarm"
                return res_json

            elif response.status_code == 429:
                err_json = {}
                try:
                    err_json = response.json()
                except Exception:
                    pass
                retry_delay = extract_gemini_retry_delay(err_json, response.headers)
                logger.warning(f"Gemini API ({model}) returned 429 Quota Exceeded. Retry delay: {retry_delay}")
                last_error = f"Gemini API quota exceeded. Please try again in {retry_delay} when your quota refreshes."
            else:
                logger.warning(f"Gemini API ('{model}') returned status {response.status_code}: {response.text[:150]}")
                last_error = f"Gemini API returned status {response.status_code}."
        except requests.exceptions.Timeout:
            last_error = "Gemini API request timed out. Please try again in a few moments."
        except Exception as model_err:
            last_error = str(model_err)

    if last_status == 429:
        raise GeminiQuotaError(last_error or f"Gemini API quota reached. Please try again in {retry_delay}.", retry_delay)

    raise RuntimeError(last_error or "Gemini AI Agent analysis failed.")


def analyze_with_grok(
    news_items: list[dict],
    market_signals: dict,
    api_key: str,
    fii_dii_data: dict | None = None,
    heavyweights: dict | None = None,
) -> dict[str, Any] | None:
    """Analyze market data using xAI Grok API."""
    try:
        url = "https://api.x.ai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        user_content = _build_user_content(news_items, market_signals, fii_dii_data, heavyweights)

        for model in ["grok-2-1212", "grok-2", "grok-beta"]:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content}
                ],
                "temperature": 0.2,
                "response_format": {"type": "json_object"}
            }

            response = requests.post(url, headers=headers, json=payload, timeout=25)
            if response.status_code == 200:
                result_text = response.json()["choices"][0]["message"]["content"]
                logger.info(f"Successfully received Grok AI Agent analysis using model '{model}'!")
                res_json = json.loads(result_text)
                res_json = _resolve_btst_conflict(res_json, market_signals, heavyweights, fii_dii_data)
                res_json["ai_agent_provider"] = f"xAI Grok ({model}) — 6-Agent Swarm"
                return res_json
            elif response.status_code == 403:
                logger.warning("xAI Grok API returned 403: Account lacks API credits on console.x.ai.")
                return None
            else:
                logger.warning(f"Grok API ('{model}') returned status {response.status_code}: {response.text[:150]}")
    except Exception as e:
        logger.error(f"Error in Grok AI Agent analysis: {e}")
    return None


def analyze_with_groq(
    news_items: list[dict],
    market_signals: dict,
    api_key: str,
    fii_dii_data: dict | None = None,
    heavyweights: dict | None = None,
) -> dict[str, Any] | None:
    """Analyze market data using Groq Cloud API (gpt-oss-120b, gpt-oss-20b, qwen3.6-27b). Ultra-fast ~1s."""
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        user_content = _build_user_content(news_items, market_signals, fii_dii_data, heavyweights)

        for model in ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b", "groq/compound"]:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content}
                ],
                "temperature": 0.2,
                "response_format": {"type": "json_object"}
            }

            try:
                response = requests.post(url, headers=headers, json=payload, timeout=8)
                if response.status_code == 200:
                    result_text = response.json()["choices"][0]["message"]["content"]
                    logger.info(f"Successfully received Groq AI Agent ({model}) analysis response!")
                    res_json = json.loads(result_text)
                    res_json = _resolve_btst_conflict(res_json, market_signals, heavyweights, fii_dii_data)
                    res_json["ai_agent_provider"] = f"Groq ({model}) — 6-Agent Swarm"
                    return res_json
                else:
                    logger.warning(f"Groq API ('{model}') returned status {response.status_code}: {response.text[:120]}")
            except Exception as m_err:
                logger.warning(f"Groq model {model} error: {m_err}")
    except Exception as e:
        logger.error(f"Error in Groq AI Agent analysis: {e}")
    return None


def analyze_with_openai(
    news_items: list[dict],
    market_signals: dict,
    api_key: str,
    fii_dii_data: dict | None = None,
    heavyweights: dict | None = None,
) -> dict[str, Any] | None:
    """Analyze market data using OpenAI API (GPT-4o-mini)."""
    try:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        user_content = _build_user_content(news_items, market_signals, fii_dii_data, heavyweights)

        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"}
        }

        response = requests.post(url, headers=headers, json=payload, timeout=8)
        if response.status_code == 200:
            result_text = response.json()["choices"][0]["message"]["content"]
            logger.info("Successfully received OpenAI GPT-4o-mini analysis response!")
            res_json = json.loads(result_text)
            res_json = _resolve_btst_conflict(res_json, market_signals, heavyweights, fii_dii_data)
            res_json["ai_agent_provider"] = "OpenAI (GPT-4o-mini) — 6-Agent Swarm"
            return res_json
    except Exception as e:
        logger.error(f"Error in OpenAI analysis: {e}")
    return None


def analyze_with_ai_agents(
    news_items: list[dict],
    market_signals: dict,
    fii_dii_data: dict | None = None,
    heavyweights: dict | None = None,
) -> dict[str, Any]:
    """
    6-Agent BTST Execution Engine:
    1. Primary: Groq Cloud (Ultra-Fast ~1s, Free, No Quota Blocks)
    2. Secondary: Google Gemini (gemini-2.5-flash)
    """
    groq_key = os.environ.get("GROQ_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")

    if groq_key:
        logger.info("Running 6-Agent BTST Analysis via Groq Cloud...")
        res = analyze_with_groq(news_items, market_signals, groq_key, fii_dii_data, heavyweights)
        if res:
            return res

    if gemini_key:
        logger.info("Running 6-Agent BTST Analysis via Google Gemini API...")
        return analyze_with_gemini(news_items, market_signals, gemini_key, fii_dii_data, heavyweights)

    raise ValueError("Neither GROQ_API_KEY nor GEMINI_API_KEY is configured in environment variables. Please add GROQ_API_KEY in Render Settings.")



if __name__ == "__main__":
    sample_news = [{"headline": "HDFC Bank Q1 profit surges 25% beating estimates", "sector": "Banking & Finance"}]
    sample_signals = {"india_vix": 11.3, "pcr": 1.05, "gift_nifty_change_pct": 0.4}
    try:
        output = analyze_with_ai_agents(sample_news, sample_signals)
        print("AI Agent Output:", output)
    except Exception as e:
        print("AI Agent Error:", e)
