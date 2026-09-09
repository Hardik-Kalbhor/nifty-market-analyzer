"""
dreaming/harvest.py — Episodic history harvesting from disk JSON files.
"""

import os
import re
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .constants import _clean_float

logger = logging.getLogger("DreamingEngine")


class HarvestMixin:
    def harvest_episodes(self, max_episodes: int = 30) -> list[dict[str, Any]]:
        """
        Extract resolved trading episodes and post-mortems from memory_log.md
        and recent analysis_*.json files.
        """
        episodes: list[dict[str, Any]] = []

        try:
            from memory_log import get_memory_log
            mem = get_memory_log(str(self._history_dir))
            raw_entries = mem._load_raw_entries()

            # Filter for resolved episodes
            for e in raw_entries:
                if e.get("status") != "pending" and e.get("outcome"):
                    trade_date = e.get("date", "")
                    actual_gap = _clean_float(e.get("actual_gap_pct"))
                    if actual_gap == 0.0:
                        m = re.search(r"Actual:\s*([+-]?\d+(?:\.\d+)?)%", str(e.get("outcome", "")))
                        if m:
                            actual_gap = _clean_float(m.group(1))
                        elif "actual:" in str(e.get("status", "")).lower():
                            actual_gap = _clean_float(str(e.get("status", "")).lower().split("actual:")[-1])
                    pred = e.get("prediction", "FLAT")
                    btst = e.get("btst_bias", "NO TRADE")
                    raw_out = str(e.get("outcome", "PARTIAL")).upper()
                    if "CORRECT" in raw_out:
                        out = "CORRECT"
                    elif "WRONG" in raw_out:
                        out = "WRONG"
                    elif "PARTIAL" in raw_out:
                        out = "PARTIAL"
                    else:
                        out = str(e.get("outcome", "PARTIAL")).strip()
                    refl = e.get("reflection", "")
                    reasoning = e.get("reasoning", "")
                    conf = int(_clean_float(e.get("confidence"), default=50))
                    fii_net = _clean_float(e.get("fii_net"), default=0.0)
                    vix = _clean_float(e.get("india_vix"), default=14.0)

                    episodes.append({
                        "trade_date": trade_date,
                        "prediction": pred,
                        "btst_bias": btst,
                        "confidence": conf,
                        "actual_gap_pct": actual_gap,
                        "outcome": out,
                        "reflection": refl,
                        "reasoning": reasoning,
                        "fii_net": fii_net,
                        "india_vix": vix,
                        "active_skills": e.get("active_skills", []),
                        "trade_structure": e.get("trade_structure", "HALF_QUANTITY"),
                    })

            # Sort chronologically, newest first, cap at max_episodes
            episodes.sort(key=lambda x: x["trade_date"], reverse=True)
            return episodes[:max_episodes]

        except Exception as err:
            logger.warning(f"DreamingEngine: Error harvesting episodes: {err}")
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # Step 1b: Harvest Live Exit Episodes & Evaluations
    # ─────────────────────────────────────────────────────────────────────────

    def harvest_exit_episodes(self, max_entries: int = 50) -> list[dict[str, Any]]:
        """
        Harvest past live exit recommendations from history/exit_evaluations.jsonl.
        Extracts position parameters, entry/current spots & premiums, verdicts,
        contrarian warnings, and correlates with end-of-day market settlement prices.
        """
        exit_log_path = self._history_dir / "exit_evaluations.jsonl"
        if not exit_log_path.exists():
            return []

        episodes: list[dict[str, Any]] = []
        settlement_cache: dict[str, float] = {}
        try:
            latest_file = self._history_dir / "latest.json"
            if latest_file.exists():
                with open(latest_file, "r", encoding="utf-8") as f:
                    ldata = json.load(f)
                    spot_val = _clean_float(ldata.get("nifty_spot") or ldata.get("spot"))
                    if spot_val > 0:
                        settlement_cache["latest"] = spot_val
        except Exception:
            pass

        try:
            with open(exit_log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if not isinstance(record, dict):
                            continue

                        pos = record.get("position") or {}
                        side = (
                            pos.get("position_side")
                            or pos.get("position_type")
                            or pos.get("option_type")
                            or "BUY_CE"
                        )
                        entry_spot = _clean_float(
                            pos.get("entry_spot") or pos.get("entry_price") or record.get("live_spot"),
                            default=24200.0,
                        )
                        entry_prem = _clean_float(
                            pos.get("entry_premium") or pos.get("entry_price"), default=0.0
                        )
                        curr_prem = _clean_float(
                            pos.get("current_premium") or pos.get("current_price"), default=0.0
                        )
                        live_spot = _clean_float(
                            record.get("live_spot") or pos.get("current_spot") or entry_spot,
                            default=entry_spot,
                        )
                        ts = str(record.get("timestamp") or "")

                        rec_date = ts[:10] if len(ts) >= 10 else ""
                        settlement_spot = None
                        if rec_date and rec_date in settlement_cache:
                            settlement_spot = settlement_cache[rec_date]
                        elif "latest" in settlement_cache:
                            settlement_spot = settlement_cache["latest"]

                        episodes.append({
                            "timestamp": ts,
                            "trade_date": rec_date,
                            "position": {
                                "position_side": str(side).upper(),
                                "trade_type": str(pos.get("trade_type") or pos.get("holding_type") or "INTRADAY").upper(),
                                "strike": str(pos.get("strike") or pos.get("instrument") or ""),
                                "entry_spot": entry_spot,
                                "entry_premium": entry_prem,
                                "current_premium": curr_prem,
                                "current_spot": _clean_float(pos.get("current_spot"), default=live_spot),
                                "risk_profile": str(pos.get("risk_profile") or "BALANCED").upper(),
                            },
                            "live_spot": live_spot,
                            "settlement_spot": settlement_spot,
                            "verdict": str(record.get("verdict") or "").upper(),
                            "engine": str(record.get("engine") or ""),
                            "contrarian_warning": str(record.get("contrarian_warning") or ""),
                            "cognigraph_regime": str(record.get("cognigraph_regime") or ""),
                            "latency_ms": _clean_float(record.get("latency_ms"), default=0.0),
                        })
                    except Exception as parse_err:
                        logger.debug(f"DreamingEngine: Skipped corrupted exit log line: {parse_err}")

            episodes.sort(key=lambda x: x["timestamp"], reverse=True)
            return episodes[:max_entries]

        except Exception as err:
            logger.warning(f"DreamingEngine: Error harvesting exit evaluations: {err}")
            return []

