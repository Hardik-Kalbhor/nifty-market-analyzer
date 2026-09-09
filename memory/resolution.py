"""
memory/resolution.py — Pending prediction resolution against actual market open.
"""

from __future__ import annotations
import os
import json
import logging
from datetime import datetime
from typing import Any, Callable

from cognigraph import get_cognigraph
from .constants import TIMEZONE, _SEPARATOR, _REFLECTION_SYSTEM_PROMPT
from .market_helpers import _next_trading_day, _fetch_nifty_actual_gap, _classify_gap

logger = logging.getLogger(__name__)


class MemoryResolutionMixin:
    def _fetch_nifty_actual_gap(
        self,
        trade_date: str,
        resolution_date: str,
    ) -> tuple[float | None, float | None, float | None]:
        return _fetch_nifty_actual_gap(trade_date=trade_date, resolution_date=resolution_date)

    def resolve_pending_entries(
        self,
        llm_reflect_fn: Callable[[str, str], str] | None = None,
    ) -> list[dict]:
        """
        Phase B+C: For every pending entry, fetch actual Nifty 50 opening price,
        compute the outcome, then optionally generate a reflection via LLM.

        `llm_reflect_fn(system_prompt, human_prompt) -> str` should call any available LLM.
        If None, reflection is skipped (outcome only).

        Returns list of resolved entry dicts.
        """
        entries = self._load_raw_entries()
        pending = [e for e in entries if e.get("status") == "pending"]

        if not pending:
            logger.info("Memory: No pending entries to resolve.")
            return []

        resolved_list = []

        for entry in pending:
            trade_date = entry.get("date")
            if not trade_date:
                continue
            try:
                # Skip if trade_date is today or in the future (market not open yet)
                today_ist = datetime.now(TIMEZONE).date()
                entry_date = datetime.strptime(trade_date, "%Y-%m-%d").date()
                next_trading_day = _next_trading_day(entry_date)

                if next_trading_day > today_ist:
                    logger.debug(f"Memory: {trade_date} → next trading day {next_trading_day} hasn't happened yet.")
                    continue

                # Phase B: Fetch actual Nifty open price
                actual_gap_pct, actual_open, prev_close = self._fetch_nifty_actual_gap(
                    trade_date=entry["date"],
                    resolution_date=next_trading_day.strftime("%Y-%m-%d"),
                )

                if actual_gap_pct is None:
                    logger.warning(f"Memory: Could not fetch actual open for {trade_date}, skipping.")
                    continue

                # Compute outcome
                actual_label = _classify_gap(actual_gap_pct)
                predicted_label = entry["prediction"].upper()

                if actual_label == predicted_label:
                    outcome_result = "✅ CORRECT"
                elif (
                    (predicted_label == "GAP UP" and actual_label == "FLAT" and actual_gap_pct > 0) or
                    (predicted_label == "GAP DOWN" and actual_label == "FLAT" and actual_gap_pct < 0)
                ):
                    outcome_result = "⚠️ PARTIAL (right direction, gap < threshold)"
                elif (
                    (predicted_label == "FLAT" and actual_label != "FLAT") or
                    (predicted_label == "GAP UP" and actual_label == "GAP DOWN") or
                    (predicted_label == "GAP DOWN" and actual_label == "GAP UP")
                ):
                    outcome_result = "❌ WRONG"
                else:
                    outcome_result = "⚠️ PARTIAL"

                outcome_text = (
                    f"Actual open: {actual_open:,.2f} ({actual_gap_pct:+.2f}%) → {actual_label} {outcome_result}"
                )

                # Phase C: LLM reflection
                reflection_text = ""
                if llm_reflect_fn is not None:
                    try:
                        import inspect
                        human_prompt = (
                            f"Prediction date: {trade_date}\n"
                            f"Predicted: {entry['prediction']} / {entry['btst_bias']} (confidence: {entry['confidence']}%)\n"
                            f"Actual Nifty open: {actual_gap_pct:+.2f}% → {actual_label} ({outcome_result})\n\n"
                            f"Original reasoning:\n{entry.get('reasoning', 'N/A')}"
                        )
                        try:
                            sig = inspect.signature(llm_reflect_fn)
                            param_count = len(sig.parameters)
                        except Exception:
                            param_count = 2

                        if param_count >= 7:
                            reflection_text = llm_reflect_fn(
                                trade_date,
                                entry.get("prediction", ""),
                                entry.get("btst_bias", ""),
                                int(entry.get("confidence") or 50),
                                entry.get("reasoning", ""),
                                actual_gap_pct,
                                outcome_result,
                            )
                        else:
                            reflection_text = llm_reflect_fn(_REFLECTION_SYSTEM_PROMPT, human_prompt)
                        logger.info(f"Memory Phase C: reflection generated for {trade_date}")
                    except Exception as ref_err:
                        logger.warning(f"Memory: Reflection LLM call failed for {trade_date}: {ref_err}")
                        reflection_text = ""

                # Write updated entry back to the log
                self._update_entry(
                    trade_date=trade_date,
                    outcome_text=outcome_text,
                    reflection_text=reflection_text,
                    actual_gap_pct=actual_gap_pct,
                    outcome_result=outcome_result,
                )

                # Ingest into CogniGraph memory layer
                try:
                    cg = get_cognigraph(str(self._log_path.parent))
                    cg.ingest_resolution(
                        trade_date=trade_date,
                        prediction=entry.get("prediction", "FLAT"),
                        btst_bias=entry.get("btst_bias", "NO TRADE"),
                        confidence=int(entry.get("confidence") or 50),
                        actual_gap_pct=actual_gap_pct,
                        outcome=outcome_result,
                        reflection=reflection_text,
                        market_signals={
                            "fii_net": entry.get("fii_net"),
                            "gift_nifty_change_pct": entry.get("gift_nifty_pct"),
                        },
                        stage1_result={
                            "prediction": entry.get("prediction"),
                            "btst_bias": entry.get("btst_bias"),
                            "fo_expiry_context": entry.get("fo_context") or entry.get("fo_expiry_context") or "",
                        },
                        trade_structure=entry.get("trade_structure"),
                    )
                except Exception as cg_err:
                    logger.warning(f"CogniGraph ingestion error for {trade_date}: {cg_err}")

                # Hermes FTS5 index update on resolution
                if getattr(self, "_fts", None):
                    try:
                        self._fts.upsert_entry(
                            trade_date=trade_date,
                            prediction=entry.get("prediction", "FLAT"),
                            btst_bias=entry.get("btst_bias", "NO TRADE"),
                            confidence=int(entry.get("confidence") or 50),
                            status="resolved",
                            outcome=outcome_result,
                            actual_gap_pct=actual_gap_pct,
                            reflection=reflection_text,
                            reasoning=entry.get("reasoning", ""),
                        )
                    except Exception as fts_res_err:
                        logger.debug(f"Memory: FTS upsert in resolve_pending skipped: {fts_res_err}")

                # Hermes Skill Curator outcome attribution
                try:
                    from skills_engine import get_skills_engine
                    se = get_skills_engine(history_dir=str(self._log_path.parent))
                    se.curator.record_outcome(trade_date, outcome_result)
                except Exception as cur_out_err:
                    logger.debug(f"Memory: SkillCurator record_outcome skipped: {cur_out_err}")

                resolved_entry = {
                    "date": trade_date,
                    "prediction": entry["prediction"],
                    "btst_bias": entry["btst_bias"],
                    "actual_gap_pct": actual_gap_pct,
                    "outcome": outcome_result,
                    "reflection": reflection_text,
                }
                resolved_list.append(resolved_entry)
                logger.info(
                    f"✅ Memory Phase B: {trade_date} → actual {actual_gap_pct:+.2f}% ({actual_label}) | {outcome_result}"
                )

            except Exception as e:
                logger.error(f"Memory: Failed to resolve entry {trade_date}: {e}", exc_info=True)

        return resolved_list

    # ─────────────────────────────────────────────────
    # PHASE D — Load Past Context (every run)
    # ─────────────────────────────────────────────────

