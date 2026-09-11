"""
exit/context.py — Exit prompt context builder.
"""

import json
from datetime import datetime
from typing import Any
from .constants import TIMEZONE
from .context_helpers import format_moneyness, format_dte, format_social_and_cognigraph
from exit_fast.constants import _safe_float


def build_exit_prompt_context(
    position: dict[str, Any],
    live_signals: dict[str, Any],
    heavyweights: dict[str, Any],
    news_items: list[dict],
    fii_dii_data: dict[str, Any] | None = None,
    social_sentiment: dict[str, Any] | None = None,
    cognigraph_context: str | None = None,
) -> str:
    """
    Builds rich, structured prompt with live position status, P&L %, heavyweights,
    FII/DII flow, option chain data, DTE, strike moneyness, expiry day context,
    social sentiment contrarian signals, and CogniGraph causal regime memory.
    """
    now_ist = datetime.now(TIMEZONE)
    trade_type = str(position.get("trade_type", "INTRADAY")).upper()
    side = str(position.get("position_side", "BUY_CE")).upper()
    strike = position.get("strike", "At-The-Money")
    entry_spot = _safe_float(position.get("entry_spot") or live_signals.get("nifty_spot"), default=0.0)
    current_spot = _safe_float(live_signals.get("nifty_spot"), default=entry_spot)

    entry_premium = _safe_float(position.get("entry_premium") or position.get("entry_price") or position.get("buy_price") or position.get("avg_price"), default=0.0)
    current_premium = _safe_float(position.get("current_premium") or position.get("current_ltp") or position.get("current_price") or position.get("ltp"), default=0.0)
    entry_time = position.get("entry_time", "Earlier today")
    risk_profile = position.get("risk_profile", "BALANCED").upper()
    dte = position.get("dte")

    spot_diff = round(current_spot - entry_spot, 1)
    spot_pct = round(((current_spot - entry_spot) / entry_spot) * 100, 2) if entry_spot > 0 else 0.0

    is_bullish = side in ["BUY_CE", "LONG_FUTURES", "SHORT_PE"]
    favorable_move = spot_pct if is_bullish else -spot_pct

    prem_info = "N/A (Tracking Spot)"
    if entry_premium > 0 and current_premium > 0:
        if side in ["SHORT_CE", "SHORT_PE"]:
            pnl_pct = round(((entry_premium - current_premium) / entry_premium) * 100, 1)
        else:
            pnl_pct = round(((current_premium - entry_premium) / entry_premium) * 100, 1)
        prem_info = f"Entry: ₹{entry_premium} ➔ Current: ₹{current_premium} ({pnl_pct:+.1f}% P&L)"

    moneyness_text = format_moneyness(strike, side, current_spot)
    dte_text = format_dte(dte)

    hw_lines = [f"  • {d['name']} ({d['weight']}% weight): ₹{d['price']} ({d['change_pct']:+.2f}%)" for sym, d in heavyweights.items()]
    hw_text = "\n".join(hw_lines) if hw_lines else "  • Heavyweight data loading..."

    pcr = live_signals.get("pcr", 1.05)
    max_pain = live_signals.get("max_pain", "N/A")
    top_oi_call = live_signals.get("top_oi_call_strike", "N/A")
    top_oi_put = live_signals.get("top_oi_put_strike", "N/A")
    pcr_interp = (
        "BEARISH (heavy call writing = resistance ceiling)" if pcr < 0.80 else
        "BULLISH (heavy put writing = support floor)" if pcr > 1.30 else
        "NEUTRAL"
    )
    oi_text = (
        f"  • PCR: {pcr:.2f} → {pcr_interp}\n"
        f"  • Max Pain: {max_pain} | Top Call OI Wall: {top_oi_call} | Top Put OI Floor: {top_oi_put}"
    )

    if fii_dii_data:
        fii_net = fii_dii_data.get("fii_net_crores", 0)
        dii_net = fii_dii_data.get("dii_net_crores", 0)
        inst_sentiment = fii_dii_data.get("institutional_sentiment", "NEUTRAL")
        fii_dii_text = f"  • FII Net: ₹{fii_net:+,.0f} Cr | DII Net: ₹{dii_net:+,.0f} Cr ({inst_sentiment})"
    else:
        fii_dii_text = "  • FII/DII data unavailable."

    social_text, cognigraph_text = format_social_and_cognigraph(
        fii_dii_data, news_items, social_sentiment, cognigraph_context, live_signals
    )

    compact_news = [f"  • [{it.get('category', 'Market')}] {it.get('headline')}" for it in news_items[:8]]
    news_text = "\n".join(compact_news) if compact_news else "  • No breaking market-moving headlines."

    time_ctx = f"Current Time: {now_ist.strftime('%H:%M:%S IST')}."
    if now_ist.hour == 9 and now_ist.minute <= 30:
        time_ctx += " ⚠️ MORNING OPENING GAP / 15-MIN ORB PHASE. High volatility and gap-fill risk."
    elif now_ist.hour == 13 and 15 <= now_ist.minute <= 45:
        time_ctx += " ⚠️ EUROPEAN MARKET OPEN WINDOW (13:30 IST). Watch for afternoon trend shift."
    elif now_ist.hour == 15 and now_ist.minute >= 0:
        time_ctx += " ⚠️ PRE-CLOSE INTRADAY AUTO-SQUARE-OFF WINDOW."

    vix_val = live_signals.get("india_vix")
    vix_chg = live_signals.get("india_vix_change_pct")
    vix_text = f"{vix_val:.2f} (Intraday Change: {vix_chg:+.2f}%)" if (vix_val is not None and vix_chg is not None) else (f"{vix_val:.2f}" if vix_val is not None else "12.5 (Estimated Calm Regime)")

    nifty_pct_val = live_signals.get("nifty_pct")
    nifty_pct_text = f"{nifty_pct_val:+.2f}%" if nifty_pct_val is not None else "0.00%"

    bank_pct_val = live_signals.get("sectoral_signals", {}).get("bank_nifty_pct")
    bank_pct_text = f"{bank_pct_val:+.2f}%" if bank_pct_val is not None else "0.00%"

    it_pct_val = live_signals.get("sectoral_signals", {}).get("it_nifty_pct")
    it_pct_text = f"{it_pct_val:+.2f}%" if it_pct_val is not None else "0.00%"

    # Quantitative Risk Metrics & Order Flow Context
    mfe_pct = float(position.get("mfe_pct", favorable_move) or 0.0)
    mae_pct = float(position.get("mae_pct", 0.0) or 0.0)
    mfe_r = float(position.get("mfe_r", 0.0) or 0.0)
    curr_r = float(position.get("current_r", 0.0) or 0.0)
    mfe_locked_str = "ACTIVE (Breakeven Locked)" if position.get("mfe_locked") else "Inactive"
    elapsed_mins = float(position.get("elapsed_minutes", 0.0) or 0.0)
    atr_val = float(live_signals.get("atr_14_1min", 18.0) or 18.0)
    atr_trail = float(position.get("atr_trail_level", current_spot) or current_spot)

    coi_call = float(live_signals.get("coi_call_change_pct", 0.0) or 0.0)
    coi_put = float(live_signals.get("coi_put_change_pct", 0.0) or 0.0)
    cvd_dir = str(live_signals.get("cvd_divergence", "NEUTRAL")).upper()
    atm_strike = live_signals.get("atm_strike", "N/A")

    coi_interp = (
        f"⚠️ AGGRESSIVE CALL WRITING (+{coi_call:.1f}% in 5m) — smart money selling into rally" if coi_call >= 15.0 else
        (f"⚠️ AGGRESSIVE PUT WRITING (+{coi_put:.1f}% in 5m) — support floor being erected" if coi_put >= 15.0 else "Normal writing pace")
    )

    return f"""
    === USER'S LIVE OPEN POSITION ===
    - Trade Type: {trade_type} ({'Overnight BTST' if trade_type == 'BTST' else 'Intraday Day Trade'})
    - Position Side: {side} ({strike})
    - {moneyness_text}
    - Entry NIFTY Spot: {entry_spot} | Live NIFTY Spot: {current_spot} (Diff: {spot_diff:+.1f} pts, {spot_pct:+.2f}%)
    - Directional Performance: {favorable_move:+.2f}% {'Favorable ✅' if favorable_move >= 0 else 'Adverse ❌'}
    - Option Premium Status: {prem_info}
    - Entry Time: {entry_time} (Elapsed: {elapsed_mins:.0f} mins) | Risk Profile: {risk_profile}
    - {time_ctx}
    - Expiry / Theta Context: {dte_text}

    === QUANTITATIVE RISK & EXCURSION METRICS ===
    - MFE (Peak Favorable Excursion): {mfe_pct:+.2f}% | Peak R-Multiple: {mfe_r:.2f}R | MFE Lock: {mfe_locked_str}
    - MAE (Max Adverse Excursion): {mae_pct:+.2f}% | Current R-Multiple: {curr_r:+.2f}R
    - ATR-14 Trailing Level (k=1.5): {atr_trail:.1f} (1-min ATR = {atr_val:.1f} pts)
    - Dead-Money Timeout Threshold: 35 minutes (Current: {elapsed_mins:.0f} mins)

    === LIVE MARKET MICROSTRUCTURE & ORDER FLOW ===
    - NIFTY 50 Change: {nifty_pct_text}
    - India VIX: {vix_text}
    - ATM Strike: {atm_strike}
    - COI Call Velocity (5-min): {coi_call:+.1f}% | COI Put Velocity (5-min): {coi_put:+.1f}%
    - COI Microstructure Flow: {coi_interp}
    - CVD Volume Delta Proxy (5 bars): {cvd_dir}
    - Bank Nifty: {bank_pct_text}
    - IT Nifty: {it_pct_text}
    - Global Asian / US Cues: {json.dumps(live_signals.get('global_market_changes', {}))}

    === OPTION CHAIN — OI STRUCTURE ===
{oi_text}

    === INSTITUTIONAL FLOW (FII / DII) ===
{fii_dii_text}

    === TOP 5 NIFTY CONSTITUENT HEAVYWEIGHTS (~39% Index Impact) ===
{hw_text}

    === RETAIL SOCIAL SENTIMENT & CONTRARIAN TRAP SIGNALS ===
{social_text}

    === COGNIGRAPH CAUSAL REGIME PRECEDENTS & HISTORICAL TRAPS ===
{cognigraph_text}

    === BREAKING NEWS HEADLINES ===
{news_text}

    Evaluate this live trade across all 7 specialist dimensions (including SOCIAL_CONTRARIAN), plus MFE_MAE and ORDER_FLOW (9 dimensions total), then synthesise a final verdict. Return the JSON exit recommendation.
    """
