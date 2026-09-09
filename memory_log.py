"""
memory_log.py — Backward-compatibility shim.

The implementation has been decomposed into the memory/ package.
"""

from memory import (  # noqa: F401
    TIMEZONE,
    GAP_UP_THRESHOLD,
    GAP_DOWN_THRESHOLD,
    _classify_gap,
    _next_trading_day,
    _fetch_nifty_actual_gap,
    build_reflect_fn_from_env,
    MemoryStorageMixin,
    MemoryResolutionMixin,
    MemoryContextMixin,
    NiftyMemoryLog,
    get_memory_log,
)

if __name__ == "__main__":
    import sys
    history_dir = sys.argv[1] if len(sys.argv) > 1 else None
    mem = get_memory_log(history_dir)
    print("Resolving pending memory log entries...")
    resolved = mem.resolve_pending_entries()
    print(f"Resolved {resolved} entries.")
    stats = mem.get_stats()
    print(f"Stats: {stats}")
