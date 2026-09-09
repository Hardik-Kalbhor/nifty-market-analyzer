"""
memory_fts/sync.py — Markdown log ingestion and atomic database upserts.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class FTSAutoSyncMixin:
    """Mixin providing markdown log parsing and database synchronization."""

    def upsert_entry(
        self,
        trade_date: str,
        prediction: str,
        btst_bias: str,
        confidence: int = 50,
        status: str = "pending",
        outcome: str = "",
        actual_gap_pct: float | None = None,
        regime: str = "",
        news_catalysts: str = "",
        signals_summary: str = "",
        reflection: str = "",
        reasoning: str = "",
        vix: float | None = None,
        gift_nifty_pct: float | None = None,
        fii_net: float | None = None,
        btst_structure: str | None = None,
        debate_consensus: str | None = None,
        ai_provider: str | None = None,
    ) -> bool:
        """
        Upsert a memory record atomically into both metadata and FTS5 tables.
        Returns True on success.
        """
        now_utc = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = None
            try:
                conn = self._get_connection()
                with conn:
                    # 1. Update metadata table
                    conn.execute("""
                        INSERT INTO nifty_memories_meta (
                            trade_date, prediction, btst_bias, confidence, status,
                            outcome, actual_gap_pct, vix, gift_nifty_pct, fii_net,
                            btst_structure, debate_consensus, ai_provider, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(trade_date) DO UPDATE SET
                            prediction = excluded.prediction,
                            btst_bias = excluded.btst_bias,
                            confidence = excluded.confidence,
                            status = excluded.status,
                            outcome = excluded.outcome,
                            actual_gap_pct = excluded.actual_gap_pct,
                            vix = coalesce(excluded.vix, nifty_memories_meta.vix),
                            gift_nifty_pct = coalesce(excluded.gift_nifty_pct, nifty_memories_meta.gift_nifty_pct),
                            fii_net = coalesce(excluded.fii_net, nifty_memories_meta.fii_net),
                            btst_structure = coalesce(excluded.btst_structure, nifty_memories_meta.btst_structure),
                            debate_consensus = coalesce(excluded.debate_consensus, nifty_memories_meta.debate_consensus),
                            ai_provider = coalesce(excluded.ai_provider, nifty_memories_meta.ai_provider),
                            updated_at = excluded.updated_at;
                    """, (
                        trade_date, prediction, btst_bias, confidence, status,
                        outcome, actual_gap_pct, vix, gift_nifty_pct, fii_net,
                        btst_structure, debate_consensus, ai_provider, now_utc
                    ))

                    # 2. Delete existing FTS entry if any, then insert updated row
                    conn.execute("DELETE FROM nifty_memories_fts WHERE trade_date = ?;", (trade_date,))
                    conn.execute("""
                        INSERT INTO nifty_memories_fts (
                            trade_date, prediction, btst_bias, outcome, regime,
                            news_catalysts, signals_summary, reflection, reasoning
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (
                        trade_date,
                        prediction or "",
                        btst_bias or "",
                        outcome or "",
                        regime or "",
                        news_catalysts or "",
                        signals_summary or "",
                        reflection or "",
                        reasoning or "",
                    ))
                return True
            except Exception as e:
                logger.warning(f"NiftyMemoryFTS upsert_entry failed for {trade_date}: {e}")
                return False
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

    def _auto_sync_from_markdown(self) -> int:
        """
        Parses history/memory_log.md and syncs any records missing in FTS5.
        Runs once on startup to ensure historical logs are completely indexed.
        """
        md_file = self._history_dir / "memory_log.md"
        if not md_file.exists():
            return 0

        synced_count = 0
        try:
            raw_text = md_file.read_text(encoding="utf-8")
            blocks = [b.strip() for b in raw_text.split("\n\n<!-- ENTRY_END -->\n\n") if b.strip()]

            tag_re = re.compile(
                r"^\[(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})"
                r"\s*\|\s*(?P<prediction>GAP UP|GAP DOWN|FLAT)"
                r"\s*\|\s*(?P<btst_bias>BUY CE|BUY PE|NO TRADE)"
                r"\s*\|\s*(?P<confidence>[0-9]+)%"
                r"\s*\|\s*(?P<status>[^\]]+)\]$",
                re.IGNORECASE,
            )
            reasoning_re = re.compile(r"REASONING:\n(.*?)(?=\nOUTCOME:|\nREFLECTION:|\Z)", re.DOTALL)
            outcome_re = re.compile(r"OUTCOME:\n(.*?)(?=\nREFLECTION:|\Z)", re.DOTALL)
            reflection_re = re.compile(r"REFLECTION:\n(.*?)$", re.DOTALL)

            for block in blocks:
                lines = block.splitlines()
                if not lines:
                    continue
                tag_m = tag_re.match(lines[0].strip())
                if not tag_m:
                    continue

                trade_date = tag_m.group("date")
                pred = tag_m.group("prediction").upper()
                bias = tag_m.group("btst_bias").upper()
                conf = int(tag_m.group("confidence"))
                status = tag_m.group("status").strip().lower()

                reasoning_m = reasoning_re.search(block)
                reasoning = reasoning_m.group(1).strip() if reasoning_m else ""

                outcome_m = outcome_re.search(block)
                outcome = outcome_m.group(1).strip() if outcome_m else ""

                reflection_m = reflection_re.search(block)
                reflection = reflection_m.group(1).strip() if reflection_m else ""

                # Extract signal cues from reasoning block
                vix_m = re.search(r"India VIX:\s*([0-9.]+)", reasoning)
                vix = float(vix_m.group(1)) if vix_m else None

                gift_m = re.search(r"GIFT Nifty:\s*([+-]?[0-9.]+)%", reasoning)
                gift_pct = float(gift_m.group(1)) if gift_m else None

                fii_m = re.search(r"FII Net:\s*₹?([+-]?[0-9,]+)", reasoning)
                fii_net = float(fii_m.group(1).replace(",", "")) if fii_m else None

                # Support both "Actual: +0.45%" and "Actual open: 24,200 (+0.45%)"
                actual_gap_m = re.search(r"(?:Actual(?: open)?:\s*.*?|\()([+-]?[0-9.]+)%", outcome)
                actual_gap = float(actual_gap_m.group(1)) if actual_gap_m else None

                # Derive basic regime
                regime_parts = []
                if vix:
                    regime_parts.append("HIGH_VIX" if vix > 16.0 else "LOW_VIX" if vix < 12.5 else "MOD_VIX")
                if fii_net:
                    regime_parts.append("FII_BUY" if fii_net > 500 else "FII_SELL" if fii_net < -500 else "FII_NEUT")
                regime_str = "|".join(regime_parts)

                self.upsert_entry(
                    trade_date=trade_date,
                    prediction=pred,
                    btst_bias=bias,
                    confidence=conf,
                    status=status,
                    outcome=outcome,
                    actual_gap_pct=actual_gap,
                    regime=regime_str,
                    signals_summary=f"VIX: {vix}, GIFT: {gift_pct}%, FII: {fii_net}",
                    reflection=reflection,
                    reasoning=reasoning,
                    vix=vix,
                    gift_nifty_pct=gift_pct,
                    fii_net=fii_net,
                )
                synced_count += 1

            if synced_count > 0:
                logger.info(f"NiftyMemoryFTS auto-synced {synced_count} entries from memory_log.md")
        except Exception as e:
            logger.warning(f"NiftyMemoryFTS _auto_sync_from_markdown warning: {e}")

        return synced_count
