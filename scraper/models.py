"""
scraper/models.py — Data models for scraped news items.
"""

from dataclasses import dataclass, asdict


@dataclass
class NewsItem:
    """Represents a single scraped news article."""
    headline: str
    source: str
    published_date: str
    link: str
    snippet: str = ""
    sector: str = "General"
    category: str = "general"  # macro, india, commodity, corporate, event

    def to_dict(self) -> dict:
        return asdict(self)
