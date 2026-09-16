"""Convergence metrics for a resolved market's price series.

All functions operate on the *winning outcome's* price series (i.e. the
token whose price should end at ~1.0), so "converged" always means
"priced near 1.0 and stayed there."
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class ConvergenceMetrics:
    n_points: int
    window_start: pd.Timestamp
    window_end: pd.Timestamp
    coverage_frac: float  # fraction of expected 1-min bars actually present
    price_at_window_start: Optional[float]
    hours_to_converge_90: Optional[float]  # hours before resolution price permanently >= 0.90
    hours_to_converge_95: Optional[float]
    reverted_after_90: bool  # did price cross 0.90 then later drop back below it?
    reverted_after_95: bool
    in_uncertain_band_last6h: bool  # was price in [0.40, 0.60] at any point in final 6h?
    in_uncertain_band_last1h: bool
    min_price_last6h: Optional[float]
    max_abs_move_last6h: Optional[float]  # largest single-step |delta price| in final 6h


def _permanent_crossing_hours(df: pd.DataFrame, threshold: float, window_end) -> tuple:
    """Find the earliest index i such that price[i:] is entirely >= threshold.
    Returns (hours_before_resolution, reverted) where reverted indicates the
    series touched >= threshold at some earlier point and dropped back below
    it before the permanent crossing."""
    prices = df["price"].to_numpy()
    ts = df["timestamp"].to_numpy()
    n = len(prices)
    if n == 0:
        return None, False

    above = prices >= threshold
    # Find the last index where price is below threshold; permanent
    # crossing is the index right after that (or 0 if never below).
    below_idx = np.where(~above)[0]
    if len(below_idx) == 0:
        # always above threshold
        perm_idx = 0
    else:
        last_below = below_idx[-1]
        if last_below == n - 1:
            # still below threshold at resolution -> never converged
            return None, bool(above.any())
        perm_idx = last_below + 1

    reverted = bool(above[:perm_idx].any())
    crossing_ts = pd.Timestamp(ts[perm_idx])
    hours_before = (window_end - crossing_ts).total_seconds() / 3600.0
    return float(hours_before), reverted


def compute_metrics(
    price_df: pd.DataFrame,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
    expected_bar_minutes: int = 1,
) -> ConvergenceMetrics:
    """Compute convergence metrics for one market's winning-outcome price series.

    `price_df` must have columns [timestamp, price], already restricted to
    [window_start, window_end] (typically a 72h pre-resolution window).
    """
    df = price_df.sort_values("timestamp").reset_index(drop=True)
    n = len(df)
    expected_bars = max(1, int((window_end - window_start).total_seconds() / 60 / expected_bar_minutes))
    coverage = n / expected_bars

    price_at_start = float(df["price"].iloc[0]) if n else None

    h90, rev90 = _permanent_crossing_hours(df, 0.90, window_end)
    h95, rev95 = _permanent_crossing_hours(df, 0.95, window_end)

    last6h = df[df["timestamp"] >= window_end - pd.Timedelta(hours=6)]
    last1h = df[df["timestamp"] >= window_end - pd.Timedelta(hours=1)]

    in_band_6h = bool(((last6h["price"] >= 0.40) & (last6h["price"] <= 0.60)).any()) if len(last6h) else False
    in_band_1h = bool(((last1h["price"] >= 0.40) & (last1h["price"] <= 0.60)).any()) if len(last1h) else False
    min_last6h = float(last6h["price"].min()) if len(last6h) else None
    max_move_last6h = float(last6h["price"].diff().abs().max()) if len(last6h) > 1 else None

    return ConvergenceMetrics(
        n_points=n,
        window_start=window_start,
        window_end=window_end,
        coverage_frac=coverage,
        price_at_window_start=price_at_start,
        hours_to_converge_90=h90,
        hours_to_converge_95=h95,
        reverted_after_90=rev90,
        reverted_after_95=rev95,
        in_uncertain_band_last6h=in_band_6h,
        in_uncertain_band_last1h=in_band_1h,
        min_price_last6h=min_last6h,
        max_abs_move_last6h=max_move_last6h,
    )
