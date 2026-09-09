"""
memory/storage.py — Memory log prediction persistence (Phase A).
"""

import logging
from typing import Any

from .constants import _SEPARATOR

logger = logging.getLogger(__name__)


class MemoryStorageMixin:
    """Mixin providing Phase A prediction storage."""

    def store_prediction(
        self,
        trade_date: str,
        prediction: str,
        btst_bias: str,
        confidence: int,
        reasoning: str,
        dimension_scores: dict | None = None,
        fii_net: float | None = None,
        gift_nifty_pct: float | None = None,
        india_vix: float | None = None,
        ai_provider: str | None = None,
        btst_structure: str | None = None,
        debate_consensus: str | None = None,
        dte: int | None = None,
        fo_expiry_context: str | None = None,
        active_skills: list[str] | None = None,
    ) -> bool:
        """
        Phase A: Append a new 'pending' entry for today's 15:15 IST BTST prediction.
        Idempotent — a second call for the same trade_date is a no-op.
        Returns True if written, False if skipped (already exists).

        btst_structure:  calibrated trade size from debate committee
                         (e.g. "FULL_BTST", "HALF_QUANTITY", "HEDGED_SPREAD", "STRICT_NO_TRADE")
        debate_consensus: "UNANIMOUS" | "MAJORITY" | "SPLIT" — or None if debate skipped
        """
        # Idempotency: fast raw-text scan
        if self._log_path.exists():
            raw = self._log_path.read_text(encoding="utf-8")
            if f"[{trade_date} |" in raw and "| pending]" in raw:
                logger.info(f"Memory: entry for {trade_date} already exists, skipping Phase A.")
                return False

        tag = f"[{trade_date} | {prediction} | {btst_bias} | {confidence}% | pending]"

        # Build the reasoning block with supporting signals
        signals_parts = []
        if gift_nifty_pct is not None:
            signals_parts.append(f"GIFT Nifty: {gift_nifty_pct:+.2f}%")
        if fii_net is not None:
            signals_parts.append(f"FII Net: ₹{fii_net:+,.0f} Cr")
        if india_vix is not None:
            signals_parts.append(f"India VIX: {india_vix:.2f}")
        if dimension_scores:
            dim_summary = " | ".join(
                f"{k}: {v.get('bias', 'N/A')}"
                for k, v in dimension_scores.items()
                if isinstance(v, dict)
            )
            signals_parts.append(f"Dimensions: [{dim_summary}]")
        # Debate committee outcome (if debate ran)
        if btst_structure:
            debate_line = f"Debate Committee: {btst_structure}"
            if debate_consensus:
                debate_line += f" ({debate_consensus})"
            signals_parts.append(debate_line)
        if ai_provider:
            signals_parts.append(f"Engine: {ai_provider}")

        signals_line = "\n".join(signals_parts)
        full_reasoning = f"{reasoning}\n{signals_line}".strip()

        entry = f"{tag}\n\nREASONING:\n{full_reasoning}{_SEPARATOR}"

        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(entry)

        # Hermes FTS5 index update
        if getattr(self, "_fts", None):
            try:
                self._fts.upsert_entry(
                    trade_date=trade_date,
                    prediction=prediction,
                    btst_bias=btst_bias,
                    confidence=confidence,
                    status="pending",
                    outcome="",
                    signals_summary=signals_line.replace("\n", " | "),
                    reasoning=full_reasoning,
                    vix=india_vix,
                    gift_nifty_pct=gift_nifty_pct,
                    fii_net=fii_net,
                    btst_structure=btst_structure,
                    debate_consensus=debate_consensus,
                    ai_provider=ai_provider,
                )
            except Exception as fts_store_err:
                logger.debug(f"Memory: FTS upsert in store_prediction skipped: {fts_store_err}")
        # Hermes Skill Curator attribution
        try:
            from skills_engine import get_skills_engine
            se = get_skills_engine(history_dir=str(self._log_path.parent))
            skills_to_record = active_skills
            if skills_to_record is None:
                matched_skills = se.match_skills(
                    signals={"india_vix": india_vix, "gift_nifty_change_pct": gift_nifty_pct, "dte": dte},
                    stage1_result={"prediction": prediction, "btst_bias": btst_bias, "fo_expiry_context": fo_expiry_context}
                )
                skills_to_record = [s["name"] for s in matched_skills]
            if skills_to_record:
                se.curator.record_activations(trade_date, skills_to_record)
        except Exception as cur_err:
            logger.debug(f"Memory: SkillCurator record_activations skipped: {cur_err}")

        logger.info(f"✅ Memory Phase A: stored prediction [{trade_date}] {prediction} / {btst_bias} @ {confidence}%"
                    + (f" | Debate: {btst_structure} ({debate_consensus})" if btst_structure else ""))
        return True
