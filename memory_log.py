"""
memory_log.py — Decision Memory & Self-Reflection Loop for the NIFTY Analyzer.

Implements a 4-phase learning loop so the AI agent learns from its own past predictions:

  Phase A (15:15 IST): store_prediction()     — log today's BTST call as "pending"
  Phase B (08:30 IST): resolve_pending()       — fetch actual Nifty open, mark outcome
  Phase C (08:30 IST): _generate_reflection()  — LLM writes 2-3 sentence post-mortem
  Phase D (every run):  load_past_context()    — inject last N lessons into LLM prompt

The memory is stored as a plain-text Markdown file (history/memory_log.md).
Human-readable, zero extra dependencies, works on Render ephemeral storage.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pytz
import requests
import yf_cache

logger = logging.getLogger(__name__)

TIMEZONE = pytz.timezone("Asia/Kolkata")

# A gap is "UP" if actual open is >= +0.20% above prev close, "DOWN" if <= -0.20%
GAP_UP_THRESHOLD = 0.20     # %
GAP_DOWN_THRESHOLD = -0.20  # %

# Hard delimiter — cannot appear in LLM prose, safe as entry boundary
_SEPARATOR = "\n\n<!-- ENTRY_END -->\n\n"

# Pre-compiled regex for parsing entries
_TAG_RE = re.compile(
    r"^\[(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})"
    r"\s*\|\s*(?P<prediction>GAP UP|GAP DOWN|FLAT)"
    r"\s*\|\s*(?P<btst_bias>BUY CE|BUY PE|NO TRADE)"
    r"\s*\|\s*(?P<confidence>[0-9]+)%"
    r"\s*\|\s*(?P<status>[^\]]+)\]$",
    re.IGNORECASE,
)
_REASONING_RE = re.compile(r"REASONING:\n(.*?)(?=\nOUTCOME:|\nREFLECTION:|\Z)", re.DOTALL)
_OUTCOME_RE = re.compile(r"OUTCOME:\n(.*?)(?=\nREFLECTION:|\Z)", re.DOTALL)
_REFLECTION_RE = re.compile(r"REFLECTION:\n(.*?)$", re.DOTALL)

# Reflection system prompt — compact, re-injected verbatim into future prompts
_REFLECTION_SYSTEM_PROMPT = (
    "You are a NIFTY 50 trading analyst reviewing your own past BTST gap prediction "
    "now that the actual market outcome is known.\n\n"
    "Write exactly 2-3 sentences of plain prose. No bullets, no headers, no markdown.\n\n"
    "Cover in order:\n"
    "1. Was the directional call correct? (mention actual gap % if available)\n"
    "2. Which part of the thesis held or failed? (GIFT Nifty, FII flows, heavyweights, VIX, news)\n"
    "3. One concrete lesson for the next similar analysis.\n\n"
    "Be specific and terse. Your output is stored verbatim and re-read by future analysts "
    "so every word must earn its place. Write in past tense."
)


class NiftyMemoryLog:
    """Append-only NIFTY prediction memory log with self-reflection."""

    def __init__(self, history_dir: str | None = None):
        if history_dir is None:
            # Resolve relative to this file's location (news_repo/history/)
            base = os.path.join(os.path.dirname(__file__), "history")
        else:
            base = history_dir

        try:
            os.makedirs(base, exist_ok=True)
            self._log_path = Path(base) / "memory_log.md"
        except (OSError, PermissionError):
            # Render ephemeral fallback
            fallback = "/tmp/history"
            os.makedirs(fallback, exist_ok=True)
            self._log_path = Path(fallback) / "memory_log.md"

        logger.debug(f"NiftyMemoryLog path: {self._log_path}")

    # ─────────────────────────────────────────────────
    # PHASE A — Store Prediction (15:15 IST)
    # ─────────────────────────────────────────────────

    def store_prediction(
        self,
        trade_date: str,
        prediction: str,
        btst_bias: str,
        confidence: int,
        reasoning: str,
        dimension_scores: dict | None = None,
        fii_net: float | None = None,
        gift_nifty_pct: float | None = None,
        india_vix: float | None = None,
        ai_provider: str | None = None,
        btst_structure: str | None = None,
        debate_consensus: str | None = None,
    ) -> bool:
        """
        Phase A: Append a new 'pending' entry for today's 15:15 IST BTST prediction.
        Idempotent — a second call for the same trade_date is a no-op.
        Returns True if written, False if skipped (already exists).

        btst_structure:  calibrated trade size from debate committee
                         (e.g. "FULL_BTST", "HALF_QUANTITY", "HEDGED_SPREAD", "STRICT_NO_TRADE")
        debate_consensus: "UNANIMOUS" | "MAJORITY" | "SPLIT" — or None if debate skipped
        """
        # Idempotency: fast raw-text scan
        if self._log_path.exists():
            raw = self._log_path.read_text(encoding="utf-8")
            if f"[{trade_date} |" in raw and "| pending]" in raw:
                logger.info(f"Memory: entry for {trade_date} already exists, skipping Phase A.")
                return False

        tag = f"[{trade_date} | {prediction} | {btst_bias} | {confidence}% | pending]"

        # Build the reasoning block with supporting signals
        signals_parts = []
        if gift_nifty_pct is not None:
            signals_parts.append(f"GIFT Nifty: {gift_nifty_pct:+.2f}%")
        if fii_net is not None:
            signals_parts.append(f"FII Net: ₹{fii_net:+,.0f} Cr")
        if india_vix is not None:
            signals_parts.append(f"India VIX: {india_vix:.2f}")
        if dimension_scores:
            dim_summary = " | ".join(
                f"{k}: {v.get('bias', 'N/A')}"
                for k, v in dimension_scores.items()
                if isinstance(v, dict)
            )
            signals_parts.append(f"Dimensions: [{dim_summary}]")
        # Debate committee outcome (if debate ran)
        if btst_structure:
            debate_line = f"Debate Committee: {btst_structure}"
            if debate_consensus:
                debate_line += f" ({debate_consensus})"
            signals_parts.append(debate_line)
        if ai_provider:
            signals_parts.append(f"Engine: {ai_provider}")

        signals_line = "\n".join(signals_parts)
        full_reasoning = f"{reasoning}\n{signals_line}".strip()

        entry = f"{tag}\n\nREASONING:\n{full_reasoning}{_SEPARATOR}"

        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(entry)

        logger.info(f"✅ Memory Phase A: stored prediction [{trade_date}] {prediction} / {btst_bias} @ {confidence}%"
                    + (f" | Debate: {btst_structure} ({debate_consensus})" if btst_structure else ""))
        return True


    # ─────────────────────────────────────────────────
    # PHASE B+C — Resolve Outcomes (08:30 IST next day)
    # ─────────────────────────────────────────────────

    def resolve_pending_entries(
        self,
        llm_reflect_fn: Callable[[str, str], str] | None = None,
    ) -> list[dict]:
        """
        Phase B+C: For every pending entry, fetch actual Nifty 50 opening price,
        compute the outcome, then optionally generate a reflection via LLM.

        `llm_reflect_fn(system_prompt, human_prompt) -> str` should call any available LLM.
        If None, reflection is skipped (outcome only).

        Returns list of resolved entry dicts.
        """
        entries = self._load_raw_entries()
        pending = [e for e in entries if e.get("status") == "pending"]

        if not pending:
            logger.info("Memory: No pending entries to resolve.")
            return []

        resolved_list = []
        for entry in pending:
            trade_date = entry["date"]
            try:
                # Skip if trade_date is today or in the future (market not open yet)
                today_ist = datetime.now(TIMEZONE).date()
                entry_date = datetime.strptime(trade_date, "%Y-%m-%d").date()
                next_trading_day = _next_trading_day(entry_date)

                if next_trading_day > today_ist:
                    logger.debug(f"Memory: {trade_date} → next trading day {next_trading_day} hasn't happened yet.")
                    continue

                # Phase B: Fetch actual Nifty open price
                actual_gap_pct, actual_open, prev_close = _fetch_nifty_actual_gap(
                    trade_date=entry["date"],
                    resolution_date=next_trading_day.strftime("%Y-%m-%d"),
                )

                if actual_gap_pct is None:
                    logger.warning(f"Memory: Could not fetch actual open for {trade_date}, skipping.")
                    continue

                # Compute outcome
                actual_label = _classify_gap(actual_gap_pct)
                predicted_label = entry["prediction"].upper()

                if actual_label == predicted_label:
                    outcome_result = "✅ CORRECT"
                elif (
                    (predicted_label == "GAP UP" and actual_label == "FLAT" and actual_gap_pct > 0) or
                    (predicted_label == "GAP DOWN" and actual_label == "FLAT" and actual_gap_pct < 0)
                ):
                    outcome_result = "⚠️ PARTIAL (right direction, gap < threshold)"
                elif (
                    (predicted_label == "FLAT" and actual_label != "FLAT") or
                    (predicted_label == "GAP UP" and actual_label == "GAP DOWN") or
                    (predicted_label == "GAP DOWN" and actual_label == "GAP UP")
                ):
                    outcome_result = "❌ WRONG"
                else:
                    outcome_result = "⚠️ PARTIAL"

                outcome_text = (
                    f"Actual open: {actual_open:,.2f} ({actual_gap_pct:+.2f}%) → {actual_label} {outcome_result}"
                )

                # Phase C: LLM reflection
                reflection_text = ""
                if llm_reflect_fn is not None:
                    try:
                        human_prompt = (
                            f"Prediction date: {trade_date}\n"
                            f"Predicted: {entry['prediction']} / {entry['btst_bias']} (confidence: {entry['confidence']}%)\n"
                            f"Actual Nifty open: {actual_gap_pct:+.2f}% → {actual_label} ({outcome_result})\n\n"
                            f"Original reasoning:\n{entry.get('reasoning', 'N/A')}"
                        )
                        reflection_text = llm_reflect_fn(_REFLECTION_SYSTEM_PROMPT, human_prompt)
                        logger.info(f"Memory Phase C: reflection generated for {trade_date}")
                    except Exception as ref_err:
                        logger.warning(f"Memory: Reflection LLM call failed for {trade_date}: {ref_err}")
                        reflection_text = ""

                # Write updated entry back to the log
                self._update_entry(
                    trade_date=trade_date,
                    outcome_text=outcome_text,
                    reflection_text=reflection_text,
                    actual_gap_pct=actual_gap_pct,
                    outcome_result=outcome_result,
                )

                resolved_entry = {
                    "date": trade_date,
                    "prediction": entry["prediction"],
                    "btst_bias": entry["btst_bias"],
                    "actual_gap_pct": actual_gap_pct,
                    "outcome": outcome_result,
                    "reflection": reflection_text,
                }
                resolved_list.append(resolved_entry)
                logger.info(
                    f"✅ Memory Phase B: {trade_date} → actual {actual_gap_pct:+.2f}% ({actual_label}) | {outcome_result}"
                )

            except Exception as e:
                logger.error(f"Memory: Failed to resolve entry {trade_date}: {e}", exc_info=True)

        return resolved_list

    # ─────────────────────────────────────────────────
    # PHASE D — Load Past Context (every run)
    # ─────────────────────────────────────────────────

    def load_past_context(self, n: int = 5) -> str:
        """
        Phase D: Return a formatted string of the last N resolved predictions
        to inject into the LLM prompt as institutional memory.

        Only includes entries that have been resolved (have an OUTCOME section).
        Returns empty string if no resolved entries exist yet.
        """
        entries = self._load_raw_entries()
        resolved = [e for e in entries if e.get("status") not in ("pending",) and e.get("outcome")]

        if not resolved:
            return ""

        # Most recent first
        recent = resolved[-n:][::-1]

        parts = ["📚 PAST NIFTY GAP PREDICTION LESSONS (most recent first — learn from these):"]
        for i, e in enumerate(recent, 1):
            outcome_line = e.get("outcome", "Unknown")
            reflection_line = e.get("reflection", "").strip()
            lesson_block = (
                f"  {i}. [{e['date']}] Predicted: {e['prediction']} / {e['btst_bias']} ({e['confidence']}%)\n"
                f"     Outcome: {outcome_line}\n"
            )
            if reflection_line:
                lesson_block += f"     Lesson: {reflection_line}\n"
            parts.append(lesson_block)

        context = "\n".join(parts)
        logger.debug(f"Memory: Loaded {len(recent)} past lessons for context injection.")
        return context

    # ─────────────────────────────────────────────────
    # Stats / API
    # ─────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """
        Return accuracy statistics for the /api/memory endpoint.
        """
        entries = self._load_raw_entries()
        resolved = [e for e in entries if e.get("outcome")]
        pending = [e for e in entries if e.get("status") == "pending"]

        correct = sum(1 for e in resolved if "CORRECT" in e.get("outcome", ""))
        partial = sum(1 for e in resolved if "PARTIAL" in e.get("outcome", ""))
        wrong = sum(1 for e in resolved if "WRONG" in e.get("outcome", ""))
        total = len(resolved)

        return {
            "total_predictions": total + len(pending),
            "resolved": total,
            "pending": len(pending),
            "correct": correct,
            "partial": partial,
            "wrong": wrong,
            "accuracy_pct": round((correct / total * 100) if total > 0 else 0.0, 1),
            "entries": [
                {
                    "date": e["date"],
                    "prediction": e["prediction"],
                    "btst_bias": e["btst_bias"],
                    "confidence": e["confidence"],
                    "outcome": e.get("outcome", "pending"),
                    "reflection": e.get("reflection", ""),
                }
                for e in reversed(entries[-20:])  # last 20 entries, newest first
            ],
        }

    # ─────────────────────────────────────────────────
    # Internal Helpers
    # ─────────────────────────────────────────────────

    def _load_raw_entries(self) -> list[dict]:
        """Parse all entries from the memory log. Returns list of dicts."""
        if not self._log_path.exists():
            return []

        try:
            text = self._log_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Memory: Could not read log file: {e}")
            return []

        raw_blocks = [b.strip() for b in text.split(_SEPARATOR) if b.strip()]
        entries = []
        for block in raw_blocks:
            parsed = self._parse_block(block)
            if parsed:
                entries.append(parsed)
        return entries

    def _parse_block(self, block: str) -> dict | None:
        """Parse a single memory log entry block into a dict."""
        lines = block.splitlines()
        if not lines:
            return None

        tag_match = _TAG_RE.match(lines[0].strip())
        if not tag_match:
            return None

        entry = {
            "date": tag_match.group("date"),
            "prediction": tag_match.group("prediction").upper(),
            "btst_bias": tag_match.group("btst_bias").upper(),
            "confidence": int(tag_match.group("confidence")),
            "status": tag_match.group("status").strip().lower(),
        }

        reasoning_m = _REASONING_RE.search(block)
        entry["reasoning"] = reasoning_m.group(1).strip() if reasoning_m else ""

        outcome_m = _OUTCOME_RE.search(block)
        entry["outcome"] = outcome_m.group(1).strip() if outcome_m else ""

        reflection_m = _REFLECTION_RE.search(block)
        entry["reflection"] = reflection_m.group(1).strip() if reflection_m else ""

        return entry

    def _update_entry(
        self,
        trade_date: str,
        outcome_text: str,
        reflection_text: str,
        actual_gap_pct: float,
        outcome_result: str,
    ) -> None:
        """
        Atomically update the first pending entry matching trade_date
        by replacing its tag and appending OUTCOME + REFLECTION sections.
        Uses temp-file + os.replace() to prevent corruption on crash.
        """
        if not self._log_path.exists():
            return

        text = self._log_path.read_text(encoding="utf-8")
        blocks = text.split(_SEPARATOR)

        result_label = "correct" if "CORRECT" in outcome_result else (
            "partial" if "PARTIAL" in outcome_result else "wrong"
        )
        new_tag_status = f"{result_label} | actual: {actual_gap_pct:+.2f}%"

        updated = False
        new_blocks = []
        for block in blocks:
            stripped = block.strip()
            if not stripped:
                new_blocks.append(block)
                continue

            lines = stripped.splitlines()
            tag_line = lines[0].strip()
            tag_match = _TAG_RE.match(tag_line)

            if (
                not updated
                and tag_match
                and tag_match.group("date") == trade_date
                and tag_match.group("status").strip().lower() == "pending"
            ):
                # Replace the pending tag
                new_tag = (
                    f"[{trade_date} | {tag_match.group('prediction').upper()} "
                    f"| {tag_match.group('btst_bias').upper()} "
                    f"| {tag_match.group('confidence')}% | {new_tag_status}]"
                )
                # Remove old tag line, keep the rest
                rest = "\n".join(lines[1:]).strip()

                # Remove any stale OUTCOME / REFLECTION sections before appending fresh ones
                rest = _OUTCOME_RE.sub("", rest).strip()
                rest = _REFLECTION_RE.sub("", rest).strip()

                new_block = new_tag
                if rest:
                    new_block += "\n\n" + rest
                new_block += f"\n\nOUTCOME:\n{outcome_text}"
                if reflection_text:
                    new_block += f"\n\nREFLECTION:\n{reflection_text}"

                new_blocks.append(new_block)
                updated = True
            else:
                new_blocks.append(block)

        if not updated:
            logger.warning(f"Memory: Could not find pending entry for {trade_date} to update.")
            return

        new_text = _SEPARATOR.join(new_blocks)

        # Atomic write
        tmp_path = self._log_path.with_suffix(".tmp")
        tmp_path.write_text(new_text, encoding="utf-8")
        os.replace(tmp_path, self._log_path)
        logger.debug(f"Memory: Entry for {trade_date} atomically updated.")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers (module-level, no class dependency)
# ─────────────────────────────────────────────────────────────────────────────

def _classify_gap(gap_pct: float) -> str:
    """Classify a gap percentage into GAP UP / GAP DOWN / FLAT."""
    if gap_pct >= GAP_UP_THRESHOLD:
        return "GAP UP"
    if gap_pct <= GAP_DOWN_THRESHOLD:
        return "GAP DOWN"
    return "FLAT"


def _next_trading_day(from_date) -> object:
    """Return the next weekday (Mon–Fri) after from_date. Simple approximation — ignores NSE holidays."""
    next_day = from_date + timedelta(days=1)
    while next_day.weekday() >= 5:  # 5=Sat, 6=Sun
        next_day += timedelta(days=1)
    return next_day


def _fetch_nifty_actual_gap(trade_date: str, resolution_date: str) -> tuple[float | None, float | None, float | None]:
    """
    Fetch actual Nifty 50 opening price for resolution_date using yf_cache.
    Returns (gap_pct, actual_open, prev_close) or (None, None, None) on failure.

    Uses yf_cache.fetch_daily_bars() which handles retries, 429 back-off, host
    rotation, and 24-hour disk caching so reruns are instant.
    """
    from_ts = int((datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=5)).timestamp())
    to_ts   = int((datetime.strptime(resolution_date, "%Y-%m-%d") + timedelta(days=2)).timestamp())

    bars = yf_cache.fetch_daily_bars("^NSEI", period1_ts=from_ts, period2_ts=to_ts, timeout=8.0)
    if not bars or len(bars) < 2:
        logger.warning(f"Memory: No sufficient bars returned for ^NSEI around {resolution_date}")
        return None, None, None

    # Find the resolution date's bar (or nearest trading day on/after it)
    from datetime import date as _date
    res_date = datetime.strptime(resolution_date, "%Y-%m-%d").date()
    bar_dates = [datetime.strptime(b["date"], "%Y-%m-%d").date() for b in bars]

    # Find index of resolution date or the nearest future trading day
    idx = None
    for i, d in enumerate(bar_dates):
        if d >= res_date:
            idx = i
            break

    if idx is None or idx == 0:
        logger.warning(f"Memory: Could not find a usable bar on/after {resolution_date}")
        return None, None, None

    actual_open = bars[idx].get("open")
    prev_close  = bars[idx - 1].get("close")

    if actual_open is None or prev_close is None or prev_close == 0:
        logger.warning(f"Memory: Missing open/close values for {resolution_date}")
        return None, None, None

    gap_pct = ((actual_open - prev_close) / prev_close) * 100
    return round(gap_pct, 3), round(actual_open, 2), round(prev_close, 2)



def build_reflect_fn_from_env() -> Callable[[str, str], str] | None:
    """
    Build a simple reflect function that calls Groq or Gemini (whichever key is set).
    Returns None if neither key is available.
    """
    groq_key = os.environ.get("GROQ_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")

    if groq_key:
        def reflect_via_groq(system_prompt: str, human_prompt: str) -> str:
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json",
            }
            for model in ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.6-27b"]:
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": human_prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 200,
                }
                try:
                    r = requests.post(url, headers=headers, json=payload, timeout=10)
                    if r.status_code == 200:
                        return r.json()["choices"][0]["message"]["content"].strip()
                except Exception as e:
                    logger.warning(f"Groq reflection call failed ({model}): {e}")
            raise RuntimeError("All Groq models failed for reflection")

        return reflect_via_groq

    if gemini_key:
        def reflect_via_gemini(system_prompt: str, human_prompt: str) -> str:
            for model in ["gemini-2.5-flash", "gemini-flash-latest"]:
                url = (
                    f"https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{model}:generateContent?key={gemini_key}"
                )
                payload = {
                    "contents": [
                        {"role": "user", "parts": [{"text": system_prompt + "\n\n" + human_prompt}]}
                    ],
                    "generationConfig": {"maxOutputTokens": 200, "temperature": 0.3},
                }
                try:
                    r = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=12)
                    if r.status_code == 200:
                        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                except Exception as e:
                    logger.warning(f"Gemini reflection call failed ({model}): {e}")
            raise RuntimeError("All Gemini models failed for reflection")

        return reflect_via_gemini

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton accessor (lazy-init, one instance per process)
# ─────────────────────────────────────────────────────────────────────────────
_memory_log_instance: NiftyMemoryLog | None = None


def get_memory_log(history_dir: str | None = None) -> NiftyMemoryLog:
    """Return the process-level singleton NiftyMemoryLog instance."""
    global _memory_log_instance
    if _memory_log_instance is None:
        _memory_log_instance = NiftyMemoryLog(history_dir)
    return _memory_log_instance


# ─────────────────────────────────────────────────────────────────────────────
# Smoke test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile

    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")

    with tempfile.TemporaryDirectory() as tmp:
        ml = NiftyMemoryLog(history_dir=tmp)

        # Phase A
        today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
        ml.store_prediction(
            trade_date=today,
            prediction="GAP UP",
            btst_bias="BUY CE",
            confidence=72,
            reasoning="GIFT Nifty +0.65%, FII net +₹1200Cr. Heavyweights positive.",
            fii_net=1200.0,
            gift_nifty_pct=0.65,
            india_vix=11.5,
        )

        # Phase D
        ctx = ml.load_past_context()
        print("Past context (empty on first run):", repr(ctx))

        # Stats
        stats = ml.get_stats()
        print("Stats:", json.dumps(stats, indent=2))

        print("\n✅ Smoke test passed.")
