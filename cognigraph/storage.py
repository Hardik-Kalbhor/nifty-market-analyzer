"""
cognigraph/storage.py — Persistence, bootstrap seed priors, decay & pruning, and statistics.
"""

import os
import json
import logging
from typing import Any
from .constants import COGNIGRAPH_SCHEMA_VERSION, _days_between, _today_str, _safe_float

logger = logging.getLogger("CogniGraph")


class StorageMixin:
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


