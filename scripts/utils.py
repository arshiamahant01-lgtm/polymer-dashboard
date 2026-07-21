"""Shared helpers for the polymer dashboard fetch scripts."""
import os
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def load_env():
    """Load KEY=VALUE pairs from ~/polymer-dashboard/.env into os.environ (no external dep)."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def upsert_csv(filename: str, new_rows: list[dict], key_cols: list[str]) -> int:
    """Merge new_rows into data/<filename>, deduping on key_cols. Returns rows added/updated."""
    path = DATA_DIR / filename
    new_df = pd.DataFrame(new_rows)
    if new_df.empty:
        return 0

    if path.exists():
        existing = pd.read_csv(path, dtype=str)
        combined = pd.concat([existing, new_df.astype(str)], ignore_index=True)
    else:
        combined = new_df.astype(str)

    before = len(combined)
    combined = combined.drop_duplicates(subset=key_cols, keep="last")
    combined = combined.sort_values(by=key_cols).reset_index(drop=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    combined.to_csv(path, index=False)
    return len(new_df)
