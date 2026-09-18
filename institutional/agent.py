"""
institutional/agent.py — Unified Institutional Synthesis Agent.

Sends all scraped brokerage & technical desk articles to a single LLM invocation
(Groq with Gemini fallback) to extract desk-specific S/R calls and synthesize
a cohesive, high-conviction Street Consensus verdict.
"""

import os
import json
import logging
from typing import Optional, Any
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

_GROQ_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
_GEMINI_MODELS = ["gemini-2.5-flash", "gemini-flash-latest"]

def _clean_json_text(text: str) -> str:
    """Extract and clean raw JSON from model output, removing markdown fences or conversational preambles."""
    t = text.strip()
    if t.startswith("```"):
        import re as _re
        t = _re.sub(r"^```(?:json)?\s*", "", t)
        t = _re.sub(r"\s*```$", "", t)
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        return t[start:end + 1]
    return t.strip()


_INSTITUTIONAL_SYSTEM_PROMPT = """You are the Chief Institutional Equity Strategist analyzing Indian brokerage & technical desk notes on NIFTY 50 for the upcoming trading session.
You have been provided with published reports and market outlooks from leading institutional desks (e.g., Religare Broking / Ajit Mishra, Anand Rathi / Ganesh Dongre, HDFC Securities / Nagaraj Shetti, IndiaCharts / Rohit Srivastava).

YOUR TWO OBJECTIVES:

1. DESK-BY-DESK TECHNICAL EXTRACTION:
   For EACH provided desk:
   - Directional Bias: exactly one of "BULLISH", "BEARISH", or "RANGEBOUND".
     * ACCURATELY HANDLE NEGATION & CONTRARIAN CALLS:
       - "sell on rallies near 23,600" is BEARISH (with 23,600 as resistance).
       - "structure remains weak despite recovery" is BEARISH.
       - "does NOT expect rally to sustain" is BEARISH.
       - "buy on dips toward 23,000" is BULLISH.
   - Key SUPPORT levels:
     * s1: primary/immediate support (integer).
     * s2: secondary/deeper support (integer or null).
   - Key RESISTANCE levels:
     * r1: primary/immediate resistance/hurdle (integer).
     * r2: secondary/higher target resistance (integer or null).
   - CRITICAL FILTER FOR QUOTES VS TARGETS:
     * Do NOT treat previous closing or settlement prints (e.g. "Nifty settled at 23,217.60", "closed at 23,200", "opened at 23,150") as support/resistance targets!
     * Only extract numbers explicitly described as support, resistance, hurdle, supply zone, or upside/downside targets.
   - Expected opening gap: "Positive", "Negative", or "Flat".
   - Thesis: Exactly 1 concise sentence summarizing the analyst's core view and actionable level.
   - raw_levels: list of distinct price levels mentioned as targets/hurdles by the analyst.

2. UNIFIED STREET CONSENSUS SYNTHESIS:
   Synthesize all desk views into a single cohesive Street Consensus:
   - next_day_bias: Overall institutional consensus bias ("BULLISH" | "BEARISH" | "RANGEBOUND").
   - bull_pct: Estimated % of desks leaning bullish (0 - 100).
   - bear_pct: Estimated % of desks leaning bearish (0 - 100).
   - s1: Primary consensus support zone (e.g. "23,000 — 23,100" or single price if unanimous).
   - s2: Secondary consensus support zone (e.g. "22,800 — 22,900" or null).
   - r1: Primary consensus resistance/supply zone (e.g. "23,400 — 23,600" or single price).
   - r2: Secondary consensus breakout resistance (e.g. "23,800 — 24,000" or null).
   - expected_gap: Overall expected market opening gap ("Positive", "Negative", or "Flat").
   - thesis: High-conviction synthesis narrative (1-2 sentences) explaining institutional alignment, key battleground level, and what breaks the thesis.

Return ONLY a valid JSON object matching this schema (no markdown, no backticks, no preamble):
{
  "provider_calls": {
    "<provider_key>": {
      "next_day_bias": "BULLISH" | "BEARISH" | "RANGEBOUND",
      "s1": integer or null,
      "s2": integer or null,
      "r1": integer or null,
      "r2": integer or null,
      "expected_gap": "Positive" | "Negative" | "Flat",
      "thesis": "string",
      "raw_levels": [integers]
    }
  },
  "consensus": {
    "next_day_bias": "BULLISH" | "BEARISH" | "RANGEBOUND",
    "bull_pct": integer,
    "bear_pct": integer,
    "s1": string,
    "s2": string or null,
    "r1": string,
    "r2": string or null,
    "expected_gap": "Positive" | "Negative" | "Flat",
    "thesis": "string"
  }
}
"""


def _run_institutional_synthesis_agent(
    raw_providers: dict,
    nifty_spot: Optional[float] = None,
) -> Optional[dict]:
    """
    Execute the unified Institutional Synthesis Agent over all collected desk reports.
    Returns:
      {
        "provider_calls": { ... },
        "consensus": { ... }
      }
    Returns None if models fail or keys are absent.
    """
    if not raw_providers:
        return None

    # Construct user context with concise desk texts (800 chars each prevents TPM limit errors)
    context_lines = [
        f"CURRENT NIFTY SPOT: {nifty_spot or 'Unknown'}",
        "\nINSTITUTIONAL BROKERAGE & TECHNICAL DESK NOTES:\n",
    ]

    for key, data in raw_providers.items():
        name = data.get("name", key)
        analyst = data.get("analyst", "")
        title = data.get("best_title", "")
        text = data.get("combined_text", "")[:1600].strip()
        context_lines.append(f"=== DESK: {name} ({analyst}) [key: {key}] ===")
        if title:
            context_lines.append(f"Headline: {title}")
        context_lines.append(f"Article Body:\n\"\"\"\n{text}\n\"\"\"\n")


    user_content = "\n".join(context_lines)

    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()

    # 1. Try Groq model cascade
    if groq_key:
        headers = {
            "Authorization": f"Bearer {groq_key}",
            "Content-Type": "application/json",
        }
        for model in _GROQ_MODELS:
            try:
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": _INSTITUTIONAL_SYSTEM_PROMPT},
                        {"role": "user",   "content": user_content},
                    ],
                    "temperature": 0.1,
                }
                resp = requests.post(_GROQ_URL, headers=headers, json=payload, timeout=14)
                if resp.status_code == 200:
                    raw_json = resp.json()["choices"][0]["message"]["content"]
                    cleaned = _clean_json_text(raw_json)
                    parsed = json.loads(cleaned)
                    validated = _validate_agent_output(parsed, raw_providers)
                    if validated:
                        logger.info(f"🏛️ Institutional Agent ({model}): synthesized {len(validated['provider_calls'])} desks successfully")
                        return validated
                elif resp.status_code in (413, 429):
                    logger.warning(f"Institutional Agent Groq ({model}): HTTP {resp.status_code} — trying next model")
                else:
                    logger.debug(f"Institutional Agent Groq ({model}): HTTP {resp.status_code}")
            except Exception as e:
                logger.debug(f"Institutional Agent Groq ({model}) error: {e}")

    # 2. Try Gemini Flash fallback
    if gemini_key:
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{
                "role": "user",
                "parts": [{"text": _INSTITUTIONAL_SYSTEM_PROMPT + "\n\n" + user_content}]
            }],
            "generationConfig": {"response_mime_type": "application/json"},
        }
        for model in _GEMINI_MODELS:
            try:
                url = _GEMINI_URL.format(model=model, key=gemini_key)
                resp = requests.post(url, headers=headers, json=payload, timeout=14)
                if resp.status_code == 200:
                    raw_json = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                    cleaned = _clean_json_text(raw_json)
                    parsed = json.loads(cleaned)
                    validated = _validate_agent_output(parsed, raw_providers)
                    if validated:
                        logger.info(f"🏛️ Institutional Agent Gemini ({model}): synthesized {len(validated['provider_calls'])} desks successfully")
                        return validated
                elif resp.status_code in (413, 429):
                    logger.warning(f"Institutional Agent Gemini ({model}): HTTP {resp.status_code}")
            except Exception as e:
                logger.debug(f"Institutional Agent Gemini ({model}) error: {e}")

    logger.warning("Institutional Agent: All AI models offline or unavailable")
    return None



def _validate_agent_output(parsed: Any, raw_providers: dict) -> Optional[dict]:
    """Validate and normalize the structure returned by the LLM."""
    if not isinstance(parsed, dict):
        return None

    raw_calls = parsed.get("provider_calls")
    if not isinstance(raw_calls, dict) or not raw_calls:
        return None

    valid_biases = {"BULLISH", "BEARISH", "RANGEBOUND"}
    normalized_calls = {}

    for key, call in raw_calls.items():
        if not isinstance(call, dict):
            continue
        bias = str(call.get("next_day_bias", "RANGEBOUND")).upper()
        if bias not in valid_biases:
            bias = "RANGEBOUND"

        def _to_int(val):
            if val is None:
                return None
            try:
                return int(float(str(val).replace(",", "").strip()))
            except Exception:
                return None

        s1 = _to_int(call.get("s1"))
        s2 = _to_int(call.get("s2"))
        r1 = _to_int(call.get("r1"))
        r2 = _to_int(call.get("r2"))

        gap = str(call.get("expected_gap", "Flat")).capitalize()
        if gap not in {"Positive", "Negative", "Flat"}:
            gap = "Positive" if bias == "BULLISH" else "Negative" if bias == "BEARISH" else "Flat"

        raw_lvls = call.get("raw_levels", [])
        cleaned_raw = []
        if isinstance(raw_lvls, list):
            for x in raw_lvls:
                ix = _to_int(x)
                if ix and 20000 <= ix <= 30000:
                    cleaned_raw.append(ix)

        thesis = str(call.get("thesis", "")).strip()

        normalized_calls[key] = {
            "next_day_bias": bias,
            "s1": s1,
            "s2": s2,
            "r1": r1,
            "r2": r2,
            "expected_gap": gap,
            "thesis": thesis,
            "raw_levels_found": cleaned_raw,
        }

    if not normalized_calls:
        return None

    consensus = parsed.get("consensus", {})
    if not isinstance(consensus, dict):
        consensus = {}

    c_bias = str(consensus.get("next_day_bias", "RANGEBOUND")).upper()
    if c_bias not in valid_biases:
        c_bias = "RANGEBOUND"

    try:
        bull_pct = int(consensus.get("bull_pct", 0))
    except Exception:
        bull_pct = 0

    try:
        bear_pct = int(consensus.get("bear_pct", 0))
    except Exception:
        bear_pct = 0

    def _zone_str(val):
        if val is None:
            return None
        s = str(val).strip()
        return s if s else None

    normalized_consensus = {
        "next_day_bias": c_bias,
        "bull_pct": bull_pct,
        "bear_pct": bear_pct,
        "s1": _zone_str(consensus.get("s1")),
        "s2": _zone_str(consensus.get("s2")),
        "r1": _zone_str(consensus.get("r1")),
        "r2": _zone_str(consensus.get("r2")),
        "expected_gap": str(consensus.get("expected_gap", "Flat")).capitalize(),
        "thesis": str(consensus.get("thesis", "")).strip(),
    }

    return {
        "provider_calls": normalized_calls,
        "consensus": normalized_consensus,
    }
