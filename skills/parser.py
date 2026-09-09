"""
skills/parser.py — Frontmatter parsing and numeric sanitization for skills.
"""

from __future__ import annotations

import re
from typing import Any


def _clean_numeric(val: Any) -> float:
    """Parse numeric values safely, stripping currency, commas, and percentage characters."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        cleaned = re.sub(r"[^\d.-]", "", str(val))
        return float(cleaned) if cleaned else 0.0
    except Exception:
        return 0.0


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """
    Parse YAML-style frontmatter enclosed by '---' from markdown content.
    Handles BOM, leading whitespace, and basic data types (lists, ints, bools).
    Returns (metadata_dict, body_markdown).
    """
    frontmatter: dict[str, Any] = {}
    cleaned_text = text.lstrip("\ufeff").strip()
    body = cleaned_text

    if cleaned_text.startswith("---"):
        parts = cleaned_text.split("---", 2)
        if len(parts) >= 3:
            raw_meta = parts[1].strip()
            body = parts[2].strip()

            current_list_key = None
            for line in raw_meta.splitlines():
                line_str = line.strip()
                if not line_str or line_str.startswith("#"):
                    continue

                if line_str.startswith("- ") and current_list_key:
                    item_val = line_str[2:].strip().strip("\"'")
                    frontmatter.setdefault(current_list_key, []).append(item_val)
                    continue

                if ":" in line_str:
                    k, v = line_str.split(":", 1)
                    k = k.strip()
                    v = v.strip().strip("\"'")
                    if not v:
                        current_list_key = k
                        frontmatter[k] = []
                    else:
                        current_list_key = None
                        if v.isdigit():
                            frontmatter[k] = int(v)
                        elif v.lower() == "true":
                            frontmatter[k] = True
                        elif v.lower() == "false":
                            frontmatter[k] = False
                        else:
                            frontmatter[k] = v

    return frontmatter, body
