"""
dreaming/axioms_storage.py — Persistence and merging of macro axioms.
"""

import os
import json
import logging
from typing import Any
from .constants import _clean_float, _now_ist_str

logger = logging.getLogger("DreamingEngine")


class AxiomStorageMixin:
    def _load_axioms(self) -> None:
        """Load existing macro axioms from disk."""
        if self._axioms_path.exists():
            try:
                with open(self._axioms_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
                raw_axioms = data.get("axioms", [])
                if isinstance(raw_axioms, list):
                    for ax in raw_axioms:
                        if isinstance(ax, dict) and "axiom_id" in ax:
                            self._axioms[ax["axiom_id"]] = ax
                elif isinstance(raw_axioms, dict):
                    for k, ax in raw_axioms.items():
                        if isinstance(ax, dict):
                            self._axioms[ax.get("axiom_id", k)] = ax
                logger.debug(f"DreamingEngine: Loaded {len(self._axioms)} macro axioms.")
            except Exception as e:
                logger.warning(f"DreamingEngine: Failed to load macro_axioms.json: {e}")
                self._axioms = {}

    def _save_axioms(self) -> None:
        """Atomically persist macro axioms."""
        payload = {
            "schema_version": 1,
            "last_dreamed_at": _now_ist_str(),
            "total_axioms": len(self._axioms),
            "axioms": list(self._axioms.values()),
        }
        tmp_path = str(self._axioms_path) + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self._axioms_path)
        except Exception as e:
            logger.error(f"DreamingEngine: Failed to save macro_axioms.json: {e}")
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass



    def merge_and_store_axioms(self, new_axioms: list[dict[str, Any]]) -> int:
        """
        Merge newly discovered axioms into self._axioms, updating observation
        counts and confidence scores.
        """
        with self._lock:
            updated_count = 0
            for ax in new_axioms:
                if not isinstance(ax, dict):
                    continue
                aid = ax.get("axiom_id")
                if not aid:
                    continue

                ax_norm = dict(ax)
                ax_norm["observation_count"] = int(_clean_float(ax.get("observation_count"), default=1.0))
                ax_norm["confidence"] = round(_clean_float(ax.get("confidence"), default=0.7), 2)
                if not isinstance(ax_norm.get("evidence_dates"), (list, tuple, set)):
                    ax_norm["evidence_dates"] = [str(ax_norm["evidence_dates"])] if ax_norm.get("evidence_dates") else []
                else:
                    ax_norm["evidence_dates"] = list(ax_norm["evidence_dates"])

                if aid in self._axioms:
                    existing = self._axioms[aid]
                    obs_old = int(_clean_float(existing.get("observation_count"), default=1.0))
                    obs_new = ax_norm["observation_count"]
                    existing["observation_count"] = obs_old + obs_new
                    # Running average of confidence
                    c_old = _clean_float(existing.get("confidence"), default=0.7)
                    c_new = ax_norm["confidence"]
                    existing["confidence"] = round((c_old * 0.6) + (c_new * 0.4), 2)
                    existing["last_validated"] = ax.get("last_validated", _now_ist_str())
                    # Merge evidence dates
                    ev_set = set(existing.get("evidence_dates", []))
                    ev_set.update(ax_norm["evidence_dates"])
                    existing["evidence_dates"] = sorted(list(ev_set))[-10:]
                    if ax.get("statement"):
                        existing["statement"] = str(ax["statement"])
                else:
                    self._axioms[aid] = ax_norm

                updated_count += 1

            self._save_axioms()
            return updated_count

    # ─────────────────────────────────────────────────────────────────────────
    # Step 3: CogniGraph Rebalancing & Decay
    # ─────────────────────────────────────────────────────────────────────────

