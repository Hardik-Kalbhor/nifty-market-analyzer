"""
cognigraph/extraction.py — Causal triples extraction from episode resolutions.
"""

from typing import Any
from .constants import _safe_float


class ExtractionMixin:
    """Rule-based deterministic extraction of causal triples from reflection + market context."""

    def _extract_causal_triples(
        self,
        prediction: str,
        btst_bias: str,
        actual_gap_pct: float,
        outcome_clean: str,
        reflection: str,
        market_signals: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Rule-based deterministic extraction of causal triples from reflection + market context."""
        triples: list[dict[str, Any]] = []
        ref_lower = str(reflection or "").lower()
        pred_upper = str(prediction or "FLAT").upper()
        gap_val = _safe_float(actual_gap_pct, 0.0)

        if outcome_clean == "WRONG":
            if any(k in ref_lower for k in ("theta", "decay", "time value", "premium erosion")):
                triples.append({
                    "subject": "BTST_Trade",
                    "relation": "failed_due_to",
                    "target": "Overnight_Theta_Decay",
                    "polarity": "NEGATIVE",
                    "detail": "Overnight theta decay exceeded opening gap margin",
                })
            if any(k in ref_lower for k in ("diverge", "divergence", "heavyweight", "hdfc", "reliance")):
                triples.append({
                    "subject": "GIFT_Nifty_Gap",
                    "relation": "invalidated_by",
                    "target": "Heavyweight_Divergence",
                    "polarity": "NEGATIVE",
                    "detail": "Key index heavyweights diverged from global cues at open",
                })
            if any(k in ref_lower for k in ("iv crush", "volatility crush", "iv dropped")):
                triples.append({
                    "subject": "BTST_Trade",
                    "relation": "crushed_by",
                    "target": "Post_Open_IV_Crush",
                    "polarity": "NEGATIVE",
                    "detail": "Implied volatility collapse eroded option contract value",
                })
            if any(k in ref_lower for k in ("fii selling", "fii outflow", "institutional sell")):
                triples.append({
                    "subject": "Bullish_Momentum",
                    "relation": "overwhelmed_by",
                    "target": "FII_Net_Selling",
                    "polarity": "NEGATIVE",
                    "detail": "Heavy institutional selling neutralized overnight positive cues",
                })
            if not triples:
                triples.append({
                    "subject": "BTST_Trade",
                    "relation": "failed_under",
                    "target": "Adverse_Opening_Microstructure",
                    "polarity": "NEGATIVE",
                    "detail": f"Actual gap was {gap_val:+.2f}% vs predicted {pred_upper}",
                })
        elif outcome_clean == "CORRECT":
            if any(k in ref_lower for k in ("gift", "overnight cue", "global market", "us rally", "nasdaq")):
                triples.append({
                    "subject": "Global_Market_Momentum",
                    "relation": "sustained",
                    "target": "Gap_Followthrough",
                    "polarity": "POSITIVE",
                    "detail": "Overnight global cues directly carried through to Indian market open",
                })
            if any(k in ref_lower for k in ("fii", "institutional", "dii")):
                triples.append({
                    "subject": "Institutional_Flow_Alignment",
                    "relation": "boosted",
                    "target": "Directional_Gap_Conviction",
                    "polarity": "POSITIVE",
                    "detail": "FII/DII flow direction matched the overnight breakout",
                })
            if not triples:
                triples.append({
                    "subject": btst_bias or pred_upper,
                    "relation": "confirmed_by",
                    "target": "Opening_Momentum_Continuation",
                    "polarity": "POSITIVE",
                    "detail": f"Accurate {pred_upper} call ({gap_val:+.2f}% actual open)",
                })

        return triples
