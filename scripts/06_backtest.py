#!/usr/bin/env python3
"""Run the late-game-correction backtest across the full sample (core
market_sample.csv + the NBA moneyline sample) under both a tight and a
wide spread/impact assumption, and report risk-adjusted results by
liquidity tier and category.

Writes:
  - data/processed/backtest_trades_tight.csv / _wide.csv
  - data/processed/backtest_summary.csv
  - docs/figures/backtest_equity_curve.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polydrift.backtest import (  # noqa: E402
    TIGHT_SPREAD_MODEL,
    WIDE_SPREAD_MODEL,
    backtest_market,
    summarize_trades,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = REPO_ROOT / "data" / "processed" / "market_sample.csv"
NBA_PATH = REPO_ROOT / "data" / "processed" / "nba_markets.csv"
SERIES_DIR = REPO_ROOT / "data" / "processed" / "price_series"
FIG_DIR = REPO_ROOT / "docs" / "figures"

STAKE = 100.0
WINDOW_HOURS = 72.0
ENTRY_LOW = 0.55
ENTRY_HIGH = 0.85


def load_universe() -> pd.DataFrame:
    core = pd.read_csv(SAMPLE_PATH)[["market_id", "liquidity_tier", "category", "volume_num", "closed_time"]]
    nba = pd.read_csv(NBA_PATH)[["market_id", "liquidity_tier", "volume_num", "closed_time"]]
    nba["category"] = "Sports (NBA)"
    combined = pd.concat([core, nba], ignore_index=True).drop_duplicates(subset="market_id")
    return combined


def run(universe: pd.DataFrame, slippage_model) -> pd.DataFrame:
    trades = []
    for _, row in universe.iterrows():
        series_path = SERIES_DIR / f"{row['market_id']}.csv"
        if not series_path.exists():
            continue
        price_df = pd.read_csv(series_path, parse_dates=["timestamp"])
        if price_df.empty:
            continue
        price_df["timestamp"] = pd.to_datetime(price_df["timestamp"], utc=True)
        resolution_time = pd.Timestamp(row["closed_time"])
        if resolution_time.tzinfo is None:
            resolution_time = resolution_time.tz_localize("UTC")

        trade = backtest_market(
            market_id=row["market_id"],
            liquidity_tier=row["liquidity_tier"],
            category=row["category"],
            volume_num=row["volume_num"],
            price_df=price_df,
            resolution_time=resolution_time,
            slippage_model=slippage_model,
            stake=STAKE,
            window_hours=WINDOW_HOURS,
            entry_low=ENTRY_LOW,
            entry_high=ENTRY_HIGH,
        )
        if trade is not None:
            trades.append(trade.__dict__)
    return pd.DataFrame(trades)


def plot_equity_curves(tight_trades: pd.DataFrame, wide_trades: pd.DataFrame) -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 5))
    curves = [("tight spread", tight_trades, "#2a6f97"), ("wide spread", wide_trades, "#c1121f")]
    for label, trades, color in curves:
        if trades.empty:
            continue
        sorted_trades = trades.sort_values("entry_timestamp")
        equity = sorted_trades["pnl"].cumsum()
        ax.plot(range(len(equity)), equity.values, label=f"{label} (n={len(trades)})", color=color)
    ax.axhline(0, color="black", linewidth=0.8, linestyle="--")
    ax.set_xlabel("Trade # (ordered by entry time)")
    ax.set_ylabel("Cumulative P&L ($, $100 stake/trade)")
    ax.set_title("Late-game correction strategy: cumulative P&L")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "backtest_equity_curve.png", dpi=150)
    plt.close(fig)


def main() -> None:
    universe = load_universe()
    print(f"Backtest universe: {len(universe)} markets")

    summaries = []
    all_trades = {}
    for label, model in [("tight", TIGHT_SPREAD_MODEL), ("wide", WIDE_SPREAD_MODEL)]:
        trades = run(universe, model)
        all_trades[label] = trades
        out_path = REPO_ROOT / "data" / "processed" / f"backtest_trades_{label}.csv"
        trades.to_csv(out_path, index=False)
        print(f"\n=== {label.upper()} spread scenario: {len(trades)} trades ===")

        overall = summarize_trades(trades)
        overall["scenario"] = label
        overall["cut"] = "overall"
        summaries.append(overall)
        print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in overall.items()})

        for tier, g in trades.groupby("liquidity_tier"):
            s = summarize_trades(g)
            s["scenario"] = label
            s["cut"] = f"tier:{tier}"
            summaries.append(s)

        for cat, g in trades.groupby("category"):
            s = summarize_trades(g)
            s["scenario"] = label
            s["cut"] = f"category:{cat}"
            summaries.append(s)

    summary_df = pd.DataFrame(summaries)
    summary_df.to_csv(REPO_ROOT / "data" / "processed" / "backtest_summary.csv", index=False)
    print("\n=== Summary (tight scenario, by tier) ===")
    tight_summary = summary_df[(summary_df["scenario"] == "tight") & summary_df["cut"].str.startswith("tier")]
    print(tight_summary.to_string(index=False))

    print("\n=== Summary (wide scenario, by tier) ===")
    wide_summary = summary_df[(summary_df["scenario"] == "wide") & summary_df["cut"].str.startswith("tier")]
    print(wide_summary.to_string(index=False))

    plot_equity_curves(all_trades["tight"], all_trades["wide"])
    print(f"\nWrote figure -> {FIG_DIR / 'backtest_equity_curve.png'}")


if __name__ == "__main__":
    main()
