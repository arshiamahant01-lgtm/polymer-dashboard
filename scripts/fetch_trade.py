"""Fetch India polymer import/export trade flows from UN Comtrade's free public
preview API (no key needed, but ANNUAL only and lags — India's own Comtrade
reporting is typically 1-2 years behind; treat as structural/annual context,
never a fresh daily signal). See CLAUDE.md / PLAN.md for the TRADESTAT caveat
(better freshness but no stable free API found — manual cross-check for now).

HS codes used: 3901=PE, 3902=PP, 3904=PVC, 390761=PET.
"""
import datetime as dt
import sys
import time

import requests

from utils import upsert_csv

INDIA_REPORTER_CODE = 699
HS_CODES = {"PE": "3901", "PP": "3902", "PVC": "3904", "PET": "390761"}
FLOWS = {"M": "import", "X": "export"}
YEARS_TO_FETCH = [dt.date.today().year - 2, dt.date.today().year - 1]

PARTNER_REF_URL = "https://comtradeapi.un.org/files/v1/app/reference/partnerAreas.json"
PREVIEW_URL = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"


def load_partner_names() -> dict[int, str]:
    resp = requests.get(PARTNER_REF_URL, timeout=30)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    return {r["PartnerCode"]: r["PartnerDesc"] for r in results}


def fetch_year(hs_code: str, year: int, flow: str, retries: int = 4) -> list[dict]:
    params = {
        "reporterCode": INDIA_REPORTER_CODE,
        "period": year,
        "cmdCode": hs_code,
        "flowCode": flow,
    }
    for attempt in range(retries):
        resp = requests.get(PREVIEW_URL, params=params, timeout=60)
        if resp.status_code == 429:
            time.sleep(3 * (attempt + 1))
            continue
        resp.raise_for_status()
        return resp.json().get("data", [])
    resp.raise_for_status()
    return []


def run():
    partner_names = load_partner_names()

    for polymer, hs_code in HS_CODES.items():
        rows = []
        for year in YEARS_TO_FETCH:
            for flow_code, flow_label in FLOWS.items():
                try:
                    data = fetch_year(hs_code, year, flow_code)
                except Exception as exc:
                    print(f"Comtrade fetch failed for {polymer} {year} {flow_code}: {exc}", file=sys.stderr)
                    continue
                for r in data:
                    if not r.get("isAggregate", True) and r.get("partnerCode") == 0:
                        continue  # skip world-aggregate rows, we want per-partner
                    partner_code = r.get("partnerCode")
                    if partner_code == 0:
                        continue
                    rows.append({
                        "period": str(year),
                        "partner_country": partner_names.get(partner_code, f"code:{partner_code}"),
                        "flow": flow_label,
                        "qty_kg": r.get("netWgt"),
                        "value_usd": r.get("primaryValue") or r.get("cifvalue") or r.get("fobvalue"),
                    })
                time.sleep(1.5)

        added = upsert_csv(
            f"india_trade_{polymer.lower()}.csv", rows,
            key_cols=["period", "partner_country", "flow"],
        )
        print(f"india_trade_{polymer.lower()}.csv: upserted {added} rows")


if __name__ == "__main__":
    run()
