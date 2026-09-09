"""
cognigraph/regime.py — Regime classification, similarity calculation, and exponential decay.
"""

import math
from typing import Any
from .constants import _safe_float, _days_between, _today_str


class RegimeMixin:
    @staticmethod
    def classify_regime(market_signals: dict[str, Any] | None, stage1_result: dict[str, Any] | None = None) -> str:
        """
        Deterministically bucket current market state into a canonical regime key:
          Format: {VIX_BUCKET}|{DTE_BUCKET}|{FII_BUCKET}|{GAP_INTENT}
        """
        if not isinstance(market_signals, dict):
            market_signals = {}
        if not isinstance(stage1_result, dict):
            stage1_result = {}

        # 1. India VIX
        vix = _safe_float(market_signals.get("india_vix"), default=13.5)

        if vix < 13.0:
            vix_b = "VIX_LOW"
        elif vix <= 16.0:
            vix_b = "VIX_MOD"
        else:
            vix_b = "VIX_HIGH"

        # 2. Days To Expiry (DTE)
        dte = None
        fo_ctx = str(stage1_result.get("fo_expiry_context", "")).lower()
        if "expiry today" in fo_ctx or "0 dte" in fo_ctx:
            dte = 0
        elif "expiry tomorrow" in fo_ctx or "1 dte" in fo_ctx or "next day expiry" in fo_ctx:
            dte = 1
        elif "dte" in market_signals:
            try:
                dte = int(market_signals["dte"])
            except (ValueError, TypeError):
                dte = None

        if dte is None:
            dte_b = "DTE_NEAR"
        elif dte == 0:
            dte_b = "DTE_EXPIRY"
        elif dte == 1:
            dte_b = "DTE_NEAR"
        else:
            dte_b = "DTE_MID"

        # 3. FII Flow
        fii = _safe_float(market_signals.get("fii_net") or market_signals.get("fii_cash"), default=0.0)

        if fii > 1500:
            fii_b = "FII_BULL"
        elif fii < -1500:
            fii_b = "FII_BEAR"
        else:
            fii_b = "FII_NEUT"

        # 4. Gap / Directional Intent
        gift_pct = _safe_float(market_signals.get("gift_nifty_change_pct"), default=0.0)

        pred = str(stage1_result.get("prediction", "")).upper()
        if gift_pct >= 0.40 or "STRONG GAP UP" in pred:
            gap_b = "GAP_STRONG_UP"
        elif gift_pct >= 0.15 or pred == "GAP UP":
            gap_b = "GAP_MILD_UP"
        elif gift_pct <= -0.15 or pred == "GAP DOWN":
            gap_b = "GAP_DOWN"
        else:
            gap_b = "GAP_FLAT"

        return f"{vix_b}|{dte_b}|{fii_b}|{gap_b}"

    # ─────────────────────────────────────────────────────────────────────────
    # Step 2: Causal Triples & Time-Decay Engine
    # ─────────────────────────────────────────────────────────────────────────

    def _compute_decay(self, last_seen_date: str, now_date: str | None = None) -> float:
        """
        Compute exponential half-life decay multiplier: 2^(-delta_days / half_life).
        """
        now = now_date or _today_str()
        days = _days_between(last_seen_date, now)
        if self.half_life_days <= 0:
            return 1.0
        return math.pow(2.0, -days / self.half_life_days)



    def _get_regime_similarity(self, reg1: str, reg2: str) -> float:
        """Compute structural overlap between two 4-part regime keys."""
        parts1 = reg1.split("|")
        parts2 = reg2.split("|")
        if len(parts1) != len(parts2):
            return 0.0
        matches = sum(1 for p1, p2 in zip(parts1, parts2) if p1 == p2)
        return matches / len(parts1)

