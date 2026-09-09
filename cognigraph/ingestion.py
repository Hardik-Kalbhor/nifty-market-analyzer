"""
cognigraph/ingestion.py — Causal triples ingestion, resolution updating, and axiom reinforcement.
"""

import logging
from typing import Any
from .constants import _safe_float, _today_str

logger = logging.getLogger("CogniGraph")


class IngestionMixin:
    """Causal triples ingestion, resolution updating, and axiom reinforcement."""

    def add_or_update_triple(
        self,
        subject: str,
        relation: str,
        target: str,
        polarity: str = "POSITIVE",
        regime: str = "",
        detail: str = "",
        evidence_date: str | None = None,
        weight_increment: float = 1.0,
    ) -> None:
        """Insert or update a causal relation edge with exponential decay."""
        with self._lock:
            edge_key = f"{subject}->{relation}->{target}"
            today = evidence_date or _today_str()

            if edge_key in self._triples:
                edge = self._triples[edge_key]
                decay = self._compute_decay(edge.get("last_seen", today), today)
                new_weight = round((edge.get("weight", 1.0) * decay) + weight_increment, 4)
                edge["weight"] = new_weight
                edge["count"] = edge.get("count", 1) + 1
                edge["last_seen"] = today
                if regime and regime not in edge.get("regimes", []):
                    edge.setdefault("regimes", []).append(regime)
                if detail and detail not in edge.get("details", []):
                    edge.setdefault("details", []).append(detail)
                    edge["details"] = edge["details"][-5:]
                if today not in edge.get("evidence_dates", []):
                    edge.setdefault("evidence_dates", []).append(today)
                    edge["evidence_dates"] = edge["evidence_dates"][-5:]
                edge["polarity"] = polarity.upper()
            else:
                self._triples[edge_key] = {
                    "subject": subject,
                    "relation": relation,
                    "target": target,
                    "polarity": polarity.upper(),
                    "weight": round(weight_increment, 4),
                    "count": 1,
                    "last_seen": today,
                    "regimes": [regime] if regime else [],
                    "details": [detail] if detail else [],
                    "evidence_dates": [today],
                }

    def ingest_resolution(
        self,
        trade_date: str,
        prediction: str | None = None,
        btst_bias: str | None = None,
        confidence: int | None = None,
        actual_gap_pct: float | None = None,
        outcome: str = "UNKNOWN",
        reflection: str | None = None,
        market_signals: dict[str, Any] | None = None,
        stage1_result: dict[str, Any] | None = None,
        trade_structure: str | None = None,
        explicit_triples: list[dict[str, Any]] | None = None,
        reasoning: str | None = None,
        signals: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Ingest a resolved prediction, update the episodic log, and extract causal triples."""
        with self._lock:
            signals_merged = dict(market_signals or {})
            if signals and isinstance(signals, dict):
                signals_merged.update(signals)

            regime = self.classify_regime(signals_merged, stage1_result)
            outcome_raw = str(outcome or "UNKNOWN").upper()
            if "CORRECT" in outcome_raw:
                outcome_clean = "CORRECT"
            elif "PARTIAL" in outcome_raw:
                outcome_clean = "PARTIAL"
            elif "WRONG" in outcome_raw:
                outcome_clean = "WRONG"
            else:
                outcome_clean = "UNKNOWN"

            pred_clean = str(prediction or "FLAT").upper().strip()
            bias_clean = str(btst_bias or "NO TRADE").upper().strip()
            conf_clean = int(confidence) if confidence is not None else 50
            gap_clean = round(_safe_float(actual_gap_pct, 0.0), 2)
            ref_clean = str(reflection or reasoning or "").strip()

            episode = {
                "date": trade_date,
                "regime": regime,
                "prediction": pred_clean,
                "btst_bias": bias_clean,
                "confidence": conf_clean,
                "actual_gap_pct": gap_clean,
                "outcome": outcome_clean,
                "reflection": ref_clean,
                "trade_structure": trade_structure or "UNKNOWN",
                "triples": [],
            }

            triples_to_record: list[dict[str, Any]] = []
            if explicit_triples:
                triples_to_record = explicit_triples
            else:
                triples_to_record = self._extract_causal_triples(
                    prediction=prediction,
                    btst_bias=btst_bias,
                    actual_gap_pct=actual_gap_pct,
                    outcome_clean=outcome_clean,
                    reflection=reflection or reasoning,
                    market_signals=signals_merged,
                )

            for t in triples_to_record:
                sub = t.get("subject", "BTST_Trade")
                rel = t.get("relation", "affected_by")
                obj = t.get("target") or t.get("object", "Market_Factor")
                pol = t.get("polarity", "NEGATIVE" if outcome_clean == "WRONG" else "POSITIVE")
                det = t.get("detail") or str(reflection or "")[:120]

                self.add_or_update_triple(
                    subject=sub,
                    relation=rel,
                    target=obj,
                    polarity=pol,
                    regime=regime,
                    detail=det,
                    evidence_date=trade_date,
                    weight_increment=1.0,
                )
                episode["triples"].append(f"{sub}->{rel}->{obj}")

            self._episodes[trade_date] = episode
            if regime not in self._regime_index:
                self._regime_index[regime] = []
            if trade_date not in self._regime_index[regime]:
                self._regime_index[regime].append(trade_date)

            self.save()
            return episode

    def reinforce_from_axiom(self, axiom: dict[str, Any]) -> str | None:
        """
        Mint or reinforce a causal triple directly from a synthesized Macro Axiom.
        """
        if not isinstance(axiom, dict):
            return None
        sub = axiom.get("subject")
        rel = axiom.get("relation")
        tar = axiom.get("target")
        if not sub or not rel or not tar:
            return None
        pol = axiom.get("polarity", "NEGATIVE").upper()
        reg = axiom.get("regime", "")
        stmt = axiom.get("statement", "")
        try:
            conf = float(axiom.get("confidence", 0.7))
        except (ValueError, TypeError):
            conf = 0.7
        weight_boost = round(conf * 2.0, 2)
        self.add_or_update_triple(
            subject=sub,
            relation=rel,
            target=tar,
            polarity=pol,
            regime=reg,
            detail=stmt[:150] if stmt else "",
            evidence_date=_today_str(),
            weight_increment=weight_boost,
        )
        self.save()
        return f"{sub}->{rel}->{tar}"
