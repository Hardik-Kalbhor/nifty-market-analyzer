"""
intraday/patterns.py — Intraday candlestick/gap pattern detection.
"""

from typing import Any

def _detect_intraday_pattern(
    gap_prediction: str,
    news_sentiment: str,
    sentiment_score: float,
    event_risk: str,
) -> dict:
    """
    Detect the expected intraday pattern based on gap prediction,
    sentiment, and news scores.
    """
    # Pattern matrix
    if gap_prediction == "GAP UP":
        if news_sentiment == "BULLISH" and sentiment_score > 5:
            return {
                "pattern": "TRENDING UP",
                "description": "Strong gap up with bullish sentiment. Expect a trending up day with higher highs.",
                "strategy": "Buy on dips. Trail stop-loss at opening price. Target: 1-1.5% above open.",
                "option_strategy": "Buy CE at opening dip. Sell PE for premium collection.",
                "risk_level": "MODERATE",
            }
        elif news_sentiment == "BEARISH":
            return {
                "pattern": "GAP FILL",
                "description": "Gap up against bearish pressure. High probability of gap fill during the day.",
                "strategy": "Sell on rise near resistance. Target: Previous day's close. Stop-loss: Day's high.",
                "option_strategy": "Buy PE or sell CE at higher strikes. Gap fill probability is high.",
                "risk_level": "HIGH",
            }
        else:
            return {
                "pattern": "RANGE + UPSIDE BIAS",
                "description": "Gap up with mixed signals. Likely to consolidate with mild upside bias.",
                "strategy": "Buy near day's low, sell near day's high. Keep tight stop-losses.",
                "option_strategy": "Short strangle/straddle if premium is good. Buy CE for directional play.",
                "risk_level": "MODERATE",
            }

    elif gap_prediction == "GAP DOWN":
        if news_sentiment == "BEARISH" and sentiment_score < -5:
            return {
                "pattern": "TRENDING DOWN",
                "description": "Strong gap down with bearish sentiment. Expect a trending down day with lower lows.",
                "strategy": "Sell on rise. Trail stop-loss at opening price. Target: 1-1.5% below open.",
                "option_strategy": "Buy PE at opening bounce. Sell CE for premium collection.",
                "risk_level": "MODERATE",
            }
        elif news_sentiment == "BULLISH":
            return {
                "pattern": "GAP FILL UP",
                "description": "Gap down against bullish support. High probability of gap fill recovery during the day.",
                "strategy": "Buy on dips near support. Target: Previous day's close. Stop-loss: Day's low.",
                "option_strategy": "Buy CE or sell PE at lower strikes. Gap fill recovery expected.",
                "risk_level": "HIGH",
            }
        else:
            return {
                "pattern": "RANGE + DOWNSIDE BIAS",
                "description": "Gap down with mixed signals. Likely to consolidate with mild downside bias.",
                "strategy": "Sell near day's high, cover near day's low. Keep tight stop-losses.",
                "option_strategy": "Short strangle if premium is fat. Buy PE for directional play.",
                "risk_level": "MODERATE",
            }

    else:  # FLAT
        if event_risk == "HIGH":
            return {
                "pattern": "VOLATILE WHIPSAW",
                "description": "Flat opening with high event risk. Expect volatile whipsaw moves in both directions.",
                "strategy": "Wait for directional clarity. Avoid early trades. Trade after event outcome is clear.",
                "option_strategy": "Buy straddle/strangle for volatility play. Avoid directional bets.",
                "risk_level": "VERY HIGH",
            }
        elif abs(sentiment_score) > 10:
            direction = "UPWARD" if sentiment_score > 0 else "DOWNWARD"
            return {
                "pattern": f"BREAKOUT {direction}",
                "description": f"Flat opening but strong news sentiment suggests {direction.lower()} breakout during the day.",
                "strategy": f"Wait for breakout confirmation past opening range. Trade in direction of sentiment.",
                "option_strategy": f"Buy {'CE' if sentiment_score > 0 else 'PE'} after opening range breakout for trending move.",
                "risk_level": "MODERATE",
            }
        elif news_sentiment == "MIXED":
            return {
                "pattern": "RANGE-BOUND",
                "description": "Flat opening with mixed sentiment. Expect a range-bound day with no clear trend.",
                "strategy": "Sell at resistance, buy at support. Trade the range with tight risk management.",
                "option_strategy": "Sell straddle/strangle. Premium collection day. Time decay is your friend.",
                "risk_level": "LOW",
            }
        else:
            sentiment_dir = "bullish" if news_sentiment == "BULLISH" else "bearish"
            return {
                "pattern": f"SLOW {sentiment_dir.upper()} DRIFT",
                "description": f"Flat opening with {sentiment_dir} tilt. Expect a slow directional drift throughout the day.",
                "strategy": f"Trade with the sentiment. {'Buy dips' if sentiment_dir == 'bullish' else 'Sell rises'} with patience.",
                "option_strategy": f"Buy {'CE' if sentiment_dir == 'bullish' else 'PE'} ITM for directional play.",
                "risk_level": "LOW",
            }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Volatility Score
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

