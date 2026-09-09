from __future__ import annotations
import os
import re
import json
import logging
from datetime import datetime
from typing import Any, Callable
import requests
from .constants import TIMEZONE, _clean_float, _now_ist_str

logger = logging.getLogger("DreamingEngine")


class AxiomSynthesisMixin:
    def synthesize_macro_axioms_heuristic(
        self, episodes: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Deterministic Rule Mining: Clusters recurring failure and success
        patterns across market indicators (FII flows, VIX, Heavyweights, Expiry).
        """
        synthesized: list[dict[str, Any]] = []
        today_date = datetime.now(TIMEZONE).strftime("%Y-%m-%d")

        if not episodes:
            return synthesized

        # Cluster 1: FII Heavy Selling vs Bullish Bias
        fii_bear_episodes = [
            e for e in episodes
            if e.get("fii_net", 0) < -1500 and "BUY CE" in e.get("btst_bias", "")
        ]
        if len(fii_bear_episodes) >= 2:
            failures = sum(1 for e in fii_bear_episodes if e.get("outcome") in ("WRONG", "PARTIAL"))
            fail_rate = failures / len(fii_bear_episodes)
            if fail_rate >= 0.5:
                synthesized.append({
                    "axiom_id": "AXIOM_FII_OUTFLOW_BULLISH_VETO",
                    "statement": "Heavy FII cash outflow (> -1,500 Cr) routinely neutralizes overnight gap up momentum, resulting in opening sell-offs.",
                    "subject": "FII_Heavy_Selling",
                    "relation": "invalidates",
                    "target": "BUY_CE_Continuation",
                    "polarity": "NEGATIVE",
                    "regime": "VIX_MOD|DTE_NEAR|FII_BEAR|GAP_MILD_UP",
                    "confidence": round(min(0.95, 0.65 + 0.1 * failures), 2),
                    "observation_count": len(fii_bear_episodes),
                    "evidence_dates": [e["trade_date"] for e in fii_bear_episodes if e.get("trade_date")],
                    "last_validated": today_date,
                })

        # Cluster 2: High VIX Premium Decay Trap
        high_vix_episodes = [
            e for e in episodes
            if e.get("india_vix", 0) > 16.5 and e.get("outcome") in ("WRONG", "PARTIAL")
        ]
        if len(high_vix_episodes) >= 2:
            synthesized.append({
                "axiom_id": "AXIOM_HIGH_VIX_THETA_CRUSH",
                "statement": "Elevated India VIX (> 16.5) induces rapid morning implied volatility crush; naked option longs lose premium despite minor favorable gaps.",
                "subject": "Elevated_India_VIX",
                "relation": "crushes",
                "target": "Naked_Option_Premium",
                "polarity": "NEGATIVE",
                "regime": "VIX_HIGH|DTE_NEAR|FII_NEUT|GAP_STRONG_UP",
                "confidence": round(min(0.90, 0.60 + 0.1 * len(high_vix_episodes)), 2),
                "observation_count": len(high_vix_episodes),
                "evidence_dates": [e["trade_date"] for e in high_vix_episodes if e.get("trade_date")],
                "last_validated": today_date,
            })

        # Cluster 3: Consistent Correct Predictions
        correct_episodes = [e for e in episodes if e.get("outcome") == "CORRECT"]
        if len(correct_episodes) >= 3:
            fii_bull_wins = [e for e in correct_episodes if e.get("fii_net", 0) > 1000]
            if len(fii_bull_wins) >= 2:
                synthesized.append({
                    "axiom_id": "AXIOM_INSTITUTIONAL_INFLOW_FOLLOW_THROUGH",
                    "statement": "Positive FII cash buying (> +1,000 Cr) coupled with moderate VIX establishes durable overnight gap follow-through.",
                    "subject": "FII_Heavy_Buying",
                    "relation": "reinforced",
                    "target": "Bullish_Opening_Drive",
                    "polarity": "POSITIVE",
                    "regime": "VIX_MOD|DTE_NEAR|FII_BULL|GAP_STRONG_UP",
                    "confidence": round(min(0.92, 0.70 + 0.08 * len(fii_bull_wins)), 2),
                    "observation_count": len(fii_bull_wins),
                    "evidence_dates": [e["trade_date"] for e in fii_bull_wins if e.get("trade_date")],
                    "last_validated": today_date,
                })

        # Cluster 4: Skill Playbook Reflections
        for ep in episodes:
            skills = ep.get("active_skills") or []
            if "expiry_day_pinning" in skills and ep.get("outcome") in ("WRONG", "PARTIAL"):
                synthesized.append({
                    "axiom_id": "AXIOM_EXPIRY_THETA_GRAVITY",
                    "statement": "Holding directional BTST options into expiry day incurs severe theta erosion within the first 15 minutes unless hedged with spreads.",
                    "subject": "Expiry_Day_Theta",
                    "relation": "erodes",
                    "target": "Naked_Out_Of_Money_Options",
                    "polarity": "NEGATIVE",
                    "regime": "VIX_LOW|DTE_EXPIRY|FII_NEUT|GAP_MILD_UP",
                    "confidence": 0.85,
                    "observation_count": 2,
                    "evidence_dates": [ep.get("trade_date", today_date)],
                    "last_validated": today_date,
                })
                break

        return synthesized

    def synthesize_macro_axioms_llm(
        self,
        episodes: list[dict[str, Any]],
        llm_distill_fn: Callable[[str], str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Use an LLM (Gemini / Groq) to extract generalizable market truths from episodic post-mortems.
        Falls back to heuristic synthesis if no response or parse error.
        """
        if not llm_distill_fn:
            return self.synthesize_macro_axioms_heuristic(episodes)

        recent_samples = episodes[:10]
        context_lines = []
        for e in recent_samples:
            context_lines.append(
                f"- Date: {e.get('trade_date')} | Pred: {e.get('prediction')} ({e.get('btst_bias')}) "
                f"| Actual Gap: {e.get('actual_gap_pct', 0):+.2f}% | Outcome: {e.get('outcome')} "
                f"| FII: ₹{e.get('fii_net', 0):.0f} Cr | VIX: {e.get('india_vix', 0):.1f}\n"
                f"  Reasoning: {e.get('reasoning', '')[:100]}\n"
                f"  Reflection: {e.get('reflection', '')[:120]}"
            )

        prompt = (
            "You are the NIFTY Hypatia Memory Consolidation 'Dreaming' Engine.\n"
            "Analyze the following recent trading outcomes and reflections, and extract 2-4 "
            "durable, universal 'Macro Axioms' that should permanently guide future trading committees.\n\n"
            "EPISODIC TRADE HISTORY:\n" + "\n".join(context_lines) + "\n\n"
            "Output ONLY a valid JSON array of objects with this exact structure:\n"
            "[\n"
            "  {\n"
            "    \"axiom_id\": \"AXIOM_SHORT_IDENTIFIER\",\n"
            "    \"statement\": \"Concise, empirical market rule in present tense.\",\n"
            "    \"subject\": \"Root_Cause_Indicator\",\n"
            "    \"relation\": \"invalidates|reinforces|crushes|supports\",\n"
            "    \"target\": \"Market_Direction_Or_Trade\",\n"
            "    \"polarity\": \"POSITIVE\" or \"NEGATIVE\",\n"
            "    \"confidence\": 0.85\n"
            "  }\n"
            "]"
        )

        try:
            import inspect
            sig = inspect.signature(llm_distill_fn)
            if len(sig.parameters) >= 2:
                sys_prompt = "You are the NIFTY Hypatia Memory Consolidation 'Dreaming' Engine. Extract durable universal Macro Axioms."
                raw_resp = llm_distill_fn(sys_prompt, prompt)
            else:
                raw_resp = llm_distill_fn(prompt)

            match = re.search(r"\[\s*\{.*\}\s*\]", raw_resp, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                today_date = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
                axioms = []
                for item in parsed:
                    if isinstance(item, dict) and "statement" in item:
                        aid = item.get("axiom_id") or f"AXIOM_{abs(hash(item['statement'])) % 100000}"
                        axioms.append({
                            "axiom_id": aid.upper().replace(" ", "_"),
                            "statement": item["statement"],
                            "subject": item.get("subject", "Market_Signal"),
                            "relation": item.get("relation", "affects"),
                            "target": item.get("target", "Trade_Outcome"),
                            "polarity": item.get("polarity", "NEGATIVE").upper(),
                            "confidence": float(item.get("confidence", 0.75)),
                            "observation_count": len(recent_samples),
                            "evidence_dates": [e["trade_date"] for e in recent_samples if e.get("trade_date")],
                            "last_validated": today_date,
                        })
                if axioms:
                    return axioms
        except Exception as e:
            logger.warning(f"DreamingEngine: LLM distillation failed ({e}), falling back to heuristic.")

        return self.synthesize_macro_axioms_heuristic(episodes)

