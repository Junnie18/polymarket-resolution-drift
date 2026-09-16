#!/usr/bin/env python3
"""Build a candidate sample of resolved Polymarket markets across liquidity
tiers and categories.

Pulls pages of closed markets from the Gamma API across several volume
bands (to guarantee niche/low-volume markets are represented, since the
default volume-sorted listing is dominated by flagship markets), filters
to markets with a clear winner and usable CLOB token ids, classifies each
by keyword category, and writes the candidate list to
data/processed/market_candidates.csv.

This script does NOT hit the CLOB price-history endpoint -- that happens
in 02_collect_price_history.py, which also drops candidates with
insufficient price coverage. Keeping metadata collection and price-history
collection separate means we can over-sample here cheaply.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polydrift.categorize import classify  # noqa: E402
from polydrift.gamma import fetch_markets, parse_outcomes, winning_outcome_index  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = REPO_ROOT / "data" / "processed" / "market_candidates.csv"

# (label, volume_min, volume_max, max_results) -- bands overlap deliberately
# at the boundaries is avoided by using half-open ranges; max is None = no cap.
VOLUME_BANDS = [
    ("flagship", 1_000_000, None, 150),
    ("mid", 10_000, 1_000_000, 250),
    ("niche", 500, 10_000, 400),
]

# Minimum closedTime cutoff: Polymarket's central limit order book (CLOB)
# went live in 2022; markets closed well before that may predate CLOB price
# history entirely. We use a conservative cutoff and additionally validate
# coverage empirically in script 02.
MIN_CLOSED_TIME = pd.Timestamp("2023-01-01", tz="UTC")


def build_candidates() -> pd.DataFrame:
    rows = []
    seen_ids = set()
    for label, vmin, vmax, max_results in VOLUME_BANDS:
        markets = fetch_markets(
            closed=True,
            order="volumeNum",
            ascending=False,
            volume_num_min=vmin,
            volume_num_max=vmax,
            max_results=max_results,
        )
        print(f"[{label}] fetched {len(markets)} markets (volume {vmin}-{vmax})")
        for m in markets:
            mid = m.get("id")
            if mid is None or mid in seen_ids:
                continue
            closed_time_raw = m.get("closedTime")
            if not closed_time_raw:
                continue
            try:
                closed_time = pd.Timestamp(closed_time_raw)
                if closed_time.tzinfo is None:
                    closed_time = closed_time.tz_localize("UTC")
                else:
                    closed_time = closed_time.tz_convert("UTC")
            except (ValueError, TypeError):
                continue
            if closed_time < MIN_CLOSED_TIME:
                continue

            parsed = parse_outcomes(m)
            token_ids = parsed["clob_token_ids"]
            if len(token_ids) != 2:
                continue
            win_idx = winning_outcome_index(m)
            if win_idx is None:
                continue

            seen_ids.add(mid)
            question = m.get("question", "")
            rows.append(
                {
                    "market_id": mid,
                    "condition_id": m.get("conditionId"),
                    "question": question,
                    "slug": m.get("slug"),
                    "category": classify(question),
                    "liquidity_tier": label,
                    "volume_num": m.get("volumeNum"),
                    "closed_time": closed_time.isoformat(),
                    "winning_token_id": token_ids[win_idx],
                    "losing_token_id": token_ids[1 - win_idx],
                    "winning_outcome_label": parsed["outcomes"][win_idx]
                    if len(parsed["outcomes"]) == 2
                    else None,
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    df = build_candidates()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    print(f"\nWrote {len(df)} candidates to {OUT_PATH}")
    print(df.groupby(["liquidity_tier", "category"]).size().unstack(fill_value=0))


if __name__ == "__main__":
    main()
