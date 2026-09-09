"""
memory/market_helpers.py — Gap classification, trading calendar calculation, and reflection LLM callers.
"""

from __future__ import annotations
import os
import json
import logging
import requests
from datetime import datetime, timedelta
from typing import Any, Callable

import yf_cache
from .constants import (
    GAP_UP_THRESHOLD,
    GAP_DOWN_THRESHOLD,
    _REFLECTION_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers (module-level, no class dependency)
# ─────────────────────────────────────────────────────────────────────────────

def _classify_gap(gap_pct: float) -> str:
    """Classify a gap percentage into GAP UP / GAP DOWN / FLAT."""
    if gap_pct >= GAP_UP_THRESHOLD:
        return "GAP UP"
    if gap_pct <= GAP_DOWN_THRESHOLD:
        return "GAP DOWN"
    return "FLAT"


def _next_trading_day(from_date) -> object:
    """Return the next weekday (Mon–Fri) after from_date. Simple approximation — ignores NSE holidays."""
    next_day = from_date + timedelta(days=1)
    while next_day.weekday() >= 5:  # 5=Sat, 6=Sun
        next_day += timedelta(days=1)
    return next_day


def _fetch_nifty_actual_gap(trade_date: str, resolution_date: str) -> tuple[float | None, float | None, float | None]:
    """
    Fetch actual Nifty 50 opening price for resolution_date using yf_cache.
    Returns (gap_pct, actual_open, prev_close) or (None, None, None) on failure.

    Uses yf_cache.fetch_daily_bars() which handles retries, 429 back-off, host
    rotation, and 24-hour disk caching so reruns are instant.
    """
    from_ts = int((datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=5)).timestamp())
    to_ts   = int((datetime.strptime(resolution_date, "%Y-%m-%d") + timedelta(days=2)).timestamp())

    bars = yf_cache.fetch_daily_bars("^NSEI", period1_ts=from_ts, period2_ts=to_ts, timeout=8.0)
    if not bars or len(bars) < 2:
        logger.warning(f"Memory: No sufficient bars returned for ^NSEI around {resolution_date}")
        return None, None, None

    # Find the resolution date's bar (or nearest trading day on/after it)
    from datetime import date as _date
    res_date = datetime.strptime(resolution_date, "%Y-%m-%d").date()
    bar_dates = [datetime.strptime(b["date"], "%Y-%m-%d").date() for b in bars]

    # Find index of resolution date or the nearest future trading day
    idx = None
    for i, d in enumerate(bar_dates):
        if d >= res_date:
            idx = i
            break

    if idx is None or idx == 0:
        logger.warning(f"Memory: Could not find a usable bar on/after {resolution_date}")
        return None, None, None

    actual_open = bars[idx].get("open")
    prev_close  = bars[idx - 1].get("close")

    if actual_open is None or prev_close is None or prev_close == 0:
        logger.warning(f"Memory: Missing open/close values for {resolution_date}")
        return None, None, None

    gap_pct = ((actual_open - prev_close) / prev_close) * 100
    return round(gap_pct, 3), round(actual_open, 2), round(prev_close, 2)



def build_reflect_fn_from_env() -> Callable[[str, str], str] | None:
    """
    Build a simple reflect function that calls Groq or Gemini (whichever key is set).
    Returns None if neither key is available.
    """
    groq_key = os.environ.get("GROQ_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")

    if groq_key:
        def reflect_via_groq(system_prompt: str, human_prompt: str) -> str:
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json",
            }
            for model in ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.6-27b"]:
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": human_prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 200,
                }
                try:
                    r = requests.post(url, headers=headers, json=payload, timeout=10)
                    if r.status_code == 200:
                        return r.json()["choices"][0]["message"]["content"].strip()
                except Exception as e:
                    logger.warning(f"Groq reflection call failed ({model}): {e}")
            raise RuntimeError("All Groq models failed for reflection")

        return reflect_via_groq

    if gemini_key:
        def reflect_via_gemini(system_prompt: str, human_prompt: str) -> str:
            for model in ["gemini-2.5-flash", "gemini-flash-latest"]:
                url = (
                    f"https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{model}:generateContent?key={gemini_key}"
                )
                payload = {
                    "contents": [
                        {"role": "user", "parts": [{"text": system_prompt + "\n\n" + human_prompt}]}
                    ],
                    "generationConfig": {"maxOutputTokens": 200, "temperature": 0.3},
                }
                try:
                    r = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=12)
                    if r.status_code == 200:
                        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                except Exception as e:
                    logger.warning(f"Gemini reflection call failed ({model}): {e}")
            raise RuntimeError("All Gemini models failed for reflection")

        return reflect_via_gemini

    return None


