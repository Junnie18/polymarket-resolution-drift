"""Client for ESPN's public (unofficial, unauthenticated) site API.

Used as the "faster-moving external signal" for sports markets: ESPN's
live win-probability model updates in real time during a game and each
play carries a wall-clock timestamp, so it can be compared directly
against Polymarket's price series. This is an undocumented but widely
used public API (no key, no auth) — see e.g. site.api.espn.com.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from .http_cache import cached_get

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"

# Sports we support for the external-signal case study. Polymarket's
# "NBA: A vs. B" / "NFL: A vs. B" market naming maps onto these.
SPORT_PATHS = {
    "NBA": "basketball/nba",
    "NFL": "football/nfl",
}


def fetch_scoreboard(sport: str, date_yyyymmdd: str) -> Dict[str, Any]:
    path = SPORT_PATHS[sport]
    return cached_get(
        f"espn/scoreboard/{sport}",
        f"{BASE_URL}/{path}/scoreboard",
        params={"dates": date_yyyymmdd, "limit": 100},
    )


def fetch_summary(sport: str, event_id: str) -> Dict[str, Any]:
    path = SPORT_PATHS[sport]
    return cached_get(
        f"espn/summary/{sport}",
        f"{BASE_URL}/{path}/summary",
        params={"event": event_id},
    )


def list_events_for_date(sport: str, date_yyyymmdd: str) -> List[Dict[str, Any]]:
    """Return a simplified list of {id, home, away, date} for a scoreboard date."""
    data = fetch_scoreboard(sport, date_yyyymmdd)
    out = []
    for ev in data.get("events", []):
        competitions = ev.get("competitions", [])
        if not competitions:
            continue
        competitors = competitions[0].get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        out.append(
            {
                "id": ev["id"],
                "home": home.get("team", {}).get("displayName"),
                "away": away.get("team", {}).get("displayName"),
                "home_winner": home.get("winner"),
                "away_winner": away.get("winner"),
                "date": ev.get("date"),
                "status": ev.get("status", {}).get("type", {}).get("completed"),
            }
        )
    return out


def win_probability_timeseries(sport: str, event_id: str) -> Optional[pd.DataFrame]:
    """Join ESPN's `winprobability` array (per-play home win %) to the
    `plays` array (which carries wall-clock timestamps) via playId.

    Returns a DataFrame with columns [timestamp (UTC), home_win_prob], or
    None if this game doesn't have win-probability / wallclock data.
    """
    data = fetch_summary(sport, event_id)
    wp = data.get("winprobability")
    plays = data.get("plays")
    if not wp or not plays:
        return None
    play_wallclock = {p["id"]: p.get("wallclock") for p in plays if "id" in p}
    rows = []
    for entry in wp:
        play_id = entry.get("playId")
        wallclock = play_wallclock.get(play_id)
        if not wallclock:
            continue
        rows.append({"timestamp": wallclock, "home_win_prob": entry.get("homeWinPercentage")})
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.dropna(subset=["home_win_prob"]).sort_values("timestamp").reset_index(drop=True)
    return df
