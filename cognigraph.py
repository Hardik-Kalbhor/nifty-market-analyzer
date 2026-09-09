"""
cognigraph.py — Lightweight Hierarchical Cognitive Graph Memory Layer for NIFTY Agents.

Implements the CogniGraph architecture (adapted from LiCoMemory / ACL 2026):
  1. Macro / Regime Layer: Discrete market state bucketing (VIX, DTE, FII flow, gap intent).
  2. Relational / Causal Triples: Directed, weighted causal edges with exponential half-life decay.
  3. Episodic Ground-Truth: Date-anchored prediction records, actual outcomes, and post-mortems.

Supports persona-conditioned memory retrieval:
  - CONSERVATIVE: Failure modes, theta drag, IV crush, and heavyweight divergence traps.
  - AGGRESSIVE: Momentum follow-through, breakout continuation, and high-conviction catalysts.
  - NEUTRAL: Capital preservation and risk-adjusted trade structure performance.
  - JUDGE: Regime win rates, historical calibration, and opposing argument validation.

Pure Python, zero external database dependencies, thread-safe, persisted to history/cognigraph.json.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default half-life for memory decay (weights halve every 30 days)
DEFAULT_HALF_LIFE_DAYS = 30.0

# Canonical schema version
COGNIGRAPH_SCHEMA_VERSION = 1


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Parse a float safely, stripping extraneous text (%, Cr, commas, etc.)."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        cleaned = re.sub(r"[^\d.-]", "", str(val).strip())
        return float(cleaned) if cleaned else default
    except Exception:
        return default


def _days_between(d1_val: Any, d2_val: Any) -> float:
    """Compute days between two date strings safely."""
    try:
        if not d1_val or not d2_val:
            return 0.0
        d1_str = str(d1_val)[:10]
        d2_str = str(d2_val)[:10]
        dt1 = datetime.strptime(d1_str, "%Y-%m-%d")
        dt2 = datetime.strptime(d2_str, "%Y-%m-%d")
        return abs((dt2 - dt1).total_seconds()) / 86400.0
    except Exception:
        return 0.0


def _today_str() -> str:
    """Return today's date string YYYY-MM-DD."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class CogniGraph:
    """
    Hierarchical Cognitive Knowledge Graph memory layer for autonomous trading agents.
    """

    def __init__(self, history_dir: str | None = None, half_life_days: float = DEFAULT_HALF_LIFE_DAYS):
        self.half_life_days = half_life_days
        self._lock = threading.RLock()

        if history_dir is None:
            base = os.getenv("HISTORY_DIR", os.path.join(os.path.dirname(__file__), "history"))
        else:
            base = history_dir

        try:
            os.makedirs(base, exist_ok=True)
            self._file_path = Path(base) / "cognigraph.json"
        except (OSError, PermissionError):
            fallback = "/tmp/history"
            os.makedirs(fallback, exist_ok=True)
            self._file_path = Path(fallback) / "cognigraph.json"

        # In-memory graph representation
        self._triples: dict[str, dict[str, Any]] = {}  # edge_key -> edge data
        self._episodes: dict[str, dict[str, Any]] = {} # trade_date -> episode data
        self._regime_index: dict[str, list[str]] = {}  # regime -> list of trade_dates

        self._load_or_bootstrap()

    # ─────────────────────────────────────────────────────────────────────────
    # Step 1: Macro & Regime Scaffolding
    # ─────────────────────────────────────────────────────────────────────────

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

    def add_or_update_triple(
        self,
        subject: str,
        relation: str,
        target: str,
        polarity: str,
        regime: str,
        detail: str = "",
        evidence_date: str | None = None,
        weight_increment: float = 1.0,
    ) -> None:
        """
        Insert or update a causal relation edge with exponential decay.
        """
        with self._lock:
            edge_key = f"{subject}->{relation}->{target}"
            today = evidence_date or _today_str()

            if edge_key in self._triples:
                edge = self._triples[edge_key]
                decay = self._compute_decay(edge["last_seen"], today)
                new_weight = (edge["weight"] * decay) + weight_increment
                edge["weight"] = round(new_weight, 4)
                edge["count"] += 1
                edge["last_seen"] = today
                if regime and regime not in edge["regimes"]:
                    edge["regimes"].append(regime)
                if detail and detail not in edge["details"]:
                    edge["details"].append(detail)
                    edge["details"] = edge["details"][-5:]  # keep last 5 details
                if evidence_date and evidence_date not in edge["evidence_dates"]:
                    edge["evidence_dates"].append(evidence_date)
                    edge["evidence_dates"] = edge["evidence_dates"][-5:]
            else:
                self._triples[edge_key] = {
                    "subject": subject,
                    "relation": relation,
                    "target": target,
                    "polarity": polarity.upper(),  # "POSITIVE" or "NEGATIVE"
                    "weight": round(weight_increment, 4),
                    "count": 1,
                    "last_seen": today,
                    "regimes": [regime] if regime else [],
                    "details": [detail] if detail else [],
                    "evidence_dates": [evidence_date] if evidence_date else [],
                }

    # ─────────────────────────────────────────────────────────────────────────
    # Step 3: Ingestion of Post-Mortem Resolutions
    # ─────────────────────────────────────────────────────────────────────────

    def ingest_resolution(
        self,
        trade_date: str,
        prediction: str,
        btst_bias: str,
        confidence: int,
        actual_gap_pct: float,
        outcome: str,
        reflection: str,
        market_signals: dict[str, Any] | None = None,
        stage1_result: dict[str, Any] | None = None,
        trade_structure: str | None = None,
        explicit_triples: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Ingest a resolved prediction, update the episodic log, and extract causal triples.
        """
        with self._lock:
            regime = self.classify_regime(market_signals, stage1_result)

            # Standardize outcome
            outcome_clean = "CORRECT" if "CORRECT" in outcome.upper() else (
                "PARTIAL" if "PARTIAL" in outcome.upper() else "WRONG"
            )

            # 1. Record Episode
            episode = {
                "date": str(trade_date),
                "regime": regime,
                "prediction": str(prediction or "FLAT").upper(),
                "btst_bias": str(btst_bias or "NO TRADE").upper(),
                "confidence": int(confidence or 50),
                "actual_gap_pct": round(_safe_float(actual_gap_pct, 0.0), 2),
                "outcome": outcome_clean,
                "reflection": str(reflection or "").strip(),
                "trade_structure": str(trade_structure or "UNKNOWN"),
                "triples": [],
            }

            # 2. Extract or use explicit triples
            triples_to_record: list[dict[str, Any]] = []
            if explicit_triples:
                triples_to_record = explicit_triples
            else:
                triples_to_record = self._extract_causal_triples(
                    prediction=prediction,
                    btst_bias=btst_bias,
                    actual_gap_pct=actual_gap_pct,
                    outcome_clean=outcome_clean,
                    reflection=reflection,
                    market_signals=market_signals or {},
                )

            # 3. Insert triples into graph
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

            # Store in indexes
            self._episodes[trade_date] = episode
            if regime not in self._regime_index:
                self._regime_index[regime] = []
            if trade_date not in self._regime_index[regime]:
                self._regime_index[regime].append(trade_date)

            # Persist to disk
            self.save()
            return episode

    def _extract_causal_triples(
        self,
        prediction: str,
        btst_bias: str,
        actual_gap_pct: float,
        outcome_clean: str,
        reflection: str,
        market_signals: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Rule-based deterministic extraction of causal triples from reflection + market context.
        """
        triples: list[dict[str, Any]] = []
        ref_lower = str(reflection or "").lower()
        pred_upper = str(prediction or "FLAT").upper()
        gap_val = _safe_float(actual_gap_pct, 0.0)

        if outcome_clean == "WRONG":
            # Identify failure modes
            if any(k in ref_lower for k in ["theta", "decay", "time value", "premium erosion"]):
                triples.append({
                    "subject": btst_bias or pred_upper,
                    "relation": "failed_due_to",
                    "target": "Overnight_Theta_Decay",
                    "polarity": "NEGATIVE",
                    "detail": "Overnight theta decay exceeded opening gap margin",
                })

            if any(k in ref_lower for k in ["diverge", "divergence", "heavyweight", "hdfc", "reliance"]):
                triples.append({
                    "subject": "GIFT_Nifty_Gap",
                    "relation": "invalidated_by",
                    "target": "Heavyweight_Divergence",
                    "polarity": "NEGATIVE",
                    "detail": "Key index heavyweights diverged from global cues at open",
                })

            if any(k in ref_lower for k in ["iv crush", "volatility crush", "iv dropped"]):
                triples.append({
                    "subject": btst_bias or pred_upper,
                    "relation": "crushed_by",
                    "target": "Post_Open_IV_Crush",
                    "polarity": "NEGATIVE",
                    "detail": "Implied volatility collapse eroded option contract value",
                })

            if any(k in ref_lower for k in ["fii selling", "fii outflow", "institutional sell"]):
                triples.append({
                    "subject": "Bullish_Momentum",
                    "relation": "overwhelmed_by",
                    "target": "FII_Net_Selling",
                    "polarity": "NEGATIVE",
                    "detail": "Heavy institutional selling neutralized overnight positive cues",
                })

            if not triples:
                # Default generic failure triple
                triples.append({
                    "subject": btst_bias or pred_upper,
                    "relation": "failed_under",
                    "target": "Adverse_Opening_Microstructure",
                    "polarity": "NEGATIVE",
                    "detail": f"Actual gap was {gap_val:+.2f}% vs predicted {pred_upper}",
                })

        elif outcome_clean == "CORRECT":
            # Identify success catalysts
            if any(k in ref_lower for k in ["gift", "overnight cue", "global market", "us rally", "nasdaq"]):
                triples.append({
                    "subject": "Global_Market_Momentum",
                    "relation": "sustained",
                    "target": "Gap_Followthrough",
                    "polarity": "POSITIVE",
                    "detail": "Overnight global cues directly carried through to Indian market open",
                })

            if any(k in ref_lower for k in ["fii", "institutional", "dii"]):
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

    # ─────────────────────────────────────────────────────────────────────────
    # Step 4: Persona-Conditioned Retrieval Engine
    # ─────────────────────────────────────────────────────────────────────────

    def get_agent_memory(
        self,
        persona: str,
        current_signals: dict[str, Any] | None,
        stage1_result: dict[str, Any] | None = None,
        max_items: int = 3,
    ) -> str:
        """
        Query CogniGraph conditioned on the agent's persona.
        Returns a formatted markdown string ready for injection into the agent's prompt.
        """
        with self._lock:
            current_regime = self.classify_regime(current_signals, stage1_result)
            persona_upper = persona.upper()

            if persona_upper == "CONSERVATIVE":
                return self._retrieve_conservative(current_regime, max_items)
            elif persona_upper == "AGGRESSIVE":
                return self._retrieve_aggressive(current_regime, max_items)
            elif persona_upper == "NEUTRAL":
                return self._retrieve_neutral(current_regime, max_items)
            elif persona_upper in ("JUDGE", "SYNTHESIS"):
                return self.get_judge_calibration(current_signals, stage1_result)
            elif persona_upper in ("MOMENTUM_SCALPER", "INTRADAY_MOMENTUM"):
                return self._retrieve_intraday_momentum(current_regime, max_items)
            elif persona_upper in ("WALL_DEFENDER", "INTRADAY_DEFENDER"):
                return self._retrieve_intraday_defender(current_regime, max_items)
            elif persona_upper in ("TACTICAL_SCALPER", "INTRADAY_TACTICAL"):
                return self._retrieve_neutral(current_regime, max_items)
            else:
                return self._retrieve_general(current_regime, max_items)

    def _get_regime_similarity(self, reg1: str, reg2: str) -> float:
        """Compute structural overlap between two 4-part regime keys."""
        parts1 = reg1.split("|")
        parts2 = reg2.split("|")
        if len(parts1) != len(parts2):
            return 0.0
        matches = sum(1 for p1, p2 in zip(parts1, parts2) if p1 == p2)
        return matches / len(parts1)

    def _retrieve_conservative(self, current_regime: str, max_items: int) -> str:
        """Retrieve failure modes, traps, and theta drag cases."""
        now = _today_str()
        candidate_edges: list[tuple[float, dict[str, Any]]] = []

        for edge in self._triples.values():
            if edge["polarity"] != "NEGATIVE":
                continue

            decay = self._compute_decay(edge["last_seen"], now)
            decayed_weight = edge["weight"] * decay

            # Bonus for regime overlap
            regime_bonus = 1.0
            for r in edge["regimes"]:
                sim = self._get_regime_similarity(current_regime, r)
                if sim > 0.5:
                    regime_bonus = max(regime_bonus, 1.0 + sim)

            score = decayed_weight * regime_bonus
            candidate_edges.append((score, edge))

        candidate_edges.sort(key=lambda x: x[0], reverse=True)
        top = [e for _, e in candidate_edges[:max_items]]

        if not top:
            return ""

        lines = [
            "🛡️ COGNIGRAPH CAUSAL RISK PRECEDENTS (Empirical Failure Modes for Current Regime):",
            f"   [Active Regime: {current_regime}]",
        ]
        for e in top:
            sub = e["subject"]
            rel = e["relation"].replace("_", " ")
            tar = e["target"].replace("_", " ")
            detail = f" — {e['details'][-1]}" if e.get("details") else ""
            ev_date = f" ({e['evidence_dates'][-1]})" if e.get("evidence_dates") else ""
            lines.append(f"   • Antipattern: {sub} {rel} {tar}{ev_date}{detail} (seen {e['count']}x)")

        lines.append("   → Instruction: Explicitly challenge optimistic gap assumptions using these failure precedents.")
        return "\n".join(lines)

    def _retrieve_aggressive(self, current_regime: str, max_items: int) -> str:
        """Retrieve momentum continuations and successful breakout drivers."""
        now = _today_str()
        candidate_edges: list[tuple[float, dict[str, Any]]] = []

        for edge in self._triples.values():
            if edge["polarity"] != "POSITIVE":
                continue

            decay = self._compute_decay(edge["last_seen"], now)
            decayed_weight = edge["weight"] * decay

            regime_bonus = 1.0
            for r in edge["regimes"]:
                sim = self._get_regime_similarity(current_regime, r)
                if sim > 0.5:
                    regime_bonus = max(regime_bonus, 1.0 + sim)

            score = decayed_weight * regime_bonus
            candidate_edges.append((score, edge))

        candidate_edges.sort(key=lambda x: x[0], reverse=True)
        top = [e for _, e in candidate_edges[:max_items]]

        if not top:
            return ""

        lines = [
            "⚡ COGNIGRAPH MOMENTUM PRECEDENTS (Empirical Continuation Drivers for Current Regime):",
            f"   [Active Regime: {current_regime}]",
        ]
        for e in top:
            sub = e["subject"]
            rel = e["relation"].replace("_", " ")
            tar = e["target"].replace("_", " ")
            detail = f" — {e['details'][-1]}" if e.get("details") else ""
            ev_date = f" ({e['evidence_dates'][-1]})" if e.get("evidence_dates") else ""
            lines.append(f"   • Catalyst: {sub} {rel} {tar}{ev_date}{detail} (confirmed {e['count']}x)")

        lines.append("   → Instruction: Cite these proven continuation catalysts to support capturing the overnight gap.")
        return "\n".join(lines)

    def _retrieve_neutral(self, current_regime: str, max_items: int) -> str:
        """Retrieve structure performance and risk-reward optimization."""
        matching_episodes = [
            ep for ep in self._episodes.values()
            if self._get_regime_similarity(current_regime, ep.get("regime", "")) >= 0.5
        ]

        if not matching_episodes:
            matching_episodes = list(self._episodes.values())[-5:]

        struct_counts: dict[str, dict[str, int]] = {}
        for ep in matching_episodes:
            st = ep.get("trade_structure") or "HALF_QUANTITY"
            out = ep.get("outcome", "PARTIAL")
            if st not in struct_counts:
                struct_counts[st] = {"CORRECT": 0, "PARTIAL": 0, "WRONG": 0}
            struct_counts[st][out] = struct_counts[st].get(out, 0) + 1

        lines = [
            "⚖️ COGNIGRAPH STRUCTURAL CONTEXT (Risk-Adjusted Performance for Current Regime):",
            f"   [Active Regime: {current_regime} | Evaluated Sessions: {len(matching_episodes)}]",
        ]
        for st, counts in struct_counts.items():
            if st == "UNKNOWN":
                continue
            total = sum(counts.values())
            success_pct = round(((counts.get("CORRECT", 0) + 0.5 * counts.get("PARTIAL", 0)) / total) * 100) if total else 0
            lines.append(f"   • Structure '{st}': {success_pct}% capital preservation / win rate across {total} trades")

        if not any(st != "UNKNOWN" for st in struct_counts):
            lines.append("   • Baseline Structural Advice: In unconfirmed or high-risk regimes, favor 'HEDGED_SPREAD' or 'HALF_QUANTITY' to limit overnight gap risk.")

        lines.append("   → Instruction: Balance risk vs reward; choose structure that limits downside if gap fails.")
        return "\n".join(lines)

    def _retrieve_intraday_momentum(self, current_regime: str, max_items: int) -> str:
        """Retrieve momentum scalping precedents."""
        return self._retrieve_aggressive(current_regime, max_items).replace("BTST", "Intraday")

    def _retrieve_intraday_defender(self, current_regime: str, max_items: int) -> str:
        """Retrieve wall defense & mean-reversion precedents."""
        return self._retrieve_conservative(current_regime, max_items).replace("BTST", "Intraday")

    def _retrieve_general(self, current_regime: str, max_items: int) -> str:
        return self._retrieve_neutral(current_regime, max_items)

    def get_judge_calibration(
        self,
        current_signals: dict[str, Any] | None,
        stage1_result: dict[str, Any] | None = None,
    ) -> str:
        """
        Generate statistical calibration and failure probability context for the Judge.
        """
        with self._lock:
            regime = self.classify_regime(current_signals, stage1_result)
            stage1_bias = (stage1_result or {}).get("btst_bias", "BUY CE").upper()

            # Find episodes matching or close to current regime
            matched = []
            for ep in self._episodes.values():
                sim = self._get_regime_similarity(regime, ep.get("regime", ""))
                if sim >= 0.5:
                    matched.append((sim, ep))

            matched.sort(key=lambda x: x[0], reverse=True)
            relevant_episodes = [ep for _, ep in matched[:15]]

            total = len(relevant_episodes)
            if total == 0:
                return (
                    f"COGNIGRAPH REGIME CALIBRATION:\n"
                    f"  Current Regime Signature: {regime}\n"
                    f"  Historical Baseline: Sparse regime samples. Exercise standard risk moderation.\n"
                )

            correct_cnt = sum(1 for ep in relevant_episodes if ep.get("outcome") == "CORRECT")
            partial_cnt = sum(1 for ep in relevant_episodes if ep.get("outcome") == "PARTIAL")
            wrong_cnt = sum(1 for ep in relevant_episodes if ep.get("outcome") == "WRONG")

            win_rate = round(((correct_cnt + 0.5 * partial_cnt) / total) * 100, 1)

            # Find dominant failure trap in this regime
            traps = []
            for edge in self._triples.values():
                if edge["polarity"] == "NEGATIVE" and any(self._get_regime_similarity(regime, r) >= 0.5 for r in edge["regimes"]):
                    traps.append(edge)
            traps.sort(key=lambda x: x["count"], reverse=True)
            top_trap = f"{traps[0]['subject']} {traps[0]['relation']} {traps[0]['target']}" if traps else "None recorded"

            lines = [
                "🏛️ COGNIGRAPH REGIME CALIBRATION FOR JUDGE:",
                f"  Current Regime: {regime}",
                f"  Matching Historical Sessions: {total} (Win Rate: {win_rate}%)",
                f"  Historical Breakdown: {correct_cnt} Correct, {partial_cnt} Partial, {wrong_cnt} Failed",
                f"  Primary Failure Trap in this Regime: '{top_trap}'",
                f"  Proposed Direction: {stage1_bias}",
            ]

            if win_rate < 50.0 and stage1_bias != "NO TRADE":
                lines.append(
                    f"  ⚠️ Warning: Win rate in this regime is sub-50%. Favor 'HEDGED_SPREAD' or 'HALF_QUANTITY' over 'FULL_BTST'."
                )
            elif win_rate >= 75.0:
                lines.append(
                    f"  ✅ Strong Alignment: Regime exhibits high consistency. If debate consensus holds, 'FULL_BTST' is justified."
                )

            return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────────────────
    # Step 5: Persistence, Loading & Seed Priors
    # ─────────────────────────────────────────────────────────────────────────

    def save(self) -> None:
        """Persist graph atomically to JSON."""
        with self._lock:
            data = {
                "schema_version": COGNIGRAPH_SCHEMA_VERSION,
                "last_updated": _today_str(),
                "half_life_days": self.half_life_days,
                "triples": self._triples,
                "episodes": self._episodes,
                "regime_index": self._regime_index,
            }
            tmp_path = str(self._file_path) + ".tmp"
            try:
                os.makedirs(self._file_path.parent, exist_ok=True)
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, default=str)
                os.replace(tmp_path, self._file_path)
            except Exception as e:
                logger.error(f"CogniGraph: Failed to save {self._file_path}: {e}")
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass

    def _load_or_bootstrap(self) -> None:
        """Load from disk or seed with domain priors if file does not exist."""
        with self._lock:
            if self._file_path.exists():
                try:
                    with open(self._file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._triples = data.get("triples") if isinstance(data.get("triples"), dict) else {}
                    self._episodes = data.get("episodes") if isinstance(data.get("episodes"), dict) else {}
                    self._regime_index = data.get("regime_index") if isinstance(data.get("regime_index"), dict) else {}
                    logger.debug(
                        f"CogniGraph loaded: {len(self._triples)} triples, {len(self._episodes)} episodes."
                    )
                    # Merge any missing seed priors
                    if "Retail_Euphoria_Trap->invalidated_by->Institutional_FII_Dumping" not in self._triples:
                        self._bootstrap_seed_priors()
                        self.save()
                    return
                except Exception as e:
                    logger.warning(f"CogniGraph: Error loading {self._file_path}, bootstrapping: {e}")

            # Bootstrap seed domain priors
            self._bootstrap_seed_priors()
            self.save()

    def _bootstrap_seed_priors(self) -> None:
        """
        Prime the graph with empirical market microstructure and options failure/success priors
        so the system provides intelligent risk debate from Day 1.
        """
        today = _today_str()

        negative_priors = [
            ("BUY_CE", "failed_due_to", "Overnight_Theta_Decay", "VIX_MOD|DTE_NEAR|FII_BEAR|GAP_MILD_UP",
             "Theta decay on 1 DTE options frequently overwhelms gaps below +0.30%"),
            ("GIFT_Nifty_Gap_Up", "invalidated_by", "Heavyweight_Divergence", "VIX_MOD|DTE_NEAR|FII_NEUT|GAP_MILD_UP",
             "HDFC Bank and Reliance selling off at open rapidly pulls NIFTY gap back to flat"),
            ("BUY_CE", "crushed_by", "Post_Open_IV_Crush", "VIX_HIGH|DTE_NEAR|FII_NEUT|GAP_STRONG_UP",
             "Post-event volatility collapse results in premium loss despite gap up open"),
            ("BUY_PE", "failed_due_to", "Short_Covering_Bounce", "VIX_MOD|DTE_EXPIRY|FII_BULL|GAP_DOWN",
             "Overnight short positions squeezed by domestic institutional dip buyers"),
            ("BUY_CE", "pinned_by", "Max_Pain_Resistance", "VIX_LOW|DTE_EXPIRY|FII_NEUT|GAP_MILD_UP",
             "NIFTY spot pinned to heavy Call writing strike on weekly expiry"),
            ("Retail_Euphoria_Trap", "invalidated_by", "Institutional_FII_Dumping", "VIX_MOD|DTE_NEAR|FII_BEAR|GAP_MILD_UP",
             "Retail hyper-bullish sentiment on Reddit/Telegram faded aggressively by institutional sell-programs at open"),
            ("Retail_Panic_Bottom", "countered_by", "DII_Accumulation", "VIX_HIGH|DTE_NEAR|FII_NEUT|GAP_DOWN",
             "Extreme retail panic/FUD on social forums signals imminent capitulation bounce supported by domestic buying"),
        ]

        positive_priors = [
            ("Global_Tech_Rally", "sustained", "Gap_Continuation", "VIX_LOW|DTE_MID|FII_BULL|GAP_STRONG_UP",
             "Nasdaq and Asian tech rally generates multi-hour opening trend continuation"),
            ("FII_Heavy_Buying", "reinforced", "Bullish_Opening_Drive", "VIX_MOD|DTE_NEAR|FII_BULL|GAP_STRONG_UP",
             "FII cash buying above +2,000 Cr creates sustained institutional gap holding"),
            ("High_PCR_Oversold", "supported", "Contrarian_Gap_Up", "VIX_HIGH|DTE_NEAR|FII_NEUT|GAP_MILD_UP",
             "PCR < 0.75 triggers sharp short-covering gap up on mild global cues"),
        ]

        for sub, rel, tar, reg, det in negative_priors:
            self.add_or_update_triple(
                subject=sub, relation=rel, target=tar, polarity="NEGATIVE",
                regime=reg, detail=det, evidence_date=today, weight_increment=2.0
            )

        for sub, rel, tar, reg, det in positive_priors:
            self.add_or_update_triple(
                subject=sub, relation=rel, target=tar, polarity="POSITIVE",
                regime=reg, detail=det, evidence_date=today, weight_increment=2.0
            )

    def decay_and_prune(self, threshold: float = 0.2, max_idle_days: float = 60.0) -> dict[str, int]:
        """
        Consolidation routine: Apply time-decay to all causal edges and prune
        edges whose decayed weight drops below threshold AND have not been seen
        in > max_idle_days. Returns {'decayed': count, 'pruned': count}.
        """
        with self._lock:
            now = _today_str()
            pruned_keys = []
            decayed_count = 0

            for edge_key, edge in list(self._triples.items()):
                if not isinstance(edge, dict):
                    continue
                last_seen = edge.get("last_seen") or now
                decay = self._compute_decay(last_seen, now)
                w = _safe_float(edge.get("weight"), default=1.0)
                new_weight = round(w * decay, 4)
                edge["weight"] = new_weight
                decayed_count += 1

                # Check pruning eligibility: must be low weight AND stale
                idle_days = _days_between(last_seen, now)
                if new_weight < threshold and idle_days > max_idle_days:
                    pruned_keys.append(edge_key)

            for key in pruned_keys:
                del self._triples[key]

            if decayed_count > 0:
                self.save()

            return {"decayed": decayed_count, "pruned": len(pruned_keys)}

    def reinforce_from_axiom(self, axiom: dict[str, Any]) -> str | None:
        """
        Mint or reinforce a causal triple directly from a synthesized Macro Axiom.
        axiom dict expects:
          - subject: str
          - relation: str
          - target: str
          - polarity: 'POSITIVE' | 'NEGATIVE'
          - regime: str
          - statement: str
          - confidence: float (0.0 to 1.0)
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

    # ─────────────────────────────────────────────────────────────────────────
    # Stats & API Surface
    # ─────────────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Return graph metrics for the /api/memory dashboard endpoint."""
        with self._lock:
            now = _today_str()
            total_triples = len(self._triples)
            active_triples = 0
            neg_triples = 0
            pos_triples = 0

            for edge in self._triples.values():
                decay = self._compute_decay(edge["last_seen"], now)
                if (edge["weight"] * decay) >= 0.2:
                    active_triples += 1
                if edge["polarity"] == "NEGATIVE":
                    neg_triples += 1
                else:
                    pos_triples += 1

            total_episodes = len(self._episodes)
            correct = sum(1 for ep in self._episodes.values() if ep.get("outcome") == "CORRECT")
            partial = sum(1 for ep in self._episodes.values() if ep.get("outcome") == "PARTIAL")
            wrong = sum(1 for ep in self._episodes.values() if ep.get("outcome") == "WRONG")

            accuracy_pct = round(((correct + 0.5 * partial) / total_episodes) * 100, 1) if total_episodes else 0.0

            sorted_traps = sorted(
                [e for e in self._triples.values() if e["polarity"] == "NEGATIVE"],
                key=lambda x: x["weight"] * self._compute_decay(x["last_seen"], now),
                reverse=True,
            )[:5]

            traps_summary = [
                {
                    "triple": f"{t['subject']} {t['relation']} {t['target']}",
                    "count": t["count"],
                    "weight": round(t["weight"] * self._compute_decay(t["last_seen"], now), 2),
                    "last_seen": t["last_seen"],
                }
                for t in sorted_traps
            ]

            return {
                "total_triples": total_triples,
                "active_triples": active_triples,
                "negative_risk_triples": neg_triples,
                "positive_catalyst_triples": pos_triples,
                "total_episodes": total_episodes,
                "accuracy_pct": accuracy_pct,
                "regimes_indexed": len(self._regime_index),
                "top_failure_traps": traps_summary,
            }


# ─────────────────────────────────────────────────────────────────────────────
# Singleton Accessor
# ─────────────────────────────────────────────────────────────────────────────

_cognigraph_instance: CogniGraph | None = None
_instance_lock = threading.Lock()


def get_cognigraph(history_dir: str | None = None) -> CogniGraph:
    """Return process-level singleton CogniGraph instance, or new instance if explicit history_dir is given."""
    global _cognigraph_instance
    if history_dir is not None:
        if _cognigraph_instance is not None and str(_cognigraph_instance._file_path.parent) == str(Path(history_dir).resolve()):
            return _cognigraph_instance
        return CogniGraph(history_dir)

    if _cognigraph_instance is None:
        with _instance_lock:
            if _cognigraph_instance is None:
                _cognigraph_instance = CogniGraph()
    return _cognigraph_instance


def reset_cognigraph() -> None:
    """Reset the singleton instance (useful for test isolation)."""
    global _cognigraph_instance
    with _instance_lock:
        _cognigraph_instance = None
