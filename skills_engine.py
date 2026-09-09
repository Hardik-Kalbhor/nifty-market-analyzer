# skills_engine.py — backward-compatibility shim
from skills import (  # noqa: F401
    _clean_numeric,
    _parse_frontmatter,
    SkillCurator,
    SkillsEngine,
    get_skills_engine,
)

__all__ = [
    "_clean_numeric",
    "_parse_frontmatter",
    "SkillCurator",
    "SkillsEngine",
    "get_skills_engine",
]
