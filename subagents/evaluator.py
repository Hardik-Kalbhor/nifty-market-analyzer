"""
subagents/evaluator.py — Concurrent evaluation and prompt formatting for dynamic subagents.
"""

import concurrent.futures
import json
import logging
import requests
from typing import Any

from .constants import (
    _GROQ_URL, _GEMINI_URL, _GEMINI_MODELS, _GROQ_MODELS, SPECIALIST_SPECS
)
from .matcher import _clean_numeric
from .fallback import _generate_fallback_verdict

logger = logging.getLogger("DynamicSubagents")

def evaluate_single_specialist(
    specialist_name: str,
    market_signals: dict[str, Any],
    news_items: list[dict[str, Any]],
    stage1_result: dict[str, Any],
    gemini_key: str = "",
    groq_key: str = "",
) -> dict[str, Any]:
    """Execute evaluation for one specialist subagent."""
    spec = SPECIALIST_SPECS.get(specialist_name)
    if not spec:
        return _generate_fallback_verdict(specialist_name, market_signals, stage1_result)

    sys_prompt = spec["system_prompt"]
    human_prompt = (
        f"Stage 1 Proposed Trade: {stage1_result.get('prediction', 'FLAT')} / {stage1_result.get('btst_bias', 'NO TRADE')}\n"
        f"Confidence: {stage1_result.get('confidence', 50)}%\n"
        f"Market Signals: Spot={market_signals.get('nifty_spot')}, GIFT={market_signals.get('gift_nifty_change_pct')}%, "
        f"VIX={market_signals.get('india_vix')}, FII Net=₹{market_signals.get('fii_net')} Cr\n"
        f"Top News: {'; '.join([n.get('title') or n.get('headline') or '' for n in news_items[:5] if isinstance(n, dict)])}\n\n"
        "Provide your specialist risk verdict and rationale."
    )

    # 1. Try Gemini Flash
    if gemini_key:
        for model in _GEMINI_MODELS:
            url = _GEMINI_URL.format(model=model, key=gemini_key)
            payload = {
                "contents": [{"role": "user", "parts": [{"text": sys_prompt + "\n\n" + human_prompt}]}],
                "generationConfig": {"maxOutputTokens": 250, "temperature": 0.2},
            }
            try:
                r = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=6.0)
                if r.status_code == 200:
                    raw_text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                    m = re.search(r"\{.*\}", raw_text, re.DOTALL)
                    if m:
                        parsed = json.loads(m.group(0))
                        if isinstance(parsed, dict) and parsed.get("verdict") in {
                            "FULL_BTST", "HALF_QUANTITY", "HEDGED_SPREAD", "STRICT_NO_TRADE"
                        }:
                            parsed["subagent"] = specialist_name
                            parsed["confidence"] = int(_clean_numeric(parsed.get("confidence"), 70))
                            return parsed
            except Exception as e:
                logger.debug(f"Specialist {specialist_name} Gemini {model} error: {e}")

    # 2. Try Groq if Gemini unavailable
    if groq_key:
        for model in _GROQ_MODELS:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": human_prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 250,
            }
            try:
                r = requests.post(
                    _GROQ_URL,
                    headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=5.0,
                )
                if r.status_code == 200:
                    raw_text = r.json()["choices"][0]["message"]["content"].strip()
                    m = re.search(r"\{.*\}", raw_text, re.DOTALL)
                    if m:
                        parsed = json.loads(m.group(0))
                        if isinstance(parsed, dict) and parsed.get("verdict") in {
                            "FULL_BTST", "HALF_QUANTITY", "HEDGED_SPREAD", "STRICT_NO_TRADE"
                        }:
                            parsed["subagent"] = specialist_name
                            parsed["confidence"] = int(_clean_numeric(parsed.get("confidence"), 70))
                            return parsed
            except Exception as e:
                logger.debug(f"Specialist {specialist_name} Groq {model} error: {e}")

    # 3. Fallback to deterministic domain rule
    return _generate_fallback_verdict(specialist_name, market_signals, stage1_result)


def evaluate_dynamic_subagents(
    matched_names: list[str],
    market_signals: dict[str, Any] | None = None,
    news_items: list[dict[str, Any]] | None = None,
    stage1_result: dict[str, Any] | None = None,
    gemini_key: str = "",
    groq_key: str = "",
) -> list[dict[str, Any]]:
    """
    Execute all matched specialist subagents concurrently via ThreadPoolExecutor.
    """
    if not matched_names:
        return []

    signals = market_signals if isinstance(market_signals, dict) else {}
    news = news_items if isinstance(news_items, list) else []
    stage1 = stage1_result if isinstance(stage1_result, dict) else {}

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(matched_names))) as executor:
        future_to_name = {
            executor.submit(
                evaluate_single_specialist,
                name,
                signals,
                news,
                stage1,
                gemini_key,
                groq_key,
            ): name
            for name in matched_names
        }

        done, _ = concurrent.futures.wait(list(future_to_name.keys()), timeout=8.0)
        for fut in done:
            try:
                res = fut.result()
                if res:
                    results.append(res)
            except Exception as e:
                name = future_to_name[fut]
                logger.warning(f"Specialist {name} execution failed: {e}")
                results.append(_generate_fallback_verdict(name, market_signals, stage1_result))

    return results


def format_specialists_prompt(specialist_verdicts: list[dict[str, Any]]) -> str:
    """
    Format dynamic specialist subagent assessments for injection into the Judge prompt.
    """
    if not specialist_verdicts:
        return ""

    lines = ["🎯 DYNAMIC CATALYST SPECIALISTS (Domain Subagents):"]
    for sv in specialist_verdicts:
        name = sv.get("subagent", "Specialist")
        verdict = sv.get("verdict", "HALF_QUANTITY")
        conf = sv.get("confidence", 70)
        rationale = sv.get("specialist_rationale", "")
        lines.append(f"  • [{name}] Recommends: {verdict} ({conf}% confidence)")
        if rationale:
            lines.append(f"    Domain Insight: {rationale}")

    lines.append("  → Instruction: Weigh these specialized catalyst assessments alongside the 3 debate personas.")
    return "\n".join(lines)
