#!/usr/bin/env python3
"""Measure the lag between ESPN's live win-probability signal and
Polymarket's price for the same NBA games.

For each matched game: find the wall-clock time ESPN's win probability
(for the team that actually won) permanently crosses 90%, find the
wall-clock time Polymarket's price permanently crosses 90%, and take the
difference. Positive lag = Polymarket reacted later than ESPN's model.

Writes data/processed/external_signal_lag.csv and a lag histogram figure.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polydrift import espn  # noqa: E402
from polydrift.convergence import find_permanent_crossing  # noqa: E402
from polydrift.nba_match import find_matching_espn_event, winner_win_probability  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
NBA_MARKETS_PATH = REPO_ROOT / "data" / "processed" / "nba_markets.csv"
SERIES_DIR = REPO_ROOT / "data" / "processed" / "price_series"
OUT_PATH = REPO_ROOT / "data" / "processed" / "external_signal_lag.csv"
FIG_DIR = REPO_ROOT / "docs" / "figures"

THRESHOLD = 0.90


def process_market(row: pd.Series) -> dict:
    result = {
        "market_id": row["market_id"],
        "question": row["question"],
        "liquidity_tier": row["liquidity_tier"],
        "volume_num": row["volume_num"],
        "matched": False,
        "espn_event_id": None,
        "espn_crossing_ts": None,
        "polymarket_crossing_ts": None,
        "lag_minutes": None,
        "espn_reverted": None,
        "polymarket_reverted": None,
        "skip_reason": None,
    }

    event = find_matching_espn_event(row["question"], row["game_date_slug"])
    if event is None:
        result["skip_reason"] = "no_espn_match"
        return result
    result["matched"] = True
    result["espn_event_id"] = event["id"]

    if event.get("home_winner") is None:
        result["skip_reason"] = "espn_no_winner_flag"
        return result
    home_won = bool(event["home_winner"])

    wp_df = espn.win_probability_timeseries("NBA", event["id"])
    if wp_df is None or wp_df.empty:
        result["skip_reason"] = "no_espn_winprob_data"
        return result
    wp_df = winner_win_probability(wp_df, home_won)

    espn_crossing_ts, espn_reverted = find_permanent_crossing(
        wp_df, THRESHOLD, timestamp_col="timestamp", value_col="winner_win_prob"
    )
    result["espn_reverted"] = espn_reverted
    if espn_crossing_ts is None:
        result["skip_reason"] = "espn_never_converged"
        return result
    result["espn_crossing_ts"] = espn_crossing_ts.isoformat()

    series_path = SERIES_DIR / f"{row['market_id']}.csv"
    if not series_path.exists():
        result["skip_reason"] = "no_polymarket_series"
        return result
    pm_df = pd.read_csv(series_path, parse_dates=["timestamp"])
    pm_df["timestamp"] = pd.to_datetime(pm_df["timestamp"], utc=True)
    pm_crossing_ts, pm_reverted = find_permanent_crossing(pm_df, THRESHOLD)
    result["polymarket_reverted"] = pm_reverted
    if pm_crossing_ts is None:
        result["skip_reason"] = "polymarket_never_converged"
        return result
    result["polymarket_crossing_ts"] = pm_crossing_ts.isoformat()

    lag = (pm_crossing_ts - espn_crossing_ts).total_seconds() / 60.0
    result["lag_minutes"] = lag
    return result


def main() -> None:
    nba = pd.read_csv(NBA_MARKETS_PATH)
    rows = []
    t0 = time.time()
    for i, (_, row) in enumerate(nba.iterrows()):
        rows.append(process_market(row))
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(nba)} processed ({time.time() - t0:.0f}s elapsed)")

    df = pd.DataFrame(rows)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)

    n_matched = df["matched"].sum()
    n_with_lag = df["lag_minutes"].notna().sum()
    print(f"\nMatched to an ESPN game: {n_matched}/{len(df)}")
    print(f"Usable lag measurement: {n_with_lag}/{len(df)}")
    print("\nSkip reasons:")
    print(df.loc[df["lag_minutes"].isna(), "skip_reason"].value_counts())

    valid = df.dropna(subset=["lag_minutes"])
    if len(valid):
        print("\n=== Lag (minutes) by liquidity tier, Polymarket 90% crossing minus ESPN 90% crossing ===")
        print(valid.groupby("liquidity_tier")["lag_minutes"].describe().to_string())
        print(f"\nOverall median lag: {valid['lag_minutes'].median():.1f} min")
        pct_lagged = 100 * (valid["lag_minutes"] > 0).mean()
        print(f"% of games where Polymarket lagged ESPN (lag > 0): {pct_lagged:.1f}%")

        FIG_DIR.mkdir(parents=True, exist_ok=True)
        fig, ax = plt.subplots(figsize=(7, 5))
        ax.hist(valid["lag_minutes"], bins=20, color="#2a6f97", edgecolor="white")
        ax.axvline(0, color="black", linestyle="--", linewidth=1)
        ax.set_xlabel("Minutes (Polymarket 90% crossing - ESPN win-prob 90% crossing)")
        ax.set_ylabel("Number of games")
        ax.set_title("Polymarket lag vs. ESPN live win probability (NBA)")
        fig.tight_layout()
        fig.savefig(FIG_DIR / "external_signal_lag_hist.png", dpi=150)
        plt.close(fig)
        print(f"Wrote figure -> {FIG_DIR / 'external_signal_lag_hist.png'}")


if __name__ == "__main__":
    main()
