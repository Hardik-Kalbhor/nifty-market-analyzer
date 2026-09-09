"""
test_memory_fts.py — Unit Tests for SQLite FTS5 Hybrid Memory Recall Engine.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from memory_fts import NiftyMemoryFTS, _sanitize_fts_query
from memory_log import NiftyMemoryLog


class TestMemoryFTS(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.fts = NiftyMemoryFTS(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_init_and_tables(self):
        """Verify FTS5 virtual table and metadata tables are created."""
        conn = self.fts._get_connection()
        tables = [row["name"] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        ).fetchall()]
        conn.close()

        self.assertIn("nifty_memories_fts", tables)
        self.assertIn("nifty_memories_meta", tables)

    def test_query_sanitization(self):
        """Verify query sanitizer strips FTS5 syntax control chars and prevents syntax errors."""
        bad_query = 'NIFTY: 50 * "Crude oil" dropped -2.5% ^ (war OR conflict) NOT peace'
        sanitized = _sanitize_fts_query(bad_query)
        self.assertTrue(len(sanitized) > 0)
        self.assertNotIn("*", sanitized)
        self.assertNotIn(":", sanitized)
        self.assertNotIn("^", sanitized)
        self.assertNotIn("(", sanitized)
        self.assertNotIn(")", sanitized)

        # Verify that SQLite FTS5 can parse and execute this sanitized query cleanly
        conn = self.fts._get_connection()
        try:
            cursor = conn.execute("SELECT * FROM nifty_memories_fts WHERE nifty_memories_fts MATCH ?;", (sanitized,))
            self.assertIsInstance(cursor.fetchall(), list)
        finally:
            conn.close()

        # Empty or single char queries return empty string
        self.assertEqual(_sanitize_fts_query(""), "")
        self.assertEqual(_sanitize_fts_query("a b c"), "")

    def test_upsert_and_bm25_search(self):
        """Verify upserting records and retrieving them with BM25 keyword matching."""
        self.fts.upsert_entry(
            trade_date="2026-08-10",
            prediction="GAP DOWN",
            btst_bias="BUY PE",
            confidence=80,
            status="resolved",
            outcome="CORRECT",
            actual_gap_pct=-0.45,
            regime="HIGH_VIX|FII_BEAR",
            news_catalysts="Crude oil spike following Middle East conflict escalation",
            signals_summary="VIX: 18.5, GIFT: -0.40%, FII: -3100 Cr",
            reflection="Overnight geopolitical escalation and surging Brent crude caused sustained gap down.",
            reasoning="Brent crude jumped +4% and FII sold heavily ahead of US CPI print.",
            vix=18.5,
            gift_nifty_pct=-0.40,
            fii_net=-3100.0,
        )

        self.fts.upsert_entry(
            trade_date="2026-08-11",
            prediction="GAP UP",
            btst_bias="BUY CE",
            confidence=75,
            status="resolved",
            outcome="CORRECT",
            actual_gap_pct=0.55,
            regime="LOW_VIX|FII_BULL",
            news_catalysts="IT earnings rally led by TCS and Infosys margin expansion",
            signals_summary="VIX: 12.1, GIFT: +0.60%, FII: +2400 Cr",
            reflection="Tech rally in Nasdaq carried through into Indian IT heavyweights.",
            reasoning="Strong ADR gains and domestic institutional support.",
            vix=12.1,
            gift_nifty_pct=0.60,
            fii_net=2400.0,
        )

        # Search for crude oil shock
        crude_results = self.fts.search("crude oil conflict escalation", limit=2)
        self.assertEqual(len(crude_results), 1)
        self.assertEqual(crude_results[0]["trade_date"], "2026-08-10")
        self.assertEqual(crude_results[0]["prediction"], "GAP DOWN")

        # Search for IT earnings
        it_results = self.fts.search("infosys earnings tech rally", limit=2)
        self.assertEqual(len(it_results), 1)
        self.assertEqual(it_results[0]["trade_date"], "2026-08-11")
        self.assertEqual(it_results[0]["prediction"], "GAP UP")

    def test_find_analogs_from_market_state(self):
        """Verify find_analogs correctly constructs an adaptive query from signals and news."""
        self.fts.upsert_entry(
            trade_date="2026-07-15",
            prediction="GAP DOWN",
            btst_bias="BUY PE",
            confidence=85,
            status="resolved",
            outcome="CORRECT",
            actual_gap_pct=-0.60,
            signals_summary="VIX: 19.2, GIFT: -0.55%",
            reflection="High VIX coupled with negative GIFT Nifty resulted in sharp opening drop.",
            reasoning="High VIX elevated volatility risk.",
        )

        mock_signals = {
            "india_vix": 18.2,
            "gift_nifty_change_pct": -0.45,
            "pcr": 0.60,
        }
        mock_news = [
            {"headline": "Crude oil crosses $85 as supply concerns resurface"},
            {"headline": "Global markets trade cautious ahead of Fed interest rate verdict"},
        ]
        mock_stage1 = {
            "prediction": "GAP DOWN",
            "btst_bias": "BUY PE",
        }

        analogs = self.fts.find_analogs(
            signals=mock_signals,
            news_items=mock_news,
            stage1_result=mock_stage1,
            limit=2,
        )

        self.assertGreaterEqual(len(analogs), 1)
        self.assertEqual(analogs[0]["trade_date"], "2026-07-15")

        prompt_str = self.fts.format_analogs_prompt(analogs)
        self.assertIn("HISTORICAL MARKET ANALOGS", prompt_str)
        self.assertIn("2026-07-15", prompt_str)
        self.assertIn("GAP DOWN", prompt_str)

    def test_auto_sync_from_markdown(self):
        """Verify that existing memory_log.md entries are automatically synced into FTS5."""
        md_path = Path(self.test_dir) / "memory_log.md"
        sample_md = (
            "[2026-06-01 | GAP UP | BUY CE | 72% | resolved]\n\n"
            "REASONING:\n"
            "GIFT Nifty: +0.45%\n"
            "FII Net: ₹+1,850 Cr\n"
            "India VIX: 13.20\n"
            "Heavy foreign inflows into private banks.\n\n"
            "OUTCOME:\n"
            "Actual: +0.48% (GAP UP). Profit target achieved.\n\n"
            "REFLECTION:\n"
            "Banking leadership with GIFT Nifty momentum provided strong followthrough."
            "\n\n<!-- ENTRY_END -->\n\n"
        )
        md_path.write_text(sample_md, encoding="utf-8")

        # Create new FTS instance targeting this folder
        fts2 = NiftyMemoryFTS(self.test_dir)
        matches = fts2.search("banking private foreign inflows", limit=2)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["trade_date"], "2026-06-01")
        self.assertEqual(matches[0]["prediction"], "GAP UP")

    def test_memory_log_integration(self):
        """Verify end-to-end integration between NiftyMemoryLog and NiftyMemoryFTS."""
        mem = NiftyMemoryLog(history_dir=self.test_dir)

        # 1. Phase A: Store prediction
        written = mem.store_prediction(
            trade_date="2026-09-08",
            prediction="GAP UP",
            btst_bias="BUY CE",
            confidence=70,
            reasoning="Reliance earnings positive and GIFT Nifty indicates gap up open.",
            gift_nifty_pct=0.35,
            fii_net=1200.0,
            india_vix=13.5,
            btst_structure="HALF_QUANTITY",
            debate_consensus="MAJORITY",
        )
        self.assertTrue(written)

        # Check FTS indexing
        search_res = mem.search_memories("Reliance earnings positive")
        self.assertEqual(len(search_res), 1)
        self.assertEqual(search_res[0]["trade_date"], "2026-09-08")

        # 2. Stats should include FTS metadata
        stats = mem.get_stats()
        self.assertIn("fts", stats)
        self.assertEqual(stats["fts"]["status"], "active")
        self.assertGreaterEqual(stats["fts"]["indexed_entries"], 1)

        # 3. Phase D: load_past_context with market signals
        ctx = mem.load_past_context(
            current_signals={"india_vix": 13.5, "gift_nifty_change_pct": 0.35},
            stage1_result={"prediction": "GAP UP", "btst_bias": "BUY CE"},
        )
        self.assertIn("HISTORICAL MARKET ANALOGS", ctx)
        self.assertIn("2026-09-08", ctx)

    def test_reserved_fts_keywords(self):
        """Verify queries with FTS5 reserved keywords (NOT, NEAR, AND, OR) never cause operational errors."""
        tricky_queries = [
            "NOT banana",
            "near expiry",
            "and also or",
            "war NOT peace",
            "bank NEAR rally",
            "NOT",
            "AND",
            "OR",
            "NEAR",
        ]
        for q in tricky_queries:
            results = self.fts.search(q)
            self.assertIsInstance(results, list)

    def test_short_options_terms(self):
        """Verify 2-letter tokens like 'ce', 'pe', 'oi' are preserved and searchable."""
        sanitized = _sanitize_fts_query("BUY CE options oi unwinding")
        self.assertIn('"ce"', sanitized)
        self.assertIn('"oi"', sanitized)

        self.fts.upsert_entry(
            trade_date="2026-05-10",
            prediction="GAP UP",
            btst_bias="BUY CE",
            news_catalysts="Call options unwinding at 24500 CE strike",
        )
        res = self.fts.search("CE options")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["trade_date"], "2026-05-10")

    def test_alternate_gap_regex_format(self):
        """Verify markdown sync correctly parses 'Actual open: 24,200 (+0.45%)' format."""
        md_path = Path(self.test_dir) / "memory_log.md"
        sample_md = (
            "[2026-04-15 | GAP UP | BUY CE | 75% | resolved]\n\n"
            "REASONING:\n"
            "GIFT Nifty: +0.30%\n"
            "India VIX: 14.1\n\n"
            "OUTCOME:\n"
            "Actual open: 24,310.50 (+0.42%) → GAP UP ✅ CORRECT\n\n"
            "REFLECTION:\n"
            "Accurate gap call.\n\n<!-- ENTRY_END -->\n\n"
        )
        md_path.write_text(sample_md, encoding="utf-8")
        fts3 = NiftyMemoryFTS(self.test_dir)
        res = fts3.search("GAP UP", limit=1)
        self.assertEqual(len(res), 1)
        self.assertAlmostEqual(res[0]["actual_gap_pct"], 0.42)

    def test_concurrent_multithreaded_access(self):
        """Verify WAL mode allows concurrent threads to read and write without database lock errors."""
        import concurrent.futures

        def worker(i: int):
            date_str = f"2026-01-{i:02d}"
            # Write
            self.fts.upsert_entry(
                trade_date=date_str,
                prediction="GAP UP" if i % 2 == 0 else "GAP DOWN",
                btst_bias="BUY CE" if i % 2 == 0 else "BUY PE",
                news_catalysts=f"Worker event {i} market catalysts",
            )
            # Read
            res = self.fts.search(f"Worker event {i}")
            return len(res) >= 1

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker, i) for i in range(1, 15)]
            results = [f.result(timeout=10) for f in futures]

        self.assertTrue(all(results))

    def test_none_confidence_formatting(self):
        """Verify that a None confidence value formats cleanly without rendering 'None%'."""
        analogs = [{
            "trade_date": "2026-03-01",
            "prediction": "GAP UP",
            "btst_bias": "BUY CE",
            "confidence": None,
            "outcome": "CORRECT",
            "actual_gap_pct": 0.35,
            "reflection": "Strong opening.",
        }]
        prompt_str = self.fts.format_analogs_prompt(analogs)
        self.assertNotIn("None%", prompt_str)
        self.assertIn("50%", prompt_str)


if __name__ == "__main__":
    unittest.main()

