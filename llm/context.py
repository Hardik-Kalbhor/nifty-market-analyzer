"""
llm/context.py — User content builders, F&O expiry context, and BTST conflict resolution.
"""

import json
import logging
from typing import Any, Optional
from datetime import date, timedelta
import calendar
import pytz

from .constants import NIFTY_50_WEIGHTS

logger = logging.getLogger(__name__)

def _get_fo_expiry_context() -> str:
    """
    Compute F&O expiry context for today (IST).
    Weekly expiry = every Tuesday (effective Sep 2025). Monthly expiry = last Tuesday of the month.
    """
    from datetime import date, timedelta
    import calendar
    import pytz
    from datetime import datetime
    today = datetime.now(pytz.timezone("Asia/Kolkata")).date()

    # Find the last Tuesday of this month
    year, month = today.year, today.month
    last_day = calendar.monthrange(year, month)[1]
    last_tue = max(
        date(year, month, d)
        for d in range(last_day, 0, -1)
        if date(year, month, d).weekday() == 1
    )

    is_weekly_expiry = today.weekday() == 1  # Tuesday
    is_monthly_expiry = is_weekly_expiry and today == last_tue
    tomorrow_is_expiry = (today + timedelta(days=1)).weekday() == 1

    if is_monthly_expiry:
        return "⚠️ TODAY IS MONTHLY F&O EXPIRY (Tuesday). Strong pin-to-Max-Pain bias. Force NO TRADE unless a massive catalyst exists."
    elif is_weekly_expiry:
        return "⚠️ TODAY IS WEEKLY F&O EXPIRY (Tuesday). Option writers defend Max Pain. Bias FLAT. Reduce confidence by 10%."
    elif tomorrow_is_expiry:
        return "📅 TOMORROW IS F&O EXPIRY (Tuesday). BTST positions carry overnight expiry risk — prefer NO TRADE or very tight targets."
    return "No F&O expiry today or tomorrow."


def _build_user_content(
    news_items: list[dict],
    market_signals: dict,
    fii_dii_data: dict | None = None,
    heavyweights: dict | None = None,
    past_context: str = "",
) -> str:
    """Build enriched user prompt with all market signals, live heavyweights, FII/DII, and F&O expiry context.

    past_context: formatted string of past NIFTY lessons from NiftyMemoryLog.load_past_context()
                  (Phase D injection). Empty string = no memory yet.
    """
    compact_news = [
        {"headline": item.get("headline"), "sector": item.get("sector"), "category": item.get("category")}
        for item in news_items[:15]
    ]

    nifty_spot = market_signals.get("nifty_spot")
    nifty_pct = market_signals.get("nifty_pct")
    max_pain = market_signals.get("max_pain")
    top_call = market_signals.get("top_oi_call_strike")
    top_put = market_signals.get("top_oi_put_strike")
    fo_context = _get_fo_expiry_context()

    spot_line = f"Nifty 50 Spot: {nifty_spot} ({nifty_pct:+.2f}%)" if nifty_spot else "Nifty 50 Spot: Market closed / unavailable"
    if max_pain:
        oi_line = f"Max Pain: {max_pain} | Top Call OI Wall (Resistance): {top_call} | Top Put OI Floor (Support): {top_put}"
    else:
        oi_line = "PCR/Max Pain/OI Strikes: Neutral defaults (Use PCR if available)"

    vix_val = market_signals.get("india_vix")
    vix_chg = market_signals.get("india_vix_change_pct")
    vix_str = f"{vix_val:.2f} ({vix_chg:+.2f}%)" if (vix_val is not None and vix_chg is not None) else (f"{vix_val:.2f}" if vix_val is not None else "12.5 (Estimated Calm)")

    gift_chg = market_signals.get("gift_nifty_change_pct")
    gift_str = f"{gift_chg:+.2f}%" if gift_chg is not None else "0.00%"

    pcr_val = market_signals.get("pcr")
    pcr_str = f"{pcr_val:.2f}" if pcr_val is not None else "1.05"

    bank_pct = market_signals.get("sectoral_signals", {}).get("bank_nifty_pct")
    bank_str = f"{bank_pct:+.2f}%" if bank_pct is not None else "0.00%"

    it_pct = market_signals.get("sectoral_signals", {}).get("it_nifty_pct")
    it_str = f"{it_pct:+.2f}%" if it_pct is not None else "0.00%"

    # Live Heavyweights (~39% NIFTY impact)
    hw_lines = []
    if heavyweights:
        for sym, d in heavyweights.items():
            if isinstance(d, dict) and "name" in d:
                hw_lines.append(f"  • {d['name']} ({d.get('weight', 0)}% weight): ₹{d.get('price', 0)} ({d.get('change_pct', 0):+.2f}%)")
    hw_text = "\n".join(hw_lines) if hw_lines else "  • Heavyweights live feed loading..."

    # FII/DII Institutional Flow
    if fii_dii_data and isinstance(fii_dii_data, dict):
        fii_net = fii_dii_data.get("fii_net_crores", 0)
        dii_net = fii_dii_data.get("dii_net_crores", 0)
        inst_sent = fii_dii_data.get("institutional_sentiment", "NEUTRAL")
        fii_text = f"  • FII: ₹{fii_net:+.0f} Cr | DII: ₹{dii_net:+.0f} Cr | Net: ₹{fii_net + dii_net:+.0f} Cr ({inst_sent})"
    else:
        fii_text = "  • FII/DII data unavailable."

    # Phase D: Inject past lessons from memory log (if any)
    memory_section = (
        f"\n\n{past_context}\n\n"
        "Apply the above lessons when evaluating today's signals. Avoid repeating recently observed mistakes.\n"
        if past_context.strip()
        else ""
    )

    return f"""
    NIFTY 50 Multi-Source Input Data:

    📰 Scraped News Articles ({len(compact_news)} items):
{json.dumps(compact_news, indent=2)}

    📊 Live Market Microstructure Signals:
    - {spot_line}
    - GIFT Nifty Overnight Change: {gift_str}
    - India VIX: {vix_str}
    - Put-Call Ratio (PCR): {pcr_str} (>1.25 Bullish, <0.80 Bearish)
    - {oi_line}
    - Bank Nifty: {bank_str}
    - IT Nifty: {it_str}
    - Global Market Cues: {json.dumps(market_signals.get('global_market_changes', {}))}

    🏛️ Institutional Cash Flows (FII / DII):
{fii_text}

    🏢 Top 5 NIFTY Heavyweights (~39% Index Impact):
{hw_text}

    📅 F&O Expiry Context: {fo_context}
{memory_section}
    Evaluate across all 6 specialist dimensions and produce the BTST prediction JSON.
    """


# Weights for each BTST specialist dimension
_BTST_WEIGHTS = {
    "macro_global": 0.25,
    "fii_dii": 0.20,
    "heavyweights": 0.20,
    "oi_pcr": 0.15,
    "news_catalyst": 0.10,
    "vix_regime": 0.10,
}


