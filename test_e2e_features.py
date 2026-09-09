"""
test_e2e_features.py — Comprehensive End-to-End Feature Verification Test Suite.

Verifies all 15 core architectural capabilities of the NIFTY Market Analyzer:
  1. News Scraping & 4-Layer NLP Sentiment Engine
  2. Market Microstructure & Institutional Radar
  3. Stage 1 Gap Prediction & Hard Confluence Arbiter
  4. CogniGraph 3-Tier Causal Knowledge Graph
  5. SQLite FTS5 Hybrid Historical Analog Recall
  6. AgentSkills Procedural Trading Playbooks Engine
  7. Dynamic Catalyst Specialists & Subagent Delegation
  8. Stage 2 Multi-Persona Risk Debate Committee & Gemini Judge
  9. Intraday Pattern & ORB 3-Analyst Debate Committee
 10. Live Exit Advisor & Sub-5ms Fast-Path Circuit Breakers
 11. Complete MemoryLog Closed-Loop (Phase A -> Resolution -> Reflection)
 12. Hermes 20:00 IST Post-Market Dreaming Memory Consolidation
 13. Trajectory Dataset Exporter (ShareGPT & Hermes Formats)
 14. AutoScheduler 6-Daily-Run Cadence
 15. Flask REST API End-to-End Integration Suite
"""

import json
import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

# Core imports
from analyzer import (
    analyze_news,
    _score_sentiment,
    _is_negated,
    BULLISH_SYNONYMS,
    BEARISH_SYNONYMS,
)
from cognigraph import CogniGraph, get_cognigraph
from memory_fts import NiftyMemoryFTS, _sanitize_fts_query
from skills_engine import SkillsEngine, _parse_frontmatter
from dynamic_subagents import (
    SPECIALIST_SPECS,
    match_dynamic_subagents,
    evaluate_dynamic_subagents,
    format_specialists_prompt,
)
from debate_engine import run_debate, run_intraday_debate
from exit_fast_path import evaluate_fast_path, generate_rule_based_fallback
from exit_analyzer import evaluate_exit_with_ai, _resolve_dimension_conflict
from memory_log import NiftyMemoryLog
from dreaming_engine import DreamingEngine
from trajectory_exporter import TrajectoryExporter
from auto_scheduler import init_scheduler
from server import app


class TestEndToEndSystemFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="nifty_e2e_")
        cls.history_dir = os.path.join(cls.temp_dir, "history")
        cls.skills_dir = os.path.join(cls.temp_dir, "skills")
        os.makedirs(cls.history_dir, exist_ok=True)
        os.makedirs(cls.skills_dir, exist_ok=True)

        # Copy existing skills to temp directory
        src_skills = os.path.join(os.path.dirname(__file__), "skills")
        if os.path.exists(src_skills):
            for item in os.listdir(src_skills):
                s = os.path.join(src_skills, item)
                d = os.path.join(cls.skills_dir, item)
                if os.path.isdir(s):
                    shutil.copytree(s, d)

        # Patch IST time to 11:30 AM so deterministic tests are immune to real-world 15:15 market close cutoffs
        from datetime import datetime
        import pytz
        from unittest.mock import patch
        cls.time_patcher = patch("exit_fast_path._get_now_ist", return_value=datetime(2026, 9, 9, 11, 30, tzinfo=pytz.timezone("Asia/Kolkata")))
        cls.time_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls.time_patcher.stop()
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    # ── 1. News Scraping & 4-Layer NLP Sentiment Engine ────────────────────────
    def test_feature_01_nlp_sentiment_engine(self):
        """Feature 1: 4-Layer NLP sentiment analysis with regex, synonyms, keywords & negation."""
        # 1.1 Direct keyword / regex
        bull_score, bear_score, bull_matches, bear_matches = _score_sentiment("Markets rally on strong quarterly profits")
        self.assertGreater(bull_score, bear_score)
        self.assertTrue(any("rally" in f.lower() or "profit" in f.lower() for f in bull_matches))

        # 1.2 Synonym expansion ("crude tumbles" -> mapped to crude fall/bullish for India)
        bull_syn, bear_syn, _, _ = _score_sentiment("Crude tumbles as oil prices drop")
        self.assertGreater(bull_syn, 0)

        # 1.3 Negation detection ("unlikely to hike" flips sentiment)
        text = "RBI is unlikely to hike interest rates"
        idx = text.find("hike")
        has_neg = _is_negated(text, idx)
        self.assertTrue(has_neg)

        # 1.4 Full news analysis weighting
        mock_news = [
            {"headline": "HDFC Bank posts 20% surge in net profit", "category": "Corporate", "published": datetime.now().isoformat(), "source": "Livemint"},
            {"headline": "Global tech stocks jump on strong earnings", "category": "International", "published": datetime.now().isoformat(), "source": "ET"},
            {"headline": "Crude oil plunges to 6-month lows", "category": "Commodity", "published": datetime.now().isoformat(), "source": "Google News"},
        ]
        res = analyze_news(
            news_items=mock_news,
            gift_nifty_change_pct=0.45,
            india_vix=12.8,
            india_vix_change_pct=-2.5,
            pcr=1.15,
            global_market_changes={"sp500": 0.8, "nasdaq": 1.2},
            fii_net_cr=1800.0,
        )
        self.assertEqual(res["prediction"], "GAP UP")
        self.assertEqual(res["btst_bias"], "BUY CE")
        self.assertGreater(res["confidence"], 60)
        self.assertIn("bullish_factors", res)
        print("  ✅ Feature 1: 4-Layer NLP Sentiment Engine verified.")

    # ── 2. Market Microstructure & Institutional Radar ─────────────────────────
    def test_feature_02_microstructure_and_institutional_radar(self):
        """Feature 2: Institutional Radar calculations and level extractions."""
        from institutional_scraper import _classify_bias, _extract_nifty_levels, _build_consensus

        bias_bull = _classify_bias("Nifty looks bullish, upside momentum expected")
        self.assertEqual(bias_bull, "BULLISH")

        levels = _extract_nifty_levels("Support at 24,100 and resistance at 24,500. Target 24,800.")
        self.assertIn(24100, levels)
        self.assertIn(24500, levels)
        self.assertIn(24800, levels)

        consensus = _build_consensus({
            "ET": {"next_day_bias": "BULLISH", "r1": 24800},
            "Moneycontrol": {"next_day_bias": "BULLISH", "r1": 24750},
        })
        self.assertEqual(consensus["next_day_bias"], "BULLISH")
        print("  ✅ Feature 2: Market Microstructure & Institutional Radar verified.")

    # ── 3. Stage 1 Gap Prediction & Confluence Arbiter ─────────────────────────
    def test_feature_03_stage1_confluence_arbiter(self):
        """Feature 3: Safety rules override unaligned predictions to protect capital."""
        from llm_analyzer import _resolve_btst_conflict

        raw_ai = {
            "prediction": "GAP UP",
            "confidence": 68,
            "btst_bias": "BUY CE",
            "news_sentiment": "BULLISH",
            "dimension_scores": {
                "macro_global": {"verdict": "GAP UP", "bias": "BULLISH", "note": "US green"},
                "fii_dii": {"verdict": "GAP DOWN", "bias": "BEARISH", "note": "FII heavy selling"},
                "oi_pcr": {"verdict": "GAP DOWN", "bias": "BEARISH", "note": "Call writing"},
                "heavyweights": {"verdict": "GAP DOWN", "bias": "BEARISH", "note": "Banks weak"},
                "vix_regime": {"verdict": "FLAT", "bias": "CALM", "note": "VIX 13.0"},
                "news_catalyst": {"verdict": "GAP UP", "bias": "BULLISH", "note": "Positive news"},
            }
        }
        fii_dii = {"fii_net_crores": -3200, "institutional_sentiment": "STRONG_BEARISH"}
        res = _resolve_btst_conflict(raw_ai, {"india_vix": 13.0}, {}, fii_dii)
        self.assertEqual(res["btst_bias"], "NO TRADE")
        self.assertTrue(res.get("conflict_resolved"))
        print("  ✅ Feature 3: Stage 1 Confluence Arbiter safety overrides verified.")

    # ── 4. CogniGraph 3-Tier Causal Knowledge Graph ────────────────────────────
    def test_feature_04_cognigraph_engine(self):
        """Feature 4: Knowledge graph triples, regime bucketing, and time-decay."""
        cg = CogniGraph(history_dir=self.history_dir, half_life_days=25.0)

        # 4.1 Regime bucketing
        regime = cg.classify_regime(
            {"india_vix": 13.5, "dte": 1, "fii_net": 1800.0, "gift_nifty_change_pct": 0.35},
            {"prediction": "GAP UP"},
        )
        self.assertIn("VIX_MOD", regime)
        self.assertIn("DTE_NEAR", regime)
        self.assertIn("FII_BULL", regime)

        # 4.2 Add causal triple
        cg.add_or_update_triple(
            subject="BUY_CE",
            relation="succeeded_with",
            target="FII_Cash_Buying_Confluence",
            polarity="POSITIVE",
            regime=regime,
            detail="Strong FII inflows of >2000 Cr backed overnight gap",
            evidence_date="2026-09-01",
            weight_increment=1.5,
        )

        # 4.3 Persona context retrieval
        cons_ctx = cg.get_agent_memory("CONSERVATIVE", {"india_vix": 13.5, "dte": 1, "fii_net": 1800.0}, {"prediction": "GAP UP"})
        self.assertIn("COGNIGRAPH CAUSAL RISK PRECEDENTS", cons_ctx)
        agg_ctx = cg.get_agent_memory("AGGRESSIVE", {"india_vix": 13.5, "dte": 1, "fii_net": 1800.0}, {"prediction": "GAP UP"})
        self.assertIn("COGNIGRAPH MOMENTUM PRECEDENTS", agg_ctx)

        cg.save()
        self.assertTrue(os.path.exists(os.path.join(self.history_dir, "cognigraph.json")))
        print("  ✅ Feature 4: CogniGraph 3-Tier Causal Knowledge Graph verified.")

    # ── 5. SQLite FTS5 Hybrid Historical Analog Recall ─────────────────────────
    def test_feature_05_sqlite_fts5_analog_recall(self):
        """Feature 5: SQLite FTS5 full-text indexing, BM25 ranking, and query sanitization."""
        fts = NiftyMemoryFTS(self.history_dir)

        # 5.1 Query sanitizer prevents syntax crashes
        bad_query = "NIFTY: (50) * 'crude shock' ^ -2.5% NOT peace"
        sanitized = _sanitize_fts_query(bad_query)
        self.assertNotIn(":", sanitized)
        self.assertNotIn("*", sanitized)
        self.assertNotIn("(", sanitized)

        # 5.2 Upsert records
        fts.upsert_entry(
            trade_date="2026-09-01",
            prediction="GAP UP",
            btst_bias="BUY CE",
            confidence=75,
            regime="VIX_LOW|FII_BULL",
            reasoning="Strong global tech rally, NASDAQ +2.1%, GIFT Nifty up.",
            reflection="Momentum carried through at market open.",
            outcome="CORRECT",
            actual_gap_pct=0.48,
            vix=11.5,
            fii_net=2100.0,
        )
        fts.upsert_entry(
            trade_date="2026-09-02",
            prediction="GAP DOWN",
            btst_bias="NO TRADE",
            confidence=65,
            regime="VIX_HIGH|FII_BEAR",
            reasoning="Middle East geopolitical crude oil surge, inflation fears.",
            reflection="Crude surge caused severe gap down.",
            outcome="CORRECT",
            actual_gap_pct=-0.62,
            vix=18.2,
            fii_net=-3100.0,
        )

        # 5.3 Analog search
        analogs = fts.find_analogs(
            signals={"india_vix": 12.0, "fii_net": 1800.0},
            stage1_result={"prediction": "GAP UP", "reasoning": "tech rally NASDAQ"},
            limit=1,
        )
        self.assertGreaterEqual(len(analogs), 1)
        self.assertEqual(analogs[0]["trade_date"], "2026-09-01")

        prompt_str = fts.format_analogs_prompt(analogs)
        self.assertIn("HISTORICAL MARKET ANALOGS", prompt_str)
        print("  ✅ Feature 5: SQLite FTS5 Hybrid Analog Recall verified.")

    # ── 6. AgentSkills Procedural Trading Playbooks Engine ─────────────────────
    def test_feature_06_skills_engine(self):
        """Feature 6: AgentSkills parsing, trigger matching, and prompt formatting."""
        skills_eng = SkillsEngine(skills_dir=self.skills_dir, history_dir=self.history_dir)
        self.assertGreaterEqual(len(skills_eng._skills_cache), 1)

        # Trigger matching
        matched = skills_eng.match_skills(
            signals={"dte": 0, "india_vix": 15.0},
            stage1_result={"fo_expiry_context": "Weekly expiry today", "prediction": "GAP UP"},
        )
        self.assertTrue(len(matched) > 0)
        matched_names = [s["name"] for s in matched]
        self.assertIn("expiry_day_pinning", matched_names)

        prompt_block = skills_eng.format_skills_prompt(matched)
        self.assertIn("ACTIVE PROCEDURAL TRADING PLAYBOOKS", prompt_block)
        print(f"  ✅ Feature 6: AgentSkills Engine verified ({len(skills_eng._skills_cache)} skills loaded).")

    # ── 7. Dynamic Catalyst Specialists & Subagent Delegation ──────────────────
    def test_feature_07_dynamic_catalyst_specialists(self):
        """Feature 7: Adaptive catalyst specialist subagents matching and evaluation."""
        self.assertIn("RBI_Policy_Quant", SPECIALIST_SPECS)
        self.assertIn("Geopolitical_Crude_Analyst", SPECIALIST_SPECS)
        self.assertIn("Options_Greeks_ZeroDTE_Quant", SPECIALIST_SPECS)

        # Matching
        news_rbi = [{"headline": "RBI governor announces monetary policy decision on repo rates"}]
        matched = match_dynamic_subagents(market_signals={"dte": 0}, news_items=news_rbi)
        self.assertIn("RBI_Policy_Quant", matched)
        self.assertIn("Options_Greeks_ZeroDTE_Quant", matched)

        # Execution with fallback
        verdicts = evaluate_dynamic_subagents(
            matched_names=["RBI_Policy_Quant", "Options_Greeks_ZeroDTE_Quant"],
            market_signals={"dte": 0, "nifty_spot": 24500},
            news_items=news_rbi,
            stage1_result={"prediction": "GAP UP", "btst_bias": "BUY CE"},
            gemini_key="mock",
            groq_key="mock",
        )
        self.assertEqual(len(verdicts), 2)
        for v in verdicts:
            self.assertIn("subagent", v)
            self.assertIn("verdict", v)
            self.assertIn("confidence", v)

        prompt_view = format_specialists_prompt(verdicts)
        self.assertIn("DYNAMIC CATALYST SPECIALISTS", prompt_view)
        print("  ✅ Feature 7: Dynamic Catalyst Specialists verified.")

    # ── 8. Stage 2 Multi-Persona Risk Debate Committee & Gemini Judge ──────────
    def test_feature_08_debate_committee_and_judge(self):
        """Feature 8: Multi-persona parallel debate committee + synthesis judge."""
        stage1 = {
            "btst_bias": "BUY CE",
            "prediction": "GAP UP",
            "confidence": 75,
            "reasoning": "Strong momentum and global rally.",
        }
        signals = {
            "nifty_spot": 24800.0,
            "india_vix": 13.2,
            "gift_nifty_change_pct": 0.40,
            "dte": 1,
        }

        mock_personas = {
            "AGGRESSIVE": {"persona": "AGGRESSIVE", "verdict": "FULL_BTST", "confidence": 85, "rationale": "Strong bull momentum."},
            "CONSERVATIVE": {"persona": "CONSERVATIVE", "verdict": "HEDGED_SPREAD", "confidence": 70, "rationale": "Theta risk overnight."},
            "NEUTRAL": {"persona": "NEUTRAL", "verdict": "HALF_QUANTITY", "confidence": 75, "rationale": "Position sizing hedge."},
        }

        def mock_runner(name, *args, **kwargs):
            return mock_personas.get(name, mock_personas["NEUTRAL"])

        mock_judge = {
            "btst_structure": "HEDGED_SPREAD",
            "trade_instruction": "Buy 24800 CE, sell 25000 CE to cap downside theta risk.",
            "debate_consensus": "MAJORITY",
            "confidence_adjustment": -5,
            "judge_rationale": "Overnight theta risk favors hedged spread.",
        }

        with patch("debate_engine._run_persona", side_effect=mock_runner), \
             patch("debate_engine._gemini_call", return_value=mock_judge):
            result = run_debate(
                stage1_result=stage1,
                market_signals=signals,
                groq_key="mock_key",
                gemini_key="mock_key",
            )
            self.assertEqual(result["btst_structure"], "HEDGED_SPREAD")
            self.assertEqual(result["debate_consensus"], "MAJORITY")
            self.assertIn("debate", result)
            self.assertIn("aggressive", result["debate"])
            self.assertIn("conservative", result["debate"])
            self.assertIn("neutral", result["debate"])
            print("  ✅ Feature 8: Stage 2 Multi-Persona Risk Debate Committee verified.")

    # ── 9. Intraday Pattern & ORB 3-Analyst Debate Committee ───────────────────
    def test_feature_09_intraday_debate_committee(self):
        """Feature 9: Intraday Opening Range Breakout & 3-Analyst Debate Committee."""
        intraday_data = {
            "intraday_bias": {"bias": "BUY_CALLS_ON_DIPS", "confidence": 72},
            "market_phase": {"phase": "ORB_BREAKOUT"},
            "volatility": {"level": "MODERATE"},
        }
        signals = {"nifty_spot": 24850.0, "india_vix": 13.0}

        mock_intra_judge = {
            "structure": "TREND_BUY_CALLS",
            "action_plan": "Enter 24850 CE above morning high with 30 pt SL.",
            "entry_zone": "24830 - 24860",
            "target": 24950.0,
            "stop_loss": 24800.0,
            "debate_consensus": "UNANIMOUS",
            "confidence_adjustment": 5,
            "judge_rationale": "High ORB momentum verified across sectors.",
        }

        with patch("debate_engine._run_intraday_persona", return_value={"verdict": "TREND_BUY_CALLS", "confidence": 75}), \
             patch("debate_engine._gemini_call", return_value=mock_intra_judge):
            res = run_intraday_debate(
                intraday_result=intraday_data,
                market_signals=signals,
                heavyweights={},
                news_sentiment="BULLISH",
                groq_key="mock",
                gemini_key="mock",
            )
            self.assertIn("debate", res)
            self.assertEqual(res["debate"]["structure"], "TREND_BUY_CALLS")
            self.assertEqual(res["debate"]["target"], 24950.0)
            print("  ✅ Feature 9: Intraday Pattern & ORB Debate Committee verified.")

    # ── 10. Live Exit Advisor & Fast-Path Circuit Breakers ─────────────────────
    def test_feature_10_live_exit_advisor_and_circuit_breakers(self):
        """Feature 10: Live Exit Advisor fast-path, stop loss rules, and conflict resolution."""
        # 10.1 VIX shock fast-path
        pos_shock = {"trade_type": "INTRADAY", "position_side": "BUY_CE", "entry_spot": 24800, "entry_premium": 150, "current_premium": 140}
        sig_shock = {"nifty_spot": 24780, "india_vix": 20.5, "india_vix_change_pct": 9.2}
        res_shock = evaluate_fast_path(pos_shock, sig_shock)
        self.assertIsNotNone(res_shock)
        self.assertEqual(res_shock["verdict"], "EMERGENCY_EXIT")

        # 10.2 Option premium hard stop loss (-30%)
        pos_hard_stop = {"trade_type": "INTRADAY", "position_side": "BUY_CE", "entry_spot": 24800, "entry_premium": 100, "current_premium": 70}
        res_hard_stop = evaluate_fast_path(pos_hard_stop, {"nifty_spot": 24750, "india_vix_change_pct": 1.0})
        self.assertIsNotNone(res_hard_stop)
        self.assertEqual(res_hard_stop["verdict"], "FULL_EXIT")

        # 10.3 Conflict resolution override
        parsed_mock = {
            "verdict": "HOLD_AND_RIDE",
            "dimension_scores": {
                "greeks_decay": {"verdict": "TRAIL"},
                "vix_regime": {"verdict": "TRAIL"},
                "oi_pcr": {"verdict": "EXIT"},
                "price_action": {"verdict": "TRAIL"},
                "heavyweights": {"verdict": "HOLD"},
                "macro_global": {"verdict": "HOLD"},
            }
        }
        resolved = _resolve_dimension_conflict(parsed_mock)
        self.assertNotEqual(resolved["verdict"], "HOLD_AND_RIDE")
        self.assertTrue(resolved.get("conflict_resolved"))
        print("  ✅ Feature 10: Live Exit Advisor & Fast-Path Circuit Breakers verified.")

    # ── 11. Complete Closed-Loop MemoryLog Cycle ───────────────────────────────
    def test_feature_11_closed_loop_memory_log_cycle(self):
        """Feature 11: Phase A (prediction) -> Resolution -> Phase B/C (reflection & triples)."""
        mem = NiftyMemoryLog(history_dir=self.history_dir)

        # 11.1 Phase A: Store prediction
        mem.store_prediction(
            trade_date="2026-09-08",
            prediction="GAP UP",
            btst_bias="BUY CE",
            confidence=78,
            reasoning="GIFT Nifty positive, strong US close.",
            fii_net=1950.0,
            gift_nifty_pct=0.42,
            india_vix=12.9,
            btst_structure="HEDGED_SPREAD",
            debate_consensus="MAJORITY",
        )
        stats_before = mem.get_stats()
        self.assertGreaterEqual(stats_before["total_predictions"], 1)

        # 11.2 Phase B/C: Next morning gap resolution & reflection
        cg = get_cognigraph(self.history_dir)
        ep = cg.ingest_resolution(
            trade_date="2026-09-08",
            prediction="GAP UP",
            btst_bias="BUY CE",
            confidence=78,
            actual_gap_pct=0.52,
            outcome="CORRECT",
            reflection="Positive GIFT Nifty and FII buying carried into cash open.",
            market_signals={"fii_net": 1950.0, "gift_nifty_change_pct": 0.42, "india_vix": 12.9},
            stage1_result={"prediction": "GAP UP", "btst_bias": "BUY CE"},
            trade_structure="HEDGED_SPREAD",
        )
        self.assertEqual(ep["outcome"], "CORRECT")
        self.assertTrue(len(ep["triples"]) > 0)

        # 11.3 Phase D: Load past lessons
        past_ctx = mem.load_cognigraph_context("CONSERVATIVE", {"india_vix": 13.0})
        self.assertIn("COGNIGRAPH CAUSAL RISK PRECEDENTS", past_ctx)
        print("  ✅ Feature 11: Closed-Loop MemoryLog Cycle verified.")

    # ── 12. Hermes 20:00 IST Dreaming Consolidation Engine ────────────────────
    def test_feature_12_dreaming_consolidation_engine(self):
        """Feature 12: Autonomous post-market memory consolidation and macro-axioms synthesis."""
        # Write resolved entry to memory_log.md
        log_file = os.path.join(self.history_dir, "memory_log.md")
        resolved_block = (
            "\n\n<!-- ENTRY_END -->\n\n"
            "[2026-09-07 | GAP UP | BUY CE | 70% | resolved | CORRECT]\n"
            "REASONING:\n"
            "GIFT Nifty was up, FII bought ₹1500 Cr.\n"
            "OUTCOME:\n"
            "Actual: +0.45% (GAP UP) | CORRECT\n"
            "REFLECTION:\n"
            "FII cash buying sustained the opening drive.\n"
            "\n\n<!-- ENTRY_END -->\n\n"
        )
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(resolved_block)

        dream_eng = DreamingEngine(history_dir=self.history_dir)
        report = dream_eng.run_consolidation_cycle(llm_distill_fn=None, dry_run=False)
        self.assertIn(report["status"], ["COMPLETED", "success"])
        self.assertGreaterEqual(report["episodes_processed"], 1)
        self.assertIn("macro_axioms", report)
        self.assertTrue(os.path.exists(os.path.join(self.history_dir, "macro_axioms.json")))
        self.assertTrue(os.path.exists(os.path.join(self.history_dir, "dream_report.json")))
        print(f"  ✅ Feature 12: Dreaming Consolidation Engine verified ({report['macro_axioms']['active_total']} active axioms).")

    # ── 13. Hermes Trajectory Dataset Exporter ─────────────────────────────────
    def test_feature_13_trajectory_exporter(self):
        """Feature 13: Export multi-turn agent reasoning and tool trajectories to fine-tuning formats."""
        exporter = TrajectoryExporter(history_dir=self.history_dir)
        summary = exporter.export_all(include_pending=True)

        self.assertEqual(summary["status"], "success")
        self.assertIn("sharegpt", summary["files"])
        self.assertIn("alpaca", summary["files"])
        self.assertIn("dpo", summary["files"])

        # Validate that exported files exist and contain valid JSONL
        for fmt, fpath in summary["files"].items():
            self.assertTrue(os.path.exists(fpath))
            with open(fpath, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
                for line in lines:
                    parsed = json.loads(line)
                    self.assertIsInstance(parsed, dict)
        print("  ✅ Feature 13: Trajectory Dataset Exporter verified (ShareGPT, Alpaca/Hermes, DPO).")

    # ── 14. AutoScheduler 6-Daily-Run Cadence ──────────────────────────────────
    def test_feature_14_autoscheduler_cadence(self):
        """Feature 14: AutoScheduler 6-daily-run timetable including 20:00 IST Dreaming."""
        scheduler = init_scheduler()
        job_ids = [job.id for job in scheduler.get_jobs()]

        expected_jobs = [
            "run_0830_premarket",
            "run_0945_intraday",
            "run_1330_afternoon",
            "run_1515_btst",
            "run_1730_postmarket",
            "run_2000_dreaming",
        ]
        for ejob in expected_jobs:
            self.assertIn(ejob, job_ids)

        scheduler.shutdown(wait=False)
        print(f"  ✅ Feature 14: AutoScheduler verified ({len(job_ids)} scheduled runs configured).")

    # ── 15. Flask REST API End-to-End Integration Suite ───────────────────────
    def test_feature_15_flask_rest_api_suite(self):
        """Feature 15: Flask REST API endpoints end-to-end client responses."""
        client = app.test_client()

        # 15.1 Health check
        r_health = client.get("/api/health")
        self.assertEqual(r_health.status_code, 200)
        self.assertEqual(r_health.get_json()["status"], "ok")

        # 15.2 Memory API
        r_mem = client.get("/api/memory")
        self.assertEqual(r_mem.status_code, 200)
        self.assertIn("cognigraph", r_mem.get_json()["data"])

        # 15.3 CogniGraph API with persona query
        r_cg_cons = client.get("/api/cognigraph?persona=CONSERVATIVE")
        self.assertEqual(r_cg_cons.status_code, 200)
        self.assertIn("persona_context", r_cg_cons.get_json()["data"])

        # 15.4 Dreaming Status API
        r_dream_stat = client.get("/api/dreaming/status")
        self.assertEqual(r_dream_stat.status_code, 200)
        self.assertIn("macro_axioms", r_dream_stat.get_json()["data"])

        # 15.5 Trajectories Export API (GET & POST)
        r_traj_get = client.get("/api/trajectories/export?format=sharegpt")
        self.assertEqual(r_traj_get.status_code, 200)
        self.assertIn(r_traj_get.get_json()["status"], ["ok", "success"])

        r_traj_post = client.post("/api/trajectories/export", json={"format": "alpaca"})
        self.assertEqual(r_traj_post.status_code, 200)
        self.assertIn(r_traj_post.get_json()["status"], ["ok", "success"])

        # 15.6 Live Exit Advisor API (Fast-path trigger)
        pos_payload = {
            "trade_type": "INTRADAY",
            "position_side": "BUY_CE",
            "entry_spot": 24800,
            "entry_premium": 100,
            "current_premium": 70,  # -30% hard stop
        }
        with patch("server.fetch_all_market_signals", return_value={"nifty_spot": 24800, "india_vix": 13.0}), \
             patch("server.fetch_fii_dii_data", return_value=None), \
             patch("server.scrape_all_news", return_value=[]):
            r_exit = client.post("/api/exit-advisor", json=pos_payload)
            self.assertEqual(r_exit.status_code, 200)
            self.assertEqual(r_exit.get_json()["data"]["verdict"], "FULL_EXIT")
            self.assertTrue(r_exit.get_json()["data"]["is_fast_path"])

        # 15.7 Institutional Radar API
        r_radar = client.get("/api/institutional-radar")
        self.assertEqual(r_radar.status_code, 200)

        # 15.8 History API
        r_hist = client.get("/api/history")
        self.assertEqual(r_hist.status_code, 200)

        print("  ✅ Feature 15: Flask REST API End-to-End Suite verified.")


if __name__ == "__main__":
    print("\n" + "=" * 76)
    print("🌟 RUNNING COMPLETE END-TO-END FEATURE VERIFICATION (15 CORE FEATURES)")
    print("=" * 76 + "\n")
    unittest.main(verbosity=2)
