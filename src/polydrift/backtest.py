"""Backtest a "late-game correction" strategy on the resolution-drift
pattern documented in convergence.py: buy the crowd-favorite outcome when
it's already leaning (>55%) but hasn't fully converged (<85%) in the
final 72h, hold to resolution, and see whether the eventual convergence
pays for the spread/impact of getting in.

The strategy uses only information available at trade time -- it looks
at whichever side is priced higher right now, not which side actually
wins. It can and does lose money outright on entries where the crowd's
leader at trade time turns out to lose (upsets): that is real risk, not
hindsight.

IMPORTANT DATA LIMITATION: Polymarket's public CLOB API does not expose
historical order-book depth or trade-level fills for resolved markets
(verified: /book 404s for closed markets, /trades requires an API key we
don't have). There is therefore no way to *measure* historical bid-ask
spread or slippage here -- it must be *modeled*. The SlippageModel below
is a documented, parameterized assumption (tier-based half-spread + a
square-root market-impact term keyed to trade size relative to the
market's lifetime volume as a liquidity proxy), not measured data. We run
the backtest under multiple spread scenarios (see script 06) to show how
sensitive the results are to this assumption, rather than presenting a
single number as ground truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd


@dataclass
class SlippageModel:
    """Executed price = quoted_price + half_spread + impact, where impact
    grows with sqrt(stake / liquidity_proxy). half_spread is in price
    units (e.g. 0.01 = 1 cent) and varies by liquidity tier."""

    half_spread_by_tier: Dict[str, float]
    # tuned so a $100 stake in a ~$1k-volume niche market has a few-cent impact
    impact_coefficient: float = 0.02

    def execution_price(self, quoted_price: float, tier: str, stake: float, volume_proxy: float) -> float:
        half_spread = self.half_spread_by_tier.get(tier, self.half_spread_by_tier["niche"])
        liquidity_proxy = max(volume_proxy, 100.0)  # floor to avoid division blow-ups on ~$0 volume markets
        impact = self.impact_coefficient * np.sqrt(stake / liquidity_proxy)
        exec_price = quoted_price + half_spread + impact
        return float(min(exec_price, 0.995))  # can't pay more than ~par for a binary contract


TIGHT_SPREAD_MODEL = SlippageModel(half_spread_by_tier={"flagship": 0.005, "mid": 0.015, "niche": 0.03})
WIDE_SPREAD_MODEL = SlippageModel(half_spread_by_tier={"flagship": 0.015, "mid": 0.04, "niche": 0.08})


@dataclass
class Trade:
    market_id: str
    liquidity_tier: str
    category: Optional[str]
    entry_timestamp: pd.Timestamp
    hours_before_resolution: float
    quoted_price: float
    exec_price: float
    favorite_won: bool  # did the side we bought (the favorite at entry time) end up winning?
    stake: float
    payout: float
    pnl: float
    return_pct: float


def find_entry(
    price_df: pd.DataFrame,
    resolution_time: pd.Timestamp,
    window_hours: float = 72.0,
    entry_low: float = 0.55,
    entry_high: float = 0.85,
) -> Optional[pd.Series]:
    """Find the first bar, scanning forward from window start, where the
    *favorite* (max(price, 1-price)) sits in [entry_low, entry_high].
    price_df holds the WINNING outcome's price; the favorite may or may
    not be the winner at any given instant. Returns a row with an added
    'favorite_price' and 'favorite_is_winner' column, or None if the
    favorite never sits in the band during the window."""
    if price_df.empty:
        return None
    window_start = resolution_time - pd.Timedelta(hours=window_hours)
    df = price_df[(price_df["timestamp"] >= window_start) & (price_df["timestamp"] <= resolution_time)].copy()
    if df.empty:
        return None
    df["favorite_price"] = df["price"].clip(lower=1 - df["price"])
    df["favorite_is_winner"] = df["price"] >= 0.5
    mask = (df["favorite_price"] >= entry_low) & (df["favorite_price"] <= entry_high)
    hits = df[mask]
    if hits.empty:
        return None
    return hits.iloc[0]


def backtest_market(
    market_id: str,
    liquidity_tier: str,
    category: Optional[str],
    volume_num: float,
    price_df: pd.DataFrame,
    resolution_time: pd.Timestamp,
    slippage_model: SlippageModel,
    stake: float = 100.0,
    window_hours: float = 72.0,
    entry_low: float = 0.55,
    entry_high: float = 0.85,
) -> Optional[Trade]:
    entry = find_entry(price_df, resolution_time, window_hours, entry_low, entry_high)
    if entry is None:
        return None

    quoted_price = float(entry["favorite_price"])
    favorite_won = bool(entry["favorite_is_winner"])
    exec_price = slippage_model.execution_price(quoted_price, liquidity_tier, stake, volume_num)

    shares = stake / exec_price
    payout = shares * 1.0 if favorite_won else 0.0
    pnl = payout - stake
    return_pct = pnl / stake

    hours_before = (resolution_time - entry["timestamp"]).total_seconds() / 3600.0

    return Trade(
        market_id=market_id,
        liquidity_tier=liquidity_tier,
        category=category,
        entry_timestamp=entry["timestamp"],
        hours_before_resolution=hours_before,
        quoted_price=quoted_price,
        exec_price=exec_price,
        favorite_won=favorite_won,
        stake=stake,
        payout=payout,
        pnl=pnl,
        return_pct=return_pct,
    )


def summarize_trades(trades: pd.DataFrame) -> Dict[str, float]:
    if trades.empty:
        return {}
    n = len(trades)
    win_rate = (trades["pnl"] > 0).mean()
    total_pnl = trades["pnl"].sum()
    total_stake = trades["stake"].sum()
    roi = total_pnl / total_stake if total_stake else float("nan")
    mean_ret = trades["return_pct"].mean()
    std_ret = trades["return_pct"].std(ddof=1) if n > 1 else float("nan")
    sharpe_like = mean_ret / std_ret if std_ret and not np.isnan(std_ret) and std_ret > 0 else float("nan")

    sorted_pnl = trades.sort_values("entry_timestamp")["pnl"]
    equity = sorted_pnl.cumsum() + total_stake / n if n else pd.Series(dtype=float)
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max.replace(0, np.nan)
    max_drawdown = drawdown.min() if len(drawdown) else float("nan")

    return {
        "n_trades": n,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "total_stake": total_stake,
        "roi": roi,
        "mean_return_pct": mean_ret,
        "std_return_pct": std_ret,
        "sharpe_like": sharpe_like,
        "max_drawdown_pct": max_drawdown,
    }
