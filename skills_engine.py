"""
skills_engine.py — Procedural Trading Playbooks & Curator Engine for NIFTY Agents.

Adapted from the Nous Research Hermes Agent skills architecture (compatible with agentskills.io):
  1. Portable Markdown Playbooks: Loads SKILL.md files with YAML frontmatter from skills/ directory.
  2. Context-Aware Trigger Matching: Dynamically activates relevant playbooks based on live market conditions
     (DTE, VIX, FII/DII divergence, heavyweight conflict, monetary policy news).
  3. Skill Curator Subsystem: Tracks activation frequency, win rate, and outcome attribution per playbook.
  4. Atomic Persistence: Safely persists performance stats via atomic file replacement.
  5. Defensive Input Handling: Full protection against NoneType or malformed signal values.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Global singleton cache keyed by (skills_dir, history_dir)
_SKILLS_ENGINES: dict[str, SkillsEngine] = {}
_ENGINE_LOCK = threading.Lock()


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


class SkillsEngine:
    """Discovers, evaluates, and matches procedural trading playbooks."""

    def __init__(self, skills_dir: str | None = None, history_dir: str | None = None):
        if skills_dir is None:
            self._skills_dir = Path(__file__).parent / "skills"
        else:
            self._skills_dir = Path(skills_dir)

        if history_dir is None:
            self._history_dir = Path(__file__).parent / "history"
        else:
            self._history_dir = Path(history_dir)

        self._skills_cache: dict[str, dict[str, Any]] = {}
        self.curator = SkillCurator(self._history_dir)
        self.reload_skills()

    def reload_skills(self) -> int:
        """Scan skills directory and parse all SKILL.md playbooks."""
        self._skills_cache.clear()
        if not self._skills_dir.exists():
            logger.debug(f"Skills directory {self._skills_dir} does not exist.")
            return 0

        loaded = 0
        for skill_file in self._skills_dir.glob("**/SKILL.md"):
            try:
                content = skill_file.read_text(encoding="utf-8")
                frontmatter, body = _parse_frontmatter(content)
                name = frontmatter.get("name") or skill_file.parent.name
                skill_entry = {
                    "name": name,
                    "description": frontmatter.get("description", ""),
                    "triggers": frontmatter.get("triggers", []),
                    "priority": frontmatter.get("priority", 50),
                    "body": body,
                    "path": str(skill_file),
                }
                self._skills_cache[name] = skill_entry
                loaded += 1
            except Exception as e:
                logger.warning(f"Failed to load skill from {skill_file}: {e}")

        logger.info(f"SkillsEngine: Loaded {loaded} procedural trading skills from {self._skills_dir}")
        return loaded

    def match_skills(
        self,
        signals: dict[str, Any] | None = None,
        stage1_result: dict[str, Any] | None = None,
        news_items: list[dict[str, Any]] | None = None,
        heavyweights: dict[str, Any] | None = None,
        fii_dii: dict[str, Any] | None = None,
        max_skills: int = 2,
    ) -> list[dict[str, Any]]:
        """
        Evaluate current market state and return the top matched playbooks sorted by priority.
        """
        if not self._skills_cache:
            self.reload_skills()

        matched: list[dict[str, Any]] = []

        # 1. Evaluate context variables
        dte_val = None
        if signals and isinstance(signals, dict):
            dte_val = signals.get("dte")

        fo_context = ""
        if stage1_result and isinstance(stage1_result, dict):
            fo_context = (stage1_result.get("fo_expiry_context") or "").lower()

        # News text scan with defensive extraction
        news_text = ""
        if news_items:
            extracted_titles = []
            for it in news_items[:15]:
                if isinstance(it, dict):
                    extracted_titles.append(str(it.get("headline") or it.get("title") or ""))
                elif isinstance(it, str):
                    extracted_titles.append(it)
            news_text = " ".join(extracted_titles).lower()

        # Heavyweight divergence check (defensive)
        hw_divergence = False
        if heavyweights and isinstance(heavyweights, dict) and stage1_result and isinstance(stage1_result, dict):
            pred = str(stage1_result.get("prediction") or "").upper()
            bias = str(stage1_result.get("btst_bias") or "").upper()

            hdfc_entry = heavyweights.get("HDFCBANK") or {}
            rel_entry = heavyweights.get("RELIANCE") or {}

            hdfc_pct = _clean_numeric(hdfc_entry.get("change_pct")) if isinstance(hdfc_entry, dict) else 0.0
            rel_pct = _clean_numeric(rel_entry.get("change_pct")) if isinstance(rel_entry, dict) else 0.0

            if "UP" in pred or "BUY CE" in bias:
                if hdfc_pct <= -0.40 and rel_pct <= -0.40:
                    hw_divergence = True
            elif "DOWN" in pred or "BUY PE" in bias:
                if hdfc_pct >= 0.40 and rel_pct >= 0.40:
                    hw_divergence = True

        # FII/DII divergence check (defensive)
        inst_divergence = False
        if fii_dii and isinstance(fii_dii, dict):
            fii_val = fii_dii.get("fii_net_crores") if fii_dii.get("fii_net_crores") is not None else fii_dii.get("fii_net")
            dii_val = fii_dii.get("dii_net_crores") if fii_dii.get("dii_net_crores") is not None else fii_dii.get("dii_net")

            fii_f = _clean_numeric(fii_val)
            dii_f = _clean_numeric(dii_val)

            if (fii_f <= -1500.0 and dii_f >= 1500.0) or (fii_f >= 1500.0 and dii_f <= -1500.0):
                inst_divergence = True

        # 2. Match against registered skills
        for name, skill in self._skills_cache.items():
            triggers = skill.get("triggers", [])
            matched_trigger = False

            for tr in triggers:
                tr_lower = tr.lower()
                # Expiry trigger
                if tr_lower in ("dte_near_or_zero", "fo_expiry"):
                    if (dte_val is not None and dte_val <= 1) or ("expiry" in fo_context):
                        matched_trigger = True
                        break

                # RBI / Monetary policy trigger
                elif tr_lower in ("rbi_news_catalyst", "event_risk_high"):
                    rbi_terms = ["rbi", "mpc", "repo rate", "interest rate decision", "monetary policy", "das"]
                    is_high_risk = stage1_result and isinstance(stage1_result, dict) and stage1_result.get("event_risk") == "HIGH"
                    if any(term in news_text for term in rbi_terms) or is_high_risk:
                        matched_trigger = True
                        break

                # Heavyweight divergence trigger
                elif tr_lower in ("heavyweight_conflict", "reliance_hdfc_counter_trend"):
                    if hw_divergence:
                        matched_trigger = True
                        break

                # Institutional divergence trigger
                elif tr_lower in ("institutional_absorption", "fii_sell_dii_buy_extreme"):
                    if inst_divergence:
                        matched_trigger = True
                        break

            if matched_trigger:
                matched.append(skill)

        # Sort by priority descending
        matched.sort(key=lambda s: s.get("priority", 50), reverse=True)
        return matched[:max_skills]

    def format_skills_prompt(self, skills: list[dict[str, Any]]) -> str:
        """
        Format matched skills into a clear Markdown directive block for agent prompts.
        """
        if not skills:
            return ""

        parts = [
            "🎯 ACTIVE PROCEDURAL TRADING PLAYBOOKS (AgentSkills Standard):",
            "The following curated playbooks have been triggered by current market conditions. Strictly follow these directives:\n",
        ]

        for s in skills:
            name = s.get("name", "playbook")
            desc = s.get("description", "")
            body = s.get("body", "").strip()

            parts.append(f"### Playbook: {name}")
            if desc:
                parts.append(f"> Context: {desc}\n")
            parts.append(body)
            parts.append("")

        return "\n".join(parts).strip()


def get_skills_engine(skills_dir: str | None = None, history_dir: str | None = None) -> SkillsEngine:
    """Get or initialize the SkillsEngine singleton keyed by directories."""
    global _SKILLS_ENGINES
    s_key = os.path.abspath(skills_dir) if skills_dir else "default_skills"
    h_key = os.path.abspath(history_dir) if history_dir else "default_history"
    cache_key = f"{s_key}::{h_key}"

    with _ENGINE_LOCK:
        if cache_key not in _SKILLS_ENGINES:
            _SKILLS_ENGINES[cache_key] = SkillsEngine(skills_dir, history_dir)
        return _SKILLS_ENGINES[cache_key]
