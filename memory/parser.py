"""
memory/parser.py — Memory log parsing and atomic entry updates.
"""

import os
import logging
from pathlib import Path
from typing import Any

from .constants import (
    _SEPARATOR,
    _TAG_RE,
    _REASONING_RE,
    _OUTCOME_RE,
    _REFLECTION_RE,
)

logger = logging.getLogger(__name__)


class MemoryParserMixin:
    """Mixin providing log block parsing and atomic updates."""

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
