"""
trajectory/collector.py — Trajectory episode collection and data joining.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from .constants import _clean_float

logger = logging.getLogger("TrajectoryExporter")


class TrajectoryCollectorMixin:
    """Mixin providing trajectory data gathering and correlation."""

    def collect_trajectories(self, include_pending: bool = False) -> list[dict[str, Any]]:
        """
        Gather resolved trade episodes by joining memory_log.md entries with
        corresponding analysis_*.json snapshots and exit evaluations.
        """
        episodes: list[dict[str, Any]] = []

        # 1. Load memory entries from memory_log
        raw_entries: list[dict[str, Any]] = []
        try:
            from memory_log import get_memory_log
            mem = get_memory_log(str(self._history_dir))
            raw_entries = mem._load_raw_entries()
        except Exception as mem_err:
            logger.warning(f"TrajectoryExporter: MemoryLog load error: {mem_err}")

        # 2. Index analysis_*.json files by date (preferring 1515 canonical BTST run)
        analysis_by_date: dict[str, dict[str, Any]] = {}
        if self._history_dir.exists():
            for f in sorted(self._history_dir.glob("analysis_*.json")):
                try:
                    # Match date YYYY-MM-DD from filename
                    dm = re.search(r"(\d{4}-\d{2}-\d{2})", f.name)
                    if dm:
                        date_str = dm.group(1)
                        if date_str not in analysis_by_date or "1515" in f.name:
                            with open(f, "r", encoding="utf-8") as jf:
                                content = json.load(jf)
                                if isinstance(content, dict):
                                    analysis_by_date[date_str] = content
                except Exception as af_err:
                    logger.debug(f"TrajectoryExporter: Skipping analysis file {f.name}: {af_err}")

        # 3. Join memory entries with analysis data
        for entry in raw_entries:
            trade_date = entry.get("date", "")
            status = entry.get("status", "resolved")
            outcome = entry.get("outcome", "")

            if not include_pending and status == "pending" and not outcome:
                continue

            analysis_data = analysis_by_date.get(trade_date, {})

            # Extract signals with multiple defensive fallback layers
            market_signals = dict(analysis_data.get("market_signals") or {})
            if not market_signals:
                fii_val = analysis_data.get("fii_dii", {}).get("fii_net_crores") if isinstance(analysis_data.get("fii_dii"), dict) else None
                gift_val = analysis_data.get("gift_nifty", {}).get("change_pct") if isinstance(analysis_data.get("gift_nifty"), dict) else None
                vix_val = analysis_data.get("india_vix", {}).get("current") if isinstance(analysis_data.get("india_vix"), dict) else None
                pcr_val = analysis_data.get("oi_pcr", {}).get("pcr") if isinstance(analysis_data.get("oi_pcr"), dict) else None

                market_signals = {
                    "fii_net": fii_val,
                    "gift_nifty_change_pct": gift_val,
                    "india_vix": vix_val,
                    "pcr": pcr_val,
                }

            # If any signal remains None, parse from entry reasoning text
            reasoning_text = entry.get("reasoning", "")
            if market_signals.get("fii_net") is None:
                fm = re.search(r"FII Net:\s*₹?([+-]?[\d,]+)", reasoning_text)
                if fm:
                    market_signals["fii_net"] = _clean_float(fm.group(1))

            if market_signals.get("gift_nifty_change_pct") is None:
                gm = re.search(r"GIFT Nifty:\s*([+-]?[\d\.]+)%", reasoning_text)
                if gm:
                    market_signals["gift_nifty_change_pct"] = _clean_float(gm.group(1))

            if market_signals.get("india_vix") is None:
                vm = re.search(r"India VIX:\s*([\d\.]+)", reasoning_text)
                if vm:
                    market_signals["india_vix"] = _clean_float(vm.group(1))

            if market_signals.get("pcr") is None:
                pm = re.search(r"PCR\s*([\d\.]+)", reasoning_text)
                if pm:
                    market_signals["pcr"] = _clean_float(pm.group(1))

            # Extract actual gap pct
            actual_gap_pct = 0.0
            if outcome:
                gm = re.search(r"([+-]?\d+\.?\d*)%", outcome)
                if gm:
                    actual_gap_pct = _clean_float(gm.group(1))

            # Extract debate committee data if present
            debate_data = analysis_data.get("debate") or {}
            dynamic_subagents = debate_data.get("dynamic_subagents") or []

            # Extract structure and consensus with regex fallback from reasoning
            btst_structure = analysis_data.get("btst_structure") or entry.get("btst_structure")
            if not btst_structure:
                sm = re.search(r"Debate Committee:\s*([A-Z_]+)", reasoning_text)
                if sm and sm.group(1) in {"FULL_BTST", "HALF_QUANTITY", "HEDGED_SPREAD", "STRICT_NO_TRADE"}:
                    btst_structure = sm.group(1)
            if not btst_structure:
                btst_structure = "HALF_QUANTITY"

            debate_consensus = analysis_data.get("debate_consensus") or entry.get("debate_consensus")
            if not debate_consensus:
                cm = re.search(r"Debate Committee:\s*[A-Z_]+\s*\(([A-Z]+)\)", reasoning_text)
                if cm and cm.group(1) in {"UNANIMOUS", "MAJORITY", "SPLIT"}:
                    debate_consensus = cm.group(1)
            if not debate_consensus:
                debate_consensus = "MAJORITY"

            episode = {
                "trade_date": trade_date,
                "prediction": entry.get("prediction", "FLAT"),
                "btst_bias": entry.get("btst_bias", "NO TRADE"),
                "confidence": entry.get("confidence", 50),
                "btst_structure": btst_structure,
                "trade_instruction": analysis_data.get("trade_instruction", ""),
                "debate_consensus": debate_consensus,
                "status": status,
                "outcome": outcome,
                "actual_gap_pct": actual_gap_pct,
                "reasoning": entry.get("reasoning", "") or analysis_data.get("ai_reasoning", ""),
                "reflection": entry.get("reflection", ""),
                "market_signals": market_signals,
                "heavyweights": analysis_data.get("heavyweights", {}),
                "bullish_factors": analysis_data.get("bullish_factors", []),
                "bearish_factors": analysis_data.get("bearish_factors", []),
                "debate": debate_data,
                "dynamic_subagents": dynamic_subagents,
                "source": "live_trading_loop",
            }
            episodes.append(episode)

        # 4. Also harvest standalone analysis_*.json snapshots not present in memory_log
        covered_dates = {ep["trade_date"] for ep in episodes}
        for date_str, analysis_data in sorted(analysis_by_date.items()):
            if date_str not in covered_dates and isinstance(analysis_data, dict):
                signals = dict(analysis_data.get("market_signals") or {})
                if not signals:
                    fii_val = analysis_data.get("fii_dii", {}).get("fii_net_crores") if isinstance(analysis_data.get("fii_dii"), dict) else None
                    gift_val = analysis_data.get("gift_nifty", {}).get("change_pct") if isinstance(analysis_data.get("gift_nifty"), dict) else None
                    vix_val = analysis_data.get("india_vix", {}).get("current") if isinstance(analysis_data.get("india_vix"), dict) else None
                    pcr_val = analysis_data.get("oi_pcr", {}).get("pcr") if isinstance(analysis_data.get("oi_pcr"), dict) else None
                    signals = {
                        "fii_net": fii_val,
                        "gift_nifty_change_pct": gift_val,
                        "india_vix": vix_val,
                        "pcr": pcr_val,
                    }

                # Also inspect dimension_scores notes for missing values
                dim_scores = analysis_data.get("dimension_scores") or {}
                if isinstance(dim_scores, dict):
                    if signals.get("fii_net") is None and "fii_dii" in dim_scores:
                        fn_match = re.search(r"net\s*([+-]?)\s*₹?\s*([+-]?\d+)", str(dim_scores["fii_dii"].get("note", "")))
                        if fn_match:
                            sign = -1 if ("-" in (fn_match.group(1) + fn_match.group(2))) else 1
                            num = abs(_clean_float(fn_match.group(2)))
                            signals["fii_net"] = sign * num
                    if signals.get("gift_nifty_change_pct") is None and "macro_global" in dim_scores:
                        gn_match = re.search(r"GIFT\s*([+-]?[\d\.]+)%", str(dim_scores["macro_global"].get("note", "")))
                        if gn_match:
                            signals["gift_nifty_change_pct"] = _clean_float(gn_match.group(1))
                    if signals.get("india_vix") is None and "vix_regime" in dim_scores:
                        vx_match = re.search(r"VIX\s*([\d\.]+)", str(dim_scores["vix_regime"].get("note", "")))
                        if vx_match:
                            signals["india_vix"] = _clean_float(vx_match.group(1))
                    if signals.get("pcr") is None and "oi_pcr" in dim_scores:
                        pcr_match = re.search(r"PCR\s*([\d\.]+)", str(dim_scores["oi_pcr"].get("note", "")))
                        if pcr_match:
                            signals["pcr"] = _clean_float(pcr_match.group(1))

                debate_data = analysis_data.get("debate") or {}
                dynamic_subagents = debate_data.get("dynamic_subagents") or []

                episode = {
                    "trade_date": date_str,
                    "prediction": analysis_data.get("prediction", "FLAT"),
                    "btst_bias": analysis_data.get("btst_bias", "NO TRADE"),
                    "confidence": int(_clean_float(analysis_data.get("confidence"), 50)),
                    "btst_structure": analysis_data.get("btst_structure") or "STRICT_NO_TRADE",
                    "trade_instruction": analysis_data.get("trade_instruction", ""),
                    "debate_consensus": analysis_data.get("debate_consensus") or "MAJORITY",
                    "status": "archived_snapshot",
                    "outcome": analysis_data.get("outcome", ""),
                    "actual_gap_pct": _clean_float(analysis_data.get("actual_gap_pct"), 0.0),
                    "reasoning": analysis_data.get("ai_reasoning") or analysis_data.get("final_summary") or "",
                    "reflection": analysis_data.get("reflection", ""),
                    "market_signals": signals,
                    "heavyweights": analysis_data.get("heavyweights", {}),
                    "bullish_factors": analysis_data.get("bullish_factors", []),
                    "bearish_factors": analysis_data.get("bearish_factors", []),
                    "debate": debate_data,
                    "dynamic_subagents": dynamic_subagents,
                    "source": "analysis_snapshot",
                }
                episodes.append(episode)

        logger.info(f"TrajectoryExporter: Collected {len(episodes)} trajectory episodes.")
        return episodes
