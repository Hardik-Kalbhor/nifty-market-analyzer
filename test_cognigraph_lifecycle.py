"""
test_cognigraph_lifecycle.py — Feature 1 & 2 verification for CogniGraph core and MemoryLog.
"""

import json
import os
import shutil
import tempfile
from unittest.mock import patch


def test_feature_1_cognigraph_core():
    print("\n🔍 [1/5] Testing CogniGraph Core Engine...")
    from cognigraph import CogniGraph, _days_between, _safe_float

    temp_dir = tempfile.mkdtemp()
    try:
        cg = CogniGraph(history_dir=temp_dir, half_life_days=30.0)

        # 1.1 Regime Classification
        signals = {"india_vix": "15.2%", "gift_nifty_change_pct": "+0.35%", "fii_net": "-1800 Cr", "dte": 1}
        stage1 = {"prediction": "GAP UP", "fo_expiry_context": "Next day expiry"}
        regime = cg.classify_regime(signals, stage1)
        assert regime == "VIX_MOD|DTE_NEAR|FII_BEAR|GAP_MILD_UP", f"Unexpected regime: {regime}"
        print("  ✅ 1.1 Regime classification with dirty inputs passed:", regime)

        # 1.2 Triples and Decay
        cg.add_or_update_triple("BUY_CE", "failed_due_to", "Overnight_Theta_Decay", "NEGATIVE", regime, "Theta loss 40%", "2026-08-01", 2.0)
        assert cg._compute_decay("2026-08-01", "2026-08-31") < 0.51
        print("  ✅ 1.2 Half-life exponential decay calculation passed")

        # 1.3 Persona Retrievals
        cons_mem = cg.get_agent_memory("CONSERVATIVE", signals, stage1)
        assert "COGNIGRAPH CAUSAL RISK PRECEDENTS" in cons_mem
        assert "Overnight Theta Decay" in cons_mem
        print("  ✅ 1.3 Conservative persona memory retrieval passed")

        agg_mem = cg.get_agent_memory("AGGRESSIVE", signals, stage1)
        assert "COGNIGRAPH MOMENTUM PRECEDENTS" in agg_mem
        print("  ✅ 1.4 Aggressive persona memory retrieval passed")

        neut_mem = cg.get_agent_memory("NEUTRAL", signals, stage1)
        assert "COGNIGRAPH STRUCTURAL CONTEXT" in neut_mem
        print("  ✅ 1.5 Neutral persona memory retrieval passed")

        judge_mem = cg.get_judge_calibration(signals, stage1)
        assert "COGNIGRAPH REGIME CALIBRATION" in judge_mem
        print("  ✅ 1.6 Judge calibration retrieval passed")

        # 1.4 Ingest Resolution & Check Triples
        ep = cg.ingest_resolution(
            trade_date="2026-09-08",
            prediction="GAP UP",
            btst_bias="BUY CE",
            actual_gap_pct=0.45,
            outcome="CORRECT (+0.45%)",
            reasoning="GIFT Nifty momentum and FII flow",
            reflection="Momentum thesis held as FII absorption persisted.",
            signals=signals,
            stage1_result=stage1,
        )
        assert ep["regime"] == regime
        assert "CORRECT" in ep["outcome"]
        print("  ✅ 1.7 Ingest resolution into episode graph passed")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_feature_2_memory_log_integration():
    print("\n🔍 [2/5] Testing MemoryLog Integration & Loop...")
    from memory_log import NiftyMemoryLog

    temp_dir = tempfile.mkdtemp()
    try:
        ml = NiftyMemoryLog(history_dir=temp_dir)

        # 2.1 Store prediction
        ml.store_prediction(
            trade_date="2026-09-08",
            prediction="GAP UP",
            btst_bias="BUY CE",
            confidence=75,
            reasoning="GIFT Nifty: +0.45%\nFII Net: ₹+1200 Cr\nIndia VIX: 13.5",
            fii_net=1200.0,
            gift_nifty_pct=0.45,
            india_vix=13.5,
            ai_provider="Groq-Llama3-70b",
            btst_structure="HALF_QUANTITY",
            debate_consensus="MAJORITY",
        )
        print("  ✅ 2.1 Stored Phase A prediction in MemoryLog")

        # 2.2 Ingest resolution via mock
        with patch.object(ml, "_fetch_nifty_actual_gap", return_value=(0.45, 25200.0, 25087.0)):
            resolved = ml.resolve_pending_entries(
                llm_reflect_fn=lambda t, p, b, c, r, g, out: "Thesis held cleanly on GIFT momentum."
            )
            assert len(resolved) == 1
            assert resolved[0]["date"] == "2026-09-08"
            assert "CORRECT" in resolved[0]["outcome"]
            print("  ✅ 2.2 MemoryLog Phase B+C resolution loop passed and updated CogniGraph")

        # 2.3 Verify MemoryLog stats include CogniGraph
        stats = ml.get_stats()
        assert "cognigraph" in stats
        assert stats["cognigraph"]["total_triples"] > 0
        print(f"  ✅ 2.3 MemoryLog get_stats() includes CogniGraph ({stats['cognigraph']['total_triples']} triples)")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    test_feature_1_cognigraph_core()
    test_feature_2_memory_log_integration()
    print("\n✅ All CogniGraph lifecycle tests passed successfully!")
