"""
server.py — Backward-compatibility shim and server runner.

The Flask application and routes have been modularized into the routes/ package.
"""

import os
import logging
from routes import app, get_history_dir
from scraper import scrape_all_news
from fii_dii_scraper import fetch_fii_dii_data
from market_signals_scraper import fetch_all_market_signals

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)
