import pandas as pd

from polydrift.convergence import compute_metrics


def _series(prices, start="2024-01-01T00:00:00Z", freq="1min"):
    ts = pd.date_range(start=start, periods=len(prices), freq=freq, tz="UTC")
    return pd.DataFrame({"timestamp": ts, "price": prices})


def test_converges_and_stays():
    prices = [0.5, 0.6, 0.7, 0.92, 0.93, 0.95, 0.97, 0.99]
    df = _series(prices)
    window_start, window_end = df["timestamp"].iloc[0], df["timestamp"].iloc[-1]
    m = compute_metrics(df, window_start, window_end)
    assert m.hours_to_converge_90 is not None
    # crossed permanently at index 3 (0.92), resolution at index 7 -> 4 minutes before end
    assert abs(m.hours_to_converge_90 - 4 / 60) < 1e-6
    assert m.reverted_after_90 is False


def test_reverts_before_permanent_crossing():
    prices = [0.5, 0.92, 0.80, 0.93, 0.95, 0.97]
    df = _series(prices)
    window_start, window_end = df["timestamp"].iloc[0], df["timestamp"].iloc[-1]
    m = compute_metrics(df, window_start, window_end)
    assert m.hours_to_converge_90 is not None
    assert m.reverted_after_90 is True


def test_never_converges():
    prices = [0.5, 0.55, 0.45, 0.60, 0.50]
    df = _series(prices)
    window_start, window_end = df["timestamp"].iloc[0], df["timestamp"].iloc[-1]
    m = compute_metrics(df, window_start, window_end)
    assert m.hours_to_converge_90 is None


def test_uncertain_band_detection():
    prices = [0.9] * 10 + [0.5] + [0.9] * 5
    df = _series(prices)
    window_start, window_end = df["timestamp"].iloc[0], df["timestamp"].iloc[-1]
    m = compute_metrics(df, window_start, window_end)
    assert m.in_uncertain_band_last6h is True
    # last 1h = last 60 points, but we only have 16 total, so all counted
    assert m.in_uncertain_band_last1h is True


def test_empty_series():
    df = pd.DataFrame(columns=["timestamp", "price"])
    window_start = pd.Timestamp("2024-01-01", tz="UTC")
    window_end = pd.Timestamp("2024-01-04", tz="UTC")
    m = compute_metrics(df, window_start, window_end)
    assert m.n_points == 0
    assert m.hours_to_converge_90 is None
    assert m.price_at_window_start is None
