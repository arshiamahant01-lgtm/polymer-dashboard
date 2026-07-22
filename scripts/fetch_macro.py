"""Fetch macro drivers: Brent/WTI crude, Henry Hub gas (EIA + Business Insider),
global GDP growth (World Bank), USD/INR (Frankfurter). Idempotent — safe to run daily.

EIA API v2 needs a free key (see CLAUDE.md) — set EIA_API_KEY in polymer-dashboard/.env.
EIA's own daily spot-price series reports with a real lag (observed 1-2+ weeks
behind, not just a reporting-day delay), so it's used for its ~1-year backfill
depth but is NOT the freshest source for recent days. Business Insider's markets
pages (no key, no auth) embed a same-day-updated ~3-week rolling OHLC table per
commodity as inline JSON (window.historicalPrices.configs — found via view-source,
same pattern as fetch_credco.py's JS-bundle discovery) and are fetched *after* EIA
so their fresher values win on any overlapping date. No naphtha equivalent exists
on Business Insider (checked; 404) — naphtha stays on the crude-crack-spread proxy
in fetch_naphtha_check.py, which re-derives from crude_oil.csv on every run, so it
gets fresher automatically once Brent here does.
World Bank and Frankfurter need no key.
"""
import datetime as dt
import json
import os
import sys

import requests

from utils import load_env, upsert_csv

load_env()

EIA_API_KEY = os.environ.get("EIA_API_KEY")
TODAY = dt.date.today()
ONE_YEAR_AGO = TODAY - dt.timedelta(days=365)

BI_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
BI_BRENT_URL = "https://markets.businessinsider.com/commodities/oil-price"
BI_WTI_URL = "https://markets.businessinsider.com/commodities/oil-price?type=wti"
BI_NATGAS_URL = "https://markets.businessinsider.com/commodities/natural-gas-price"


def fetch_bi_historical(url: str) -> list[dict]:
    """Scrape the embedded `window.historicalPrices.configs` JSON blob from a
    Business Insider Markets commodity page: ~3 weeks of daily OHLC, no key, no
    auth, updated same day. Returns [{date, value}] using the daily Close."""
    resp = requests.get(url, headers=BI_HEADERS, timeout=30)
    resp.raise_for_status()
    html = resp.text
    marker = "historicalPrices: {"
    start = html.find(marker)
    if start == -1:
        print(f"Business Insider: 'historicalPrices' blob not found at {url} (page may have changed)", file=sys.stderr)
        return []
    start = html.find("{", start)
    depth, i = 0, start
    while i < len(html):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    data = json.loads(html[start:i + 1])
    rows = []
    for r in data.get("model", []):
        close, raw_date = r.get("Close"), r.get("Date")
        if not close or not raw_date:
            continue
        date_iso = dt.datetime.strptime(raw_date, "%m/%d/%y").date().isoformat()
        rows.append({"date": date_iso, "value": close})
    return rows


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
        print("EIA_API_KEY not set yet — skipping EIA crude/nat-gas backfill (see CLAUDE.md).", file=sys.stderr)
    else:
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
        print(f"crude_oil.csv: upserted {added} rows from EIA")

        henry_hub = fetch_eia_series("natural-gas/pri/fut", "RNGWHHD", ONE_YEAR_AGO)
        rows = [{"date": r["date"], "henry_hub": r["value"]} for r in henry_hub]
        added = upsert_csv("natgas.csv", rows, key_cols=["date"])
        print(f"natgas.csv: upserted {added} rows from EIA (henry_hub)")

    # Business Insider: fresher (same-day) than EIA for recent dates. Runs after
    # EIA so its values win on any overlapping date via upsert_csv's keep="last".
    try:
        bi_brent = fetch_bi_historical(BI_BRENT_URL)
        bi_wti = fetch_bi_historical(BI_WTI_URL)
        brent_by_date = {r["date"]: r["value"] for r in bi_brent}
        wti_by_date = {r["date"]: r["value"] for r in bi_wti}
        all_dates = sorted(set(brent_by_date) | set(wti_by_date))
        rows = [
            {"date": d, "brent": brent_by_date.get(d, ""), "wti": wti_by_date.get(d, "")}
            for d in all_dates
        ]
        added = upsert_csv("crude_oil.csv", rows, key_cols=["date"])
        print(f"crude_oil.csv: upserted {added} rows from Business Insider")
    except Exception as exc:
        print(f"Business Insider crude fetch failed (non-fatal): {exc}", file=sys.stderr)

    try:
        bi_gas = fetch_bi_historical(BI_NATGAS_URL)
        rows = [{"date": r["date"], "henry_hub": r["value"]} for r in bi_gas]
        added = upsert_csv("natgas.csv", rows, key_cols=["date"])
        print(f"natgas.csv: upserted {added} rows from Business Insider (henry_hub)")
    except Exception as exc:
        print(f"Business Insider nat-gas fetch failed (non-fatal): {exc}", file=sys.stderr)


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
