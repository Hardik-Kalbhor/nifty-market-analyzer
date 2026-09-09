"""
intraday/market_phase.py — Time-of-day market phase detection.
"""

from datetime import datetime
from .constants import IST

def _get_market_phase() -> dict:
    """Determine the current market phase based on IST time."""
    now = datetime.now(IST)
    hour = now.hour
    minute = now.minute
    time_val = hour * 100 + minute

    if time_val < 900:
        return {
            "phase": "PRE-MARKET",
            "description": "Markets haven't opened yet. Focus on global cues and overnight news.",
            "volatility_factor": 1.0,
            "icon": "🌅",
        }
    elif time_val < 915:
        return {
            "phase": "PRE-OPEN",
            "description": "Pre-open session active. Gap prediction is most relevant.",
            "volatility_factor": 1.2,
            "icon": "⏰",
        }
    elif time_val < 945:
        return {
            "phase": "OPENING HALF-HOUR",
            "description": "High volatility opening phase. Gap fill or extension pattern determines the day.",
            "volatility_factor": 1.5,
            "icon": "🔥",
        }
    elif time_val < 1130:
        return {
            "phase": "TREND FORMATION",
            "description": "The day's trend is being established. Watch for breakout/breakdown from opening range.",
            "volatility_factor": 1.2,
            "icon": "📈",
        }
    elif time_val < 1330:
        return {
            "phase": "LUNCH SESSION",
            "description": "Low volume lunch period. Markets tend to be range-bound and choppy.",
            "volatility_factor": 0.7,
            "icon": "🍽️",
        }
    elif time_val < 1500:
        return {
            "phase": "AFTERNOON TREND",
            "description": "Institutional activity picks up. Closing trend starts forming.",
            "volatility_factor": 1.3,
            "icon": "📊",
        }
    elif time_val < 1530:
        return {
            "phase": "CLOSING SESSION",
            "description": "Last 30 minutes — short covering, profit booking, and closing moves.",
            "volatility_factor": 1.4,
            "icon": "🏁",
        }
    else:
        return {
            "phase": "AFTER MARKET",
            "description": "Markets are closed. Focus shifts to next-day prediction (BTST).",
            "volatility_factor": 0.5,
            "icon": "🌙",
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Intraday Pattern Detection
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

