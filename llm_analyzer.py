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
You are an expert NIFTY 50 Stock Market Analyst & Risk Manager acting as a Multi-Agent Intelligence System.
Your job is to analyze market news, FII/DII institutional flows, India VIX, and global market signals to predict:
1. Next-Day Opening Gap: GAP UP, GAP DOWN, or FLAT
2. Confidence Score (10% to 92%)
3. BTST Trading Bias: BUY CE, BUY PE, or NO TRADE

CRITICAL EVALUATION RULES:
1. Context & Trade-offs: Evaluate full sentence context (e.g. margin compression vs loan growth).
2. Negations: Detect negations (e.g. "unlikely to cut", "out of the question").
3. NIFTY Stock Weightage: News on heavyweights (HDFC Bank 11.5%, Reliance 9.2%, ICICI 8.1%, Infosys 5.8%, TCS 4.2%) has massive impact. Small-cap news has ZERO Nifty index impact.
4. Numerical Scale: Differentiate between a 2% minor profit move vs a 350% explosive profit beat.
5. Signal Confluence: If signals conflict (e.g. Bearish news vs Bullish FII buying), force NO TRADE.

Return ONLY a valid JSON object in this exact schema:
{
  "prediction": "GAP UP" | "GAP DOWN" | "FLAT",
  "confidence": number (10-92),
  "btst_bias": "BUY CE" | "BUY PE" | "NO TRADE",
  "news_sentiment": "BULLISH" | "BEARISH" | "MIXED",
  "bullish_factors": ["list of bullish drivers sorted in STRICT DESCENDING ORDER of NIFTY impact (highest impact first)"],
  "bearish_factors": ["list of bearish drivers sorted in STRICT DESCENDING ORDER of NIFTY impact (highest impact first)"],
  "nifty_heavyweight_impact": "string summary of impact from top Nifty stocks",
  "reasoning": "brief 2-sentence explanation of the prediction"
}
"""


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


def analyze_with_gemini(news_items: list[dict], market_signals: dict, api_key: str) -> dict[str, Any]:
    """
    Analyze market data strictly using Google Gemini AI Agent.
    If quota is reached (429), raises GeminiQuotaError with exact refresh time.
    """
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set.")

    # Take top 12 news items for compact deep reasoning
    compact_news = [
        {"headline": item.get("headline"), "sector": item.get("sector"), "category": item.get("category")}
        for item in news_items[:12]
    ]
    user_content = f"""
    NIFTY 50 Market Input Data:
    - Scraped News Articles ({len(compact_news)} items): {json.dumps(compact_news, indent=2)}
    - Market Microstructure Signals: {json.dumps(market_signals, indent=2)}
    
    Analyze this data and produce the prediction JSON.
    """
    
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
                res_json["ai_agent_provider"] = f"Google Gemini ({model})"
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


def analyze_with_grok(news_items: list[dict], market_signals: dict, api_key: str) -> dict[str, Any] | None:
    """Analyze market data using xAI Grok API."""
    try:
        url = "https://api.x.ai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        compact_news = [
            {"headline": item.get("headline"), "sector": item.get("sector"), "category": item.get("category")}
            for item in news_items[:10]
        ]
        user_content = f"""
        NIFTY 50 Market Input Data:
        - Scraped News Articles ({len(compact_news)} items): {json.dumps(compact_news, indent=2)}
        - Market Microstructure Signals: {json.dumps(market_signals, indent=2)}
        
        Analyze this data and produce the prediction JSON.
        """

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
                return json.loads(result_text)
            elif response.status_code == 403:
                logger.warning("xAI Grok API returned 403: Account lacks API credits on console.x.ai. Falling back to rule-based engine.")
                return None
            else:
                logger.warning(f"Grok API ('{model}') returned status {response.status_code}: {response.text[:150]}")
    except Exception as e:
        logger.error(f"Error in Grok AI Agent analysis: {e}")
    return None


def analyze_with_groq(news_items: list[dict], market_signals: dict, api_key: str) -> dict[str, Any] | None:
    """Analyze market data using Groq Cloud API (Llama 3.3 70B / Llama 3.1 8B). 100% Free & Ultra-Fast."""
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        compact_news = [
            {"headline": item.get("headline"), "sector": item.get("sector"), "category": item.get("category")}
            for item in news_items[:12]
        ]
        user_content = f"""
        NIFTY 50 Market Input Data:
        - Scraped News Articles ({len(compact_news)} items): {json.dumps(compact_news, indent=2)}
        - Market Microstructure Signals: {json.dumps(market_signals, indent=2)}
        
        Analyze this data and produce the prediction JSON.
        """

        for model in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]:
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
                    res_json["ai_agent_provider"] = f"Groq ({model})"
                    return res_json
                else:
                    logger.warning(f"Groq API ('{model}') returned status {response.status_code}: {response.text[:120]}")
            except Exception as m_err:
                logger.warning(f"Groq model {model} error: {m_err}")
    except Exception as e:
        logger.error(f"Error in Groq AI Agent analysis: {e}")
    return None


def analyze_with_openai(news_items: list[dict], market_signals: dict, api_key: str) -> dict[str, Any] | None:
    """Analyze market data using OpenAI API (GPT-4o-mini)."""
    try:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        compact_news = [
            {"headline": item.get("headline"), "sector": item.get("sector"), "category": item.get("category")}
            for item in news_items[:12]
        ]
        user_content = f"""
        NIFTY 50 Market Input Data:
        - Scraped News Articles ({len(compact_news)} items): {json.dumps(compact_news, indent=2)}
        - Market Microstructure Signals: {json.dumps(market_signals, indent=2)}
        
        Analyze this data and produce the prediction JSON.
        """

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
            res_json["ai_agent_provider"] = "OpenAI (GPT-4o-mini)"
            return res_json
    except Exception as e:
        logger.error(f"Error in OpenAI analysis: {e}")
    return None


def analyze_with_ai_agents(news_items: list[dict], market_signals: dict) -> dict[str, Any]:
    """
    Direct Google Gemini AI Agent Execution:
    Strictly runs Google Gemini API. If quota is exceeded (429), raises GeminiQuotaError
    with exact time required for the quota to refresh.
    """
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        raise ValueError("GEMINI_API_KEY is not configured in Render environment variables. Please add your Gemini API key in Settings.")

    logger.info("Running AI Agent Analysis strictly via Google Gemini API...")
    return analyze_with_gemini(news_items, market_signals, gemini_key)


if __name__ == "__main__":
    sample_news = [{"headline": "HDFC Bank Q1 profit surges 25% beating estimates", "sector": "Banking & Finance"}]
    sample_signals = {"india_vix": 11.3, "pcr": 1.05, "gift_nifty_change_pct": 0.4}
    try:
        output = analyze_with_ai_agents(sample_news, sample_signals)
        print("Gemini Output:", output)
    except Exception as e:
        print("Gemini Error:", e)
