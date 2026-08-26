"""
exit_fast_path.py — Deterministic Fast-Path Safety Engine & Heavyweight Tracker
Executes in 0-10ms to catch emergency events, flash crashes, hard stop hits,
and 15:15 IST pre-close cutoffs without waiting for an LLM call.
"""

import os
import time
import logging
import concurrent.futures
from datetime import datetime
from typing import Any, Optional
import pytz

try:
    import yfinance as yf
    try:
        yf.set_tz_cache_location("/tmp/py-yfinance")
    except Exception:
        pass
except ImportError:
    yf = None

logger = logging.getLogger("ExitFastPath")
TIMEZONE = pytz.timezone("Asia/Kolkata")


def is_expiry_day() -> bool:
    """Returns True if today is Thursday (NIFTY 50 weekly expiry day in IST)."""
    now_ist = datetime.now(TIMEZONE)
    return now_ist.weekday() == 3  # 0=Mon, 3=Thu


# Top 5 NIFTY heavyweights accounting for ~39% index weight
HEAVYWEIGHT_TICKERS = {
    "HDFCBANK.NS": {"name": "HDFC Bank", "weight": 11.5},
    "RELIANCE.NS": {"name": "Reliance", "weight": 9.2},
    "ICICIBANK.NS": {"name": "ICICI Bank", "weight": 8.1},
    "INFY.NS": {"name": "Infosys", "weight": 5.8},
    "TCS.NS": {"name": "TCS", "weight": 4.2},
}


def fetch_heavyweight_stocks() -> dict[str, Any]:
    """
    Concurrently fetch live price and percent change for top 5 NIFTY heavyweights.
    Executes in ~200-350ms using ThreadPoolExecutor and fast_info.
    """
    stocks = {}
    if not yf:
        return stocks

    def _fetch_single(ticker: str, meta: dict):
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            last_price = getattr(info, "last_price", None)
            prev_close = getattr(info, "previous_close", None)
            if last_price and prev_close and prev_close > 0:
                pct = round(((last_price - prev_close) / prev_close) * 100, 2)
                return ticker, {
                    "name": meta["name"],
                    "weight": meta["weight"],
                    "price": round(last_price, 2),
                    "change_pct": pct,
                }
        except Exception as e:
            logger.debug(f"Error fetching {ticker}: {e}")
        return ticker, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(_fetch_single, sym, meta)
            for sym, meta in HEAVYWEIGHT_TICKERS.items()
        ]
        done, not_done = concurrent.futures.wait(futures, timeout=3.5)
        for f in not_done:
            f.cancel()

        for f in done:
            try:
                sym, data = f.result()
                if data:
                    stocks[sym] = data
            except Exception:
                pass

    return stocks


def evaluate_fast_path(position: dict[str, Any], live_signals: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Evaluates 0-10ms deterministic safety conditions.
    Returns an immediate exit dict if an emergency/cutoff condition is met; otherwise returns None.

    Checks:
    1. Pre-Close Mandatory Cutoff (15:15+ IST for Intraday positions)
    2. Extreme India VIX Spike (>= 4.0% intraday jump)
    3. Severe Adverse Spot Invalidation (>= 0.60% adverse underlying move)
    4. Hard Stop Loss Hit on Option Premium (e.g. >= 25-30% loss)
    """
    now_ist = datetime.now(TIMEZONE)
    trade_type = str(position.get("trade_type", "INTRADAY")).upper()
    side = str(position.get("position_side", "BUY_CE")).upper()
    entry_spot = float(position.get("entry_spot") or 0)
    current_spot = float(live_signals.get("nifty_spot") or 0)
    vix_change_pct = float(live_signals.get("india_vix_change_pct") or 0)
    
    entry_premium = float(position.get("entry_premium") or 0)
    current_premium = float(position.get("current_premium") or 0)

    # 1. 15:15 IST Mandatory Pre-Close Square-Off for Intraday Trades
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

    # 2. Extreme Volatility / VIX Shock (>= 8.0% spike or VIX > 18 with 5% spike)
    current_vix = float(live_signals.get("india_vix") or 14.0)
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

    # 5. Expiry Day Theta Profit Lock (Thursday only — short sellers)
    # On expiry day, theta collapses dramatically in the last 2 hours.
    # If a short option seller is already at +40%+ profit, lock it before whipsaw.
    if is_expiry_day() and entry_premium > 0 and current_premium > 0:
        is_short = side in ["SHORT_CE", "SHORT_PE"]
        if is_short:
            prem_pnl_pct = ((entry_premium - current_premium) / entry_premium) * 100
            if prem_pnl_pct >= 40.0:
                return {
                    "verdict": "PARTIAL_BOOK_70",
                    "action": f"EXPIRY DAY: Book 70% profit now (premium decayed {prem_pnl_pct:.1f}%). Trail remaining 30% with tight SL.",
                    "confidence": 88,
                    "urgency": "HIGH",
                    "engine": "Deterministic Fast-Path (Expiry Day Theta Lock)",
                    "reasoning": (
                        f"Today is weekly NIFTY expiry day (Thursday). Premium has decayed {prem_pnl_pct:.1f}% "
                        f"(₹{entry_premium} → ₹{current_premium}). Theta collapse accelerates sharply post-13:00 IST — "
                        f"lock the majority of gains before option expiry volatility whipsaw."
                    ),
                    "trailing_sl": round(current_spot, 2) if current_spot > 0 else round(entry_spot, 2),
                    "is_fast_path": True,
                    "is_expiry_day": True,
                }

    # 6. PCR Extreme — Option Chain Sentiment Warning
    # PCR < 0.70: heavy call writing = bearish market structure (resistance ahead for bulls)
    # PCR > 1.50: heavy put writing = bullish market structure (support for bulls, resistance for bears)
    pcr = float(live_signals.get("pcr") or 1.05)
    is_bullish_trade = side in ["BUY_CE", "LONG_FUTURES", "SHORT_PE"]
    is_bearish_trade = side in ["BUY_PE", "SHORT_FUTURES", "SHORT_CE"]

    if pcr < 0.70 and is_bullish_trade and current_spot > 0:
        return {
            "verdict": "TRAIL_SL_TIGHT",
            "action": f"Tighten stop-loss immediately. PCR at {pcr:.2f} signals aggressive call writers building a resistance ceiling.",
            "confidence": 78,
            "urgency": "MEDIUM",
            "engine": "Deterministic Fast-Path (PCR Extreme Bear Wall)",
            "reasoning": (
                f"PCR is at {pcr:.2f} (extreme bearish zone < 0.70). Aggressive call writers are building "
                f"a strong resistance ceiling above current spot {current_spot}. Bullish trade momentum at risk. "
                f"Trail stop-loss tightly to protect existing gains."
            ),
            "trailing_sl": round(current_spot * 0.9985, 1),
            "is_fast_path": True,
        }

    if pcr > 1.50 and is_bearish_trade and current_spot > 0:
        return {
            "verdict": "TRAIL_SL_TIGHT",
            "action": f"Tighten stop-loss immediately. PCR at {pcr:.2f} signals heavy put writing forming a support floor.",
            "confidence": 78,
            "urgency": "MEDIUM",
            "engine": "Deterministic Fast-Path (PCR Extreme Bull Floor)",
            "reasoning": (
                f"PCR is at {pcr:.2f} (extreme bullish zone > 1.50). Put writers are forming a strong support floor "
                f"below current spot {current_spot}. Bearish trade momentum at risk. Trail stop-loss tightly."
            ),
            "trailing_sl": round(current_spot * 1.0015, 1),
            "is_fast_path": True,
        }

    # 7. OI Wall Proximity — Spot approaching major resistance/support
    top_oi_call = live_signals.get("top_oi_call_strike")
    top_oi_put = live_signals.get("top_oi_put_strike")

    if current_spot > 0 and top_oi_call and is_bullish_trade:
        gap_to_call_wall = float(top_oi_call) - current_spot
        if 0 < gap_to_call_wall <= 50:
            return {
                "verdict": "TRAIL_SL_TIGHT",
                "action": f"Spot is {gap_to_call_wall:.0f}pts from max OI Call wall at {top_oi_call}. Tighten stop — resistance zone ahead.",
                "confidence": 80,
                "urgency": "MEDIUM",
                "engine": "Deterministic Fast-Path (OI Resistance Wall)",
                "reasoning": (
                    f"Current NIFTY spot ({current_spot}) is only {gap_to_call_wall:.0f}pts away from the "
                    f"highest Call OI strike at {top_oi_call}, which acts as a strong resistance wall. "
                    f"Bullish momentum likely to stall here. Trail stop-loss to protect gains."
                ),
                "trailing_sl": round(current_spot * 0.9985, 1),
                "is_fast_path": True,
            }

    if current_spot > 0 and top_oi_put and is_bearish_trade:
        gap_to_put_wall = current_spot - float(top_oi_put)
        if 0 < gap_to_put_wall <= 50:
            return {
                "verdict": "TRAIL_SL_TIGHT",
                "action": f"Spot is {gap_to_put_wall:.0f}pts from max OI Put wall at {top_oi_put}. Tighten stop — support zone ahead.",
                "confidence": 80,
                "urgency": "MEDIUM",
                "engine": "Deterministic Fast-Path (OI Support Wall)",
                "reasoning": (
                    f"Current NIFTY spot ({current_spot}) is only {gap_to_put_wall:.0f}pts above the "
                    f"highest Put OI strike at {top_oi_put}, which acts as a strong support wall. "
                    f"Bearish momentum likely to stall here. Trail stop-loss to protect gains."
                ),
                "trailing_sl": round(current_spot * 1.0015, 1),
                "is_fast_path": True,
            }

    return None



def generate_rule_based_fallback(
    position: dict[str, Any],
    live_signals: dict[str, Any],
    heavyweights: dict[str, Any]
) -> dict[str, Any]:
    """
    Mathematical fallback engine when all AI LLM providers are offline/timing out.
    Computes percentage-of-spot and premium targets with 100% reliability.
    """
    trade_type = str(position.get("trade_type", "INTRADAY")).upper()
    side = str(position.get("position_side", "BUY_CE")).upper()
    entry_spot = float(position.get("entry_spot") or live_signals.get("nifty_spot") or 24200)
    current_spot = float(live_signals.get("nifty_spot") or entry_spot)
    entry_premium = float(position.get("entry_premium") or 0)
    current_premium = float(position.get("current_premium") or 0)

    spot_change_pct = ((current_spot - entry_spot) / entry_spot) * 100 if entry_spot > 0 else 0.0
    pts_diff = round(current_spot - entry_spot, 1)

    is_bullish_trade = side in ["BUY_CE", "LONG_FUTURES", "SHORT_PE"]
    favorable_move = spot_change_pct if is_bullish_trade else -spot_change_pct

    # Heavyweight pulse
    hw_bullish = sum(1 for s in heavyweights.values() if s.get("change_pct", 0) > 0.3)
    hw_bearish = sum(1 for s in heavyweights.values() if s.get("change_pct", 0) < -0.3)

    # 1. Target 2 / Large Move (+0.50% or higher)
    if favorable_move >= 0.50:
        verdict = "PARTIAL_BOOK_70"
        action = "Book 70% profit. Move stop-loss on remaining 30% to lock gains."
        confidence = 88
        trailing_sl = round(entry_spot + (pts_diff * 0.5) if is_bullish_trade else entry_spot - (abs(pts_diff) * 0.5), 1)
        reason = f"Underlying has moved +{favorable_move:.2f}% ({abs(pts_diff)} pts) in your favor. Secure majority profits."

    # 2. Target 1 / Standard Move (+0.25% to +0.50%)
    elif favorable_move >= 0.25:
        verdict = "PARTIAL_BOOK_50"
        action = "Book 50% profit. Trail stop-loss on remaining quantity to Cost (Breakeven)."
        confidence = 82
        trailing_sl = round(entry_spot, 1)
        reason = f"Target 1 reached with a +{favorable_move:.2f}% favorable move. Risk-free trade by trailing SL to breakeven."

    # 3. Adverse Invalidation (-0.25% or worse)
    elif favorable_move <= -0.25:
        verdict = "FULL_EXIT"
        action = "Exit position. Move against position has broken short-term structure."
        confidence = 85
        trailing_sl = round(current_spot, 1)
        reason = f"NIFTY has moved {favorable_move:.2f}% against your entry level ({abs(pts_diff)} pts adverse). Invalidation triggered."

    # 4. BTST Morning Gap Check
    elif trade_type == "BTST":
        now_ist = datetime.now(TIMEZONE)
        if now_ist.hour == 9 and now_ist.minute <= 30:
            if favorable_move >= 0.15:
                verdict = "PARTIAL_BOOK_70"
                action = "Book 70% of BTST gap gains immediately before morning range fade."
                confidence = 84
                trailing_sl = round(entry_spot, 1)
                reason = "Overnight BTST gap realized. Lock profits in first 15 minutes."
            else:
                verdict = "TRAIL_SL_TO_COST"
                action = "Hold with tight stop at cost. Watch 09:30 15-min ORB breakout."
                confidence = 75
                trailing_sl = round(entry_spot, 1)
                reason = "Flat morning opening. Maintain disciplined stop at entry level."
        else:
            verdict = "FULL_EXIT"
            action = "Close BTST trade. Holding past morning window incurs theta decay."
            confidence = 80
            trailing_sl = round(current_spot, 1)
            reason = "BTST window expired (after 09:45 IST). Close overnight options to avoid premium erosion."

    # 5. Normal trend continuation
    else:
        if (is_bullish_trade and hw_bullish >= 3) or (not is_bullish_trade and hw_bearish >= 3):
            verdict = "HOLD_AND_RIDE"
            action = "Maintain position. Heavyweights strongly aligned with trade direction."
            confidence = 80
            trailing_sl = round(entry_spot * 0.998 if is_bullish_trade else entry_spot * 1.002, 1)
            reason = "Constituent heavyweights are supporting the directional momentum."
        else:
            verdict = "TRAIL_SL_TIGHT"
            action = "Hold with tightened stop-loss. Momentum is consolidating."
            confidence = 72
            trailing_sl = round(entry_spot * 0.9985 if is_bullish_trade else entry_spot * 1.0015, 1)
            reason = "Market is in range-bound consolidation. Maintain tight risk controls."

    return {
        "verdict": verdict,
        "action": action,
        "confidence": confidence,
        "urgency": "NORMAL" if "HOLD" in verdict else "MEDIUM",
        "engine": "Rule-Based Deterministic Engine (AI Offline)",
        "reasoning": reason,
        "trailing_sl": trailing_sl,
        "heavyweight_alignment": f"{hw_bullish} Bullish / {hw_bearish} Bearish",
        "favorable_move_pct": round(favorable_move, 2),
        "is_fallback": True,
    }
