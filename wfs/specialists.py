"""
wfs/specialists.py — Evaluation of 7 specialist dimensions for historical sessions.
"""

from typing import Any
from .constants import _safe_float, _safe_int

def evaluate_7_specialist_dimensions(session: dict[str, Any]) -> dict[str, Any]:
    """
    Evaluates market conditions from the 7 Specialist Dimensions:
    1. Greeks & Decay: DTE to expiry, theta erosion, ITM/ATM/OTM delta profile.
    2. OI & PCR: Put-Call Ratio ceiling (>1.50) / floor (<0.70).
    3. Heavyweights: HDFC Bank + Reliance + ICICI Bank + INFY + TCS alignment.
    4. Price Action: Day return %, range location, ORB momentum.
    5. VIX Regime: India VIX absolute level (<13 calm, 13-16 moderate, >16 elevated) & change.
    6. Macro & Global: FII/DII institutional cash flow + S&P 500 / NASDAQ overnight cues.
    7. Social Contrarian: Retail crowd mood vs institutional money positioning (Trap alerts).
    """
    session = session or {}
    dte = _safe_int(session.get("dte"), 3)
    pcr = _safe_float(session.get("pcr"), 1.0)
    vix = _safe_float(session.get("india_vix"), 14.0)
    vix_change = _safe_float(session.get("vix_change_pct"), 0.0)
    change_pct = _safe_float(session.get("change_pct"), 0.0)
    fii_net = _safe_float(session.get("fii_net_crores"), 0.0)
    social = session.get("social_sentiment") or {}
    contrarian_alert = str(social.get("contrarian_warning") or "")
    hw = session.get("heavyweights") or {}

    # 1. Greeks & Decay Agent
    greeks_verdict = "HOLD"
    if dte == 0:
        greeks_verdict = "PARTIAL_BOOK_70" if abs(change_pct) >= 0.3 else "TRAIL_SL_TIGHT"
        greeks_note = "Expiry day 0 DTE: aggressive theta burn requires rapid profit lock or exit."
    elif dte == 1:
        greeks_verdict = "PARTIAL_BOOK_50" if abs(change_pct) >= 0.4 else "HOLD"
        greeks_note = "1 DTE pre-expiry: theta decay accelerates past 13:00 IST."
    else:
        greeks_note = f"{dte} DTE: Normal theta decay curve; options delta intact."

    # 2. OI & PCR Agent
    if pcr < 0.70:
        oi_verdict = "BEARISH_WALL"
        oi_note = f"PCR at {pcr:.2f} (<0.70): Aggressive call writers forming resistance ceiling."
    elif pcr > 1.45:
        oi_verdict = "BULLISH_FLOOR"
        oi_note = f"PCR at {pcr:.2f} (>1.45): Heavy put writing providing strong underlying floor."
    else:
        oi_verdict = "BALANCED"
        oi_note = f"PCR at {pcr:.2f}: Even distribution across option strikes."

    # 3. Heavyweights Agent
    hw_bulls = sum(1 for s in hw.values() if isinstance(s, dict) and _safe_float(s.get("change_pct")) > 0.3)
    hw_bears = sum(1 for s in hw.values() if isinstance(s, dict) and _safe_float(s.get("change_pct")) < -0.3)
    if hw_bulls >= 3:
        hw_verdict = "BULLISH_ALIGNED"
        hw_note = f"{hw_bulls}/5 heavyweights strongly advancing (>0.3%)."
    elif hw_bears >= 3:
        hw_verdict = "BEARISH_ALIGNED"
        hw_note = f"{hw_bears}/5 heavyweights declining (<-0.3%)."
    else:
        hw_verdict = "DIVERGENT"
        hw_note = f"Heavyweights split: {hw_bulls} up, {hw_bears} down."

    # 4. Price Action Agent
    if change_pct >= 0.40:
        pa_verdict = "STRONG_BULLISH"
        pa_note = f"Strong bullish momentum (+{change_pct:.2f}%) with higher intraday highs."
    elif change_pct <= -0.40:
        pa_verdict = "STRONG_BEARISH"
        pa_note = f"Heavy selling pressure ({change_pct:.2f}%) breaking support."
    else:
        pa_verdict = "CONSOLIDATION"
        pa_note = f"Range-bound consolidation ({change_pct:+.2f}%)."

    # 5. VIX Regime Agent
    if vix_change >= 6.0 or vix >= 18.0:
        vix_verdict = "VOLATILITY_SHOCK"
        vix_note = f"VIX elevated at {vix:.1f} (+{vix_change:.1f}% intraday surge)."
    elif vix < 13.0:
        vix_verdict = "CALM_LOW_VOL"
        vix_note = f"Subdued volatility (VIX {vix:.1f}); favourable for directional trend holding."
    else:
        vix_verdict = "NORMAL"
        vix_note = f"VIX at {vix:.1f}; standard options pricing environment."

    # 6. Macro & Global Agent
    global_cues = session.get("global_cues") or {}
    sp_pct = _safe_float(global_cues.get("sp500_pct"), 0.0)
    if fii_net > 1000 and sp_pct > 0.2:
        macro_verdict = "BULLISH_FLOW"
        macro_note = f"FII net cash buying +₹{fii_net:,.0f} Cr aligned with positive US markets."
    elif fii_net < -1000 and sp_pct < -0.2:
        macro_verdict = "BEARISH_FLOW"
        macro_note = f"FII net cash selling ₹{fii_net:,.0f} Cr aligned with weak global cues."
    else:
        macro_verdict = "NEUTRAL"
        macro_note = f"FII net ₹{fii_net:,.0f} Cr; mixed institutional cues."

    # 7. Social Contrarian Agent
    if "BULL TRAP" in contrarian_alert:
        social_verdict = "BULL_TRAP_DANGER"
        social_note = "Retail euphoria clashes with institutional distribution. High bull trap probability."
    elif "BEAR TRAP" in contrarian_alert:
        social_verdict = "BEAR_TRAP_DANGER"
        social_note = "Retail panic clashes with institutional accumulation. High short squeeze risk."
    else:
        social_verdict = "NEUTRAL"
        social_note = f"Social mood {social.get('mood', 'NEUTRAL')} without acute divergence."

    return {
        "greeks_decay": {"verdict": greeks_verdict, "note": greeks_note},
        "oi_pcr": {"verdict": oi_verdict, "note": oi_note},
        "heavyweights": {"verdict": hw_verdict, "note": hw_note},
        "price_action": {"verdict": pa_verdict, "note": pa_note},
        "vix_regime": {"verdict": vix_verdict, "note": vix_note},
        "macro_global": {"verdict": macro_verdict, "note": macro_note},
        "social_contrarian": {"verdict": social_verdict, "note": social_note},
    }


