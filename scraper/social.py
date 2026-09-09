"""
scraper/social.py — Social media sentiment fetchers (Reddit & Telegram).
"""

import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime

from .models import NewsItem
from .constants import HEADERS, SPAM_PROMO_REGEX
from .classifiers import _classify_sector, _clean_html, _is_personal_finance_noise

logger = logging.getLogger(__name__)

def fetch_reddit_posts(subreddit: str, min_score: int = 5, limit: int = 20) -> list[NewsItem]:
    """
    Fetch trending retail discussions from Reddit without API keys via public JSON endpoint.
    Filters by minimum score, removes noise and personal finance advice.
    """
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"
    items: list[NewsItem] = []
    reddit_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 NiftySwarm/2.0",
        "Accept": "application/json",
    }
    try:
        resp = requests.get(url, headers=reddit_headers, timeout=5)
        if resp.status_code != 200:
            logger.debug(f"Reddit r/{subreddit} returned HTTP {resp.status_code}")
            return []

        data = resp.json()
        if not isinstance(data, dict):
            return []
        data_block = data.get("data")
        if not isinstance(data_block, dict):
            return []
        children = data_block.get("children")
        if not isinstance(children, list):
            return []

        for child in children:
            if not isinstance(child, dict):
                continue
            post = child.get("data")
            if not isinstance(post, dict):
                continue
            if post.get("stickied") or post.get("over_18"):
                continue

            raw_score = post.get("score")
            try:
                score = int(raw_score) if raw_score is not None else 0
            except (ValueError, TypeError):
                score = 0

            if score < min_score:
                continue

            title = _clean_html(str(post.get("title") or ""))
            selftext = _clean_html(str(post.get("selftext") or ""))
            combined = f"{title} {selftext}".strip()

            if not combined or _is_personal_finance_noise(combined):
                continue

            # Format timestamp
            created_utc = post.get("created_utc")
            pub_date = datetime.now().strftime("%d %b %Y, %I:%M %p")
            if created_utc is not None:
                try:
                    dt = datetime.fromtimestamp(float(created_utc), tz=timezone.utc)
                    pub_date = dt.strftime("%d %b %Y, %I:%M %p")
                except Exception:
                    pass

            permalink = str(post.get("permalink") or "")
            full_link = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else permalink

            snippet = selftext[:300] if selftext else f"Reddit community discussion on r/{subreddit} with {score} upvotes."

            items.append(
                NewsItem(
                    headline=title,
                    source=f"Reddit (r/{subreddit})",
                    published_date=pub_date,
                    link=full_link,
                    snippet=snippet,
                    sector=_classify_sector(combined),
                    category="social_sentiment",
                )
            )
    except Exception as e:
        logger.debug(f"Error fetching Reddit r/{subreddit}: {e}")

    return items


def fetch_telegram_channel(channel_username: str, limit: int = 15) -> list[NewsItem]:
    """
    Scrape public Telegram channel web preview (https://t.me/s/{channel})
    without MTProto/API keys or login requirements.
    Filters out promotional spam, tips services, and personal finance noise.
    """
    channel_clean = channel_username.lstrip("@").strip()
    url = f"https://t.me/s/{channel_clean}"
    items: list[NewsItem] = []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=5)
        if resp.status_code != 200:
            logger.debug(f"Telegram @{channel_clean} returned HTTP {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.content, "html.parser")
        message_wraps = soup.select("div.tgme_widget_message_wrap")

        # Process messages from newest to oldest up to limit
        for wrap in reversed(message_wraps[-limit:]):
            text_el = wrap.select_one("div.tgme_widget_message_text")
            if not text_el:
                continue

            raw_text = _clean_html(str(text_el))
            if not raw_text or len(raw_text) < 20:
                continue

            # Anti-spam filter: eliminate VIP channel promos, WhatsApp numbers, tips services
            if SPAM_PROMO_REGEX.search(raw_text) or _is_personal_finance_noise(raw_text):
                continue

            # Extract message date & link
            date_anchor = wrap.select_one("a.tgme_widget_message_date")
            link = date_anchor.get("href", f"https://t.me/s/{channel_clean}") if date_anchor else f"https://t.me/s/{channel_clean}"

            time_el = wrap.select_one("time")
            pub_date = ""
            if time_el and time_el.get("datetime"):
                try:
                    dt = datetime.fromisoformat(time_el["datetime"].replace("Z", "+00:00"))
                    pub_date = dt.strftime("%d %b %Y, %I:%M %p")
                except Exception:
                    pub_date = datetime.now().strftime("%d %b %Y, %I:%M %p")
            else:
                pub_date = datetime.now().strftime("%d %b %Y, %I:%M %p")

            # Break into headline and snippet
            lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
            first_line = lines[0] if lines else raw_text
            if len(first_line) > 100:
                headline = first_line[:97] + "..."
            else:
                headline = first_line

            snippet = raw_text[:300]

            category = "breaking_flash" if any(kw in channel_clean.lower() for kw in ("cnbc", "moneycontrol", "news")) else "social_sentiment"

            items.append(
                NewsItem(
                    headline=headline,
                    source=f"Telegram (@{channel_clean})",
                    published_date=pub_date,
                    link=link,
                    snippet=snippet,
                    sector=_classify_sector(raw_text),
                    category=category,
                )
            )
    except Exception as e:
        logger.debug(f"Error fetching Telegram channel @{channel_clean}: {e}")

    return items


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Deduplication
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


