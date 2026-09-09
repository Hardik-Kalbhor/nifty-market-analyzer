"""
trajectory_exporter.py — Trajectory Dataset Exporter for LLM Fine-Tuning.

Adapted from Nous Research Hermes Agent trajectory generation architecture:
Compiles real-world multi-turn risk committee debates, catalyst specialist assessments,
and next-day market settlements into standard dataset formats:
  1. ShareGPT (Multi-turn SFT conversation format for Axolotl, LLaMA-Factory, Unsloth)
  2. DPO (Direct Preference Optimization pairwise chosen/rejected alignment format)
  3. Alpaca (Instruction-following single-turn format)

Enables continuous fine-tuning of open-source models (e.g. LLaMA-3, Qwen-2.5, Mistral)
on real NIFTY 50 trading decision intelligence and post-mortem reflections.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("TrajectoryExporter")

_SYSTEM_PROMPT = (
    "You are a Senior Quantitative Options Strategist and Risk Arbiter for the NIFTY 50 index. "
    "Your objective is to evaluate multi-dimensional market signals (GIFT Nifty momentum, FII/DII order flows, "
    "options open interest and Max Pain gravity, heavyweight index contributions, India VIX regime, and macro news) "
    "and synthesize a strictly calibrated overnight BTST (Buy Today, Sell Tomorrow) or intraday trade structure. "
    "Prioritize capital preservation over directional greed, mandate spread hedging when theta decay or event risk "
    "is elevated, and strictly enforce defined stop loss boundaries."
)


def _clean_float(val: Any, default: float = 0.0) -> float:
    """Safely parse float from string or numeric."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        s = str(val).strip().replace(",", "")
        m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
        if m:
            return float(m.group(0))
        return default
    except Exception:
        return default


class TrajectoryExporter:
    """
    Exports trading reasoning trajectories and post-market outcomes into SFT and DPO datasets.
    """

    def __init__(self, history_dir: str | Path | None = None):
        self._lock = threading.RLock()
        if history_dir is None:
            base = os.getenv("HISTORY_DIR", os.path.join(os.path.dirname(__file__), "history"))
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

    def export_sharegpt(self, episodes: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """
        Convert trade trajectories into ShareGPT multi-turn conversational format.
        Schema:
          {
            "id": "trade_YYYY-MM-DD",
            "conversations": [
              {"from": "system", "value": "..."},
              {"from": "human", "value": "..."},
              {"from": "gpt", "value": "..."},
              {"from": "human", "value": "..."},
              {"from": "gpt", "value": "..."}
            ]
          }
        """
        if episodes is None:
            episodes = self.collect_trajectories()

        sharegpt_dataset: list[dict[str, Any]] = []

        for ep in episodes:
            trade_date = ep.get("trade_date", "unknown_date")
            signals = ep.get("market_signals", {})
            bull_factors = ep.get("bullish_factors", [])
            bear_factors = ep.get("bearish_factors", [])
            debate = ep.get("debate", {})
            specialists = ep.get("dynamic_subagents", [])

            # Human turn 1: Context & observation
            signals_desc = (
                f"Market Signals for {trade_date}:\n"
                f"- GIFT Nifty Change: {signals.get('gift_nifty_change_pct', 'N/A')}%\n"
                f"- India VIX: {signals.get('india_vix', 'N/A')}\n"
                f"- Institutional FII Net Flow: ₹{signals.get('fii_net', 'N/A')} Cr\n"
                f"- Put-Call Ratio (PCR): {signals.get('pcr', 'N/A')}\n"
                f"- Bullish Factors: {', '.join(bull_factors[:4]) if bull_factors else 'None recorded'}\n"
                f"- Bearish Factors: {', '.join(bear_factors[:4]) if bear_factors else 'None recorded'}\n\n"
                "Evaluate these market conditions through the multi-agent Risk Committee and dynamic catalyst specialists. "
                "Synthesize the calibrated BTST structure, consensus verdict, and actionable trade instruction."
            )

            # Assistant turn 1: Reasoning, Committee Debate, and Final Calibrated Verdict
            gpt_reasoning_parts = ["<thought>"]
            if debate:
                agg = debate.get("aggressive", {})
                cons = debate.get("conservative", {})
                neut = debate.get("neutral", {})
                gpt_reasoning_parts.append(
                    f"Committee Perspectives:\n"
                    f"• Aggressive: {agg.get('verdict', 'N/A')} ({agg.get('confidence', 0)}%) — {agg.get('rationale', '')}\n"
                    f"• Conservative: {cons.get('verdict', 'N/A')} ({cons.get('confidence', 0)}%) — {cons.get('rationale', '')}\n"
                    f"• Neutral: {neut.get('verdict', 'N/A')} ({neut.get('confidence', 0)}%) — {neut.get('rationale', '')}"
                )
            if specialists:
                gpt_reasoning_parts.append("Catalyst Specialists:")
                for sp in specialists:
                    gpt_reasoning_parts.append(
                        f"• [{sp.get('subagent')}]: {sp.get('verdict')} ({sp.get('confidence')}%) — {sp.get('specialist_rationale')}"
                    )
            gpt_reasoning_parts.append(f"Base Reasoning: {ep.get('reasoning', '')}")
            gpt_reasoning_parts.append("</thought>")

            gpt_turn_1 = (
                f"{chr(10).join(gpt_reasoning_parts)}\n\n"
                f"**Directional Prediction**: {ep.get('prediction')} | **BTST Bias**: {ep.get('btst_bias')}\n"
                f"**Calibrated Trade Structure**: {ep.get('btst_structure')}\n"
                f"**Committee Consensus**: {ep.get('debate_consensus')} (Confidence: {ep.get('confidence')}%)\n"
                f"**Actionable Instruction**: {ep.get('trade_instruction') or 'Execute with tight stop loss and disciplined sizing.'}"
            )

            conversations = [
                {"from": "system", "value": _SYSTEM_PROMPT},
                {"from": "human", "value": signals_desc},
                {"from": "gpt", "value": gpt_turn_1},
            ]

            # If outcome is known, add settlement evaluation and reflection turns
            outcome = ep.get("outcome")
            reflection = ep.get("reflection")
            if outcome or reflection:
                human_turn_2 = (
                    f"Market Settlement Report for {trade_date}:\n"
                    f"- Actual Open Gap: {ep.get('actual_gap_pct'):+.2f}%\n"
                    f"- Trade Outcome: {outcome or 'SETTLED'}\n\n"
                    "Conduct a disciplined post-mortem reflection. Review what held, what failed, and the durable lesson learned."
                )
                gpt_turn_2 = (
                    f"Post-Mortem Reflection:\n"
                    f"{reflection or f'The trade outcome was {outcome}. The directional bias performed in accordance with risk limits.'}"
                )
                conversations.append({"from": "human", "value": human_turn_2})
                conversations.append({"from": "gpt", "value": gpt_turn_2})

            sharegpt_dataset.append({
                "id": f"nifty_btst_{trade_date}",
                "conversations": conversations,
            })

        return sharegpt_dataset

    def export_dpo(self, episodes: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """
        Convert trade trajectories into DPO (Direct Preference Optimization) pair format.
        Schema:
          {
            "id": "dpo_YYYY-MM-DD",
            "prompt": "...",
            "chosen": "...",
            "rejected": "...",
            "metadata": {...}
          }
        """
        if episodes is None:
            episodes = self.collect_trajectories()

        dpo_dataset: list[dict[str, Any]] = []

        for ep in episodes:
            trade_date = ep.get("trade_date", "unknown_date")
            outcome = ep.get("outcome", "").upper()
            signals = ep.get("market_signals", {})
            structure = ep.get("btst_structure", "HALF_QUANTITY")
            instruction = ep.get("trade_instruction", "")
            reasoning = ep.get("reasoning", "")
            reflection = ep.get("reflection", "")

            prompt = (
                f"Analyze NIFTY 50 overnight trade risk for {trade_date}:\n"
                f"GIFT Nifty: {signals.get('gift_nifty_change_pct', 'N/A')}%, "
                f"India VIX: {signals.get('india_vix', 'N/A')}, "
                f"FII Net: ₹{signals.get('fii_net', 'N/A')} Cr, "
                f"PCR: {signals.get('pcr', 'N/A')}.\n"
                "Recommend calibrated position sizing, risk controls, and BTST options structure."
            )

            is_correct = "CORRECT" in outcome

            if is_correct:
                # Chosen is the winning calibrated strategy with risk bounds
                chosen = (
                    f"Calibrated Verdict: {structure}\n"
                    f"Consensus: {ep.get('debate_consensus', 'MAJORITY')} (Confidence: {ep.get('confidence', 70)}%)\n"
                    f"Strategy: {instruction or 'Deploy controlled size adhering to conservative bounds.'}\n"
                    f"Rationale: {reasoning}\n"
                    "Risk Controls: VIX and theta decay strictly factored in; stops enforced."
                )
                # Rejected is an aggressive uncalibrated bet ignoring risk bounds
                rejected = (
                    f"Calibrated Verdict: FULL_BTST\n"
                    f"Consensus: UNANIMOUS (Confidence: 95%)\n"
                    f"Strategy: Take maximum naked contracts without stop loss.\n"
                    f"Rationale: Pure momentum bet. Disregard VIX levels, theta decay, or overnight headline risk."
                )
            elif "WRONG" in outcome:
                # When wrong, the chosen response is the corrective defensive strategy learned in reflection
                chosen = (
                    f"Calibrated Verdict: STRICT_NO_TRADE (Defensive Fallback)\n"
                    f"Post-Mortem Lesson: {reflection or 'Macro signals diverged; defensive capital preservation mandated.'}\n"
                    f"Corrective Action: Never take naked directional risk when heavyweight or institutional signals conflict with momentum."
                )
                # Rejected was the failed thesis that caused the wrong call
                rejected = (
                    f"Calibrated Verdict: FULL_BTST\n"
                    f"Rationale: {reasoning or 'Overconfidently held directional position despite conflicting macro signals.'}\n"
                    "Action: Ignored dissenting committee signals and maintained unhedged overnight exposure."
                )
            else:
                # Partial / Neutral
                chosen = (
                    f"Calibrated Verdict: HEDGED_SPREAD\n"
                    f"Rationale: Mixed signals warrant defined-risk spread structures rather than naked calls or puts.\n"
                    f"Instruction: {instruction or 'Cap downside with vertical spreads.'}"
                )
                rejected = (
                    f"Calibrated Verdict: FULL_BTST\n"
                    "Rationale: High conviction despite mixed signals; full capital allocation without hedging."
                )

            dpo_dataset.append({
                "id": f"nifty_dpo_{trade_date}",
                "prompt": prompt,
                "chosen": chosen,
                "rejected": rejected,
                "metadata": {
                    "trade_date": trade_date,
                    "prediction": ep.get("prediction"),
                    "btst_bias": ep.get("btst_bias"),
                    "outcome": outcome or "SETTLED",
                    "actual_gap_pct": ep.get("actual_gap_pct", 0.0),
                    "confidence": ep.get("confidence", 50),
                },
            })

        return dpo_dataset

    def export_alpaca(self, episodes: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """
        Convert trade trajectories into Alpaca instruction-tuning format.
        Schema:
          {
            "instruction": "...",
            "input": "...",
            "output": "...",
            "metadata": {...}
          }
        """
        if episodes is None:
            episodes = self.collect_trajectories()

        alpaca_dataset: list[dict[str, Any]] = []

        for ep in episodes:
            trade_date = ep.get("trade_date", "unknown_date")
            signals = ep.get("market_signals", {})

            instruction = (
                "You are an institutional NIFTY 50 trading quant. "
                "Synthesize prevailing market signals into a calibrated BTST trade structure and risk allocation."
            )
            input_text = (
                f"Date: {trade_date}\n"
                f"GIFT Nifty: {signals.get('gift_nifty_change_pct', 'N/A')}%\n"
                f"India VIX: {signals.get('india_vix', 'N/A')}\n"
                f"FII Net Flow: ₹{signals.get('fii_net', 'N/A')} Cr\n"
                f"PCR: {signals.get('pcr', 'N/A')}"
            )
            output_text = (
                f"Prediction: {ep.get('prediction')} | Bias: {ep.get('btst_bias')}\n"
                f"Structure: {ep.get('btst_structure')} ({ep.get('debate_consensus')})\n"
                f"Confidence: {ep.get('confidence')}%\n"
                f"Instruction: {ep.get('trade_instruction')}\n"
                f"Analysis: {ep.get('reasoning')}"
            )

            alpaca_dataset.append({
                "instruction": instruction,
                "input": input_text,
                "output": output_text,
                "metadata": {
                    "trade_date": trade_date,
                    "outcome": ep.get("outcome", ""),
                },
            })

        return alpaca_dataset

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
