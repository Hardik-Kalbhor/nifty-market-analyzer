"""
llm/providers.py — LLM API integrations (Gemini, Grok, Groq, OpenAI).
"""

import os
import json
import logging
import requests
from typing import Any, Optional

from .constants import SYSTEM_PROMPT, GeminiQuotaError, extract_gemini_retry_delay
from .context import _build_user_content
from .resolution import _resolve_btst_conflict

logger = logging.getLogger(__name__)

def analyze_with_gemini(
    news_items: list[dict],
    market_signals: dict,
    api_key: str,
    fii_dii_data: dict | None = None,
    heavyweights: dict | None = None,
    past_context: str = "",
) -> dict[str, Any]:
    """
    Analyze market data strictly using Google Gemini AI Agent.
    If quota is reached (429), raises GeminiQuotaError with exact refresh time.
    past_context: Phase D memory lessons injected into the prompt.
    """
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set.")

    user_content = _build_user_content(news_items, market_signals, fii_dii_data, heavyweights, past_context)

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
    past_context: str = "",
) -> dict[str, Any] | None:
    """Analyze market data using xAI Grok API.
    past_context: Phase D memory lessons injected into the prompt.
    """
    try:
        url = "https://api.x.ai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        user_content = _build_user_content(news_items, market_signals, fii_dii_data, heavyweights, past_context)

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
    past_context: str = "",
) -> dict[str, Any] | None:
    """Analyze market data using Groq Cloud API (gpt-oss-120b, gpt-oss-20b, qwen3.6-27b). Ultra-fast ~1s.
    past_context: Phase D memory lessons injected into the prompt.
    """
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        user_content = _build_user_content(news_items, market_signals, fii_dii_data, heavyweights, past_context)

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
    past_context: str = "",
) -> dict[str, Any] | None:
    """Analyze market data using OpenAI API (GPT-4o-mini).
    past_context: Phase D memory lessons injected into the prompt.
    """
    try:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        user_content = _build_user_content(news_items, market_signals, fii_dii_data, heavyweights, past_context)

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


