"""Fetch plastics-industry news from plastemart.com's news listing page.

Plastemart's RSS feeds are dead (all stale since 2017 — verified), so this scrapes
the listing page's HTML directly, which is actively updated (confirmed articles
dated within the current month at time of writing).

Written to its own file, data/plastemart_news.json — kept separate from
news_digest.json's 4-category Google News/PIB digest by design (own tab on the
dashboard, not merged categorization).
"""
import datetime as dt
import html
import json
import re
import sys

import requests

from utils import DATA_DIR

URL = "https://www.plastemart.com/plastics-industry-news-developments"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
ARTICLE_RE = re.compile(
    r'class="news-listing">\s*<a href="([^"]+)">\s*<h1>([^<]+)</h1>.*?<span>([^<]+)</span>',
    re.DOTALL,
)
MAX_ARTICLES = 10


def parse_date(raw: str) -> str:
    """'21-Jul-26' -> '2026-07-21'"""
    return dt.datetime.strptime(raw.strip(), "%d-%b-%y").date().isoformat()


def run():
    resp = requests.get(URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    articles = []
    for link, title, raw_date in ARTICLE_RE.findall(resp.text):
        try:
            published = parse_date(raw_date)
        except ValueError:
            continue
        articles.append({
            "title": html.unescape(title.strip()),
            "link": "https://www.plastemart.com" + link,
            "published": published,
        })

    articles.sort(key=lambda a: a["published"], reverse=True)
    articles = articles[:MAX_ARTICLES]

    digest = {"date": dt.date.today().isoformat(), "articles": articles}
    (DATA_DIR / "plastemart_news.json").write_text(json.dumps(digest, indent=2, ensure_ascii=False))
    print(f"plastemart_news.json: wrote {len(articles)} articles")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"fetch_plastemart_news failed: {exc}", file=sys.stderr)
        sys.exit(1)
