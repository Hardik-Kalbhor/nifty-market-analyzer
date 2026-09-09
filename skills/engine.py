"""
skills/engine.py — SkillsEngine discovery, trigger matching, and singleton access.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

from .parser import _clean_numeric, _parse_frontmatter
from .curator import SkillCurator

logger = logging.getLogger(__name__)


class SkillsEngine:
    """Discovers, evaluates, and matches procedural trading playbooks."""

    def __init__(self, skills_dir: str | None = None, history_dir: str | None = None):
        if skills_dir is None:
            self._skills_dir = Path(__file__).parent
        else:
            self._skills_dir = Path(skills_dir)

        if history_dir is None:
            self._history_dir = Path(__file__).parent.parent / "history"
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


# Global singleton cache keyed by (skills_dir, history_dir)
_SKILLS_ENGINES: dict[str, SkillsEngine] = {}
_ENGINE_LOCK = threading.Lock()


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
