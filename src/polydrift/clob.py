"""Client for Polymarket's CLOB API price-history endpoint.

Public, unauthenticated REST API at https://clob.polymarket.com. No API
key exists or is required for `/prices-history`.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from .http_cache import cached_get

BASE_URL = "https://clob.polymarket.com"


def fetch_price_history(
    token_id: str,
    start_ts: int,
    end_ts: int,
    fidelity: int = 1,
) -> List[Dict[str, Any]]:
    """Fetch price history for a CLOB token between two unix timestamps.

    `fidelity` is in minutes (1 = minute-level, the finest Polymarket
    exposes). Returns a list of {"t": unix_ts, "p": price} dicts.
    """
    params = {
        "market": token_id,
        "startTs": start_ts,
        "endTs": end_ts,
        "fidelity": fidelity,
    }
    body = cached_get("clob/prices_history", f"{BASE_URL}/prices-history", params=params, timeout=30)
    return body.get("history", [])


def price_history_df(token_id: str, start_ts: int, end_ts: int, fidelity: int = 1) -> pd.DataFrame:
    """Fetch price history and return it as a DataFrame with columns
    [timestamp (UTC datetime), price (float)], sorted and deduplicated."""
    history = fetch_price_history(token_id, start_ts, end_ts, fidelity=fidelity)
    if not history:
        return pd.DataFrame(columns=["timestamp", "price"])
    df = pd.DataFrame(history)
    df["timestamp"] = pd.to_datetime(df["t"], unit="s", utc=True)
    df = df.rename(columns={"p": "price"})[["timestamp", "price"]]
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
    return df
