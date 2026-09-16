#!/usr/bin/env python3
"""Collect resolved NBA moneyline markets from Polymarket for the external
signal case study.

Polymarket names its per-game NBA moneyline markets with slugs like
"nba-sas-nyk-2026-06-10" (league-away-home-date), with no over/under or
spread suffix. We pull across several volume bands (to get both flagship
playoff games and quiet regular-season games), filter to that slug
pattern, pull price history for the winning side, and write:
  - data/processed/nba_markets.csv
  - data/processed/price_series/<market_id>.csv (reused from script 02)
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polydrift.clob import price_history_df  # noqa: E402
from polydrift.gamma import fetch_markets, parse_outcomes, winning_outcome_index  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = REPO_ROOT / "data" / "processed" / "nba_markets.csv"
SERIES_DIR = REPO_ROOT / "data" / "processed" / "price_series"

SLUG_RE = re.compile(r"^nba-([a-z]+)-([a-z]+)-(\d{4}-\d{2}-\d{2})$")
WINDOW_HOURS = 72
MIN_CLOSED_TIME = pd.Timestamp("2023-01-01", tz="UTC")

VOLUME_BANDS = [
    ("flagship", 500_000, None, 60),
    ("mid", 20_000, 500_000, 80),
    ("niche", 500, 20_000, 100),
]
# Gamma's offset-based pagination errors out past ~2900; stay comfortably
# under that per band while scanning enough pages to find slug matches
# (most markets in a volume band are NOT clean NBA moneylines).
MAX_SCAN_PER_BAND = 2500


def collect() -> pd.DataFrame:
    rows = []
    seen = set()
    for label, vmin, vmax, max_results in VOLUME_BANDS:
        markets = fetch_markets(
            closed=True,
            order="volumeNum",
            ascending=False,
            volume_num_min=vmin,
            volume_num_max=vmax,
            max_results=MAX_SCAN_PER_BAND,  # over-fetch since most won't match the slug pattern
        )
        n_matched = 0
        for m in markets:
            slug = m.get("slug", "") or ""
            match = SLUG_RE.match(slug)
            if not match:
                continue
            mid = m.get("id")
            if mid is None or mid in seen:
                continue
            closed_time_raw = m.get("closedTime")
            if not closed_time_raw:
                continue
            closed_time = pd.Timestamp(closed_time_raw)
            if closed_time.tzinfo is None:
                closed_time = closed_time.tz_localize("UTC")
            else:
                closed_time = closed_time.tz_convert("UTC")
            if closed_time < MIN_CLOSED_TIME:
                continue
            parsed = parse_outcomes(m)
            token_ids = parsed["clob_token_ids"]
            if len(token_ids) != 2:
                continue
            win_idx = winning_outcome_index(m)
            if win_idx is None:
                continue

            away_abbr, home_abbr, game_date = match.groups()
            seen.add(mid)
            rows.append(
                {
                    "market_id": mid,
                    "question": m.get("question"),
                    "slug": slug,
                    "away_abbr": away_abbr,
                    "home_abbr": home_abbr,
                    "game_date_slug": game_date,
                    "liquidity_tier": label,
                    "volume_num": m.get("volumeNum"),
                    "closed_time": closed_time.isoformat(),
                    "winning_token_id": token_ids[win_idx],
                    "winning_outcome_label": parsed["outcomes"][win_idx]
                    if len(parsed["outcomes"]) == 2
                    else None,
                }
            )
            n_matched += 1
            if n_matched >= max_results:
                break
        print(f"[{label}] matched {n_matched} NBA moneyline markets")
    return pd.DataFrame(rows)


def pull_price_series(df: pd.DataFrame) -> pd.DataFrame:
    kept = []
    t0 = time.time()
    for i, row in df.iterrows():
        resolution_time = pd.Timestamp(row["closed_time"])
        window_start = resolution_time - pd.Timedelta(hours=WINDOW_HOURS)
        start_ts = int(window_start.timestamp())
        end_ts = int(resolution_time.timestamp())
        try:
            series = price_history_df(str(row["winning_token_id"]), start_ts, end_ts, fidelity=1)
        except Exception as exc:  # noqa: BLE001
            print(f"  fetch error for {row['market_id']}: {exc}")
            continue
        if len(series) < 10:
            continue
        out_path = SERIES_DIR / f"{row['market_id']}.csv"
        series.to_csv(out_path, index=False)
        kept.append({**row.to_dict(), "n_points": len(series)})
        if (i + 1) % 25 == 0:
            print(f"  {i + 1}/{len(df)} processed ({time.time() - t0:.0f}s elapsed)")
    return pd.DataFrame(kept)


def main() -> None:
    df = collect()
    print(f"\nTotal NBA moneyline candidates: {len(df)}")
    kept = pull_price_series(df)
    SERIES_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    kept.to_csv(OUT_PATH, index=False)
    print(f"Kept {len(kept)} markets with usable price history -> {OUT_PATH}")
    if len(kept):
        print(kept["liquidity_tier"].value_counts())


if __name__ == "__main__":
    main()
