"""
skills/curator.py — Skill Curator tracking performance metrics and win rates.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SkillCurator:
    """Monitors and audits the performance and win rates of active skills."""

    def __init__(self, history_dir: Path | str):
        self._history_dir = Path(history_dir)
        self._stats_file = self._history_dir / "skill_stats.json"
        self._lock = threading.Lock()
        self._data: dict[str, Any] = self._load_data()

    def _load_data(self) -> dict[str, Any]:
        """Load stored skill performance metrics."""
        if self._stats_file.exists():
            try:
                raw = self._stats_file.read_text(encoding="utf-8")
                return json.loads(raw)
            except Exception as e:
                logger.warning(f"SkillCurator could not read stats file: {e}")
        return {
            "version": 1,
            "skills": {},
            "date_attributions": {},  # trade_date -> list of skill names
        }

    def _save_data(self) -> None:
        """Atomically persist skill stats to disk to prevent file corruption."""
        try:
            self._history_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = self._stats_file.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            os.replace(tmp_path, self._stats_file)
        except Exception as e:
            logger.warning(f"SkillCurator could not save stats file: {e}")

    def record_activations(self, trade_date: str, skill_names: list[str]) -> None:
        """Record which skills were active for a particular trade date."""
        if not skill_names:
            return
        with self._lock:
            self._data.setdefault("date_attributions", {})[trade_date] = skill_names
            for name in skill_names:
                stats = self._data.setdefault("skills", {}).setdefault(name, {
                    "activations": 0,
                    "wins": 0,
                    "losses": 0,
                    "partials": 0,
                    "last_activated": None,
                })
                stats["activations"] += 1
                stats["last_activated"] = trade_date
            self._save_data()

    def record_outcome(self, trade_date: str, outcome_str: str) -> None:
        """Update win/loss metrics for skills that were active on trade_date."""
        with self._lock:
            active_skills = self._data.get("date_attributions", {}).get(trade_date, [])
            if not active_skills:
                return

            is_win = "CORRECT" in outcome_str.upper()
            is_partial = "PARTIAL" in outcome_str.upper()
            is_loss = "WRONG" in outcome_str.upper()

            for name in active_skills:
                stats = self._data.setdefault("skills", {}).setdefault(name, {
                    "activations": 1,
                    "wins": 0,
                    "losses": 0,
                    "partials": 0,
                    "last_activated": trade_date,
                })
                if is_win:
                    stats["wins"] += 1
                elif is_partial:
                    stats["partials"] += 1
                elif is_loss:
                    stats["losses"] += 1

            self._save_data()

    def get_report(self) -> dict[str, Any]:
        """Generate a health and effectiveness report for all registered skills."""
        with self._lock:
            report = {}
            for name, s in self._data.get("skills", {}).items():
                total_resolved = s["wins"] + s["losses"] + s["partials"]
                win_pct = round((s["wins"] / total_resolved * 100), 1) if total_resolved > 0 else None

                status = "INSUFFICIENT_DATA"
                if total_resolved >= 3:
                    status = "HEALTHY" if (win_pct is not None and win_pct >= 60.0) else "NEEDS_REVIEW"

                report[name] = {
                    "activations": s.get("activations", 0),
                    "wins": s.get("wins", 0),
                    "losses": s.get("losses", 0),
                    "partials": s.get("partials", 0),
                    "win_pct": win_pct,
                    "health_status": status,
                    "last_activated": s.get("last_activated"),
                }
            return report

    def get_curator_report(self) -> dict[str, Any]:
        """Standardized curator report dictionary for DreamingEngine."""
        return {"skills": self.get_report()}
