"""Phase 9 — tests for historical (vaastav) loader.

We don't hit the network; instead we monkey-patch the season cache dir to a
tmp path and write toy CSVs that mirror vaastav's column layout.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src import historical as hist


# ---------------------------------------------------------------------- #
# Toy data builders
# ---------------------------------------------------------------------- #
def _toy_players(n: int = 6) -> pd.DataFrame:
    rows = []
    for i in range(1, n + 1):
        rows.append({
            "id": i,
            "first_name": f"F{i}",
            "second_name": f"L{i}",
            "web_name": f"P{i}",
            "team": (i % 3) + 1,        # 3 teams
            "element_type": ((i - 1) % 4) + 1,
            "now_cost": 50 + i,
        })
    return pd.DataFrame(rows)


def _toy_teams() -> pd.DataFrame:
    return pd.DataFrame([
        {"id": t, "name": f"Team{t}", "short_name": f"T{t}", "strength": 3,
         "strength_overall_home": 1100, "strength_overall_away": 1080,
         "strength_attack_home": 1100, "strength_attack_away": 1080,
         "strength_defence_home": 1100, "strength_defence_away": 1080}
        for t in (1, 2, 3)
    ])


def _toy_history(player_ids: list[int], n_gws: int = 8) -> pd.DataFrame:
    rows = []
    for pid in player_ids:
        for gw in range(1, n_gws + 1):
            rows.append({
                "element": pid,
                "GW": gw,
                "opponent_team": ((pid + gw) % 3) + 1,
                "was_home": gw % 2,
                "minutes": 60 + (pid + gw) % 30,
                "total_points": (pid + gw) % 10,
                "bps": 10 + (pid + gw) % 20,
                "ict_index": float(5 + (pid + gw) % 7),
                "value": 50 + pid,
                "expected_goal_involvements": 0.3,
                "expected_goals_conceded": 1.0,
                "goals_scored": 0,
                "assists": 0,
                "clean_sheets": 0,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------- #
# Fixture: fake cache dir with toy CSVs for two seasons
# ---------------------------------------------------------------------- #
@pytest.fixture
def fake_cache(tmp_path, monkeypatch):
    cache = tmp_path / "vaastav"
    monkeypatch.setattr(hist, "EXTERNAL_DIR", cache)

    seasons = ["2023-24", "2024-25"]
    for season in seasons:
        season_dir = cache / season
        season_dir.mkdir(parents=True)
        players = _toy_players()
        teams = _toy_teams()
        history = _toy_history(players["id"].tolist())
        players.to_csv(season_dir / "players_raw.csv", index=False)
        teams.to_csv(season_dir / "teams.csv", index=False)
        history.to_csv(season_dir / "merged_gw.csv", index=False)
    return cache, seasons


# ---------------------------------------------------------------------- #
# Tests
# ---------------------------------------------------------------------- #
def test_load_vaastav_season_normalises_schema(fake_cache):
    _, seasons = fake_cache
    data = hist.load_vaastav_season(seasons[0], download_if_missing=False)

    players = data["players"]
    history = data["history"]
    teams = data["teams"]

    # Renamed columns
    assert "player_id" in players.columns
    assert "player_id" in history.columns
    assert "round" in history.columns
    assert "team" in teams.columns

    # Position mapping
    assert set(players["position"].unique()).issubset({"GKP", "DEF", "MID", "FWD"})

    # Season tag added
    assert (history["season"] == seasons[0]).all()
    assert (players["season"] == seasons[0]).all()

    # Strength fields joined onto players
    assert "strength_overall_home" in players.columns


def test_download_skipped_when_cached(fake_cache, monkeypatch):
    _, seasons = fake_cache
    # If anything tries to fetch, raise loudly.
    def boom(*a, **kw):
        raise AssertionError("network call attempted but cache exists")
    monkeypatch.setattr(hist.requests, "get", boom)

    paths = hist.download_vaastav_season(seasons[0])
    assert all(p.exists() for p in paths.values())


def test_build_multi_season_training_concats_and_isolates(fake_cache):
    _, seasons = fake_cache
    df = hist.build_multi_season_training(seasons=seasons)

    assert not df.empty
    assert set(df["season"].unique()) == set(seasons)

    # Lag features must exist (proves _add_lag_features ran)
    assert any(c.endswith("_lag1") for c in df.columns)

    # Per-season isolation: a player_id appears in both seasons but lag rows
    # should never reference a different season's data — check by counting
    # GW1 rows: with lag1 dropped they should be absent from training.
    assert (df["round"] >= 2).all(), "GW1 rows should be dropped after lag-1 NaNs removed"


def test_build_with_current_season_appends(fake_cache):
    _, seasons = fake_cache

    # Build a tiny "current" history+players that look like our live cache
    cur_players = _toy_players(n=4)
    cur_players = cur_players.rename(columns={"id": "player_id"})
    cur_players["position"] = cur_players["element_type"].map({1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"})
    teams = _toy_teams().rename(columns={"id": "team", "name": "team_name"})
    cur_players = cur_players.merge(teams, on="team", how="left")

    cur_history = _toy_history(cur_players["player_id"].tolist(), n_gws=6)
    cur_history = cur_history.rename(columns={"element": "player_id", "GW": "round"})

    df = hist.build_multi_season_training(
        seasons=seasons,
        current_history=cur_history,
        current_players=cur_players,
        current_season_label="2025-26",
    )
    assert "2025-26" in set(df["season"].unique())
    assert set(df["season"].unique()) == set(seasons) | {"2025-26"}


def test_load_raises_without_cache_or_network(tmp_path, monkeypatch):
    monkeypatch.setattr(hist, "EXTERNAL_DIR", tmp_path / "empty")
    with pytest.raises(FileNotFoundError):
        hist.load_vaastav_season("2023-24", download_if_missing=False)
