"""
subagents/matcher.py — Real-time market catalyst trigger matching for dynamic subagents.
"""

import re
import logging
from typing import Any
from .constants import SPECIALIST_SPECS

logger = logging.getLogger("DynamicSubagents")

def _clean_numeric(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        s = str(val).strip().replace(",", "")
        m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
        return float(m.group(0)) if m else default
    except Exception:
        return default


def match_dynamic_subagents(
    market_signals: dict[str, Any] | None = None,
    news_items: list[dict[str, Any]] | None = None,
    stage1_result: dict[str, Any] | None = None,
    heavyweights: dict[str, Any] | None = None,
    max_specialists: int = 2,
) -> list[str]:
    """
    Evaluate market signals, breaking news, and heavyweight movement to
    determine which specialist subagents should be spawned dynamically.
    Returns list of specialist names (max_specialists).
    """
    signals = market_signals if isinstance(market_signals, dict) else {}
    news = news_items if isinstance(news_items, list) else []
    stage1 = stage1_result if isinstance(stage1_result, dict) else {}
    hw = heavyweights if isinstance(heavyweights, dict) else {}

    matched: list[tuple[int, str]] = []  # (priority, name)

    # Compile all news text
    news_texts = []
    for it in news:
        if isinstance(it, dict):
            title = it.get("title") or it.get("headline") or ""
            news_texts.append(str(title).lower())
    full_news_corpus = " ".join(news_texts)

    # 1. RBI Policy Quant
    rbi_kws = SPECIALIST_SPECS["RBI_Policy_Quant"]["triggers"]["news_keywords"]
    if any(kw in full_news_corpus for kw in rbi_kws):
        matched.append((10, "RBI_Policy_Quant"))

    # 2. Geopolitical Crude Analyst
    crude_kws = SPECIALIST_SPECS["Geopolitical_Crude_Analyst"]["triggers"]["news_keywords"]
    if any(kw in full_news_corpus for kw in crude_kws):
        matched.append((8, "Geopolitical_Crude_Analyst"))

    # 3. 0-DTE Options Greeks Quant
    dte_val = signals.get("dte")
    if dte_val is not None:
        try:
            if int(dte_val) <= 1:
                matched.append((9, "Options_Greeks_ZeroDTE_Quant"))
        except (ValueError, TypeError):
            pass
    fo_ctx = str(stage1.get("fo_expiry_context", "")).lower()
    if not any(m[1] == "Options_Greeks_ZeroDTE_Quant" for m in matched):
        if any(c in fo_ctx for c in ["expiry today", "expiry tomorrow", "0 dte", "1 dte"]):
            matched.append((9, "Options_Greeks_ZeroDTE_Quant"))

    # 4. Heavyweight Earnings Specialist
    earn_kws = SPECIALIST_SPECS["Heavyweight_Earnings_Specialist"]["triggers"]["news_keywords"]
    has_earnings_news = any(kw in full_news_corpus for kw in earn_kws)
    has_hw_move = False
    for stock_data in hw.values():
        if isinstance(stock_data, dict):
            chg = abs(_clean_numeric(stock_data.get("change_pct"), 0.0))
            if chg >= 0.8:
                has_hw_move = True
                break
    if has_earnings_news or has_hw_move:
        matched.append((7, "Heavyweight_Earnings_Specialist"))

    # 5. FII Order Flow Tracer
    fii_net = abs(_clean_numeric(signals.get("fii_net") or signals.get("fii_cash"), 0.0))
    if fii_net >= 1800.0:
        matched.append((6, "FII_OrderFlow_Tracer"))

    # Sort by priority descending and cap at max_specialists
    matched.sort(key=lambda x: x[0], reverse=True)
    return [name for _, name in matched[:max_specialists]]


