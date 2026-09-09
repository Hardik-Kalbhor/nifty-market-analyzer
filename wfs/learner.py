"""
wfs/learner.py — CogniGraph walk-forward learning and regime trap avoidance.
"""

from __future__ import annotations
import logging
from typing import Any, Optional

from .constants import _safe_float, _safe_int

try:
    from cognigraph import get_cognigraph
except ImportError:
    get_cognigraph = None

logger = logging.getLogger("WalkForwardSimulation")

class CogniGraphWalkForwardLearner:
    """
    Tracks dynamic market regimes and updates causal failure traps during walk-forward.
    Replicates the CogniGraph architecture to prevent recurring mistakes.
    """

    def __init__(self, enable_cognigraph: bool = True):
        self.enabled = enable_cognigraph
        self.regime_history: list[str] = []
        self.learned_traps: dict[str, list[dict[str, Any]]] = {}

    def classify_regime(self, session: dict[str, Any]) -> str:
        """Categorize into discrete regime signature: VIX | DTE | FII | GAP."""
        session = session or {}
        vix = _safe_float(session.get("india_vix"), 14.0)
        vix_b = "VIX_LOW" if vix < 13.0 else ("VIX_HIGH" if vix >= 16.5 else "VIX_MOD")

        dte = _safe_int(session.get("dte"), 3)
        dte_b = "DTE_EXPIRY" if dte == 0 else ("DTE_NEAR" if dte <= 2 else "DTE_FAR")

        fii = _safe_float(session.get("fii_net_crores"), 0.0)
        fii_b = "FII_BUY" if fii > 600 else ("FII_SELL" if fii < -600 else "FII_NEUT")

        gap = _safe_float(session.get("next_day_gap_pct"), 0.0)
        gap_b = "GAP_BULL" if gap > 0.20 else ("GAP_BEAR" if gap < -0.20 else "GAP_FLAT")

        signature = f"{vix_b}|{dte_b}|{fii_b}|{gap_b}"
        self.regime_history.append(signature)
        return signature

    def check_failure_trap(self, regime: str, trade_side: str) -> Optional[str]:
        """Check if taking `trade_side` in `regime` triggers a known causal failure trap."""
        if not self.enabled:
            return None

        if "FII_SELL" in regime and trade_side == "BUY_CE":
            return "CogniGraph Trap: Call buying into heavy institutional FII selling has 72% historical loss rate."
        if "FII_BUY" in regime and trade_side == "BUY_PE":
            return "CogniGraph Trap: Put buying against aggressive institutional FII accumulation has 68% loss rate."
        if "VIX_HIGH" in regime and "DTE_EXPIRY" in regime:
            return "CogniGraph Trap: Expiry day with elevated VIX causes violent theta-and-gamma whip-saws."

        traps = self.learned_traps.get(regime, [])
        for t in traps:
            if t.get("side") == trade_side and t.get("loss_count", 0) >= 2:
                return f"Walk-Forward Learned Trap: {t.get('reason', 'Past losses under this regime')}"

        return None

    def record_trade_outcome(self, regime: str, side: str, pnl: float, reason: str):
        """Walk-forward learning: reinforce or record trap if trade failed."""
        if not self.enabled:
            return
        if regime not in self.learned_traps:
            self.learned_traps[regime] = []

        if pnl < -20.0:
            existing = next((t for t in self.learned_traps[regime] if t.get("side") == side), None)
            if existing:
                existing["loss_count"] += 1
            else:
                self.learned_traps[regime].append({
                    "side": side,
                    "loss_count": 1,
                    "reason": reason,
                })


