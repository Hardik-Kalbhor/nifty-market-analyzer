"""
fii_dii_scraper.py — Institutional Flow (FII/DII) Cash Market Scraper.
Fetches daily FII and DII net cash buy/sell figures (in ₹ Crores) for Indian markets.
Primary source: NSE India official API.
Fallback source: Moneycontrol Market Stats.
"""

import logging
import requests
from bs4 import BeautifulSoup
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def _fetch_from_nse() -> dict[str, Any] | None:
    """Fetch FII/DII data directly from NSE India API."""
    try:
        session = requests.Session()
        # Handshake to acquire session cookies
        session.get("https://www.nseindia.com", headers=HEADERS, timeout=5)
        response = session.get(
            "https://www.nseindia.com/api/fiidiiTradeReact",
            headers=HEADERS,
            timeout=5,
        )

        if response.status_code == 200:
            data = response.json()
            fii_info = {}
            dii_info = {}
            date_str = ""

            for row in data:
                cat = row.get("category", "")
                if "FII" in cat or "FPI" in cat:
                    fii_info = {
                        "buy": float(row.get("buyValue", 0)),
                        "sell": float(row.get("sellValue", 0)),
                        "net": float(row.get("netValue", 0)),
                    }
                    date_str = row.get("date", "")
                elif "DII" in cat:
                    dii_info = {
                        "buy": float(row.get("buyValue", 0)),
                        "sell": float(row.get("sellValue", 0)),
                        "net": float(row.get("netValue", 0)),
                    }

            if fii_info or dii_info:
                fii_net = fii_info.get("net", 0.0)
                dii_net = dii_info.get("net", 0.0)
                total_net = fii_net + dii_net

                if total_net > 500:
                    sentiment = "STRONG BULLISH"
                elif total_net > 0:
                    sentiment = "BULLISH"
                elif total_net < -500:
                    sentiment = "STRONG BEARISH"
                else:
                    sentiment = "BEARISH"

                logger.info(f"Successfully scraped FII/DII data from NSE India for date: {date_str}")
                return {
                    "source": "NSE India",
                    "date": date_str,
                    "fii": fii_info,
                    "dii": dii_info,
                    "fii_net_crores": fii_net,
                    "dii_net_crores": dii_net,
                    "total_net_crores": round(total_net, 2),
                    "institutional_sentiment": sentiment,
                }
    except Exception as e:
        logger.warning(f"Failed to fetch FII/DII from NSE India: {e}")

    return None


def _fetch_from_moneycontrol() -> dict[str, Any] | None:
    """Fallback: Scrape FII/DII data from Moneycontrol."""
    url = "https://www.moneycontrol.com/stocks/marketstats/fii_dii_activity/index.php"
    try:
        response = requests.get(url, headers=HEADERS, timeout=6)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            # Parse table containing FII/DII daily stats
            tables = soup.find_all("table")
            for table in tables:
                text = table.get_text()
                if "FII" in text and "DII" in text:
                    rows = table.find_all("tr")
                    fii_net = 0.0
                    dii_net = 0.0
                    date_str = ""

                    for row in rows:
                        cols = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                        if len(cols) >= 4:
                            col_text = " ".join(cols).lower()
                            if "fii" in col_text or "fpi" in col_text:
                                try:
                                    fii_net = float(cols[-1].replace(",", "").replace("₹", ""))
                                except ValueError:
                                    pass
                            elif "dii" in col_text:
                                try:
                                    dii_net = float(cols[-1].replace(",", "").replace("₹", ""))
                                except ValueError:
                                    pass

                    total_net = fii_net + dii_net
                    sentiment = "BULLISH" if total_net > 0 else "BEARISH"

                    logger.info("Successfully scraped FII/DII data from Moneycontrol")
                    return {
                        "source": "Moneycontrol",
                        "date": date_str or "Latest",
                        "fii_net_crores": fii_net,
                        "dii_net_crores": dii_net,
                        "total_net_crores": round(total_net, 2),
                        "institutional_sentiment": sentiment,
                    }
    except Exception as e:
        logger.warning(f"Failed to fetch FII/DII from Moneycontrol: {e}")

    return None


def fetch_fii_dii_data() -> dict[str, Any]:
    """
    Public master function to fetch FII/DII cash market flow data.
    Tries NSE India API first, falls back to Moneycontrol or neutral values.
    """
    logger.info("Fetching FII/DII cash market institutional flow data...")
    result = _fetch_from_nse()
    if result:
        return result

    result = _fetch_from_moneycontrol()
    if result:
        return result

    # Fallback default if both requests fail/timeout
    logger.warning("Using fallback neutral values for FII/DII data.")
    return {
        "source": "Fallback (Neutral)",
        "date": "N/A",
        "fii_net_crores": 0.0,
        "dii_net_crores": 0.0,
        "total_net_crores": 0.0,
        "institutional_sentiment": "NEUTRAL",
    }


if __name__ == "__main__":
    import json
    data = fetch_fii_dii_data()
    print(json.dumps(data, indent=2))
