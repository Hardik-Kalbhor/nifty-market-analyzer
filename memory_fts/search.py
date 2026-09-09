"""
memory_fts/search.py — BM25 text search, analog retrieval, and prompt formatting.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any

from .constants import _sanitize_fts_query

logger = logging.getLogger(__name__)


class FTSSearchMixin:
    """Mixin providing full-text search, market analog finding, and prompt formatting."""

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
