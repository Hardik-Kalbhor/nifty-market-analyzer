"""
scheduler/runner.py — BackgroundScheduler lifecycle and job scheduling.
"""

from __future__ import annotations

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .constants import TIMEZONE
from .pipeline import run_automated_analysis
from .dreaming_task import run_dreaming_consolidation

logger = logging.getLogger("AutoScheduler")


def init_scheduler() -> BackgroundScheduler:
    """
    Schedules 6 daily runs for Mon-Fri trading days in Asia/Kolkata (IST) timezone:
    1. 08:30 IST - Pre-Market & Overnight Gap Check (BTST)
    2. 09:45 IST - Post-Open Range Settlement & ORB Intraday Bias
    3. 13:30 IST - European Market Opening & Afternoon Reversal Check
    4. 15:15 IST - Pre-Close BTST Selection Entry Check
    5. 17:30 IST - Post-Market FII/DII Official Inflow Audit
    6. 20:00 IST - Hermes Post-Market Autonomous Dreaming Memory Consolidation
    """
    scheduler = BackgroundScheduler(timezone=TIMEZONE)

    # 1. 08:30 IST (Mon-Fri)
    scheduler.add_job(
        run_automated_analysis,
        trigger=CronTrigger(day_of_week="mon-fri", hour=8, minute=30, timezone=TIMEZONE),
        args=["1. Pre-Market & Overnight Gap (08:30 IST)"],
        id="run_0830_premarket",
        replace_existing=True,
    )

    # 2. 09:45 IST (Mon-Fri)
    scheduler.add_job(
        run_automated_analysis,
        trigger=CronTrigger(day_of_week="mon-fri", hour=9, minute=45, timezone=TIMEZONE),
        args=["2. Post-Open Range & Intraday Structure (09:45 IST)"],
        id="run_0945_intraday",
        replace_existing=True,
    )

    # 3. 13:30 IST (Mon-Fri)
    scheduler.add_job(
        run_automated_analysis,
        trigger=CronTrigger(day_of_week="mon-fri", hour=13, minute=30, timezone=TIMEZONE),
        args=["3. European Open & Afternoon Shift (13:30 IST)"],
        id="run_1330_afternoon",
        replace_existing=True,
    )

    # 4. 15:15 IST (Mon-Fri)
    scheduler.add_job(
        run_automated_analysis,
        trigger=CronTrigger(day_of_week="mon-fri", hour=15, minute=15, timezone=TIMEZONE),
        args=["4. Pre-Close BTST Selection Window (15:15 IST)"],
        id="run_1515_btst",
        replace_existing=True,
    )

    # 5. 17:30 IST (Mon-Fri)
    scheduler.add_job(
        run_automated_analysis,
        trigger=CronTrigger(day_of_week="mon-fri", hour=17, minute=30, timezone=TIMEZONE),
        args=["5. Post-Market FII/DII Official Flow Audit (17:30 IST)"],
        id="run_1730_postmarket",
        replace_existing=True,
    )

    # 6. 20:00 IST (Mon-Fri) - Hermes Post-Market Autonomous Dreaming Memory Consolidation
    scheduler.add_job(
        run_dreaming_consolidation,
        trigger=CronTrigger(day_of_week="mon-fri", hour=20, minute=0, timezone=TIMEZONE),
        id="run_2000_dreaming",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("📅 AutoScheduler started! 6 Daily Trading Runs scheduled (Mon-Fri: 08:30, 09:45, 13:30, 15:15, 17:30, 20:00 Dreaming IST).")
    return scheduler
