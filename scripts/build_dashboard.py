"""Reads everything in data/ and renders dashboard/index.html — a single
self-contained HTML file (inline CSS/JS, no external requests) ready to be
published via the Artifact tool. Follows the dataviz skill: fixed categorical
palette, one axis per chart, legend for 2+ series, hover tooltips, light/dark
aware.
"""
import datetime as dt
import json
from pathlib import Path

import pandas as pd

from utils import DATA_DIR

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = ROOT / "dashboard"

POLYMER_FAMILIES = ["PP", "HDPE", "LDPE", "LLDPE", "PVC", "EVA"]
TRADE_POLYMERS = ["pp", "pe", "pvc", "pet"]


def read_csv_safe(name: str) -> pd.DataFrame:
    path = DATA_DIR / name
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def series_from_df(df: pd.DataFrame, date_col: str, value_col: str) -> list[dict]:
    if df.empty or value_col not in df.columns:
        return []
    sub = df[[date_col, value_col]].dropna()
    sub = sub.sort_values(date_col)
    return [{"x": str(r[date_col]), "y": float(r[value_col])} for _, r in sub.iterrows()]


def latest_and_delta(points: list[dict]) -> dict:
    if not points:
        return {"value": None, "delta": None, "date": None}
    latest = points[-1]
    prev = points[-2] if len(points) > 1 else None
    delta = (latest["y"] - prev["y"]) if prev else None
    return {"value": latest["y"], "delta": delta, "date": latest["x"]}


def build_macro_charts() -> dict:
    crude = read_csv_safe("crude_oil.csv")
    natgas = read_csv_safe("natgas.csv")
    usdinr = read_csv_safe("usdinr.csv")
    naphtha = read_csv_safe("naphtha_estimate.csv")

    charts = {}
    charts["Crude Oil (USD/bbl)"] = {
        "series": [
            {"name": "Brent", "points": series_from_df(crude, "date", "brent")},
            {"name": "WTI", "points": series_from_df(crude, "date", "wti")},
        ]
    }
    charts["Natural Gas — Henry Hub (USD/MMBtu)"] = {
        "series": [{"name": "Henry Hub", "points": series_from_df(natgas, "date", "henry_hub")}]
    }
    charts["USD/INR"] = {
        "series": [{"name": "USD/INR", "points": series_from_df(usdinr, "date", "rate")}]
    }
    naphtha_series = []
    if not naphtha.empty:
        for method, label in [
            ("brent_crack_spread_estimate", "Naphtha proxy (Brent + crack spread) — estimate"),
            ("tradingeconomics_broker_reference", "Naphtha (Trading Economics, broker ref.) — unverified"),
        ]:
            sub = naphtha[naphtha["method"] == method]
            naphtha_series.append({"name": label, "points": series_from_df(sub, "date", "naphtha_proxy_usd_per_ton")})
    charts["Naphtha (USD/tonne) — ⚠️ estimate, no real feed exists"] = {"series": naphtha_series}

    return charts


def build_kpis() -> list[dict]:
    crude = read_csv_safe("crude_oil.csv")
    natgas = read_csv_safe("natgas.csv")
    usdinr = read_csv_safe("usdinr.csv")
    prices = read_csv_safe("domestic_price_log.csv")

    kpis = []
    for label, df, col, unit in [
        ("Brent crude", crude, "brent", "$/bbl"),
        ("USD/INR", usdinr, "rate", ""),
        ("Henry Hub gas", natgas, "henry_hub", "$/MMBtu"),
    ]:
        pts = series_from_df(df, "date", col)
        ld = latest_and_delta(pts)
        kpis.append({"label": label, "unit": unit, **ld, "sparkline": pts[-14:]})

    if not prices.empty:
        om = prices[prices["price_type"] == "open_market"]
        for family in ["PP", "PVC"]:
            fam = om[(om["polymer_family"] == family) & (om["producer"] == "RIL")]
            fam = fam.sort_values("date")
            pts = [{"x": str(r["date"]), "y": float(r["price"])} for _, r in fam.iterrows()]
            ld = latest_and_delta(pts)
            kpis.append({
                "label": f"RIL {family} (open market)", "unit": "₹/kg", **ld,
                "sparkline": pts[-14:],
            })
    return kpis


def build_polymer_price_charts() -> dict:
    prices = read_csv_safe("domestic_price_log.csv")
    if prices.empty:
        return {}
    charts = {}
    for family in POLYMER_FAMILIES:
        fam_df = prices[prices["polymer_family"] == family]
        if fam_df.empty:
            continue
        series = []
        om_ril = fam_df[(fam_df["price_type"] == "open_market") & (fam_df["producer"] == "RIL")].sort_values("date")
        if not om_ril.empty:
            series.append({
                "name": "RIL — open market (Credco)",
                "points": [{"x": str(r["date"]), "y": float(r["price"])} for _, r in om_ril.iterrows()],
            })
        om_other = fam_df[(fam_df["price_type"] == "open_market") & (fam_df["producer"] != "RIL")]
        if not om_other.empty:
            agg = om_other.groupby("date")["price"].median().reset_index().sort_values("date")
            series.append({
                "name": "Other producers — open market (Credco)",
                "points": [{"x": str(r["date"]), "y": float(r["price"])} for _, r in agg.iterrows()],
            })
        direct = fam_df[fam_df["price_type"] == "producer_direct"].sort_values("date")
        for producer, grp in direct.groupby("producer"):
            series.append({
                "name": f"{producer} — producer-direct",
                "points": [{"x": str(r["date"]), "y": float(r["price"])} for _, r in grp.iterrows()],
            })
        if series:
            charts[family] = {"series": series}
    return charts


PLASTEMART_PRODUCERS = ["RIL", "IOCL", "HMEL", "OPAL"]


def build_plastemart_comparison() -> dict:
    """Per polymer family: the union of the 4 most recent producer-direct revision
    dates across all Plastemart producers combined (a common date column), with a
    blank cell for any producer that didn't revise on a given date — plus the
    latest open-market (Credco) price as a separately labeled reference point
    (never blended into the producer-direct grid, per the CLAUDE.md hard rule)."""
    prices = read_csv_safe("domestic_price_log.csv")
    if prices.empty:
        return {}
    pm = prices[(prices["price_type"] == "producer_direct") & (prices["source"] == "plastemart")]
    om = prices[prices["price_type"] == "open_market"]

    comparison = {}
    for family in POLYMER_FAMILIES:
        fam_pm = pm[pm["polymer_family"] == family]
        if fam_pm.empty:
            continue
        dates = sorted(fam_pm["date"].unique())[-4:]
        rows = {}
        for producer in PLASTEMART_PRODUCERS:
            by_date = fam_pm[fam_pm["producer"] == producer].set_index("date")["price"]
            rows[producer] = [
                round(float(by_date[d]), 2) if d in by_date.index else None
                for d in dates
            ]

        open_market_latest = None
        fam_om = om[om["polymer_family"] == family]
        if not fam_om.empty:
            ril_om = fam_om[fam_om["producer"] == "RIL"].sort_values("date")
            basis = ril_om if not ril_om.empty else fam_om.sort_values("date")
            latest_date = basis["date"].max()
            latest_rows = basis[basis["date"] == latest_date]
            open_market_latest = {
                "price": round(float(latest_rows["price"].median()), 2),
                "date": str(latest_date),
            }

        comparison[family] = {"dates": dates, "rows": rows, "open_market_latest": open_market_latest}
    return comparison


def build_plastemart_news() -> dict:
    path = DATA_DIR / "plastemart_news.json"
    if not path.exists():
        return {"date": None, "articles": []}
    return json.loads(path.read_text())


def build_trade_charts() -> dict:
    charts = {}
    for polymer in TRADE_POLYMERS:
        df = read_csv_safe(f"india_trade_{polymer}.csv")
        if df.empty:
            continue
        latest_period = df["period"].max()
        latest = df[df["period"] == latest_period]
        top = {}
        for flow in ["import", "export"]:
            sub = latest[latest["flow"] == flow].sort_values("value_usd", ascending=False).head(5)
            top[flow] = [
                {"name": r["partner_country"], "value": float(r["value_usd"])}
                for _, r in sub.iterrows()
            ]
        charts[polymer.upper()] = {"period": str(latest_period), "top": top}
    return charts


def build_capacity_table() -> list[dict]:
    df = read_csv_safe("capacity_reference.csv")
    if df.empty:
        return []
    df = df.sort_values(["polymer_family", "producer"])
    return df.to_dict(orient="records")


def build_news() -> dict:
    path = DATA_DIR / "news_digest.json"
    if not path.exists():
        return {"date": None, "categories": {}}
    return json.loads(path.read_text())


def freshness_stamps() -> dict:
    stamps = {}
    macro_dates = []
    for fname in ["crude_oil.csv", "natgas.csv", "usdinr.csv"]:
        df = read_csv_safe(fname)
        if not df.empty:
            macro_dates.append(str(df["date"].max()))
    stamps["Macro (crude/gas/FX)"] = min(macro_dates) if macro_dates else "no data yet"

    for label, fname, col in [
        ("Domestic open-market prices", "domestic_price_log.csv", "date"),
        ("India trade flows", "india_trade_pp.csv", "period"),
        ("News digest", None, None),
    ]:
        if fname:
            df = read_csv_safe(fname)
            stamps[label] = str(df[col].max()) if not df.empty else "no data yet"
        else:
            news = build_news()
            stamps[label] = news.get("date") or "no data yet"

    prices = read_csv_safe("domestic_price_log.csv")
    pm = prices[prices["source"] == "plastemart"] if not prices.empty and "source" in prices.columns else prices.iloc[0:0]
    stamps["Plastemart producer-direct prices"] = str(pm["date"].max()) if not pm.empty else "no data yet"
    stamps["Plastemart news"] = build_plastemart_news().get("date") or "no data yet"
    return stamps


def render_html(data: dict) -> str:
    template_path = ROOT / "scripts" / "dashboard_template.html"
    template = template_path.read_text()
    return template.replace("__DASHBOARD_DATA__", json.dumps(data))


def main():
    data = {
        "generated_at": dt.datetime.now().isoformat(timespec="minutes"),
        "kpis": build_kpis(),
        "macro_charts": build_macro_charts(),
        "polymer_price_charts": build_polymer_price_charts(),
        "plastemart_comparison": build_plastemart_comparison(),
        "trade_charts": build_trade_charts(),
        "capacity_table": build_capacity_table(),
        "news": build_news(),
        "plastemart_news": build_plastemart_news(),
        "freshness": freshness_stamps(),
    }
    html = render_html(data)
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    (DASHBOARD_DIR / "index.html").write_text(html)
    print(f"dashboard/index.html written ({len(html)} bytes)")


if __name__ == "__main__":
    main()
