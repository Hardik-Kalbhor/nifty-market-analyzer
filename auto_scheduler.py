import os
import json
import logging
from datetime import datetime
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from scraper import scrape_all_news
from fii_dii_scraper import fetch_fii_dii_data
from market_signals_scraper import fetch_all_market_signals
from llm_analyzer import analyze_with_ai_agents
from analyzer import analyze_news
from intraday_analyzer import generate_intraday_prediction

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AutoScheduler")

TIMEZONE = pytz.timezone("Asia/Kolkata")
try:
    HISTORY_DIR = os.path.join(os.path.dirname(__file__), "history")
    os.makedirs(HISTORY_DIR, exist_ok=True)
except (OSError, PermissionError):
    HISTORY_DIR = "/tmp/history"
    os.makedirs(HISTORY_DIR, exist_ok=True)


def run_automated_analysis(run_name: str = "Scheduled Run"):
    """
    Executes the full automated analysis pipeline and saves timestamped report history.
    """
    now_ist = datetime.now(TIMEZONE)
    timestamp_str = now_ist.strftime("%Y-%m-%d_%H%M")
    logger.info(f"🚀 Running Automated Schedule [{run_name}] at {now_ist.strftime('%Y-%m-%d %H:%M:%S IST')}")

    try:
        # Phase 1: Scrape news
        news_items = scrape_all_news()

        # Phase 2: Microstructure signals & FII/DII
        fii_dii_data = fetch_fii_dii_data()
        market_signals = fetch_all_market_signals()

        # Phase 3: AI Agent / Rule Engine Analysis
        ai_result = analyze_with_ai_agents(news_items, market_signals)

        if ai_result:
            result = analyze_news(
                news_items=news_items,
                gift_nifty_change_pct=market_signals.get("gift_nifty_change_pct"),
                india_vix=market_signals.get("india_vix"),
                india_vix_change_pct=market_signals.get("india_vix_change_pct"),
                pcr=market_signals.get("pcr"),
                global_market_changes=market_signals.get("global_market_changes"),
            )
            result["prediction"] = ai_result.get("prediction", result["prediction"])
            result["confidence"] = ai_result.get("confidence", result["confidence"])
            result["btst_bias"] = ai_result.get("btst_bias", result["btst_bias"])
            result["news_sentiment"] = ai_result.get("news_sentiment", result["news_sentiment"])
            result["ai_agent_provider"] = ai_result.get("ai_agent_provider")
            result["ai_reasoning"] = ai_result.get("reasoning")
            if ai_result.get("bullish_factors"):
                result["bullish_factors"] = ai_result["bullish_factors"]
            if ai_result.get("bearish_factors"):
                result["bearish_factors"] = ai_result["bearish_factors"]
        else:
            result = analyze_news(
                news_items=news_items,
                gift_nifty_change_pct=market_signals.get("gift_nifty_change_pct"),
                india_vix=market_signals.get("india_vix"),
                india_vix_change_pct=market_signals.get("india_vix_change_pct"),
                pcr=market_signals.get("pcr"),
                global_market_changes=market_signals.get("global_market_changes"),
            )

        # Phase 4: Intraday Prediction
        intraday = generate_intraday_prediction(
            news_sentiment=result.get("news_sentiment", "NEUTRAL"),
            gap_prediction=result.get("prediction", "FLAT"),
            event_risk=result.get("event_risk", "LOW"),
            scores=result.get("scores", {"confidence": result.get("confidence", 50)}),
            bullish_factors=result.get("bullish_factors", []),
            bearish_factors=result.get("bearish_factors", []),
            sector_summary=result.get("sector_summary", {}),
        )

        result["intraday"] = intraday
        result["fii_dii"] = fii_dii_data
        result["market_signals_detail"] = market_signals
        result["run_metadata"] = {
            "run_name": run_name,
            "executed_at_ist": now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
        }

        # Save to history/ directory
        filepath = os.path.join(HISTORY_DIR, f"analysis_{timestamp_str}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        latest_filepath = os.path.join(HISTORY_DIR, "latest.json")
        with open(latest_filepath, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        conf = result.get("confidence", result.get("scores", {}).get("confidence", 50))
        logger.info(f"✅ Automated Run [{run_name}] Completed! Prediction: {result['prediction']} ({conf}%). History saved to {filepath}")
        return result

    except Exception as e:
        logger.error(f"❌ Automated Run [{run_name}] failed: {e}")
        return None


def init_scheduler():
    """
    Schedules 5 daily runs for Mon-Fri trading days in Asia/Kolkata (IST) timezone:
    1. 08:30 IST - Pre-Market & Overnight Gap Check (BTST)
    2. 09:45 IST - Post-Open Range Settlement & ORB Intraday Bias
    3. 13:30 IST - European Market Opening & Afternoon Reversal Check
    4. 15:15 IST - Pre-Close BTST Selection Entry Check
    5. 17:30 IST - Post-Market FII/DII Official Inflow Audit
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

    scheduler.start()
    logger.info("📅 AutoScheduler started! 5 Daily Trading Runs scheduled (Mon-Fri at 08:30, 09:45, 13:30, 15:15, 17:30 IST).")
    return scheduler


if __name__ == "__main__":
    import time
    logger.info("Starting AutoScheduler daemon in standalone test mode...")
    sched = init_scheduler()
    print("\n--- Scheduled Jobs ---")
    for job in sched.get_jobs():
        print(f"• [{job.id}] {job.name} -> Next run: {job.next_run_time}")
    print("\nExecuting immediate test run...")
    run_automated_analysis("Standalone Manual Test Run")
