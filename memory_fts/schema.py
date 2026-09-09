"""
memory_fts/schema.py — SQLite connection management and FTS5 schema initialization.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


class FTSConnectionMixin:
    """Mixin providing SQLite connection setup and database schema initialization."""

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
