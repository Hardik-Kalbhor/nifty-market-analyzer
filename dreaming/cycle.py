"""
dreaming/cycle.py — Autonomous post-market consolidation cycle execution.
"""

from __future__ import annotations
import os
import json
import logging
from typing import Any, Callable
from .constants import _clean_float, _now_ist_str

logger = logging.getLogger("DreamingEngine")


class ConsolidationCycleMixin:
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

        # 1. Harvest episodes (Predictions & Live Exits)
        episodes = self.harvest_episodes()
        logger.info(f"  📖 Harvested {len(episodes)} resolved trade episodes.")

        exit_episodes = self.harvest_exit_episodes()
        logger.info(f"  🚪 Harvested {len(exit_episodes)} live exit evaluations.")

        exit_audit = self.audit_exit_effectiveness(exit_episodes)
        logger.info(
            f"  ⚖️ Exit Effectiveness: {exit_audit.get('effectiveness_score_pct', 100)}% "
            f"({len(exit_audit.get('timely_profit_locks', []))} locks, "
            f"{len(audit_res_errors := exit_audit.get('lethal_hold_errors', []))} lethal holds, "
            f"{len(exit_audit.get('premature_panic_exits', []))} premature exits)."
        )

        # 2. Synthesize Macro Axioms (Predictions + Exits)
        if llm_distill_fn:
            new_pred_axioms = self.synthesize_macro_axioms_llm(episodes, llm_distill_fn)
        else:
            new_pred_axioms = self.synthesize_macro_axioms_heuristic(episodes)

        new_exit_axioms = self.synthesize_exit_macro_axioms(exit_audit, exit_episodes)
        all_new_axioms = new_pred_axioms + new_exit_axioms
        logger.info(
            f"  💡 Synthesized {len(all_new_axioms)} candidate macro axioms "
            f"({len(new_pred_axioms)} directional + {len(new_exit_axioms)} exit rules)."
        )

        # Persist axioms if not dry run
        if not dry_run:
            merged_count = self.merge_and_store_axioms(all_new_axioms)
        else:
            merged_count = len(all_new_axioms)

        # 3. Rebalance CogniGraph & Record Exit Failure Traps
        if not dry_run:
            cogni_stats = self.rebalance_cognigraph()
            traps_recorded = self.record_exit_traps_in_cognigraph(exit_audit)
            cogni_stats["exit_traps_recorded"] = traps_recorded
        else:
            cogni_stats = {"dry_run": True, "exit_traps_recorded": len(exit_audit.get("lethal_hold_errors", []))}

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
            "exit_episodes_processed": len(exit_episodes),
            "exit_advisor_audit": {
                "total_exits_audited": exit_audit.get("total_exits_audited", 0),
                "timely_profit_locks": len(exit_audit.get("timely_profit_locks", [])),
                "premature_panic_exits": len(exit_audit.get("premature_panic_exits", [])),
                "lethal_hold_errors": len(exit_audit.get("lethal_hold_errors", [])),
                "protective_exits": len(exit_audit.get("protective_exits", [])),
                "effectiveness_score_pct": exit_audit.get("effectiveness_score_pct", 100.0),
                "failure_traps_identified": exit_audit.get("failure_traps_identified", []),
            },
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

