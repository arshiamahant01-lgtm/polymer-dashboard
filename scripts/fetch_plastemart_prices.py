"""Fetch producer-direct polymer price circulars from plastemart.com (RIL, IOCL,
HMEL, OPaL — free, no login required).

Each producer/polymer combination has an archive listing page
(plastemart.com/polymer-pricelist/<slug>/<n>/<id>) linking to dated circular files.
Filenames are inconsistent (mixed case, mixed date-token order, occasional typos)
so we never construct a URL from a date/producer pattern — always scrape the
literal hrefs off each archive page and extract the date via regex.

Representative price per circular = mean of every numeric grade/location price in
the file's main pricing table(s) — a network-average approximation, not any single
grade or city (see the caveat on the dashboard). Plastemart prices are in Rs./MT;
divided by 1000 here to match this repo's ₹/kg convention (see log_price.py,
build_kpis()).

GAIL is intentionally excluded — its real circulars are packaged as .rar archives
(no unrar/7z available in this environment) and its Plastemart archive page mostly
surfaces a third-party dealer's price sheet, not a verified GAIL-direct number.

Idempotent: skips any circular already downloaded to data/plastemart_raw/.
"""
import datetime as dt
import io
import re
import sys

import pandas as pd
import PyPDF2
import requests

from utils import DATA_DIR, upsert_csv

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
BASE = "https://www.plastemart.com"
DATE_RE = re.compile(r"(\d{1,2})[-.](\d{1,2})[-.](\d{4})")
HREF_RE = re.compile(r'href="(/Upload/pricelist/[^"]+\.(?:xlsx|pdf))"', re.IGNORECASE)

# (producer, polymer_family, archive_url, filename must contain ALL of these
#  (case-insensitive), filename must contain NONE of these)
ARCHIVE_PAGES = [
    ("RIL", "PP", f"{BASE}/polymer-pricelist/pp-reliance/4/9", ["reliance"], ["sez", "deem"]),
    ("RIL", "PE", f"{BASE}/polymer-pricelist/hdpe-reliance/2/9", ["pe-reliance"], ["sez", "deem"]),
    ("RIL", "PVC", f"{BASE}/polymer-pricelist/pvc-reliance/7/9", ["pvc-reliance"], []),
    ("IOCL", "PP", f"{BASE}/polymer-pricelist/pp-iocl/4/33", ["iocl"], []),
    ("IOCL", "HDPE", f"{BASE}/polymer-pricelist/hdpe-iocl/2/33", ["iocl"], []),
    ("IOCL", "LLDPE", f"{BASE}/polymer-pricelist/lldpe-iocl/3/33", ["iocl"], []),
    ("HMEL", "PP", f"{BASE}/polymer-pricelist/pp-hmel/4/42", ["hmel"], []),
    ("HMEL", "HDPE", f"{BASE}/polymer-pricelist/hdpe-hmel/2/42", ["hmel"], []),
    ("HMEL", "LLDPE", f"{BASE}/polymer-pricelist/lldpe-hmel/3/42", ["hmel"], []),
    ("OPAL", "HDPE", f"{BASE}/polymer-pricelist/hdpe-opal/2/38", ["opal"], []),
]

# RIL's PE-Reliance.xlsx bundles HDPE/LLDPE/LDPE as separate stacked tables inside
# one sheet, each preceded by an "...Annexure..." header row naming the grade type.
NON_DATA_SHEETS = {"price policy", "tr.qty.dis.", "tr.qtydis.", "tr.qty dis."}


def find_circulars(url: str) -> list[tuple[str, str]]:
    """Returns [(date_iso, absolute_url), ...] for every circular link on the page."""
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    out = []
    for href in HREF_RE.findall(resp.text):
        m = DATE_RE.search(href)
        if not m:
            continue
        d, mo, y = m.groups()
        try:
            date_iso = dt.date(int(y), int(mo), int(d)).isoformat()
        except ValueError:
            continue
        out.append((date_iso, BASE + href))
    return out


def filter_links(links: list[tuple[str, str]], must_contain: list[str], must_not_contain: list[str]) -> list[tuple[str, str]]:
    kept = {}
    for date_iso, url in links:
        fname = url.rsplit("/", 1)[-1].lower()
        if not all(tok in fname for tok in must_contain):
            continue
        if any(tok in fname for tok in must_not_contain):
            continue
        # if the same date appears twice (case/typo variants), keep the first seen
        kept.setdefault(date_iso, url)
    return sorted(kept.items())


def detect_pe_family(header_text: str, default: str) -> str:
    t = header_text.upper()
    if "LLDPE" in t:
        return "LLDPE"
    if "HDPE" in t:
        return "HDPE"
    if "LDPE" in t:
        return "LDPE"
    return default


def parse_xlsx(content: bytes, default_family: str) -> dict[str, list[float]]:
    """Returns {polymer_family: [numeric grade/location prices]} for an RIL circular."""
    xl = pd.ExcelFile(io.BytesIO(content))
    values: dict[str, list[float]] = {}
    data_sheets = [s for s in xl.sheet_names if s.strip().lower() not in NON_DATA_SHEETS]
    # prefer an "ex-works"/"ex works" sheet if present (factory-basis price, no
    # freight/depot markup); otherwise use every remaining data sheet.
    ex_works = [s for s in data_sheets if "ex" in s.strip().lower() and "works" in s.strip().lower()]
    sheets = ex_works or data_sheets
    for sheet_name in sheets:
        df = xl.parse(sheet_name, header=None)
        current_family = default_family
        for i in range(len(df)):
            cell0 = df.iat[i, 0]
            if isinstance(cell0, str) and ("annexure" in cell0.lower() or "grades" in cell0.lower()):
                current_family = detect_pe_family(cell0, default_family)
                continue
            for c in range(3, df.shape[1]):
                v = df.iat[i, c]
                if isinstance(v, (int, float)) and not pd.isna(v) and v > MIN_PLAUSIBLE_PRICE:
                    values.setdefault(current_family, []).append(float(v))
    return values


NUM_RE = re.compile(r"\b\d{4,7}(?:\.\d{1,2})?\b")
MIN_PLAUSIBLE_PRICE = 30000  # Rs./MT — well above any freight/discount/adjustment
                              # line item (seen up to ~8000), well below no genuine
                              # grade price (seen from ~82000 up)

# IOCL/OPaL circulars stack PP/HDPE/LLDPE grade tables in one document without a
# clean per-line family tag on every row (e.g. "RAFFIA"/"INJ." grade names repeat
# across all three families). Classify by distinctive grade-code keywords, carrying
# the last-seen family forward within a block, and reset at each block boundary
# (a divider line — city/location headers repeat between stacked tables — with no
# digits at all) so a block's early ambiguous lines don't inherit the previous
# block's family.
FAMILY_KEYWORDS = [
    (re.compile(r"\bLL[\s\-]|\bLLDPE\b|\bROTO\b|\bXRLL\b|\bXMLL\b|\bXFLL\b", re.I), "LLDPE"),
    (re.compile(r"\bHD[\s\-]|\bHDPE\b|\bGPBM\b|\bPIPE-|\bMBM\b|\bLBM\b|\bXEHD\b|\bXMHD\b|\bDXB\b|\bDXF\b|\bXFHD\b", re.I), "HDPE"),
    (re.compile(r"\bPP\b|\bBOPP\b|\bRCP\b|\bICP\b|\bXHF\b|\bXLF\b", re.I), "PP"),
]


def is_divider_line(line: str) -> bool:
    return not any(ch.isdigit() for ch in line) and len(line.split()) >= 2


def parse_pdf(content: bytes, default_family: str) -> dict[str, list[float]]:
    reader = PyPDF2.PdfReader(io.BytesIO(content))
    values: dict[str, list[float]] = {}
    for page in reader.pages:
        text = page.extract_text() or ""
        current_family = None
        for line in text.splitlines():
            if is_divider_line(line):
                current_family = None
                continue
            for pattern, fam in FAMILY_KEYWORDS:
                if pattern.search(line):
                    current_family = fam
                    break
            family = current_family or default_family
            for tok in NUM_RE.findall(line):
                v = float(tok)
                if v > MIN_PLAUSIBLE_PRICE:
                    values.setdefault(family, []).append(v)
    return values


def run():
    raw_dir = DATA_DIR / "plastemart_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for producer, default_family, url, must_contain, must_not_contain in ARCHIVE_PAGES:
        try:
            links = find_circulars(url)
        except Exception as exc:
            print(f"[{producer} {default_family}] failed to list archive page: {exc}", file=sys.stderr)
            continue
        circulars = filter_links(links, must_contain, must_not_contain)
        if not circulars:
            print(f"[{producer} {default_family}] no circulars found on {url}", file=sys.stderr)
            continue

        for date_iso, file_url in circulars:
            ext = file_url.rsplit(".", 1)[-1].lower()
            dest = raw_dir / f"{producer}_{default_family}_{date_iso}.{ext}"

            if dest.exists():
                content = dest.read_bytes()
            else:
                try:
                    resp = requests.get(file_url, headers=HEADERS, timeout=30)
                    resp.raise_for_status()
                    content = resp.content
                    dest.write_bytes(content)
                except Exception as exc:
                    print(f"[{producer} {default_family} {date_iso}] download failed: {exc}", file=sys.stderr)
                    continue

            try:
                if ext == "xlsx":
                    by_family = parse_xlsx(content, default_family)
                else:
                    by_family = parse_pdf(content, default_family)
            except Exception as exc:
                print(f"[{producer} {default_family} {date_iso}] parse failed ({dest.name}): {exc}", file=sys.stderr)
                continue

            for family, prices in by_family.items():
                if not prices:
                    continue
                avg_rs_per_mt = sum(prices) / len(prices)
                rows.append({
                    "date": date_iso,
                    "polymer_family": family,
                    "producer": producer,
                    "price": round(avg_rs_per_mt / 1000, 2),  # Rs./MT -> ₹/kg
                    "grade_count": len(prices),
                    "price_type": "producer_direct",
                    "notes": dest.name,
                    "source": "plastemart",
                })

    if not rows:
        print("plastemart: no producer-direct rows parsed", file=sys.stderr)
        return

    added = upsert_csv(
        "domestic_price_log.csv", rows,
        key_cols=["date", "polymer_family", "producer", "price_type", "source"],
    )
    print(f"domestic_price_log.csv: upserted {added} plastemart producer-direct rows")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"fetch_plastemart_prices failed: {exc}", file=sys.stderr)
        sys.exit(1)
