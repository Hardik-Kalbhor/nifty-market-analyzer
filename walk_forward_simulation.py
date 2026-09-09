"""
walk_forward_simulation.py — Backward-compatibility shim.

The implementation has been decomposed into the wfs/ package.
"""

from wfs import (  # noqa: F401
    TIMEZONE,
    DEFAULT_RISK_FREE_RATE,
    TRADING_DAYS_PER_YEAR,
    _safe_float,
    _safe_int,
    HistoricalDataFeed,
    evaluate_7_specialist_dimensions,
    CogniGraphWalkForwardLearner,
    simulate_debate_committee,
    TradeExecutionEngine,
    QuantitativeMetricsCalculator,
    run_walk_forward_simulation,
)

if __name__ == "__main__":
    import argparse
    import logging
    parser = argparse.ArgumentParser(description="Multi-Month Historical Walk-Forward Simulation")
    parser.add_argument("--months", type=int, default=6, help="Number of months to simulate (default: 6)")
    parser.add_argument("--capital", type=float, default=100000.0, help="Initial capital in INR (default: 100000.0)")
    parser.add_argument("--risk", type=str, default="BALANCED", choices=["CONSERVATIVE", "BALANCED", "AGGRESSIVE"], help="Risk profile")
    parser.add_argument("--disable-cognigraph", action="store_true", help="Disable CogniGraph guardrails")
    parser.add_argument("--disable-scaleout", action="store_true", help="Disable 3-tier scale out")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    res = run_walk_forward_simulation(
        months=args.months,
        initial_capital=args.capital,
        risk_profile=args.risk,
        enable_cognigraph=not args.disable_cognigraph,
        enable_scale_out=not args.disable_scaleout,
    )
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
