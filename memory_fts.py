"""
memory_fts.py — SQLite FTS5 Hybrid Memory Recall Engine for NIFTY Agents.

Adapted from the Nous Research Hermes Agent memory retrieval architecture:
  1. Full-Text Search (SQLite FTS5) with Porter stemming and BM25 ranking.
  2. Auto-indexing of existing historical records from memory_log.md.
  3. Regime-conditioned & catalyst-driven analog search for live trading runs.
  4. Thread-safe execution with WAL mode for concurrent multi-agent read access.
  5. Guaranteed connection closure and robust error handling.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Global singleton cache keyed by db directory path
_FTS_INSTANCES: dict[str, NiftyMemoryFTS] = {}
_INSTANCES_LOCK = threading.Lock()


def _sanitize_fts_query(text: str) -> str:
    """
    Sanitize raw free-form text or headlines into a safe SQLite FTS5 query string.
    - Strips non-alphanumeric characters.
    - Retains 2-letter financial/options terms (ce, pe, oi, it, up).
    - Quotes every token (e.g. "term") to prevent FTS5 syntax errors from reserved words (not, near, and, or).
    - Joins tokens with OR for broad BM25 recall.
    """
    if not text:
        return ""

    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", text)
    raw_tokens = [t.strip().lower() for t in cleaned.split() if t.strip()]

    # Critical financial & options abbreviations that must not be discarded
    financial_short_terms = {"ce", "pe", "oi", "it", "up"}
    stop_words = {
        "the", "and", "for", "with", "this", "that", "from", "are", "was", "will",
        "has", "have", "had", "its", "into", "been", "also", "about", "after", "over",
        "all", "any", "not", "near", "but", "out"
    }

    meaningful = []
    for tok in raw_tokens:
        if tok in stop_words:
            continue
        if len(tok) >= 3 or tok in financial_short_terms:
            meaningful.append(tok)

    if not meaningful:
        return ""

    # Wrap each token in double quotes so FTS5 treats it as a literal word
    quoted_tokens = [f'"{tok}"' for tok in meaningful[:12]]
    return " OR ".join(quoted_tokens)


class NiftyMemoryFTS:
    """SQLite FTS5-backed episodic memory and analog retrieval engine."""

    def __init__(self, history_dir: str | None = None):
        if history_dir is None:
            base = os.path.join(os.path.dirname(__file__), "history")
        else:
            base = history_dir

        try:
            os.makedirs(base, exist_ok=True)
            self._db_path = Path(base) / "memory_fts.db"
        except (OSError, PermissionError):
            fallback = "/tmp/history"
            os.makedirs(fallback, exist_ok=True)
            self._db_path = Path(fallback) / "memory_fts.db"

        self._lock = threading.Lock()
        self._history_dir = self._db_path.parent
        self._init_db()
        self._auto_sync_from_markdown()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a thread-safe connection with WAL mode and fallback on permission error."""
        try:
            conn = sqlite3.connect(
                str(self._db_path),
                timeout=10.0,
                check_same_thread=False,
            )
        except (sqlite3.OperationalError, OSError, PermissionError):
            fallback = Path("/tmp/history") / "memory_fts.db"
            os.makedirs(str(fallback.parent), exist_ok=True)
            self._db_path = fallback
            conn = sqlite3.connect(
                str(self._db_path),
                timeout=10.0,
                check_same_thread=False,
            )

        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
        except Exception:
            pass
        return conn

    def _init_db(self) -> None:
        """Initialize the SQLite tables (FTS5 virtual table + metadata table)."""
        with self._lock:
            conn = None
            try:
                conn = self._get_connection()
                with conn:
                    # 1. Virtual table for BM25 text search
                    conn.execute("""
                        CREATE VIRTUAL TABLE IF NOT EXISTS nifty_memories_fts USING fts5(
                            trade_date UNINDEXED,
                            prediction,
                            btst_bias,
                            outcome,
                            regime,
                            news_catalysts,
                            signals_summary,
                            reflection,
                            reasoning,
                            tokenize = 'porter unicode61'
                        );
                    """)

                    # 2. Metadata table for structured attributes & numeric filters
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS nifty_memories_meta (
                            trade_date TEXT PRIMARY KEY,
                            prediction TEXT,
                            btst_bias TEXT,
                            confidence INTEGER,
                            status TEXT,
                            outcome TEXT,
                            actual_gap_pct REAL,
                            vix REAL,
                            gift_nifty_pct REAL,
                            fii_net REAL,
                            btst_structure TEXT,
                            debate_consensus TEXT,
                            ai_provider TEXT,
                            updated_at TEXT
                        );
                    """)
                logger.debug(f"NiftyMemoryFTS initialized at {self._db_path}")
            except Exception as e:
                logger.error(f"Failed to initialize SQLite FTS5 database: {e}", exc_info=True)
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

    # ─────────────────────────────────────────────────────────────────────────
    # Ingestion & Auto-Sync
    # ─────────────────────────────────────────────────────────────────────────

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

    # ─────────────────────────────────────────────────────────────────────────
    # Search & Analog Retrieval (Hermes BM25 Core)
    # ─────────────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        limit: int = 3,
        outcome_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Execute BM25 ranked full-text search across all memories.
        `outcome_filter`: optional 'CORRECT', 'WRONG', or 'PARTIAL' to focus on specific lessons.
        """
        sanitized = _sanitize_fts_query(query)
        if not sanitized:
            return []

        fts_query = sanitized
        if outcome_filter:
            clean_filter = re.sub(r"[^a-zA-Z]", "", outcome_filter).upper()
            if clean_filter:
                fts_query = f'outcome: "{clean_filter}" AND ({sanitized})'

        results = []
        conn = None
        try:
            conn = self._get_connection()
            # SQLite FTS5 rank ordering (lower rank value = stronger BM25 relevance)
            sql = """
                SELECT
                    f.trade_date,
                    f.prediction,
                    f.btst_bias,
                    f.outcome,
                    f.regime,
                    f.news_catalysts,
                    f.signals_summary,
                    f.reflection,
                    f.reasoning,
                    rank as bm25_score,
                    m.confidence,
                    m.actual_gap_pct,
                    m.vix,
                    m.gift_nifty_pct,
                    m.fii_net,
                    m.btst_structure
                FROM nifty_memories_fts f
                LEFT JOIN nifty_memories_meta m ON f.trade_date = m.trade_date
                WHERE nifty_memories_fts MATCH ?
                ORDER BY rank
                LIMIT ?;
            """
            cursor = conn.execute(sql, (fts_query, limit))
            for row in cursor.fetchall():
                results.append(dict(row))
        except sqlite3.OperationalError as op_err:
            logger.warning(f"NiftyMemoryFTS search operational error with query '{fts_query}': {op_err}")
        except Exception as e:
            logger.error(f"NiftyMemoryFTS search error: {e}", exc_info=True)
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        return results

    def find_analogs(
        self,
        signals: dict[str, Any] | None = None,
        news_items: list[dict[str, Any]] | None = None,
        stage1_result: dict[str, Any] | None = None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """
        Find historical market days that are analogous to the current trading environment.
        Synthesizes an adaptive query using:
          - Dominant market indicators (VIX regime, FII direction, GIFT Nifty direction)
          - Salient keywords extracted from breaking news headlines
          - Proposed BTST direction / stage 1 bias
        """
        query_terms: list[str] = []

        # 1. Indicator-based tokens
        if signals:
            vix = signals.get("india_vix")
            if vix is not None:
                try:
                    vix_f = float(vix)
                    if vix_f >= 16.5:
                        query_terms.extend(["high vix", "elevated volatility", "iv crush"])
                    elif vix_f <= 12.5:
                        query_terms.extend(["low vix", "range bound"])
                except (ValueError, TypeError):
                    pass

            gift = signals.get("gift_nifty_change_pct")
            if gift is not None:
                try:
                    gift_f = float(gift)
                    if abs(gift_f) >= 0.35:
                        query_terms.append("gift nifty momentum" if gift_f > 0 else "gift nifty gap down")
                except (ValueError, TypeError):
                    pass

            pcr = signals.get("pcr")
            if pcr is not None:
                try:
                    pcr_f = float(pcr)
                    if pcr_f <= 0.65:
                        query_terms.append("oversold short covering")
                    elif pcr_f >= 1.35:
                        query_terms.append("overbought call resistance")
                except (ValueError, TypeError):
                    pass

        # 2. News Catalyst extraction (scan first 8 headlines for high-impact themes)
        if news_items:
            key_themes = [
                "crude", "oil", "rbi", "fed", "inflation", "cpi", "budget", "election",
                "tariff", "war", "conflict", "hike", "cut", "rally", "selloff", "earnings",
                "hdfc", "reliance", "tcs", "infy", "adani", "rupee"
            ]
            found_themes = set()
            for it in news_items[:8]:
                headline = (it.get("headline") or it.get("title") or "").lower()
                for theme in key_themes:
                    if theme in headline:
                        found_themes.add(theme)
            query_terms.extend(list(found_themes)[:4])

        # 3. Stage 1 proposed trade bias
        if stage1_result:
            bias = stage1_result.get("btst_bias")
            pred = stage1_result.get("prediction")
            if bias and bias != "NO TRADE":
                query_terms.append(bias)
            if pred and pred != "FLAT":
                query_terms.append(pred)

        composite_query = " ".join(query_terms).strip()
        if not composite_query:
            composite_query = "nifty gap momentum FII institutional"

        analogs = self.search(composite_query, limit=limit)

        # Relaxed fallback: if strict composite returns 0 and we had multiple terms, try primary cues
        if not analogs and len(query_terms) > 2:
            relaxed_query = " ".join(query_terms[:2])
            analogs = self.search(relaxed_query, limit=limit)

        return analogs

    def format_analogs_prompt(self, analogs: list[dict[str, Any]], max_items: int = 3) -> str:
        """
        Format retrieved FTS5 analogs into an injection-ready, token-efficient Markdown block.
        """
        if not analogs:
            return ""

        lines = [
            "🏛️ HISTORICAL MARKET ANALOGS (Hermes FTS5 Recall):",
            "The following past market sessions shared similar catalysts or microstructure signals:",
        ]

        for i, a in enumerate(analogs[:max_items], 1):
            date_str = a.get("trade_date", "Past Date")
            pred = a.get("prediction", "N/A")
            bias = a.get("btst_bias", "N/A")
            conf = a.get("confidence") or 50
            outcome = a.get("outcome", "Unknown")
            actual_gap = a.get("actual_gap_pct")
            actual_str = f"{actual_gap:+.2f}%" if actual_gap is not None else "N/A"
            reflection = (a.get("reflection") or a.get("reasoning") or "").strip()
            signals_summary = a.get("signals_summary", "").strip()

            line_entry = (
                f"  {i}. [{date_str}] Predicted: {pred} ({bias} @ {conf}%) | Actual Gap: {actual_str} | Outcome: {outcome}\n"
            )
            if signals_summary:
                line_entry += f"     Signals: {signals_summary}\n"
            if reflection:
                # Truncate reflection to max 2 sentences to preserve prompt budget
                short_refl = ". ".join(reflection.split(". ")[:2]).strip()
                if not short_refl.endswith("."):
                    short_refl += "."
                line_entry += f"     Precedent Lesson: {short_refl}\n"

            lines.append(line_entry)

        lines.append("Use these historical precedents to calibrate trade sizing and identify potential failure traps.")
        return "\n".join(lines).strip()


def get_memory_fts(history_dir: str | None = None) -> NiftyMemoryFTS:
    """Get or initialize the NiftyMemoryFTS singleton for the given directory."""
    global _FTS_INSTANCES
    key = os.path.abspath(history_dir) if history_dir else "default"
    with _INSTANCES_LOCK:
        if key not in _FTS_INSTANCES:
            _FTS_INSTANCES[key] = NiftyMemoryFTS(history_dir)
        return _FTS_INSTANCES[key]
