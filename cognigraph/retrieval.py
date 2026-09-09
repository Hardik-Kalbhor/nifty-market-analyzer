"""
cognigraph/retrieval.py — Persona-conditioned memory retrieval and judge calibration.
"""

import logging
from typing import Any
from .constants import _safe_float, _today_str

logger = logging.getLogger("CogniGraph")


class RetrievalMixin:
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

