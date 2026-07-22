"""Fetch Credco's OPEN-MARKET polymer prices (credcosourcing.com).

IMPORTANT: these are open-market/trader-resale prices, not producer-direct/contract
prices. Always tagged price_type="open_market" and must never be blended with
producer-direct entries in domestic_price_log.csv (see CLAUDE.md).

Credco's own site only exposes a short rolling window of history (no free way to
backfill a full year) — we save a raw daily snapshot (data/credco_raw/<date>.json)
and an aggregated per-family/per-producer median into domestic_price_log.csv, and
build real history ourselves day by day going forward.
"""
import datetime as dt
import json
import re
import statistics as stats
import sys

import requests

from utils import DATA_DIR, upsert_csv

API_URL = "https://api.credcosourcing.com/api/products"
TODAY = dt.date.today().isoformat()

KNOWN_PRODUCERS = {
    "RIL", "HMEL", "IOCL", "HALDIA", "GAIL", "OPAL", "BOROUGE", "BCPL", "SABIC",
    "HANWHA", "EXXON", "DOW", "BASELL", "LG", "FORMOSA", "SUMITOMO", "TOTAL",
    "TITAN", "MRPL", "SCG", "SIPCHEM", "LOTTE",
}

FAMILY_MAP = {
    "HD": "HDPE", "LD": "LDPE", "LL": "LLDPE", "PP": "PP", "PVC": "PVC", "EVA": "EVA",
}


def parse_family(category_full_name: str) -> str:
    prefix = category_full_name.split(" - ")[0].strip()
    return FAMILY_MAP.get(prefix, prefix)


def parse_producer(product_name: str) -> str:
    last_token = product_name.strip().split()[-1].upper()
    return last_token if last_token in KNOWN_PRODUCERS else "OTHER"


def fetch_products() -> list[dict]:
    resp = requests.get(API_URL, headers={"Accept": "application/json"}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def to_float(v) -> float | None:
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def run():
    products = fetch_products()

    raw_dir = DATA_DIR / "credco_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{TODAY}.json").write_text(json.dumps(products, indent=2))

    groups: dict[tuple, list[float]] = {}
    for p in products:
        price = to_float(p.get("current_price"))
        if price is None:
            continue
        family = parse_family(p.get("category_full_name", ""))
        producer = parse_producer(p.get("product_name", ""))
        groups.setdefault((family, producer), []).append(price)

    rows = []
    for (family, producer), prices in groups.items():
        rows.append({
            "date": TODAY,
            "polymer_family": family,
            "producer": producer,
            "price": round(stats.median(prices), 2),
            "grade_count": len(prices),
            "price_type": "open_market",
            "source": "credco",
        })

    added = upsert_csv("domestic_price_log.csv", rows, key_cols=["date", "polymer_family", "producer", "price_type", "source"])
    print(f"domestic_price_log.csv: upserted {added} open-market rows from {len(products)} Credco grades")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"fetch_credco failed: {exc}", file=sys.stderr)
        sys.exit(1)
