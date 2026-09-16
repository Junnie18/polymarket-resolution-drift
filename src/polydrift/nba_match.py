"""Match Polymarket NBA moneyline markets to ESPN game events.

Polymarket's question text is "TeamA vs. TeamB" using team nicknames only
(e.g. "Spurs vs. Knicks"); ESPN's scoreboard gives full display names
(e.g. "San Antonio Spurs"). We match by nickname substring on ESPN's
scoreboard for the game date encoded in the Polymarket slug (+/- 1 day,
since a market's nominal "game date" can shift across a UTC day boundary
for late tip-offs).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

import pandas as pd

from . import espn


def _nickname(team_phrase: str) -> str:
    return team_phrase.strip()


def parse_question_teams(question: str) -> Optional[tuple]:
    """Split 'TeamA vs. TeamB' into (team_a, team_b) nicknames."""
    m = re.match(r"^(.+?)\s+vs\.?\s+(.+)$", question.strip())
    if not m:
        return None
    return _nickname(m.group(1)), _nickname(m.group(2))


def find_matching_espn_event(
    question: str, game_date_slug: str, sport: str = "NBA"
) -> Optional[Dict[str, Any]]:
    """Search ESPN scoreboard around `game_date_slug` for an event whose
    home/away display names contain the two team nicknames parsed from
    `question`. Returns the matched event dict (from
    espn.list_events_for_date) or None."""
    teams = parse_question_teams(question)
    if teams is None:
        return None
    nick_a, nick_b = teams

    base_date = pd.Timestamp(game_date_slug)
    candidates = []
    for delta_days in (0, -1, 1):
        d = (base_date + pd.Timedelta(days=delta_days)).strftime("%Y%m%d")
        try:
            events = espn.list_events_for_date(sport, d)
        except Exception:  # noqa: BLE001
            continue
        candidates.extend(events)

    for ev in candidates:
        home, away = ev.get("home") or "", ev.get("away") or ""
        names = f"{home} {away}"
        if nick_a.lower() in names.lower() and nick_b.lower() in names.lower():
            return ev
    return None


def winner_win_probability(wp_df: pd.DataFrame, home_won: bool) -> pd.DataFrame:
    """Convert ESPN's home_win_prob series into "probability assigned to the
    team that actually won" -- directly comparable to a Polymarket winning-
    outcome price series."""
    out = wp_df.copy()
    if home_won:
        out["winner_win_prob"] = out["home_win_prob"]
    else:
        out["winner_win_prob"] = 1 - out["home_win_prob"]
    return out
