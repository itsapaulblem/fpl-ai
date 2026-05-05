"""Client for the official Fantasy Premier League public API.

Endpoints documented (community):
- bootstrap-static/  : players, teams, events (gameweeks)
- fixtures/          : all fixtures
- element-summary/{player_id}/ : per-player history & upcoming fixtures
- entry/{team_id}/   : a manager's team metadata
- entry/{team_id}/event/{gw}/picks/ : a manager's GW picks
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import requests

BASE = "https://fantasy.premierleague.com/api"
DEFAULT_TIMEOUT = 20
USER_AGENT = "fpl-ai/0.1 (+https://github.com/yourname/fpl-ai)"


class FPLClient:
    def __init__(self, session: requests.Session | None = None, sleep: float = 0.2):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.sleep = sleep

    def _get(self, path: str) -> Any:
        url = f"{BASE}/{path.lstrip('/')}"
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        time.sleep(self.sleep)  # be polite
        return resp.json()

    # --- core endpoints ---
    def bootstrap(self) -> dict:
        """Players, teams, gameweeks, positions."""
        return self._get("bootstrap-static/")

    def fixtures(self) -> list[dict]:
        return self._get("fixtures/")

    def player_summary(self, player_id: int) -> dict:
        """Per-player gameweek history and upcoming fixtures."""
        return self._get(f"element-summary/{player_id}/")

    def manager_entry(self, team_id: int) -> dict:
        return self._get(f"entry/{team_id}/")

    def manager_picks(self, team_id: int, gw: int) -> dict:
        return self._get(f"entry/{team_id}/event/{gw}/picks/")


def current_gameweek(bootstrap: dict) -> int:
    """Return the current/next gameweek id from bootstrap data."""
    events = bootstrap["events"]
    for ev in events:
        if ev.get("is_current"):
            return ev["id"]
    for ev in events:
        if ev.get("is_next"):
            return ev["id"]
    return events[0]["id"]


def next_gameweek(bootstrap: dict) -> int:
    for ev in bootstrap["events"]:
        if ev.get("is_next"):
            return ev["id"]
    cur = current_gameweek(bootstrap)
    return min(cur + 1, 38)
