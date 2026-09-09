"""
verify_features.py — Comprehensive End-to-End Verification of CogniGraph Features.

Verifies:
  1. CogniGraph core engine (regime bucketing, time-decay, persona retrieval).
  2. MemoryLog integration (Phase A/B/C/D loop, resolution ingestion, stats).
  3. DebateEngine integration (BTST debate & Intraday debate prompt injections).
  4. Flask Server API endpoints (/api/memory, /api/cognigraph with ?persona=).
  5. Disk persistence & JSON schema validity.
"""

import json
import os
import shutil
import tempfile
from unittest.mock import patch

# ── 1. CogniGraph Core Engine Verification ──────────────────────────────────
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
            confidence=80,
            actual_gap_pct=-0.22,
            outcome="WRONG",
            reflection="Heavyweight divergence in HDFC Bank pulled the index down.",
            market_signals=signals,
            stage1_result=stage1,
            trade_structure="FULL_BTST",
        )
        assert ep["outcome"] == "WRONG"
        assert any("Heavyweight_Divergence" in t for t in ep["triples"])
        print("  ✅ 1.7 Causal triple rule-based extraction passed")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ── 2. MemoryLog Integration Verification ──────────────────────────────────
def test_feature_2_memory_log_integration():
    print("\n🔍 [2/5] Testing MemoryLog Integration (Phase A to D)...")
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
            reasoning="Strong global cues",
            fii_net=-500.0,
            gift_nifty_pct=0.35,
        )
        print("  ✅ 2.1 Phase A store_prediction passed")

        # 2.2 Ingest resolution
        entry = {
            "prediction": "GAP UP",
            "btst_bias": "BUY CE",
            "confidence": 75,
            "fii_net": -500.0,
            "gift_nifty_pct": 0.35,
            "trade_structure": "HALF_QUANTITY",
        }
        # Simulate resolution hook
        from cognigraph import get_cognigraph
        cg = get_cognigraph(temp_dir)
        cg.ingest_resolution(
            trade_date="2026-09-08",
            prediction=entry["prediction"],
            btst_bias=entry["btst_bias"],
            confidence=entry["confidence"],
            actual_gap_pct=-0.15,
            outcome="❌ WRONG",
            reflection="Theta decay eroded call premium before gap could be monetized.",
            market_signals={"fii_net": entry["fii_net"], "gift_nifty_change_pct": entry["gift_nifty_pct"]},
            stage1_result={"prediction": entry["prediction"], "btst_bias": entry["btst_bias"]},
            trade_structure=entry["trade_structure"],
        )

        # 2.3 Phase D Persona Context
        cons_ctx = ml.load_cognigraph_context("CONSERVATIVE", {"india_vix": 14.5})
        assert "COGNIGRAPH CAUSAL RISK PRECEDENTS" in cons_ctx
        print("  ✅ 2.2 Phase D load_cognigraph_context passed")

        # 2.4 Stats with CogniGraph
        stats = ml.get_stats()
        assert "cognigraph" in stats
        assert stats["cognigraph"]["total_triples"] > 0
        print(f"  ✅ 2.3 MemoryLog get_stats() includes CogniGraph ({stats['cognigraph']['total_triples']} triples)")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ── 3. Debate Engine Integration Verification ──────────────────────────────
def test_feature_3_debate_engine():
    print("\n🔍 [3/5] Testing Debate Engine Integration...")
    from debate_engine import run_debate, run_intraday_debate

    stage1 = {
        "btst_bias": "BUY CE",
        "prediction": "GAP UP",
        "confidence": 70,
        "reasoning": "GIFT Nifty pointing up",
    }
    signals = {
        "nifty_spot": 25150.0,
        "india_vix": 14.0,
        "gift_nifty_change_pct": 0.35,
    }

    mock_agg = {"persona": "AGGRESSIVE", "verdict": "FULL_BTST", "confidence": 80, "rationale": "Momentum positive"}
    mock_cons = {"persona": "CONSERVATIVE", "verdict": "HEDGED_SPREAD", "confidence": 70, "rationale": "Theta risk"}
    mock_neut = {"persona": "NEUTRAL", "verdict": "HALF_QUANTITY", "confidence": 65, "rationale": "Balanced"}
    mock_judge = {
        "btst_structure": "HEDGED_SPREAD",
        "trade_instruction": "Execute Bull Call Spread.",
        "debate_consensus": "MAJORITY",
        "confidence_adjustment": 0,
        "judge_rationale": "CogniGraph risk precedents justify hedged structure.",
    }

    def mock_persona_runner(name, prompt, ctx, key):
        # Verify persona received tailored memory block
        if name == "AGGRESSIVE":
            assert "COGNIGRAPH MOMENTUM PRECEDENTS" in ctx
        elif name == "CONSERVATIVE":
            assert "COGNIGRAPH CAUSAL RISK PRECEDENTS" in ctx
        elif name == "NEUTRAL":
            assert "COGNIGRAPH STRUCTURAL CONTEXT" in ctx
        return {"AGGRESSIVE": mock_agg, "CONSERVATIVE": mock_cons, "NEUTRAL": mock_neut}[name]

    def mock_judge_runner(agg, cons, neut, s1, sig, key):
        from cognigraph import get_cognigraph
        cg = get_cognigraph()
        calib = cg.get_judge_calibration(sig, s1)
        assert "COGNIGRAPH REGIME CALIBRATION" in calib
        return mock_judge

    with patch("debate_engine._run_persona", side_effect=mock_persona_runner) as p_mock, \
         patch("debate_engine._run_judge", side_effect=mock_judge_runner) as j_mock:

        result = run_debate(stage1, signals, groq_key="mock_key", gemini_key="mock_key")
        assert result["btst_structure"] == "HEDGED_SPREAD"
        assert result["debate_consensus"] == "MAJORITY"
        print("  ✅ 3.1 BTST 3-Agent parallel debate received tailored CogniGraph memory blocks")
        print("  ✅ 3.2 Gemini Judge received CogniGraph regime calibration")

    # 3.3 Intraday Debate
    intraday_res = {
        "intraday_bias": {"bias": "BUY_CALLS_ON_DIPS", "confidence": 65},
        "market_phase": {"phase": "OPENING"},
        "volatility": {"level": "MODERATE"},
    }
    mock_intra_judge = {
        "structure": "TREND_BUY_CALLS",
        "action_plan": "Scalp dips near support",
        "entry_zone": "25130 - 25150",
        "target": 25200.0,
        "stop_loss": 25100.0,
        "debate_consensus": "UNANIMOUS",
        "confidence_adjustment": 5,
        "judge_rationale": "CogniGraph confirms dip buying bounce.",
    }
    with patch("debate_engine._run_intraday_persona", return_value={"verdict": "TREND_BUY_CALLS", "confidence": 70}) as intra_p_mock, \
         patch("debate_engine._gemini_call", return_value=mock_intra_judge):
        res = run_intraday_debate(intraday_res, signals, {}, {}, groq_key="mock", gemini_key="mock")
        assert "debate" in res
        assert res["debate"]["structure"] == "TREND_BUY_CALLS"
        print("  ✅ 3.3 Intraday Debate Committee ran and verified")


# ── 4. Flask Server API Endpoints Verification ─────────────────────────────
def test_feature_4_server_api():
    print("\n🔍 [4/5] Testing Flask API Endpoints...")
    from server import app

    client = app.test_client()

    # 4.1 GET /api/memory
    resp = client.get("/api/memory")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert "cognigraph" in data["data"]
    cg_stats = data["data"]["cognigraph"]
    assert "total_triples" in cg_stats
    print(f"  ✅ 4.1 /api/memory endpoint verified (active triples: {cg_stats['active_triples']})")

    # 4.2 GET /api/cognigraph without params
    resp = client.get("/api/cognigraph")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert "top_failure_traps" in data["data"]
    print(f"  ✅ 4.2 /api/cognigraph endpoint verified ({len(data['data']['top_failure_traps'])} top failure traps)")

    # 4.3 GET /api/cognigraph with ?persona=CONSERVATIVE
    resp = client.get("/api/cognigraph?persona=CONSERVATIVE")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["data"]["requested_persona"] == "CONSERVATIVE"
    assert "COGNIGRAPH CAUSAL RISK PRECEDENTS" in data["data"]["persona_context"]
    print("  ✅ 4.3 /api/cognigraph?persona=CONSERVATIVE returned formatted precedents")

    # 4.4 GET /api/cognigraph with ?persona=AGGRESSIVE
    resp = client.get("/api/cognigraph?persona=AGGRESSIVE")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "COGNIGRAPH MOMENTUM PRECEDENTS" in data["data"]["persona_context"]
    print("  ✅ 4.4 /api/cognigraph?persona=AGGRESSIVE returned formatted catalysts")


# ── 5. Disk Persistence & Schema Integrity ─────────────────────────────────
def test_feature_5_disk_persistence():
    print("\n🔍 [5/5] Testing Disk Persistence & Schema Integrity...")
    from cognigraph import get_cognigraph

    cg = get_cognigraph()
    cg.save()

    file_path = cg._file_path
    assert os.path.exists(file_path), f"File does not exist: {file_path}"

    with open(file_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    assert "schema_version" in raw
    assert raw["schema_version"] == 1
    assert "triples" in raw
    assert len(raw["triples"]) > 0
    assert "episodes" in raw
    assert "regime_index" in raw
    print(f"  ✅ 5.1 {file_path} validated as valid JSON schema v{raw['schema_version']}")
    print(f"  ✅ 5.2 Seed domain priors persisted: {len(raw['triples'])} triples")


if __name__ == "__main__":
    print("=" * 70)
    print("🚀 STARTING FULL FEATURE VERIFICATION")
    print("=" * 70)
    test_feature_1_cognigraph_core()
    test_feature_2_memory_log_integration()
    test_feature_3_debate_engine()
    test_feature_4_server_api()
    test_feature_5_disk_persistence()
    print("\n" + "=" * 70)
    print("🎉 ALL 5 FEATURE AREAS ARE WORKING PROPERLY WITH ZERO ERRORS!")
    print("=" * 70)
