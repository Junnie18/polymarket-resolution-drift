#!/usr/bin/env python3
"""Compute convergence metrics for every market in the sample and produce
tier/category-level aggregate statistics + plots.

Reads data/processed/market_sample.csv and the per-market price series in
data/processed/price_series/, writes:
  - data/processed/convergence_metrics.csv       (one row per market)
  - data/processed/convergence_summary_by_tier.csv
  - data/processed/convergence_summary_by_category.csv
  - docs/figures/convergence_*.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polydrift.convergence import compute_metrics  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = REPO_ROOT / "data" / "processed" / "market_sample.csv"
SERIES_DIR = REPO_ROOT / "data" / "processed" / "price_series"
METRICS_OUT = REPO_ROOT / "data" / "processed" / "convergence_metrics.csv"
BY_TIER_OUT = REPO_ROOT / "data" / "processed" / "convergence_summary_by_tier.csv"
BY_CATEGORY_OUT = REPO_ROOT / "data" / "processed" / "convergence_summary_by_category.csv"
FIG_DIR = REPO_ROOT / "docs" / "figures"

WINDOW_HOURS = 72
TIER_ORDER = ["flagship", "mid", "niche"]


def compute_all_metrics(sample: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in sample.iterrows():
        market_id = row["market_id"]
        series_path = SERIES_DIR / f"{market_id}.csv"
        if not series_path.exists():
            continue
        df = pd.read_csv(series_path, parse_dates=["timestamp"])
        if df.empty:
            continue
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

        resolution_time = pd.Timestamp(row["closed_time"])
        if resolution_time.tzinfo is None:
            resolution_time = resolution_time.tz_localize("UTC")
        window_start = resolution_time - pd.Timedelta(hours=WINDOW_HOURS)

        m = compute_metrics(df, window_start, resolution_time)
        rows.append(
            {
                "market_id": market_id,
                "question": row["question"],
                "liquidity_tier": row["liquidity_tier"],
                "category": row["category"],
                "volume_num": row["volume_num"],
                "n_points": m.n_points,
                "coverage": m.coverage_frac,
                "price_at_window_start": m.price_at_window_start,
                "hours_to_converge_90": m.hours_to_converge_90,
                "hours_to_converge_95": m.hours_to_converge_95,
                "reverted_after_90": m.reverted_after_90,
                "reverted_after_95": m.reverted_after_95,
                "in_uncertain_band_last6h": m.in_uncertain_band_last6h,
                "in_uncertain_band_last1h": m.in_uncertain_band_last1h,
                "min_price_last6h": m.min_price_last6h,
                "max_abs_move_last6h": m.max_abs_move_last6h,
                "converged_90": m.hours_to_converge_90 is not None,
            }
        )
    return pd.DataFrame(rows)


def summarize(metrics: pd.DataFrame, by: str) -> pd.DataFrame:
    def agg(g: pd.DataFrame) -> pd.Series:
        return pd.Series(
            {
                "n_markets": len(g),
                "pct_never_converged_90": 100 * (~g["converged_90"]).mean(),
                "median_hours_to_converge_90": g["hours_to_converge_90"].median(),
                "p25_hours_to_converge_90": g["hours_to_converge_90"].quantile(0.25),
                "p75_hours_to_converge_90": g["hours_to_converge_90"].quantile(0.75),
                "pct_reverted_after_90": 100 * g["reverted_after_90"].mean(),
                "pct_in_uncertain_band_last6h": 100 * g["in_uncertain_band_last6h"].mean(),
                "pct_in_uncertain_band_last1h": 100 * g["in_uncertain_band_last1h"].mean(),
                "median_max_abs_move_last6h": g["max_abs_move_last6h"].median(),
            }
        )

    out = metrics.groupby(by).apply(agg, include_groups=False)
    return out.reset_index()


def plot_convergence_by_tier(metrics: pd.DataFrame) -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7, 5))
    data = [
        metrics.loc[metrics["liquidity_tier"] == t, "hours_to_converge_90"].dropna()
        for t in TIER_ORDER
    ]
    ax.boxplot(data, tick_labels=TIER_ORDER, showfliers=False)
    ax.set_ylabel("Hours before resolution that price permanently crossed 90%")
    ax.set_title("Convergence timing by liquidity tier (higher = converged earlier)")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "convergence_hours_by_tier.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 5))
    band_pct = metrics.groupby("liquidity_tier")["in_uncertain_band_last6h"].mean().reindex(TIER_ORDER) * 100
    ax.bar(TIER_ORDER, band_pct.values, color=["#2a6f97", "#61a5c2", "#a9d6e5"])
    ax.set_ylabel("% of markets with price in [40%, 60%] within final 6h")
    ax.set_title("Share of markets still uncertain within 6h of resolution")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "uncertain_band_by_tier.png", dpi=150)
    plt.close(fig)


def main() -> None:
    sample = pd.read_csv(SAMPLE_PATH)
    metrics = compute_all_metrics(sample)
    metrics.to_csv(METRICS_OUT, index=False)
    print(f"Wrote {len(metrics)} market metrics -> {METRICS_OUT}")

    by_tier = summarize(metrics, "liquidity_tier")
    by_tier = by_tier.set_index("liquidity_tier").reindex(TIER_ORDER).reset_index()
    by_tier.to_csv(BY_TIER_OUT, index=False)
    print("\n=== By liquidity tier ===")
    print(by_tier.to_string(index=False))

    by_category = summarize(metrics, "category")
    by_category.to_csv(BY_CATEGORY_OUT, index=False)
    print("\n=== By category ===")
    print(by_category.to_string(index=False))

    plot_convergence_by_tier(metrics)
    print(f"\nWrote figures -> {FIG_DIR}")


if __name__ == "__main__":
    main()
