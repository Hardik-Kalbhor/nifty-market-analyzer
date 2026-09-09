"""
wfs/execution.py — Trade execution and 3-tier scale-out engine for walk-forward simulation.
"""

from __future__ import annotations
from typing import Any, Optional
from .constants import _safe_float, _safe_int

class TradeExecutionEngine:
    """
    Simulates realistic options & futures trade lifecycles:
    - Entry at 15:15 IST (BTST)
    - Next-morning 09:15-09:30 resolution (Gap outcome)
    - 3-Tier Scale-Out P&L simulation:
      - Tier 1 (50% lots): locked at market open based on overnight move.
      - Tier 2 (25% lots): trailed to breakeven cost if open is favorable.
      - Tier 3 (25% lots): momentum runner capturing extended trend or stopped at cost.
    - Transaction costs & slippage (0.05% slippage + ₹40 exchange/brokerage charge).
    """

    def __init__(
        self,
        initial_capital: float = 100000.0,
        lot_size: int = 75,
        enable_scale_out: bool = True,
        risk_profile: str = "BALANCED",
    ):
        self.initial_capital = max(1000.0, _safe_float(initial_capital, 100000.0))
        self.capital = self.initial_capital
        self.lot_size = max(1, _safe_int(lot_size, 75))
        self.enable_scale_out = enable_scale_out
        self.risk_profile = str(risk_profile or "BALANCED").strip().upper()
        self.closed_trades: list[dict[str, Any]] = []
        self.daily_equity_curve: list[dict[str, Any]] = []
        self.is_bankrupt: bool = False

    def execute_session_trade(
        self,
        session: dict[str, Any],
        decision: dict[str, Any],
        regime: str,
    ) -> Optional[dict[str, Any]]:
        session = session or {}
        decision = decision or {}
        side = decision.get("position_side", "NO_TRADE")
        verdict = decision.get("verdict", "STRICT_NO_TRADE")

        # Margin Call / Depletion Protection
        if self.is_bankrupt or self.capital < 15000.0:
            self.is_bankrupt = True
            self.daily_equity_curve.append({
                "date": session.get("date", ""),
                "session_id": session.get("session_id", ""),
                "equity": round(self.capital, 2),
                "daily_pnl": 0.0,
                "daily_return_pct": 0.0,
                "drawdown_pct": 0.0,
            })
            return None

        if side == "NO_TRADE" or verdict == "STRICT_NO_TRADE":
            self.daily_equity_curve.append({
                "date": session.get("date", ""),
                "session_id": session.get("session_id", ""),
                "equity": round(self.capital, 2),
                "daily_pnl": 0.0,
                "daily_return_pct": 0.0,
                "drawdown_pct": 0.0,
            })
            return None

        # Position Sizing based on risk profile and available capital
        if self.risk_profile == "AGGRESSIVE":
            base_lots = 3 if verdict == "FULL_BTST" else 2
        elif self.risk_profile == "CONSERVATIVE":
            base_lots = 1
        else:  # BALANCED
            base_lots = 2 if verdict == "FULL_BTST" else 1

        max_affordable_lots = max(1, int(self.capital // 25000))
        lots = min(base_lots, max_affordable_lots)
        num_shares = lots * self.lot_size

        entry_spot = _safe_float(session.get("close"), 24000.0)
        next_open = _safe_float(session.get("next_day_open"), entry_spot)
        gap_pct = _safe_float(session.get("next_day_gap_pct"), 0.0)
        spot_pts = next_open - entry_spot

        is_ce = (side == "BUY_CE")
        trade_spot_pts = spot_pts if is_ce else -spot_pts
        trade_spot_pct = gap_pct if is_ce else -gap_pct

        dte = _safe_int(session.get("dte"), 3)
        theta_drag_pts = 12.0 if dte <= 1 else (8.0 if dte <= 3 else 5.0)

        if self.enable_scale_out:
            t1_pts = (trade_spot_pts * 0.50) - theta_drag_pts
            t2_pts = max(0.0, (trade_spot_pts * 0.50) - theta_drag_pts) if trade_spot_pct >= 0.20 else ((trade_spot_pts * 0.50) - theta_drag_pts)
            if trade_spot_pct >= 0.35:
                t3_pts = ((trade_spot_pts * 1.25) * 0.50) - theta_drag_pts
            elif trade_spot_pct >= 0.15:
                t3_pts = max(0.0, (trade_spot_pts * 0.50) - theta_drag_pts)
            else:
                t3_pts = (trade_spot_pts * 0.50) - theta_drag_pts

            net_option_pts = (0.50 * t1_pts) + (0.25 * t2_pts) + (0.25 * t3_pts)
        else:
            net_option_pts = (trade_spot_pts * 0.50) - theta_drag_pts

        slippage_pts = 1.0
        net_pts_after_slip = net_option_pts - slippage_pts
        trade_pnl_inr = round(net_pts_after_slip * num_shares - 40.0, 2)

        trade_pnl_pct = round((trade_pnl_inr / self.capital) * 100, 3) if self.capital > 0 else 0.0
        self.capital = max(0.0, self.capital + trade_pnl_inr)

        trade_record = {
            "trade_id": f"TRD_{len(self.closed_trades) + 1:03d}",
            "session_id": session.get("session_id", ""),
            "date": session.get("date", ""),
            "regime": regime,
            "side": side,
            "verdict": verdict,
            "lots": lots,
            "entry_spot": entry_spot,
            "exit_spot": next_open,
            "spot_move_pts": round(spot_pts, 1),
            "spot_move_pct": round(gap_pct, 2),
            "option_pnl_pts": round(net_pts_after_slip, 1),
            "pnl_inr": trade_pnl_inr,
            "pnl_pct": trade_pnl_pct,
            "capital_after": round(self.capital, 2),
            "scale_out_executed": self.enable_scale_out,
            "is_win": trade_pnl_inr > 0,
        }
        self.closed_trades.append(trade_record)

        self.daily_equity_curve.append({
            "date": session.get("date", ""),
            "session_id": session.get("session_id", ""),
            "equity": round(self.capital, 2),
            "daily_pnl": trade_pnl_inr,
            "daily_return_pct": trade_pnl_pct,
            "drawdown_pct": 0.0,
        })

        return trade_record


