"""
dynamic_subagents.py — Dynamic Subagent Spawning & Specialist Delegation Engine.

Adapted from Nous Research Hermes Agent dynamic task delegation architecture:
Dynamically spawns domain-specialist subagents based on real-time market catalysts:
  1. RBI_Policy_Quant              (Rate decisions, repo rate, banking margins, post-event IV crush)
  2. Geopolitical_Crude_Analyst    (Crude oil shocks, OPEC, war escalation, OMC margin compression)
  3. Options_Greeks_ZeroDTE_Quant  (0/1 DTE expiry day pinning, Max Pain gravity, gamma explosions)
  4. Heavyweight_Earnings_Specialist (Results announcements, quarterly earnings, index veto)
  5. FII_OrderFlow_Tracer          (Extreme institutional cash buying/dumping, block absorption)
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import re
from typing import Any, Callable

import requests

logger = logging.getLogger("DynamicSubagents")

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
_GEMINI_MODELS = ["gemini-2.5-flash", "gemini-flash-latest"]
_GROQ_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b"]


# ─────────────────────────────────────────────────────────────────────────────
# Specialist Definitions & System Prompts
# ─────────────────────────────────────────────────────────────────────────────

SPECIALIST_SPECS = {
    "RBI_Policy_Quant": {
        "domain": "Monetary Policy & Banking Valuation",
        "system_prompt": (
            "You are the RBI Policy & Banking Quant on the NIFTY Risk Committee.\n"
            "Your domain: Evaluate repo rate decisions, MPC monetary stance, bond yields, "
            "and BankNifty impact on NIFTY 50. Highlight post-policy IV collapse and rate sensitivity.\n"
            "Output ONLY valid JSON:\n"
            "{\n"
            "  \"subagent\": \"RBI_Policy_Quant\",\n"
            "  \"verdict\": \"FULL_BTST\" | \"HALF_QUANTITY\" | \"HEDGED_SPREAD\" | \"STRICT_NO_TRADE\",\n"
            "  \"confidence\": <int 50-95>,\n"
            "  \"specialist_rationale\": \"<2-3 sentences on policy rate expectations, banking sector sensitivity, and IV risk>\"\n"
            "}"
        ),
        "triggers": {
            "news_keywords": ["rbi", "mpc", "repo rate", "monetary policy", "interest rate", "shaktikanta", "governor", "rate cut", "rate hike", "crr", "sfr"],
        },
    },
    "Geopolitical_Crude_Analyst": {
        "domain": "Crude Oil & Geopolitical Macro Risk",
        "system_prompt": (
            "You are the Geopolitical Macro & Energy Analyst on the NIFTY Risk Committee.\n"
            "Your domain: Model crude oil (Brent/WTI) price spikes, OPEC quota decisions, Middle East tensions, "
            "and rupee depreciation impacts on Indian OMCs (BPCL, IOC), Paints (Asian Paints), and inflation.\n"
            "Output ONLY valid JSON:\n"
            "{\n"
            "  \"subagent\": \"Geopolitical_Crude_Analyst\",\n"
            "  \"verdict\": \"FULL_BTST\" | \"HALF_QUANTITY\" | \"HEDGED_SPREAD\" | \"STRICT_NO_TRADE\",\n"
            "  \"confidence\": <int 50-95>,\n"
            "  \"specialist_rationale\": \"<2-3 sentences on crude price trends, import bill pressure, and gap sustainability>\"\n"
            "}"
        ),
        "triggers": {
            "news_keywords": ["crude", "brent", "oil", "opec", "iran", "hormuz", "middle east", "russia", "israel", "red sea", "tariffs", "sanctions"],
        },
    },
    "Options_Greeks_ZeroDTE_Quant": {
        "domain": "0-DTE Gamma & Expiry Pinning Dynamics",
        "system_prompt": (
            "You are the 0-DTE Options Greeks & Expiry Pinning Quant on the NIFTY Risk Committee.\n"
            "Your domain: Weekly/Monthly expiry market microstructure, gamma explosions, Max Pain gravity, "
            "heavy Call/Put writing strikes, and overnight theta decay on near-expiry options.\n"
            "Output ONLY valid JSON:\n"
            "{\n"
            "  \"subagent\": \"Options_Greeks_ZeroDTE_Quant\",\n"
            "  \"verdict\": \"FULL_BTST\" | \"HALF_QUANTITY\" | \"HEDGED_SPREAD\" | \"STRICT_NO_TRADE\",\n"
            "  \"confidence\": <int 50-95>,\n"
            "  \"specialist_rationale\": \"<2-3 sentences analyzing pinning gravity, strike proximity, and spread hedging necessity>\"\n"
            "}"
        ),
        "triggers": {
            "max_dte": 1,
            "fo_context_contains": ["expiry today", "expiry tomorrow", "0 dte", "1 dte", "next day expiry", "weekly expiry"],
        },
    },
    "Heavyweight_Earnings_Specialist": {
        "domain": "Mega-Cap Heavyweight Earnings & Index Veto",
        "system_prompt": (
            "You are the Heavyweight Earnings & Index Veto Specialist on the NIFTY Risk Committee.\n"
            "Your domain: Analyze earnings results and outsized single-day moves in HDFC Bank, Reliance, TCS, "
            "and ICICI Bank. Assess whether heavyweight divergence vetoes the broader market gap direction.\n"
            "Output ONLY valid JSON:\n"
            "{\n"
            "  \"subagent\": \"Heavyweight_Earnings_Specialist\",\n"
            "  \"verdict\": \"FULL_BTST\" | \"HALF_QUANTITY\" | \"HEDGED_SPREAD\" | \"STRICT_NO_TRADE\",\n"
            "  \"confidence\": <int 50-95>,\n"
            "  \"specialist_rationale\": \"<2-3 sentences on heavyweight earnings/price divergence vetoing or supporting the trade>\"\n"
            "}"
        ),
        "triggers": {
            "news_keywords": ["hdfc bank q", "reliance q", "tcs q", "infosys q", "icici bank q", "quarterly results", "earnings beat", "earnings miss"],
            "heavyweight_abs_change_gt": 0.8,
        },
    },
    "FII_OrderFlow_Tracer": {
        "domain": "Institutional Flow & Liquidity Absorption",
        "system_prompt": (
            "You are the FII / Institutional Order Flow Tracer on the NIFTY Risk Committee.\n"
            "Your domain: Track institutional liquidity sweeps, aggressive FII cash selling/buying (> ₹2,000 Cr), "
            "DII absorption patterns, and foreign portfolio investor positioning into market open.\n"
            "Output ONLY valid JSON:\n"
            "{\n"
            "  \"subagent\": \"FII_OrderFlow_Tracer\",\n"
            "  \"verdict\": \"FULL_BTST\" | \"HALF_QUANTITY\" | \"HEDGED_SPREAD\" | \"STRICT_NO_TRADE\",\n"
            "  \"confidence\": <int 50-95>,\n"
            "  \"specialist_rationale\": \"<2-3 sentences on foreign institutional accumulation/distribution and opening drive follow-through>\"\n"
            "}"
        ),
        "triggers": {
            "fii_net_abs_gt": 1800.0,
        },
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Helper & Matcher
# ─────────────────────────────────────────────────────────────────────────────

def _clean_numeric(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        s = str(val).strip().replace(",", "")
        m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
        return float(m.group(0)) if m else default
    except Exception:
        return default


def match_dynamic_subagents(
    market_signals: dict[str, Any] | None = None,
    news_items: list[dict[str, Any]] | None = None,
    stage1_result: dict[str, Any] | None = None,
    heavyweights: dict[str, Any] | None = None,
    max_specialists: int = 2,
) -> list[str]:
    """
    Evaluate market signals, breaking news, and heavyweight movement to
    determine which specialist subagents should be spawned dynamically.
    Returns list of specialist names (max_specialists).
    """
    signals = market_signals if isinstance(market_signals, dict) else {}
    news = news_items if isinstance(news_items, list) else []
    stage1 = stage1_result if isinstance(stage1_result, dict) else {}
    hw = heavyweights if isinstance(heavyweights, dict) else {}

    matched: list[tuple[int, str]] = []  # (priority, name)

    # Compile all news text
    news_texts = []
    for it in news:
        if isinstance(it, dict):
            title = it.get("title") or it.get("headline") or ""
            news_texts.append(str(title).lower())
    full_news_corpus = " ".join(news_texts)

    # 1. RBI Policy Quant
    rbi_kws = SPECIALIST_SPECS["RBI_Policy_Quant"]["triggers"]["news_keywords"]
    if any(kw in full_news_corpus for kw in rbi_kws):
        matched.append((10, "RBI_Policy_Quant"))

    # 2. Geopolitical Crude Analyst
    crude_kws = SPECIALIST_SPECS["Geopolitical_Crude_Analyst"]["triggers"]["news_keywords"]
    if any(kw in full_news_corpus for kw in crude_kws):
        matched.append((8, "Geopolitical_Crude_Analyst"))

    # 3. 0-DTE Options Greeks Quant
    dte_val = signals.get("dte")
    if dte_val is not None:
        try:
            if int(dte_val) <= 1:
                matched.append((9, "Options_Greeks_ZeroDTE_Quant"))
        except (ValueError, TypeError):
            pass
    fo_ctx = str(stage1.get("fo_expiry_context", "")).lower()
    if not any(m[1] == "Options_Greeks_ZeroDTE_Quant" for m in matched):
        if any(c in fo_ctx for c in ["expiry today", "expiry tomorrow", "0 dte", "1 dte"]):
            matched.append((9, "Options_Greeks_ZeroDTE_Quant"))

    # 4. Heavyweight Earnings Specialist
    earn_kws = SPECIALIST_SPECS["Heavyweight_Earnings_Specialist"]["triggers"]["news_keywords"]
    has_earnings_news = any(kw in full_news_corpus for kw in earn_kws)
    has_hw_move = False
    for stock_data in hw.values():
        if isinstance(stock_data, dict):
            chg = abs(_clean_numeric(stock_data.get("change_pct"), 0.0))
            if chg >= 0.8:
                has_hw_move = True
                break
    if has_earnings_news or has_hw_move:
        matched.append((7, "Heavyweight_Earnings_Specialist"))

    # 5. FII Order Flow Tracer
    fii_net = abs(_clean_numeric(signals.get("fii_net") or signals.get("fii_cash"), 0.0))
    if fii_net >= 1800.0:
        matched.append((6, "FII_OrderFlow_Tracer"))

    # Sort by priority descending and cap at max_specialists
    matched.sort(key=lambda x: x[0], reverse=True)
    return [name for _, name in matched[:max_specialists]]


# ─────────────────────────────────────────────────────────────────────────────
# Specialist Evaluation (Gemini / Groq / Fallback)
# ─────────────────────────────────────────────────────────────────────────────

def _generate_fallback_verdict(
    specialist_name: str,
    market_signals: dict[str, Any],
    stage1_result: dict[str, Any],
) -> dict[str, Any]:
    """Generate deterministic domain rule-based verdict when LLM is unavailable."""
    prop_bias = stage1_result.get("btst_bias", "NO TRADE")
    vix = _clean_numeric(market_signals.get("india_vix"), 13.5)
    fii = _clean_numeric(market_signals.get("fii_net"), 0.0)

    if specialist_name == "RBI_Policy_Quant":
        return {
            "subagent": "RBI_Policy_Quant",
            "verdict": "HEDGED_SPREAD" if "BUY" in prop_bias else "STRICT_NO_TRADE",
            "confidence": 75,
            "specialist_rationale": "Event implied volatility crush post-announcement severely penalizes naked premium. Favor hedged spreads.",
        }
    elif specialist_name == "Geopolitical_Crude_Analyst":
        return {
            "subagent": "Geopolitical_Crude_Analyst",
            "verdict": "HALF_QUANTITY" if "BUY" in prop_bias else "STRICT_NO_TRADE",
            "confidence": 70,
            "specialist_rationale": "Crude oil volatility injects headline gap risk into Indian equities. Size down exposure.",
        }
    elif specialist_name == "Options_Greeks_ZeroDTE_Quant":
        return {
            "subagent": "Options_Greeks_ZeroDTE_Quant",
            "verdict": "HALF_QUANTITY" if vix < 16.0 else "HEDGED_SPREAD",
            "confidence": 80,
            "specialist_rationale": "Overnight theta on 1-DTE options requires strict risk limits to avoid gap opening decay traps.",
        }
    elif specialist_name == "Heavyweight_Earnings_Specialist":
        return {
            "subagent": "Heavyweight_Earnings_Specialist",
            "verdict": "HEDGED_SPREAD",
            "confidence": 75,
            "specialist_rationale": "Heavyweight earnings divergence can unilaterally veto market momentum. Protect downside.",
        }
    elif specialist_name == "FII_OrderFlow_Tracer":
        if fii < -1500 and "BUY CE" in prop_bias:
            return {
                "subagent": "FII_OrderFlow_Tracer",
                "verdict": "STRICT_NO_TRADE",
                "confidence": 85,
                "specialist_rationale": "Heavy foreign institutional selling undermines Call buying; opening gap up likely to face institutional dumping.",
            }
        return {
            "subagent": "FII_OrderFlow_Tracer",
            "verdict": "HALF_QUANTITY",
            "confidence": 75,
            "specialist_rationale": "Institutional order flow shows high volume concentration. Exercise position sizing moderation.",
        }

    return {
        "subagent": specialist_name,
        "verdict": "HALF_QUANTITY",
        "confidence": 70,
        "specialist_rationale": "Domain specialist advises standard risk moderation.",
    }


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
