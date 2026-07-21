# Polymer Market Tracking Dashboard

Free-tier tracking dashboard for the India polymer market (PP, PE, PVC, PET), built for a
Reliance polymer distributor. See `PLAN.md` for the full design rationale and verified source
research. This file is the quick-reference for maintaining the pipeline.

## Data sources (see PLAN.md for full detail/caveats)

| Script | Source | Key needed? | Notes |
|---|---|---|---|
| `fetch_macro.py` | EIA API v2 (Brent/WTI, Henry Hub), World Bank API (GDP), Frankfurter.dev (USD/INR) | EIA: yes, free (`EIA_API_KEY` env var). Others: no | FRED CSV endpoint is bot-blocked from scripted `curl`/`requests` (connection reset) — do not use it; EIA API is the reliable source for oil/gas |
| `fetch_news.py` | Google News RSS, PIB RSS | No | Categorizes into Price moves / Policy & Tariffs / Supply & Capacity-Geopolitical / Macro |
| `fetch_credco.py` | `api.credcosourcing.com/api/products` (real JSON API, found via the site's JS bundle — no key, no auth) | No | **Open-market** PP/HDPE/LDPE/LLDPE/PVC/EVA prices, 616 grades — NOT producer-direct price. Tag `price_type=open_market`. API returns a short trailing price_trend per grade but no deep history endpoint found — can't backfill a full year, only accumulate day by day |
| `fetch_trade.py` | TRADESTAT (commerce.gov.in), UN Comtrade API (backup, free key, 500 calls/day) | Comtrade: optional free key for full tier | India trade data lags 6-8 weeks (TRADESTAT) to 6-12+ months (Comtrade) — never treat as daily-fresh |
| `fetch_natgas_india.py` | PPAC (ppac.gov.in/natural-gas/gas-price) | No | PDF-only, bi-annual/monthly notifications — brittle, parse defensively |
| `fetch_naphtha_check.py` | tradingeconomics.com/commodity/naphtha (secondary, light single-value check) + crude-based crack-spread proxy (primary) | No | No free real naphtha feed exists anywhere — always label as estimate/unverified |

## Key files in `data/`
- `domestic_price_log.csv` — columns `date,polymer_family,producer,price,grade_count,price_type,...`. Holds **two distinct series** tagged by `price_type`:
  - `open_market` — auto-populated daily by `fetch_credco.py` (real API: `api.credcosourcing.com/api/products`, median price per polymer family/producer, full raw daily snapshots kept in `data/credco_raw/<date>.json`).
  - `producer_direct` — **manually entered** by the user whenever a Reliance/HMEL/IOCL price circular arrives (see `log_price.py`). This is the only free source of true producer-direct price, and the eventual prediction target.
  Always plot these as separate labeled series on the dashboard — never averaged/blended (see Hard rule below).
- `capacity_reference.csv` — hand-maintained plant capacity table, updated occasionally from IR decks/news, not scraped daily.

## Daily flow
1. Run all `fetch_*.py` (idempotent — skip rows that already exist for today).
2. Run `build_dashboard.py` to regenerate `dashboard/index.html`.
3. Publish `dashboard/index.html` via the Artifact tool.
Automated by a scheduled cloud routine (see the `schedule` skill) — not session-based `CronCreate`, which expires after 7 days.

## Hard rule
Credco (open-market) and `domestic_price_log.csv` (producer-direct) must always render as two separate, clearly labeled series on the dashboard — never averaged or blended.
