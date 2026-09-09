"""
memory/context.py — Memory retrieval, semantic FTS analog search, and macro axiom loading.
"""

import os
import json
import logging
from typing import Any

from cognigraph import get_cognigraph

logger = logging.getLogger(__name__)


class MemoryContextMixin:
    def load_cognigraph_context(
        self,
        persona: str,
        current_signals: dict | None = None,
        stage1_result: dict | None = None,
        max_items: int = 3,
    ) -> str:
        """
        Query CogniGraph memory layer tailored specifically to an agent's persona and active regime.
        """
        try:
            cg = get_cognigraph(str(self._log_path.parent))
            return cg.get_agent_memory(
                persona=persona,
                current_signals=current_signals,
                stage1_result=stage1_result,
                max_items=max_items,
            )
        except Exception as e:
            logger.warning(f"CogniGraph load_cognigraph_context failed: {e}")
            return ""

    def load_fts_analogs(
        self,
        current_signals: dict | None = None,
        news_items: list[dict] | None = None,
        stage1_result: dict | None = None,
        limit: int = 3,
    ) -> str:
        """
        Hermes FTS5 Recall: Retrieve past market days sharing analogous catalysts,
        VIX regimes, or institutional flows using BM25 search.
        """
        if not getattr(self, "_fts", None):
            return ""
        try:
            analogs = self._fts.find_analogs(
                signals=current_signals,
                news_items=news_items,
                stage1_result=stage1_result,
                limit=limit,
            )
            return self._fts.format_analogs_prompt(analogs)
        except Exception as e:
            logger.debug(f"Memory: load_fts_analogs error: {e}")
            return ""

    def search_memories(
        self,
        query: str,
        limit: int = 3,
        outcome_filter: str | None = None,
    ) -> list[dict]:
        """Search historical memories using SQLite FTS5 BM25 text match."""
        if getattr(self, "_fts", None):
            return self._fts.search(query=query, limit=limit, outcome_filter=outcome_filter)
        return []

    def load_macro_axioms_context(self, max_axioms: int = 3) -> str:
        """Retrieve consolidated Macro Axioms distilled by the 20:00 IST Dreaming Engine."""
        try:
            from dreaming_engine import get_dreaming_engine
            engine = get_dreaming_engine(str(self._log_path.parent))
            return engine.format_macro_axioms_prompt(max_axioms=max_axioms)
        except Exception as e:
            logger.debug(f"Memory: load_macro_axioms_context skipped: {e}")
            return ""

    def load_past_context(
        self,
        n: int = 5,
        persona: str | None = None,
        current_signals: dict | None = None,
        stage1_result: dict | None = None,
        news_items: list[dict] | None = None,
    ) -> str:
        """
        Phase D: Return institutional memory to inject into the LLM prompt.
        1. If persona is provided, queries CogniGraph first.
        2. If current_signals or news_items or stage1_result are given, queries FTS5 for analogous precedents.
        3. Prepends top consolidated Macro Axioms if available.
        4. Falls back to last N chronological entries.
        """
        if persona:
            cogni_ctx = self.load_cognigraph_context(persona, current_signals, stage1_result)
            if cogni_ctx:
                return cogni_ctx

        axioms_ctx = self.load_macro_axioms_context(max_axioms=3)

        # Hermes FTS5 analog recall if market conditions are provided
        if current_signals or stage1_result or news_items:
            fts_ctx = self.load_fts_analogs(
                current_signals=current_signals,
                news_items=news_items,
                stage1_result=stage1_result,
                limit=3,
            )
            if fts_ctx:
                if axioms_ctx:
                    return f"{axioms_ctx}\n\n{fts_ctx}"
                return fts_ctx

        entries = self._load_raw_entries()
        resolved = [e for e in entries if e.get("status") not in ("pending",) and e.get("outcome")]

        if not resolved:
            return axioms_ctx

        # Most recent first
        recent = resolved[-n:][::-1]

        parts = ["📚 PAST NIFTY GAP PREDICTION LESSONS (most recent first — learn from these):"]
        for i, e in enumerate(recent, 1):
            outcome_line = e.get("outcome", "Unknown")
            reflection_line = e.get("reflection", "").strip()
            lesson_block = (
                f"  {i}. [{e['date']}] Predicted: {e['prediction']} / {e['btst_bias']} ({e['confidence']}%)\n"
                f"     Outcome: {outcome_line}\n"
            )
            if reflection_line:
                lesson_block += f"     Lesson: {reflection_line}\n"
            parts.append(lesson_block)

        context = "\n".join(parts)
        if axioms_ctx:
            context = f"{axioms_ctx}\n\n{context}"

        logger.debug(f"Memory: Loaded {len(recent)} past lessons for context injection.")
        return context

    # ─────────────────────────────────────────────────
    # Stats / API
    # ─────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """
        Return accuracy statistics for the /api/memory endpoint, including CogniGraph graph metrics and FTS5 status.
        """
        entries = self._load_raw_entries()
        resolved = [e for e in entries if e.get("outcome")]
        pending = [e for e in entries if e.get("status") == "pending"]

        correct = sum(1 for e in resolved if "CORRECT" in e.get("outcome", ""))
        partial = sum(1 for e in resolved if "PARTIAL" in e.get("outcome", ""))
        wrong = sum(1 for e in resolved if "WRONG" in e.get("outcome", ""))
        total = len(resolved)

        cognigraph_stats = {}
        try:
            cg = get_cognigraph(str(self._log_path.parent))
            cognigraph_stats = cg.get_stats()
        except Exception as e:
            logger.warning(f"CogniGraph stats retrieval failed: {e}")

        fts_stats = {}
        if getattr(self, "_fts", None):
            conn = None
            try:
                conn = self._fts._get_connection()
                row = conn.execute("SELECT count(*) as count FROM nifty_memories_meta;").fetchone()
                fts_stats = {"indexed_entries": row["count"] if row else 0, "status": "active"}
            except Exception as e:
                fts_stats = {"status": "error", "error": str(e)}
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

        curator_report = {}
        try:
            from skills_engine import get_skills_engine
            se = get_skills_engine(history_dir=str(self._log_path.parent))
            curator_report = se.curator.get_report()
        except Exception:
            pass

        dreaming_stats = {}
        try:
            from dreaming_engine import get_dreaming_engine
            de = get_dreaming_engine(str(self._log_path.parent))
            dreaming_stats = {
                "total_axioms": len(de._axioms),
                "top_axioms": list(de._axioms.values())[:3],
            }
        except Exception:
            pass

        return {
            "total_predictions": total + len(pending),
            "resolved": total,
            "pending": len(pending),
            "correct": correct,
            "partial": partial,
            "wrong": wrong,
            "accuracy_pct": round((correct / total * 100) if total > 0 else 0.0, 1),
            "cognigraph": cognigraph_stats,
            "fts": fts_stats,
            "skills_curator": curator_report,
            "dreaming": dreaming_stats,
            "entries": [
                {
                    "date": e["date"],
                    "prediction": e["prediction"],
                    "btst_bias": e["btst_bias"],
                    "confidence": e["confidence"],
                    "outcome": e.get("outcome", "pending"),
                    "reflection": e.get("reflection", ""),
                }
                for e in reversed(entries[-20:])  # last 20 entries, newest first
            ],
        }

    # ─────────────────────────────────────────────────
    # Internal Helpers
    # ─────────────────────────────────────────────────

