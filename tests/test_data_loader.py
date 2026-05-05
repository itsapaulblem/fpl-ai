"""Tests for src.data_loader feature engineering — no network needed.

The critical thing we test: NO DATA LEAKAGE. Every lag/rolling feature
must be derived from gameweeks strictly *before* the row's `round`.
"""
import numpy as np
import pandas as pd

from src.data_loader import build_training_set


def _toy_history(n_players: int = 3, n_gws: int = 8) -> pd.DataFrame:
    """Build a tiny per-(player, GW) history table with deterministic stats."""
    rows = []
    rng = np.random.default_rng(42)
    for pid in range(1, n_players + 1):
        for gw in range(1, n_gws + 1):
            rows.append({
                "player_id": pid,
                "round": gw,
                "opponent_team": ((pid + gw) % 4) + 1,
                "was_home": gw % 2,
                "minutes": 90,
                "total_points": int(rng.integers(0, 12)),
                "bps": int(rng.integers(0, 40)),
                "ict_index": float(rng.uniform(0, 20)),
                "expected_goal_involvements": float(rng.uniform(0, 1)),
                "expected_goals_conceded": float(rng.uniform(0, 2)),
                "goals_scored": 0,
                "assists": 0,
                "clean_sheets": 0,
                "value": 50,
            })
    return pd.DataFrame(rows)


def _toy_players() -> pd.DataFrame:
    return pd.DataFrame([
        {"player_id": 1, "team": 1, "element_type": 3, "position": "MID", "strength": 4,
         "strength_attack_home": 4, "strength_attack_away": 3,
         "strength_defence_home": 4, "strength_defence_away": 3,
         "strength_overall_home": 4, "strength_overall_away": 3},
        {"player_id": 2, "team": 2, "element_type": 4, "position": "FWD", "strength": 3,
         "strength_attack_home": 3, "strength_attack_away": 3,
         "strength_defence_home": 3, "strength_defence_away": 3,
         "strength_overall_home": 3, "strength_overall_away": 3},
        {"player_id": 3, "team": 3, "element_type": 2, "position": "DEF", "strength": 5,
         "strength_attack_home": 5, "strength_attack_away": 4,
         "strength_defence_home": 5, "strength_defence_away": 4,
         "strength_overall_home": 5, "strength_overall_away": 4},
    ])


def test_build_training_set_creates_lag_and_roll_features():
    train = build_training_set(_toy_history(), _toy_players())
    expected_cols = {
        "minutes_lag1", "minutes_roll3", "minutes_roll5",
        "total_points_lag1", "total_points_roll3", "total_points_roll5",
        "bps_lag1", "ict_index_lag1",
        "is_home", "opp_strength", "target_points",
    }
    assert expected_cols.issubset(set(train.columns))


def test_no_data_leakage_lag1_is_strictly_previous_gw():
    """For every row, total_points_lag1 must equal the player's points
    from the *previous* gameweek — never the current one."""
    history = _toy_history()
    train = build_training_set(history, _toy_players())

    for _, row in train.iterrows():
        prev = history[
            (history["player_id"] == row["player_id"])
            & (history["round"] == row["round"] - 1)
        ]
        assert len(prev) == 1
        assert row["total_points_lag1"] == prev.iloc[0]["total_points"]


def test_first_gw_per_player_is_dropped():
    """No row should have a NaN lag1 — round=1 has no prior GW."""
    train = build_training_set(_toy_history(), _toy_players())
    assert train["total_points_lag1"].notna().all()
    # Row with round=1 is dropped
    assert (train["round"] >= 2).all()


def test_target_column_present_and_matches_total_points():
    train = build_training_set(_toy_history(), _toy_players())
    assert (train["target_points"] == train["total_points"]).all()


def test_empty_history_returns_empty_frame():
    out = build_training_set(pd.DataFrame(), _toy_players())
    assert out.empty
