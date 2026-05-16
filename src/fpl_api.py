"""Client for the official Fantasy Premier League public API.

Wraps the four endpoints we explored in `notebooks/01_explore_api.ipynb`:

| Method                    | Endpoint                              | Returns                                      |
|---------------------------|---------------------------------------|----------------------------------------------|
| `bootstrap()`             | `bootstrap-static/`                   | players, teams, gameweeks, positions         |
| `fixtures()`              | `fixtures/`                           | every fixture with difficulty ratings        |
| `player_summary(pid)`     | `element-summary/{pid}/`              | one player's per-GW history + upcoming games |
| `manager_picks(tid, gw)`  | `entry/{tid}/event/{gw}/picks/`       | a manager's squad for a given GW             |

Plus two helpers — `current_gameweek()` and `next_gameweek()` — for finding
"what GW are we in right now?" without re-implementing the logic everywhere.
"""
from __future__ import annotations

import time
from typing import Any

import requests

BASE_URL = "https://fantasy.premierleague.com/api"
DEFAULT_TIMEOUT = 20  # seconds
USER_AGENT = "fpl-ai/0.1"


class FPLClient:
    """Tiny, polite wrapper over the FPL JSON API."""

    def __init__(
        self,
        session: requests.Session | None = None,
        sleep_between_calls: float = 0.2,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.sleep = sleep_between_calls
        self.timeout = timeout

    # Internal
    def _get(self, path: str) -> Any:
        url = f"{BASE_URL}/{path.lstrip('/')}"
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        if self.sleep:
            time.sleep(self.sleep)  # be polite — avoids rate limiting
        return resp.json()

    # Public endpoints
    def bootstrap(self) -> dict:
        """Static season data: ~600 players, 20 teams, 38 GWs, 4 positions."""
        return self._get("bootstrap-static/")

    def fixtures(self) -> list[dict]:
        """Every fixture in the season with home/away difficulty ratings."""
        return self._get("fixtures/")

    def player_summary(self, player_id: int) -> dict:
        """One player's `history` (this season per-GW) + `fixtures` (upcoming)
        + `history_past` (career season totals)."""
        return self._get(f"element-summary/{int(player_id)}/")

    def manager_entry(self, team_id: int) -> dict:
        """A manager's profile: name, region, overall rank, summary stats."""
        return self._get(f"entry/{int(team_id)}/")

    def manager_picks(self, team_id: int, gameweek: int) -> dict:
        """The 15 players a manager fielded in a given gameweek."""
        return self._get(f"entry/{int(team_id)}/event/{int(gameweek)}/picks/")

    def manager_transfers(self, team_id: int) -> list[dict]:
        """All transfers a manager has made this season (one row per transfer).

        Each row has `element_in`, `element_out`, `event` (the GW the transfer
        applies to), `time`, plus the buy/sell prices in tenths of £m.
        Pending transfers for the upcoming GW appear here as soon as they are
        confirmed in the FPL UI — *before* the deadline for that GW passes."""
        return self._get(f"entry/{int(team_id)}/transfers/")

    def manager_history(self, team_id: int) -> dict:
        """Per-GW results, past seasons, and `chips` already used this season."""
        return self._get(f"entry/{int(team_id)}/history/")

    def event_live(self, gw: int) -> dict:
        """Live/realised stats for every player in the given gameweek.
        Returns `{elements: [{id, stats: {total_points, minutes, ...}}]}`."""
        return self._get(f"event/{int(gw)}/live/")

    def classic_league_standings(self, league_id: int, page_standings: int = 1) -> dict:
        """Standings for a public/private classic league.

        Returns `{league: {...}, standings: {results: [{entry, entry_name,
        player_name, rank, total, ...}], has_next, page}, new_entries: {...}}`.
        """
        return self._get(
            f"leagues-classic/{int(league_id)}/standings/"
            f"?page_standings={int(page_standings)}"
        )


# Module-level helpers (don't need an instance)
def current_gameweek(bootstrap: dict) -> int:
    """Return the currently-live gameweek id, falling back to the next one
    (preseason) or 1 (everything else failed)."""
    events = bootstrap["events"]
    for ev in events:
        if ev.get("is_current"):
            return int(ev["id"])
    for ev in events:
        if ev.get("is_next"):
            return int(ev["id"])
    return int(events[0]["id"]) if events else 1


def next_gameweek(bootstrap: dict) -> int:
    """Return the upcoming gameweek id (the one we want to predict for)."""
    events = bootstrap["events"]
    for ev in events:
        if ev.get("is_next"):
            return int(ev["id"])
    cur = current_gameweek(bootstrap)
    return min(cur + 1, 38)
