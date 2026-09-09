"""
dreaming_engine.py — Autonomous 20:00 IST Memory Consolidation Engine.

Adapted from Nous Research Hermes Agent cognitive memory architecture:
Consolidates episodic trade memories into durable Macro Axioms, applies
exponential decay and reinforcement to CogniGraph causal edges, audits
active procedural playbooks, and writes session consolidation reports.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pytz

logger = logging.getLogger("DreamingEngine")
TIMEZONE = pytz.timezone("Asia/Kolkata")


def _clean_float(val: Any, default: float = 0.0) -> float:
    """Safely parse float from string or numeric, handling currencies, commas, and signs."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        s = str(val).strip().replace(",", "")
        m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
        if m:
            return float(m.group(0))
        return default
    except Exception:
        return default


def _now_ist_str() -> str:
    """Current timestamp in IST ISO format."""
    return datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S IST")


class DreamingEngine:
    """
    Orchestrates the post-market 20:00 IST consolidation cycle.
    """

    def __init__(self, history_dir: str | None = None):
        self._lock = threading.RLock()
        if history_dir is None:
            base = os.getenv("HISTORY_DIR", os.path.join(os.path.dirname(__file__), "history"))
        else:
            base = history_dir

        try:
            os.makedirs(base, exist_ok=True)
            self._history_dir = Path(base)
        except (OSError, PermissionError):
            fallback = "/tmp/history"
            os.makedirs(fallback, exist_ok=True)
            self._history_dir = Path(fallback)

        self._axioms_path = self._history_dir / "macro_axioms.json"
        self._dream_report_path = self._history_dir / "dream_report.json"

        self._axioms: dict[str, dict[str, Any]] = {}
        self._load_axioms()

    # ─────────────────────────────────────────────────────────────────────────
    # Step 1: Harvest Episodic History
    # ─────────────────────────────────────────────────────────────────────────

    def harvest_episodes(self, max_episodes: int = 30) -> list[dict[str, Any]]:
        """
        Extract resolved trading episodes and post-mortems from memory_log.md
        and recent analysis_*.json files.
        """
        episodes: list[dict[str, Any]] = []

        try:
            from memory_log import get_memory_log
            mem = get_memory_log(str(self._history_dir))
            raw_entries = mem._load_raw_entries()

            # Filter for resolved episodes
            for e in raw_entries:
                if e.get("status") != "pending" and e.get("outcome"):
                    trade_date = e.get("date", "")
                    actual_gap = _clean_float(e.get("actual_gap_pct"))
                    if actual_gap == 0.0:
                        m = re.search(r"Actual:\s*([+-]?\d+(?:\.\d+)?)%", str(e.get("outcome", "")))
                        if m:
                            actual_gap = _clean_float(m.group(1))
                        elif "actual:" in str(e.get("status", "")).lower():
                            actual_gap = _clean_float(str(e.get("status", "")).lower().split("actual:")[-1])
                    pred = e.get("prediction", "FLAT")
                    btst = e.get("btst_bias", "NO TRADE")
                    raw_out = str(e.get("outcome", "PARTIAL")).upper()
                    if "CORRECT" in raw_out:
                        out = "CORRECT"
                    elif "WRONG" in raw_out:
                        out = "WRONG"
                    elif "PARTIAL" in raw_out:
                        out = "PARTIAL"
                    else:
                        out = str(e.get("outcome", "PARTIAL")).strip()
                    refl = e.get("reflection", "")
                    reasoning = e.get("reasoning", "")
                    conf = int(_clean_float(e.get("confidence"), default=50))
                    fii_net = _clean_float(e.get("fii_net"), default=0.0)
                    vix = _clean_float(e.get("india_vix"), default=14.0)

                    episodes.append({
                        "trade_date": trade_date,
                        "prediction": pred,
                        "btst_bias": btst,
                        "confidence": conf,
                        "actual_gap_pct": actual_gap,
                        "outcome": out,
                        "reflection": refl,
                        "reasoning": reasoning,
                        "fii_net": fii_net,
                        "india_vix": vix,
                        "active_skills": e.get("active_skills", []),
                        "trade_structure": e.get("trade_structure", "HALF_QUANTITY"),
                    })

            # Sort chronologically, newest first, cap at max_episodes
            episodes.sort(key=lambda x: x["trade_date"], reverse=True)
            return episodes[:max_episodes]

        except Exception as err:
            logger.warning(f"DreamingEngine: Error harvesting episodes: {err}")
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # Step 2: Synthesize Macro Axioms (Dual Engine: Heuristic + LLM)
    # ─────────────────────────────────────────────────────────────────────────

    def _load_axioms(self) -> None:
        """Load existing macro axioms from disk."""
        if self._axioms_path.exists():
            try:
                with open(self._axioms_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
                raw_axioms = data.get("axioms", [])
                if isinstance(raw_axioms, list):
                    for ax in raw_axioms:
                        if isinstance(ax, dict) and "axiom_id" in ax:
                            self._axioms[ax["axiom_id"]] = ax
                elif isinstance(raw_axioms, dict):
                    for k, ax in raw_axioms.items():
                        if isinstance(ax, dict):
                            self._axioms[ax.get("axiom_id", k)] = ax
                logger.debug(f"DreamingEngine: Loaded {len(self._axioms)} macro axioms.")
            except Exception as e:
                logger.warning(f"DreamingEngine: Failed to load macro_axioms.json: {e}")
                self._axioms = {}

    def _save_axioms(self) -> None:
        """Atomically persist macro axioms."""
        payload = {
            "schema_version": 1,
            "last_dreamed_at": _now_ist_str(),
            "total_axioms": len(self._axioms),
            "axioms": list(self._axioms.values()),
        }
        tmp_path = str(self._axioms_path) + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self._axioms_path)
        except Exception as e:
            logger.error(f"DreamingEngine: Failed to save macro_axioms.json: {e}")
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

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

    def merge_and_store_axioms(self, new_axioms: list[dict[str, Any]]) -> int:
        """
        Merge newly discovered axioms into self._axioms, updating observation
        counts and confidence scores.
        """
        with self._lock:
            updated_count = 0
            for ax in new_axioms:
                if not isinstance(ax, dict):
                    continue
                aid = ax.get("axiom_id")
                if not aid:
                    continue

                ax_norm = dict(ax)
                ax_norm["observation_count"] = int(_clean_float(ax.get("observation_count"), default=1.0))
                ax_norm["confidence"] = round(_clean_float(ax.get("confidence"), default=0.7), 2)
                if not isinstance(ax_norm.get("evidence_dates"), (list, tuple, set)):
                    ax_norm["evidence_dates"] = [str(ax_norm["evidence_dates"])] if ax_norm.get("evidence_dates") else []
                else:
                    ax_norm["evidence_dates"] = list(ax_norm["evidence_dates"])

                if aid in self._axioms:
                    existing = self._axioms[aid]
                    obs_old = int(_clean_float(existing.get("observation_count"), default=1.0))
                    obs_new = ax_norm["observation_count"]
                    existing["observation_count"] = obs_old + obs_new
                    # Running average of confidence
                    c_old = _clean_float(existing.get("confidence"), default=0.7)
                    c_new = ax_norm["confidence"]
                    existing["confidence"] = round((c_old * 0.6) + (c_new * 0.4), 2)
                    existing["last_validated"] = ax.get("last_validated", _now_ist_str())
                    # Merge evidence dates
                    ev_set = set(existing.get("evidence_dates", []))
                    ev_set.update(ax_norm["evidence_dates"])
                    existing["evidence_dates"] = sorted(list(ev_set))[-10:]
                    if ax.get("statement"):
                        existing["statement"] = str(ax["statement"])
                else:
                    self._axioms[aid] = ax_norm

                updated_count += 1

            self._save_axioms()
            return updated_count

    # ─────────────────────────────────────────────────────────────────────────
    # Step 3: CogniGraph Rebalancing & Decay
    # ─────────────────────────────────────────────────────────────────────────

    def rebalance_cognigraph(self) -> dict[str, Any]:
        """
        Execute exponential decay across all CogniGraph triples, prune dead edges,
        and reinforce validated relationships from active macro axioms.
        """
        stats: dict[str, Any] = {"decayed": 0, "pruned": 0, "reinforced": 0}
        try:
            from cognigraph import get_cognigraph
            cg = get_cognigraph(str(self._history_dir))

            # 1. Decay and prune
            decay_results = cg.decay_and_prune(threshold=0.2, max_idle_days=60.0)
            stats["decayed"] = decay_results.get("decayed", 0)
            stats["pruned"] = decay_results.get("pruned", 0)

            # 2. Reinforce from high-conviction macro axioms
            with self._lock:
                for ax in self._axioms.values():
                    if float(ax.get("confidence", 0.0)) >= 0.70:
                        reinforced_key = cg.reinforce_from_axiom(ax)
                        if reinforced_key:
                            stats["reinforced"] += 1

            logger.info(
                f"DreamingEngine: CogniGraph rebalanced: {stats['decayed']} decayed, "
                f"{stats['pruned']} pruned, {stats['reinforced']} reinforced."
            )
            return stats
        except Exception as e:
            logger.warning(f"DreamingEngine: CogniGraph rebalancing failed: {e}")
            return stats

    # ─────────────────────────────────────────────────────────────────────────
    # Step 4: Skill Playbook Health Audit
    # ─────────────────────────────────────────────────────────────────────────

    def audit_skills(self) -> dict[str, Any]:
        """
        Audit procedural playbooks in SkillCurator and recommend optimizations.
        """
        audit_res: dict[str, Any] = {
            "total_skills": 0,
            "excelling_skills": [],
            "needs_review_skills": [],
            "healthy_skills": [],
            "recommendations": [],
        }
        try:
            from skills_engine import get_skills_engine
            se = get_skills_engine(history_dir=str(self._history_dir))
            curator_report = se.curator.get_curator_report()
            stats = curator_report.get("skills", {})

            audit_res["total_skills"] = len(stats)

            for name, data in stats.items():
                win_rate = data.get("win_pct") if data.get("win_pct") is not None else data.get("win_rate_pct", 0.0)
                acts = data.get("activations", 0)

                if acts >= 3 and win_rate >= 70.0:
                    audit_res["excelling_skills"].append({
                        "name": name,
                        "win_rate_pct": win_rate,
                        "activations": acts,
                    })
                elif acts >= 3 and win_rate < 40.0:
                    audit_res["needs_review_skills"].append({
                        "name": name,
                        "win_rate_pct": win_rate,
                        "activations": acts,
                    })
                    audit_res["recommendations"].append(
                        f"Playbook '{name}' underperformed ({win_rate}% win rate across {acts} trades). "
                        f"Review triggers or tighten threshold criteria."
                    )
                else:
                    audit_res["healthy_skills"].append({
                        "name": name,
                        "win_rate_pct": win_rate,
                        "activations": acts,
                    })

            if not audit_res["recommendations"]:
                audit_res["recommendations"].append(
                    "All active procedural playbooks operating within expected risk boundaries."
                )

            return audit_res
        except Exception as e:
            logger.warning(f"DreamingEngine: Skill audit failed: {e}")
            return audit_res

    # ─────────────────────────────────────────────────────────────────────────
    # Step 5: Full Consolidation Cycle Orchestrator
    # ─────────────────────────────────────────────────────────────────────────

    def run_consolidation_cycle(
        self,
        llm_distill_fn: Callable[[str], str] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """
        Execute the full 20:00 IST post-market dreaming consolidation loop.
        """
        start_time = _now_ist_str()
        logger.info(f"🌙 DreamingEngine: Starting 20:00 IST Memory Consolidation at {start_time}")

        # 1. Harvest episodes
        episodes = self.harvest_episodes()
        logger.info(f"  📖 Harvested {len(episodes)} resolved trade episodes.")

        # 2. Synthesize Macro Axioms
        if llm_distill_fn:
            new_axioms = self.synthesize_macro_axioms_llm(episodes, llm_distill_fn)
        else:
            new_axioms = self.synthesize_macro_axioms_heuristic(episodes)
        logger.info(f"  💡 Synthesized {len(new_axioms)} candidate macro axioms.")

        # Persist axioms if not dry run
        if not dry_run:
            merged_count = self.merge_and_store_axioms(new_axioms)
        else:
            merged_count = len(new_axioms)

        # 3. Rebalance CogniGraph
        if not dry_run:
            cogni_stats = self.rebalance_cognigraph()
        else:
            cogni_stats = {"dry_run": True}

        # 4. Audit Procedural Skills
        skill_audit = self.audit_skills()

        # 5. Export Trajectory Datasets (ShareGPT, DPO, Alpaca)
        trajectory_export_stats = {}
        if not dry_run:
            try:
                from trajectory_exporter import get_trajectory_exporter
                exporter = get_trajectory_exporter(str(self._history_dir))
                trajectory_export_stats = exporter.export_all()
                logger.info(f"  📦 Exported trajectory datasets: {trajectory_export_stats.get('total_exported', 0)} episodes.")
            except Exception as exp_err:
                logger.warning(f"DreamingEngine: Trajectory dataset export skipped: {exp_err}")
                trajectory_export_stats = {"error": str(exp_err)}
        else:
            trajectory_export_stats = {"dry_run": True}

        # 6. Write Dream Report
        report = {
            "dream_timestamp": start_time,
            "status": "COMPLETED",
            "episodes_processed": len(episodes),
            "macro_axioms": {
                "active_total": len(self._axioms),
                "newly_synthesized": merged_count,
                "top_axioms": list(self._axioms.values())[:5],
            },
            "cognigraph_rebalancing": cogni_stats,
            "skill_curator_audit": skill_audit,
            "trajectory_export": trajectory_export_stats,
        }

        if not dry_run:
            tmp_report = str(self._dream_report_path) + ".tmp"
            try:
                with open(tmp_report, "w", encoding="utf-8") as f:
                    json.dump(report, f, indent=2, ensure_ascii=False)
                os.replace(tmp_report, self._dream_report_path)
            except Exception as e:
                logger.warning(f"DreamingEngine: Failed to save dream_report.json: {e}")

        logger.info(f"✨ DreamingEngine: Consolidation cycle complete! Total active axioms: {len(self._axioms)}")
        return report

    # ─────────────────────────────────────────────────────────────────────────
    # Context Formatting for LLM Prompts
    # ─────────────────────────────────────────────────────────────────────────

    def format_macro_axioms_prompt(self, max_axioms: int = 3) -> str:
        """
        Format top consolidated macro axioms for injection into daily committee prompts.
        """
        with self._lock:
            if not self._axioms:
                return ""

            def _sort_key(ax: dict[str, Any]) -> float:
                conf = _clean_float(ax.get("confidence"), default=0.7)
                obs = max(1.1, _clean_float(ax.get("observation_count"), default=1.0))
                return conf * math.log(obs)

            sorted_axioms = sorted(self._axioms.values(), key=_sort_key, reverse=True)

            lines = ["💎 CONSOLIDATED MACRO AXIOMS (Post-Market Empirical Distillations):"]
            for ax in sorted_axioms[:max_axioms]:
                aid = ax.get("axiom_id", "AXIOM")
                stmt = ax.get("statement", "")
                conf_pct = round(_clean_float(ax.get("confidence"), default=0.7) * 100)
                obs = int(_clean_float(ax.get("observation_count"), default=1.0))
                lines.append(f"  • [{aid}] (Conf: {conf_pct}%, validated {obs}x): {stmt}")

            lines.append("  → Instruction: Respect these consolidated macro axioms as empirical ground truth.")
            return "\n".join(lines)


# Singleton factory
_dreaming_instances: dict[str, DreamingEngine] = {}
_dreaming_lock = threading.Lock()


def get_dreaming_engine(history_dir: str | None = None) -> DreamingEngine:
    """Return cached DreamingEngine for the specified directory."""
    with _dreaming_lock:
        key = str(Path(history_dir).resolve()) if history_dir else "default"
        if key not in _dreaming_instances:
            _dreaming_instances[key] = DreamingEngine(history_dir)
        return _dreaming_instances[key]
