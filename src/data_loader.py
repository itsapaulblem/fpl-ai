"""Phase 4 — Data loading & feature engineering.

Three responsibilities:

1. **Fetch & cache** raw data from the FPL API (`fetch_*` functions).
2. **Tidy** the raw JSON into clean DataFrames (`players_frame`, etc.).
3. **Engineer features** — turn per-GW history into a model-ready table where
   every feature uses **only past information** (`build_training_set`).

The cardinal rule: NO data leakage. Every feature for gameweek `t` is
computed from gameweeks `< t`. We enforce this with `.shift(1)` before any
rolling aggregation.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from tqdm import tqdm

from .fpl_api import FPLClient

# ---------------------------------------------------------------------- #
# Paths
# ---------------------------------------------------------------------- #
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"


def _ensure_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------- #
# 1. Fetching
# ---------------------------------------------------------------------- #
def players_frame(bootstrap: dict) -> pd.DataFrame:
    """Tidy player-level table joined with team & position metadata.

    Returns one row per player with both raw FPL stats and human-readable
    team / position names.
    """
    teams = pd.DataFrame(bootstrap["teams"])[[
        "id", "code", "name", "short_name", "strength",
        "strength_overall_home", "strength_overall_away",
        "strength_attack_home", "strength_attack_away",
        "strength_defence_home", "strength_defence_away",
    ]].rename(columns={"id": "team", "name": "team_name", "code": "team_code"})

    positions = pd.DataFrame(bootstrap["element_types"])[[
        "id", "singular_name_short",
    ]].rename(columns={"id": "element_type", "singular_name_short": "position"})

    keep = [
        "id", "web_name", "first_name", "second_name",
        "team", "element_type", "now_cost",
        "selected_by_percent", "form", "points_per_game",
        "minutes", "total_points", "goals_scored", "assists",
        "clean_sheets", "goals_conceded", "saves", "bonus", "bps",
        "influence", "creativity", "threat", "ict_index",
        "expected_goals", "expected_assists",
        "expected_goal_involvements", "expected_goals_conceded",
        "status", "chance_of_playing_next_round",
    ]
    raw = pd.DataFrame(bootstrap["elements"])
    keep = [c for c in keep if c in raw.columns]
    players = raw[keep].rename(columns={"id": "player_id"})
    players["price"] = players["now_cost"] / 10.0

    players = players.merge(teams, on="team", how="left")
    players = players.merge(positions, on="element_type", how="left")

    # Numeric coercion (FPL serves several stats as strings)
    numeric = [
        "form", "points_per_game", "selected_by_percent",
        "influence", "creativity", "threat", "ict_index",
        "expected_goals", "expected_assists",
        "expected_goal_involvements", "expected_goals_conceded",
    ]
    for col in numeric:
        if col in players.columns:
            players[col] = pd.to_numeric(players[col], errors="coerce")

    return players


def fetch_player_histories(
    bootstrap: dict,
    client: FPLClient | None = None,
    limit: int | None = None,
    show_progress: bool = True,
) -> pd.DataFrame:
    """Fetch every player's per-GW history. Slow — ~600 API calls.

    Each row = (player_id, gameweek). Cache the result with `save_parquet()`.
    """
    client = client or FPLClient()
    elements = bootstrap["elements"]
    if limit is not None:
        elements = elements[:limit]

    iterator = tqdm(elements, desc="player histories") if show_progress else elements
    rows: list[dict] = []
    for el in iterator:
        pid = el["id"]
        try:
            summary = client.player_summary(pid)
        except Exception:  # noqa: BLE001 - tolerate occasional API hiccup
            continue
        for h in summary.get("history", []):
            h["player_id"] = pid
            rows.append(h)
    return pd.DataFrame(rows)


def fetch_fixtures(client: FPLClient | None = None) -> pd.DataFrame:
    client = client or FPLClient()
    return pd.DataFrame(client.fixtures())


# ---------------------------------------------------------------------- #
# 2. Caching helpers
# ---------------------------------------------------------------------- #
def save_parquet(df: pd.DataFrame, path: Path) -> Path:
    """Save to parquet; fall back to CSV if pyarrow isn't installed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(path, index=False)
        return path
    except Exception:
        csv_path = path.with_suffix(".csv")
        df.to_csv(csv_path, index=False)
        return csv_path


def load_parquet(path: Path) -> pd.DataFrame | None:
    if path.exists():
        return pd.read_parquet(path)
    csv_path = path.with_suffix(".csv")
    if csv_path.exists():
        return pd.read_csv(csv_path)
    return None


# ---------------------------------------------------------------------- #
# 3. Upcoming fixtures (used at inference time)
# ---------------------------------------------------------------------- #
def upcoming_fixtures(
    fixtures: pd.DataFrame, players: pd.DataFrame, next_gw: int, horizon: int = 1
) -> pd.DataFrame:
    """For each player, attach the next `horizon` fixture(s) with difficulty."""
    fx = fixtures[(fixtures["event"] >= next_gw) & (fixtures["event"] < next_gw + horizon)]

    home = fx.rename(columns={
        "team_h": "team", "team_a": "opponent",
        "team_h_difficulty": "difficulty",
        "team_a_difficulty": "opp_difficulty",
    })[["event", "team", "opponent", "difficulty", "opp_difficulty"]].copy()
    home["is_home"] = 1

    away = fx.rename(columns={
        "team_a": "team", "team_h": "opponent",
        "team_a_difficulty": "difficulty",
        "team_h_difficulty": "opp_difficulty",
    })[["event", "team", "opponent", "difficulty", "opp_difficulty"]].copy()
    away["is_home"] = 0

    team_fixtures = pd.concat([home, away], ignore_index=True)
    return players.merge(team_fixtures, on="team", how="left")


# ---------------------------------------------------------------------- #
# 4. Feature engineering — the heart of Phase 4
# ---------------------------------------------------------------------- #
ROLLING_WINDOWS = (3, 5)
LAG_FEATURES = [
    "minutes",
    "total_points",
    "bps",
    "ict_index",
    "expected_goal_involvements",
    "expected_goals_conceded",
]


def _add_lag_features(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    """For each `LAG_FEATURES` column, add lag-1 + rolling means of windows.

    All lags use `.shift(1)` first → guarantees no data leakage from the
    current row into its own features.
    """
    feats = [f for f in LAG_FEATURES if f in df.columns]
    grp = df.groupby(group_cols, sort=False)
    for f in feats:
        shifted = grp[f].shift(1)
        df[f"{f}_lag1"] = shifted
        for window in ROLLING_WINDOWS:
            df[f"{f}_roll{window}"] = (
                shifted.groupby([df[c] for c in group_cols])
                .rolling(window, min_periods=1)
                .mean()
                .reset_index(level=list(range(len(group_cols))), drop=True)
            )
    return df


def build_training_set(
    history: pd.DataFrame,
    players: pd.DataFrame,
) -> pd.DataFrame:
    """Turn per-GW player history into a supervised learning table.

    Features = info known *before* kickoff.
    Label    = `total_points` scored in that gameweek.
    """
    if history.empty:
        return history.copy()

    df = history.copy()

    # Coerce numerics — the FPL API often returns these as strings.
    numeric_cols = LAG_FEATURES + [
        "value", "was_home", "round", "opponent_team",
        "goals_scored", "assists", "clean_sheets",
    ]
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.sort_values(["player_id", "round"]).reset_index(drop=True)
    df = _add_lag_features(df, group_cols=["player_id"])

    # Join player metadata + opponent strength
    static_cols = [
        "player_id", "team", "element_type", "position",
        "strength_attack_home", "strength_attack_away",
        "strength_defence_home", "strength_defence_away",
        "strength_overall_home", "strength_overall_away",
    ]
    static_cols = [c for c in static_cols if c in players.columns]
    df = df.merge(players[static_cols], on="player_id", how="left")

    opp_strength = (
        players[["team", "strength"]]
        .drop_duplicates()
        .rename(columns={"team": "opponent_team", "strength": "opp_strength"})
    )
    df = df.merge(opp_strength, on="opponent_team", how="left")

    df["is_home"] = df["was_home"].astype("Int64") if "was_home" in df.columns else 0
    df["target_points"] = df["total_points"]

    # Drop the first row per player (no lag1 feature) so we never train on NaN.
    first_lag = f"{LAG_FEATURES[0]}_lag1"
    df = df.dropna(subset=[first_lag]).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------- #
# 5. Convenience: do everything end-to-end with caching
# ---------------------------------------------------------------------- #
def load_or_fetch(
    client: FPLClient | None = None,
    use_cache: bool = True,
    refresh: bool = False,
) -> dict[str, pd.DataFrame]:
    """Return a dict with players / history / fixtures DataFrames.

    Caches to `data/processed/`. Pass `refresh=True` to force re-download.
    """
    _ensure_dirs()
    client = client or FPLClient()

    paths = {
        "players": PROCESSED_DIR / "players.parquet",
        "history": PROCESSED_DIR / "history.parquet",
        "fixtures": PROCESSED_DIR / "fixtures.parquet",
    }

    if use_cache and not refresh:
        cached = {k: load_parquet(p) for k, p in paths.items()}
        if all(v is not None for v in cached.values()):
            return cached  # type: ignore[return-value]

    boot = client.bootstrap()
    players = players_frame(boot)
    fixtures = fetch_fixtures(client)
    history = fetch_player_histories(boot, client)

    save_parquet(players, paths["players"])
    save_parquet(history, paths["history"])
    save_parquet(fixtures, paths["fixtures"])
    return {"players": players, "history": history, "fixtures": fixtures}
