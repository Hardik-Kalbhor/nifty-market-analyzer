"""
exit/enricher.py — Quantitative Position Enricher.
Computes MFE/MAE excursions, R-multiples, ATR-scaled trails, elapsed time, and option attributes.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, date, time as dtime
from typing import Any
import pytz

from .session_manager import get_trade_session_manager, TradeSessionManager

logger = logging.getLogger(__name__)
TIMEZONE = pytz.timezone("Asia/Kolkata")


def _parse_elapsed_minutes(entry_time_raw: Any, now_dt: datetime) -> float:
    """Parse various formats of entry_time into elapsed minutes."""
    if entry_time_raw is None:
        return 0.0

    if isinstance(entry_time_raw, (int, float)):
        return max(0.0, float(entry_time_raw))

    if isinstance(entry_time_raw, datetime):
        if entry_time_raw.tzinfo is None:
            entry_time_raw = TIMEZONE.localize(entry_time_raw)
        delta = (now_dt - entry_time_raw).total_seconds() / 60.0
        return max(0.0, round(delta, 1))

    s = str(entry_time_raw).strip()
    if not s or s.lower() in ("earlier today", "morning", "open", "n/a"):
        return 0.0

    # Match ISO format: 2026-09-11T10:05:00
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = TIMEZONE.localize(dt)
        delta = (now_dt - dt).total_seconds() / 60.0
        return max(0.0, round(delta, 1))
    except Exception:
        pass

    # Match time string: HH:MM or HH:MM:SS
    m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?", s)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        ss = int(m.group(3) or 0)
        today = now_dt.date()
        entry_dt = TIMEZONE.localize(datetime.combine(today, dtime(hh, mm, ss)))
        delta = (now_dt - entry_dt).total_seconds() / 60.0
        return max(0.0, round(delta, 1))

    # Match explicit minutes string e.g. "45 min"
    m_min = re.match(r"^(\d+(?:\.\d+)?)\s*(?:min|m|minutes)?$", s, re.I)
    if m_min:
        return float(m_min.group(1))

    return 0.0


def enrich_position(
    position: dict[str, Any],
    live_signals: dict[str, Any],
    session_mgr: TradeSessionManager | None = None,
) -> dict[str, Any]:
    """
    Enriches open position with quantitative risk parameters:
    - MFE % & R-Multiple (Maximum Favorable Excursion)
    - MAE % (Maximum Adverse Excursion)
    - MFE Breakeven Lock status (>= 1.5R)
    - Elapsed minutes since entry
    - ATR-14 1-min scaled trailing stop level
    - Directional R-multiple (current favorable excursion in R units, 1R = 0.60%)
    - Option buyer / seller classification
    - GIFT Nifty indicative price & open 1-min low
    """
    enriched = dict(position)
    now_dt = datetime.now(TIMEZONE)

    current_spot = float(live_signals.get("nifty_spot") or enriched.get("entry_spot") or 24200.0)
    entry_spot = float(enriched.get("entry_spot") or current_spot or 24200.0)
    enriched["entry_spot"] = entry_spot
    enriched["current_spot"] = current_spot

    side = str(enriched.get("position_side", "BUY_CE")).upper()
    enriched["position_side"] = side
    is_bullish = side in ["BUY_CE", "LONG_FUTURES", "SHORT_PE"]
    is_bearish = side in ["BUY_PE", "SHORT_FUTURES", "SHORT_CE"]
    enriched["is_bullish"] = is_bullish
    enriched["is_bearish"] = is_bearish
    enriched["is_option_buyer"] = side in ["BUY_CE", "BUY_PE"]
    enriched["is_option_seller"] = side in ["SHORT_CE", "SHORT_PE"]

    # Directional spot performance
    spot_diff = current_spot - entry_spot
    spot_pct = (spot_diff / entry_spot) * 100.0 if entry_spot > 0 else 0.0
    favorable_move_pct = spot_pct if is_bullish else -spot_pct
    enriched["spot_pct_move"] = round(spot_pct, 2)
    enriched["favorable_move_pct"] = round(favorable_move_pct, 2)

    # 1R = 0.60% move (hard stop loss distance)
    current_r = round(favorable_move_pct / 0.60, 2)
    enriched["current_r"] = current_r

    # Elapsed time calculation
    entry_time_raw = enriched.get("entry_time")
    elapsed_minutes = _parse_elapsed_minutes(entry_time_raw, now_dt)
    if "elapsed_minutes" in enriched and enriched["elapsed_minutes"] is not None:
        try:
            elapsed_minutes = max(elapsed_minutes, float(enriched["elapsed_minutes"]))
        except Exception:
            pass
    enriched["elapsed_minutes"] = elapsed_minutes

    # Session-backed MFE / MAE tracking
    sm = session_mgr or get_trade_session_manager()
    session = sm.create_or_get_session(enriched, live_spot=current_spot)
    session_id = session.get("session_id")
    enriched["session_id"] = session_id

    mfe_pct = float(session.get("mfe_pct", 0.0))
    mae_pct = float(session.get("mae_pct", 0.0))
    mfe_r = float(session.get("mfe_r", 0.0))

    # Allow client override if explicitly provided
    if enriched.get("mfe_spot") is not None:
        try:
            mfe_sp = float(enriched["mfe_spot"])
            calc_mfe = ((mfe_sp - entry_spot) / entry_spot) * 100.0 if is_bullish else ((entry_spot - mfe_sp) / entry_spot) * 100.0
            mfe_pct = max(mfe_pct, round(calc_mfe, 2))
            mfe_r = round(mfe_pct / 0.60, 2)
        except Exception:
            pass

    if enriched.get("mae_spot") is not None:
        try:
            mae_sp = float(enriched["mae_spot"])
            calc_mae = ((mae_sp - entry_spot) / entry_spot) * 100.0 if is_bullish else ((entry_spot - mae_sp) / entry_spot) * 100.0
            mae_pct = min(mae_pct, round(calc_mae, 2))
        except Exception:
            pass

    # Ensure mfe is at least current favorable move
    mfe_pct = max(mfe_pct, favorable_move_pct)
    mfe_r = max(mfe_r, current_r)
    enriched["mfe_pct"] = round(mfe_pct, 2)
    enriched["mae_pct"] = round(mae_pct, 2)
    enriched["mfe_r"] = round(mfe_r, 2)
    enriched["mfe_locked"] = bool(mfe_r >= 1.5)

    # ATR-14 Trailing Level calculation
    atr_val = float(live_signals.get("atr_14_1min") or 18.0)
    risk_prof = str(enriched.get("risk_profile") or "BALANCED").upper()
    if enriched.get("atr_multiplier"):
        atr_k = float(enriched["atr_multiplier"])
    elif risk_prof == "CONSERVATIVE":
        atr_k = 1.0
    elif risk_prof in ("TREND_RIDER", "AGGRESSIVE"):
        atr_k = 2.0
    else:
        atr_k = 1.5
    enriched["atr_14_1min"] = atr_val
    enriched["atr_multiplier"] = atr_k

    if is_bullish:
        enriched["atr_trail_level"] = round(current_spot - (atr_k * atr_val), 1)
    else:
        enriched["atr_trail_level"] = round(current_spot + (atr_k * atr_val), 1)

    # Microstructure & BTST helpers
    gift_ind = float(live_signals.get("gift_nifty_indicative") or 0.0)
    if gift_ind <= 0 and current_spot > 0:
        gift_chg = float(live_signals.get("gift_nifty_change_pct", 0.0) or 0.0)
        gift_ind = round(current_spot * (1 + gift_chg / 100.0), 1)
    enriched["gift_nifty_indicative"] = gift_ind

    open_low = float(live_signals.get("open_1min_low") or (current_spot - 25.0 if current_spot > 0 else 0.0))
    enriched["open_1min_low"] = open_low

    return enriched
