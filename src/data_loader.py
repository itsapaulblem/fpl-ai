"""Build training and inference datasets from the FPL API."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from tqdm import tqdm

from .fpl_api import FPLClient, current_gameweek

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
RAW_DIR = DATA_DIR / "raw"
PROC_DIR = DATA_DIR / "processed"


def _ensure_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROC_DIR.mkdir(parents=True, exist_ok=True)


def fetch_bootstrap(client: FPLClient | None = None) -> dict:
    _ensure_dirs()
    client = client or FPLClient()
    boot = client.bootstrap()
    return boot


def players_frame(bootstrap: dict) -> pd.DataFrame:
    """Static player table joined with team & position names."""
    teams = pd.DataFrame(bootstrap["teams"])[
        ["id", "name", "short_name", "strength",
         "strength_overall_home", "strength_overall_away",
         "strength_attack_home", "strength_attack_away",
         "strength_defence_home", "strength_defence_away"]
    ].rename(columns={"id": "team", "name": "team_name"})

    positions = pd.DataFrame(bootstrap["element_types"])[
        ["id", "singular_name_short"]
    ].rename(columns={"id": "element_type", "singular_name_short": "position"})

    players = pd.DataFrame(bootstrap["elements"])
    keep = [
        "id", "web_name", "first_name", "second_name",
        "team", "element_type", "now_cost", "selected_by_percent",
        "form", "points_per_game", "minutes", "total_points",
        "goals_scored", "assists", "clean_sheets", "goals_conceded",
        "saves", "bonus", "bps", "influence", "creativity", "threat",
        "ict_index", "expected_goals", "expected_assists",
        "expected_goal_involvements", "expected_goals_conceded",
        "status", "chance_of_playing_next_round",
    ]
    keep = [c for c in keep if c in players.columns]
    players = players[keep].rename(columns={"id": "player_id"})
    players["price"] = players["now_cost"] / 10.0
    players = players.merge(teams, on="team", how="left")
    players = players.merge(positions, on="element_type", how="left")

    # numeric coercion
    for c in ["form", "points_per_game", "selected_by_percent",
              "influence", "creativity", "threat", "ict_index",
              "expected_goals", "expected_assists",
              "expected_goal_involvements", "expected_goals_conceded"]:
        if c in players.columns:
            players[c] = pd.to_numeric(players[c], errors="coerce")
    return players


def fetch_player_histories(
    bootstrap: dict,
    client: FPLClient | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """Fetch every player's per-GW history for the current season.

    Returns a long DataFrame keyed by (player_id, round).
    """
    client = client or FPLClient()
    rows: list[dict] = []
    elements = bootstrap["elements"]
    if limit:
        elements = elements[:limit]
    for el in tqdm(elements, desc="player histories"):
        pid = el["id"]
        try:
            summary = client.player_summary(pid)
        except Exception:
            continue
        for h in summary.get("history", []):
            h["player_id"] = pid
            rows.append(h)
    df = pd.DataFrame(rows)
    return df


def fetch_fixtures(client: FPLClient | None = None) -> pd.DataFrame:
    client = client or FPLClient()
    fx = pd.DataFrame(client.fixtures())
    return fx


def upcoming_fixtures(
    fixtures: pd.DataFrame, players: pd.DataFrame, next_gw: int, horizon: int = 1
) -> pd.DataFrame:
    """For each player, build their next `horizon` fixtures with difficulty."""
    fx = fixtures.copy()
    fx = fx[(fx["event"] >= next_gw) & (fx["event"] < next_gw + horizon)]
    home = fx.rename(columns={
        "team_h": "team", "team_a": "opponent",
        "team_h_difficulty": "difficulty", "team_a_difficulty": "opp_difficulty",
    })[["event", "team", "opponent", "difficulty", "opp_difficulty"]]
    home["is_home"] = 1
    away = fx.rename(columns={
        "team_a": "team", "team_h": "opponent",
        "team_a_difficulty": "difficulty", "team_h_difficulty": "opp_difficulty",
    })[["event", "team", "opponent", "difficulty", "opp_difficulty"]]
    away["is_home"] = 0
    team_fx = pd.concat([home, away], ignore_index=True)

    out = players.merge(team_fx, on="team", how="left")
    return out


def save_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(path, index=False)
    except Exception:
        # Fall back to CSV if pyarrow not installed.
        df.to_csv(path.with_suffix(".csv"), index=False)


def build_training_set(
    history: pd.DataFrame,
    players: pd.DataFrame,
    fixtures: pd.DataFrame,
) -> pd.DataFrame:
    """Create supervised dataset: features known *before* the GW, label = total_points that GW."""
    if history.empty:
        return history

    h = history.copy()
    # Coerce numerics
    num_cols = [
        "minutes", "goals_scored", "assists", "clean_sheets", "goals_conceded",
        "saves", "bonus", "bps", "influence", "creativity", "threat", "ict_index",
        "expected_goals", "expected_assists", "expected_goal_involvements",
        "expected_goals_conceded", "total_points", "value", "was_home",
        "round", "opponent_team",
    ]
    for c in num_cols:
        if c in h.columns:
            h[c] = pd.to_numeric(h[c], errors="coerce")

    h = h.sort_values(["player_id", "round"]).reset_index(drop=True)

    # Lagged rolling features (use only past GWs)
    feats = ["minutes", "total_points", "bps", "ict_index",
             "expected_goal_involvements", "expected_goals_conceded"]
    feats = [f for f in feats if f in h.columns]
    grp = h.groupby("player_id")
    for f in feats:
        h[f"{f}_lag1"] = grp[f].shift(1)
        h[f"{f}_roll3"] = grp[f].shift(1).rolling(3, min_periods=1).mean().reset_index(level=0, drop=True)
        h[f"{f}_roll5"] = grp[f].shift(1).rolling(5, min_periods=1).mean().reset_index(level=0, drop=True)

    # Join player static info
    static_cols = ["player_id", "team", "element_type", "position",
                   "strength_attack_home", "strength_attack_away",
                   "strength_defence_home", "strength_defence_away",
                   "strength_overall_home", "strength_overall_away"]
    static_cols = [c for c in static_cols if c in players.columns]
    h = h.merge(players[static_cols], on="player_id", how="left")

    # Difficulty proxy from opponent team strength
    teams_idx = players[["team", "strength"]].drop_duplicates().rename(
        columns={"team": "opponent_team", "strength": "opp_strength"}
    )
    h = h.merge(teams_idx, on="opponent_team", how="left")

    h["is_home"] = h["was_home"].astype("Int64")
    h["target_points"] = h["total_points"]

    # Drop first GW per player (no lags)
    h = h.dropna(subset=[f"{feats[0]}_lag1"]) if feats else h
    return h
