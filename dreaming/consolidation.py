"""
dreaming/consolidation.py — CogniGraph rebalancing, skills audit, and consolidation cycle.
"""

import os
import json
import math
import logging
from typing import Any
from .constants import _clean_float, _now_ist_str

logger = logging.getLogger("DreamingEngine")


class ConsolidationMixin:
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


