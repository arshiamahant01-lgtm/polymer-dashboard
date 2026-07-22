"""Log a producer-direct price you received (e.g. from a Reliance/HMEL/IOCL circular).

This is the ONLY free source of true producer-direct price, and the future
prediction target. Run interactively:

    python3 log_price.py

Or non-interactively:

    python3 log_price.py --polymer PP --producer RIL --price 142.5 --date 2026-07-20 --notes "circular #123"
"""
import argparse
import datetime as dt

from utils import upsert_csv

VALID_FAMILIES = ["PP", "HDPE", "LDPE", "LLDPE", "PVC", "PET", "EVA"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--polymer", choices=VALID_FAMILIES)
    parser.add_argument("--producer", help="e.g. RIL, HMEL, IOCL")
    parser.add_argument("--price", type=float, help="₹/kg")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    polymer = args.polymer or input(f"Polymer ({'/'.join(VALID_FAMILIES)}): ").strip().upper()
    producer = args.producer or input("Producer (e.g. RIL, HMEL, IOCL): ").strip().upper()
    price = args.price if args.price is not None else float(input("Price (₹/kg): ").strip())
    notes = args.notes or input("Notes (optional, e.g. circular #): ").strip()

    row = {
        "date": args.date,
        "polymer_family": polymer,
        "producer": producer,
        "price": price,
        "grade_count": 1,
        "price_type": "producer_direct",
        "notes": notes,
        "source": "manual",
    }
    added = upsert_csv(
        "domestic_price_log.csv", [row],
        key_cols=["date", "polymer_family", "producer", "price_type", "source"],
    )
    print(f"Logged: {args.date} {polymer} {producer} price_type=producer_direct ₹{price}/kg ({added} row)")


if __name__ == "__main__":
    main()
