"""Naphtha has no free numeric API anywhere (genuine ICIS/Platts paid product).
This script produces two ⚠️ ESTIMATES, never real market prints:

1. Primary: a crude-oil crack-spread proxy computed from Brent (data/crude_oil.csv).
   Naphtha has historically traded roughly Brent + $50-100/ton depending on the
   cycle; we use a fixed +$75/ton offset as a rough, clearly-labeled estimate.
2. Secondary cross-check: a single value lightly scraped from Trading Economics'
   naphtha page (OTC/CFD broker-derived reference, describes itself as tracking
   "a contract for difference that tracks the benchmark market" — not a verified
   spot price). Scraped as one number, low frequency, since TE sells bulk/API
   access separately and this HTML structure can change without notice.
"""
import datetime as dt
import re
import sys

import pandas as pd
import requests

from utils import DATA_DIR, upsert_csv

CRACK_SPREAD_USD_PER_TON = 75.0
BRENT_BBL_TO_TON = 7.33  # rough Brent barrels-per-tonne conversion, for the proxy only

TE_URL = "https://tradingeconomics.com/commodity/naphtha"
TE_PATTERN = re.compile(r"Naphtha (?:rose|fell) to ([\d.]+) USD/T on ([A-Za-z]+ \d{1,2}, \d{4})")


def compute_crack_spread_proxy():
    path = DATA_DIR / "crude_oil.csv"
    if not path.exists():
        print("crude_oil.csv not found yet — run fetch_macro.py first", file=sys.stderr)
        return
    df = pd.read_csv(path)
    df = df.dropna(subset=["brent"])
    rows = []
    for _, r in df.iterrows():
        brent_per_ton = float(r["brent"]) * BRENT_BBL_TO_TON
        rows.append({
            "date": r["date"],
            "naphtha_proxy_usd_per_ton": round(brent_per_ton + CRACK_SPREAD_USD_PER_TON, 2),
            "method": "brent_crack_spread_estimate",
        })
    added = upsert_csv("naphtha_estimate.csv", rows, key_cols=["date", "method"])
    print(f"naphtha_estimate.csv: upserted {added} proxy rows")


def fetch_te_cross_check():
    try:
        resp = requests.get(TE_URL, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}, timeout=30)
        resp.raise_for_status()
        match = TE_PATTERN.search(resp.text)
        if not match:
            print("Trading Economics naphtha cross-check: pattern not found (page may have changed).", file=sys.stderr)
            return
        price, date_str = match.groups()
        parsed_date = dt.datetime.strptime(date_str, "%B %d, %Y").date().isoformat()
        row = {
            "date": parsed_date,
            "naphtha_proxy_usd_per_ton": price,
            "method": "tradingeconomics_broker_reference",
        }
        added = upsert_csv("naphtha_estimate.csv", [row], key_cols=["date", "method"])
        print(f"naphtha_estimate.csv: upserted {added} TE cross-check row ({price} USD/T on {parsed_date})")
    except Exception as exc:
        print(f"Trading Economics naphtha cross-check failed (non-fatal): {exc}", file=sys.stderr)


if __name__ == "__main__":
    compute_crack_spread_proxy()
    fetch_te_cross_check()
