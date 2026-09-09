"""
dreaming_engine.py — Backward-compatibility shim.

The implementation has been decomposed into the dreaming/ package.
"""

from dreaming import (  # noqa: F401
    TIMEZONE,
    _clean_float,
    _now_ist_str,
    HarvestMixin,
    ExitAuditMixin,
    AxiomStorageMixin,
    AxiomSynthesisMixin,
    ConsolidationMixin,
    ConsolidationCycleMixin,
    DreamingEngine,
    get_dreaming_engine,
)
