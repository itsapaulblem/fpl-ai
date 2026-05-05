"""Phase 9 — Historical data loader (vaastav/Fantasy-Premier-League).

Pulls per-gameweek player history from prior seasons so we can train on
multi-season data. The current season alone gives ~26k training rows;
adding 3 historical seasons quadruples that.

Data source:
    https://github.com/vaastav/Fantasy-Premier-League
    Per season we need:
        data/{season}/players_raw.csv     - player metadata
        data/{season}/gws/merged_gw.csv   - all per-GW rows for the season
        data/{season}/teams.csv           - team strength ratings

Vaastav files are cached to data/external/vaastav/{season}/ after first
download (gitignored). Season strings: '2022-23', '2023-24', '2024-25'.

Why per-season grouping for lag features:
    Player ids are reassigned each season — Haaland is element 318 in
    2022-23 and 355 in 2023-24. We treat (season, player_id) as the lag
    grouping key so a player's GW1 history never accidentally rolls into
    another season's stats.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd
import requests

from .data_loader import (
    DATA_DIR,
    LAG_FEATURES,
    _add_lag_features,
)

VAASTAV_RAW = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"
EXTERNAL_DIR = DATA_DIR / "external" / "vaastav"

# Files we need from each season's data folder.
SEASON_FILES = {
    "players": "players_raw.csv",
    "history": "gws/merged_gw.csv",
    "teams": "teams.csv",
}


# ---------------------------------------------------------------------- #
# Download
# ---------------------------------------------------------------------- #
def _season_dir(season: str) -> Path:
    return EXTERNAL_DIR / season


def download_vaastav_season(season: str, force: bool = False) -> dict[str, Path]:
    """Download the three CSVs we need for one season into the cache."""
    out_dir = _season_dir(season)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    for key, rel in SEASON_FILES.items():
        local = out_dir / Path(rel).name  # flatten gws/merged_gw.csv -> merged_gw.csv
        if local.exists() and not force:
            paths[key] = local
            continue
        url = f"{VAASTAV_RAW}/{season}/{rel}"
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        local.write_bytes(resp.content)
        paths[key] = local
    return paths


# ---------------------------------------------------------------------- #
# Schema normalisation — vaastav columns vary by season
# ---------------------------------------------------------------------- #
HISTORY_RENAMES = {
    "element": "player_id",
    "GW": "round",  # some seasons capitalise it
}

# Columns we want from history; NaNs are fine (older seasons lack `expected_*`)
HISTORY_KEEP = [
    "player_id", "round", "opponent_team", "was_home", "minutes",
    "total_points", "bps", "ict_index", "value",
    "expected_goal_involvements", "expected_goals_conceded",
    "goals_scored", "assists", "clean_sheets",
]

PLAYERS_KEEP = [
    "id", "first_name", "second_name", "web_name", "team",
    "element_type", "now_cost",
]

TEAMS_KEEP = [
    "id", "name", "short_name", "strength",
    "strength_overall_home", "strength_overall_away",
    "strength_attack_home", "strength_attack_away",
    "strength_defence_home", "strength_defence_away",
]

POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def load_vaastav_season(season: str, download_if_missing: bool = True) -> dict[str, pd.DataFrame]:
    """Return a `{players, history, teams}` dict for one historical season,
    with column names normalised to match `data_loader.players_frame()`."""
    paths = {k: _season_dir(season) / Path(v).name for k, v in SEASON_FILES.items()}
    if not all(p.exists() for p in paths.values()):
        if not download_if_missing:
            raise FileNotFoundError(f"No cached vaastav data for {season}.")
        paths = download_vaastav_season(season)

    # ---- players ----
    players_raw = pd.read_csv(paths["players"])
    keep = [c for c in PLAYERS_KEEP if c in players_raw.columns]
    players = players_raw[keep].rename(columns={"id": "player_id"})
    players["position"] = players["element_type"].map(POSITION_MAP)
    if "now_cost" in players.columns:
        players["price"] = players["now_cost"] / 10.0

    # ---- teams ----
    teams_raw = pd.read_csv(paths["teams"])
    keep = [c for c in TEAMS_KEEP if c in teams_raw.columns]
    teams = teams_raw[keep].rename(columns={"id": "team", "name": "team_name"})

    # Join team metadata + strength fields onto players
    players = players.merge(teams, on="team", how="left")

    # ---- history ----
    history_raw = pd.read_csv(paths["history"], low_memory=False)
    # Only rename source columns whose target doesn't already exist (avoids dup cols).
    safe_renames = {k: v for k, v in HISTORY_RENAMES.items()
                    if k in history_raw.columns and v not in history_raw.columns}
    history_raw = history_raw.rename(columns=safe_renames)
    # Drop any duplicate-named columns (keep first).
    history_raw = history_raw.loc[:, ~history_raw.columns.duplicated()]
    keep = [c for c in HISTORY_KEEP if c in history_raw.columns]
    history = history_raw[keep].copy()

    history["season"] = season
    players["season"] = season

    return {"players": players, "history": history, "teams": teams}


# ---------------------------------------------------------------------- #
# Multi-season training assembly
# ---------------------------------------------------------------------- #
def _build_one_season_training(history: pd.DataFrame, players: pd.DataFrame) -> pd.DataFrame:
    """Per-season equivalent of `data_loader.build_training_set`, but groups
    lag features by (season, player_id) so seasons stay isolated."""
    if history.empty:
        return history.copy()

    df = history.copy()

    numeric = LAG_FEATURES + [
        "value", "was_home", "round", "opponent_team",
        "goals_scored", "assists", "clean_sheets",
    ]
    for c in numeric:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.sort_values(["season", "player_id", "round"]).reset_index(drop=True)
    df = _add_lag_features(df, group_cols=["season", "player_id"])

    # Static joins
    static = [
        "player_id", "season", "team", "element_type", "position",
        "strength_attack_home", "strength_attack_away",
        "strength_defence_home", "strength_defence_away",
        "strength_overall_home", "strength_overall_away",
    ]
    static = [c for c in static if c in players.columns]
    df = df.merge(players[static], on=["player_id", "season"], how="left")

    if {"team", "strength"}.issubset(players.columns):
        opp = (players[["season", "team", "strength"]]
               .drop_duplicates()
               .rename(columns={"team": "opponent_team", "strength": "opp_strength"}))
        df = df.merge(opp, on=["season", "opponent_team"], how="left")

    df["is_home"] = df["was_home"].astype("Int64") if "was_home" in df.columns else 0
    df["target_points"] = df["total_points"]

    first_lag = f"{LAG_FEATURES[0]}_lag1"
    if first_lag in df.columns:
        df = df.dropna(subset=[first_lag]).reset_index(drop=True)
    return df


def build_multi_season_training(
    seasons: Iterable[str],
    current_history: pd.DataFrame | None = None,
    current_players: pd.DataFrame | None = None,
    current_season_label: str = "current",
) -> pd.DataFrame:
    """Stitch together training rows from each historical season + current.

    Each season is processed independently (lags grouped within season) then
    concatenated. The `season` column is preserved so you can do per-season
    validation if you want.
    """
    parts: list[pd.DataFrame] = []

    for season in seasons:
        data = load_vaastav_season(season)
        part = _build_one_season_training(data["history"], data["players"])
        parts.append(part)

    if current_history is not None and current_players is not None:
        cur_h = current_history.copy()
        cur_p = current_players.copy()
        cur_h["season"] = current_season_label
        cur_p["season"] = current_season_label
        parts.append(_build_one_season_training(cur_h, cur_p))

    combined = pd.concat(parts, ignore_index=True, sort=False)
    return combined


__all__ = [
    "VAASTAV_RAW",
    "EXTERNAL_DIR",
    "download_vaastav_season",
    "load_vaastav_season",
    "build_multi_season_training",
]
