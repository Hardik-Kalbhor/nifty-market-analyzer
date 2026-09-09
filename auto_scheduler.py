# auto_scheduler.py — backward-compatibility shim
from scheduler import (  # noqa: F401
    TIMEZONE,
    HISTORY_DIR,
    _cleanup_old_history,
    gather_scheduled_inputs,
    run_automated_analysis,
    run_dreaming_consolidation,
    init_scheduler,
)

__all__ = [
    "TIMEZONE",
    "HISTORY_DIR",
    "_cleanup_old_history",
    "gather_scheduled_inputs",
    "run_automated_analysis",
    "run_dreaming_consolidation",
    "init_scheduler",
]

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger("AutoScheduler")
    logger.info("Starting AutoScheduler daemon in standalone test mode...")
    sched = init_scheduler()
    print("\n--- Scheduled Jobs ---")
    for job in sched.get_jobs():
        print(f"• [{job.id}] {job.name} -> Next run: {job.next_run_time}")
    print("\nExecuting immediate test run...")
    run_automated_analysis("Standalone Manual Test Run")
