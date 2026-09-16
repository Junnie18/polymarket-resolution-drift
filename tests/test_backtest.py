import pandas as pd
import pytest

from polydrift.backtest import (
    TIGHT_SPREAD_MODEL,
    SlippageModel,
    backtest_market,
    find_entry,
    summarize_trades,
)


def _series(prices, start="2024-01-01T00:00:00Z", freq="1h"):
    ts = pd.date_range(start=start, periods=len(prices), freq=freq, tz="UTC")
    return pd.DataFrame({"timestamp": ts, "price": prices})


def test_find_entry_detects_band_crossing():
    # winning-outcome price rises from 0.5 to 0.99 over the window
    prices = [0.50, 0.60, 0.70, 0.90, 0.99]
    df = _series(prices)
    resolution_time = df["timestamp"].iloc[-1]
    entry = find_entry(df, resolution_time, window_hours=10, entry_low=0.55, entry_high=0.85)
    assert entry is not None
    assert entry["favorite_price"] == pytest.approx(0.60)
    assert entry["favorite_is_winner"] is True or entry["favorite_is_winner"] == True  # noqa: E712


def test_find_entry_none_when_never_in_band():
    prices = [0.50, 0.50, 0.51, 0.99]
    df = _series(prices)
    resolution_time = df["timestamp"].iloc[-1]
    entry = find_entry(df, resolution_time, window_hours=10, entry_low=0.55, entry_high=0.85)
    assert entry is None


def test_find_entry_captures_favorite_when_winner_is_underdog():
    # winning outcome trades at 0.3 (an underdog win) -> favorite price is
    # 0.7 on the LOSING side; a favorite-momentum entry here would buy the
    # loser and take a full loss.
    prices = [0.30, 0.30, 0.30]
    df = _series(prices)
    resolution_time = df["timestamp"].iloc[-1]
    entry = find_entry(df, resolution_time, window_hours=10, entry_low=0.55, entry_high=0.85)
    assert entry is not None
    assert entry["favorite_price"] == pytest.approx(0.70)
    assert bool(entry["favorite_is_winner"]) is False


def test_slippage_model_widens_with_smaller_liquidity_and_larger_stake():
    model = SlippageModel(half_spread_by_tier={"flagship": 0.01, "niche": 0.05})
    cheap = model.execution_price(0.5, "flagship", stake=100, volume_proxy=1_000_000)
    thin = model.execution_price(0.5, "niche", stake=100, volume_proxy=1_000)
    assert cheap > 0.5
    assert thin > cheap


def test_backtest_market_loses_full_stake_on_upset():
    # favorite (0.7) is priced on the losing side the whole time
    prices = [0.30] * 5
    df = _series(prices)
    resolution_time = df["timestamp"].iloc[-1]
    trade = backtest_market(
        "m1", "flagship", "Politics", 1_000_000, df, resolution_time,
        TIGHT_SPREAD_MODEL, stake=100, window_hours=10, entry_low=0.55, entry_high=0.85,
    )
    assert trade is not None
    assert trade.favorite_won is False
    assert trade.payout == 0.0
    assert trade.pnl == -100.0


def test_backtest_market_profits_when_favorite_wins():
    prices = [0.60] * 5
    df = _series(prices)
    resolution_time = df["timestamp"].iloc[-1]
    trade = backtest_market(
        "m2", "flagship", "Politics", 1_000_000, df, resolution_time,
        TIGHT_SPREAD_MODEL, stake=100, window_hours=10, entry_low=0.55, entry_high=0.85,
    )
    assert trade is not None
    assert trade.favorite_won is True
    assert trade.pnl > 0


def test_summarize_trades_empty():
    assert summarize_trades(pd.DataFrame()) == {}
