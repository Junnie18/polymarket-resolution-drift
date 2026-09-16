#!/usr/bin/env python3
"""Select a stratified sample from the candidate pool and pull minute-level
CLOB price history for the final 72h before resolution of each market.

Reads data/processed/market_candidates.csv (from 01_collect_markets.py),
selects up to MAX_PER_CELL markets per (liquidity_tier, category) cell,
pulls price-history for the winning outcome's token from
resolution_time - 72h to resolution_time, and writes:
  - data/processed/price_series/<market_id>.csv   (timestamp, price)
  - data/processed/market_sample.csv               (kept markets + coverage stats)
  - data/processed/price_collection_log.csv        (every attempt, incl. drops)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polydrift.clob import price_history_df  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
CANDIDATES_PATH = REPO_ROOT / "data" / "processed" / "market_candidates.csv"
SERIES_DIR = REPO_ROOT / "data" / "processed" / "price_series"
SAMPLE_OUT = REPO_ROOT / "data" / "processed" / "market_sample.csv"
LOG_OUT = REPO_ROOT / "data" / "processed" / "price_collection_log.csv"

MAX_PER_CELL = 15
WINDOW_HOURS = 72
MIN_POINTS = 30
MIN_COVERAGE = 0.02  # at least 2% of expected 1-min bars present
RANDOM_SEED = 42


def select_sample(candidates: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for _, group in candidates.groupby(["liquidity_tier", "category"]):
        n = min(len(group), MAX_PER_CELL)
        parts.append(group.sample(n=n, random_state=RANDOM_SEED))
    return pd.concat(parts).reset_index(drop=True)


def main() -> None:
    candidates = pd.read_csv(CANDIDATES_PATH)
    sample = select_sample(candidates)
    print(f"Selected {len(sample)} markets from {len(candidates)} candidates")
    SERIES_DIR.mkdir(parents=True, exist_ok=True)

    kept_rows = []
    log_rows = []
    t0 = time.time()
    for i, row in sample.iterrows():
        market_id = row["market_id"]
        resolution_time = pd.Timestamp(row["closed_time"])
        if resolution_time.tzinfo is None:
            resolution_time = resolution_time.tz_localize("UTC")
        window_start = resolution_time - pd.Timedelta(hours=WINDOW_HOURS)
        start_ts = int(window_start.timestamp())
        end_ts = int(resolution_time.timestamp())

        status = "ok"
        n_points = 0
        coverage = 0.0
        try:
            df = price_history_df(str(row["winning_token_id"]), start_ts, end_ts, fidelity=1)
        except Exception as exc:  # noqa: BLE001 - log and continue on any fetch failure
            status = f"fetch_error: {exc}"
            df = pd.DataFrame(columns=["timestamp", "price"])

        n_points = len(df)
        expected_bars = max(1, WINDOW_HOURS * 60)
        coverage = n_points / expected_bars

        if status == "ok" and (n_points < MIN_POINTS or coverage < MIN_COVERAGE):
            status = f"insufficient_coverage(n={n_points}, cov={coverage:.4f})"

        if status == "ok":
            out_path = SERIES_DIR / f"{market_id}.csv"
            df.to_csv(out_path, index=False)
            kept_rows.append({**row.to_dict(), "n_points": n_points, "coverage": coverage})

        log_rows.append(
            {
                "market_id": market_id,
                "question": row["question"],
                "liquidity_tier": row["liquidity_tier"],
                "category": row["category"],
                "status": status,
                "n_points": n_points,
                "coverage": coverage,
            }
        )

        if (i + 1) % 25 == 0:
            elapsed = time.time() - t0
            print(f"  {i + 1}/{len(sample)} processed ({elapsed:.0f}s elapsed)")

    kept_df = pd.DataFrame(kept_rows)
    log_df = pd.DataFrame(log_rows)
    kept_df.to_csv(SAMPLE_OUT, index=False)
    log_df.to_csv(LOG_OUT, index=False)

    print(f"\nKept {len(kept_df)}/{len(sample)} markets with usable price history")
    print(f"Wrote sample -> {SAMPLE_OUT}")
    print(f"Wrote log -> {LOG_OUT}")
    if len(kept_df):
        print(kept_df.groupby(["liquidity_tier", "category"]).size().unstack(fill_value=0).to_string())
    print("\nDrop reasons:")
    print(log_df[log_df["status"] != "ok"]["status"].str.replace(r"\(.*\)", "", regex=True).value_counts())


if __name__ == "__main__":
    main()
