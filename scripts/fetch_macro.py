"""Fetch macro drivers: Brent/WTI crude, Henry Hub gas (EIA), global GDP growth
(World Bank), USD/INR (Frankfurter). Idempotent — safe to run daily.

EIA API v2 needs a free key (see CLAUDE.md) — set EIA_API_KEY in polymer-dashboard/.env.
World Bank and Frankfurter need no key.
"""
import datetime as dt
import os
import sys

import requests

from utils import load_env, upsert_csv

load_env()

EIA_API_KEY = os.environ.get("EIA_API_KEY")
TODAY = dt.date.today()
ONE_YEAR_AGO = TODAY - dt.timedelta(days=365)


def fetch_eia_series(path: str, series_id: str, start: dt.date) -> list[dict]:
    """Pull a daily EIA v2 series between start and today. Returns [{date, value}]."""
    url = f"https://api.eia.gov/v2/{path}/data/"
    params = {
        "api_key": EIA_API_KEY,
        "frequency": "daily",
        "data[0]": "value",
        "facets[series][]": series_id,
        "start": start.isoformat(),
        "end": TODAY.isoformat(),
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        "offset": 0,
        "length": 5000,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    rows = payload.get("response", {}).get("data", [])
    return [{"date": r["period"], "value": r["value"]} for r in rows if r.get("value") is not None]


def fetch_crude_and_gas():
    if not EIA_API_KEY:
        print("EIA_API_KEY not set yet — skipping crude/nat-gas fetch (see CLAUDE.md).", file=sys.stderr)
        return

    brent = fetch_eia_series("petroleum/pri/spt", "RBRTE", ONE_YEAR_AGO)
    wti = fetch_eia_series("petroleum/pri/spt", "RWTC", ONE_YEAR_AGO)
    brent_by_date = {r["date"]: r["value"] for r in brent}
    wti_by_date = {r["date"]: r["value"] for r in wti}
    all_dates = sorted(set(brent_by_date) | set(wti_by_date))
    rows = [
        {"date": d, "brent": brent_by_date.get(d, ""), "wti": wti_by_date.get(d, "")}
        for d in all_dates
    ]
    added = upsert_csv("crude_oil.csv", rows, key_cols=["date"])
    print(f"crude_oil.csv: upserted {added} rows")

    henry_hub = fetch_eia_series("natural-gas/pri/fut", "RNGWHHD", ONE_YEAR_AGO)
    rows = [{"date": r["date"], "henry_hub": r["value"]} for r in henry_hub]
    added = upsert_csv("natgas.csv", rows, key_cols=["date"])
    print(f"natgas.csv: upserted {added} rows (henry_hub)")


def fetch_gdp():
    url = "https://api.worldbank.org/v2/country/IND;WLD/indicator/NY.GDP.MKTP.KD.ZG"
    resp = requests.get(url, params={"format": "json", "per_page": 20}, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if len(payload) < 2 or not payload[1]:
        print("World Bank GDP: no data returned", file=sys.stderr)
        return
    rows = [
        {"year": r["date"], "country": r["country"]["value"], "growth_pct": r["value"]}
        for r in payload[1]
        if r.get("value") is not None
    ]
    added = upsert_csv("gdp.csv", rows, key_cols=["year", "country"])
    print(f"gdp.csv: upserted {added} rows")


def fetch_usdinr():
    start = ONE_YEAR_AGO.isoformat()
    end = TODAY.isoformat()
    url = f"https://api.frankfurter.dev/v1/{start}..{end}"
    resp = requests.get(url, params={"base": "USD", "symbols": "INR"}, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    rates = payload.get("rates", {})
    rows = [{"date": d, "rate": v.get("INR")} for d, v in rates.items() if v.get("INR") is not None]
    added = upsert_csv("usdinr.csv", rows, key_cols=["date"])
    print(f"usdinr.csv: upserted {added} rows")


if __name__ == "__main__":
    fetch_crude_and_gas()
    fetch_gdp()
    fetch_usdinr()
