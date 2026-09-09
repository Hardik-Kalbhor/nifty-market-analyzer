"""
debate/api.py — LLM API callers and Judge synthesis.
"""

import json
import logging
import time
import requests
from typing import Any

from .constants import (
    _GROQ_URL, _GEMINI_URL, _GROQ_MODELS, _GEMINI_MODELS,
    TRADE_STRUCTURES, _JUDGE_SYSTEM, _get_engine_fn,
)
from .context import _format_retail_score

logger = logging.getLogger(__name__)

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


def _run_persona(persona_name: str, system_prompt: str, context: str, groq_key: str = "", gemini_key: str = "") -> dict:
    """Run a single persona agent and return its verdict dict (with fallback)."""
    t0 = time.time()
    result = None
    call_groq = _get_engine_fn("_groq_call", _groq_call)
    call_gemini = _get_engine_fn("_gemini_call", _gemini_call)
    if groq_key:
        result = call_groq(system_prompt, context, groq_key)
    if not result and gemini_key:
        result = call_gemini(system_prompt, context, gemini_key)
    elapsed = round(time.time() - t0, 2)

    if result and isinstance(result, dict) and result.get("verdict") in TRADE_STRUCTURES:
        logger.info(f"[Debate] {persona_name}: {result.get('verdict')} "
                    f"(conf={result.get('confidence')}%) in {elapsed}s")
        return result

    # Fallback verdict if LLM fails or returns invalid structure
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
    specialist_verdicts: list[dict] | None = None,
) -> dict | None:
    """Run the Gemini synthesis judge. Returns judge output dict or None."""
    cogni_calib = ""
    try:
        from cognigraph import get_cognigraph
        cg = get_cognigraph()
        cogni_calib = cg.get_judge_calibration(market_signals, stage1_result)
    except Exception as cg_err:
        logger.debug(f"[Debate] CogniGraph judge calibration skipped: {cg_err}")

    fts_analogs_str = ""
    try:
        from memory_fts import get_memory_fts
        fts = get_memory_fts()
        analogs = fts.find_analogs(signals=market_signals, stage1_result=stage1_result, limit=2)
        if analogs:
            fts_analogs_str = fts.format_analogs_prompt(analogs)
    except Exception as fts_err:
        logger.debug(f"[Debate] FTS judge analogs skipped: {fts_err}")

    skills_prompt_str = ""
    try:
        from skills_engine import get_skills_engine
        se = get_skills_engine()
        matched_skills = se.match_skills(signals=market_signals, stage1_result=stage1_result)
        if matched_skills:
            skills_prompt_str = se.format_skills_prompt(matched_skills)
    except Exception as se_err:
        logger.debug(f"[Debate] Skills matching skipped: {se_err}")

    specialists_prompt_str = ""
    if specialist_verdicts:
        try:
            from dynamic_subagents import format_specialists_prompt
            specialists_prompt_str = format_specialists_prompt(specialist_verdicts)
        except Exception as d_err:
            logger.debug(f"[Debate] Dynamic subagents prompt format error: {d_err}")

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

{cogni_calib}

{fts_analogs_str}

{skills_prompt_str}

{specialists_prompt_str}

Synthesise the 3 debate committee verdicts and dynamic specialist assessments into a final calibrated trade structure."""

    t0 = time.time()
    call_gemini = _get_engine_fn("_gemini_call", _gemini_call)
    result = call_gemini(_JUDGE_SYSTEM, judge_context, gemini_key)
    elapsed = round(time.time() - t0, 2)

    if result and isinstance(result, dict) and result.get("btst_structure") in TRADE_STRUCTURES:
        logger.info(f"[Debate] Judge: {result.get('btst_structure')} "
                    f"({result.get('debate_consensus')}) in {elapsed}s")
        return result

    logger.warning(f"[Debate] Judge failed or returned invalid response — skipping synthesis")
    return None


