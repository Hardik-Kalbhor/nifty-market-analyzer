"""
scheduler/dreaming_task.py — Post-market autonomous 20:00 IST dreaming consolidation task.
"""

from __future__ import annotations

import logging
from typing import Any

from .constants import HISTORY_DIR

logger = logging.getLogger("AutoScheduler")


def run_dreaming_consolidation() -> dict[str, Any] | None:
    """
    Phase 4: Post-Market Autonomous 20:00 IST Dreaming Consolidation Cycle.
    Synthesizes Macro Axioms, ages and rebalances CogniGraph, audits procedural
    playbooks, and logs dream consolidation report.
    """
    logger.info("🌙 AutoScheduler: Initiating 20:00 IST Post-Market Dreaming Memory Consolidation...")
    try:
        from dreaming_engine import get_dreaming_engine
        from memory_log import build_reflect_fn_from_env

        reflect_fn = None
        try:
            reflect_fn = build_reflect_fn_from_env()
        except Exception:
            pass

        engine = get_dreaming_engine(HISTORY_DIR)
        report = engine.run_consolidation_cycle(llm_distill_fn=reflect_fn, dry_run=False)
        logger.info(
            f"✅ Dreaming Consolidation Complete: {report.get('episodes_processed')} episodes processed, "
            f"{report.get('macro_axioms', {}).get('active_total')} active axioms."
        )
        return report
    except Exception as e:
        logger.error(f"❌ Dreaming Consolidation failed: {e}", exc_info=True)
        return None
