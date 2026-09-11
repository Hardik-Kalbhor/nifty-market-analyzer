"""
exit_fast/rules_critical.py — Critical exit rules (Time cutoff, VIX shock, Spot invalidation, Hard stop).
"""

from datetime import datetime
from typing import Any, Optional
from .constants import _safe_float, _get_now_ist


def evaluate_critical_rules(
    position: dict[str, Any],
    live_signals: dict[str, Any],
    current_time: Optional[datetime] = None
) -> Optional[dict[str, Any]]:

    now_ist = current_time or _get_now_ist()
    trade_type = str(position.get("trade_type", "INTRADAY")).upper()
    side = str(position.get("position_side", "BUY_CE")).upper()
    entry_spot = _safe_float(position.get("entry_spot"), 0.0)
    current_spot = _safe_float(live_signals.get("nifty_spot"), 0.0)
    vix_change_pct = _safe_float(live_signals.get("india_vix_change_pct"), 0.0)
    
    entry_premium = _safe_float(position.get("entry_premium") or position.get("entry_price") or position.get("buy_price") or position.get("avg_price"), 0.0)
    current_premium = _safe_float(position.get("current_premium") or position.get("current_ltp") or position.get("current_price") or position.get("ltp"), 0.0)

    # 1. Extreme Volatility / VIX Shock (>= 8.0% spike or VIX > 18 with 5% spike)
    current_vix = _safe_float(live_signals.get("india_vix"), 14.0)
    is_vix_shock = (vix_change_pct >= 8.0) or (current_vix >= 18.0 and vix_change_pct >= 5.0)
    if is_vix_shock:
        return {
            "verdict": "EMERGENCY_EXIT",
            "action": "Liquidate position immediately with market order.",
            "confidence": 92,
            "urgency": "CRITICAL",
            "engine": "Deterministic Fast-Path (VIX Shock)",
            "reasoning": f"India VIX spiked sharply by +{vix_change_pct:.2f}% (VIX at {current_vix:.2f}). Extreme volatility expansion threatens option whip-saws and rapid risk expansion.",
            "trailing_sl": round(current_spot, 2) if current_spot > 0 else 0,
            "is_fast_path": True,
        }

    # 3. Severe Adverse Spot Invalidation (>= 0.60% against trade)
    if entry_spot > 0 and current_spot > 0:
        spot_pct_move = ((current_spot - entry_spot) / entry_spot) * 100
        
        # Bullish trade (BUY_CE, LONG_FUTURES, SHORT_PE) suffering severe drop
        if side in ["BUY_CE", "LONG_FUTURES", "SHORT_PE"] and spot_pct_move <= -0.60:
            return {
                "verdict": "FULL_EXIT",
                "action": "Exit immediately. Structural support completely invalidated.",
                "confidence": 90,
                "urgency": "HIGH",
                "engine": "Deterministic Fast-Path (Spot Invalidation)",
                "reasoning": f"NIFTY dropped {spot_pct_move:.2f}% ({round(current_spot - entry_spot, 1)} pts) below your entry level of {entry_spot}. Hard stop breached.",
                "trailing_sl": round(current_spot, 2),
                "is_fast_path": True,
            }
        
        # Bearish trade (BUY_PE, SHORT_FUTURES, SHORT_CE) suffering severe rally
        if side in ["BUY_PE", "SHORT_FUTURES", "SHORT_CE"] and spot_pct_move >= 0.60:
            return {
                "verdict": "FULL_EXIT",
                "action": "Exit immediately. Resistance broken with strong upside momentum.",
                "confidence": 90,
                "urgency": "HIGH",
                "engine": "Deterministic Fast-Path (Spot Invalidation)",
                "reasoning": f"NIFTY rallied +{spot_pct_move:.2f}% (+{round(current_spot - entry_spot, 1)} pts) above your entry level of {entry_spot}. Hard stop breached.",
                "trailing_sl": round(current_spot, 2),
                "is_fast_path": True,
            }

    # 4. Hard Stop Loss on Option Premium (e.g. Loss >= 28%)
    if entry_premium > 0 and current_premium > 0:
        is_short = side in ["SHORT_CE", "SHORT_PE", "SHORT_FUTURES"]
        if is_short:
            # Option Selling: profit when premium drops (decay), loss when premium surges
            prem_pnl_pct = ((entry_premium - current_premium) / entry_premium) * 100
        else:
            # Option Buying: profit when premium rises, loss when premium drops
            prem_pnl_pct = ((current_premium - entry_premium) / entry_premium) * 100

        if prem_pnl_pct <= -28.0:
            loss_pct = abs(prem_pnl_pct)
            direction_desc = (
                f"Option premium surged against short position from {entry_premium} to {current_premium}"
                if is_short else
                f"Option premium dropped from {entry_premium} to {current_premium}"
            )
            return {
                "verdict": "FULL_EXIT",
                "action": f"Exit at market. Stop-loss triggered at -{loss_pct:.1f}% loss.",
                "confidence": 92,
                "urgency": "HIGH",
                "engine": "Deterministic Fast-Path (Premium Stop Hit)",
                "reasoning": f"{direction_desc} (-{loss_pct:.1f}% loss), exceeding the maximum 25-28% capital risk limit.",
                "trailing_sl": round(current_spot, 2) if current_spot > 0 else round(entry_spot, 2),
                "is_fast_path": True,
            }


    # 4. 15:15 IST Mandatory Pre-Close Square-Off for Intraday Trades
    if trade_type == "INTRADAY":
        if now_ist.hour == 15 and now_ist.minute >= 15:
            return {
                "verdict": "PRE_CLOSE_EXIT",
                "action": "Mandatory square-off before 15:20 broker auto-liquidation penalty.",
                "confidence": 95,
                "urgency": "HIGH",
                "engine": "Deterministic Fast-Path (Time Cutoff)",
                "reasoning": f"Current time is {now_ist.strftime('%H:%M IST')}. Intraday positions must be squared off before market close.",
                "trailing_sl": round(current_spot, 2),
                "is_fast_path": True,
            }

    return None
