"""
cognigraph.py — Backward-compatibility shim.

The implementation has been decomposed into the cognigraph/ package.
"""

from cognigraph import (  # noqa: F401
    DEFAULT_HALF_LIFE_DAYS,
    COGNIGRAPH_SCHEMA_VERSION,
    _safe_float,
    _days_between,
    _today_str,
    RegimeMixin,
    StorageMixin,
    ExtractionMixin,
    IngestionMixin,
    RetrievalMixin,
    CogniGraph,
    get_cognigraph,
    reset_cognigraph,
)
