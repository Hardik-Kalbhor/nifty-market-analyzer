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


def analyze_with_gemini(news_items: list[dict], market_signals: dict, api_key: str) -> dict[str, Any] | None:
    """Analyze market data using Google Gemini API (gemini-2.5-flash)."""
    try:
        # Take top 10 news items for compact fast processing
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
        
        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": SYSTEM_PROMPT + "\n\n" + user_content}]}
            ],
            "generationConfig": {"response_mime_type": "application/json"}
        }

        # Try gemini-2.5-flash first, fallback to gemini-flash-latest
        for model in ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.5-pro"]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            headers = {"Content-Type": "application/json"}
            
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                result_text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
                logger.info(f"Successfully received Gemini AI Agent analysis response using '{model}'!")
                return json.loads(result_text)
            else:
                logger.warning(f"Gemini API ('{model}') returned status {response.status_code}: {response.text[:150]}")
    except Exception as e:
        logger.error(f"Error in Gemini AI Agent analysis: {e}")
    return None


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


def analyze_with_ai_agents(news_items: list[dict], market_signals: dict) -> dict[str, Any] | None:
    """
    Master function: Checks for GEMINI_API_KEY or GROK_API_KEY in environment variables.
    Tries Gemini first, then Grok, returning None if neither key is configured or both fail.
    """
    gemini_key = os.environ.get("GEMINI_API_KEY")
    grok_key = os.environ.get("GROK_API_KEY") or os.environ.get("XAI_API_KEY")

    if gemini_key:
        logger.info("Running AI Agent Analysis via Gemini API...")
        res = analyze_with_gemini(news_items, market_signals, gemini_key)
        if res:
            res["ai_agent_provider"] = "Google Gemini"
            return res

    if grok_key:
        logger.info("Running AI Agent Analysis via Grok API...")
        res = analyze_with_grok(news_items, market_signals, grok_key)
        if res:
            res["ai_agent_provider"] = "xAI Grok"
            return res

    logger.info("No active AI Agent response (GEMINI_API_KEY / GROK_API_KEY). Using enhanced rule-based NLP + signals.")
    return None


if __name__ == "__main__":
    # Test script fallback behavior
    sample_news = [{"headline": "HDFC Bank Q1 profit surges 25% beating estimates", "sector": "Banking & Finance"}]
    sample_signals = {"india_vix": 11.3, "pcr": 1.05, "gift_nifty_change_pct": 0.4}
    output = analyze_with_ai_agents(sample_news, sample_signals)
    print("AI Agent Output:", output)
