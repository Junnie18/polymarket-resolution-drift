"""Client for Polymarket's Gamma API (market/event metadata).

Public, unauthenticated REST API at https://gamma-api.polymarket.com.
No API key exists or is required for the read endpoints used here.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .http_cache import cached_get

BASE_URL = "https://gamma-api.polymarket.com"


def fetch_markets_page(
    closed: bool = True,
    limit: int = 100,
    offset: int = 0,
    order: str = "volumeNum",
    ascending: bool = False,
    volume_num_min: Optional[float] = None,
    volume_num_max: Optional[float] = None,
    extra_params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Fetch one page of markets from the Gamma API."""
    params: Dict[str, Any] = {
        "closed": str(closed).lower(),
        "limit": limit,
        "offset": offset,
        "order": order,
        "ascending": str(ascending).lower(),
    }
    if volume_num_min is not None:
        params["volume_num_min"] = volume_num_min
    if volume_num_max is not None:
        params["volume_num_max"] = volume_num_max
    if extra_params:
        params.update(extra_params)
    return cached_get("gamma/markets", f"{BASE_URL}/markets", params=params)


def fetch_markets(
    closed: bool = True,
    order: str = "volumeNum",
    ascending: bool = False,
    volume_num_min: Optional[float] = None,
    volume_num_max: Optional[float] = None,
    max_results: int = 500,
    page_size: int = 100,
    extra_params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Fetch up to `max_results` markets, paginating through the Gamma API."""
    results: List[Dict[str, Any]] = []
    offset = 0
    while len(results) < max_results:
        page = fetch_markets_page(
            closed=closed,
            limit=page_size,
            offset=offset,
            order=order,
            ascending=ascending,
            volume_num_min=volume_num_min,
            volume_num_max=volume_num_max,
            extra_params=extra_params,
        )
        if not page or not isinstance(page, list):
            # Gamma returns a dict (e.g. {"error": "offset too large..."})
            # once offset exceeds its deep-pagination limit; stop cleanly.
            break
        results.extend(page)
        offset += page_size
        if len(page) < page_size:
            break
    return results[:max_results]


def parse_outcomes(market: Dict[str, Any]) -> Dict[str, Any]:
    """Parse a market's outcomes/prices/clobTokenIds JSON-string fields.

    Returns a dict with `outcomes` (list[str]), `outcome_prices` (list[float]),
    and `clob_token_ids` (list[str]), or empty lists if a field is malformed.
    """
    out: Dict[str, Any] = {"outcomes": [], "outcome_prices": [], "clob_token_ids": []}
    for key, field in (
        ("outcomes", "outcomes"),
        ("outcome_prices", "outcomePrices"),
        ("clob_token_ids", "clobTokenIds"),
    ):
        raw = market.get(field)
        if not raw:
            continue
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        out[key] = parsed
    return out


def winning_outcome_index(market: Dict[str, Any]) -> Optional[int]:
    """Return the index of the outcome that resolved TRUE (price ~1.0), or
    None if the market's final prices don't clearly show a winner (e.g.
    still-unsettled or malformed data)."""
    parsed = parse_outcomes(market)
    prices = parsed["outcome_prices"]
    if len(prices) < 2:
        return None
    try:
        prices_f = [float(p) for p in prices]
    except (TypeError, ValueError):
        return None
    best_idx = max(range(len(prices_f)), key=lambda i: prices_f[i])
    if prices_f[best_idx] < 0.98:
        return None
    return best_idx
