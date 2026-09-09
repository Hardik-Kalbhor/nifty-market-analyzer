"""
wfs/metrics.py — Quantitative risk and portfolio performance analytics.
"""

import math
from typing import Any
from .constants import DEFAULT_RISK_FREE_RATE, TRADING_DAYS_PER_YEAR, _safe_float

class QuantitativeMetricsCalculator:
    """
    Computes portfolio and risk metrics across the walk-forward simulation:
    - Cumulative Return (%) & Absolute P&L (₹)
    - Annualized Sharpe Ratio (Rf = 6.5%)
    - Annualized Sortino Ratio (Downside deviation only)
    - Maximum Drawdown (MDD %) & Max Drawdown Duration
    - Win Rate %, Profit Factor, Expectancy, Profit/Loss Ratio
    - Monthly Performance Breakdown
    - Regime Performance Breakdown
    """

    @staticmethod
    def calculate_metrics(
        initial_capital: float,
        equity_curve: list[dict[str, Any]],
        trades: list[dict[str, Any]],
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    ) -> dict[str, Any]:
        if not equity_curve:
            return {}

        initial_capital = max(1000.0, _safe_float(initial_capital, 100000.0))
        final_capital = equity_curve[-1]["equity"]
        total_pnl = round(final_capital - initial_capital, 2)
        cumulative_return_pct = round(((final_capital - initial_capital) / initial_capital) * 100, 2)

        peak = initial_capital
        max_drawdown_pct = 0.0
        drawdown_duration_days = 0
        current_dd_days = 0

        for pt in equity_curve:
            eq = pt["equity"]
            if eq > peak:
                peak = eq
                current_dd_days = 0
            else:
                current_dd_days += 1

            dd_pct = ((peak - eq) / peak) * 100.0 if peak > 0 else 0.0
            pt["drawdown_pct"] = round(dd_pct, 2)
            if dd_pct > max_drawdown_pct:
                max_drawdown_pct = dd_pct
            if current_dd_days > drawdown_duration_days:
                drawdown_duration_days = current_dd_days

        max_drawdown_pct = round(max_drawdown_pct, 2)

        daily_returns = [pt["daily_return_pct"] / 100.0 for pt in equity_curve]
        n_days = len(daily_returns)
        mean_daily_return = sum(daily_returns) / n_days if n_days > 0 else 0.0

        daily_rf = risk_free_rate / TRADING_DAYS_PER_YEAR
        excess_returns = [r - daily_rf for r in daily_returns]
        mean_excess = sum(excess_returns) / n_days if n_days > 0 else 0.0

        variance = sum((r - mean_daily_return) ** 2 for r in daily_returns) / (n_days - 1) if n_days > 1 else 0.0
        std_daily = math.sqrt(variance)

        total_trades = len(trades)
        winning_trades = [t for t in trades if t["is_win"]]
        losing_trades = [t for t in trades if not t["is_win"]]
        win_rate = round((len(winning_trades) / total_trades) * 100, 1) if total_trades > 0 else 0.0

        if std_daily > 1e-6 and total_trades > 0:
            sharpe_ratio = round((mean_excess / std_daily) * math.sqrt(TRADING_DAYS_PER_YEAR), 2)
        else:
            sharpe_ratio = 0.0

        downside_sq_sum = sum(min(0.0, r - daily_rf) ** 2 for r in daily_returns)
        downside_dev = math.sqrt(downside_sq_sum / n_days) if n_days > 0 else 0.0

        if downside_dev > 1e-6 and total_trades > 0 and std_daily > 1e-6:
            sortino_ratio = round((mean_excess / downside_dev) * math.sqrt(TRADING_DAYS_PER_YEAR), 2)
        else:
            sortino_ratio = 0.0

        gross_profit = sum(t["pnl_inr"] for t in winning_trades)
        gross_loss = abs(sum(t["pnl_inr"] for t in losing_trades))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

        avg_win = round(gross_profit / len(winning_trades), 2) if winning_trades else 0.0
        avg_loss = round(gross_loss / len(losing_trades), 2) if losing_trades else 0.0
        win_loss_ratio = round(avg_win / avg_loss, 2) if avg_loss > 0 else 0.0

        # Monthly breakdown
        monthly_map: dict[str, list[dict[str, Any]]] = {}
        for t in trades:
            month_key = t["date"][:7]
            if month_key not in monthly_map:
                monthly_map[month_key] = []
            monthly_map[month_key].append(t)

        monthly_performance = []
        for m, m_trades in sorted(monthly_map.items()):
            m_wins = sum(1 for t in m_trades if t["is_win"])
            m_pnl = round(sum(t["pnl_inr"] for t in m_trades), 2)
            monthly_performance.append({
                "month": m,
                "trades": len(m_trades),
                "wins": m_wins,
                "win_rate": round((m_wins / len(m_trades)) * 100, 1),
                "pnl_inr": m_pnl,
            })

        # Regime breakdown
        regime_map: dict[str, list[dict[str, Any]]] = {}
        for t in trades:
            reg = t.get("regime", "OTHER")
            if reg not in regime_map:
                regime_map[reg] = []
            regime_map[reg].append(t)

        regime_performance = []
        for r, r_trades in sorted(regime_map.items(), key=lambda x: len(x[1]), reverse=True):
            r_wins = sum(1 for t in r_trades if t["is_win"])
            r_pnl = round(sum(t["pnl_inr"] for t in r_trades), 2)
            regime_performance.append({
                "regime": r,
                "trades": len(r_trades),
                "wins": r_wins,
                "win_rate": round((r_wins / len(r_trades)) * 100, 1),
                "pnl_inr": r_pnl,
            })

        return {
            "initial_capital": initial_capital,
            "final_capital": round(final_capital, 2),
            "total_pnl_inr": total_pnl,
            "cumulative_return_pct": cumulative_return_pct,
            "sharpe_ratio": sharpe_ratio,
            "sortino_ratio": sortino_ratio,
            "max_drawdown_pct": max_drawdown_pct,
            "drawdown_duration_days": drawdown_duration_days,
            "total_trades": total_trades,
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate_pct": win_rate,
            "profit_factor": profit_factor,
            "avg_win_inr": avg_win,
            "avg_loss_inr": avg_loss,
            "win_loss_ratio": win_loss_ratio,
            "monthly_performance": monthly_performance,
            "regime_performance": regime_performance,
            "equity_curve": equity_curve,
            "trades_sample": trades[-20:],
        }


