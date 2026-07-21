"""Fetch and categorize polymer/petrochemical news for the morning digest.
Primary source: Google News RSS (reliable, tunable queries).
Secondary: PIB RSS (best-effort — PIB's RSS params are inconsistent/brittle; failures are non-fatal).
Writes data/news_digest.json, replaced fresh each run (news is a today-view, not a time series).
"""
import datetime as dt
import json
import sys
from urllib.parse import quote

import feedparser

from utils import DATA_DIR

GOOGLE_NEWS_BASE = "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"

CATEGORY_QUERIES = {
    "Price moves": [
        '("polypropylene" OR "polyethylene" OR "PVC" OR "PET resin") price India -stock -IPO -shares when:2d',
        'Reliance ("PP price" OR "PE price" OR "PVC price") when:3d',
    ],
    "Policy & Tariffs": [
        '(polymer OR plastics OR PVC) import duty India when:7d',
        'anti-dumping (PVC OR polymer) India when:14d',
        'DGFT plastics OR polymer when:14d',
    ],
    "Supply & Capacity / Geopolitical": [
        'petrochemical plant (shutdown OR turnaround OR outage) India when:7d',
        'naphtha cracker (outage OR shutdown) when:7d',
        '(Red Sea OR Hormuz) shipping disruption chemicals when:7d',
        'Reliance OR IOCL OR HMEL polymer capacity expansion when:30d',
    ],
    "Macro": [
        'crude oil price outlook when:2d',
        'USD INR forecast when:3d',
    ],
}

MAX_ITEMS_PER_CATEGORY = 6

# Google News surfaces a lot of generic "market research report" spam (IndexBox and
# similar syndication mills) alongside real news — filter titles containing these tells.
NOISE_MARKERS = [
    "market analysis", "market size", "market report", "market forecast",
    "market share", "market growth", "market trends", "market outlook",
    "cagr", "forecast period", "market research",
]


def is_noise(title: str) -> bool:
    lowered = title.lower()
    return any(marker in lowered for marker in NOISE_MARKERS)


def fetch_google_news(query: str) -> list[dict]:
    url = GOOGLE_NEWS_BASE.format(query=quote(query))
    feed = feedparser.parse(url)
    items = []
    for entry in feed.entries:
        items.append({
            "title": entry.get("title", "").strip(),
            "link": entry.get("link", ""),
            "published": entry.get("published", ""),
            "source": entry.get("source", {}).get("title", "Google News"),
        })
    return items


def build_digest() -> dict:
    digest = {"date": dt.date.today().isoformat(), "categories": {}}
    seen_links = set()

    for category, queries in CATEGORY_QUERIES.items():
        items = []
        for q in queries:
            try:
                for item in fetch_google_news(q):
                    if item["link"] in seen_links or is_noise(item["title"]):
                        continue
                    seen_links.add(item["link"])
                    items.append(item)
            except Exception as exc:
                print(f"news fetch failed for query {q!r}: {exc}", file=sys.stderr)
        digest["categories"][category] = items[:MAX_ITEMS_PER_CATEGORY]

    return digest


if __name__ == "__main__":
    digest = build_digest()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / "news_digest.json"
    out_path.write_text(json.dumps(digest, indent=2, ensure_ascii=False))
    total = sum(len(v) for v in digest["categories"].values())
    print(f"news_digest.json written: {total} items across {len(digest['categories'])} categories")
