"""
wfs/core.py — Main orchestrator for multi-month historical walk-forward simulation.
"""

from __future__ import annotations
import os
import json
import logging
from datetime import datetime
from typing import Any, Optional
from pathlib import Path

from .constants import TIMEZONE, DEFAULT_RISK_FREE_RATE, _safe_float, _safe_int
from .feed import HistoricalDataFeed
from .specialists import evaluate_7_specialist_dimensions
from .learner import CogniGraphWalkForwardLearner
from .debate import simulate_debate_committee
from .execution import TradeExecutionEngine
from .metrics import QuantitativeMetricsCalculator

logger = logging.getLogger("WalkForwardSimulation")

def run_walk_forward_simulation(
    months: int = 6,
    initial_capital: float = 100000.0,
    risk_profile: str = "BALANCED",
    enable_cognigraph: bool = True,
    enable_scale_out: bool = True,
    history_dir: Optional[str] = None,
) -> dict[str, Any]:
    """
    Main entry point for executing Phase 6 Multi-Month Historical Walk-Forward Simulation.
    Executes all 126 trading days across 7 dimensions, CogniGraph regimes,
    debate committees, and 3-tier scale out execution in <1 second.
    """
    months = max(1, min(12, _safe_int(months, 6)))
    initial_capital = max(1000.0, _safe_float(initial_capital, 100000.0))
    risk_profile = str(risk_profile or "BALANCED").strip().upper()
    if risk_profile not in ("CONSERVATIVE", "AGGRESSIVE", "BALANCED"):
        risk_profile = "BALANCED"

    start_time = datetime.now()
    feed = HistoricalDataFeed(history_dir=history_dir)
    sessions = feed.load_or_generate_sessions(months=months)

    cg_learner = CogniGraphWalkForwardLearner(enable_cognigraph=enable_cognigraph)
    executor = TradeExecutionEngine(
        initial_capital=initial_capital,
        enable_scale_out=enable_scale_out,
        risk_profile=risk_profile,
    )

    logger.info(f"Starting {months}-month historical walk-forward simulation across {len(sessions)} sessions...")

    for session in sessions:
        # Step 1: 7-Perspective Specialist Dimension Evaluation
        dimensions = evaluate_7_specialist_dimensions(session)

        # Step 2: CogniGraph Regime Classification
        regime = cg_learner.classify_regime(session)

        # Step 3: Failure Trap Invalidation Check
        preliminary_side = "BUY_CE" if _safe_float(session.get("change_pct")) > 0 else "BUY_PE"
        trap_warning = cg_learner.check_failure_trap(regime, preliminary_side)

        # Step 4: Multi-Persona Risk Debate Committee Simulation
        decision = simulate_debate_committee(
            dimensions=dimensions,
            session=session,
            cognigraph_trap=trap_warning,
            risk_profile=risk_profile,
        )

        # Step 5: Trade Execution & 3-Tier Scale-Out Simulation
        trade = executor.execute_session_trade(session, decision, regime)

        # Step 6: Walk-Forward Learning Feedback
        if trade:
            cg_learner.record_trade_outcome(
                regime=regime,
                side=trade["side"],
                pnl=trade["pnl_pct"],
                reason=f"Spot moved {trade['spot_move_pct']}% under {regime}",
            )

    # Step 7: Quantitative Metrics & Statistics
    metrics = QuantitativeMetricsCalculator.calculate_metrics(
        initial_capital=initial_capital,
        equity_curve=executor.daily_equity_curve,
        trades=executor.closed_trades,
    )

    elapsed_ms = round((datetime.now() - start_time).total_seconds() * 1000, 1)
    metrics["simulation_config"] = {
        "months": months,
        "sessions_count": len(sessions),
        "initial_capital": initial_capital,
        "risk_profile": risk_profile,
        "enable_cognigraph": enable_cognigraph,
        "enable_scale_out": enable_scale_out,
        "elapsed_ms": elapsed_ms,
        "timestamp": datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S IST"),
    }

    report_path = Path(feed.history_dir) / "walk_forward_simulation_report.json"
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)
        logger.info(f"Walk-forward report saved to {report_path}")
    except Exception as e:
        logger.warning(f"Could not persist walk-forward report: {e}")

    return metrics


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    res = run_walk_forward_simulation(months=6)
    print("\n" + "=" * 60)
    print("📈 Phase 6: Multi-Month Historical Walk-Forward Simulation Results")
    print("=" * 60)
    print(f"Initial Capital : ₹{res['initial_capital']:,.0f}")
    print(f"Final Capital   : ₹{res['final_capital']:,.0f}")
    print(f"Cumulative P&L  : ₹{res['total_pnl_inr']:+,.0f} ({res['cumulative_return_pct']:+,.2f}%)")
    print(f"Sharpe Ratio    : {res['sharpe_ratio']}")
    print(f"Sortino Ratio   : {res['sortino_ratio']}")
    print(f"Max Drawdown    : {res['max_drawdown_pct']}%")
    print(f"Win Rate        : {res['win_rate_pct']}% ({res['winning_trades']}/{res['total_trades']} wins)")
    print(f"Profit Factor   : {res['profit_factor']}")
    print(f"Simulation Time : {res['simulation_config']['elapsed_ms']}ms")
    print("=" * 60)
