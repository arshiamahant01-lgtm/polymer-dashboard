"""Fetch India's domestic administered (APM) natural gas price from PPAC.

PPAC (ppac.gov.in/natural-gas/gas-price) publishes monthly price notifications,
but they are SCANNED/IMAGE PDFs — text extraction returns nothing with PyPDF2,
and no OCR toolchain (tesseract/poppler) is available in this environment. Rather
than silently fail, this script finds the latest notification PDF, saves it
locally for manual reading, and logs a clear message. If the user later installs
tesseract + pdftoppm, this can be upgraded to real OCR extraction.
"""
import re
import sys

import requests

from utils import DATA_DIR

PAGE_URL = "https://www.ppac.gov.in/natural-gas/gas-price"
PDF_LINK_RE = re.compile(r'href="(https://ppac\.gov\.in/download\.php\?file=gasprice/[^"]*Dom[^"]*\.pdf)"', re.IGNORECASE)


def find_latest_pdf_url() -> str | None:
    resp = requests.get(PAGE_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30, allow_redirects=True)
    resp.raise_for_status()
    matches = PDF_LINK_RE.findall(resp.text)
    if not matches:
        return None
    # filenames are prefixed with a unix timestamp, e.g. 1782821785_..., so max() sorts to latest
    return max(matches, key=lambda u: u.split("file=gasprice/")[-1])


def run():
    url = find_latest_pdf_url()
    if not url:
        print("Could not find a PPAC gas price PDF link on the page.", file=sys.stderr)
        return

    pdf_dir = DATA_DIR / "ppac_pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    filename = url.split("file=gasprice/")[-1]
    dest = pdf_dir / filename

    if not dest.exists():
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        print(f"Saved new PPAC notification: {dest.name}")
    else:
        print(f"Already have latest PPAC notification: {dest.name}")

    print(
        "NOTE: PPAC notifications are scanned/image PDFs — no text could be auto-extracted "
        f"(no OCR toolchain installed). Read the price manually from {dest} and log it via "
        "log_price.py if you want it tracked, or install tesseract+poppler to automate this."
    )


if __name__ == "__main__":
    run()
