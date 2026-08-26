"""
test_institutional_radar.py — Unit tests for institutional_scraper.py

Tests:
  1. _classify_bias — text classification for bullish/bearish/rangebound
  2. _extract_nifty_levels — extracts valid NIFTY-range numbers from text
  3. _build_consensus_call — aggregates provider calls into consensus
  4. get_cached_institutional_radar — cache load/save round-trip
  5. _extract_brokerage_call — parses institution/action from article
  6. _action_from_text — brokerage action classification
"""

import json
import os
import tempfile
import time
import unittest

from institutional_scraper import (
    _classify_bias,
    _extract_nifty_levels,
    _build_consensus_call,
    _extract_brokerage_call,
    _action_from_text,
    save_institutional_radar_cache,
    load_institutional_radar_cache,
    get_cached_institutional_radar,
    _CACHE_TTL_HOURS,
)


class TestClassifyBias(unittest.TestCase):
    def test_bullish(self):
        self.assertEqual(_classify_bias("Nifty looks bullish, upside expected"), "BULLISH")

    def test_bearish(self):
        self.assertEqual(_classify_bias("Market likely to decline on selling pressure, downside risk"), "BEARISH")

    def test_rangebound(self):
        self.assertEqual(_classify_bias("Markets may remain sideways amid uncertainty"), "RANGEBOUND")

    def test_mixed_leans_bull(self):
        # More bullish keywords than bearish
        self.assertEqual(_classify_bias("bullish rally expected, buy dips, upside target"), "BULLISH")


class TestExtractNiftyLevels(unittest.TestCase):
    def test_extracts_valid_levels(self):
        text = "Support at 24,100 and resistance at 24,500. Next target 24,800."
        levels = _extract_nifty_levels(text)
        self.assertIn(24100, levels)
        self.assertIn(24500, levels)
        self.assertIn(24800, levels)

    def test_ignores_out_of_range(self):
        text = "Nifty at 100, also 50000, and 24200"
        levels = _extract_nifty_levels(text)
        self.assertNotIn(100, levels)
        self.assertNotIn(50000, levels)
        self.assertIn(24200, levels)

    def test_empty_text(self):
        self.assertEqual(_extract_nifty_levels("no numbers here"), [])


class TestBuildConsensusCall(unittest.TestCase):
    def _sample_calls(self):
        return {
            "religare": {"next_day_bias": "BULLISH", "s1": 24000, "s2": 23800, "r1": 24400, "r2": 24700, "expected_gap": "Positive"},
            "hdfc_sec": {"next_day_bias": "BULLISH", "s1": 24050, "s2": 23850, "r1": 24450, "r2": 24750, "expected_gap": "Positive"},
            "anand_rathi": {"next_day_bias": "BEARISH", "s1": 23900, "s2": 23700, "r1": 24300, "r2": 24600, "expected_gap": "Negative"},
        }

    def test_consensus_bias_majority_bull(self):
        consensus = _build_consensus_call(self._sample_calls())
        self.assertEqual(consensus["next_day_bias"], "BULLISH")

    def test_bull_pct(self):
        consensus = _build_consensus_call(self._sample_calls())
        self.assertAlmostEqual(consensus["bull_pct"], 67, delta=5)

    def test_sr_zones_are_strings(self):
        consensus = _build_consensus_call(self._sample_calls())
        # S1 zone should be a string (range or single)
        self.assertIsInstance(consensus["s1"], str)

    def test_empty_calls_returns_empty(self):
        result = _build_consensus_call({})
        self.assertEqual(result, {})


class TestActionFromText(unittest.TestCase):
    def test_buy(self):
        self.assertEqual(_action_from_text("Morgan Stanley initiates with Outperform"), "BUY")

    def test_sell(self):
        self.assertEqual(_action_from_text("Goldman Sachs downgrades HDFC Bank to Underperform"), "SELL")

    def test_hold(self):
        self.assertEqual(_action_from_text("CLSA maintains Neutral rating on Reliance"), "HOLD")

    def test_target_raised(self):
        self.assertEqual(_action_from_text("Jefferies raises price target to 2000"), "TARGET RAISED")


class TestExtractBrokerageCall(unittest.TestCase):
    def _sample_article(self):
        return {
            "title": "Morgan Stanley upgrades Reliance Industries to Outperform, target ₹3,200",
            "summary": "Morgan Stanley has raised its rating on Reliance to Outperform with a target of ₹3,200, citing strong refining margins.",
            "published": "Tue, 26 Aug 2026",
            "link": "https://example.com/reliance-ms",
        }

    def test_institution_detected(self):
        call = _extract_brokerage_call(self._sample_article())
        self.assertIsNotNone(call)
        self.assertEqual(call["institution"], "Morgan Stanley")

    def test_stock_detected(self):
        call = _extract_brokerage_call(self._sample_article())
        self.assertEqual(call["stock_symbol"], "RELIANCE")

    def test_action_is_buy(self):
        call = _extract_brokerage_call(self._sample_article())
        self.assertIn("BUY", call["action"].upper())

    def test_target_price_extracted(self):
        call = _extract_brokerage_call(self._sample_article())
        self.assertEqual(call["target_price"], 3200)

    def test_no_institution_returns_none(self):
        article = {"title": "Markets open lower today", "summary": "Nifty falls 100 points."}
        result = _extract_brokerage_call(article)
        self.assertIsNone(result)


class TestCacheRoundTrip(unittest.TestCase):
    def test_save_and_load(self):
        sample = {
            "fetched_ts": time.time(),
            "fetched_at_ist": "26 Aug 2026, 08:30 AM IST",
            "consensus_bias": "BULLISH",
            "bull_pct": 67,
            "provider_calls": {},
            "brokerage_calls": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            save_institutional_radar_cache(sample, tmpdir)
            loaded = load_institutional_radar_cache(tmpdir)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["consensus_bias"], "BULLISH")

    def test_stale_cache_returns_none(self):
        sample = {
            "fetched_ts": time.time() - (_CACHE_TTL_HOURS + 1) * 3600,
            "fetched_at_ist": "Old",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            save_institutional_radar_cache(sample, tmpdir)
            loaded = load_institutional_radar_cache(tmpdir)
        self.assertIsNone(loaded)

    def test_get_cached_uses_fresh_cache(self):
        sample = {
            "fetched_ts": time.time(),
            "fetched_at_ist": "26 Aug 2026, 08:30 AM IST",
            "consensus_bias": "BEARISH",
            "bull_pct": 20,
            "provider_calls": {},
            "brokerage_calls": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            save_institutional_radar_cache(sample, tmpdir)
            result = get_cached_institutional_radar(tmpdir, force_refresh=False)
        self.assertEqual(result["consensus_bias"], "BEARISH")


if __name__ == "__main__":
    unittest.main(verbosity=2)
