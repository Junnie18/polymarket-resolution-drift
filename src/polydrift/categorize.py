"""Heuristic keyword-based categorization of Polymarket markets.

The Gamma API's per-market `category` field is almost always null for
closed markets (verified empirically: 499/500 top-volume closed markets
had category=None), and per-event tags require a separate API call per
event. Rather than pay that cost for every sampled market, we classify by
keyword match on the question text. This is a heuristic, not ground
truth -- documented as a limitation in docs/findings.md.
"""
from __future__ import annotations

import re
from typing import Dict, List

CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "Sports": [
        "nba", "nfl", "nhl", "mlb", "ncaa", "soccer", "football", "basketball",
        "baseball", "hockey", "tennis", "golf", "ufc", "mma", "boxing",
        "world cup", "olympics", "champions league", "premier league", "f1",
        "formula 1", " vs. ", " vs ", "super bowl", "world series", "playoffs",
        "wimbledon", "grand slam", "PGA",
    ],
    "Crypto": [
        "bitcoin", "btc", "ethereum", "eth ", "crypto", "solana", "dogecoin",
        "altcoin", "stablecoin", "defi", "nft", "binance", "coinbase",
    ],
    "Politics": [
        "election", "president", "presidential", "congress", "senate",
        "governor", "prime minister", "parliament", "democrat", "republican",
        "vote", "poll", "nominee", "impeach", "cabinet", "supreme court",
        "referendum", "prime minister", "chancellor", "mayor",
    ],
    "Economy/Business": [
        "fed ", "federal reserve", "interest rate", "inflation", "gdp",
        "recession", "stock", "s&p", "nasdaq", "dow jones", "earnings",
        "cpi", "unemployment", "ipo", "bankruptcy", "tariff", "jobs report",
    ],
    "Entertainment/Culture": [
        "movie", "oscar", "grammy", "box office", "album", "celebrity",
        "netflix", "taylor swift", "actor", "actress", "tv show", "season finale",
    ],
    "Science/Tech": [
        "openai", "spacex", "nasa", "launch", "vaccine", "ai model", "gpt-",
        "artificial intelligence", "chatgpt", "rocket",
    ],
}

_COMPILED = {
    cat: [re.compile(re.escape(kw), re.IGNORECASE) for kw in kws]
    for cat, kws in CATEGORY_KEYWORDS.items()
}


def classify(question: str) -> str:
    """Return the first matching category for a market question, or 'Other'."""
    if not question:
        return "Other"
    for cat, patterns in _COMPILED.items():
        for pat in patterns:
            if pat.search(question):
                return cat
    return "Other"
