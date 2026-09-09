"""
trajectory/core.py — TrajectoryExporter class definition, file export, and singleton access.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .collector import TrajectoryCollectorMixin
from .formatters import TrajectoryFormattersMixin

logger = logging.getLogger("TrajectoryExporter")


class TrajectoryExporter(TrajectoryCollectorMixin, TrajectoryFormattersMixin):
    """
    Exports trading reasoning trajectories and post-market outcomes into SFT and DPO datasets.
    """

    def __init__(self, history_dir: str | Path | None = None):
        self._lock = threading.RLock()
        if history_dir is None:
            base = os.getenv("HISTORY_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "history"))
        else:
            base = str(history_dir)

        try:
            os.makedirs(base, exist_ok=True)
            self._history_dir = Path(base)
        except (OSError, PermissionError):
            fallback = "/tmp/history"
            os.makedirs(fallback, exist_ok=True)
            self._history_dir = Path(fallback)

        self._export_dir = self._history_dir

    def export_all(
        self,
        output_dir: str | Path | None = None,
        include_pending: bool = False,
    ) -> dict[str, Any]:
        """
        Atomically write ShareGPT, DPO, and Alpaca datasets to disk as JSONL files.
        """
        with self._lock:
            out_path = Path(output_dir) if output_dir else self._export_dir
            out_path.mkdir(parents=True, exist_ok=True)

            episodes = self.collect_trajectories(include_pending=include_pending)

            sharegpt_data = self.export_sharegpt(episodes)
            dpo_data = self.export_dpo(episodes)
            alpaca_data = self.export_alpaca(episodes)

            files_written: dict[str, str] = {}

            # Helper for atomic JSONL write
            def _write_jsonl(filename: str, records: list[dict[str, Any]]) -> str:
                target = out_path / filename
                temp = out_path / f"{filename}.tmp"
                with open(temp, "w", encoding="utf-8") as f:
                    for rec in records:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                os.replace(temp, target)
                return str(target)

            files_written["sharegpt"] = _write_jsonl("trajectories_sharegpt.jsonl", sharegpt_data)
            files_written["dpo"] = _write_jsonl("trajectories_dpo.jsonl", dpo_data)
            files_written["alpaca"] = _write_jsonl("trajectories_alpaca.jsonl", alpaca_data)

            logger.info(
                f"TrajectoryExporter: Successfully exported {len(episodes)} episodes to {out_path}"
            )

            return {
                "status": "success",
                "total_exported": len(episodes),
                "export_dir": str(out_path),
                "files": files_written,
                "timestamp": datetime.now().isoformat(),
            }


# ─────────────────────────────────────────────────────────────────────────────
# Thread-safe Singleton Access
# ─────────────────────────────────────────────────────────────────────────────

_EXPORTERS: dict[str, TrajectoryExporter] = {}
_EXPORTERS_LOCK = threading.Lock()


def get_trajectory_exporter(history_dir: str | None = None) -> TrajectoryExporter:
    """Return a cached TrajectoryExporter instance keyed by history_dir."""
    key = os.path.abspath(history_dir) if history_dir else "default"
    with _EXPORTERS_LOCK:
        if key not in _EXPORTERS:
            _EXPORTERS[key] = TrajectoryExporter(history_dir)
        return _EXPORTERS[key]
