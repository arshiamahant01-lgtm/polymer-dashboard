# Polymer Market Tracking Dashboard (India-focused, free-tier)

## Context
The user distributes Reliance-made PP, PE, PVC, and PET in India and wants a single place to track the demand/supply and pricing drivers behind those markets, with India import/export detail, a morning news digest, and (eventually) a price-prediction capability. Constraint: free data sources only — no paid subscriptions (confirmed: no S&P Global access despite the connector appearing in-account). Two research passes verified which of the sources the user listed (ICIS, S&P Global, Argus, Comtrade, etc.) actually have usable free tiers, and found free substitutes/government sources where the originals are paywalled.

Locked-in decisions from earlier clarification:
- **Delivery**: hosted web dashboard (Claude Artifact), not a spreadsheet.
- **Refresh**: automated every morning via a scheduled cloud routine (not manual, not session-only cron — session cron jobs expire in 7 days and vanish when this session ends, which is wrong for a standing dashboard).
- **Trade granularity**: aggregate India import/export flows by country/HS-code, not shipment/buyer-level (buyer-level customs data is a paid product from resellers like Zauba/Seair/Volza — out of scope for v1, noted as a future paid add-on).
- **API/MCP question**: no custom MCP server needed for v1. Plain Python fetch scripts run directly (via Bash) inside the scheduled routine are simpler, sufficient, and easier to debug than standing up MCP infrastructure. Revisit MCP only if this data ever needs to be queried live from a *different* Claude surface (e.g. claude.ai chat without file/shell access).

## Verified free data sources

| Variable | Source | Access | Freshness / gotcha |
|---|---|---|---|
| Crude oil (Brent/WTI) | EIA API v2 (free instant key) + FRED | JSON API | Daily |
| Naphtha | **No free direct feed exists** (genuine ICIS/Platts paid product) | — | Proxy: derive from Brent + a typical crack-spread offset, clearly labeled "estimate" on the dashboard, not real market data |
| Natural gas (global) | FRED `DHHNGSP` / EIA API | JSON API | Daily |
| Natural gas (India domestic/APM) | PPAC (ppac.gov.in/natural-gas/gas-price) | **PDF only** | Bi-annual/monthly notification, needs PDF text scraping |
| Global GDP/growth | World Bank API (`api.worldbank.org/v2`) | JSON, no key needed | Annual (backdrop indicator, not daily) |
| USD/INR | Frankfurter.dev (ECB-based, free, no key) | JSON API | Daily |
| India polymer trade (import/export, by country, HS 3901/3902/3904/3907) | **TRADESTAT** (tradestat.commerce.gov.in) — primary | Free web queries | ~6-8 week lag, most current free India-specific source |
| India polymer trade — supplementary | UN Comtrade API (free key, 500 calls/day) | JSON API | India's own reporting lags 6-12+ months — use for annual/structural view only |
| Trade — historical benchmarking | WITS (wits.worldbank.org) | Free | Same lag caveats as Comtrade |
| Polymer price-movement commentary | Plastemart.com | Free, confirmed real daily news | Qualitative ("PP price hiked ₹2/kg"), not a clean numeric feed |
| Polymer price data (numeric) | PolymerUpdate/ICIS/ChemAnalyst | **Paywalled** — only demo/sample data free | Not usable for automated numeric pricing |
| News aggregation | Google News RSS (tuned queries), PIB RSS (policy/duty changes), ET/Business Standard/Moneycontrol RSS | Free RSS | Google News results need query tuning to cut market-research spam |
| Industry/company context | Reliance IR (ril.com/investors) quarterly transcripts | Free | Quarterly, not real-time — good qualitative capacity/pricing commentary |

**Important gap to flag to the user directly**: there is no free, automatable, numeric feed of actual domestic PP/PE/PVC/PET selling prices — the exact thing needed as the target variable for "predict prices" later. As a distributor, the user receives Reliance's own price-change circulars directly. The single best fix, free and higher-quality than any scraped proxy, is for the user to log those circular prices into the dashboard's data store themselves (a 30-second manual entry each time a circular arrives). This becomes the ground-truth series that the future prediction model is trained against.

## Architecture

```
~/polymer-dashboard/
  data/
    crude_oil.csv          # date, brent, wti
    natgas.csv              # date, henry_hub, india_apm
    usdinr.csv              # date, rate
    gdp.csv                 # year, country, growth_pct
    india_trade_pp.csv      # month, partner_country, flow(import/export), qty, value_usd
    india_trade_pe.csv
    india_trade_pvc.csv
    india_trade_pet.csv
    domestic_price_log.csv  # date, polymer, grade, price, source("circular"/"plastemart"/"estimate")
    news_digest.json        # today's categorized headlines + links
  scripts/
    fetch_macro.py          # EIA, FRED, World Bank, Frankfurter — daily
    fetch_natgas_india.py   # PPAC PDF scrape — monthly-aware, cheap to run daily
    fetch_trade.py          # TRADESTAT + Comtrade — runs but only meaningfully changes ~monthly
    fetch_news.py           # Google News/PIB/ET RSS pulls, keyword-categorized
    build_dashboard.py      # reads all CSVs/JSON, renders dashboard/index.html
  dashboard/
    index.html              # generated static dashboard, republished as the Artifact
  CLAUDE.md                 # documents the pipeline for future sessions
```

**Daily flow** (run by a scheduled cloud routine, e.g. 7:00am IST):
1. Run each `fetch_*.py`, appending new rows to the relevant CSV/JSON (idempotent — skip if today's row already exists).
2. Run `build_dashboard.py` to regenerate `dashboard/index.html` with fresh embedded data (KPI tiles with day-over-day deltas, trend charts, trade-flow charts, categorized news list, a per-section "data as of" freshness stamp since cadences differ: daily macro vs. weeks-old trade data).
3. Republish via the Artifact tool to the same URL so the user has one stable link to check each morning.

## Build steps
1. Scaffold the directory structure above; write `CLAUDE.md` describing each fetcher's source/HS-code/units so future sessions don't have to rediscover this research.
2. Implement `fetch_macro.py` first (highest reliability, all confirmed-working JSON APIs) and get one clean end-to-end run producing real CSV rows.
3. Implement `fetch_news.py` (Google News + PIB RSS, tuned queries from the research above) with simple keyword categorization (Price moves / Policy & Tariffs / Capacity & Plants / Macro).
4. Implement `fetch_trade.py` against TRADESTAT/Comtrade for HS 3901/3902/3904/3907, aggregated by partner country and flow direction.
5. Implement `fetch_natgas_india.py` (PPAC PDF parse) — lowest priority/most brittle, fine to stub with manual fallback initially.
6. Add `domestic_price_log.csv` plus a trivial way for the user to append a row (a one-line CLI prompt or a note in the dashboard on how to message it in) — this is the future prediction target.
7. Build `build_dashboard.py` and the dataviz-skill-compliant HTML dashboard (KPI tiles, trend lines, trade bar charts, news feed, freshness stamps), publish via the Artifact tool.
8. Set up the recurring schedule (via the schedule skill/routines, not session CronCreate) to run steps 1-7 every morning.
9. Explicitly defer price prediction to a phase 2, once a few months of `domestic_price_log.csv` + driver data has accumulated.

## Verification
- Run each `fetch_*.py` manually once and inspect the resulting CSV rows for sane values (e.g., Brent in the $60-100 range, USD/INR ~85-100).
- Run `build_dashboard.py` and open the generated HTML locally before first publish.
- Confirm the scheduled routine fires once (check for a fresh "data as of" timestamp the next morning) before considering setup done.
- Explicitly review the dashboard with the user for the naphtha-proxy and India-trade-lag caveats so expectations are set correctly from day one.
