"""Shared HTTP client with on-disk JSON caching and retry/backoff.

All Polymarket/ESPN pulls in this project go through `cached_get`, so a
rerun of any script hits the network only for cache misses. Raw responses
are stored under data/raw/<namespace>/ so the pipeline is reproducible
without re-hitting the live APIs.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw"

_session = requests.Session()
_session.headers.update(
    {"User-Agent": "polydrift-research/0.1 (+github.com/Junnie18/polymarket-resolution-drift)"}
)

# Minimum spacing between requests to any single host, to stay polite to
# free/public endpoints that have no API key and no documented rate limit.
_MIN_INTERVAL_SEC = 0.15
_last_request_ts: Dict[str, float] = {}


class FetchError(RuntimeError):
    pass


def _cache_key(url: str, params: Optional[Dict[str, Any]]) -> str:
    payload = json.dumps({"url": url, "params": params or {}}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def _throttle(host: str) -> None:
    now = time.monotonic()
    last = _last_request_ts.get(host, 0.0)
    wait = _MIN_INTERVAL_SEC - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_request_ts[host] = time.monotonic()


@retry(
    reraise=True,
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    retry=retry_if_exception_type((requests.exceptions.RequestException, FetchError)),
)
def _do_get(url: str, params: Optional[Dict[str, Any]], timeout: int) -> Dict[str, Any]:
    host = requests.utils.urlparse(url).netloc
    _throttle(host)
    resp = _session.get(url, params=params, timeout=timeout)
    if resp.status_code == 429 or resp.status_code >= 500:
        raise FetchError(f"retryable status {resp.status_code} for {url} params={params}")
    if resp.status_code == 422:
        # Gamma returns 422 with a JSON body (e.g. "offset too large, use
        # /markets/keyset for deeper pagination") for out-of-range paging
        # params. Treat as a normal (non-retryable) response body rather
        # than an exception, so callers can detect and stop paginating.
        return resp.json()
    resp.raise_for_status()
    return resp.json()


def cached_get(
    namespace: str,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
    force_refresh: bool = False,
) -> Any:
    """GET `url` with `params`, caching the JSON response to
    data/raw/<namespace>/<hash>.json. Returns the parsed JSON (cached or
    freshly fetched).
    """
    cache_dir = RAW_DIR / namespace
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _cache_key(url, params)
    cache_file = cache_dir / f"{key}.json"

    if cache_file.exists() and not force_refresh:
        with open(cache_file, "r") as f:
            return json.load(f)["body"]

    body = _do_get(url, params, timeout)
    with open(cache_file, "w") as f:
        json.dump({"url": url, "params": params, "body": body}, f)
    return body
